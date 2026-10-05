"""Envia as vendas aprovadas para a API de Conversões do Meta (evento Purchase, dados do cliente com SHA-256)."""

import hashlib
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rastro.meta import ClienteMeta, ErroMeta
from rastro.modelos import Conta, Venda, Visita, agora

log = logging.getLogger(__name__)
LIMITE_IDADE = timedelta(days=7)  # o Meta recusa eventos com mais de 7 dias


def _sha256(valor: str | None) -> str | None:
    if not valor:
        return None
    return hashlib.sha256(valor.strip().lower().encode()).hexdigest()


def _telefone(telefone: str | None) -> str | None:
    if not telefone:
        return None
    if len(telefone) in (10, 11):  # DDD + número, sem o código do Brasil
        telefone = "55" + telefone
    return telefone


def montar_evento(venda: Venda, visita: Visita | None) -> dict[str, Any]:
    partes_nome = (venda.cliente_nome or "").split()
    user_data: dict[str, Any] = {
        "em": [_sha256(venda.cliente_email)],
        "ph": [_sha256(_telefone(venda.cliente_telefone))],
        "fn": [_sha256(partes_nome[0])] if partes_nome else None,
        "ln": [_sha256(partes_nome[-1])] if len(partes_nome) > 1 else None,
        "country": [_sha256("br")] if venda.moeda == "BRL" else None,
        "external_id": [_sha256(visita.visitante_id if visita and visita.visitante_id else venda.cliente_email)],
        "client_ip_address": (visita.ip if visita else None) or venda.cliente_ip,
        "client_user_agent": visita.user_agent if visita else None,
        "fbc": visita.fbc if visita else None,
        "fbp": visita.fbp if visita else None,
    }
    user_data = {chave: valor for chave, valor in user_data.items() if valor and valor != [None]}
    evento: dict[str, Any] = {
        "event_name": "Purchase",
        "event_time": int((venda.aprovada_em or venda.criada_em).timestamp()),
        "event_id": f"rastro-{venda.plataforma}-{venda.id_externo}",
        # "website" exige o user agent do navegador, que só existe quando a venda veio de uma visita rastreada.
        "action_source": "website" if user_data.get("client_user_agent") else "system_generated",
        "user_data": user_data,
        "custom_data": {
            "currency": venda.moeda,
            "value": round(venda.valor_bruto_cent / 100, 2),
            "order_id": venda.id_externo,
            "content_type": "product",
            "content_name": venda.produto_nome,
            "content_ids": [venda.produto_nome or venda.id_externo],
        },
    }
    if visita and visita.url_entrada:
        evento["event_source_url"] = visita.url_entrada
    return evento


def enviar_venda(conta: Conta, venda: Venda, visita: Visita | None, cliente: ClienteMeta) -> None:
    """Envia uma venda e anota o resultado nela (não acessa o banco)."""
    if (venda.aprovada_em or venda.criada_em) < agora() - LIMITE_IDADE:
        venda.capi_situacao, venda.capi_erro = "erro", "Venda com mais de 7 dias: o Meta não aceita mais o evento."
        return
    try:
        cliente.enviar_eventos(conta.capi_pixel_id, [montar_evento(venda, visita)], conta.capi_codigo_teste)
    except (ErroMeta, OSError) as erro:
        venda.capi_situacao, venda.capi_erro = "erro", str(erro)[:1000]
        return
    venda.capi_situacao, venda.capi_erro, venda.capi_enviado_em = "enviado", None, agora()


def enviar_pendentes(sessao: Session, conta: Conta, versao_api: str, cliente: ClienteMeta | None = None,
                     limite: int = 200) -> int:
    """Envia as vendas com envio pendente da conta. Faz commit a cada venda. Devolve quantas processou."""
    if not (conta.capi_ativo and conta.capi_pixel_id and conta.capi_token):
        return 0
    vendas = sessao.scalars(select(Venda).where(Venda.conta_id == conta.id, Venda.capi_situacao == "pendente")
                            .order_by(Venda.id).limit(limite)).all()
    if not vendas:
        return 0
    ids_visitas = {venda.visita_id for venda in vendas if venda.visita_id}
    visitas = {v.id: v for v in sessao.scalars(select(Visita).where(Visita.id.in_(ids_visitas)))} if ids_visitas else {}
    sessao.commit()  # nenhuma transação aberta durante as chamadas ao Meta
    cliente = cliente or ClienteMeta(conta.capi_token, versao_api)
    for venda in vendas:
        enviar_venda(conta, venda, visitas.get(venda.visita_id), cliente)
        sessao.commit()
    return len(vendas)
