# Controls

How Return to Krondor reads the keyboard and the mouse, and where a
control remap would have to plug in. Nothing in the shipping game
rewrites a binding after startup. This note does not change the game.

The click that follows a mouse event — walk, talk, door — is
[`interactions.md`](interactions.md). The buttons those clicks land on
are [`ui.md`](ui.md). Camera stepping from `[` and `]` is
[`scene-runtime.md`](scene-runtime.md).

Function names are the stable citations. `RtK.c` line numbers move every
time the decompile is regenerated;
`python tools/show_func.py out/decompiled/RtK.c FUN_0041be90` re-finds
one. There is no DirectInput. Gameplay input is a Win32 keyboard hook
plus window messages, both looked up in the same binding maps.

---

## 1. Two separate systems

A key or a mouse message becomes one of two things.

**A binding on a named map.** `FUN_00417cd0` builds `GameDefault` and
`Interface`. The debug console builds `Console`. Each map is a hash of
0x28-byte records. A match posts a small integer command onto one of
four queues. The frame loop drains those queues.

**A `kronctrl` widget.** Dialogs, buttons, and the inventory live here.
`WinCtrl_Keyboard`, `WinCtrl_Mouse`, and `WinCtrl_Browse` deliver
messages to the control under the cursor or the control that has focus.
Those messages are not the binding commands. A remap of "walk forward"
does not move a dialog's Tab or Esc.

The two meet at the window. `FUN_00434b05` is the game window procedure
(`CGameWindow`). `FUN_00435563` is a second procedure with the same
mouse translation and a shorter keyboard path.

---

## 2. The binding record

`FUN_0041be90(map, key, command, mode, modifiers, trigger, destination, data)`
allocates one record and hangs it on the hash chain for `key`.

| Offset | Argument | Meaning |
|---|---|---|
| `+0` | assigned | Serial id from the map's counter at `map+0x3c` |
| `+4` | key | Hash key. A virtual-key code, or a window message (`WM_MOUSEMOVE` is `0x200`) |
| `+8` | command | The integer the dispatcher switches on |
| `+0xc` | mode | Bit mask. Bit `0x20` matches every mode. Otherwise the bit must overlap `DAT_00628d6c+0x4bc2c` |
| `+0x10` | modifiers | Required modifier state. See below |
| `+0x14` | trigger | When the record fires |
| `+0x18` | runtime | `1` while a Held Down binding is latched |
| `+0x1c` | runtime | Pointer to the latched event packet |
| `+0x20` | destination | Which of the four queues receives the packet |
| `+0x24` | data | What is copied into the packet's third dword |

The hash bucket is `(key >> 4) % (map+0x28)`. A new map starts with 17
buckets (`FUN_0041a8dd` writes `0x11` at `+0x28`). Every record for one
key shares one chain. Changing a key means unlinking the record and
linking it under the new bucket. `FUN_0041be90` only inserts.

Several records may share a key. `FUN_0041dd51` walks the whole chain
and posts every record whose mode and modifiers match. It does not stop
at the first hit. The modifier test makes the usual pairs exclusive, so
a plain key and the same key with Control do not both fire.

### Modifiers

`FUN_0041dd51` samples the keys with `GetKeyState`, not
`GetAsyncKeyState`. A set bit means that key must be down. A clear bit
means it must be up.

| Bit | Key | `GetKeyState` |
|---|---|---|
| `1` | Control | `0x11` |
| `2` | Shift | `0x10` |
| `4` | Alt | `0x12` (`VK_MENU`) |

There is no "don't care" for a modifier. A binding stored with
modifiers `0` will not fire while Shift, Control, or Alt is held.

### Trigger

The keyboard hook passes the virtual key as the lookup key and the
hook's `lParam` as the second argument. Bit `0x40000000` of that
`lParam` is the previous key state (auto-repeat). Bit `0x80000000` is
the transition (1 = being released). Mouse messages pass the window
`lParam` instead, which is the point, so those bits are clear for any
on-screen y.

| Value | Name in the debug table | What the matcher does |
|---|---|---|
| `0` | `Up` | Posts. No binding uses this |
| `1` | `Pressed` | Posts on a key-down that is not an auto-repeat |
| `2` | `Held Down` | On key-down, latches the packet and changes the record's trigger to `3`. `FUN_0041dbf3` copies that packet onto the queue every frame |
| `3` | `Released` | The latch's key-up. Drops the packet, puts the trigger back to `2`, and posts once |
| `4` | `Dont Care` | Posts on every matching message. Mouse bindings use this. The switch has no `case 4`, so it falls through and posts |

