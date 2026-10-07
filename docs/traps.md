# Traps

How a trapped chest or door goes from a click to the lock screen, and
when the result actually lands. The key match, the screen types, the
layout names, and the skill roll are already in
[`inventory.md`](inventory.md) §10. The click that reaches `DoTrapLock`
is in [`interactions.md`](interactions.md). This note is the clock:
the gear, and the wait between a blown trap and the scene script.

Function names are the stable citations.
`python tools/show_func.py out/decompiled/RtK.c FUN_0056604a` re-finds
one. `RtK.c` line numbers move. Nothing here writes to the game install.

---

## 1. From the scene into the lock screen

A trapped object is a character. Chapter 9's chests and doors use the
same `OnTrigger`:

```
if (TRUE == IsLocked () || TRUE == IsTrapped ())
    DoTrapLock ();
else
    DoLooting ();
```

`DoTrapLock` is `FUN_004366c0(0x12, character)` when an interface is
already up (`DAT_00628d6c+0x354`). Case `0x12` forces the actor to
James (`DAT_0066dfb0`), switches to palette 1, and opens the lock
screen `FUN_00565c30`. The screen copies the instance trap index
(`+0xd0`), the trapped flag (`+0xd4`), and the lock flag (`+0xd8`)
into `DAT_0066fc90`, `DAT_0066fc20`, and `DAT_0066fc60`. Index `-1`
means no layout. Otherwise the layout is
`DAT_00616f20 + index * 0x28`.

The party is not moved by that open. Scenes that care about where
everyone stands do it themselves, on a touch plate, before the UI.
Scene `70003`'s chest plate sets formation `TRChest` under the comment
"Set position for failed trap disarm". Scene `70005` sets `GBChest`
under "set positions should James fail to disarm trap". Those plates
are armed from the scene `OnEnter` and again from the character
`OnTrigger` that calls `DoTrapLock`.

---

## 2. Two clocks for one tool drop

`Options` / `TrapGame` in the book ini is `DAT_00617a5c`.
`FUN_00410f44` reads it and `FUN_00411194` writes it back. The byte
in the image is `1`.

Dropping a tool is dialog message `0x2200` in `FUN_00569046`. The
control selects the mode:

| Control | Mode | Tool |
|---|---|---|
| `0x95` | 4 | Probe |
| `0x96` | 5 | Lockpick |
| `0x97` | `FUN_0056adf7(2, part)` | Disarm pick, `DAT_0066fc24 = 2` |
| `0x98` | `FUN_0056adf7(1, part)` | Disarm pick, `DAT_0066fc24 = 1` |
| `0x99` | `FUN_0056adf7(0, part)` | Disarm pick, `DAT_0066fc24 = 0` |

A lockpick (`0x96`) dropped while `DAT_0066fc20` is set and the three
stages are not all disarmed (`FUN_0056a7c2` returns 0) detonates
immediately, animated or not. The log is
`Trap detonating on lock pick attempt on trapped obj that is not disarmed!`
Using the key (`FUN_0056899d`) does the same thing.

**`TrapGame` off.** The drop rolls before `FUN_00569046` returns, and
runs the latched callback on the spot. The fit values and the skill
virtuals are the table in `inventory.md` §10. There is no gear.

**`TrapGame` on.** The drop does not roll. It latches a callback,
starts the sprites, and waits for a later dialog beat to apply whatever
the click left in `DAT_0066fc1c`.

The latch installed at drop, before any click:

| Mode | Callback waiting when the beat arrives |
|---|---|
| 1, 2, 3 (disarm) | `FUN_0056a922`, detonate |
| 4 (probe) | a stage fail (`FUN_0056a1b1` trigger, `FUN_0056a293` mechanism, `FUN_0056a375` delivery). Each of those then rolls probe skill and may detonate |
| 5 (lockpick), dropped part id 10 | `FUN_0056a7a1`, a sound |
| 5, any other part | the latch is left alone. The trapped case already detonated above |

So a disarm attempt is a detonation until a click replaces that latch.
A probe attempt is a failed probe until a click replaces it.

