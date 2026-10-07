# How items are worked out

What each family in the catalog actually is: gold, weapons, armor,
alchemy, potions, rings, books, and the rest. How an instance moves
between bags is [`inventory.md`](inventory.md). What a swing does with
a weapon is [`combat.md`](combat.md). How a potion is brewed is
[`alchemy.md`](alchemy.md). When an item gets a picture is
[`effects.md`](effects.md).

The live catalog is `MagicInvItem.txt`, 464 rows. Prices below are the
catalog `Price`, in sovereigns. Nothing here writes to the game install.

Function names are the stable citations.
`python tools/show_func.py out/decompiled/RtK.c FUN_00492024` re-finds
one.

---

## 1. One list, fourteen families

Every pickup is a row in that file. The engine stores the category at
definition `+0x18` and the subcategory at `+0x1c`. `UniqueID` is the
integer at definition `+0x40`. It is not a unique key: five daggers can
share a low number. Three values of it are special. `0` is gold.
`223` (`0xdf`) is the lockpick row, which is how the lock screen
recognizes the tool. `999` is every creature weapon, plus the Baby row,
and `DropAllOwnedItems` skips both `0` and `999`.

| Id | Category | Rows | What the player is holding |
|---:|---|---:|---|
| 0 | Weapon | 132 | A swung or shot weapon, an arrow stack, or a creature's natural attack |
| 1 | Armor | 71 | A worn piece, a shield, or the Baby row |
| 2 | Alchemy | 22 | A reagent stack or one of the six bench tools |
| 3 | Amulet | 15 | A neck slot |
| 4 | Book | 13 | A path book, or one of the four Golden Grimoire volumes |
| 5 | Document | 20 | A plot paper |
| 6 | Gem | 18 | Coin, a cash gem, a flawed gem, or a plot stone |
| 7 | Key | 8 | A lock token |
| 8 | Picks | 1 | `Lockpicks` |
| 9 | Potion | 42 | A drink, a resin, an oil, a grease, or the catalyst |
| 10 | Ring | 52 | A finger slot, including the poison lookalikes |
| 11 | Scroll | 21 | A cast, or a permanent path bonus |
| 12 | Wand | 9 | A held cast |
| 13 | Recipe | 40 | A formula scroll for the bench |

Twenty-one rows are stacks (`Aggregate : True`): gold, the four cash
gems, arrows, the fourteen reagents, and the flask. Everything else is
one object.

Quality is a ladder, not a flag that means "enchanted."

| Grade | `Quality_Points` | `QLTY_*` |
|---|---:|---:|
| Poor | 100 | 0 |
| Average | 200 | 1 |
| Good | 300 | 2 |
| Excellent | 400 | 3 |
| Magical | 500 | 4 |

One weapon, SlayerBane, spells the top grade `Magic` instead of
`Magical`. Below 401 points the inventory name appends the current
points, the original points, and the grade. Worn gear loses points when
it stops a blow; the resins put points back. Both of those are below.

`Location_Active` is where a row is worn: `Pack`, `Hand`, `Torso`,
`Arms`, `Legs`, `Ring`, `Neck`. The pack is the bag. The eight equipment
pointers are a second view of objects that stay in the bag. Slot 0 is a
weapon. Slot 1 is a shield. The header in `RtkGame.def` names the other
six and then disagrees with itself about slot 4.

---

## 2. Gold

Gold is not a character stat. It is a stack in somebody's bag.

The row is category Gem, subcategory `Money` (38, `0x26`), `UniqueID` 0,
price 1, weight `0.05` pounds per coin. A stack of 200 is 10 pounds.
`FUN_00492024` is the purse. It walks every party member (virtual
`+0x10c`) and, for each bag entry whose subcategory is Money, adds
quantity times the catalog price at definition `+0x2c`.

Four other rows are Money, and they count as sovereigns at their price:

| Item | Price | Weight each |
|---|---:|---:|
| Gold | 1 | 0.05 |
| Small Emerald | 50 | 0.05 |
| Small Flawless Diamond | 100 | 0.05 |
| Large Emerald | 500 | 0.1 |
| Large Flawless Diamond | 1000 | 0.1 |