Leaving navigation mode (`FUN_0043aa5d`, old mode was `1`) calls
`FUN_0041da41`, which clears every latch, and `FUN_00419c0c`, which
empties the actor queue. A remap that moves a key while it is held
should go through that clear, or the latch still points at the old
packet.

### Mode bits

`FUN_0041d3e6` names the bits. The live mode dword is
`DAT_00628d6c+0x4bc2c`. `FUN_0043aa5d` is the writer.

| Bit | Name |
|---|---|
| `0x01` | Navigation State. Adventure movement. Compared as the value `1` in several places |
| `0x02` | Conversation State |
| `0x04` | Combat State. Combat also runs with the value `0x40`, which this table does not name |
| `0x08` | Interface State. Installing this bit pushes the `Interface` map |
| `0x10` | Paused State |
| `0x20` | Any State. The binding matches no matter what the mode dword is |

A combat binding is stored as `0x44`, so it matches mode `4` and mode
`0x40`.

### Destination

Four queues, created by `FUN_0041c31a`. `FUN_0041da09(n)` returns queue
`n`. The debug strings in `FUN_00419c78` are the original enum names.

| Value | Name | Who drains it |
|---|---|---|
| `0` | `eEventDest_MainPartyLeader` | Nobody. No binding uses it |
| `1` | `eEventDest_InterfaceRequest` | Nobody. No binding uses it |
| `2` | `eEventDest_Actor` | `FUN_00419aaf`, from the movement tick `FUN_00403b42` |
| `3` | `eEventDest_FnNotification` | `FUN_004188c6`, from `FUN_00419c5c` at the start of the frame `FUN_0045e351` |

`FUN_00419c5c` calls `FUN_0041dbf3` first, so a held key is posted again
before the function queue is drained. The actor queue is drained later,
inside the movement tick, and only while that tick decides the actor is
the one being driven.

### Data

| Value | Name | Packet's third dword |
|---|---|---|
| `0` | `No Data` | `0` |
| `1` | `Mouse XY` | The message `lParam`. Low 16 bits are x, high 16 are y |
| `2` | unnamed | Also copies `lParam`. The console's character binding uses this. The name table only filled 0 and 1 |

The packet itself is 12 bytes: destination, command, data.
`FUN_00423cf3` enqueues it.

---

## 3. From the hardware to a lookup

### Keyboard

`FUN_0041ad00` installs a thread-local `WH_KEYBOARD` hook
(`SetWindowsHookExA(2, FUN_0041e0fc, ...)`). `FUN_0041857c` removes it
with `FUN_0041ad39`.

`FUN_0041e0fc`:

1. If the mode dword has bit `0x08`, the hook returns immediately and
   the key is left for the window procedure. The binding maps are not
   consulted. Interface mode therefore does not see keyboard bindings
   at all, including the Pause record on the `Interface` map.
2. Otherwise it walks the active map list (`DAT_00625e14`) and calls
   `FUN_0041dd51(map, virtualKey, lParam)`.
3. A return of `1` means a record fired. The hook returns `1`, which
   keeps the key from reaching the window. Gameplay keys do not become
   `WM_KEYDOWN`.
4. A return of `2` stops the walk. That is a map whose pass flag
   (`map+0x40`) is `0` and which did not match.
5. A return of `0` tries the next map.

After the walk, if some active map contains a record keyed `0x401` and
Control and Alt are up, a printable result of `MapVirtualKeyA(vk, 2)`
is allowed through (the hook returns 0). That is how the console
receives characters. `FUN_00574ee0` is the printable test. Space is
allowed through on its own.

### Mouse

Mouse messages never enter the hook. Both window procedures hand them
to `FUN_0041dcd9(message, lParam)`, which walks the same map list.

`FUN_00434b05` and `FUN_00435563` rewrite a double-click into the
matching single click before the lookup:

| Incoming | Looked up as |
|---|---|
| `WM_LBUTTONDBLCLK` `0x203` | `WM_LBUTTONDOWN` `0x201` |
| `WM_RBUTTONDBLCLK` `0x206` | `WM_RBUTTONDOWN` `0x204` |
| `WM_MBUTTONDBLCLK` `0x209` | `WM_MBUTTONDOWN` `0x207` |

