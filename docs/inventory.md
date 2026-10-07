# Inventory and item transfers

How an item is defined, how a character holds it, and every way it moves:
between party members, into a chest or a corpse, onto the ground, through
a shop, or through a lock. The click that opens a chest or a door is in
[`interactions.md`](interactions.md). What a weapon does in a fight is in
[`combat.md`](combat.md). What each family is worth, and how gold is
broken into gems, is in [`items.md`](items.md). This note is the object
those systems share.

Function names are the stable citations. `RtK.c` line numbers move every
time the decompile is regenerated;
`python tools/show_func.py out/decompiled/RtK.c FUN_004c9c58` re-finds one.
Script examples are from the inflated sources under
`out/plaintext/GameData/`. Nothing here writes to the game install.

---

## 1. The shape of it

Every person, enemy, chest, door, desk, and backpack is a character
(`CCharInst`). Each one owns the same inventory: a bag of item instances,
eight equipment pointers into that bag, a running encumbrance, a lock
flag, and a trap.

An item the player can pick up is not a separate world object with its
own rules. It is an instance of a row in `MagicInvItem.txt`, hanging off
some character's bag. A chest is a character whose bag you are allowed to
open. A corpse you loot is the same. A pile on the floor is a character
the engine created in the scene group `DroppedItems`.

The five party slots the interface always resolves by name are James,
Jazhara, William, Kendaric, and Solon (`FUN_004366c0`). Anyone else is
just another character passed into the same screens.

---

## 2. The catalog

`RtkGame.def` points the game at two files:

```
InventoryTable  : MagicInvItem.txt
InventoryScript : InventoryItemScript.txt
```

`MagicInvItem.txt` is the live catalog: 464 items. The older `#define`
block at the top of `RtkGame.def` (`DAGGER` 0, `LEATHER_JERKIN` 100,
`IITEM_*` field numbers, `INV_LOC_*`, `INV_CLASSLIMIT_*`) is a second,
earlier numbering. Combat's actor resolver reads the catalog, not that
block. The `WEAP_*` constants are a third numbering and do not index the
13-row weapon table in [`combat.md`](combat.md).

Each catalog row ends at `End_Item`. The fields that are present on every
row:

| Field | Role |
|---|---|
| `Item_Name` | The script name. `PutItemInInventory` and the other character methods look the row up by this string |
| `UniqueID` | Authored id, stored at definition `+0x40`. Several quality variants of one weapon share a low number; it is not a unique key in the file. `0` is gold, `223` (`0xdf`) is lockpicks, `999` is a creature weapon or the Baby row |
| `UA_Tag` / `AS_Tag` | Unassessed name and assessed name. `REF(Dagger_poor)` means "use that row's tag" |
| `Description` | One or more lines |
| `Category` / `SubCategory` | See the tables below |
| `Quality_Original` | `Poor`, `Average`, `Good`, `Excellent`, `Magical` (`QLTY_*` 0..4 in `RtkGame.def`) |
| `Quality_Points` | 100, 200, 300, 400, 500 for those five grades |
| `Price` | Base price in sovereigns |
| `Location_Stored` / `Location_Active` | Where it rests and where it is worn: `Pack`, `Hand`, `Neck`, and the other `INV_LOC_*` names |
| `Encumbrance` | Pounds. Gold is `0.05` |
| `Aggregate` | Present and `True` on stacks. Absent means one object, quantity 1 |
| `Classification` | Weapon family (`Bladed` and the others). Armor and other rows carry one too |
| `Weapon_Damage` | `Rand(min-max)` on weapons |
| `Effect` | Optional ready or use effect, the same modifier vocabulary as spells |

Categories, and the integer the engine stores at definition `+0x18`:

| Id | Category | Rows |
|---:|---|---:|
| 0 | Weapon | 132 |
| 1 | Armor | 71 |
| 2 | Alchemy | 22 |
| 3 | Amulet | 15 |
| 4 | Book | 13 |
| 5 | Document | 20 |
| 6 | Gem | 18 |
| 7 | Key | 8 |
| 8 | Picks | 1 (`Lockpicks`) |
| 9 | Potion | 42 |
| 10 | Ring | 52 |
| 11 | Scroll | 21 |
| 12 | Wand | 9 |
| 13 | Recipe | 40 |

How those Alchemy, Potion, and Recipe rows are brewed and used is in
[`alchemy.md`](alchemy.md).

Subcategory lives at definition `+0x1c`. Weapons use `Dagger` through
`Warhammer` (0..12). Armor uses `Chainmail`, `Leather`, `Plate`,
`Shield`. Keys use the token that `Model_Type` names on a door:

| Id | Subcategory |
|---:|---|
| 30 | `LucasKey` |
| 31 | `SkullKey` |
| 32 | `PetesKey` |
| 33 | `YusefKey` |
| 34 | `SkeletonKey` |
| 35 | `SlavePenKey` |
| 36 | `NecromancerKey` |
| 37 | `MagicKey` |

`Multi_Use` (21) is the subcategory on lockpicks and on several potions.
`Money` (38) is gold. `UseByMage`, `UseByPriest`, `UseByAll`, and
`UseByMagic` (26..29) are the class-restriction subcategories.

Twenty-one rows are stacks (`Aggregate : True`): gold, arrows, the
alchemy reagents, flasks, and the flawless gems. Everything else is a
single object.

---

## 3. An item instance

Creating an item is `FUN_004ddb0b`. The object is `0x54` bytes. The
definition pointer is at `+0x28`. The owner character is at `+0x2c`.
Quantity is at `+0x50` and starts at 1. The assessed flag is at `+0x4c`.
Current and original quality are copied from the definition's `+0x24` and
`+0x28` onto the instance at `+0xc` and `+0x10`. Effects are a list at
`+0x14`.

`FUN_004dddee` writes the quantity and, when the item has an owner, asks
that character to recompute encumbrance.

Weight of one instance (`FUN_004ddf3d`): if the definition is not a stack,
the weight is the catalog encumbrance at definition `+0x44`. If it is a
stack, the weight is quantity times that encumbrance.

The display name (`FUN_004dde28`) is the assessed or unassessed tag. Below
quality 401 (`0x191`) the UI appends the current quality, the original
quality, and the grade name.

---

## 4. What a character holds

On the character:

| Offset | What |
|---|---|
| `+0x14` | The 3D actor |
| `+0x18` / `+0x1c` / `+0x20` | The bag: vector, pointer array, count |
| `+0x2c` .. `+0x48` | Eight equipment pointers. Each one points at an item that is also still in the bag |
| `+0x4c` | The retained item. `UnEquip` can park a slot here, and `RestoreRetainedItem` puts it back |
| `+0x50` | Total encumbrance, a float |
| `+0x54` | The character definition |
| `+0xd0` | Trap-layout index. `-1` means no layout. This is the instance field. The key token is a different `+0xd0`, on the definition |
| `+0xd4` | Trapped. `1` when a trap layout is set |
| `+0xd8` | Locked |

A new character starts unlocked, untrapped, with an empty bag, eight null
slots, and trap index `-1` (`FUN_004c786c`).

`RtkGame.def` names the eight slots as arms, legs, chest, primary hand,
off hand, shield, two rings, and neck. Off hand and shield are both index
4 in that header, and the author left question marks on the line. Two
engine checks pin the low slots more tightly than that header does:
`FUN_004ca524` returns slot 0 only when the item's category is Weapon, and
`FUN_004ca559` returns slot 1 only when the subcategory is Shield (17).
The pack is the bag, not a ninth pointer. `INVSLOT_PACK` is 8, which is
`MAX_INVSLOT`, the first index past the equipment array.

