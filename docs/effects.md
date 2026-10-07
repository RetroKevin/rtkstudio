# How effects are drawn

A flame, a zap, a heal glow, and an explosion are the same object: a
True3D actor running a `.bex` graph. The graph swaps sprites, moves the
actor, scales it, and fades it. The caster's gesture and the target's
flinch are ordinary skeletal clips on the characters, played on the same
clock. Nothing in the shipped game is a particle system.

True3D does contain a particle-sprite type. Return to Krondor never
defines one, never instances one, and the effect loader refuses the type
if a graph asks for it. The rest of this note is what the game does
instead, in a fight and on the adventure map, and what a magical item
would have to touch to grow a picture of its own.

The file layouts and the node-type table are already written:

| What | Where |
|---|---|
| `.bex` record layout, node types, joints, events | [`misc-formats.md`](misc-formats.md) |
| Cast clip, flinch clip, projectile graphs | [`animations.md`](animations.md) §6 |
| Spell math, the 85 effect names, item modifier names | [`combat.md`](combat.md) §12 and §16 |
| Backdrop, actors, compose order | [`scene-runtime.md`](scene-runtime.md) |
| Trap blasts `explo.bex` / `explog.bex` | [`traps.md`](traps.md) |

Function names are the stable citations. `RtK.c` line numbers are against
`out/decompiled/` as it stands; `python tools/show_func.py out/decompiled/RtK.c FUN_0042ceaf`
re-finds one.

---

## 1. What is on screen

A scene frame is still the three layers in [`animations.md`](animations.md):
the 640×480 painting, True3D actors in that camera, then the flat Rtlib32
interface. An effect is an actor in the middle layer. It is occluded by
the same depth overlay as a character. It is not a 2D sprite queue, and
it is not a colour cycle in the painting.

`FUN_0042ceaf` (`RtK.c:29327`) is the spawn. It places a new actor on the
source character, built from the shared `SPELLGEN_ACD` definition the
world load looks up (`RtK.c:166150`), and tints it with `FXPALETTE.BMP`.
`FUN_004fe548` (`RtK.c:166751`) then hangs the parsed `.bex` on that
actor and records the source id and the target id. Each frame
`FUN_0042fb8d` (`RtK.c:31060`) runs whichever nodes are active.

A node can only put two kinds of mesh on that actor. `FUN_004fe06b`
(`RtK.c:166564`, the `LoadFXSprite` log) accepts a dictionary object
whose type word is 7 or 9 and rejects everything else with
`ResMgr: LoadFXSprite: invalid sprite`:

| Type word | What True3D calls it | Loader |
|---|---|---|
| 7 | simple-sprite definition | `FUN_10001000` returns early when `*obj == 7` |
| 9 | 3D-sprite definition | `_t3dDefine3DSprite` sets `*obj = 9` |
| `0xb` | particle-sprite definition | refused |
| `0xc` | particle-sprite instance | refused |

Those sprites live in `FX.t3d` and `HiColorFX.t3d`. A type-9 node in the
graph names one. A type-12 node fades it by writing the polygon render
method's upper nibble. A type-7 node pins the actor to a joint
(`FX_DAG_*`, the same 20-joint rig as a character). A type-8 node hides
the actor or toggles a light. A type-4 node ends the graph. The full
switch is in [`misc-formats.md`](misc-formats.md).

Coloured room light is a third, separate thing: an `.ldx` light
definition (`fxred.ldx`, `fxblue.ldx`, `flames.ldx`, `strobe.ldx`, and
the rest under `Worlds/`). A torch is one of those, not a tile and not
a `.bex`.

---

## 2. The particle type the game does not use

`t3dll.dll` exports a full particle-sprite API. A definition is object
type `0xb` (`FUN_10032190` stores that word). An instance is object type
`0xc` (`t3dIsParticleSpriteValid`). The world loader creates them from
two chunk types in `FUN_10022d60` (`t3dll.c:27314`):

| Chunk | Function | Role |
|---|---|---|
| `0x0c` | `FUN_10023f60` | define a particle sprite |
| `0x0d` | `FUN_100240a0` | instance one into the world |

