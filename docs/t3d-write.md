# T3D FastFile write path

`tools/rtkt3d_write.py` repacks a `.t3d` archive so modified members can be
substituted back in. It is the write counterpart to the read-only
`tools/rtkt3d.py`; read that and `docs/t3d-format.md` first for the layout
itself. This document covers only what the *writer* does: what it recomputes,
what it preserves verbatim, how the model was pinned down, and what is still
unmodelled.

The bar it hits: **identity rebuild is byte-exact for all 144 shipped
archives** (10,674 members, 382,064,045 bytes). See *Verification*.

## API

```python
def rebuild(src: Path, dst: Path, replacements: dict[str, bytes]) -> dict
```

`replacements` maps a member name, exactly as `rtkt3d` reports it, to its new
raw stored bytes. Unlisted members are copied through unchanged. Replacement
payloads may be larger, smaller, or zero-length. Returns a report dict:

| Key | Meaning |
|---|---|
| `src`, `dst` | paths used |
| `members` | member count (excludes the sentinel) |
| `replaced`, `copied` | how many members were substituted vs passed through |
| `missing` | sorted names in `replacements` that are not in the archive |
| `src_size`, `size`, `size_delta` | byte sizes before/after and the difference |
| `member_bytes_in`, `member_bytes_out` | payload totals, header excluded |
| `header_bytes`, `name_pool_bytes` | `16 + (members+1)*8`, and the name pool |
| `identical` | nothing was replaced and the size is unchanged |

Supporting entry points in the same module:

- `build(members, version=0x15700) -> bytes` — serialise `(name, bytes)` pairs
  into a whole archive. Input order is irrelevant; ordering is imposed.
- `rebuild_identity(src, dst)` — `rebuild` with an empty `replacements`.
- `verify(path, expected) -> list[str]` — re-open with the reader and diff
  against `{name: bytes}`; empty list means every member matched.
- `main()` — CLI: `python tools/rtkt3d_write.py src.t3d dst.t3d -r NAME=FILE`.

`rebuild` refuses a source that `rtkt3d.FastFile.validate()` flags, and
refuses variant B (no shipped archive uses it, so the writer has nothing to
validate against).

## What gets recomputed

Everything structural is rebuilt from the member list; nothing is patched in
place, and no bytes of the source header region are copied forward.

| Field | How it is derived |
|---|---|
| header `+0x08` count | `len(members) + 1` — the sentinel is counted |
| header `+0x0c` name_bytes | length of the freshly built name pool |
| directory offsets | running cursor from `data_start`, in directory order |
| directory name pointers | `(pool_start + pool_offset[name]) - entry_pos`, self-relative per `FUN_10017d90` |
| sentinel offset | the final cursor, i.e. the new file size |
| data region | members concatenated in directory order |

`data_start = 0x10 + count * 8 + name_bytes`, which is exactly the region
`FUN_10017750` maps (`MapViewOfFile(..., local_4 + 0x10 + local_8 * 8)`).
There is no padding and no alignment anywhere: members tile the data region
end to end, which is forced by `FUN_10017990` deriving a member's size as
`next_entry.offset - entry.offset`.

Because a member's size is only ever implied by the next entry's offset, there
is no size field to go stale. Growing or shrinking a payload shifts every
subsequent offset and the sentinel, and that is the whole of it — the header
region's *size* only changes if the set of names changes.

## What is preserved verbatim

| Field | Why |
|---|---|
| magic `02 3d ff ff` | `strncmp(hdr, DAT_1010f2c4, 4)` in `FUN_10017750` |
| version dword | copied from the source archive by `rebuild`. All 144 ship `0x15700`; `FUN_10017750` never reads it, so the writer has no basis for changing it. `build()` defaults to `0x15700`. |
| member payload bytes | the archive is a container; it does not interpret contents |
| member names | `rebuild` never renames, so the name pool and all name pointers come out identical to the source |

## The two sort orders

This is the part that is easy to get wrong, and the reason an identity rebuild
is worth running on all 144 archives rather than a sample.

**The directory is sorted by `name.lower()`.** The loader finds members with
`bsearch` (`FUN_10017990` → `FUN_100f4a00`) using the comparator
`FUN_10017a00`, which is `_stricmp`. MSVC's `_stricmp` folds to *lower* case.
Mis-sort the directory and lookups silently fail to find members.

**The name pool is sorted by `name.upper()`**, which is *not* the same
ordering. The two differ only where `_` (0x5f) is compared against a letter,
because `_` sorts before `a`..`z` but after `A`..`Z`. The loader never
constrains the pool order — any self-relative pointer into it works — so this
had to come from the shipped files.

139 of the 144 archives contain no name pair that can tell the two orderings
apart. The remaining 5 do:

| Archive | Directory order | Name-pool order |
|---|---|---|
| `Chars.t3d` | `A1FACE__.BMP` < `A1FACE_A.bmp` | `A1FACE_A.bmp` < `A1FACE__.BMP` |
| `HiColorChars.t3d` | same pair | same pair |
| `FX.t3d` | `B_fr0001.bmp` < `ball.spx` | `ball.spx` < `B_fr0001.bmp` |
| `HiColorFX.t3d` | same pair | same pair |
| `Tracks.t3d` | `a_ambie.trk` < `aire000.trk` | `aire000.trk` < `a_ambie.trk` |

