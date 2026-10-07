# Three small formats: `.bex`, `.ktx`, `.kgi`

| Format | Files | What it is | Status |
|---|---|---|---|
| `.bex` | 368 | "binary FX info" — the spell/effect graphs | **container fully resolved**, per-node payloads mostly resolved |
| `.ktx` | 237 | plain narration text with a six-tag markup | **fully resolved** |
| `.kgi` | 1 | the default save-game thumbnail, a raw RGB555 bitmap | **fully resolved** |

Readers: `tools/rtkbex.py`, `tools/rtktext.py`, `tools/rtkgameshot.py`.
Validators: `tools/validate_bex.py`, `tools/validate_text.py`.

> **On the line numbers below.** They are against `out/decompiled/` as it
> stands at the time of writing. That tree gets regenerated, and `RtK.c`
> shifted by ~300 lines while this was being written. The stable anchor is
> the `// ===== FUN_0042d433 @ 0042d433 =====` banner, not the line number;
> `tools/lines.py RtK.c FUN_0042d433` re-derives any citation.

---

# `.bex` — binary FX info

## How it was found

`Bex.t3d` is opened by `FUN_004fe2e7` (`out/decompiled/RtK.c:166659`), which
slurps the whole file and hands the buffer to `FUN_0042d7a2`; on failure it
logs `FXLoadBinaryFXInfoSprites failed.` That name is the whole lead. The
functions that matter:

| Function | File:line | Role |
|---|---|---|
| `FUN_004fe2e7` | `RtK.c:166659` | open `Bex.t3d` / the loose file, read it whole |
| `FUN_0042d7a2` | `RtK.c:29830` | walk the entry stream to pre-load sprites — **fixes the record stride** |
| `FUN_0042d433` | `RtK.c:29628` | the real parser: every on-disk field and its runtime slot |
| `FUN_0042caf8` | `RtK.c:29147` | the destructor — says which runtime slots are heap pointers |
| `FUN_0042cc3d` | `RtK.c:29211` | entry type → runtime payload size |
| `FUN_0042cbde` | `RtK.c:29184` | find an entry by id (a linear scan on dword 0) |
| `FUN_0042fb8d` | `RtK.c:31060` | the per-frame update: a `switch` on the entry type. **This is what gives each type a meaning.** |
| `FUN_0042e59e` / `FUN_0042e62e` | `RtK.c:30428` / `30460` | resolve the two trailing id lists |
| `FUN_0042e6c4` | `RtK.c:30492` | the `0x201…` actor selector |
| `FUN_0042c81c` | `RtK.c:28953` | the `FX_DAG_*` attach point |
| `FUN_0042e9ad` | `RtK.c:30624` | the type-3 motion handler |
| `FUN_0042fa00` / `FUN_0042f9c4` | `RtK.c:30994` / `30972` | the event sender |
| `FUN_0042e25d` / `FUN_0042e352` | `RtK.c:30310` / `30353` | the event listener |
| `FUN_0042ceaf` | `RtK.c:29327` | create an effect by `.bex` name |

`FUN_004fe548` (`RtK.c:166751`) is the instantiation: it calls
`FUN_0042d433(buffer, name)` and then stores the caster id at `+0x08` and the
target id at `+0x10` of the instance. Those two words are what the selector
codes below resolve against.

## Layout

```
0x00                    0x20 bytes   header
0x20                                 entry_count entries, back to back
<end>                                nothing; the last entry ends at EOF
```

### Header (0x20 bytes)

`FUN_0042d433` copies all eight dwords into the 0x20-byte runtime FXINFO and
then overwrites slots 6 and 7 with the file-name and entry-array pointers.
Only one dword carries information:

| Offset | Type | Meaning |
|---|---|---|
| `0x00` | u32 | **not a field.** Runtime slot; 0 in 359/368 files |
| `0x04` | u32 | **entry count** (`FUN_0042d7a2`'s loop bound, `FUN_0042d433`'s `puVar2[1]`) |
| `0x08`–`0x1f` | — | runtime slots; zero in 357/368 files |

