"""Estúdio de Reels: análise dos clipes, projetos, exportação e API. Usa o ffmpeg de verdade, com clipes curtos
gerados na hora."""

import subprocess
import time
from datetime import datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient

from estudio import exportar as exp
from estudio.midia import (
    Cor, ErroMidia, avisos_do_clipe, detectar_fala, ffmpeg, interpretar_sonda, ler_audio, medir_volume, picos_onda,
    sondar, InfoVideo,
)
from estudio.projetos import Ajustes, ErroImportacao, Estudio, Item, Midia
from estudio.servidor import criar_app

TAXA = 16000
CABECALHO = {"X-Estudio": "1"}


def _gerar(destino, *args):
    subprocess.run([ffmpeg(), "-v", "error", "-y", *args, str(destino)], check=True)
    return destino


@pytest.fixture(scope="session")
def clipes(tmp_path_factory):
    """Três clipes de 2 s: com fala no meio, horizontal sem fala clara e vertical sem som."""
    pasta = tmp_path_factory.mktemp("clipes")
    fala = _gerar(
        pasta / "fala.mp4", "-f", "lavfi", "-i", "testsrc2=s=180x320:r=24:d=2",
        "-f", "lavfi", "-i", "sine=f=300:d=1,adelay=500|500,apad=whole_dur=2,volume=0.3",
        "-f", "lavfi", "-i", "anoisesrc=d=2:a=0.002",
        "-filter_complex", "[1:a][2:a]amix=inputs=2:normalize=0[a]", "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-t", "2",
    )
    horizontal = _gerar(
        pasta / "horizontal.mp4", "-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=2",
        "-f", "lavfi", "-i", "sine=f=500:d=2,volume=0.05", "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "2",
    )
    mudo = _gerar(pasta / "mudo.mp4", "-f", "lavfi", "-i", "testsrc2=s=180x320:r=24:d=2",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p")
    texto = pasta / "nao-e-video.mp4"
    texto.write_text("isto não é um vídeo")
    return {"fala": fala, "horizontal": horizontal, "mudo": mudo, "texto": texto}


@pytest.fixture
def estudio(tmp_path):
    return Estudio(tmp_path / "meus-reels")


def _importar(estudio, projeto_id, caminho):
    with open(caminho, "rb") as arquivo:
        return estudio.importar(projeto_id, arquivo, caminho.name)


# Sondagem

SONDA_CELULAR = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'IMG_0001.MOV':
  Duration: 00:00:08.03, start: 0.000000, bitrate: 15722 kb/s
  Stream #0:0[0x1](und): Video: hevc (Main) (hvc1 / 0x31637668), yuv420p(tv, bt709), 1920x1080, 15527 kb/s, 29.97 fps, 29.97 tbr, 600 tbn (default)
      Metadata:
        handler_name    : Core Media Video
      Side data:
        displaymatrix: rotation of -90.00 degrees
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 191 kb/s (default)
"""


def test_sonda_le_celular_girado():
    info = interpretar_sonda(SONDA_CELULAR)
    assert info == InfoVideo(duracao=8.03, largura=1080, altura=1920, fps=29.97, codec="hevc", tem_audio=True,
                             cor=Cor(matriz="bt709", primarias="bt709", transferencia="bt709", faixa="tv"))


def test_sonda_ignora_capa_e_le_rotacao_antiga():
    texto = """  Duration: 00:01:02.50, start: 0.000000, bitrate: 900 kb/s
  Stream #0:0: Video: mjpeg (Baseline), yuvj420p(pc), 600x600, 90k tbr, 90k tbn (attached pic)
  Stream #0:1(und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 720x1280 [SAR 1:1 DAR 9:16], 24 fps, 24 tbr
    Metadata:
      rotate          : 180
  Stream #0:2(und): Audio: aac, 48000 Hz, mono"""
    info = interpretar_sonda(texto)
    assert (info.duracao, info.largura, info.altura, info.fps, info.codec) == (62.5, 720, 1280, 24.0, "h264")


def test_sonda_recusa_arquivo_sem_video():
    with pytest.raises(ErroMidia, match="não tem vídeo"):
        interpretar_sonda("  Duration: 00:00:10.00\n  Stream #0:0: Audio: mp3, 44100 Hz, stereo")


def test_sondar_clipes_reais(clipes):
    assert sondar(clipes["fala"]) == InfoVideo(duracao=2.0, largura=180, altura=320, fps=24.0, codec="h264",
                                                tem_audio=True)
    assert sondar(clipes["mudo"]).tem_audio is False
    with pytest.raises(ErroMidia):
        sondar(clipes["texto"])


# Fala e volume


def _audio(*partes):
    """partes: (segundos, amplitude do tom de 300 Hz); por baixo de tudo, um chiado de fundo."""
    sinal = []
    for segundos, amplitude in partes:
        t = np.arange(int(segundos * TAXA)) / TAXA
        sinal.append(amplitude * np.sin(2 * np.pi * 300 * t))
    sinal = np.concatenate(sinal)
    ruido = np.random.default_rng(1).normal(0, 0.002, len(sinal))
    return (sinal + ruido).astype(np.float32)


def test_detecta_fala_entre_silencios():
    inicio, fim = detectar_fala(_audio((0.5, 0), (2.0, 0.3), (1.5, 0)))
    assert inicio == pytest.approx(0.5, abs=0.03)
    assert fim == pytest.approx(2.5, abs=0.03)


def test_estalo_curto_nao_conta_como_fala():
    inicio, _ = detectar_fala(_audio((0.3, 0), (0.02, 0.5), (0.5, 0), (1.0, 0.3), (0.5, 0)))
    assert inicio == pytest.approx(0.82, abs=0.03)


def test_sem_contraste_nao_corta():
    assert detectar_fala(np.zeros(TAXA * 2, dtype=np.float32)) is None
    assert detectar_fala(_audio((2.0, 0.3))) is None  # som contínuo, como música: não há onde cortar
    ruido = np.random.default_rng(2).normal(0, 0.05, TAXA * 2).astype(np.float32)
    assert detectar_fala(ruido) is None


def test_fala_desde_o_primeiro_quadro():
    # Fala de verdade tem pausas entre as palavras, que dão o contraste com o fundo.
    inicio, fim = detectar_fala(_audio((0.4, 0.3), (0.1, 0), (0.4, 0.3), (0.1, 0), (1.0, 0.3)))
    assert inicio == 0 and fim == pytest.approx(2.0, abs=0.03)


def test_onda_resumida():
    onda = picos_onda(_audio((1.0, 0), (1.0, 0.3)))
    assert onda["por_segundo"] == 100 and len(onda["picos"]) == 200
    assert max(onda["picos"]) == 1.0 and onda["picos"][10] < 0.1


def test_avisos_de_palavra_cortada():
    info = InfoVideo(duracao=8.0, largura=720, altura=1280, fps=24, codec="h264", tem_audio=True)
    codigos = [a["codigo"] for a in avisos_do_clipe(info, (0.0, 7.99), {"picos": [1.0]})]
    assert codigos == ["fala_no_inicio", "fala_no_fim"]
    assert avisos_do_clipe(info, (0.5, 7.0), {"picos": [1.0]}) == []


def test_le_audio_e_mede_volume(clipes):
    audio = ler_audio(clipes["fala"])
    assert len(audio) == pytest.approx(2 * TAXA, abs=TAXA * 0.05)
    integrado, pico = medir_volume(clipes["fala"], 0.4, 1.2)
    assert -40 < integrado < -10 and pico < 0
    assert medir_volume(clipes["fala"], 0, 0.3) is None  # trecho só de ruído: mudo demais para medir
    assert len(ler_audio(clipes["mudo"])) == 0


# Projetos


def test_importar_ja_corta_o_silencio(estudio, clipes):
    projeto = estudio.criar("Meu Reels")
    _, midia, item = _importar(estudio, projeto.id, clipes["fala"])
    assert midia.fala_inicio == pytest.approx(0.5, abs=0.05)
    assert item.entrada == pytest.approx(0.38, abs=0.05) and item.saida == pytest.approx(1.75, abs=0.05)
    assert midia.tira_quadros == 4 and estudio.arquivo_tira(projeto.id, midia.id).exists()
    assert estudio.abrir(projeto.id).linha == [item]

    _, mudo, item_mudo = _importar(estudio, projeto.id, clipes["mudo"])
    assert (item_mudo.entrada, item_mudo.saida) == (0.0, 2.0)
    assert [a.codigo for a in mudo.avisos] == ["sem_audio"]


def test_importar_recusa_o_que_nao_e_video(estudio, clipes, tmp_path):
    projeto = estudio.criar()
    with pytest.raises(ErroImportacao, match="não é um vídeo que o ffmpeg"):
        _importar(estudio, projeto.id, clipes["texto"])
    planilha = tmp_path / "dados.xlsx"
    planilha.write_bytes(b"x")
    with pytest.raises(ErroImportacao, match="Formatos aceitos"):
        _importar(estudio, projeto.id, planilha)
    assert list(estudio.pasta_midia(projeto.id).iterdir()) == []


def test_corte_sugerido():
    base = dict(id="a" * 12, nome="x", arquivo="x.mp4", largura=1, altura=1, fps=24, codec="h264", tem_audio=True)
    assert Midia(**base, duracao=8, fala_inicio=0.5, fala_fim=6.0).corte_sugerido() == (0.38, 6.25)
    assert Midia(**base, duracao=8, fala_inicio=0.05, fala_fim=7.9).corte_sugerido() == (0.0, 8.0)
    assert Midia(**base, duracao=8).corte_sugerido() == (0.0, 8.0)


def test_aplicar_confere_e_limita_os_cortes(estudio, clipes):
    projeto = estudio.criar()
    _, midia, item = _importar(estudio, projeto.id, clipes["fala"])
    copia = Item(id="b" * 12, midia_id=midia.id, entrada=1.95, saida=99)
    salvo = estudio.aplicar(projeto.id, Ajustes(nome="  Novo   nome ", formato="feed", enquadramento="desfocado",
                                                igualar_volume=False, linha=[copia, item]))
    assert salvo.nome == "Novo nome" and salvo.formato == "feed" and salvo.enquadramento == "desfocado"
    assert [i.id for i in salvo.linha] == [copia.id, item.id]
    assert (salvo.linha[0].entrada, salvo.linha[0].saida) == (1.9, 2.0)

    with pytest.raises(ErroImportacao, match="não está no projeto"):
        estudio.aplicar(projeto.id, Ajustes(nome="x", linha=[Item(id="c" * 12, midia_id="d" * 12, entrada=0, saida=1)]))
    with pytest.raises(ErroImportacao, match="mesmo identificador"):
        estudio.aplicar(projeto.id, Ajustes(nome="x", linha=[item, item]))


def test_remover_midia_tira_da_linha_e_apaga_arquivos(estudio, clipes):
    projeto = estudio.criar()
    _, midia, _ = _importar(estudio, projeto.id, clipes["fala"])
    arquivo = estudio.arquivo_midia(projeto.id, midia)
    projeto = estudio.remover_midia(projeto.id, midia.id)
    assert projeto.midias == [] and projeto.linha == [] and not arquivo.exists()


def test_listar_ignora_projeto_corrompido(estudio):
    bom = estudio.criar("Bom")
    (estudio.pasta / "abcdefabcdef").mkdir()
    (estudio.pasta / "abcdefabcdef" / "projeto.json").write_text("{quebrado")
    assert [p.id for p in estudio.listar()] == [bom.id]


# Exportação


def test_escolher_fps_e_ganho():
    assert exp.escolher_fps([(24.0, 5), (30.0, 3)]) == ("24", 24.0)
    assert exp.escolher_fps([(23.976, 5), (29.97, 8)]) == ("30000/1001", 30000 / 1001)
    assert exp.escolher_fps([(120.0, 2)]) == ("60", 60.0)
    assert exp.escolher_fps([]) == ("30", 30.0)
    assert exp.calcular_ganho((-24.0, -10.0)) == 9.0  # sobe até o teto de pico (-1 dBTP), não até -14 LUFS
    assert exp.calcular_ganho((-20.0, -20.0)) == 6.0
    assert exp.calcular_ganho((-8.0, -0.5)) == -6.0
    assert exp.calcular_ganho(None) == 0.0


def test_nome_do_arquivo_sem_caracteres_proibidos(tmp_path):
    momento = datetime(2026, 10, 6, 21, 30)
    assert exp.nome_do_arquivo('Bicarbonato: "parte" 1/2?', tmp_path, momento) == "Bicarbonato parte 12 2026-10-06 21h30.mp4"
    (tmp_path / "x 2026-10-06 21h30.mp4").write_bytes(b"")
    assert exp.nome_do_arquivo("x", tmp_path, momento) == "x 2026-10-06 21h30 (2).mp4"
    assert exp.nome_do_arquivo("...", tmp_path, momento) == "reels 2026-10-06 21h30.mp4"


def test_lista_de_emenda_escapa_aspas(tmp_path):
    assert exp.linha_da_lista(tmp_path / "it's.mov").endswith("/it'\\''s.mov'")


def test_filtro_nao_apaga_a_taxa_de_quadros():
    grafo = exp.filtro_video(1080, 1920, "30", 90, "preencher")
    assert grafo.rstrip("[v]").endswith("trim=end_frame=90")  # um setpts aqui derrubaria para 25 quadros/s
    assert "gblur" in exp.filtro_video(1080, 1920, "30", 90, "desfocado")


def _sondar_saida(caminho):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(caminho)], capture_output=True, text=True)
    return interpretar_sonda(r.stderr)