`GameDefault` does register `0x203`. The window procedures never pass
`0x203` through, so that record does not run. Middle-button messages
are forwarded and nothing is bound to `0x207` or `0x208`, so a middle
click does not become a command. `WM_MOUSEWHEEL` (`0x20a`) is not in
either procedure. The `OnMouseWheel` in the decompile is MFC
`CScrollView`, not the game window.

While a movie player is installed (`window+0xa0`), `FUN_00434b05`
swallows mouse input instead of translating it. Escape as `WM_CHAR`
(`0x1b`) asks the player to close.

### Active maps

`FUN_0041ad64` pushes a map onto the head of `DAT_00625e14`.
`FUN_0041dcd9` and the hook both start at the head, so the most recently
pushed map is tested first.

| Map | Built by | Pass flag `+0x40` | When it is on the list |
|---|---|---|---|
| `GameDefault` | `FUN_00417cd0`, stored at `DAT_00628d6c+0x340` | `1` (keep searching) | From startup, via `FUN_0041ad64` |
| `Interface` | `FUN_00417cd0`, stored at `+0x344` | `0` (stop the search on a miss) | While mode bit `0x08` is set. `FUN_0043aa5d` pushes it on the way in and `FUN_0041adb2` removes it on the way out |
| `Console` | `FUN_00452abf` (the console constructor), on the console object at `+0x58` | `1` | While the console is open. Alt+C toggles it through command `0x26` → `FUN_00453357` |

Because `Interface` is first and its pass flag is 0, a mouse message
that does not hit an interface binding does not fall through to
`GameDefault`. Keyboard does not use this path during interface mode;
the hook has already stepped aside, and the window procedure sends the
key to `WinCtrl` instead.

---

## 4. `GameDefault`

Registered in `FUN_00417cd0`. Command names that exist in
`FUN_0041d296` are Move Forward (`1`), Move Backward (`2`), Turn CW
(`4`), and Turn CCW (`5`). Every other command keeps the filler name
`UNDEFINED` plus its number. The real combat names below come from the
log strings inside the handlers, not from that table.

`FUN_00419c78` prints joke strings (`kill the wabbit`, `program better
than this`) for commands 1–9. Nothing calls it. Those strings are not
the live names.

### Movement (destination Actor, navigation mode, Held Down)

`FUN_00419aaf` folds the actor queue into six flags. `FUN_00403b42`
declares a 4-int array and then clears six ints, so the fifth and sixth
land on the following stack slots (`local_44`, `local_40`).

| Key | Mods | Command | Flag | Effect in `FUN_00403b42` |
|---|---|---|---|---|
| Up `0x26` | none | `1` Move Forward | `[0]` | Step along the actor heading |
| Up | Control | `0x41` | `[1]` | Same step. In the navigation branch (`local_68 == 2`) this writes party-group `+0x8c` to `1`. Plain Up writes `0`. That is the same field a control-click writes; the reader is still open in [`interactions.md`](interactions.md) |
| Down | | | | Not bound. Command `2` Move Backward is implemented (`[2]` steps backward) and has no key |
| Right `0x27` | none, and again with Control | `4` Turn CW | `[3]` | Decrease heading |
| Left `0x25` | none, and again with Control | `5` Turn CCW | `[4]` | Increase heading |
| Esc `0x1b` | none | `3` | `[5]` | Clears the move and turn slots on the actor and calls `FUN_0045ae65` |

The Control copies of Left and Right post the same command as the plain
keys. They exist so the turn still matches while Control is held,
because a modifiers-`0` record refuses to fire when Control is down.
There is no Down Arrow binding, and no strafe.

### World mouse (destination Function, mode Any, trigger Dont Care)

| Message | Mods | Command | Handler |
|---|---|---|---|
| `WM_MOUSEMOVE` `0x200` | none, and again with Control | `0x20` | `FUN_00418756`. Stores x, y at `DAT_00628d6c+0x264` and `+0x268` |
| `WM_LBUTTONDOWN` `0x201` | none | `0x21` | `FUN_00418778` → picker `+0x34`. The adventure click |
| `WM_LBUTTONDOWN` | Control | `0x22` | `FUN_00418807` → picker `+0x38` |
| `WM_LBUTTONDBLCLK` `0x203` | none | `0x22` | Registered, never reached. See section 3 |
| `WM_RBUTTONDOWN` `0x204` | none | `0x23` | `FUN_0041882e` → picker `+0x3c` |
| `WM_LBUTTONUP` `0x202` | none | `0x24` | `FUN_004187e0`. Mode is combat `0x44`, not Any. The adventure picker slot is an empty stub |