---

## 3. The gear

With `TrapGame` on, the drop also writes engine variable 9:

| Tool | Skill virtual | Value stored |
|---|---|---|
| Probe (`FUN_0056b75c`) | `+0x9c` | `skill / 5 + 1` |
| Disarm (`FUN_0056b7c0`) | `+0xa4` | `skill / 5 + 1` |
| Lockpick (`FUN_0056b824`) | `+0xa0` | `skill / 5 + 1` |

`RtSetVar(DAT_0066e058, 9, value)`. The lock screen's own open sets
the same variable to 1. No function in `RtK.c` reads variable 9. The
dialog script is the consumer, and that script was not extracted, so
what the number does to the sweep (speed, length, a branch) is not
visible from the C.

The same three functions pick the queue id in `DAT_0066fc84`.
`DAT_00617a60` is `1` in the image and is never assigned in `RtK.c`,
so the queue is `0x1516`. The other branch would store `0x1517`.
Script hook `0x14de` (`FUN_00569bde`) is what actually starts it, by
enabling the gear control and calling
`FUN_004b9981(0x1514, DAT_0066fc84)`.

The dialog registers these hooks on its create message (`0x2000` in
`FUN_0056604a`). The order they run is the script's, not this list:

| Script id | Function | What the C does |
|---|---|---|
| `0x14dd` | `FUN_00569e91` | Stop the gear, the tool sprite, and `0x14ea`, then call the latched callback |
| `0x14de` | `FUN_00569bde` | Enable the gear control and start queue `DAT_0066fc84` |
| `0x14df` | `FUN_0056a9f0` | Show the mechanism sprite |
| `0x14e0` | `FUN_0056abc6` | Clear the trap, close the UI, and start the world reaction (§5) |
| `0x14e1` | `FUN_0056aadb` | Show the delivery sprite |
| `0x14e2` | `FUN_0056b035` | A mechanism burst sprite |
| `0x14e3` | `FUN_0056b077` | Another mechanism sprite |
| `0x14e4` | `FUN_0056b0c5` | A delivery sprite |
| `0x14e5` | `FUN_0056a792` | Close the UI and run the character `OnTrigger` |
| `0x14e6` | `FUN_0056b8f7` | A sound chosen by mechanism id |
| `0x14e7` | `FUN_0056b94d` | A sound chosen by delivery id |

### The click

Control `0x6f` in `FUN_0056604a` (dialog message `0x100`) is the gear
click. It freezes sprite `0x1514` with `process_setqueue(0x1514, 0, 0)`,
reads the current cell, and turns one cell field into an angle:

```
raw   = *(cell + 0x1c) * 4
angle = raw - 0x53a8          // 21416
if angle > 359:
    angle = raw - 0x5510      // one turn, 360 degrees
```

The log line names that angle `aRotate` and the four bounds
`aDisarmA1`, `aDisarmA2`, `aNeutralA1`, `aNeutralA2`. The call that
would fill those `%d` slots was not recovered, so the names are not
pinned to particular locals. The comparisons are.

`disarmLow < angle < disarmHigh` is the long arc. Outside it — the
short arc that crosses 0 — the log says `Between Disarm Angles` and
the click calls `FUN_00569c33`, which replaces the latch with a
success callback.

Inside the long arc but outside `neutralLow < angle < neutralHigh`,
the log says `Between Neutral Angles` and the click calls
`FUN_00569d0e`. That rolls `1..101` against disarm skill (`+0xa4`).
Skill below the roll latches `FUN_0056a922` and logs
`Detonating trap - disarm in netural area - failed subsequent disarm trap skill check.`
(The binary spells it "netural".) Skill at or above the roll clears
the latch, so the later beat does nothing.

Inside the neutral interval the log says `Failed` and the click does
not touch the latch. For a disarm, that leaves the detonation that
was stored at drop.

