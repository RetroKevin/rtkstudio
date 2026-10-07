# Combat

How a fight in Return to Krondor is authored, how a character is ordered to
act, and how a swing becomes a hit and a wound. This is the runtime in
`RtK.exe`. Item and spell text live in the inflated game data:
`out/plaintext/GameData/MagicInvItem.txt`, `MagicResult.txt`, `Chars.tbl`,
and the per-chapter `*.def` files.

Function names are the stable citations. `RtK.c` line numbers move every
time the decompile is regenerated;
`python tools/show_func.py out/decompiled/RtK.c FUN_004a1acb` re-finds one.
The formulas below were checked against the shipping instructions where the
decompiler dropped a compare or a floating-point step.

Two resolvers are both still reachable. The one the player hits is the
actor path (`FUN_004a1acb` and its siblings). A second, older path
(`FUN_004615b2`) still runs parting strikes. They do not use the same
tables. Each section says which one it is.

---

## 1. What a fight is

A fight is a `CombatDef` on a scene: a list of groups, a start position and
facing for every participant, a polygon the fight is allowed to happen in,
a music cue, and `OnStart` / `OnEnd` script. It is not a separate screen.
The same scene, camera, and walk grid stay up. Characters are the same 3D
actors used for conversation.

The engine types are `CCombatDef`, `CCombatNode`, and a manager that
autosaves when a fight begins (`CCombatManager : autosave failed` is the
failure string). Entering real combat is `FUN_00501387`, which only runs
when the scene-root mode at `DAT_00628d6c + 0x4bc2c` is 4. It logs
`Real Combat Started`, then `FUN_005018d1` loads `Combat Configuration`.
Setup that builds the participant list logs `Initializing Combat`
(`FUN_005044f3`).

A save records each fight on its scene as `Combat <name>` with
`NumTimesPlayed`. `@LastCombat.rtk` is one such save, taken inside a
fight: party members carry `Health`, `Damage` (non-permanent wounds),
`SpellPts`, `AttackStyle`, `CastStyle`, `TrollishBloodRounds`, and
`PoisonDmgPerRnd`.

---

## 2. How a fight is authored

`CombatDef` blocks live in the chapter scripts. Chapter 0 alone has 94.
A typical one (`Chapter0.def`, `Combat3`) names:

| Field | Role |
|---|---|
| `CombatMusic` | cue from the music table in `RtkGame.def` (`KrondorAboveGround`, `Dark_Suspense_Battle`, `Final_Bear_Battle`, …) |
| `Groups` | who fights. `Party` is the player side. Other names are enemy groups already placed in the scene |
| `Formation` | per member: x, y, z, facing in degrees |
| `RunToFormations` | walk or run to that mark when the fight starts |
| `Arena` | five XYZ points, the fight polygon |
| `OnStart` / `OnEnd` | script. Start usually enables a camera set and teleports. End sets story flags, arms touch sensors, and often puts the camera back |

`PotentialCombats` is a field on every conversation definition. In the
shipped chapters it is always empty. Fights are started by script, not by
that field.

The script verbs, registered in `FUN_004cab9e` / `FUN_004cd9ce` on a
character and in `FUN_004d6567` on a group:

| Verb | Who |
|---|---|
| `EnterCombat` / `ExitCombat` | character |
| `SetCombatAIMode` | character or group. Called as `SetCombatAIMode(mode, NULL, actor)`. Chapter 2 uses mode 0 and 1 to turn assassins on and off |
| `SetAmbientAIMode` | the out-of-combat wander mode |
| `SetInitiative` / `SetLoseTurn` / `SetSurprised` | force turn order |
| `DoResistCheck` | a spell or effect resistance roll from script |
| `DropDead` / `IsAlive` / `IsWounded` / `Ressurect` | life state. The script spelling is `Ressurect` |
| `GetCombat` / `Resume` | scene looks up a `CombatDef` and continues it. Used when a conversation has to freeze a fight and put a character back into it |

Random encounters are ordinary `CombatDef`s (`RandomCombat1` in chapter 0)
armed by a pressure plate of the same name. Wilderness rooms in chapter 0
keep fourteen `CombatGroupNN` groups and a `CombatNumber`; `RessurectGeneric`
revives the group selected by that counter, and `KillGeneric` kills all
fourteen when the room is done.

---

## 3. The people in it

Characters are `CharacterDef` records in `Chars.tbl`. The party starters:

| | James | Jazhara | William | Solon |
|---|---|---|---|---|
| Class text | Thief | LPMage | Warrior | Priest |
| Class bit | 2 | 4 | 1 | 8 |

`FUN_004639d9` reads `Class :`. The first comma field is a name in the
keyword table at `0x5f0390` (`FUN_004b9450`), then `FUN_004c49fc` stores
the id on the character definition at `+0x50`. The ids are bits, and the
table order is not the bit order:

| Name | Bit |
|---|---|
| None | 0 |
| Warrior | 1 |
| Thief | 2 |
| LPMage | 4 |
| Priest | 8 |
| NPC | 16 |
| Object | 32 |
| PassThru | 64 |
| Invisible | 128 |

An unknown name becomes −1 from the lookup and 0 from `FUN_004c49fc`,
so it is stored as None. `FUN_004c6cea` treats only bits 4 and 8 as
casters. `FUN_004c6d17` treats None, NPC, Object, PassThru, and
Invisible as not a combat class.

The second comma field is the word `generic`, which sets a flag at
definition `+0x54`. No reader of that flag turned up. The third and
fourth fields are integers at `+0x40` and `+0x44`. `FUN_00499f60` rolls
them once when the actor is built and writes attack style at actor
`+0xec`: a d100 at or under the third number picks style 2 (aggressive),
otherwise a d100 at or over `100 − fourth` picks style 0 (defensive),
otherwise style 1. Both zero leaves style 1, which is why `Class : Thief`
on James has no numbers. Party members stay balanced; a soldier written
`Warrior, Generic, 28, 22` is 28% aggressive and 22% defensive.

`INV_CLASSLIMIT_*` in `RtkGame.def` is a different mask (warrior 1,
rogue 2, priest 4, mage 8). The item line "Users:" is built in
`FUN_004942db` from the item's category and subcategory, in the order
Warrior, Thief, Priest, Mage. That is not the character bit above.
Priest is character bit 8 and item-label bit 4.

A character also has eight `Attribute` numbers, a 22-value `Skills`
list, and `AttackParam`.

