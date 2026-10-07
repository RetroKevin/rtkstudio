# `.ovx` — T3D binary overlay file (scanline coverage / depth buffer)

An `.ovx` is **not an image**. It is a precomputed, run-length **coverage buffer**
for one prerendered camera view: for each of the 480 scanlines, a list of
horizontal runs carrying a linear reciprocal-depth (`1/w`) ramp. The engine
hands the two resulting arrays straight to
`t3dSetRenderContextCoverageBuffer`, which is how actors walking through a
prerendered scene get occluded by its static geometry.

The engine's own name for the format is in its error strings: *"Error reading
binary overlay file signature"*, *"Invalid width in binary overlay file"*,
*"Error parsing binary overlay file"*.

* Reader / validator: `tools/rtkovx.py`
* Rendered depth maps: `out/ovx/*.png` plus `out/ovx/overlays.csv`
* Validation log: `out/logs/ovx-validate.txt`

---

## 1. Where it comes from

> **Line numbers rot; function names do not.** The `file:line` column below
> was accurate against the decompiled output as it stood when this was
> written. Regenerating `out/decompiled/` shifts every line — the pass that
> recovered calling conventions moved `FUN_004f5bcd` from line 165482 to
> 160557, for instance. The function name is the stable identifier, since it
> encodes the address, which never changes. To locate one:
>
> ```powershell
> python tools/show_func.py out/decompiled/RtK.c FUN_004f5bcd
> ```

| what | decompiled function | file:line |
|---|---|---|
| builds the member name `"C<n>" + <scene> + <view>` and appends `".ovx"` | `FUN_004e5829`, `FUN_004e58b6` | `RtK.c:153046`, `RtK.c:153072` |
| opens `C<n>.t3d`, maps the whole member with `t3dFastFileUseView(h, t3dFastFileGetEOF(h))` | `FUN_004fedbe` | `RtK.c:167105` |
| zeroes the two 480-entry arrays at `this+0x4bc38` (counts) and `this+0x4c3b8` (row pointers), then parses | `FUN_0043af73`, `FUN_0043afb1` | `RtK.c:37708`, `RtK.c:37732` |
| **the parser** | `FUN_004f5bcd` | `RtK.c:160559` |
| hands the two arrays to the renderer | `FUN_0043b014` → `t3dSetRenderContextCoverageBuffer` | `RtK.c:37334`, `RtK.c:60163` |
| samples one row at one column | `FUN_00454596` | `RtK.c:54556` |
| recovers a span's depth line (proves the anchor rule) | `FUN_004f5e39` | `RtK.c:160657` |
| merges two coverage buffers, rewriting the same records | `FUN_004f4a3f`, `FUN_004f5d67` | `RtK.c:165072`, `RtK.c:165549` |
| deep-copies a buffer: `t3dAllocateMemory(n << 4)` for `n` spans | `FUN_004f5af3` | `RtK.c:160505`, alloc at `:165458` |

`t3dFastFileUseView` maps the member and `FUN_004f5bcd` stores pointers
*into that mapping* (`*(uint **)(param_3 + y*4) = puVar3`). The engine never
copies or decompresses span data, so the on-disk record layout **is** the
in-memory layout. That is why there is no compression here, unlike `.di_`.

The filename pieces and the magic words themselves live in `.data`, so the
decompiled C only shows symbol names. `tools/ovx_consts.py` resolves them out
of the PE image:

```
0x005f9298 [.data] = 0x000026aa (9898)   DAT_005f9298  magic word 0
0x005f929c [.data] = 0x000026a9 (9897)   DAT_005f929c  magic word 1
0x005f62a8 [.data] = '.ovx'
0x005f9598 [.data] = 'Error reading binary overlay file signature'
0x005f95f0 [.data] = 'Invalid width in binary overlay file'
0x005f9618 [.data] = 'Invalid height in binary overlay file'
```

`0x5f9298` is the head of a four-word sentinel table
`{0x26aa, 0x26a9, 0x26a8, 0x26a7}`. The parser only uses the first two; the
fourth, `0x26a7`, is what the authoring tool writes as the end-of-rows marker
(see §2). `0x26a8` is unused by any decompiled code.

---

## 2. Byte layout