| Mode | disarmLow | disarmHigh | neutralLow | neutralHigh | Success arc (crosses 0) |
|---|---:|---:|---:|---:|---|
| 1 | 9 | 351 | 53 | 307 | `angle <= 9` or `angle >= 351` (19°) |
| 2 | 16 | 344 | 65 | 295 | `<= 16` or `>= 344` (33°) |
| 3 | 40 | 320 | 82 | 278 | `<= 40` or `>= 320` (81°) |
| 4, 5 | 82 | 278 | 82 | 278 | `<= 82` or `>= 278` (165°). Neutral is the same interval, so that branch never runs |

Mode 1 is the tight arc and, on the `TrapGame` off path, the easy roll
(tool fit 100). Mode 3 is the wide arc and the hard roll (tool fit
900). The same mode number is not the same difficulty on the two
clocks.

Which mode a disarm pick gets is `FUN_0056adf7`. Rows are the part id
the tool was dropped on (1..9). Columns are the pick,
`DAT_0066fc24` 0, 1, 2, which are controls `0x99`, `0x98`, `0x97`.
A part whose stage was already failed (`DAT_0066fc68`, `DAT_0066fc10`,
or `DAT_0066fc18` equal to 1) returns `-1` instead of a mode.

| Part id | Pick 0 (`0x99`) | Pick 1 (`0x98`) | Pick 2 (`0x97`) |
|---:|---:|---:|---:|
| 1 | 3 | 2 | 1 |
| 2 | 1 | 2 | 3 |
| 3 | 3 | 2 | 1 |
| 4 | 1 | 3 | 2 |
| 5 | 3 | 2 | 1 |
| 6 | 2 | 3 | 1 |
| 7 | 1 | 3 | 2 |
| 8 | 1 | 2 | 3 |
| 9 | 3 | 1 | 2 |

The success callback (`FUN_00569c33`) depends on the part id and the
mode. Probe mode 4 identifies the stage. Disarm modes call
`FUN_0056a457` (trigger), `FUN_0056a51c` (mechanism), or `FUN_0056a5e1`
(delivery). A worked trigger logs `Disarm - Trigger - Worked`, stores
the pick, and asks `FUN_0056a7f0` whether all three stages are done.
All three done clears instance `+0xd4`. Lockpick part id 10 latches
`FUN_0056a6a6`, which clears `+0xd8` unless `DAT_0066fcb4` is set.

A failed probe does not detonate from the angle. It logs
`Probe - Trigger - Failed` (or Mechanism, or Delivery) and then
`FUN_0056ba3a` rolls `1..101` against Stealth, actor virtual `+0x9c`
(skill line 9, the short at actor `+0x96`). Skill below
the roll detonates and logs
`Detonating trap - probe failed - failed subsequent disarm trap skill check.`

---

## 4. When the latch runs

The click only stores a function pointer. The pointer runs when the
dialog script reaches id `0x14dd`, which is `FUN_00569e91`:

1. `process_setqueue` on `0x1514`, `0x1572`, and `0x14ea`, third
   argument `1`.
2. If a sound object was stored in `DAT_0066fca0`, call its virtual `+4`.
3. Call `DAT_0066fc1c` if it is set.

On the `TrapGame` off path that same call happens inside the drop,
before `FUN_00569046` returns. On the on path the player can still be
looking at the gear when the outcome is already decided; the script
beat is what plays it.

---

## 5. From the detonation to `OnFail`

