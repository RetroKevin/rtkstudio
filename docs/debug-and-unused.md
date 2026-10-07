# Debug commands, cheats, and content that never ships

What the executable and the authored scripts still contain for
developers, and which items, pictures, and models are present in the
data but never granted or shown. Nothing here writes to the game
install. Keyboard bindings that are not cheats are in
[`controls.md`](controls.md). What the combat cheats change in a fight
is in [`combat.md`](combat.md).

Function names are the stable citations.
`python tools/show_func.py out/decompiled/RtK.c FUN_0050fdbc` re-finds
one. Script lines are from the inflated sources under
`out/plaintext/GameData/`.

---

## 1. The developer flag is compiled in and never set

`DAT_006296e4` is a BSS dword in `RtK.exe`. Every check compares it
with zero. No instruction in `RtK.exe`, `t3dll.dll`, `Rtlib32.dll`,
`kronctrl.dll`, or `RtkMovie.dll` stores to that address, so it stays
0 for a normal launch.

While it is 0, these stay off:

- Command-line chapter, scene, startup script, and the `m` display
  switch (`FUN_0050b639`).
- Semicolon-separated console scripts (`FUN_00453610`). A single
  console line still runs.
- F2 quick save and F3 quick load (`FUN_004188c6` cases `0x1c` and
  `0x1d`). Otherwise the key beeps.
- Ctrl+Q in combat, `Cheat : Get Experience During Force End`
  (`FUN_00478e67`). It also requires this flag.
- Verbose error dialogs. Failures still go to the console log
  (`FUN_00455010`, `FUN_004f6bee`).
- The console commands in the gated column of section 3. Each one
  returns success and does nothing while the flag is 0.

Alt+C, the cheat toggles, and `RPCheat` do not read this flag.

---

## 2. How you reach it

### Console

`RTKRONDOR.INI` key `[Console] Console`. Bit 0 starts the game with
the console already open (`FUN_00453321` from the ini reader). The
shipping ini has `Console=0`.

Alt+C toggles it (command `0x26`, `FUN_00453357`). Enter runs the
line (`FUN_00453610`). F3 while the console is open recalls the
previous line (`FUN_004537bd`). Up/Down with Alt walk history. The
constructor plants the sample line `RunFile "myscript.txt";`.

A line with no semicolon is one console command. A line that contains
the semicolon is only parsed as a script block when the developer
flag is set. Otherwise it is still one command.

### Keys that are not the console

| Key | What it does |
|---|---|
| Alt+C | Toggle the console |
| Ctrl+Shift+C | `FUN_0041a2d0` then `FUN_004fb330`. No log string names it |
| `[` / `]` | Previous / next camera view. Not gated |
| F5 / F6 | Write / read `@bookmark.rtk`, when the game is in adventure mode and not paused. Not gated by the developer flag |
| F2 / F3 | Quick save / quick load. Developer flag, and adventure mode |
| Ctrl+Q | In combat, grant experience on a force-end. Developer flag |

### Command line

`FUN_0050cb1d` feeds each switch into `FUN_0050b639`. The letter is
the first character of the argument. `c`, `k`, `m`, and `s` run only
when the developer flag is set. `l` always runs.

| Switch | Effect |
|---|---|
| `cN` | Startup chapter name `ChapterN` (`FUN_0050c17c`). Empty means the normal boot, `FUN_004366c0(0x19)` |
| `sN` | Scene id formatted `S%.8d`, eight digits. With a chapter, `FUN_004b75f3` jumps there. Without one, the chapter starts at its default scene |
| `k` + text | Run that text as a script at startup (`FUN_0050c459`, same evaluator as the console). A missing trailing `;` is added |
| `m` | Sets the app flag at `+0xd4`. A second letter `w` clears it; any other second letter, including none, sets it. When set, render flips through GDI (`t3dDDrawFlipToGDI` in `FUN_0050bbd2`) |
| `l` | Open a console log next to the exe. Not gated |

`[Dev] NoCD` in the ini is a separate switch. If it is non-zero and a
data directory does not start with `:`, the ini object clears the
field at `+0x74`. It does not set `DAT_006296e4`.

---

## 3. Console commands

Registered in `FUN_0050fdbc`. The name is the word you type. Handlers
that consult the developer flag are marked.

### Cheats and progression

