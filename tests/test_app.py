"""Teste de fumaça da interface com o AppTest do Streamlit (roda o app.py de verdade, sem navegador)."""

import time

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from analisador import config, transcricao
from analisador.biblioteca import Etapa
from conftest import SEGMENTOS, _sse

APP = str(config.RAIZ / "app.py")


class WhisperFalso:
    def transcribe(self, caminho, language, batch_size):
        segmentos = [type("S", (), {"start": s.inicio, "end": s.fim, "text": s.texto}) for s in SEGMENTOS]
        return iter(segmentos), type("Info", (), {"duration": 80.0})


@pytest.fixture(autouse=True)
def ambiente(biblioteca, monkeypatch):
    monkeypatch.setattr(config, "PASTA_DADOS", biblioteca.pasta)
    monkeypatch.setattr(transcricao, "_carregar_modelo", lambda modelo, dispositivo: WhisperFalso())
    st.cache_resource.clear()  # cada teste com sua própria fila, apontando para a biblioteca temporária
    yield
    st.cache_resource.clear()


def abrir(aula_id: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    if aula_id:
        at.query_params["aula"] = aula_id
    return at.run()


def botao(at: AppTest, inicio: str):
    return next(b for b in at.button if b.label.startswith(inicio))


def campo(at: AppTest, rotulo: str):
    return next(t for t in at.text_input if t.label == rotulo)


def tudo(at: AppTest) -> str:
    return "\n".join(e.value for e in [*at.markdown, *at.caption, *at.subheader, *at.success, *at.error])


def test_abre_na_pagina_de_adicionar_e_pede_a_chave():
    at = abrir()
    assert not at.exception
    assert at.header[0].value == "Adicionar aulas"
    assert campo(at, "Chave")


def test_salvar_chave(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARQUIVO_ENV", tmp_path / ".env")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # o monkeypatch restaura o valor no fim do teste
    at = abrir()
    botao(at, "Salvar chave").click().run()
    assert at.warning[0].value == "Cole a chave no campo acima."
    campo(at, "Chave").input("sk-ant-minha-chave")
    botao(at, "Salvar chave").click().run()
    assert not at.exception
    assert "ANTHROPIC_API_KEY=sk-ant-minha-chave" in (tmp_path / ".env").read_text()
    assert "Claude conectado" in tudo(at)


def test_adicionar_pasta_transcreve_em_segundo_plano(video, biblioteca):
    at = abrir()
    campo(at, "Caminho da pasta com as aulas").input(str(video.parent)).run()
    assert not at.exception
    botao(at, "Processar 1 aula").click().run()
    assert not at.exception

    aula = biblioteca.aulas()[0]
    assert aula.curso == "Curso X"
    for _ in range(100):  # a fila roda numa thread; espera ela terminar
        if aula.status()["etapa"] not in Etapa.EM_ANDAMENTO:
            break
        time.sleep(0.05)
    assert aula.status()["etapa"] == Etapa.TRANSCRITA  # sem chave: só transcreve
    assert aula.segmentos() == SEGMENTOS


def test_pagina_da_aula_resumo_transcricao_e_quiz(aula_pronta):
    at = abrir(aula_pronta.id)
    assert not at.exception
    assert at.header[0].value == "Aula 01 - Introdução"
    conteudo = tudo(at)
    assert "Como precificar" in conteudo
    assert "Calcule o custo antes do preço." in conteudo
    assert "R\\$ 10 a R\\$ 20" in conteudo  # cifrão escapado para não virar fórmula
    assert "Qual o primeiro passo?" in conteudo

    at.radio(key=f"quiz-{aula_pronta.id}-0").set_value(0)
    next(b for b in at.button if b.label == "Corrigir").click().run()
    assert not at.exception
    assert at.metric[0].value == "1 de 1"
    assert "Correto!" in at.success[0].value

    botao(at, "🔁 Refazer quiz").click().run()
    assert not at.exception
    assert at.radio(key=f"quiz-{aula_pronta.id}-0").value is None
    next(b for b in at.button if b.label == "Corrigir").click().run()
    assert at.metric[0].value == "0 de 1"
    assert "Você marcou: nenhuma" in at.error[0].value


def test_flashcards_virar_e_navegar(aula_pronta):
    at = abrir(aula_pronta.id)
    assert "📍 00:00:31" not in [c.value for c in at.caption]
    botao(at, "🔄 Virar").click().run()
    assert not at.exception
    assert "📍 00:00:31" in [c.value for c in at.caption]


def test_chat_com_a_aula(aula_pronta, api):
    falsa = api((200, _sse("Segundo a aula [00:00:31], o primeiro passo é calcular o custo.")))
    at = abrir(aula_pronta.id)
    at.chat_input(key=f"chat-{aula_pronta.id}").set_value("Qual o primeiro passo?").run()
    assert not at.exception
    assert aula_pronta.chat() == [
        {"role": "user", "content": "Qual o primeiro passo?"},
        {"role": "assistant", "content": "Segundo a aula [00:00:31], o primeiro passo é calcular o custo."},
    ]
    assert falsa.pedidos[0]["body"]["messages"][-1]["content"] == "Qual o primeiro passo?"


def test_aula_sem_analise_mostra_aviso(aula_pronta):
    (aula_pronta.pasta / "analise.json").unlink()
    aula_pronta.definir_status(Etapa.TRANSCRITA, None, "Transcrição pronta.")
    at = abrir(aula_pronta.id)
    assert not at.exception
    assert any("ainda não foi gerada" in i.value for i in at.info)


def test_excluir_aula(aula_pronta, biblioteca):
    at = abrir(aula_pronta.id)
    botao(at, "Confirmar exclusão").click().run()
    assert not at.exception
    assert biblioteca.aulas() == []
    assert at.header[0].value == "Adicionar aulas"
