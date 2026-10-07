# Dialog

How a conversation is stored, how the engine plays it, and how to change
or add one. This is the chapter-script conversation, not the window
chrome. Buttons, sheets, and the bubble pictures are
[`ui.md`](ui.md). The click that starts a talk is
[`interactions.md`](interactions.md). Body motion and the mouth clock are
[`animations.md`](animations.md) and [`sprite-format.md`](sprite-format.md).
Books, letters, and Pug's narration are `.ktx` files
([`misc-formats.md`](misc-formats.md), `tools/rtktext.py`).

Nothing here writes the game install. Counts are from
`docs/voice/lines.jsonl`, produced by `tools/survey_voice.py` against the
inflated chapter sources. Function names are the stable citations;
`python tools/show_func.py out/decompiled/RtK.c FUN_004d08b2` prints a
body. `RtK.c` line numbers move every time the decompile is regenerated.

---

## 1. Three different "dialogs"

| What you see | Where it is authored | What you can change |
|---|---|---|
| A spoken scene: choices, a performance, a journal line | `ConversationDef` blocks in `GameData/ChapterN/ChapterN.def` | The whole tree. This note |
| Words on a page or a caption (`TextBox("cellsbelow.ktx")`) | `Ktx/*.ktx`, plain text with `\\p` `\\s` `\\l` `\\c` `\\r` `\\w` | The text. There is no speaker and no lip sync |
| A window: inventory, shop, lock, the choice bubble's frame | Sprite resources and `Win_CreateDlg` in `RtK.exe` | The art, via the modkit. The procedures are compiled |

A voiced conversation does not store the spoken words. `MenuText` is the
choice label. `JournalText` is the journal summary. The wav is a mix.
A few wavs carry a Sound Forge `LIST/INFO` block; those tags are a date,
an engineer, and the software, not the actor and not the line.

---

## 2. The shape of a conversation

Chapters 0 through 10 hold **1,379** `ConversationDef` blocks, each one
nested in a `SceneDef`. A block belongs to the scene whose header sits
above it at a smaller indent. `tools/rtkdef.py` parses the file;
`ConversationDef` is one of its block kinds.

Every node has the same fields. The name decides the role.

| Name | Count | Role |
|---|---|---|
| `…ROOT` | 332 | A menu. `PotentialDest` lists the children. `MenuText` is empty. No wav |
| `…FORM` | 172 | A choice row. `MenuText` is the label. No wav of its own. `OnEnd` is the consequence, or `PotentialDest` names the line that plays |
| `TK` + digits + a letter | 875 | A performance. The name is also the sound def and the track stem. Suffix `M` is the common take (821 of the audio defs). `A` `B` `C` `D` `E` `Z` are other takes of the same number |

`PotentialCombats` is on every node. Its loader, `FUN_0046bb2f`, returns
without storing anything. All 1,379 shipped values are empty. A fight
starts from `OnEnd` with `GetCombat("…").Play()`, not from this field.

A small tree from chapter 1, scene of Talia's death. `C10110ROOT` is the
menu. Its children are the lines.

```
ConversationDef C10110ROOT
    PotentialDest : TK0110M, TK0115M
    EnterNavMode : 0

ConversationDef TK0110M
    MenuText : Talia dying
    JournalText : Talia's dying words
    AddToJournal : 1
    EnterNavMode : 1
    RunToFormations : 1
```

`TK0109M` is the other shape: one child, empty `MenuText`, so it never
becomes a menu row. Playing `C10109ROOT` (empty `PotentialDest` of just
`TK0109M`) plays that line and then, in `OnEnd`, teleports and starts a
combat.

### Fields

The loader's property table is in `RtK.exe` at file offset `0x1dcb38`.
Each record is a name, a handler, and a zero. Handlers write the object
that `DAT_00629ca0` points at during the load.

