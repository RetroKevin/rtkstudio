# USB controller support

What it would take to drive Return to Krondor from a USB gamepad.
Nothing here is implemented. The keyboard and mouse pipeline it would
have to feed is [`controls.md`](controls.md).

The game is a pointer game that also has a few held keys. Plugging in
a pad does not play it. The engine's joystick code is the 1998
multimedia API, its action table is empty, and an Xbox-style pad usually
does not appear on that API at all.

---

## 1. What already runs

`FUN_100113c0` in `Rtlib32` runs at library startup when
`7THLEVEL.INI` key `MaxJoySticks` is non-zero. The default in the
`GetPrivateProfileIntA` call is 2. For joystick ids 0 and 1 it calls
`joySetCapture` on the library window (`DAT_1005cfa0+0xcd8`, the
`VIEW_CLASS` window from `FUN_1001c54f`), period 10 ms, changed-only.
The center is whatever `joyGetPos` returns at that moment, stored at
`+0x36ab` (stick 1) and `+0x36b3` (stick 2). `FUN_10011baa` releases
both captures. `FUN_1001c466` also opens the installable `joystick`
driver and reads `joycal0` / `joycal1` from `system.ini`. That is
calibration for the old driver, not a button map.

Messages arrive at that library window, not at `CGameWindow`.

| Message | Meaning |
|---|---|
| `0x3a0` | `MM_JOY1MOVE` |
| `0x3a1` | `MM_JOY2MOVE` |
| `0x3b5`, `0x3b7` | stick 1 button down, button up |
| `0x3b6`, `0x3b8` | stick 2 button down, button up |

The window procedure calls `FUN_1001187a` unless `RtPause` has set the
byte at `+0x95db`. `FUN_1001187a` offers the optional hook at
`+0x18b3` first. That pointer is cleared during library init and
`RtK.exe` never stores one. With the byte at `+0x95ca` also clear
(it is cleared in the same init), the stick is quantized and looked
up in a table of 34 script ids at `DAT_1005cfa0+0x3e6b`.

`FUN_100117d4` is the quantizer, and it is the one that runs.
`+0x95d0` selects the coarser `FUN_10011724`, and that flag starts
clear. The deadzone is 16000 units either side of the captured center,
on axes that range to 65535. The result is a small integer:

| Value | Stick, relative to the captured center |
|---|---|
| `0` | inside the deadzone |
| `1` | +X |
| `2` | −X |
| `3` | −Y |
| `4` | +X and −Y |
| `5` | −X and −Y |
| `6` | +Y |
| `7` | +X and +Y |
| `8` | −X and +Y |

Stick 1 uses that value as the table index. Stick 2 adds `0x11`, so
it uses entries 17–33. Buttons use `FUN_1001164d`. It watches the
change bits `0x100`, `0x200`, `0x400`, `0x800` (four buttons) and
stores a pressed index and a released index in slots 9–16 for stick 1,
plus `0x11` for stick 2. There is no fifth button, no second stick
axis, no trigger, and no hat beyond what the driver already folded
into X and Y.

A non-zero table entry is passed to `FUN_10021b08`, which calls
`RtCallScriptReplacementFunc`. That looks up a C function registered
with `RtAddScriptReplacementFunc`. The registrations in `RtK.exe` are
UI callbacks (page turns, party sheet, a handful of puzzle ids). None
of them is a joystick slot.

The table itself is filled by script opcode `0x65`
(`FUN_100172e6`, a 12-byte instruction: slot, then a script id).
Both startup paths zero all 34 entries (`FUN_1001ee58`,
`FUN_1001f9f2`). A scan of the extracted non-bitmap resources found no
such instruction. The archive has no type-14 resources, which is the
type the program walker `FUN_10021c7a` requires, and the 39 SCRIPT
resources are 8 bytes each, shorter than one opcode `0x65`. Nothing in
`RtK.c` writes the table.

So a device Windows still exposes as multimedia joystick 0 is captured,
quantized, and then dropped, because every slot is 0.

An Xbox pad, and most pads Steam or Windows presents as XInput, never
gets that far. `joySetCapture` does not see XInput devices. The public
binary does not link `XInput`, `dinput`, or Raw Input.

