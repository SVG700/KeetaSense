@echo off
REM Full live demo in THIS window: reset demo data + backend + dashboard + mock trap (one cycle / 20 s).
REM Ctrl+C or closing the window stops everything. Options: --lan  --no-seed  --no-browser  --cycles N
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo [demo] .venv not found - run scripts\setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" scripts\launcher.py demo %*