The slop is the proof. The exporter wrote its in-memory struct straight out,
so the non-field dwords carry whatever happened to be in that memory: zero in
357 files, **`cd cd cd cd` in two** (MSVC's uninitialised-heap fill), and
stale string bytes in nine more — `2hand.bex`'s dwords 2–5 hold the text
`entity_0`, and `0x00` holds 8. These are not a magic number or a version;
**there is no magic number**, which is why the leading `00 00 00 00` that 358
files share is a red herring.

### Entry

Each entry is variable length and **unaligned** — the fixed block starts on
the byte after the name's NUL, at whatever alignment that lands on.
`FUN_0042d7a2` reads `*(int *)(p + strlen(p) + 1 + 0x18)` to find the payload
size, which is what nails this down.

```
char   name[]            NUL-terminated, may be empty
i32    field[12]         0x30 bytes
u8     payload[field[6]]
i32    activate_count
i32    activate[activate_count]
i32    deactivate_count
i32    deactivate[deactivate_count]
```

| Field | Runtime slot | Meaning |
|---|---|---|
| `field[0]` | `+0x00` | **entry id**, the key `FUN_0042cbde` searches on |
| `field[1]` | `+0x04` | **entry type**, 1–14 |
| `field[2]` | `+0x08` | **flags**; bit 0 = starts active. Bit 2 is set by the handler on its first tick |
| `field[3]` | `+0x0c` | **repeat count**, decremented by the timer (type 1) and distance (type 11) arms |
| `field[4]` | `+0x10` | unknown; zero in all 5811 entries |
| `field[5]` | `+0x14` | overwritten with the name pointer; zero on disk |
| `field[6]` | `+0x18` | **payload size in bytes** |
| `field[7]` | `+0x1c` | unknown; zero in all 5811 entries |
| `field[8..11]` | `+0x20`–`+0x2c` | overwritten with the two counts and two pointers; zero on disk |

The loader allocates `FUN_0042cc3d(type)` bytes for the payload, **zero-fills
it**, and then copies only `field[6]` bytes over the front. That tolerance is
load-bearing: 190 of the 511 type-7 records are 4 bytes short of the runtime
struct and work anyway.

`activate` and `deactivate` are lists of entry ids. `FUN_0042e59e` sets bit 0
on every id in the first list; `FUN_0042e62e` does `flags ^= 5` on every id in
the second that currently has bit 0 set. Every handler fires both lists when
it finishes. **So a `.bex` is a graph: nodes plus activation edges**, and the
entries whose `flags & 1` is set on disk are where the effect starts.

### Entry types

`FUN_0042cc3d` enumerates types 1–14 with a fixed runtime size each; the
meanings come from the corresponding arm of `FUN_0042fb8d`'s switch. The names
below are descriptive — **the shipped binaries contain no name table for
these**, so they are not the authors' names.

| Type | Size | Count | Handler reads | Meaning |
|---|---|---|---|---|
| 1 | `0x14` | 423 | mode `+0x00`, scale `+0x08`, ms `+0x0c` | timer: wait, then fire the lists |
| 2 | `0x20` | 0 | selector `+0x1c`, location `+0x00..0x18` | `t3dSetActorLocation` |
| 3 | `0xa4` | 787 | selector `+0x00`, DAG `+0x04`, spin `+0xa0` | motion: `FUN_0042e9ad`, which drives the actor's position and heading/pitch/roll |
| 4 | `0x08` | 480 | nothing | end the effect — sets the userdata flag `FUN_0042fb8d` tests at `RtK.c:31646` |
| 5 | `0x90` | 598 | `.bex` name `+0x00`, src id `+0x40`, `+0x44`, selector `+0x48`, DAG `+0x4c` | spawn a child effect via `FUN_0042ceaf` |
| 6 | `0x10` | 687 | step `+0x00`, limit `+0x04`, mode `+0x0c` | `t3dSetActorScaleFactor` ramp |
| 7 | `0x4c` | 511 | selector `+0x00`, DAG `+0x04` | track a target actor's DAG; `+0x18`/`+0x1c`/`+0x28` are runtime |
| 8 | `0x10` | 20 | id `+0x00`, flag `+0x04` | `t3dSetActorInvisible` / light toggle |
| 9 | `0x58` | 604 | selector `+0x00`, sprite name `+0x38` | swap the actor's sprite (`t3dSetActorSprite`) |
| 10 | `0x18` | 0 | nothing | a pure trigger: fire the lists immediately |
| 11 | `0x0c` | 319 | step `+0x00`, scale `+0x04` | distance-travelled trigger |
| 12 | `0x3c` | 422 | from `+0x24`, to `+0x28`, rate `+0x2c` | translucency ramp via the polygon render method's upper nibble |
| 13 | `0x50` | 441 | `0x103e8` `+0x00`, recipient `+0x04`, event `+0x34` | send a user-defined event |
| 14 | `0x38` | 519 | `0x107d0` `+0x00`, event `+0x34` | listen for one |

Types 2 and 10 are implemented in the engine but used by no shipped file.

The type-9 sprite-name offset has two independent derivations, which is worth
noting because it is the only payload *string* whose position is proven rather
than observed: `FUN_0042d7a2` compares seven bytes at
`name + strlen + 1 + 0x68` against the literal `PARENT` and otherwise passes
that address to the resource manager's `LoadFXSprite`; `0x68 - 0x30 == 0x38`.
Independently, scanning the data finds a printable string at payload offset 56
in 602 of the 604 type-9 entries.

#### The event pair, 13 and 14

`FUN_0042fa00` copies the type-13 payload verbatim into a 21-dword t3d
message whose first word is `0x100c8` and whose second is the payload's own
first word, then calls `t3dSendMessageToActor`. `FUN_0042e352` receives
`0x100c8`, checks `message[0x04] == 0x103e8`, and scans for a type-14 entry
whose `payload[0] == 0x107d0` and whose `payload[0x34] == message[0x38]`.
Since `message[0x38]` *is* the sender's `payload[0x34]`, the two `+0x34` words
are the event id and the two leading words are the message tags. Measured
over all 5811 entries: `438/441` type-13 entries carry `0x103e8` and `517/519`
type-14 entries carry `0x107d0`; the five exceptions have an all-zero payload,
i.e. they are blank nodes left in the source data.

The entry names bear this out — the shipped type-14 names include
`OnTargetKilled`, `OnTargetActivate`, `OnCastOK`, `OnTargetOK` and
`OnCastKilled`, and type 13 has `OnTargetHit` and `OnFXEnd`.

#### `FX_DAG_*`, the attach points

`FUN_0042c81c` searches a 23-entry `{char *name, u32 code}` table at
`0x005d14b0` in `RtK.exe` (counted by `DAT_005d1568 == 0x17`), then strips the
`FX_DAG_` prefix and rewrites `_` as `-`. Reading that table out of the image
(`tools/peread.py "…/RtK.exe" 0x5d14b0 0xc0`) gives codes 0–22:

```
0 NONE          6 L_CAL         12 L_UPPERAR    18 NECK
1 SOURCE_DAG    7 L_FOO         13 L_LOWAR      19 HEAD
2 TARGET_DAG    8 R_UPPERLE     14 L_HAN        20 MAINSHADO
3 DUMMY01       9 R_CAL         15 R_UPPERAR    21 LFOOTSHAD
4 KIL          10 R_FOO         16 R_LOWAR      22 RFOOTSHAD
5 L_UPPERLE    11 TOPTORS       17 R_HAN
```

After the prefix strip and the `_`→`-` rewrite these are **exactly** the
20-joint rig that `docs/track-format.md` recovered independently from the
`.trk` files (`DUMMY01`, `KIL`, `L-UPPERLE`, … `MAINSHADO`, `LFOOTSHAD`,
`RFOOTSHAD`), in the same order. Two formats solved independently agreeing on
a 20-element ordered list is about as good as cross-validation gets here.

#### Actor selectors

`FUN_0042e6c4` tests `code & 0x200` and switches on `code - 0x201`; the type-2
arm of `FUN_0042fb8d` adds three more. The field is a `u16` —
`FUN_0042fb8d` reads `*(short *)(payload + 0x48)` for type 5 and
`*(short *)payload` for types 7 and 9.

| Code | Resolves to |
|---|---|
| `0x201` | the effect actor itself (`userdata[0]`) |
| `0x202` | the effect's source actor — instance `+0x08`, i.e. the caster |
| `0x203` | the effect's target actor — instance `+0x10` |
| `0x204` | `userdata[1]` |
| `0x205` | `userdata[1]`'s owner |
| `0x206` | `userdata[2]` |
| `0x207`–`0x209` | the location forms, type 2 only |

## Validation

`tools/validate_bex.py` over all 368 files in `out/t3d`:

```
files              : 368
parsed ok          : 368
parse errors       : 0
walk ends exactly  : 368/368
entries            : 5811
types              : {1: 423, 3: 787, 4: 480, 5: 598, 6: 687, 7: 511,
                       8: 20, 9: 604, 11: 319, 12: 422, 13: 441, 14: 519}
payload == cc3d sz : 5621/5811
payload short by   : {(type 7, 4 bytes): 190}
payload oversize   : []
id lists resolve   : 5811/5811
non-zero runtime slots: {(): 5811}
event msg ids      : {on_event 0x107d0: 517/519, send_event 0x103e8: 438/441}
unknown FX_DAG     : {}
unknown selectors  : {0: 80}
spawn_fx refs      : 131 distinct, 583/598 resolve to a shipped .bex
set_sprite names   : 83 distinct
```

Four results carry most of the weight:

- **`walk ends exactly : 368/368`.** The entry walk lands on EOF in every
  file, with no slack and no overrun. A wrong stride would not do that 368
  times over a 5811-record sample spanning 44 different entry counts.
- **`non-zero runtime slots: {(): 5811}`.** `field[4]`, `field[5]`,
  `field[7]` and `field[8..11]` — the seven slots `FUN_0042d433` overwrites —
  are zero in every single entry. That confirms both the 12-dword block size
  and which of its slots are real fields.
- **`id lists resolve : 5811/5811`.** Every one of the 6043 ids in the
  activation lists names an entry that exists in the same file. Entry ids are
  also exactly `1..N` in file order in all 368 files.
- **`unknown FX_DAG : {}`.** Every DAG code in the data falls inside the
  23-value enum, and the distribution is what spell effects should look like:
  `HEAD` 416, `MAINSHADO` 267, `TARGET_DAG` 222, `R_HAN` 202, `TOPTORS` 152.

A further cross-check: which payload dwords are *ever* non-zero, per type,
against which offsets the decompiled handlers read.

```
type  1 size 0x14  0x0 0x4 0x8 0xc
type  3 size 0xa4  0x0 0x4 0x10 0x24 0x2c 0x30 0x34 0x38 0x3c 0x48 0xa0
type  5 size 0x90  0x0 0x4 0x8 0xc 0x40 0x48 0x4c
type  6 size 0x10  0x0 0x4 0xc
type  7 size 0x4c  0x0 0x4 0x8 0xc 0x10 0x14 0x20 0x48
type  8 size 0x10  0x8
type  9 size 0x58  0x0 0x24 0x2c 0x38 0x3c
type 11 size 0xc   0x0 0x4
type 12 size 0x3c  0x0 0x24 0x28 0x2c 0x30
type 13 size 0x50  0x0 0x4 0x34
type 14 size 0x38  0x0 0x34
```

Type 4 does not appear because **no byte of any of its 480 payloads is ever
non-zero** — exactly right for a node the engine reads no parameters from.
Every offset the decompiled handlers touch appears in its type's list, and
every offset they treat as runtime scratch is absent from it: type 6's `+0x08`
(the saved initial scale), type 7's `+0x18`/`+0x1c`/`+0x28` (actor, DAG
sprite, saved location), type 12's `+0x34` (current level), type 11's `+0x08`,
and the whole of type 3's `+0x50`–`+0x9c` region that `FUN_0042e9ad` writes
its intermediate transforms into.