---

## 2. What a pad has to be able to do

Two different systems consume input. [`controls.md`](controls.md)
separates them. A pad has to reach both, or menus and the world will
not agree.

**Held actor commands** move and turn the party. Up is command `1`
(Move Forward), Left is `5` (Turn CCW), Right is `4` (Turn CW), all
Held Down, navigation mode, destination Actor. Command `2` (Move
Backward) is implemented in `FUN_00403b42` and has no key. There is no
strafe and no analog speed. The tick reads six on/off flags.

**A screen point plus a click** does everything else: walk to a spot,
talk, open a door, inventory, dialogs, combat clicking. That point is
the mouse `lParam` on `WM_MOUSEMOVE` / button messages, looked up in
the same binding maps. The widget layer (`WinCtrl_Mouse`,
`WinCtrl_Browse`) only runs because the `Interface` map turns those
messages into `FUN_004b9657` / `FUN_004b9779`. Those two functions
ignore a point outside `0 .. 639` by `0 .. 479`, which is also the
client size of the game window.

Dialog Tab, arrows, and Esc live in `kronctrl` `FUN_1000519b` and only
run when a key arrives as `WM_KEYDOWN` during interface mode. The
inventory grid and the world picker are not in that focus walk. A pad
that only synthesizes arrow keys cannot operate the inventory. A pad
that moves a cursor and clicks can, because that is how those screens
already work.

---

## 3. Where to inject it

Poll once per frame from `FUN_0045e351`, beside the existing
`FUN_00419c5c` call. That function already reposts latched keys and
drains the function queue before the rest of the frame. A pad poll
there sees one consistent mode dword (`DAT_00628d6c+0x4bc2c`) and
posts into the same queues.

Call `FUN_0041dcd9(keyOrMessage, lParam)`. That is the walk both the
keyboard hook and the window procedure use, so mode masks, modifier
bits, and the Held Down latch stay in force. Do not call
`FUN_0047e86e` and its siblings directly, and do not post
`MM_JOY*` at the library window. The first skips the mode mask. The
second lands in the empty table from section 1.

### Edges, not levels

Trigger `Pressed` (combat, camera, Esc) ignores a message whose
`lParam` has bit `0x40000000` set. That bit is "key was already down".
Send the press once, with bits `0x40000000` and `0x80000000` clear.
Further frames while the button is held must not send another press,
or a combat key fires every frame.

Trigger `Held Down` (the movement keys) latches on the first down and
is reposted by `FUN_0041dbf3` until a message with bit `0x80000000`
set arrives. Send the down once when the stick enters that direction,
and send the release when it leaves. Extra downs while latched are
ignored by the `Released` state of the latch, so a mistaken repeat is
safe. A missing release is not: the character keeps walking after the
stick recenters.

Leaving navigation already clears latches (`FUN_0041da41` from
`FUN_0043aa5d`). A pad poll should do the same when the device
disconnects, or the last direction stays latched.

### The cursor

Keep an x, y in client pixels, start at the center `(320, 240)`, and
clamp to `0 .. 639` by `0 .. 479`. While a stick is deflected, step
that point and call `FUN_0041dcd9(0x200, x | (y << 16))` once a frame.
A face button calls `FUN_0041dcd9(0x201, point)` on the press and
`FUN_0041dcd9(0x202, point)` on the release for the left button, or
`0x204` / `0x205` for the right. The `Interface` map is installed
whenever mode bit `0x08` is set, and it already turns those messages
into widget hits. No separate menu path is required.

The real mouse writes the same point. While the stick is inside the
deadzone, leave the point alone so the mouse still owns it.

### Control-click is not a mouse flag

Command `0x22` is left click with Control. The matcher asks
`GetKeyState(0x11)`. A synthetic `WM_LBUTTONDOWN` does not carry that.
Posting command `0x22` yourself when a shoulder is held is the
straightforward version. Holding a fake Control key down would also
flip every modifiers-`0` binding off for that frame, including
movement.

### Mode

Read `DAT_00628d6c+0x4bc2c` before choosing a stick's job.

