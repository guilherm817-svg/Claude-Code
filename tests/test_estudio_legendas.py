"""Legendas automáticas do Estúdio: o algoritmo das telas (com os mesmos casos do teste do JavaScript), a fonte, o
.ass, os dados do projeto, a transcrição pela API com um Whisper falso e a exportação com a legenda queimada."""

import json
import re
import shutil
import struct
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from estudio import exportar as exp
from estudio import legendas, transcricao
from estudio.midia import ffmpeg
from estudio.projetos import Ajustes, ErroImportacao, EstiloLegenda, Estudio, Item, Palavra
from estudio.servidor import criar_app
from whisper_falso import WhisperFalso

RAIZ = Path(__file__).resolve().parent.parent
CASOS = json.loads((Path(__file__).parent / "casos_legendas.json").read_text(encoding="utf-8"))
CABECALHO = {"X-Estudio": "1"}
FONTES = RAIZ / "estudio" / "static" / "fontes"


def _perto(obtido, esperado, caminho=""):
    """Igualdade de estruturas JSON, com números comparados até 1e-9."""
    if isinstance(esperado, float | int) and not isinstance(esperado, bool):
        assert obtido == pytest.approx(esperado, abs=1e-9), caminho
    elif isinstance(esperado, list):
        assert isinstance(obtido, list | tuple) and len(obtido) == len(esperado), caminho
        for i, (a, b) in enumerate(zip(obtido, esperado)):
            _perto(a, b, f"{caminho}[{i}]")
    elif isinstance(esperado, dict):
        assert set(obtido) == set(esperado), caminho
        for chave in esperado:
            _perto(obtido[chave], esperado[chave], f"{caminho}.{chave}")
    else:
        assert obtido == esperado, caminho


# Algoritmo: os mesmos casos do tests/legendas_js.test.cjs


@pytest.mark.parametrize("caso", CASOS["casos"], ids=[c["nome"] for c in CASOS["casos"]])
def test_telas_e_diagramas(caso):
    telas = legendas.montar_telas(caso["palavras"], caso["entrada"], caso["saida"], caso["estilo"])
    _perto(telas, caso["telas"], "telas")
    diagramas = [legendas.diagramar(t, caso["estilo"], caso["largura"], caso["altura"]) for t in telas]
    _perto(diagramas, caso["diagramas"], "diagramas")


@pytest.mark.parametrize("caso", CASOS["realinhar"], ids=[c["nome"] for c in CASOS["realinhar"]])
def test_realinhar_texto_corrigido(caso):
    _perto(legendas.realinhar(caso["palavras"], caso["texto"], caso["intervalo"]), caso["esperado"])


def test_animacao_de_entrada():
    for t, escala in CASOS["pop"]:
        assert legendas.escala_pop(t) == pytest.approx(escala, abs=1e-9)


def test_regras_do_algoritmo_nos_casos():
    """Confere à mão o que os casos compartilhados prometem, para eles não virarem só uma foto do código."""
    por_nome = {c["nome"]: c for c in CASOS["casos"]}
    telas = por_nome["destaque: até 3 palavras, quebra no ponto final e emenda as telas"]["telas"]
    assert [[p["texto"] for p in t["palavras"]] for t in telas] == [["ISSO", "MUDA", "TUDO."], ["AGORA", "PRESTA", "ATENÇÃO"]]
    assert (telas[0]["inicio"], telas[0]["fim"], telas[1]["inicio"], telas[1]["fim"]) == (0.1, 1.3, 1.3, 3.1)
    assert telas[0]["destaques"] == [[0.1, 0.42], [0.42, 0.72], [0.72, 1.3]]
    telas = por_nome["pausa longa começa outra tela; vão pequeno emenda, vão grande não"]["telas"]
    assert [(t["inicio"], t["fim"]) for t in telas] == [(0.0, 1.05), (1.05, 2.1), (3.0, 4.2)]
    telas = por_nome["só as palavras dentro do corte, no tempo do trecho"]["telas"]
    assert [(p["texto"], p["inicio"], p["fim"]) for p in telas[0]["palavras"]] == [
        ("FORA", 0.0, 0.05), ("DENTRO", 0.1, 0.4), ("TAMBÉM", 0.5, 0.9)]
    caso = por_nome["quadrado: o bloco sobe para não cair na faixa de baixo"]
    diagrama = caso["diagramas"][0]
    assert diagrama["linhas"][0]["base"] + legendas.ABAIXO * diagrama["em"] + diagrama["contorno"] <= 0.75 * 1080 + 0.01
    longa = por_nome["uma palavra por tela, amarela, e palavra comprida reduzida para caber"]["diagramas"][1]
    assert longa["escala"] < 1 and longa["linhas"][0]["largura"] + 2 * longa["contorno"] <= 1080 * 0.84
    assert por_nome["clássica sem maiúsculas: até 7 palavras em 2 linhas"]["telas"][0]["palavras"][1]["texto"] == "gente"


