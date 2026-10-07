#!/usr/bin/env bash
# Abre o Analisador de Aulas (Mac e Linux). Na primeira vez, prepara o ambiente Python (leva alguns minutos).
set -e
cd "$(dirname "$0")"

# O app precisa do Python 3.10 ou mais novo. O que vem com o Mac (/usr/bin/python3) é o 3.9.
python_serve() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

achar_python() {
  # Instalador do python.org e Homebrew primeiro: no Mac, nem sempre o Terminal já enxerga esses caminhos.
  for caminho in /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 \
                 /opt/homebrew/bin/python3.1[0-9] /usr/local/bin/python3.1[0-9]; do
    [ -x "$caminho" ] && python_serve "$caminho" && ACHADO="$caminho"
  done
  [ -n "$ACHADO" ] && return 0
  for nome in python3.13 python3.12 python3.11 python3.10 python3 python; do
    caminho=$(command -v "$nome" 2>/dev/null) || continue
    # No Mac, rodar o /usr/bin/python3 sem as ferramentas de desenvolvedor abre uma janela pedindo para instalá-las.
    [ "$(uname)" = "Darwin" ] && [ "$caminho" = "/usr/bin/python3" ] && continue
    if python_serve "$caminho"; then ACHADO="$caminho"; return 0; fi
  done
  return 1
}

if [ -x .venv/bin/python ] && ! python_serve .venv/bin/python; then
  echo "O ambiente foi criado com um Python antigo. Vou refazer com um mais novo."
  rm -rf .venv
fi

if [ ! -x .venv/bin/python ]; then
  ACHADO=""
  if ! achar_python; then
    echo "Não encontrei o Python 3.10 ou mais novo (o que vem com o Mac é antigo demais para o app)."
    echo "Instale o Python 3.12 em https://www.python.org/downloads/ e abra o Analisador de novo."
    if [ "$(uname)" = "Darwin" ]; then open "https://www.python.org/downloads/macos/"; fi
    exit 1
  fi
  echo "Preparando o ambiente pela primeira vez com $("$ACHADO" --version). Isso leva alguns minutos..."
  "$ACHADO" -m venv .venv
fi

.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
echo "Abrindo o app no navegador. Pressione Ctrl+C aqui para encerrar."
exec .venv/bin/python -m streamlit run app.py
