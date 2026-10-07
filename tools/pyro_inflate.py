"""Bulk-inflate Return to Krondor PyroTechnix container files.

Container layout: the ASCII signature "(c) 1998 PyroTechnix,Inc." followed by a
SUB byte (0x1a), then a raw gzip stream. Used by .def, .rtk, .tbl and friends.
"""

import argparse
import gzip
import sys
import zlib
from pathlib import Path

SIG = b"(c) 1998 PyroTechnix,Inc.\x1a"


def inflate(blob: bytes) -> bytes:
    """Return the decompressed payload, tolerating a truncated gzip tail."""
    if not blob.startswith(SIG):
        raise ValueError("missing PyroTechnix signature")
    payload = blob[len(SIG):]
    try:
        return gzip.decompress(payload)
    except (OSError, EOFError, zlib.error):
        # Some shipped files omit or corrupt the gzip trailer; salvage the
        # stream by decompressing until the inflater stops instead of failing.
        d = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
        out = d.decompress(payload)
        out += d.flush()
        if not out:
            raise
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, type=Path, help="game install root")
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--skip", default="_decomp", help="top-level dir name to ignore")
    args = ap.parse_args()

    game, out = args.game.resolve(), args.out.resolve()
    hits = misses = failures = 0
    total_in = total_out = 0

    for src in sorted(game.rglob("*")):
        if not src.is_file() or args.skip in src.relative_to(game).parts:
            continue
        with src.open("rb") as fh:
            if fh.read(len(SIG)) != SIG:
                misses += 1
                continue
        blob = src.read_bytes()
        try:
            data = inflate(blob)
        except Exception as exc:
            failures += 1
            print(f"FAIL {src.relative_to(game)}: {exc}", file=sys.stderr)
            continue

        dst = out / src.relative_to(game)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        hits += 1
        total_in += len(blob)
        total_out += len(data)
        print(f"{src.relative_to(game)}  {len(blob):>9,} -> {len(data):>10,}")

    print(
        f"\ninflated {hits} files ({total_in:,} -> {total_out:,} bytes), "
        f"{misses} non-container, {failures} failed"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