All little-endian. `u32`/`i32` = 32-bit integer, `f32` = IEEE-754 single.

### Header — 20 bytes

| off | type | value | proof |
|---|---|---|---|
| `0x00` | u32 | `0x26aa` | `if (*param_1 == DAT_005f9298)`, `RtK.c:165490`; else *"…file signature"* |
| `0x04` | u32 | `0x26a9` | `if (param_1[1] == DAT_005f929c)`, `RtK.c:165491` |
| `0x08` | u32 | **width**, must be `0x280` = 640 | `if (param_1[2] == 0x280)`, `RtK.c:165492`; else *"Invalid **width** in binary overlay file"* (`RtK.c:165513`) |
| `0x0c` | u32 | **height**, must be `0x1e0` = 480 | `if (param_1[3] == 0x1e0)`, `RtK.c:165493`; else *"Invalid **height** …"* (`RtK.c:165508`) |
| `0x10` | u32 | `y` — index of the first populated scanline; `>= 480` means "no rows" | `local_18 = *puVar3` where `puVar3 = param_1 + 4`, `RtK.c:165494-165496` |

Note the width/height guards are *equality* tests against the screen
resolution, not a general size field. There is no variant at another
resolution in the shipped data.

### Row list — repeated while `y < 480`

| off | type | meaning |
|---|---|---|
| `+0` | u32 | `n`, number of span records in row `y` |
| `+4` | `n × 16` | the span records |
| `+4+16n` | u32 | `y` for the *next* populated row; `>= 480` terminates the walk |

Straight from `RtK.c:165496-165504`:

```c
puVar3 = param_1 + 4;
param_1 = param_1 + 5;
local_18 = *puVar3;                               /* y = u32 at 0x10        */
while (local_18 < 0x1e0) {
  uVar1  = *param_1;                              /* n                      */
  puVar3 = param_1 + 1;                           /* -> first span record   */
  *(uint  *)(param_2 + local_18 * 4) = uVar1;     /* counts[y] = n          */
  *(uint **)(param_3 + local_18 * 4) = puVar3;    /* rows[y]   = &spans     */
  param_1 = puVar3 + uVar1 * 4 + 1;               /* skip 16n + 4 bytes     */
  local_18 = puVar3[uVar1 * 4];                   /* next y, just past them */
}
```

`param_1` is `uint *`, so `uVar1 * 4` words = `16 * n` bytes — that is where
the 16-byte record size comes from. It is corroborated by
`FUN_004f5af3`'s `t3dAllocateMemory(uVar1 << 4)` (`RtK.c:165458`) and by every
`* 0x10` stride in `FUN_004f4a3f`.

Rows are stored sparsely and in increasing `y`; rows never mentioned keep the
zero that `FUN_0043af73` wrote, i.e. no coverage.

### Span record — 16 bytes

| off | type | field |
|---|---|---|
| `+0x00` | i32 | `x_start`, inclusive |
| `+0x04` | i32 | `x_end`, **exclusive** |
| `+0x08` | f32 | `base` — `1/w` sampled at the *anchor* end of the span |
| `+0x0c` | f32 | `slope` — `d(1/w)/dx`, per pixel |

The anchor is `x_end` when `slope < 0`, `x_start` otherwise. Sampling is
`FUN_00454596` verbatim (`RtK.c:54977-54990`):

```c
for (p = spans; !hit && i < n && p[0] <= x; p += 4) {
  if (x < p[1]) {                       /* x_end is exclusive              */
    hit = 1;
    slope = (float)p[3];
    if (slope < 0.0) *out = (x - p[1]) * slope + (float)p[2];
    else             *out = (x - p[0]) * slope + (float)p[2];
  }
  i++;
}
```

so

```
anchor  = (slope < 0) ? x_end : x_start
1/w(x)  = (x - anchor) * slope + base      for x_start <= x < x_end
```

Three things fall out of that loop and are load-bearing:

* `p[0] <= x` is the loop *continuation* condition, so the scan gives up the
  moment it passes a span starting right of `x`. **Span lists must be sorted
  by `x_start` and must not overlap.** They are (§4).
