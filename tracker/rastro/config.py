"""Configurações lidas do ambiente (arquivo .env na pasta do projeto)."""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def _bool(valor: str | None, padrao: bool) -> bool:
    if valor is None or valor.strip() == "":
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _chave_secreta(pasta_dados: Path) -> str:
    """Usa RASTRO_CHAVE_SECRETA, ou gera uma e guarda em dados/chave_secreta (para as sessões sobreviverem a reinícios)."""
    chave = os.getenv("RASTRO_CHAVE_SECRETA", "").strip()
    if chave:
        return chave
    arquivo = pasta_dados / "chave_secreta"
    if arquivo.exists():
        return arquivo.read_text().strip()
    pasta_dados.mkdir(parents=True, exist_ok=True)
    chave = secrets.token_urlsafe(48)
    arquivo.write_text(chave)
    return chave


@dataclass(frozen=True)
class Config:
    pasta_dados: Path
    url_banco: str
    url_publica: str
    chave_secreta: str
    permitir_cadastro: bool
    confiar_proxy: bool
    meta_versao_api: str
    sincronizar_minutos: int
    sincronizar_ativo: bool


def carregar() -> Config:
    pasta = Path(os.getenv("RASTRO_PASTA_DADOS", RAIZ / "dados"))
    if not pasta.is_absolute():
        pasta = RAIZ / pasta
    return Config(
        pasta_dados=pasta,
        url_banco=os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{pasta / 'rastro.db'}",
        url_publica=os.getenv("RASTRO_URL_PUBLICA", "").strip().rstrip("/"),
        chave_secreta=_chave_secreta(pasta),
        permitir_cadastro=_bool(os.getenv("RASTRO_PERMITIR_CADASTRO"), False),
        confiar_proxy=_bool(os.getenv("RASTRO_CONFIAR_PROXY"), True),
        meta_versao_api=os.getenv("RASTRO_META_VERSAO_API", "v25.0").strip(),
        sincronizar_minutos=max(5, int(os.getenv("RASTRO_SINCRONIZAR_MINUTOS", "15"))),
        sincronizar_ativo=_bool(os.getenv("RASTRO_SINCRONIZAR"), True),
    )