| Field | Handler | Stored at | What it does |
|---|---|---|---|
| `MenuText` | `FUN_0046b976` | string at `+0xc` | The choice label. The bubble reads this and no other string |
| `JournalText` | `FUN_0046b99a` | string at `+0x10` | Passed to the journal when `AddToJournal` is 1 |
| `DisableWhenPlayed` | `FUN_0046b9be` | `+0x18` | Stored. 22 nodes set it to 1. The menu walker does not read it; shipped scripts retire a line with `GetNumTimesEntered` and `HasOccured` |
| `AddToJournal` | `FUN_0046b9dd` | `+0x1c` | 121 nodes set it to 1. On the way out, `FUN_00437f9f` records the node name and `JournalText` |
| `EnterNavMode` | `FUN_0046b9fc` | `+0x20` | 1 returns the player to walking when the node ends. 0 runs the same node again so its children play. 602 nodes are 1, 777 are 0. Roots are almost all 0 (318 of 332) |
| `IgnoreFormations` | `FUN_0046ba1b` | `+0x118` | 1 skips the walk to the marks. The approach phase treats the cast as already there |
| `RunToFormations` | `FUN_0046ba3d` | `+0x11c` | Passed through when formations are not ignored. 0 walks (`FUN_004f012a`), nonzero runs (`FUN_004f0159`) |
| `IgnoreOtherGroupMembersOnMoveToFormation` | `FUN_0046ba5f` | `+0x120` | Forwarded as the third argument of that walk or run |
| `PotentialDest` | `FUN_0046ba81` | name list at `+0x24`, count at `+0x2c` | Comma-separated child names. Resolved to objects by `FUN_004cf9e8` |
| `UseCameras` | `FUN_0046bb39` | name list at `+0x74` | View names, for example `Vw1, Vw4, Vw8, Vw7`. Often empty. The function that applies the list was not walked |
| `Groups` | `FUN_0046bc6f` → `FUN_0046bbe7` | name list at `+0x4c`, count at `+0x54` | Who is in the shot. `FUN_004d00f9` looks each name up and pulls that group in |
| `GroupMemberConversationLinks` | `FUN_0046bf3b` → `FUN_0046be7d` | array at `+0xec`, count at `+0x10c` | One row per speaker. See below |
| `Formation` | `FUN_0046bc86` | per group | `member : x, y, z, facing`. Facing is degrees, same as a combat formation |
| `TimelinePlaySoundEvents` | `FUN_0046be66` → `FUN_0046bda8` | records at `+0xf0` | A row is an integer and a name (format string `i q`). The shipped blocks that were sampled are empty |
| `PotentialCombats` | `FUN_0046bb2f` | nowhere | Accepted and discarded |

A link row is `slot, group, member, character`, format string `i q q q`.
The slot must equal the row index or the loader logs
`LinksReader1 - INVALID nIndex`. `FUN_004cf765` uses the group and the
member to find the actor. `character` is the performance name, the same
namespace as a `.trx` speaker, and it can differ from the member:
chapter 1 `TK0109M` lists member `CaptainGarruth_m0` and character
`William`.

```
GroupMemberConversationLinks 4
    0, Party, James_m0, James
    1, Party, Jazhara_m0, Jazhara
    2, DyingTalia, Talia_m0, Talia
    3, Party, William_m0, William
```

The count after the keyword is the number of rows. Zero is legal on a
root.

---

## 3. How a node plays

The conversation manager is the object at `DAT_00628d6c+0x370`.
`FUN_004d08b2` is its step. `*manager` is the state.

