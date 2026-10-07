# RTKRES archive format

Recovered by decompiling `Rtlib32.dll`'s own loader. Every field below is
cited to the function that proves it, and the whole layout is validated
against the shipped data (see *Verification*).

## Volumes

| File | Role |
|---|---|
| `RTKRES.bin` | index: 476-byte header followed by the entry table |
| `RTKRES.000` | data volume 0 |

The entry descriptor carries a volume byte that selects a file handle from an
array (`ResLoadResource`: `*(HMMIO *)(handle + 4 + volume * 4)`), so the format
generalises to `.001`, `.002`, … This release ships only volume 0; all 8,108
entries reference it.

## Header (`RTKRES.bin`, 476 bytes)

Read by `FUN_1002e6e5`, which pulls the first `0x58` bytes, then the remainder.

| Offset | Type | Value here | Meaning |
|---|---|---|---|
| `0x00` | u16 | `0x4C37` | magic; loader rejects anything else |
| `0x02` | u16 | `476` | total header size |
| `0x06` | 80 bytes | — | a text field, empty here, running to `0x56` |
| `0x56` | u16 | `0x102` | version; loader accepts `2` or `0x102` |
| `0x15b` | u8 | `0xc1` | header checksum (version `0x102` only) |
| `0x164` | — | — | key resource directory, 15 × 8 bytes |

Version `0x102` — which is what this release ships — sums the header bytes
and requires the total to come out zero, so the checksum at `0x15b` has to be
resealed after any header change. Version `2` takes a different branch
entirely and skips the checksum. See [`rtkres-write.md`](rtkres-write.md).

**The version offset is a trap.** This document and `tools/rtkres.py` both
had it at `0x06` for a while. `FUN_1002e6e5` reads `0x58` bytes into a frame
based at `local_68` and tests `local_12`, which is buffer offset
`0x68 - 0x12 = 0x56`. Reading `0x06` instead yields `2` — the format's *other*
accepted version — so the wrong offset returned a legal-looking value and the
mistake survived. It was only caught by reading the DLL's own *writer*.

### Key resource directory

`ResLoadKeyResource(handle, n, &size)` accepts `n` in 0..14 and reads
`handle[n*2 + 0x101]` / `handle[n*2 + 0x102]`. The header is copied to handle
byte `0x2a0`, so on disk the directory begins at `0x164`; its 15 eight-byte
`(offset, size)` pairs end at exactly 476, the header size.

| Key | Offset | Size | Contents |
|---|---|---|---|
| 0 | 476 | 81,080 | entry table (÷10 = 8,108 entries) |
| 3 | 81,556 | 80 | 8-byte records |
| 4 | 81,636 | 2,414 | |
| 5 | 84,050 | 190,182 | **payload for every non-BITMAP resource** |
| 6 | 274,232 | 944 | |
| 7 | 275,433 | 117,354 | |
| 14 | 275,176 | 257 | |

Keys 1 and 2 are empty in this release; their record sizes would be `0x52` and
`0x2c` (`FUN_1002e112`, `FUN_1002e44e`).

## Entry table

`0x013CB8` = 81,080 bytes at 10 bytes per entry = **8,108 entries**, exactly
matching the 8,108 `#define`s in the shipped `RTKRES.h`.

The loader does not treat the table as one flat array. `FUN_1002d1ee` resolves
an id through a chunk pointer array:

```c
chunk[id / 0x1964] + (id % 0x1964) * 10
```

so entries are paged in blocks of `0x1964` (6,500). On disk they are
contiguous; the chunking only matters to the runtime allocator.

### Descriptor (10 bytes, little-endian)

| Offset | Type | Meaning |
|---|---|---|
| `0` | u8 | resource type code |
| `1` | u8 | volume index |
| `2` | u32 | offset within that volume |
| `6` | u32 | size in bytes |

## Type codes

The first byte is the resource *type*, not a flags field. Confirmed by
comparing its histogram over all 8,108 entries with the type comments in
`RTKRES.h` — every count matches exactly.

| Code | Type | Count |
|---|---|---|
| 1 | BITMAP | 5,089 |
| 15 | CEL | 921 |
| 16 | GROUP | 17 |
| 17 | PALETTE | 13 |
| 18 | QUEUE | 168 |
| 19 | SCRIPT | 39 |
| 20 | SPRITE | 1,509 |
| 21 | TEXT | 352 |

`ResLoadResource` branches on this byte. Type 1 (BITMAP) goes through the
decompressor set up by `DecompressBitmapInit`, so bitmap payloads are
compressed and need a second decoding pass (see `bitmap-codec.md`).

## Where each type's bytes actually live

This is the easiest thing to get wrong. **Only BITMAPs live in the data
volume.** The descriptor's offset field means two different things depending
on the type:

- **BITMAP** — a genuine byte offset into `RTKRES.000`.
- **Everything else** — an offset into key resource 5, which is resident in
  `RTKRES.bin`. These are the types in the `0x0D..0x16` window, which
  `ResLoadResource` resolves from an already-loaded block, reinterpreting the
  field as a pointer after relocation.

Reading a non-BITMAP entry at its offset in `RTKRES.000` silently yields
plausible-looking bitmap bytes rather than an error, so the mistake is easy to
miss. Two checks catch it:

- The 5,089 BITMAP entries tile `RTKRES.000` **contiguously and exactly** —
  no gaps, no overlaps, `max(offset + size)` equal to the volume size of
  48,872,098. There is no room left for the other 3,019 entries.
- All 3,019 non-BITMAP offsets are below 190,182, which is precisely the size
  of key resource 5.

## Verification

- 5,089 BITMAP entries tile the data volume exactly (see above)
- type histogram matches `RTKRES.h` exactly across all eight types
- all 13 PALETTE resources parse as 236 distinct RGBQUADs
- all 5,089 bitmaps decode to exactly `stride * height` bytes

## Names

`RTKRES.h` ships with the game and maps every id to its original name and
type, so extraction can emit `xMain` or `pIntfacePal` rather than numbers.

The archive also stores names independently: `FUN_1002e112` loads key resource
1 and divides its length by `0x52`, implying a name table of 82-byte records,
which `RtGetResName` indexes. This is a cross-check for releases that lack the
header file.

## Notes

The 39 SCRIPT resources total only 360 bytes, most of them 8 bytes each, so
they are hooks rather than a bytecode program. The game's actual scripting
lives in the `.def` files, which are plain text inside a gzip container (see
`pyro-container.md`).
