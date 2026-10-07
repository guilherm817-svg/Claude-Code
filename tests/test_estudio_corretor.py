"""Corretor de prompts do Estúdio: o pedido montado para o Claude (com o SDK de verdade e só a rede simulada), a
conferência dos blocos, os erros em português, as rotas e o cancelamento no meio da correção."""

import json
import os
import select
import socket
import threading
import time
from pathlib import Path

import anthropic
import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient

from conftest import ApiFalsa, _sse
from estudio import config, corretor
from estudio.projetos import Estudio
from estudio.servidor import criar_app

CABECALHO = {"X-Estudio": "1"}
EXEMPLO = Path(__file__).parent / "dados" / "correcao_exemplo.json"
# Prompt real do usuário, gerado no Meta AI.
PROMPT_REAL = (
    'Vertical 9:16 4K 8s iPhone. Identical couple from Ingredient 1 in bedroom at night warm lamp, bathroom scale in '
    'corner. Man gently takes scale away. Man says in PT-BR: "Nao se pesa hoje" Woman says in PT-BR: "Aprendi parei '
    'com bicarbonato pra emagrecer tem muito sodio agora e comida simples e 30 min de caminhada comenta YES" '
    'No captions.'
)
CHAVE = "sk-ant-api03-SEGREDO_de-teste_0123456789abcdef"


def exemplo() -> dict:
    return json.loads(EXEMPLO.read_text(encoding="utf-8"))


def _erro(status: int, tipo: str, mensagem: str):
    return status, {"type": "error", "error": {"type": tipo, "message": mensagem}}


@pytest.fixture
def claude(monkeypatch):
    """Instala respostas simuladas da API (como o `api` do conftest faz para o Analisador)."""
    def instalar(*respostas, transporte=None):
        falsa = ApiFalsa(respostas)
        cliente = anthropic.Anthropic(
            api_key="sk-ant-teste", max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(transporte or falsa)),
        )
        monkeypatch.setattr(corretor, "_cliente", lambda: cliente)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
        return falsa
    return instalar


def pedido(**campos) -> corretor.PedidoCorrecao:
    return corretor.ler_pedido({"prompt": PROMPT_REAL, **campos})


# Pedido ao Claude e saída conferida


