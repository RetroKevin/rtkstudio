"""Folder paths in RTKRONDOR.INI.

The game reads [Directories] with GetPrivateProfileStringA and prepends
those strings to filenames. It does not turn a relative path into a path
next to the executable. Steam often starts RtK.exe with a working
directory that is not the install, so TrackDir=.\\Tracks\\ cannot open
voice files and the game reports an unreadable .trx.

On Windows the working form is an absolute path with a trailing
backslash, which is what a GOG install already stores. Under Proton a
clean relative path (Tracks/, no .\\) is the form that resolves. Steam's
file verify restores the shipped ini, so a FixDirectories helper is
written beside it and can be run again.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Key, folder next to the install. The game requires the first six.
# SFXAudioDir may be empty and then falls back to AudioDir.
DIRECTORY_FOLDERS = (
    ("GameDataDir", "GameData"),
    ("WorldDir", "Worlds"),
    ("BGDir", "Bkgnd"),
    ("TrackDir", "Tracks"),
    ("AudioDir", "Audio"),
    ("SFXAudioDir", "Audio"),
    ("CinematDir", "Cinemats"),
)

BACKUP_NAME = "RTKRONDOR.INI.rtkstudio-bak"
HELPER_PS1 = "FixDirectories.ps1"
HELPER_BAT = "FixDirectories.bat"


def ini_path(game) -> Path:
    return Path(game) / "RTKRONDOR.INI"


def proposed_value(game, folder: str, platform: str | None = None) -> str:
    """The directory string the game should store for this install.

    absolute() is used on purpose. resolve() would follow a junction back
    to a real folder whose name contains a period.
    """
    platform = platform or sys.platform
    if platform == "win32":
        base = Path(game)
        if not base.is_absolute():
            base = base.absolute()
        return str(base / folder) + "\\"
    return folder + "/"


def dotted_component(path) -> str | None:
    """A path component that contains '.', other than '.' and '..'."""
    for part in Path(path).parts:
        if part in (".", "..") or part.endswith(":"):
            continue
        if "." in part:
            return part
    return None


def _reparse(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == 0xFFFFFFFF:
        return False
    return bool(attrs & 0x400)


def _same_dir(a, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def launch_root(game, clean_dir=None, create: bool = False) -> Path:
    """Folder the game should be started from.

    strrchr('.') in the engine treats the last period in a path as the
    file extension. A folder named GOG.com makes a conversation load
    D:\\GOG.trx instead of the voice file. A junction with no period in
    its path is a second name for the same install.
    """
    game = Path(game)
    if dotted_component(game) is None or sys.platform != "win32":
        return game
    parent = Path(clean_dir) if clean_dir else Path(game.anchor)
    for name in ("RtK", "ReturnToKrondor"):
        link = parent / name
        if link.exists():
            if _reparse(link) and _same_dir(link, game):
                return link
            continue
        if not create:
            return link
        if sys.platform != "win32":
            return game
        import subprocess
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(game)],
            capture_output=True, text=True)
        if made.returncode != 0 or not link.exists():
            continue
        return link
    if create:
        raise OSError(
            "Could not make a launch folder without a period next to %s" % parent)
    return game


def _strip(value: str) -> str:
    return (value or "").strip().strip('"').strip()


def _same(current: str, proposed: str) -> bool:
    a = _strip(current).replace("/", "\\").rstrip("\\").casefold()
    b = _strip(proposed).replace("/", "\\").rstrip("\\").casefold()
    return a == b


def _windows_absolute(value: str) -> bool:
    v = _strip(value).replace("/", "\\")
    if v.startswith("\\\\"):
        return True
    return len(v) >= 2 and v[0].isalpha() and v[1] == ":"


def _dir_exists(value: str) -> bool:
    v = _strip(value)
    if not v:
        return False
    try:
        return Path(v).is_dir()
    except OSError:
        return False


def _ok(value, game, folder: str, platform: str) -> bool:
    """True when the game can open this folder from the stored string.

    An absolute path that still exists is left alone, even when it is not
    the folder the studio was pointed at. A GOG ini that names another
    drive keeps working. A relative path is not ok on Windows, because
    Steam's working directory is not the install.
    """
    if value is None:
        return False
    v = _strip(value)
    if not v:
        return False
    if v.startswith("./") or v.startswith(".\\"):
        return False
    if platform == "win32":
        if dotted_component(v):
            return False
        return _windows_absolute(v) and _dir_exists(v)
    norm = v.replace("\\", "/").rstrip("/")
    if norm == folder and (Path(game) / folder).is_dir():
        return True
    if v.startswith("/") and _dir_exists(v):
        return True
    return False


def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), newline
    try:
        return raw.decode("utf-8"), newline
    except UnicodeDecodeError:
        return raw.decode("cp1252"), newline


def _lines(text: str, newline: str) -> list[str]:
    parts = text.split(newline)
    if parts and parts[-1] == "":
        parts.pop()
        return parts
    return parts


def _section_span(lines: list[str]) -> tuple[int | None, int | None]:
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "[directories]":
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        body = lines[j].strip()
        if len(body) >= 2 and body.startswith("[") and body.endswith("]"):
            end = j
            break
    return start, end


def _key_value(line: str) -> tuple[str, str] | None:
    body = line.strip()
    if not body or body.startswith(";") or body.startswith("#") or "=" not in body:
        return None
    key, value = body.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, value


def inspect_directories(game, platform: str | None = None, clean_dir=None) -> dict:
    """Describe [Directories] without writing."""
    game = Path(game)
    platform = platform or sys.platform
    root = launch_root(game, clean_dir=clean_dir, create=False)
    path = ini_path(game)
    entries = []
    present = {}
    if path.is_file():
        text, newline = _read_text(path)
        lines = _lines(text, newline)
        start, end = _section_span(lines)
        if start is not None:
            for line in lines[start + 1:end]:
                parsed = _key_value(line)
                if parsed:
                    present[parsed[0].casefold()] = parsed[1]
    for key, folder in DIRECTORY_FOLDERS:
        current = present.get(key.casefold())
        proposed = proposed_value(root, folder, platform)
        folder_path = game / folder
        exists = folder_path.is_dir()
        ok = _ok(current, game, folder, platform)
        entries.append({
            "key": key,
            "folder": folder,
            "value": current,
            "proposed": proposed,
            "matched": ok,
            "exists": exists,
        })
    needs = [e for e in entries if not e["matched"]]
    missing = [e["folder"] for e in entries if not e["exists"]]
    # SFXAudioDir shares Audio, so a missing folder is one folder.
    missing = list(dict.fromkeys(missing))
    return {
        "ini": str(path),
        "present": path.is_file(),
        "needs_fix": bool(needs),
        "missing_folders": missing,
        "entries": entries,
        "helper": str(game / HELPER_BAT) if platform == "win32" else None,
        "dotted": dotted_component(game),
        "clean_launch": str(root) if dotted_component(game) else None,
    }


def apply_directories(game, platform: str | None = None, backup: bool = True,
                      helper: bool = True, force: bool = False,
                      clean_dir=None) -> dict:
    """Point [Directories] at this install. Other ini sections stay as they are."""
    game = Path(game)
    platform = platform or sys.platform
    root = launch_root(game, clean_dir=clean_dir, create=True)
    report = inspect_directories(game, platform, clean_dir=clean_dir)
    path = ini_path(game)
    if not path.is_file():
        report["wrote"] = False
        report["error"] = "No RTKRONDOR.INI in %s" % game
        return report
    if not report["needs_fix"] and not force:
        report["wrote"] = False
        report["changed"] = []
        return report

    text, newline = _read_text(path)
    ended = text.endswith(newline)
    lines = _lines(text, newline)
    start, end = _section_span(lines)
    wanted = {key.casefold(): (key, proposed_value(root, folder, platform))
              for key, folder in DIRECTORY_FOLDERS}
    changed = []
    if start is None:
        block = ["[Directories]"]
        for key, folder in DIRECTORY_FOLDERS:
            value = proposed_value(root, folder, platform)
            block.append("%s=%s" % (key, value))
            changed.append(key)
        lines = block + [""] + lines
    else:
        seen = set()
        for i in range(start + 1, end):
            parsed = _key_value(lines[i])
            if not parsed:
                continue
            spec = wanted.get(parsed[0].casefold())
            if spec is None:
                continue
            key, value = spec
            seen.add(key.casefold())
            if not force and _ok(parsed[1], game, 
                                 dict(DIRECTORY_FOLDERS)[key], platform):
                continue
            if _same(parsed[1], value):
                continue
            lines[i] = "%s=%s" % (key, value)
            changed.append(key)
        insert_at = end
        for key, folder in DIRECTORY_FOLDERS:
            if key.casefold() in seen:
                continue
            value = proposed_value(root, folder, platform)
            lines.insert(insert_at, "%s=%s" % (key, value))
            insert_at += 1
            changed.append(key)

    if backup:
        bak = game / BACKUP_NAME
        if not bak.exists():
            bak.write_bytes(path.read_bytes())
            report["backup"] = str(bak)
    out = newline.join(lines)
    if ended or text.endswith(newline):
        out += newline
    encoding = "mbcs" if (platform or sys.platform) == "win32" else "utf-8"
    path.write_bytes(out.encode(encoding))
    if helper and platform == "win32":
        _write_helper(game, platform, root)
        report["helper_written"] = True
    report["wrote"] = True
    report["changed"] = changed
    fresh = inspect_directories(game, platform, clean_dir=clean_dir)
    report["needs_fix"] = fresh["needs_fix"]
    report["entries"] = fresh["entries"]
    return report


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _write_helper(game: Path, platform: str, root: Path) -> None:
    """A double-click repair that survives Steam verify deleting nothing extra
    and restoring the ini. The studio does not have to be open to run it."""
    if platform != "win32":
        return
    pairs = "\r\n".join(
        "  %s = %s" % (key, _ps_quote(proposed_value(root, folder, platform)))
        for key, folder in DIRECTORY_FOLDERS
    )
    ps1 = """$ErrorActionPreference = 'Stop'
