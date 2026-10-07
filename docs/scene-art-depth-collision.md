# Scene art, depth, and collision

What a location is made of, measured against the shipped game, so a later
agent can build a new scene without rediscovering the file split. This is
the authoring map. Byte layouts that already have their own document are
cited, not repeated, except where a later measurement corrected them.

No game file was modified to produce this. The per-scene dump is
[`scene-corpus.json`](scene-corpus.json) (about 4.4 MB). Regenerate it
with:

```powershell
python tools/survey_scene_corpus.py
```

That script only reads the install and `out/plaintext`. Function names are
the stable citations. `RtK.c` and `t3dll.c` line numbers move when the
decompile is regenerated.

---

## 1. Three questions, three files

A playable place is one **scene**. A scene has one walk grid, one True3D
world, and one or more **views**. A view is one frozen camera. Characters
are 3D actors. The painting is not a texture on the world mesh.

| Question | File | Shared by |
|---|---|---|
| What does the player see? | `.di_` painting in `Bkgnd/S########.t3d` | one view, and only the variant whose `BGDef` condition is true |
| Which painted pixels hide an actor? | `.ovx` in `C<n>.t3d`, member `C<n><Scene><View>.ovx` | one view in one chapter archive |
| Where may the party walk? | `Worlds/<world>_<level>.mab` | every view of the scene |
| How tall is the floor, in the engine's region mesh? | the `.wlx` named by `T3dWorld` | the scene. The only `.wlx` loose in this install is the placeholder `Worlds/rtkworld.wlx` |
| Which view is the camera in? | `CamPoly` on the view, in `Loc_All.def` | the view. This is not a wall |
| What does a click do besides walk? | `TouchPlateDef` / `PressurePlateDef` / hotspots in `ChapterN.def` | the scene instance |

Counts from this install, GOG v1.00.6:

| Thing | Count |
|---|---|
| `Scene` blocks across all `Loc_All.def` | 533 |
| Distinct scene names | 152 (113 names are repeated in more than one chapter file) |
| `View` blocks | 3,472 |
| `BGDef` lines | 4,948 |
| Unique `.di_` member names under `Bkgnd/` | 1,556 (the archive member count in [`asset-inventory.md`](asset-inventory.md) is 1,585; the difference is the same stem stored in more than one `S########.t3d`) |
| `.ovx` members in `C0.t3d`…`C10.t3d` | 1,713, of which 47 are empty (20-byte header only) |
| `.mab` files in `Worlds/` | 53, and every scene's `T3dWorld` + `Level` names one of them |
| `SceneDef` blocks in `ChapterN.def` | 223. The other 310 `Scene` blocks have no matching instance block in that chapter file |
| Loose `.wlx` | 1, `rtkworld.wlx` |

`scene-corpus.json` keys:

| Key | Contents |
|---|---|
| `scenes[]` | chapter, name, id, desc, level, world, `mab_found`, views, plates, lightdark |
| `scenes[].views[]` | camera floats, every `BGDef`, `CamPoly` floats, `ovx_expect`, `ovx_found` |
| `mabs[]` | header text, 40-byte field hex, bounds, grid size, byte histogram |
| `dibs{}` | per-painting palette and luminance stats, keyed by member name |
| `ovx{}` | per-overlay coverage, span count, `1/w` range, keyed by member name |
| `wlx[]` | the one parsed world |
| `missing_dib`, `missing_ovx`, `missing_mab` | references that did not resolve |
| `camera_field_degrees`, `art_rollup`, `notes` | rollups, plus the diagonal-cost float and the type-`0x24` volume bytes |

---

## 2. Coordinates

Script space, camera space, and the cost map agree on this install.

