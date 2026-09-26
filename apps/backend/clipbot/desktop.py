"""ClipBot for Windows: one program that runs the dashboard, API and worker from the system tray.

Settings live in %APPDATA%\\ClipBot (config.json and settings.json; keys go to Windows Credential
Manager). The database and logs live in %LOCALAPPDATA%\\ClipBot on the system drive; clips, which get
big, go in the folder chosen on first run.
Run from source with `python -m clipbot.desktop` after building the dashboard (scripts/build_windows.ps1).
"""

import argparse
import asyncio
import ctypes
import json
import logging
import os
import secrets
import shutil
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "ClipBot"
DEFAULT_PORT = 8742
LIME, INK = (195, 248, 121), (17, 22, 27)
log = logging.getLogger("clipbot.desktop")


def frozen() -> bool:
    return getattr(sys, "frozen", False)


def config_dir() -> Path:
    # CLIPBOT_CONFIG_DIR allows a second, separate copy (and keeps tests away from the real one).
    override = os.environ.get("CLIPBOT_CONFIG_DIR")
    return Path(override) if override else Path(os.environ.get("APPDATA", Path.home())) / APP_NAME


def local_dir() -> Path:
    """The database and logs: small, precious, and kept on the system drive."""
    override = os.environ.get("CLIPBOT_CONFIG_DIR")
    return Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME


def default_clips_dir() -> Path:
    return local_dir() / "clips"


def frontend_dir() -> Path:
    if frozen():
        return Path(sys._MEIPASS) / "frontend"
    return Path(__file__).resolve().parents[2] / "frontend" / "out"


def load_config() -> dict:
    try:
        return json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_config(config: dict) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def message(text: str, ask: bool = False) -> bool:
    """A native Windows message box; with ask=True, Yes/No and returns True for Yes."""
    if os.name != "nt":
        print(text)
        return True
    flags = 0x04 | 0x20 if ask else 0x40  # MB_YESNO|MB_ICONQUESTION, or MB_ICONINFORMATION
    return ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, flags) == 6  # IDYES


def ask_for_clips_dir(default: Path) -> Path | None:
    """First run: where clips go. They get big, so the owner chooses the drive."""
    free = shutil.disk_usage(default.anchor or "/").free / 1e9
    if message(
        "Where should ClipBot keep your clips?\n\n"
        "They take a lot of space: about 2 to 3 GB for each long video.\n\n"
        f"Yes: use {default}  ({free:.0f} GB free on that drive)\n"
        "No: choose another folder",
        ask=True,
    ):
        return default
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    chosen = filedialog.askdirectory(title="Choose a folder for ClipBot's clips", mustexist=False)
    root.destroy()
    return Path(chosen) if chosen else None


def prepare_environment(config: dict) -> dict[str, str]:
    """Environment for the app's settings: database on the system drive, clips in their folder."""
    clips = Path(config["clips_dir"])
    return {
        "APP_ENV": "desktop",
        "DATABASE_URL": f"sqlite:///{(local_dir() / 'clipbot.db').as_posix()}",
        "STORAGE_ROOT": str(clips),
        "SOURCE_DIRECTORY": str(clips / "sources"),
        "WEB_ORIGIN": f"http://127.0.0.1:{config['port']}",
        "CLIPBOT_SETTINGS_DIR": str(config_dir()),
        "FRONTEND_DIR": str(frontend_dir()),
    }


def ensure_session_secret() -> None:
    """Sign-in cookies need a secret unique to this computer; make one on first run."""
    from . import stored_settings

    if not stored_settings.load().get("session_secret"):
        stored_settings.save({"session_secret": secrets.token_urlsafe(48)})


def clipbot_running(port: int) -> bool:
    import httpx

    try:
        return httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).json().get("service") == "clipbot"
    except (httpx.HTTPError, ValueError):
        return False


