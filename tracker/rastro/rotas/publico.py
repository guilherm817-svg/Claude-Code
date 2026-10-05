"""Rotas abertas: script do pixel, coleta de visitas e webhooks das plataformas."""

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from rastro.atribuicao import CAMPOS_UTM, ID_VISITA, niveis_meta
from rastro.capi import enviar_pendentes
from rastro.db import repetir_em_conflito
from rastro.modelos import Conta, Integracao, Visita, agora
from rastro.plataformas import PLATAFORMAS
from rastro.vendas import receber

log = logging.getLogger(__name__)
rotas = APIRouter()
PIXEL = Path(__file__).resolve().parent.parent / "static" / "pixel.js"
LIMITE_CORPO = 64 * 1024


def ip_cliente(request: Request) -> str | None:
    if request.app.state.config.confiar_proxy:
        encaminhado = request.headers.get("x-forwarded-for")
        if encaminhado:
            return encaminhado.split(",")[0].strip()[:64]
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()[:64]
    return request.client.host if request.client else None


def _texto(valor, limite: int = 300) -> str | None:
    if valor is None:
        return None
    valor = str(valor).strip()
    return valor[:limite] or None


@rotas.get("/p.js", include_in_schema=False)
def script_pixel() -> Response:
    return Response(PIXEL.read_text(encoding="utf-8"), media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"})


@rotas.post("/c", include_in_schema=False)
async def coletar(request: Request) -> Response:
    """Recebe os eventos do pixel (sendBeacon, text/plain). Sempre responde 204 para não gerar erro na página."""
    sem_conteudo = Response(status_code=204, headers={"Access-Control-Allow-Origin": "*"})
    corpo = await request.body()
    if len(corpo) > LIMITE_CORPO:
        return sem_conteudo
    try:
        dados = json.loads(corpo)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return sem_conteudo
    if not isinstance(dados, dict):
        return sem_conteudo
    id_visita = str(dados.get("c") or "").lower()
    if not ID_VISITA.match(id_visita) or not isinstance(dados.get("k"), str):
        return sem_conteudo
    # O banco é síncrono: grava numa thread para não travar o servidor com muitas visitas ao mesmo tempo.
    try:
        await run_in_threadpool(repetir_em_conflito, _gravar_visita, request, dados, id_visita)
    except Exception:  # noqa: BLE001 — o pixel nunca pode quebrar a página do cliente
        log.exception("Falha ao gravar visita %s", id_visita)
    return sem_conteudo


def _gravar_visita(request: Request, dados: dict, id_visita: str) -> None:
    with request.app.state.banco.sessao() as sessao:
        conta = sessao.scalar(select(Conta).where(Conta.chave_publica == dados["k"]))
        if conta is None:
            return
        visita = sessao.get(Visita, id_visita)
        if visita is not None and visita.conta_id != conta.id:
            return
        if visita is None:
            utms = dados.get("u") if isinstance(dados.get("u"), dict) else {}
            momento = agora()
            visita = Visita(id=id_visita, conta_id=conta.id, criado_em=momento,
                            dia=momento.astimezone(ZoneInfo(conta.fuso)).date(),
                            url_entrada=_texto(dados.get("url"), 1000), referrer=_texto(dados.get("ref"), 1000),
                            paginas=0, checkouts=0)
            for campo in CAMPOS_UTM:
                setattr(visita, campo, _texto(utms.get(campo)))
            for campo in ("fbclid", "gclid", "ttclid"):
                setattr(visita, campo, _texto(utms.get(campo), 500))
            for nivel, (_, id_meta) in niveis_meta({c: getattr(visita, c) for c in CAMPOS_UTM}).items():
                setattr(visita, f"{nivel}_id", id_meta)
            sessao.add(visita)
        visita.visitante_id = visita.visitante_id or _texto(dados.get("v"), 40)
        visita.fbp = visita.fbp or _texto(dados.get("fbp"), 200)
        visita.fbc = visita.fbc or _texto(dados.get("fbc"), 600)
        visita.ip = ip_cliente(request) or visita.ip
        visita.user_agent = _texto(request.headers.get("user-agent"), 500) or visita.user_agent
        visita.atualizado_em = agora()
        # Incremento feito no próprio SQL (checkouts = checkouts + 1): eventos simultâneos não se perdem.
        if dados.get("t") == "checkout":
            visita.checkouts = 1 if visita in sessao.new else Visita.checkouts + 1
        else:
            visita.paginas = 1 if visita in sessao.new else Visita.paginas + 1


def _enviar_capi(request: Request, conta_id: int) -> None:
    banco, cfg = request.app.state.banco, request.app.state.config
    try:
        with banco.sessao() as sessao:
            enviar_pendentes(sessao, sessao.get(Conta, conta_id), cfg.meta_versao_api)
    except Exception:  # noqa: BLE001 — a sincronização periódica tenta de novo
        log.exception("Falha ao enviar eventos para a API de Conversões")


@rotas.post("/webhook/{token}", include_in_schema=False)
async def webhook(token: str, request: Request, tarefas: BackgroundTasks) -> JSONResponse:
    corpo = await request.body()
    if len(corpo) > 2 * 1024 * 1024:
        return JSONResponse({"ok": False, "erro": "Corpo grande demais."}, status_code=413)
    return await run_in_threadpool(repetir_em_conflito, _processar_webhook, token, request, corpo, tarefas)


def _processar_webhook(token: str, request: Request, corpo: bytes, tarefas: BackgroundTasks) -> JSONResponse:
    with request.app.state.banco.sessao() as sessao:
        integracao = sessao.scalar(select(Integracao).where(Integracao.token == token))
        if integracao is None or not integracao.ativo:
            return JSONResponse({"ok": False, "erro": "Webhook não encontrado ou desativado."}, status_code=404)
        if integracao.segredo:
            cabecalhos = {chave.lower(): valor for chave, valor in request.headers.items()}
            modulo = PLATAFORMAS[integracao.plataforma]
            if not modulo.verificar(corpo, cabecalhos, dict(request.query_params), integracao.segredo):
                return JSONResponse({"ok": False, "erro": "Assinatura ou token do webhook inválido."},
                                    status_code=401)
        registro, venda = receber(sessao, integracao, corpo)
        resposta = {"ok": registro.situacao != "erro", "situacao": registro.situacao, "mensagem": registro.mensagem}
        if venda is not None and venda.capi_situacao == "pendente":
            tarefas.add_task(_enviar_capi, request, integracao.conta_id)
    # 200 mesmo com erro de interpretação: o webhook fica no log e pode ser reprocessado depois do ajuste,
    # sem a plataforma ficar reenviando.
    return JSONResponse(resposta)


@rotas.get("/saude", include_in_schema=False)
def saude() -> dict:
    return {"ok": True, "hora": datetime.now().isoformat(timespec="seconds")}