What the picker does with `0x21`, `0x22`, and `0x23` is the rest of
[`interactions.md`](interactions.md).

### Combat (destination Function, mode `0x44`, trigger Pressed)

Each handler is gated by its own "is this legal right now" test before
it changes the fight. The log string is what the handler prints when it
runs.

| Key | Mods | Command | Handler | Log string |
|---|---|---|---|---|
| D `0x44` | none | `0x27` | `FUN_0047ea05(picker, 0)` | `Execute - Defend Parry :` |
| D | Shift | `0x28` | `FUN_0047ea05(picker, 1)` | same function, argument `1` |
| G `0x47` | none | `0x29` | `FUN_0047eaac(picker, 0)` | `Execute - Defend Guard :` |
| G | Shift | `0x2a` | `FUN_0047eaac(picker, 1)` | same function, argument `1` |
| Enter `0x0d` | none | `0x2c` | `FUN_0047e7c1` | `Execute - Pass :` |
| A `0x41` | none | `0x2d` | `FUN_0047e86e` | `Execute - Attack :` |
| A | Shift | `0x3b` | `FUN_0047efae` | `Execute - AttackMenu :` |
| W `0x57` | none | `0x2f` | `FUN_0047eb91` | `Execute - Wait :` |
| I `0x49` | none | `0x30` | `FUN_0047e0eb` | `Execute - Inventory :` |
| S `0x53` | none | `0x31` | `FUN_0047e55f` | `Execute - Cast Spell :` |
| S | Shift | `0x3d` | `FUN_0047e73d` | `Execute - Drop Weapon And Select` |
| E `0x45` | none | `0x3a` | `FUN_0047e80b` | `Execute - Attributes :` |
| C `0x43` | none | `0x34` | `FUN_0047ee6f` | `Execute - AutoTurn :` |
| M `0x4d` | none | `0x35` | `FUN_0047ef0f` | `Execute - ActionMenu :` |
| Esc `0x1b` | none | `0x36` | `FUN_0047f05f` | `Execute - EscapeKey :` |
| F `0x46` | none | `0x37` | `FUN_00489138` | No log string. Runs only when the combat UI state at `picker+0x100` is `0xb` or `0xc`. ORs bit `0x10` into the current fighter's user-data dword |
| P `0x50` | none | `0x39` | `FUN_0047ec3b` | `Execute - Search Ground :` |
| Q `0x51` | Control | `0x38` | `FUN_00478e67` | `Cheat : Get Experience During Force End`. Also requires `DAT_006296e4` |

Commands `0x32` (Evaluate, `FUN_0047ee31`) and `0x3c` (Drop Weapon,
`FUN_0047e6a8`) have handlers and no key. `0x2b` and `0x33` are empty
cases in `FUN_004188c6`.

C in combat is AutoTurn. Cast Spell is S. The adventure C bindings
below are different records, distinguished by their modifiers, so they
do not steal the combat C.

### Conversation

| Key | Mode | Command | Handler |
|---|---|---|---|
| Esc | `0x02` Conversation | `0x40` | `FUN_004d0858` on the conversation object at `+0x370`. That function's log string is `OnCancel` |

### Camera, pause, bookmarks

These are mode Any, trigger Pressed, destination Function.

| Key | Command | What `FUN_004188c6` does |
|---|---|---|
| `[` `0xdb` | `0x71` | `FUN_0041a03b(1, 0)`, previous view. See [`scene-runtime.md`](scene-runtime.md) |
| `]` `0xdd` | `0x74` | `FUN_0041a03b(1, 1)`, next view |
| F2 `0x71` | `0x1c` | Quick save via `FUN_0051fc2f`, and only when `DAT_006296e4` is set and the mode value is exactly `1`. Otherwise `MessageBeep` |
| F3 `0x72` | `0x1d` | Quick load via `FUN_00523337`, same gate |
| Pause `0x13` | `0x1e` | `FUN_0043ab92` when `DAT_00628d6c+0x4bc34` is `0` |
| F5 `0x74` | `0x42` | Writes `bookmark.rtk` through `FUN_0051fc2f` when mode is `1`, the pause flag at `+0x4bc10` is clear, and `FUN_00547524` returns 0 |
| F6 `0x75` | `0x43` | Reads that file through `FUN_00523337`, same gate |

