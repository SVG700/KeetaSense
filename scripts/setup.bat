@echo off
REM KeetaSense one-time setup for Windows: Python venv + packages, .env, frontend packages, sample images.
REM Run from anywhere:  scripts\setup.bat
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    echo [setup] Using existing virtual environment .venv
) else (
    echo [setup] Creating virtual environment .venv ...
    where py >nul 2>nul && (py -3.12 -m venv .venv) || (python -m venv .venv)
    if not exist ".venv\Scripts\python.exe" (
        if exist ".tools\uv.exe" (
            echo [setup] No system Python found - using the portable uv in .tools
            set "UV_PYTHON_INSTALL_DIR=%CD%\.tools\python"
            .tools\uv.exe python install 3.12 --no-bin
            .tools\uv.exe venv --python 3.12 .venv
        ) else (
            echo [setup] ERROR: Python 3.12 not found. Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^) and run this again.
            exit /b 1
        )
    )
)

set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip --version >nul 2>nul || "%PY%" -m ensurepip --upgrade
echo [setup] Installing Python packages (CPU PyTorch first) ...
"%PY%" -m pip install --disable-pip-version-check torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu || exit /b 1
"%PY%" -m pip install --disable-pip-version-check -r requirements.txt || exit /b 1

if not exist ".env" (
    copy .env.example .env >nul
    echo [setup] Created .env from .env.example
)

echo [setup] Installing frontend packages ...
call npm --prefix frontend ci --no-fund --no-audit || exit /b 1

if not exist "demo\sample_tape\tape_01.jpg" "%PY%" -m demo.generate_sample_tape

echo.
echo [setup] Done. Next:  scripts\demo.bat   (full live demo)   or   scripts\start.bat
endlocal