| Command | Handler | Notes |
|---|---|---|
| `RPCheat` | `FUN_0050f06a` | `RPCheat(index)` turns slot `index` on. A second number stores that value instead. Slots are section 4 |
| `AddExperiencePoints` | `FUN_0050cfbe` | Same verb the scripts use for a chapter award |
| `StartChapter` | `FUN_0050e6df` | |
| `Teleport` | `FUN_0050ed63` | |
| `SetParty` | `FUN_0050ecd8` | |
| `LoseGame` | `FUN_0050f106` | |
| `EndGame` | `FUN_0050f14e` | |
| `RollCredits` | `FUN_0050f183` | |
| `DoResting` | `FUN_0050daaa` | |
| `DoPuzzle` | `FUN_0050dafb` | |
| `DoShopping` | `FUN_0050db86` | |
| `LoadGame` | `FUN_0050f4fc` | Gated. No argument quick-loads; an argument is the save name |
| `SaveGame` | `FUN_0050f545` | Gated |
| `EnableMap` | `FUN_0050dcf2` | |
| `EnableRest` | `FUN_0050dd4d` | |
| `EnableSaveButton` | `FUN_0050dd8d` | |
| `EnableGoblinCampMapNode` | `FUN_0050ddca` | |
| `SetVisitedAllNodesForCurrentMap` | `FUN_0050de3f` | Gated |
| `SetJumpToAnyNodeForCurrentMap` | `FUN_0050deb3` | Gated. The map click cheat from [`interactions.md`](interactions.md) |
| `DisplayCurrentMap` | `FUN_0050de07` | |
| `ExitInterface` | `FUN_0050f0d7` | |

### Camera, world, time

| Command | Handler | Notes |
|---|---|---|
| `AutoCameraSwitching` | `FUN_0050d470` | |
| `AutoCameraHeuristics` | `FUN_0050d4b5` | |
| `UserCameraSwitching` | `FUN_0050d4ff` | |
| `ChangeCameraView` | `FUN_0050e744` | |
| `SetCameraLens` | `FUN_0050d8ef` | |
| `UseAutoCameraSwitchingUntilAtFormation` | `FUN_0050e04c` | The symbol is truncated in the decompile; the string is this prefix |
| `SetDirectionalLight` | `FUN_0050e360` | |
| `SetDirectionalLightNormal` | `FUN_0050e3e5` | |
| `UseLightDarkRegions` | `FUN_0050ee17` | |
| `UseHotSpots` | `FUN_0050ee5f` | |
| `SetHotSpotRadiusScale` | `FUN_0050eea7` | |
| `SetHotSpotIntensityScale` | `FUN_0050eeef` | |
| `SetHotSpotThreshold` | `FUN_0050ef37` | |
| `SetHotSpotMax` | `FUN_0050ef7f` | |
| `SetHotSpotOffset` | `FUN_0050efc7` | |
| `SetCostmapZ` | `FUN_0050df27` | |
| `DisableNavCursor` | `FUN_0050df8f` | Gated |
| `GetHour` / `GetDay` / `GetMinute` | `FUN_0050e7d4` / `FUN_0050e782` / `FUN_0050e84a` | |
| `SetTime` | `FUN_0050e8c0` | |
| `IsDay` / `IsNight` | `FUN_0050e9b1` / `FUN_0050e9fd` | |
| `EnableTimeAccounting` | `FUN_0050e954` | |
| `GetCurrentChapterID` / `GetCurrentSceneID` | `FUN_0050e575` / `FUN_0050e5bf` | |
| `LaunchFX` / `TerminateFX` | `FUN_0050e094` / `FUN_0050e2bb` | Both gated. Ten retained effect slots |
| `UseZBufferForPicking` | `FUN_0050f6d9` | |

### Combat display and audio