* `x < p[1]` makes `x_end` exclusive.
* the caller inverts the result: `local_88 = 1.0 / local_6c` at `RtK.c:54811`,
  and feeds it to `FUN_00454654` (`RtK.c:54997`) as the ray parameter that
  scales screen offsets into world space. So the stored quantity is reciprocal
  **view depth**, `1/w`, and larger means nearer. `FUN_004f4a3f` relies on that
  ordering when it keeps the winner of two overlapping spans
  (`if (fVar8 < local_70)`, `RtK.c:165228`).

The anchor rule is not guesswork. `FUN_004f5e39` (`RtK.c:165591-165618`) asks
whether two spans lie on one depth line, and reconstructs each line's
intercept as

```c
if (fabs(p1[3] - p2[3]) <= 1e-10) {               /* same slope?            */
  if ((float)p1[3] < 0.0) { a1 = p1[1]; a2 = p2[1]; }   /* anchor = x_end   */
  else                    { a1 = p1[0]; a2 = p2[0]; }   /* anchor = x_start */
  c1 = (float)p1[2] - (float)a1 * (float)p1[3];
  c2 = (float)p2[2] - (float)a2 * (float)p2[3];
  if (fabs(c1 - c2) <= 1e-10) return 1;           /* coplanar               */
}
```

and `FUN_004f4a3f` (`RtK.c:165199-165210`) derives both endpoint values and the
intercept the same way before clipping:

```c
fVar6 = (float)piVar5[3];                                     /* slope      */
if (fVar6 < 0.0) { local_80 = (float)piVar5[2];               /* v(x_end)   */
                   local_74 = (piVar5[1] - piVar5[0]) * fVar6 + local_80; }
else             { local_74 = (float)piVar5[2];               /* v(x_start) */
                   local_80 = (piVar5[1] - piVar5[0]) * fVar6 + local_74; }
fVar10 = local_74 - (float)*piVar5 * fVar6;                   /* intercept  */
```

`FUN_004f5d67` (`RtK.c:165563-165566`) closes the loop from the other side:
when it merges a span with its right-hand neighbour it writes the neighbour's
`x_end` into field 1 and — *only when the slope is negative* — the neighbour's
field 2 into field 2, because that is exactly when the anchor moved.

### Terminator

Nothing follows the terminating row index. The file size closes exactly:

```
size == 20 + 8 * populated_rows + 16 * span_records
```

Over all 1,713 files: `20·1713 + 8·529002 + 16·1223833 = 23,847,604` bytes,
which is the exact byte total of the corpus. Zero slack, zero padding.

The parser only tests `y >= 480`, but the writer always emits `0x26a7` (9895)
— 1,713 of 1,713 files, including the 47 files that have no rows at all and so
consist of the 20-byte header with `0x26a7` in the row-index slot.

---

## 3. What the data is

* 640 × 480, one file per prerendered camera view. 1,713 files across
  `C0.t3d` … `C10.t3d`; members are named `<archive><scene>Vw<n>.ovx`, e.g.
  `C0S00010001Vw1.ovx`. Some are duplicated between neighbouring archives.
* Coverage is partial: 123,061,145 covered pixels out of 1713 × 307,200, i.e.
  **23.4 %** on average (per file 0 % to 96.7 %). Only surfaces the authoring
  tool recorded as occluders are present; large parts of each frame, typically
  open floor, are left uncovered and the engine's zeroed count array means
  "nothing here".
* `1/w` over the whole corpus lies in `[-0.474907, 0.658458]`; `|slope| <=
  0.00199749` per pixel. 6,543 spans (0.53 %) carry a non-positive `1/w`,
  i.e. geometry behind the camera plane that the offline rasteriser kept; they
  form smooth, coherent surfaces (identical slope marching cleanly across
  consecutive rows), so they are real records rather than corruption, and the
  engine's depth test simply never prefers them.
* 11,204 spans have `slope == 0.0` exactly (a surface at constant depth across
  the run); 41,158 spans are one pixel wide.
* 6,393 spans have `x_end == 641`, one past the right edge. Harmless: the
  sampler is only ever called with `x < 640`.
* 38 span records in 5 distinct overlays are all-zero except `x_start`
  (`{x_start, 0, 0.0, 0.0}`). `FUN_00454596` can never match them, since
  `x < 0` is false, so they are inert padding from the authoring tool. They
  still sit in `x_start` order, so they do not cut the scan short.
  `tools/rtkovx.py` counts them and skips them.
