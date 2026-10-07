# Hierarchical sprites: the joint hierarchy (`.adf` chunk `0x10`)

A `.trk` stores per-joint local transforms and joint *names* but no parent
links, so until now the 917 animations could only be exported as flat JSON.
The parent links are in a **chunk type `0x10`, a "hierarchical sprite
definition"**, and they live in the `.adf` scene files — *not* in the `.spx`
files, which were the prior suspect and contain no `0x10` chunk at all.

**Status: resolved.** 49 unique joint hierarchies recovered, every one a
single-rooted acyclic tree; all 98 `0x10` chunks and all 98 `0x11` chunks
**re-serialise byte-exact** from the parsed fields; every joint name in all
917 loose `.trk` files resolves to a node. glTF export now works — all 917
animations export as `.glb` with a real skeleton
(`tools/export_gltf.py --all`). See *Validation*.

This closes the "Joint hierarchy" item under *Remaining open* in
[`track-format.md`](track-format.md).

## Where the hierarchy lives

`.adf`, `.spx` and `.grx` all share the T3D FastFile container already
documented in [`track-format.md`](track-format.md) — same `\x02=PT` magic,
same version `0x15500`, same 28-byte header, same XOR-scrambled name block
(key `95 3a c5 2a 95 7a 95 6a`), same chunk stream ending `ff ff ff ff`. Only
the chunk *types* differ:

| Extension | Files | Chunk types present | `0x10` chunks |
|---|---|---|---|
| `.adf` | 192 | `04 05 08 09 10 11 12 13 14 19 1a 2c` | **98** |
| `.spx` | 166 | `04 05 06 08 2c` | 0 |
| `.grx` | 1 | `04 2c` | 0 |

So `.spx` is a dead end for the rig. The 98 `.adf` files that carry a `0x10`
are the 49 character/object model files, each present twice in `out/t3d`
(once from the 8-bit `Chars` archive, once from `HiColorChars`).

## The loader chain

Everything below is read straight out of the decompiled engine. Line numbers
are into `out/decompiled/t3dll.c` unless marked otherwise.

| Function | Line | Role |
|---|---|---|
| `FUN_10022d60` | 27311 | chunk dispatch; `case 0x10:` → `FUN_10024120`, `case 0x11:` → `FUN_10024300` |
| `FUN_10024120` | 28447 | **decodes the `0x10` payload** — the authority for the layout below |
| `FUN_1001ab60` | 20375 | the dag constructor; pins which payload word becomes which runtime field |
| `FUN_10019bb0` | 19587 | `DefineHierarchicalSprite`; re-homes the sub-dag pointers, confirms the 0x140 stride |
| `FUN_10019770` | 19431 | starts the world-transform walk — **at dag 0** |
| `FUN_10019810` | 19441 | the recursive walker; **proves sub-dag = child** and gives the composition order |
| `FUN_10024300` | 28551 | decodes the `0x11` payload (an instance of a definition) |
| `t3dGetHierarchicalSpriteDagByIndex` | 20569 | `dag_array + index * 0x140` — the dag array is indexed by position |
| `t3dGetHierarchicalSpriteDagByTrackName` | 20514 | reads `*(dag + 0x14) + 8`, i.e. the dag's track's tag |
| `FUN_0052b981` | `RtK.c` 196616 | the game's `.trk` → dag binding |
| `FUN_004b7f7e` | `RtK.c` 115321 | runtime override of the three shadow dag tracks |

## Chunk `0x10` — hierarchical sprite definition

`FUN_10024120` binds the payload as `piVar1` (`param_1[10]`, line 28471) and
reads four fixed words, then two flag-gated groups, then a variable-length
dag array.

| Offset | Type | Proof | Meaning |
|---|---|---|---|
| `0x00` | i32 | 28524-28525 (via `*piVar9` for dags, `*piVar1` for the definition) | tag (name reference) |
| `0x04` | i32 | 28483, 28494 — `*(byte *)(piVar1 + 1)` | flags |
| `0x08` | i32 | 28501 — `t3dAllocateMemory(piVar1[2] * 0x140)` | **`numdags`** |
| `0x0c` | i32 | 28472-28482, and `t3dDestroyVolume` on the failure path | collision-volume reference; `0` selects `&DAT_10127240`, the default |

Then, with `piVar9` starting at `piVar1 + 4` (line 28473):

