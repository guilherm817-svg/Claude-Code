#!/usr/bin/env bash
# Abre o Rastro no computador. Na primeira vez, prepara o ambiente Python (leva um minuto).
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Preparando o ambiente pela primeira vez..."
  PY=$(command -v python3.12 || command -v python3 || command -v python) || {
    echo "Não encontrei o Python. Instale o Python 3.10 ou mais novo: https://www.python.org/downloads/"
    exit 1
  }
  "$PY" -m venv .venv
fi

.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
echo "Rastro rodando em http://localhost:8000  (Ctrl+C para encerrar)"
exec .venv/bin/python -m rastro
