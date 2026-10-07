# The interface

How the buttons, sheets, and conversation bubbles are built, and where
they sit on the 640 × 480 frame. The frame itself — backdrop, characters,
then this interface, then the present — is
[`display-resolution.md`](display-resolution.md). Which palette a screen
loads is [`palette-map.md`](palette-map.md). What an inventory click does
to an item is [`inventory.md`](inventory.md). What a world click does
before a screen opens is [`interactions.md`](interactions.md). The title
shelf and the page-turn that opens a book or the options screens are
section 9.

Nothing here changes the game. Function names are the stable citations;
`python tools/show_func.py out/decompiled/<file>.c <name>` prints a body.
Boxes below are pixels of the frame, origin at the top left.

---

## 1. One tree of pictures

Every screen is a sprite. `kronctrl.dll` is the control library on top of
Rtlib32: a dialog is a control, a button is a control, and each one that
has art names a SPRITE resource. `Win_CreateDlg` and `Win_CreateControl`
both end in `WinCtrl_create`, which refuses the id unless
`RtGetResType` says `0x14` (SPRITE), then `RtLoad`s it.

The loaded sprite is one node in a tree. A dialog owns the controls
created with it as parent. Destroying a dialog destroys that subtree
(`WinCtrl_destroy`). Showing, enabling, and moving a parent do the same
to the children.

`FUN_004366c0` is the launcher. It resolves the five party names (James,
Jazhara, William, Kendaric, Solon), stores the screen id at `DAT_00628d5c`,
and calls the opener for that id. The id list is section 7. While a screen
is up, `DAT_00628d6c+0x354` is set; `FUN_004376a8(0)` is what pauses the
world underneath, and `FUN_004376a8(1)` is what lets it run again.

A dialog procedure is an ordinary function passed to `Win_CreateDlg`.
The messages it actually branches on:

| Message | When |
|---|---|
| `0x2001` | The dialog has been created. This is where it builds its buttons |
| `0x100` | A child was clicked. The control id is the next argument |
| `0x101` | A child's picture changed (hot, pressed, checked) |
| `0x1001` | The dialog was shown |
| `0x1002` | The dialog is going away |
| `0x2002` with key `0x1b` | Escape. The exit confirm, the identify menu, and the attack/speak menu all treat this as cancel |

Draw order is a level integer. `Win_CreateDlg`'s level argument becomes
`RtLevel` on the sprite, and the sprite list is kept sorted by it.
The sheets use 10000, the sidebar 12000, the status bar 13000, so the
bar paints over the bottom of a sheet. The menu button's sprite is then
forced to 12999 so it stays above the sidebar.

---

## 2. Where a picture lands

Sprite coordinates are centered on the frame. `RtSetScreenRes(640, 480)`
stores the visible rectangle as `(-(639/2), -(479/2))` through
`(320, 240)`, which is `(-319, -239)` through `(321, 241)`. Pixel (0, 0)
of the frame is sprite coordinate (-319, -239). The same center is what
`FUN_00545c1f` passes to `RtSetViewPortOrg` (`0x140`, `0xf0`).

A bitmap is not given a top-left. `FUN_10033f32` puts its center on the
sprite's position, then adds the hotspot:

```
left = sprite_x - (width  - 1) / 2 + hot_x
top  = sprite_y - (height - 1) / 2 + hot_y
```

The division truncates toward zero. A sprite just loaded is at (0, 0).
The hotspot is the bitmap header at offsets 12 and 16
([`bitmap-codec.md`](bitmap-codec.md)). A CEL replaces those two fields
with its own third and fourth dwords (`FUN_10013ea7`); the first dword
is the bitmap id.

Two checks fix the formula to the frame:

- `sMap` is 640 × 480 with hotspot (0, 0). Its box is exactly (0, 0,
  640, 480).
- `sMain_MenuBtn` is 117 × 21 with a hotspot that lands it at (7, 456),
  on the status bar, which is where the menu button is.

`Win_SetPos` moves the sprite, and the bitmap moves with it. The last
argument is absolute when it is 0 and a delta when it is not
(`WinCtrl_setpos` → `SpriteSetPosition`). A delta is also applied to
every child, which is how the status bar and its menu slide together.