The chunk census in [`world-format.md`](world-format.md) walks every
FastFile in the install, 2,089 files. Types `0x0c` and `0x0d` are absent.
No shipped world, model, or effect archive contains a particle sprite.

The instance the API describes is a cloud of palette pens, not a textured
billboard:

| Export | What it stores |
|---|---|
| `t3dSetParticleSpritePenList` | the colour pens, one per point |
| `t3dSetParticleSpriteUseLargeDots` | a flag at instance `+0x6c` |
| `t3dSetParticleSpriteRenderMethod` | the draw method at `+0x1c` |
| `t3dSetParticleSpriteCenterOffset` | the cloud's origin |
| `t3dSetParticleSpriteConstantIntensity` / `AmbientScaler` | brightness |
| `t3dSetParticleSpriteCollisionVolume` | a collision shape |

`t3dSetActorSprite` will accept a type-`0xc` instance as a joint's mesh
(the same call that accepts a simple, 2D, 3D, or hierarchical sprite).
`t3dCreateCollisionDisplayActor` builds one for the engine's collision
debug actor. The game's effect path never reaches either call with a
particle. `LoadFXSprite` bails out before a `.bex` can name one.

So a new "particle effect" in the sense the engine understands is a new
`0x0c`/`0x0d` chunk, or a direct `t3dCreateParticleSprite` call. A new
spell picture, which is what players see, is a new `.bex` plus sprites
in `FX.t3d`.

---

## 3. During combat

The fight is the same scene. Nobody loads a battle map. The picture is
started only from `FUN_004a5207` (`RtK.c:104341`), and only when both of
these are true:

- the spell's `Behavior_File` string is non-empty (`spell + 0x58`)
- the combat flag is set: `*(DAT_00628d6c + 0x368) + 0x84 != 0`

The log line on that branch is `... Visual Effects ... Kick Off ...`. It allocates
the `KRPEffect` (`FUN_004899f5`, 0x84 bytes) and hands it to the combat
cast `FUN_00489dc4`. The other branch, taken for an empty behavior file
or any cast while that flag is clear, applies the numbers through
`FUN_00495d4b` and does not create the effect object.

### A cast

The gesture and the graph are the sequence in
[`animations.md`](animations.md) §6. Short form:

1. The body plays `A_Cast Attack Spell` or `A_Cast Personal Spell`
   (creatures play their own `castspell` row).
2. At the row's first time (`14.5` on the attack cast, `15.7` on the
   personal cast) `On Casting Hit` calls `FUN_0048a522` (`On Start FX`).
3. That reads `Behavior_File` and calls `FUN_0042ceaf` once per target,
   or once on the caster when the spell aims at itself.
4. The graph listens for `Rp2Fx` events: `0xb` proceed, `0xc` damage,
   `0x15` apply or duration, `0x16` dispel or expire, `0x17` resist.
5. The target's body, separately, plays `A_Zapped`, `A_On Fire`,
   `A_Dazzled`, `A_Head Hurts`, or `A_Writhes in Pain`. Those clips loop
   for a condition. There is no second particle layer under them.
6. Sound is the same moment: `Spell_<path>_Cast`, `_Hit`, or `_Fail`.

A slow cast (mage class word 4) can be interrupted before step 2. Quick
and inner casts arm both the hit time and the sync time.

### A shot

Bows, bolts, and thrown spells are a second effect object, not a cast.
`FUN_0048e6db` picks the graph: `normarrow.bex`, `normbolt.bex`,
`normcbolt.bex`, or `zsto2ric2.bex`. A flaming arrow is the one swap:
actor `+0xbc == 0x19` loads `zfirarr.bex` instead of `normarrow.bex`.
Impact sends event `0x15` and then the flinch clip.

### What a swing does not do

A weapon enchantment does not spawn a graph when the blade moves. The
graph, if any, was spawned when the enchantment was cast. Later hacks
are the melee clip alone. `Weapon_DemonBlade` (the Hellblade-class
modifier) sets actor `+0x304` to 1 inside the magic scan and logs
`DemonBlade Magic Weapon` (`RtK.c:111707`). No traced reader of that
word starts a `.bex` or swaps the weapon mesh.

