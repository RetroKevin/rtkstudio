# Plan: render a new scene

How another agent should produce a scene the game will accept, in the same
art style, with depth and collision that agree with the painting, and with
objects the engine already knows how to draw.

Read [`scene-art-depth-collision.md`](scene-art-depth-collision.md) first.
Layouts live there. This file is the work order. Do not modify the game
install. Write a mod (`docs/modkit.md`).

The game does not render the room. It blits a 640×480 painting, then draws
3D actors with the view's camera, and the `.ovx` punches actors out where
the painting is nearer. A new scene is an offline render of the set, plus
script that places actors on top.

---

## What "done" means

One new scene, two views, playable from an existing scene via `Teleport`:

| Product | Where it ends up |
|---|---|
| `Loc_All.def` scene + views | modded `GameData/ChapterN/Loc_All.def` |
| `SceneDef` with one party formation and one NPC | modded `ChapterN.def` |
| Two `.di_` plates | `Bkgnd/<Scene>.t3d` |
| Two `.ovx` overlays | `C<n>.t3d` |
| One `.mab` | `Worlds/<world>_<level>.mab` |
| Reuse `T3dWorld: rtkworld.wlx` | no new world mesh in the first version |

In game: the plate matches neighbouring rooms in palette and brightness, a
character walks the floor and disappears behind a doorframe, a click on the
floor pathfinds, a click on the NPC talks.

---

## Split the geometry before rendering

| Kind | Goes into | Does not go into |
|---|---|---|
| Walls, floor, timber, crates that never move | the `.di_` and the `.ovx` | the actor list |
| Party, NPCs, anything that animates or opens | `GroupDef` / `Models.def`, drawn by the engine | the painting |
| Walkable floor and solid walls | the `.mab` | the `.ovx` (open floor has no spans) |
| View changes | `CamPoly` | the `.mab` |
| Click-to-teleport, doors-as-scripts | `TouchPlateDef` | the walk grid |

Characters are hierarchical sprites: a skeleton with 2D art on the bones
(`.adf` + `.sph` + a palette bmp), not a 3D body you re-render into the
plate. `Models.def` already binds them (`James : A1James.adf, …`). Reuse a
row from that file. A new mesh is a separate project (new `.adf`, collision
volume, palette, archive member) and is out of scope for the first scene.

Static dressing that should occlude feet is geometry in the offline scene
and a span in the `.ovx`. If it is only in the painting, the actor draws on
top of it.

---

## Phase 0 — Prove the camera before any art

The studio projector in `tools/rtkscene.py` `project_point` is a 63° pinhole
with Z up. The game's lens is `FUN_004e7012`:

```
t3dSetCameraLens(camera,
    field * 512/360,
    (field * 512/360) / 67.1289,
    1/128,
    far plane from the scene root);
```

Half of the first argument is stored at `camera+0x20`, the second at
`camera+0x24`. Click unproject (`FUN_00454654`) divides by the cotangent of
those. A generic 63° camera will not line up with a shipped plate.

Build a calibration that does not need the missing `.wlx` files:

1. Take `S00020008` view `Vw2` (or any view whose formation Z is 0 and whose
   camera Z is the eye height). Chapter 1 formation
   `Party_BothStart_20008_V2` places James at
   `(42, -1557, 0, facing 245)`.
2. Load that view's `CamDef` and its `.di_`.
3. Project the formation point. It has to land on the floor in the painting,
   on the spot the party actually stands, within a few pixels.
4. Invert the same projection: a pixel on that floor, unprojected at the
   formation's depth, has to come back as that world point.

Until step 3 is true, do not render a new plate. The `.ovx` `1/w` unit is
still unknown in the abstract (`scene-art-depth-collision.md` §9). Fitting
it so the unproject of a floor pixel returns the world point you authored
is the definition of the unit. Record the fitted scale next to the camera
code.

Also lock the flip. File row 0 is the bottom of the in-game frame. The
calibration image is the flipped one Scene Studio draws
(`tools/web/studios.js` `drawBackdrop`).

---

## Phase 1 — Author the room in world units

One coordinate space for everything: Z up, 1 unit = 1 cost-map unit, cells
of 18. Camera eye height on shipped interiors is on the order of 60–110
(Rainbow Parrot `Vw1` origin Z is 87 over a floor whose `.mab` base is 0).
Field of view 63, roll 0, unless the calibration said otherwise.

