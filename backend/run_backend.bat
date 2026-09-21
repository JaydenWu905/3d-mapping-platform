@echo off
chcp 65001 >nul
REM ============================================================
REM  Backend startup script (Phase 1 demo)
REM  Starts FastAPI service at http://127.0.0.1:8000
REM
REM  On first run, creates .venv and installs dependencies;
REM  afterwards it just starts the server.
REM  NOTE: no Conda / Pixi is used.
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] .venv not found, creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [error] Failed to create virtual environment. Please make sure Python 3.10+ is installed and on PATH.
        pause
        exit /b 1
    )
    echo [setup] Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [error] Dependency installation failed.
        pause
        exit /b 1
    )
)

echo [start] Starting backend: http://127.0.0.1:8000  (press Ctrl+C to stop)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

endlocal