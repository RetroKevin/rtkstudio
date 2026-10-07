"""Launch RtK.exe with the 640x480 frame pillarboxed on the monitor.

The installed executable is not modified. A 32-bit helper starts the process
and loads rtkframe.dll, which sizes a 4:3 window and paints black bars in the
spare space.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPER = HERE / "rtkframe.exe"
DLL = HERE / "rtkframe.dll"


def launch(exe: Path, args: list[str] | None = None, cwd: Path | None = None) -> None:
    """Start ``exe`` and return once the helper has injected the presenter."""
    exe = Path(exe)
    if not exe.is_file():
        raise FileNotFoundError(exe)
    if not HELPER.is_file() or not DLL.is_file():
        raise FileNotFoundError(
            "rtkframe.exe / rtkframe.dll are missing from %s" % HERE)
    work = Path(cwd) if cwd else exe.parent
    cmd = [str(HELPER), str(DLL), str(work), str(exe)]
    cmd.extend(args or [])
    proc = subprocess.run(cmd, cwd=str(work))
    if proc.returncode != 0:
        raise RuntimeError("frame presenter exited with %s" % proc.returncode)


def _default_exe() -> Path:
    # tools/rtkframe -> tools -> _decomp -> game install
    return HERE.parents[2].parent / "RtK.exe"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    exe = Path(argv[0]) if argv else _default_exe()
    rest = argv[1:] if argv else []
    try:
        launch(exe, rest, exe.parent)
    except (OSError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
