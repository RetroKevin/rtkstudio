# Standalone desktop studio

The studio is still the localhost viewer in [tools/viewer.py](../tools/viewer.py).
The desktop program starts that server on `127.0.0.1` and opens it in a native
window ([tools/desktop.py](../tools/desktop.py)). The game install stays
read-only; edits go into a mod project.

## Run from source

```
pip install -r requirements-desktop.txt
python tools/desktop.py --game "C:\path\to\Return To Krondor"
```

`--game` is optional after the first successful launch: the last path is
remembered. If nothing looks like an install (a folder containing
`RTKRES.bin`), a folder dialog asks for it.

`--mod` is optional. With no flag, edits go to `mods/default` under the user
data directory (`%LOCALAPPDATA%\RtKStudio` on Windows, `~/.local/share/rtkstudio`
on Linux).

Keep `python tools/viewer.py` for the browser/dev path. That one still
defaults `--mod` off, still binds port 8765, and still opens a browser.

## Windows zip

Build on Windows (PyInstaller does not cross-compile):

```
pip install -r requirements-desktop.txt
pyinstaller packaging/rtkstudio.spec
```

Zip `dist/rtkstudio/` and ship that folder. The user unpacks it and runs
`rtkstudio.exe`. Edge WebView2 is already on Windows 10/11.

First run: if the game is not next to the exe (or in a remembered / GOG
path), pick the install folder that contains `RTKRES.bin`.

Do not put the game, `out/`, or Ghidra inside the zip. Video previews still
use VLC or ffmpeg on PATH; they are not bundled.

For a debug build that keeps a terminal, set `CONSOLE = True` at the top of
[packaging/rtkstudio.spec](../packaging/rtkstudio.spec) and rebuild.

## Linux zip

Build on Linux the same way (`pip install` then `pyinstaller packaging/rtkstudio.spec`).
Ship `dist/rtkstudio/`. The binary needs WebKitGTK on the machine:

- Ubuntu 22.04+ / Debian: `gir1.2-webkit2-4.1`
- Older Ubuntu: `gir1.2-webkit2-4.0`
- Fedora: `webkit2gtk4.1`

From source you also want `python3-gi` (and `python3-tk` for the first-run
folder dialog). A PyInstaller build embeds Python; it still needs the
WebKitGTK system library.

## How this differs from `viewer.py`

| | `viewer.py` | `desktop.py` / zip |
| --- | --- | --- |
| Window | your browser | pywebview (WebView2 / WebKitGTK) |
| Port | 8765 | OS-picked (`0`) so a second copy does not collide |
| `--game` default | folder above the repo | last used, then common install paths, then a picker |
| `--mod` | off unless you pass it | on (`mods/default` in user data) |
| Caches when frozen | — | `%LOCALAPPDATA%\RtKStudio` or `~/.local/share/rtkstudio` |
| Three.js | vendored under `tools/web/vendor/` in both |
