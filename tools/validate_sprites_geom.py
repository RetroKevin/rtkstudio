"""Validate simple-sprite (0x04/0x05) parsing against every 8-bit .adf.

Also counts the 3D-sprite and BMInfo chunks the viewer needs, but the
byte-exact bar is the one the plan set: every 0x04/0x05 rebuilds identically.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtkspx

ADF_ROOT = Path(__file__).resolve().parent.parent / "out" / "t3d"


def check(label, cond, detail=""):
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label,
                           ("  --  " + detail) if detail else ""))
    return 0 if cond else 1


def main() -> int:
    files = [p for p in sorted(ADF_ROOT.rglob("*.adf"))
             if "HiColor" not in p.parts]
    print("adf files (8-bit only):", len(files))

    n4 = n5 = n8 = n9 = n2c = 0
    bad4 = bad5 = 0
    dag_ok = dag_total = 0
    parse_fail = []

    for path in files:
        try:
            sf = rtkspx.SpriteFile(path)
        except Exception as exc:
            parse_fail.append("%s: %s" % (path.name, exc))
            continue
        n4 += len(sf.simple_defs)
        n5 += len(sf.simples)
        n8 += len(sf.sprite3d_defs)
        n9 += len(sf.sprite3ds)
        n2c += len(sf.bminfos)

        pos = sf.data_offset
        idx = 1
        for _ in range(sf.name_count):
            size, ctype = struct.unpack_from("<II", sf.raw, pos)
            body = sf.raw[pos + 8:pos + 8 + size]
            obj = sf._objects[idx]
            idx += 1
            if ctype == rtkspx.CHUNK_SIMPLEDEF and obj.to_bytes() != body:
                bad4 += 1
            elif ctype == rtkspx.CHUNK_SIMPLE and obj.to_bytes() != body:
                bad5 += 1
            pos = pos + 8 + size

        for d in sf.hsprite_defs:
            for dag in d.dags:
                if not dag.sprite_ref:
                    continue
                dag_total += 1
                if dag.sprite is not None:
                    dag_ok += 1

    failed = 0
    failed += check("parsed every .adf", not parse_fail, str(len(parse_fail)))
    failed += check("0x04 identity rebuild", bad4 == 0, "%d / %d" % (n4 - bad4, n4))
    failed += check("0x05 identity rebuild", bad5 == 0, "%d / %d" % (n5 - bad5, n5))
    failed += check("0x08 3D defs parsed", n8 > 0, str(n8))
    failed += check("0x09 3D instances parsed", n9 > 0, str(n9))
    failed += check("0x2c BMInfo parsed", n2c > 0, str(n2c))
    failed += check("dag sprite_ref resolves", dag_ok == dag_total,
                    "%d / %d" % (dag_ok, dag_total))
    for e in parse_fail[:8]:
        print("    ", e)
    print()
    print("simple defs 0x04 :", n4)
    print("simple inst 0x05 :", n5)
    print("3d defs     0x08 :", n8)
    print("3d inst     0x09 :", n9)
    print("bminfo      0x2c :", n2c)
    print("result           :", "PASS" if failed == 0 else "FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
