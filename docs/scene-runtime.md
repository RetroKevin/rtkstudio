# In-game scenes

How a location in Return to Krondor is put on screen, how the player walks
through it, and how the camera and the map change. This is the runtime. The
byte layouts of the two big per-view files are already written up elsewhere:
the painted backdrop in [`dib-format.md`](dib-format.md), the depth overlay in
[`ovx-format.md`](ovx-format.md). The cost-map files are introduced in
[`asset-inventory.md`](asset-inventory.md). What a new scene has to contain,
measured across the whole install, is in
[`scene-art-depth-collision.md`](scene-art-depth-collision.md).

Function names are the stable citations. `RtK.c` line numbers move every time
the decompile is regenerated; `python tools/show_func.py out/decompiled/RtK.c FUN_004b76ce`
re-finds one.

---

## 1. The model

A playable location is three nested objects, held on the scene root at
`DAT_00628d6c`:

| Slot | What it is |
|---|---|
| `+0x18` | the chapter |
| `+0x1c` | the scene (one room, street, or wilderness node) |
| `+0x20` | the active **view** — one fixed camera |
| `+0x28` | the view waiting to become active |
| `+0x30` | the True3D world |
| `+0x2c` | the render context |
| `+0x3c` | the camera |
| `*DAT_00628d6c` | the walk grid (the cost map) |

A view is one prerendered photograph of that place: a 640×480 painting, a
matching depth overlay, and a camera whose lens and position were authored to
match the painting. Characters are real 3D actors standing in the True3D
world. Each frame the painting is drawn first, then the actors are rendered
with that camera and laid on top, and the depth overlay punches out the actor
pixels that the painting should hide.

Several views share one scene. They share the True3D world and the walk grid.
Only the painting, the depth overlay, and the camera change when the angle
changes.

The chapter's pictures live in `C0.t3d` … `C10.t3d`. A scene also names its
own True3D world file (the path is on the scene at `+0x18`). When a global
flag at `DAT_00628d6c[0xce]` is set, that path is ignored and the loader
opens `rtkworld.wlx` instead — the giant placeholder box documented in
[`world-format.md`](world-format.md).

---

## 2. Backdrop and depth

### What is loaded, and in what order

Switching to a view ends in `FUN_0043bbfe`, which frees the previous view's
pictures, installs the pending view as current, calls `FUN_004c215d`, and
then `t3dSetRenderContextCamera`.

`FUN_004c215d` does four things, in order:

1. `FUN_004c27ba` picks the backdrop record. Its name is the string at
   `view+4`.
2. `FUN_004fe722` loads that `.di_` (or a plain `.dib`) into the scene root:
   palette at `+0x778`, 640×480 indices, descriptor at `+0xb78`. Failure logs
   `Failed to load background dib`.
3. `SpriteSetBackground` hands that descriptor to the 2D sprite engine.
4. `FUN_004c21d3` → `FUN_004e7012` aims the camera, then
   `FUN_004e579e(view+0xb0)` loads the depth overlay.

The overlay name is built by `FUN_004e5829` / `FUN_004e58b6` as `C%d%s%s`
plus `.ovx`, and `FUN_004fedbe` pulls that member out of `C<n>.t3d`. The
parser (`FUN_004f5bcd`, via `FUN_0043afb1`) fills two tables on the scene
root: a count per scanline at `+0x4bc38` and a pointer per scanline at
`+0x4c3b8`. There is no decompression. The file is the buffer.

The backdrop name and the overlay name are built by different code. The
overlay pattern is fixed (`C0S00010001Vw1.ovx` and its siblings). The
backdrop name is whatever string the view record holds, and shipped stems
are not all of that shape. There are 1,585 backdrops and 1,713 overlays, so
the two sets are not a global 1:1. One activated view still loads one
backdrop and one overlay. A missing or rejected overlay leaves the count
table empty, and actors draw with nothing to hide behind.

### The camera is matched to the painting

`FUN_004e7012` reads the view's camera record (the object at `view+0x14`,
type `CCameraDef`) and calls:

```c
t3dSetCameraLens(camera,
    field * 512.0 * (1/360),
    (field * 512.0 * (1/360)) / 67.1289,
    1/128,                          /* 0.0078125, the near plane */
    *(float *)(DAT_00628d6c + 0x40));
t3dSetCameraLocation(world, camera, originAndAim);
```

`field` is the float at camera-def `+0x18`. `t3dSetCameraLens` stores half
of the first argument at `camera+0x20` and the second argument at
`camera+0x24`. Those two are what the click unproject later takes the
cotangent of. The near plane is `1/128`. The far plane is the scene-root
float at `+0x40`.

`t3dSetCameraLocation` refuses the position unless
`t3dGetRegionNumberFromWorldAndXYZ` finds a region under it. The camera has
to sit inside the True3D world, not merely in front of the painting. It
stores the region index and six floats (position and aim) on the camera.

The render buffers are 640×480, the same size as every backdrop and every
overlay. Pixel `(x, y)` means the same thing in all three.

### How a frame is stacked

`FUN_0045cfd0` is the compose. Back to front:

1. The backdrop. `FUN_0045dccd` installs the `.di_` palette and
   `SpriteCompose` blits the 640×480 indices. This is a 2D blit. The painting
   is not a textured polygon in the 3D world.
2. `t3dBeginScene`.
3. `FUN_0043b014` hands the overlay's two tables to
   `t3dSetRenderContextCoverageBuffer`. The software path copies the spans
   into the render context. The D3D path (`FUN_10015160`) turns each span
   into a depth primitive. Null tables mean "no occluders".
4. `FUN_0045d744` draws the actors with `t3dRenderActors`, into the camera's
   image buffer. Gameplay does not go through `t3dRenderScene`; that export
   clears the coverage buffer on its way in.
5. `FUN_0045ddde` composites the camera buffer over the backdrop with another
   `SpriteCompose`.
6. Fades, the cursor, and the interface overlays, then the display update.

An actor's on-screen size is ordinary perspective. The sprite is a 3D object
at a world position, seen by the camera that was lined up with the painting.
Nothing in the backdrop rescales the character. Standing further along the
camera's axis makes the sprite smaller because the lens says so.

### How a wall hides a character

The overlay is a sparse depth buffer. For each of the 480 rows it stores a
sorted list of horizontal runs. Each run is `x_start`, an exclusive `x_end`,
and a straight line in `1/w` (larger means closer). About 23% of pixels have
a run. Open floor is usually absent, which means "nothing here is in front
of an actor".

During the software actor rasterizer `FUN_1002d930`, each fragment's
reciprocal eye depth is `1 / param_3[2]`. Where a coverage run overlaps that
fragment and the run's `1/w` is greater than or equal to the fragment's, the
run keeps the pixel and the actor colour is not written. Where the actor is
closer, the run is clipped back — including along its slope, so a receding
wall can hide the feet and not the head — and the actor is drawn in the gap.
Rows with a zero count take the fast path and draw the actor solid.

That is the whole illusion. The painting is already on the screen. The 3D
pass only has to decline to cover the pixels whose painted surface is nearer
than the actor.

The same `1/w` is what a click uses. `FUN_00453c54` samples the run under the
cursor with `FUN_00454596`, inverts it to `w`, and `FUN_00454654` unprojects
`(x, y, w)` through the camera:

```
dx = ((x - (halfWidth - 0.5)) * w / halfWidth) / cot(camera+0x20)
dy = (((halfHeight - 0.5) - y) * w / halfHeight) / (cot(camera+0x20) * camera+0x24)
```

with `halfWidth` / `halfHeight` from the render context at `+0x194` / `+0x198`,
then subtracts the camera origin. The absolute world unit of `w` is still
open. `1/w ≈ 0.0046` (`w ≈ 217`) is a typical mid-scene value, and it is
consistent with this lens, but it has not been tied to the walk grid's units.

---

## 3. Where the player can walk

Walking is decided by a 2D cost grid, one per scene, loaded from a `.mab`
file. The grid is not the depth overlay, and it is not the True3D region's
wall list. Those three answer different questions: the overlay hides pixels,
the grid decides whether a step is legal, the region supplies a floor height
and a 3D collision surface.

### The file

