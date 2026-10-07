# Asset inventory

Every file type in the GOG v1.00.6 install, what each one is, and whether it
is readable yet. Regenerate with:

```powershell
python tools/inventory.py --game ".."
```

Each container below is identified from a signature check against the real
files, not inferred from the extension.

## The install, by size

| ext | files | bytes | container | status |
|---|---:|---:|---|---|
| `.t3d` | 144 | 382,064,045 | T3D FastFile archive | unpacked; payloads mostly unparsed |
| `.wav` | 1,460 | 283,477,722 | RIFF/WAVE | readable |
| `.trk` | 917 | 105,055,340 | T3D FastFile | solved |
| `.avi` | 31 | 57,198,736 | RIFF/AVI | readable, but **not original** |
| `.000` | 1 | 48,872,098 | RTKRES data volume | solved |
| `.exe` | 4 | 4,763,456 | PE image | decompiled |
| `.mab` | 53 | 3,275,106 | CostMap (text + grid) | readable |
| `.dll` | 6 | 2,151,240 | PE image | decompiled |
| `.def` | 26 | 1,120,577 | PyroTechnix gzip | solved — authored source |
| `.h` | 1 | 535,218 | text | `RTKRES.h`, resource names |
| `.trx` | 917 | 434,170 | text | lip-sync keys |
| `.bin` | 1 | 392,787 | RTKRES index | solved |
| `.trm` | 331 | 317,563 | text | solved |
| `.dat`, `.zip`, `.info` | 3 | 631,416 | Inno Setup / GOG | installer leftovers, not game data |
| `.txt`, `.tbl`, `.rtk` | 11 | 158,909 | PyroTechnix gzip | solved |
| `.ldx` | 12 | 3,224 | T3D FastFile | light/FX definitions |
| `.wlx` | 1 | 784 | T3D FastFile | **unsupported header branch** |

Roughly 891 MB in total. The `.ico`, `.ttf`, `.ini`, `.htm`, `.lnk`, `.log`
and `.inf` entries are ordinary Windows and GOG packaging files.

## Audio — `.wav`

Standard RIFF/WAVE throughout; no PyroTechnix wrapper and no custom codec.

| codec | files |
|---|---:|
| MS ADPCM, mono, 4-bit | 1,033 |
| PCM, mono, 16-bit | 416 |
| PCM, mono, 8-bit | 6 |
| PCM, stereo, 16-bit | 4 |
| MS ADPCM, stereo, 4-bit | 1 |

1,449 of 1,460 are 22,050 Hz. Both codecs are widely supported, so this
283 MB needs no reversing — the files play as they ship.

## Video — `.avi`

All 31 cutscenes carry the video FOURCC `xvid`.

**These are not the original 1998 assets.** XviD postdates the game by about
three years, so GOG re-encoded the cutscenes for the modern release. The
original Sierra-codec video is not present in this install and would have to
come from an original disc. Everything else in the install does appear to be
original data.

## Navigation — `.mab`

Pathfinding cost maps, and nearly self-documenting. Each file opens with an
ASCII header:

```
CostMap v2.05  4/7/98   NOTE: Tilesize = 18.000000
```

Three generator versions shipped: v2.05 (42 files), v2.01 (10) and v2.03 (1).
All 53 use a tile size of 18.0. The header is followed by a 53-byte binary
block of float bounds, then the grid itself, written as printable characters
— one per tile. `?` dominates (2.31 M tiles), then blank (748 K) and `@`
(7,331), with a thin tail of `"`, `a`, `b`, `!`, `#` and similar standing for
the rarer cost classes.

The grid is mostly legible in a text editor. The byte-to-cost mapping, and
the fact that a raw `0x00` is the common walkable floor, are in
[`scene-art-depth-collision.md`](scene-art-depth-collision.md).

## Bitmaps inside the `.t3d` archives

The 5,600 `.bmp` files unpacked from the archives are genuine uncompressed
Windows BMPs — no custom codec, unlike the `RTKRES` bitmaps.

| depth | files |
|---|---:|
| 8-bit | 3,292 |
| 16-bit | 2,301 |
| 24-bit | 7 |