def test_pedido_vai_com_as_regras_em_cache_e_a_saida_e_conferida(claude):
    falsa = claude((200, _sse(json.dumps(exemplo(), ensure_ascii=False))))
    eventos = list(corretor.acompanhar(pedido(pedido_original="Casal no quarto, ele tira a balança.")))

    assert [e["etapa"] for e in eventos if "etapa" in e] == [1, 2, 3, 4, 5]
    resultado = eventos[-1]["resultado"]
    assert len(resultado.problemas) == 14
    gravidades = [p.gravidade for p in resultado.problemas]
    assert gravidades == sorted(gravidades, key=["alta", "media", "baixa"].index)
    bloco1, bloco2 = resultado.blocos
    # Homem (4 palavras) + Mulher (9) com uma troca: 13 ÷ 2,5 + 0,9 + 0,5 = 6,6 s; Mulher sozinha: 11 ÷ 2,5 + 0,9.
    assert (bloco1.palavras, bloco1.duracao_fala_s, bloco1.avisos) == (13, 6.6, [])
    assert (bloco2.palavras, bloco2.duracao_fala_s, bloco2.avisos) == (11, 5.3, [])
    assert bloco1.caracteres == len(bloco1.prompt) <= corretor.LIMITE_CARACTERES
    assert (resultado.gerador, resultado.duracao_clipe, resultado.cadencia) == ("veo", 8, "natural")
    assert resultado.modelo == "claude-opus-5-5"

    corpo = falsa.pedidos[0]["body"]
    assert corpo["model"] == "claude-opus-5-5"
    assert corpo["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in falsa.pedidos[0]["headers"]["anthropic-beta"]
    assert corpo["output_config"]["effort"] == "high"
    formato = corpo["output_config"]["format"]
    assert formato["type"] == "json_schema" and formato["schema"]["additionalProperties"] is False
    assert {"problemas", "blocos", "acrescentados_pela_ia", "alertas_de_alcance", "estilo_de_legenda"} <= set(
        formato["schema"]["required"])
    assert "thinking" not in corpo and "temperature" not in corpo
    # As regras vão inteiras no system, com cache: o prefixo é o mesmo em toda correção.
    [regras] = corpo["system"]
    assert regras["cache_control"] == {"type": "ephemeral"}
    assert regras["text"] == corretor.REGRAS.read_text(encoding="utf-8")
    texto = corpo["messages"][0]["content"]
    assert f"<prompt_do_usuario>\n{PROMPT_REAL}\n</prompt_do_usuario>" in texto
    assert "Google Flow (Veo 3.1)" in texto and "Duração de cada clipe: 8 s" in texto
    assert "Cabem cerca de 17 palavras" in texto
    assert "<pedido_original>\nCasal no quarto, ele tira a balança.\n</pedido_original>" in texto
    assert "<itens_para_tirar>" not in texto


def test_regras_trazem_as_licoes_do_usuario():
    regras = " ".join(corretor.REGRAS.read_text(encoding="utf-8").split())
    for licao in ["2500", "Ingredientes", "Frames", "4K", "gêmeos", "Arm & Hammer", "Câmera lenta",
                  "Brazilian Portuguese, natural accent from Brazil, not European Portuguese", "VapoRub",
                  "trinta minutos", "fifty-four", "agora é comida", "isca de engajamento", "estilo_de_legenda",
                  "(no subtitles, no captions, no on-screen text)", "[Negative]", "2,75", "3,1"]:
        assert licao in regras, licao


def test_regras_trazem_todas_as_travas_da_skill_do_usuario():
    regras = " ".join(corretor.REGRAS.read_text(encoding="utf-8").split())
    for trava in [
        # Gesto no fígado/barriga, carro parado, elemento que passa no fundo.
        "fígado", "barriga", "liver, stomach, belly", "parked, stationary car", "warm indoor tone", "cat morphing",
        # Tipos de bloco especiais e continuação.
        "[HOOK]", "[READS Q1]", "[REACTION / IDLE]", "No speech, no voice, the man does not talk",
        "mouthing words", "mouth settling closed, no filler sound",
        # Anti-corte da 1ª palavra (1,2 s reforçado e palavra-isca) e anti-loop completo.
        "no lip movement before 1.2s", "full silence for the first 1.2s", "clipped first word", "Palavra-isca",
        "repeated words, repeating the sentence, looping speech, double speech, echo, stutter",
        "fills the whole window",
        # Troubleshooting: entonação, piscar, distância fixa, anatomia, recusa clínica, legenda que volta.
        "downward, conclusive falling intonation", "blink naturally and irregularly", "no push-in",
        "eyes natural, not widened", "shape and size stay identical", "jaleco", "estetoscópio", "no lower thirds",
        # Modelos e pronúncia.
        "5 a 8 s é o ponto ideal", '"extend"', "sluggish pacing", "nine-teen six-tees", "Ritual Labs",
    ]:
        assert trava in regras, trava
    assert "5 a 10 s" not in regras


def test_seedance_comeca_no_ponto_ideal_de_duracao():
    assert pedido(gerador="seedance").duracao_clipe == 8


def test_itens_para_tirar_e_outros_geradores_entram_no_pedido(claude):
    falsa = claude((200, _sse(json.dumps(exemplo(), ensure_ascii=False))))
    corretor.corrigir(pedido(gerador="kling", cadencia="1.25x", idioma_fala="pt-BR", objetivo="anuncio",
                             remover_itens=["  Chamada comenta YES ", ""]))
    texto = falsa.pedidos[0]["body"]["messages"][0]["content"]
    assert "Kling" in texto and "Duração de cada clipe: 10 s" in texto
    assert "Cabem cerca de 28 palavras" in texto  # (10 - 0,9) × 3,1
    assert "Português do Brasil" in texto and "Anúncio pago" in texto
    assert "<itens_para_tirar>\n- Chamada comenta YES\n</itens_para_tirar>" in texto


def test_avisos_automaticos_quando_o_bloco_passa_do_limite_ou_a_fala_nao_cabe(claude):
    resposta = exemplo()
    resposta["blocos"][0]["prompt"] += " Extra detail." * 30  # passa de 2500 caracteres
    junta = resposta["blocos"][1]["falas"][0]["texto"] + " E você, já caiu nessa? Me conta aqui embaixo agora."
    resposta["blocos"][1]["falas"][0]["texto"] = junta
    resposta["blocos"][1]["prompt"] = resposta["blocos"][1]["prompt"].replace(
        "Agora é comida simples e trinta minutos de caminhada. Comenta yes!", junta)
    claude((200, _sse(json.dumps(resposta, ensure_ascii=False))))
    bloco1, bloco2 = corretor.corrigir(pedido()).blocos

    [aviso] = bloco1.avisos
    assert aviso.tipo == "alerta" and "2.564 caracteres" in aviso.texto and "o limite é 2.500" in aviso.texto
    [aviso] = bloco2.avisos
    assert aviso.tipo == "alerta"
    assert "21 palavras" in aviso.texto and "9,3 s" in aviso.texto and "cabem cerca de 17 palavras" in aviso.texto


def test_conferir_bloco_dicas_de_fala_curta_e_fala_diferente_do_prompt():
    curto = corretor.Bloco(titulo="Bloco 1", falas=[corretor.Fala(quem="", texto="Olha isso.")],
                           duracao_estimada_s=3, prompt='She says: "Olha isso." (no subtitles)')
    [dica] = corretor.conferir_bloco(curto, pedido()).avisos
    assert dica.tipo == "dica" and "Sobram cerca de 6,3 s" in dica.texto

    trocado = curto.model_copy(update={"prompt": 'She says: "Olha só isso." (no subtitles)'})
    textos = [a.texto for a in corretor.conferir_bloco(trocado, pedido()).avisos]
    assert any("não aparece igual" in t for t in textos)

    imagem = corretor.conferir_bloco(curto, pedido(gerador="imagem"))
    assert (imagem.palavras, imagem.duracao_fala_s, imagem.avisos) == (0, 0.0, [])


def test_contas_de_tempo():
    assert corretor.contar_palavras('"Não se pesa hoje."') == 4
    assert corretor.contar_palavras("fifty-four, I'll go") == 3
    assert [corretor.palavras_que_cabem(8, c) for c in ("natural", "1.1x", "1.25x")] == [17, 19, 22]
    assert corretor.palavras_que_cabem(10, "natural") == 22


def test_ler_pedido_preenche_padroes_e_valida_em_portugues():
    assert pedido().duracao_clipe == 8
    assert pedido(gerador="kling").duracao_clipe == 10
    assert pedido(gerador="seedance", duracao_clipe="15").duracao_clipe == 15
    assert pedido(gerador="imagem", duracao_clipe=8).duracao_clipe is None
    casos = [
        ({"prompt": "   "}, "Cole o prompt"),
        ({"prompt": "x" * 20_001}, "20.000 caracteres"),
        ({"prompt": "x", "gerador": "sora"}, "Escolha o gerador"),
        ({"prompt": "x", "duracao_clipe": 10}, "até 8 segundos"),
        ({"prompt": "x", "duracao_clipe": 7.5}, "número inteiro"),
        ({"prompt": "x", "cadencia": "2x"}, "ritmo da fala"),
        ({"prompt": "x", "pedido_original": "y" * 5001}, "5.000 caracteres"),
        ({"prompt": "x", "remover_itens": "tudo"}, "itens para tirar"),
        (["não é objeto"], "Pedido inválido"),
    ]
    for dados, mensagem in casos:
        with pytest.raises(corretor.ErroCorretor, match=mensagem):
            corretor.ler_pedido(dados)


# Recusas e erros


def test_recusa_do_classificador_e_pedido_perigoso(claude):
    claude((200, _sse("", stop_reason="refusal")))
    with pytest.raises(corretor.ErroCorretor, match="não quis corrigir"):
        corretor.corrigir(pedido())

    perigoso = {**exemplo(), "recusado": True, "motivo_recusa": "Ensina a passar Vick com bicarbonato na virilha."}
    claude((200, _sse(json.dumps(perigoso, ensure_ascii=False))))
    resultado = corretor.corrigir(pedido())
    assert resultado.recusado and "virilha" in resultado.motivo_recusa
    assert resultado.blocos == []  # nada para copiar quando o pedido inteiro é perigoso


def test_resposta_cortada_ou_fora_do_formato(claude):
    claude((200, _sse('{"recusado": false', stop_reason="max_tokens")))
    with pytest.raises(corretor.ErroCorretor, match="longa demais"):
        corretor.corrigir(pedido())
    claude((200, _sse('{"resumo": "faltou o resto"}')))
    with pytest.raises(corretor.ErroCorretor, match="formato inesperado"):
        corretor.corrigir(pedido())


def _sse_eventos(*eventos: dict) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in eventos).encode()


