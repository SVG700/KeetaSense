"""KeetaSense launcher: runs everything in ONE console window.

    python scripts/launcher.py start            backend + dashboard
    python scripts/launcher.py demo             reset demo data + backend + dashboard + mock trap (20 s cycles)
    python scripts/launcher.py replay [DIR]     backend + dashboard + REPLAY of a recorded run
Options:
    --lan          accept connections from other devices (Pi, judges' phones): listen on 0.0.0.0
    --dev          use the Vite dev server (port 5173) instead of the built dashboard
    --no-browser   do not open the browser
    --no-seed      (demo) keep the current data instead of resetting it
    --cycles N     (demo/replay) stop everything after N edge cycles (used for testing)
    --sim-weather  SIMULATED weather (clearly labelled) when there is no internet on stage
    --no-bot       do not start the Telegram bot (it starts when TELEGRAM_BOT_TOKEN is set)

The scripts in this folder (start.bat, demo.bat, replay.bat, *.sh) just call this file.

How it keeps the demo safe:
  - every output line is prefixed with the service name, all in this one window
  - the backend serves the built dashboard itself: one process, one address, works offline
  - if the backend or the trap service crashes, it is restarted (up to 5 times)
  - Ctrl+C stops everything; on Windows all services are in a "job object", so
    closing this window also stops every one of them - nothing is left running
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# Windows consoles default to an old code page: print UTF-8 (Kannada, box lines) without crashing
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
PORT = 8000
DEV_PORT = 5173
MAX_RESTARTS = 5


# ---------------------------------------------------------------------------
# Windows: a job object kills all children when this launcher ends (even if the window is closed)
# ---------------------------------------------------------------------------
class _WindowsJob:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32.CreateJobObjectW.restype = wintypes.HANDLE
        self.handle = self.k32.CreateJobObjectW(None, None)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                        "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self.k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))

    def add(self, proc: subprocess.Popen) -> None:
        self.k32.AssignProcessToJobObject(self.handle, int(proc._handle))


JOB = None
if os.name == "nt":
    try:
        JOB = _WindowsJob()
    except Exception as e:  # never fatal: Ctrl+C cleanup still works
        print(f"[launcher] note: could not create a job object ({e}); close services with Ctrl+C")


# ---------------------------------------------------------------------------
# Child processes
# ---------------------------------------------------------------------------
_print_lock = threading.Lock()


def say(tag: str, text: str) -> None:
    with _print_lock:
        print(f"[{tag:<8}] {text}", flush=True)


class Service:
    def __init__(self, name: str, cmd: list[str], env: dict, restart: bool, cwd: Path = ROOT):
        self.name, self.cmd, self.env, self.restart, self.cwd = name, cmd, env, restart, cwd
        self.proc: subprocess.Popen | None = None
        self.restarts = 0
        self.stopping = False

    def start(self) -> None:
        self.proc = subprocess.Popen(self.cmd, cwd=self.cwd, env=self.env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     encoding="utf-8", errors="replace", bufsize=1)
        if JOB:
            JOB.add(self.proc)
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()

    def _pump(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            say(self.name, line.rstrip())

    def stop(self) -> None:
        self.stopping = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def child_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    env.update(extra or {})
    return env


def run_once(tag: str, cmd: list[str], env: dict) -> int:
    """Run a command to completion, streaming its output with a tag."""
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    if JOB:
        JOB.add(proc)
    for line in proc.stdout:
        say(tag, line.rstrip())
    return proc.wait()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def wait_for_backend(timeout: float = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2) as r:
                r.read()  # read the whole reply so the connection closes cleanly
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(1)
    return False


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def lan_addresses() -> list[str]:
    try:
        return sorted({a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith("127.")})
    except OSError:
        return []


def bot_token() -> str:
    """TELEGRAM_BOT_TOKEN from the environment or the project's .env file."""
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return os.environ["TELEGRAM_BOT_TOKEN"].strip()
    try:
        from dotenv import dotenv_values
        return (dotenv_values(ROOT / ".env").get("TELEGRAM_BOT_TOKEN") or "").strip()
    except ImportError:
        return ""


def dashboard_needs_build() -> bool:
    dist = ROOT / "frontend" / "dist" / "index.html"
    if not dist.exists():
        return True
    sources = [p for p in (ROOT / "frontend" / "src").rglob("*") if p.is_file()]
    sources.append(ROOT / "frontend" / "index.html")
    return max(p.stat().st_mtime for p in sources) > dist.stat().st_mtime