`AttackParam` is seven comma-separated fields. The third may be a slash
pair (`32/55` on Solon). The fourth is a small integer, almost always 0–3,
and matches a strikes-per-round count. The fifth is a damage range
(`2-12`, `17-37`). The seventh is usually 50. The melee resolver does not
read this string. It reads the live actor through virtual calls. Treat
`AttackParam` as the authored starting sheet, not as the formula inputs.

Skills are 22 integers on the `Skills :` line. `FUN_00465b17` stores
skill N through definition virtual `+(0x60 + N*4)`. `FUN_004c786c`
copies those 22 shorts onto the actor. The names are painted on bitmap
`bubac_kgnd` (857), the frame of `sAttr_Overlay` (856). They are not C
strings. `sHighlight01` through `sHighlight22` are the bars on those
labels, and `FUN_0052fd30` fills them in button order.

The button index matches the `Skills` line for 0–17, 19, and 21.
`FUN_00534912` swaps the other two: button 18 adds Life (line 20, actor
`+0xaa`) and button 20 adds Change (line 18, actor `+0xa4`).
`FUN_005341fb` tests the button index, so Life stays priest-only and
Change stays mage-only. Actor shorts after index 15 are not in line
order either; the copy writes them that way.

| Line | Sheet | Actor | Who can raise it | Where it is read |
|---:|---|---|---|---|
| 0 | Brawling | `+0x84` | anyone | No weapon, or a weapon whose classification is Special (6). `FUN_004950ba` calls virtual `+0x74` |
| 1 | Bladed | `+0x86` | not a priest | Classification Bladed (2). Chapter weapon types Broadsword, Dagger, Shortsword, Scimitar, Rapier |
| 2 | Blunt | `+0x88` | anyone | Classification Blunt (3). Club, Mace, Warhammer |
| 3 | Axe | `+0x8a` | warrior only | Classification Axe (1). Battleaxe |
| 4 | 2-Handed | `+0x8c` | anyone | Classification TwoHanded (5). 2Hand, Quarterstaff |
| 5 | Bow | `+0x8e` | not a mage or a priest | Classification Bow (4). Bow |
| 6 | Defense | `+0x90` | anyone | `FUN_004a8914`. Blind or paralyzed returns 0. Chapter field 6 adds here |
| 7 | Initiative | `+0x92` | anyone | `FUN_0049a467` adds virtual `+0x90` into the fighter score |
| 8 | Analyze | `+0x94` | not a warrior | Getter `FUN_004a6975`, virtual `+0x98` |
| 9 | Stealth | `+0x96` | anyone | Probe on the lock screen. `FUN_0056b75c` and `FUN_0056ba3a` call virtual `+0x9c` |
| 10 | Pick Lock | `+0x98` | thief only | Virtual `+0xa0`, `FUN_004a6616` |
| 11 | Disarm Traps | `+0x9a` | thief only | Virtual `+0xa4`, `FUN_004a66c8`. The sheet says "Disarm Traps" |
| 12 | Perception | `+0x9c` | anyone | Virtual `+0xa8`, `FUN_004a6a63` |
| 13 | Alchemy | `+0x9e` | mage only | Virtual `+0xac`, `FUN_004a6b4a`. See [`alchemy.md`](alchemy.md) |
| 14 | Evaluate | `+0xa0` | anyone | `FUN_004a7cc2` calls virtual `+0xb0` and sets reveal bits on the target at `+0x2e` |
| 15 | Shield | `+0xa2` | not a thief | Adjusted getter `FUN_004a677a`, virtual `+0x94` |
| 16 | Fire | `+0xa8` | mage only | Spell path Flames (id 2), virtual `+0xb4` |
| 17 | Mind | `+0xac` | mage only | Spell path the Mind (id 4), virtual `+0xb8` |
| 18 | Change | `+0xa4` | mage only | Spell path Change (id 0), virtual `+0xbc` |
| 19 | Storms | `+0xae` | mage only | Spell path the Storm (id 5), virtual `+0xc0` |
| 20 | Life | `+0xaa` | priest only | Spell path Healing (id 3), virtual `+0xc4` |
| 21 | Divine | `+0xa6` | priest only | Spell path Divine (id 1), virtual `+0xc8` |

The path names on the sheet are Fire, Mind, Life, Storms, Change, and
Divine. The spell keyword table at `0x5f6710` spells those
`Path of Flames`, `Path of the Mind`, `Path of Healing`,
`Path of the Storm`, `Path of Change`, and `Path of Divine`, ids 2, 4,
3, 5, 0, and 1. A priest is rejected for Change, Flames, Mind, and
Storm, and required for Divine and Healing (`FUN_004a33f6`). The spell
level times 10 has to be at or under the path skill.

`Char_GetSkillInt` is a different numbering. Its argument is not the
`Skills` line index. Cases 0–5 are Flames, Mind, Life, Divine, Change,
Storms. Cases 10–16 are Brawling through Defense. Then 18 Analyze, 19
Stealth, 20 Pick Lock, 21 Disarm Traps, 23 Alchemy. Anything else
returns −1, including Initiative, Perception, Evaluate, and Shield.

On the actor, the three stats the attack line adds are fetched by virtual
call: strength at `+0xcc`, agility at `+0xd0`, reason at `+0xd8`. That
order is the one printed by the older resolver as
`AV = (SKIL) + (STR) + (AGIL) + (REAS) + (STYL) + (FATE)`.

---

## 4. Orders

Click handling logs the order as it is issued (`FUN_0048835d` and the
activate/execute strings):

| Order | Click text |
|---|---|
| Full attack | Left click starts it. Double click is also a full attack |
| Single attack | one swing, and the character can still move |
| Full missile / single missile | the bow versions |
| Parry | half move, then parry |
| Defend, guard, protect | half move. Protect names the ally being covered |
| Cast | spell interface, last spell, or favourite spell 1–3 |
| Search ground | after the fight, on a corpse |
| Drop weapon | and optionally take the one on the ground |

The AI action code, logged by `FUN_0040a934`, uses the same set:
1 pass, 2 move, 6 single attack, 7 full attack, 8 single missile,
9 full missile, 13 protect, 14 parry, 15 guard, 17 cast. Cast distinguishes
a quick cast from a normal one. `No Enemy AI` is a cheat that skips the
enemy side.

Attack style is a separate stance, stored on the actor at `+0xec` and
saved as `AttackStyle`:

| Style | Attack value | Defense value | Damage range | Parry score |
|---|---|---|---|---|
| 0 | −15 | +25 | −25% | +25, then the score is halved |
| 1 | 0 | 0 | 0 | +0 |
| 2 | +25 | −25 | +25% | the attempt is refused |

The first three columns are `FUN_004b4e39`, `FUN_004b4e7f`, and
`FUN_004b4ec5`. The parry column is `FUN_004b4f0b`, and section 9 is
where the score is built. Style 0 is the cautious stance, style 2 the
committed one. Style is not cleared at the end of a swing.
`FUN_0049b2d4` (`Melee Round End Of Turn`) clears the fighter field at
`+0x6c` and sets actor `+0x574`. The stance at `+0xec` stays.

---

## 5. Initiative and rounds

For each living fighter, `FUN_0045fd81` stores a score at fighter `+0x24`:

```
d100
+ agility band          (stats +0x34 through FUN_0045f157)
+ class constant        (stats +0x20 through FUN_0045f0ae)
+ a raw skill           (stats +0x44)
+ a bonus               (fighter +0x34)
```

`d100` is `FUN_0045ee42`: `rand % 100 + 1`.

Agility bands (`FUN_0045f157`), attribute on the left, bonus on the right.
Above 200 or below 0 logs `Attribute out of Range` and contributes 0.

| Attribute | Bonus |
|---|---|
| 0–10 | −20 |
| 11–20 | −15 |
| 21–30 | −10 |
| 31–70 | 0 |
| 71–80 | +10 |
| 81–90 | +15 |
| 91–100 | +20 |
| 101–133 | +30 |
| 134–165 | +35 |
| 166–200 | +40 |

Class constants (`FUN_0045f0ae`):

| Class id | Bonus |
|---|---|
| 0 | 70 |
| 1 | 60 |
| 2 | 40 |
| 3 | 30 |
| 4 | 25 |
| 5 | 50 |
| 6 | 80 |
| 7 | 90 |

Anything else logs an error and contributes 0. These ids are not the
warrior/rogue/priest/mage bits from section 3.

`FUN_0050a572` runs at `Start of Round`. On every odd round number it
finds the actor whose name contains `James` and sets his initiative to 1,
and logs `James Loses Initiative`. No cheat flag gates it. A score of 1
is far below a normal total, so James acts last on odd rounds.

---

## 6. To hit

The melee click path is `FUN_004a1acb` (`Attack with Melee Weapon`).
`FUN_004a2145` is the same roll with the same base. A parting-style entry,
`FUN_004a1f27`, uses 70 instead of 50. Missiles use `FUN_004a188e`.

```
chance = 50 + attack value − defense value
```

Two passes then edit `chance`. `FUN_004aa186` is a floor, not a spell:

- under 40 becomes 40
- from 40 through 89 it is left alone
- at 90 or above it is raised to at least `90 + 2 * (attacker level − defender level)`, and to 90 when the attacker is the lower level

`FUN_004af3df` is `Weapon_AddHitChance` (effect id 25) on the active
weapon. It returns how much the modifier in section 12 changed the
chance, and the caller adds that delta. The cheat `Demo Dice`
(`DAT_00629d90`) raises a melee chance that fell below 80 up to 80.

`FUN_004a2784` rolls one `d100` (`FUN_004894c8`, same `1..100` shape) and
uses it for both the crit test and the hit test.

```
crit threshold = (chance + 2) / 5
```

That threshold doubles when `FUN_00477f20` says so. It says so when the
attacker's side is the smaller one on the combat manager's pair of
counters (`(count + 1) / 2` below the paired count), and also when the
average of each enemy's `((current health + (max + 1) / 2) * 100) / max`
is under 25. Magic can still replace the threshold (`Critical Hit Now`).
Immune to critical hits forces it to 0. Cursed for critical hits
replaces it with the whole hit chance. A critical hit is
`roll <= crit threshold`. Otherwise the swing hits when
`roll <= chance`, and misses when `roll > chance`.

A hit chance of 50 is therefore a 50% hit and about a 10% crit, and the
crits are the low end of the same roll, not a second roll.

Facing is folded into the attack value, not into a separate test.
`FUN_004b4f51`, from the side code `FUN_004ad1ee` writes onto `+0x580`:

| Side | Code | Attack bonus | Landing log |
|---|---|---|---|
| back | 0 | +10 | `Landed : Back` |
| front | 1 | 0 | `Landed : Front` |
| left | 2 | +5 | `Landed : Left` |
| right | 3 | +5 | `Landed : Right` |

---

## 7. Attack value

`FUN_004a238d` logs `Attack Value` and returns it. In order:

1. Weapon skill. Normally `FUN_004950ba` on the active weapon. When
   effect slot `0xc9` is set (`FUN_004aed30`; the magic scan fills it
   from `Special_Transformation`), the skill is the short from
   `vfunc +0x60` on the object at actor `+0x558` instead.
2. Strength band, `FUN_004b4dd1` of `vfunc +0xcc`.
3. Agility band, `FUN_004b4d32` of `vfunc +0xd0`.
4. Reason band, `FUN_004b4dd1` of `vfunc +0xd8`. Same table as strength.
5. Style, `FUN_004b4e39` of actor `+0xec`. See section 4.
6. Fate, the integer at actor `+0xfc`.
7. Blindness (`FUN_004aed54`) subtracts 40.
8. Facing bonus from section 6.
9. `10 * FUN_00477eb9(...)`. That walks every other fighter and adds
   one for each whose protect list (`+0x90` on the block at fighter
   `+0xe8`, tested by `FUN_0049ae29`) contains the target. Ten points
   per ally who is covering that target.
10. If the target is helpless — down, blinded, or paralyzed
    (`FUN_004a8465`, `FUN_004aed78`, `FUN_004aed54`) — add 30, logged as
    `Target Helpless`.
11. Encumbrance, `FUN_004b2ece`. See below.
12. `FUN_004aefbb`. Stunned subtracts 25, logged as
    `Stunned Attack Value`. Then the `Modifier_Attack` pair at effect
    `+0x7c` is applied with the formula in section 12. A missile swing
    also applies the pair at effect `+0x26c`
    (`Missile Attack Modifier`).

Strength and reason bands (`FUN_004b4dd1`):

| Attribute | Bonus |
|---|---|
| below 0 | −15 |
| 0–15 | −10 |
| 16–30 | −5 |
| 31–85 | 0 |
| 86–100 | +5 |
| 101–135 | +10 |
| 136–170 | +15 |
| 171 and up | +20 |