Author:

- Floor polygons and wall volumes in that space.
- Two cameras. Each `CamDef` is origin XYZ, aim XYZ, roll, field.
- A `CamPoly` per view, the floor footprint where that camera should engage.
  Overlap them slightly. `FUN_004125f6` switches views when the party enters
  one.
- NPC position and facing (degrees, the fourth formation float).
- Party formation, three points on `0x00` cells, not inside walls.

Keep the room inside a few hundred units. The placeholder world is a
±100000 box, so the camera will be accepted. Floor snapping via
`t3dGetRegionFloorHeight` will not match this room, because `rtkworld.wlx`
is an empty shell whose segment planes are not the street. Set formation Z
explicitly. Do not block on a `.wlx` writer.

Style target for the mesh, taken from the shipped plates: repeating
textures (cobble, plaster, timber, stone), hard shadows, no people, no
photograph grain. Median plate luminance is about 35/255 and about 31% of
pixels are under luminance 16. A bright even room will look like a different
game. Light it dim, with one warm practical and deep shadows.

---

## Phase 2 — Render the plate

For each camera, rasterize the set only.

Output, before quantisation: 640×480, row 0 = bottom of the frame, linear
or sRGB colour, plus a depth buffer in the calibrated `1/w`.

Then quantise:

- 256 colours, per image, not a global palette.
- Ordered dither. Shipped plates change index on about 61% of neighbour
  samples while the colour step stays small (median RGB step about 24).
  Flat bands will read as wrong.
- Duplicate palette slots are allowed. The engine stores indices. Once the
  palette is chosen, do not rematch by RGB.
- Encode with `imagecodec.encode_di_`. Signature, 640×480, zlib level 9,
  `PALETTEENTRY` with red in byte 0. The loader rejects any other size.

Name the member `<stem>.di_` and point `BGDef` at `<stem>.dib`. The loader
strips the extension and appends `.di_`. Put it in `Bkgnd/<SceneId>.t3d`.
`tools/rtkt3d_write.py` is the archive writer. One plate per condition. A
second state (night, burned, repaired) is another `BGDef` line on the same
view, not a second view. `Condition: 0` and `Condition: 1` are the common
pair. The integer's opcode map is not recovered; copy a condition string
from a working view rather than inventing one.

---

## Phase 3 — Render the depth overlay

Same camera, same meshes that should hide an actor. Do not rasterize the
floor.

For each of 480 rows, merge the occluder fragments into non-overlapping
spans sorted by `x_start`:

```
anchor = x_end if slope < 0 else x_start
1/w(x) = (x - anchor) * slope + base
```

`x_end` is exclusive. Larger `1/w` is nearer. A planar surface is one slope
per row (`d(1/w)/dx`) and a base at the anchor. Coverage on a typical
shipped view is about 20% of the frame. An overlay that covers the floor
will eat the character's feet.

Write the file `tools/rtkovx.py` can parse:

- Magics `0x26aa`, `0x26a9`, width 640, height 480.
- Sparse rows. A row with no occluder is omitted.
- Terminator `0x26a7`.
- `size == 20 + 8*rows + 16*spans`.

There is no encoder yet. Add `write_ovx` beside `parse`, then round-trip
one shipped file before writing a new one. Name the member
`C<chapter><Scene><View>.ovx` and insert it into `C<n>.t3d`. Archive lookup
is case-insensitive. A missing overlay is legal and means actors draw solid,
so a bad overlay is worse than none.

Check: project an NPC standing behind a doorframe. The spans over the
doorframe must have greater `1/w` than the actor's depth. Spans over empty
floor must be absent.

---

## Phase 4 — Render the walk grid

One `.mab` for the scene, shared by both views. Cell size 18. Bounds must
cover every `CamPoly` vertex and every formation point.

| Cell | Byte | When |
|---|---|---|
| Open floor | `0x00` | the party can stand here. This is the common floor, not `@` |
| Marked floor | `0x40` (`@`) | optional rim or scripted marker. Also walkable |
| Wall or void | `0x20` (space) or `0x3f` (`?`) | blocked. `?` is also what an out-of-range sample returns |