`MAX_ITEMS_CAN_CARRY` is 40 in `RtkGame.def`. The add function
`FUN_004c9c58` does not test that number. The inventory grid draws seven
columns and four rows of the bag.

### Adding

`FUN_004c9c58(character, item, count)` is the only insert.

- A null item returns null.
- A stack (definition `+0x14` nonzero) looks for an existing bag entry
  with the same definition pointer. If the incoming quantity is less than
  or equal to `count`, the whole stack merges and the incoming object is
  deleted. If `count` is smaller, that many are moved and the incoming
  object keeps the remainder. If there is no existing stack and `count`
  is less than the incoming quantity, a new instance is split off for
  `count` and the original is left short by that many.
- Anything else is appended to the bag as a whole object.
- The owner pointer is set. Encumbrance goes up by `FUN_004ddf3d`.
- If the owner answers virtual `+0x10c` (the same test the cursor uses
  for a party member), the definition's script receives `OnPickup`.

`FUN_004c9fb8(character, index)` is the remove. It subtracts the weight,
takes that slot out of the bag, fires `OnDrop` under the same party test,
and clears the owner. It does not delete the object. The caller does,
when the item is being destroyed rather than moved.

`FUN_004ca095` is remove-by-pointer. `FUN_004ca271` empties the bag and
deletes every object.

### Equipping

`FUN_004ca351(character, item, slot)` writes one of the eight pointers.
The previous occupant gets `OnUnEquip`. The new one gets `OnEquip`. Both
events fire only when the item's owner answers virtual `+0x10c`. A weapon
change sets actor `+0x18c` so the combat figure rebuilds.

The slot pointer does not take the item out of the bag. Equipment is a
second view of objects the bag already holds. `AddItemToEquipment` adds
the full quantity to the bag and then, when the slot argument is not `-1`,
points that slot at it.

### Encumbrance

`FUN_004ca135` is the "this will not fit" test. It runs only for a
character who answers virtual `+0x10c` and whose virtual `+0x4c` is clear
(a party member who is not being treated as a container). It adds two
shorts from virtual `+0xcc` and `+0xd4` and compares them with the current
encumbrance plus the item's weight. `FUN_004ca1c3` is the matching
question for a stack: how many more fit, or `0x7fffffff` when the piece
weighs nothing.

---

## 5. Script methods on a character

Registered by `FUN_004cd9ce` and dispatched from the character's script
method. Arguments are the script values; a bad argument count returns
failure.

| Method | What it does |
|---|---|
| `IsItemInInventory(name)` | True when some bag entry's face name matches. Equipped items are found because they are still bag entries |
| `PutItemInInventory(name)` | Looks the catalog row up (`FUN_004e431a`), builds one instance, marks it assessed, and adds quantity 1. A second argument replaces the assessed flag (`TRUE` is 1, the default) |
| `PutItemInInventory(name, assessed)` | Same, with the assessed flag taken from the second argument |
| `RemoveItemFromInventory(name)` | Clears any equipment slot whose item name matches, then deletes the first bag entry with that face name |
| `GetAggregateItemCount(name)` | The stack's quantity. A non-stack returns 1. A missing name returns 0 |
| `RemoveAggregateItemByCount(name, n)` | On a stack, deletes the entry when `n` is at least the quantity, otherwise subtracts `n` |
| `Equip(slot, name)` | Finds the bag entry by face name and writes it into that slot |
| `UnEquip(slot)` | Clears the slot. A second argument of 1 first copies the pointer to the retained slot at `+0x4c` |
| `RestoreRetainedItem(slot)` | Writes `+0x4c` back into that slot |
| `IsEquiped(name)` | True when one of the eight slots points at a bag entry with that face name |
| `TransferEquipment(other)` | Clears all eight slot pointers, then moves each bag entry onto `other` with a count of 1. See below |
| `DropItem(name)` | Builds a fresh catalog instance and places it on the ground at this character. It does not take anything out of the bag |
| `DropAllOwnedItems()` | Clears the eight slots, then drops each bag entry at the actor's feet, skipping a definition whose `+0x40` is 0 or 999 |
| `IsLocked` / `SetLocked` / `ClearLocked` | Read or write `+0xd8` |
| `IsTrapped` / `SetTrapped` / `ClearTrapped` | Read or write `+0xd4` |
| `SetTrapType(name)` | Looks the name up and stores the id at `+0xd0`. `None` (`-1`) also clears the trapped flag. Any other id sets trapped |
| `DoLooting()` | Opens interface `0x5` on this character |
| `DoTrapLock()` | Opens interface `0x12` on this character |