Agility bands (`FUN_004b4d32`):

| Attribute | Bonus |
|---|---|
| below 0 | −20 |
| 0–15 | −15 |
| 16–30 | −10 |
| 31–40 | −5 |
| 41–60 | 0 |
| 61–75 | +5 |
| 76–90 | +10 |
| 91–100 | +15 |
| 101–125 | +20 |
| 126–150 | +25 |
| 151–175 | +30 |
| 176 and up | +35 |

Missile attack value (`FUN_004a13d8`) is the same shape with a different
first term and one extra band. It starts from weapon skill (or the
off-hand skill), adds the agility band and the reason band, adds fate at
`+0xfc`, adds a range band from `FUN_004b4f51`, adds 30 against a
helpless target, then adds `FUN_004b6121` of the weapon's missile class:

| Class | Bonus |
|---|---|
| 0 | −5 |
| 1 | 0 |
| 2 | +8 |
| 3 or anything else | +15 |

The missile chance is `50 + that value − FUN_004a1561(defender)`.

### Encumbrance

`FUN_004b2d95` runs when a strike is being prepared (`FUN_004a8740`) and
when move speed is built (`FUN_0049a993`). Carried weight is the float
at actor `+0x50` (picking an item up adds that item's weight to it).

```
load = (weight * 100 + 50) / (strength + stamina)
```

The division is floating point and the result is truncated to an int.
Strength and stamina are the shorts from `vfunc +0xcc` and `vfunc +0xd4`.

| Load | Attack and defense | Move speed |
|---|---|---|
| 60 or less | unchanged | unchanged |
| 61–85 | 95% | 75% |
| 86–92 | 90% | 50% |
| 93 and up | 80% | 25% |

The attack and defense column is a ratio on the modifier record at
effect `+0x33c`, applied by `FUN_004b2ece` through the formula in
section 12. The same ratio is applied to the parry score. Move speed
is a separate multiply in `FUN_0049a993`, and blindness multiplies that
speed by 0.33 on top of the load. The agility term in the move base is
`FUN_004b4b67`: −20 below 0, then −15, −10, −5, 0 across 0–70, then +5,
+10, +15, +20, +25, and +30 from 167 up.

---

## 8. Defense value

`FUN_004a263c` logs `Defense Value`.

It always adds three things: a defense skill passed through `FUN_004af7c4`,
the integer at actor `+0x104`, and the raw agility short from `vfunc +0x8c`.

If the defender is not helpless it also adds:

- the style defense band (`FUN_004b4e7f` of `+0xec`)
- the agility band (`FUN_004b4d32` of `vfunc +0xd0`)
- while the parry-defense flag at `+0x128` is set,
  `(raw agility * 3 + 1) / 2`

`FUN_004b2ece` applies encumbrance on top. A helpless defender keeps the
first three terms only, so a downed or blinded character loses style,
the agility band, and the parry-defense bonus.

The missile defense (`FUN_004a1561`) uses the same skill-plus-bonus-plus-raw
agility base, plus 20 when `FUN_004a70a9` says the defender is covered.
If the defender is not helpless it adds the agility band, and the
parry-defense flag contributes `(agility * 3 + 1) / 2` there too. A
helpless defender instead skips those and has half their raw agility
subtracted when `+0x128` is set.

---

## 9. What the swing becomes

After the `d100`, `FUN_004a2784` writes a result code to actor `+0x57c`.
`FUN_0047b34c` is the log:

| Code | Log | When |
|---|---|---|
| 2 | `Swing : Miss` | roll above the hit chance, or the defender is protected from the element of this weapon (`+0x2c == 1` on the weapon and the defender carries that protection) |
| 3 | `Swing : Parry` | the hit landed, the defender is not blocking, the weapon is allowed to be parried, and `FUN_004a2c2b` succeeds. Damage is not rolled |
| 4 | `Swing : Block` | the hit landed and `FUN_004a29af` succeeds |
| 6 | `Swing : WimpHit` | the hit landed and the damage roll came back 0 |
| 1 | `Swing : Hit` | the hit landed and damage is greater than 0 |
| 5 | `Swing : CritHit` | the roll fell inside the crit threshold. Damage is doubled |
| 7 | `Swing : Lightning` | not a melee result. `FUN_004a1693` uses it for a spell or effect impact |

Parry (`FUN_004a2c2b`) and block (`FUN_004a29af`) are the same kind of
test. Each refuses the attempt, and returns 0, when the defender is
helpless, when the style at `+0xec` is 2, or when the matching charge
is 0. Parry also refuses when the weapon cannot be parried
(`FUN_00494db6`) and when the defender is covered (`FUN_004a70a9`).
Block is the opposite on that last point: it refuses unless the
defender is covered. An attack from behind is refused when a facing
flag is set (`FUN_004ad2bf` must be front, left, or right for a parry,
and front or left for a block).

The parry score, before the roll:

```
(weapon skill + agility band + strength band + reason band
   + style parry bonus + the defense bonus at +0x104 + 1) / 2
```

Weapon skill is the active weapon, or the skill on the object at
`+0x558` when effect slot `0xc9` is set (the scan fills that slot from
`Special_Transformation`). Encumbrance then scales the score. Parry
defense (`+0x128`) adds 25. Stunned subtracts 25. One charge at `+0x46`
is spent. A `d100` at or under the score is a parry.

The block score starts as shield skill (`vfunc +0x94`) plus the style
parry bonus, the agility band, and a shield-quality band
(`FUN_004b65aa` of `FUN_004a6ff0`: no shield 0, quality 0 is −2, 1 is 0,
2 is +2, 3 is +4; a shield-ring effect counts as quality 3). Parry
defense adds 25. Otherwise the score is cut to about a third,
`(score + 2) / 3`, except that a defender with two block charges and no
parry defense keeps two thirds, `(score * 2 + 2) / 3`. Stunned subtracts
25. One charge at `+0x47` is spent. A `d100` at or under the score is a
block.

The older resolver's parry function, `FUN_004613a1`, is a different
story. It computes

```
threshold = ((attack value + style parry bonus) * weapon parry factor + 50) / 100
```

and compares a `d100` to it, but the compare never clears the "hit
stands" flag. The flag starts at 1 and the only write sets it to 1
again. The function returns 0, which cancels damage, only when the
defender's style byte is 2, and it does that before the roll. That path
is the parting-strike resolver, not `FUN_004a2784`.

---

## 10. Damage and armor

`FUN_004a70e3` (`Roll Damage ActiveWeapon`) is the damage of a landed
melee swing.

The active weapon's `vfunc +0x14c` fills the minimum and maximum. The
decompiler does not show the store; the next use of those two locals is
the style adjustment, and the log is `Damage Range of Weapon`. Style
then scales both ends by the percent in section 4:

```
end = end + end * stylePercent / 100
```

The roll is inclusive: `FUN_004894fb` returns
`min + rand % (max − min + 1)`.

If the weapon ignores metal and the defender's armor class at
`stats +0xcc` is 2 (Chain; the armor keyword table at `0x5f04f8` is
None 0, Leather 1, Chain 2, Plate 3), a percent from the weapon
(`FUN_00494fe2`) replaces
the roll: 0 means no damage, 100 leaves it, anything else is
`(roll * percent + 50) / 100`.

Otherwise each worn piece — torso, arms, legs, the three
`FUN_004b55d1` calls — absorbs

```
(roll * rating * quality) / 100 + rating
```

and the three absorptions add up. When the armor absorbs the whole
roll, a `d100` below 21 still leaks a little: the leak is `roll − 1`
when the roll is under 6, otherwise `roll − Rand(1, 5)`. `FUN_004b0860`
edits the absorbed amount. If effect slot `0xc9` is set it adds
`4 + attacker level` to the absorption, and the pair at effect `+0x28c`
(`Armor Damaged`) is applied with the section 12 formula,
which can shrink or grow what the armor stopped. The leaked or
unabsorbed remainder is the damage, capped so it cannot exceed the roll.
`Weapon Ignores Armor` skips this and keeps the raw roll.

`FUN_004af695` is the last pass on the number that will be subtracted
from health. The defender's `Damage_Rolled` pair (effect `+0x13c`,
`Damage Rolled Against`) is applied first. The attacker's
`Damage_ByPlayer` pair (effect `+0x6c`, `Players Damage`) is applied
when that pair is present. If the target's `vfunc +0x13c` says undead,
the attacker's pair at effect `+0x18c` (`Damage to Undead`) is applied
too. Each of those is the same value-then-ratio step.