- **Z is up.** For `S00020001` / `1003_1.mab` the grid covers X `[-549, 711]` and Y `[-2004.6, 839.4]`, base height about `0`. View `Vw1`'s camera origin is `(79.14, -1594.00, 87.21)`. X and Y land inside the grid. Z does not; it is an eye height of about 87 above a floor whose base is 0. The aim point's Z is `69.26`, so the camera looks slightly down. `tools/rtkscene.py` `project_point` uses world up `(0, 0, 1)` for the same reason.
- **One world unit is the cost-map unit.** Every shipped grid derives a cell of exactly 18.0 from `(xmax-xmin)/cols` and `(ymax-ymin)/rows`. The header text says `Tilesize = 18.000000`. The on-disk dword at field-block `+0x24` is the integer `18` in all 53 files.
- **Row is Y, column is X.** Field-block `+0x14` is the X extent (`cols * 18`) and `+0x18` is the Y extent (`rows * 18`). See §6.
- **The region floor solver documented in [`scene-runtime.md`](scene-runtime.md) solves the plane for Y**, treating Y as the vertical axis. That has not been reconciled with the Z-up camera and cost map above. Do not assume the True3D mesh and the `.mab` share an up-axis until that call is traced against a real scene world. This install does not contain those scene `.wlx` files, only the placeholder box.
- **Screen space is 640×480.** Painting, overlay, and the camera buffer are the same pixels. File row 0 is the **bottom** of the picture as the game shows it. Scene Studio flips Y on draw (`tools/web/studios.js` `drawBackdrop`) because a canvas treats row 0 as the top. An unflipped export of `107101cm` has the night sky in the bottom rows and the cobbles toward the top. Flip the painting and the overlay together, or flip neither. `.ovx` scanline 0 is the same row as `.di_` row 0.

`CamDef` is eight floats: origin XYZ, aim XYZ, roll, field-of-view in degrees.

| Field degrees | Views |
|---|---|
| 63.0 | 3,454 |
| 0.0 (the whole `CamDef` is zeros: `S00020041 Vw19`, `S00020033 Vw7`, `S00050001 Vw5`, `S00050004 Vw6`, repeated across chapter copies) | 7 |
| 54.432 | 6 |
| 71.951 | 2 |

Roll, on the 3,469 views that have a `CamDef`: `0` on 3,450, `512.154` on 15, `-1.067` on 3, `0.75` on 1. Three views have no `CamDef` at all.

The lens install is `FUN_004e7012`:

```c
t3dSetCameraLens(camera,
    field * 512.0 * (1/360),
    (field * 512.0 * (1/360)) / 67.1289,
    0.0078125,   /* near = 1/128 */
    *(float *)(DAT_00628d6c + 0x40));  /* far, scene root */
```

`t3dSetCameraLens` stores half of the first argument at `camera+0x20` and the second at `camera+0x24`. Click unproject takes the cotangent of those. The camera position is refused unless `t3dGetRegionNumberFromWorldAndXYZ` finds a region under it. A new scene whose world is the placeholder `rtkworld.wlx` satisfies that with a ±100000 box. A new scene that ships its own `.wlx` has to contain the camera origin.

---

## 3. How a frame is put together

Runtime detail is [`scene-runtime.md`](scene-runtime.md) §1–2. The short form:

1. `FUN_004c215d` picks the backdrop record (`FUN_004c27ba`), loads the `.di_` (`FUN_004fe722`), aims the camera (`FUN_004e7012`), loads the `.ovx` (`FUN_004e579e`).
2. `FUN_0045cfd0` blits the painting with `SpriteCompose`, calls `t3dSetRenderContextCoverageBuffer` with the overlay tables, then `t3dRenderActors`. Gameplay does not call `t3dRenderScene`; that export clears the coverage buffer.
3. The actor image is composited over the painting. Where an overlay span's `1/w` is greater than or equal to the fragment's `1/w`, the painting keeps the pixel.

Actors are not in the painting. Doors that move, party members, NPCs, and spell actors are True3D. Static dressing (crates, timber, cobbles, the closed door in the plate) is painted. Occlusion of an actor by that dressing is the overlay's job, not a hole in the bitmap.

---

## 4. The painting

Format: [`dib-format.md`](dib-format.md). Loader: `ReadCompressedDib` / `FUN_004fea14`.