A flawed diamond, a ruby, and the fake gems are ordinary loot. They are
not Money, so they do not enter the purse. True Gold is an alchemy
reagent (`UniqueID` 143, 245 sovereigns, weight 0.1). It is not coin.

### Making change

Opening a shop copies that sum into `DAT_0066f86c` and immediately
rewrites the party's Money stacks (`FUN_00492128`). Buying and selling
add and subtract from the integer. Closing the shop
(`FUN_0055f3d5`) writes the integer back into stacks. Walking into a
shop is enough to convert the party's coin.

The five definitions are looked up by name, largest first: Large
Flawless Diamond, Large Emerald, Small Flawless Diamond, Small Emerald,
Gold. Gold's price is 1, so the counts are just the sovereigns.

If the total is greater than 25, 25 gold is set aside first and the
rest is broken greedily into the largest gem that fits. The leftover,
plus that 25, is gold. A total of 25 or less stays entirely gold. The
25 is peeled off before the gems are chosen, so a large diamond
appears only once the pile is at least 1025 (25 reserved, then 1000).

| Purse | What the party is left holding |
|---:|---|
| 20 | 20 gold |
| 75 | 1 small emerald and 25 gold |
| 100 | 1 small emerald and 50 gold |
| 1000 | 1 large emerald, 4 small diamonds, 1 small emerald, 50 gold |
| 1025 | 1 large flawless diamond and 25 gold |

The counts are then split across the party members in list order. Each
person's share of a denomination is the ceiling of count divided by
the number of members, and earlier members are filled first. Nine large
diamonds and five members is 2, 2, 2, 2, 1. A single gem goes to the
first member, and anyone else who was holding that denomination loses
it. A denomination that rounded to zero is removed.

Weight follows the new stacks. A thousand loose sovereigns is 50
pounds. After the rewrite above, that same thousand is one large
emerald, four small diamonds, one small emerald, and 50 gold, which
weighs 2.85 pounds.

Chests and corpses are not party members, so gold sitting in a chest
is not in the purse and is not converted.

### Paying

A buy is refused when the purse is below the quoted price
(`FUN_00561b37`). The quote is `FUN_0056218d`, which calls
`FUN_004e7ac6`. That starts from catalog price times the stock line's
multiplier (the float on the shop row, `1.0` or `1.2`). The rest of
the function folds in another factor. Ghidra typed the shop line as a
float, so the haggle curve is not recovered here. Each shop authors a
`HaggleVar` from 5 to 9. `ItemsShop.tbl`, the master list, authors 0.

A sale adds the quoted price to the purse (`FUN_0055ff81`) and takes
the piece off the party member. The shop's own `Gold` field is the
till it is authored with. The buy check uses the player's purse. No
branch in the sale path was shown to refuse a sale because the till
was empty.

| Shop | File | Haggle | Till |
|---|---|---:|---:|
| Aaron's Fine Weapons | `KrondorShops.def` | 5 | 25000 |
| Argus Blacksmith | | 5 | 15000 |
| Fred's General Store | | 8 | 10000 |
| Gari's General Store | | 9 | 15000 |
| Kraack's General Store | | 7 | 10000 |
| Golden Grimoire | | 5 | 50000 |
| Gerard's Luxury Goods | | 5 | 10000 |
| HH General Store | `HaldonShops.def` | 5 | 3500 |
| Witch Hut | | 5 | 1000 |
| Merrick's Shop | | 5 | 1500 |

A stock line is `Item_Name, multiplier, quantity`. Quantity 0 is on
the shelf and out of stock. Hellblade at Aaron's is `1.2` and 0.

---

## 3. Weapons

A weapon row has `Weapon_Damage : Rand(min-max)`, a `Classification`,
and usually `Location_Active : Hand`. The fight rolls that range. It
does not roll the old 13-row type table in [`combat.md`](combat.md).
Quality rarely changes the range. Excellent is often one point higher
on the top end. A magical weapon usually keeps a mundane range and
adds a `Ready` modifier.

