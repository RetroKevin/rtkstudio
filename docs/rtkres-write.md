# RTKRES archive write path

`docs/rtkres-format.md` describes how the archive is read; this describes how
to write one back. Implemented in `tools/rtkres_write.py`, validated by
`tools/validate_res_write.py` (100 checks, all passing).

The read path was recovered from `Rtlib32.dll`'s loader. The write path did not
have to be guessed, because **the same DLL ships the original build tool's
writer**, and that is where the layout below comes from:

| Function | What it establishes |
|---|---|
| `ResCreateFile` | the header's constant fields: magic `0x4C37`, size `0x1dc`, signature `0x3233`, version `0x102` |
| `ResWriteKeyResource` | key resources are appended in call order; the key's offset is the file position at call time; a zero-length key stores offset 0 |
| `ResWriteIndexBufs` | the entry table is key 0, its size is `count * 10`, and the 4th argument becomes the spare-entry-slot field |
| `ResWriteHeader` → `FUN_1002f260` | the header carries a checksum byte at `0x15b` |
| `ResGetHeader` | the header is exactly `0x77` dwords = 476 bytes |

Reading the writer rather than only the loader is what surfaced the two fields
a reader never has to think about: the **header checksum** and the **key-5
segment end table**. Both are size fields in disguise, and both are silently
wrong if you only model what the loader consumes.

## API

```python
from pathlib import Path
import rtkres_write

report = rtkres_write.rebuild(
    src_index = Path("RTKRES.bin"),   # original index, opened read-only
    dst_index = Path("out/RTKRES.bin"),
    dst_volume = Path("out/RTKRES.000"),
    replacements = {4325: new_bytes},  # resource id -> new RAW stored form
)
```

`replacements` values are the resource's bytes **exactly as they are stored on
disk**; `rebuild` does not transcode. For a BITMAP that means the compressed
form with its 24-byte header, not decoded pixels — compare `ResLoadResource`,
which hands type 1 to the `DecompressBitmapInit` decompressor, whereas every
other type is used as read. Unlisted resources are copied through unchanged.
Replacements may be larger or smaller than the original.

Returned report keys: `entries`, `replaced`, `replaced_ids`, `volume_entries`,
`inline_entries`, `index_path`, `index_size`, `index_size_delta`,
`volume_paths`, `volume_sizes`, `volume_size`, `inline_size`,
`entry_table_size`, `key_order`, `keys`, `header_checksum`, `segment_count`,
`volume_name_ok`, `expected_volume_name`.

Also exported: `header_checksum(header)`, `seal_header(header)`,
`volume_path(index_path, n)`, and the exception type `ResWriteError`.
`python tools/rtkres_write.py SRC DST --replace ID=FILE` is a thin CLI over the
same call.

## What gets recomputed

Both payload pools are laid out from scratch in ascending resource id, which is
the order the original archive uses (verified: in both pools the on-disk offsets
are strictly ascending with id, with no gaps, no overlaps, and no two entries
sharing a region).

1. **`RTKRES.000` offsets.** The 5,089 BITMAP entries are packed back to back
   from offset 0. Nothing is aligned or padded — the original tiles the volume
   exactly and `max(offset + size)` equals the file size, so inserting padding
   would break that invariant.
2. **Inline offsets.** The 3,019 entries of types `0x0D..0x16` are packed back
   to back into a new key resource 5, each descriptor's offset being its
   position within that block.
3. **The descriptor table** (key 0). Ten bytes per entry: `u8` type, `u8`
   volume, `u32` offset, `u32` size. Type and volume are carried over
   untouched; offset and size are the recomputed values. `ResWriteIndexBufs`
   emits this in 6,500-entry (`0x1964`) chunks and `FUN_1002d1ee` reads it back
   through a chunk-pointer array, but on disk the chunks are contiguous, so a
   flat write reproduces it.
4. **The key resource directory** at `0x164`. Offsets are recomputed as a
   running file position starting at 476, matching `ResWriteKeyResource`'s
   "offset = current tell" rule. Empty keys keep `(0, 0)`.
5. **The key-5 segment end table** at `0x5c` — see below.
6. **The header checksum byte** at `0x15b` — see below.

## The header, field by field

Offsets are into the 476-byte header. The engine copies it to handle byte
`0x2a0`, so every citation below that uses a handle offset has `0x2a0`
subtracted.

