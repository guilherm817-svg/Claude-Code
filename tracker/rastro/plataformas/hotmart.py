"""Webhook (postback) da Hotmart, versão 2.0.0.

A Hotmart não repassa utm_* ao webhook, só src, sck e xcod: por isso o pixel coloca o id da visita no sck.
"""

import hmac
from typing import Any

from rastro.modelos import MetodoPagamento, StatusVenda
from rastro.plataformas.base import (
    EventoIgnorado, PayloadInvalido, VendaNormalizada, centavos, data_hora, pegar, so_digitos, texto,
)

NOME = "Hotmart"

STATUS_POR_EVENTO = {
    "PURCHASE_APPROVED": StatusVenda.APROVADA,
    "PURCHASE_COMPLETE": StatusVenda.APROVADA,
    "PURCHASE_BILLET_PRINTED": StatusVenda.PENDENTE,
    "PURCHASE_DELAYED": StatusVenda.PENDENTE,
    "PURCHASE_CANCELED": StatusVenda.CANCELADA,
    "PURCHASE_EXPIRED": StatusVenda.CANCELADA,
    "PURCHASE_REFUNDED": StatusVenda.REEMBOLSADA,
    "PURCHASE_CHARGEBACK": StatusVenda.CHARGEBACK,
}

METODOS = {
    "PIX": MetodoPagamento.PIX,
    "BILLET": MetodoPagamento.BOLETO,
    "CREDIT_CARD": MetodoPagamento.CARTAO,
    "DEBIT_CARD": MetodoPagamento.CARTAO,
    "HOTCARD": MetodoPagamento.CARTAO,
    "MULTIPLE_PAYMENTS": MetodoPagamento.CARTAO,
}

ORIGEM_COMISSAO = {"produtor": "PRODUCER", "coprodutor": "COPRODUCER", "afiliado": "AFFILIATE"}


def verificar(corpo: bytes, cabecalhos: dict[str, str], consulta: dict[str, str], segredo: str) -> bool:
    recebido = cabecalhos.get("x-hotmart-hottok", "")
    return bool(recebido) and hmac.compare_digest(recebido, segredo)


def interpretar(dados: Any, papel: str = "produtor", fuso: str = "America/Sao_Paulo") -> VendaNormalizada:
    if not isinstance(dados, dict) or "event" not in dados:
        raise PayloadInvalido("Não parece um webhook da Hotmart 2.0.0 (falta o campo 'event').")
    evento = dados["event"]
    if evento not in STATUS_POR_EVENTO:
        raise EventoIgnorado(f"Evento {evento} não é uma venda.")
    compra = pegar(dados, "data", "purchase", padrao={})
    transacao = texto(compra.get("transaction"), 120)
    if not transacao:
        raise PayloadInvalido("Webhook da Hotmart sem data.purchase.transaction.")

    status = STATUS_POR_EVENTO[evento]
    metodo = METODOS.get(str(pegar(compra, "payment", "type", padrao="")).upper(), MetodoPagamento.OUTRO)
    if evento == "PURCHASE_CANCELED" and metodo == MetodoPagamento.CARTAO:
        status = StatusVenda.RECUSADA  # cartão recusado chega como "cancelada"

    bruto = centavos(pegar(compra, "price", "value"))
    origem = ORIGEM_COMISSAO.get(papel, "PRODUCER")
    comissoes = [c for c in pegar(dados, "data", "commissions", padrao=[]) or [] if isinstance(c, dict)]
    liquido = sum(centavos(c.get("value")) for c in comissoes if c.get("source") == origem)
    if not liquido and papel == "produtor":
        liquido = bruto - sum(centavos(c.get("value")) for c in comissoes if c.get("source") != "PRODUCER")

    comprador = pegar(dados, "data", "buyer", padrao={})
    telefone = comprador.get("checkout_phone") or comprador.get("phone")
    codigo_pais = so_digitos(comprador.get("checkout_phone_code"))
    if telefone and codigo_pais and not str(telefone).startswith(codigo_pais):
        telefone = f"{codigo_pais}{telefone}"
    origem_trafego = compra.get("origin") or {}
    produto = pegar(dados, "data", "product", padrao={})

    criada = data_hora(compra.get("order_date"), fuso) or data_hora(dados.get("creation_date"), fuso)
    if criada is None:
        raise PayloadInvalido("Webhook da Hotmart sem data da compra.")
    return VendaNormalizada(
        id_externo=transacao,
        status=status,
        metodo_pagamento=metodo,
        moeda=(texto(pegar(compra, "price", "currency_value"), 3) or "BRL").upper(),
        valor_bruto_cent=bruto,
        valor_liquido_cent=max(liquido, 0),
        criada_em=criada,
        aprovada_em=data_hora(compra.get("approved_date"), fuso),
        produto_id=texto(produto.get("id"), 120),
        produto_nome=texto(produto.get("name")),
        cliente_nome=texto(comprador.get("name"), 200),
        cliente_email=texto(comprador.get("email"), 200),
        cliente_telefone=so_digitos(telefone),
        cliente_documento=so_digitos(comprador.get("document")),
        cliente_ip=None,
        rastreio={
            "src": texto(origem_trafego.get("src")),
            "sck": texto(origem_trafego.get("sck")),
            "xcod": texto(origem_trafego.get("xcod")),
        },
    )