`FUN_00420cd9` builds a path from the scene name and tries the v2 reader
`FUN_00420e9c`. If that fails it falls through to the legacy text reader
`FUN_00421062`.

The v2 reader is `fread`, not a line reader. `FUN_00420e9c` reads 64 bytes
(`0x40`) that must begin with `CostMap v2`, then 40 bytes (`0x28`) into
`local_12c`, then one raw byte per tile. The 40 bytes sit at file offset 64.
Stack slots relative to `local_12c` (`ebp-0x12c`) fix the field order.
`local_11c` is `+0x10`, `local_110` is `+0x1c`, `local_10c` is `+0x20`.
Reading rows and columns from `+0x14` and `+0x18` matches 0 of the 53 files.
`file_size == 104 + rows*cols` holds for all 53 only when those counts are
taken from `+0x1c` and `+0x20`.

| Bytes in the 40 | Where it lands | Meaning |
|---|---|---|
| `0x00`–`0x0f` | cost map `+0x00`…`+0x0c` | world bounds, four floats: xmin, ymin, xmax, ymax |
| `0x10` | `+0x14` via `local_11c` | base height, added to every tile's class |
| `0x14` | not copied | f32 X extent. Equals `xmax-xmin` and `cols*18` on all 53 files |
| `0x18` | not copied | f32 Y extent. Equals `abs(ymax-ymin)` and `rows*18` |
| `0x1c` | `+0x24` via `local_110` | row count. The reader loops on this |
| `0x20` | `+0x28` via `local_10c` | column count, and the byte count of each `fread` |
| `0x24` | read, never stored | u32 tile size. `18` in all 53 files. Runtime computes its own at `+0x2c` |

The integer tile size at `+0x2c` is the world extent divided by the grid
dimension. Every shipped file's own note says that size is 18. `+0x30` is
`1 / tileSize`. World XY converts to a cell with `FUN_00421321` and back
with `FUN_004213a9`, which returns the cell centre.

Out of range, `FUN_004215f9` returns the byte `0x3f`, which is the character
`?`. The same byte is what fills most of the file.

### What a tile byte means

The v2 grid stores the character as the byte. The engine never translates
it. The tests treat that byte as flags:

| Bits | Test | Effect |
|---|---|---|
| `0x20` | `FUN_004219b6`, `FUN_0040db43` | hard block. The search will not step here, and a straight shot dies on it |
| `0x1f` | both, and the mouse ray | the class: a height and a step cost, 0–31 |
| `0x80` | `FUN_0042168c` | ignore the grid byte and read the overlay table at `+0x44` instead |
| `0x80` and `0x40` together | `FUN_004219b6` | walkable even when the class is 4 or more |

`FUN_004219b6` accepts a neighbour when bit `0x20` is clear and either the
class is below 4 or both high bits are set. Anything else is a wall as far
as the search is concerned.

Applied to the characters the inventory counted:

| Character | Byte | Class | Search |
|---|---|---|---|
| `?` | `0x3f` | 31 | blocked, and the out-of-range sentinel |
| space | `0x20` | 0 | blocked |
| `@` | `0x40` | 0 | walkable. 7,355 tiles. A marked floor, often the rim of a corridor |
| NUL | `0x00` | 0 | walkable. 198,780 tiles. This is the ordinary open floor. A text editor does not show it |
| `"` `!` `#` `a` `b` | `0x22` `0x21` `0x23` `0x61` `0x62` | 1–3 | blocked. Same height band as a cheap floor, but not a path node |

`A`, `B`, and `C` (`0x41`–`0x43`) would be walkable floors of class 1, 2,
and 3. They are legal; they are just rare in the shipped grids. `D` onward
in that run has bit `0x20` clear but a class of 4 or more, so the neighbour
test rejects it.

The legacy text reader is the same bitfield written out as letters.
`X` becomes `0x3f`. `A`–`Z` become classes 0–25 with no extra bits. `a`–`z`
become `0x40` plus the letter's place (`a` → `@`, `b` → `A`, …). A v2 file
is that encoding already, stored so a text editor can see it.

The mouse ray in `FUN_00421af1` walks the same grid in 3D. A tile's surface
height is

```
(byte & 0x1f) * scale + base
```