`TransferEquipment` is what chapter 9 uses to empty the slaves into a
chest, and to stash the party:

```
JamesCharacter.RemoveItemFromInventory ("Lockpicks");
JamesCharacter.TransferEquipment (JamesChestCharacter);
JamesCharacter.PutItemInInventory ("Lockpicks");
```

The count passed into the add is 1 for every entry. A non-stack has
quantity 1, so the object moves intact. A stack larger than 1 only
contributes 1 to the destination; the remainder stays on an object that
has already been taken out of the source bag. Lockpicks are not a stack,
which is why the script can pull them out by name, move everything else,
and put a lockpick back. Gold is a stack.

`DropItem` is a spawn, not a take. Chapter 7 uses it to place the Black
Pearl Necklace on a character in the room. `DropAllOwnedItems` is the
real empty-onto-the-floor, used when the chapter 7 vampires die.

`PutItemInInventory` always adds one. Giving three potions is three calls,
or one call on a stack name that then merges.

The exported C API is the same bag, reached from the UI and from cheats:

| Export | Body |
|---|---|
| `Char_AddInvItemToBag` | `FUN_004c9c58` with count 1 |
| `Char_AddInvItemToBody` | `FUN_004ca351` |
| `AddItemToEquipment` | add the full quantity, then equip when the slot is not `-1` |
| `Char_DropInvItem` / `Char_RemoveInvItem` | slot under 8 clears that equipment pointer; otherwise removes that bag index |
| `Char_RemoveInvItemNew` | always the bag remove |
| `RemoveItemFromEquipment` | clear the slot when it is not `-1`, then bag-remove |
| `Char_PickupInvItem` | builds a definition and an instance from the UI's current strings and adds it |

---

## 6. The party inventory screen

Where that screen sits on the frame, and how its buttons are built, is in
[`ui.md`](ui.md). This section is the bag those buttons move.

Interface ids `0x3`, `0x5`, `0x9`, `0xa`, and `0xb` all end in
`FUN_005471a8` after `FUN_004366c0` has resolved the five party names and
stored the extra character (the chest, the corpse, the NPC) at
`DAT_00628d54`. `DoLooting` is id `0x5`. A world click on a container is
the same id: action `7` in the picker calls `FUN_004366c0(0x5, character)`.
That path is section 4 and section 5 of the interactions note.

Dragging inside that screen is `FUN_00541c2b(item, count, dest, source, ...)`.

- Moving fewer than the stack's quantity calls `FUN_004c9c58(dest, item, count)`,
  which merges or splits.
- Moving the whole stack builds a new instance of the full quantity, adds
  it to the destination, and when the quantity was greater than 1 removes
  and deletes the source object.
- A newly occupied bag slot is placed on the grid by `FUN_0053f022` /
  `FUN_0053d74e`. The cell index is `column + row * 64` (`% 0x40` and
  `>> 6`).
- Stacks draw their quantity on the icon (`FUN_00541a3b`). While a drag is
  in progress the drawn count is one lower, so the cursor's piece is not
  counted twice.

Dropping from this screen onto the floor is `FUN_0053f1a5`:
`RemoveItemFromEquipment`, then `FUN_004283d1` at the actor's position.

