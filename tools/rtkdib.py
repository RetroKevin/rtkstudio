"""Reader and PNG exporter for `.di_`, the engine's compressed DIB.

`.di_` holds the 640x480 scene backdrops. The layout is not inferred -- it
comes straight out of `ReadCompressedDib`, which Ghidra names FUN_004fea14 in
`out/decompiled/RtK.c` (near line 171837). See `docs/dib-format.md`.
"""

import argparse
import struct
import zlib
from collections import Counter
from pathlib import Path

# The 8 bytes FUN_004fea14 compares against DAT_005fc354 before going on.
# Deliberately shaped like the PNG signature, with "DI_" swapped for "PNG".
SIGNATURE = b"\x89DI_\r\n\x1a\n"

# t3dFastFileUseView(f, 0x14) -- signature, width, height, compressed size.
HEADER_SIZE = 0x14

# t3dFastFileRead(f, dest, 0x400) -- PALETTEENTRY[256], 4 bytes each.
PALETTE_SIZE = 0x400
PALETTE_ENTRIES = PALETTE_SIZE // 4


class CompressedDib:
    """A decoded `.di_`: 8-bit indexed pixels plus the palette that goes with them."""

    def __init__(self, path: Path, data: bytes = None):
        self.path = Path(path)
        data = self.path.read_bytes() if data is None else data
        if not data.startswith(SIGNATURE):
            raise ValueError("bad signature %r" % data[:8])

        self.width, self.height, self.compressed_size = struct.unpack(
            "<III", data[8:HEADER_SIZE])

        pal = data[HEADER_SIZE:HEADER_SIZE + PALETTE_SIZE]
        if len(pal) != PALETTE_SIZE:
            raise ValueError("truncated palette")
        # PALETTEENTRY order. FUN_004fe722 passes this buffer to FUN_0045ca70,
        # which hands it to SpriteSetPalette -- the same path already traced
        # for RTKRES palettes, where the DIB colour table is built as
        # rgbRed = p[0], rgbGreen = p[1], rgbBlue = p[2]. So byte 0 is red.
        self.palette = [tuple(pal[i * 4:i * 4 + 3]) for i in range(PALETTE_ENTRIES)]

        body = data[HEADER_SIZE + PALETTE_SIZE:]
        if len(body) != self.compressed_size:
            raise ValueError("body is %d bytes, header says %d"
                             % (len(body), self.compressed_size))
        # FUN_004fec4a is zlib's uncompress(dest, &destLen, src, srcLen), with
        # destLen preset to width * height -- so the image is 8bpp.
        self.pixels = zlib.decompress(body)
        if len(self.pixels) != self.width * self.height:
            raise ValueError("decompressed to %d, expected %d"
                             % (len(self.pixels), self.width * self.height))

    @property
    def expected_size(self) -> int:
        return self.width * self.height

    def __repr__(self):
        return "<CompressedDib %s %dx%d>" % (self.path.name, self.width, self.height)


def _chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def write_png(path: Path, dib: CompressedDib) -> None:
    """Write an 8-bit palette-indexed PNG. No Pillow anywhere in this repo."""
    raw = bytearray()
    for y in range(dib.height):
        raw.append(0)  # filter type: none
        raw += dib.pixels[y * dib.width:(y + 1) * dib.width]

    plte = bytearray()
    for r, g, b in dib.palette:
        plte += bytes((r, g, b))

    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", dib.width, dib.height, 8, 3, 0, 0, 0))
    png += _chunk(b"PLTE", bytes(plte))
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    path.write_bytes(png)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, type=Path,
                    help="directory to scan for .di_ files")
    ap.add_argument("--out", type=Path, help="write PNGs here; omit to validate only")
    args = ap.parse_args()

    paths = sorted(args.src.rglob("*.di_"))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    ok = 0
    dims = Counter()
    errors = Counter()
    for p in paths:
        try:
            dib = CompressedDib(p)
        except Exception as exc:
            errors["%s: %s" % (type(exc).__name__, exc)] += 1
            continue
        ok += 1
        dims[(dib.width, dib.height)] += 1
        if args.out:
            write_png(args.out / (p.stem + ".png"), dib)

    print("files        : %d" % len(paths))
    print("decoded ok   : %d" % ok)
    print("errors       : %d" % sum(errors.values()))
    for msg, n in errors.most_common(5):
        print("   %5d  %s" % (n, msg))
    print("dimensions   : %s" % dict(dims))
    if args.out:
        print("PNGs written : %d -> %s" % (ok, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
