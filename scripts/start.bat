@echo off
REM Start the backend (port 8000) and the dashboard (port 5173) in two windows.
REM Close those windows (or press Ctrl+C in them) to stop.
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo [start] .venv not found - run scripts\setup.bat first.
    exit /b 1
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

start "KeetaSense backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
start "KeetaSense dashboard" cmd /k "npm --prefix frontend run dev"

echo [start] Backend:   http://127.0.0.1:8000/docs
echo [start] Dashboard: http://localhost:5173
timeout /t 6 >nul
start "" http://localhost:5173
endlocal