Rasterize floor polygons into the grid. A cell the party can cross is
`0x00`. A cell a wall occupies is `0x20`. Leave the outside as `0x3f`.
Height is `(byte & 0x1f) * 6 + base`. Class 0 is the floor. Use a higher
class only for a step you have measured. The neighbour test rejects class
4 or more unless both `0x40` and `0x80` are set.

File layout is the table in `scene-art-depth-collision.md` §6. Header
starts with `CostMap v2`. Extents at `+0x14` and `+0x18` of the 40-byte
block must equal `xmax-xmin` and `abs(ymax-ymin)`. The tile dword at
`+0x24` is 18. `file_size == 104 + rows*cols`.

`write_mab_tile` edits one cell of an existing file. A from-scratch writer
does not exist yet. Add one, then parse it back with `parse_mab`.

Pathfinding is the game's problem (`FUN_00458f40`). Diagonal cost is
`class + 1.414`. You only supply the bytes. `CamPoly` is not a wall.

---

## Phase 5 — Place objects in script

`Loc_All.def` holds the scene, the cameras, the plate names, the
footprints. `ChapterN.def` holds who stands there.

Party formation, copied from chapter 1 and moved onto your floor:

```
Formation : Party_BothStart_<your scene id>_V1
    James_m0 : x, y, z, facing
    Jazhara_m0 : x, y, z, facing
    William_m0 : x, y, z, facing
end
```

Facing is degrees. Z is the floor height you authored, not a value sampled
from `rtkworld.wlx`.

An NPC is a `GroupDef` whose `Members` name a row in `Models.def`, with the
same four floats. Pick an existing body (`Townsman #1` shares `J1Alan.adf`
and only swaps the palette). Give the group a conversation the chapter
already knows how to start, or a one-line script copied from a working
group. Do not invent a new `.adf`.

A door the player opens is an actor plus a `TouchPlateDef` (`Poly`,
optional `PlaneEQ`, `Range`, script). The painted door in the plate is the
closed state. If the door must swing, it cannot only be paint.

`AmbientLight` is four floats and lights the actors, not the plate. Start
from a dim interior such as `0.30, 1, 1, 1`. `Fog` can be the shipped line
`0, 0, 500, 0, 0, 0`.

`rtkdef.py` keeps only the last duplicate field, so a second `BGDef` is
dropped if you round-trip a view through `Block.fields`. Write the `.def`
text yourself, or fix that comparison before using the parser to save.

---

## Phase 6 — Package and check

Mod project, never the install (`python tools/viewer.py --mod mods/<name>`).

Checks, in order:

1. `rtkdib` decodes both plates at 640×480.
2. `rtkovx.parse` accepts both overlays and reports coverage well under a
   full frame. Floor rows are empty.
3. `parse_mab` reports 18-unit cells and the formation points land on
   `0x00`.
4. Scene Studio, with the backdrop flip on, shows the walk grid on the
   floor and the `CamPoly` corners on the right ground. The studio's
   projector is only a guide until Phase 0 has replaced it.
5. In the game: walk onto the new scene, change views by crossing
   `CamPoly`, walk behind the occluder, click the NPC.

---

## Tools to write, and tools to leave alone

| Need | Already in the repo | Still to write |
|---|---|---|
| Decode and encode `.di_` | `rtkdib.py`, `imagecodec.encode_di_` | quantiser and dither aimed at the luminance numbers |
| Parse `.ovx` | `rtkovx.py` | `write_ovx`, plus the span merger |
| Parse `.mab`, poke one tile | `rtkscene.parse_mab`, `write_mab_tile` | a full grid writer |
| Insert archive members | `rtkt3d_write.py` | a scene builder that calls it for `.di_` and `.ovx` |
| Project a point | `project_point` (approximate) | the `FUN_004e7012` camera, calibrated in Phase 0 |
| Edit `.def` text | modkit text path | stop the last-`BGDef`-wins bug before relying on it |
| Draw characters | the game, from `Models.def` | nothing, if you reuse a row |
| Scene `.wlx` | reader only, and only `rtkworld.wlx` is shipped | not for the first scene |

Do not retile the walk grid by hand in a text editor. The floor byte is
`0x00`, which a text editor does not show.

Do not cover the floor in the `.ovx`.

Do not paint James into the plate.

Do not point `T3dWorld` at `1003.wlx` or any other scene world. Those files
are not in the install.