def _bloco_de_texto(indice: int, texto: str) -> list[dict]:
    return [
        {"type": "content_block_start", "index": indice, "content_block": {"type": "text", "text": ""}},
        *[{"type": "content_block_delta", "index": indice, "delta": {"type": "text_delta", "text": texto[i:i + 300]}}
          for i in range(0, len(texto), 300)],
        {"type": "content_block_stop", "index": indice},
    ]


def test_recusa_no_meio_com_o_modelo_de_reserva_continuando_o_json(claude):
    # O modelo pedido recusa no meio: o texto parcial fica, vem o bloco "fallback" e o modelo de reserva continua
    # do ponto onde o outro parou. O JSON só fecha juntando os dois pedaços.
    texto = json.dumps(exemplo(), ensure_ascii=False)
    meio = len(texto) // 2
    resposta = _sse_eventos(
        {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 12, "output_tokens": 1}}},
        *_bloco_de_texto(0, texto[:meio]),
        {"type": "content_block_start", "index": 1, "content_block": {
            "type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "modelo-de-reserva"},
            "trigger": {"type": "refusal", "category": None}}},
        {"type": "content_block_stop", "index": 1},
        *_bloco_de_texto(2, texto[meio:]),
        {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
         "usage": {"output_tokens": 345}},
        {"type": "message_stop"},
    )
    claude((200, resposta))
    resultado = corretor.corrigir(pedido())
    assert len(resultado.problemas) == 14 and len(resultado.blocos) == 2
    assert resultado.modelo == "modelo-de-reserva"  # quem terminou a resposta


