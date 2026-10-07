"""Reader for Return to Krondor .kgi files -- the save-game screenshot bitmap.

There is exactly one in the game, `Map.kgi` inside `SC.t3d`, and it is the
placeholder thumbnail the save/load list shows when a slot has no screenshot
of its own.  No header, no compression: 192 x 155 pixels of little-endian
RGB555, row-major, top-down.  192 * 155 * 2 == 0xE880 == 59520 bytes.

Every number above is read straight out of the engine:

    FUN_00528f6f   out/decompiled/RtK.c:195179  "DisplayDefaultGameShot".
                   Opens `Map.kgi` in `SC.t3d`, *requires*
                   t3dFastFileGetEOF() == 0xE880 (else
                   "DisplayDefaultGameShot: Map.kgi i..."), and reads it
                   straight into the 0xE880-byte global at DAT_0065cc68.
                   When the display is in pixel format 3 it instead takes a
                   FastFile view and runs it through FUN_005291a9.
    FUN_005291a9   out/decompiled/RtK.c:195264  the 0x7440-iteration
                   (29760-pixel) converter
                   `out = ((in & 0x7fe0) << 1) | (in & 0x1f)`,
                   i.e. RGB555 -> RGB565.  That it is applied on load for
                   format 3 and not for format 2 is what proves the file
                   itself is 555.
    FUN_00529380   out/decompiled/RtK.c:195367  the inverse, 565 -> 555,
                   used by "SaveCurrentGameShot" (FUN_0052922b:195282) which
                   writes the same 0xE880 bytes into a save file.
    FUN_00528ca0   out/decompiled/RtK.c:195059  "CaptureScreenShot".  Its
                   two nested loops are `for (y = 0; y < 0x9b; y++)` and
                   `for (x = 0; x < 0xc0; x++)`, writing consecutive u16s --
                   so the buffer is 0xc0 = 192 wide by 0x9b = 155 tall.  It
                   also gives the two pixel formats explicitly: format 2 uses
                   masks red 0x7c00 / green 0x03e0 / blue 0x001f (555),
                   format 3 uses red 0xf800 / green 0x07e0 / blue 0x001f
                   (565).
    FUN_00528eaa   out/decompiled/RtK.c:195107  the blitter; its source row
                   stride is `param_6 * 0x180`, and 0x180 == 384 == 192 * 2.
    FUN_005295d6   out/decompiled/RtK.c:195477  "ScreenShotDisplayProc",
                   which rejects any rectangle exceeding 0xc0 x 0x9b.

Line numbers are against out/decompiled/ as regenerated 2026-10-05; the
"// ===== FUN_00528f6f @ 00528f6f =====" banner is the stable anchor, and
tools/_lines.py re-derives any citation.

See docs/misc-formats.md.
"""

import struct
import zlib
from pathlib import Path

WIDTH = 0xC0           # FUN_00528ca0's inner loop bound
HEIGHT = 0x9B          # FUN_00528ca0's outer loop bound
PIXELS = WIDTH * HEIGHT        # 0x7440, the loop count in FUN_005291a9
SIZE = PIXELS * 2              # 0xE880, the size FUN_00528f6f insists on
ROW_STRIDE = WIDTH * 2         # 0x180, the stride in FUN_00528eaa


def to_565(pixel: int) -> int:
    """FUN_005291a9, verbatim."""
    return ((pixel & 0x7FE0) << 1 | pixel & 0x1F) & 0xFFFF


def to_555(pixel: int) -> int:
    """FUN_00529380, verbatim."""
    return (((pixel & 0xFFE0) >> 1) & 0xFFE0 | pixel & 0x1F) & 0xFFFF


class GameShot:
    """A 192x155 RGB555 image."""

    def __init__(self, path, data=None):
        self.path = Path(path)
        raw = self.path.read_bytes() if data is None else data
        if len(raw) != SIZE:
            raise ValueError("expected %d bytes, got %d" % (SIZE, len(raw)))
        self.raw = raw
        self.pixels = struct.unpack("<%dH" % PIXELS, raw)

    def rgb_rows(self):
        """Rows of (r, g, b) byte triples, 5-bit channels scaled to 8 bits."""
        for y in range(HEIGHT):
            row = self.pixels[y * WIDTH:(y + 1) * WIDTH]
            out = bytearray()
            for p in row:
                r = (p >> 10) & 0x1F
                g = (p >> 5) & 0x1F
                b = p & 0x1F
                out += bytes((r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2))
            yield bytes(out)

    def png(self) -> bytes:
        def chunk(tag, body):
            c = tag + body
            return (struct.pack(">I", len(body)) + c
                    + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

        scan = b"".join(b"\x00" + r for r in self.rgb_rows())
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT,
                                             8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(scan, 9))
                + chunk(b"IEND", b""))

    def stats(self):
        """Enough to tell a real image from noise."""
        distinct = len(set(self.pixels))
        # Mean absolute difference between vertically adjacent pixels, as a
        # fraction of the 5-bit range.  Real images are smooth; noise is not.
        total = 0
        for y in range(HEIGHT - 1):
            a = self.pixels[y * WIDTH:(y + 1) * WIDTH]
            b = self.pixels[(y + 1) * WIDTH:(y + 2) * WIDTH]
            for pa, pb in zip(a, b):
                total += abs(((pa >> 10) & 0x1F) - ((pb >> 10) & 0x1F))
        vdiff = total / float(WIDTH * (HEIGHT - 1))
        total = 0
        for y in range(HEIGHT):
            row = self.pixels[y * WIDTH:(y + 1) * WIDTH]
            for i in range(WIDTH - 1):
                total += abs(((row[i] >> 10) & 0x1F)
                             - ((row[i + 1] >> 10) & 0x1F))
        hdiff = total / float((WIDTH - 1) * HEIGHT)
        # Bit 15 is unused in 555.  If the file really is 555 it should be
        # clear everywhere; if it were 565 it would be set about half the time.
        bit15 = sum(1 for p in self.pixels if p & 0x8000)
        return {"distinct_colours": distinct,
                "mean_vertical_red_step": round(vdiff, 3),
                "mean_horizontal_red_step": round(hdiff, 3),
                "pixels_with_bit15_set": bit15}

    def __repr__(self):
        return "GameShot(%s, %dx%d)" % (self.path.name, WIDTH, HEIGHT)


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        g = GameShot(arg)
        print(g, g.stats())
        out = Path(arg).with_suffix(".png")
        out.write_bytes(g.png())
        print("wrote", out)