`scale` defaults to 6 (`cost map +0x18`, set in the constructor) and `base`
is the header dword at `+0x14`. So `?`, class 31, stands `186 + base` above
the floor, and `@`, class 0, is the floor itself. The ray is how a click
finds the ground when the depth overlay has no run under the cursor. The
height also rejects a step whose clearance is below the class: `FUN_0040db43`
compares a clearance value (the direct-path call passes `18.0`) against
`byte & 0x1f`.

### The search

`FUN_00458f40` is the move order. It converts the actor and the destination
to cells. If they fall in the same cell, or the world distance is at most
`0.01`, it skips the search and steps straight there. Otherwise
`FUN_0040f681` → `FUN_0040ddeb`.

`FUN_0040ddeb` first tries a straight shot with `FUN_0040db43`, a grid
Bresenham. The shot fails on bit `0x20` or on a class the clearance cannot
clear. When the shot is clear the path is the two endpoints and nothing
else.

Otherwise `FUN_0040e96f` runs an A* search:

- The graph is the 8 neighbours of a cell. `FUN_0040ed5a` picks which
  quadrant the goal is in, and the eight expanders (`FUN_0040efe1` and its
  siblings) try every direction, goal-ward first.
- A neighbour has to pass `FUN_004219b6`. The goal cell is allowed through
  even when that test fails, so a click can finish on a blocked tile the
  path only touches at the end.
- Step cost, from `FUN_0040f2e5`: an orthogonal step costs `class + 1`. A
  diagonal step costs `class + DAT_005c9314` (a tunable constant, not a
  hard-coded √2 in the decompile).
- The heuristic (`FUN_0040ecb1`, mode in `DAT_0061e5c8`) is Manhattan, the
  Chebyshev distance (the larger of |dx| and |dy|), or a random number.
- Each node stores `g` at `+4`, `h` at `+8`, and `f = g + h` at `+0`. The
  open list (`DAT_0061e5c0`) is a linked list kept sorted by `f`
  (`FUN_0040f42a` inserts, `FUN_0040f3b0` pops the head). A node already on
  the open or closed list is only updated when the new `f` is smaller.
- The parent pointer is `+0x14`. After the goal is popped, `FUN_0040ddeb`
  walks the parents, drops collinear corners, and converts the cells back
  to world XY.

`FUN_00458f40` keeps that polyline and the locomotion code follows it.
Scripted travel is a second layer on top: a `CPathDef` is a list of
waypoints, and `FUN_004eecc0` feeds them to `FUN_004ef00a`, which calls
`FUN_00458f40` for each leg. The party leader is the actor that searches.
The other members are attached to the party track named `party` when the
scene loads (`FUN_004bd829` inside `FUN_004b7018`).

---

## 4. Collisions

Three different blockers, checked by different code.

### The grid

This is what stops the player walking through a wall of the painting. The
search never enters a tile with bit `0x20`, and `FUN_0040db43` cuts a
straight line on the same bit or on a class above the mover's clearance.
The authoring tool baked the walls into the `.mab`. At runtime the wall
planes are not re-tested on every step of a walk.

A second, coarser exclusion exists as 2D polygons on the scene. `FUN_0042b245`
is a point-in-polygon test. `FUN_004da51e` runs it over the scene's polygon
list and rejects a click that lands inside one. Those polygons are also how
a view decides it owns a point; see the camera section.

### True3D regions, floors, walls, obstacles

The world loaded by `FUN_004fd3ca` (`t3dParseReadWorldWithPalette`) is a
region mesh. `t3dGetRegionNumberFromWorldAndXYZ` walks a BSP from
`world+0xc` and returns the leaf region. Each region has:

- a floor plane at `region+0x30`. `t3dGetRegionFloorHeight(region, x, z)`
  solves it for Y:

  ```
  Y = (nz * z + nx * x + d) / -ny
  ```

- walls, with their own planes, vertex lists, and render methods
  (`t3dGetRegionNumWalls`, `t3dGetRegionWallPlane`, …)
