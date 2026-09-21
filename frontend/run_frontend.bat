@echo off
chcp 65001 >nul
REM ============================================================
REM  Frontend startup script (Phase 1 demo)
REM  Starts Vite dev server at http://localhost:5173
REM  (/api requests are proxied to backend port 8000)
REM
REM  On first run, runs npm install; afterwards it just starts.
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "node_modules" (
    echo [setup] node_modules not found, installing dependencies...
    call npm install
    if errorlevel 1 (
        echo [error] Dependency installation failed. Please make sure Node.js 18+ and npm are installed.
        pause
        exit /b 1
    )
)

echo [start] Starting frontend: http://localhost:5173  (press Ctrl+C to stop)
call npm run dev

endlocal