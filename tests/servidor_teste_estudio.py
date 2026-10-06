"""Sobe o Estúdio para os testes de tela com um Whisper falso no lugar do modelo de verdade.

    python tests/servidor_teste_estudio.py --porta 8700

A pasta dos projetos vem do ESTUDIO_PASTA_DADOS, como no Estúdio de verdade.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from estudio import transcricao  # noqa: E402
from estudio.servidor import criar_app  # noqa: E402
from whisper_falso import WhisperFalso  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--porta", type=int, required=True)
    parser.add_argument("--frase", default="Isso muda tudo agora")
    args = parser.parse_args()
    falso = WhisperFalso(args.frase)
    transcricao._carregar_modelo = lambda modelo, dispositivo: falso
    uvicorn.run(criar_app(), host="127.0.0.1", port=args.porta, log_level="warning")