Most shipped sprite headers are empty aside from the reference list.
Across all 1,509 SPRITE resources the count at `+0x08` equals the count
at `+0x0c`, and the references start at `+0x26`. Bytes `+0x00`, `+0x04`,
`+0x10`, `+0x14`, `+0x18`, `+0x20`, `+0x22`, `+0x24`, and `+0x25` are
zero in every one of them. The loader (`FUN_10014408`) reads the count,
the level at `+0x1c` (zero on 1,505 sprites; 10000, 9999, or 30000 on
the other four), and the pick-mode byte at `+0x21` (1 on 249 sprites,
0 on the rest). The scrollable byte at `+0x25` is never set; scroll bars
are their own controls.

A sprite's references are bitmaps, cels, text, and queues. Several
bitmaps in one sprite are the cels of one control. `SpriteShow` picks
which cel is visible. A QUEUE is a 2D animation over that list;
`SpriteAnimate` advances it on the interface refresh
([`animations.md`](animations.md)). The spell-book flames and the party
book are queues. A button's up/down/disabled pictures are cels, not a
playing queue.

---

## 3. Buttons

`Win_CreateControl(rt, parent, sprite, type, flags, id, ...)` builds a
child. Types 1 through 5 share the procedure `FUN_100010d0`. Type 0 is
a static picture (`FUN_1000a470`): it does not click, and the parent
chooses its cel. Type 8 is rewritten to type 1 with flag `0x20`.

The procedure itself only special-cases two of those types. Type 5 is a
radio: checking one clears the others in the dialog group, which is how
the five sidebar tabs work. Type 3 toggles a checked bit. Types 1, 2,
and 4 are push buttons. Type 4 is what the document viewer uses for its
page controls. Type 2 has the procedure and no call site in `RtK.exe`.

Flags stored on the control that change behavior:

| Flag | Effect |
|---|---|
| `0x400` | Create it hidden. The default is visible |
| `0x800` | Create it disabled. The default is enabled |
| `0x1000` | `RtCopy` the sprite instead of using the shared one |
| `0x20` | Do not pick a cel. Tell the parent the state, and let the parent call `SpriteShow` |
| `0x40` | Also notify the parent on press (`0x102`) and release (`0x104`), not only on the click |
| bit 0 of the dialog flags | Modal. The parent is disabled until the dialog is destroyed |

When the control draws itself, the cel comes from how many cels the
sprite has and from three states: enabled, hot, checked. The slots are
up, hot, disabled, then the same three again for the checked form.
A sprite with fewer cels collapses onto the slots it does have
(`FUN_10001640`), so a two-cel button is up and down, and a three-cel
button adds disabled. The highlight cel is often a pixel or two larger
than the up cel; the exit-confirm labels are 207 × 17 up and 209 × 19
highlighted.

`Win_CreateRect` is an invisible hit rectangle. `Win_CreateScrollBar`
is the scrollbar, used by the save list, the inventory, and the shop.
`GridCreate(rt, columns, rows)` is a cell table with no art of its own.
`FUN_0053e195` makes one 7 × 64 grid per character, which is the bag.
That is why an inventory slot index is `column + row * 64` in
[`inventory.md`](inventory.md). Dragging an item off a cell is
`Win_Carry` / `Win_CancelCarry`; what the drop does to the bag is the
inventory note, not this one.

`Win_MsgBox` builds a box from `sMsgBackground` (a 32 × 32 tile),
`sMsgBorders`, and the `sMsgButton*` sprites. It is the engine's
yes/no/ok box, separate from the conversation bubbles.

---

## 4. The frame that stays up

Two dialogs are created for the whole session, not per screen.

`sMenu_ClickArea` (4536) is a full-frame dialog at level 1
(`FUN_00545c1f`). It is the click catcher behind everything else.

`sMain_StatusBar` (4575) is its child, at level 13000 (`FUN_00545d23`,
procedure `FUN_00545eb8`). The bar picture is 640 × 81 and its hotspot
puts the top edge at y = 433, so at rest only the bottom 47 pixels of
the frame show it. The menu button is a child, so it lives in that
strip.