* 88 spans (of 1.22 M) start left of their predecessor's end — by 1 px in 28
  cases, by up to 91 px in one. Slack in whatever wrote the files. The sampler
  returns the first match, so the left span wins.

### Rendering

`tools/rtkovx.py --out` writes one 640 × 480 indexed PNG per overlay:
palette index 0 (magenta) is "no coverage", 1…255 is a logarithmic ramp over
`1/w` between that overlay's 1st and 99th percentile, white = nearest. The
results are unambiguous architecture — walls, doorways, window openings,
floorboards, receding floors, small props — which is the strongest single
confirmation that the field assignment is right.

---

## 4. Validation over all 1,713 files

`python tools/rtkovx.py --game "<install>" --out out/ovx`
(full output in `out/logs/ovx-validate.txt`; `--dir out/t3d` over the
extracted copies gives byte-identical numbers)

```
overlays found       : 1713 (23847604 bytes)
parsed ok            : 1713
parse errors         : 0
content-check failures: 0

populated rows       : 529002
span records         : 1223833
covered pixels       : 123061145 of 526233600 (23.4%)

  degenerate span (all zero but x_start)       38
  empty overlay (no populated rows)            47
  float32 model: depth line in range           1223795
  rejected int32 depth: OUT of range           1223833
  rejected swapped base/slope: OUT of range    657332
  rejected swapped base/slope: in range        566501
  rejected x-as-float32: denormal              1223833
  rejected x1-as-length: run overlaps predecessor 481842
  rejected x1-as-length: run past 641          582334
  size formula exact                           1713
  span overlaps its predecessor                88
  span with non-positive 1/w                   6543
  span x_end > 640                             6393
  terminator == 0x26a7                         1713

vertical 1/w continuity over 1278130 overlapping span pairs:
    p0.5    5.375e-04
    p0.9    1.959e-03
    p0.99   4.731e-01
    p0.999  9.108e-01
    fraction < 1%  0.95295

planarity, |2nd difference of intercept| / scale, per candidate reading:
  engine                 n=823007   median 3.314e-08  p90 1.319e-07  p99 1.569e-06  frac<1e-4 0.99627
  anchor always x_start  n=823007   median 7.646e-08  p90 1.778e-03  p99 3.250e-02  frac<1e-4 0.78666
  anchor always x_end    n=823007   median 5.499e-08  p90 2.348e-03  p99 1.209e-01  frac<1e-4 0.80493
  swapped base/slope     n=3610     median 0.000e+00  p90 0.000e+00  p99 9.464e-03  frac<1e-4 0.90554
```

### Structural checks