@pytest.mark.parametrize("resposta, mensagem, codigo", [
    (_erro(401, "authentication_error", "invalid x-api-key"), "Chave da API do Claude inválida", "chave"),
    (_erro(400, "invalid_request_error", "Your credit balance is too low to access the Anthropic API."),
     "Sem créditos", "creditos"),
    (_erro(404, "not_found_error", "model: claude-x"), "Modelo claude-opus-5-5 não encontrado", "erro"),
    (_erro(429, "rate_limit_error", "Too many"), "Limite de uso", "erro"),
    (_erro(529, "overloaded_error", "Overloaded"), "sobrecarregados", "erro"),
])
def test_erros_da_api_em_portugues(claude, resposta, mensagem, codigo):
    claude(resposta)
    with pytest.raises(corretor.ErroCorretor, match=mensagem) as erro:
        corretor.corrigir(pedido())
    assert erro.value.codigo == codigo


def test_sem_conexao_e_erro_no_meio_da_resposta(claude):
    def sem_rede(request):
        raise httpx2.ConnectError("sem rede", request=request)
    claude(transporte=sem_rede)
    with pytest.raises(corretor.ErroCorretor, match="Sem conexão") as erro:
        corretor.corrigir(pedido())
    assert erro.value.codigo == "conexao"

    inicio = _sse("").split(b"event: content_block_start")[0]
    quebrada = inicio + b'event: error\ndata: {"type": "error", "error": {"type": "overloaded_error", "message": "x"}}\n\n'
    claude((200, quebrada))
    with pytest.raises(corretor.ErroCorretor, match="sobrecarregados"):
        corretor.corrigir(pedido())

    def cai_no_meio(request):
        def corpo():
            yield inicio
            raise httpx2.ReadError("conexão caiu")
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=corpo())
    claude(transporte=cai_no_meio)
    with pytest.raises(corretor.ErroCorretor, match="caiu no meio da resposta") as erro:
        corretor.corrigir(pedido())
    assert erro.value.codigo == "conexao"


# Rotas


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARQUIVO_ENV", tmp_path / ".env")
    # setenv antes de delenv: assim o monkeypatch anota o valor original e o devolve no fim, mesmo que a rota
    # /api/chave grave outra chave no processo.
    for nome in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.setenv(nome, "")
        monkeypatch.delenv(nome)
    return TestClient(criar_app(Estudio(tmp_path / "meus-reels")))


def _linhas(resposta) -> list[dict]:
    return [json.loads(linha) for linha in resposta.text.splitlines() if linha.strip()]


def test_rota_estado_e_opcoes(cliente):
    estado = cliente.get("/api/corretor/estado").json()
    assert estado["tem_chave"] is False and estado["modelo"] == "claude-opus-5-5"
    veo = next(g for g in estado["geradores"] if g["id"] == "veo")
    assert (veo["padrao"], veo["teto"], veo["duracoes"]) == (8, 8, [4, 6, 8])
    assert [c["palavras_por_segundo"] for c in estado["cadencias"]] == [2.5, 2.75, 3.1]
    assert estado["limite_caracteres"] == 2500


