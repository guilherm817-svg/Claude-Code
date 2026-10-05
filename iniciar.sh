#!/usr/bin/env bash
# Abre o Analisador de Aulas. Na primeira vez, prepara o ambiente Python (leva alguns minutos).
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Preparando o ambiente pela primeira vez. Isso leva alguns minutos..."
  PY=$(command -v python3.12 || command -v python3 || command -v python) || {
    echo "Não encontrei o Python. Instale o Python 3.10 ou mais novo: https://www.python.org/downloads/"
    exit 1
  }
  "$PY" -m venv .venv
fi

.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
echo "Abrindo o app no navegador. Pressione Ctrl+C aqui para encerrar."
exec .venv/bin/python -m streamlit run app.py
