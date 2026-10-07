# Enemy encounters

Who is placed in a fight, the sheet they spawn with, and the experience
that fight pays. Hit, damage, armor, and spell math stay in
[`combat.md`](combat.md). This is the runtime in `RtK.exe` plus the
authored text in `out/plaintext/GameData/Chars.tbl`, `ChapterEvents.tbl`,
and the per-chapter `*.def` files.

Function names are the stable citations. `RtK.c` line numbers move every
time the decompile is regenerated;
`python tools/show_func.py out/decompiled/RtK.c FUN_004c786c` re-finds one.
The experience split below was checked against the shipping instructions
where the decompiler dropped the divide.

---

## 1. What an encounter is

A fight is a `CombatDef` on a scene. It names `GroupDef`s that are
already placed in that scene. Each group's `Members` list binds a
`CharacterDef` from `Chars.tbl` to a scene instance (`Thug #1, Thug1_m0`).
The same 3D actors walk the scene and then stand in the formation.

`GoodGuys : 0` is the enemy side. The chapter's `GroupDef Party` is
`GoodGuys : 1`. At runtime the side lives in the short at actor `+0xcc`,
returned by `FUN_004ab820` (vtable `+0x104`). Side 0 is the side whose
death feeds the kill-experience pool. Side 1 is the side `FUN_00475d29`
name-checks against James, Jazhara, William, Solon, and Kendaric.

The eleven chapter scripts hold 538 `CombatDef`s:

| Ch | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fights | 94 | 97 | 96 | 106 | 2 | 63 | 2 | 12 | 3 | 55 | 8 |

Chapters 4, 6, and 8 are almost entirely one scripted battle each. The
early chapters are full of small room fights.

Entering real combat is still `FUN_00501387`, as in combat.md section 1.
`SetCombatAIMode` is how a script turns a placed enemy into a fighter.
Mode 0 (`FUN_004069a1`) stores an optional target actor and sets AI flag
`0x100000`. Mode 1 (`FUN_00406a2e`) sets AI flag `0x400000`. Both clear
the same flag group first. Chapter 2 uses mode 1 and mode 0 to turn the
assassins on and off. Surprise is per fight: the naga combat in chapter 9
(`NagaCombat` on scene `S00070003`) gives each death naga
`SetInitiative(200)` and sets James, Jazhara, Kendaric, and Solon
`SetSurprised(TRUE)`.

---

## 2. How a fight is chosen

Most fights are a pressure plate, a door, or a conversation calling
`CombatDef.Play()` on a group that is already in the room. Three patterns
are doing the work of a random-encounter table.

### Generic rooms, chapters 0–3

Scenes `S00020077` through `S00020082` each carry fourteen groups,
`CombatGroup01`–`CombatGroup14`, fourteen combats `Combat01`–`Combat14`,
and a saved `CombatNumber`. `SetupGeneric` in `Chapter0.def` hides all
fourteen, then, when `nRoomType` is 1:

- a `RollD100(50)` may show the next treasure chest
- a second `RollD100(50)` may show the combat group whose index equals
  `CombatNumber`, if that group is still alive, and play the matching
  combat

On a successful combat toss the script adds 1 to `CombatNumber`, including
the branch that finds the indexed group already dead and shows rats
instead. A failed toss shows rats and leaves the counter where it is, so
the next visit retries the same slot. `GenericCombatNumber_77` through
`_82` on the chapter copy those counters across saves. The same message
names are in chapters 1–3.

### One ambush, chapter 0

`CombatDef RandomCombat1` on scene `S00020042` is two thugs (`Thug #1`,
`Thug #2`) plus the party. The pressure plate of the same name is shipped
inactive (`Active : FALSE`). On the first entry, `RollD100(50)` shows
group `Thugs_2` and plays the combat. Later entries see
`GetNumTimesEntered()` already past 0.

### Catacombs, chapter 9

A 50% roll on certain catacomb entrances teleports to a picker scene.
`S00070033` keeps a `Visited` counter. Visits 0 through 3 show `Ghouls1`
through `Ghouls4` and play `Combat1` through `Combat4`. Each ghoul group
is four `Ghoul` instances. After the fourth visit the counter path stops
and the camera is handed back. The `RandomCombatN.ktx` text boxes on
those fights are flavor lines.