Commands `0x72`, `0x73`, `0x75`, and `0x76` also call `FUN_0041a03b`
with different step sizes. Nothing in `GameDefault` binds them.

`DAT_006296e4` gates the quick save, the quick load, the Ctrl+Q combat
cheat, and the verbose error dialogs. `RtK.c` only reads it. No store
turned up in the decompile, so what sets the flag is still open.

### Debug

| Key | Mods | Command | Effect |
|---|---|---|---|
| C | Control+Shift | `0x25` | `FUN_0041a2d0` then `FUN_004fb330`. Not named beyond that |
| C | Alt | `0x26` | `FUN_00453357`, toggles the console and its map |

---

## 5. The `Interface` map

Pushed only while mode bit `0x08` is set. Every record is mode
`0x08`, trigger Dont Care, destination Function, except Pause which is
mode Any and trigger Pressed. Pause on this map is unreachable from the
keyboard: while the map is installed the hook is not running, and the
window procedure does not call `FUN_0041dcd9` for key messages.

Mouse records call back into the widget layer. `FUN_004188c6` cases
`0x7a`–`0x89` call `FUN_004377d4`, which calls `FUN_004b9779`. Case
`0x8a` calls `FUN_004377ac` → `FUN_004b9657`.

`FUN_004b9779(x, y, down, leftButton, mkStyle)`:

| `down`, `leftButton` | Widget message |
|---|---|
| `1, 1` | `RtK_TG_BUTTONDOWN(WM_LBUTTONDOWN, mk \| MK_LBUTTON, point)` then `WinCtrl_Mouse(..., 1)` which is control message `0x8004` |
| `0, 1` | `RtK_TG_BUTTONUP(WM_LBUTTONUP, ...)` then `WinCtrl_Mouse(..., 2)` which is `0x8005` |
| `1, 0` | right button down, `MK_RBUTTON` |
| `0, 0` | right button up |

`mkStyle` on the binding is the Windows `MK_` value the handler should
attach: Control becomes `MK_CONTROL` (`8`), Shift becomes `MK_SHIFT`
(`4`). Alt is passed as `4` in the command's last argument and
`FUN_004b9779` only special-cases `1` and `2`, so an Alt-modified
interface click arrives with no `MK_` bit. Windows mouse messages have
no `MK_ALT`.

Both functions refuse a point outside `0 .. 639` by `0 .. 479`. That
gate is the 640×480 frame from
[`display-resolution.md`](display-resolution.md).

`FUN_004b9657` is the move. It hit-tests sprites, calls
`WinCtrl_Browse` for the sprite id under the cursor, and
`WinCtrl_Mouse(..., 4)` which is control message `0x8006`.

The binding list, command to `FUN_004377d4` arguments:

| Message | Mods | Command | `down` | left | style |
|---|---|---|---|---|---|
| move `0x200` | none | `0x8a` | | | move, not a button |
| left up `0x202` | none | `0x7a` | 0 | 1 | 0 |
| left down `0x201` | none | `0x7b` | 1 | 1 | 0 |
| left up | Shift | `0x80` | 0 | 1 | 2 → `MK_SHIFT` |
| left down | Shift | `0x81` | 1 | 1 | 2 |
| left up | Control | `0x7c` | 0 | 1 | 1 → `MK_CONTROL` |
| left down | Control | `0x7d` | 1 | 1 | 1 |
| left up | Alt | `0x7e` | 0 | 1 | 4, dropped by the handler |
| left down | Alt | `0x7f` | 1 | 1 | 4, dropped |
| right down `0x204` | none | `0x83` | 1 | 0 | 0 |
| right up `0x205` | none | `0x82` | 0 | 0 | 0 |
| right up | Shift | `0x88` | 0 | 0 | 2 |
| right down | Shift | `0x89` | 1 | 0 | 2 |
| right up | Control | `0x84` | 0 | 0 | 1 |
| right down | Control | `0x85` | 1 | 0 | 1 |
| right up | Alt | `0x86` | 0 | 0 | 4, dropped |
| right down | Alt | `0x87` | 1 | 0 | 4, dropped |
| Pause `0x13` | none | `0x1e` | | | same pause command as `GameDefault`, and not reached from the hook |