```c
if ((*(byte *)(piVar1 + 1) & 1) == 0) {        // 28483
  local_c = 0; local_8 = 0; local_4 = 0;
} else {
  local_c = *piVar9; local_8 = piVar1[5]; local_4 = piVar1[6];
  piVar9 = piVar1 + 7;                         // 3 words consumed
}
if ((*(byte *)(piVar1 + 1) & 2) == 0) {        // 28494
  local_1c = 0x3f800000;                       // 1.0f
} else {
  local_1c = *piVar9; piVar9 = piVar9 + 1;     // 1 word consumed
}
```

| Flag | Words | Becomes |
|---|---|---|
| `0x1` | 3 × f32 | default-instance centre offset (`FUN_10019bb0` param 5 → `piVar5[9..11]`) |
| `0x2` | 1 × f32 | bounding radius (`FUN_10019bb0` param 7; cf. `t3dGetHierarchicalSpriteDefinitionBoundingRadius`) |

Every shipped definition has `flags == 2`, so in practice the dag array starts
at offset `0x14` after one bounding-radius float.

### The dag record

The loop at lines 28504-28532 walks one disk record per dag, with
`piVar11 = piVar9 + 5` — five words of header, then `piVar9[4]` child
indices:

```c
for (puVar13 = puVar5; puVar13 < puVar5 + numdags * 0x50; puVar13 += 0x50) {
  piVar11 = piVar9 + 5;                               // 28505
  iVar6   = piVar9[4];                                // 28506  numSubDags
  for (piVar12 = piVar11; piVar12 < piVar11 + iVar6; piVar12++)
    *piVar12 = (int)(puVar5 + *piVar12 * 0x50);        // 28508  index -> pointer
  ...resolve piVar9[2] -> iVar6, piVar9[3] -> uVar7, *piVar9 -> name...
  FUN_1001ab60(puVar13, pcVar10, uVar7, iVar6, piVar9[4], piVar11);  // 28530
  piVar9 = piVar12;                                   // 28531  next record
}
```

Line 28508 is the decisive one: each stored word is multiplied by the runtime
dag stride and added to the array base, so **the sub-dag list holds 0-based
indices into this same dag array**.

| Offset | Type | Runtime field | Meaning |
|---|---|---|---|
| `0x00` | i32 | `dag+0x04` (`FUN_1001ab60` param 2) | dag name (name reference) |
| `0x04` | i32 | — | **not read by the loader**; zero in all 1393 dags |
| `0x08` | i32 | `dag+0x14` (param 4, line 20399 `param_1[5] = param_4`) | **track** reference |
| `0x0c` | i32 | `dag+0x08` (param 3, line 20398 `param_1[2] = param_3`) | **sprite** reference (`0` = no geometry) |
| `0x10` | u32 | `dag+0xec` (param 5, line 20391 `param_1[0x3b] = param_5`) | **`numSubDags`** |
| `0x14` | u32[n] | `dag+0xf0` (param 6, line 20396 `param_1[0x3c] = param_6`) | **child dag indices** |

so `record_size == 20 + 4 * numSubDags`, and

```
payload_size = 16
             + (flags & 1 ? 12 : 0)
             + (flags & 2 ?  4 : 0)
             + sum over dags of (20 + 4 * numSubDags)
```

which holds exactly for all 98 chunks — and more than that, the whole payload
re-serialises byte-for-byte from the parsed fields (196/196 including the
`0x11` chunks), so the record is not merely the right *size*.

The `0x08`/`0x0c` assignment is not guesswork about which is which:
`t3dGetHierarchicalSpriteDagByTrackName` (line 20514) looks up a dag by
reading `*(byte **)(*(int *)(iVar6 + 0x14) + 8)` — i.e. it follows `dag+0x14`
and reads *that object's* tag — which is only meaningful if `dag+0x14` is the
track. And `FUN_10019bb0` switches on `**(undefined4 **)(uVar6 + 8)`
accepting runtime type ids `10`, `0xc` and `0xe` (the sprite types),
confirming `dag+0x08` is the sprite.

### Sub-dag means child, and the composition order

`FUN_10019770` (line 19431) seeds the walk:

```c
FUN_10019810(param_1, *(int *)(param_2 + 0x20), 0.0, 0.0, 0.0);
```

