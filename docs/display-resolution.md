# How the screen is drawn, and what a higher resolution can change

The picture that reaches the monitor is one **640 × 480, 16-bit, 4:3** frame.
Background paintings, 3D characters, the interface, the cursor and fades are
all composited into that frame before it is presented. There is no resolution
key in `RTKRONDOR.INI`. `[Graphics]` stores gamma, the engine choice and a
DirectDraw driver. `[Cinemat] Stretch` is read by `FUN_00451931` into the
application object and belongs to movie playback, separate from this frame.

Nothing below changes the game. Function names are the stable citations;
`python tools/show_func.py out/decompiled/<file>.c <name>` prints a body.

## One frame, two engines

| piece | where it lives | pixels |
|---|---|---|
| Scene paintings (`.di_`) | inline 8-bit buffer in the game object, then a DirectDraw overlay | 640 × 480 indexed |
| Occlusion (`.ovx`) | 480 scanline rows of horizontal spans, in that same pixel grid | 640 × 480 |
| Characters and props | True3D (`t3dll.dll`) rasterized into the camera buffer | 640 × 480, 16-bit |
| Interface, dialogs, inventory | Rtlib32 sprite compositor, drawn into the locked camera buffer | same 640 × 480 |
| Present | `t3dDDrawUpdateDisplay` | that buffer, 1:1 |

Where the interface sprites sit inside that frame is
[`ui.md`](ui.md).

Authored art is 8-bit with one realised palette at a time (see
[`palette-map.md`](palette-map.md)). The framebuffer the player sees is
16-bit. `t3dDDrawInitializeEx` is called with bits-per-pixel `0x10`. After
`GetSurfaceDesc` on the back buffer it classifies the masks into a format
code at offset `0x474`:

| code | masks it matched | `SpriteSetPixelFormat` |
|---|---|---|
| 2 | fallback, and the 0x7C00 case | 5, 5, 5 (RGB555) |
| 3 | 0xF800 | 5, 6, 5 (RGB565) |
| 4, 5 | blue-first variants | the game logs *Unknown pixel format* and aborts |

`FUN_100728b0` is the packer those codes select. A 32-bit desktop only
repeats these 15- or 16-bit values; the frame has no further colour in it.

## How a frame is built

`FUN_0045ceb0` is the tick. It runs the world, then `FUN_0045cfd0`
(*ComposeScene*), then `t3dDDrawUpdateDisplay`.

1. **Backdrop.** `FUN_004fe722` loads the view's `.di_` through
   `ReadCompressedDib` (`FUN_004fea14`) into the buffer at object offset
   `0xb98`, demanding the width and height stored at `0xb80` and `0xb84`.
   Both are initialised to 640 and 480. The loader rejects a file whose
   header disagrees. All 1,585 shipped files are 640 × 480; see
   [`dib-format.md`](dib-format.md).
2. **Overlay upload.** `FUN_0045dccd` locks the scratch overlay and
   `SpriteCompose`s into it. `FUN_00528a87` then
   `t3dDDrawApplyOverlay` with the fast-blit flag, which is
   `IDirectDrawSurface::BltFast` onto the display back buffer. Same-size
   copy. The overlay itself was opened by `FUN_00528a0b` at
   `t3dDDrawOpenOverlay(..., 0x280, 0x1e0, ...)`.
3. **Characters.** Software mode locks that back buffer
   (`t3dDDrawLockBackBuffer`) and points the camera at the locked bits.
   `t3dBeginScene` / `t3dRenderActors` draw into it. The coverage buffer
   from the `.ovx` is installed first (`t3dSetRenderContextCoverageBuffer`),
   which is how a figure disappears behind a doorframe that exists only in
   the painting. Hardware mode (`Engine=1`, the `0x2f8` flag) clears and
   draws through Direct3D into the same camera size.
4. **Interface.** `FUN_0045ddde` calls `SpriteCompose` on the locked camera
   pointer. The destination width and height in that call are the literals
   `0x280` and `0x1e0`. The pitch and the pointer are read from the camera,
   so they follow whatever surface was locked; the rectangle does not.
5. **Present.** `t3dDDrawUpdateDisplay`. Fullscreen flips or fast-blits the
   back buffer. Windowed mode `Blt`s it to the primary using the rectangle
   at offset `0x3c` of the DirectDraw object.

`RtSetScreenRes` in the real boot (`FUN_0050bbd2`) is
`RtSetScreenRes(rt, 0x280, 0x1e0, 0x10, 0)`. The last argument is the
"change the Windows mode" flag, and it is clear, so this call only stores
640 × 480 into the sprite runtime and recentres its viewport
(`FUN_1003a497`: origin at `width/2`, `height/2`). The 8-bit
`RtSetScreenRes(..., 8, 1)` call is the separate `xInitGame` entry, which
does call `ChangeDisplaySettings`.