| Mode | Stick that would otherwise walk |
|---|---|
| bit `0x08` (interface) | Move the cursor. The `Interface` map's pass flag is 0, so a synthesized arrow key stops there and never reaches `GameDefault` |
| `1` (navigation) | Actor commands `1`, `4`, `5`, and `2` if down is bound |
| `4` or `0x40` (combat) | Either still walks, or becomes the cursor. Combat orders are clicks and the letter keys; both already exist |
| `2` (conversation) | Cursor, plus whatever key is Esc. Esc in this mode is command `0x40` |

Only poll while the game window is foreground. A background pad would
walk the party.

---

## 4. Which API

`XInputGetState` from `XInput9_1_0.dll` is the small one. It is present
on every Windows this GOG build runs on, it sees Xbox pads and the
pads that identify as XInput (most third-party USB pads, and Steam
Input when it is offering an Xbox layout). Poll slots 0–3.
`ERROR_DEVICE_NOT_CONNECTED` is the disconnect signal. Thumbsticks come
back as −32768..32767. A deadzone near 8000 is the same fraction of
the axis as the old 16000-unit test. Use the sign, not the magnitude.
The movement tick has no speed to scale.

`XInput9_1_0` does not see a raw HID pad that is not XInput: a
DualSense, a Switch Pro, many flight sticks, unless Steam, DS4Windows,
or the Windows gamepad mapper is already presenting them as XInput.
`Windows.Gaming.Input` sees those on current Windows and is a WinRT
API, a different kind of dependency for this binary. Raw Input plus
HID is the complete set and the largest amount of code. None of the
three is linked today.

Do not build this on `joySetCapture`. Four buttons, two axes, the
wrong window, an empty script table, and no Xbox pad.

Vibration has no existing call. It can wait.

---

## 5. A default that fits the commands that exist

This is a layout that only uses commands the game already dispatches.
It is not data in the executable.

| Pad | While navigating | While the cursor is the right tool |
|---|---|---|
| Left stick or d-pad up | command `1`, held | nudge the cursor up |
| Left stick or d-pad down | command `2`, held | nudge the cursor down |
| Left stick or d-pad left / right | commands `5` / `4`, held | nudge the cursor |
| Right stick | always the cursor | always the cursor |
| A | left click at the cursor (`0x201` / `0x202`) | same |
| B | right click (`0x204` / `0x205`) | same |
| X | command `0x22` (the control-click), one shot | same |
| Y | the Esc binding for the current mode (`3`, `0x40`, or `0x36`) | same |
| LB / RB | commands `0x71` / `0x74`, previous and next camera. These are `Pressed`, so a hold needs its own repeat timer or it steps once | same |
| Start | command `0x1e` (Pause), one shot | same |
| Back | virtual key `I` (`0x49`), which is Inventory only in combat mode `0x44` | harmless in other modes; the binding's mode mask drops it |

Letter keys for combat (A attack, D defend, S cast, C auto-turn, and
the rest of the table in [`controls.md`](controls.md)) can be extra
buttons or a chord. Synthesize the virtual key, one edge each, and the
mode mask does the filtering. The same physical button must not also
be a mouse click in that mode, or one press both swings and clicks.

Shoulders as camera and as a Shift/Control modifier cannot be the same
button without a mode check. Camera commands are mode Any, so they
fire in combat too.

---

## 6. What not to build

- A writer for the `+0x3e6b` script table. Nothing in the archive reads
  those slots back as movement or clicks.
- New commands in `FUN_004188c6` for "pad north". The actor flags and
  the mouse messages already express a pad.
- Analog movement. `FUN_00403b42` consumes booleans.
- Relying on dialog focus (`FUN_1000519b`) as the menu cursor. It does
  not cover the bag grid or the world.
- Feeding the pad through `SendInput` of `WM_KEYDOWN` as the only
  mechanism. It can work — a posted key does reach the `WH_KEYBOARD`
  hook — but interface mode returns from that hook immediately, and
  the widget path still needs a point. `FUN_0041dcd9` is one call site
  for both.

A later remap screen can own the table in section 5. The binding
records do not have to grow a "controller button" key. The poller is
the map. The records stay keyboard and mouse.