`Play` on a conversation is `FUN_004d0398`. It calls the manager with
that node. `Group.Converse()` does the same with the pointer stored at
`group+0x54+0x70`. `Group.ChangeConversationNode("C10110ROOT")` writes
that pointer (`FUN_004d6567`'s `ChangeConversationNode` arm). An empty
string clears it. `Group.SpeakTo()` is registered and returns without
doing anything. No chapter script calls it.

### Getting in

Two doors.

A click uses the pointer `ChangeConversationNode` stored. Each frame
`FUN_004bdeab` walks that node's children and calls `OnCanPlay`. If any
child returns 1, the group's talk flag goes on and the cursor can become
the talk cursor ([`interactions.md`](interactions.md) §4–5). The click
then enters `FUN_004d08b2` on that node.

A script does not need the cursor:

```
S00020007.GetConversation("C10171ROOT").Play();
Garruth.ChangeConversationNode("C10146ROOT");
```

`GetConversation` is `FUN_004bdff7` on the scene. `HasOccured` is true
when the enter count at `+0x104` is greater than 0. `GetNumTimesEntered`
returns that count. Both are methods on the conversation, also registered
from `FUN_004d0398`.

### `OnCanPlay`

The call is the script event dispatcher `FUN_004b9fce`. A missing event
returns **3**. A `return TRUE` / `return FALSE` comes back as **1** / **0**.
A `return 2` comes back as the integer **2**.

| Return | What the manager does |
|---|---|
| 1 | The child is a menu row. Also the value that lights the talk cursor |
| 2 | Not a row. The menu built so far is dropped and this child is entered immediately. Earlier siblings are not offered |
| 0 or 3 | Skipped. 3 is what a missing `OnCanPlay` produces |

Of the 1,379 nodes, `OnCanPlay` is conditional on 964, always-true on
159, always-false on 2, and absent on 254. Almost all of the absent ones
are roots (245). A root is entered with `Play` and does not need
`OnCanPlay`. A child does. Nine voiced nodes have no `OnCanPlay`; as
children they are skipped.

One child returning 1 plays immediately, with no bubble. `TK0109M` is
that case, which is why its `MenuText` can be empty. Two or more
children returning 1 open the choice bubble. The scan is in order of
`PotentialDest`, and a 2 stops it.

Chapter 7 `TK1005M` uses 2 for real. The first visit returns true. Later
visits return 2 while a drink-and-room condition holds, so the line
plays itself instead of sitting in the menu, and false once that
condition is over.

### The five states

**1, enter.** If the game is in adventure mode (`+0x4bc2c == 1`), switch
to conversation mode 2 and call the script event `Display`. `Display`
returning anything but 3 means the node is showing something; the
manager stops there. A missing `Display` returns 3, which means "nothing
to show". The manager then walks `PotentialDest`.

Zero playable children: back to adventure mode, and the camera cleanup
`FUN_004bdeab` / `FUN_004c0f13`. One child: state 3 on that child. Two or
more: `FUN_004366c0(0x10)` and `FUN_0053a867`, then state 2.

**2, waiting for a choice.** The step does nothing. The bubble's click
(`FUN_0053af43` on mouse-up, and `FUN_0053a8ff` on the dialog message)
calls `FUN_004d0830`, which stores the chosen child and sets state 3,
then `FUN_0053b04a` closes the bubble.

**3, approach.** First tick places the cast (`FUN_004cf1a6`,
`FUN_004cf765`, `FUN_004cffec`, `FUN_004d00f9`) and, unless formations
are ignored, walks or runs them to the marks. Later ticks wait until the
cast has arrived (`FUN_004cfb86`) or three seconds have passed
(`DAT_0062a784`, set to world time plus 3000). Then state 4.

**4, the performance.** Once `+0xe0` is 1, call `OnStart`, then
`FUN_004cf538`, which binds the body track (`FUN_0052b981`) and starts
the clock (`FUN_0052bd3f`). Each advanced frame calls a script event
named `Frame` plus the frame number: `Event Frame30 ()` in chapter 9
starts six skeleton groups walking. A missing frame event returns 3 and
is ignored. `FUN_004d0159` ends the performance when the clock reaches
its done state (`DAT_0066c248 == 4`). Esc in conversation mode is
`FUN_004d0858`, and it fires `OnCancel` only in this state, after
`OnStart` has run.

**5, leave.** Increment `+0x104`. If `AddToJournal` is 1, write the
journal entry. If `EnterNavMode` is 1, switch back to adventure mode.
Call `OnEnd`. Then either clean up and stop (`EnterNavMode` 1) or call
the manager again on this same node (`EnterNavMode` 0), which is how a
line falls through into its own children.

`OnEnd` is ordinary script. It may `Play` another conversation,
`Teleport`, `ChangeConversationNode`, start a combat, arm a plate, or
`TextBox` a `.ktx`. 580 nodes have an `OnEnd`. A root that was only a
menu parent never reaches state 5, so its `OnEnd` does not run on the
way in. `Display` already skipped it.

`Pause` and `Resume` are also conversation methods (`FUN_004d0398`).
They call `FUN_0052c86f` / `FUN_0052c8c8`.

---

## 4. The choice bubble

`FUN_0053a867` builds dialog `0x1b38` with procedure `FUN_0053a8ff`.
The background comes from the second size table at `0x60e9c0` (the same
four sprites as the other bubbles in [`ui.md`](ui.md) §6). The row
count picks the sprite.

On show, the procedure divides the bubble's text rectangle into one
band per choice and writes `MenuText` (`+0xc`) into `sConvChoice*`.
An empty string logs `ERROR: Blank conversation string` and stops, so
every row of a real menu needs a label. 270 voiced nodes have an empty
`MenuText`; they are the auto-played single children, and they never
reach this procedure.

Thirteen or more choices logs `ERROR: Can't handle %d choices`. The
count check allows 12. The authored row art is `sConvChoice1` through
`sConvChoice11`, so a menu of 11 is the size the pictures were drawn
for.

Hover and click are `FUN_0053af43`. The chosen index is
`DAT_0060e898`.

---

## 5. The performance files

A voiced node is four names that match, case-insensitively.

| Piece | Where | Join |
|---|---|---|
| The node | `ConversationDef TK0071M` in the chapter | the name |
| The sound | `AudioGroup Conversation` in `RtkGame.def` | `TK0071M, chapter0\0071mix.wav, , 2, 4, 1, 0, 1, 0, 1.000000, 0` |
| The body | `Tracks/TK0071M.trk`, registered in `ConversationTracks.tbl` | `tk0071m.trk, TK0071MDUMMY01_TRACKDEF, FRAME_TK0071M, FRAME_TK_FROM, FRAME_TK_TO` |
| The mouth and the gestures | `Tracks/TK0071M.trx` | first line is the wav basename, `0071mix.wav` |

`FUN_004cf1a6` is the gate. It compares the first two characters at
`+0x88` with the literal `tk`. On a match it loads the `.trx` (that
extension sits in the binary next to `tk`) and the body track.
`FUN_0052bd3f` then looks the node's name up in the audio dictionary and
plays that sound (`FUN_004e5f37`). One wav for the whole node. The mix
is not one sentence.

The track is not bound to a person. `ConversationTracks.tbl` lists every
loose take under `ConversationGroup All`, and `FUN_0052b981` stamps the
7-character stem onto whichever humanoid is speaking. The file names in
the table are lowercase. The `DUMMY01_TRACKDEF` tag is uppercase;
`FUN_00589520` folds a tag to uppercase before the dictionary lookup.
The rig has to be the 17-joint humanoid. A naga is not.

`FUN_0052be95` walks the `.trx` against world time and drives the face
sprites. The file is plain latin-1:

```
0005mix.wav
  21  369
   0   1
  ...            one "frame, viseme" pair per viseme row
14
  1    0   28    phrase rows; not a reliable speaker index
...
  0   0
  -1            gesture keys, per speaker, each slice ending in -1
0 1
0 James
```

`tools/survey_voice.py` parses all 917 and records the layout in
`docs/voice/index.json` under `trx_layout`. `.trm` is the same pairs
without the wav line. The integer that picks a face bitmap was not
recovered as a named table ([`animations.md`](animations.md) §4).

There are 73 conversation audio defs with no `ConversationDef` (Pug's
chapter narration is not in that count; it is `PugChapN` plus
`Ktx/PugChaptN.ktx`). `docs/voice/orphans.jsonl` lists them. A scene can
still play one of those with `GetAudio("label").Play()` if an
`AudioInstance` on the scene points at it. That path does not run the
conversation manager, the formation, or the lip sync.

---

## 6. How to edit

Edits go through a mod project. The install is not the file you change.
`out/plaintext/GameData/` is the inflated text, useful to read and to
diff, and a build does not read it back. The viewer re-wraps a `.def`,
`.tbl`, or `.rtk` in its PyroTechnix gzip envelope when you save. See
[`modkit.md`](modkit.md).

```powershell
python tools/viewer.py --mod mods/example
```

The asset keys are `file/GameData/Chapter1/Chapter1.def`,
`file/GameData/RtkGame.def`, and
`file/GameData/ConversationTracks.tbl`. A loose override is written into
the build even when the install has no such file, which is how a new
wav or a new track arrives. **Duplicate as new** on a `.trk` creates
`file/Tracks/{stem}.trk`. A `.trx` is not rewritten by the track editor.

The chapter sources are latin-1. A comment is `//`. A script event is
`Event Name ()` … `<EndEvent>`. `TRUE` and `FALSE` are the booleans.
`return 2` is the integer, not a boolean.

### Change a line that already exists

| You want | Edit |
|---|---|
| The words on the choice | `MenuText` on that child. Keep it non-empty if two or more siblings can return 1 |
| The journal entry | `JournalText`, and `AddToJournal : 1` |
| Whether it is offered | `OnCanPlay`. Return true, false, or 2. Do not delete it on a child you still want in the menu |
| What it does afterwards | `OnEnd`. `EnterNavMode : 0` if the children should play next; `: 1` if this node is the end and `OnEnd` starts whatever follows |
| Who stands where | `Groups`, the link rows, and `Formation` |
| The camera at the start | `OnStart`, usually a `Teleport` to a view. `UseCameras` is the other field; its consumer was not walked |
| Something mid-line | `Event FrameN ()`, N the frame index the performance clock reports |
| Esc | `Event OnCancel ()`. It runs only after the performance has started |

Retiring a line is a condition, not a delete. The usual test is
`GetNumTimesEntered() == 0` or `HasOccured()` on this node or on another:

```
Object ScribeTalk = S00020007.GetConversation("TK0175M");
if (ScribeTalk.GetNumTimesEntered() > 0)
    { Return TRUE; }
else
    { Return FALSE; }
```

`DisableWhenPlayed : 1` is stored and is not what the menu consults.

### Add a choice to a menu that already exists

1. Pick the parent (`…ROOT`, or a line whose `EnterNavMode` is 0).
2. Add a `ConversationDef` in the **same scene**. A `FORM` name is the
   shipped pattern for a row that has no wav. A `TK` name is the pattern
   for a row that plays a performance.
3. Put the new name in the parent's `PotentialDest`, comma-separated.
   Order is the menu order, and it is the order a `return 2` is tested.
4. Give the child a non-empty `MenuText` and an `OnCanPlay` that returns
   true when the row should appear.
5. Put the consequence in the child's `OnEnd`, or point its
   `PotentialDest` at the performance and set `EnterNavMode` so the
   follow-on actually runs.
6. If the NPC should offer this menu when clicked, some `OnEnter` or
   earlier `OnEnd` must call `Group.ChangeConversationNode("…ROOT")`.
   Clearing it with `""` takes the talk cursor away.

No new audio is required for a `FORM` whose `OnEnd` only sets flags,
shows a `.ktx`, or starts a combat.

### Add a voiced line

The node name, the audio def, the track stem, and the `.trx` basename
are one identifier. Use seven characters for the stem (`TK` + four
digits + a letter). The binder copies seven characters onto the rig.

1. The `ConversationDef`, as above, with links for every speaker and a
   formation if they should move.
2. A row in `RtkGame.def` under `AudioGroup Conversation`. Copy the tail
   from a neighbour; every shipped conversation row ends
   `, , 2, 4, 1, 0, 1, 0, 1.000000, 0`. Point the path at
   `chapterN\yourmix.wav`.
3. The wav, beside the other chapter mixes: mono, and the shipped
   conversation takes are MS ADPCM, 22050 Hz, 4-bit. A PCM wav can be
   dropped in as an override; matching the neighbours is the safe choice.
4. `Tracks/<stem>.trk` on the 17-joint humanoid, and a row in
   `ConversationTracks.tbl`:
   `tk0123m.trk, TK0123MDUMMY01_TRACKDEF, FRAME_TK0123M, FRAME_TK_FROM, FRAME_TK_TO`.
5. `Tracks/<stem>.trx` whose first line is the wav's basename, not the
   folder. Speaker names must be the character names the links use.
   Without a `.trx` the body can still be registered; the mouth clock
   and the per-speaker gesture slices will not be there.

An `AudioInstance` on the scene is a different hook. It lets script call
`GetAudio("label").Play()`. It does not cast the shot or play the track.
The performance path uses the node's name, not the instance label.

### Add a caption instead of a performance

`TextBox("cellsbelow.ktx")` from `OnEnd` opens a `.ktx`. That file is
the one place the written words live. Markup is `\\p` between pages,
`\\s` between a heading and a body, `\\l` `\\c` `\\r` for alignment,
`\\wN:` for dwell. Bytes above `0x7f` are shown as spaces. Pug's chapter
voice is `PugChapN` in the conversation audio group plus
`Ktx/PugChaptN.ktx`, and it is not a `ConversationDef`.

---

## 7. Open

- **`DisableWhenPlayed`.** Written to `+0x18` by `FUN_0046b9be`. Not read
  by `FUN_004d08b2` or by the cursor pass `FUN_004bdeab`. The scripts
  that retire a line do it in `OnCanPlay`.
- **The bytes at `+0x88`.** `FUN_004cf1a6` requires them to start with
  `tk`. The def header and the audio def are written `TK…`, and the
  track table lists lowercase filenames. The scratch buffer the
  constructor copies into `+0x88` was not recovered line by line. The
  join itself is measured: all 875 voiced nodes match an audio def by
  that name.
- **`UseCameras`.** Parsed into the list at `+0x74`. Which call switches
  the view to those names was not walked. Shipped `OnStart` blocks that
  need a camera call `Teleport` themselves.
- **`TimelinePlaySoundEvents`.** The row format is an integer and a
  name. A non-empty block was not found in the sample, so what the
  integer counts was not checked against a live row.
- **Phrase rows in a `.trx`.** Column 0 is inside `1..speaker count` on
  some files and outside it on others, so it is not a speaker index.
  They are stored raw in `docs/voice/trx.jsonl`.
- **The viseme-to-bitmap table.** The `.trx` times the mouth. Which
  integer selects which face sprite was not recovered.
