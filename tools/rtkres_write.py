"""Writer for the Return to Krondor RTKRES resource archive.

`tools/rtkres.py` reads the archive; this module writes one back out, so a
resource can be replaced with content of a different length and the whole
`RTKRES.bin` / `RTKRES.000` pair repacked around it.

The layout is taken from Rtlib32.dll's own *writer*, which ships in the game
and is decompiled in `out/decompiled/Rtlib32.c`. That is worth stressing: the
loader (`ResOpenFile`) only tells you how the bytes are consumed, but
`ResCreateFile`, `ResWriteKeyResource`, `ResWriteIndexBufs` and `ResWriteHeader`
tell you how they were *produced*, including two fields the read path never
needs to recompute:

  * `ResWriteKeyResource(handle, n, buf, len)` stores `len` in the key table
    and the *current file position* as the key's offset, then appends `buf`.
    Key resources are therefore laid down back to back in call order, and a
    key with `len == 0` gets offset 0 rather than a real position.
  * `ResWriteHeader` ends in `FUN_1002f260`, which zeroes header byte `0x15b`,
    sums all 476 header bytes, and stores `(-sum) & 0xff` there. Both header
    read paths verify it (`FUN_1002e6e5` for version `0x102`, `FUN_1002e807`
    for version `2`), so a rewritten header with a stale checksum byte is
    rejected by the engine even though every other field is correct.

Header map, by handle offset minus `0x2a0` (the header is copied to handle byte
`0x2a0`; `ResGetHeader`/`ResWriteHeader` move `0x77` dwords == 476 bytes):

| Offset | Size | Field | Proof |
|---|---|---|---|
| `0x00` | u16 | magic `0x4C37` | `ResCreateFile`, `FUN_1002e6e5` |
| `0x02` | u16 | header size, 476 | `ResCreateFile` writes `0x1dc` |
| `0x04` | u16 | signature `0x3233` (`"32"`) | `ResCreateFile` |
| `0x06` | 80 | title, `len` byte then two C strings | `ResGetTitle`, `ResSetTitle` |
| `0x56` | u16 | version, `2` or `0x102` | `FUN_1002e6e5` reads buffer `+0x56` |
| `0x58` | u32 | entry id | `ResSetEntryId` writes handle `+0x2f8` |
| `0x5c` | 48×u32 | key-5 segment cumulative end offsets | `FUN_1002e32f` |
| `0x11c` | u32 | key-5 segment count | `FUN_1002e32f`, `ResLoadResource` |
| `0x120` | u32 | max fade colours | `ResGetMaxFadeColors` |
| `0x124` | u32 | max transparent colours | `ResGetMaxTransColors` |
| `0x128` | u32 | spare entry slots (1000) | `ResWriteIndexBufs`, `ResCountResources` |
| `0x12c` | u32 | string count | `ResCountStrings` |
| `0x130` | u32 | variable count | `ResCountVariables` |
| `0x134` | u32 | max screen messages | `ResGetMaxScrMsg` |
| `0x158` | u8 | build type | `ResGetBuildType` |
| `0x15b` | u8 | header checksum | `FUN_1002f260` |
| `0x164` | 15×8 | key resource directory | `FUN_1002e807` copies `0x78` bytes here |

The version word is at `0x56`, not `0x06`: `FUN_1002e6e5` reads the first `0x58`
bytes into a stack buffer whose `local_12` sits `0x68 - 0x12 == 0x56` bytes in,
and `ResCreateFile` writes `0x102` to handle `+0x2f6`. This release stores
`0x102` there, so the engine takes the checksum-verifying branch. The `2` that
`rtkres.py` reports from offset `0x06` is the first byte of the title field.

Where payload lives, and what that costs the writer:

  * BITMAP (type 1) entries hold a real byte offset into `RTKRES.000`. All
    5,089 of them tile the volume exactly.
  * Types `0x0d..0x16` are resolved out of key resource 5 instead
    (`ResLoadResource` takes the `type < 0xd || type > 0x16` branch only for
    volume-resident entries). All 3,019 of them tile key 5 exactly.
  * `ResLoadResource`'s inline branch does not treat `entry.offset` as a plain
    offset into key 5. Key 5 is loaded as a list of separately allocated
    *segments* (`FUN_1002e32f`), and the offset indexes their concatenation:

        for i in range(seg_count):            # header[0x11c]
            if seg_end[i] > offset: break     # header[0x5c + i*4]
        if i: offset -= seg_end[i - 1]
        ptr = seg_base[i] + offset

    This release has `seg_count == 1` and `seg_end[0] == 190182`, exactly key
    5's size, which is why a flat read works. It also means **the segment end
    table is a size field in disguise**: resize key 5 without updating
    `header[0x5c]` and every inline resource past the old end resolves through
    the wrong branch.

In both pools the original file stores entries in ascending id order with no
gaps, overlaps, or aliasing, so writing them back in id order reproduces the
original byte for byte.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rtkres

HEADER_SIZE = 476          # ResCreateFile: 0x1dc
SIGNATURE_OFF = 0x04       # u16 0x3233
VERSION_OFF = 0x56         # u16, 2 or 0x102
SEG_ENDS_OFF = 0x5C        # 48 u32 cumulative segment ends for key 5
SEG_ENDS_MAX = 48          # 0x5c .. 0x11b
SEG_COUNT_OFF = 0x11C      # u32
CHECKSUM_OFF = 0x15B       # u8, FUN_1002f260
KEY_TABLE_OFF = rtkres.KEY_TABLE_OFF   # 0x164
KEY_COUNT = rtkres.KEY_COUNT           # 15
KEY_ENTRIES = rtkres.KEY_ENTRIES       # 0
KEY_INLINE = rtkres.KEY_INLINE         # 5
ENTRY_STRIDE = rtkres.ENTRY_STRIDE     # 10
COPY_CHUNK = 1 << 20


class ResWriteError(Exception):
    """The requested archive cannot be represented on disk."""


def header_checksum(header: bytes) -> int:
    """The byte that belongs at 0x15b so the header sums to zero mod 256.

    `FUN_1002f260`: zero the slot, sum all 0x1dc bytes, store `(sum ^ 0xff) + 1`.
    """
    if len(header) != HEADER_SIZE:
        raise ResWriteError(f"header is {len(header)} bytes, expected {HEADER_SIZE}")
    total = sum(header) - header[CHECKSUM_OFF]
    return (-total) & 0xFF


def seal_header(header: bytearray) -> bytearray:
    """Stamp the checksum byte in place and return the buffer."""
    header[CHECKSUM_OFF] = 0
    header[CHECKSUM_OFF] = header_checksum(bytes(header))
    return header


def volume_path(index_path: Path, volume: int) -> Path:
    """`FUN_1002e528`: strip the extension, then `wsprintfA(p, ".%03i", vol)`."""
    return Path(index_path).with_suffix(f".{volume:03d}")


def _entry_table(entries, offsets, sizes) -> bytes:
    """Pack the descriptor table: u8 type, u8 volume, u32 offset, u32 size."""
    out = bytearray(len(entries) * ENTRY_STRIDE)
    for i, e in enumerate(entries):
        struct.pack_into("<BBII", out, i * ENTRY_STRIDE,
                         e.type_code, e.volume, offsets[e.id], sizes[e.id])
    return bytes(out)


def rebuild(src_index: Path, dst_index: Path, dst_volume: Path,
            replacements: dict) -> dict:
    """Write a new RTKRES.bin/.000 pair, substituting resource id -> new bytes.

    `replacements` maps resource id to its new RAW stored form (already in
    whatever encoding that resource type uses on disk; this function does not
    transcode). Unlisted resources are copied through unchanged.
    Returns a report dict with counts and the new sizes.
    """
    src_index = Path(src_index)
    dst_index = Path(dst_index)
    dst_volume = Path(dst_volume)

    src = rtkres.ResFile(src_index)
    try:
        return _rebuild(src, src_index, dst_index, dst_volume, replacements)
    finally:
        src.close()


def _rebuild(src, src_index, dst_index, dst_volume, replacements):
    entries = src.entries
    count = len(entries)

    for rid, payload in replacements.items():
        if not isinstance(rid, int) or not 0 <= rid < count:
            raise ResWriteError(f"resource id {rid!r} outside 0..{count - 1}")
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise ResWriteError(f"replacement for id {rid} is not bytes")

    sizes = [len(replacements[e.id]) if e.id in replacements else e.size
             for e in entries]
    offsets = [0] * count

    # The engine derives volume names from the index name, so a mismatch here
    # produces a pair the game cannot open even though both files are correct.
    expected_volume = volume_path(dst_index, 0)
    volume_name_ok = dst_volume.name.lower() == expected_volume.name.lower()

    inline_ids, volume_ids = [], []
    for e in entries:
        (inline_ids if e.inline else volume_ids).append(e.id)

    # --- pool 1: the data volumes -------------------------------------------
    # Lay out in ascending id order, which is how the original was written.
    # Volume 0 always gets a file even if nothing lands in it, so the pair the
    # engine expects to find next to the index is never missing.
    cursors = {0: 0}
    for rid in volume_ids:
        vol = entries[rid].volume
        offsets[rid] = cursors.get(vol, 0)
        cursors[vol] = offsets[rid] + sizes[rid]

    volumes = {v: (dst_volume if v == 0 else volume_path(dst_volume, v))
               for v in cursors}
    for vol, path in volumes.items():
        path.parent.mkdir(parents=True, exist_ok=True)

    handles = {v: open(p, "wb") for v, p in volumes.items()}
    try:
        for rid in volume_ids:
            e = entries[rid]
            fh = handles[e.volume]
            if rid in replacements:
                fh.write(bytes(replacements[rid]))
            elif e.size:
                _copy_from_volume(src, e, fh)
    finally:
        for fh in handles.values():
            fh.close()

    volume_sizes = {v: p.stat().st_size for v, p in volumes.items()}
    for vol, expected in cursors.items():
        if volume_sizes[vol] != expected:
            raise ResWriteError(f"volume {vol}: wrote {volume_sizes[vol]} bytes, "
                                f"descriptors claim {expected}")

    # --- pool 2: the inline block (key resource 5) ---------------------------
    inline = bytearray()
    for rid in inline_ids:
        offsets[rid] = len(inline)
        if rid in replacements:
            inline += bytes(replacements[rid])
        elif sizes[rid]:
            inline += src.read_raw(entries[rid])
    inline = bytes(inline)

    # --- the index file ------------------------------------------------------
    key_blocks = {KEY_ENTRIES: _entry_table(entries, offsets, sizes),
                  KEY_INLINE: inline}
    for n, (off, size) in enumerate(src.keys):
        if n in key_blocks or size == 0:
            continue
        key_blocks[n] = src.raw[off:off + size]
        if len(key_blocks[n]) != size:
            raise ResWriteError(f"key {n} runs past the end of {src_index.name}")

    # ResWriteKeyResource records the file position at call time, so the key
    # table's offsets encode the order the original tool emitted them in --
    # 0, 3, 4, 5, 6, 14, 7 here, not sorted by key index. Replay that order.
    order = sorted((n for n, b in key_blocks.items() if b),
                   key=lambda n: src.keys[n][0])

    header = bytearray(src.raw[:HEADER_SIZE])
    body = bytearray()
    new_keys = [(0, 0)] * KEY_COUNT
    for n in order:
        new_keys[n] = (HEADER_SIZE + len(body), len(key_blocks[n]))
        body += key_blocks[n]
    for n in range(KEY_COUNT):
        struct.pack_into("<II", header, KEY_TABLE_OFF + n * 8, *new_keys[n])

    _fix_segments(header, len(inline), src)
    seal_header(header)

    dst_index.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_index, "wb") as fh:
        fh.write(header)
        fh.write(body)

    index_size = dst_index.stat().st_size
    if index_size != HEADER_SIZE + len(body):
        raise ResWriteError("short write on the index file")

    return {
        "entries": count,
        "replaced": len(replacements),
        "replaced_ids": sorted(replacements),
        "volume_entries": len(volume_ids),
        "inline_entries": len(inline_ids),
        "index_path": str(dst_index),
        "index_size": index_size,
        "index_size_delta": index_size - len(src.raw),
        "volume_paths": {v: str(p) for v, p in volumes.items()},
        "volume_sizes": volume_sizes,
        "volume_size": volume_sizes.get(0, 0),
        "inline_size": len(inline),
        "entry_table_size": len(key_blocks[KEY_ENTRIES]),
        "key_order": order,
        "keys": new_keys,
        "header_checksum": header[CHECKSUM_OFF],
        "segment_count": struct.unpack_from("<I", header, SEG_COUNT_OFF)[0],
        "volume_name_ok": volume_name_ok,
        "expected_volume_name": expected_volume.name,
    }


def _copy_from_volume(src, entry, out):
    """Stream one resource across so a 48 MB volume never lands in memory."""
    fh = src._volumes.get(entry.volume)
    if fh is None:
        fh = src._volumes[entry.volume] = src.volume(entry.volume).open("rb")
    fh.seek(entry.offset)
    left = entry.size
    while left:
        chunk = fh.read(min(left, COPY_CHUNK))
        if not chunk:
            raise ResWriteError(f"volume {entry.volume} ended inside resource "
                                f"{entry.id} (wanted {left} more bytes)")
        out.write(chunk)
        left -= len(chunk)


def _fix_segments(header: bytearray, inline_size: int, src) -> None:
    """Keep the key-5 segment end table consistent with the new key-5 size.

    `FUN_1002e32f` splits key 5 into `header[0x11c]` segments whose cumulative
    end offsets live at `header[0x5c + i*4]`, and `ResLoadResource` uses that
    table to turn an inline offset into a pointer. With a single segment the
    last cumulative end is just key 5's size.
    """
    seg_count = struct.unpack_from("<I", header, SEG_COUNT_OFF)[0]
    if seg_count > SEG_ENDS_MAX:
        raise ResWriteError(f"segment count {seg_count} exceeds the "
                            f"{SEG_ENDS_MAX}-slot table at {SEG_ENDS_OFF:#x}")
    if seg_count == 0:
        if inline_size:
            raise ResWriteError("key 5 has payload but the header declares "
                                "zero segments")
        return
    if seg_count == 1:
        struct.pack_into("<I", header, SEG_ENDS_OFF, inline_size)
        return
    # Multi-segment archives exist in the format but not in this release, so
    # there is no evidence for how a build tool chose the split points. Only
    # let it through when key 5 is byte-identical to the original.
    if inline_size != src.keys[KEY_INLINE][1]:
        raise ResWriteError(
            f"archive declares {seg_count} key-5 segments; resizing the inline "
            "block would need a re-segmentation rule this release does not "
            "demonstrate")


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Repack an RTKRES archive.")
    ap.add_argument("src_index", type=Path)
    ap.add_argument("dst_index", type=Path)
    ap.add_argument("--volume", type=Path,
                    help="output data volume (default: dst_index with .000)")
    ap.add_argument("--replace", action="append", default=[],
                    metavar="ID=FILE", help="substitute raw bytes for a resource")
    args = ap.parse_args(argv)

    replacements = {}
    for spec in args.replace:
        rid, _, path = spec.partition("=")
        replacements[int(rid)] = Path(path).read_bytes()

    volume = args.volume or volume_path(args.dst_index, 0)
    report = rebuild(args.src_index, args.dst_index, volume, replacements)
    for key in ("entries", "replaced", "index_size", "volume_size",
                "inline_size", "header_checksum"):
        print("%-16s %s" % (key, report[key]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
