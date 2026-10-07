# Alchemy and potions

How a potion is learned, brewed, and used. The catalog rows live in
`MagicInvItem.txt`. The forty formulas live in a table compiled into
`RtK.exe` at `0x612e28`, one `0x38`-byte record each. The blank
experiment page is a separate template at `0x613790`. What a finished
potion does in a fight is the spell record in `MagicResult.txt`,
reached from the item's `Effect_Spell`.

Item instances, stacks, and `PutItemInInventory` are in
[`inventory.md`](inventory.md). The combat clip for a thrown flask is
in [`animations.md`](animations.md). Nothing here writes to the game
install.

Function names are the stable citations. `RtK.c` line numbers move
every time the decompile is regenerated;
`python tools/show_func.py out/decompiled/RtK.c FUN_00554870` re-finds
one.

---

## 1. The shape of it

A Lesser Path mage brews on the party book's alchemy bench. The book
holds one shared list of known formulas. Two mages do not keep
separate notebooks.

A formula is one of three things:

| State | How it got there | Skill roll when brewed from its page |
|---:|---|---|
| 0 | Unknown. The page is skipped | |
| 1 | A recipe item was used, or it is one of the three formulas a new game starts with | No roll. The brew succeeds once level and ingredients pass |
| 2 | The mix was discovered on the blank page | Roll, disaster weight `0.1` |
| 3 | The blank experiment page only | Roll, disaster weight `0.2` |

Using a recipe writes state 1 even if the formula was already
discovered at state 2, so a scroll makes a risky formula safe.
`FUN_005553b4` is that write. The field is record `+8`.

A new game (`FUN_0054e02f`, from `FUN_0043b93d`) clears every formula
and then sets three of them to state 1:

| Record | Formula | Level required |
|---:|---|---:|
| 0 | Weak Potion of Healing | 1 |
| 32 | Weak Protection from Fire | 2 |
| 36 | Weak Antidote | 1 |

Jazhara does not carry those three scrolls. The flags are already set.

---

## 2. Who may brew

`FUN_00547b30` requires class bit 4, `LPMage`. Jazhara and Kendaric are
the two companions with that bit. James, William, and Solon fail the
test, so the bench will not take their ingredients.

The bench has four columns (`FUN_00547925`):

| Column | Companion |
|---:|---|
| 0 | James |
| 1 | Jazhara |
| 2 | William, or Kendaric if he is the one found first in the party list |
| 3 | Solon |

Only columns 1 and 2 keep a working mix (`DAT_00613838` and
`DAT_00613870`). Column 2 is one slot shared by William and Kendaric.
`FUN_005479a7` walks the party and returns whichever of those two it
meets first. If William is ahead of Kendaric, that column is William,
and the mage test fails.

Alchemy is skill line 13 in the `Skills` list on a character. The other
21 lines are in [`combat.md`](combat.md) section 3. It is stored
as a short at actor `+0x9e`. The starting values:

| Companion | Level (`Attribute` field 0) | Alchemy |
|---|---:|---:|
| James | 3 | 0 |
| Jazhara | 2 | 20 |
| William | 3 | 0 |
| Kendaric | 5 | 60 |
| Solon | 6 | 0 |

The brew roll does not read `+0x9e` raw. It calls virtual `+0xac`
(`FUN_004a6b4a`), the same adjusted value the character sheet shows.
That getter starts from `+0x9e` and then applies the bonus block at
character `+0x3c8`. The only shipped `Attribute_Alchemy` grant is the
Alchemist's Ring, a flat `+35` (`Effect_Modify : Value`, despite the
blurb saying "percent"). The equip path that would drop that `+35`
into `+0x3c8` was not walked; the applier itself stores the modifier
at `+0x23c` of its target (`FUN_004b0cea`, case `0x0a`).

---

## 3. The bench

Fourteen reagents and six tools are the bench. Each reagent is a
stack (`Aggregate : True`). The bench identifies a reagent by its
catalog `UniqueID`, read back from the item definition at `+0x40`
(`FUN_004db828`). `FUN_0055547c` maps those ids onto fourteen slots.
A formula stores the slot numbers, and `0x14` means that slot is empty.

