#!/usr/bin/env bash
# Abre o Estúdio de Reels no Mac ou no Linux. Na primeira vez, prepara o ambiente Python (leva alguns minutos).
# No Mac, o jeito mais fácil é dar dois cliques em "Abrir Estúdio.command", que chama este arquivo.
set -e
cd "$(dirname "$0")"

# O app precisa do Python 3.10 a 3.14 (o recomendado é o 3.13). O que vem com o Mac (/usr/bin/python3) é o 3.9,
# e um Python recém-lançado ainda não tem as bibliotecas da transcrição (ctranslate2, onnxruntime) prontas para ele.
python_serve() {
  "$1" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)' 2>/dev/null
}

python_novo_demais() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] > (3, 14) else 1)' 2>/dev/null
}

achar_python() {
  # Na ordem de preferência. O instalador do python.org e o Homebrew vêm antes do PATH porque, no Mac, nem sempre
  # o Terminal já enxerga esses caminhos.
  for versao in 3.13 3.12 3.14 3.11 3.10; do
    for caminho in "/Library/Frameworks/Python.framework/Versions/$versao/bin/python3" \
                   "/opt/homebrew/bin/python$versao" "/usr/local/bin/python$versao" \
                   "$(command -v "python$versao" 2>/dev/null)"; do
      if [ -n "$caminho" ] && [ -x "$caminho" ] && python_serve "$caminho"; then ACHADO="$caminho"; return 0; fi
    done
  done
  for nome in python3 python; do
    caminho=$(command -v "$nome" 2>/dev/null) || continue
    # No Mac, rodar o /usr/bin/python3 sem as ferramentas de desenvolvedor abre uma janela pedindo para instalá-las.
    [ "$(uname)" = "Darwin" ] && [ "$caminho" = "/usr/bin/python3" ] && continue
    if python_serve "$caminho"; then ACHADO="$caminho"; return 0; fi
    python_novo_demais "$caminho" && NOVO_DEMAIS="$("$caminho" --version 2>&1)"
  done
  return 1
}

if [ -x .venv/bin/python ] && ! python_serve .venv/bin/python; then
  echo "O ambiente foi criado com um Python que o app não aceita. Vou refazer com outro."
  rm -rf .venv
fi

if [ ! -x .venv/bin/python ]; then
  ACHADO=""
  NOVO_DEMAIS=""
  if ! achar_python; then
    if [ -n "$NOVO_DEMAIS" ]; then
      echo "Encontrei o $NOVO_DEMAIS, que é novo demais: as bibliotecas da transcrição ainda não saíram para ele."
    else
      echo "Não encontrei o Python 3.10 ou mais novo (o que vem com o Mac é antigo demais para o app)."
    fi
    echo "Instale o Python 3.13 em https://www.python.org/downloads/ (procure na lista \"Python 3.13\", não o"
    echo "botão da versão mais nova) e abra de novo. Pode deixar o outro Python instalado."
    if [ "$(uname)" = "Darwin" ]; then open "https://www.python.org/downloads/macos/"; fi
    exit 1
  fi
  echo "Preparando o ambiente pela primeira vez com $("$ACHADO" --version 2>&1). Isso leva alguns minutos..."
  "$ACHADO" -m venv .venv
fi

if ! .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt; then
  echo
  echo "Falha ao instalar as dependências. Confira a internet e tente de novo. Se continuar falhando, instale o"
  echo "Python 3.13 em https://www.python.org/downloads/, apague a pasta .venv deste projeto e abra de novo."
  exit 1
fi
exec .venv/bin/python -m estudio
