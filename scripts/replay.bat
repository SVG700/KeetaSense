@echo off
REM Stage insurance: backend + dashboard + REPLAY of a recorded run (no camera / Pi needed).
REM Uses demo\replay_real if it exists, otherwise the synthetic demo\replay. Or: replay.bat path\to\pack
REM Ctrl+C or closing the window stops everything.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo [replay] .venv not found - run scripts\setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" scripts\launcher.py replay %*