| Slot | Item | `UniqueID` | Tool the slot requires |
|---:|---|---:|---|
| 0 | Essential Saltes | 132 | Dissolution Mixer, and the Retrieval Apparatus when the saltes are placed by hand |
| 1 | Aqua Fortis | 130 | Infusion Bottle |
| 2 | Aqua Regia | 131 | Infusion Bottle |
| 3 | Powdered Fennel | 133 | Mortar and Pestle (`Base Labratory`) |
| 4 | Fire Lotus Dust | 134 | Mortar and Pestle |
| 5 | Vampire Ashes | 136 | Mortar and Pestle |
| 6 | Powdered Opal | 135 | Mortar and Pestle |
| 7 | Elixir of Bloodwine | 137 | Distillation Chamber |
| 8 | Essence of Ergot | 138 | Distillation Chamber |
| 9 | Tincture of Vitriol | 139 | Distillation Chamber |
| 10 | True Copper | 140 | Crucible (`Melting Pan`) |
| 11 | True Lead | 142 | Crucible |
| 12 | True Gold | 143 | Crucible |
| 13 | True Iron | 141 | Crucible |

The tool names in parentheses are the assessed names. The catalog
keys keep the original spelling: `Base Labratory`, `Retrieval
Aparatus`, `Essential Saltes`, `Stength_Weak` on Aqua Fortis. Those
tokens are what the executable's keyword table matches.

Every formula uses Essential Saltes. Weak and strong are the same
recipe with Aqua Fortis swapped for Aqua Regia. Fortis is the weak
aqua (`Classification : Stength_Weak`, 15 sovereigns). Regia is the
strong aqua (`Strength_Strong`, 45 sovereigns).

The Flask (`UniqueID` 144) is a stack with a two-sovereign price and
a description about a bottle deposit. No formula slot maps to 144, so
a brew does not consume a flask. `Chocha` reuses `UniqueID` 144 and
`Classification : Container`. It is an herbal joke item, not a
fifteenth reagent.

Placing an ingredient by hand is `FUN_0055339a`, and it only accepts
drops onto the blank page (`record + 4 == 0x4f`) from a mage.
`FUN_00556661` checks the tool. The known-recipe buttons do not use
that drop path. They call `FUN_00551c9e`, which pulls the formula's
own ingredients out of the mage's stack, after `FUN_00556681` has
checked the tools those slots need. That check covers the mixer,
infusion bottle, mortar, still, and crucible. It does not ask for the
Retrieval Apparatus. Dragging saltes onto the blank page does.

The four dose buttons are controls `0x7f0` through `0x7f3`: one dose,
one dose, two doses, three doses. Each dose is one potion and one of
every reagent in the formula. The success callback creates that many
item instances (`FUN_00554e01`) and marks each one assessed.

---

## 4. One brew

The confirm control is `0x428` (`FUN_0054fdd0`).

The mage picks an hour on a 12-hour face (`FUN_0055034a`). If the
chosen hour is not later than the current hour, the wait wraps by 12
hours. A wait under 4 hours is refused (string id `0x42e`) and nothing
is consumed. A scheduled world event that falls inside the wait can
shorten it (`FUN_004bd25a`). If that shortened wait is still under 4
hours, the staged reagents of both mage columns are destroyed and time
passes, with no potion.

Otherwise `FUN_00554870` resolves the brew.

1. **Blank page, no matching formula.** The five slots are compared
   with every real formula (`FUN_00554a58`). No match rolls the skill
   check at weight `0.2`. Failure plays the fail animation. A disaster
   also breaks tools first (`FUN_00556913`).
2. **Blank page, matching formula.** If that formula was still
   unknown, its state becomes 2, so the page appears in the book.
   The potion produced is that formula's item. The roll still uses
   weight `0.2`, because the working page is still the blank page.
3. **Level.** Virtual `+0x108` is the character's level (actor
   `+0x5c`, `FUN_004ab840`). Below the formula's level, string id
   `0x429` is shown and time still passes. The reagents are not
   destroyed on this path.
4. **Skill.** State 1 skips the roll. State 2 rolls at `0.1`. State 3
   rolls at `0.2`. See the next section.
5. **Finish.** The success animation's script (`0xbf0`,
   `FUN_00554e01`) deletes the staged reagent counts and creates the
   potions. The fail animation's script (`0xe9c`, `FUN_00555248`)
   deletes the reagents and shows the failure line. Dismissing either
   message advances the clock by the chosen wait (`FUN_00554762`).

A success sound, a fail sound, and a breakage sound are
`IfaceAlchBrewWork`, `IfaceAlchBrewFail`, and `IfaceAlchBrewFailBreak`
in `RtkGame.def`. The pour animation is one of six queues, chosen by
the formula's byte at `+0x30`. Two doses and three doses play extra
flask queues on top of that (`FUN_0055446b`).

