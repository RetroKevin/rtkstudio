"""Launch settings in RTKRONDOR.INI.

Engine 1 with a Driver guid asks True3D for a hardware device. On current
Windows that call lands in the graphics driver's own DLL (nv3dum.dll,
atiumdag.dll, and the others named in Steam reports) and the process
exits with "An error has been detected which prevents the game from
continuing". The ini loader's fallback, when that guid cannot be read,
is the software renderer (Engine 0). A GOG install that stores Engine=1
and no Driver line already takes that fallback.

This repair writes Engine=0 and the small set of Cinemat, Console, and
Audio values a working install uses. [Directories] and every other
section stay as they are. Compatibility mode is not turned on: Windows
uses that shim to force its own DirectDraw onto a program named RtK.exe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import rtkpaths

BACKUP_NAME = "RTKRONDOR.INI.launch-bak"
DISPLAY_PATCH = "https://github.com/RetroKevin/return-to-krondor-display"

SAFE_SECTIONS = (
    ("Cinemat", ("Playback=1", "Stretch=0")),
    ("Console", ("Console=0",)),
    ("Audio", (
        "MasterVolume=1.000000",
        "MusicVolume=1.000000",
        "MusicEnabled=1",
    )),
    ("Graphics", ("Gamma=1.000000", "Engine=0")),
)


def _graphics(game) -> dict:
    path = rtkpaths.ini_path(game)
    found = {}
    if not path.is_file():
        return found
    text, newline = rtkpaths._read_text(path)
    lines = rtkpaths._lines(text, newline)
    section = None
    for line in lines:
        body = line.strip()
        if len(body) >= 2 and body.startswith("[") and body.endswith("]"):
            section = body[1:-1].strip().casefold()
            continue
        if section != "graphics":
            continue
        parsed = rtkpaths._key_value(line)
        if parsed:
            found[parsed[0].casefold()] = parsed[1].strip()
    return found


def _engine_needs_repair(graphics: dict) -> bool:
    if "engine" not in graphics:
        return False
    try:
        engine = int(graphics["engine"].split()[0])
    except ValueError:
        return True
    driver = graphics.get("driver", "").strip().strip('"')
    if engine == 0:
        return False
    if engine == 1 and not driver:
        return False
    return True


def _dotted_folder(game: Path) -> str | None:
    for part in Path(game).parts:
        if part in (".", "..") or part.endswith(":"):
            continue
        if "." in part:
            return part
    return None


def _compat_layers(exe: Path) -> str:
    if sys.platform != "win32" or not exe.is_file():
        return ""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers")
        try:
            value, _ = winreg.QueryValueEx(key, str(exe))
        except FileNotFoundError:
            return ""
        finally:
            winreg.CloseKey(key)
    except OSError:
        return ""
    return str(value or "")


def _dep_policy() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetSystemDEPPolicy())
    except (AttributeError, OSError, ValueError):
        return None


def _system_dpi() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetDpiForSystem.restype = ctypes.c_uint
        dpi = int(user32.GetDpiForSystem())
    except (AttributeError, OSError, ValueError):
        return None
    if dpi < 96:
        return None
    return dpi


def scaling_note(dpi: int) -> str | None:
    """Combat text is a 12pt font sized from the process DPI."""
    if dpi <= 96:
        return None
    percent = int(round(dpi * 100 / 96))
    return (
        "Windows display scaling is %d%%. The combat font is 12 points "
        "sized from that DPI, so the top bar and the hover HP draw too "
        "large for the 640x480 layout. Set scaling to 100%%. Replacing "
        "Krondor.ttf does not change the size. The display patch already "
        "turns off font smoothing for these letters." % percent)


def _warnings(game: Path) -> list[str]:
    notes = []
    dotted = _dotted_folder(game)
    if dotted:
        notes.append(
            "The folder %r contains a period. The game cuts a path at the "
            "last period, so a conversation crashes while opening its voice "
            "file. Fix folder paths makes a launch folder with no period. "
            "Start RtK.exe from that folder. Steam's Play button still starts "
            "the original path." % dotted)
    if not (game / "ddraw.dll").is_file():
        notes.append(
            "This folder has no ddraw.dll. The picture on Windows 10 and 11 "
            "uses the display patch at %s." % DISPLAY_PATCH)
    for name in ("RtK.exe", "RtKGame.exe"):
        layers = _compat_layers(game / name)
        if any(flag in layers.upper() for flag in ("WIN98", "WIN95", "WINXP", "NT4SP5")):
            notes.append(
                "%s has a Windows compatibility mode set. Clear that checkbox. "
                "The mode makes Windows load its own DirectDraw, which is the "
                "failure the display patch avoids." % name)
            break
    dpi = _system_dpi()
    if dpi:
        note = scaling_note(dpi)
        if note:
            notes.append(note)
    policy = _dep_policy()
    if policy in (1, 3):
        notes.append(
            "Data Execution Prevention is turned on for every program. "
            "If launch still dies with ACCESS_VIOLATION in msvcrt.dll, add "
            "RtK.exe as a DEP exception in System Properties. This repair "
            "does not change that setting.")
    return notes


def inspect_launch(game) -> dict:
    game = Path(game)
    graphics = _graphics(game)
    return {
        "ini": str(rtkpaths.ini_path(game)),
        "present": rtkpaths.ini_path(game).is_file(),
        "engine": graphics.get("engine"),
        "driver": graphics.get("driver", ""),
        "needs_repair": _engine_needs_repair(graphics),
        "warnings": _warnings(game),
    }


def _replace_sections(lines: list[str]) -> tuple[list[str], list[str]]:
    wanted = {name.casefold(): (name, body) for name, body in SAFE_SECTIONS}
    out = []
    changed = []
    i = 0
    seen = set()
    while i < len(lines):
        body = lines[i].strip()
        if len(body) >= 2 and body.startswith("[") and body.endswith("]"):
            name = body[1:-1].strip()
            spec = wanted.get(name.casefold())
            if spec:
                key, rows = spec
                seen.add(name.casefold())
                block = ["[%s]" % key, *rows]
                nxt = i + 1
                while nxt < len(lines):
                    peek = lines[nxt].strip()
                    if len(peek) >= 2 and peek.startswith("[") and peek.endswith("]"):
                        break
                    nxt += 1
                current = [line.strip() for line in lines[i:nxt] if line.strip()]
                if current != block:
                    changed.append(key)
                out.extend(block)
                i = nxt
                continue
        out.append(lines[i])
        i += 1
    for name, rows in SAFE_SECTIONS:
        if name.casefold() in seen:
            continue
        if out and out[-1].strip():
            out.append("")
        out.append("[%s]" % name)
        out.extend(rows)
        changed.append(name)
    return out, changed


def apply_launch(game, backup: bool = True) -> dict:
    game = Path(game)
    report = inspect_launch(game)
    path = rtkpaths.ini_path(game)
    if not path.is_file():
        report["wrote"] = False
        report["error"] = "No RTKRONDOR.INI in %s" % game
        return report
    if not report["needs_repair"]:
        report["wrote"] = False
        report["changed"] = []
        return report
    text, newline = rtkpaths._read_text(path)
    lines = rtkpaths._lines(text, newline)
    updated, changed = _replace_sections(lines)
    if not changed:
        report["wrote"] = False
        report["changed"] = []
        report["needs_repair"] = False
        return report
    if backup:
        bak = game / BACKUP_NAME
        if not bak.exists():
            bak.write_bytes(path.read_bytes())
            report["backup"] = str(bak)
    out = newline.join(updated) + newline
    encoding = "mbcs" if sys.platform == "win32" else "utf-8"
    path.write_bytes(out.encode(encoding))
    report["wrote"] = True
    report["changed"] = changed
    fresh = inspect_launch(game)
    report["needs_repair"] = fresh["needs_repair"]
    report["engine"] = fresh["engine"]
    report["driver"] = fresh["driver"]
    report["warnings"] = fresh["warnings"]
    return report