```
0x00  8     signature 89 44 49 5f 0d 0a 1a 0a     (\x89DI_\r\n\x1a\n)
0x08  u32   width     = 640
0x0c  u32   height    = 480
0x10  u32   zlib size
0x14  1024  PALETTEENTRY[256], byte 0 = red, byte 3 unused
0x414 zlib  width*height bytes, 8-bit indices, no row padding
```

The loader checks width and height against the caller's 640×480. A different size is rejected. The palette is installed verbatim by `FUN_0045ca70` → `SpriteSetPalette`. There is no 10-colour system reserve, unlike RTKRES bitmaps.

### What the plates look like

Decoded from `Bkgnd/` for this note: `100101cm` (Rainbow Parrot main room), `100801cm` and `107101cm` (street / yard), `200107cm` (torchlit stone passage), `703801nt` (dark rock face), `witchdocbig` (a parchment filling the frame, not a room).

- Late-1990s pre-rendered 3D. Repeating texture maps, hard shadow edges, no photographed grain, no people.
- The frame is dark. Across 1,556 paintings the median mean-luminance is **34.9** (0–255). The median fraction of pixels with luminance under 16 is **0.31**. The median fraction above 220 is **0**. The brightest plate in the set has mean luminance 122.6. A new plate that is evenly mid-grey will not sit with the others.
- Palettes are full 8-bit but not full of unique colours. Median used indices **236**, median duplicate RGB slots **19** (min 0, max 254).  Duplicate slots are not interchangeable; the index is what the engine stored. Write an indexed PNG if a replacement has to keep slot identity (`docs/image-write.md`).
- Neighbour samples (every 4th pixel, compared with the next pixel) differ in index **61%** of the time at the median, and the mean sum of absolute RGB deltas on those changes is about **24**. That is dither plus texture, not flat colour bands and not JPEG blocks. zlib is lossless. Banding in the art is the 256-colour quantiser.
- Interiors: warm yellow on timber, grey-brown stone, deep red-brown shadow. Exteriors: cobble and plaster, a hard sun or a black night sky. Passages: a small warm pool and a large pure-black region (`200107cm`).
- `*nt` stems (`703801nt`–`703804nt`) are the dark variants. `106601bg` and `witchdocbig` are the only other stems that do not end in `cm`. `witchdocbig` is a torn parchment with a red spiral glyph on a grey sheet, letterboxed by a flat dark surround. It is a prop plate, not a walkable room.
- There is no UI-safe rectangle in the file. The status UI is drawn on top afterwards. Plates use the full 640×480.
- Conditional plates are separate files, not layers. `S00020004` view `Vw1` in chapter 3 lists four:

```
BGDef : 100401CM.dib, Condition: 0,
BGDef : 104301cm.dib, Condition: 2,
BGDef : 107001cm.dib, Condition: 2,
BGDef : 107101cm.dib, Condition: 1,
```

`107101cm` is the street plate described above. Same camera, different paint, chosen by condition. Views with more than one `BGDef`: 2,340 views have 1, 866 have 2, 188 have 3, 78 have 4.

Condition tails, most common first: `Condition: 0,` (2,153), `Condition: 1,` (1,433), `Condition: 2, TRUE` (769), `Condition: 2,` (245), `Condition: 2, FALSE` (91), then script predicates (`Chapter10.ship_raised`, `IsDay()`, `InnBurned`, `Escaped`). The integer after `Condition:` is evaluated by `FUN_004c27ba` via `FUN_004bb4d6` on the backdrop record at `+8`. The opcode map for that integer is not written down. Keep the text the game already uses.

`tools/rtkdef.py` stores block fields in a dict and tests `key.lower() not in block.fields` while the stored key keeps its original case, so a second `BGDef` **overwrites** the first. `survey_scene_corpus.py` re-reads the lines. Anything that trusts `Block.fields["BGDef"]` alone sees only the last variant.

89 `BGDef` stems are not in `Bkgnd/`. They are listed in `scene-corpus.json` `missing_dib`. Most are `6006xxCM` / `60250xCM` (referenced, never shipped) plus `104228cine`, `104229cine`, `104230cine` and `witchdoc`-adjacent `703902cm`. A new scene should not point at these.

### Names