All 5 follow the upper-case ordering, with no exceptions and no ambiguity (no
two names in any archive collide under either fold). Phase 4 of
`tools/validate_t3d_write.py` is a negative control that rebuilds everything
with the two obvious-but-wrong pool orderings and requires them to fail:

```
upper fold (the model)   byte-exact 144/144  broken: -
lower fold               byte-exact 139/144  broken: ['Chars.t3d', 'FX.t3d', 'HiColorChars.t3d', 'HiColorFX.t3d', 'Tracks.t3d']
directory order          byte-exact 139/144  broken: ['Chars.t3d', 'FX.t3d', 'HiColorChars.t3d', 'HiColorFX.t3d', 'Tracks.t3d']
```

So the field is load-bearing, and a sample-based test would have missed it.

Both folds are implemented as ASCII-only byte folds (`bytes.lower()` /
`bytes.upper()` on latin-1), matching C's `tolower`/`toupper` in the "C"
locale. `str.lower()`/`str.upper()` would be wrong — they fold non-ASCII and
expand some code points. Every name in every shipped archive is drawn from
`space # ' - . 0-9 A-Z _ a-z`, so the distinction never bites in practice, but
the writer accepts arbitrary latin-1 names and the byte fold keeps those sane.

## The sentinel

The last directory entry owns no data. Its offset dword is the file size,
which is what gives the last real member its length. Its name-pointer dword is
**0** in all 144 shipped archives, so the writer emits 0. A self-relative 0
points the "name" at the entry's own offset field, i.e. it is deliberate
filler, not a real pointer — nothing reads it, because
`t3dFastFileGetListOfFiles` and the bsearch both stop at `count - 1`.

## Edge cases handled

- **Extension-only names.** `Bex.t3d` holds a member literally named `.bex`
  (3,467 bytes). Extracted, its filename is just the extension, which Python's
  `glob` hides as a dotfile while `os.walk`/`Path.rglob` see it. Inside the
  archive it is an ordinary name with an empty stem, and it round-trips like
  any other; the sweep grows it, shrinks it and empties it explicitly.
- **Zero-byte members.** `Tracks.t3d`'s `pivots.trk` ships at 0 bytes. Two
  adjacent entries then share an offset, which the reader's monotonicity check
  permits. The writer can also shrink any member to 0, or grow a 0-byte member.
- **Duplicate names.** Rejected by `build()` with `T3DWriteError`, because the
  loader's case-insensitive bsearch could not distinguish them. No shipped
  archive has any.
- **Empty archive.** `build([])` emits a valid 24-byte archive: header plus a
  lone sentinel.

## Verification

`tools/validate_t3d_write.py` runs three phases over every `.t3d` in the game
install, writing only under `out/t3d-write/` (never into the install):

1. **Identity** — `rebuild` with `{}` and compare to the source byte for byte.
2. **Substitution** — for each archive pick the smallest, largest, median,
   first-in-directory, last-in-directory and any extension-only member;
   replace each with a grown, shrunk or emptied payload; rebuild; re-open with
   `rtkt3d.py` and require `validate()` clean and every member byte-identical
   to what was handed in. The report's own arithmetic
   (`header + name_pool + data == size`) must also close.
3. **Named cases** — `.bex` grown/shrunk/emptied, the zero-byte `pivots.trk`
   grown from nothing, 40 simultaneous substitutions in `Tracks.t3d` (one of
   the 5 upper-fold archives), and every member of the smallest archive
   replaced at once.
4. **Negative control** — the name-pool ordering check above; the two wrong
   models must not score 144/144, or phase 1 would prove nothing.

Current result:

```
identity    : 144/144 archives byte-exact  (10674 members)
substitution: 144/144 archives verified    (532 substitutions)
result      : PASS
```

Identity covers 382,064,045 bytes in and the same out. The 532 substitutions
break down as 178 grown, 177 shrunk, 177 emptied. Rebuilt archives were also
fed back through the reader's own CLI (`python tools/rtkt3d.py <files>`) as an
independent check: 40 rebuilt archives, 1,638 entries, `clean=40
problem/fail=0`.

## Not modelled

- **Variant B** (4-byte header, 17-byte directory entries, 13-byte inline
  names, loaded by `FUN_10017800`/`FUN_10017a20`/`FUN_10017db0`). No shipped
  archive uses it, so there is nothing to round-trip against and the writer
  refuses it rather than guessing. The 13-byte inline name field would cap
  names at 12 characters, which several shipped names exceed (longest is 29),
  so converting is not generally possible anyway.
- **The version dword.** Preserved, not derived. `FUN_10017750` ignores it
  entirely, so its meaning is unknown beyond "every shipped file says
  `0x15700`".
- **Why the packer used two different case folds.** The behaviour is pinned
  down exactly; the cause is not. Most likely the original tool sorted the
  name pool with an upper-casing comparator and the directory with `_stricmp`,
  but that is a guess and the writer does not depend on it.
- **Member *contents*.** This is a container writer only. Nested formats
  (`.trk`, `.spx`, `.bmp`, `.ovx`, `.bex`, DI\_ images) have their own
  encoders; `rebuild` takes whatever bytes it is given and does not validate
  that a replacement is a well-formed anything.
- **Inter-member ordering of payloads.** Data is emitted in directory order.
  Every shipped archive already stores it that way (verified: the data region
  tiles contiguously in directory order in all 144), so there is no observed
  case of a packer choosing a different data order.
