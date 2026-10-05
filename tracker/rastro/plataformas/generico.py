"""Formato próprio do Rastro, para checkouts sem adaptador (via Zapier, n8n, Make ou código próprio).

{
  "id": "pedido-123",                 obrigatório, único por venda
  "status": "aprovada",               aprovada, pendente, recusada, cancelada, reembolsada ou chargeback
  "valor": 197.00,                    o que o cliente pagou (reais)
  "valor_liquido": 180.50,            o que fica para você (opcional; padrão = valor)
  "metodo_pagamento": "pix",          pix, cartao, boleto (opcional)
  "data": "2026-10-05T14:30:00-03:00",
  "data_aprovacao": "...",            (opcional)
  "moeda": "BRL",                     (opcional)
  "produto": {"id": "...", "nome": "..."},
  "cliente": {"nome": "...", "email": "...", "telefone": "...", "documento": "...", "ip": "..."},
  "rastreio": {"utm_source": "...", "utm_campaign": "...", "sck": "..."}
}
"""

import hashlib
import hmac
from typing import Any

from rastro.modelos import MetodoPagamento, StatusVenda
from rastro.plataformas.base import (
    CAMPOS_RASTREIO, EventoIgnorado, PayloadInvalido, VendaNormalizada, centavos, data_hora, so_digitos, texto,
)

NOME = "Genérico (API / Zapier / n8n)"

SINONIMOS_STATUS = {
    "aprovado": StatusVenda.APROVADA, "pago": StatusVenda.APROVADA, "paga": StatusVenda.APROVADA,
    "paid": StatusVenda.APROVADA, "approved": StatusVenda.APROVADA,
    "pending": StatusVenda.PENDENTE, "aguardando": StatusVenda.PENDENTE, "aguardando_pagamento": StatusVenda.PENDENTE,
    "recusado": StatusVenda.RECUSADA, "refused": StatusVenda.RECUSADA,
    "cancelado": StatusVenda.CANCELADA, "canceled": StatusVenda.CANCELADA, "expirada": StatusVenda.CANCELADA,
    "reembolsado": StatusVenda.REEMBOLSADA, "refunded": StatusVenda.REEMBOLSADA,
}

SINONIMOS_METODO = {"cartão": MetodoPagamento.CARTAO, "credit_card": MetodoPagamento.CARTAO,
                    "card": MetodoPagamento.CARTAO, "billet": MetodoPagamento.BOLETO}


def verificar(corpo: bytes, cabecalhos: dict[str, str], consulta: dict[str, str], segredo: str) -> bool:
    """Aceita o segredo puro em X-Rastro-Token ou o HMAC-SHA256 do corpo em X-Rastro-Assinatura."""
    token = cabecalhos.get("x-rastro-token", "")
    if token and hmac.compare_digest(token, segredo):
        return True
    assinatura = cabecalhos.get("x-rastro-assinatura", "").removeprefix("sha256=")
    esperado = hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return bool(assinatura) and hmac.compare_digest(assinatura, esperado)


def interpretar(dados: Any, papel: str = "produtor", fuso: str = "America/Sao_Paulo") -> VendaNormalizada:
    if not isinstance(dados, dict):
        raise PayloadInvalido("O corpo precisa ser um objeto JSON.")
    if dados.get("teste") is True:
        raise EventoIgnorado("Chamada de teste recebida com sucesso.")
    id_externo = texto(dados.get("id"), 120)
    if not id_externo:
        raise PayloadInvalido("Falta o campo 'id'.")
    status_bruto = str(dados.get("status") or "").strip().lower()
    status = status_bruto if status_bruto in StatusVenda.TODOS else SINONIMOS_STATUS.get(status_bruto)
    if status is None:
        raise PayloadInvalido(f"Status '{dados.get('status')}' inválido. Use: {', '.join(StatusVenda.TODOS)}.")
    metodo_bruto = str(dados.get("metodo_pagamento") or "").strip().lower()
    metodo = metodo_bruto if metodo_bruto in MetodoPagamento.TODOS else SINONIMOS_METODO.get(metodo_bruto,
                                                                                               MetodoPagamento.OUTRO)
    criada = data_hora(dados.get("data"), fuso)
    if criada is None:
        raise PayloadInvalido("Falta o campo 'data' (ISO 8601, ex.: 2026-10-05T14:30:00-03:00).")
    bruto = centavos(dados.get("valor"))
    liquido = centavos(dados.get("valor_liquido")) if dados.get("valor_liquido") not in (None, "") else bruto
    aprovada = data_hora(dados.get("data_aprovacao"), fuso)
    if status == StatusVenda.APROVADA and aprovada is None:
        aprovada = criada
    produto = dados.get("produto") or {}
    cliente = dados.get("cliente") or {}
    rastreio = dados.get("rastreio") or {}
    return VendaNormalizada(
        id_externo=id_externo,
        status=status,
        metodo_pagamento=metodo,
        moeda=(texto(dados.get("moeda"), 3) or "BRL").upper(),
        valor_bruto_cent=bruto,
        valor_liquido_cent=liquido,
        criada_em=criada,
        aprovada_em=aprovada,
        produto_id=texto(produto.get("id") or produto.get("nome"), 120),
        produto_nome=texto(produto.get("nome")),
        cliente_nome=texto(cliente.get("nome"), 200),
        cliente_email=texto(cliente.get("email"), 200),
        cliente_telefone=so_digitos(cliente.get("telefone")),
        cliente_documento=so_digitos(cliente.get("documento")),
        cliente_ip=texto(cliente.get("ip"), 64),
        rastreio={campo: texto(rastreio.get(campo)) for campo in CAMPOS_RASTREIO},
    )