def test_javascript_da_os_mesmos_resultados():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node não instalado")
    r = subprocess.run([node, str(RAIZ / "tests" / "legendas_js.test.cjs")], capture_output=True, text=True,
                       cwd=RAIZ, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


def test_tabelas_do_javascript_iguais_as_do_python():
    codigo = (RAIZ / "estudio" / "static" / "legendas.js").read_text(encoding="utf-8")
    for fonte in ("black", "extrabold"):
        lista = re.search(rf"\b{fonte}: \[([\d,\s]+)\]", codigo).group(1)
        assert [int(v) for v in lista.split(",") if v.strip()] == legendas._LARGURAS[fonte]
    for nome, valor in (("FATOR_ASS", legendas.FATOR_ASS), ("DESLOCAMENTO_ASS", legendas.DESLOCAMENTO_ASS)):
        assert float(re.search(rf"const {nome} = ([\d.]+);", codigo).group(1)) == valor


# Fonte


def _ler_fonte(caminho: Path) -> dict:
    """Lê do .ttf o que as legendas usam: nomes, métricas verticais e a largura de cada caractere."""
    dados = caminho.read_bytes()
    tabelas = {}
    for i in range(struct.unpack(">H", dados[4:6])[0]):
        etiqueta, _, inicio, _ = struct.unpack(">4sIII", dados[12 + 16 * i:28 + 16 * i])
        tabelas[etiqueta.decode()] = inicio
    u16 = lambda pos: struct.unpack(">H", dados[pos:pos + 2])[0]  # noqa: E731
    nomes, base = {}, tabelas["name"]
    armazenamento = base + u16(base + 4)
    for i in range(u16(base + 2)):
        plataforma, codificacao, _, nome_id, tamanho, deslocamento = struct.unpack(
            ">6H", dados[base + 6 + 12 * i:base + 18 + 12 * i])
        if plataforma == 3 and codificacao == 1:
            texto = dados[armazenamento + deslocamento:armazenamento + deslocamento + tamanho].decode("utf-16-be")
            nomes.setdefault(nome_id, texto)
    os2 = tabelas["OS/2"]
    metricas = {"upm": u16(tabelas["head"] + 18), "peso": u16(os2 + 4), "subida": u16(os2 + 74),
                "descida": u16(os2 + 76)}
    # cmap formato 4 (Unicode BMP) e hmtx: a largura de avanço de cada caractere.
    cmap = tabelas["cmap"]
    sub = next(cmap + struct.unpack(">I", dados[cmap + 8 + 8 * i:cmap + 12 + 8 * i])[0]
               for i in range(u16(cmap + 2)) if (u16(cmap + 4 + 8 * i), u16(cmap + 6 + 8 * i)) == (3, 1))
    segmentos = u16(sub + 6) // 2
    fins = [u16(sub + 14 + 2 * i) for i in range(segmentos)]
    comecos = [u16(sub + 16 + 2 * segmentos + 2 * i) for i in range(segmentos)]
    deltas = [struct.unpack(">h", dados[sub + 16 + 4 * segmentos + 2 * i:sub + 18 + 4 * segmentos + 2 * i])[0]
              for i in range(segmentos)]
    pos_offsets = sub + 16 + 6 * segmentos
    numero_metricas = u16(tabelas["hhea"] + 34)

    def largura(caractere: str) -> int | None:
        c = ord(caractere)
        for i in range(segmentos):
            if comecos[i] <= c <= fins[i]:
                deslocamento = u16(pos_offsets + 2 * i)
                if deslocamento == 0:
                    glifo = (c + deltas[i]) & 0xFFFF
                else:
                    glifo = u16(pos_offsets + 2 * i + deslocamento + 2 * (c - comecos[i]))
                    glifo = (glifo + deltas[i]) & 0xFFFF if glifo else 0
                return u16(tabelas["hmtx"] + 4 * min(glifo, numero_metricas - 1))
        return None

    return {"nomes": nomes, **metricas, "largura": largura}


@pytest.mark.parametrize("chave", list(legendas.FONTES))
def test_fonte_bate_com_as_constantes(chave):
    fonte = legendas.FONTES[chave]
    info = _ler_fonte(FONTES / fonte["arquivo"])
    # O Fontname do .ass precisa ser o nome de família de dentro do arquivo, senão o libass usa outra fonte.
    assert info["nomes"][1] == fonte["familia"] and info["peso"] == fonte["peso"]
    assert legendas.FATOR_ASS == pytest.approx((info["subida"] + info["descida"]) / info["upm"], abs=1e-9)
    assert legendas.DESLOCAMENTO_ASS == pytest.approx(
        (info["subida"] - (info["subida"] + info["descida"]) / 2) / info["upm"], abs=1e-9)
    assert {c: info["largura"](c) for c in legendas.CARACTERES} == legendas.LARGURAS[chave]
    assert (FONTES / "OFL.txt").read_text(encoding="utf-8").startswith("Copyright 2020 The Poppins Project Authors")


def _renderizar_ass(pasta: Path, texto: str, largura=1080, altura=1920) -> tuple[np.ndarray, str]:
    """Queima o .ass num quadro preto, como a exportação faz (pasta de trabalho com legendas/ e fontes/)."""
    ass = exp.preparar_legenda(pasta, texto)
    r = subprocess.run([ffmpeg(), "-hide_banner", "-v", "info", "-f", "lavfi", "-i",
                        f"color=c=black:s={largura}x{altura}:r=30:d=2", "-vf",
                        f"ass=filename={ass}:fontsdir=fontes,format=rgb24", "-ss", "0.5", "-frames:v", "1",
                        "-f", "rawvideo", "-"], capture_output=True, cwd=pasta)
    assert r.returncode == 0, r.stderr.decode()[-2000:]
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(altura, largura, 3), r.stderr.decode("utf-8", "replace")


@pytest.mark.parametrize("preset,arquivo", [("destaque", "Poppins-Black"), ("caixa", "Poppins-ExtraBold")])
def test_libass_usa_a_poppins_e_nao_uma_fonte_reserva(tmp_path, preset, arquivo):
    estilo = {**legendas.ESTILO_PADRAO, "preset": preset}
    palavras = [{"inicio": 0.1, "fim": 0.6, "texto": "Olá"}, {"inicio": 0.6, "fim": 1.0, "texto": "pessoal"}]
    texto = legendas.gerar_ass(legendas.legendas_do_trecho(palavras, 0, 2, estilo, 1080, 1920), estilo, 1080, 1920)
    quadro, log = _renderizar_ass(tmp_path, texto)
    familia = legendas.FONTES[legendas.PRESETS[preset]["fonte"]]["familia"]
    selecoes = re.findall(r"fontselect: \((.+?), \d+, \d+\) -> (.+)", log)
    assert selecoes and all(pedida == familia and arquivo in usada for pedida, usada in selecoes), selecoes
    assert (quadro.min(axis=2) > 200).sum() > 2000  # o texto branco apareceu


# O .ass


def _dialogos(texto: str) -> list[tuple[int, str, str, str, str]]:
    linhas = [l for l in texto.splitlines() if l.startswith("Dialogue:")]
    return [tuple(l[len("Dialogue: "):].split(",", 9)[i] for i in (0, 1, 2, 3, 9)) for l in linhas]


def test_ass_cabecalho_estilo_e_tempos_sem_buraco():
    caso = CASOS["casos"][0]
    estilo = caso["estilo"]
    telas = legendas.legendas_do_trecho(caso["palavras"], caso["entrada"], caso["saida"], estilo, 1080, 1920)
    texto = legendas.gerar_ass(telas, estilo, 1080, 1920)
    for linha in ("PlayResX: 1080", "PlayResY: 1920", "ScaledBorderAndShadow: yes", "WrapStyle: 2"):
        assert linha in texto.splitlines()
    assert "Style: Legenda,Poppins Black,100,&H00FFFFFF," in texto
    dialogos = _dialogos(texto)
    assert len(dialogos) == 4  # duas telas com duas linhas cada
    assert [(d[1], d[2]) for d in dialogos] == [("0:00:00.10", "0:00:01.30")] * 2 + [("0:00:01.30", "0:00:03.10")] * 2
    primeira = dialogos[0][4]
    diagrama = telas[0][1]
    assert primeira.startswith(f"{{\\pos(540,{legendas._num(diagrama['linhas'][0]['y'])})\\fs{legendas._num(diagrama['fs'])}"
                               f"\\bord{legendas._num(diagrama['contorno'])}\\fscx75\\fscy75\\t(0,90,\\fscx108\\fscy108)"
                               "\\t(90,150,\\fscx100\\fscy100)}")
    # "MUDA" fica amarela de 0,42 a 0,72 s, ou seja, de 320 a 620 ms depois do começo da tela (0,10 s).
    assert "{\\1c&HFFFFFF&\\t(320,320,\\1c&H00DDFF&)\\t(620,620,\\1c&HFFFFFF&)}MUDA" in primeira
    assert primeira.endswith("}MUDA")
    assert dialogos[0][4].count("\\1c") == 5  # cada palavra começa com a cor dela


def test_ass_escapa_texto_e_desenha_caixas():
    assert legendas.escapar("a{b}c\\N") == "a\\{b\\}c\\⁠N"
    assert legendas.cor_ass("#FFDD00") == "&H00DDFF&"
    assert legendas.cor_ass("#000000", 0.62, com_alfa=True) == "&H61000000"
    estilo = {**legendas.ESTILO_PADRAO, "preset": "caixa", "animacao": False}
    palavras = [{"inicio": 0, "fim": 0.5, "texto": "{oi}"}, {"inicio": 0.5, "fim": 1, "texto": "a\\nb"}]
    texto = legendas.gerar_ass(legendas.legendas_do_trecho(palavras, 0, 2, estilo, 1080, 1920), estilo, 1080, 1920)
    dialogos = _dialogos(texto)
    caixas = [d for d in dialogos if d[3] == "Caixa"]
    textos = [d for d in dialogos if d[3] == "Legenda"]
    assert len(caixas) == len(textos) == 1 and caixas[0][0] == "0" and textos[0][0] == "1"
    assert re.match(r"\{\\an5\\pos\(540,[\d.]+\)\\p1\}m [\d.]+ 0 l .* b .*\{\\p0\}$", caixas[0][4])
    assert textos[0][4].endswith("}\\{OI\\} A\\⁠NB")
    assert "\\fscx" not in texto  # sem animação


def test_ass_le_a_legenda_que_o_libass_queima(tmp_path):
    """A legenda queimada cai onde o diagrama diz: no meio das maiúsculas da linha, centrada."""
    estilo = {**legendas.ESTILO_PADRAO, "animacao": False}
    palavras = [{"inicio": 0.0, "fim": 1.5, "texto": "HHHH"}]
    telas = legendas.legendas_do_trecho(palavras, 0, 2, estilo, 1080, 1920)
    quadro, _ = _renderizar_ass(tmp_path, legendas.gerar_ass(telas, estilo, 1080, 1920))
    amarelo = (quadro[:, :, 0] > 200) & (quadro[:, :, 1] > 150) & (quadro[:, :, 2] < 100)
    ys, xs = np.nonzero(amarelo)
    linha = telas[0][1]["linhas"][0]
    em = telas[0][1]["em"]
    assert ys.max() == pytest.approx(linha["base"], abs=2)  # pé do H na linha de base
    assert ys.min() == pytest.approx(linha["base"] - 0.708 * em, abs=2)  # altura do H na Poppins Black: 708
    assert (xs.min() + xs.max()) / 2 == pytest.approx(540, abs=2)


# Dados do projeto


def _gerar(destino, *args):
    subprocess.run([ffmpeg(), "-v", "error", "-y", *args, str(destino)], check=True)
    return destino


@pytest.fixture(scope="module")
def clipes(tmp_path_factory):
    """Clipes lisos de 2 s (fundo azul-escuro, para achar a legenda pela cor): com som no meio e sem som."""
    pasta = tmp_path_factory.mktemp("clipes-legendas")
    falado = _gerar(pasta / "falado.mp4", "-f", "lavfi", "-i", "color=c=0x22324a:s=360x640:r=30:d=2",
                    "-f", "lavfi", "-i", "sine=f=300:d=1,adelay=500|500,apad=whole_dur=2,volume=0.3",
                    "-f", "lavfi", "-i", "anoisesrc=d=2:a=0.002",
                    "-filter_complex", "[1:a][2:a]amix=inputs=2:normalize=0[a]", "-map", "0:v", "-map", "[a]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-t", "2")
    mudo = _gerar(pasta / "mudo.mp4", "-f", "lavfi", "-i", "color=c=0x22324a:s=360x640:r=30:d=2",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p")
    return {"falado": falado, "mudo": mudo}


@pytest.fixture
def estudio(tmp_path):
    return Estudio(tmp_path / "meus-reels")


def _importar(estudio, projeto_id, caminho):
    with open(caminho, "rb") as arquivo:
        return estudio.importar(projeto_id, arquivo, caminho.name)


def _palavras(*trios):
    return [Palavra(inicio=a, fim=b, texto=t) for a, b, t in trios]


def test_projeto_antigo_abre_com_legendas_desligadas(estudio):
    projeto = estudio.criar("Antigo")
    arquivo = estudio.pasta_projeto(projeto.id) / "projeto.json"
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    for chave in ("legendas_ativas", "idioma_legenda", "estilo_legenda", "legendas"):
        dados.pop(chave)
    arquivo.write_text(json.dumps(dados), encoding="utf-8")
    aberto = estudio.abrir(projeto.id)
    assert (aberto.legendas_ativas, aberto.idioma_legenda, aberto.legendas) == (False, "auto", {})
    assert aberto.estilo_legenda == EstiloLegenda(preset="destaque", tamanho="M", posicao="baixo", maiusculas=True,
                                                  animacao=True)


def test_salvar_legendas_substitui_mantem_e_confere(estudio, clipes):
    projeto = estudio.criar()
    _, a, item_a = _importar(estudio, projeto.id, clipes["falado"])
    _, b, item_b = _importar(estudio, projeto.id, clipes["falado"])
    base = dict(nome="x", linha=[item_a, item_b])
    salvo = estudio.aplicar(projeto.id, Ajustes(**base, legendas_ativas=True, idioma_legenda="en",
                                                estilo_legenda=EstiloLegenda(preset="caixa", tamanho="G"),
                                                legendas={a.id: _palavras((0.5, 0.9, " Olá "), (0.9, 2.3, "mundo"))}))
    assert salvo.legendas_ativas and salvo.idioma_legenda == "en" and salvo.estilo_legenda.preset == "caixa"
    # O excesso pequeno no fim é só limitado à duração; o texto perde os espaços das pontas.
    assert [(p.inicio, p.fim, p.texto) for p in salvo.legendas[a.id]] == [(0.5, 0.9, "Olá"), (0.9, 2.0, "mundo")]

    # A transcrição de b chega pelo servidor; um salvamento da tela sem b não a apaga.
    estudio.gravar_legenda(projeto.id, b.id, _palavras((0.6, 1.0, "oi")))
    salvo = estudio.aplicar(projeto.id, Ajustes(**base, legendas={a.id: _palavras((0.5, 1.0, "trocado"))}))
    assert [p.texto for p in salvo.legendas[a.id]] == ["trocado"] and [p.texto for p in salvo.legendas[b.id]] == ["oi"]
    salvo = estudio.aplicar(projeto.id, Ajustes(**base, legendas={b.id: []}))
    assert salvo.legendas[b.id] == [] and len(salvo.legendas[a.id]) == 1

    erros = [
        ({"c" * 12: []}, "não está no projeto"),
        ({a.id: _palavras((1.0, 1.2, "b"), (0.5, 0.8, "a"))}, "fora de ordem"),
        ({a.id: _palavras((1.0, 1.0, "zero"))}, "termina antes de começar"),
        ({a.id: _palavras((1.0, 4.0, "longe"))}, "fora do tempo"),
        ({a.id: _palavras(*[(0.0, 0.1, "x")] * 5001)}, "palavras demais"),
    ]
    for legendas_ruins, mensagem in erros:
        with pytest.raises(ErroImportacao, match=mensagem):
            estudio.aplicar(projeto.id, Ajustes(**base, legendas=legendas_ruins))
    with pytest.raises(ValueError, match="vazia"):
        Palavra(inicio=0, fim=1, texto="   ")
    with pytest.raises(ValueError):
        Palavra(inicio=0, fim=1, texto="x" * 81)

    estudio.remover_midia(projeto.id, a.id)
    assert list(estudio.abrir(projeto.id).legendas) == [b.id]


# Transcrição pela API, com o Whisper falso


@pytest.fixture
def whisper(monkeypatch):
    falso = WhisperFalso("Isso muda tudo agora")
    monkeypatch.setattr(transcricao, "_carregar_modelo", lambda modelo, dispositivo: falso)
    return falso


@pytest.fixture
def cliente(estudio):
    return TestClient(criar_app(estudio), base_url="http://127.0.0.1")


def _esperar(cliente, trabalho):
    for _ in range(200):
        if trabalho["estado"] not in ("na_fila", "transcrevendo"):
            return trabalho
        time.sleep(0.05)
        trabalho = cliente.get(f"/api/legendas/{trabalho['id']}").json()
    raise AssertionError(trabalho)


def _subir(cliente, pid, caminho):
    with open(caminho, "rb") as arquivo:
        r = cliente.post(f"/api/projetos/{pid}/midias", files={"arquivo": (caminho.name, arquivo)}, headers=CABECALHO)
    assert r.status_code == 200, r.text
    return r.json()["midia"]


def test_api_transcreve_em_segundo_plano(cliente, clipes, whisper):
    pid = cliente.post("/api/projetos", json={}, headers=CABECALHO).json()["id"]
    falado, mudo = _subir(cliente, pid, clipes["falado"]), _subir(cliente, pid, clipes["mudo"])
    assert cliente.post(f"/api/projetos/{pid}/legendas", json={}).status_code == 403  # sem o cabeçalho da tela

    trabalho = cliente.post(f"/api/projetos/{pid}/legendas", json={"midias": None}, headers=CABECALHO).json()
    trabalho = _esperar(cliente, trabalho)
    assert trabalho["estado"] == "pronta" and trabalho["progresso"] == 1.0 and trabalho["etapa"] == "Legendas prontas."
    assert sorted(trabalho["concluidas"]) == sorted([falado["id"], mudo["id"]]) and trabalho["pendentes"] == []
    palavras = trabalho["resultados"][falado["id"]]
    assert [p["texto"] for p in palavras] == ["Isso", "muda", "tudo", "agora"]
    assert 0.4 < palavras[0]["inicio"] < 0.6 and palavras[-1]["fim"] <= falado["duracao"]
    assert trabalho["resultados"][mudo["id"]] == []  # sem som: sem legenda e sem chamar o modelo
    assert len(whisper.pedidos) == 1
    assert whisper.pedidos[0]["word_timestamps"] is True and whisper.pedidos[0]["condition_on_previous_text"] is False
    assert whisper.pedidos[0]["idioma"] is None  # "auto": o Whisper detecta
    projeto = cliente.get(f"/api/projetos/{pid}").json()
    assert projeto["legendas"][falado["id"]] == palavras

    # Sem "refazer", quem já tem legenda não é transcrito de novo; com ele, usa o idioma salvo no projeto.
    trabalho = _esperar(cliente, cliente.post(f"/api/projetos/{pid}/legendas", json={}, headers=CABECALHO).json())
    assert trabalho["estado"] == "pronta" and trabalho["concluidas"] == [] and len(whisper.pedidos) == 1
    cliente.put(f"/api/projetos/{pid}", json={**{k: projeto[k] for k in ("nome", "linha")}, "idioma_legenda": "en"},
                headers=CABECALHO)
    trabalho = cliente.post(f"/api/projetos/{pid}/legendas", json={"midias": [falado["id"]], "refazer": True},
                            headers=CABECALHO).json()
    assert _esperar(cliente, trabalho)["concluidas"] == [falado["id"]] and whisper.pedidos[-1]["idioma"] == "en"
    assert cliente.post(f"/api/projetos/{pid}/legendas", json={"midias": ["d" * 12]},
                        headers=CABECALHO).status_code == 404
    assert cliente.get("/api/legendas/naoexiste").status_code == 404


def test_api_devolve_a_legenda_gravada_e_o_trabalho_em_andamento(cliente, clipes, monkeypatch):
    """Uma tela que recarrega no meio da transcrição volta a acompanhar o trabalho e recebe, dos clipes já prontos, a
    legenda como está gravada (com a correção feita depois), e não o texto que saiu do Whisper."""
    liberar = threading.Event()

    class Segura(WhisperFalso):
        def transcribe(self, audio, language=None, **opcoes):
            if self.pedidos:  # o segundo clipe espera
                liberar.wait(10)
            return super().transcribe(audio, language, **opcoes)

    falso = Segura("Isso muda tudo agora")
    monkeypatch.setattr(transcricao, "_carregar_modelo", lambda modelo, dispositivo: falso)
    pid = cliente.post("/api/projetos", json={}, headers=CABECALHO).json()["id"]
    primeiro, segundo = _subir(cliente, pid, clipes["falado"]), _subir(cliente, pid, clipes["falado"])
    assert cliente.get(f"/api/projetos/{pid}/legendas").json() is None
    trabalho = cliente.post(f"/api/projetos/{pid}/legendas", json={}, headers=CABECALHO).json()
    try:
        for _ in range(200):
            if trabalho["concluidas"]:
                break
            time.sleep(0.05)
            trabalho = cliente.get(f"/api/legendas/{trabalho['id']}").json()
        assert trabalho["concluidas"] == [primeiro["id"]] and trabalho["pendentes"] == [segundo["id"]]

        projeto = cliente.get(f"/api/projetos/{pid}").json()
        corrigidas = [{**p, "texto": "mudou"} if p["texto"] == "muda" else p for p in projeto["legendas"][primeiro["id"]]]
        r = cliente.put(f"/api/projetos/{pid}", json={**{k: projeto[k] for k in ("nome", "linha")},
                                                      "legendas": {primeiro["id"]: corrigidas}}, headers=CABECALHO)
        assert r.status_code == 200, r.text
        andando = cliente.get(f"/api/projetos/{pid}/legendas").json()
        assert andando["id"] == trabalho["id"] and andando["pendentes"] == [segundo["id"]]
        assert andando["resultados"] == {primeiro["id"]: corrigidas}
        assert cliente.get(f"/api/legendas/{trabalho['id']}").json()["resultados"] == {primeiro["id"]: corrigidas}
        # Pedir de novo (como a tela faz ao abrir o projeto) devolve o mesmo trabalho, também com a correção.
        de_novo = cliente.post(f"/api/projetos/{pid}/legendas", json={}, headers=CABECALHO).json()
        assert de_novo["id"] == trabalho["id"] and de_novo["resultados"] == {primeiro["id"]: corrigidas}
    finally:
        liberar.set()
    trabalho = _esperar(cliente, trabalho)
    assert trabalho["concluidas"] == [primeiro["id"], segundo["id"]]
    assert [p["texto"] for p in trabalho["resultados"][primeiro["id"]]] == ["Isso", "mudou", "tudo", "agora"]
    assert cliente.get(f"/api/projetos/{pid}/legendas").json() is None


def test_api_recusa_legenda_ruim_em_portugues(cliente, clipes):
    pid = cliente.post("/api/projetos", json={}, headers=CABECALHO).json()["id"]
    midia = _subir(cliente, pid, clipes["falado"])
    projeto = cliente.get(f"/api/projetos/{pid}").json()
    base = {k: projeto[k] for k in ("nome", "linha")}
    for palavra, mensagem in (({"inicio": 0, "fim": 1, "texto": " "}, "Uma palavra da legenda está vazia."),
                              ({"inicio": 0, "fim": 1, "texto": "x" * 81}, "Uma palavra da legenda passou de 80 letras.")):
        r = cliente.put(f"/api/projetos/{pid}", json={**base, "legendas": {midia["id"]: [palavra]}}, headers=CABECALHO)
        assert r.status_code == 422 and [d["msg"] for d in r.json()["detail"]] == [mensagem]
    r = cliente.put(f"/api/projetos/{pid}", json={**base, "legendas": {"e" * 12: []}}, headers=CABECALHO)
    assert r.status_code == 400 and "não está no projeto" in r.json()["detail"]


def test_api_explica_quando_o_modelo_nao_baixa(cliente, clipes, monkeypatch):
    def sem_internet(modelo, dispositivo):
        raise transcricao.ErroTranscricao(transcricao._sem_internet(modelo))
    monkeypatch.setattr(transcricao, "_carregar_modelo", sem_internet)
    pid = cliente.post("/api/projetos", json={}, headers=CABECALHO).json()["id"]
    _subir(cliente, pid, clipes["falado"])
    _subir(cliente, pid, clipes["falado"])
    trabalho = _esperar(cliente, cliente.post(f"/api/projetos/{pid}/legendas", json={}, headers=CABECALHO).json())
    assert trabalho["estado"] == "erro" and "internet" in trabalho["erro"] and "1,6 GB" in trabalho["erro"]
    assert trabalho["pendentes"] == [] and trabalho["concluidas"] == []


def test_erro_de_download_vira_mensagem_amigavel(monkeypatch):
    import faster_whisper
    import httpx

    def bloqueado(*args, **kwargs):
        raise httpx.ProxyError("403 Forbidden")
    monkeypatch.setattr(faster_whisper, "WhisperModel", bloqueado)
    transcricao._carregar_modelo.cache_clear()
    try:
        with pytest.raises(transcricao.ErroTranscricao, match="precisam de internet"):
            transcricao._carregar_modelo("large-v3-turbo", "cpu")
    finally:
        transcricao._carregar_modelo.cache_clear()


def test_palavras_do_whisper_ajustadas_ao_clipe():
    brutas = [{"inicio": -0.05, "fim": 0.3, "texto": " Oi "}, {"inicio": 0.3, "fim": 0.3, "texto": "tchau."},
              {"inicio": 0.4, "fim": 0.5, "texto": "  "}, {"inicio": 1.98, "fim": 2.4, "texto": "fim"}]
    ajustadas = transcricao.ajustar_palavras(brutas, 2.0)
    assert [(p.inicio, p.fim, p.texto) for p in ajustadas] == [(0.0, 0.3, "Oi"), (0.3, 0.35, "tchau."),
                                                                (1.98, 2.0, "fim")]


# Exportação


def _quadro(arquivo: Path, instante: float) -> np.ndarray:
    r = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{instante:.3f}", "-i", str(arquivo), "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(1920, 1080, 3)


def _cores(quadro: np.ndarray) -> tuple[int, int]:
    """Pixels amarelos e brancos na faixa de baixo da tela, onde a legenda "Abaixo do rosto" fica."""
    faixa = quadro[int(1920 * 0.55):int(1920 * 0.75)].astype(int)
    r, g, b = faixa[:, :, 0], faixa[:, :, 1], faixa[:, :, 2]
    return int(((r > 190) & (g > 150) & (b < 110)).sum()), int(((r > 200) & (g > 200) & (b > 200)).sum())


def _projeto_legendado(estudio, clipes, ativas=True):
    projeto = estudio.criar("Legendado")
    _, a, item_a = _importar(estudio, projeto.id, clipes["falado"])
    _, b, item_b = _importar(estudio, projeto.id, clipes["falado"])
    linha = [Item(id=item_a.id, midia_id=a.id, entrada=0, saida=2), Item(id=item_b.id, midia_id=b.id, entrada=0, saida=2)]
    falas = {a.id: _palavras((0.2, 0.5, "Isso"), (0.5, 0.9, "muda"), (0.9, 1.3, "tudo")),
             b.id: _palavras((0.2, 0.6, "Olha"), (0.6, 1.0, "isso"))}
    estudio.aplicar(projeto.id, Ajustes(nome="Legendado", linha=linha, legendas_ativas=ativas, legendas=falas,
                                        igualar_volume=False))
    return projeto.id, a, b


def _exportar(estudio, pid):
    resultado = exp.Exportador(estudio).iniciar(pid, sincrono=True)
    assert resultado.estado == "pronta", resultado.erro
    return estudio.pasta_exportados(pid) / resultado.arquivo


def test_exportar_queima_a_legenda_no_instante_certo(estudio, clipes):
    pid, _, _ = _projeto_legendado(estudio, clipes)
    saida = _exportar(estudio, pid)
    amarelos, brancos = _cores(_quadro(saida, 0.7))  # "MUDA" (0,5 a 0,9 s) em amarelo, "ISSO" e "TUDO" em branco
    assert amarelos > 1500 and brancos > 3000
    assert _cores(_quadro(saida, 0.1)) == (0, 0)  # antes da primeira palavra, nada
    amarelos, brancos = _cores(_quadro(saida, 2.0 + 0.8))  # segundo clipe: "ISSO" amarela
    assert amarelos > 1000 and brancos > 1000
    cache = estudio.pasta_cache(pid)
    assert sorted(p.name for p in (cache / "fontes").iterdir()) == ["Poppins-Black.ttf", "Poppins-ExtraBold.ttf"]
    assert not list((cache / "legendas").glob("*.ass"))  # o .ass só existe enquanto o trecho é renderizado

    projeto = estudio.abrir(pid)
    estudio.aplicar(pid, Ajustes(**projeto.model_dump(include={"nome", "linha", "legendas"}), legendas_ativas=False))
    assert _cores(_quadro(_exportar(estudio, pid), 0.7)) == (0, 0)


def test_editar_o_texto_refaz_so_o_trecho_afetado(estudio, clipes):
    pid, a, b = _projeto_legendado(estudio, clipes)
    _exportar(estudio, pid)
    pasta = estudio.pasta_cache(pid) / "trechos"
    antes = {p.name: p.stat().st_mtime_ns for p in pasta.glob("*.mov")}
    assert len(antes) == 2

    projeto = estudio.abrir(pid)
    estudio.aplicar(pid, Ajustes(**projeto.model_dump(include={"nome", "linha", "legendas_ativas", "igualar_volume"}),
                                 legendas={b.id: _palavras((0.2, 0.6, "Olhe"), (0.6, 1.0, "isso"))}))
    _exportar(estudio, pid)
    depois = {p.name: p.stat().st_mtime_ns for p in pasta.glob("*.mov")}
    assert len(set(antes) & set(depois)) == 1  # o trecho do clipe a foi reaproveitado
    mantido = (set(antes) & set(depois)).pop()
    assert antes[mantido] == depois[mantido]


def test_sem_legenda_a_chave_do_trecho_nao_muda(estudio, clipes):
    """Quem já exportou antes das legendas não perde os trechos prontos: a chave sem legenda é a mesma de antes."""
    pid, a, _ = _projeto_legendado(estudio, clipes, ativas=False)
    _exportar(estudio, pid)
    projeto = estudio.abrir(pid)
    arquivo = estudio.arquivo_midia(pid, a)
    quadros = exp.contar_quadros(2.0, 30.0)
    chave = "|".join(map(str, [exp.VERSAO_RENDER, arquivo.name, arquivo.stat().st_size, arquivo.stat().st_mtime_ns,
                               "0.000", quadros, 1080, 1920, "30", projeto.enquadramento, "0.00"]))
    nome = __import__("hashlib").sha1(chave.encode()).hexdigest()[:20] + ".mov"
    assert (estudio.pasta_cache(pid) / "trechos" / nome).exists()
    # Ligadas mas sem palavra dentro do corte: também fica sem legenda (e com a mesma chave).
    item = projeto.linha[0]
    projeto.legendas_ativas = True
    assert exp.legenda_do_item(projeto, item.model_copy(update={"entrada": 1.5}), 1080, 1920) is None
    assert exp.legenda_do_item(projeto, item, 1080, 1920).startswith("[Script Info]")
