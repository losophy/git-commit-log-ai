@echo off
setlocal

cd /d "%~dp0"

echo [1/3] Checking dependencies...
.\.venv\Scripts\python.exe -c "import PyInstaller" >nul 2>nul
if %errorlevel% neq 0 (
    echo PyInstaller not found, installing...
    .\.venv\Scripts\python.exe -m pip install pyinstaller
)

echo [2/3] Cleaning old artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist git-commit-log-ai.exe del /q git-commit-log-ai.exe

echo [3/3] Building exe...
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name git-commit-log-ai --distpath . --hidden-import openai main.py

if %errorlevel% neq 0 (
    echo BUILD FAILED - see errors above.
    exit /b 1
)

echo.
echo Done: git-commit-log-ai.exe
echo Usage: double-click, then pick a Git repo in the window.
echo Note: put a .env next to the exe for the first run (copy .env.example).
endlocal