---

## 6. The console map

Lives on the console object. Alt+C pushes it. Keys:

| Key | Mods | Command | Handler |
|---|---|---|---|
| Enter `0x0d` | none | `0x8b` | `FUN_00453610`, runs the line |
| F3 `0x72` | none | `0x8c` | `FUN_004537bd` |
| Up | Alt | `0x8d` | `FUN_0045342e` |
| Down `0x28` | Alt | `0x8e` | `FUN_00453479` |
| Backspace `0x08` | none | `0x8f` | `FUN_004537da` |
| synthetic `0x401` | none, and again with Shift | `0x90` | `FUN_00453866` with the character |

`0x401` is not a Windows message the system posts. When the mode is not
interface, `WM_CHAR` in `FUN_00434b05` calls `FUN_0041dcd9(0x401, character)`.
The hook's printable-key exception exists so those characters are not
eaten before `WM_CHAR` is generated. Data kind is `2`.

F3 on this map and F3 on `GameDefault` are different commands. The
console map is tested first while it is open, and its pass flag is 1,
so an F3 that matches here does not also quick-load.

---

## 7. Widget keyboard, the other path

When mode bit `0x08` is set, `WM_KEYDOWN` (`0x100`), `WM_KEYUP`
(`0x101`), `WM_SYSKEYDOWN` (`0x104`), and `WM_SYSKEYUP` (`0x105`) go to
`FUN_00437808`. That calls `DAT_0066e06c`, which `FUN_004366c0` sets to
`FUN_004b98cc` for every chapter startup it handles.

`FUN_004b98cc` calls `RtK_TG_KEYBOARD` and then `WinCtrl_Keyboard`.
`WinCtrl_Keyboard(root, isDown, vk)` turns a down into control message
`0x800c` and an up into `0x800d`, and delivers it to the focused
control (`root+0x68`) or to the optional override at `root+0x94`.

The dialog procedure `FUN_1000519b` (`kronctrl`, message `0x800c`)
hardcodes the navigation keys:

| Virtual key | Effect |
|---|---|
| Tab `0x09` | Next or previous tab stop, from Shift via `GetKeyState(0x10)`. `Win_GetDlgTabItem` |
| Left `0x25`, Up `0x26` | Previous control in the group. `Win_GetDlgGroupItem` |
| Right `0x27`, Down `0x28` | Next in the group |
| Esc `0x1b` | Hide the dialog (`FUN_10005161`) |
| anything else | `WinCtrl_findvirtkey`. A control whose procedure returns 0 for message `0x8010` is the match. The button procedure `FUN_100010d0` matches when the key equals the dword at control `+0x40` |

`Win_CreateControl` stores its seventh argument at `+0x40`
(`piVar1[0x10] = param_7`). The call sites that build the shipping
screens pass `0`. So the accelerator slot exists, and the screens do
not use it. Tab, the arrows, and Esc are compiled into `FUN_1000519b`,
not stored in a binding.

`RtK_TG_KEYBOARD` in `Rtlib32` also handles `WM_CHAR` when a text field
is active, and it special-cases virtual key `0x79` (F10) on
`WM_SYSKEYDOWN`. That is the library's own key path, underneath the
control messages.

---

## 8. Names for a remap screen

`FUN_0041c3b7` fills a 255-entry table at `DAT_0061fa18`, 20 bytes each,
indexed by virtual-key code. Unnamed slots are `UNDEFINED` plus the
decimal code. The named slots cover the letters, digits, function keys,
arrows, keypad, and the punctuation the game cares about.

Two slots do not match the key the matcher actually tests:

- Shift is slot `0x10` and Control is slot `0x11`, which are `VK_SHIFT`
  and `VK_CONTROL`.
- The string `Alt` is stored at slot `0x7f`. The modifier test uses
  `GetKeyState(0x12)`. Looking up `VK_MENU` in this table returns the
  filler, not `Alt`. The annotated dump prints the word `ALT` from the
  modifier bit, not from this table.

`FUN_0041adf0(map, opcode)` is that dump. Opcode `0x20002` writes lines
tagged `KEY`, `COMMAND`, `GAME STATE`, `MODIFIER KEY FLAGS`,
`TRIGGER TYPE`, `EVENT DESTINATION`, and `EVENT DATA`, each followed by
the table name and the integer. Opcode `0x20001` writes a compact form
of the same records. Nothing in `RtK.exe` calls `FUN_0041adf0`.

