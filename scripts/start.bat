@echo off
REM Start KeetaSense (backend + dashboard) in THIS window. Ctrl+C or closing the window stops it.
REM Options: --lan (let the Pi / phones connect)  --dev (Vite dev server)  --no-browser
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo [start] .venv not found - run scripts\setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" scripts\launcher.py start %*
