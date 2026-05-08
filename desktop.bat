@echo off
cd /d "%~dp0"
if not exist .venv (
    echo Primo avvio: creo virtualenv ed installo dipendenze...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
echo Avvio app desktop...
python app_desktop.py
