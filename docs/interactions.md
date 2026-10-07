# Interactions

How a click in Return to Krondor becomes a walk, a conversation, a door, or
a scene change. The scene, the camera, the cost map, and the view switch
are already in [`scene-runtime.md`](scene-runtime.md). This note is the
layer on top of that: the mouse, the cursor, and the script objects the
click ends up calling.

Function names are the stable citations. `RtK.c` line numbers move every
time the decompile is regenerated;
`python tools/show_func.py out/decompiled/RtK.c FUN_0045b3d3` re-finds one.
Script examples are from the inflated chapter sources under
`out/plaintext/GameData/`. Nothing here writes to the game install.

---

## 1. The shape of it

Adventure mode is game-mode value `1` on the scene root at
`DAT_00628d6c+0x4bc2c`. In that mode `FUN_0043a9ea` returns the picker at
`+0x35c`. Combat (`4`, and `0x40`) uses a different picker at `+0x360` or
`+0x364` and is not this note.

Every interesting click is the same pipeline:

1. A Windows mouse message is translated into a small integer event.
2. The event calls a method on the picker.
3. The picker already knows what is under the cursor, because the cursor
   is redrawn from a fresh pick every frame.
4. That hit is either a walk order, a character UI, or a script
   `OnTrigger`.

Doors and teleporters are not a separate engine object. A locked door is a
character whose model type is `Door`. A doorway the party walks through is
a touch-plate polygon whose script calls `Teleport`.

---

## 2. From the mouse to an event

`FUN_00435563` and `FUN_00434b05` are the window procedures. Mouse messages
go to `FUN_0041dcd9`, which walks the binding table built by `FUN_0041be90`
on the map named `GameDefault` (`DAT_00628d6c+0x340`). The record layout,
the rest of the keys, and what a remap would have to touch are in
[`controls.md`](controls.md). This section is the adventure click.

A binding is a 0x28-byte record:

| Field | Meaning |
|---|---|
| `+4` | Windows message, the hash key |
| `+8` | game event posted to `FUN_004188c6` |
| `+0xc` | mode mask. Bit `0x20` means the binding is legal in every mode. Otherwise the bit has to overlap `DAT_00628d6c+0x4bc2c` |
| `+0x10` | modifier bits. `1` control, `2` shift, `4` alt. A clear bit means that key must be up |
| `+0x14` | payload kind. `4` is a mouse point, `1` is a key |

The adventure bindings that matter:

| Windows message | Modifiers | Event | What it calls |
|---|---|---|---|
| `WM_MOUSEMOVE` `0x200` | none, or control | `0x20` | `FUN_00418756`, stores the point at `+0x264` / `+0x268` |
| `WM_LBUTTONDOWN` `0x201` | none | `0x21` | `FUN_00418778` → picker `+0x34` = `FUN_0045b3d3`, the click |
| `WM_LBUTTONDOWN` `0x201` | control | `0x22` | `FUN_00418807` → picker `+0x38` = `FUN_0045b5da` |
| `WM_RBUTTONDOWN` `0x204` | none | `0x23` | `FUN_0041882e` → picker `+0x3c` = `FUN_0045b627` |
| `WM_LBUTTONUP` `0x202` | none | `0x24` | `FUN_004187e0` → picker `+0x40`, which on this picker is an empty stub |

A double-click does not get its own event. Both window procedures rewrite
`WM_LBUTTONDBLCLK` (`0x203`) into `WM_LBUTTONDOWN` before the binding table
sees it, so it takes the ordinary click. A binding of `0x203` to event
`0x22` is registered and never reached from these procedures.

Keyboard camera keys live in the same table. `[` (`VK_OEM_4`, `0xdb`) posts
event `0x71` and `]` (`VK_OEM_6`, `0xdd`) posts event `0x74`. `FUN_004188c6`
turns those into `FUN_0041a03b(1, 0)` and `FUN_0041a03b(1, 1)`, the
exit-table view step from the scene note. Events `0x72`–`0x73` and
`0x75`–`0x76` also call `FUN_0041a03b`, and they are not bound on
`GameDefault`.

