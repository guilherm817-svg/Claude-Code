@echo off
rem Abre o Analisador de Aulas. Na primeira vez, prepara o ambiente Python (leva alguns minutos).
cd /d "%~dp0"
title Analisador de Aulas

if not exist ".venv\Scripts\python.exe" (
    echo Preparando o ambiente pela primeira vez. Isso leva alguns minutos...
    py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Nao encontrei o Python. Instale o Python 3.12 em https://www.python.org/downloads/
        echo e marque a opcao "Add python.exe to PATH" durante a instalacao.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo Falha ao instalar as dependencias. Verifique sua internet e tente de novo.
    pause
    exit /b 1
)

echo.
echo Abrindo o app no navegador. Deixe esta janela aberta enquanto usa; feche-a para encerrar.
".venv\Scripts\python.exe" -m streamlit run app.py
pause
