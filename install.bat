@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from python.org and tick "Add Python to PATH", then run this again.
  pause
  exit /b 1
)
if not exist venv python -m venv venv
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
if not exist data mkdir data
echo.
echo Install complete. Edit config.yaml and .env, then double-click run_orion.bat
pause
