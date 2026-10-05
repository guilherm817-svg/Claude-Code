"""Webhook da Kiwify. Valores em centavos; UTMs, src e sck vêm em TrackingParameters."""

import hashlib
import hmac
from typing import Any

from rastro.modelos import MetodoPagamento, StatusVenda
from rastro.plataformas.base import (
    CAMPOS_RASTREIO, EventoIgnorado, PayloadInvalido, VendaNormalizada, data_hora, inteiro, pegar, so_digitos, texto,
)

NOME = "Kiwify"

STATUS = {
    "paid": StatusVenda.APROVADA,
    "approved": StatusVenda.APROVADA,
    "authorized": StatusVenda.APROVADA,
    "waiting_payment": StatusVenda.PENDENTE,
    "pending": StatusVenda.PENDENTE,
    "processing": StatusVenda.PENDENTE,
    "refused": StatusVenda.RECUSADA,
    "rejected": StatusVenda.RECUSADA,
    "canceled": StatusVenda.CANCELADA,
    "cancelled": StatusVenda.CANCELADA,
    "expired": StatusVenda.CANCELADA,
    "refunded": StatusVenda.REEMBOLSADA,
    "chargedback": StatusVenda.CHARGEBACK,
    "chargeback": StatusVenda.CHARGEBACK,
}

STATUS_POR_EVENTO = {
    "order_approved": StatusVenda.APROVADA,
    "billet_created": StatusVenda.PENDENTE,
    "pix_created": StatusVenda.PENDENTE,
    "order_rejected": StatusVenda.RECUSADA,
    "order_refunded": StatusVenda.REEMBOLSADA,
    "chargeback": StatusVenda.CHARGEBACK,
}

METODOS = {
    "pix": MetodoPagamento.PIX,
    "boleto": MetodoPagamento.BOLETO,
    "credit_card": MetodoPagamento.CARTAO,
    "card": MetodoPagamento.CARTAO,
}


def verificar(corpo: bytes, cabecalhos: dict[str, str], consulta: dict[str, str], segredo: str) -> bool:
    """A Kiwify manda ?signature= com o HMAC-SHA1 do corpo, usando o token do webhook como chave."""
    recebido = consulta.get("signature", "")
    esperado = hmac.new(segredo.encode(), corpo, hashlib.sha1).hexdigest()
    return bool(recebido) and hmac.compare_digest(recebido, esperado)


def interpretar(dados: Any, papel: str = "produtor", fuso: str = "America/Sao_Paulo") -> VendaNormalizada:
    if not isinstance(dados, dict):
        raise PayloadInvalido("Corpo do webhook da Kiwify não é um objeto JSON.")
    evento = str(dados.get("webhook_event_type") or "").lower()
    if evento == "abandoned_cart" or (dados.get("checkout_link") and not dados.get("order_id")):
        raise EventoIgnorado("Carrinho abandonado não é uma venda.")
    pedido = texto(dados.get("order_id"), 120)
    if not pedido:
        raise PayloadInvalido("Webhook da Kiwify sem order_id.")

    status = STATUS.get(str(dados.get("order_status") or "").lower()) or STATUS_POR_EVENTO.get(evento)
    if status is None:
        raise EventoIgnorado(f"Status '{dados.get('order_status')}' / evento '{evento}' não é uma venda.")

    comissoes = dados.get("Commissions") or {}
    bruto = inteiro(comissoes.get("charge_amount")) or inteiro(comissoes.get("product_base_price"))
    liquido = inteiro(comissoes.get("my_commission")) or inteiro(comissoes.get("settlement_amount")) or bruto
    cliente = dados.get("Customer") or {}
    produto = dados.get("Product") or {}
    rastreio = dados.get("TrackingParameters") or {}

    criada = data_hora(dados.get("created_at"), fuso)
    if criada is None:
        raise PayloadInvalido("Webhook da Kiwify sem created_at.")
    aprovada = data_hora(dados.get("approved_date"), fuso)
    if status == StatusVenda.APROVADA and aprovada is None:
        aprovada = data_hora(dados.get("updated_at"), fuso) or criada
    return VendaNormalizada(
        id_externo=pedido,
        status=status,
        metodo_pagamento=METODOS.get(str(dados.get("payment_method") or "").lower(), MetodoPagamento.OUTRO),
        moeda=(texto(comissoes.get("currency") or comissoes.get("product_base_price_currency"), 3) or "BRL").upper(),
        valor_bruto_cent=bruto,
        valor_liquido_cent=liquido,
        criada_em=criada,
        aprovada_em=aprovada,
        produto_id=texto(produto.get("product_id"), 120),
        produto_nome=texto(produto.get("product_name")),
        cliente_nome=texto(cliente.get("full_name") or cliente.get("first_name"), 200),
        cliente_email=texto(cliente.get("email"), 200),
        cliente_telefone=so_digitos(cliente.get("mobile")),
        cliente_documento=so_digitos(cliente.get("CPF") or cliente.get("cnpj")),
        cliente_ip=texto(cliente.get("ip"), 64),
        rastreio={campo: texto(pegar(rastreio, campo)) for campo in CAMPOS_RASTREIO},
    )
