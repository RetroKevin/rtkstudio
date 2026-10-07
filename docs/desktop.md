# Standalone desktop studio

The studio is still the localhost viewer in [tools/viewer.py](../tools/viewer.py).
The desktop program starts that server on `127.0.0.1` and opens it in a native
window ([tools/desktop.py](../tools/desktop.py)). Edits go into a mod project.
The install is left unchanged, except two repairs that write
`RTKRONDOR.INI` and keep a backup. **Fix folder paths** writes absolute
paths when `[Directories]` entries are relative, missing, or contain a
period in a folder name. **Repair launch settings** writes the software
renderer when a hardware Driver guid is selected.

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

## Linux

The published archive is built on Ubuntu 24.04 by
`.github/workflows/linux.yml` in the public studio repo and attached to the
GitHub release as `RtKStudio-linux-x64.tar.gz`. It needs WebKitGTK 4.1 and
glibc 2.39 or newer.

To build on the machine that will run it, including Ubuntu 22.04:

```
sh packaging/build-linux.sh
```

That installs GTK, WebKitGTK, and the Python packages, then writes
`dist/rtkstudio/`. The binary still needs the system WebKitGTK library.
WebKit 4.1 is `gir1.2-webkit2-4.1` on Ubuntu 24.04 and Debian, and
`webkit2gtk4.1` on Fedora. Ubuntu 22.04 has `gir1.2-webkit2-4.0` instead.
The folder dialog also wants `python3-tk`.

## How this differs from `viewer.py`

| | `viewer.py` | `desktop.py` / zip |
| --- | --- | --- |
| Window | your browser | pywebview (WebView2 / WebKitGTK) |
| Port | 8765 | OS-picked (`0`) so a second copy does not collide |
| `--game` default | folder above the repo | last used, then common install paths, then a picker |
| `--mod` | off unless you pass it | on (`mods/default` in user data) |
| Caches when frozen | — | `%LOCALAPPDATA%\RtKStudio` or `~/.local/share/rtkstudio` |
| Three.js | vendored under `tools/web/vendor/` in both |
