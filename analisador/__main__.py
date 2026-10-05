"""Linha de comando para processar um curso inteiro sem abrir a interface.

    python -m analisador processar "C:\\Cursos\\Meu Curso"
    python -m analisador processar aula1.mp4 aula2.mp4 --curso "Meu Curso"
    python -m analisador listar
"""

import argparse
import logging
import sys
from pathlib import Path

from . import config
from .biblioteca import Biblioteca, Etapa, formatar_tempo, listar_midias
from .pipeline import processar_aula
from .transcricao import MODELOS_WHISPER


def _processar(args) -> int:
    biblioteca = Biblioteca()
    arquivos: list[tuple[Path, str | None]] = []
    for caminho in map(Path, args.caminhos):
        if caminho.is_dir():
            arquivos += [(p, args.curso or caminho.name) for p in listar_midias(caminho)]
        elif caminho.is_file():
            arquivos.append((caminho, args.curso))
        else:
            print(f"Não encontrado: {caminho}", file=sys.stderr)
    if not arquivos:
        print("Nenhum vídeo ou áudio encontrado.", file=sys.stderr)
        return 1
    if not config.credenciais_claude():
        print("Aviso: ANTHROPIC_API_KEY não configurada; as aulas serão só transcritas.\n")

    falhas = 0
    for n, (arquivo, curso) in enumerate(arquivos, 1):
        aula = biblioteca.adicionar(arquivo, curso)
        print(f"[{n}/{len(arquivos)}] {aula.titulo}")
        if aula.status()["etapa"] == Etapa.PRONTA and not args.refazer_analise:
            print("  já processada\n")
            continue

        def relatar(etapa, progresso, mensagem):
            if etapa in (Etapa.TRANSCREVENDO, Etapa.ANALISANDO):
                print(f"\r  {mensagem:<70}", end="", flush=True)

        processar_aula(aula, modelo_whisper=args.modelo_whisper, idioma=args.idioma,
                       refazer_analise=args.refazer_analise, relatar=relatar)
        status = aula.status()
        falhas += status["etapa"] == Etapa.ERRO
        print(f"\r  {status['etapa']}: {status['mensagem'] or 'ok'}".ljust(74) + "\n")
    return 1 if falhas else 0


def _listar(_args) -> int:
    for aula in Biblioteca().aulas():
        status = aula.status()["etapa"]
        print(f"{status:<13} {formatar_tempo(aula.duracao or 0)}  {aula.curso} / {aula.titulo}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m analisador", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("processar", help="transcreve e analisa arquivos ou pastas de aulas")
    p.add_argument("caminhos", nargs="+", help="arquivos de vídeo/áudio ou pastas do curso")
    p.add_argument("--curso", help="nome do curso (padrão: nome da pasta)")
    p.add_argument("--modelo-whisper", default=config.MODELO_WHISPER, choices=list(MODELOS_WHISPER))
    p.add_argument("--idioma", default=config.IDIOMA, help="código do idioma (pt, en, es...) ou auto")
    p.add_argument("--refazer-analise", action="store_true", help="gera a análise de novo mesmo se já existir")
    p.set_defaults(func=_processar)

    sub.add_parser("listar", help="mostra as aulas da biblioteca").set_defaults(func=_listar)

    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
