# The image write path

Every other image tool here reads. `tools/imagecodec.py` is the import side:
PNG in, `.di_` or RTKRES BITMAP out, so the art can leave the game, be edited
in any paint program, and come back as a file the engine's own loaders accept.

Standard library only — `zlib` and `struct`. There is no Pillow in this repo
and the PNG handling is hand-rolled, matching the export side in
`tools/preview.py`.

**Status: validated against every shipped image.** 1,585 of 1,585 `.di_`
files, 5,089 of 5,089 RTKRES BITMAP resources and 5,600 of 5,600 t3d `.bmp`
textures round-trip with their pixels byte-identical. Numbers in full under
*Validation*.

## The round trip

```
  .di_ / BITMAP  --rtkdib/rtkbitmap-->  indices + palette  --preview-->  PNG
                                                                          |
                                                                     paint program
                                                                          |
  .di_ / BITMAP  <--imagecodec--------  indices + palette  <--imagecodec--+
```

Read with the existing decoders, write with this module. Only the import
direction is new; the export direction already existed.

## API

```python
decode_png(data, check_crc=True) -> (width, height, palette | None, pixels)
quantize(width, height, rgb, palette) -> bytes
remap(pixels, src_palette, dst_palette) -> bytes
encode_di_(width, height, pixels, palette, level=9) -> bytes
encode_dib_bitmap(width, height, pixels, palette=None, flags=0,
                  field12=0, field16=0, res_id=0) -> bytes
png_to_indexed(data, palette, check_crc=True) -> (width, height, pixels)
nearest_index(palette, r, g, b) -> int
palette_block(palette) -> bytes          # the 1024-byte .di_ colour table
stride_for(width) -> int                 # (width + 3) & ~3
```

Palettes are lists of `(r, g, b)` tuples, as `rtkdib.CompressedDib.palette`
and `rtkres.parse_palette` already produce. Longer entries are accepted and
truncated to three channels, so a `PALETTEENTRY` 4-tuple works too. Pixels are
`bytes` of 8-bit palette indices, **top-down**, in every function here; the
bottom-up DIB layout is an encoding detail and never leaves `encode_dib_bitmap`.

`png_to_indexed` is the one call an importer actually needs: it reads a PNG and
returns pixels already on the target palette, picking `remap` or `quantize`
depending on what the PNG turned out to be.

## Which PNGs are accepted

| Colour type | Bit depths | Result |
|---|---|---|
| 0 greyscale | 1, 2, 4, 8, 16 | RGB triples, grey replicated |
| 2 truecolour | 8, 16 | RGB triples |
| 3 indexed | 1, 2, 4, 8 | one index per pixel, plus the PLTE |
| 4 greyscale + alpha | 8, 16 | RGB triples, alpha dropped |
| 6 truecolour + alpha | 8, 16 | RGB triples, alpha dropped |

All five scanline filters (none, sub, up, average, Paeth) are implemented.
Multiple `IDAT` chunks are concatenated, ancillary chunks are ignored, and an
unrecognised *critical* chunk is an error, as the PNG spec requires. Chunk CRCs
are verified; pass `check_crc=False` to read a file with broken ones.

Sub-byte greyscale is scaled to the full range the way PNG's own sample-depth
reduction does (1bpp to 0/255, 2bpp in steps of 85, 4bpp in steps of 17).
16-bit samples are truncated to their high byte.

Three things are deliberately not supported:

- **Interlaced (Adam7) PNGs are rejected** with a clear error. Re-save without
  interlacing; no paint program defaults to it.
- **Alpha is dropped.** Colour types 4 and 6 lose their alpha channel and
  `tRNS` is ignored, so a transparent pixel keeps whatever colour was stored
  underneath it. This is not laziness: the engine's formats are 8-bit indexed
  with no alpha channel at all, and transparency there is *a palette index the
  blitter skips*. It has to be expressed as that index. Painting with alpha and
  expecting the engine to honour it will not work; paint with the transparent
  index instead.