### The roll

`FUN_00556840` draws a uniform integer from 1 through 101 with
`FUN_004894fb`, the same roller the lock screen uses. The skill is
the adjusted alchemy value.

The brew succeeds when the roll is less than or equal to the skill.
A skill of 100 still fails on a roll of 101. A skill of 101 or more
does not fail this check.

On a failed roll the same function decides whether the tools break.
With `margin = 100 - skill` and `cut = trunc(margin * weight)`:

- the failure is ordinary when the roll is below `100 - cut`
- the failure is a disaster otherwise

`weight` is the `0.1` or `0.2` above. Truncation is toward zero.
Jazhara at 20, experimenting (`0.2`), succeeds on 1–20, fails
plainly on 21–83, and breaks tools on 84–101. The same skill on a
discovered formula (`0.1`) breaks tools only on 92–101. Kendaric at
60, brewing a recipe he learned from a scroll, does not roll at all.

A disaster then draws a second uniform integer, 1 through 100
(`FUN_004894c8`), and breaks tools from this table. The dissolution
mixer survives every roll except 100, which breaks all six tools.

| Roll | Tools broken |
|---:|---|
| 1–7 | Mortar |
| 8–15 | Infusion Bottle |
| 16–23 | Crucible |
| 24–31 | Retrieval Apparatus |
| 32–39 | Distillation Chamber |
| 40–43 | Mortar, Infusion Bottle |
| 44–47 | Mortar, Crucible |
| 48–51 | Mortar, Retrieval Apparatus |
| 52–55 | Mortar, Distillation Chamber |
| 56–59 | Infusion Bottle, Crucible |
| 60–63 | Infusion Bottle, Retrieval Apparatus |
| 64–67 | Infusion Bottle, Distillation Chamber |
| 68–71 | Crucible, Retrieval Apparatus |
| 72–75 | Crucible, Distillation Chamber |
| 76–79 | Retrieval Apparatus, Distillation Chamber |
| 80–81 | Mortar, Infusion Bottle, Crucible |
| 82–83 | Mortar, Infusion Bottle, Retrieval Apparatus |
| 84–85 | Mortar, Infusion Bottle, Distillation Chamber |
| 86–87 | Mortar, Crucible, Retrieval Apparatus |
| 88–89 | Mortar, Crucible, Distillation Chamber |
| 90–91 | Mortar, Retrieval Apparatus, Distillation Chamber |
| 92–93 | Infusion Bottle, Crucible, Retrieval Apparatus |
| 94–95 | Infusion Bottle, Crucible, Distillation Chamber |
| 96–97 | Infusion Bottle, Retrieval Apparatus, Distillation Chamber |
| 98–99 | Crucible, Retrieval Apparatus, Distillation Chamber |
| 100 | All six |

Broken tools are deleted from the mage (`FUN_00556754`).

---

## 5. The forty formulas

Level is the character level the brew requires. Price is the potion's
catalog price in sovereigns, not the cost of the reagents. The reagent
order is Saltes, the aqua, then the remaining slots. A dash is an
empty slot.

