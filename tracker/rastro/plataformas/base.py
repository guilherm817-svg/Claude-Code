"""Formato comum de venda e utilitários para os adaptadores de cada plataforma."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

CAMPOS_RASTREIO = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "src", "sck", "xcod")


class EventoIgnorado(Exception):
    """O webhook é válido, mas não representa uma venda (carrinho abandonado, assinatura cancelada...)."""


class PayloadInvalido(Exception):
    """Faltam campos obrigatórios ou o formato não é o esperado."""


@dataclass
class VendaNormalizada:
    id_externo: str
    status: str
    metodo_pagamento: str
    valor_bruto_cent: int
    valor_liquido_cent: int
    criada_em: datetime
    aprovada_em: datetime | None = None
    moeda: str = "BRL"
    produto_id: str | None = None
    produto_nome: str | None = None
    cliente_nome: str | None = None
    cliente_email: str | None = None
    cliente_telefone: str | None = None
    cliente_documento: str | None = None
    cliente_ip: str | None = None
    rastreio: dict[str, str | None] = field(default_factory=dict)


def texto(valor: Any, limite: int = 300) -> str | None:
    if valor is None:
        return None
    valor = str(valor).strip()
    if not valor or valor.lower() in {"null", "none", "undefined"}:
        return None
    return valor[:limite]


def centavos(valor: Any) -> int:
    """Converte reais (97, "97.00", "97,00") em centavos."""
    if valor is None or valor == "":
        return 0
    if isinstance(valor, str):
        valor = valor.strip().replace("R$", "").strip()
        if "," in valor:
            valor = valor.replace(".", "").replace(",", ".")
    try:
        return int((Decimal(str(valor)) * 100).quantize(Decimal("1")))
    except InvalidOperation:
        return 0


def inteiro(valor: Any) -> int:
    if valor is None or valor == "":
        return 0
    try:
        return int(Decimal(str(valor)))
    except InvalidOperation:
        return 0


def data_hora(valor: Any, fuso_padrao: str = "America/Sao_Paulo") -> datetime | None:
    """Aceita epoch (s ou ms), ISO 8601 e "AAAA-MM-DD HH:MM[:SS]". Datas sem fuso usam fuso_padrao."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)) or (isinstance(valor, str) and re.fullmatch(r"\d{10,13}", valor.strip())):
        numero = float(valor)
        if numero > 1e12:
            numero /= 1000
        return datetime.fromtimestamp(numero, tz=timezone.utc)
    texto_data = str(valor).strip().replace("Z", "+00:00")
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}.*", texto_data):  # 05/10/2026 14:30
        dia, resto = texto_data[:10], texto_data[10:]
        d, m, a = dia.split("/")
        texto_data = f"{a}-{m}-{d}{resto}"
    try:
        resultado = datetime.fromisoformat(texto_data)
    except ValueError:
        return None
    if resultado.tzinfo is None:
        resultado = resultado.replace(tzinfo=ZoneInfo(fuso_padrao))
    return resultado.astimezone(timezone.utc)


def so_digitos(valor: Any) -> str | None:
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", str(valor))
    return digitos or None


def pegar(dados: Any, *caminho: str, padrao: Any = None) -> Any:
    """pegar(d, "data", "buyer", "email") sem quebrar quando algum nível falta."""
    atual = dados
    for chave in caminho:
        if not isinstance(atual, dict):
            return padrao
        atual = atual.get(chave)
        if atual is None:
            return padrao
    return atual
