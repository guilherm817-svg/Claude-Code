"""Configurações do Estúdio de Reels, lidas do ambiente ou do arquivo .env na raiz do projeto."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv, set_key

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_ENV = RAIZ / ".env"
load_dotenv(ARQUIVO_ENV)

PASTA_DADOS = Path(os.environ.get("ESTUDIO_PASTA_DADOS") or RAIZ / "meus-reels")
PORTA = int(os.environ.get("ESTUDIO_PORTA") or 8502)
MODELO_CLAUDE = os.environ.get("ESTUDIO_MODELO_CLAUDE", "claude-opus-5-5")

EXTENSOES_VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}

# Formatos de saída: largura, altura e nome na tela.
FORMATOS = {
    "reels": (1080, 1920, "Reels, Stories e TikTok (9:16)"),
    "feed": (1080, 1350, "Feed do Instagram (4:5)"),
    "quadrado": (1080, 1080, "Quadrado (1:1)"),
    "youtube": (1920, 1080, "YouTube (16:9)"),
}

VOLUME_ALVO = -14.0  # LUFS: volume de referência das redes sociais
PICO_MAXIMO = -1.0  # dBTP: teto para o som não distorcer depois de subir o volume
FOLGA_ANTES_DA_FALA = 0.12  # segundos mantidos antes da primeira palavra, para não comer o começo dela
FOLGA_DEPOIS_DA_FALA = 0.25  # segundos mantidos depois da última palavra, para o fim não soar cortado

# Legendas automáticas: o mesmo Whisper do Analisador, assim o modelo já baixado é aproveitado.
MODELO_WHISPER = os.environ.get("ESTUDIO_MODELO_WHISPER") or "large-v3-turbo"
DISPOSITIVO = os.environ.get("ESTUDIO_DISPOSITIVO") or "auto"  # auto, cpu ou cuda


def credenciais_claude() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def salvar_chave_api(chave: str) -> None:
    """Grava a chave no .env (que fica só no seu computador, o mesmo do Analisador) e já a ativa neste processo."""
    chave = chave.strip() if isinstance(chave, str) else ""
    # Só letras, números, - e _: a chave vai numa linha do .env e não pode carregar quebra de linha nem aspas.
    if not re.fullmatch(r"sk-ant-[A-Za-z0-9_-]{10,400}", chave):
        raise ValueError("Essa não parece uma chave da API do Claude. A chave começa com sk-ant- e é criada em "
                         "console.anthropic.com, em API Keys.")
    ARQUIVO_ENV.touch(exist_ok=True)
    set_key(str(ARQUIVO_ENV), "ANTHROPIC_API_KEY", chave, quote_mode="never")
    os.environ["ANTHROPIC_API_KEY"] = chave