- Scene `S00020001` → archive `Bkgnd/S00020001.t3d`.
- `BGDef` stem `100101cm` → member `100101cm.di_`. The script writes `.dib`. `FUN_004fe722` strips the extension and appends `.di_`.
- Stem shape is usually 6 digits plus `cm`. The viewer reads the last two digits as the view number (`100101` → view 01). That is a convention, not a loader check. Pairing is the string on the view, not the digits.
- Chapter archives `C0.t3d`–`C10.t3d` hold **no** `.di_` in this install. `C3.t3d` is 486 members: 456 `.ovx` and 30 `.ktx`.

`AmbientLight` is four floats on every scene. `S00020001` in chapter 0 is `1, 1, 1, 1`. The same scene in chapter 1 is `0.30, 1, 1, 1` and in chapter 3 is `0.40, 0.70, 0.70, 0.70`. The painting does not change with this field; it is the 3D ambient on the actors. `Fog` is six numbers. The common line is `0, 0.000000, 500.000000, 0, 0, 0`.

988 `LightDarkDef` regions sit on scenes (165 scenes carry at least one). They are not walk blockers. Example from chapter 1, `S00020002`:

```
LightDarkDef : Light/Dark Region 1
Begin
   LightIntensity : 0.300000
   BorderThickness: 0.150000
   Poly : 160.618500, -1802.441162, -0.037554, ...
   Condition: 0,
End
```

---

## 5. The depth overlay

Format: [`ovx-format.md`](ovx-format.md). Parser: `FUN_004f5bcd`. An `.ovx` is not an image. It is a sparse list of horizontal spans, each a straight line in reciprocal view depth.

```
u32 magic0 = 0x26aa
u32 magic1 = 0x26a9
u32 width  = 640
u32 height = 480
u32 first_y                 # >= 480 means no rows. Empty files store 0x26a7 here.

repeat while y < 480:
    u32 n
    n times:
        i32 x_start         # inclusive
        i32 x_end           # exclusive
        f32 base            # 1/w at the anchor column
        f32 slope           # d(1/w)/dx
    u32 next_y              # >= 480 ends the list. Shipped files write 0x26a7
```

`file_size = 20 + 8*populated_rows + 16*spans` on all 1,713 files.

```
anchor = x_end if slope < 0 else x_start
1/w(x) = (x - anchor) * slope + base
```

Larger `1/w` is nearer. The software rasterizer `FUN_1002d930` hides the actor fragment when the span's `1/w` is greater than or equal to `1/param_3[2]`. A row with no spans draws the actor solid. That is why open floor is usually absent: about **23.4%** of all overlay pixels are covered (123,061,145 of 526,233,600). Per-file coverage median is **0.193**, maximum **0.967**.

Sentinel table at `RtK.exe+0x5f9298`: `0x26aa, 0x26a9, 0x26a8, 0x26a7`. `0x26a8` is unused by the parser and by every shipped file.

The member name is built by `FUN_004e5829` / `FUN_004e58b6` as `C%d%s%s` plus `.ovx`. Example: chapter 1, scene `S00020001`, view `Vw1` → `C1S00020001Vw1.ovx`. The backdrop stem is a different string and is not consulted.

Same scene, many archives. `S00020001` is declared in chapter folders 0, 1, 10, 2, 3, 5, and 8. Overlays exist as `C1S00020001Vw*.ovx` and `C2S00020001Vw*.ovx` (30 members contain that scene id). There is no `C0S00020001Vw1.ovx`. Matching the folder number to the archive digit hits 1,553 views. Another 1,052 views have an overlay under a **different** chapter digit. **867** scene/view pairs have no `.ovx` in any chapter archive; those views draw actors with nothing to hide behind. 159 members use a lowercase `c` (`c3S000…`). Archive lookup is `stricmp`, so the case is not a different file.

A click samples the same span (`FUN_00454596`), inverts to `w`, and unprojects with `FUN_00454654`. A second coverage buffer vetoes the hit when the two `w` values differ by more than `0.001`. If the cursor is not on a span, the click falls through to the cost-map ray. The absolute world unit of `w` is still not tied to the 18-unit cell. A mid-scene sample is `1/w ≈ 0.0046` (`w ≈ 217`). Corpus endpoint range is about `[-0.475, 0.658]`.