The command, mode, trigger, destination, and data tables are
`FUN_0041d296`, `FUN_0041d3e6`, `FUN_0041d584`, `FUN_0041d6fb`, and
`FUN_0041d84b`. Combat commands are not in the command table. A remap
screen that wants "Attack" has to supply that string itself; the
executable only has it inside `FUN_0047e86e`'s log text.

---

## 9. What a remap would have to change

The defaults are immediate calls in `FUN_00417cd0` and in the console
constructor. They are not read from the ini. The profile keys that do
exist (`Options` / `CombatStats`, `Options` / `TrapGame`, `Cinemat` /
`Stretch`, `Audio` / `BGThread`, and the `Directories` entries) are not
bindings.

`FUN_0041b743(map, path)` is a loader. It clears the map, reads a tag,
and if the tag is `0x20001` it pushes one record per row by calling
`FUN_0041be90` with the seven fields in the order key, command, mode,
modifiers, trigger, destination, data. `FUN_0041ba50` copies one
existing record into a map. No call site of either function turned up
in `RtK.c`. The machinery to replace a map from a stream is present and
unused.

A remap that stays inside this design:

1. Keep the command, mode, trigger, destination, and data. Change `+4`,
   the key, and rehash. The bucket is `(key >> 4) % bucketCount`.
2. Leave `+0x10` alone unless the user is also editing modifiers. A
   modifiers value of `0` means the new key will not fire while Shift,
   Control, or Alt is held.
3. Treat mouse messages (`0x200` and up) as a different column from
   virtual keys. They share the hash. Rebinding "Attack" must not
   overwrite the left-click record.
4. Preserve the duplicate records that exist so a key still works with
   Control held (Left, Right, mouse move). Collapsing them to one row
   changes when the command fires.
5. Edit `GameDefault` for gameplay and `Interface` for widget clicks.
   They are different commands. The console map is a third list.
6. Do not expect a keyboard change to affect dialog Tab, arrows, or
   Esc. Those are `FUN_1000519b`. A per-button hotkey would be the
   `+0x40` slot `WinCtrl_findvirtkey` already searches, which the
   shipping screens leave at `0`.
7. There is no save. A remap needs its own store. `FUN_0041b743` can
   reload a map if that store is written in the `0x20001` shape, and
   today nothing does.
8. Clear latches (`FUN_0041da41`) before rehashing a Held Down binding,
   or the packet at `+0x1c` still belongs to the old key.

The movement keys are Held Down and destination Actor. Combat, camera,
and the function keys are Pressed and destination Function. A UI that
only rewrites `+4` on the existing records keeps that split.

---

## 10. Joystick

`Rtlib32` can capture two legacy multimedia joysticks
(`joySetCapture` in `FUN_100113c0`, `7THLEVEL.INI` key `MaxJoySticks`).
Move messages `0x3a0` and `0x3a1`, and button messages `0x3b5`–`0x3b8`,
are handled on the library's own window and turned into a script id.
The table those ids come from is cleared at startup, and nothing in
this game writes it. A pad that Windows exposes through that old API
therefore does nothing here.

That path is not a USB controller. What it would take to add one is
[`controller.md`](controller.md). A keyboard remap does not go through
it either.

---

## 11. Open

- **What writes `DAT_006296e4`.** It gates F2, F3, Ctrl+Q, and the
  error dialogs. No store showed up in `RtK.c`.
- **Command `0x25` (Ctrl+Shift+C).** It calls `FUN_0041a2d0` and
  `FUN_004fb330`. The two functions were not walked.
- **The F key in combat.** `FUN_00489138` sets bit `0x10` on the
  fighter's user data during UI states `0xb` and `0xc`. The bit was
  not followed to a named action.
- **Party-group `+0x8c`.** Control+Up writes `1` and Up writes `0`, in
  the same place a control-click writes `1`. The reader is still the
  open item in [`interactions.md`](interactions.md).
- **`FUN_0041b743` and `FUN_0041adf0`.** The load and dump entry points
  have no callers. They may be reachable from a function pointer the
  decompiler did not resolve; no reference to the addresses turned up
  in the C dump.
- **Alt as a display name.** Slot `0x7f` says `Alt`. The live modifier
  is virtual key `0x12`.