## What is parameterized, and what is a constant

The 3D projector follows the camera buffer. `t3dSetCameraImageBuffer`
stores width, pitch and height. `t3dSetRenderContextCamera` then sets

```
centerX = width  * 0.5
centerY = height * 0.5
```

and `t3dComputeWorldToEyeCoefficients` scales the view by `cot(half-angle)`
times those centers. The lens is set once, in `FUN_0045bab4`:

```
t3dSetCameraLens(camera, 89.6, 1.3347458, 0.0078125, far)
```

89.6° is the horizontal field. `1.3347458` is the aspect constant (4/3 is
1.333…). Vertical scale is `aspect * cot(half-angle) * centerY`. A buffer
with the same 4:3 shape keeps circles circular and just has more pixels. A
16:9 buffer, with this constant left as it is, draws the world about a third
too wide.

That is the part that would track a larger camera. The rest of the frame
would not:

| site | why 640 × 480 is structural |
|---|---|
| Boot | `xInitGame` and `FUN_0050bbd2` both call `FUN_0043be98(..., 0x280, 0x1e0, ...)`, and that pair is what `t3dSetCameraImageBuffer` receives |
| Backdrop memory | the game object contains the pixel array inline. The constructor zeroes `0x12c00` dwords there: 307,200 bytes, which is `640 * 480` and no more. A larger painting writes off the end of the object |
| Backdrop files | the loader compares the file against the 640 × 480 fields above and fails the load on a mismatch |
| Overlay | created at 640 × 480 and applied with `BltFast`, which does not scale |
| `.ovx` | `FUN_004f5bcd` requires width `0x280` and height `0x1e0` or it reports *Invalid width/height in binary overlay file*. The in-memory tables (`FUN_0043af73`) are 480 entries at `this+0x4bc38` and `this+0x4c3b8`. Spans are x positions in a 640-wide row. See [`ovx-format.md`](ovx-format.md) |
| Interface compose | `FUN_0045ddde` and `FUN_0045dccd` pass width 640 and height 480 as literals |
| Window | `FUN_00433ce0` builds the client rect as 640 × 480 and the style `0x80CA0000` (caption, system menu, minimize). There is no thick frame and no maximize box |
| Startup blit | `FUN_00434374` `BitBlt`s 640 × 480 |
| Screenshots | `FUN_005295d6` rejects a rectangle past `0x280 × 0x1e0` |

`RTKRONDOR.INI` has nowhere to name a size. `DAT_0063f10c`, the value passed
as the fullscreen argument to `t3dDDrawInitializeEx`, sits in the BSS tail of
`.data` (zero-filled at load) and has four absolute references in `RtK.exe`,
all reads. The shipped boot therefore takes the windowed DirectDraw path:
cooperative level `DDSCL_NORMAL` (8), no `SetDisplayMode`, an offscreen back
buffer at the camera size, and a `Blt` into the window.

## The upscale already compiled into `t3dll.dll`

`t3dDDrawInitializeEx` reads two flag bits the game never sets:

| flag | `reg[0xd]` | display size | present |
|---|---|---|---|
| bit 0 (`0x1`) | 1 | camera × 1 | `BltFast` from an extra offscreen surface |
| bit 1 (`0x2`) | 2 | camera × 2 | `Blt` (`DDBLT_WAIT`), which stretches when the sizes differ |
| neither | 0 | camera | draw directly into the back buffer |

The multiplication is applied only when the fullscreen argument is also set.
The extra surface is created at the **original** camera size, and
`t3dDDrawLockBackBuffer` locks that surface when it exists, so the renderer
keeps drawing 640 × 480. `t3dDDrawUpdateDisplay` then stretches it onto the
display back buffer. `t3dDDrawApplyStretchBuffer` is the same stretch, and
nothing in `RtK.exe` calls it.

The game's calls pass `0x48` (the Direct3D attempt: 3D-device cap, video
memory) or `0` (software). Neither includes bit 0 or bit 1.

Turning bit 1 on by itself would still composite wrong. The backdrop is
applied with `BltFast` onto surface slot 4, the **display** back buffer.
The 3D and the interface are drawn into slot 5, the small surface, and the
present then stretches slot 5 over the whole display, covering the backdrop.
The stretch path is real. The frame order in `FUN_0045cfd0` was written for
the 1:1 case, where slot 5 does not exist and both steps hit the same
surface.