### Models rejected

- **"The leading `00 00 00 00` is a magic number or a version."** It is dword
  0 of the runtime FXINFO struct, which the loader never reads from disk. Two
  files have `cd cd cd cd` there and `2hand.bex` has `8`.
- **"`2hand.bex` starts with `08 00 00 00 07 00 00 00` + `entity_0`, so there
  is a string table at offset 8."** No: `entity_0` sits in header dwords 2–5,
  which are exporter slop. Every entry name in `2hand.bex` lives inside the
  entry stream from 0x20 onward, and the walk still lands exactly on EOF.
- **"The fixed block is aligned after the name."** It is not. Assuming
  4-byte alignment breaks the walk on the first entry whose name length is not
  3 mod 4, which is most of them.
- **"The payload size can be inferred from the type."** Usually, but 190
  type-7 records are 4 bytes shorter than `FUN_0042cc3d(7)`. The size must be
  read from `field[6]`.

## Open on `.bex`

- **Per-type payload fields the engine never reads** in the branches I
  traced: type 3's `+0x10`, `+0x24`, `+0x30`–`+0x3c` and `+0x48`; type 7's
  `+0x08`–`+0x14` and `+0x20`; type 9's `+0x24`; type 12's `+0x30`; type 5's
  `+0x44`. They are non-zero in the data, so they are real. Some are
  presumably consumed by `FUN_0042e9ad`'s deeper arms (a 350-line function)
  and by `FUN_0042ceaf`. Bounded work, not small work.