Classification is the family the row claims:

| Classification | Subcategories |
|---|---|
| Bladed | Dagger, Shortsword, Rapier, Scimitar, Broadsword |
| TwoHanded | Greatsword, Quarterstaff |
| Blunt | Mace, Warhammer, Club |
| Axe | Battleaxe |
| Bow | Longbow |
| Arrow | Arrow |
| Special | The twelve creature attacks |

Mundane ranges, weights, and prices. Where poor and average share a
range, one cell covers both.

| Weapon | Poor | Average | Good | Excellent | Weight |
|---|---|---|---|---|---|
| Dagger | 2–7, 5s | 2–7, 20s | 2–7, 50s | 2–8, 100s | 1 |
| Shortsword | 4–10, 8s | 4–10, 40s | 5–11, 300s | 6–12, 950s | 4 |
| Rapier | 1–10, 32s | 2–12, 160s | 2–12, 400s | 2–13, 650s | 2 or 3 |
| Scimitar | 4–14, 38s | 4–14, 100s | 5–15, 380s | 5–16, 800s | 4 |
| Broadsword | 5–15 at 50s, 75s, and 250s | | | 5–16, 500s | 6 |
| Greatsword | 4–20, 150s | 7–27, 350s | 8–28, 750s | 9–29, 1500s | 11–12 |
| Quarterstaff | 2–10 at 5s, 15s, 35s, 65s | | | | 6 |
| Mace | 1–9, 35s | 2–10, 60s | 2–10, 150s | 2–11, 900s | 9 |
| Warhammer | 4–24, 75s | 5–25, 125s | 5–25, 325s | 6–26, 750s | 16 |
| Club | 2–6, 2s | 2–6, 4s | | | 4 |
| Battleaxe | 8–18, 70s | 8–20, 210s | 8–22, 350s | 8–24, 600s | 14 |
| Longbow | 2–10, 80s | 4–12, 100s | 4–12, 180s | 4–14, 500s | 3–5 |

There is no good or excellent club. The arrow row is a stack, damage
`0`, price 5, weight 0.25, quality Magical. It is ammunition, not a
swing.

The usual enchanted pattern is a flat `Damage_Normal` plus
`Modifier_Attack`. The named enchanted dagger, shortsword, rapier,
broadsword, staff, mace, and bow sit on that pattern at about +3 to +5
damage and +15 attack, priced from 500 (the dagger) to 1500 (the
staff). Individual blades then replace or stack other modifiers:

| Modifier | What the row is asking for | Examples |
|---|---|---|
| `Weapon_DemonBlade` | The demon-blade rider | Hellblade 5, Stormblade 20, Hammer of Fire 12 |
| `Critical_HitChance` ratio | Scales the crit threshold | Centurion 200, Deathblade 150, Kahooli's Bow 200 |
| `Critical_Cursed` ratio 1000 | The cursed-crit state | The cursed dagger, broadsword, greatsword, mace, warhammer, longbow |
| `Damage_Undead` ratio | Damage against undead | SlayerBane 250, Mace of Light 200, The Day Hammer 300, ElfersBlade 200 |
| `Damage_IgnoreArmor` ratio 0 | Skip armor | Argent, The Grey Mace, Enchanted Longbow, KrondorBow |
| `Damage_IgnoreMetalic` ratio 0 | The metal-armor bypass | Thunderstaff, Elfwood |
| `Strikes_WithBladed` or `Strikes_WithBow` | An extra strike of that family | Slicer, Peregrine, Edge of Onan-ka, The Moon Axe, Farkiller |
| `Strikes_Round` ratio | A ratio on strikes per round | Catalyst 200, ElfersBlade 300 |
| `Attribute_Strength` or `Attribute_Agility` ratio | A percent on the attribute | StrongBlade 125, Staff of Ironwood 130, Dagger of Dala 120 |

A ratio of 200 doubles, 50 halves, 0 zeroes, on the formula in
[`combat.md`](combat.md) §12. A `+` in the value (`Damage_Normal` `+4`)
is still that integer. Cursed weapons are cheap and still carry a
positive damage or attack line plus `Critical_Cursed`.