| Command | Handler | Notes |
|---|---|---|
| `SetCombatSpeed` | `FUN_0050cf70` | Also written by the options screen |
| `EnablePartyStatusQuickView` | `FUN_0050d20c` | |
| `EnableRoundStatusLine` | `FUN_0050d287` | |
| `EnableTurnStatusLine` | `FUN_0050d287` | Same handler |
| `EnableCombatDamageReporting` | `FUN_0050d2f3` | |
| `EnableCombatConditionReporting` | `FUN_0050d329` | |
| `EnableCombatEquipmentReporting` | `FUN_0050d35f` | |
| `EnableCombatExperienceReporting` | `FUN_0050d395` | |
| `EnableCombatTextHeadDagDebug` | `FUN_0050d242` | |
| `PlaySound` | `FUN_0050ea49` | Gated |
| `PlayCinemat` | `FUN_0050d9a3` | Gated |
| `SetAudioTrackVolume` | `FUN_0050f249` | |
| `SetAudioGlobalVolume` | `FUN_0050f2ad` | |
| `SetAudioDebugLevel` | `FUN_0050e68d` | |
| `FadeTrackIn` / `FadeTrackOut` / `ClearTrack` | `FUN_0050f2fa` / `FUN_0050f3a9` / `FUN_0050f458` | |
| `SetMasterVolume` | `FUN_0050f91a` | Gated |
| `SetMusicVolume` | `FUN_0050f980` | Gated |
| `SetGamma` | `FUN_0050f9e8` | Gated |
| `ChooseNextEngine` | `FUN_0050fa48` | Gated |
| `ShowBookOptions` / `SetBookOptions` | `FUN_0050fa80` / `FUN_0050fc8e` | Both gated |
| `ShowSystemSettings` / `WriteSystemSettings` | `FUN_0050f777` / `FUN_0050f721` | Both gated |

Audio channel constants registered next to those commands, not as
verbs: `eAudio_WaveMusic` 0, `eAudio_WaveSFX` 1, `eAudio_WaveCVS` 2,
`eAudio_WaveCombat` 3, `eAudio_WaveAmbient` 4,
`eAudio_WaveInterface` 5.

### Script, log, and trace

| Command | Handler | Notes |
|---|---|---|
| `Evaluate` | `FUN_0050d09f` | |
| `RunFile` | `FUN_0050d15b` | |
| `Trace` | `FUN_0050ce1e` | Gated |
| `MsgBox` / `TextBox` | `FUN_0050cd00` / `FUN_0050cd0a` | |
| `DisplayDocument` | `FUN_0050e609` | |
| `LogToFile` | `FUN_0050f592` | |
| `VerboseReporting` | `FUN_0050f201` | Writes the dword at game `+0x4bc24` |
| `ShowFPS` | `FUN_0050f00f` | |
| `EnableT3DParseStats` | `FUN_0050d437` | |
| `EnableConsoleStrings` / `DisableConsoleStrings` | `FUN_0050d1a0` / `FUN_0050d3cb` | |
| `DisableRandomness` | `FUN_0050e4c3` | |
| `RollD100` | `FUN_0050e4fc` | |
| `GetVersion` | `FUN_0050cf14` | |
| `SetCursorMemory` | `FUN_0050f4aa` | |

`FUN_0051a786` also publishes log-channel constants. The float is the
channel mask value: `DebugWarning` 2, `DebugInfo` 4, `DebugTest` 8,
`RolePlay` 16, `T3D` 32, `Loading` 64, `Movement` 128, `Audio` 256,
`KEvent` 512, `KMethod` 1024, `KTrace` 2048, `IFace` 4096.

---

## 4. The roleplay cheat list

`FUN_0050a69d` fills a text menu titled `Roleplay Cheat Codes`. The
same slots are what `RPCheat` writes, in this order. The menu string
`No Mgc Queue Cheaks` is spelled that way in the binary. The combat
log uses a different sentence, listed in [`combat.md`](combat.md)
section 15.

| Index | Menu label |
|---:|---|
| 0 | Ignore Damage |
| 1 | Mgc Quick Always |
| 2 | Mgc Quick Never |
| 3 | Mgc Slow Always |
| 4 | Mgc Slow Never |
| 5 | Mgc Resist All |
| 6 | Mgc Resist None |
| 7 | God Mode-Jam |
| 8 | God Mode-Jaz |
| 9 | God Mode-Wil |
| 10 | God Mode-Sol |
| 11 | God Mode-Ken |
| 12 | God Mode-Good |
| 13 | God Mode-Bad |
| 14 | Ignore SpellPts |
| 15 | Win Initiative |
| 16 | No Enemy AI |
| 17 | Show All Spells |
| 18 | Demo Dice |
| 19 | Kill Topgun |
| 20 | Kill Topgun Spells |
| 21 | No Mgc Space Checks |
| 22 | No Mgc Queue Cheaks |
| 23 | Revive Enemies |
| 24 | Revive Full Health |
| 25 | Min Magic Duration |
| 26 | Mgc Keep OnRelease |
| 27 | Items Assessed |
| 28 | Ctrl Q |
| 29 | Experience |
| 30 | Fate Condition Off |
| 31 | Experience for CtrlQ |