- **`field[4]` and `field[7]`** are zero everywhere. Nothing in the shipped
  data distinguishes "reserved" from "a field nothing happens to set."
- **Type names.** No name table ships. The names above describe behaviour;
  they are not recovered identifiers.
- **15 of 598 type-5 references** name a `.bex` that is not in the extracted
  set — either a cut effect or one inside an archive not yet unpacked.
- **80 type-5 entries have selector 0**, which is not one of
  `FUN_0042e6c4`'s codes. `FUN_0042fb8d` guards the call with
  `if (selector & 0x200)`, so 0 means "do not resolve"; what the engine uses
  instead is not traced.
- **5 of 368 files have no entry with `flags & 1`**, so nothing in them ever
  activates. Presumably dead data.

---

# `.ktx` — narration text

Plain 8-bit text. No header, no container, no compression, no NULs.

## The loader

`FUN_004ff07c` (`out/decompiled/RtK.c:167196`) opens `Ktx.t3d`, or
`C<n>.t3d` for the per-chapter variant, reads `t3dFastFileGetEOF()` bytes
straight into a `std::string`, and then does exactly one transformation
(`RtK.c:167303`):

```c
local_150 = *(int *)(*param_3 + -8);                      /* string length */
for (local_154 = 0; local_154 < local_150; local_154 = local_154 + 1) {
  _local_14c = CONCAT31(uStack_14b,*(byte *)(*param_3 + local_154));
  if (0x7f < *(byte *)(*param_3 + local_154)) {
    FUN_0058c2c4(param_3,local_154,0x20);
  }
}
```

