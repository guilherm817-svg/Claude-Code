"""Rotas do Corretor de prompts e da chave da API. Ficam separadas para o servidor só precisar incluí-las.

A correção pode levar dezenas de segundos, então a resposta vem em linhas de JSON (uma por etapa) e termina com
o resultado ou com o erro. A chave da API nunca volta em nenhuma resposta.
"""

import json
import logging

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import config, corretor

log = logging.getLogger(__name__)


async def _corpo(request: Request):
    try:
        return await request.json()
    except ValueError:
        return None


def _linha(dados: dict) -> str:
    return json.dumps(dados, ensure_ascii=False) + "\n"


async def _transmitir(pedido: corretor.PedidoCorrecao):
    """Passa as etapas da correção para a tela, linha a linha.

    Se o navegador desistir no meio (Cancelar, aba fechada), o servidor cancela esta resposta. A espera pela thread
    é abandonada na hora, sem aguardar o próximo evento do Claude, e a conexão com a API é derrubada.
    """
    cancelamento = corretor.Cancelamento()
    eventos = corretor.acompanhar(pedido, cancelamento)
    acabou = na_thread = False
    try:
        while True:
            na_thread = True
            try:
                evento = await anyio.to_thread.run_sync(next, eventos, None, abandon_on_cancel=True)
            except corretor.ErroCorretor as erro:
                acabou = True
                yield _linha({"erro": str(erro), "codigo": erro.codigo})
                return
            except Exception:
                acabou = True
                log.exception("Falha inesperada no Corretor de prompts")
                yield _linha({"erro": "Algo deu errado ao corrigir o prompt. Tente de novo.", "codigo": "erro"})
                return
            na_thread = False
            if evento is None:
                acabou = True
                return
            if "resultado" in evento:
                evento = {"resultado": evento["resultado"].model_dump(mode="json")}
            yield _linha(evento)
    finally:
        if not acabou:
            cancelamento.cancelar()
            # Parada entre dois eventos: fecha aqui mesmo. Se a thread ainda roda, ela termina sozinha ao ver o
            # cancelamento (fechar um gerador em uso por outra thread daria erro).
            if not na_thread:
                eventos.close()


def rotas_corretor() -> APIRouter:
    rotas = APIRouter()

    @rotas.get("/api/corretor/estado")
    def estado():
        return {"tem_chave": config.credenciais_claude(), "modelo": config.MODELO_CLAUDE, **corretor.opcoes()}

    @rotas.post("/api/chave")
    async def salvar_chave(request: Request):
        dados = await _corpo(request)
        try:
            config.salvar_chave_api(dados.get("chave") if isinstance(dados, dict) else None)
        except ValueError as erro:
            return JSONResponse({"detail": str(erro)}, status_code=400)
        return {"tem_chave": True, "modelo": config.MODELO_CLAUDE}

    @rotas.post("/api/corretor")
    async def corrigir(request: Request):
        try:
            pedido = corretor.ler_pedido(await _corpo(request))
        except corretor.ErroCorretor as erro:
            return JSONResponse({"detail": str(erro)}, status_code=400)
        if not config.credenciais_claude():
            return JSONResponse({"detail": "Falta conectar o Corretor ao Claude: cole a sua chave da API.",
                                 "codigo": "chave"}, status_code=400)

        return StreamingResponse(_transmitir(pedido), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store"})

    return rotas