Damage that armor did stop can scar the armor. A `Rand(0, 12)` picks
the piece: under 3 the torso, under 10 the arms, otherwise the legs,
falling through to another piece if that slot is empty. The quality
loss is the blocked amount when that amount is under 4, otherwise
`blocked / Rand(1, 4)`. A piece whose quality hits the floor logs
`Armor Broke` / `Weapon Broke` through `FUN_004ab650`.

The wound is applied by `FUN_004a42d4(target, −damage, kind, attacker)`.
Kind 2 is missile, 3 is a physical rider such as poison on the swing,
5 is fire or lightning, 7 is a heal. Current health is compared with
the blow in the older damage function `FUN_0046190c`: if the blow is
at least the current health, health becomes 0 and `FUN_0045f3eb` kills
the actor. Non-permanent damage is a separate pool (`Damage` in the
save, `NonPerm Dmg` in the stat dump). Healing and rest clear it;
`Char_Rest` is the rest entry.

The cheat `Demo Damage` raises a blow that came in under half the
target's health up to that half.

---

## 11. Weapons

Two descriptions of a weapon exist, and they are not the same table.

**The item.** `MagicInvItem.txt` gives every weapon a `Weapon_Damage`
of the form `Rand(min-max)`, a `Classification` (`Bladed` and the
others), and optional ready effects (`Modifier_Attack`, `Damage_Normal`,
`Strikes_WithBladed`, …). The actor resolver rolls that item range.
Quality is `Poor`, `Average`, `Good`, `Excellent`, `Magical`
(`QLTY_*` in `RtkGame.def`). Enchanted weapons usually keep a mundane
range and add a flat bonus through an effect rather than raising the
range. The Hellblade-class items are the exception pattern: a magic
effect on the item, not a bigger `Rand`.

**The type table.** A static 13-row table at `0x5DD3C0`, stride `0x24`,
read only by `FUN_00460aca`. Nothing in the decompile writes it. The
older resolver rolls columns 0 and 1 as its damage dice, with an
exclusive upper bound (`min + rand % (max − min)`, `FUN_0045ee74`).
The actor resolver does not read this table.

| Row | Min | Max (exclusive) | Hands | vs armor 1 | 2 | 3 | 4 | Parry factor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 3 | 13 | 1 | 100 | 100 | 100 | 100 | 50 |
| 1 | 8 | 28 | 2 | 100 | 100 | 100 | 100 | 50 |
| 2 | 1 | 6 | 1 | 100 | 100 | 100 | 0 | 50 |
| 3 | 2 | 8 | 2 | 100 | 100 | 50 | 100 | 66 |
| 4 | 3 | 9 | 1 | 100 | 100 | 100 | 50 | 50 |
| 5 | 10 | 26 | 2 | 100 | 100 | 100 | 100 | 50 |
| 6 | 2 | 9 | 1 | 100 | 100 | 100 | 100 | 50 |
| 7 | 7 | 28 | 2 | 100 | 100 | 100 | 100 | 50 |
| 8 | 2 | 5 | 1 | 100 | 100 | 50 | 100 | 50 |
| 9 | 2 | 13 | 1 | 100 | 100 | 100 | 50 | 50 |
| 10 | 1 | 10 | 1 | 100 | 100 | 50 | 50 | 66 |
| 11 | 3 | 9 | 2 | 100 | 100 | 100 | 0 | 50 |
| 12 | 4 | 12 | 2 | 100 | 100 | 100 | 0 | 0 |

Hands above 1 also fills the off-hand slot (`FUN_00460ae2`). A parry
factor of 0 means no parry charge is granted (`FUN_004600da`); row 12
is the one that cannot parry. At the start of a round a weapon with a
positive factor grants one parry charge. Entering parry defense
(`FUN_00461e04`) sets the charge to 9999 and raises the parry-defense
flag. The armor percents are what fraction of the roll gets through
that armor type; armor type 0 always lets 100% through
(`FUN_00461877`). `GetArmorDamageWithMeleeWeapon` is the error string
for an unknown armor type.

Which skill a type uses, in the older resolver only (`FUN_004604f1`):
types 0, 2, 4, 9, 10 read the skill at stats `+0x5c`; types 6, 7, 8
read `+0x60`; types 1, 3, 5, 11, 12 read `+0x68`. The inventory
`WEAP_*` constants in `RtkGame.def` are a different numbering (rapier
is 13, bow is 12) and do not index this table.