| Potion | Lvl | Price | Reagents |
|---|---:|---:|---|
| Weak Potion of Healing | 1 | 150 | Saltes, Fortis, Fennel, Bloodwine |
| Strong Potion of Healing | 3 | 300 | Saltes, Regia, Fennel, Bloodwine |
| Resin of Repair | 1 | 240 | Saltes, Fortis, Fennel, Copper |
| Resin of Total Repair | 3 | 450 | Saltes, Regia, Fennel, Copper |
| Weak Potion of Abjuration | 3 | 105 | Saltes, Fortis, Fennel, Ergot |
| Strong Potion of Abjuration | 4 | 410 | Saltes, Regia, Fennel, Ergot |
| Fire Oil | 3 | 345 | Saltes, Fortis, Lotus, Vitriol, Copper |
| Strong Fire Oil | 5 | 515 | Saltes, Regia, Lotus, Vitriol, Copper |
| Weak Potion of the Beast | 3 | 540 | Saltes, Fortis, Opal, Bloodwine, Lead |
| Strong Potion of the Beast | 5 | 1140 | Saltes, Regia, Opal, Bloodwine, Lead |
| Weak Lightning Shield | 2 | 300 | Saltes, Fortis, Lotus, Bloodwine, Iron |
| Strong Lightning Shield | 4 | 600 | Saltes, Regia, Lotus, Bloodwine, Iron |
| Grease of Poison | 1 | 225 | Saltes, Fortis, Bloodwine, Lead |
| Grease of Deadly Poison | 3 | 375 | Saltes, Regia, Bloodwine, Lead |
| Holy Balm, weak | 1 | 275 | Saltes, Fortis, Vampire Ashes, Vitriol |
| Holy Balm, strong | 3 | 510 | Saltes, Regia, Vampire Ashes, Vitriol |
| Magical Blade Grease | 2 | 465 | Saltes, Fortis, Ergot, Copper |
| Enchanted Blade Grease | 4 | 1200 | Saltes, Regia, Ergot, Copper |
| Resin of Quality | 3 | 2250 | Saltes, Fortis, Opal, Copper |
| Resin of Maximum Quality | 5 | 3800 | Saltes, Regia, Opal, Copper |
| Potion of Spellcasting | 3 | 690 | Saltes, Fortis, Ergot, Gold |
| Great Potion of Spellcasting | 5 | 1800 | Saltes, Regia, Ergot, Gold |
| Weak Potion of Magic | 3 | 1500 | Saltes, Fortis, Opal, Ergot, Gold |
| Strong Potion of Magic | 5 | 3000 | Saltes, Regia, Opal, Ergot, Gold |
| Weak Potion of Regeneration | 2 | 450 | Saltes, Fortis, Fennel, Bloodwine, Gold |
| Strong Potion of Regeneration | 4 | 1200 | Saltes, Regia, Fennel, Bloodwine, Gold |
| Potion of Strength | 2 | 432 | Saltes, Fortis, Bloodwine, Gold |
| Potion of Might | 3 | 1025 | Saltes, Regia, Bloodwine, Gold |
| Weak Protection from Magic | 1 | 345 | Saltes, Fortis, Ergot, Iron |
| Strong Protection from Magic | 3 | 825 | Saltes, Regia, Ergot, Iron |
| Weak Protection from Undead | 1 | 240 | Saltes, Fortis, Vampire Ashes, Iron |
| Strong Protection from Undead | 3 | 345 | Saltes, Regia, Vampire Ashes, Iron |
| Weak Protection from Fire | 2 | 285 | Saltes, Fortis, Lotus, Iron |
| Strong Protection from Fire | 4 | 630 | Saltes, Regia, Lotus, Iron |
| Weak Iron Skin | 2 | 430 | Saltes, Fortis, Vitriol, Iron |
| Strong Iron Skin | 4 | 1200 | Saltes, Regia, Vitriol, Iron |
| Poison Antidote | 1 | 150 | Saltes, Fortis, Fennel, Bloodwine, Lead |
| Strong Antidote | 3 | 375 | Saltes, Regia, Fennel, Bloodwine, Lead |
| Weak Potion of Striking | 2 | 525 | Saltes, Fortis, Vitriol, Gold |
| Strong Potion of Striking | 4 | 1050 | Saltes, Regia, Vitriol, Gold |

The recipe scroll's `Description` names the same reagents. Each scroll
is `Category : Recipe`, `SubCategory : UseByMage`, `UniqueID` 250, one
use, and its effect is `LearnPotion_*`. That modifier is what calls
`FUN_005553b4`. Unread, every scroll shows as "Recipe for a Potion".

Jazhara starts with no scrolls. Her laboratory is a draw of three
pairs: Mortar or Crucible, Retrieval Apparatus or Infusion Bottle,
Distillation Chamber or Dissolution Mixer. She also starts with 6–10
each of Aqua Fortis and Essential Saltes, and 7 of Fennel, Fire Lotus
Dust, Bloodwine, Ergot, Vitriol, Copper, Iron, and Lead. She does not
start with Aqua Regia, Powdered Opal, Vampire Ashes, or True Gold.

Kendaric starts with all six tools, 10 Saltes, 8 Fortis, and 12 of
that same reagent list. His five scrolls are Fire Oil, Resin of
Quality, Potion of Might, Strong Antidote, and Weak Potion of
Striking.