(line 19436). `hsprite+0x20` is the dag array base (the same field
`t3dGetHierarchicalSpriteDagByIndex` indexes), so **the walk starts at dag 0
with the world origin: dag 0 is the root.** `FUN_10019810` then recurses into
the sub-dag list (lines 19545-19550) passing its own accumulated world
transform down:

```c
if (*(int *)(param_2 + 0xec) != 0) {
  do {
    FUN_10019810(param_1, *(int *)(*(int *)(param_2 + 0xf0) + uVar11 * 4),
                 fVar4, fVar5, fVar6);
    uVar11 = uVar11 + 1;
  } while (uVar11 < *(uint *)(param_2 + 0xec));
}
```

Parent-to-child recursion, so the sub-dag list is the child list. The
transform it propagates (lines 19525-19529) is

```c
t3dRotatePointCCWAboutQuaternion(local_translation, parent_quat, &rotated);
pos   = rotated * parent_scale + parent_pos;
t3dMultQuaternion(parent_quat, local_quat, world_quat);
scale = parent_scale * local_scale;
```

`t3dRotatePointCCWAboutQuaternion` (line 39222) expands to the plain
`(w² − |u|²)v + 2(u·v)u + 2w(u × v)`, i.e. ordinary `q v q⁻¹` with no
conjugation, and `t3dMultQuaternion(a, b, out)` (line 39137) is the plain
Hamilton product `a*b`. So

> `pos_world = pos_parent + scale_parent · (quat_parent ⊗ trans_local)`
> `quat_world = quat_parent · quat_local`
> `scale_world = scale_parent · scale_local`

which is **exactly** glTF's `M_world = M_parent · T · R · S` for uniform `S`.
That is why `tools/export_gltf.py` can emit one glTF node per dag with the
local TRS copied straight in, with no basis change invented.

## Chunk `0x11` — hierarchical sprite instance

`FUN_10024300` (line 28551) reads two words and calls
`t3dCreateHierarchicalSprite`:

| Offset | Type | Meaning |
|---|---|---|
| `0x00` | i32 | tag (name reference) |
| `0x04` | i32 | reference to the `0x10` definition |
| `0x08` | i32 | present on disk (payload is 12 bytes in all 98), **never read**; zero everywhere |

## Naming, and how a `.trk` binds to a rig

Within one definition every dag is tagged `PREFIX + joint + "_DAG"` and
points at a track tagged `PREFIX + joint + "_TRACK"`. The prefix is a
convention of the asset pipeline, not a field; `tools/rtkspx.py` recovers it
as the longest common prefix of the dag tags, which comes out at 3
characters for 48 of the 49 definitions (`A1C`, `B7C`, `OBJ`, …) and 6 for
`SHADOW_HS_DEF`.

A `.trk` tags its chunks `STEM + joint + "_TRACKDEF"` where `STEM` is the
7-character file stem (`TK0005M`), so the joint name is the common key.
`RtK.c` `FUN_0052b981` (line 196616) does exactly that at runtime — for each
dag it reads the dag's current track tag, overwrites the leading characters
with the animation id, and looks the result up:

```c
local_20 = t3dGetDagTrack(local_18);
t3dGetObjectTag(local_20, local_44);
if (local_20 != 0) {
  _strncpy(local_44, (char *)(param_1 + 0x3d), 7);
  FUN_00589520(local_44);
  iVar2 = t3dGetPointerFromDictionary(local_10, local_44);
  if (iVar2 != 0) { t3dSetDagTrack(..., local_18, iVar2); ... }
}
```

`GameData/Models.def` is the external map from character to rig. It is a
26-byte `(c) 1998 PyroTechnix,Inc.` banner followed by a plain gzip stream,
and each line names the `.adf` **and the `_HS_DEF` tag**:

```
James : A1James.adf, A1CJAMES.SPH, A1CA1CJAMES_HS_DEF, A1JAMES_ACD, 244, ...
```

`GameData/ConversationTracks.tbl` (same container) lists the loose
`TK####M.trk` files under `ConversationGroup All` keyed by
`TK####MDUMMY01_TRACKDEF`, which is why those tracks use only the shared
17-joint humanoid subset: they are authored once and played on whichever
character is speaking. **The loose conversation tracks are deliberately not
bound to one rig**; that is a property of the game's design, not a gap in the
format.

### The standard humanoid tree