---

## 3. The people on the sheet

`Chars.tbl` has 208 `CharacterDef`s.

| First word of `Class` | Count |
|---|---:|
| Warrior | 65 |
| Thief | 31 |
| LPMage | 12 |
| Priest | 4 |
| NPC | 42 |
| Object | 52 |
| Invisible | 2 |

The 112 combat-class defs (Warrior, Thief, Priest, LPMage) split by model:

| `Model_Type` | Count |
|---|---:|
| Character | 74 |
| Monster | 31 |
| Boned | 2 |
| Party | 5 |

and by nationality: Kingdom 74, Undead 20, Monster 11, Keshian 6, Kesh 1.
The five `Party` models are James, Jazhara, William, Solon, and Kendaric.
Class bits (Warrior 1, Thief 2, LPMage 4, Priest 8) are the ones in
combat.md section 3, stored at definition `+0x50`.

A second set of bits is identity, stored at actor `+0x58` when the actor
is built (`FUN_004c786c`). The definition's `+0x3c` is 1 only when the
`CharacterDef` name is one of the five companions (`FUN_004c5295`); every
other def leaves it 0.

| Companion | Actor `+0x58` |
|---|---:|
| James | 1 |
| Jazhara | 2 |
| William | 4 |
| Solon | 8 |
| Kendaric | 0x10 |

James is a Thief, so his class bit is 2 and his identity bit is 1. Story
experience pays the identity bit. Level-up health pays the class bit.

---

## 4. Level, health, and the chapter row

`Attribute :` is eight integers, read by `FUN_00463e5e` into definition
virtuals `+0x30` through `+0x4c`. `FUN_004c786c` copies three of them onto
the actor:

| Index | Actor field | Role |
|---|---|---|
| 0 | `+0x5c` | level. `FUN_004ab840` (vtable `+0x108`) returns this short |
| 6 | `+100` (`0x64`) | max health |
| 7 | `+0x74` | max spell points |

Indices 1–5 are stored. Their names are not in the parser. Enemy level is
this authored number plus at most one chapter row. Companion level-up,
which increments `+0x5c` and rolls new health, is `FUN_004a32db` in
combat.md section 14.

### Chapter rows

The `chapter` keyword on a character def is `FUN_00463773`. It reads eight
comma fields, missing fields defaulting to 0 (`FUN_00426210`), copies them
in order into a 32-byte block, and `FUN_004c6e06` appends that block to
the list at definition `+0x104`.

`FUN_004c71a3` picks one row. Under chapter 11 it takes the exact chapter
match, otherwise the row with the greatest chapter key still at or below
the current chapter. One row is applied, so a later row replaces an
earlier one for that visit; the bonuses are added to the base sheet.

`FUN_004c8d4e` adds the row onto the actor:

| Field | Added to |
|---|---|
| 0 | the chapter key. Compared, never added |
| 1 | level at `+0x5c` |
| 2 | max health at `+100` |
| 3 | max spell points at `+0x74` |
| 4 | the primary weapon's skill |
| 5 | the off-hand weapon's skill, skipped when it lands on the same skill as field 4 |
| 6 | Defense, skill line 6, through actor virtual `+0x68` |
| 7 | a spawn-weight ceiling read by `FUN_004c786c`. The shipped rows leave it 0 |

Fields 4 and 5 are routed by the weapon-type ids at definition `+0xa0`
and `+0xa8`. The names are the keyword table at `0x5f0420`. `local_c`
in `FUN_004c8d4e` is only a flag so field 5 does not add twice to the
skill field 4 already used.

| Type id | Name | Skill line |
|---|---|---|
| 1, 3, 5, 10, 11 | Broadsword, Dagger, Shortsword, Scimitar, Rapier | 1 Bladed |
| 7, 8, 9 | Club, Mace, Warhammer | 2 Blunt |
| 6 | Battleaxe | 3 Axe |
| 2, 4 | 2Hand, Quarterstaff | 4 2-Handed |
| 13 | Bow | 5 Bow |

Spear (12) and Brawler (26) are in that keyword table and absent from
the switch, so a chapter row adds no weapon skill for them. The rest
of the 22 names are in combat.md section 3. A line with a single
number, `Chapter : 9`, is a row of zeros. It matches that chapter and
adds nothing.

