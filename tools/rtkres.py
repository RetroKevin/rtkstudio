"""Reader for the Return to Krondor RTKRES resource archive.

Format recovered by decompiling Rtlib32.dll's own loader (ResOpenFile,
ResLoadResource, ResReadResourceData and friends). Field offsets below are
cited to the function that proves them.

  RTKRES.bin  index volume: 476-byte header, then the entry table.
  RTKRES.000  data volume 0. The entry's volume byte selects the volume, so
              the format generalises to .001, .002, ... which this release
              does not use.

Entry descriptors are 10 bytes and the loader walks them in chunks of
0x1964 (6500) entries:
    FUN_1002d1ee: chunk[id / 0x1964] + (id % 0x1964) * 10
"""

import struct
from pathlib import Path

MAGIC = 0x4C37          # FUN_1002e6e5: local_68 == 0x4c37
HEADER_SIZE_OFF = 0x02  # u16, total header bytes
# FUN_1002e6e5 reads 0x58 bytes into a frame starting at local_68 and tests
# the version as local_12, i.e. buffer offset 0x68 - 0x12. 0x06 begins an
# 80-byte field that runs to 0x56; reading the version there happens to yield
# 2, which is the format's *other* accepted version, so the wrong offset
# looked right. This release is 0x102.
VERSION_OFF = 0x56      # u16, loader accepts 2 or 0x102
ENTRY_STRIDE = 10
CHUNK = 0x1964

# ResLoadKeyResource indexes a directory of 15 "key resources", each an
# (offset, size) pair: handle[n*2 + 0x101] / handle[n*2 + 0x102]. The header is
# copied to handle byte 0x2a0, so on disk the directory starts at 0x164 and its
# 15 * 8 bytes run to exactly 476 -- the header size.
KEY_TABLE_OFF = 0x164
KEY_COUNT = 15
KEY_ENTRIES = 0   # key 0 is the entry table
KEY_NAMES = 1     # 0x52-byte records (FUN_1002e112)
KEY_INLINE = 5    # payload block for every non-BITMAP resource

# The first descriptor byte is the resource type. Confirmed by cross-checking
# its histogram over all 8108 entries against the type comments in RTKRES.h --
# every count matches exactly. ResLoadResource reads types outside 0x0d..0x16
# from the volume and decompresses type 1 via DecompressBitmapInit.
TYPE_CODES = {
    1: "BITMAP",    # 5089
    15: "CEL",      #  921
    16: "GROUP",    #   17
    17: "PALETTE",  #   13
    18: "QUEUE",    #  168
    19: "SCRIPT",   #   39
    20: "SPRITE",   # 1509
    21: "TEXT",     #  352
}
TYPE_BITMAP = 1
# ResLoadResource: types in this window are resolved from already-resident
# memory rather than by seeking the volume.
INLINE_LO, INLINE_HI = 0x0D, 0x16


class Entry:
    __slots__ = ("id", "type_code", "volume", "offset", "size", "name", "type")

    def __init__(self, rid, type_code, volume, offset, size):
        self.id = rid
        self.type_code = type_code
        self.volume = volume
        self.offset = offset
        self.size = size
        self.name = None
        self.type = TYPE_CODES.get(type_code, f"TYPE{type_code}")

    @property
    def compressed(self):
        return self.type_code == TYPE_BITMAP

    @property
    def inline(self):
        return INLINE_LO <= self.type_code <= INLINE_HI

    def __repr__(self):
        return (f"Entry(id={self.id}, name={self.name!r}, type={self.type}, "
                f"vol={self.volume}, off={self.offset:#x}, size={self.size})")