30 of the 49 rigs cover the 17-joint set the loose tracks use, and 29 of
those 30 induce an identical sub-tree over it:

```
DUMMY01                     (root)
└── KIL                     (pelvis)
    ├── L-UPPERLE → L-CAL → L-FOO
    ├── R-UPPERLE → R-CAL → R-FOO
    └── TOPTORS
        ├── L-UPPERAR → L-LOWAR → L-HAN
        ├── R-UPPERAR → R-LOWAR → R-HAN
        └── NECK → HEAD
```

The single dissenter is `B7CB7CNAGA_HS_DEF`, and it is genuine data, not a
misparse: its payload consumes exactly 544 of 544 bytes with every dag
carrying `numSubDags = 1, subs = [i+1]`. The naga is a serpent whose body
segments were given the leg bone names, so its rig is one 22-node chain. The
bone-offset test below rejects it automatically (it scores 0/17).

## Validation

`tools/validate_sprites.py`, full output in `out/logs/validate_sprites.txt`.

### Container and layout

```
.adf  192 files  parsed 192  errors 0   files with a 0x10 chunk: 98
.spx  166 files  parsed 166  errors 0   files with a 0x10 chunk: 0
.grx    1 files  parsed   1  errors 0   files with a 0x10 chunk: 0
terminator ffffffff            : 359/359
0x10 chunks                    : 98      0x11 chunks: 98
byte-exact re-serialisation    : 196/196
unique definitions by tag      : 49  (+49 duplicate copies across archives)
```

Byte-exact on every `0x10` and `0x11` payload means no unmodelled padding and
no mis-sized record anywhere in the hierarchy data.

### Structure

```
single-rooted acyclic tree, root == dag 0 : 49/49
total dags                                : 1393
definition flags                          : {2: 49}
dag word @+0x04                           : {0: 1393}
children-per-dag                          : {0: 424, 1: 822, 2: 50, 3: 16,
                                              4: 52, 5: 10, 6: 17, 7: 2}
dags-per-definition                       : 2 to 54
```

The structural test is not just "parses": every child index is in range,
every dag is named as a child at most once, there is exactly one node with no
parent, it is dag 0, and every dag is reachable from dag 0.

### Cross-checks against independently stored data

```
dag tag with _DAG->_TRACK == the referenced track's own tag : 1390/1393
Models.def entries naming an _HS_DEF tag, resolved           : 152
Models.def entries naming a non-hierarchical sprite          : 52
Models.def entries naming an _HS_DEF not found               : 2
every joint name in a loose .trk resolves to a dag           : 917/917
```

- The 3 tag exceptions are `SHADOW_HS_DEF`, whose `SHADOWLEFT/KILT/RGHT` dags
  all share one `SHADOW_TRACK`. `RtK.c` `FUN_004b7f7e` (line 115321)
  explains it: the game replaces the tracks of dags 1-3 of the shadow rig at
  runtime with freshly created `SHADOW%d_TRACKDEF` tracks.
- The 52 non-hierarchical entries name `*_3DSPRITEDEF` or `NULLSPRITE` —
  static props with no rig, correctly absent from the `0x10` set.
- The 2 unresolved are **typos in the game's own `Models.def`**:
  `C6CDRAGONSOUL_HS_DEF` (the real tag is `C6CC6CDRAGONSOUL_HS_DEF`) and
  `R2CR2CSULLENMICAEL` (missing the `H`).

### Bone offsets: the strongest check

The `.adf` gives every dag a one-keyframe default track — the bind pose —
whose translation is that bone's offset from its parent. A `.trk` stores its
own translation per joint per frame. These are two separately authored files,
so if the offsets agree the `.trk` joints and the `.adf` dags are provably the
same skeleton. Over all 917 loose tracks, 15601 joint comparisons:

```
rig A1CA1CJAMES_HS_DEF : 12700/15601 agree within 0.01 units  (81.41%)
rig B6CB6CDEMON_HS_DEF :   917/15589 agree within 0.01 units   (5.88%)
```

For `A1James` the 18.6% that differ are exactly the joints that are *supposed*
to translate during an animation — `KIL` (pelvis, 730 files), `L-FOO` (835)
and `R-FOO` (834) — plus 4 files on the shadow nodes. For `B6Demon` nothing
matches except `DUMMY01` at the origin. The test therefore both confirms the
mapping and discriminates sharply between rigs.

### Rig selection is measured, not chosen

