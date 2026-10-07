"""Validate tools/rtkworld.py, and establish how unusual rtkworld.wlx is.

Three passes:
  1. parse every file in Worlds/ that is a T3D FastFile with tools/rtkworld.py
  2. confirm tools/rtktrack.py still handles the .ldx files identically, so
     the new module is a superset and not a fork
  3. sweep every T3D FastFile in the install and in out/t3d for a non-zero
     header field 0x0c and for chunk types 0x21 / 0x22, to check the claim
     that rtkworld.wlx is the only file that exercises either
"""

import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtktrack  # noqa: E402
import rtkworld  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT.parent


def header(raw):
    if len(raw) < rtktrack.HEADER_SIZE or raw[:4] != rtktrack.MAGIC:
        return None
    return struct.unpack_from("<6I", raw, 4)


def chunk_types(raw, count, name_bytes):
    pos = rtktrack.HEADER_SIZE + name_bytes
    types = []
    for _ in range(count):
        if pos + 8 > len(raw):
            return types, pos, False
        size, ctype = struct.unpack_from("<II", raw, pos)
        if pos + 8 + size > len(raw):
            return types, pos, False
        types.append(ctype)
        pos += 8 + size
    return types, pos, True


def main():
    print("=== Worlds/ parsed with tools/rtkworld.py ===")
    ok = bad = 0
    for f in sorted((GAME / "Worlds").iterdir()):
        if not f.is_file() or header(f.read_bytes()) is None:
            continue
        try:
            w = rtkworld.World(f)
        except Exception as exc:  # noqa: BLE001
            print("  %-16s FAIL %r" % (f.name, exc))
            bad += 1
            continue
        ok += 1
        slack = sum(w.payload_slack.values())
        print("  %-16s f0c=%d chunks=%-3d names=%-2d objects=%d bsps=%d "
              "lightdefs=%-2d ends=%d/%d term=%s unconsumed=%d"
              % (f.name, w.field_0c, w.chunk_count, len(w.names),
                 len(w.objects), len(w.bsps), len(w.lightdefs),
                 w.end_offset, len(w.raw),
                 w.terminator == b"\xff\xff\xff\xff", slack))
    print("  parsed %d, failed %d" % (ok, bad))

    print()
    print("=== same .ldx files via tools/rtktrack.py (unchanged) ===")
    agree = disagree = 0
    for f in sorted((GAME / "Worlds").glob("*.ldx")):
        t = rtktrack.Track(f)
        w = rtkworld.World(f)
        same = (t.version == w.version and t.name_count == w.chunk_count
                and [c[2] for c in t.chunks] == [c[2] for c in w.chunks]
                and t.end_offset == w.end_offset
                and t.terminator == w.terminator)
        agree += same
        disagree += not same
    print("  identical header/chunk reading: %d agree, %d differ"
          % (agree, disagree))
    # rtktrack used to refuse this file on field_0c != 0. That guard was
    # dropped once the branch was shown not to affect the byte layout, so the
    # base reader should now get the container right on its own; only the
    # 0x21/0x22 chunk bodies need rtkworld.
    try:
        base = rtktrack.Track(GAME / "Worlds" / "rtkworld.wlx")
        ref = rtkworld.World(GAME / "Worlds" / "rtkworld.wlx")
        ok = (base.field_0c == ref.field_0c
              and base.names == ref.names
              and len(base.chunks) == len(ref.chunks))
        print("  rtktrack on rtkworld.wlx: accepted, agrees with rtkworld: %s" % ok)
    except ValueError as exc:
        print("  rtktrack on rtkworld.wlx: REGRESSION, rejected with %r" % (str(exc),))

    print()
    print("=== sweep for field_0c != 0 and chunk types 0x21 / 0x22 ===")
    roots = [GAME / "Worlds", GAME / "Tracks", ROOT / "out" / "t3d"]
    scanned = 0
    not_fastfile = 0
    f0c = Counter()
    types_total = Counter()
    exotic = []
    walk_ok = 0
    for root in roots:
        if not root.exists():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            raw = f.read_bytes()
            h = header(raw)
            if h is None:
                not_fastfile += 1
                continue
            scanned += 1
            version, count, field_0c, maxsz, name_bytes, f18 = h
            f0c[field_0c] += 1
            types, end, complete = chunk_types(raw, count, name_bytes)
            walk_ok += complete
            types_total.update(types)
            if field_0c or 0x21 in types or 0x22 in types:
                exotic.append((str(f.relative_to(GAME)), field_0c,
                               sorted(set(types))))
    print("  T3D FastFiles scanned      :", scanned)
    print("  non-FastFile files skipped :", not_fastfile)
    print("  chunk walks that complete  : %d/%d" % (walk_ok, scanned))
    print("  field_0c histogram         :", dict(f0c))
    print("  chunk type histogram       :",
          {hex(k): v for k, v in sorted(types_total.items())})
    print("  files with field_0c!=0 or a 0x21/0x22 chunk:")
    for e in exotic:
        print("     ", e)
    return 0 if bad == 0 and disagree == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