### Difficulty and generic wounds

After the chapter row, `FUN_004c786c` copies max health to actor `+0x68`
and max spell points to `+0x78`. Then, for a def whose `+0x3c` is 0 and
whose max health is not 0, difficulty (`DAT_005e9b20`, the Play Easy /
Play Medium / Play Hard menu) rescales the live pools at `+100` and
`+0x74`:

| Menu | Value | Live health and spell points |
|---|---|---|
| Play Easy | 0 | `(value * 85 + 50) / 100` when the pool is above 10 |
| Play Medium | 1 | unchanged |
| Play Hard | 2 | `(value * 140 + 50) / 100` |

The copies at `+0x68` and `+0x78` stay at the pre-difficulty numbers. Kill
experience reads those copies, so Easy and Hard change how long the enemy
lives and leave the experience value on the chapter-adjusted sheet.

`Class : …, Generic` sets definition `+0x54`. For those defs the current
health at `+0x60` is four rolls from `(max + 3) / 6` to `(max + 2) / 3`,
summed and capped at the live max. The two style percents on the same
`Class` line are the aggressive and defensive chances in combat.md
section 3.

### Arabic Thug #1

Base sheet: `Attribute : 2,76,40,78,35,30,28,0`, so level 2, health 28,
spell points 0. `Class : Warrior, Generic, 33`. Rows:

| Chapter | +level | +health | +spell | +primary | +off-hand | +skill 6 |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 7 | 0 | 10 | 10 | 15 |
| 2 | 2 | 14 | 0 | 20 | 20 | 30 |
| 3 | 2 | 20 | 0 | 30 | 20 | 40 |
| 5 | 3 | 30 | 0 | 45 | 15 | 50 |

In chapter 4 the chapter-3 row is the latest that still applies: level 4,
health 48, before Easy or Hard and before the generic wound roll. In
chapter 5 and after, the chapter-5 row applies: level 5, health 58.

---

## 5. Bestiary

Base sheet only: level, health, and spell points from `Attribute` indexes
0, 6, and 7. A scale note is the one row `FUN_004c8d4e` would add at that
chapter (`+level / +health / +spell`). Weapon-skill adds on those same
rows are omitted here; they follow the table in section 4.

Goblins are `Model_Type : Monster`. The leader's nationality is Kingdom;
the others are Monster.

| Name | Class | Lv | HP | SP | Scale |
|---|---|---:|---:|---:|---|
| Goblin - Basic | Warrior, Generic, 5, 38 | 6 | 46 | 0 | ch 7 `+1/+8/+0`; ch 9 `+2/+12/+0` |
| Goblin - Archer | Warrior, Generic, 0, 40 | 7 | 45 | 0 | ch 7 `+1/+5/+0`; ch 9 `+2/+15/+0` |
| Goblin - Shaman | Priest, Generic, 10, 25 | 10 | 75 | 48 | ch 7 `+1/+5/+11`; ch 9 `+1/+5/+22` |
| Goblin - Leader | Warrior, Generic, 15, 50 | 8 | 56 | 0 | ch 7 `+1/+14/+0`; ch 9 `+2/+19/+0` |
| Goblin - Warlord | Warrior, Generic, 38, 22 | 11 | 150 | 0 | ch 7 `+1/+5/+0`; ch 9 `+1/+10/+0` |

A row stays in force until a later row applies, so chapter 8 still uses
the chapter-7 line.

Undead. Skeleton warriors and the giant skeleton are `Boned`. The rest
are `Monster` unless noted.

