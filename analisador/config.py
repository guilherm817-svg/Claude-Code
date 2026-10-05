"""Configurações do app, lidas do ambiente ou do arquivo .env na raiz do projeto."""

import os
from pathlib import Path

from dotenv import load_dotenv, set_key

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_ENV = RAIZ / ".env"
load_dotenv(ARQUIVO_ENV)

PASTA_DADOS = Path(os.environ.get("ANALISADOR_PASTA_DADOS") or RAIZ / "biblioteca")
MODELO_CLAUDE = os.environ.get("ANALISADOR_MODELO_CLAUDE", "claude-opus-5-5")
MODELO_WHISPER = os.environ.get("ANALISADOR_MODELO_WHISPER", "large-v3-turbo")
IDIOMA = os.environ.get("ANALISADOR_IDIOMA", "pt")
DISPOSITIVO = os.environ.get("ANALISADOR_DISPOSITIVO", "auto")

EXTENSOES_MIDIA = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".ts", ".mpg", ".mpeg",
    ".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".flac", ".wma",
}


def credenciais_claude() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def salvar_chave_api(chave: str) -> None:
    """Grava a chave no .env (que fica só no seu computador) e já a ativa neste processo."""
    chave = chave.strip()
    ARQUIVO_ENV.touch(exist_ok=True)
    set_key(str(ARQUIVO_ENV), "ANTHROPIC_API_KEY", chave, quote_mode="never")
    os.environ["ANTHROPIC_API_KEY"] = chave