$ini = Join-Path $PSScriptRoot 'RTKRONDOR.INI'
if (-not (Test-Path -LiteralPath $ini)) {
  throw "No RTKRONDOR.INI next to this script"
}
$want = [ordered]@{
%s
}
$enc = [System.Text.Encoding]::Default
$text = [System.IO.File]::ReadAllText($ini, $enc)
$newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
$lines = New-Object System.Collections.Generic.List[string]
foreach ($line in ($text -split "`r`n|`n", -1)) { $lines.Add($line) }
if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -eq '') { $lines.RemoveAt($lines.Count - 1) }
$start = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
  if ($lines[$i].Trim().ToLowerInvariant() -eq '[directories]') { $start = $i; break }
}
if ($start -lt 0) {
  $block = New-Object System.Collections.Generic.List[string]
  $block.Add('[Directories]')
  foreach ($key in $want.Keys) { $block.Add($key + '=' + $want[$key]) }
  $block.Add('')
  $lines.InsertRange(0, $block)
} else {
  $end = $lines.Count
  for ($j = $start + 1; $j -lt $lines.Count; $j++) {
    $body = $lines[$j].Trim()
    if ($body.StartsWith('[') -and $body.EndsWith(']')) { $end = $j; break }
  }
  $seen = @{}
  for ($i = $start + 1; $i -lt $end; $i++) {
    $body = $lines[$i].Trim()
    if (-not $body -or $body.StartsWith(';') -or $body.StartsWith('#') -or -not $body.Contains('=')) { continue }
    $name = $body.Split('=', 2)[0].Trim()
    foreach ($key in @($want.Keys)) {
      if ($name.Equals($key, [StringComparison]::OrdinalIgnoreCase)) {
        $lines[$i] = $key + '=' + $want[$key]
        $seen[$key] = $true
      }
    }
  }
  $at = $end
  foreach ($key in $want.Keys) {
    if (-not $seen.ContainsKey($key)) {
      $lines.Insert($at, $key + '=' + $want[$key])
      $at++
    }
  }
}
$out = ($lines -join $newline) + $newline
[System.IO.File]::WriteAllText($ini, $out, $enc)
Write-Host "Folder paths in RTKRONDOR.INI now point at this install."
""" % pairs
    (game / HELPER_PS1).write_bytes(ps1.replace("\n", "\r\n").encode("utf-8"))
    bat = (
        "@echo off\r\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0"
        + HELPER_PS1 +
        "\"\r\n"
        "if errorlevel 1 (\r\n"
        "  echo The folder paths were not updated.\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "pause\r\n"
    )
    (game / HELPER_BAT).write_bytes(bat.encode("ascii"))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", type=Path, required=True)
    ap.add_argument("--apply", action="store_true",
                    help="Rewrite the ini. Without this, only print the report.")
    args = ap.parse_args(argv)
    if args.apply:
        report = apply_directories(args.game)
    else:
        report = inspect_directories(args.game)
    for entry in report["entries"]:
        state = "ok" if entry["matched"] else "fix"
        print("%s [%s] %s -> %s" % (state, entry["key"], entry["value"], entry["proposed"]))
    if report.get("missing_folders"):
        print("missing folders: %s" % ", ".join(report["missing_folders"]))
    if args.apply:
        print("wrote" if report.get("wrote") else "unchanged")
    return 0 if not report.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