`FUN_0056a922` is the UI detonation. It sets `DAT_0066fc74`, asks the
frame loop for five extra `RtService` pumps (`FUN_0045ec31(5)` into
`DAT_00629b58`; the dialog's destroy message sets that back to 0),
disables controls `0x9b` and `0x9c`, and plays the trap sprites and a
sound. It does not call the character script.

The world hears about it from script hook `0x14e0`, `FUN_0056abc6`:

1. Clear instance `+0xd4`, unless `DAT_0066fcb4` is set.
2. Close the lock UI with `FUN_0056ae7e(-1)`. Argument `-1` does not
   run `OnTrigger`. Argument `1` does, which is the path a finished
   key screen and a fully disarmed trap use (`FUN_0056a792`,
   `FUN_0056a7f0`).
3. Walk every character in the scene list (`FUN_004ee57f` on
   `DAT_00628d6c+4`) through `FUN_0056bafc`.

`FUN_0056bafc` applies damage from the layout ids, then queues a
reaction clip. The clip's end callback is `FUN_0056baa4`, and that is
what runs the character's `OnFail`. If no character queued a clip,
`FUN_0056abc6` calls `FUN_0056baa4` itself, so `OnFail` runs before
the hook returns.

The damage, all of it subtracted through `FUN_004a42d4`:

| Layout test | Roll | Kind | Extra |
|---|---|---|---|
| Delivery 7 or 8, and character `+0x58 == 1` | four uniform draws of `2..8` | 0 | forces reaction clip `0x8d3` |
| Mechanism 6 | three uniform draws of `2..8` | 3 | `explo.bex` when the character has a sound id |
| Mechanism 4, and (delivery 9 or character `+0x58 == 1`) | one uniform draw of `2..12` | 6 | half of that again as a second effect; `explog.bex` when delivery is 9 |

Mechanism 6 is Ember and Fire. Mechanism 4 is Serpent, Dagger, and
Venom. Delivery 9 is Venom and Fire. The other ids are in §6.

The reaction clip id comes from a `1..101` roll: under 31 is `0x8a9`,
under 61 is `0x875`, otherwise `0x8ac`. Character `+0x58 == 1`
overrides that with `0x8d3`. The length stored by `FUN_0040bbd0` is
`(that roll / 5) + 25`, or `+ 15` when `+0x58 == 1`. Values under 1
are stored as 0. The unit of that number was not tied to a frame or
a millisecond. `OnFail` waits until that clip ends.

Chapter 9 does declare `OnFail`, on the slave-pen cage and on two
doors (the workshop door and the skull door). All three bodies are
empty. The reaction and the damage still happen; the script hook is
just unused there.

---

## 6. What the three layout ids are

`SetTrapType` stores an index at instance `+0xd0`. The 21 names and
their indexes are the table in `inventory.md` §10. Each record's three
integers, at `+0x10`, `+0x14`, and `+0x18`, are the trigger, the
mechanism, and the delivery. They are not one id per element name.

| Id | Used as | Names that carry it |
|---|---|---|
| 1 | trigger | every `Wire` |
| 2 | trigger | every `Plate` |
| 3 | trigger | every `Hook` |
| 4 | mechanism | Serpent, Dagger, Venom |
| 5 | mechanism | Needle, Blade |
| 6 | mechanism | Ember, Fire |
| 7 | delivery | Serpent, Needle, Ember |
| 8 | delivery | Dagger, Blade |
| 9 | delivery | Venom, Fire |

`SerpentWire` is `(1, 4, 7)`. `FireHook` is `(3, 6, 9)`. Chapter 9
sets `SerpentWire`, `NeedleWire`, `EmberHook`, and `VenomHook` on
specific chests. Chapter 3 rolls `SetTrapType` across the wire, plate,
and hook names when it stocks a chest. `InnerSlavePenCageLock.SetTrapType("FireHook")`
is present and commented out.

---

## 7. Open questions

- **Variable 9.** The skill writes it and the dialog script is the
  only plausible reader. The script resource was not extracted, so the
  gear's degrees per frame, and the order of hooks `0x14dd`–`0x14e7`,
  are not in this note.
- **`DAT_00617a60`.** It selects queue `0x1516` versus `0x1517`. The
  image byte is 1, and nothing in `RtK.c` stores it.
- **The clip length unit.** `(roll / 5) + 25` is what `OnFail` waits
  on. Whether `FUN_0040bbd0` counts frames was not traced.
- **Character `+0x58`.** It gates the delivery-7/8 damage, the
  mechanism-4 damage, clip `0x8d3`, and the shorter length bonus.
  The field was not tied to a script property.
- **The skill virtuals `+0xa4`, `+0x9c`, `+0xa0`.** Still unnamed, same
  as in `inventory.md`.
- **`DAT_0066fcb4`.** When it is set, a successful lockpick does not
  clear `+0xd8` and a detonation does not clear `+0xd4`. Nothing in
  these paths writes it.
