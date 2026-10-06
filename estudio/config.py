"""Configurações do Estúdio de Reels, lidas do ambiente ou do arquivo .env na raiz do projeto."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

PASTA_DADOS = Path(os.environ.get("ESTUDIO_PASTA_DADOS") or RAIZ / "meus-reels")
PORTA = int(os.environ.get("ESTUDIO_PORTA") or 8502)

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