Ranking the covering rigs by that score and keeping only the top scorers:

```
loose Tracks/  : top-scoring group is tree-unanimous : 913/917
                 top-scoring group disagrees         :   4
                 the 4 disagree only on: LFOOTSHAD, MAINSHADO, RFOOTSHAD
archived .t3d  : top-scoring group is tree-unanimous : 659
                 top-scoring group disagrees         :  97  (same 3 joints)
                 no covering rig                     :  40
```

So for 913 of the 917 loose animations the hierarchy is fully determined by
the data. For the remaining 4 (the 20-joint tracks) all 17 body joints are
determined and only the three *shadow blob* helper nodes differ between rigs:
`K3ArabicThug1` and `K6Skel_Warrior_#1` hang them off the character root
while the others hang them off `DUMMY01`.

### Archived tracks

40 of the 801 tracks inside the `.t3d` archives reference joint names that no
extracted rig has — `ATTACK_MARKER` (24 files), prop nodes like `AXE`, `BOW`,
`MACE01`, `MUG`, and crowd nodes like `BOYA`, `GIRL2`. These belong to rigs
not present among the 98 `.adf` files with a `0x10` chunk, so they are
honestly unresolved rather than forced onto a wrong rig.

## glTF export

`tools/export_gltf.py` writes glTF 2.0 `.glb` (hand-rolled JSON plus a binary
chunk, standard library only). One glTF node per dag, node index == dag
index, `children` copied from the sub-dag list, rest TRS from the dag's own
default track, and one animation with `rotation` + `translation` samplers per
animated joint at `update_interval` ms per keyframe. Quaternions are
reordered from the engine's w-first to glTF's xyzw; no other change is made
to any value.

The engine is Z-up (bone offsets run up `+z`), so the rig is parented under a
single extra node named `ZUP_TO_YUP` carrying a −90° rotation about X. That
wrapper is the only transform this exporter introduces, and it touches no
joint value.

`python tools/export_gltf.py --all` exports every loose animation:

```
tracks in     : 917
.glb written  : 917
skipped       : 0
total size    : 115.1 MB
```

Re-reading 120 of them at random and checking as a glTF consumer would —
exactly one root, every node with at most one parent, every accessor inside
the buffer, every animation channel targeting a real node:

```
structurally valid : 120/120
nodes per file     : 30
channels           : 3846
keyframes          : 792932
```

`tools/_probe_gltf_render.py` reads a `.glb` back as a plain consumer would
(no use of `rtkspx`), runs forward kinematics through the node tree and draws
the result to `out/probe/skeleton_*.png` in two projections. The output is an
unmistakable standing human figure — two legs with knees and ankles, pelvis,
torso, two arms with elbows and hands, neck, head — gesturing coherently
across frames, with `nodes=30, roots=[29], max_parents=1` and a 57-unit
figure height whose lowest ankle sits at `y = 4.70`. A wrong parent table
cannot produce that in both projections.

## Rejected models

Recorded so they are not retried.

- **`.spx` is the hierarchical sprite.** It was the prime suspect on the
  strength of the name and the shared container. It is wrong: all 166 `.spx`
  parse cleanly and contain only chunk types `04 05 06 08 2c`, with **zero**
  `0x10` chunks. Whatever `.spx` is, it is not the rig.
- **`.grx` carries the rig.** Also wrong: the single `cursors.grx` has only
  types `04` and `2c`.
- **The dag record has a parent index.** The word at dag `+0x04` is the only
  candidate and `FUN_10024120` never reads it; it is zero in all 1393 dags.
  Parenting is stored as child lists, not parent pointers.
- **The sub-dag list holds pointers or name references.** Line 28508
  multiplies each stored word by the dag stride and adds the array base, so
  they are plain 0-based indices. Treating them as references produces
  out-of-range values immediately.
- **`B7CB7CNAGA_HS_DEF` is a misparse.** Tempting, because it is a pure
  `0 → 1 → … → 21` chain. It is not: the payload consumes exactly 544/544
  bytes, name references decrease monotonically, track references step by 2,
  and the same parser yields correct branching trees for the other 48 rigs.
  The naga rig really is a chain.
