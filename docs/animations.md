# How animation works

Return to Krondor draws a still painting, then moves 3D actors in front of
it. Almost every character motion — walk, talk, swing, flinch, cast — is a
skeletal clip on that actor. Spell fire, glows, and explosions are a second
system: small scene graphs that swap sprites, move them, and fade them.
Buttons, cursors, and puzzle screens are a third system, ordinary 2D sprite
lists composited by Rtlib32.

This note is the runtime. The file layouts it sits on are already written
up elsewhere:

| What | Where |
|---|---|
| `.trk` / `.trx` / `.trm` keyframes and lip-sync text | [`track-format.md`](track-format.md) |
| Joint hierarchy in `.adf` chunk `0x10` | [`sprite-format.md`](sprite-format.md) |
| Spell-effect graphs (`.bex`) | [`misc-formats.md`](misc-formats.md) |
| Fight rules, hit math, the cast order | [`combat.md`](combat.md) |
| Backdrop, depth overlay, compose order | [`scene-runtime.md`](scene-runtime.md) |
| UI bitmaps, cels, queues | [`rtkres-format.md`](rtkres-format.md), [`bitmap-codec.md`](bitmap-codec.md) |

Function names are the stable citations. `RtK.c` line numbers move every
time the decompile is regenerated;
`python tools/show_func.py out/decompiled/RtK.c FUN_00441aca` re-finds one.

---

## 1. What is on screen

A scene frame is three layers, composed by `FUN_0045cfd0`:

1. A 640×480 8-bit painting (`.di_`). One picture per camera view. It does
   not animate.
2. True3D actors, rasterized into the same camera, with the `.ovx` depth
   overlay punching out pixels the painting should hide. Characters, doors,
   chests, and spell props are all actors.
3. Rtlib32's 2D compositor: cursor, dialogue UI, inventory, fades. That
   pass calls `SpriteAnimate` every refresh. The function is imported;
   its body lives in `kronctrl.dll`, which is not in this decompile.

Cutscenes are separate `.avi` files (XviD in the GOG build), not this
pipeline.

The engine has a particle-sprite type, and the game never uses it. A
"spell effect" is an actor (or a few of them) driven by a `.bex` graph.
A torch is a light definition in a `.ldx`, not an animated tile. Where
those graphs run, in a fight and on the map, and why a magical item
does not start one, is [`effects.md`](effects.md).

---

## 2. A 3D character

### The rig

`Models.def` names, for each character, an `.adf`, a sphere, a
hierarchical-sprite tag, an actor tag, and a palette bitmap. James is:

```
James : A1James.adf, A1CJAMES.SPH, A1CA1CJAMES_HS_DEF, A1JAMES_ACD, ...
```

The `.adf` chunk `0x10` is the skeleton: an array of dags, each 0x140
bytes at runtime, each pointing at a child list, a mesh, and a track.
`t3dll` builds that in `FUN_10024120` and instances it with
`t3dCreateHierarchicalSprite` (`FUN_10024300`). The game spawns the actor
with `t3dCreateActor`.

A humanoid dag name starts with a 3-character rig prefix (`A1C` on James)
and then a joint: `KIL` is the pelvis, `DUMMY01` is the root, then the
legs, torso, arms, neck, and head. The 17-joint set, and the 20-joint set
that adds three shadow helpers, is listed in
[`track-format.md`](track-format.md). Forty-nine distinct hierarchies
ship; most characters share one.

The mesh on a dag is a 3D sprite (chunk `0x08` / `0x09`) textured by
BMInfo records whose names are archive `.bmp` files. A dag can instead
carry a **simple sprite** (chunk `0x04`): an ordered list of those
bitmaps. That list is how a face changes expression and how a door
changes from shut to open — a frame index, not a skeleton.

### The clip

A `.trk` is one clip. It holds one track definition and one track object
per joint. On disk each keyframe is eight floats (quaternion, translation,
scale). The loader (`FUN_10024380`, then `DefineTrack`) scatters that
into a 9-float runtime record, 0x24 bytes per frame. Shipped animated
joints are authored at **33 ms** per frame, speed 1.0, with the reverse
and interpolate bits clear. The root joint `DUMMY01` has a single
keyframe in every loose file; the body motion is on `KIL` and below.

917 loose clips live in `Tracks/`, each with a sibling `.trx`. Another
801 `.trk` files live inside the `.t3d` archives (the combat and gesture
libraries). Both are the same format.