Opening the sidebar (`FUN_00545dd7`) calls `FUN_00546303(1)`, which
moves the status bar and every child by (0, −32). The bar's top goes
to y = 401 and almost the whole 81 pixels are on screen (the last two
are clipped at y = 480). Closing the sidebar calls `FUN_00546303(0)`
and adds (0, +32) back.

| Sprite | Id | Box at rest | Role |
|---|---:|---|---|
| `sMain_StatusBar` | 4575 | (0, 433) 640 × 81 | the bottom strip. Slides up 32 pixels while the sidebar is open |
| `sMain_MenuBtn` | 4538 | (7, 456) 117 × 21 | opens `sMain_MenuBack`. Control id `0x65` |
| `sMain_MenuBack` | 4543 | (23, 222) 227 × 226 | the popup. Hidden until the menu button is down |
| `sMain_Book` | 4545 | (54, 231) 160 × 35 | id `0x68`. Enabled when bit 0 of `DAT_00628d6c+0x4bc2c` is set and the pointer at `+0x4cb40` has a non-zero word just before it. Save-and-quit uses that same test. The click opens the save window in section 9 |
| `sMain_Options` | 4550 | (49, 268) 168 × 33 | id `0x6b`. `FUN_00529740(1)`. Enabled on that same bit 0 |
| `sMain_Journal` | 4555 | (50, 303) 167 × 34 | id `0x6d`. Enabled on bit 0 |
| `sMain_Rest` | 4560 | (49, 337) 166 × 35 | id `0x6c`. Opens the party sheet when `FUN_00547236` is true |
| `sMain_Maps` | 4565 | (52, 374) 161 × 32 | id `0x6e`. `FUN_005473c0`, the travel map. Enabled on bit 0 and when `DAT_00628d6c+0x4bbd4` is set |
| `sMain_Exit` | 4570 | (52, 408) 162 × 40 | id `0x6f`. The confirm below |

Those six menu boxes are the at-rest positions. They ride the same
32-pixel slide as the bar.

The sidebar is not a child of the status bar, so it does not slide.
`sMain_SideBar` (4577) is (582, 0), 58 × 416, level 12000. The five tabs
are type-5 radios on it (`FUN_00546436`):

| Sprite | Id | Box | Control | Opens |
|---|---:|---|---:|---|
| `sMain_AttributesTab` | 4579 | (600, −1) 40 × 79 | `0x97` | `sAttr_Bkgnd`, full frame |
| `sMain_SpellsTab` | 4587 | (601, 83) 39 × 80 | `0x9a` | `sSpellsBkDrop` |
| `sMain_InventoryTab` | 4595 | (602, 168) 38 × 78 | `0x98` | `sInv_BottomCover` |
| `sMain_PartyTab` | 4603 | (600, 249) 40 × 82 | `0x99` | the party sheet, which has no root sprite |
| `sMain_ExitTab` | 4611 | (598, 332) 42 × 83 | `0x9b` | closes the sidebar |

The attributes tab starts one pixel above the frame because its height
is odd and the center calculation truncates. The five tabs run down the
right edge and stop at y = 415, which is the bottom of the 416-pixel
sidebar. The sidebar art is the strip behind them.

Checking a tab hides the other three sheets and shows its own
(`FUN_0054678d`, `FUN_005469be`, `FUN_00546849`, `FUN_00546905`). The
party tab and the rest button stay disabled while `FUN_00547236` is
false. That function returns false when the object at
`DAT_00628d6c+0x348` has zero at `+0x20`, when `+0x4bbd8` is zero, when
the object at `+0x368` has a non-zero `+0x84`, or when the open
interface id is `0xe`.

Exit confirm is `sMain_ExitConfirm` (4620) at (184, 163), 272 × 153
(`FUN_00546e35`):

| Sprite | Box | Id | Does |
|---|---|---:|---|
| `sMain_ExitWSave` | (216, 184) 207 × 17 | `0x9e` | save and quit, only if a save exists |
| `sMain_ExitWoSave` | (215, 230) 207 × 17 | `0x9c` | quit without saving (`FUN_0050c7fa`) |
| `sMain_ExitReturn` | (216, 276) 207 × 17 | `0x9d` | close the confirm and reopen the menu |

---

## 5. The four sheets

Each sheet is a dialog parented to the sidebar, level 10000, and each
one is created on the first click and shown again after that.