---

## 4. Out of combat

The same `FUN_004a5207` test is the whole rule. If
`*(DAT_00628d6c + 0x368) + 0x84` is 0, a spell, a potion, and a
`CastOnUse` item all take the immediate-apply branch. The numbers land.
The cast clip does not play. The `.bex` is not spawned. Drinking a
healing potion on the adventure map is silent as a picture even when
the matching combat potion has a behavior file.

A few potion rows split the *numbers* by that same flag, which is a
different mechanism. `Effect_Check : IfInCombat` and `IfOutCombat` are
spell-effect gates (ids 8 and 9 in [`combat.md`](combat.md) §12). They
decide whether a modifier is stored. They do not start a graph.
Regeneration and the poison potion are the rows that use the pair: one
effect for a fight, a different effect on the map, and neither row has
a `Behavior_File`.

### What does draw outside a fight

Chapter scripts call `LaunchFX`. `FUN_0050e094` (`RtK.c:178725`) is the
verb. It resolves the source character and the target character, then
calls `FUN_0042ceaf` with the `.bex` name. It does not look at the
combat flag.

```
LaunchFX ("nrgzap.bex", James, SidiCharacter)
```

A fourth argument of `TRUE` retains the actor. The handler stores the
id in a 10-slot table at `DAT_00628d6c + 0x4bbe0` and returns the slot
index. `TerminateFX` (`FUN_0050e2bb`) destroys that actor. The table is
full at 10; the log is `LaunchFX ERROR:  no empty retainer slots, free a slot!`.

Nine chapter files call it, 128 times, 23 distinct graphs. The common
ones are story beats, not spells: `gappear.bex` (26), `appear.bex` (19),
`healme.bex` (18), `zarrow2.bex` (18), `nrgzap.bex` (12), `zapped.bex`
(6), `blulight.bex` (5). A few are held: chapter 1 keeps `zfirbody.bex`
and `zfirhead.bex` on James, chapter 10 keeps `zrhand.bex`, `glight.bex`,
`zr2hand.bex`, and `zr3hand.bex`. One `zfirebody.bex` call in chapter 8
is commented out.

Traps are the other hard-coded spawn. Mechanism 6 plays `explo.bex`,
and mechanism 4 with delivery 9 plays `explog.bex`. See
[`traps.md`](traps.md). Those calls go through `FUN_0042ceaf` as well,
so they show on the adventure map.

Room light, fog, and the hotspot glow stay as they were. They are scene
data, not effects.

---

## 5. Spells

`MagicResult.txt` is 113 records. 73 name a `Behavior_File`. 51 distinct
files cover them; `zfir2dem.bex` alone is six records (Demonblade,
Phoenix Blades, both poison-oil potions, both magic-blade potions).

The 60 player spells, ten on each of six paths, all have a file. The
prefix is the path: `zfir`, `zmen`, `zlif`, `zdiv`, `zcha`, `zsto`.
Paths, costs, and the modifier record are in
[`combat.md`](combat.md) §12. This table is only the picture.

The 40 records with no file never take the visual branch, in or out of
combat, because `FUN_004a5207` treats an empty behavior string as
"apply now". They are:

- three item-weapon rows: `Weapon Demonblade`, `Weapon Stun`, `Weapon Blind`
- the ten `Monster …` attacks (the creature clip is the picture)
- twenty-three potions and the four `Path of …` rows and
  `Scroll of Elementals Protection`

The thirteen non-player records that do have a picture:

| Record | Type | File | Duration |
|---|---|---|---|
| Potion Fire Oil Weak / Strong | Attack | `zpotfoil.bex` | Instant |
| Potion Beast Weak / Strong | Transform | `zchabea.bex` | Battle |
| Potion Fire Shield Weak | Protect | `zsto2shiw.bex` | Rounds |
| Potion Fire Shield Strong | Protect | `zsto2shiw.bex` | Battle |
| Potion Poison Weak | Weapon | `zfir2dem.bex` | Rounds |
| Potion Poison Strong | Weapon | `zfir2dem.bex` | Battle |
| Potion Holy Balm Weak / Strong | Attack | `zpotpalm.bex` | Battle |
| Potion Magic Blade Weak / Strong | Weapon | `zfir2dem.bex` | Battle |
| Poison Death | Strike | `zfir2lan.bex` | Instant |