The picker vtable adventure mode installs is `0x005a6fe8`. The store is
inside `FUN_00439738`. Slot `+0x30` is `FUN_0045b3b0`, which turns picking
on and enables three of the four tests (hotspot, actor, cost map; not the
fallback ground test).

---

## 3. What is under the cursor

`FUN_0045db05` (`kRender_DrawSmartCursor`) reads the cursor, calls
`FUN_00453c13`, and draws the sprite whose id that call returned.
`FUN_00453c13` does two things: `FUN_00453c54` classifies the pixel, then
virtual `+0x4c` (`FUN_0045b6ef`) turns the hit into a cursor id.

`FUN_00453c54` keeps the nearest hit. The tests, in the order they can
win:

| Order | Test | Hit kind stored at picker `+8` |
|---|---|---|
| 1 | `FUN_004b9a36` on the interface overlay at `DAT_00628d6c[0xd5]` | `5`, and the rest of the tests are skipped |
| 2 | `FUN_0043591a` builds the camera ray. `FUN_004c0dc3` tests hotspot volumes along it | `1`, pointer at `+0x10` |
| 3 | Depth overlay under the pixel (`FUN_00454596`), unprojected by `FUN_00454654`, then `FUN_004fa544` for an actor at that depth. A second coverage buffer whose `w` differs by more than `0.001` vetoes the sample, so a click on the wall behind an actor stays a wall | `3` if an actor is closer |
| 4 | Cost-map ray `FUN_004221c3` / `FUN_00421af1`. A hotspot hit is kept when it is clearly in front of the ground (about `√2` tiles, scaled by the hotspot's `+0x90`) | `2`, world point at `+0x14` |
| 5 | A second actor query along the whole ray, if it is closer than the ground | `3` |
| 6 | `FUN_00422604`, only when the fallback flag at picker `+0x38` is set. Adventure mode leaves it clear | `2` |
| 7 | `FUN_004fa34c` against a held actor list, and only if the hit is not already an actor | `3` |

Kind `2` is then rejected by `FUN_004da51e` if the point sits in a 2D
exclusion polygon. The point is not stored, and the click is a miss.

Kind `3` is an actor whose user-data `+0x80` is a character. The
character's virtual `+0xfc` is a kind code. Code `0x20` with virtual
`+0x100` equal to `8` is dropped: the click falls through as a miss. That
is how an invisible blocker (`Object Impassable` in `Chars.tbl`, `Class :
Invisible`) can occupy space without being a target. Code `0x20` with any
other subtype is stored as kind `4` instead of `3`. People, and objects
that are not code `0x20`, stay kind `3`. The numeric codes have not been
tied to the `Class` / `Model_Type` strings by a traced parser.

The cursor names are the pair list at `0x005dc728`, looked up by
`FUN_004b9489`. `FUN_0045b6ef` returns one of these ids.

---

## 4. Hit kind to action to cursor

`FUN_0045b6ef` writes an action code to picker `+0x3c` and returns the
cursor id. The party leader has to be standing still (`mover +0x18 == 0`)
before a ground hit becomes a walk; otherwise a ground hit draws
`BASICCURSOR` and clicks do nothing.

| Hit `+8` | Action `+0x3c` | Cursor | When |
|---|---|---|---|
| `1` hotspot, no character at hotspot `+0x94` | `3` | `MANIPULATECURSOR` (13) | the volume itself is the target |
| `1` hotspot, character attached | `4` | `MANIPULATECURSOR` (13) | a touch plate with a script object |
| `2` ground, leader idle, cell walkable (`FUN_00421939`) | `6` | `MOVETOCURSOR` (6), or `EYEGROUNDCURSOR` (24) when `FUN_004286b1` finds an exit region under the point | the ordinary floor |
| `2` ground, leader moving or cell blocked | `0` | `BASICCURSOR` (1) | |
| `3` character, group name is `Party` | `2` | `TALKCURSOR` (23) if flag `+0x40` is set, else `FULLATTACKCURSOR` (7) if `+0x44` is set, else `BASICCURSOR` | clicking your own party |
| `3` character, any other group | `1` | `TALKCURSOR` (25) when virtuals `+0x10c` and `+0x130` are both true and `+0x40` is clear. `TALKCURSOR` (23) when `+0x40` is set. Otherwise `EYECURSOR` (5) | an NPC you can or cannot talk to |
| `3` character, action still `2`, virtual `+0x4c` true | `7` | `MANIPULATECURSOR` (13) | a container, chest, or similar prop |
| `4` object | `5` | `MANIPULATECURSOR` (13) | an object that is allowed to receive `OnTrigger` |
| none | `0` | `INACTIVECURSOR` (0) when picking is disabled (`+0x24 == 0`) | |

The two flags `+0x40` and `+0x44` are copied from the character's group
record at `character+200`, fields `+0x74` then `+0x58` / `+0x5c`. They are
filled when a conversation on that scene can play (`FUN_004bdff7` walks
conversations and calls `OnCanPlay`). So the talk cursor tracks "a
conversation on this character is currently allowed", not a hard-coded NPC
bit.

`UseHotSpots` (`FUN_0050ee5f`) writes `DAT_00628d6c+0x304`. That flag is
read when a hotspot *light* is attached (`FUN_00431336`). It does not
gate the click tests above.

---

## 5. The click

`FUN_0045b3d3` runs only when picking is enabled and `+8` is non-zero. It
switches on the action code:

| Action | Left click |
|---|---|
| `1` NPC | If virtual `+0x10c` is true and `+0x130` is false, `FUN_004366c0(0xc, character)` (`FUN_00547161`). If `+0x130` is true, `FUN_004366c0(0xd, character)` (`FUN_005471a8`). If `+0x40` is set, `FUN_004d08b2` opens that character's conversation directly |
| `2` party / prop | `+0x40` opens the conversation the same way. Otherwise, if `+0x44` is set, `FUN_004d6df4` |
| `3` bare hotspot | virtual `+0x44` on the hotspot object |
| `4` touch plate | If the plate is armed (`FUN_004d764c` reads `+0x14`), virtual `+0x44`, then `OnTrigger` on the attached character |
| `5` object | `OnTrigger` on the character |
| `6` ground | Store the world point (`FUN_004fa07c`) and raise the move flag with `FUN_0045612f(0)` |
| `7` container | `FUN_004366c0(0x5, character)`, the same UI `DoLooting` opens |

`FUN_004366c0` is the interface launcher. The ids used from a world click:

| Id | Opens |
|---|---|
| `0x5`, `0x9`, `0xb` | `FUN_005471a8` |
| `0xc`, `0xd`, `0xe` | `FUN_00547161` or `FUN_005471a8` as above |
| `0x12` | the lock UI. `DoTrapLock` is the script call that requests it |
| `0x17` | the travel map. `DisplayCurrentMap` requests it |

Control-click (`FUN_0045b5da`) does only one thing: if the action is `6`,
it stores the same point and raises the move flag with `FUN_0045612f(1)`.

Right-click (`FUN_0045b627`): on a character (hit kind `3`), if virtual
`+0x10c` is true it re-enters the left-click method; if not, it calls
`FUN_00492eb3` / `FUN_00492fa4` on that character. On a walk point whose
action is `6`, if `FUN_004286b1` names a region it opens interface `0x9`
on that region.

---

## 6. Clicking the floor to move

The move flag is `DAT_00629a2c`, set by `FUN_0045612f` and cleared by
`FUN_00456116`. The destination is the three floats at `DAT_0062ae90`.

`FUN_0045e8b5`, from the render loop, consumes the flag once
`FUN_004d6b76` agrees the party may move:

1. It logs `RenderLoop: New dest point` with the leader's name.
2. It reads the cost-map byte under the point (`FUN_0042163e`). Bit `0x20`
   or a class of 4 or more cancels the order. That is the same walk test
   as the search in the scene note.
3. It writes the point onto the party group at `+0x58` / `+0x5c`.
4. It sets party-group `+0x8c` from the flag argument: `0` for a plain
   left click, `1` for a control-click. What reads `+0x8c` after that was
   not traced; both paths then call the same follower.
5. `FUN_004ef00a` builds the path. That is the waypoint follower from the
   scene note, and it calls `FUN_00458f40` per leg. The leader searches.
   The other members stay on the `party` track.

A scripted move is the same follower from the other side. `WalkTo`,
`RunTo`, and `FlyTo` are methods on a group. `WalkTo("formation")` resolves
a `Formation` block — a list of `name : x, y, z, facing` — and
`FUN_004ef00a` walks the leader there. `DisableNavCursor(TRUE)` is what a
cutscene calls first so the player cannot queue a new point while that
walk runs. The cursor drawer (`FUN_0045dea1`) hides the nav cursor when
`DAT_00628d6c+0x4bbbc` is set and `+0x4bbc8` is not `1`.

Clicking the painted view is this path. Clicking the travel map is not.
`DisplayCurrentMap` (`FUN_0050de07`) opens interface `0x17`, and
`FUN_005473c0` picks one of four dialogs from the id at
`DAT_00628d6c+0x4bbdc` (written by `EnableMap`'s second argument):

| Id | Dialog |
|---|---|
| 0 | `FUN_00547680`, palette 2, proc `0x547f70` |
| 1 | `FUN_00547786`, palette 4, proc `0x54960f` |
| 2 | `FUN_00547703`, palette 3, proc `0x548ab6` |
| 3 | `FUN_00547809`, palette 5 |

`SetVisitedAllNodesForCurrentMap` only does anything when that id is `3`.
`SetJumpToAnyNodeForCurrentMap` is the cheat next to it. A click inside
the dialog is a `SpritePicked` test (`FUN_00547408` is the shape). Which
button travels where lives in those four dialog procs and was not walked.
Leaving a node still ends in `Teleport` or `FUN_004b7c9c`; the map does
not have its own movement code.

---

## 7. Talking to someone

How a node is written, how a line is added, and how the performance files
join up is [`dialog.md`](dialog.md). This section is the click.

A conversation is a `ConversationDef` on a scene. The fields that decide
how it plays:

| Field | Effect |
|---|---|
| `MenuText` | the line shown when this node is a choice. Empty on roots |
| `JournalText`, `AddToJournal` | journal entry |
| `DisableWhenPlayed` | the node goes away after it has run |
| `EnterNavMode` | `1` returns the player to walking when the node ends |
| `PotentialDest` | the next node names, comma-separated |
| `Groups` and `GroupMemberConversationLinks` | who is in the shot, and which member speaks |
| `Formation` | where those people stand |
| `OnCanPlay` | script. Return true and the node is offered |
| `OnEnd` | script after the line finishes. This is where most plot side effects are |

`GetConversation("name")` on a scene returns that object. `Play` is the
method at `0x005f1c50` (`FUN_004d0398`). It calls `FUN_004d08b2`, the
conversation manager at `DAT_00628d6c+0x370`, with the node as the root.

`FUN_004d08b2` in adventure mode (`+0x4bc2c == 1`) first switches the game
mode to `2` and calls `Display` on the node. If `Display` returns `3`, the
node has nothing to show and the manager continues. Otherwise it walks the
child list at `+0x28`. Each child is tested with `OnCanPlay`. Children
that return `1` are the menu. `GetNumTimesEntered` is how a node remembers
that it has run; `HasOccured` is the other query.

A click on an NPC with the talk cursor does not call `Play` itself. It
opens interface `0xc` or `0xd`, or, when the conversation-available flag
`+0x40` is set, calls `FUN_004d08b2` on the conversation pointer stored on
the character. `Group.Converse()` is the script form of that call: it
passes `group+0x54` field `+0x70` to the same manager. `Group.SpeakTo()`
matches the method name and returns success without doing anything else.
No chapter script calls `SpeakTo`.

`EnterConversation` / `ExitConversation` are character methods. They bookend
the shot. `ChangeConversationNode` retargets the current node. Roots are
named things like `C9EC01ROOT` and point at line nodes through
`PotentialDest`. A line node's `OnEnd` is ordinary script: it may `Play`
the next conversation, start a combat, or `Teleport`.

`TK0109M` in chapter 1 is a compact example. `OnCanPlay` returns true.
`OnEnd` teleports to scene `20001` view `9` and then plays a combat. The
root `C10109ROOT` has an empty menu and `PotentialDest : TK0109M`, so
playing the root offers that one line.

---

## 8. Doors

A door the player unlocks is a character, not a portal.

`Chars.tbl` defines them with `Class : Object` and `Model_Type : Door`,
plus an optional key token:

| Character | Model type | Model |
|---|---|---|
| `Generic Door` | `Door` | `Generic Door` |
| `Lucas Trap Door` | `Door, LucasKey` | `Lucas Trap Door` |
| `Petes Door` | `Door, PetesKey` | `Petes Door` |
| `BPT Skull Door` | `Door, SkullKey` | `BPT Skull Door` |
| `BPT Necromancers Door` | `Door, NecromancerKey` | `BPT Necromancers Door` |

The model line in `Models.def` is a `Container2D` sprite
(`CONTAINER2D_ACD`). The door is a flat 3D actor stood in the scene the
same way a chest is. Cages use the same pattern with `Model_Type : Cage,
YusefKey`.

The script surface on that character:

| Method | What it does |
|---|---|
| `IsLocked` / `SetLocked` / `ClearLocked` | the lock flag. `SetLocked` is what a scene's `OnEnter` calls to shut a door the player has not opened |
| `IsTrapped` / `SetTrapped` / `ClearTrapped` / `SetTrapType` | the trap on the same object |
| `DoTrapLock` | if an interface is up (`DAT_00628d6c+0x354`), `FUN_004366c0(0x12, character)`. That is the lockpicking screen |
| `DoLooting` | `FUN_004366c0(0x5, character)`, the container screen |

A conversation often *is* the door. In chapter 9 the slave-pen lock node
`C9SP01FORM` returns false from `OnCanPlay` until Roweland has been talked
to and the goblin is not close. Its `OnEnd` does `Door.DoTrapLock()`. The
click that started it was a talk click or a touch plate, and the door
character is only involved once the line finishes. What the lock
screen does with that character, including the gear and the wait
before `OnFail`, is in [`traps.md`](traps.md).

The wheel puzzle (`pDoorPuzzlePal`, dialog `FUN_0053b2b2`) is a third
thing: a full-screen puzzle, opened like any other interface, not a scene
door.

---

## 9. Touch plates, pressure plates, teleporters

Both plate types are polygons on the scene, with an `OnTrigger` script and
an `Active` flag. `DisArm` / `IsArmed` clear and test the armed flag at
`+0x14` (`FUN_004d7637`, `FUN_004d764c`). An unarmed plate's click does
not call `OnTrigger`.

**Touch plate** (`TouchPlateDef`, class `CTouchPlateSensor`). A polygon, a
plane equation, a `Range`, and a `StretchFactor`. The click ray hits it as
kind `1`. Action `4` requires the plate to be armed, then calls `OnTrigger`.
This is how a painted doorway, a statue, and a puzzle switch are clickable
without being characters. Chapter 9's `DoorToEC` is the pattern:

```
TouchPlateDef DoorToEC
  Poly : ...
  Active : TRUE
  Range : 350
  OnTrigger:
    Teleport (70001, 4, TRUE);
```

**Pressure plate** (`PressurePlateDef`, class `CPressurePlateSensor`). The
same polygon, plus `NavigationSensor`. `TRUE` marks a region the player is
not supposed to treat as a destination (chapter 9's `NoNav1` / `NoNav2`
have no `OnTrigger` at all). `FALSE` is a tripwire: `ToSlavePens` waits
until the party walks into the polygon, then `WalkTo`s the party and the
goblins into a combat formation and disarms itself. The trigger entry is
`FUN_004d765d`, which is only the `OnTrigger` call. The walker that
decides the party has entered the polygon was not separated from the
general sensor poll.

`CTimerSensor`, `CGameTimeSensor`, and `CIdleSensor` are the other three
sensor classes. They share `OnTrigger`, `DisArm`, and `IsArmed`. A game-time
sensor is how a scene waits until a clock value and then teleports. They
are not clicks.

---

## 10. Teleport and the other ways the scene changes

`Teleport` is `FUN_0050ed63`, a method on the game object.

```
Teleport(sceneId, viewId)
Teleport(sceneId, viewId, fade)
```

It always stays in the current chapter (`chapter+0xec`). The two integers
are the scene id and the view id, the same numbers as `Scene` `id :` and
`View` `id :` in `Loc_All.def`. The optional third argument becomes the
fade mode passed as `param_5` of `FUN_004b76ce`:

| Call | Fade mode | Meaning, from the scene note |
|---|---|---|
| two arguments | `2` | fade only when the chapter, the scene, or the overlay object actually changed |
| third argument true | `1` | always fade |
| third argument false | `0` | never fade |

`FUN_004b7c9c` resolves the ids and calls `FUN_004b76ce`. A miss logs
`kScene_Goto: Chapter %d Scene %d` and returns 0. The load that follows —
`OnExit`, fade, world, cost map, `OnEnter`, then the new view's painting —
is section 6 of the scene note.

`GotoScene` and `xGotoScene` are the named form of the same function. They
take chapter, scene, and view strings. `Teleport` is what the plates use
because the authors had the numeric ids in hand.

Three other transitions, so they do not get confused with a teleporter:

| Cause | Code | What changes |
|---|---|---|
| The party walks into another view's `CamPoly` | `FUN_004125f6` → `FUN_004b7c9c` with the same scene | painting, overlay, camera. No `OnExit` |
| `[` / `]` or the exit table | `FUN_0041a03b` | the previous or next view index in `scene+0x1c`, if `ValidCameraViews` allows it |
| `ChangeCameraView` | `FUN_0050e744` | a scripted view change inside the scene |

A plate that says `Teleport (70001, 4, TRUE)` replaces the scene. A plate
that says `PartyGroup.WalkTo("some formation")` does not.

---

## 11. What a scene script can call

The names the executable registers, limited to the ones this note depends
on. Handlers of `0` are methods on the object. The others are native
functions on the game object.

**Game object.** `Teleport`, `GotoScene` via the scene instead,
`ChangeCameraView`, `UseHotSpots`, `DisableNavCursor`, `EnableMap`,
`DisplayCurrentMap`, `PlayCinemat`, `DoPuzzle`, `DoShopping`, `DoResting`.

**Scene.** `GetConversation`, `GetGroup`, `GetTouchSensor`,
`GetPressureSensor`, `GetView`, `GotoScene`, `OnEnter`, `OnExit`.

**Group.** `Converse`, `WalkTo`, `RunTo`, `FlyTo`, `SetFormation`,
`GetCharacter`. `SpeakTo` is registered and empty.

**Character.** `EnterConversation`, `ExitConversation`, `IsLocked`,
`SetLocked`, `ClearLocked`, `DoTrapLock`, `DoLooting`, `OnTrigger`.

**Conversation.** `Play`, `OnCanPlay`, `OnEnd`, `GetNumTimesEntered`,
`HasOccured`, `Pause`, `Resume`.

**Plate.** `OnTrigger`, `DisArm`, `IsArmed`.

---

## 12. Open questions

- **Kind code `0x20` and subtype `8`.** The click filter is solid. The
  table that would show these are `Class : Object` and `Class : Invisible`
  was not found.
- **Virtuals `+0x10c`, `+0x130`, and `+0x4c` on a character.** The first
  two choose the talk UI, the third chooses the container UI. Their
  original names were not recovered.
- **Party-group `+0x8c`.** A plain click writes 0 and a control-click
  writes 1, and both then call `FUN_004ef00a`. The reader of that flag was
  not traced, so it is not yet safe to call the control-click "run".
- **`Group.SpeakTo`.** The method matches and returns success with an
  empty body. Talking goes through `Play` and `Converse`.
- **The pressure-plate entry test.** `OnTrigger` is `FUN_004d765d`. The
  function that decides the party polygon now contains the plate was not
  separated from the sensor poll.
- **The four travel-map dialogs.** Which proc is Krondor, the sewers, the
  northlands, and the goblin camp, and which button calls `Teleport`, was
  not walked.
- **`FUN_004b7c9c`'s fourth argument**, the bool from `DAT_00628d6c+0x32c`.
  It is forwarded into `FUN_004b76ce` and was not named.