**Attributes.** Root `sAttr_Bkgnd` (854), a full-frame picture. The
panel on it is the attribute book: arrows, the point pool, the done
and reset buttons (`sAttr_*`).

**Spells.** Root `sSpellsBkDrop` (1256), the full-frame black. The book
itself is `sSpells` (1258), 597 × 416 at (−1, 0) — one pixel left of the
inventory sheet, because its hotspot is −22 rather than −21. Character
tabs and heads are `sSpells_Tab_*` and `sSpells_Head_*`. The six spell
groups (Flames, Mind, Change, Storms, Divine, Life) are rows of cel
sprites, `sSpells_Flames01` through `10` and the same for the others.

**Inventory.** Root `sInv_BottomCover` (3714), a 640 × 81 strip at
(9, 366). The sheet picture is `sInventory` (3716), 597 × 416 at (0, 0),
so it fills the frame to the left of the sidebar and stops at the
status bar. `sInventoryPanel` (3710) is the character panel at
(205, 5), 192 × 300. The mode banner sits under it at (208, 331),
190 × 82, and which sprite is shown is the mode: `sInventoryDefaultMode`,
`sInventoryLootingChestMode`, `sInventoryLootingBodyMode`,
`sInventoryLootingGroundMode`. The bag behind those pictures is the
7 × 64 grid from section 3.

**Party.** No root sprite. The procedure builds `sParty_Bkgnd` (full
frame) and the character tabs and heads (`sParty_Tab_*`,
`sParty_Head_*`). `sParty_Panel_Buttons` is (422, 375), 163 × 37.

**Shop** is the same shape as inventory and not a sidebar tab.
Interface `0x8` calls `FUN_0055b6ff`. `sShopping_Main` (4245) is
597 × 416 at (0, 0). The quantity popup is `sShopping_QuantityPopup`
(4361) at (200, 89), 230 × 199.

---

## 6. Conversation bubbles and the small menus

Three interface ids open a bubble. All three take the size from the
table at `0x60e1b8` (four records of 20 bytes: sprite, minimum lines,
maximum lines, top inset, bottom inset), then `Win_SetPos` the dialog
to sprite coordinate (32, 22), which is absolute. The insets are signed
and expand the text rectangle inside the bubble
(`top -= inset`, `bottom += inset`).

| Lines | Sprite | Box after the (32, 22) move |
|---|---|---|
| 0–3 | `sConvBackTiny` (4191) | (156, 153) 350 × 154 |
| 4–5 | `sConvBackSmall` (4193) | (156, 130) 350 × 199 |
| 6–9 | `sConvBackBig` (4195) | (156, 80) 350 × 299 |
| 10–12 | `sConvBackHuge` (4189) | (156, 30) 350 × 400 |

They share a left edge at x = 156 and a width of 350, and they grow up
and down as the line count rises. The huge bubble's bottom is y = 430,
just above the resting status bar. A second copy of the table at
`0x60e9c0` uses the same four sprites with the line ranges 0–3, 4–4,
5–8, and 9–12.

Which id picks which size:

| Id | Opener | Size |
|---|---|---|
| `0x13` | `FUN_0053a522` | forced through `FUN_005384f3(10)`, so the huge bubble. Dialog id `0x1b38` |
| `0x14` | `FUN_005383b0` | measures the text and walks the table from 9 lines down. Dialog id `0x1b3a` |
| `0x15` | `FUN_00539eb5` | `FUN_005384f3(3)`, the tiny bubble. Dialog id `0x1b39` |

The choice rows are `sConvChoice1` through `sConvChoice11`, each with a
highlight partner. The bubble procedure writes the menu string into
those controls (`FUN_004b994d` from the tables at `0x60e20c`,
`0x60e284`, and `0x60e2fc`). The conversation that decides which lines
exist is [`dialog.md`](dialog.md). The click that opens it is
[`interactions.md`](interactions.md).

The identify menu is separate. `FUN_0054aa30` opens `sMisc_IDMenu`
(575), a 481 × 411 panel at (79, 9), with Assess, Use, Drop, and Exit
along the bottom at y = 375 (`sMisc_AssessBtn` 89 × 17 at x = 121, then
Use at 225, Drop at 326, Exit at 426). `FUN_0054bd26` builds the other
small menu: `sMisc_AttackBtn` and `sMisc_SpeakBtn` on `sMisc_NPCMenu`,
which is 178 × 110 at (232, 185). The attack and speak captions sit
inside that panel at about (262, 209) and (263, 256).