### Binding a clip to a skeleton

`FUN_00441aca` is the bind. Given an actor and an animation resource it:

1. Turns on user frame control for that hierarchical sprite, so the game
   — not the engine's free-running clock — owns the frame index.
2. Loads the `.trk` if it is not already in the True3D dictionary
   (`FUN_004fdde0` → `t3dParseReadWorld`).
3. Walks every dag except dag 0. It copies 7 characters from the resource
   at `+0x28` (the clip stem: `CMBT007`, `TK0005M`, `GEST012`) and appends
   the dag name **with its first three characters skipped**, then
   `_TRACK`. `A1CKIL` plus stem `CMBT007` looks up `CMBT007KIL_TRACK`.
4. `t3dSetDagTrack` installs that track. A track with fewer than two
   frames is pinned to frame 0. A longer track gets a from-frame of 0 (or
   the caller's start offset) and a to-frame read from the resource at
   `+0x50`.
5. Dags whose names contain `SPACER_` or `WEAPON_`, plus two further
   prefixes at `DAT_005d65b8` and `DAT_005d65c0`, are left alone. Those
   are attachment points, not animated bones.

This is also the answer to the open question in
[`sprite-format.md`](sprite-format.md) about a 7-character paste. The
engine does not overwrite the dag's own name. It builds a new dictionary
tag: 7-character stem, then the joint, then `_TRACK`. The exact order of
the string operations in the decompiler is still a bit scrambled (a
4-character copy lands on the same buffer after the joint suffix is
appended), but the inputs are the stem at `+0x28` and the dag name from
character 3.

### Playing it

Each frame the engine samples the installed tracks and runs forward
kinematics.

- `FUN_1007f730` advances a track's logical frame from world time, the
  update interval, and the loop / reverse bits.
- `FUN_10019810` walks the dag tree from the root. When the from-frame
  and to-frame differ it lerps translation and scale and calls
  `t3dSlerpQuaternions`, then concatenates the parent quaternion. The
  interpolate enable bit lives on the dag at `+0x11c`; the blend fraction
  is the float at `+0x104`.
- `t3dHierarchicalSpriteUpdateAllTransformations` publishes the result
  and refreshes bounds.

The game does not leave that clock alone. Actor userdata `+0x11c` is an
animation queue (`CAnimationQueue` is the failure string in
`FUN_0040cd7c`). `FUN_0040bc8b` integrates queue time, honours reverse and
ping-pong flags, and pushes from/to/blend into every dag through
`FUN_0040baf2` / `FUN_0040b9f9`. `FUN_0040cfba` is what actually calls
`FUN_00441aca` when a queue item starts. A cross-fade between two clips
is `FUN_0040c4c0`: it slerps keyframes from one track definition into
another.

Combat animation speed is a separate scale. The options screen writes
`Combat Animation Speed` (`CombatSpeed` in the ini); `SetCombatSpeed` is
also a console verb. See [`combat.md`](combat.md) §15.

---

## 3. Who picks the clip

Clips are not chosen by filename in the chapter scripts. They are rows in
`RtkGame.def`, turned into animation resources at load, and the game
passes a resource id into the queue.

### Gestures and conversation

`TrackGroup Gestures` (about line 3561) is the adventure library:
`gest001.trk` through the `gest*` and `cust*` files. The comment on each
row is the performance — "head turn left", "pointing north", "squatting",
"laugh", and a `Bound/` set for a character who is tied up. A row is
shorter than a combat row: file, track-def tag, frame id, from, to, comment.

`GestureDef` blocks under that group bind a stance to one or more of
those tracks. Stances are `Stance-Even`, `Stance-Normal`, `Stance-Angry`,
`Stance-Crossed`, `Stance-Sitting`, `Stance-Bound`. A named gesture such
as `Normal-Laughing` lists `GEST012DUMMY01_TRACKDEF`. Conversation lines
request a gesture; the queue plays that track on the speaker.

Dialogue body motion is the loose `TK####M.trk` set (the 917 files).
Entering a conversation calls `FUN_0052b981`, which binds the 7-character
stem the same way `FUN_00441aca` does. `FUN_0052bbe7` loads the file on
demand, building a `…DUMMY01_TRACKDEF` tag first.

### Walking

Walks are clips in the combat catalog, not a separate locomotion format.
The names in `CTrackGroup Combat` say what they are: `A_Walking`,
`A_Walking Starting`, `A_Walking Cycle`, `A_Walking Ending`, then
left/right and normal/skirt variants (`Str Rt Walk Norm`, `Cyl Lt Walk
Skrt`, `Lft Nrml Walk2Run`, …) and one walk per body letter
(`A_Walk_A` … `A_Walk_F`). Creatures get their own: `naga` walk
start/cycle/end, `ratt` Walk Start/Cycle/Stop, `dmon` walk_startright,
and so on.

The movement controller (`FUN_004586b3` and `FUN_00456d2d`) enqueues
whatever resource id it was given. `FUN_004568c9` maps the surface the
actor is standing on, and the actor's class, to a slot index stored on
the controller. `WalkTo` / `RunTo` are script verbs; they do not name a
`.trk` themselves.

### Combat poses

`CTrackGroup Combat` (from about line 5576) is the whole fight library.
A row looks like:

```
cmbt007.trk, CMBT007DUMMY01_TRACKDEF, FRAME_CMBT007, FRAME_CMBT_FROM, FRAME_CMBT007_TO, 6.200000, 0.000000, 250, 15, 1, 0, 67109392, A_Hack
```

| Field | Role |
|---|---|
| file, `…_TRACKDEF` tag | the clip |
| `FRAME_*` id, from, to | the frame window the queue plays |
| two floats | callback times, in the same units the queue uses. They land on the queued clip at `+0x38` and `+0x3c`. Loops (ambient, walk) are `0, 0`. `A_Cast Attack Spell` is `14.5, 25`; `A_Cast Personal Spell` is `15.7, 19.5`. A cast or a shot schedules its effect off these. See §6 |
| small integers (`250`, `15`, `1`, `0`) | playback and classification. `250` is the common value; attacks often use `100`, `66`, or `33`. Not every one of these has been tied to a struct field |
| large integer | a bit mask. The picker filters on it. Bodies A–F use distinct low bits (`2064`, `2080`, `2112`, `2144`, `2128`, `2096` on the walk rows) |
| trailing name | what the clip is. This is the authoritative label |

Humanoid clips are one file per pose, repeated for six bodies, lettered
**A through F** in the trailing name. A is the unarmed / light set
(punch, throw). B adds hack, slash, thrust, and block. C–F repeat that
vocabulary for the other bodies (skirted walks, different timing). The
`#define FRAME_AAMBIENTFIGHT` block at the top of `RtkGame.def` is an
older, smaller A/B window table (idle, dodge, punch, hack, slash,
thrust, death, cast). The catalog the game actually queues is the
`CTrackGroup`.

The move list, taken from those names:

| Kind | Names |
|---|---|
| Idle | `A_Ambient`, `A_Ambient #1`, `A_Ambient #2`, `A_Combat Movement`, `A_Turning`, `A_Neutral to Fighting Stance` |
| Attack | `A_Hack`, `A_High Slash`, `A_Medium Slash`, `A_High Thrust`, `A_Medium Thrust`, `A_Punch High`, `A_Punch Low`, `A_Throw Potion` |
| Defense | `A_Dodge`, `B_Block High`, `B_Block Low` |
| Hit | `A_Hacked Forwards/Backwards`, slashed, thrust, punched, `A_Hit by Arrow`, `A_Hit from Behind High/Low`, `A_Zapped` |
| Cast | `A_Cast Attack Spell`, `A_Cast Personal Spell` |
| Affliction | `A_On Fire`, `A_Dazzled`, `A_Head Hurts`, `A_Writhes in Pain` |
| Death | `A_Killed from Behind`, plus the death clips on the creature sets; get-up is `A_Get Up from Back` / `from Front` |
| Travel | the walk start / cycle / end rows above |

`CStrikeDefGroup Combat` (about line 6056) pairs an attack frame id with
a reaction frame id — punch-high (`FRAME_CMBT003`) against dodge, punched
high, hit from behind, block high, and the same reactions on the other
bodies. `CTrackReactionGroup` is a shorter list of the same idea. The
reaction that plays is chosen from that table, not invented in code.

### The combat call

A swing that has already resolved its hit (see [`combat.md`](combat.md))
reaches presentation like this:

1. `FUN_0047b4b7` reads the weapon and maps it to an attack style, 1–5.
2. `FUN_00445be0` case 8 calls `FUN_004480ec`.
3. `FUN_004480ec` switches on that style. Style 4 (the armed swing)
   further switches on a second integer and lands on internal pose ids
   1–4; style 5 lands on 8 or 9; styles 1–3 are fixed poses 6, 7, and 5.
   If attacker and defender are the same actor it logs
   `kCombatAnimCharacterAttack`.
4. The matching catalog row is queued (`FUN_00449d07`, `FUN_0044971c`,
   `FUN_0040d0ed`). A timed callback on that queue (`FUN_004494df`) is
   what fires the swing sample, not a second skeleton.

Creature sets live in the same `CTrackGroup`, one prefix per body:

| Prefix | What the names say |
|---|---|
| `gtsk` | Ambient, Attack01–04, Attack Critical, Death, Dodge, React, Writhes, Walk |
| `smsk` | Sewer000–008, Headhurt, Onfire, React, Walk, Writhes |
| `drgs` | Ambient, Dodge, Attack, Reaction to Hit, Affected by Spell, Cast Spell |
| `aire`, `flyd` | ambient, attack, attack2, dodge, death, castspell, reactspell, deathspell |
| `seam` | ambient, dodge, attack, secondary attack, reaction, death, affected by spell |
| `naga` | ambient, dodge, attack, cast, walk start/cycle/end, react, spectacular death |
| `tent` | tent anim 1–8 |
| `dmon` | ambient, dodge, claw, cast, react, walk, die |
| `ratt` | ambient, Walk Start/Cycle/Stop, Dodge, Attack |
| `pign` | walk start/cycle/stop, ambient |
| `skul` | ambient, react to hit, cast spell, die |

These are the "skills" a non-humanoid actually performs. A character's
22-value `Skills` list in `Chars.tbl` is the combat math
([`combat.md`](combat.md) §3), not a list of clips.

---

## 4. Face, mouth, equipment

The head mesh does not lip-sync by moving vertices. A conversation has
two clocks.

The body clock is the `.trk`, played as above. The mouth clock is the
sibling `.trx`: a wav name, a frame count, then pairs of
`(frame index, small integer)`. `.trm` is the same pairs without the wav
line. All 917 loose clips have a matching `.trx`, and the frame count
agrees with the track.

At runtime `FUN_0052be95` walks those frame tables against world time and
fills per-speaker from-frame, to-frame, and blend. `FUN_0052cb32` writes
them with `t3dSetDagFromFrame`, `t3dSetDagToFrame`, and
`t3dSetDagfInterpolationValue`, then updates the hierarchy. The mouth
shapes themselves are simple-sprite frames on the face polygons.
`FUN_00443078` steps those frames; the face tags in the rig are `FACE`
(helpers in `tools/rtkcharacter.py` retarget `FACE`, `FRNT`, `LEG`, and
the other equipment slots the same way). Actor userdata `+0x50`, `+0x54`,
and `+0x58` hold the current face and simple-sprite indices.

Which integer in a `.trx` pair selects which bitmap is the part not fully
walked. The files are viseme timings; the face driver is the simple-sprite
index; the table that joins them was not recovered as a named array.

Equipment and armour are the same mechanism. Swapping a chest piece
swaps which bitmap the torso simple sprite shows. It does not swap the
skeleton. `NO_HEAD_SWAP` on the `Models.def` line is the flag that
forbids the generic head.

Shadows are not authored clips. `FUN_004b7f7e` builds three single-frame
tracks at runtime (`SHADOW%d_TRACKDEF`) and binds them to the shadow dags.

---

## 5. Objects

A door or a chest is a character whose class is `Object`
([`interactions.md`](interactions.md) §8). `Models.def` points it at a
`Container2D` actor (`CONTAINER2D_ACD`): a flat mesh stood in the scene
like any other actor, occluded by the same depth overlay.

Its open / closed / locked look is a simple-sprite frame, not a `.trk`.
`FUN_004431b6` walks the actor's polygons and sets the frame from the
object's state. `FUN_00499b64` / `FUN_00499bfe` call
`t3dSetSimpleSpriteCurrentFrame`. `t3dSuspendSimpleSpriteAnimation` holds
a sprite still.

Anything that is a full hierarchical actor — a creature, a tentacle, the
occasional prop that shipped with an `ATTACK_MARKER` style rig — uses the
skeletal path in §2. A model with no `0x10` chunk does not.

---

## 6. Spells, shots, and skill effects

A spell's picture and a spell's gesture are two objects on one clock.
The gesture is a catalog clip. The picture is a `.bex` graph, started
when that clip reaches the time written on its row. The target's flinch
is a third clip, chosen when the graph reports a hit. Weapon skills do
not get their own graphs. A sword skill is a melee clip. A bow skill is
a shot clip plus one of four projectile graphs. An enchanted weapon is a
spell that was cast earlier; the swing after that is still the melee clip.

The math (cost, resistance, damage attributes) is in
[`combat.md`](combat.md) §12. This section is only what you see.

### What a spell row points at

`MagicResult.txt` is one record per spell, potion, and monster attack.
The picture is the last field:

```
Behavior_File : zfir2dem.bex
```

`zfir2dem` is Demonblade. The prefix follows the path (`zfir`, `zmen`,
`zlif`, `zdiv`, `zcha`, `zsto`) and then a short name. Many records
share one file: Phoenix Blades reuses `zfir2dem.bex`, Restoration reuses
`zlif2bre.bex`. Sixty named spells, and 73 `Behavior_File` lines once
potions are counted. Monster attacks in the same file (`Monster Claws
of a Sewer Monster`, `Monster Teeth of a Death Naga`, and the rest)
have no `Behavior_File`. Their visual is the creature clip from §3.

`Spell_Type` on the row is the mechanical class, not a clip name:
`Weapon`, `State`, `Protect`, `Strike`, `Dispel`, `Heal`, `Combat`,
`Special`, `Transform`, `Lightning`, and on potions `Personal` and
`Attack`. A `Weapon` row such as Demonblade enchants the weapon. A
`Strike` or `Lightning` row is the thing that flies or hits. A `State`
or `Protect` row is the thing that sits on the target afterward.

### The cast clip

`FUN_00489dc4` is the combat cast. It reads the caster's mode at
actor `+0x53c`:

| `+0x53c` | Set by | What the cast does |
|---|---|---|
| 0 | `FUN_0047e431`, log `Quick Casting Mode` | plays the cast clip now |
| 1 | `FUN_0047e48b` when the class word is 4, log `Slow Casting Mode` | queues the effect and does not play the clip yet. A slow cast can be interrupted |
| 2 | `FUN_0047e48b` when the class word is 8, log `Inner Casting Mode` | plays the clip now, same as quick |

The clip itself is one of two catalog rows, repeated per body letter.
`FUN_0048a4a1` returns 4 or 5. `FUN_00445be0` turns that into a picker:

| Return | Picker | Mask passed to `FUN_00445d4b` | Clip it selects |
|---|---|---|---|
| 4 | `FUN_00447514` | `0x80100` | `A_Cast Attack Spell` (flag `524560`, category `0x80100`) |
| 5 | `FUN_00447794` | `0x90100` | `A_Cast Personal Spell` (flag `590096`, category `0x90100`) |

The default is the attack cast. A few spell records flip it to the
personal cast: when the cast-source flag at actor `+0x550` is clear,
`FUN_0048a4a1` looks at spell `+0x1c` and spell `+0x20` and returns 5
for `(+0x1c == 0 and +0x20 == 9)` or `(+0x1c == 5 and +0x20` in
`1, 5, 7, 9)`. When `+0x550` is set, the choice is attack-cast only if
spell `+0x14` is 11. Those three fields were not tied back to
`Spell_Type` or `Magic_Path` by name. Bodies B–F are the same two rows
with their own flags; `FUN_00445d4b` adds the body nibble (`0x10` A,
`0x20` B, `0x40` C, `0x60` D, `0x50` E, `0x30` F) before the catalog
filter in `FUN_00446333`.

Creatures do not use these two rows. Their cast clips are the ones
named in the catalog: `aire`/`flyd` `castspell`, `naga` `cast spell`,
`dmon` `castspell`, `skul` `cast spell`, `drgs` `Cast Spell`.

### How the clip releases the picture

The effect object is a `KRPEffect` (the constructor logs that name,
vtable `PTR_FUN_005a79a0`). The cast stores it on the queued clip at
`+0x50` and arms three callbacks:

| When | Function | Virtual | What it logs and does |
|---|---|---|---|
| clip callback at `+0xc` | `FUN_0048995f` | `+0x14` `FUN_0048b8ef` | `On Casting Str`. A log only |
| time at clip `+0x38` | `FUN_0048997b` | `+0x18` `FUN_0048bac6` | `On Casting Hit`. If the graph is not already up, calls `FUN_0048a522` |
| time at clip `+0x3c`, and only when effect `+0x44` is set | `FUN_00489997` | `+0x1c` `FUN_0048bb53` | `On Casting Sync`. Starts the graph if the hit callback did not, then advances it |

`+0x44` is 0 only for a pure slow cast. Quick and inner casts set it,
so they arm both times. On `A_Cast Attack Spell` that is 14.5 and then
25. On `A_Cast Personal Spell` it is 15.7 and then 19.5. Those numbers
are the two floats on the catalog row.

`FUN_0048a522` logs `On Start FX`. It reads the behavior name from
spell `+0x58` (the `Behavior_File`, already cached by `FUN_004fe4ca`)
and calls `FUN_0042ceaf` once per target, or once on the caster when
the spell is aimed at itself. Each returned id is kept so a later
message can poke that instance.

The poke is `FUN_0042d26c(fxId, -1, event)`. The log line is `Rp2Fx`.
The event ids seen on the cast path:

| Event | Who sends it | Meaning in the logs |
|---|---|---|
| `0xb` | slow-cast sync, and a shot's release | the graph may proceed |
| `0xc` | slow-cast sync when the cast is allowed to finish, and the damage tick | proceed / damage |
| `0x15` | `OnTargetHit` when the spell is applied or has a duration | `SFx Duration`, or the apply on an instant that is not a special case |
| `0x16` | duration expired, dispel, orphan cleanup | `SFx Dispelled`, `SFx Expired`, `Bad Orphaned` |
| `0x17` | `OnTargetHit` when the target resists | `SFx Resisted` |

`OnTargetHit` is `FUN_0048c122` (vtable `+0x04`). It does not pick a
clip. It tells the graph which ending to play, then the graph's own
nodes swap sprites, move, scale, and fade. Node types are listed in
[`misc-formats.md`](misc-formats.md). The events the graph listens for
are the type-14 names shipped in the files: `OnCastOK`, `OnTargetHit`,
`OnTargetOK`, `OnFXEnd`, `OnTargetKilled`.

Sound is the same moment, not a separate animation. `FUN_0048f21e`
builds `Spell_<path>_Cast`, `_Hit`, or `_Fail` and plays it with
`FUN_00440e20`. The path word on the spell record (`+0x1c`) is switched
as Change, Divine, Flame, Life, Mind, Storm — not the order of the
path table in [`combat.md`](combat.md) §12. Call `0` is `Sound Mgc
Conjure` and appends `Cast` (this is the `On Casting Hit` call). Call
`3` is `Sound Mgc Worked` and appends `Hit`. Calls `2` and `4` append
`Fail` (`Sound Mgc Killed`, `Sound Mgc Resisted`). The wavs are the
`Spell_Flame_Cast` family in `RtkGame.def`.

### What the target's body does

The `.bex` is not the flinch. The flinch is another catalog clip,
queued with `FUN_00445be0` case 10, which is `FUN_00448967`. The pose
number selects a mask, and the mask selects the row. Checked against
the A-body flags:

| Pose | Mask | Clip |
|---|---|---|
| 6 | `0x1000200` | `A_Hit by Arrow` |
| 7 | `0x1001200` or `0x1003200` | `A_Hit by Arrow Backwards` / `Forwards` |
| 8 | `0x180200` | `A_On Fire` |
| 9 | `0x880200` | `A_Writhes in Pain` |
| 10 | `0x280200` | `A_Dazzled` |
| 11 | `0x480200` | `A_Head Hurts` |
| 12 | `0x2080200` | `A_Zapped` |
| 13 | `0x2081200` or `0x2083200` | `A_Zapped Backwards` / `Forwards` |
| 14 | `0x8200` | `A_Dodge` |

A miss on that filter falls back to the zapped family (`0x2080200` /
`0x2081200`). Creature bodies use the matching names in their own
prefix: `reactspell`, `Onfire`, `Headhurt`, `Writhes`, `Affected by
Spell`.

Those affliction clips are also the ongoing picture of a condition.
`A_On Fire`, `A_Dazzled`, `A_Head Hurts`, and `A_Writhes in Pain` loop
as body animation. There is no second layer of particles under them.
When the duration ends, `FUN_0048c901` (`OnDurationExpired`) sends
event `0x16` and the graph tears itself down.

### Shots: bows, bolts, thrown spells

A missile is a second effect object (`FUN_0048ecaf`), not a cast.
`FUN_0048e6db` picks the graph from the shot type at effect `+0x2c`:

| Type | File | When |
|---|---|---|
| 0 | `normarrow.bex` | an ordinary arrow. `zfirarr.bex` instead when actor `+0xbc` is `0x19` (the shooter, or the actor currently in the fight) |
| 1 | `normbolt.bex` | a bolt |
| 2 | `zsto2ric2.bex` | the lightning shot (`Ride the Lightning` uses `zsto2rid.bex` as its cast; this is the projectile) |
| 3 | `normcbolt.bex` | a crossbow bolt |

An arrow plays a clip first: `FUN_00445be0` case 6 (`FUN_00447a14`,
mask `0x1000100`), and the release callback is the clip's `+0x38`
time, the same slot a cast uses for `On Casting Hit`. Bolts and the
lightning shot skip that wait and fire the virtual immediately.
Release sends `Rp2Fx` event `0xb` (`FUN_0048edfa`, `On Casting Hit` on
the missile vtable). Impact is `FUN_0048ee88` (`Msl OnTargetHit`):
event `0x15`, then a reaction clip.

The reaction depends on the weapon word at the shooter's `+0x57c` and
on the shot type:

| Shot | Weapon word `+0x57c` | Reaction pose |
|---|---|---|
| lightning (type 2) | any | 12 or 13, `A_Zapped` or the forwards/back pair, if the target's `+0x4c` virtual is set |
| crossbow (type 3) | not 2 | same zapped pair. Weapon word 2 plays no flinch |
| arrow (type 0) | 1, 5, 6, 7 | 6 or 7, `A_Hit by Arrow` |
| bolt (type 1) | 1, 5, 6, 7 | zapped, and if that clip is missing, pose 4 |
| any | 4 | pose 2, which `FUN_00448967` does not implement, so no flinch clip |
| any | 2 | no flinch clip |

`A_Throw Potion` is the other thrown clip (flag `8388880`, category
`0x800100`, picker `FUN_00447c6d`). Its row times are `11.1, 11.1`.

### Skills

A combat skill does not have a behavior file.

The 22 skill numbers on a character change the roll
([`combat.md`](combat.md) §3). The names, from Brawling through Divine,
are in that section. The picture of using the skill
is the melee catalog: `A_Hack`, `A_High Slash`, `A_Medium Slash`,
`A_High Thrust`, `A_Medium Thrust`, `A_Punch High`, `A_Punch Low`,
and the block and dodge rows. `FUN_0047b4b7` maps the weapon to an
attack style and `FUN_004480ec` maps the style to a pose. The
defender's answering clip comes from `CStrikeDefGroup`, which pairs
an attack frame id with a reaction frame id (punched, hacked, blocked,
hit from behind). That pairing is authored. It is not a `.bex`.

What *does* show a graph on a weapon is a spell or a potion whose
`Spell_Type` is `Weapon` or `Attack`: Demonblade and Phoenix Blades
(`zfir2dem.bex`), Lightning Blade (`zsto2bla.bex`), the fire-oil
potions (`zpotfoil.bex`), the magic-blade potions (again
`zfir2dem.bex`). The cast plays the cast clip and the graph. Later
swings play the normal melee clip. A flaming arrow is the exception
that changes the projectile: actor `+0xbc == 0x19` swaps
`normarrow.bex` for `zfirarr.bex` at release. What `0x19` names was
not traced past that compare.

Lockpicking, traps, and alchemy are not combat clips. They open
Rtlib32 screens (`FUN_004366c0`, lock id `0x12`, container id `0x5`).
The lock screen's gear and the delay before `OnFail` are in
[`traps.md`](traps.md).

`explo.bex` and `explog.bex` are spawned from hard-coded sites as well
as from spell graphs. `SPELLGEN_ACD` is loaded with the scene; its
own visuals were not traced past the load.

---

## 7. 2D animation

Rtlib32's archive (`RTKRES`) holds the flat art:

| Type | Count | What it is |
|---|---|---|
| BITMAP | 5,089 | one 8-bit image, LZW or scanline RLE |
| CEL | 921 | 16 bytes pointing at one bitmap. One frame |
| SPRITE | 1,509 | a list of cels, queues, bitmaps, text |
| QUEUE | 168 | an indexed sequence through a sprite's list. This is a 2D animation |
| GROUP | 17 | a list of sprite ids |
| SCRIPT | 39 | sprite bytecode. Opcode `0xc9` calls `SpriteScreenShake` |

A screen is a sprite resource passed to `Win_CreateDlg`. Every UI refresh
calls `SpriteAnimate` on the live tree, which is what advances a queue.
The title shelf, the save-book page turn, and the party-sheet book use
that queue; the command layout and the timings are
[`ui.md`](ui.md) §9.
The cursor is the same machinery: `FUN_0045db05` asks `FUN_00453c13` for
a sprite id and the compositor draws it. Palettes are per screen, not per
bitmap — `RtSetPalette` then `SpriteChangePalette`. Thirteen palettes
ship. Nothing in the traced code cycles individual colours inside a
painting.

Inventory icons are not in `MagicInvItem.txt`. That table is stats and
tags. The pictures are bitmaps in `RTKRES`, almost certainly static cels;
no plaintext table maps an item tag to an animated queue.

---

## 8. Putting a swing and a spell together

A hack that connects:

1. The fight is still the scene. Nobody loaded a battle map.
2. The attack style picks a catalog row (`A_Hack` on body A, `B_Hack` on
   body B, `gtsk` Attack01 on that creature).
3. `FUN_00441aca` points every bone at that clip's joint tracks.
4. The queue plays the frame window. `CStrikeDefGroup` has already
   paired this attack with the defender's reaction (`A_Hacked
   Forwards`, a block, a dodge) and the swing sample plays.
5. A weapon enchantment does not spawn a new graph on the swing. The
   graph was spawned when the enchantment was cast. A flaming arrow is
   the case that does swap the projectile, to `zfirarr.bex`.

A cast is §6. The caster plays `A_Cast Attack Spell` or `A_Cast
Personal Spell`. At the first time on that row (`14.5` or `15.7`)
`On Casting Hit` spawns the spell's `.bex`. The target's body, if it
flinches, plays `A_Zapped`, `A_On Fire`, `A_Dazzled`, `A_Head Hurts`,
or `A_Writhes in Pain`.

---

## 9. Open

- The four small integers on a `CTrackGroup` row (`250, 15, 1, 0` and
  their variants) are only partly tied to runtime fields. The 7-character
  stem at resource `+0x28` and the to-frame at `+0x50` are read by
  `FUN_00441aca`. The rest of the record layout was not dumped field by
  field.
- Two dag-name prefixes skipped alongside `SPACER_` and `WEAPON_` still
  have no recovered spelling (`DAT_005d65b8`, `DAT_005d65c0`).
- `.trx` integer → face bitmap is not a recovered table. Lip-sync timing
  is; the last lookup is not.
- `SpriteAnimate` and `SpriteScreenShake` are imports. `kronctrl.dll` is
  not decompiled here, so 2D queue timing and the shake implementation
  stop at the call.
- Several `.bex` payload fields are non-zero and unread in the branches
  traced so far. The list is in [`misc-formats.md`](misc-formats.md).
- Which numeric resource id maps to which catalog row is built when
  `RtkGame.def` loads (`FUN_004fcf98`). The table was not dumped.
- `SPELLGEN_ACD`'s visuals, past "it is loaded with the scene", are
  untraced.
- Spell-record fields `+0x14`, `+0x1c`, and `+0x20` decide attack-cast
  versus personal-cast, and `+0x1c` also selects the `Spell_<path>_`
  sound. They were not matched to `Spell_Type` or `Magic_Path` by name.
  The sound switch's path order (Change, Divine, Flame, Life, Mind,
  Storm) is not the path-table order in `combat.md` §12.
- The shooter clip selected by mask `0x1000100` (`FUN_00447a14`) was
  not pinned to a single catalog name. `A_Throw Potion` is the
  neighbouring mask `0x800100`.
- Weapon word `+0x57c` selects the impact flinch. The integers 1, 2, 4,
  5, 6, 7 were not named back to bow, crossbow, or spear.
- No multi-frame backdrop turned up. Views are single paintings.