Strikes per round for a player character go through `FUN_004b4bf6`.
The first argument is a weapon-class bit, the second is the value
compared against the thresholds (a level or a skill; the call site
passes a virtual-call result), and the third adds 1 when the character
is making a full attack rather than a single one.

| Class bit | 1 strike while value is | 2 strikes | 3 strikes |
|---|---|---|---|
| 1 | under 6 | under 11 | under 16, then the error return |
| 2 | under 7 | under 13 | 13 and up |
| 4 | under 11 | under 20 | then the error return |
| 8 | under 8 | under 15 | then the error return |

`FUN_0049a8d0` stores the full count, and stores `(count + 1) / 2` as
the single-attack count. Magic can add strikes per round, strikes with
a blade, or strikes with a bow (`FUN_004af991`). A weapon in the off
hand is suppressed when `No Full Left Hand` is set (`FUN_004a705c`),
except for weapon class 8, which keeps it.

---

## 12. Magic

Sixty spells, ten on each of six paths. Ids and paths are in
`RtkGame.def`.

| Path id | Name | Spells |
|---|---|---|
| 0 | Fire | Demonblade, Sunray, Fire Eater, Prandur's Touch, Fire Lance, Phoenix Blades, Fire Rain, Crown of Flame, Birthing Sun, Firestorm |
| 1 | Mind | Mind Scan, Contest of Wills, Friends, Confusion, Dispel Mind Magic, Paralysis, Domination, Mass Friendship, Mass Confusion, Mass Domination |
| 2 | Life | Minor Healing, Minor Harm, Restoration, Sung's Caress, Cure Poison, Harm, Lifedrain, Full Heal, Slay, Mass Heal |
| 3 | Divine | Blessing, Curse, Harm Undead, Divine Protection, Divine Favor, Divine Aid, Command Undead, Wrath, Great Blessing, Fate |
| 4 | Change | Improve Quality, Assessment, Armor, Weaken, Disrupt, Slow, Speed of Thought, Troll's Blood, Transform, Disintegrate |
| 5 | Storms | Lightning Blade, Shield of Winds, Thunderclap, Lightning's Touch, Teleport, Lightning Strike, Maelstrom, Shield of Lightning, Summon Air Elemental, Chaos Storm |

`MagicResult.txt` is the effect table. Each spell has a path, a caster
class (`LPMage` and the others), a level, a spell-point cost, a range
(`Touch`, `LineOfSight`), a duration (`Rounds` plus `Rand` and a
per-level increment), a resistance stat (`N/A`, `Stamina`, `Reason`,
`Agility` — the `SPELL_RESISTEDBY_*` constants), and one or more
effects. An effect is permanent, temporary, or instant; it names an
attribute (`State_Blind`, `Damage_FireSpell`, `Weapon_AddFireNormal`,
`Strikes_WithBladed`, …) and a value that is either flat or
`Rand(min-max)`, sometimes scaled by caster level.

Range and area constants in `RtkGame.def`: none, touch, line of sight,
field; one ally, one enemy, all allies, all enemies, a 30-foot circle,
special, self.

### How a modifier changes a number

Every persistent bonus and penalty is a four-int record. `FUN_004af5ce`
fills it from the active effects. `FUN_0049b660` applies it.

| Offset | Meaning |
|---|---|
| +0 | a flat value is present |
| +4 | the flat value, positive or negative |
| +8 | a ratio is present |
| +12 | the ratio. 100 leaves the number alone |

The flat value is added first. A positive number is not allowed to cross
below 0, and a negative number is not allowed to cross above 0. A 0
just receives the flat value, so it can become negative. The ratio is
applied second:

| Ratio | Result |
|---|---|
| 0 | 0 |
| 50 | `(n + 1) / 2` |
| 150 | `n + (n + 1) / 2` |
| 200 | `n * 2` |
| anything else | `(n * ratio) / 100`, rounded by adding 0.5 before truncating |

`Effect_AttrMod : Value` fills the flat half. `Ratio` fills the other.
Both can be present on one record. The log line is `Value : N Ratio : M`.

### Resistance

The resist stat is the spell field at `+0x40`. `FUN_004918aa` prints it:
0 none, 1 Agility, 2 Reason, 3 Stamina. The roll logs `Resist Chance`
and `Resist Roll`:

```
chance = focus + Resist_Base + attribute band + (defender level − caster level) * 5
```

`Resist_Base` is the spell field at `+0x50`. Focus is `DAT_00629e68`,
the second game-mode trio: Focus Magic adds 10, Focus Balanced adds 25,
Focus Combat adds 50. The attribute band is `FUN_004b64e1`: −20 below 0,
then −15, −10, −5, 0 across 0–70, then +5, +10, +15, +25, and +30 from
151 up. The defender resists when `d100 <= chance`.

`FUN_004afedc` then adds magical resistance on top of that margin.
`Resist_Bonus` (the pair at effect `+0xec`) always counts. `Resist_Undead`
(effect `+0x2ac`) counts when the defender is undead. A mind-resistance
pair at effect `+0x27c` counts when the spell's field at `+0x1c` is 4.
A positive bonus makes the effect easier to resist, except under
`ForEffect`, where the same bonus is added to the roll instead.

`Effect_Resist` (`+0x30`) says what a successful resist does:

| Id | Name | On a resist |
|---|---|---|
| 0 | `NoEffect` | the effect's value is set to 0 |
| 1 | `ForEffect` | the value is set to 0, but the bonus helps the spell instead of the defender |
| 2 | `HalfEffect` | the value becomes `(value + 1) / 2`, and the effect still lands |

`Effect_Check` (`+0x34`) says whether that roll runs:

| Id | Name | |
|---|---|---|
| 0 | `NoCheck` | the effect lands, no roll |
| 1 | `OnCast` | the roll above |
| 2 | `OnCast_NoCheck` | lands, no roll |
| 3 | `PerRound` | the roll is repeated |
| 4 | `ReleaseWithTarget` | lands, no roll |
| 5 | `IfMage` | only an LPMage (class bit 4) is affected |
| 6 | `IfMagic` | only a caster (bit 4 or 8) is affected |
| 7 | `OnCastFromMagic` | the roll, and only against a caster |
| 8 | `IfInCombat` | nothing happens out of combat |
| 9 | `IfOutCombat` | nothing happens in combat |