- obstacles (`t3dGetRegionNumObstacles`). An obstacle whose type is `0xe`
  carries an edge polygon; subtypes `0x26`, `0x27`, and `0x29` are the ones
  `FUN_004f2aea` reads a plane from. `t3dIsObstacleFloor` is bit 0 of the
  obstacle's flags. `t3dGetObstacleNextRegion` exists in `t3dll` and has no
  caller in `RtK.c`
- lights, sounds, and a reverb offset and volume

`FUN_004fafe3` is the placement helper. It reads the actor's position, finds
the region, samples the floor height, clamps a negative height to 0, adds a
per-view foot offset (`DAT_0062aef8` / `DAT_0062aefc`, via `FUN_00435c24` or
`FUN_00435b68`), and writes the actor back with `t3dSetActorLocation`.

`t3dCollisionDetection` is the swept test against this geometry.
`FUN_004f9c57` and `FUN_004f2aea` use it as a short probe (a sphere cast of
length 4400 along a view vector) and, on an edge-polygon hit, copy the
plane out. `t3dGetCollisionNodeSkitterVector` in `t3dll` computes the slide
along a hit of type `0x12` or `0x13`. `RtK.c` never calls
`t3dGetSkitterAmount`. Sliding, if it happens for these actors, happens
inside the engine during the collision call, not in the path search.

`t3dPickObjectOnScreen` (`FUN_004f2fc5`) is the screen-space version of the
same mesh. It builds a camera ray and accepts a hit only when the picked
object's type is `0x28` and its user data is `0x13` — a region wall — then
returns the region index and the wall index. That is the editor's wall
picker and one of the click paths. It is not the walk blocker.

### Other actors

`t3dCollisionWithActors` tests the mover's volume against other actors'
sprite volumes. The adventure code around `RtK.c` 19964 dispatches on
volume types 2, 4, and `0x22`. `FUN_0044ca1f` sweeps a sphere against an
edge list with `t3dMovingSphereWithXYZEdge` for party-versus-party and
party-versus-prop blocking. `t3dDetectNearestActorAlongPath` and
`t3dPickSpriteFaceAlongPath` are the "who is standing on this line" queries
used when a click might be on a character rather than the floor.

Combat reuses the actor volumes and has its own grid. `FUN_004ac838`
(`DetermineCost` in the log strings) compares a distance against the combat
board at `DAT_00628d6c+0x36c` and returns a tier 0, 1, or 2. It does not
search the scene's `.mab`.

The strings `POLY_ACD`, `POLY_INST`, and `poly1.spr` belong to
`FUN_004f4524`, an in-engine polygon drawing mode. They are not the walk
grid and they are not the depth overlay.

---

## 5. Changing the camera

A view change keeps the chapter, the scene, the True3D world, and the walk
grid. It swaps the painting, the depth overlay, and the camera.

### Who asks for it

Three callers, all of which end in `FUN_004b76ce` or its numeric wrapper
`FUN_004b7c9c`:

- **Walking into another view's footprint.** `FUN_004125f6` reads the party
  leader's position and tests it against each candidate view's polygon list
  at `view+0xf4` (`FUN_0042b245`), including views linked from the current
  one at `view+0x15c`. It picks the best candidate (`FUN_00412148` /
  `FUN_004121f3`) and will not switch again for 3000 ms of world time unless
  forced. The game loop then calls `FUN_004b7c9c` with the same chapter, the
  same scene, and the new view index.
- **The exit table.** `FUN_0041a03b` walks the array at `scene+0x1c`. Each
  record's `+0x10` is a view index. It finds the record for the current view
  and steps to the previous or next one, skipping any index absent from the
  `ValidCameraViews` list (`+0x4bbc4`, tested by `FUN_0043ac72`). The
  keyboard cases `0x71`–`0x76` call this. It only runs when camera switching
  is enabled (`DAT_00628d6c+0x4bbbc`, set from the script call
  `ValidCameraViews`).
- **Script and debug.** `GotoNextView` advances to the next view in the
  scene, then the next scene, then the next chapter. `xGotoScene` and the
  scene object's `GotoScene` can name a view in the same breath as a new
  scene; see the next section.

`FUN_00411eae`, run once the new view index is known, rebuilds the
linked-view list at `view+0x158` by testing which neighbouring views'
polygons overlap this view's footprint.

### What the switch does

