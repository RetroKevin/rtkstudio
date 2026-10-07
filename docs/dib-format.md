# `.di_` — the compressed DIB

The 640x480 scene backdrops. 1,585 files, 244,769,520 bytes, the largest
single asset class in the game.

Nothing below is guessed from a hexdump. The whole layout came out of the
engine's own loader in one read.

## Finding the loader

The extension never appears in the binaries, so searching for `.di_` finds
nothing. The string `DI_` does, and it leads straight to an error message:

```
ReadCompressedDib: Compressed DI...
```

That sits inside `FUN_004fea14` in `out/decompiled/RtK.c`, which is
`ReadCompressedDib` itself. The name also resolves what the extension means:
a **compressed DIB**, the squeezed counterpart to the plain `.dib` files that
ship alongside.

Function names are quoted rather than line numbers throughout this document,
because regenerating `out/decompiled/` shifts every line while the name —
which encodes the address — stays put. To pull one up:

```powershell
python tools/show_func.py out/decompiled/RtK.c FUN_004fea14
```

## Layout

| offset | size | field |
|---|---|---|
| `0x00` | 8 | signature `89 44 49 5f 0d 0a 1a 0a` |
| `0x08` | u32 | width |
| `0x0c` | u32 | height |
| `0x10` | u32 | compressed size |
| `0x14` | 1024 | `PALETTEENTRY[256]` |
| `0x414` | *compressed size* | zlib stream |

Each field is pinned by a specific line of the loader:

- **20-byte header.** `t3dFastFileUseView(f, 0x14)` maps exactly `0x14` bytes
  before anything is read out of it.
- **Signature.** An 8-iteration byte compare against `DAT_005fc354`. It is
  deliberately PNG-shaped — `\x89PNG\r\n\x1a\n` with `PNG` replaced by `DI_`
  — which is why the same high-bit, CRLF and SUB guards appear. The file is
  *not* otherwise PNG-like: there are no chunks, and the dimensions that
  follow are little-endian, where PNG's would be big-endian.
- **Width and height.** Checked as `*(int *)(hdr + 8) == param_3` and
  `*(int *)(hdr + 0xc) == param_4`, the caller's expected dimensions. The
  loader refuses the file on mismatch rather than trusting the header.
- **Palette.** `t3dFastFileRead(f, param_5, local_8)` with `local_8 = 0x400`,
  i.e. 1024 bytes = 256 entries of 4 bytes.
- **Compressed size.** `t3dFastFileUseView(f, *(undefined4 *)(hdr + 0x10))`
  maps the remainder of the file in one view.
- **8 bits per pixel.** `local_14 = param_3 * param_4` is the output length
  handed to the decompressor — one byte per pixel, no stride padding.

## The decompressor is zlib

`FUN_004fec4a(param_6, &local_14, iVar3, size)` matches zlib's

```c
int uncompress(Bytef *dest, uLongf *destLen, const Bytef *source, uLong sourceLen);
```

argument for argument, with `destLen` preset to `width * height` and the
failure path logging `ReadCompressedDib: uncompress fa...`. Feeding the body
to `zlib.decompress` confirms it: a plain zlib stream, no custom framing.

## Channel order

The palette is `PALETTEENTRY`, so **byte 0 is red**.

This is the one field that cannot be settled by looking at the bytes — a zero
fourth byte is equally consistent with `RGBQUAD`, and reading it the wrong
way round produces an image that still looks plausible, merely wrong. The
call chain settles it instead. `FUN_004fe722` passes the palette buffer as
`DAT_00628d6c + 0x778`, and `FUN_0045ca70` hands that same pointer to
`SpriteSetPalette`. That is the identical path already traced for RTKRES
palettes in [`rtkres-format.md`](rtkres-format.md), where `FUN_10039acd`
builds the DIB colour table as `rgbRed = p[0]`, `rgbGreen = p[1]`,
`rgbBlue = p[2]`.

Unlike the RTKRES palettes, there is no 10-entry system-colour offset here:
the file carries all 256 slots and they are installed verbatim.

## Orientation

None needed. The decompressed buffer is already in top-down row order, so
unlike the RTKRES bitmaps — which fill a bottom-up Windows DIB and must be
flipped, see [`bitmap-codec.md`](bitmap-codec.md) — these export directly.

## Validation

```
python tools/rtkdib.py --src out/t3d --out out/dib
```

```
files        : 1585
decoded ok   : 1585
errors       : 0
dimensions   : {(640, 480): 1585}
PNGs written : 1585
```

Every file decompresses to exactly `width * height` bytes, and the header's
compressed size matches the remaining byte count exactly on all 1,585 — zero
slack, so there is no unmodelled padding or trailer. All are 640x480.

Spot-rendering confirms the colour decision independently: backdrops come out
as brown rock and torch-lit timber. A red/blue swap would turn those blue,
which is obvious on sight.

## Caller context

`FUN_004fe722` logs `Loading Dib: %s` and, on failure,
`Failed to load background dib`. So these are scene backdrops, which fits
1,585 files at exactly the game's 640x480 screen resolution.

The same function has a second branch calling `FUN_004fe906` for the
uncompressed case — the sibling loader for the plain `.dib` files.
