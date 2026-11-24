@echo off
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
(
echo @echo off
echo cd /d "%~dp0"
echo start "" "%~dp0venv\Scripts\pythonw.exe" main.py --voice
) > "%STARTUP%\Orion.bat"
echo Orion will now appear in the corner of your screen, listening, every time you log in.
echo To undo: delete "%STARTUP%\Orion.bat"
pause
