@echo off
rem Setup: creates .venv, installs libraries, creates .env from template.
setlocal
cd /d "%~dp0"
echo ============================================
echo  LEAD-ASSISTENT - installation
echo ============================================
echo.
echo [1/3] Creating virtual environment .venv ...
python -m venv .venv
if errorlevel 1 (
  echo ERROR: Python not found. Install Python 3.10+ from python.org
  echo        and tick "Add Python to PATH" during installation.
  pause
  exit /b 1
)
echo [2/3] Installing libraries ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
  echo ERROR: could not install libraries. Check your internet connection.
  pause
  exit /b 1
)
echo [3/3] Preparing .env ...
if not exist ".env" copy ".env.example" ".env" >nul
echo.
echo DONE.
echo.
echo 1. Open the file .env in Notepad (it is now open).
echo 2. Paste your GigaChat Authorization Key after GIGACHAT_API_KEY=
echo    (no quotes, no spaces).
echo 3. Save, close Notepad, and run start.bat
echo.
start notepad ".env"
pause