`Cheat : Demo Damage` is a combat-log line. It is not its own slot.
`Demo Dice` is the slot.

The menu is posted from an MFC command handler: button `1048` calls
`FUN_00500ff5`. Button `1049` opens `Roleplay Test Option`
(`FUN_0050ab7b`), seven forced magic outcomes:

| Index | Label |
|---:|---|
| 0 | 0 Mgc - Normal |
| 1 | 1 Mgc - Q Failed |
| 2 | 2 Mgc - Q Resist |
| 3 | 3 Mgc - Q Worked |
| 4 | 4 Mgc - S Failed |
| 5 | 5 Mgc - S Resist |
| 6 | 6 Mgc - S Worked |

Other buttons on that same message map: `1144` toggles a Store
caption (`FUN_00500e2b`), `1146` toggles `SC On` / `SC Off`
(`FUN_00500ee3`), `1145` returns the shell to state 6
(`FUN_005090e6`). State 6 is the root of the combat test shell below.
No shipping key posts `1048`. The way in that does not need that
dialog is `RPCheat` on the console.

`ToggleCheatMode` on a character is a different mechanism. It is a
script method (`FUN_0051a913` name `ToggleCheatMode`), used by the
chapters on specific actors: the chapter 6 and 10 bears, chapter 5
air elementals and the monster, chapter 7 townsfolk (argument `2`)
and the vampire, chapter 9 tentacles, ghouls, and the lich. It is
not the player cheat list.

---

## 5. The combat test shell

A state machine in `DAT_005fe548` drives text menus inside the window
the game subclasses. The subclass failure log is `Attempt to subclass
TopGun's window failed.` The shell can give weapons, start a test
fight, and print pathing numbers.

Strings that belong to it:

- `Test Menu`, `Test Goblin`, `Test Zombie`, `Test Node`
- `--- Modal Test Combat Started ---`
- `--- Modeless Test Combat Started ---`
- `--- Test Popup Combat Started ---`
- Menus titled `RolePlay mode`, `Combat Configuration`, `Turn Option`,
  `GameModes`, `Inventory Option`, `Select Item to Use`, `Add Group`,
  `Select Character`, `Attacker : <NOT SELECTED>`, `Target : <NOT SELECTED>`
- Path readout: `Best Path`, `Full Move`, `Geo. Dist`, `Touch Range`,
  `Line of Sight`, `Def rel to Att`, `Att rel to Def`

`Test Goblin` and `Test Zombie` are not rows in `Chars.tbl`. They
exist only as those menu strings. The weapon picker inside the shell
lists the ordinary catalog grades (`Dagger_poor` through
`Longbow_poor`, armor, rings, potions, books, wands, scrolls). Those
are the same items the game already grants. They are not a second
item list.

`grid.adf` / `GRID_ACD` is loaded by the costmap drawer
(`FUN_00421af1`'s caller at `RtK.c` around the `s_grid_adf_005ce008`
load). `HOTSPOT.ADF`, `spellgen.adf`, and `marker.spr` are the same
kind of engine prop: the hotspot pass, the spell generator, and the
combat marker. `poly1.spr` is the polygon-placement debug sprite.
The engine logs `Can't open sprite file poly1.spr` when that mode
wants it. It is not a scene overlay. See
[`ovx-format.md`](ovx-format.md).

---

## 6. Levels

There is no separate test map in `Worlds/`. Chapter 0 is a real
chapter (`Chapter0.def` from `RtkGame.def`). Later chapters read its
flags (`bYusufKilled`, `bHelpedWhisperer`,
`bSweatshopChildrenReleased`, the generic chest and combat counters).
It is the cross-chapter state object, and it also owns early scenes.

The procedural rooms (chapters 0, 1, 2, and 3) document
`nRoomType` in the script:

| Value | Comment in the source | What the script does |
|---:|---|---|
| -1 | Null, for debugging | `MsgBox(" ERROR - No RoomType defined")` |
| 0 | empty | `MsgBox("Room is empty")`, then shows the rat groups |
| 1 | random | Treasure / combat roll |
| 2 | custom, one per room | The authored room |