def build_dashboard(env: dict) -> bool:
    """Build frontend/dist if it is missing or older than the source. Works offline."""
    if not dashboard_needs_build():
        say("launcher", "dashboard build is up to date")
        return True
    npm = "npm.cmd" if os.name == "nt" else "npm"
    say("launcher", "building the dashboard (npm run build) ...")
    try:
        code = run_once("build", [npm, "--prefix", "frontend", "run", "build"], env)
    except FileNotFoundError:
        code = -1
        say("launcher", "npm not found")
    if code != 0:
        if (ROOT / "frontend" / "dist" / "index.html").exists():
            say("launcher", "WARNING: build failed - using the previous dashboard build")
            return True
        say("launcher", "ERROR: no dashboard build available. Install Node.js or use --dev.")
        return False
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Run KeetaSense in one window.")
    ap.add_argument("mode", choices=["start", "demo", "replay"])
    ap.add_argument("replay_dir", nargs="?", help="replay folder (default demo/replay_real, else demo/replay)")
    ap.add_argument("--lan", action="store_true")
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-seed", action="store_true")
    ap.add_argument("--cycles", type=int)
    ap.add_argument("--sim-weather", action="store_true",
                    help="use SIMULATED weather (labelled; rain in ~4 h) - for a demo without internet")
    ap.add_argument("--no-bot", action="store_true", help="do not start the Telegram bot")
    ap.add_argument("--inject", choices=["blur", "dark", "glare", "stuck", "motor"],
                    help="(demo) the MOCK trap simulates this fault - demo the quality gate / health alerts")
    args = ap.parse_args()

    os.chdir(ROOT)
    env = child_env({"KEETA_WEATHER": "simulated"} if args.sim_weather else None)
    if args.sim_weather:
        say("launcher", "weather: SIMULATED (labelled as such on every screen)")
    if port_in_use(PORT):
        say("launcher", f"ERROR: port {PORT} is already in use - is KeetaSense already running in another window?")
        return 1

    if not args.dev and not build_dashboard(env):
        return 1

    if args.mode == "demo" and not args.no_seed:
        say("launcher", "loading 14 days of SIMULATED demo history ...")
        if run_once("seed", [PY, "-m", "demo.seed", "--reset"], env) != 0:
            say("launcher", "ERROR: seeding failed (see above)")
            return 1

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    services = [Service("backend", [PY, "-m", "uvicorn", "backend.main:app", "--host", host, "--port", str(PORT)],
                        env, restart=True)]
    if args.dev:  # Vite dev server, started with node directly so stopping it really stops it
        services.append(Service("vite", ["node", "node_modules/vite/bin/vite.js", "--port", str(DEV_PORT)],
                                env, restart=False, cwd=ROOT / "frontend"))
    edge = None
    if args.mode in ("demo", "replay"):
        edge_cmd = [PY, "-m", "edge.main", "--demo"]
        edge_env = dict(env, MOCK_HARDWARE="1")
        if args.mode == "replay":
            folder = Path(args.replay_dir) if args.replay_dir else (
                ROOT / "demo" / "replay_real" if (ROOT / "demo" / "replay_real" / "manifest.jsonl").exists()
                else ROOT / "demo" / "replay")
            edge_cmd += ["--replay", str(folder)]
            say("launcher", f"REPLAY mode: {folder}")
        if args.cycles:
            edge_cmd += ["--cycles", str(args.cycles)]
        if args.inject:
            edge_cmd += ["--inject", args.inject]
            say("launcher", f"MOCK fault injection: {args.inject}")
        edge = Service("trap", edge_cmd, edge_env, restart=not args.cycles)

    stop_event = threading.Event()

    def on_signal(*_):
        stop_event.set()
    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        for s in services:
            s.start()
        say("launcher", "waiting for the backend ...")
        if not wait_for_backend():
            say("launcher", "ERROR: backend did not start (see the [backend] lines above)")
            return 1
        url = f"http://127.0.0.1:{DEV_PORT if args.dev else PORT}"
        say("launcher", "=" * 60)
        say("launcher", f"Dashboard: {url}   (switch 'Live' on)")
        if args.lan:
            for ip in lan_addresses():
                say("launcher", f"On the same Wi-Fi: http://{ip}:{DEV_PORT if args.dev else PORT}"
                                f"   (Pi BACKEND_URL=http://{ip}:{PORT})")
        say("launcher", "Press Ctrl+C (or close this window) to stop everything.")
        say("launcher", "=" * 60)
        if edge:
            edge.start()
            services.append(edge)
        if bot_token() and not args.no_bot:   # Telegram bot for farmers (needs internet to reach Telegram)
            bot = Service("bot", [PY, "-m", "backend.telegram_bot"], env, restart=True)
            bot.start()
            services.append(bot)
            say("launcher", "Telegram bot started (TELEGRAM_BOT_TOKEN is set)")
        if not args.no_browser:
            webbrowser.open(url)

        # supervise: restart crashed services, stop when the edge finished its --cycles
        while not stop_event.is_set():
            time.sleep(0.5)
            for s in services:
                code = s.proc.poll() if s.proc else None
                if code is None or s.stopping:
                    continue
                if s is edge and args.cycles:
                    say("launcher", f"trap service finished {args.cycles} cycle(s) - stopping")
                    stop_event.set()
                elif s.restart and s.restarts < MAX_RESTARTS:
                    s.restarts += 1
                    say("launcher", f"WARNING: {s.name} stopped (exit {code}) - restarting "
                                    f"({s.restarts}/{MAX_RESTARTS})")
                    time.sleep(2)
                    s.start()
                else:
                    say("launcher", f"{s.name} stopped (exit {code})")
                    s.stopping = True
    finally:
        say("launcher", "stopping all services ...")
        for s in reversed(services):
            s.stop()
        say("launcher", "stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