Two more centered panels, opened when an enemy is examined:
`sMisc_Enemy1_Back` at (206, 106), 230 × 268, and `sMisc_Enemy2_Back`
at (203, 121), 230 × 237.

---

## 7. Every interface id

`FUN_004366c0` switches on the id. The openers for the four sheets are
thin: they check the matching sidebar radio and call the show function
from section 4.

| Id | Opens |
|---|---|
| `0x0` | No dialog. Resolves the party and installs the three UI hooks, with the world left running |
| `0x1` | Spells sheet (`FUN_005471ef`) |
| `0x3` | Inventory sheet (`FUN_005471a8`) |
| `0x4` | Party sheet, if resting is allowed (`FUN_0054729f`). Otherwise it logs and returns |
| `0x5`, `0x6`, `0x7`, `0x9`, `0xa`, `0xb` | Inventory sheet. `0x5` is `DoLooting` and a container click. `0x9` is the right-click region menu |
| `0x8` | The shop (`FUN_0055b6ff`) |
| `0xc`, `0xd`, `0xe` | Attributes sheet (`FUN_00547161`). `0xc` is the NPC click that is not a direct conversation |
| `0x10` | No dialog. `FUN_004376a8(1)`, world running |
| `0x11` | No dialog. `FUN_004376a8(0)`, world paused |
| `0x12` | Lock and trap. Palette 1, `FUN_00565c30`. The art is the `sTrap_*` range in [`palette-map.md`](palette-map.md) |
| `0x13`, `0x14`, `0x15` | The conversation bubbles in section 6 |
| `0x16` | A puzzle, from the bits of the third argument. Bit 1 palette 6, the beam puzzle (`FUN_00558780`). Bit 2 palette 7, the ship console (`FUN_0055a190`). Bit 4 palette 8, the door wheel (`FUN_0053b190`) |
| `0x17` | The travel map (`FUN_005473c0`). Which of the four maps, and which hotspot travels where, is [`interactions.md`](interactions.md) |
| `0x18` | No dialog. Restores the world unless flag bit 3 at `DAT_00628d6c+0x4bc2c` is already set |
| `0x19` | Palette 9 (`pBookSysPal`) and no dialog of its own. The shelf, the save window, and the options screens are opened by the callers in section 9 |
| `0x1a` | A dialog with no root sprite (`FUN_00544cfb`, procedure `FUN_00544e80`). Three call sites pass it an object. What that object draws was not walked |
| anything else | Returns 0 |

There is no case `0x2` or `0xf`.

The cursor is the same compositor, drawn after the controls. Which
cursor id a world hit becomes is the table in
[`interactions.md`](interactions.md). `sCursor_Pointer` is an 8 × 8
bitmap with hotspot (3, 3), so the center of that bitmap sits on the
sprite position, and the position is updated to the mouse.

---

## 8. Open

- The TEXT resource header is copied as eleven dwords (`FUN_1002240c`)
  and then a string is resolved from one of them. The status-bar caption
  is sprite 15, whose only reference is a TEXT. The field layout inside
  those eleven dwords was not pinned down.
- Conversation choice rows are placed by the bubble procedure from the
  line count. The bubble boxes above are the backgrounds; the y of each
  `sConvChoice*` row was not measured one by one.
- `Win_CreateControl` type 2 shares the button procedure and is not used
  by `RtK.exe`. Type 4 is used, by the document viewer, and nothing in
  the procedure distinguishes it from a push button.

---

## 9. The title shelf, and the page that turns

The title screen and the in-game Book button are two doors into the same
art. Neither one is interface `0x19`. That case only installs palette 9.

**From the title.** `FUN_0050c17c` checks the string at its `+0xe4`. When
the length word in front of that string is 0, no chapter was named, so it
calls `FUN_004366c0(0x19)` and then `FUN_00534ebf`. That creates the shelf
dialog: root sprite `sBookShelf` (7099, one bitmap), id 2000, procedure
`FUN_00534ef3`, level 10000. On message `0x2000` the procedure registers
four script replacements, and on `0x2001` `FUN_0053563c` builds the
buttons. The shelf picture itself does not play a queue. It is already
the open shelf.