All report compression 0. That is 88 MB of textures usable as-is.

## `.ldx` and `.wlx` share the track container

Both use the same T3D FastFile container as `.trk`: magic `\x02=PT`, version
`0x15500`. They live in `Worlds/`.

All 12 `.ldx` parse with the existing reader. They carry no track chunks —
these are light and effect definitions, named `TORCH_LIGHTDEF`, `FX_BLUE`,
`FX_GREEN`, `FX_LIGHTBLUE` and so on.

`rtkworld.wlx` is the single file in the game that sets header field `0x0c`
to a nonzero value, and the reader rejects it rather than guessing:

```
ValueError: field_0c=1 not supported
```

That is exactly the branch [`track-format.md`](track-format.md) lists as
unexplained because no shipped `.trk` exercises it — in `FUN_10022970` it
triggers an object-table preload sized `local_18 << 6`. The world file is the
test case that was missing.

## Inside the `.t3d` archives

Unpacking the 144 archives yields 10,675 files. Every type is identified by
signature; three of them turned out to need no reversing at all.

> **Counting trap.** Some archive members have an empty name, so they unpack
> to a file that is nothing but an extension — `out/t3d/bex/.bex` is a real
> 3,467-byte file with 27 entries. Python's `glob` treats a leading dot as a
> hidden file and silently skips these, which is how a `.bex` sweep returns
> 367 instead of 368. Use `os.walk` or `Path.rglob` when the count matters.

| payload | files | bytes | what it is | status |
|---|---:|---:|---|---|
| `.di_` | 1,585 | 244,769,520 | compressed DIB, 640x480 backdrops | **solved** |
| `.ovx` | 1,713 | 23,847,604 | scanline depth/coverage overlay | **solved** |
| `.bmp` | 5,600 | 87,554,634 | uncompressed Windows BMP | readable |
| `.trk` | 801 | 19,071,164 | animation tracks | solved |
| `.adf` | 192 | 5,461,480 | T3D FastFile — **holds the joint hierarchy** | **solved** |
| `.bex` | 368 | 792,256 | binary FX graphs | **solved** |
| `.spx` | 166 | 189,368 | T3D FastFile — sprites, no rig | parsed |
| `.ktx` | 237 | 49,345 | narration text with markup | **solved** |
| `.dib` | 10 | 26,604 | Windows BMP | readable |
| `.grx` | 1 | 3,564 | T3D FastFile — cursors | parsed |
| `.kgi` | 1 | 59,520 | save thumbnail, RGB555 192x155 | **solved** |

`.di_` was the largest unknown in the project and is now fully reversed —
see [`dib-format.md`](dib-format.md). It is a PNG-shaped signature over a
20-byte header, a 256-entry palette and a plain zlib stream; all 1,585 decode
exactly and export to `out/dib/`.

`.spx`, `.adf` and `.grx` are all T3D FastFiles — magic `\x02=PT`, version
`0x15500`, the same container as the solved `.trk`. The container layer of
`tools/rtktrack.py` parses them unchanged; only their chunk types differ.

`.ktx`, `.bex` and `.kgi` are covered in
[`misc-formats.md`](misc-formats.md): narration text with a six-tag markup
vocabulary, binary FX graphs, and the default save thumbnail as raw RGB555.

`.ovx` is also solved — see [`ovx-format.md`](ovx-format.md). It is not an
image but a run-length **depth buffer**: per scanline, a list of 16-byte
spans carrying `x_start`, `x_end` and an affine `1/w` depth line. The 640x480
in its header is an equality check against the screen, not an array size.
These pair with the `.di_` backdrops to let the engine occlude 3D characters
correctly against prerendered 2D art.

The joint hierarchy turned out **not** to be in `.spx`, the obvious-looking
candidate, but in the sibling `.adf` files as chunk type `0x10` — see
[`sprite-format.md`](sprite-format.md). All 166 `.spx` parse and carry only
chunk types `04 05 06 08 2c`, with zero hierarchy chunks. With the rig
recovered, all 917 animations now export as glTF 2.0.