`FUN_0058c2c4` (`RtK.c:264002`) is
`void __thiscall FUN_0058c2c4(void *this, int index, undefined1 ch)` doing
`str[index] = ch`. So **every byte above 0x7f is replaced with a space.** The
shipped files contain 15 occurrences of `0x92` (cp1252 right single quote, in
`Return1`, `Return2`, `Witch1`, `Izmali3`, `Karack`) and 3 of `0x96` (en dash,
in `Izmali3`). Those characters are displayed as spaces in the released game.
`tools/rtktext.py` exposes both readings: `.text` is what the engine shows,
`.authored` is the cp1252 decode of what the writers typed.

On failure the loader logs `Failed to load text file: %s`.

## Markup

Six backslash tags, each of which exists in the binary as a literal string
constant that a `std::string::find` or substring helper is called with. The
addresses are in `RtK.exe`'s `.data`:

| Tag | Literal at | Consumer | Meaning |
|---|---|---|---|
| `\p` | `0x005d0288`, `0x00612a7c` | `FUN_00428112` (`RtK.c:25990`, uses it at `26016`) | **page break**; the viewer splits the whole file on it and makes one page object per part |
| `\s` | `0x005d0284`, `0x00612a88` | `FUN_0042800a` (`RtK.c:25947`), `FUN_0054d7c1` (`RtK.c:214124`, at `214197`) | splits a page into a **heading** and a body |
| `\o` | `0x005d4b94`, `0x00612a8c` | `FUN_0054d7c1` (`RtK.c:214202`) | a third per-page field |
| `\w`…`:` | `0x00612a94` + `0x00612a90`, also `0x005d20f0` + `0x005d20ec` | `FUN_0054da94` (`RtK.c:214231`, at `214252`); `FUN_0043248a` (`RtK.c:32366`) for the credits | the text between `\w` and `:` goes through `atoi` (`FUN_005753c0`); the result is the page's **dwell time**, defaulting to the caller's value — 10000 when absent |
| `\l` `\c` `\r` | `0x005f8484`, `0x005f8488`, `0x005f848c` | `FUN_004eb090` (`RtK.c:154011`, at `154068`/`154077`/`154086`) | **alignment**: sets the text-box field to 1 / 2 / 3, default 1 (left) |

