from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
STATE_DIR = ROOT / ".starshot"
PID_FILE = STATE_DIR / "server.pid"
LOG_FILE = STATE_DIR / "server.log"
HOST = "127.0.0.1"
PORT = "8000"
DEFAULT_DECK_SET = ROOT / "resources" / "decks" / "core_0_2"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start, stop, or check the StarShot dev server.",
        epilog=(
            "Deck loader: edit resources\\decks\\core_0_2\\base_deck.toml and "
            "desperation_deck.toml, or start with --deck-set path\\to\\deck_set. "
            "A deck set needs manifest.toml, base_deck.toml, and desperation_deck.toml. "
            "See docs\\context\\deck_data.md."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser(
        "start",
        help="Start or restart the StarShot dev server.",
        epilog=(
            "Examples: python scripts\\server_control.py start --deck-set resources\\decks\\core_0_2 "
            "or start_server.bat --deck-set resources\\decks\\core_0_2"
        ),
    )
    start.add_argument("-d", "--deck-set", type=Path, help="Deck set directory to use for new and active games.")
    subparsers.add_parser("stop", help="Stop the StarShot dev server.")
    subparsers.add_parser("status", help="Show StarShot dev server status.")
    args = parser.parse_args(argv)

    if args.command == "start":
        return start_server(args.deck_set)
    if args.command == "stop":
        return stop_server()
    if args.command == "status":
        return show_status()
    return 2


def start_server(deck_set: Path | None = None) -> int:
    missing = [name for name in ("fastapi", "uvicorn") if importlib.util.find_spec(name) is None]
    if missing:
        print("Missing server dependencies: " + ", ".join(missing))
        print("Install them with:")
        print("  python -m pip install -e .[dev]")
        return 1

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    deck_set_path = resolve_deck_set_path(deck_set)
    catalog = validate_deck_set(deck_set_path)
    if is_running():
        print(f"StarShot server is already running on http://{HOST}:{PORT}; restarting it.")
        stop_server()
        time.sleep(0.5)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    env["STARSHOT_DECK_SET"] = str(deck_set_path)
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
    print(f"Deck set: {catalog.id} ({catalog.name})")
    print(f"Deck path: {catalog.path}")
    print(f"PID: {process.pid}")
    print(f"Log: {LOG_FILE}")
    print("Deck files: manifest.toml, base_deck.toml, desperation_deck.toml")
    print("Deck docs: docs\\context\\deck_data.md")
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


def resolve_deck_set_path(deck_set: Path | None) -> Path:
    if deck_set is not None:
        return (ROOT / deck_set).resolve() if not deck_set.is_absolute() else deck_set.resolve()
    configured = os.environ.get("STARSHOT_DECK_SET")
    if configured:
        configured_path = Path(configured)
        return (ROOT / configured_path).resolve() if not configured_path.is_absolute() else configured_path.resolve()
    return DEFAULT_DECK_SET.resolve()


def validate_deck_set(deck_set_path: Path):
    sys.path.insert(0, str(BACKEND_DIR))
    try:
        from starshot.rules.deck_data import load_deck_catalog

        return load_deck_catalog(deck_set_path)
    except Exception as exc:
        print("Deck loader error:")
        print(f"  {exc}")
        print("")
        print("Expected deck-set layout:")
        print("  manifest.toml")
        print("  base_deck.toml")
        print("  desperation_deck.toml")
        print("")
        print("Use:")
        print("  python scripts\\server_control.py start --deck-set path\\to\\deck_set")
        print("  start_server.bat --deck-set path\\to\\deck_set")
        print("")
        print("You can also set STARSHOT_DECK_SET=path\\to\\deck_set before starting the server.")
        print("Deck authoring docs: docs\\context\\deck_data.md")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    raise SystemExit(main())