In `KrondorShops.def` the third number on a shop row is the starting
stock. Aaron's Fine Weapons stocks flasks and a shelf of finished
potions. Argus and Fred's stock flasks. Gari's and Kraack's list
every reagent, every tool, and all forty scrolls, and most of those
rows start at 0. The Gari scrolls that start at 1 are Resin of
Repair, Weak Beast, Grease of Poison, Enchanted Blade Grease, Strong
Potion of Magic, Potion of Might, Weak Protection from Undead, Strong
Protection from Fire, and Weak Potion of Striking. The Golden
Grimmoire stocks the reagents in quantity, all six tools, and most of
the scrolls. Gerard's Luxury Goods stocks reagents and one mortar;
its other tools start at 0. In `HaldonShops.def`, HH General Store and the Witch Hut both stock
the reagents and all six tools. The Witch Hut is the shelf that
starts with Vampire Ashes in stock.

---

## 6. What a potion does

Every brewed potion is one use (`Effect_CastMax : 1`).
`Effect_NonCombat : 1` can be used on the map. `0` is a combat use.
The numbers below are the spell or modifier the engine applies.
Where the item blurb disagrees, the blurb is in the note.

A ratio is the share of the original that remains, in percent.
`50` leaves half, `25` leaves a quarter, `0` leaves none, `200`
doubles, `300` triples.

### Drunk or applied on the map

| Potion | Effect |
|---|---|
| Weak Healing | `Health_Grant` `Rand(20-30)` |
| Strong Healing | `Health_Grant` `Rand(40-60)` |
| Resin of Repair | `Item_QualityImprove` by 100, toward the next 100-point grade. The blurb's example is 63/300 becoming 100/300 |
| Resin of Total Repair | `Item_QualityRestore` to the item's original quality. The modifier value is 400 |
| Resin of Quality | `Item_QualityUpgrade` by 100, one grade |
| Resin of Maximum Quality | `Item_QualityMakeExcellent` to the excellent grade. The modifier value is 400 |
| Potion of Spellcasting | `Magic_GrantSpellPt` 20 |
| Great Potion of Spellcasting | `Magic_GrantSpellPt` 50 |
| Weak Regeneration | Immediate `Health_Grant` `Rand(15-20)`, then 5 health each round for the battle |
| Strong Regeneration | Immediate `Health_Grant` `Rand(45-60)`, then 15 health each round for the battle |
| Weak Antidote | `Dispel_Poison` |
| Strong Antidote | `Dispel_Poison`, then `Immune_Poison` for the battle |
| Potion of Poison | Not a brew. `State_Poison` for `Rand(2-5)` rounds at `Rand(5-15)`, plus an immediate `Damage_Poison` `Rand(5-15)`. Catalog price 75 |

### Combat, on the drinker

| Potion | Effect |
|---|---|
| Weak Abjuration | `Dispel_Blindness` and `Dispel_Stunning` only. The blurb also mentions paralysis. There is no spell record for the weak potion |
| Strong Abjuration | Those two dispels, plus immunity to blindness, stunning, confusion, and paralysis for the battle |
| Weak Beastwalk | Transform the mage into a sewer monster for the battle (`zchabea.bex`). Anyone who is not a Lesser Path mage also takes `Rand(5-10)` |
| Strong Beastwalk | The same transform, plus `Health_Grant` `Rand(25-60)`, plus `Rand(7-12)` to a non-mage. The blurb says full health |
| Weak Lightning Shield | 5 rounds. Normal damage taken is halved, normal fire damage is reduced to none, and a melee hit is reflected as fire at ratio `100`. Behavior `zsto2shiw.bex`. The catalog name is Fire Shield; the assessed name is Lightning Shield |
| Strong Lightning Shield | The same three modifiers for the whole battle. The spell text says the reflected fire has no resistance check. The item blurb still mentions a resistance check |
| Weak Magic | Caster level `+3` for the battle. A non-caster takes `Rand(5-10)` |
| Strong Magic | Caster level `+6` for the battle. A non-caster takes `Rand(7-12)`. The blurb says the drinker casts as level 20 |
| Strength | `Attribute_Strength` `+30` for the battle |
| Might | `Attribute_Strength` `+50` for the battle |
| Weak Magic Protection | `Resist_Bonus` `+25` for the battle |
| Strong Magic Protection | `Resist_Bonus` `+50` for the battle |
| Weak Undead Protection | Undead damage taken at ratio `50`, undead resistance `+25`, for the battle |
| Strong Undead Protection | Undead damage taken at ratio `25`, undead resistance `+50`, for the battle |
| Weak Fire Protection | Normal fire damage taken at ratio `0`, spell fire at ratio `50`, for the battle |
| Strong Fire Protection | Both fire channels at ratio `0` |
| Weak Iron Skin | `Modifier_Armor` `+15` and normal damage blocked `+3`, for the battle. The written description says defense 25 |
| Strong Iron Skin | `Modifier_Armor` `+30` and normal damage blocked `+6`. The written description says defense 50 |

