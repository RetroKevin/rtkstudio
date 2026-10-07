# BITMAP resource format and codec

Reversed from `Rtlib32.dll`: `FUN_1002dd8e` (load), `FUN_1002d0c0` (expand),
`DecompressBitmapData` + `FUN_10041f2a` + `FUN_10041d60` (LZW), and
`FUN_1002f1ec` (scanline RLE).

**Status: complete.** All 5,089 BITMAP resources decode to exactly their
expected `stride * height` byte count.

## Resource header (24 bytes)

| Offset | Type | Meaning |
|---|---|---|
| `0` | u32 | width |
| `4` | u32 | height |
| `8` | u32 | flags |
| `12` | u32 | unknown (often a signed offset; hotspot-like) |
| `16` | u32 | unknown |
| `20` | u32 | the resource's own id |

Pixel data starts at offset 24. Rows are padded to a dword boundary:
`stride = (width + 3) & ~3`. Pixels are 8-bit palette indices.

`FUN_1002dd8e` copies these six dwords into a 0x24-byte runtime struct, which
is why the in-memory field offsets differ from the on-disk ones.

## Two codecs, selected by `flags & 0x80`

`FUN_1002d0c0` branches on bit 7, and it partitions the archive cleanly:

| `flags & 0x80` | Codec | Count |
|---|---|---|
| clear | chunked LZW | 210 |
| set | scanline RLE | 4,879 |

### Codec A — chunked LZW (`flags & 0x80 == 0`)

Three nested layers.

**Chunks.** A stream of u16 control words; the top 3 bits select the method
and the low 13 bits give the chunk's compressed length in bytes.

| Control | Method |
|---|---|
| `0x0000` | stored — copy `len` bytes verbatim |
| `0x4000` | LZW, 10-bit codes |
| `0x6000` | LZW, 11-bit codes |
| `0x8000` | LZW, 12-bit codes |
| `0xE000` | end of data |

**Sub-blocks.** Each compressed chunk holds sub-blocks, each prefixed with a
u16 length. `FUN_10041d60` clears the dictionary and bit state on entry, so
every sub-block is an independent LZW stream.

**LZW.** MSB-first, fixed code width for the chunk, dictionary seeded with the
256 literals and the next free code starting at `0x100`. There is no clear
code; the end code is `(1 << width) - 1`, and the dictionary freezes rather
than resetting once it reaches `(1 << width) - 2`. Entries are stored as a u16
prefix, a u8 suffix and a u8 length, which lets the decoder emit a string
backwards into the output and then write its first character at the front.

The original reads bits through a rotating table of eight u16 masks set up by
`FUN_10041a70`, which initially looks like obfuscation. It is not: those are
just the leftover-bit masks for each bit phase of the chosen code width. For
width 10 the high bytes cycle `00, 3f, 0f, 03`, matching leftovers of 0, 6, 4
and 2 bits; widths 9, 11 and 12 check out identically. A plain MSB-first bit
reader is therefore equivalent, which is what `tools/rtkbitmap.py` implements.

### Codec B — scanline RLE (`flags & 0x80` set)

The payload opens with a row offset table of `height` u16 entries
(`FUN_1002f1ec` starts reading at `data + height * 2`), followed by a
byte-oriented opcode stream:

| Opcode | Meaning |
|---|---|
| `0x00` | end of scanline; advance to the next row at `stride` |
| `0x01`–`0x7f` | run of `op` pixels, value in the following byte |
| `0x80`–`0xfe` | literal of `0xff ^ op` bytes |
| `0xff` | literal whose length is taken from the following byte |

The original unrolls runs and literals two bytes at a time, handling the odd
byte via the low bit — a pure optimisation with no effect on the output. The
bitmap ends when a second `0x00` follows a row terminator.

## Verification

Decoding every BITMAP resource and comparing against `stride * height`:

```
  flags & 0x80 set    4879  exact
  flags & 0x80 clear   210  exact
```

No mismatches and no errors across all 5,089 resources.

## Palettes

Pixels are 8-bit palette indices. PALETTE resources are plain RGBQUAD arrays:
944 bytes / 4 = **236 entries**, which is 256 less the 20 reserved Windows
system colours, so indices are offset by 10 to address the table. All 13
palettes parse as 236 fully distinct colours.

These resources are *not* in `RTKRES.000` — like every non-BITMAP type they
live in key resource 5 inside `RTKRES.bin`. Reading them at their offset in
the data volume yields bitmap bytes that look superficially palette-like; see
`rtkres-format.md`.

## Export

`tools/export_bitmaps.py` writes all 5,089 bitmaps as palette-indexed PNGs
(hand-rolled PNG writer, no Pillow dependency). Sampling 296 decoded bitmaps,
mean horizontal neighbour-equality is 0.576 against roughly 0.004 expected
from random noise over 236 colours, confirming real image content rather than
a plausible-looking misparse.

### There is no per-bitmap palette, by design

Nothing in the bitmap header names a palette, and nothing in SPRITE/CEL/GROUP
does either. The engine uses **one global palette**, loaded by
`ResLoadPalette` from key resource 6 — its handle fields map to header offset
`0x194`, which is directory entry 6 (`0x164 + 6*8`). The function returns
`size >> 2`, independently confirming 4 bytes per entry and 236 entries.

Key 6 is byte-identical to the `pIntfacePal` resource in all 236 slots, so
applying either gives the same, correct result.

Entries are `PALETTEENTRY` (`peRed, peGreen, peBlue, peFlags`), not `RGBQUAD`
— the fourth byte is 0 in every slot, matching `peFlags`. So the channel
order is plain RGB and needs no swap.

The other 12 PALETTE resources (`pMapPal`, `pBookSysPal`, `pDoorPuzzlePal`
and so on) are scene-specific alternates swapped in at runtime via
`SpriteSetPalette` / `SpriteChangePalette`; the sprite object holds its
palette array at runtime offset `0x23d0` (`SpriteGetPalette`). They are
context, not a static per-bitmap mapping.