| check | result |
|---|---|
| magic words `0x26aa`/`0x26a9` | 1713 / 1713 |
| width 640, height 480 | 1713 / 1713 |
| row indices strictly increasing and `< 480` | 1713 / 1713 |
| `size == 20 + 8·rows + 16·spans`, nothing trailing | 1713 / 1713, zero slack |
| terminator word `== 0x26a7` | 1713 / 1713 |
| `0 <= x_start < x_end <= 641` | 1,223,795 / 1,223,795 non-degenerate spans |
| spans sorted by `x_start`, non-overlapping (needed by `FUN_00454596`'s early exit) | 1,223,707 strictly ordered; 88 start left of their predecessor's end (overlap 1–91 px, 37 of them by ≤ 2 px); none is out of `x_start` order, so the early exit is never tripped |
| `base`, `slope` finite as f32, `1/w` and `slope` in a plausible range | 1,223,795 / 1,223,795 |

### Content checks — the ones that would fail if the layout were wrong

Arithmetic can fit the wrong structure, so these two tests look only at
whether the *numbers mean what we say they mean*. Both compare records that
the parser handles independently of each other.

**Vertical `1/w` continuity.** Each row is its own record; nothing in the
format ties row `y` to row `y+1`. Reconstruct `1/w` at the midpoint of every
place where a span in row `y` overlaps a span in row `y+1`: 1,278,130 pairs,
median relative disagreement **5.4 × 10⁻⁴**, p90 **2.0 × 10⁻³**, and
**95.3 %** agree within 1 %. The ~5 % that do not are silhouette edges, where
the two rows' spans genuinely belong to different surfaces — exactly where a
real depth buffer is discontinuous.

**Planarity / the anchor rule.** `1/w` is affine in screen space over a plane
(`1/w = A·x + B·y + C`), so every span sharing one *bit-exact* slope `A` must
have an intercept `C(y) = B·y + C` that is linear in `y`, and its second
difference over three consecutive rows must vanish. Over 823,007 such row
triples the engine's anchor rule gives a normalised second difference with
median **3.3 × 10⁻⁸** and **99.63 %** below `10⁻⁴` — floating-point noise.
This is also what rejects the two naive anchors (below).

---

## 5. Models tried and rejected

Recording these so they are not retried.

| model | why it dies |
|---|---|
| **`.ovx` is an image** (the 640 × 480 in the header invited this) | no pixel array exists; the 20 + 8R + 16S size formula closes exactly with zero slack, and 47 files are 20 bytes long |
| **span fields 0/1 are `f32`** | all 1,223,833 span records give denormals (`9.4e-44`, `5.8e-43`, …) for both; as `i32` they are `0 <= x_start < x_end <= 641` and sorted, 100 % of the time |
| **span fields 2/3 are `i32`** | **0 of 1,223,833** spans yield a depth line that stays inside `(0, 10⁶)` over their own run. The first record of `C0S00010001Vw1.ovx` reads `999762704` / `3059688749` as ints, `0.00461329` / `-3.32512e-06` as floats. Ghidra prints `fVar1 = (float)local_10[3]` because it typed the record `int *`; the data says f32 |
| **span fields 2/3 swapped**, i.e. `(slope, base)` | numeric range alone does not kill it (566,501 of 1,223,833 spans still look plausible), but the planarity test does: grouping by bit-exact slope finds only 3,610 consecutive-row triples versus 823,007 under the correct reading — the plane structure disappears entirely |
| **field 1 is a run length, not an exclusive end** | 481,842 rows would have runs overlapping their predecessor and 582,334 runs would end past column 641; also contradicts `if (x < p[1])` at `RtK.c:54979` |
| **field 2 is anchored at `x_start` always** | planarity frac < 10⁻⁴ drops from 99.63 % to 78.67 %, p90 from `1.3e-7` to `1.8e-3` |
| **field 2 is anchored at `x_end` always** | planarity frac < 10⁻⁴ drops to 80.49 %, p90 `2.3e-3` |
| **span records are 12 or 20 bytes** | the size formula would not close on a single file; `param_1 = puVar3 + uVar1 * 4 + 1` on a `uint *` (`RtK.c:165502`) is 16 bytes per record, as is `t3dAllocateMemory(n << 4)` at `RtK.c:165458` |
| **the trailing word is a checksum / count** | it is read as the next row index (`local_18 = puVar3[uVar1 * 4]`) and the walk ends on `>= 480`; it is `0x26a7` in every file, the fourth entry of the sentinel table at `RtK.exe+0x5f9298` |

---

## 6. Still unresolved

* **Units of `w`.** `1/w` is proven; the world-space scale it is expressed in
  is not pinned down here. `FUN_00454654` (`RtK.c:54997`) multiplies `w` by
  camera parameters at `camera+0x20` / `camera+0x24` and the render context's
  `+0x194` / `+0x198` half-extents, so recovering absolute units means
  reversing the camera setup too. Typical values (`1/w ≈ 0.0046`, so
  `w ≈ 217`) are consistent across a scene but have not been tied to anything
  external.
* **`0x26a8`**, the third sentinel-table word, is referenced by nothing in the
  decompiled output and appears in no file. Probably a reserved marker in the
  authoring tool's own format family.
* **No writer exists in the game.** `FUN_004f4a3f` merges and rewrites spans
  in memory, but nothing serialises an `.ovx`; the files were produced by an
  offline tool (the neighbouring `.data` strings `POLY_ACD`, `POLY_INST`,
  `poly1.spr` belong to an in-engine polygon-placement debug mode, not to this
  format). So the exact rounding the writer used is inferred, not read.
* **Why 88 spans overlap and why 38 are all-zero** is a property of that
  missing tool, not of the format.