18 views in chapter 3, scenes `S00010001` and `S00010002`, also carry an `Overlays` field such as `000101_i.ovl`. No `.ovl` file exists in the install, and `C3.t3d` has no such member. The field is unused by the `.ovx` loader.

---

## 6. The walk grid

This is what stops the party walking through a painted wall. It is not the overlay and it is not the region mesh.

Loader: `FUN_00420cd9` → `FUN_00420e9c` (v2) or `FUN_00421062` (legacy text). Path pairing, confirmed for all 533 scene blocks: `Worlds/<T3dWorld stem>_<Level>.mab`. `S00020001`, world `1003.wlx`, level `1` → `1003_1.mab`. No scene with a `T3dWorld` failed that lookup. No `.mab` was left over.

### On-disk layout

`FUN_00420e9c` reads 64 bytes, checks the `CostMap v2` prefix, reads 40 bytes into `local_12c`, then `fread`s each row.

| File offset | Size | Field |
|---|---|---|
| 0 | 64 | ASCII. Must start with `CostMap v2`. The rest of the 64 is not parsed. Shipped text: `CostMap v2.05  4/7/98   NOTE: Tilesize = 18.000000` (42 files), `v2.01  2/4/98` (10), `v2.03  4/7/98` (1) |
| 64 | 16 | f32 xmin, ymin, xmax, ymax |
| 80 | 4 | f32 base height → runtime `+0x14` |
| 84 | 4 | f32 X extent. Not copied. Equals `xmax-xmin` |
| 88 | 4 | f32 Y extent. Not copied. Equals `abs(ymax-ymin)` |
| 92 | 4 | u32 row count → runtime `+0x24` (`local_110`, `ebp-0x110`, which is `+0x1c` from `local_12c`) |
| 96 | 4 | u32 column count → runtime `+0x28`, and the byte count of each row `fread` (`local_10c`) |
| 100 | 4 | u32 `18`. Read into the 40-byte buffer, never stored. `FUN_00420b75` computes a tile size at runtime `+0x2c` with `__ftol` of an extent divided by the column count, then stores `1/tile` at `+0x30` |
| 104 | rows×cols | one byte per cell, row-major |

`FUN_00420b75` also writes runtime `+0x1c = xmax-xmin` and `+0x20 = abs(ymax-ymin)`, which is why the on-disk extents can be ignored. [`scene-runtime.md`](scene-runtime.md) §3 now matches this table. An older revision of that section put rows and columns at `+0x14` and `+0x18` of the 40-byte block. That reading matches **0** of the 53 files. The `+0x1c`/`+0x20` reading matches **53**, with no trailing slack.

`1003_1.mab` fields: bounds `[-549, -2004.616, 711, 839.384]`, base `≈ 0`, extents `(1260, 2844)`, grid **158 × 70**, tile dword 18. `1260/70 = 18`, `2844/158 = 18`.

Height of a cell for the mouse ray (`FUN_00421af1`):

```
(byte & 0x1f) * scale + base
```

`scale` defaults to 6 (`cost map +0x18`, set to `0x40c00000` which is float `6.0` in `FUN_00420cd9`). Class 0 is the floor. Class 31 is `186 + base`.

### What a byte means

The v2 reader does not translate the byte. `FUN_004219b6` accepts a neighbour when bit `0x20` is clear and either the class (`byte & 0x1f`) is below 4, or bits `0x80` and `0x40` are both set. Bit `0x80` alone redirects the sample to an overlay table at cost-map `+0x44` (`FUN_0042168c`).

| Byte | Character | Class | Search | Cells in the 53 files |
|---|---|---|---|---|
| `0x00` | NUL | 0 | **walkable** | 198,780 |
| `0x40` | `@` | 0 | walkable | 7,355 |
| `0x20` | space | 0 | blocked | 747,945 |
| `0x3f` | `?` | 31 | blocked, and the out-of-range sentinel | 2,313,141 |
| `0x21` `0x22` `0x23` | `!` `"` `#` | 1–3 | blocked | 228, 922, 127 |
| `0x61`– | `a` and other lowercase | 1–3 with bit `0x20` | blocked | thin tail |
| `0x41`–`0x43` | `A` `B` `C` | 1–3, bit `0x20` clear | walkable, legal, rare | see histograms |