### Put on a weapon, or thrown

| Potion | Effect |
|---|---|
| Grease of Poison | The weapon adds `Rand(2-8)` poison for 4 rounds. Behavior `zfir2dem.bex` |
| Grease of Deadly Poison | The weapon adds `Rand(6-12)` poison for the battle. The blurb says 10–30 a round |
| Magical Blade Grease | `+15` to hit and `+5` damage for the battle. The blurb says "+15 percent" |
| Enchanted Blade Grease | `+35` to hit and `+10` damage for the battle |
| Weak Striking | Damage the drinker deals, before armor, at ratio `200` for the battle |
| Strong Striking | The same channel at ratio `300` |
| Fire Oil | Thrown. One enemy, `Damage_FireNormal` `Rand(25-50)`. Behavior `zpotfoil.bex` |
| Strong Fire Oil | Thrown. One target, `Rand(35-65)` fire, same behavior. The blurb says a 30-foot area. The spell record's target is a single `Target` |
| Holy Balm, weak | Thrown at undead. That undead takes rolled damage at ratio `200` for the battle. Behavior `zpotpalm.bex` |
| Holy Balm, strong | The same, at ratio `300` |

The Thaumaturical Catalyst (`UniqueID` 151, price 1200,
`Classification : PotNonBrewRemy`) is a potion in the catalog and has
no use effect and no formula. Its text says it counters evil magic.
The bench does not produce it.

`Item_PoisonDeath` (9999 poison damage, `zfir2lan.bex`) is the effect
on the Poison Ring and the rings that look like Prandur's Blessing.
It is not a brew result.

---

## 7. Reagent prices

All fourteen reagents are `Quality_Original : Magical`. Encumbrance is
in pounds.

| Reagent | Price | Weight | Role on the bench |
|---|---:|---:|---|
| Powdered Fennel | 2 | 0.05 | Powders, mortar |
| Essential Saltes | 4 | 0.05 | Every formula, dissolution mixer |
| Elixir of Bloodwine | 8 | 0.5 | Liquids, still |
| Aqua Fortis | 15 | 0.25 | Weak aqua, infusion bottle |
| Essence of Ergot | 15 | 0.5 | Liquids, still |
| Fire Lotus Dust | 25 | 0.05 | Powders, mortar |
| True Lead | 25 | 0.1 | Metals, crucible |
| Aqua Regia | 45 | 0.5 | Strong aqua, infusion bottle |
| True Iron | 40 | 0.1 | Metals, crucible |
| Tincture of Vitriol | 75 | 0.5 | Liquids, still |
| Powdered Opal | 75 | 0.05 | Powders, mortar |
| True Copper | 85 | 0.1 | Metals, crucible |
| Vampire Ashes | 150 | 0.05 | Powders, mortar |
| True Gold | 245 | 0.1 | Metals, crucible |

| Tool | Price | Weight |
|---|---:|---:|
| Crucible | 125 | 5 |
| Dissolution Mixer | 125 | 6 |
| Distillation Chamber | 150 | 4 |
| Infusion Bottle | 150 | 2 |
| Mortar and Pestle | 275 | 4 |
| Retrieval Apparatus | 350 | 3 |

---

## 8. Open questions

- **The Alchemist's Ring and the brew roll.** The roll uses virtual
  `+0xac`, which folds in the block at character `+0x3c8`. The item
  applier stores `Attribute_Alchemy` at `+0x23c` of its own target.
  Those two stores were not shown to be the same object.
- **Column 2 when both William and Kendaric are in the party.** The
  walker returns whichever handle it finds first. What order the
  party list actually keeps them in, chapter by chapter, was not
  enumerated.
- **A shortened wait under 4 hours.** The branch destroys staged
  reagents and passes time with no potion. Which shipped events can
  cut a brew that way was not listed.
- **Strong Fire Oil's area.** The item blurb says 30 feet. The spell
  record names one `Target` and `Rand(35-65)` fire. No separate area
  field was read off that record.
- **Three ids on each formula record,** at `+0x24`, `+0x28`, and
  `+0x2c`. They sit in the same numeric range as alchemy-screen
  controls. The page string is the id at `+0x20`, and the pour
  animation is the byte at `+0x30`. The middle three were not each
  tied to a control.