A few weapons also have a `Use` block that casts. DragonStaff, the
Mace of Ishap, the Battlehammer of Onan-Ka, and Elfwood are limited to
one cast a fight and set `Effect_Recharge : 1`, so the charge comes
back next fight. Firestaff and Thunderstaff are a pool of 15 with no
recharge line. The Ready block on those two is separate from the cast.

| Weapon | Spell the row names | Uses |
|---|---|---|
| DragonStaff | `Storm_Choas` | 1 per fight, recharges |
| Mace of Ishap | `Life_HealingWind` | 1 per fight, recharges |
| Battlehammer of Onan-Ka | `Life_HealingWind` | 1 per fight, recharges |
| Elfwood | `Storm_LightStrike` | 1 per fight, recharges |
| Firestaff | `Fire_FireRain` | 15, no recharge line |
| Thunderstaff | `Storm_LightStrike` | 15, no recharge line |

The Battlehammer's description says Battlehymn. The spell field is
`Life_HealingWind`, the same cast as the Mace of Ishap. Elfwood's shop
comment says Chaos Storm. The spell field is `Storm_LightStrike`.
`Storm_Choas` is the spelling in the file.

The twelve creature weapons are `SubCategory : Monster`, price 0,
weight 0, `UniqueID` 999, description `NonDisplay`. Their ranges are
the monster's attack: sewer claws `Rand(5-20)`, the sea monster
`Rand(75-120)`, the dragon soul `Rand(10-40)`. Several name a
`Mstr_*` cast. They are not shop stock and they are not dropped when
the body spills.

---

## 4. Armor and shields

Armor has no damage range and no armor number in the catalog. The piece
is identified by subcategory (the material) and classification (the
slot). Absorption in a fight is
`(roll * rating * quality) / 100 + rating` per worn piece, summed for
torso, arms, and legs. The rating itself is computed in `FUN_004b55d1`
and was not recovered as a table. Quality on the instance is the
current points, so a battered breastplate stops less than a fresh one
of the same row. The full pass, including the chip that scars the
piece, is [`combat.md`](combat.md) §10.

| Piece | Slot | Poor price / weight | Excellent price / weight |
|---|---|---|---|
| Leather jerkin | Torso | 80 / 4 | 3000 / 6 |
| Leather vambraces | Arms | 35 / 2 | 1500 / 4 |
| Leather greaves | Legs | 50 / 3 | 1500 / 5 |
| Chainmail shirt | Torso | 250 / 25 | 5500 / 25 |
| Chainmail sleeves | Arms | 150 / 6 | 4500 / 6 |
| Chainmail leggings | Legs | 150 / 10 | 4500 / 10 |
| Breastplate | Torso | 700 / 30 | 10000 / 30 |
| Plate vambraces | Arms | 300 / 15 | 6000 / 15 |
| Plate greaves | Legs | 400 / 20 | 6000 / 20 |
| Shield | Hand | 25 / 18 | 1400 / 21 |

Average and good sit between those prices. Plate stays near 30 / 15 /
20 pounds at every mundane grade. Chain and leather move a few pounds
between grades. A full poor plate suit is on the order of 65 pounds
before the shield. That is the load in the encumbrance bands: carried
weight times 100, over strength plus stamina. Above 60 the attack,
defense, and parry shrink. Above 92 they are at 80 percent and move
speed is at 25 percent.

Magical armor adds `Armor_Enchanted` or `Armor_Special`, value 1, and
then a real modifier. The enchanted leather, chain, and plate of each
slot are the plain `Armor_Enchanted` row, lighter than the excellent
grade of the same piece and priced above it (the enchanted breastplate
is 20000 and 25 pounds). Named pieces:

| Piece | Beyond the enchant flag |
|---|---|
| Dragonskin Jerkin | Normal fire taken at ratio 0, spell fire at 50 |
| Komandorskin Jerkin | Normal fire at 0, and immune to critical hits |
| Poison-Proof Jerkin, Armor of Ishap | Immune to poison |
| Mail of Invulnerability | Immune to critical hits |
| Jerkin of Graff | Immune to critical hits, normal fire at 0, strength at ratio 50 |
| Ironskin jerkin, vambraces, greaves | Agility at ratio 60 |
| Dragonskin vambraces and greaves | Defense +15 |
| Viox Chainmail Shirt | Strength at ratio 150 |
| Sleeves of Strength | Strength 125, agility 50 |
| Chainmail Leggings of Clumsiness | Strength 150, agility 25 |
| Draken Plate | Spell fire at ratio 15, and cursed criticals |
| Cursed chain shirt, sleeves, leggings, and the cursed shield | Cursed criticals, priced 10 to 30 |

Shields are armor category, subcategory Shield, classification Shield,
worn in the hand. The block score uses shield skill plus a quality
band: no shield 0, then −2, 0, +2, +4 across qualities 0 through 3. A
shield-ring effect counts as quality 3. Enchanted Shield is
`Armor_Enchanted` plus shield skill at ratio 125, and it weighs 12
instead of about 20. Shield of Agility is shield skill at 140 and
`Strikes_LeftFree` 1.

`Baby` is an armor-category row with no subcategory, `UniqueID` 999,
price 1, weight 24, location Pack. It is the row the engine skips when
a body spills, alongside the creature weapons.

---

## 5. Crafting

The only craft is the alchemy bench. There is no smithing recipe and no
armor pattern. Repair and upgrade are potions, drunk or applied as
items, not a second station.

The bench, the forty formulas, the skill roll, and the tool breakage
are [`alchemy.md`](alchemy.md). The short form:

- Fourteen reagent stacks and six tools. Every formula starts with
  Essential Saltes. Weak formulas use Aqua Fortis. Strong formulas
  swap in Aqua Regia and are otherwise the same reagents.
- The flask is a two-sovereign stack. No formula consumes one.
- A recipe scroll is category Recipe, one use, `LearnPotion_*`. Using
  it sets that formula to state 1, which brews with no skill roll.
- A new game already knows three formulas: weak healing, weak
  protection from fire, weak antidote.
- Jazhara's alchemy is 20. Kendaric's is 60. The Alchemist's Ring is a
  flat `Attribute_Alchemy` of 35. Whether that 35 reaches the brew
  roll is still open in the alchemy note.
- One dose consumes one of each reagent in the formula and yields one
  potion. The dose buttons go up to three.

The four resins are the craft result that changes gear rather than a
body:

| Resin | What it writes |
|---|---|
| Repair | `Item_QualityImprove` by 100, toward the next 100-point grade |
| Total Repair | `Item_QualityRestore` back to the item's original quality |
| Quality | `Item_QualityUpgrade` by 100, one grade |
| Maximum Quality | `Item_QualityMakeExcellent` |

A piece scarred in a fight can be walked back up those grades. The
resin does not change `Weapon_Damage`. A dagger repaired to excellent
points is still the dagger row it always was.

---

## 6. Potions

Forty-two potion rows. The forty that brew are in the alchemy note,
with the rolled numbers. Two more sit in the category and do not brew:
Potion of Poison, and the Thaumaturical Catalyst (`UniqueID` 151,
price 1200, no effect and no formula).

Subcategory on a potion says how the row is labeled, not a second
ruleset: Potion, Resin, Oil, Grease, Catalyst. Every brewed potion is
one charge (`Effect_CastMax : 1`). `Effect_NonCombat : 1` can be used
on the map. `0` is a combat use. On the map the numbers apply and the
spell picture does not play.

The families, by what they touch:

| Family | Map or fight | The number |
|---|---|---|
| Healing, weak / strong | Map | Health `Rand(20-30)` / `Rand(40-60)` |
| Regeneration, weak / strong | Both | A small heal now, then 5 or 15 a round in the fight |
| Antidote, weak / strong | Map | Dispel poison. The strong one also grants immunity for the battle |
| Spellcasting / Great | Map | 20 or 50 spell points |
| The four resins | Map | Quality, as above |
| Abjuration, Beast, Magic, Strength, Might, the four protections, Iron Skin, Striking | Fight, on the drinker | A battle-length modifier. Beast and the magic potions also hurt a drinker who is not the right caster |
| Poison grease, blade grease | Fight, on a weapon | Poison or attack and damage for the battle, or for a few rounds |
| Fire oil, holy balm | Thrown | Fire at one target, or a ratio on damage an undead takes |

Where a blurb disagrees with the spell record, the alchemy note quotes
both. Strong Fire Oil's text says a 30-foot area. The record names one
target.

---

## 7. Rings and amulets

Two ring slots and one neck slot. A ring weighs about 0.05. An amulet
weighs 0.25 to 1. `Ready` is on while worn. `Use` is a cast the player
invokes. `Effect_Recharge : 1` with `Effect_CastLimit : Limited` is the
"once this fight, back next fight" pattern. Storm Ring is the odd one:
two Lightning Strikes per combat. The others in that pattern are one.

Rings worth separating from the list:

| Ring | While worn | Cast |
|---|---|---|
| Ring of Prandur's Blessing | Fire damage taken at 0, spell fire at 50, fire-path damage at 150, quick flames | |
| Ring of Freedom | Immune to paralysis, agility 125 | |
| Manna Ring | Spell-point cost at 25, caster level at 150 | |
| Mage's Ring | Spell-point cost at 50, caster level at 150 | Ride the Lightning, 1 per fight |
| Alchemist's Ring | Alchemy +35, quick change, immune to poison | |
| Rogue's Ring | Lock +25, traps +25, analyze +15, defense +15, immune to poison | |
| Warrior's Ring | Attack +30, defense +20 | |
| Shield Ring | Counts as a quality-3 shield for the block band | |
| Ring of Winds | Missiles taken at 0, defense +50 | |
| Poison Ring | | `Item_PoisonDeath` |

The smaller copies (Tiny Manna, Small Manna, Hawk Eye, Small Shield,
Small Assess, Small War, Small Mind, Small Mage, Fire Ring, Change
Ring) are the same modifiers at a lower ratio or without the cast.

A second set shares a `UniqueID` with a real ring, weighs the same,
costs 5 to 290, and casts `Item_PoisonDeath`. The names say so:
`PrandurPoison`, `MannaPoison`, `FreePoison`, `EaglePoison`,
`ShieldPoison`, `WindPoison`, `MagePoison`, `WarPoison`, `MindPoison`.
They are lookalikes, not weaker versions of the blessing. Next to them
are inert rings at the same id and a mundane price: Gold Ring 25,
Ornate Gold Ring 125, PrandurGold 225, MannaGold 675, ShieldGold 1750.
Iron Ring is price 1 and has no effect. Cursed Ring is defense −10 and
cursed criticals.

Amulets follow the same split. Sung, Domination, and Fire cast once a
fight (Breath of Sung, Enslave the Will, Fire Rain) and Sung also sets
`Health_AmuletSung`. Protection is armor +15 and a point of armor
block. Poison Resistance is poison immunity. The Sword amulet is
bladed skill +15 and an extra bladed strike. The Bow amulet is missile
attack +15 and an extra bow strike. Missile Shield zeroes missile
damage. Knowledge is analyze +35. Nalor has no effect block. The fake
Sung charm and the fake Sword amulet cut strength and agility to half.
Black Pearl Necklace and Whisperer's Locket are `WhenWearing` script
hooks, not stat modifiers. Upright Man is lock +15 and traps +15.

`UseByMage`, `UseByPriest`, `UseByMagic`, and `UseByAll` are the
subcategories on the rows that say who may use them. Equipping itself
(`FUN_004ca351`) does not read that field. A gate in the inventory
screen was not walked.

---

## 8. Books, scrolls, wands

Path books and the "Hint" books are a `Use` on the map that adds a
flat path skill: 20 for a Path book, 10 for a Hint. Prices run from
12500 to 25000. Book of Necromancy is the mixed one: Change +1, Mind
+13, Flames −7, Storms −9. The four `GG Book` rows are price 0, weight
1, and have no effect. They are the Grimoire volumes, not spells.