The second column of addresses is not a coincidence. `0x00612a74` holds the
literal `ktx` itself, and the tags follow it contiguously:

```
00612a74  6b 74 78 00 00 00 00 00 5c 70 00 00 5c 77 00 00  ktx.....\p..\w..
00612a84  3a 00 00 00 5c 73 00 00 5c 6f 00 00 3a 00 00 00  :...\s..\o..:...
00612a94  5c 77 00 00                                      \w..
```

That is the whole `.ktx` markup vocabulary sitting in one block next to the
extension string, which is a useful independent check that the six tags are
the complete set and that nothing was missed. Likewise `\l`, `\c` and `\r` are
consecutive at `0x005f8484`:

```
005f8480  e7 ff ff ff 5c 6c 00 00 5c 63 00 00 5c 72 00 00  ....\l..\c..\r..
```

`\l` appears 3 times and `\c` once in the shipped text; `\r` is never used.
There are **no** speaker tags, no `|` separators and no bracketed markup of
any kind — I checked for all three and found zero instances.

The `\w` numbers are durations in milliseconds, not timestamps. Two things
settle it: the four credits files use a flat `6000` on every page, and the
chapter files' values are not monotonic (`PugChapt0.ktx` is `40200` then
`30400`, `PugChapt3.ktx` is `32700, 29350, 17800`), which rules out absolute
cue times. The magnitudes also fit — 6 s per credits card, 12–44 s per
chapter narration page.

## Validation

`tools/validate_text.py` over all 237 files:

```
files                : 237
sizes                : min=19 max=1346 total=49345
distinct byte values : 79
pure 7-bit ASCII     : 231/237
bytes >= 0x80        : {0x92: 15, 0x96: 3}
line endings CRLF    : 237/237 (no bare CR or LF anywhere)
NUL-free             : 237/237
control bytes present: {0x0a: 707, 0x0d: 707}
backslash tags       : {p: 64, w: 35, s: 15, o: 11, l: 3, c: 1}
unrecognised tags    : {}
pages per file       : {1: 214, 3: 15, 4: 4, 5: 1, 7: 3}
pages with a heading : 15
pages with an \o part: 11
dwell values         : {None: 266, 6000: 17, 400: 2, 12500..44300: 1 each}
alignments           : {left: 300, center: 1}
page rejoin exact    : 237/237
parse errors         : []
```

Two numbers close the format. `unrecognised tags : {}` — every one of the 129
backslash sequences in the corpus is one of the six tags the engine has a
literal for, so there is no undiscovered markup. And
`control bytes present: {0x0a: 707, 0x0d: 707}`, an exact match, which proves
every line ending is a CRLF pair with no stragglers.