`zfir2dem.bex` is the flame-on-a-weapon graph. A magic-blade potion and
a poison-oil potion show that same graph. They do not get a graph of
their own. And they show it only inside a fight.

---

## 6. Magical items

`MagicInvItem.txt` is 464 items. `Quality_Original : Magical` is a
quality tier (367 items, plus one spelled `Magic`), the same ladder as
Poor / Average / Good / Excellent. It does not mean the item has a
picture. 62 of those Magical rows have no `Effect` block at all.

An item effect is one of three kinds. The keyword table is at
`0x5f30b8` in `RtK.exe`, pairs of name and id:

| Keyword | Id | What it is |
|---|---|---|
| `Ready` | 0 | passive modifiers while the item is worn. 150 blocks |
| `Use` | 1 | something the player invokes. 143 blocks |
| `Unready` | 2 | the adventure-mode hook, tested before `OnCanUse`. 31 blocks |

`Effect_NonCombat` is stored at effect `+0x18` by `FUN_004f83c9`.
`FUN_004909fe` (`RtK.c:92320`, log `UseItm`) reads it. Out of combat, a
`Use` effect with `Effect_NonCombat : 0` is greyed out. `1` leaves it
enabled. 101 blocks are `1`, 73 are `0`. The flag does not start a
graph. It only decides whether the menu row is live on the map.

### Ready: numbers, no mesh

A `Ready` block is the modifier list (`Modifier_Attack`,
`Weapon_AddFireNormal`, `Weapon_DemonBlade`, …). The scan copies those
into the actor's effect slots. Hellblade is the pattern people expect
to burn: the description says the blade dances with flame, and the data
is

```
Effect : Ready
  Effect_Modifier : Weapon_DemonBlade    value 5
  Effect_Modifier : Modifier_Attack      value 25
```

There is no `Behavior_File` field on an item, and this block never
calls `FUN_004a5207`. The flame sentence is prose. The mesh is whatever
bitmap `Chars.t3d` already uses for that weapon. Equipping it does not
attach a sprite to `R_HAN` and unequipping it does not remove one.

The item-side spell that *would* be the flame, `Weapon Demonblade`
(item-spell id 0, `Item_WpnDemonblade`), is one of the 40 records with
no behavior file. Pointing a `CastOnUse` at it would still not draw
`zfir2dem.bex`. The player spell `Demonblade` is the record that names
that file.

### Use: a spell, and a picture only in a fight

`Effect_Magic` is a second closed table at `0x5f3450`:

| Keyword | Id | Log line when the item is described |
|---|---|---|
| `CastOnUse` | 0 | `Magic On Use` |
| `WhenWearing` | 1 | `Magic Active` |
| `WhenRead` | 2 | `Magic if Read` |

`WhenRead` is implemented and unused. No shipped item says it.

`CastOnUse` names a spell in the table at `0x5f3470` (79 names,
`Fire_FireRain` through `Mstr_TouchShadows`). `FUN_004de963` resolves
that name to a `MagicResult` record when the player uses the item.
`FUN_00488e3a` then calls `FUN_004a5207` with the item flag set.

Inside a fight, a non-empty `Behavior_File` on that spell takes the
visual branch: cast clip, graph, sound. Thunderstaff's `Use` block
casts `Storm_LightStrike`, so the lightning picture is the spell's
picture, played because a fight is running. Outside a fight the same
use applies the spell and skips the graph, even when `Effect_NonCombat`
is 1.

123 items have a `CastOnUse`. The ones players think of as glowing
weapons (Hellblade, Catalyst, the enchanted blades) are not in that
set. Their magic is a `Ready` modifier.

### Unready: a script, not a glow

Four items put `WhenWearing` on an `Unready` block, all aimed at
`Special_Script` (item-spell id 78), all with `Effect_NonCombat : 1`:

- Black Pearl Necklace
- Nightstone
- Whisperer's Locket
- ScepterOfKarack

`Special_Script` is not a behavior file. The picture, if the scene has
one, is a `LaunchFX` the chapter already calls, or nothing. Nightstone's
`OnUse` is chapter script; see [`inventory.md`](inventory.md).

---

## 7. How a picture could be added to an item

No item row can name a `.bex`. The hooks that already reach
`FUN_0042ceaf` are a spell's `Behavior_File` and a chapter's `LaunchFX`.
Everything else is a code change. These are the cuts, in the order that
matches how the game is already built. None of them are made here.

### A picture that already works, if the spell has a file

Give the item a `Use` block with `Effect_Magic : CastOnUse` and
`Effect_Spell` set to a spell that already has a `Behavior_File`.
In combat, `FUN_004a5207` plays that spell's cast and graph. The
magic-blade potions are the shipped example: they are weapons in the
data, and they show `zfir2dem.bex` because their *spell* names the file
and because they are used in a fight.

`Weapon Demonblade`, `Weapon Stun`, and `Weapon Blind` do not qualify.
They are the item-facing copies, and their behavior string is empty.
A Hellblade that should burn has to point at the player spell
`Demonblade`, or the item-facing copy has to grow `Behavior_File : zfir2dem.bex`.

That still does nothing while the weapon is merely worn, and nothing
on the adventure map. The cast plays when the item is used, then the
graph lives as long as that spell's duration says, then `0x16` tears
it down. The next swing does not start it again.

### A picture on the map, without a new executable path

`LaunchFX` already ignores the combat flag. A chapter `OnUse` (the
same verb Nightstone uses) can call

```
LaunchFX ("zfir2dem.bex", JamesCharacter, JamesCharacter, TRUE)
```

and hold the actor until `TerminateFX`. Ten retained slots are the
ceiling. The graph's own nodes decide whether the sprite sits on
`R_HAN`, the head, or the actor root. This is how chapter 1 keeps a
fire on James and how chapter 10 keeps hand-glows. It is per scene
script, not a column on the item. Dropping the item, or walking into
a chapter that does not repeat the call, drops the picture.

A static "this blade looks magical" change is not an effect at all.
The weapon mesh is a sprite in `Chars.t3d`. A different bitmap is how
Hellblade already differs from a mundane dagger. That swap does not
animate unless the simple-sprite frame index is driven, which equipment
does not do today.

### What has no hook

Three gaps are real, and each one is a specific branch:

1. **Worn items never start a graph.** A `Ready` block is applied by
   the magic scan. It does not call `FUN_004a5207` or `FUN_0042ceaf`.
   A glow that appears on equip and leaves on unequip needs a new call
   at the ready and unready sites, with the actor id stored somewhere
   the 10-slot `LaunchFX` table does not already own. `WhenWearing`
   is the keyword that sounds like that hook. On the four items that
   use it, the payload is `Special_Script`.

2. **Out-of-combat use never starts a graph.** The gate is the second
   clause of `FUN_004a5207`: combat flag clear means immediate apply.
   Removing that clause would send map-use down the same `KRPEffect`
   path as a fight. The cast clip picker still expects the combat
   catalog and a combat animation queue, so the graph can be spawned
   from `FUN_0042ceaf` directly (as `LaunchFX` does) more cleanly than
   by forcing `FUN_00489dc4` to run with no fight.

3. **Particle sprites cannot be named by a `.bex`.** `FUN_004fe06b`
   accepts type 7 and type 9 only. Authoring a `0x0c` chunk would put
   a particle definition in a world, and `t3dSetActorSprite` could hang
   the instance on a joint, but no shipped graph can request it. A
   spark aura on a sword is a new sprite in `FX.t3d` (a simple sprite
   or a 3D sprite) driven by a `.bex`, or it is an engine change that
   teaches `LoadFXSprite` to accept type `0xb`.

A coloured light on the hand is the closest glow the current nodes can
do without new art: a type-8 light toggle, or an `.ldx` the scene
already knows how to load (`fxred.ldx` and the others). The graph still
has to be started by one of the two hooks above.