Scrolls of Flames, Mind, Storms, and Change are the same kind of use,
at +5, priced 5000 to 10000. The other scrolls are `CastOnUse` of a
named spell. Sung's Breath, the Hero Reborn, Cleanse the Blood, and
Silban can be used on the map. Lightning Strike, Chain Lightning,
Restoration, Cleanse the Mind, the elemental-protection scroll, the
beast scroll, and Ride the Lightning are combat casts. Ship Raising
Ritual is a script, not a spell. Six more (Madness, Tith, Silban,
Firestorm, Chaos, Unbeing) are priced 200 and cast the matching big
spell. Tith's field is `Divine_BattleHymm`.

Wands are held in the hand, weight 1 to 2.5, and cast:

| Wand | Spell | Note |
|---|---|---|
| Prandur's Wrath | `Fire_PrandurTouch` | 20000 |
| Domination | `Mental_EnslaveWill` | 25000 |
| The Sun | `Fire_BirthingSun` | 12000 |
| Bone of Death | `Life_HandOfDeath` | Limited to 6 casts, no recharge line |
| Madness, Firestorm, Chaos, Unbeing | The same big spells as the 200-sovereign scrolls | Each also applies −1 to its own path |
| Scepter of Karack | `Special_Script` | Pack, not a combat cast. Usable by anyone |

---

## 9. The rest of the bag

**Gems that are not money.** Small and large flawed diamonds (38 and
112), the ruby (1250), and `FakeRuby` (5) are loot. The dissolved and
intact fake ruby, diamond, and emerald are the chapter 3 stones. The
intact ones set `Chapter3.bHaveFakeRubies` when a party member picks
them up. Nightstone, Shell of Eortis, and Tear of the Gods are plot
objects. Nightstone's use is a chapter script, not a modifier.

**Keys.** Eight rows, one subcategory each: Lucas, Skull, Pete, Yusuf,
Skeleton (the Skeletal hand), Slave Pen, Necromancer, Magic. The lock
test walks the bag for category Key. An exact subcategory match wins.
`MagicKey` is kept and used only when no exact key was found. The
Magic Key costs 750. The others cost 5 or 10. Each also has an Unready
script block. The match itself does not consume the key.

**Documents.** Eighteen of the twenty are an Unready script: the
nighthawk papers, Yusuf's documents, the death warrant, the prince's
writ, the letter of recommendation, and the rest. Paper Scrap and
Shipping Papers have no effect. Using one runs the item script, the
same path as Nightstone.

**Lockpicks.** One row, `UniqueID` 223, price 150, weight 2,
classification Thief. The lock screen offers the tool when that id is
in James's bag. A success does not decrement it.

**Alchemy tools and reagents.** Six tools, from the crucible at 125
sovereigns and 5 pounds to the retrieval apparatus at 350 and 3 pounds.
Fourteen reagents, from fennel at 2 sovereigns to True Gold at 245.
The prices, the weights, and which tool each slot requires are the
table in [`alchemy.md`](alchemy.md).

---

## 10. What is still open

- **The haggle curve.** `HaggleVar` is on every shop. `FUN_004e7ac6`
  starts from catalog price times the stock multiplier and then folds
  in another factor. The decompile types that object as a float, so
  the curve was not read out as a formula.
- **The merchant's till.** Each shop authors `Gold`. The buy check
  compares the player's purse with the quote. No sale path was shown
  to stop because the till hit zero.
- **Armor ratings.** The absorption formula is in the combat note.
  `FUN_004b55d1` is where the per-piece rating comes from, and the
  decompiler dropped the values in that switch.
- **Class limits.** `UseByMage` and the other subcategories are on the
  rows. The equip function does not test them.
- **The Alchemist's Ring and the brew roll.** The ring grants
  `Attribute_Alchemy` 35. The roll reads a virtual that is supposed to
  include equipment bonuses. The two stores were not shown to be the
  same object.