The same screen is how the party moves gear between James, Jazhara,
William, Kendaric, and Solon. There is no separate "give to companion"
script verb. The drag is the transfer.

---

## 7. Chests, corpses, and other containers

A container is a character in `Chars.tbl` with `Class : Object` and
`Nationality : Lootable` (or `Pickable` for a loose potion). The model
type selects the picture and, for a locked one, the lock screen:

| `Model_Type` | Id at definition `+0xcc` | Examples |
|---|---:|---|
| `Party` | 0 | the five companions |
| `Character` | 1 | |
| `Boned` | 2 | |
| `Monster` | 3 | |
| `Backpack` | 4 | `Treasure Pack` |
| `Chest` | 5 | `Treasure Chest`, with a key token |
| `Container` | 6 | `2D Container` |
| `Desk` | 7 | `Yusufs Desk` |
| `Door` | 8 | |
| `Shelf` | 9 | |
| `Arrow` | 10 | |
| `Baby` | 11 | |
| `Cube` | 12 | |
| `Fire` | 13 | |
| `Potion` | 14 | |
| `Tools` | 15 | |
| `Item` | 16 | |
| `SignPost` | 17 | |
| `Cage` | 18 | `Cage, YusefKey` |
| `Gate` | 19 | |

Contents are `InventoryItems` on that character definition. A placed
chest in a chapter is a group member of that definition, and its
`OnTrigger` decides between the lock and the bag. The throne-room chest
in chapter 9 is the pattern:

```
Event OnTrigger ()
{
    Object Chest = S00070008.GetTouchSensor ("Chest");
    if (TRUE == IsLocked () || TRUE == IsTrapped ())
    {
        Chest.Arm ();
        DoTrapLock ();
    }
    else
    {
        DoLooting ();
    }
}
```

`DoLooting` opens the same grid as the party inventory, with this
character on the other side of the drag. Taking from the chest and
putting back into the chest are both `FUN_00541c2b`.

Enemies are characters too. Their `InventoryItems` are the loot. Nothing
in the engine automatically moves a dead enemy's bag onto the party.
Chapter scripts call `DropAllOwnedItems` when something should spill
(the chapter 7 vampires), or they leave the bag on the body and let a
later `DoLooting` open it, or they `PutItemInInventory` onto the body
just before the player can reach it (chapter 9 puts the Armor of Ishap
on the giant, and keys onto the chests). `TransferEquipment` is the
scripted form of "empty this person into that chest."

A click on your own party opens the party screen. A click on a container
opens looting. Which cursor that is, and the virtual `+0x4c` test that
chooses the container, is the interactions note.

---

## 8. The ground

`FUN_004283d1(items, count, position)` is the world drop.

1. It finds the group named `DroppedItems` on the current scene. A miss
   logs `DroppedItems::Add - unable to get` and returns.
2. It looks for an existing member of that group within a small radius
   of the point (`FUN_004285d2`).
3. Failing that, it creates a character named `DroppedItemContainer_m%d`
   (`FUN_004284df`), places the actor at the point, and adds it to the
   group.
4. Each item is added to that character's bag with its current quantity.

Searching the pile under a point is `FUN_004286b1` / `FUN_0042870e`, and
it ignores a container whose bag is empty. Leaving the scene clears the
group in `FUN_004287fc`.

Two other callers drop a single equipped piece at the actor's feet:
`FUN_0040aed8` (the weapon in slot 0, after `RemoveItemFromEquipment`)
and a deferred action of type 2 in `FUN_0047a62c` (again
`RemoveItemFromEquipment`, then the drop). The inventory screen's own
drop is `FUN_0053f1a5`, above.

---

## 9. Shops