**From a running chapter.** The Book row (`sMain_Book`, id `0x68`) calls
`FUN_0043bb6b`, which sets the mode field at `DAT_00628d6c+0x4bc30` to 3
when it was 0. `FUN_0043b718` sees mode 3 and calls `FUN_00547317`:
palette 9, the status bar, then `FUN_00535dec`. That is the save window,
dialog id 1000, procedure `FUN_00535e1d`, no root sprite. The shelf is
not created on this path. Choosing Exit to Shelf (`sBookWinExitToShelf`,
id `0x3ef`) calls `FUN_00537af9`, which shows the shelf if it already
exists and calls `FUN_00534ebf` if it does not.

### What a page turn is

A page turn is a QUEUE resource played on a sprite.
`FUN_004b9981(sprite, queue)` is `process_setqueue(sprite, queue, 0)`.
`RtSetQueue` is the same call with the hide flag in the last argument.
`process_setqueue` (`Rtlib32.c`) copies the queue onto the sprite through
`SpriteSetQueue`. `SpriteAnimate`, already called on every refresh,
steps it.

A queue is a list of commands. `FUN_10036669` gives each command's size
from the table `FUN_10036780` fills; command 1 is 22 bytes. While that
command is current, `FUN_10036875` reads it and `FUN_100309e5` sets the
sprite's cel range. `FUN_10037940` then holds the frame until
`timeGetTime` passes a deadline, adds the command's delay to that
deadline, and steps. The delay is wall-clock milliseconds.

Command 1's layout, from `FUN_10036875`:

| Offset | What it is |
|---|---|
| `0` | opcode, as a word |
| `2` | first cel. If the byte at `+0x12` is nonzero, this is an Rt variable index instead |
| `6` | last cel. If the byte at `+0x13` is nonzero, this is an Rt variable index instead |
| `0xe` | milliseconds to hold each cel. A value of `-1` leaves the sprite's current period alone |

The queue reference on a sprite is not one of the cels. Cel 0 is the
first bitmap in the sprite's list.

Command `0x15` is an embedded script call. The sprite message procedure
`FUN_10020e31` sees it and runs the bytes through the script interpreter.
Those bytes are script opcode 1, whose argument is a SCRIPT resource id
(`FUN_100176c5` into `FUN_10021b08`). `FUN_10021b08` runs the C function
registered for that id with `RtAddScriptReplacementFunc`. The 8-byte
SCRIPT body stays in the archive; the registered function is what runs.

Every shelf page-turn does the same four commands, 76 bytes. The click
handler sets Rt variable `0xd` to 11 and `0xe` to 12, disables the shelf
buttons through `FUN_00535a25`, creates the open-book sprite as a control
on the shelf, and starts the queue.

| Command | What plays |
|---|---|
| cels 0 through variable `0xd` | cels 0..11, 125 ms each. Twelve frames, 1.5 s |
| call `xBook_StartBookOpeningSound` (7096) | `FUN_00538360`, the opening sound, at the splice |
| cels from variable `0xe` through 32 | cels 12..32, 125 ms each. Twenty-one frames, 2.625 s |
| call the finished script | the screen that click was opening |

Each of those sprites holds 33 bitmaps. On the options turn they are
named `bbk11_0001` onward, and cel 0 is that first bitmap. Twelve frames
plus twenty-one frames is the whole list. The two variables are the
splice point, and every call site stores the same 11 and 12.

### Which click plays which queue

`FUN_0053563c` builds the shelf. A click is message `0x100` in
`FUN_00534ef3`.

