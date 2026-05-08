#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
    echo "Primo avvio: creo virtualenv ed installo dipendenze..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi
echo "Avvio app desktop..."
python app_desktop.py
