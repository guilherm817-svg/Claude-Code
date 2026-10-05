"""Adaptadores de webhook. Para adicionar uma plataforma, crie um módulo com NOME, verificar() e interpretar()."""

from types import ModuleType

from rastro.plataformas import generico, hotmart, kiwify
from rastro.plataformas.base import EventoIgnorado, PayloadInvalido, VendaNormalizada

PLATAFORMAS: dict[str, ModuleType] = {
    "hotmart": hotmart,
    "kiwify": kiwify,
    "generico": generico,
}

__all__ = ["PLATAFORMAS", "EventoIgnorado", "PayloadInvalido", "VendaNormalizada"]