def test_exportar_monta_reels_com_duracao_exata(estudio, clipes):
    projeto = estudio.criar("Teste")
    for nome in ("fala", "horizontal", "mudo"):
        _importar(estudio, projeto.id, clipes[nome])
    projeto = estudio.abrir(projeto.id)
    esperado = sum(round((i.saida - i.entrada) * 24) for i in projeto.linha) / 24

    exportador = exp.Exportador(estudio)
    resultado = exportador.iniciar(projeto.id, sincrono=True)
    assert resultado.estado == "pronta", resultado.erro
    saida = estudio.pasta_exportados(projeto.id) / resultado.arquivo
    info = _sondar_saida(saida)
    assert (info.largura, info.altura, info.fps, info.tem_audio) == (1080, 1920, 24.0, True)
    assert info.duracao == pytest.approx(esperado, abs=0.05)
    assert len(ler_audio(saida)) / TAXA == pytest.approx(esperado, abs=0.05)
    trechos = sorted((estudio.pasta_cache(projeto.id) / "trechos").glob("*.mov"))
    assert len(trechos) == 3

    # Mudando só o formato, os trechos são refeitos; exportando de novo igual, são reaproveitados.
    projeto.formato = "quadrado"
    estudio.salvar(projeto)
    resultado = exportador.iniciar(projeto.id, sincrono=True)
    info = _sondar_saida(estudio.pasta_exportados(projeto.id) / resultado.arquivo)
    assert (info.largura, info.altura) == (1080, 1080)
    novos = sorted((estudio.pasta_cache(projeto.id) / "trechos").glob("*.mov"))
    assert len(novos) == 3 and not set(novos) & set(trechos)
    antes = [p.stat().st_mtime_ns for p in novos]
    exportador.iniciar(projeto.id, sincrono=True)
    assert [p.stat().st_mtime_ns for p in novos] == antes


