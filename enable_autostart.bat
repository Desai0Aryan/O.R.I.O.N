@echo off
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
(
echo @echo off
echo cd /d "%~dp0"
echo call venv\Scripts\activate
echo python main.py --voice
) > "%STARTUP%\Orion.bat"
echo Orion will now start in voice mode every time you log in.
echo To undo: delete "%STARTUP%\Orion.bat"
pause