`FUN_004b6e2f` is the loader. It updates the chapter pointer, calls
`FUN_004b7018` (which reloads the world only when the scene object actually
changed), resolves the view index with `FUN_004bf911`, and parks the view
with `FUN_0043bba5`. Parking writes the pending slot at `+0x28` and does not
touch the camera yet.

The frame loop notices `+0x28` and calls `FUN_0043bbfe`:

- `FUN_0043bc99` → `FUN_004c20fa` drops the old overlay (`FUN_004ff00c`) and
  zeroes the coverage tables (`FUN_0043af73`).
- `FUN_004c215d` loads the new backdrop, aims the camera, loads the new
  overlay.
- `t3dSetRenderContextCamera` makes that camera the one the 3D pass uses.

`OnExit` / `OnEnter` do not fire for this. In `FUN_004b76ce` those script
calls, and the clearing of the `ValidCameraViews` list, are gated on
`bVar1` (the chapter or the scene changed) or on the overlay object at
`+0x348`. A pure angle change leaves the scene script running.

The fade flag works the same way. `param_5` is 0 (never), 1 (always), or 2
(only when the chapter, the scene, or that overlay object says something
changed). `xGotoScene` passes 2. A view-only switch under mode 2 does not
fade. When a fade does run, `FUN_004b7568` steps the overlay at `+0x4bba0`
twelve times with `Sleep(duration/10)`, duration from `DAT_00628d6c+800`.
The alternate path `FUN_004b74c5` uses the scratch-buffer fade when
`+0x31c` is set. Coming back in, `FUN_0045ea79` arms the compose-time fade.

---

## 6. Changing the map

A map change is the same function with a different scene pointer.

### From script

`xGotoScene` pulls three strings out of the string table — chapter, scene,
view — and calls `FUN_004b75f3` with fade mode 2. The scene object's own
`GotoScene` handler does the same with the arguments the script passed.
`FUN_004b75f3` resolves the names (`FUN_004e4173` for the chapter,
`FUN_004bc5d4` for the scene, `FUN_004bf5d9` for the view) and calls
`FUN_004b76ce`. A miss logs `Given scene does NOT exist`.

`FUN_004b7c9c` is the same transition with integer indexes. A chapter index
of `-1` means "stay in this chapter".

### What is torn down and what is kept

`FUN_004b76ce` notices that `+0x18` or `+0x1c` changed (`bVar1`):

1. The current scene gets `OnExit` (virtual call at `+0x30` with the string
   `OnExit`), provided a scene is loaded.
2. The fade runs, as above.
3. `FUN_004b6e2f` → `FUN_004b7018` does the reload. It logs `Loading Scene`,
   calls `FUN_004ff505` and `FUN_004b6de9` to drop the old scene's tracks,
   and — when the world path or the reload flag says so — `FUN_004fd3ca`
   destroys and recreates the True3D world from the scene's world file (or
   from `rtkworld.wlx`). The same load looks up `HOTSPOT_ACD` and
   `SPELLGEN_ACD` in the world dictionary and shares those objects.
4. If the world path or the scene field at `+0x19c` changed, the old cost
   map is freed and a new `.mab` is built (`FUN_004fd7c2`).
5. The party track is rebound. `FUN_004bd829` looks up `party` and stores
   that actor at `DAT_00628d6c[1]`.
6. The pending view is set, and `FUN_00411eae` rebuilds view links.
7. Back in `FUN_004b76ce`, the `ValidCameraViews` list is freed, the new
   scene gets `OnEnter`, and `FUN_004c0edd` / `FUN_004c0f13` finish scene
   startup.
8. The pending view is applied on the next compose, exactly as a camera
   change would.

Two scene changes that name the same world file skip the `t3d` reload. The
cost map is also kept when the path and `+0x19c` match. The backdrop and
overlay are still replaced, because those belong to the view.

`RtSceneIn` / `RtSceneOut` are a different mechanism. In `RtK.exe` they are
import thunks. In `Rtlib32` they load and tear down a PyroTechnix `.rtk`
scene for the editor shell (`FUN_0052f312` calls `RtSceneIn` after
`SetCurrentDirectory`). The game's own map changes go through `FUN_004b75f3`,
not through those two.