A door that never sets `nRoomType` therefore hits the debug message.
That message is still in the shipping script.

`PugChapt%d.ktx` is the narrative plate for a chapter
(`RtK.c` string at `0x5d4b0c`). `PugChapt0.ktx` through
`PugChapt10.ktx` are that sequence. The archive spells some of them
with a lowercase `p`. Windows treats those as the same file.

---

## 7. Easter eggs that are wired up

### Fountain of youth

Chapter 2, scene `S00020032`, marked in the source as the
`FOUNTAIN OF YOUTH` block. The touch sensor `FountainOfYouth` takes
whatever `Gold` is in the fountain container's inventory, removes it,
and if `nNumTimesUsedFountainOfYouth` is still under 5, awards the
`FoutainOfYouth` event. The event name is spelled that way in
`ChapterEvents.tbl`: 300, 300, 300 for the first three party slots.
The gold is consumed either way. The award stops after five uses.

### PyroTechnix tombstones

Chapter 7, scene `S00060031`, comment `EASTER EGG #2`. After the
boss vampire is dead, four pressure plates around the coffin
(`EasterEggRight`, `EasterEggTop`, `EasterEggLeft`,
`EasterEggBottom`) arm. `TombEasterEggTimer` is 30 seconds. Running
the four plates in order before the timer fires plays `TrumpetFlare`.
Entering the graveyard scene `S00060009` then sets
`nWhichTombstonesToDisplay`: 1 for counterclockwise, 2 for clockwise,
0 if the run did not complete.

Each of the twelve tombstones is a touch plate that opens a `.ktx`.
Column 0 is the normal inscription. Column 1 is the counterclockwise
run. Column 2 is the clockwise run.

| Stone | Normal | Counterclockwise | Clockwise |
|---:|---|---|---|
| 1 | Fantasy1 | Elfers | Conaway |
| 2 | Feldon | MaryJo | Ward |
| 3 | Fantasy3 | Mills | Heath |
| 4 | Fantasy4 | Kraack | Bishop |
| 5 | Fantasy5 | Bartsch | Dennis |
| 6 | Fantasy6 | Miller | BillMiller |
| 7 | Fantasy7 | Wiggins | Wujcik |
| 8 | Fantasy8 | Meuter | DaveMiller |
| 9 | Fantasy9 | Gordos | Jantzen |
| 10 | Fantasy10 | Brown | Mush |
| 11 | Fantasy11 | Sinjin | SpaceCombat |
| 12 | Fantasy12 | Dietrich | Ambrus |

`SpaceCombat.ktx` is one of those clockwise inscriptions, not a
hidden game mode.

### Babies

Not unused. `CharacterDef Baby` uses `Model : Baby` (`c8baby.adf`).
Chapter 5 puts the catalog item `Baby` ("Two Infant Babies.",
encumbrance 24, `UniqueID` 999) into James's bag and hides the
`Baby` group. `BabyCrib` is a chest model; the crib character holds
the Nightstone. A commented line in chapter 10 would also have given
the wife a `Baby`. It is commented out. The chapter 5 path is live.

### Maria Maria

A second model row on Maria Royos's mesh, palette `z0Palette.bmp`.
`CharacterDef Maria Maria` copies Maria's display name and is placed
in chapters 2 and 10. It is a palette variant that does get used.

---

## 8. Items in the catalog that nothing grants

`MagicInvItem.txt` has 464 rows. Every name was matched as a whole
token against the other inflated scripts, the shops, and
`Chars.tbl`. Creature attack rows are excluded below: their names are
compiled into `RtK.exe` (`Claws Sewer Monster` and the claws, teeth,
stinger, touch, and lich-staff rows that alias it). The disguised
poison rings (`PrandurPoison`, `FreePoison`, and the Eagle, Wind, and
Mage poison rings) are real shop stock. The comment after the item
name made an earlier scan look like they were unused. They are not.

These names appear in the catalog and nowhere else. No shop row, no
character inventory, no `PutItemInInventory`, no door
`Model_Type` that asks for them:

| Item | What the row says | Why it looks abandoned |
|---|---|---|
| `Fake Diamond (dissolved)` | Gem, paste diamond, price 1 | The intact diamond, emerald, and ruby are the chapter 3 stones. The dissolved ruby is loot on `CharacterDef Sewer Monster` (chapter 3, quantity `1, 3, 2`). The dissolved diamond and emerald have no owner |
| `Fake Emerald (Dissolved)` | Same, for the emerald | Same |
| `Skeletal hand` | Key, subcategory `SkeletonKey`, use text "Opens BPT Door" | No character carries it, and no door's `Model_Type` asks for `SkeletonKey`. The other seven keys are the ones [`inventory.md`](inventory.md) section 10 actually matches |
| `GG Book 1` | Book, price 0, weight 1, no effect. Unassessed name points at Path of Flames | Four placeholder grimoire rows. Assessed name and description are the strings `GG Book 1` through `GG Book 4` |
| `GG Book 2` | same | |
| `GG Book 3` | same | |
| `GG Book 4` | same | |

`UniqueID` 999 is the Baby row, and that one is granted. It is not
an unused id.

---

## 9. Pictures and models nothing asks for

Checked case-insensitively against the inflated scripts and against
the strings in `RtK.exe`. A file that only appears inside a `//`
comment is listed as authored and then disabled.

### Text plates in `Ktx.t3d` with no live reference

| File | Notes |
|---|---|
| `Test.ktx` | The name is the whole content of the clue. No script and no exe string |
| `princemoney.ktx` | |
| `knutedoor.ktx` | |
| `lucaskey.ktx` | |
| `SwordStone.ktx` | |
| `whisp_t012.ktx`, `whisp_t013.ktx` | `whisp_t011.ktx` is shown in chapters 1 and 2. `whisp_t014.ktx` is only in a commented `TextBox` |
| `JorathDeal1.ktx`, `JorathDeal2.ktx`, `JorathDeal3.ktx` | |
| `KendaricCreditor1.ktx` through `KendaricCreditor4.ktx` | |
| `NightHawkNote.ktx`, `NightHawkNote1.ktx`, `NightHawkNoteBurned.ktx` | |
| `RtkCredits02.ktx`, `RtkCredits03.ktx`, `RtkCredits04.ktx` | The credits object defaults to `RtkCredits01.ktx` only (`FUN_00432153`). No format string builds the 02–04 names |

`YorricsSkull.ktx` is in chapter 7 as `//TextBox ("YorricsSkull.ktx");`.
The plate is in the archive. The call is commented out.
`Jamesburning.ktx` is live (`TextBox("Jamesburning.ktx")` in chapter
1). The chapter 1 timer of the same name is a different object.

`PugChapt0.ktx` through `PugChapt10.ktx` are used, via `PugChapt%d.ktx`.

### Resource-archive leftovers

`sSpikeCursorTest`, `qSpikeCursor_Test_Norm`, and
`qSpikeCursor_Test_Hot` are in `RTKRES`. Neither the scripts nor
`RtK.exe` name them. A screen could still pull them by numeric id
from inside the archive. Nothing in the authored text does.

`bInvDummy` and the `r_*_Dummy` bitmaps are named like placeholders.
The dummy digit strips are the sort of art a font or a counter uses
by id, so they are not on the unused list. `bInvDummy` is only a
name match. It was not traced to a widget.

### Models

Every name in `Models.def` is referenced from a character or a
chapter. The `.adf` files that look unused at a glance
(`dagger.adf`, the `*CHead.adf` heads, `c8baby.adf`, `Container2d.adf`)
are named from `Models.def` or from the exe, once case is ignored.
`Q1FthRowland.adf` is the Father Roweland mesh under a shorter
spelling. It is the model that row uses.

The debug-shaped meshes that *are* loaded by the exe, so they are
not dead files: `grid.adf`, `HOTSPOT.ADF`, `spellgen.adf`,
`marker.spr` / `MK_COMBATMARKER_ACD`.

---

## 10. What this pass did not prove

- Which MFC menu or toolbar posts command `1048`. The handler and the
  cheat strings are in the exe. The click that opens that dialog in
  a normal play session was not found. `RPCheat` does not need it.
- Whether `sSpikeCursorTest` is reachable by resource id from a
  screen script stored inside `RTKRES`. It is not reachable by name.
- A full orphan walk of all 5,089 bitmaps. Sprites point at bitmaps
  by id, so a bitmap with no name reference can still be on a live
  screen. Section 9 is the set whose names are debug-shaped or whose
  `.ktx` never appears.
- What `FUN_004fb330` (Ctrl+Shift+C) draws. The call is there. It has
  no log string.