Walkable cells total **206,141**. Blocked cells total **3,063,453**. Out of 3,269,594 cells. The ordinary floor is the NUL byte, not `@`. `@` tends to trace the rim of a corridor or fill a marked room. A text editor hides the NUL, which is why an earlier note counted `@` as the floor.

Coarse map of `1003_1.mab`, every 4th row and every 2nd column. `.` is `0x00`, `@` is `@`, space is a blocked space, `?` is out of the room:

```
  0 ???????????????????????????????????
  4 ?????@@..?????@@@?@@???????????????
  8 ????@....@?......  @???????????????
 24 ?......???@@@@@????????????????????
 32 ?@..........@@@@@@@@@??????????????
```

The legacy text reader (`FUN_00421062`) is a different encoding of the same bits. `X` becomes `0x3f`. `A`–`Z` become classes 0–25 with no extra bits. `a`–`z` become `0x40` plus the letter index (`a` → `@`). Anything else, including a missing glyph, becomes byte 0. No shipped file failed the v2 header check, so this reader is the fallback, not the format on disk.

### The search

`FUN_00458f40` turns the actor and the destination into cells. Distance at most `0.01`, or the same cell, skips the search. Otherwise `FUN_0040ddeb` tries a grid Bresenham (`FUN_0040db43`, clearance argument `18.0` on the direct-path call) and, if that hits a blocked cell, an A* (`FUN_0040e96f`).

- Eight neighbours. Goal-ward directions first.
- Orthogonal step cost is `class + 1`. Diagonal step cost is `class + DAT_005c9314`.
- `DAT_005c9314` in this executable is float **1.4140000343322754** (`f4 fd b4 3f` at VA `0x005c9314`). That is a rounded square root of two, added, not used as a multiplier.
- The goal cell is allowed even when the neighbour test fails.
- Heuristic is Manhattan, Chebyshev, or random, selected by `DAT_0061e5c8`.

Scripted `PathDef` waypoints still pathfind each leg on this grid.

`CamPoly` does not block walking. It is the footprint that makes `FUN_004125f6` switch the camera. `S00020001` view `Vw1` in chapter 0 is a quad (4 points, 12 floats) in the same XYZ as the grid. 2,995 of 3,472 views have a `CamPoly`. The point test is `FUN_0042b245`, X/Y only; Z is stored and ignored by that test.

---

## 7. Other collision

### Click order

`FUN_00453c54`, written up in [`interactions.md`](interactions.md):

1. UI overlay.
2. Hotspot along the camera ray.
3. `.ovx` sample, unproject, actor at that depth. Second buffer veto at `|Δw| > 0.001`.
4. Cost-map ray → walk destination, then rejected if it sits in a click-exclusion polygon (`FUN_004da51e` over `scene+0x80`).
5. Actor along the ray.

The walk cursor still requires the destination cell to pass `FUN_00421939`.

### Plates, groups, combat

From `ChapterN.def`, attached in the corpus under `scenes[].plates` when a `SceneDef` exists:

| Block | Count |
|---|---|
| `GroupDef` | 933 |
| `TouchPlateDef` | 441 |
| `PressurePlateDef` | 266 |
| `CombatDef` | 164 |

A touch plate is a click volume: `Poly` (XYZ triples), optional `PlaneEQ` (four floats), `Range`, `Active`, and a script (`Teleport`, conversation, door). A pressure plate with `NavigationSensor : TRUE` is a region the player is not supposed to pick as a destination. Neither plate writes the `.mab`. Combat `Arena` polygons are the fight, not the adventure grid. `DetermineCost` (`FUN_004ac838`) uses the combat board at `DAT_00628d6c+0x36c` and returns tier 0, 1, or 2.

### True3D world