def test_exportar_projeto_vazio(estudio):
    projeto = estudio.criar()
    with pytest.raises(exp.ErroExportacao, match="pelo menos um clipe"):
        exp.Exportador(estudio).iniciar(projeto.id)


# API


@pytest.fixture
def cliente(estudio):
    return TestClient(criar_app(estudio))


def test_api_fluxo_completo(cliente, clipes):
    projeto = cliente.post("/api/projetos", json={"nome": "Reels do pepino"}, headers=CABECALHO).json()
    pid = projeto["id"]
    with open(clipes["fala"], "rb") as arquivo:
        r = cliente.post(f"/api/projetos/{pid}/midias", files={"arquivo": ("Bloco 1.mp4", arquivo, "video/mp4")},
                         headers=CABECALHO)
    assert r.status_code == 200, r.text
    midia, item = r.json()["midia"], r.json()["item"]
    assert midia["nome"] == "Bloco 1.mp4" and item["entrada"] > 0.3

    video = cliente.get(f"/api/projetos/{pid}/midias/{midia['id']}/arquivo", headers={"Range": "bytes=0-99"})
    assert video.status_code == 206 and len(video.content) == 100  # o <video> precisa disso para pular no tempo
    assert cliente.get(f"/api/projetos/{pid}/midias/{midia['id']}/tira.jpg").headers["content-type"] == "image/jpeg"
    assert len(cliente.get(f"/api/projetos/{pid}/midias/{midia['id']}/onda").json()["picos"]) == 200

    item_inteiro = {**item, "entrada": 0, "saida": 2}
    r = cliente.put(f"/api/projetos/{pid}", json={"nome": "Reels do pepino", "formato": "reels",
                                                  "enquadramento": "preencher", "igualar_volume": True,
                                                  "linha": [item_inteiro]}, headers=CABECALHO)
    assert r.json()["linha"][0]["entrada"] == 0

    exportacao = cliente.post(f"/api/projetos/{pid}/exportar", headers=CABECALHO).json()
    for _ in range(300):
        exportacao = cliente.get(f"/api/exportacoes/{exportacao['id']}").json()
        if exportacao["estado"] not in ("preparando", "renderizando"):
            break
        time.sleep(0.1)
    assert exportacao["estado"] == "pronta", exportacao
    lista = cliente.get(f"/api/projetos/{pid}/exportados").json()
    assert [a["nome"] for a in lista] == [exportacao["arquivo"]]
    baixado = cliente.get(f"/api/projetos/{pid}/exportados/{exportacao['arquivo']}")
    assert baixado.status_code == 200 and "attachment" in baixado.headers["content-disposition"]
    assert cliente.get(f"/api/projetos/{pid}/exportados/..%2Fprojeto.json").status_code == 404

    assert cliente.delete(f"/api/projetos/{pid}/midias/{midia['id']}", headers=CABECALHO).status_code == 204
    assert cliente.get(f"/api/projetos/{pid}").json()["linha"] == []
    assert cliente.delete(f"/api/projetos/{pid}", headers=CABECALHO).status_code == 204
    assert cliente.get(f"/api/projetos/{pid}").status_code == 404


def test_api_recusa_pedido_de_fora(cliente):
    assert cliente.post("/api/projetos", json={}).status_code == 403  # sem o cabeçalho da tela
    assert cliente.get("/api/projetos", headers={"Host": "site-malicioso.com"}).status_code == 400
    assert cliente.get("/api/projetos/../../etc").status_code == 404
    assert cliente.get("/api/projetos/zzz").status_code == 404


def test_api_erros_em_portugues(cliente, clipes):
    pid = cliente.post("/api/projetos", json={}, headers=CABECALHO).json()["id"]
    with open(clipes["texto"], "rb") as arquivo:
        r = cliente.post(f"/api/projetos/{pid}/midias", files={"arquivo": ("x.mp4", arquivo)}, headers=CABECALHO)
    assert r.status_code == 400 and "não é um vídeo" in r.json()["detail"]
    r = cliente.post(f"/api/projetos/{pid}/exportar", headers=CABECALHO)
    assert r.status_code == 400 and "pelo menos um clipe" in r.json()["detail"]


def test_tela_abre(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "Estúdio de Reels" in r.text
