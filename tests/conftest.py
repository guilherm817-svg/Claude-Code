import json
import os
import sys
from pathlib import Path

import anthropic
import httpx2
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
# Nunca usar a biblioteca nem a chave reais durante os testes.
os.environ["ANALISADOR_PASTA_DADOS"] = str(RAIZ / ".pytest_cache" / "biblioteca-nao-usar")
os.environ["ESTUDIO_PASTA_DADOS"] = str(RAIZ / ".pytest_cache" / "estudio-nao-usar")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

from analisador.biblioteca import Biblioteca, Etapa, Segmento  # noqa: E402
from analisador.modelos import (  # noqa: E402
    Analise, Capitulo, Conceito, Flashcard, MaterialEstudo, QuestaoQuiz, VisaoGeral,
)


@pytest.fixture
def biblioteca(tmp_path):
    return Biblioteca(tmp_path / "biblioteca")


@pytest.fixture
def video(tmp_path):
    arquivo = tmp_path / "Curso X" / "Aula 01 - Introdução.mp4"
    arquivo.parent.mkdir(parents=True)
    arquivo.write_bytes(b"video falso")
    return arquivo


SEGMENTOS = [
    Segmento(0.0, 12.5, "Olá, bem-vindos à aula."),
    Segmento(12.5, 29.0, "Hoje vamos falar de precificação."),
    Segmento(31.0, 45.0, "O primeiro passo é calcular o custo, uns R$ 10 a R$ 20."),
    Segmento(65.0, 80.0, "Agora, a margem de lucro."),
]


def analise_exemplo() -> Analise:
    return Analise(
        visao_geral=VisaoGeral(
            titulo_sugerido="Como precificar",
            resumo="A aula explica como precificar.",
            pontos_chave=["Calcule o custo antes do preço."],
            conceitos=[Conceito(termo="Margem", explicacao="Quanto sobra.")],
            acoes_praticas=["Liste seus custos."],
            capitulos=[Capitulo(inicio="00:00:00", titulo="Abertura", resumo="Boas-vindas.")],
        ),
        estudo=MaterialEstudo(
            flashcards=[Flashcard(pergunta="Qual o primeiro passo?", resposta="Calcular o custo.", minuto="00:00:31")],
            quiz=[QuestaoQuiz(pergunta="O que vem primeiro?", alternativas=["Custo", "Preço", "Venda", "Lucro"],
                              correta=0, explicacao="O custo vem antes.", minuto="00:00:31")],
        ),
        modelo="claude-opus-5-5",
        gerada_em="2026-10-05T10:00:00",
    )


@pytest.fixture
def aula_pronta(biblioteca, video):
    aula = biblioteca.adicionar(video, "Curso X")
    aula.salvar_transcricao(SEGMENTOS, 80.0, "tiny", "pt")
    aula.salvar_analise(analise_exemplo())
    aula.definir_status(Etapa.PRONTA)
    return aula


def _sse(texto: str, stop_reason: str = "end_turn") -> bytes:
    eventos = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 1,
                      "cache_creation_input_tokens": 900, "cache_read_input_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        *[("content_block_delta", {"type": "content_block_delta", "index": 0,
                                   "delta": {"type": "text_delta", "text": texto[i:i + 40]}})
          for i in range(0, len(texto), 40)],
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                           "usage": {"output_tokens": 345}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {nome}\ndata: {json.dumps(dados)}\n\n" for nome, dados in eventos).encode()


class ApiFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.pedidos.append({"headers": request.headers, "body": json.loads(request.content)})
        status, corpo = self.respostas.pop(0)
        if status != 200:
            return httpx2.Response(status, json=corpo)
        return httpx2.Response(200, content=corpo, headers={"content-type": "text/event-stream"})


@pytest.fixture
def api(monkeypatch):
    from analisador import analise as analise_mod

    def instalar(*respostas):
        falsa = ApiFalsa(respostas)
        cliente = anthropic.Anthropic(
            api_key="sk-ant-teste", max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(falsa)),
        )
        monkeypatch.setattr(analise_mod, "_cliente", lambda: cliente)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
        return falsa
    return instalar
