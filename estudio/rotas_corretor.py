"""Rotas do Corretor de prompts e da chave da API. Ficam separadas para o servidor só precisar incluí-las.

A correção pode levar dezenas de segundos, então a resposta vem em linhas de JSON (uma por etapa) e termina com
o resultado ou com o erro. A chave da API nunca volta em nenhuma resposta.
"""

import json
import logging

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

        def eventos():
            try:
                for evento in corretor.acompanhar(pedido):
                    if "resultado" in evento:
                        evento = {"resultado": evento["resultado"].model_dump(mode="json")}
                    yield _linha(evento)
            except corretor.ErroCorretor as erro:
                yield _linha({"erro": str(erro), "codigo": erro.codigo})
            except Exception:
                log.exception("Falha inesperada no Corretor de prompts")
                yield _linha({"erro": "Algo deu errado ao corrigir o prompt. Tente de novo.", "codigo": "erro"})

        return StreamingResponse(eventos(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store"})

    return rotas
