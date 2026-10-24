@echo off
rem Start: launches the app and opens the browser.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Setup required: run setup.bat first.
  pause
  exit /b 1
)
if not exist ".env" (
  echo File .env not found: run setup.bat first.
  pause
  exit /b 1
)
echo Starting LEAD-ASSISTENT ... open http://localhost:8000
echo Close this window or press Ctrl+C to stop.
start "" cmd /c "timeout /t 4 /nobreak >nul & start "" http://localhost:8000"
".venv\Scripts\python.exe" app.py
pause