| Id | Sprite | What the click does |
|---|---|---|
| `0x7d3` | `sBookShelfExit` | Quit confirm. No queue |
| `0x7d4` | `sBookShelfDeletePlayer` | `FUN_00535c01(1)`, delete mode. Pushes cursor `sBookShelf_DeleteCursor` with queues `qBookSys_Delete_Norm` and `qBookSys_Delete_Hot`. Each queue is one cel |
| `0x7d5` | `sBookShelfCancelDelete` | `FUN_00535c01(0)`. Created hidden, shown in delete mode |
| `0x7d6` | `sBookShelfOptions` | `sBookShelfSysOptionsOpen` / `qBookShelfSysOptionsOpen`. Finishes in `xBookSys_SysOptionsFinished` |
| `0x7d7` | `sBookShelfNewPlayer` | `sBookShelfNewBookOpen` / `qBookSysNewBookOpen`. Finishes in `xBookSys_NewOpenFinished` |
| `0x7d8` | `sBookShelfCredits` | `FUN_004320c3`, the credits screen. No queue |
| `0x7d9` + n | `sBookShelfBook1` … `Book10` | That slot's open sprite and queue, ids stored on the button. All ten queues finish in `xBookSys_OpenFinished` |

The three finish functions:

- `xBookSys_OpenFinished` (`FUN_00535b9e`) destroys the page-turn control,
  re-enables the shelf, hides the shelf, and calls `FUN_00535dec`. That
  is the save window: `sBookWinSave`, `sBookWinLoad`, `sBookWinDelete`,
  `sBookWinOptions`, twelve `sBookWinListSaveGameName*` rows, and
  `sBookWinReturnToGame` (id `0x3f0`), which the builder disables when
  `DAT_00628d6c+0x18` is 0 because no chapter is loaded.
- `xBookSys_NewOpenFinished` (`FUN_005380e2`) hides the shelf and calls
  `FUN_00432a50(0)`. That constructs the game-options screen, vtable
  `0x005A6938`, with the book-name field enabled.
- `xBookSys_SysOptionsFinished` (`FUN_0053814a`) calls `FUN_00529740(0)`,
  the system-options screen, vtable `0x005A9F78`.

`sBookWinOptions` (id `0x3ec`) also opens game options, through
`FUN_00432a50(1)`, with the book-name field left disabled. That click
does not play a queue. The page turn already happened on the way in.

### Options, journal, and documents, once they are open

System options and game options both open through `FUN_0052e785`: palette
from the screen object, then a dialog whose root is `sOptionsBackdrop`
(7918). The child is `sOptionsSystemBackground` or
`sOptionsGameBackground`, one bitmap each. Nothing in that opener starts
a queue.

The row that lights up is a separate sprite, `sSysOptionsMVolBrowse`,
`sGameOptionsDifficultyBrowse`, and the other `*Browse` names. Each is a
single cel. `FUN_004f267b` shows it while that row is the current one
and hides it otherwise. System options tracks the current row at object
`+0x48` (`FUN_0052a19c`); game options tracks it at `+0x2c`
(`FUN_00433b33`). The buttons on those rows are the ordinary cel slots
from section 3: accept is three bitmaps, a radio such as
`sSysOptionsMusicOn` is four.

The journal (`FUN_00438802`, root `sJournalFrame`) and the document viewer
(`FUN_004379e0`, root `sDocBackdrop`) are the same kind of screen. Each
root is one bitmap. Journal tabs are four bitmaps each (`bJournalTab0A`
through `D`), and the document's previous and next buttons are four
bitmaps (`bDocPrevNormal`, `Hilite`, `Browse`, `Gray`). Turning a
document page swaps which page sprite is shown. It does not play a queue.

### The party sheet's book

The readable book on the party sheet is the same machine at a different
speed. Opening it is control id `0x42e` in the party procedure: it
disables that control and calls `RtSetQueue` on `sParty_Book` (3941) with
`qParty_Book_Open` (3942). The sprite is 31 bitmaps (`brstf_0001`, then
`brstf_c001` onward) plus that queue. The queue plays cels 1 through 30
at 83 ms each, about 2.5 s, then calls `xParty_Book_Open_Finished`
(3736), which the party dialog registered as `FUN_00550c2c`. That
destroys the opening control and creates the open-book page controls.

A later page flip uses `sParty_RecipePageTurn`. `qFlipPageForwards` plays
cels 0 through 4 at 83 ms, and `qFlipPageBackwards` plays cels 4 through
0. `FUN_100309e5` treats a descending range as a reverse. Each ends in
`xParty_Page_Turn_FinishedFwd` or `xParty_Page_Turn_FinishedBwd`
(`FUN_00551256`, `FUN_00551294`), which uncovers the page that was
under the flip.