`t3dDDrawResize` can rebuild the device for a new camera size and the same
flag. `RtK.exe` does not call it. `t3dDDrawWM_Move_Size` (`FUN_004349a2` on
a move) stores the window client rectangle, in screen coordinates, as the
windowed `Blt` destination. A client larger than 640 × 480 would make that
`Blt` scale the finished frame. The window is created at 640 × 480 without a
sizing frame, so that rectangle stays 640 × 480.

## What each kind of "higher resolution" would actually do

### Scale the finished frame

This is the path that keeps the picture honest. Background, characters,
interface, cursor and fades are already one image, so they stay aligned, and
the `.ovx` keeps meaning what it means.

The frame is 4:3. Integer scales that fit common desktops:

| desktop | largest integer fit | scaled frame | border |
|---|---|---|---|
| 1920 × 1080 | 2× | 1280 × 960 | 320 px spare width, 120 px spare height |
| 1920 × 1200 | 2× | 1280 × 960 | wider vertical margin |
| 2560 × 1440 | 3× | 1920 × 1440 | 320 px each side, height filled |
| 3840 × 2160 | 4× | 2560 × 1920 | 640 px spare width, 240 px spare height |

1080p is not an integer multiple: 1920/640 = 3 and 1080/480 = 2.25. Filling
the height means a 1440 × 1080 image with 240 px of black on each side.
Point sampling at 2.25× makes some source pixels two output pixels and some
three, which reads as shimmer on edges. Integer 2× (1280 × 960, centered) is
the clean point-sample result on a 1080p monitor. A filtered scale is the
way to fill the height evenly.

Filter choice is one choice for the whole frame. The paintings and the
interface text share the buffer, so a sharp pixel scaler keeps the UI
readable and leaves the paintings blocky, and a soft or filmic scaler flatters
the paintings and blurs the text. There is no separate UI layer to filter
differently at present time.

Pointer input is in the same 640 × 480 client space. A presenter that owns a
larger window has to map the cursor back down. DirectDraw wrappers that
replace the present (`DDrawCompat`, dgVoodoo2 and the same family) do that
mapping, and they also absorb the exclusive-mode `SetDisplayMode(640, 480, 16)`
the fullscreen path would issue. That is the practical way to get a borderless
window on a current desktop. Windows' own DPI stretch of the 640 × 480 window
is the same idea at the worst quality, applied to the whole window including
its frame.

The DLL's 2× blit is a cruder version of this: 1280 × 960, fullscreen only,
and only after the backdrop blit is aimed at the small surface. Quality is
whatever `IDirectDrawSurface::Blt` does in the installed DirectDraw
implementation, which on current Windows is the emulator's stretch.

### Draw the 3D larger and leave the paintings

`t3dSetCameraImageBuffer` plus a matching `RtSetScreenRes` would make
characters rasterize at the new size, at the same 89.6° field, provided the
new size stays 4:3 so the aspect constant still matches. The paintings would
then be the soft layer: they are offline renders at 640 × 480, and the
install contains no larger source. The coverage mask would also be wrong.
`t3dSetRenderContextCoverageBuffer` copies `height` rows from the arrays the
game built, and those arrays are 480 long with spans measured across 640
columns. A taller buffer reads off the end of them. A wider buffer tests
occlusion at the wrong x. Doorframes, columns and tabletops would stop hiding
the figures that walk behind them.

The interface compose would still write a 640 × 480 rectangle. The inline
backdrop array would still be 307,200 bytes.

### Replace the paintings

A real internal resolution means new assets, not a scale factor. Each view
needs a backdrop at the new size (the loader and the inline buffer both have
to grow with it) and an `.ovx` regenerated in that pixel grid (the parser's
checks are equality tests against 640 and 480). The lens aspect constant has
to stay equal to width/height. The compose calls, the overlay open, the
window rect and `RtSetScreenRes` have to take the same pair. UI bitmaps are
authored in the centered 640 × 480 sprite space; they would sit in the middle
of a larger frame at their original pixel size unless they are redrawn or the
compositor is taught to scale them.

Widescreen is the same work plus a new aspect constant. The current paintings
are 4:3. A wider frame has to come from new art, or from cropping the
existing art and accepting a narrower vertical field.

## Summary

The modern-quality win that preserves the game is to scale the finished
640 × 480 frame: integer when the filter is point sampling, filtered when the
goal is to fill a 16:9 height, always with the 4:3 frame intact and the
pointer mapped back. The engine already contains a 2× version of that idea,
unused, and wired to the wrong surface for the backdrop. Drawing the world
itself at a higher resolution is a content problem. The projector would
follow, and the paintings, the occlusion masks, the interface rectangle and
the inline backdrop buffer would not.