class ResFile:
    def __init__(self, index_path: Path):
        self.index_path = Path(index_path)
        self.raw = self.index_path.read_bytes()

        magic = struct.unpack_from("<H", self.raw, 0)[0]
        if magic != MAGIC:
            raise ValueError(f"bad magic {magic:#06x}, expected {MAGIC:#06x}")

        self.header_size = struct.unpack_from("<H", self.raw, HEADER_SIZE_OFF)[0]
        self.version = struct.unpack_from("<H", self.raw, VERSION_OFF)[0]

        self.keys = [
            struct.unpack_from("<II", self.raw, KEY_TABLE_OFF + n * 8)
            for n in range(KEY_COUNT)
        ]
        table_off, table_bytes = self.keys[KEY_ENTRIES]
        self.inline_base = self.keys[KEY_INLINE][0]
        self.count = table_bytes // ENTRY_STRIDE

        self.entries = []
        for i in range(self.count):
            o = table_off + i * ENTRY_STRIDE
            flags, volume, offset, size = struct.unpack_from("<BBII", self.raw, o)
            self.entries.append(Entry(i, flags, volume, offset, size))

        self._volumes = {}

    def volume(self, index: int) -> Path:
        """Volume n is the sibling file with extension .%03d."""
        return self.index_path.with_suffix(f".{index:03d}")

    def read_raw(self, entry: Entry) -> bytes:
        """Bytes exactly as stored, without decompression.

        Only BITMAPs live in the data volume -- those 5089 entries tile
        RTKRES.000 exactly, leaving no room for anything else. Every other
        type is resident in key resource 5, and its offset field is relative
        to that block, which is why ResLoadResource treats it as a pointer.
        """
        if entry.size == 0:
            return b""
        if entry.inline:
            start = self.inline_base + entry.offset
            return self.raw[start:start + entry.size]
        path = self.volume(entry.volume)
        fh = self._volumes.get(entry.volume)
        if fh is None:
            fh = self._volumes[entry.volume] = path.open("rb")
        fh.seek(entry.offset)
        return fh.read(entry.size)

    def close(self):
        for fh in self._volumes.values():
            fh.close()
        self._volumes.clear()


def parse_palette(data: bytes):
    """PALETTE resources are PALETTEENTRY arrays: 944 bytes == 236 entries.

    Channel order is red, green, blue, flags. The engine proves it without
    having to guess:

      - FUN_1001e8a9 calls ResLoadPalette straight into the middle of a
        PALETTEENTRY[256] staging buffer, then SpriteSetPalette copies all
        0x400 bytes verbatim to the sprite's palette array. FUN_10001a0c does
        the same for a scene palette swap, copying 0x3b0 == 944 bytes.
      - FUN_10039acd and FUN_10039cfc then build the DIB colour table from
        that array with `rgbRed = p[0]; rgbGreen = p[1]; rgbBlue = p[2]`.

    So resource byte 0 reaches GDI as red. Nothing in the chain swaps bytes.
    (A zero fourth byte would be equally consistent with RGBQUAD, so that
    observation alone settles nothing -- the assignment above is what does.)
    """
    n = len(data) // 4
    return [(data[i * 4], data[i * 4 + 1], data[i * 4 + 2]) for i in range(n)]


SYSTEM_COLOURS = 10
"""Palette index of the first game colour.

The 236 resource entries occupy indices 10..245, leaving the 20 reserved
Windows system colours at each end. Three independent confirmations:

  - FUN_10001a0c installs a swapped-in palette with
    `SpriteChangePalette(sprite, 10, 0xec, ...)` -- start 10, count 236.
  - FUN_1001e8a9 fills a PALETTEENTRY[256] from GetSystemPaletteEntries and
    then loads the resource at buffer offset 0x28 == 10 entries in.
  - FUN_10032dc7 marks exactly indices 10..0xf5 (245) as the game's own.
"""

# What GetSystemPaletteEntries returns for indices 0..9 and 246..255 on a
# 256-colour display: the Windows default static palette. FUN_1001e8a9 seeds
# the table with it and the resource never overwrites these 20 slots, so they
# are part of the colours the game actually displays. Reconstructed from the
# documented Windows palette rather than from the game's files.
WINDOWS_STATIC_PALETTE = {
    0: (0, 0, 0), 1: (128, 0, 0), 2: (0, 128, 0), 3: (128, 128, 0),
    4: (0, 0, 128), 5: (128, 0, 128), 6: (0, 128, 128), 7: (192, 192, 192),
    8: (192, 220, 192), 9: (166, 202, 240),
    246: (255, 251, 240), 247: (160, 160, 164), 248: (128, 128, 128),
    249: (255, 0, 0), 250: (0, 255, 0), 251: (255, 255, 0), 252: (0, 0, 255),
    253: (255, 0, 255), 254: (0, 255, 255), 255: (255, 255, 255),
}


def palette_to_256(entries):
    """Expand a 236-entry palette into the full 256-entry table the game sees."""
    table = [(0, 0, 0)] * 256
    for idx, rgb in WINDOWS_STATIC_PALETTE.items():
        table[idx] = rgb
    for i, rgb in enumerate(entries):
        idx = i + SYSTEM_COLOURS
        if 0 <= idx < 256:
            table[idx] = rgb
    return table


def load_names(header_path: Path):
    """Map resource id -> (name, type) using the shipped RTKRES.h."""
    import re
    text = Path(header_path).read_text(errors="replace")
    pattern = re.compile(r"#define\s+(\S+)\s+(\d+)\s*//\s*(\d+)\s+(\w+)")
    out = {}
    for name, rid, _echo, rtype in pattern.findall(text):
        out[int(rid)] = (name, rtype)
    return out