Paragraph breaks are blank lines (`\r\n\r\n`); 136 of the 237 files are a
single line with no internal structure at all. The directory split is
`Ktx` 24 (the documents and books, which is where almost all the markup
lives) and `C0`/`C1`/`C2`/`C3`/`C5`/`C7`/`C9` 213 (per-chapter narration,
almost all plain prose).

Nothing is open on `.ktx`.

---

# `.kgi` — the default save-game thumbnail

One file in the game: `Map.kgi` inside `SC.t3d`, 59,520 bytes. It is a raw
**192 × 155 RGB555** bitmap, little-endian, row-major, top-down, with no
header and no palette. `192 * 155 * 2 == 0xE880 == 59520`.

## Proof

| Function | File:line | What it gives |
|---|---|---|
| `FUN_00528f6f` | `RtK.c:195179` | "DisplayDefaultGameShot": opens `Map.kgi` in `SC.t3d` and **requires `t3dFastFileGetEOF() == 0xe880`**, else logs `DisplayDefaultGameShot: Map.kgi i…`. Reads it straight into the `0xE880`-byte global at `DAT_0065cc68` when the display is in pixel format 2 |
| `FUN_005291a9` | `RtK.c:195264` | the format-3 path: `out = ((in & 0x7fe0) << 1) \| (in & 0x1f)` over `0x7440` pixels — a 555→565 widen. Applied on load **for format 3 and not for format 2**, which is what proves the file itself is 555 |
| `FUN_00529380` | `RtK.c:195367` | the inverse 565→555, used by "SaveCurrentGameShot" (`FUN_0052922b`, `RtK.c:195282`) which writes the same `0xE880` bytes into a save slot |
| `FUN_00528ca0` | `RtK.c:195059` | "CaptureScreenShot". Its loops are `for (y = 0; y < 0x9b; y++) for (x = 0; x < 0xc0; x++)` writing consecutive u16s, so the buffer is **0xc0 = 192 wide by 0x9b = 155 tall**. It also states both pixel layouts outright: format 2 masks are red `0x7c00` / green `0x03e0` / blue `0x001f`, format 3 are red `0xf800` / green `0x07e0` / blue `0x001f` |
| `FUN_00528eaa` | `RtK.c:195107` | the blitter; its source row stride is `param_6 * 0x180`, and `0x180 == 384 == 192 * 2` |
| `FUN_005295d6` | `RtK.c:195477` | "ScreenShotDisplayProc", which rejects any rectangle exceeding `0xc0 × 0x9b` and any screen position outside `0x280 × 0x1e0` (640 × 480) |

`FUN_00528f3e` and `FUN_00528f53` (`RtK.c:195144`, `195159`) clear and copy
the buffer with a loop count of `0x3a20` dwords = 14,880 dwords = 59,520
bytes, agreeing again.

So `.kgi` is almost certainly "Krondor game image" — the name is a guess, the
contents are not. Note that the leading bytes
`82 4c 82 4c 61 44 61 44 82 4c e2 50 42 51 63 59` are not a signature; they
are the first eight pixels of the map's dark red border.

## Validation

`tools/rtkgameshot.py` decodes the single file and writes a PNG:

```
GameShot(map.kgi, 192x155)
  distinct_colours         : 253
  mean_vertical_red_step   : 2.236   (of 31)
  mean_horizontal_red_step : 1.843   (of 31)
  pixels_with_bit15_set    : 0
```

Two independent confirmations beyond the arithmetic:

- **`pixels_with_bit15_set : 0`** across all 29,760 pixels. Bit 15 is the
  unused bit of RGB555. In a 565 image of this brightness it would be set in
  roughly half of them.
- **The decoded image is the game's parchment world map of the Krondor
  region**, correctly oriented and correctly coloured, with a legible compass
  rose and legend. A wrong width would shear it; a wrong channel order would
  tint it. Output at `out/t3d/SC/map.png`.

253 distinct colours out of 32,768 possible suggests the source art was an
8-bit paletted image, which is consistent with the rest of the game's assets.

Nothing is open on `.kgi` beyond the expansion of the extension itself.
