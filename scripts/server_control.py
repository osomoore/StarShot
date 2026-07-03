from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".starshot"
PID_FILE = STATE_DIR / "server.pid"
LOG_FILE = STATE_DIR / "server.log"
HOST = "127.0.0.1"
PORT = "8000"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start, stop, or check the StarShot dev server.")
    parser.add_argument("command", choices=("start", "stop", "status"))
    args = parser.parse_args(argv)

    if args.command == "start":
        return start_server()
    if args.command == "stop":
        return stop_server()
    if args.command == "status":
        return show_status()
    return 2


def start_server() -> int:
    if is_running():
        print(f"StarShot server is already running on http://{HOST}:{PORT}")
        print(f"PID: {PID_FILE.read_text(encoding='utf-8').strip()}")
        return 0

    missing = [name for name in ("fastapi", "uvicorn") if importlib.util.find_spec(name) is None]
    if missing:
        print("Missing server dependencies: " + ", ".join(missing))
        print("Install them with:")
        print("  python -m pip install -e .[dev]")
        return 1

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")
    log_handle = LOG_FILE.open("a", encoding="utf-8")

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "starshot.api.app:app",
            "--app-dir",
            "backend",
            "--host",
            HOST,
            "--port",
            PORT,
            "--reload",
        ],
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    log_handle.close()
    PID_FILE.write_text(str(process.pid), encoding="utf-8")

    print(f"Started StarShot server on http://{HOST}:{PORT}")
    print(f"PID: {process.pid}")
    print(f"Log: {LOG_FILE}")
    return 0


def stop_server() -> int:
    if not PID_FILE.exists():
        print("No StarShot server PID file found.")
        return 0

    pid = read_pid()
    if pid is None:
        PID_FILE.unlink(missing_ok=True)
        print("Removed invalid server PID file.")
        return 0

    if not process_exists(pid):
        PID_FILE.unlink(missing_ok=True)
        print("StarShot server was not running; removed stale PID file.")
        return 0

    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
    else:
        os.kill(pid, signal.SIGTERM)

    PID_FILE.unlink(missing_ok=True)
    print("Stopped StarShot server.")
    return 0


def show_status() -> int:
    if is_running():
        pid = PID_FILE.read_text(encoding="utf-8").strip()
        print(f"StarShot server is running on http://{HOST}:{PORT}")
        print(f"PID: {pid}")
        print(f"Log: {LOG_FILE}")
    else:
        print("StarShot server is not running.")
    return 0


def is_running() -> bool:
    pid = read_pid()
    return pid is not None and process_exists(pid)


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