---

## 7. The rest of what lives on a scene

**Clicks.** `FUN_00453c13` → `FUN_00453c54` classifies a point on the
painting. Roughly in order: the interface overlay, a camera ray
(`FUN_0043591a`), a depth sample when coverage is enabled, an actor hit
along that ray (`FUN_004fa544`), a cost-map ray (`FUN_004221c3` /
`FUN_00421af1`) that becomes a walk destination, and the 2D exclusion
polygons. A second coverage buffer can veto the depth sample when the two
`w` values differ by more than `0.001`, which is how a click distinguishes
"on the actor" from "on the wall behind the actor". The walk destination
that survives is handed to `FUN_00458f40`.

**Clicks, talk, doors, teleports.** The pick itself is summarised above.
What a click then does — walk, talk, a locked door, a touch plate, a
`Teleport` — is written up in [`interactions.md`](interactions.md).
`UseHotSpots` only arms the hotspot *light* actor (`DAT_00628d6c+0x304`).
It is not the door.

**Light and sound.** Regions and zones carry ambient light, point lights,
directional lights, sounds, and reverb (`t3dAddPointLightToRegion`,
`t3dSetRegionReverbVolume`, `t3dSetZoneReverbVolume`, and the zone
membership calls). A zone is a named set of regions. None of that affects
the walk grid. It is why the same room can change its lighting without a
new painting, and why a region can have its own reverb.

**Script surface.** The scene object registers `GotoScene`, `OnEnter`,
`OnExit`, `GetView`, and the audio and conversation accessors. The game
object registers `ChangeCameraView`, `AutoCameraSwitching`,
`AutoCameraHeuristics`, `ValidCameraViews`, and `UseHotSpots`. Those names
are the vocabulary of the chapter scripts. The inflated `.def` / `.rtk` /
`.tbl` sources are not checked out under `out/plaintext` in this workspace;
the names above are the ones the executable registers.

**What a scene is made of, collected.** One True3D world. One `.mab`. One
or more views, and for each view a backdrop, an `.ovx`, a camera record,
and a footprint polygon. An exit table of view indexes. Optional linked
views, scripted waypoint paths, hotspot actors, lights, and sounds.

---

## 8. Open questions

- **Units of `w`.** Reciprocal view depth is proven, and the unproject
  formula is proven. The number has not been matched to the cost map's
  18-unit tiles or to the region floor's coordinates.
- **The two extent floats and the trailing tile-size dword** of the v2 field
  block are redundant with the bounds and with `rows`/`cols`. The loader
  recomputes both. What the 64-byte header stores past the `CostMap v2` text
  is still padding; the reader only `strncmp`s the prefix.
- **`DAT_005c9314`** is the diagonal step surcharge. The shipped dword at
  `RtK.exe` VA `0x005c9314` is `f4 fd b4 3f`, float `1.4140000343322754`
  (a rounded √2, not the full `1.41421356`). `FUN_0040d74b` is what writes
  the global. An orthogonal step costs `class + 1`. A diagonal step costs
  `class + 1.414`.
- **Whether adventure movement calls `t3dCollisionDetection` every frame.**
  The probes that were traced are short casts. The thing that actually
  stops a walk is the `.mab` search. Continuous sliding would have to be
  inside `t3dll`, and `t3dGetSkitterAmount` has no `RtK.c` caller.
- **`t3dGetObstacleNextRegion`.** Implemented, unused from `RtK.c`. Stairs
  and landings are visible as edge-polygon subtypes and as floor-flagged
  obstacles; the code that would stitch two regions together through an
  obstacle was not found on the game side.
- **The exact fields of an exit record** past `+0x10` (the view index) and
  the enable flag the view linker tests. The on-disk scene definition that
  fills `scene+0x1c` was not walked.
- **How `FUN_004fafe3` assigns the floor height to a component.** It samples
  the plane and clamps a negative result to 0, and it writes an actor
  location that also includes the view's foot offset. The decompile drops
  the store that would show which of X, Y, Z receives the plane result.
- **DIB-to-OVX name pairing** beyond "whichever view is being activated".
  The overlay name is built in code. The backdrop name is a string on the
  view.