| Offset | Size | Field | This release | Proof |
|---|---|---|---|---|
| `0x00` | u16 | magic | `0x4C37` | `ResCreateFile`, `FUN_1002e6e5` rejects anything else |
| `0x02` | u16 | header size | 476 | `ResCreateFile` writes `0x1dc` |
| `0x04` | u16 | signature | `0x3233` (`"32"`) | `ResCreateFile` |
| `0x06` | 80 | title: length byte, then two C strings | empty (`0x02`) | `ResGetTitle` reads handle `+0x2a6`; `ResSetTitle` builds it |
| `0x56` | u16 | version | `0x102` | `ResCreateFile` writes handle `+0x2f6` |
| `0x58` | u32 | entry id | 13 | `ResSetEntryId` writes handle `+0x2f8` |
| `0x5c` | 48×u32 | key-5 segment cumulative end offsets | `[190182]` | `FUN_1002e32f`, `ResLoadResource` |
| `0x11c` | u32 | key-5 segment count | 1 | `FUN_1002e32f` loops to handle `+0x3bc` |
| `0x120` | u32 | max fade colours | 236 | `ResGetMaxFadeColors` |
| `0x124` | u32 | max transparent colours | 0 | `ResGetMaxTransColors` |
| `0x128` | u32 | spare entry slots | 1000 | `ResWriteIndexBufs` arg 4; `ResCountResources` subtracts it |
| `0x12c` | u32 | string count | 2 | `ResCountStrings` |
| `0x130` | u32 | variable count | 14 | `ResCountVariables` |
| `0x134` | u32 | max screen messages | 274 | `ResGetMaxScrMsg` |
| `0x158` | u8 | build type | 0 | `ResGetBuildType` |
| `0x159` | 2 | unknown, zero here | 0 | copied by `FUN_1002e807` |
| `0x15b` | u8 | header checksum | `0xD5` | `FUN_1002f260` |
| `0x164` | 15×8 | key resource directory | see below | `FUN_1002e807` copies `0x78` bytes here |

### Correction: the version word is at `0x56`, not `0x06`

`rtkres.py` documents version at `0x06` and reads `2` there. That offset is
actually the first byte of the 80-byte title field, and the `2` is the title's
length byte (`ResSetTitle` stores `len(a) + len(b)`, i.e. 1 + 1 for two empty
strings). The real version word is at `0x56` and holds `0x102`:

- `FUN_1002e6e5` reads the first `0x58` bytes into a stack buffer based at
  `local_68` and branches on `local_12`, which sits `0x68 - 0x12 = 0x56` bytes
  into it.
- `ResCreateFile` writes `0x102` to handle `+0x2f6`, which is header `0x56`.

This matters for the writer, because `0x102` is the branch that **verifies the
header checksum**. Had the version really been `2`, the writer could have left
the checksum byte alone. (The `2` branch, `FUN_1002e807`, checks the sum too —
it just scatters a differently packed header — so either way the checksum is
load-bearing.) Both fields are preserved verbatim, so this is a documentation
correction rather than a behaviour change; `tools/rtkres.py` is owned elsewhere
and was not modified.

### Header checksum (`0x15b`)

`FUN_1002f260`, the tail of `ResWriteHeader`:

```c
header[0x15b] = 0;
for (i = 0; i < 0x1dc; i++) sum += header[i];
header[0x15b] = (sum ^ 0xff) + 1;       /* i.e. (-sum) & 0xff */
```

So all 476 header bytes sum to zero mod 256. The shipped header does
(`sum == 0`, byte `0x15b == 0xD5`), and `header_checksum()` independently
predicts `0xD5` from the header with the slot blanked — a 1-in-256 coincidence
otherwise, so the formula is confirmed from both the code and the data. The
writer recomputes it last, after every other header field is final.

### Key-5 segment end table (`0x5c`)

This is the field most likely to be missed, because the read path appears not
to need it. `rtkres.py` reads an inline resource at `inline_base + offset` and
that works — but it is not what the engine does.

`FUN_1002e32f` does not load key 5 as one block. It seeks to key 5's offset and
then carves it into `header[0x11c]` separately allocated **segments**, whose
cumulative end offsets are the `u32` array at `header[0x5c]`. `ResLoadResource`
then turns an inline offset into a pointer with:

```c
for (i = 0; i < seg_count; i++)          /* header[0x11c]     */
    if (seg_end[i] > offset) break;      /* header[0x5c+i*4]  */
if (i != 0) offset -= seg_end[i - 1];
ptr = seg_base[i] + offset;
```

This release has `seg_count == 1` and `seg_end[0] == 190182`, exactly key 5's
size, which collapses the whole thing to `seg_base[0] + offset` and is why the
flat read is correct here. But it means the table is key 5's size recorded a
second place. Grow the inline block without updating it and every inline
resource at or beyond the old end falls off the end of the loop with
`i == seg_count`, reads `seg_end[seg_count - 1]` as its base correction, and
resolves through an out-of-bounds segment pointer. The writer therefore sets
`header[0x5c] = len(new_key5)` whenever `seg_count == 1`.

### Key resource directory and physical order

The directory is 15 `(offset, size)` pairs. In this archive the blocks tile
`RTKRES.bin` perfectly with no gaps and no trailing slack:

| Block | Offset | Size | End |
|---|---|---|---|
| header | 0 | 476 | 476 |
| key 0 — entry table | 476 | 81,080 | 81,556 |
| key 3 | 81,556 | 80 | 81,636 |
| key 4 | 81,636 | 2,414 | 84,050 |
| key 5 — inline payload | 84,050 | 190,182 | 274,232 |
| key 6 | 274,232 | 944 | 275,176 |
| key 14 | 275,176 | 257 | 275,433 |
| key 7 | 275,433 | 117,354 | 392,787 = file size |

