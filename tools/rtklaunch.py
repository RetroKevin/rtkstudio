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


def enable_developer(exe, game_root) -> int:
    """Patch `exe` so the developer compares succeed. Returns sites changed."""
    exe = Path(exe).resolve()
    install = (Path(game_root) / "RtK.exe").resolve()
    if exe == install:
        raise RuntimeError("refusing to patch the installed RtK.exe")
    if exe.name.lower() != "rtk.exe":
        raise RuntimeError("developer patch expects RtK.exe, got %s" % exe.name)
    blob = bytearray(exe.read_bytes())
    sites = _sites(blob)
    if len(sites) < 30:
        raise RuntimeError(
            "RtK.exe does not have the expected developer compares (%d)" % len(sites))
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
