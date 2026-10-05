"""Monta o app FastAPI: rotas, arquivos do painel e sincronização em segundo plano."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from rastro import __version__
from rastro.config import Config, carregar
from rastro.db import Banco
from rastro.rotas import conta, painel, publico
from rastro.seguranca import LimiteTentativas
from rastro.sincronizacao import laco_sincronizacao

ESTATICOS = Path(__file__).resolve().parent / "static"
log = logging.getLogger(__name__)


def criar_app(cfg: Config | None = None, banco: Banco | None = None) -> FastAPI:
    cfg = cfg or carregar()
    banco = banco or Banco(cfg.url_banco)
    banco.criar_tabelas()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        tarefa = None
        if cfg.sincronizar_ativo:
            tarefa = asyncio.create_task(laco_sincronizacao(banco, cfg.meta_versao_api, cfg.sincronizar_minutos))
        yield
        if tarefa:
            tarefa.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarefa

    app = FastAPI(title="Rastro", version=__version__, lifespan=ciclo_de_vida, docs_url=None, redoc_url=None)
    app.state.config = cfg
    app.state.banco = banco
    app.state.limite_login = LimiteTentativas()
    app.state.sincronizando = set()

    @app.middleware("http")
    async def proteger_api(request: Request, chamar):
        # Proteção contra CSRF: o painel manda X-Rastro em toda alteração; outro site não consegue mandar
        # esse cabeçalho sem um CORS que o Rastro nunca libera para /api.
        if (request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS")
                and request.headers.get("x-rastro") != "1"):
            return JSONResponse({"detail": "Requisição recusada."}, status_code=403)
        resposta = await chamar(request)
        if request.url.path.startswith("/api/"):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    app.include_router(publico.rotas)
    app.include_router(conta.rotas)
    app.include_router(painel.rotas)
    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")

    @app.get("/", include_in_schema=False)
    def inicio() -> FileResponse:
        return FileResponse(ESTATICOS / "index.html", headers={"Cache-Control": "no-cache"})

    return app