Note the physical order: **0, 3, 4, 5, 6, 14, 7** — key 14 sits between 6 and
7, not at the end. Because `ResWriteKeyResource` stamps the file position at
call time, that ordering is a fossil of the order the original build tool made
its calls in, and it is not recoverable from the key indices. The writer
replays it by sorting the keys on their *original* offsets rather than on their
index. Writing them in index order would still produce a loadable archive, but
not a byte-identical one, and byte-identity is the test that proves nothing
else is being silently regenerated.

## Preserved verbatim

- All header bytes other than the key directory, the segment end table and the
  checksum. That includes the title, entry id, version, signature, colour
  limits, string/variable counts, max screen messages, build type, the spare
  entry slot count, and the three bytes at `0x158`–`0x15a`.
- Key resources 3, 4, 6, 7 and 14, copied through as opaque blocks. Keys 1 and
  2 are empty in this release; the loader would read them as `0x52`-byte name
  records (`FUN_1002e112`) and `0x2c`-byte records (`FUN_1002e44e`). Since key 1
  is the name table, **renaming or adding resources is out of scope** — the
  writer substitutes payloads only and never changes the entry count.
- Each descriptor's type code and volume byte.

## Volume naming

`FUN_1002e528` derives volume filenames from the index name: strip the
extension, then `wsprintfA(p, ".%03i", volume)`. So `RTKRES.bin` implies
`RTKRES.000`. `rebuild` honours `dst_volume` as given, and reports
`volume_name_ok` / `expected_volume_name` so a caller that picks a name the
engine will not look for finds out rather than shipping an unloadable pair.
Entries with a volume byte other than 0 are written to siblings of
`dst_volume`; volume 0 always gets a file even if nothing lands in it.

## Validation

`python tools/validate_res_write.py` — 100 checks, all passing, writing under
`out/resrepack/`. The game install is only ever read.

1. **Checksum formula** — `header_checksum()` predicts the shipped `0x15b`
   byte (`0xD5`).
2. **Identity rebuild is byte-exact.** `rebuild(..., {})` reproduces
   `RTKRES.bin` (392,787 bytes) and `RTKRES.000` (48,872,098 bytes) with
   matching SHA-256 for both. Takes about 0.1 s.
3. **Header** — magic, size, signature, version `0x102`, header bytes summing
   to zero, segment end equal to the inline size, and keys tiling the index
   with no gaps.
4. **Substitutions**, five cases: a BITMAP grown 6,100 → 10,196 bytes; a BITMAP
   shrunk 2,269 → 756; a SPRITE grown 86 → 4,182; a CEL shrunk 16 → 5; and a
   mixed case touching six resources in both pools at once, including id 0, the
   last BITMAP and the last inline entry. For each case: the volume and index
   sizes move by exactly the expected deltas, the archive reopens with 8,108
   entries, **all 8,108 resources read back with the expected bytes** (untouched
   ones identical to the original, substituted ones equal to what was supplied),
   descriptors keep their type and volume and carry the new size, the header
   re-passes every check, both pools still tile exactly, and an identity rebuild
   *of the modified pair* is itself byte-exact.
5. **Decoders** — a PALETTE edited through `rebuild` decodes with the new
   colour via `rtkres.parse_palette`, the other 12 palettes decode unchanged,
   and 255 sampled BITMAPs decode to identical pixels through
   `rtkbitmap.decode_resource`.
6. **Guards** — out-of-range ids, negative ids and non-`bytes` payloads raise
   `ResWriteError`.

## Not modelled

- **Multi-segment key 5.** The format supports up to 48 segments
  (`0x5c`–`0x11b`), but this release ships one, so there is no evidence of how
  a build tool chose split points. `rebuild` raises `ResWriteError` if an
  archive declares more than one segment *and* the inline block changes size;
  an unchanged inline block passes through untouched.
- **Adding, deleting or renaming resources.** The entry count is fixed at the
  source archive's. The header reserves 1,000 spare entry slots
  (`header[0x128]`, consumed at runtime by `ResDynamicResource`), and keys 1/2
  would hold the name and variable tables, but all three are empty or unused
  here so nothing constrains how a new entry's name record should be written.
- **Multiple volumes.** The code splits entries by their volume byte and names
  extra volumes per `FUN_1002e528`, but all 8,108 entries here are volume 0, so
  only that path is exercised.
- **Version-2 headers.** `FUN_1002e807` unpacks a differently scattered header
  for version `2`; this release is `0x102` and the writer only reproduces that.
- **Payload semantics.** `rebuild` is byte-level. It does not compress a bitmap,
  validate a sprite, or check that a replacement is well-formed for its type —
  the bitmap codec (`docs/bitmap-codec.md`) and the per-type encoders own that.
- **The three bytes at `0x158`–`0x15a`** beyond `0x158` being the build type;
  they are zero here and copied through.
- **Keys 3, 4, 6, 7, 14 contents.** Record sizes are known for key 3 (8-byte
  records, `FUN_1002e2d6`) but the blocks are copied as opaque bytes, so a mod
  cannot yet edit whatever they hold.