A dead target is skipped. `Mgc Resist All` and `Mgc Resist None` force
the result after the roll.

Casting during a fight is an order (section 4). A slow cast can be
interrupted (`Slow Cast Spell was Disrupted`). Quick cast waits for
the on-hit callback. `OnTargetHit` either applies the spell, reports
it resisted, or waits out a duration (`FUN_0048c122`, `FUN_0048ee88`).
The cast clip, the `.bex`, and the target's flinch share that callback.
How they line up is in [`animations.md`](animations.md) §6.
Spell points are the pair in the save (`current, max`). `Ignore
SpellPts` is a cheat. Level-up spell-point gains are in section 14.

Out of combat the same table drives scrolls, wands, and potions. A
potion is an item whose effect uses the same attribute vocabulary.

---

## 13. Conditions

The five states are flags the magic scan writes (section 16). What
combat does with each one:

| State | Combat effect |
|---|---|
| Blind | −40 attack value, the target counts as helpless (no style, no agility band, no parry or block), and move speed is multiplied by 0.33 |
| Paralyzed | Helpless, same as blind for defense and for the parry and block attempts. Does not take the −40 |
| Stunned | Helpless for the "cannot act" bit (slot 1, shared with paralyzed). −25 attack value, −25 parry, −25 block |
| Confused | Excluded from ally and target lists that also skip the helpless (`FUN_0049c957` and the protect scan). Not a to-hit penalty of its own |
| Poison | The flat value on `State_Poison` is added into the running per-round at effect `+0x35c` by `FUN_004b31cd`. Immunity clears that total |

`FUN_004b2eed` is the clock that spends those totals. The world timer
(`FUN_004bad40`) calls it once per 5 minutes of game time that have
piled up, and only while the combat manager's `+0x84` is 0. Each call
passes how many 5-minute chunks elapsed.

- Regeneration rounds at effect `+0x358` heal `((max health + 3) / 4) * chunks` (wound kind 8) and the counter drops by that many chunks.
- Poison at `+0x35c` deals `perRound * chunks` (kind 6). If health is then below 2, the poison is cleared and the log is `Poison Wore Off`.

Troll's Blood is the `Health_Regeneration` pair, not a sixth state.
When `FUN_004b31cd` sees that pair it logs `Trollish Blood`, heals the
actor to full (kind 8), and clears the cached pair. The save field is
`TrollishBloodRounds`.

Charm is `FUN_0047769f` (`Rule : Charm End Combat`). If one side is
reduced to a single charmed combatant who can still act, that
combatant is hit for 99999, the fight ends, and the survivor is kept.

Parry defense is the flag at `+0x128`. It adds the agility term to
defense and adds 25 to the parry score. It does not by itself negate a
swing. A covered defender (`FUN_004a70a9`) gains +20 missile defense
and is the only defender who can block; that same flag makes a parry
refuse.

`Walked into a Guarding Enemy` (`FUN_0049c2b0`) is the interrupt for
moving onto a character who is holding guard.

---

## 14. Death, experience, level

Health at 0 removes the actor (`FUN_0045f3eb` on the older path;
`FUN_004a42d4` is the call the actor path uses to apply the signed
change). When no one on the party side can act, `FUN_0043bd35` logs
`The Party is dead. Replay combat` and offers the replay callback
`FUN_0043bdb9`.

`FUN_004abf9f` adds experience to the pool at `+4`, capped at 999998.
While the pool is at least the next threshold (`FUN_004ac160`, a
per-level table indexed from the record at `+0x10`), it:

- adds 100 advancement points (the `+8` field, `AdvancementPts` in the save)
- sets all 22 advancement limits (`+0x14`, 22 dwords) to 30
- calls `FUN_004a32db`

`FUN_004a32db` increments level at actor `+0x5c`, then grows the two
pools:

| Class bit | Health gained | Spell points gained |
|---|---|---|
| 1 Warrior | `Rand(10, 15)` | none |
| 2 Thief | `Rand(8, 12)` | none |
| 4 LPMage | `Rand(5, 8)` | `Rand(4, 6)` |
| 8 Priest | `Rand(9, 13)` | `Rand(3, 5)` |

Any other bit hits the default and calls `FUN_004b6640` instead of
rolling. The class value is the keyword id from section 3, read back
through virtual `+0xfc` (`FUN_004ab7e0` returns the short at definition
`+0x50`).

Health also adds the stamina band `FUN_004b6206` (about −4 at the
bottom to +6 at the top, 0 across the middle). Spell points add
`FUN_004b6304` of the third attribute the level-up call reads, a
smaller band from −3 to +4. Both `Rand` calls are inclusive.

---

## 15. Presentation

How a pose, a flinch, and a spell graphic are actually played is in
[`animations.md`](animations.md). Combat poses in `RtkGame.def` are frame
ranges on the character tracks:
idle fight, dodge, punch high and low, throw, draw, hack, slash high
and low, thrust high and low, death, attack spell, personal spell.
The A set and the B set are the two bodies. `FUN_004480ec` is the
animation entry that logs `kCombatAnimCharacterAttack`.

The fight UI is the attack menu, the spell casting screen, and the
weapon popup. `CombatStats` and `CombatSpeed` are the two options
written to the ini by the options screen. `SetCombatSpeed` is also a
console verb. The combat log (`DAT_006721c8`) is what prints
`Chance To Hit`, `Attack Value`, `Defense Value`, and the swing line
when combat statistics are on.

Cheats registered while combat initializes (`FUN_005044f3`), each a
toggle: `Ignore Damage`, `Mgc Quick Always`, `Mgc Quick Never`,
`Mgc Slow Always`, `Mgc Slow Never`, `Mgc Resist All`, `Mgc Resist
None`, `God Mode` per companion and for the good side and the bad
side, `Ignore SpellPts`, `Win Initiative`, `No Enemy AI`,
`Show All Spells`, `Demo Dice`, `Kill Topgun`, `Kill Topgun Spells`,
`No Mgc Space Checks`, `No Mgc Queue Checks`, `Revive Enemies`,
`Revive Full Health`, `Min Magic Duration`, `Mgc Keep OnRelease`,
`Items Assessed`, `Ctrl Q`, `Experience`, `Fate Condition Off`.

