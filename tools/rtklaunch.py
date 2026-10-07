"""Turn on RtK's developer checks in a *copy* of RtK.exe, and build the
command line that starts a chapter and scene.

DAT_006296e4 is a BSS dword. Nothing in the exe stores to it, so it stays
0 and FUN_0050b639 ignores -c, -s, -k, and -m. Every check is
`cmp dword ptr [0x6296e4], 0` followed by jz or jnz. Comparing with 1
while the dword stays 0 takes the same branch as a set flag.

The installed exe is never written. Callers pass the exe inside a build.
"""

from pathlib import Path

FLAG_ADDR = bytes((0xE4, 0x96, 0x62, 0x00))
CMP = bytes((0x83, 0x3D)) + FLAG_ADDR  # cmp dword ptr [0x6296e4], imm8


def _sites(blob: bytes):
    """(offset of the imm8, already_on) for each developer-flag compare."""
    out = []
    start = 0
    while True:
        i = blob.find(CMP, start)
        if i < 0:
            break
        imm = i + len(CMP)
        if imm >= len(blob):
            break
        nxt = blob[imm + 1] if imm + 1 < len(blob) else 0
        op = blob[imm]
        # 74/75 are short jz/jnz. 00 then 0F 84 is the near jz.
        near = (op == 0x00 and nxt == 0x0F and
                imm + 2 < len(blob) and blob[imm + 2] == 0x84)
        if op in (0x00, 0x01) and (nxt in (0x74, 0x75) or near or op == 0x01):
            out.append((imm, op == 0x01))
        start = imm
    return out


def game_binary(folder) -> Path:
    """The retail image in a folder.

    After the display patch, RtK.exe is a small launcher and the game is
    RtKGame.exe. An untouched GOG folder still has the game in RtK.exe.
    """
    folder = Path(folder)
    named = folder / "RtKGame.exe"
    if named.is_file() and named.stat().st_size > 1_000_000:
        return named
    plain = folder / "RtK.exe"
    if plain.is_file() and plain.stat().st_size > 1_000_000:
        return plain
    raise FileNotFoundError(
        "No game executable in %s. Expected RtKGame.exe, or RtK.exe larger than 1 MB."
        % folder)


def launch_binary(folder) -> Path:
    """What to start. The small RtK.exe forwards its arguments to RtKGame.exe."""
    folder = Path(folder)
    launcher = folder / "RtK.exe"
    if launcher.is_file():
        return launcher
    return game_binary(folder)


def enable_developer(exe, game_root) -> int:
    """Patch `exe` so the developer compares succeed. Returns sites changed."""
    exe = Path(exe).resolve()
    root = Path(game_root).resolve()
    installed = [p.resolve() for name in ("RtK.exe", "RtKGame.exe")
                 if (p := (root / name)).is_file()]
    if exe in installed:
        raise RuntimeError("refusing to patch the installed game")
    if exe.name.lower() not in ("rtk.exe", "rtkgame.exe"):
        raise RuntimeError(
            "developer patch expects the game executable, got %s" % exe.name)
    blob = bytearray(exe.read_bytes())
    sites = _sites(blob)
    if len(sites) < 30:
        raise RuntimeError(
            "%s does not have the expected developer compares (%d)"
            % (exe.name, len(sites)))
    changed = 0
    for imm, already in sites:
        if already:
            continue
        blob[imm] = 0x01
        changed += 1
    if changed:
        exe.write_bytes(blob)
    return changed


def launch_args(chapter=None, scene=None):
    """Argv tail. `-c9` is Chapter9. `-s70020` is scene S00070020."""
    args = []
    if chapter is not None and str(chapter) != "":
        args.append("-c%d" % int(chapter))
    if scene is not None and str(scene) != "":
        args.append("-s%d" % int(scene))
    return args
