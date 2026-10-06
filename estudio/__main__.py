"""Abre o Estúdio de Reels no navegador.

    python -m estudio
    python -m estudio --sem-navegador --porta 8600
"""

import argparse
import socket
import threading
import webbrowser

import uvicorn

from . import config
from .servidor import criar_app


def porta_livre(inicial: int) -> int:
    for porta in range(inicial, inicial + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", porta))
                return porta
            except OSError:
                continue
    raise SystemExit(f"Nenhuma porta livre entre {inicial} e {inicial + 19}. Feche outros Estúdios abertos.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m estudio", description="Abre o Estúdio de Reels.")
    parser.add_argument("--porta", type=int, default=config.PORTA)
    parser.add_argument("--sem-navegador", action="store_true", help="não abre o navegador sozinho")
    args = parser.parse_args()

    porta = porta_livre(args.porta)
    endereco = f"http://127.0.0.1:{porta}"
    print(f"Estúdio de Reels aberto em {endereco}")
    print("Deixe esta janela aberta enquanto usa; feche-a para encerrar.")
    if not args.sem_navegador:
        threading.Timer(1.0, webbrowser.open, args=(endereco,)).start()
    uvicorn.run(criar_app(), host="127.0.0.1", port=porta, log_level="warning")


if __name__ == "__main__":
    main()