Swing, hit, block, and death samples are the `CVHit*`, `CVAttacking*`,
`CVDying*` entries in `RtkGame.def`, one trio per body: man, woman,
James, Kendaric, Solon, vampire, demon, goblin, goblin leader, shaman,
warlord. `eAudio_WaveCombat` is the mixer channel.

---

## 16. Editing effects and classes

Text mods already rewrap `MagicResult.txt`, `MagicInvItem.txt`, and
`Chars.tbl`. The executable will not grow a new status or a new class
from a new word in those files.

### Status effects

Spell effects are an 85-name table in the executable at `0x5f6a30`
(`Modifier_Armor` is id 1, `Damage_BlockNormBackLight` is id 85).
`FUN_004f9865` looks the `Effect_AttrType` word up with `FUN_004b9450`.
`FUN_004e9ea0` accepts ids 1 through 85 and turns anything else, including
a failed lookup (−1), into 0. Id 0 is never scanned, so a new name is
stored and then ignored.

While an effect is active, `FUN_004b32db` ("Perform Magic Scan On")
copies specific ids into fixed slots on the actor's effect block at
`+0x18c`. The five states are:

| Effect | Id | Slot written | What combat does with it |
|---|---|---|---|
| `State_Blind` | 26 | `0xb6`, and slot 7 | −40 attack value. The target counts as helpless |
| `State_Confusion` | 27 | `0xb8`, and slot 4 | announced; the combat penalty is the slot-4 bit shared with other effects |
| `State_Paralyzed` | 28 | `0xb4`, and slot 1 | helpless. Slot 1 is the "cannot act" bit |
| `State_Poison` | 29 | modifier pair at `0x4b` | per-round poison. `PoisonDmgPerRnd` in the save |
| `State_Stunned` | 30 | `0xba`, OR'd into slot 1 | helpless, and −25 on the parry and block scores |

The matching immunities are the same scan: `Immune_Blindness` 69,
`Immune_Confusion` 70, `Immune_Paralysis` 71, `Immune_Stunning` 72,
`Immune_Poison` 73. Poison immunity also clears the poison amount.
`FUN_004972cd` prints Blinded / Confused / Paralyzed / Poisoned /
Stunned when the effect is up and the query is still clear.
`FUN_00498f93` prints the "wore off" lines.

The same scan also wires the modifiers you can retune without new code:
`Modifier_Armor`, `Modifier_Attack`, `Modifier_Defense`,
`Modifier_MoveRate`, `Strikes_PerRound`, `Attribute_Strength`, the
`Damage_Block*` family, `Resist_Bonus`, `Resist_Undead`,
`Health_Regeneration`, `Weapon_AddFireNormal`, `Weapon_AddNormalDamage`,
`Weapon_AddHitChance`, `Weapon_AddPoisonDamage`, `Magic_CasterLevel`.
Instant results (heals, direct damage, the five `Dispel_*` ids) are
applied at cast time, not by this scan.

What a text edit can do:

- Change duration, cost, range, resist stat, and the rolled value on a
  spell that already uses one of those names. Sunray is the pattern:
  `Effect_AttrType : State_Blind`, `Effect_Result : Temporary`,
  `Duration_Value : Rand(1-2)`.
- Add another `Effect` block to an existing spell, still using a name
  from the 85.
- Put `Immune_Poison` (or any other wired name) on an item or spell
  that did not have it.
- Author a new spell record that points at an existing `Effect_AttrType`
  and an existing `Magic_Class` (`Rogue`, `Warrior`, `Priest`, or
  `LPMage` — `FUN_00440d26` stores those as 0, 1, 2, 3). The behavior
  file (`.bex`) is a separate asset; the numbers work without one only
  as far as the effect id itself is wired.

What it cannot do: a sixth state. There is no empty slot. A new word
never reaches `FUN_004b32db`, and the apply text, the clear text, the
queries (`FUN_004aed54` blind, `FUN_004aed78` paralyzed, `FUN_004aed9c`
confusion, `FUN_004aedc0` stun, `FUN_004aede4` poison), and the combat
math each name these five ids.

Item enchantments are a second closed table, at `0x5f30f0`, about 104
names starting at `Armor_Enchanted`. `FUN_004f8407` looks them up and
`FUN_004dc89d` whitelists the ids. An unknown word hits the default and
becomes id `0x2a`, which is `Modifier_Attack`. A typo on an item
modifier silently grants an attack bonus.

### Classes

Changing class in data means editing the first word of `Class :` in
`Chars.tbl` to one of the nine names above, and optionally the two
style percents. Level-up health and spell points follow the bit, so
turning a warrior into `LPMage` also switches them to the mage row in
section 14. Skills, attributes, weapons, and `AttackParam` are ordinary
fields on the same record.

Adding a class (a ranger, a sixth caster) needs a new row in the
keyword table, a new case in `FUN_004c49fc` (anything outside the nine
ids is stored as 0), new cases in `FUN_004b616d` and `FUN_004b6283`,
and a decision in `FUN_004c6cea` if the class casts. Spell
`Magic_Class` only has the four names above; a new caster class would
not match any spell until that parser grew a fifth name. Item "Users:"
would not list the new class until `FUN_004942db` did.

---

## 17. What is not pinned down

- **The 22 skill names.** Pinned in section 3. Bladed is line 1, Bow
  is line 5, Shield is line 15.
- **The class ids 0–7 in the initiative table.** They are not the
  warrior/rogue/priest/mage bits. The bit assignment for those four is
  solid; the initiative switch is a different enum.
- **Which authored `AttackParam` field feeds which runtime stat.**
  The column layout is visible (strikes, a damage range, a trailing
  50). The parser that copies it onto the actor was not walked.
- **The experience threshold table.** Dumped in
  [`encounters.md`](encounters.md): the four class tables, the companion
  starting pools, and the kill-experience split.
- **The virtual call that fills weapon min and max** (`+0x14c` inside
  `FUN_004a70e3`). The style scale and the inclusive roll after it are
  clear. The decompiler dropped the store into the two range locals.
- **Armor piece ratings inside `FUN_004b55d1`.** The absorption formula
  that calls it is in section 10. The per-piece rating and quality
  fields it returns were not opened.
- **The float step between the parry halving and the encumbrance
  ratio.** The integer score in section 9 is what the decompile builds.
  A `ftol` sits on it before `FUN_004b2ece`, and that instruction was
  not opened. The `d100` compare after it is `roll <= score`.
- **Whether `James Loses Initiative` is intentional.** It is
  unconditional on odd rounds. No design comment survives next to it.
