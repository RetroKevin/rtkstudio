# Animation tracks: `.trk`, `.trx`, `.trm`

The `Tracks/` directory holds 917 `.trk`/`.trx` pairs (105 MB) plus 331 `.trm`
files. These are character animation tracks with their lip-sync timing.

**Status: fully resolved.** A `.trk` is a chunk stream, not a flat keyframe
array. All 917 files parse with zero errors and all 917 **re-serialise to a
byte-exact copy of the original**, so no byte of the format is unaccounted
for. See *Validation* for the numbers.

## `.trx` and `.trm` are plain text

No work needed. A `.trx` names its audio file, then gives a count and a frame
total, then integer pairs:

```
0005mix.wav
  21  369
   0   1
  28   2
  68   1
```

`.trm` is the same idea without the header line: a total, then pairs. The
pairs are frame-indexed state changes — given the `.wav` reference and the
small value range, these are lip-sync / viseme timings.

The `.trk` basename, the `.trx` basename and the `.wav` name all agree, and
all 917 pairs are present with no orphans on either side.

## `.trk` — a T3D FastFile

`.trk` shares the `02 3d` magic of `.t3d`, which is
[a variation of the DirectX SDK FastFile sample](https://wld-doc.github.io/formats/t3d_fast_file).
It is the engine's generic scene container; a `.trk` simply happens to hold
only track objects.

The loader chain in `t3dll.dll`, which is the authority for everything below:

| Function | Role |
|---|---|
| `FUN_10022970` | top level: header, then `name_count` chunks |
| `FUN_10022b80` | 28-byte header + XOR-scrambled name block |
| `FUN_10022c80` | the XOR decoder |
| `FUN_10022cf0` | raw read, from a handle or a FastFile view |
| `FUN_10022d60` | one chunk: 8-byte header, body, then dispatch on type |
| `FUN_100265b0` | pulls a chunk body into the scratch buffer |
| `FUN_10026610` | grows that buffer; floors it at the header's `0x10` field |
| `FUN_10024380` | chunk type `0x12` — a track definition (the keyframes) |
| `FUN_10024460` | chunk type `0x13` — a track |
| `FUN_10025430` | chunk type `0x1e` — wav info |
| `FUN_10025480` | chunk type `0x1f` — sound definition |
| `FUN_1007ee00` | `DefineTrack`, the runtime constructor the `0x12` handler calls |

### Overall layout

```
0x0000                      28 bytes   header
0x001c            name_bytes bytes     name block (XOR scrambled)
0x001c+name_bytes                      chunk stream: exactly name_count chunks
<end>                        4 bytes    ff ff ff ff terminator
```

The data region starts immediately after the name block — at offset **768**
for the 913 standard files (`28 + 740`). There is no gap. The previously
reported "588 zero-filled bytes" followed by keyframes at 1356 was an
artefact: the first chunk is the root joint's single-keyframe track
definition, which is almost entirely zeros, so the real chunk stream was
mistaken for padding.

### Header (28 bytes)

`FUN_10022b80` reads `0x1c` bytes and binds six words; the word at `0x18` is
read and discarded.

| Offset | Type | Value here | Meaning |
|---|---|---|---|
| `0x00` | char[4] | `02 3d 50 54` | magic, `"\x02=PT"` |
| `0x04` | u32 | `0x15500` | version; parser accepts `0x15500` and `0x15501` |
| `0x08` | u32 | 34 / 40 / 42 | **chunk count** (`FUN_10022970`'s loop bound) |
| `0x0c` | u32 | 0 | selects an alternate preload path; 0 in every shipped file |
| `0x10` | u32 | varies | **largest chunk payload size**, a buffer hint |
| `0x14` | u32 | 740 / 944 | size in bytes of the name block |
| `0x18` | u32 | 34 / 40 / 42 | unused by the loader; mirrors `0x08` |

`0x10` is **not** a record count. `FUN_10026610` uses it only as a floor when
sizing the scratch buffer:

```c
if (param_2 < *(uint *)(param_1 + 0x1c)) param_2 = *(uint *)(param_1 + 0x1c);
```

Checked directly: `0x10 == max(chunk payload size)` in **917/917** files.

> **Correction to earlier notes.** The relation
> `file_size == 1356 + field_0x10 * 16` does hold for all 917 files, and so
> does `field_0x10 == frames * 32 + 12`. Both are algebraic consequences of
> the real structure (one root joint with a single keyframe plus *N* joints
> with `frames` keyframes each), not evidence for a 16-byte record. The
> rejected "16 sections of `12 + frames*32`" model fit the file size exactly
> for the same reason. Size formulas that fit perfectly can still describe
> the wrong structure.

### Name block — XOR scrambled

The `name_bytes` immediately after the header are obfuscated with a repeating
8-byte XOR key (`FUN_10022c80`), held at `DAT_1010f728` in `t3dll.dll`:

```
95 3a c5 2a 95 7a 95 6a
```

A useful confirmation that the address is right: the constant stored
immediately after the key in the DLL is `02 3d 50 54`, the file magic the
parser compares against.

Decoded, the block is **a leading NUL byte**, then `name_count`
NUL-terminated strings, then slack left over from the allocation. The leading
NUL matters: chunks reference names by *byte offset*, and offset 0 therefore
reads as the empty string, which lets 0 serve as the "untagged" sentinel that
`FUN_10024460` tests for.

Only this block is scrambled. The chunk stream is stored plain — with the one
exception of the wav path inside a `0x1e` chunk, which is scrambled with the
same key.

### Name references

Every chunk field that names something is a signed int with three cases,
identically in `FUN_10024380`, `FUN_10024460` and `FUN_10025480`:

```c
if (ref < 0)  name = name_block - ref;                  // byte offset into the block
else          object = object_table[ref];               // 1-based index of an earlier chunk
// ref == 0 means "no tag" (FUN_10024460 guards on it)
```

The object table is the `local_1c` array `FUN_10022970` allocates as
`name_count * 4 + 4` and fills from index 1, so the indices are 1-based.

### Chunk stream

`FUN_10022970` runs exactly `name_count` iterations of `FUN_10022d60`:

```c
uVar4 = 1;
do {
  puVar2 = FUN_10022d60(&ctx);      // read one chunk
  local_1c[uVar4] = puVar2;         // record it in the object table
  uVar5 = uVar4 + 1;
  uVar4 = uVar5;
} while (uVar5 <= local_20);        // local_20 == header 0x08
```

`FUN_10022d60` reads an 8-byte chunk header and dispatches on the type:

| Offset | Type | Meaning |
|---|---|---|
| `0x00` | u32 | payload size in bytes, excluding this header |
| `0x04` | u32 | chunk type |

`FUN_10022d60` has 36 cases (`0x01`–`0x2c`: sprites, volumes, lights, sounds,
zones…). `.trk` files use only four of them. Measured over all 917 files:

| Type | Count | Handler | Meaning |
|---|---|---|---|
| `0x12` | 15601 | `FUN_10024380` | track definition — the keyframe array |
| `0x13` | 15601 | `FUN_10024460` | track — name + playback defaults + a def reference |
| `0x1e` | 1 | `FUN_10025430` | wav info (only `TK0048M`) |
| `0x1f` | 1 | `FUN_10025480` | sound definition (only `TK0048M`) |

So the chunk stream is a flat `TRACKDEF, TRACK, TRACKDEF, TRACK, …` sequence,
one pair per joint, in the same order as the name block — which is why
`name_count` is twice the joint count. **This is the answer to how the
keyframe block is divided: it is not divided by a table at all. Each joint's
keyframes live in their own chunk, and the chunk's own 8-byte header plus the
12-byte payload header carry the length.** The "tables of 32-bit integers"
seen between keyframe runs were these headers, read without knowing the
boundaries.

### Chunk `0x12` — track definition

Payload, per `FUN_10024380`:

| Offset | Type | Meaning |
|---|---|---|
| `0x00` | i32 | tag (name reference, always negative here) |
| `0x04` | i32 | 0 in all 15601 shipped definitions; purpose unknown |
| `0x08` | i32 | `frames`, the keyframe count |
| `0x0c` | f32[8] × `frames` | the keyframes |

so `payload_size == 12 + frames * 32`, verified for every definition in all
917 files.

The handler allocates `frames * 0x24` and scatters each 8-float disk record
into the 9-float runtime record:

```c
piVar5 = payload + 3;       // first disk record,    8 ints
piVar8 = runtime + 4;       // first runtime record, 9 ints, base = piVar8-4
do {
  piVar8[3]  = *piVar5;     // disk[0]   -> runtime[7]
  *piVar8    = piVar5[1];   // disk[1..3]-> runtime[4..6]
  piVar8[1]  = piVar5[2];
  piVar8[2]  = piVar5[3];
  piVar8[-4] = piVar5[4];   // disk[4..7]-> runtime[0..3]
  piVar8[-3] = piVar5[5];
  piVar8[-2] = piVar5[6];
  piVar8[-1] = piVar5[7];
  piVar8[4]  = 0;           // runtime[8] cleared
  piVar5 += 8;
  piVar8 += 9;
} while (...);
```

`t3dGetTrackDefinitionTransformation` then reads the runtime record as
`quaternion = [0..3]`, `translation = [4..6]`, `scale = [7]`. Composing the
two gives the **disk** record:

| Float | Meaning |
|---|---|
| `[0]` | scale |
| `[1..3]` | translation x, y, z |
| `[4..7]` | quaternion w, x, y, z |

> **Correction to earlier notes.** The on-disk order is *scale first*, not
> quaternion first. A record read starting at the quaternion looks like
> `quat(4), 1.0, translation(3)` because the `1.0` is the *next* record's
> scale — which is exactly the pattern previously recorded. The decompiler
> output settles the phase, and the 100% unit-quaternion rate below confirms
> it empirically.

Quaternions are **w-first**. `t3dVectorAngleToQuaternion` is conclusive:

```c
*param_5   = cos(angle * 0.5);          // q[0] = w
param_5[1] = sin(angle * 0.5) * axis_x; // q[1..3] = x, y, z
```

`t3dConjugateQuaternion` negates `[1..3]` and leaves `[0]`, and the diagonal
of `t3dQuaternionToMatrix` is `q0²+q1²-q2²-q3²`, `q0²-q1²+q2²-q3²`,
`q0²-q1²-q2²+q3²`, both of which agree.

### Angle unit (for the Euler helpers)

Not needed to read a `.trk`, since keyframes are quaternions, but worth
recording because the track accessors expose Euler angles. The engine's
native angle unit is **512 per revolution**:

- `t3dFloatSine(x)` computes `sin(x * 0.012271846)`, and `0.012271846 = 2π/512`
- `t3dEulerToQuaternionDeg` scales its inputs by `1.4222224 == 512/360`
- `t3dQuaternionToEulerDeg` scales its outputs by `0.703125 == 360/512`

`t3dEulerToQuaternion` also takes heading as `512.0 - heading`, so heading
runs in the opposite sense from pitch and roll.

### Chunk `0x13` — track

Payload, per `FUN_10024460`:

| Offset | Type | Meaning |
|---|---|---|
| `0x00` | i32 | tag (name reference; 0 means untagged) |
| `0x04` | i32 | reference to the track definition this track plays |
| `0x08` | i32 | flags |
| `0x0c` | i32 | update interval in ms — present only if `flags & 1` |

Flag bits, from the setters the handler calls:

| Bit | Setter | Meaning |
|---|---|---|
| `0x1` | `t3dSetTrackDefaultUpdateInterval` | the `0x0c` word is present |
| `0x2` | `t3dSetTrackDefaultReverse` | play reversed |
| `0x4` | `t3dSetTrackDefaultInterpolate` | interpolate between keyframes |

The handler also hardcodes `t3dSetTrackDefaultSpeed(track, 0x3f800000)`, i.e.
speed 1.0.

Measured: 14684 tracks carry `flags == 1` with interval 33 ms (≈30 fps); the
remaining 917 — exactly one per file, the root joint's — carry `flags == 0`
and so have a 12-byte payload. No shipped track sets the reverse or
interpolate bit.

### Chunk `0x1e` — wav info

Payload, per `FUN_10025430`:

| Offset | Type | Meaning |
|---|---|---|
| `0x00` | i32 | tag (name reference) |
| `0x04` | u16 | length of the path that follows |
| `0x06` | u8[len] | path, XOR-scrambled with the same key, then padded to 4 bytes |

Only `TK0048M.trk` has one; it decodes to
`K:\Krondor\Gamefiles\TRACKS\0048mix.wav`, a build-machine path.

### Chunk `0x1f` — sound definition

Payload, per `FUN_10025480`: `{i32 tag, i32 flags, i32, i32 wav_ref}` followed
by flag-gated optional words (volume, pitch, doppler…). Only `TK0048M.trk` has
one, with `flags == 0x104`. The optional-word decoding is implemented in the
loader but not in the reader, since there is a single instance to test against.

### Skeletons

| Joints | Chunks | Files |
|---|---|---|
| 17 | 34 | 913 |
| 20 | 40 | 3 |
| 20 + 2 sound chunks | 42 | 1 (`TK0048M`) |

The 17-joint rig, in file order: `DUMMY01` (root), `KIL`, `L-UPPERLE`,
`L-CAL`, `L-FOO`, `R-UPPERLE`, `R-CAL`, `R-FOO`, `TOPTORS`, `L-UPPERAR`,
`L-LOWAR`, `L-HAN`, `R-UPPERAR`, `R-LOWAR`, `R-HAN`, `NECK`, `HEAD`. The
20-joint variant appends `MAINSHADO`, `LFOOTSHAD`, `RFOOTSHAD`. Each tag is
the file stem concatenated with the joint name and `_TRACKDEF` / `_TRACK`
(`TK0005MHEAD_TRACKDEF`); `TK0048M` uses lowercase joint names.

### Frame counts

In every file the root joint (`DUMMY01`) has exactly **1** keyframe and all
remaining joints have the same count, which equals the frame total on line 2
of the sibling `.trx`. Verified 917/917. This is what makes
`header_0x10 == frames * 32 + 12` hold: the largest chunk is any non-root
definition.

## Validation

`tools/validate_tracks.py` over all 917 files:

```
files              : 917
parsed ok          : 917
parse errors       : 0
chunk types        : {0x12: 15601, 0x13: 15601, 0x1e: 1, 0x1f: 1}
chunks == name_cnt : 917/917
hdr 0x10 == max sz : 917/917
hdr 0x18 == name_cnt: 917/917
bytes after chunks : {4: 917}       <- the ff ff ff ff terminator
tail == ffffffff   : 917/917
tags match names   : 917/917
track->def resolved: 917/917
trackdef unk field : {0: 15601}
track flags        : {0: 917, 1: 14684}
update intervals   : {33: 14684, None: 917}
trx frame agreement: 917/917
shape (ndefs, root_frames, rest_uniform): {(17, 1, True): 913, (20, 1, True): 4}

quaternions        : 3239497
unit length (1e-3) : 3239497 (100.0000%)
worst |len-1|      : 0
scale histogram top: [(1.0, 3239497)]
frame-to-frame rot : 3223896 steps, 11902 over 30 deg (0.3692%)
```

**100.0000%** of the 3,239,497 extracted quaternions are unit length, with a
worst-case `|‖q‖ - 1|` of exactly 0.0 in float32. The earlier ~24.9%
background rate was the coincidence floor of the wrong alignment. Scale is
1.0 everywhere — nine distinct float bit patterns, all within 4.1e-6 of 1.0,
i.e. 1.0 plus exporter noise. 99.63% of consecutive keyframes rotate less
than 30°, which is what temporal continuity should look like.

`tools/roundtrip_tracks.py` re-serialises each parsed file from the decoded
fields — header, XOR-reconstructed name block, every chunk rebuilt from its
parsed values, terminator:

```
files              : 917
byte-exact rebuild : 917/917
```

Byte-exact on every file means there is no unmodelled padding, no skipped
field and no mis-sized record anywhere in the 105 MB.

### Tracks inside the `.t3d` archives

The 917 files above are the loose tracks in the install. Unpacking the `.t3d`
archives yields 801 more, which the same reader handles with no changes:

```
files              : 801
parsed ok          : 800
parse errors       : 1      <- Tracks/pivots.trk, a zero-byte archive entry
quaternions        : 557786
unit length (1e-3) : 557786 (100.0000%)
worst |len-1|      : 1.35e-07
```

That brings coverage to **1,717 of 1,717** non-empty tracks in the game. The
archived set exercises a wider range of rigs than the loose one — 15 to 35
joints, against the loose files' near-uniform 17 or 20 — which is useful
evidence that the layout is not overfitted to one skeleton.

## Tools

| Path | Purpose |
|---|---|
| `tools/rtktrack.py` | reader; exposes per-joint `Frame(quat, translation, scale)` arrays |
| `tools/validate_tracks.py` | the sweep above |
| `tools/roundtrip_tracks.py` | byte-exact re-serialisation check |
| `tools/export_tracks.py` | dumps every animation to `out/animations/*.json` |

`export_tracks.py` writes 917 JSON files (218 MB), one per animation: joint
list, and per joint the flattened `rotation_wxyz`, `translation_xyz`, scale,
update interval and flags, plus the `.trx` lip-sync keys.

## Remaining open

Small and bounded, but real:

- **`0x12` payload word at `0x04`.** Zero in all 15601 definitions, and
  `FUN_10024380` never reads it. Nothing in the shipped data distinguishes
  "reserved" from "a field no track happens to set."
- **Joint hierarchy.** A `.trk` carries per-joint local transforms and joint
  *names* but no parent links. The rig comes from the hierarchical sprite that
  the track is bound to (`t3dGetHierarchicalSpriteDagByTrackName`,
  `t3dSetDagTrack`), which lives elsewhere. Without it the tracks cannot be
  composed into world-space poses, which is also why the export is JSON rather
  than glTF — emitting glTF would require inventing a skeleton.
- **Coordinate convention.** The handedness and axis order are not pinned
  down, and nothing in the track data alone can settle them; it needs checking
  against rendered output. This does not affect extraction, which is pure
  quaternions.
- **`0x1f` optional fields.** Decoded in the loader, not in the reader; one
  instance in the whole game.
- **Version `0x15501`.** Accepted by the loader, used by no shipped `.trk`.
- ~~**`header 0x0c != 0`**~~ — **resolved.** It is the number of type-`0x22`
  world objects the file defines. Both arms of the branch in `FUN_10022970`
  fall into the same chunk loop; the non-zero arm only pre-allocates the
  object table, so the byte layout is unaffected and the guard could simply
  be dropped. `Worlds/rtkworld.wlx` is the only file in the game that sets
  it, out of 2,089 T3D FastFiles. See [`world-format.md`](world-format.md).
- **`header 0x18` is the name count, `0x08` the chunk count.** They are equal
  in all 917 `.trk`, which is why the two readings were indistinguishable
  here; `rtkworld.wlx` separates them at 2 chunks and 1 name.
