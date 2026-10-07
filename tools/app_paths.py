"""Where the studio keeps its files, in source and in a frozen build.

A PyInstaller bundle has no repo sitting above the game. Bundled assets
live in sys._MEIPASS; caches and the last-used game path live in a user
data directory. Source runs keep the old layout (repo/out, install above
the repo).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "RtKStudio"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory that contains bundled `web/`."""
    if frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def web_root() -> Path:
    return bundle_dir() / "web"


def repo_dir() -> Path:
    """Source repo root, or the folder next to the executable when frozen."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_data() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or
                    Path.home() / "AppData" / "Local")
        name = APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or
                    Path.home() / ".local" / "share")
        name = APP_NAME.lower()
    path = base / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return user_data() / "config.json"


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data: dict) -> None:
    config_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def assetdb_cache() -> Path:
    if frozen():
        return user_data() / "assetdb.json"
    return repo_dir() / "out" / "assetdb.json"


def preview_cache() -> Path:
    path = (user_data() / "preview") if frozen() else (repo_dir() / "out" / "preview")
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_mod() -> Path:
    cfg = load_config()
    raw = cfg.get("mod")
    if raw:
        return Path(raw)
    return user_data() / "mods" / "default"


def looks_like_game(path: Path) -> bool:
    try:
        return (Path(path) / "RTKRES.bin").is_file()
    except OSError:
        return False


def candidate_games():
    seen = []

    def add(path):
        if path is None:
            return
        try:
            resolved = Path(path)
        except TypeError:
            return
        if resolved not in seen:
            seen.append(resolved)

    cfg = load_config()
    if cfg.get("game"):
        add(cfg["game"])
    here = repo_dir()
    add(here)
    add(here.parent)
    if not frozen():
        add(Path(__file__).resolve().parent.parent.parent)
    home = Path.home()
    add(home / "GOG Games" / "Return To Krondor")
    add(Path(r"C:\GOG Games\Return To Krondor"))
    add(Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Return To Krondor"))
    add(home / ".local" / "share" / "Steam" / "steamapps" / "common" /
        "Return to Krondor")
    add(home / ".steam" / "steam" / "steamapps" / "common" / "Return to Krondor")
    return seen


def find_game():
    for path in candidate_games():
        if looks_like_game(path):
            return path.resolve()
    return None


def pick_game_folder():
    """Stdlib folder dialog. None if the user cancels or Tk is missing."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    chosen = filedialog.askdirectory(
        title="Select the Return to Krondor install (the folder with RTKRES.bin)")
    root.destroy()
    if not chosen:
        return None
    return Path(chosen)


def resolve_game(explicit=None, prompt=False):
    """A game install path, or None."""
    if explicit:
        path = Path(explicit).resolve()
        return path if looks_like_game(path) else path
    found = find_game()
    if found:
        return found
    if prompt:
        picked = pick_game_folder()
        if picked:
            return picked.resolve()
    return None


def remember(game=None, mod=None):
    cfg = load_config()
    if game is not None:
        cfg["game"] = str(Path(game))
    if mod is not None:
        cfg["mod"] = str(Path(mod))
    save_config(cfg)
