"""Native desktop window around the localhost studio viewer.

Starts the existing HTTP server on 127.0.0.1 (OS-picked port) and opens
it in a pywebview window. The game install stays read-only; edits go
into a mod project.

    python tools/desktop.py --game "C:\\path\\to\\Return To Krondor"

For the browser/dev path, keep using ``python tools/viewer.py``.
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app_paths
import viewer


def _icon_path() -> Path | None:
    """Same file the packaged exe embeds: the K with a wrench."""
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "rtkstudio.ico"
    if bundled.is_file():
        return bundled
    dev = Path(__file__).resolve().parent.parent / "packaging" / "rtkstudio.ico"
    return dev if dev.is_file() else None


def _use_window_icon(window, path: Path):
    """Put the exe's icon on the title bar.

    WinForms asks the exe for icon 0 and then narrows the handle to 32
    bits, which drops it on 64-bit Windows. Assigning Form.Icon from the
    same file, on the UI thread, is the path that actually sticks.
    """
    def apply():
        native = getattr(window, "native", None)
        if native is None:
            return

        def assign():
            from System.Drawing import Icon
            native.Icon = Icon(str(path))

        try:
            import System
            native.Invoke(System.Action(assign))
        except Exception:
            try:
                assign()
            except Exception:
                pass

    try:
        window.events.shown += apply
    except Exception:
        pass


def _mod_project(explicit):
    import modproject
    root = Path(explicit) if explicit else app_paths.default_mod()
    root.mkdir(parents=True, exist_ok=True)
    return modproject.ModProject(root)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", type=Path, default=None,
                    help="game install (the folder that contains RTKRES.bin)")
    ap.add_argument("--mod", type=Path, default=None,
                    help="mod project directory (default: user-data mods/default)")
    ap.add_argument("--cache", type=Path, default=None,
                    help="asset index cache")
    ap.add_argument("--rebuild", action="store_true",
                    help="re-index the install")
    args = ap.parse_args(argv)

    try:
        import webview
    except ImportError:
        print("pywebview is not installed. From the repo:")
        print("  pip install -r requirements-desktop.txt")
        print("Or keep using the browser: python tools/viewer.py")
        return 2

    game = app_paths.resolve_game(args.game, prompt=True)
    if game is None or not app_paths.looks_like_game(game):
        hint = game or "(no folder chosen)"
        print("No RTKRES.bin under %s" % hint)
        print("The studio needs a Return to Krondor install. Pass --game,")
        print("or pick the folder that contains RTKRES.bin.")
        return 2
    game = game.resolve()

    mod = _mod_project(args.mod)
    cache = args.cache or app_paths.assetdb_cache()
    app_paths.remember(game=game, mod=mod.root)

    try:
        server, url = viewer.bind_server(
            game, cache, mod, port=0, rebuild=args.rebuild)
    except OSError as exc:
        print("Cannot start the local server: %s" % exc)
        return 1

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print("serving %s" % url, flush=True)

    def on_closed():
        server.shutdown()

    window = webview.create_window(
        "Return to Krondor",
        url,
        width=1280,
        height=800,
    )
    icon = _icon_path()
    if icon is not None and sys.platform == "win32":
        _use_window_icon(window, icon)
    try:
        window.events.closed += on_closed
    except Exception:
        pass
    webview.start()
    server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