| Name | Class | Lv | HP | SP |
|---|---|---:|---:|---:|
| Skeleton Warriors | Warrior, Generic, 45 | 8 | 75 | 0 |
| Giant Skeleton Warrior | Warrior, Generic, 75 | 10 | 200 | 0 |
| Ghoul | Warrior, Generic, 65 | 9 | 80 | 0 |
| Zombie Warrior | Warrior, Generic, 55 | 9 | 100 | 0 |
| Zombie Priest | Priest, Generic, 25, 25 | 9 | 75 | 50 |
| Zombie Townsman | Warrior, Generic, 28 | 7 | 75 | 50 |
| Zombie Townswoman | Warrior, Generic, 18 | 7 | 75 | 50 |
| Shadow | Warrior, Generic, 83 | 7 | 75 | 0 |
| Vampire | Warrior, Generic, 75 | 10 | 145 | 25 |
| Male Vampire #1 | Warrior, Generic, 75 | 5 | 89 | 5 |
| Male Vampire #2 | Warrior, Generic, 25 | 5 | 85 | 5 |
| Female Vampire #1 | Warrior, Generic, 15 | 7 | 95 | 15 |
| Female Vampire #2 | Warrior, Generic, 15 | 5 | 95 | 15 |
| Female Vampire #3 | Warrior, Generic, 15 | 5 | 105 | 15 |
| Vampire Boy | Warrior, Generic, 75 | 5 | 65 | 15 |
| Vampire Girl | Warrior, Generic, 75 | 5 | 70 | 10 |
| Lich Priest | Priest, Generic, 0, 45 | 13 | 250 | 1000 |
| Demon | Warrior, Generic, 33 | 8 | 131 | 30 |
| Death Naga | Warrior, Generic, 78 | 5 | 65 | 50 |
| Dragon Soul | LPMage, Generic, 15 | 8 | 260 | 260 |

Other monsters, plus the two character-model bosses that anchor a chapter
fight.

| Name | Class | Lv | HP | SP | Note |
|---|---|---:|---:|---:|---|
| Lowland Troll 1 | Warrior, Generic, 50, 15 | 5 | 110 | 0 | |
| Lowland Troll 2 | Warrior, Generic, 44, 14 | 5 | 108 | 0 | |
| Sewer Monster | Warrior, Generic, 10, 45 | 5 | 120 | 0 | |
| Air Elemental | Warrior, Generic, 55 | 5 | 80 | 35 | |
| Flying Demon | LPMage, Generic | 12 | 250 | 50 | |
| Tentacle | Warrior, Generic, 100 | 9 | 85 | 0 | |
| Skull | LPMage, Generic | 9 | 85 | 160 | |
| Sea Monster | Warrior, Generic, 40, 15 | 5 | 175 | 0 | nationality Kingdom |
| Bear | Warrior | 9 | 100 | 0 | character model. From chapter 10: `+3/+30/+0` |
| Yusuf ben Ali | Warrior, , 0, 55 | 3 | 34 | 0 | character model, no scale row |

None of the undead or the non-goblin monsters above have a multi-field
chapter row. A bare `Chapter : N` on those defs adds nothing.

---

## 6. Kill experience

When an actor on side 0 dies, `FUN_0047803d` adds this to the fight pool
at combat `+0xb0`:

```
level * (healthSnapshot + 2 * spellSnapshot)
```

`level` is actor `+0x5c`. `healthSnapshot` is actor `+0x68` and
`spellSnapshot` is actor `+0x78`: the max health and max spell points
after the chapter row, copied before the Easy/Hard rescale. A side-1
death increments the party-side counter at combat `+0x24` and adds
nothing to the pool.

At the end of the fight `FUN_00475ed0` passes the pool to `FUN_004abacf`.
The shipping instructions, which the current decompile drops, are:

```
fild  pool
fstp  float
call  FUN_004abc6e          ; companion count
fild  count
fdivr pool                  ; pool / count
fadd  0.5
call  __ftol
```

before that, integer difficulty:

| Menu | Pool |
|---|---|
| Easy | `pool + pool / 4` |
| Medium | unchanged |
| Hard | `pool - pool / 6` |

The share is `(int)(adjustedPool / count + 0.5)`, and at least 1. The
count is how many actors in the party list return nonzero from vtable
`+0x10c`. That virtual is `FUN_004ab860`, which returns definition
`+0x3c`, so the count is how many of James, Jazhara, William, Solon, and
Kendaric are in the list. Each of them is paid the same share through
`FUN_004abf9f`, which adds it to the pool at experience-record `+4` and
then levels up while the pool meets the next threshold. The record is
only created for those five companions (`FUN_004a0ea0`).

The pool is clamped to 999998 once it passes 999999. The `Experience`
cheat (`DAT_00629dbc`) replaces the share with enough points to reach the
next threshold.

A second gate sits on the experience record at `+0xc`: the share is paid
when that dword is 0. The constructor and the save keys for the pool
(`+4`) and advancement points (`+8`) do not write it. What sets it is
still open; see section 9.