def test_rotas_recusam_pedido_sem_o_cabecalho_da_tela(cliente):
    assert cliente.post("/api/corretor", json={"prompt": "x"}).status_code == 403
    assert cliente.post("/api/chave", json={"chave": CHAVE}).status_code == 403
    assert not config.ARQUIVO_ENV.exists()


@pytest.mark.parametrize("corpo, mensagem", [
    ({}, "Cole o prompt"),
    ({"prompt": ""}, "Cole o prompt"),
    ({"prompt": "x", "gerador": "sora"}, "Escolha o gerador"),
    ({"prompt": "x", "gerador": "kling", "duracao_clipe": 30}, "até 10 segundos"),
    ([1, 2], "Pedido inválido"),
])
def test_rota_corretor_recusa_entrada_invalida(cliente, corpo, mensagem):
    r = cliente.post("/api/corretor", json=corpo, headers=CABECALHO)
    assert r.status_code == 400 and mensagem in r.json()["detail"]


def test_rota_corretor_recusa_corpo_que_nao_e_json(cliente):
    r = cliente.post("/api/corretor", content=b"isto nao e json", headers={**CABECALHO, "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["detail"] == "Pedido inválido."


def test_rota_corretor_pede_a_chave_quando_falta(cliente):
    r = cliente.post("/api/corretor", json={"prompt": PROMPT_REAL}, headers=CABECALHO)
    assert r.status_code == 400 and r.json()["codigo"] == "chave"


def test_rota_chave_grava_no_env_sem_devolver_a_chave(cliente):
    config.ARQUIVO_ENV.write_text("ANALISADOR_IDIOMA=pt\n")
    r = cliente.post("/api/chave", json={"chave": f"  {CHAVE}\n"}, headers=CABECALHO)
    assert r.status_code == 200 and r.json() == {"tem_chave": True, "modelo": "claude-opus-5-5"}
    assert CHAVE not in r.text
    linhas = config.ARQUIVO_ENV.read_text().splitlines()
    assert linhas == ["ANALISADOR_IDIOMA=pt", f"ANTHROPIC_API_KEY={CHAVE}"]
    assert os.environ["ANTHROPIC_API_KEY"] == CHAVE
    estado = cliente.get("/api/corretor/estado")
    assert estado.json()["tem_chave"] is True and CHAVE not in estado.text


@pytest.mark.parametrize("chave", ["abc", "sk-ant-curta", "sk-ant-api03-boa\nOUTRA=1", 12345, None])
def test_rota_chave_recusa_o_que_nao_parece_chave(cliente, chave):
    r = cliente.post("/api/chave", json={"chave": chave}, headers=CABECALHO)
    assert r.status_code == 400 and "sk-ant-" in r.json()["detail"]
    assert str(chave) not in r.json()["detail"]
    assert not config.ARQUIVO_ENV.exists() and "ANTHROPIC_API_KEY" not in os.environ


def test_rota_corretor_responde_em_etapas_e_termina_no_resultado(cliente, claude):
    claude((200, _sse(json.dumps(exemplo(), ensure_ascii=False))))
    r = cliente.post("/api/corretor", json={"prompt": PROMPT_REAL, "gerador": "veo", "duracao_clipe": 8},
                     headers=CABECALHO)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    linhas = _linhas(r)
    assert [linha["etapa"] for linha in linhas[:-1]] == [1, 2, 3, 4, 5]
    assert linhas[0]["texto"] == "Enviando o prompt para o Claude"
    resultado = linhas[-1]["resultado"]
    assert len(resultado["blocos"]) == 2 and resultado["blocos"][0]["caracteres"] > 0
    assert resultado["acrescentados_pela_ia"][0]["item"].startswith("Chamada")


def test_rota_corretor_erro_da_api_vira_linha_de_erro_sem_vazar_a_chave(cliente, claude):
    claude(_erro(401, "authentication_error", "invalid x-api-key"))
    r = cliente.post("/api/corretor", json={"prompt": PROMPT_REAL}, headers=CABECALHO)
    assert r.status_code == 200
    ultima = _linhas(r)[-1]
    assert ultima == {"erro": ultima["erro"], "codigo": "chave"} and "inválida" in ultima["erro"]
    assert "sk-ant-teste" not in r.text


def test_tela_tem_as_abas_e_o_corretor(cliente):
    pagina = cliente.get("/static/index.html").text
    assert "Corretor de prompts" in pagina and "/static/corretor.css" in pagina
    assert cliente.get("/static/corretor.js").status_code == 200


# Cancelamento: com uma "API" de verdade na rede local, que fica raciocinando e só manda pings


class ApiPensando:
    """Responde como o Claude raciocinando: começa a mensagem e depois só manda pings (que o SDK ignora), por até
    15 s. Anota quando o cliente derruba a conexão."""

    def __init__(self):
        self.servidor = socket.create_server(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.servidor.getsockname()[1]}"
        self.fechou = threading.Event()
        threading.Thread(target=self._atender, daemon=True).start()

    def _atender(self):
        conexao, _ = self.servidor.accept()
        with conexao:
            pedido = b""
            while b"\r\n\r\n" not in pedido:
                pedido += conexao.recv(65536)
            cabecalho, corpo = pedido.split(b"\r\n\r\n", 1)
            tamanho = int(next(linha.split(b":")[1] for linha in cabecalho.split(b"\r\n")
                               if linha.lower().startswith(b"content-length")))
            while len(corpo) < tamanho:
                corpo += conexao.recv(65536)
            inicio = _sse("").split(b"event: content_block_start")[0]
            ping = b"event: ping\ndata: {\"type\": \"ping\"}\n\n"
            try:
                conexao.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
                                b"transfer-encoding: chunked\r\n\r\n")
                for pedaco in [inicio, *[ping] * 150]:
                    conexao.sendall(f"{len(pedaco):x}\r\n".encode() + pedaco + b"\r\n")
                    pronto, _, _ = select.select([conexao], [], [], 0.1)
                    if pronto and not conexao.recv(1024):
                        self.fechou.set()
                        return
            except OSError:
                self.fechou.set()

    def cliente(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key="sk-ant-teste", base_url=self.url, max_retries=0,
                                   http_client=anthropic.DefaultHttpxClient(trust_env=False))


@pytest.fixture
def api_pensando(monkeypatch):
    api = ApiPensando()
    monkeypatch.setattr(corretor, "_cliente", api.cliente)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    yield api
    api.servidor.close()


def test_cancelar_derruba_a_conexao_com_a_api_mesmo_enquanto_o_claude_raciocina(api_pensando):
    cancelamento = corretor.Cancelamento()
    eventos = corretor.acompanhar(pedido(), cancelamento)
    assert [next(eventos)["etapa"], next(eventos)["etapa"]] == [1, 2]
    erro = {}

    def esperar_o_proximo():
        try:
            next(eventos)
        except corretor.ErroCorretor as e:
            erro["codigo"] = e.codigo

    thread = threading.Thread(target=esperar_o_proximo)
    thread.start()
    time.sleep(0.4)
    assert thread.is_alive()  # parada esperando o Claude, que só manda pings
    cancelamento.cancelar()
    thread.join(2)
    assert not thread.is_alive() and erro == {"codigo": "cancelada"}
    assert api_pensando.fechou.wait(2)


def test_navegador_que_desiste_derruba_a_conexao_com_a_api(api_pensando, tmp_path, caplog):
    servidor = uvicorn.Server(uvicorn.Config(criar_app(Estudio(tmp_path / "meus-reels")), host="127.0.0.1",
                                             port=0, log_level="warning"))
    thread = threading.Thread(target=servidor.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if servidor.started:
                break
            time.sleep(0.05)
        porta = servidor.servers[0].sockets[0].getsockname()[1]
        with httpx2.Client(trust_env=False, timeout=10) as http:
            with http.stream("POST", f"http://127.0.0.1:{porta}/api/corretor", json={"prompt": PROMPT_REAL},
                             headers=CABECALHO) as r:
                linhas = r.iter_lines()
                assert [json.loads(next(linhas))["etapa"] for _ in range(2)] == [1, 2]
                time.sleep(0.3)
            # Sair antes do fim fecha a conexão, como o Cancelar da tela ou fechar a aba.
        assert api_pensando.fechou.wait(3), "a conexão com a API continuou aberta depois que o navegador desistiu"
        time.sleep(0.3)
        assert not [r for r in caplog.records if r.levelname == "ERROR"]
    finally:
        servidor.should_exit = True
        thread.join(5)