A shop is a `Shop` block in `KrondorShops.def` or `HaldonShops.def`, or
the master list `ItemsShop.tbl`. The header carries `Desc`, `HaggleVar`,
`City`, `XYZLoc`, and `Gold` (Aaron's Fine Weapons stocks 25000). Each
stock line is:

```
Item_Name, priceMultiplier, quantity
```

`Dagger_poor, 1.0, 2` is two poor daggers at the catalog price.
`Hellblade, 1.2, 0` is listed, marked up, and out of stock. A trailing
quantity may be empty.

`DoShopping` is `FUN_0050db86`. It takes the shop name and up to four
extra numbers (three floats and an optional int), stores them at
`DAT_0063f2e8`, resolves the shop, and opens interface `0x8`
(`FUN_0055b6ff`).

Opening that screen sums every Money stack on the party into one purse
and rewrites the stacks. Closing it writes the purse back. The five
denominations and the split are in [`items.md`](items.md).

Buying one piece is `FUN_0055f4cc`. It builds an instance from the stock
row, adds it to the selected party member (`DAT_0066dfb8` indexed by
`DAT_0066f834`), marks it assessed, fires `OnAssess` when that member
answers virtual `+0x10c`, and decrements the stock quantity. At zero the
shelf icon is destroyed. Buying a count of a stack is `FUN_0055f68c`:
the stock quantity drops by the count, and one instance of that count is
added. `FUN_0055f81a` is the button that chooses between those two. On a
purchase it multiplies the count by the row price (`FUN_0056218d`) and
passes the negative of that to `FUN_00561c5e`, the money change.

Selling is `FUN_0055f8d8`. The piece is removed from the party member.
If the shop already lists that definition with quantity still above zero,
the stock count goes up; otherwise the function continues into the
"shop does not carry this" path.

---

## 10. Doors, locks, keys, traps

A locked door is a character, same as a chest. The second `Model_Type`
token is the key the definition requires, stored at definition `+0xd0`.
`FUN_00463d6b` parses `Model_Type : Door, SkullKey` into definition
`+0xcc` = Door (8) and `+0xd0` = `SkullKey` (31).

The eight keys in the catalog:

| Item | Subcategory |
|---|---|
| `Lucas' Key` | `LucasKey` |
| `Skull Key` | `SkullKey` |
| `Pete's Key` | `PetesKey` |
| `Yusuf's Key` | `YusefKey` |
| `Skeletal hand` | `SkeletonKey` |
| `Slave Pen Key` | `SlavePenKey` |
| `Necromancer's Key` | `NecromancerKey` |
| `Magic Key` | `MagicKey` |

`FUN_004c8c92(door, bag)` walks the acting character's bag. A Key
(category 7) whose subcategory equals the door's required id is the
match and is returned immediately. A Key whose subcategory is `MagicKey`
(37) is remembered and returned only when no exact key was found. No key
returns 0. The lock screen calls this with the door as `this` and the
party member `DAT_0066fcac` as the bag (`FUN_00568972`).

`DoTrapLock` opens interface `0x12`, which is `FUN_00565c30`. The door's
model type picks the screen:

| Definition `+0xcc` | Screen | What the player gets |
|---|---|---|
| Chest (5), Backpack (4) | 1 | Probe, disarm, and lockpick |
| Desk (7) | 4 | The same tools, the desk layout |
| Door (8), and the default | 0 | The same tools, the door layout |
| Container (6), Cage (18) | 2 | A key screen. No probe and no disarm |
| Gate (19) | 3 | A key screen |

The acting character is James's slot (`DAT_0066dfb0` copied to
`DAT_0066fcac`). Tools are offered only when that bag contains an item
whose definition `+0x40` equals `0xdf` (`FUN_0056bf0e`). That is the
lockpick test. The success and failure paths that follow do not decrement
that item.

The trap on the instance is separate from the key. `SetTrapType` stores
a layout index at instance `+0xd0` and raises `+0xd4`. The names are
`None` plus seven elements across three mechanisms:

| | Wire | Plate | Hook |
|---|---:|---:|---:|
| Serpent | 0 | 7 | 14 |
| Dagger | 1 | 8 | 15 |
| Venom | 2 | 9 | 16 |
| Needle | 3 | 10 | 17 |
| Blade | 4 | 11 | 18 |
| Ember | 5 | 12 | 19 |
| Fire | 6 | 13 | 20 |

`None` is `-1` and clears the trapped flag. The lock screen indexes
`DAT_00616f20` by that id, stride `0x28`, and treats the record as three
stages: trigger, mechanism, delivery. All three disarmed
(`FUN_0056a7c2`) clears instance `+0xd4` and logs
`Trap Status : Completely Disarmed`.

Using the key (`FUN_0056899d`) while a trap is still live detonates it
(`FUN_0056a922`, log `Trap detonating on use key attempt`). A safe lock
clears `+0xd8`. On a key screen (types 2 and 3) the UI then closes and
the character's `OnTrigger` runs (`FUN_0056ae7e(1)`), which is how a
door conversation continues into `DoLooting` or a teleport.

Dropping a tool on the lock is `FUN_00569046`:

| Control | Mode | Tool |
|---|---|---|
| `0x95` | 4 | Probe |
| `0x96` | 5 | Lockpick |
| `0x97`, `0x98`, `0x99` | from `FUN_0056adf7` | The three disarm picks |

A lockpick dropped on a lock that is still trapped detonates, same as the
key. With the animated tools off (`DAT_00617a5c == 0`) the attempt is a
roll in `FUN_004894fb`: a uniform integer from `-toolFit` through 101.
It succeeds when that roll is strictly less than the character's skill.
The tool fits and the skill virtual are:

| Mode | Tool fit | Skill |
|---|---:|---|
| 1 | 100 | virtual `+0xa4` |
| 2 | 400 | virtual `+0xa4` |
| 3 | 900 | virtual `+0xa4` |
| 4 probe | 900 | virtual `+0x9c` (Stealth, skill line 9) |
| 5 lockpick | 1400 | virtual `+0xa0` |

A successful lockpick (`FUN_0056a6a6`) clears `+0xd8` unless
`DAT_0066fcb4` is set. A failed probe or lockpick plays the fail
(`FUN_00569dc5`). A failed disarm of modes 1..3 rolls `1..101` against
virtual `+0xa4` and detonates when the skill is below the roll
(`FUN_00569d0e`). That is the `TrapGame` off path. The gear, the
angle windows, and the wait before `OnFail` are in
[`traps.md`](traps.md).

Scenes call `SetLocked()` from `OnEnter`, so a door the player has not
opened starts shut even though a fresh character is created unlocked.
`ClearLocked` is the script way through; the lock screen is the player
way through.

---

## 11. Item scripts

`InventoryItemScript.txt` attaches a script object to a catalog name.
The events the engine actually calls are:

| Event | When |
|---|---|
| `OnPickup` | The instance was just added to a party member (`FUN_004c9c58`) |
| `OnDrop` | It was just removed from one (`FUN_004c9fb8`) |
| `OnEquip` / `OnUnEquip` | `FUN_004ca351` changed a slot, and the owner is a party member |
| `OnAssess` | `PutItemInInventory` and the shop purchase pass a true assessed flag, and the owner is a party member |
| `OnCanUse` / `OnUse` | Using the item from the inventory screen |

Most rows in the file are empty stubs left over from the template
(`Dagger_poor`, `Godswrath`). The ones with bodies are plot items:

- `Nightstone` `OnCanUse` is true only in chapter 7, by day, in scene
  `60009`, before the party has used it. `OnUse` leaves the inventory,
  plays `OpenTombDoor`, flips the crypt lighting, teleports, disarms two
  sensors, and starts conversation `C71092ROOT`.
- The fake intact gems set `Chapter3.bHaveFakeRubies` on pickup, and
  their `OnCanUse` is chapter 3 only.