`rtkworld.wlx` is 784 bytes. Version `0x15500`, `field_0c = 1`, one BSP node, one object `R000001`. Eight vertices, the corners of `[-100000, 100000]³`. Six quads. Six segments, all kind `-15` (edge polygon plus an explicit plane). The segment planes are inward unit normals, but their constants are `0` or `200`, not `±100000`. Polygon 0 is the only one with `flags & 1`. BSP node plane `(0, 1, 0, 0)`, `field4 = 1`, both children null. This is a placeholder shell, not a Krondor street. Scene files name worlds such as `1003.wlx`; those files are not loose in `Worlds/` and were not found as `.wlx` anywhere else in the install. When `DAT_00628d6c[0xce]` is set, the loader ignores the scene path and opens `rtkworld.wlx`.

Chunk layouts: [`world-format.md`](world-format.md). Segment kinds the loader accepts are `9`, `0xC`, `0xE`, `0x12`, and `-15`. Only `-15` appears in the one real file.

`t3dCollisionDetection` is used as a short probe (sphere cast length 4400 in `FUN_004f9c57` / `FUN_004f2aea`). `t3dGetSkitterAmount` has no caller in `RtK.c`. The thing that stops a walk is the `.mab` search.

### Actor volumes

The type word is the first dword of the volume. Constructors in `t3dll.c` are the authority. Several exports share an address, so a decompiler label on a `switch` arm is often the wrong name. `t3dDestroyPlane`, `t3dDestroySphere`, and `t3dDestroyXYZSphere` are all `10017e50` (free the block). `t3dDuplicatePolyhedron` and `t3dDuplicateSphereList` are both `1006f3e0` (copy 7 dwords). `t3dDuplicatePlane` and `t3dDuplicateXYZSphere` are both `100edae0` (copy 5 dwords).

| Type | What `t3dCreate*` writes | Size | Layout |
|---|---|---|---|
| `0` | none. `t3dDuplicateVolume` returns `&DAT_10127240` | static | First dword is 0. The symbol sits in the zero-filled tail of `t3dll.dll` `.data` (virtual size past the raw bytes), so a dump of the file at VA `0x10127240` is not the runtime object |
| `1` | polyhedron **definition** (`t3dDefinePolyhedron`) | `0x2c` | `[0]=1`, `[2]=name`, `[5]=param_3`, `[6]=face count`, `[7]=faces` (`count * 0x20`), `[8]=vertex count`, `[9]=vertices` (`count * 12`), `[10]=instance` |
| `2` | polyhedron **instance** | `0x1c` | `[0]=2`, `[5]=scale`, `[6]=definition`. Bounding radius is `scale * *(definition+0x14)` |
| `3` | sphere-list **definition** (`t3dDefineSphereList`) | `0x28` | `[0]=3`, `[5]=param_3`, `[6]=count`, `[7]=centres` (`count * 12`), `[8]=radii` (`count * 4`), `[9]=instance` |
| `4` | sphere-list **instance** | `0x1c` | `[0]=4`, `[5]=scale`, `[6]=definition`. Same radius formula as type 2 |
| `0x22` | `t3dCreateSphere` | `0x0c` | `[0]=0x22`, `[1]=back-pointer`, `[2]=radius` |
| `0x23` | `t3dCreateXYZSphere` | `0x14` | `[0]=0x23`, `[1..3]=centre`, `[4]=radius` |
| `0x24` | no creator. Singleton `&DAT_1011f398` | 8 bytes observed | `24 00 00 00  a0 f3 11 10`. The pointer is VA `0x1011f3a0`, which is the C string `WLDPATH`. `t3dDuplicateVolume` returns the singleton. `t3dDestroyVolume` ignores it. Bounding radius does not handle this type |
| `0x25` | `t3dCreatePlane` | `0x14` | `[0]=0x25`, `[1..3]` from the first argument, `[4]` the second. Not an arm of `t3dDuplicateVolume` |

