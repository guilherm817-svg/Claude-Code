@echo off
REM Abre o Rastro no computador. Na primeira vez, prepara o ambiente Python (leva um minuto).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Preparando o ambiente pela primeira vez...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo Nao encontrei o Python. Instale o Python 3.10 ou mais novo em https://www.python.org/downloads/
    echo e marque "Add python.exe to PATH" na instalacao.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
echo Rastro rodando em http://localhost:8000  (feche esta janela para encerrar)
start "" http://localhost:8000
".venv\Scripts\python.exe" -m rastro
pause
