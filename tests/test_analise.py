"""Testa as chamadas ao Claude com o SDK de verdade, trocando só a rede por respostas simuladas."""

import pytest

from analisador import analise
from analisador.biblioteca import Etapa
from analisador.pipeline import processar_aula
from conftest import _sse, analise_exemplo


def test_analisar_envia_transcricao_em_cache_e_le_saida_estruturada(api, aula_pronta):
    esperado = analise_exemplo()
    falsa = api(
        (200, _sse(esperado.visao_geral.model_dump_json())),
        (200, _sse(esperado.estudo.model_dump_json())),
    )
    progresso = []
    resultado = analise.analisar(aula_pronta, lambda f, m: progresso.append(m))

    assert resultado.visao_geral == esperado.visao_geral
    assert resultado.estudo == esperado.estudo
    assert resultado.uso.entrada_cache_gravada == 1800
    assert resultado.uso.saida == 690
    assert progresso == ["Gerando resumo e capítulos…", "Gerando flashcards e quiz…"]

    primeiro, segundo = (p["body"] for p in falsa.pedidos)
    assert primeiro["model"] == "claude-opus-5-5"
    assert primeiro["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in falsa.pedidos[0]["headers"]["anthropic-beta"]
    assert primeiro["output_config"]["effort"] == "high"
    assert primeiro["output_config"]["format"]["type"] == "json_schema"
    assert primeiro["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert "thinking" not in primeiro and "temperature" not in primeiro
    # A transcrição vai no system com cache, idêntica nas duas chamadas (o prefixo é reaproveitado).
    instrucoes, bloco_aula = primeiro["system"]
    assert bloco_aula["cache_control"] == {"type": "ephemeral"}
    assert "[00:00:31] O primeiro passo é calcular o custo" in bloco_aula["text"]
    assert 'duracao="00:01:20"' in bloco_aula["text"]
    assert segundo["system"] == primeiro["system"]
    assert "cerca de 10" in segundo["messages"][0]["content"]


def test_analisar_trata_recusa_e_chave_invalida(api, aula_pronta):
    api((200, _sse("", stop_reason="refusal")))
    with pytest.raises(analise.ErroAnalise, match="recusou"):
        analise.analisar(aula_pronta)

    api((401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}))
    with pytest.raises(analise.ErroAnalise, match="Chave da API do Claude inválida"):
        analise.analisar(aula_pronta)


def test_json_invalido_vira_erro_amigavel(api, aula_pronta):
    api((200, _sse('{"titulo_sugerido": "x"}')))
    with pytest.raises(analise.ErroAnalise, match="formato inesperado"):
        analise.analisar(aula_pronta)


def test_erro_da_api_no_pipeline_vira_status(api, aula_pronta):
    api((529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}))
    processar_aula(aula_pronta, modelo_whisper="tiny", idioma="pt", refazer_analise=True)
    status = aula_pronta.status()
    assert status["etapa"] == Etapa.ERRO
    assert "529" in status["mensagem"]


def test_chat_em_streaming_reaproveita_o_mesmo_prefixo(api, aula_pronta):
    falsa = api((200, _sse("No [00:00:31] ele explica que o custo vem primeiro.")))
    historico = [{"role": "user", "content": "Do que trata a aula?"},
                 {"role": "assistant", "content": "De precificação."}]
    resposta = "".join(analise.responder(aula_pronta, historico, "Qual o primeiro passo?"))

    assert resposta == "No [00:00:31] ele explica que o custo vem primeiro."
    corpo = falsa.pedidos[0]["body"]
    assert corpo["messages"] == [*historico, {"role": "user", "content": "Qual o primeiro passo?"}]
    assert corpo["system"] == analise.montar_system(aula_pronta)
    assert corpo["cache_control"] == {"type": "ephemeral"}
    assert corpo["output_config"] == {"effort": "medium"}
    assert corpo["fallbacks"] == "default"


def test_chat_avisa_quando_resposta_e_cortada(api, aula_pronta):
    api((200, _sse("Resposta longa", stop_reason="max_tokens")))
    assert "cortada" in "".join(analise.responder(aula_pronta, [], "?"))
