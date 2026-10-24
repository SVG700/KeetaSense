@echo off
REM Full live demo: fresh simulated history + backend + dashboard + edge device in mock mode.
REM The mock trap sends a new tape section every 20 seconds; turn on "Live" in the dashboard.
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo [demo] .venv not found - run scripts\setup.bat first.
    exit /b 1
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set MOCK_HARDWARE=1

if not exist "demo\sample_tape\tape_01.jpg" .venv\Scripts\python.exe -m demo.generate_sample_tape
echo [demo] Loading 14 days of SIMULATED history ...
.venv\Scripts\python.exe -m demo.seed --reset || exit /b 1

start "KeetaSense backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
start "KeetaSense dashboard" cmd /k "npm --prefix frontend run dev"
echo [demo] Waiting for the backend ...
timeout /t 8 >nul
start "KeetaSense edge (mock)" cmd /k ".venv\Scripts\python.exe -m edge.main --demo"
start "" http://localhost:5173

echo [demo] Running. Dashboard: http://localhost:5173  (switch "Live" on)
echo [demo] Close the three windows to stop.
endlocal
