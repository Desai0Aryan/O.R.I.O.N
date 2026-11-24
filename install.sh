#!/usr/bin/env bash
# One-time install for Mac/Linux. Run:  bash install.sh
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Install Python 3.10+ first (python.org or your package manager)."; exit 1; }
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
mkdir -p data
chmod +x run_orion.sh enable_autostart.sh
echo
echo "Install complete. Edit config.yaml and .env, then run:  ./run_orion.sh"