- **A fixed 7-character tag prefix.** `RtK.c` `FUN_0052b981` substitutes 7
  characters, which suggested dag tags are prefixed with 7. They are not —
  measured prefixes are 3 characters (48 rigs) or 6 (`SHADOW`). Assuming 7
  shreds the joint names (`A6CKIL` → `L`) and drops the joint match rate to
  0/917. The 7 in the engine is the width of the *animation id* being pasted
  in, not the width of the prefix being replaced; reconciling those two is
  still open (see below).
- **"Smallest covering rig" as the rig-selection rule.** It fits (917/917)
  but picks `B6CB6CDEMON_HS_DEF`, whose bone offsets match the tracks only
  5.88% of the time. A joint-set subset test says nothing about whether the
  skeleton is the right one; the bone-offset test does.

## Remaining open

- **The dag word at `+0x04`.** Zero in all 1393 dags, never read by
  `FUN_10024120`, and with no counterpart in the engine's own text scene
  compiler (which passes exactly name, sprite, track, `NUMSUBDAGS` and the
  sub-dag list to `FUN_1001ab60`). Nothing distinguishes "reserved" from "a
  field no model sets".
- **The third word of a `0x11` payload.** Same situation: on disk, zero in
  all 98, unread.
- **`FUN_0052b981`'s 7-character substitution.** With 3-character dag
  prefixes, pasting 7 characters over `A1CKIL_TRACK` yields
  `TK0005MTRACK`, which is not a valid tag. Either that code path applies to
  assets not in the shipped `.adf` set, or the decompiled argument order
  misleads. It does not affect reading the hierarchy — the joint-name match
  is independently confirmed by the bone offsets — but the exact runtime
  lookup is not fully explained.
- **Which rig the 4 twenty-joint loose tracks use.** Their 17 body joints are
  determined; the 3 shadow helper nodes are not.
- **40 archived tracks** reference joints from rigs that are not among the 98
  `.adf` files carrying a `0x10` chunk.
- **Handedness and axis order** remain as recorded in `track-format.md`: the
  exporter applies only the documented Z-up→Y-up wrapper and does not claim
  the chirality is settled.
- **Simple sprites and 3D sprites are now parsed.** Chunk `0x04`
  (`t3dDefineSimpleSprite`, `FUN_10023360`) and `0x05`
  (`t3dCreateSimpleSprite`, `FUN_10023430`) rebuild byte-exact:
  414 / 414 definitions and 29,234 / 29,234 instances in the 8-bit `.adf`
  set. A dag's `sprite_ref` is a `0x09` instance of a `0x08` 3D sprite
  (`t3dDefine3DSprite` / `FUN_10023ad0`): 1,782 definitions, 1,704
  instances, every one of the 1,662 non-zero dag refs resolves. Textures
  are `0x2c` BMInfo records (`t3dDefineBMInfoMIPMapped`, `FUN_100231b0`)
  whose XOR-scrambled name is the archive `.bmp` (6,000 of them).
  Chunks `0x14`, `0x19`/`0x1a` are still untraced. See
  `tools/validate_sprites_geom.py`.

## Tools

| Path | Purpose |
|---|---|
| `tools/rtkspx.py` | the reader: `SpriteFile`, `HSpriteDef`, `Dag`, simple/3D sprites, `BMInfo`, `rest_pose`, `score_rig`, `match_rig` |
| `tools/rtkcharacter.py` | Models.def → rig + sprites + compatible `.trk`; scene JSON for the viewer |
| `tools/validate_sprites_geom.py` | 0x04/0x05 byte-exact plus 0x08/0x09/0x2c counts |
| `tools/validate_sprites.py` | the sweep above |
| `tools/export_gltf.py` | glTF 2.0 `.glb` export of an animation on a recovered rig |
| `tools/_probe_gltf_render.py` | reads a `.glb` back and draws the skeleton to a PNG |
| `tools/_probe_chain.py` | hexdumps a `0x10` chunk; surveys which rigs are chains |
| `tools/_probe_induced.py` | induced-sub-tree agreement across covering rigs |
| `tools/_probe_match.py` | `.trk` joint-name coverage against the rig set |

The four `_probe_*` scripts are one-off investigation passes. They are the
provenance of the numbers quoted above, but they are scratch and `.gitignore`
keeps them out of version control, so they will not be present in a fresh
clone. The three entries above them are the maintained tools.

`tools/rtkspx.py` subclasses `rtktrack.Track`, so the container layer it uses
is the one already proven byte-exact over all 917 `.trk` files.