Adventure blocking in `RtK.c` dispatches volume types **2**, **4**, and **`0x22`** into `t3dCollisionWithActors`. Type 4 also sweeps edges with `t3dMovingSphereWithXYZEdge`. A hierarchical sprite's `0x10` chunk stores a volume reference at dword `+0x0c`; zero selects `&DAT_10127240`. That reference is not the walk grid. Two actors can overlap a legal `.mab` cell and still be stopped by these volumes.

A polyhedron face on the way in is 8 dwords. The loader then treats dword `+4` as a count and dword `+8` as a pointer to `count` records of 16 bytes, and rewrites two vertex slots in each record from caller pointers into the copied vertex array (`t3dDefinePolyhedron` around the `puVar10[-7]` loop). The on-disk chunk that feeds this API was not identified.

---

## 8. Building a new scene

The work order for an agent that will render one — camera calibration,
what is painted versus what stays a live actor, and which writers do not
exist yet — is [`scene-render-plan.md`](scene-render-plan.md).

1. Add a `Scene` to `GameData/ChapterN/Loc_All.def` with `id`, `Desc`, `Level`, `AmbientLight` (4 floats), `Fog` (6 numbers), `T3dWorld`.
2. Add one or more `View`s. Each needs `id`, `Active`, `CamDef` (8 floats, field 63 unless you have a reason), one or more `BGDef` lines with a `Condition`, optional `CamPoly`, `UseStretch`, `MinPass`.
3. Paint a 640×480 indexed picture. Embed its own 256-colour palette, red in byte 0. Store row 0 as the bottom of the in-game frame. Keep it dark and dithered. Do not paint the party. Export with `tools/imagecodec.py` `encode_di_` (zlib level 9). Put the member in `Bkgnd/S########.t3d` under the stem the `BGDef` names, extension `.di_`.
4. For every view that should hide actors behind the set, write an `.ovx` for that same camera. Spans only where the painting is in front of where an actor can stand. Anchor rule in §5. Terminate with `0x26a7`. Name it `C<chapter><Scene><View>.ovx` and put it in that chapter's `C<n>.t3d`. A missing file is legal: actors draw solid.
5. Write `Worlds/<world>_<level>.mab`. Header `CostMap v2`, 64 bytes, then the 40-byte field block in §6, then `rows*cols` bytes. Cell 18. Paint `0x00` for open floor, `@` (`0x40`) for a marked floor, space (`0x20`) or `?` (`0x3f`) for blocked. Cover every coordinate the `CamPoly` and the plates use.
6. Add a `SceneDef` in `ChapterN.def` for groups, plates, paths, and combat. Plates do not replace the grid.
7. If actors must stand on a real region floor, the scene needs a `.wlx` the loader can open. The placeholder box accepts any camera inside ±100000 and does not model the room.
8. Check it in Scene Studio (`tools/viewer.py`). The studio projects `.mab` cells through `CamDef` onto the flipped painting. Trust that composite over an unflipped PNG.

`UseStretch` and `MinPass` are stored on the view (3,454 views have both). Their runtime effect is not re-derived here. Shipped values are mostly `UseStretch : FALSE` and `MinPass : 1`, with `TRUE` / `10` on at least the raised view `S00020004 Vw5`.

---

## 9. Still unresolved

- World unit of overlay `w`. Reciprocal view depth and the unproject formula are known. They are not matched to the 18-unit cell.
- `Condition:` integer opcodes inside `FUN_004bb4d6`.
- Why a scene `.wlx` such as `1003.wlx` is not in the install, and whether the region floor's Y axis is the script's Z.
- `0x26a8` in the overlay sentinel table.
- Type `0x24` volume beyond the 8 bytes and the `WLDPATH` string.
- On-disk source of polyhedron faces and sphere lists.
- The 867 views with no `.ovx` anywhere: authored empty, or a name this survey did not guess. The guess was `C<digit><Scene><View>.ovx` in every chapter archive, case-insensitive.
- `Overlays: *.ovl` on 18 views. No file.
- `UseStretch`, `MinPass`, and the exact exit-record fields past view index `+0x10`.
- Whether adventure movement calls `t3dCollisionDetection` every frame. The traced probes are short. The walk stop is the `.mab`.