def port_free(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def setup_logging() -> None:
    (local_dir() / "logs").mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        local_dir() / "logs" / "clipbot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs can carry signed media links


def brand_image(size: int = 64):
    """The ClipBot mark: sound bars on a lime tile."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 4, fill=LIME)
    bars = [0.30, 0.55, 0.80, 0.55, 0.30]
    width = size / 11
    for i, height in enumerate(bars):
        x = size * 0.2 + i * width * 1.6
        half = size * height / 2
        draw.rounded_rectangle((x, size / 2 - half, x + width, size / 2 + half), radius=width / 2, fill=INK)
    return image


class ClipBot:
    """The API server and the worker, running in background threads of one process."""

    def __init__(self, port: int):
        import uvicorn

        from .api import app

        self.url = f"http://127.0.0.1:{port}/"
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
        )
        self.stop = threading.Event()
        self.threads = []

    def start(self) -> None:
        from .local_worker import run

        api = threading.Thread(target=self.server.run, name="api", daemon=True)
        api.start()
        deadline = time.monotonic() + 60
        while not self.server.started:
            if not api.is_alive() or time.monotonic() > deadline:
                raise RuntimeError(f"The ClipBot server didn't start; see the log in {local_dir() / 'logs'}")
            time.sleep(0.2)
        worker = threading.Thread(target=lambda: asyncio.run(run(self.stop)), name="worker", daemon=True)
        worker.start()
        self.threads = [api, worker]
        log.info("ClipBot is running at %s", self.url)

    def quit(self) -> None:
        log.info("Quitting")
        self.stop.set()
        self.server.should_exit = True
        for thread in self.threads:
            thread.join(timeout=30)  # a long upload keeps going at most this long; its job resumes next time

    def open(self) -> None:
        webbrowser.open(self.url)


def posting_paused() -> bool:
    from .db import Session
    from .models import SystemState

    with Session() as db:
        return bool(db.get(SystemState, 1).stop_all_posting)


def set_posting_paused(paused: bool) -> None:
    from .db import transaction
    from .models import SystemState

    with transaction() as db:
        db.get(SystemState, 1).stop_all_posting = paused


def reset_password() -> None:
    """For a forgotten password: the next visit to the dashboard asks for a new one."""
    from .db import transaction
    from .models import User

    with transaction() as db:
        owner = db.get(User, "owner")
        if owner:
            db.delete(owner)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def starts_with_windows() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_start_with_windows(enabled: bool) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --background')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def run_tray(clipbot: ClipBot, clips: Path) -> None:
    import pystray

    def toggle_pause(icon, item):
        set_posting_paused(not posting_paused())

    def toggle_startup(icon, item):
        set_start_with_windows(not starts_with_windows())

    def forgot_password(icon, item):
        if message(
            "Reset the studio password? You'll choose a new one next time you open ClipBot.", ask=True
        ):
            reset_password()
            clipbot.open()

    def quit_app(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open ClipBot", lambda icon, item: clipbot.open(), default=True),
        pystray.MenuItem("Pause posting", toggle_pause, checked=lambda item: posting_paused()),
        pystray.MenuItem(
            "Start with Windows", toggle_startup, checked=lambda item: starts_with_windows(), visible=frozen()
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open clips folder", lambda icon, item: os.startfile(clips)),
        pystray.MenuItem("Open logs", lambda icon, item: os.startfile(local_dir() / "logs")),
        pystray.MenuItem("Reset studio password…", forgot_password),
        pystray.MenuItem("Quit ClipBot", quit_app),
    )
    pystray.Icon(APP_NAME, brand_image(), "ClipBot", menu).run()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument(
        "--background", action="store_true", help="don't open the dashboard (start with Windows)"
    )
    parser.add_argument("--no-tray", action="store_true", help="run without the tray icon until Ctrl+C")
    parser.add_argument(
        "--import-env", metavar="PATH", help="move an existing .env setup's keys and settings in"
    )
    args = parser.parse_args(argv)
    if frozen() and sys.stdout is None:  # a windowed app has no console to print to
        sys.stdout = sys.stderr = open(os.devnull, "w")
    if args.import_env:
        from . import stored_settings

        os.environ["CLIPBOT_SETTINGS_DIR"] = str(config_dir())
        counts = stored_settings.import_env_file(Path(args.import_env))
        message(
            f"Imported {counts['keys']} keys into Windows Credential Manager and {counts['settings']} "
            f"settings into {config_dir() / 'settings.json'}."
        )
        return 0

    config = load_config()
    port = int(config.get("port", DEFAULT_PORT))
    if clipbot_running(port):  # already open: just show it
        if not args.background:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return 0
    if not port_free(port):
        message(
            f'Port {port} is used by another program. Set a different "port" in {config_dir() / "config.json"}.'
        )
        return 1
    if not config.get("clips_dir"):
        chosen = ask_for_clips_dir(default_clips_dir())
        if not chosen:
            return 0
        config.update(clips_dir=str(chosen), port=port)
        save_config(config)
    config.setdefault("port", port)
    clips = Path(config["clips_dir"])
    clips.mkdir(parents=True, exist_ok=True)
    local_dir().mkdir(parents=True, exist_ok=True)
    if not (frontend_dir() / "index.html").is_file():
        message(
            f"The dashboard files are missing from {frontend_dir()}. Build them with scripts/build_windows.ps1."
        )
        return 1

    os.environ.update(prepare_environment(config))
    os.chdir(local_dir())  # nothing is read from a stray .env in the working folder
    setup_logging()
    ensure_session_secret()
    try:
        clipbot = ClipBot(port)
        clipbot.start()
    except Exception as exc:
        log.exception("Startup failed")
        message(f"ClipBot couldn't start: {exc}")
        return 1
    if not args.background:
        clipbot.open()
    try:
        if args.no_tray:
            while True:
                time.sleep(1)
        else:
            run_tray(clipbot, clips)
    except KeyboardInterrupt:
        pass
    finally:
        clipbot.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