---

## 7. Level thresholds

`FUN_004ab980` picks the table from the class bit (vtable `+0xfc`) and
stores the pointer at experience-record `+0x10`. `FUN_004ac160` returns

```
table[(level - table[0]) * 2 + 3]
```

`table[0]` is the class base level. The value is how high the pool must
be to leave that level. The last entry of each table is 999999. The pool
clamps at 999998, so that last level does not advance.

The numbers are ×1.5 from one row to the next, with the half rounded.
That rounding is in the table, not in a multiply at runtime.

**Thief** (`DAT_005e9978`, base 3). James starts here.

| Level | Pool to advance | Level | Pool to advance |
|---:|---:|---:|---:|
| 2 | 1000 | 11 | 38443 |
| 3 | 1500 | 12 | 57665 |
| 4 | 2250 | 13 | 86497 |
| 5 | 3375 | 14 | 129746 |
| 6 | 5062 | 15 | 194619 |
| 7 | 7593 | 16 | 291929 |
| 8 | 11390 | 17 | 437893 |
| 9 | 17085 | 18 | 999999 |
| 10 | 25628 | | |

**Lesser Path mage** (`DAT_005e9a00`, base 2). Jazhara and Kendaric.

| Level | Pool to advance | Level | Pool to advance |
|---:|---:|---:|---:|
| 1 | 1000 | 8 | 22781 |
| 2 | 2000 | 9 | 34171 |
| 3 | 3000 | 10 | 51257 |
| 4 | 4500 | 11 | 76886 |
| 5 | 6750 | 12 | 115330 |
| 6 | 10125 | 13 | 172995 |
| 7 | 15187 | 14 | 999999 |

**Warrior** (`DAT_005e9ad8`, base 3). William.

| Level | Pool to advance |
|---:|---:|
| 2 | 1500 |
| 3 | 2250 |
| 4 | 3375 |
| 5 | 5062 |
| 6 | 7593 |
| 7 | 11390 |
| 8 | 17085 |
| 9 | 25628 |
| 10 | 999999 |

**Priest** (`DAT_005e9a70`, base 3). Solon.

| Level | Pool to advance | Level | Pool to advance |
|---:|---:|---:|---:|
| 2 | 8000 | 9 | 136687 |
| 3 | 12000 | 10 | 205031 |
| 4 | 18500 | 11 | 307546 |
| 5 | 27000 | 12 | 461320 |
| 6 | 40500 | 13 | 691980 |
| 7 | 60750 | 14 | 999999 |
| 8 | 91125 | | |

Health and spell points gained on a level-up are the class table in
combat.md section 14. Any class bit outside those four has no threshold
table; `FUN_004ac160` returns 999999.

### Starting pools

`FUN_004ab980` writes a starting pool when the identity bit matches.
The level-up loop runs on the next positive call to `FUN_004abf9f`,
which adds its grant and then levels against the whole pool.

| Companion | Authored level | Class table | Seed |
|---|---:|---|---:|
| James | 3 | Thief | 251 |
| Jazhara | 2 | Lesser Path | 1801 |
| William | 3 | Warrior | 501 |
| Solon | 6 | Priest | 27001 |
| Kendaric | 5 | Lesser Path | 4501 |

Solon's 27001 and Kendaric's 4501 are the same numbers as their columns
on the `StartChapter5` event (section 8). The seed is applied when the
actor is built. The event adds those numbers again when chapter 4 ends.
Priest level 6 advances at 40500, so the 27001 seed stays at level 6
and 27001 + 27001 = 54002 advances to 7 (the level-7 row is 60750).
Mage level 5 advances at 6750, so the 4501 seed stays at level 5 and
4501 + 4501 = 9002 advances to 6 (the level-6 row is 10125). Easy and
Hard rescale the event grant. The seed is stored as written.

---

## 8. Story experience

`AddExperiencePoints("name")` is `FUN_0050cfbe`. It looks the name up on
the world (`GetButtonID` on `DAT_00629ef0`) and calls `FUN_004abd0d`.

The `event` lines in `ChapterEvents.tbl` are parsed by `FUN_0046cfcd`
(keyword table at `0x5de650`, under the `chapterevents` block). The
record is 0x28 bytes:

| Line field | Example `StartChapter0` | Stored at | Paid to |
|---|---|---|---|
| 0 | 0 (chapter id) | `+0x10` | recorded only. `FUN_004abd0d` pays from `+0x14` |
| 1 | StartChapter0 | `+0xc` | the lookup name |
| 2 | 500 | `+0x14` | James |
| 3 | 1000 | `+0x18` | Jazhara |
| 4 | 0 | `+0x1c` | William |
| 5 | 0 | `+0x20` | Solon |
| 6 | 0 | `+0x24` | Kendaric |

`FUN_004abebc` finds the companion by the identity bit at actor `+0x58`.
A zero column is skipped. `FUN_004abf4f` applies difficulty to each
column before the add: Easy adds a quarter, Hard subtracts a sixth when
the value is above 6, Medium leaves it. The optional second script
argument defaults to 1 and is the flag that shows the experience notice
and the "Level Up" line. The pool and the level-up loop run either way.

Fight-shaped rows, in file order. Columns are James, Jazhara, William,
Solon, Kendaric. The comments are the ones in the tbl.

| Event | James | Jazhara | William | Solon | Kendaric | Note in the file |
|---|---:|---:|---:|---:|---:|---|
| PassGuard | 50 | 50 | 0 | 0 | 0 | enter the sweatshop by conversation instead of combat |
| EnterJailBackDoor | 100 | 100 | 100 | 0 | 0 | avoiding the archer combat |
| YeBittenDogNoCombat | 100 | 100 | 100 | 0 | 0 | |
| GreetMockers | 250 | 100 | 100 | 0 | 0 | avoid the mocker hunting party |
| ExitDrunkTreasureHunters | 100 | 100 | 100 | 0 | 0 | avoid that combat |
| ExitHostileTreasureHunters | 100 | 100 | 100 | 0 | 0 | avoid that combat |
| DestroySewerMnstEggs | 250 | 250 | 250 | 0 | 0 | |
| MockerPeace | 250 | 150 | 150 | 0 | 0 | avoid Jak's mockers |
| TacticalVictory | 0 | 0 | 1500 | 0 | 0 | win the merc battle |
| TacticalVictory2 | 0 | 0 | 1250 | 0 | 0 | the Bear battle. The chapter 6 calls are commented out |
| DefeatAirElementals | 500 | 500 | 0 | 500 | 500 | |
| DefeatFlyingDemon | 1000 | 1000 | 0 | 1000 | 1000 | |
| DestroyBossVampire | 1500 | 1500 | 0 | 1500 | 1500 | |
| KilledNoTownsPeople | 1000 | 1000 | 0 | 1000 | 1000 | |
| KilledSomeTownsPeople | 100 | 100 | 0 | 100 | 100 | |
| DefeatTentacles | 400 | 400 | 0 | 400 | 400 | |
| DefeatDragonSoul | 1500 | 1500 | 0 | 1500 | 1500 | |
| StartChapter5 | 0 | 0 | 2000 | 27001 | 4501 | chapter-4 event, fired as chapter 5 starts |

`StartChapter0` pays James 500 and Jazhara 1000, on top of the seeds in
section 7 (251 and 1801). The rest of the file is puzzles, conversations,
and chapter-start awards. The tbl is the full list.

Kill experience and these rows are separate grants. A dead goblin pays
the formula in section 6, and a later `AddExperiencePoints` pays again.

---

## 9. What is not pinned down

- **Attribute indexes 1–5.** Indexes 0, 6, and 7 are level, health, and
  spell points. The middle five are stored by `FUN_00463e5e` and never
  named in that parser.
- **What `ArmorParam`'s two fields mean in a fight.** The keyword is
  `FUN_00465a25`: field 0 is an integer stored through definition virtual
  `+0x54`, field 1 is a string stored at definition `+0xe4`. Combat.md
  section 10 still owns the absorption formula. This parser was not
  followed into that formula. Shipped examples: skeletons `20,4`, the
  sewer monster `45,8`, the shaman `15,2`.
- **Which `AttackParam` field feeds which live stat.** Unchanged from
  combat.md section 17. The keyword itself is `FUN_00464a70`.
- **Experience-record `+0xc`.** `FUN_004abacf` pays a companion when this
  dword is 0. `FUN_004ab980` does not write it, and the save readers for
  the pool and the advancement points do not either.