- **Colour management is ignored.** `gAMA`, `sRGB` and `iCCP` are read past.
  Sample values are taken at face value, which is what the 1998 art assumes.

## Getting onto the engine's palette

The engine runs an 8-bit indexed display, so an import has to end up as indices
into a palette that already exists. Two routes, depending on what came back out
of the PNG.

### `remap` — indexed in, indexed out

Each source index resolves to the destination entry closest to the colour it
stood for, via a 256-byte translation table applied in one pass. Identical
palettes give the identity table, which is the common case: export, edit
without touching the colour table, re-import, and nothing moves.

One subtlety worth stating plainly. An index whose colour is unchanged keeps
its own number **even when another slot holds the same RGB**. Duplicate slots
are not interchangeable to the engine — the blitter skips a specific index for
transparency — so collapsing them would change behaviour, not just numbering.
This matters here: 1,572 of the 1,585 backdrop palettes contain at least one
duplicated colour.

Indices past the end of `src_palette` have no colour to stand for and map to 0.

### `quantize` — truecolour in, indexed out

Nearest colour by squared distance in plain RGB, ties going to the lowest
index, so the mapping is deterministic. Colours already in the palette map onto
themselves exactly, which is what makes re-importing an unmodified export
lossless. Each distinct input colour is resolved once and cached, so the cost
tracks the number of distinct colours rather than the pixel count — a 640x480
backdrop quantizes in about 40 ms.

There is no dithering and no palette generation. Both are deliberate:

- The art is flat-shaded 8-bit drawn against a fixed palette. Dithering a
  region the palette already covers exactly only adds noise.
