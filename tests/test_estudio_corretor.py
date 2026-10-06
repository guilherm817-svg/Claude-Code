"""Corretor de prompts do Estúdio: o pedido montado para o Claude (com o SDK de verdade e só a rede simulada), a
conferência dos blocos, os erros em português e as rotas."""

import json
import os
from pathlib import Path

import anthropic
import httpx2
import pytest
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