- Documents and the Black Pearl Necklace have their own `OnUse` bodies
  further down the same file.

The call is on the definition, `definition->vtable + 0x30`, with the
event name. A container that fails virtual `+0x10c` does not run
`OnPickup` or `OnDrop`, so moving loot around inside a chest does not
fire the plot events. The events fire when the piece lands on a party
member.

---

## 12. How a character is stocked

`Chars.tbl` puts the starting bag on the definition. Two spellings show
up. A one-line entry names the item and, optionally, a quantity and an
assessed flag:

```
Lockpicks
Antidote - Weak,1,1
Potion of Healing - Weak,1,1
```

A block names one or more candidate rows, a quantity, a quality band,
and whether it starts assessed:

```
Item
  DEF     : Rapier_average
  Quality : 98,100
  Quantity: 1
end
Item
  DEF     : Gold
  Quantity: 0,4,7
end
Item
  DEF     : Scimitar_poor, Dagger_average, Dagger_good
  DEF     : Scimitar_poor, Scimitar_good, Dagger_excellent
  Quantity: 1
  Quality : 75, 100
End
```

Several `DEF` lines, and several names on one line, are the authored
way to offer a draw. `Quantity: 0,2` and `Quantity: -1,2` are ranges,
including "maybe nothing." Gold's three numbers are the stack James and
Jazhara start with (`0,4,7` and `1,8,4`). The function that rolls those
lists was not separated from the rest of the character loader.

`Yusufs Desk` is a stocked container: `Nationality : Lootable`,
`Model_Type : Desk`, `Money : 25`, and a bag that includes
`Recipe for Fire Oil - Weak`, `Yusuf's Key,1,1`, a weapon draw, and
potion ranges. An empty `Treasure Chest` is the same kind of character
with an empty `InventoryItems` block; the chapter fills it later with
`PutItemInInventory`, or the player fills it by dragging.

---

## 13. Where a transfer comes from

| You wanted | The call |
|---|---|
| Script gives a party member or an NPC one item | `PutItemInInventory` |
| Script takes one item away, by name, from whoever has it | `IsItemInInventory` then `RemoveItemFromInventory`, the chapter 9 catalyst check |
| Script moves a whole bag onto another character | `TransferEquipment` |
| Script spills a body onto the floor | `DropAllOwnedItems` |
| Script plants a fresh item in the room | `DropItem` |
| Player moves gear between companions, or between a companion and a chest | The inventory grid, `FUN_00541c2b` |
| Player drops something in the world | `FUN_0053f1a5` into the `DroppedItems` group |
| Player buys or sells | `DoShopping`, then `FUN_0055f4cc` / `FUN_0055f68c` / `FUN_0055f8d8` |
| Player opens a locked chest or door | `OnTrigger` sees `IsLocked` or `IsTrapped`, calls `DoTrapLock`, and on the next click `DoLooting` |
| A matching key, or the Magic Key, is in the bag | `FUN_004c8c92` |

---

## 14. Open questions

- **The `Chars.tbl` roller.** The `DEF` lists and the `Quantity` pairs
  are consistent across the file. The function that picks one name and
  rolls the range was not pulled out of the character loader.
- **`DAT_0066fcb4`.** When it is set, a successful lockpick does not
  clear `+0xd8`. Nothing in the paths above writes it.
- **Class limits.** `INV_CLASSLIMIT_*` and the `UseByMage` family are in
  the data. `FUN_004ca351` itself does not test them; a gate in the
  inventory UI was not walked.
- **The eight slot names.** The header in `RtkGame.def` disagrees with
  itself on slot 4, and the engine only pins slot 0 (a weapon) and slot
  1 (a shield). The other six were not each matched to a body location.
- **Virtual `+0xa4`, `+0x9c`, and `+0xa0`.** They are the shorts the lock
  roll compares. They were not named back to a skill row in `Chars.tbl`.