- The palette is not yours to choose. A `.di_` carries its own 256 colours, and
  a BITMAP carries none at all — the engine has one global palette with
  scene-specific alternates swapped in at runtime (`docs/bitmap-codec.md`, "There
  is no per-bitmap palette"). New colours cannot be smuggled in through the
  pixels.

So quantization is a safety net for art that strayed off-palette, not a
conversion pipeline. If you need colours the palette does not have, the palette
is what has to change, and writing `PALETTE` resources is not implemented here.

On the game's own truecolour textures — the 2,308 16- and 24-bit t3d `.bmp`
files, forced onto the interface palette, which is the worst case this codebase
contains — the RMS colour shift is 19.9 out of a possible 441. Every one of the
59,943 sampled pixels was verified against an independently brute-forced
nearest match.

## Writing `.di_`

`encode_di_` is a direct inversion of `ReadCompressedDib`; the layout is in
[`dib-format.md`](dib-format.md) and nothing about it is re-derived here.

- Pixels are `width * height` bytes, **top-down, no stride padding**. The
  loader hands `width * height` to zlib's `uncompress` as the output length, so
  there is no room for padding and no flip.
- The palette is 256 `PALETTEENTRY` records, `(red, green, blue, flags)`. Byte
  0 is red. The flags byte is written as 0, which is what all 1,585 shipped
  files have in all 256 slots — checked, not assumed.
- Short palettes are padded with black; the file always carries all 256 slots.
- The body is a plain zlib stream, level 9 by default.

One constraint comes from the loader rather than the format: `ReadCompressedDib`
compares the header's width and height against the dimensions the *caller*
expects and refuses the file on mismatch. **A replacement backdrop must keep the
dimensions of the one it replaces.** All 1,585 shipped files are 640x480.

## Writing RTKRES BITMAP resources

`encode_dib_bitmap` emits a type-1 BITMAP resource: the 24-byte header from
[`bitmap-codec.md`](bitmap-codec.md), then pixel data in the uncompressed
**stored** mode, which sidesteps the LZW encoder entirely.

### Why stored mode is safe

`DecompressBitmapData` in `Rtlib32.dll` is explicit about what it accepts:

```c
if ((uVar1 & 0xe000) == 0xe000) return param_4 == 0;       // end of data
if ((uVar1 & 0xe000) == 0) {                               // stored
  if (param_4 < (uVar1 & 0x1fff)) return false;
  CopyHugeBytes(param_3, puVar2, uVar1 & 0x1fff);
}
...
if (local_c == 0) break;                                   // -> return false
```

Three constraints follow, and the encoder satisfies all three:

- no chunk may be empty — a zero-length chunk falls into the `local_c == 0`
  break and fails the whole bitmap;
- no chunk may run past the remaining output;
- the stream must deliver **exactly** `stride * height` bytes before the end
  marker, or the `param_4 == 0` test fails and `FUN_1002d0c0` frees the bitmap
  and reports an error.

So the encoder slices the buffer into stored chunks of at most 8,191 bytes (the
control word's length field is 13 bits) and terminates with `0xE000`.

This is not an unused branch of the loader: **17 chunks in the shipped archive
are stored chunks**, totalling 17,580 bytes, and one of them is at the full
8,191-byte maximum. The engine does this to itself already.

### Orientation and padding

Rows are padded to a dword, `stride = (width + 3) & ~3`. `FUN_1002dd8e`
computes that itself — `*(uint *)(buf + 8) = *(int *)(buf + 4) + 3U &
0xfffffffc` — so the file never stores it, and the decompressor's expected
output length is `stride * height`.

The file is **bottom-up**: the last row of the image is the first row in the
file. Both of the engine's codecs fill a bottom-up Windows DIB and the buffer
goes straight to GDI with a positive `biHeight`. Getting this backwards flips
the image, and it has bitten this project once already, so it is a test rather
than a comment: see `bottom-up in the file` and `bottom-up survives the decoder`
in `tools/validate_imagecodec.py`.

`pixels` may be either tightly packed (`width * height`) or already
stride-padded (`stride * height`, what `rtkbitmap.decode_resource` returns).
Padded input is preserved byte for byte; tight input is padded with zeros. The
padding bytes are off-screen and the PNG does not carry them, so a bitmap that
goes out to PNG and back comes home with zeroed padding — which is why the
sweep checks the padded and the cropped buffers separately.

### Header fields and the palette

`flags` bit 7 selects the codec. It is always cleared on write, because clear
means the chunked stream and that is the branch which understands stored
chunks. The other flag bits and the three trailing header dwords (`field12`,
`field16`, `res_id`) are carried through unchanged, so a re-encoded resource
keeps whatever the original said; offsets 12 and 16 are still unidentified and
this is not the place to guess at them.

`palette` is accepted for symmetry with `encode_di_` and **ignored**. A BITMAP
resource has no colour table; the palette belongs to the scene.

## Validation

```
python tools/validate_imagecodec.py
```

Five sweeps, all counted rather than sampled. Current run, 42 seconds on eight
processes:

```
.di_ files             : 1585
  encode_di_ exact     : 1585 / 1585
  PNG round trip exact : 1585 / 1585
  exported PNG matches : 1527 / 1527
  quantize recovers    : 1581 exact, 4 same colour via a duplicate
  remap identity       : 1585 / 1585
  palettes with dupes  : 1572

BITMAP resources       : 5089 (rle 4879, lzw 210, skipped 0)
  stored mode exact    : 5089 / 5089
  header preserved     : 5089 / 5089
  PNG round trip exact : 5089 / 5089
  PNG -> resource exact: 5089 / 5089
  exported PNG matches : 5089 / 5089
  size: 94887724 bytes stored vs 48872098 shipped (1.9x)

t3d .bmp textures      : 5600 (8bpp 3292, 16bpp 2301, 24bpp 7)
  dimensions agree     : 5600 / 5600
  indexed -> BITMAP    : 5600 / 5600
  indexed -> .di_      : 3292 / 3292
  quantize is nearest  : 59943 / 59943 sampled pixels in 2308 truecolour files
  RMS colour shift     : 19.86 (RGB distance, 0..441)

foreign PNGs           : 118
  agree with Tk        : 118
  disagree             : 0
  pixels compared      : 58253
  variants (type,depth): t2/d8 x21, t3/d4 x7, t4/d8 x1, t6/d8 x89
  scanline filters     : none=19714, sub=1760, up=5419, avg=129, paeth=3851

synthetic checks      : 99
  passed              : 99

FAILURES: 0
```

What each sweep actually proves:

1. **`.di_`** — decode with `rtkdib`, re-encode, decode again: pixels *and*
   palette identical on all 1,585. Then the same pixels out to PNG and back
   through `decode_png`, which is what makes the editing workflow lossless
   rather than merely plausible. Then a quantize leg: render to truecolour and
   map back onto the same palette. 1,581 recover their exact indices; the other
   4 land on a different index holding an identical RGB, because their palette
   has duplicate colours and RGB alone cannot distinguish the slots.
2. **BITMAP** — decode with `rtkbitmap`, re-encode in stored mode, decode
   again: byte-identical including row padding on all 5,089, across both
   shipped codecs. The PNG leg additionally re-imports from the *cropped*
   PNG pixels, which is the path an edited file really takes.
3. **t3d `.bmp`** — the 3D engine's texture maps, a different asset class from
   the RTKRES resources and the source of the "5,600 bitmaps" count. Read
   through `preview.bmp_to_png`, so the PNG reaching `decode_png` is one this
   module did not write.
4. **Foreign PNGs** — 118 PNGs from Ghidra's own icons and documentation,
   compared pixel by pixel against Tk's PNG reader, an independent decoder that
   happens to ship with CPython. This is what really tests the scanline
   filters: the corpus uses all five, including 129 average-filtered and 3,851
   Paeth-filtered scanlines, and 4-bit indexed PNGs that nothing in the game
   uses.
5. **Synthetic** — one PNG per (colour type, bit depth, filter) combination, 13
   pixels wide so sub-byte rows end mid-byte, covering the variants no corpus
   here contains (16-bit samples, 1- and 2-bit depths, greyscale). Plus the
   inputs that must be *rejected*, the chunking constraints quoted from
   `DecompressBitmapData`, and the orientation assertions.

There is also a reverse check against the on-disk PNGs from earlier export
runs, folded into sweeps 1 and 2: `decode_png` reads back every PNG under
`out/png` and `out/dib` and is checked against the archive rather than against
itself. 5,089 of 5,089 and 1,527 of 1,527 agree; the 58 skipped backdrops are
the ones whose filename stems collide across t3d directories, where there is no
unambiguous PNG to compare against.

## Limitations

- **Stored mode is bigger.** Re-encoding the whole archive would take it from
  48.9 MB to 94.9 MB, 1.9x. No LZW or RLE *encoder* exists, so the only way to
  keep the original size is to leave a resource untouched. `.di_` has no such
  problem: it is zlib either way, and re-encoding all 1,585 at level 9 comes
  out slightly *smaller* than shipped (243.4 MB against 244.8 MB).
- **Nothing here repacks an archive.** These functions return bytes. Getting a
  new BITMAP back into `RTKRES.000` means rebuilding the volume and the entry
  table, which is a separate job; the 5,089 entries tile the volume exactly, so
  sizes cannot change in place.
- **Palettes are read-only.** Writing `PALETTE` resources is not implemented,
  so the available colours are fixed.
- **Alpha and interlacing**, as above.
- **Truecolour import can move indices between duplicate palette slots.** RGB
  alone cannot tell two identical slots apart, so if a transparency index
  shares its colour with a visible one, a truecolour round trip may swap them.
  Edit as an **indexed** PNG and `remap` preserves index identity exactly.
- **`decode_png` is pure Python**, so a multi-megapixel filtered PNG takes a
  second or two. Game-sized art is immediate.
