# Which palette goes with which bitmap

RTKRES holds 5,089 BITMAP resources and 13 PALETTE resources. The bitmaps are
8-bit indexed and carry no colour table, so something has to pair them up. The
answer is **not stored per bitmap, and there is no bitmap→palette table
anywhere**. The engine realises exactly one palette at a time and the game
picks it **per screen, in `RtK.exe` code**. This document gives the evidence
for that, the recovered screen→palette table, and what it does and does not
resolve.

`tools/palettemap.py` is the table plus `palette_for(resource_name_or_id)`.

## The engine has one palette, not one per bitmap

`RtSetPalette(hRt, id)` is `Rtlib32.dll` export 245 (`Rtlib32.c` 17533). It
posts internal message `0xb5`, handled by `FUN_10001a0c` (`Rtlib32.c` 2),
which is the whole mechanism:

```c
FUN_10013c92(id, 0x11)                      // require resource type 17 = PALETTE
FUN_10041f90(lib + 0x32cb, payload, 0x3b0)  // copy 944 bytes = 236 PALETTEENTRY
SpriteChangePalette(sprite, 10, 0xec, ...)  // install at slots 10..245
```

Three things fall out of those three lines. The second argument is a PALETTE
*resource id* — the type check is `0x11`, which is 17, the PALETTE type code.
`0x3b0` is 944, exactly the size of every one of the 13 PALETTE resources. And
`10, 0xec` is start 10, count 236, matching the index window `tools/rtkres.py`
already established.

Nothing downstream is per-bitmap. `SpriteRealizePalette` and
`SpriteSelectPalette` (`Rtlib32.c` 33108 and 33130) each read a single handle
at `sprite + 0x46c`, created once by `CreatePalette` at `Rtlib32.c` 33203.
Bitmaps are blitted against whatever is realised at the time.

So the association is screen-scoped, and the negative half of this result is
real: **no per-bitmap palette reference exists**, in the archive or in the
exe. What *does* exist is a complete record of which screen names which
palette, and that turns out to be enough.

### `pIntfacePal` is the engine default, provably

`FUN_1001e8a9` (`Rtlib32.c` 18253) seeds the table from
`GetSystemPaletteEntries` and then calls `ResLoadPalette`, which reads **key
resource 6** of the archive. Key resource 6 is 944 bytes and compares
byte-for-byte equal to PALETTE resource 0, `pIntfacePal` — and unequal to the
other twelve. `RtK.exe` has 28 `RtSetPalette` call sites; 16 of them pass a
literal `0`, which is what a screen does on the way out.

## Where the per-screen choice is written down

Three places, all in `RtK.exe`.

**1. Direct call sites.** Ten sites pass a literal palette id 1..10, each
immediately next to the dialog it is opening:

```c
void FUN_00547786(void) {                       // RtK.c 210870
  Win_Show(...);  FUN_004376a8(0);
  RtSetPalette(DAT_0066e058, 4);                // 4 == pHaldonMapPal
  DAT_0066df6c = Win_CreateDlg(DAT_0066e05c, 0, 0x57, 0, 0x4b2, 0x54960f,
                               10000, 0, 0);    // 0x57 == 87 == sHaldonHead
```

`Win_CreateDlg`'s third argument is a SPRITE resource id, not an arbitrary
window tag. `WinCtrl_create` (`kronctrl.c` 1032, body in `Rtlib32`) does
`RtGetResType(hRt, id)` and refuses to build the control unless the type is
`0x14` = SPRITE, then `RtLoad`s it. `Win_CreateControl`'s third argument is
the same thing. So each site names both the palette and the screen's root
sprite — and `sHaldonHead`'s one sprite reference is `88 bHaldmap_`, the asset
that exposed the problem in the first place.

**2. A C++ screen base class.** `FUN_0052e785` (`RtK.c` 198739) is the shared
"open me" method: it reads a palette id out of the object, calls
`RtSetPalette` with it unless it is the sentinel `0x8000000`, then
`Win_CreateDlg`s. Its vtable has a fixed shape — slot `+0x1c` is always
`FUN_0052e785`, slot `+0x14` returns the screen's palette id as a constant,
slot `+0x20` is the control builder. Scanning `.rdata` for function-pointer
runs with that shape (`tools/_probe_vtabpal.py`) enumerates them:

| vtable VA | slot `+0x14` | returns | builder | screen |
|---|---|---|---|---|
| `0x005A6550` | `FUN_00427A40` | 12 `pPaperPal` | `FUN_00427701` | text-page viewer |
| `0x005A6880` | `FUN_00432970` | 10 `pPugNarrativePal` | `FUN_00432221` | end credits |
| `0x005A6938` | `FUN_00433C50` | 9 `pBookSysPal` | `FUN_00432C38` | game options |
| `0x005A6CB0` | `FUN_00437E50` | 11 `pDocumentPal` | `FUN_004379E0` | document viewer |
| `0x005A6EB8` | `FUN_004CEA00` | 0 `pIntfacePal` | `FUN_00438802` | journal |
| `0x005A9F78` | `FUN_0052A3C0` | 9 or none | `FUN_00529922` | system options |

This is the only place `pDocumentPal` and `pPaperPal` appear at all — they
have no literal `RtSetPalette` site. The journal row is worth keeping: it is a
*positive* statement that a screen uses the default, not an absence.

**3. Two static tables in the image**, both read by name-resolved code:

- `0x00610A60`, 44 records of 24 bytes, walked by `FUN_0054a428` (`RtK.c`
  212190). Field `+0x00` is a wilderness node's sprite id, `+0x0c` is a path
  count and `+0x10` points at that many `(node, sprite)` pairs. It names 109
  sprites, ids 125..427 — every hotspot and every road segment on the
  wilderness map, none of which appears as a literal anywhere.
- `0x00615F7C`, `(name, sprite)` pairs feeding the `pDocumentPal` viewer's
  page list: `7758 sDocJoraths1`, `7760 sDocNighthawks1`, `7768 sDocGerards`,
  `7770 sDocScribes`, `7772 sDocPromissories`, `7774 sDocThievesMap`,
  `7776 sDocWoodcutters1`, `7782 sWitchDoc`.

## From screens to bitmaps

The archive's own records carry sprite→bitmap edges. Three record layouts,
each validated over every instance in the archive
(`tools/_probe_resgraph.py`):

| Type | Layout | Validated |
|---|---|---|
| SPRITE | `70 + 4n` bytes; `n` at `+0x0c`; `n` u32 resource refs from `+0x26` | 1,509 / 1,509 exact size match, every ref in range |
| CEL | 16 bytes; u32 at `+0x00` is a BITMAP id | 921 / 921 resolve to BITMAP |
| GROUP | flat u32 array of SPRITE ids | 17 / 17, 189 refs, all SPRITE |

Sprite references resolve to 5,030 BITMAP, 1,451 CEL, 167 QUEUE and 351 TEXT —
i.e. a sprite holds the full flat list of everything it can draw, and the
queues index into it, so closing sprite→(bitmap | cel→bitmap) is sufficient.

Closing the engine-cited seeds over that graph gives, for the four maps and
the two puzzles that have fully literal control lists, a **perfectly
contiguous bitmap id run with no gaps**:

```
pMapPal        seeds 16   bitmaps  17   26..57     0 bitmaps in span unreached
pCataMapPal    seeds 14   bitmaps  15   59..86     0
pHaldonMapPal  seeds 16   bitmaps  17   88..119    0
pWildMapPal    seeds 111  bitmaps 200   121..430   0
pBPTPuzzlePal  seeds 19   bitmaps  77   6839..6961 0
pDoorPuzzlePal seeds 8    bitmaps 108   6971..7090 0
```

That is the load-bearing observation. Six independently-seeded screens each
reach a closed, gapless id interval and stop exactly where the next screen's
root sprite begins. The archive is laid out one screen at a time, in authoring
order, so a screen's id interval *is* its asset set. That is what licenses the
ranges in the table: the bounds are the screens' own first and last cited
resources, and nothing from another screen falls inside.

## The table

`BLOCKS` in `tools/palettemap.py`. Each entry carries its own evidence string.

| Palette | Resource id ranges | Bitmaps | Screen |
|---|---|---|---|
| `pIntfacePal` | everything else | 2,523 | default |
| `pTrapPal` | 5352–6835 | 990 | trap disarming |
| `pMapPal` | 25–57 | 17 | Krondor city map |
| `pCataMapPal` | 58–86 | 15 | catacombs map |
| `pHaldonMapPal` | 87–119 | 17 | Haldon Head map |
| `pWildMapPal` | 120–430 | 200 | wilderness map |
| `pBPTPuzzlePal` | 6836–6969 | 79 | beam/orb puzzle |
| `pShipPuzzlePal` | 4716–5351 | 525 | ship console puzzle |
| `pDoorPuzzlePal` | 6970–7090 | 108 | door wheel puzzle |
| `pBookSysPal` | 7091–7713, 7918–8107 | 591 | bookshelf, save/load, options |
| `pPugNarrativePal` | 7744–7753, 7908–7917 | 2 | Pug narrative, end credits |
| `pDocumentPal` | 7758–7783 | 13 | document viewer (scanned pages) |
| `pPaperPal` | 7754–7757, 7784–7799 | 9 | text-page viewer |

**2,566 of the 5,089 bitmaps get a non-default palette. The other 2,523 get
`pIntfacePal`**, which is not a fallback guess — it is the palette the engine
loads at startup and restores at 16 call sites.

### Where the id ranges came from, screen by screen

- **Maps.** `FUN_00547680` / `FUN_00547703` / `FUN_00547786` / `FUN_00547809`
  pair palettes 2/3/4/5 with root sprites 25/58/87/120. Each dialog proc
  (`FUN_00547f70`, `FUN_00548ab6`, `FUN_0054960f`, `FUN_0054a75c`) resolves
  its hotspot sprites through `FUN_004b9610`, which is just
  `RtLoad` + `RtGetResource`. Krondor 27..55, catacombs 60..84, Haldon
  89..117, wilderness from the `0x610A60` table.
- **Ship console puzzle.** `FUN_004366c0` case `0x16` with `param_3 & 2` sets
  palette 7 and calls `FUN_0055a190`. The builder `FUN_0055a3cf` creates 88
  controls from `4719 sPicture` to `5317 sReal_28t`. Note the dialog *root*
  it passes to `Win_CreateDlg` is `0x1bb9 = 7097 sBookShelfBkGnd`, which looks
  wrong and probably is an asset-reuse quirk in the game; the identification
  rests on the control list and on the script hooks it registers
  (`0x126c..0x126e` = `xUpdatePuzzle`, `xUpdateInsertedPieces`,
  `xSolvedDelayFinished`), not on the root.
- **Traps.** Same dispatcher, case `0x12`, palette 1, `FUN_00565c30`.
  `FUN_0056604a` adds 84 controls spanning `5354 sTrap_GearSink` to
  `6830 sTrap_Gate`; `FUN_005689fd` the five tools; `FUN_0056a1b1/293/375`
  the door, chest and desk covers at 6774..6816.
- **Puzzles.** `param_3 & 1` → palette 6 and `6838 sPuzzleBack`;
  `param_3 & 4` → palette 8 and `6970 sDoorPuzBkGnd`.
- **Books and options.** Case `0x19` sets palette 9 with no dialog of its
  own; the bookshelf screens are built by `FUN_00534ebf`, `FUN_0053563c`,
  `FUN_00534ef3`, `FUN_005363bd`, `FUN_00537c6b`, `FUN_00538316`,
  `FUN_0053819b` over 7099..7709, and the two options classes above cover
  7918..8107.
- **Documents.** Both viewers open on `7756 sDocBackdrop`; the split between
  them is the `0x615F7C` page table (images → `pDocumentPal`) versus
  `FUN_00427701`'s literal `7788 sDocBody` / `7789 tDocBody` (text →
  `pPaperPal`).

## Does it render correctly?

`tools/_probe_palcheck.py`, output in `out/probe/palcheck.txt`, samples up to
40 bitmaps per palette and scores each under all 13:

    score(P) = E[ |P[a] - P[b]| : a,b 4-neighbours ]
             / E[ |P[a] - P[b]| : a,b independent draws from the same histogram ]

Lower is smoother. The denominator makes it scale-free so a narrow-gamut
palette cannot win by default.

**The decisive number is the head-to-head against the old behaviour.** Over
the 266 sampled bitmaps that this table *moves off* `pIntfacePal`:

```
palettemap's pick is smoother   237  (89.1%)
tie (within 1%)                  10  ( 3.8%)
pIntfacePal is smoother          19  ( 7.1%)
pIntfacePal is smoothest of 13    1  ( 0.4%)
```

So for the bitmaps the table reassigns, the viewer's old default is essentially
never the most plausible palette, and the new choice beats it nine times out
of ten.

The full 13-way ranking is weaker, and honestly so:

```
TOTAL n=306   mapped palette ranks first 172 (56.2%)
              within 5% of the best score 207 (67.6%)
```

`pDoorPuzzlePal` 40/40 and `pDocumentPal` 13/13 rank first; `pShipPuzzlePal`
30/40 and `pBookSysPal` 28/40. `pBPTPuzzlePal` ranks first only 1/40 and
`pWildMapPal` 0/7 — and those are exactly the cases where the metric is wrong
rather than the table, which the rendered samples settle:

| asset | under the mapped palette | under `pIntfacePal` |
|---|---|---|
| `121 bmaps_wild` | green forest, blue sea, white snowline | brown-grey mush, speckle |
| `6839 bdapu_zzle` | clean gold hex frame | olive frame with magenta speckle |
| `7745 bNarrateBack` | warm parchment Midkemia map | sickly yellow-green, magenta in the forests |
| `7759 bDocJoraths1` | aged paper, red-brown ink | olive-green paper, black ink |

All of these are in `out/png/palcheck/`, each written twice — once under the
mapped palette and once under `pIntfacePal` with `WRONG` in the filename — so
the comparison can be made by eye. The metric penalises `pBPTPuzzlePal` and
`pWildMapPal` because several palettes are within a few percent of each other
on those images; the visual difference is not subtle.

## What is not resolved

Stated plainly rather than filled in:

- **The 2,523 bitmaps left at `pIntfacePal`** are correct by the engine's own
  default, but only a handful of their screens are *positively* confirmed (the
  journal, via `FUN_004CEA00`). The rest are default by absence of any
  `RtSetPalette` on a path that reaches them. That is weaker evidence than for
  the 2,566 reassigned ones.
- **Ids 7714–7743**, the character-pick screen built by `FUN_00556c92`: no
  `RtSetPalette` on any path I could follow, so it keeps the default, but this
  is absence of evidence.
- **The shared document chrome.** `7756 sDocBackdrop`, `7757 cDocBackdrop` and
  the page arrows `7790..7799` are created by *both* document viewers, so they
  are genuinely realised under two different palettes depending on which one
  is open. `palettemap.AMBIGUOUS` lists them; `palette_for` resolves them to
  `pPaperPal` because that class creates all of them as literals while the
  `pDocumentPal` class creates only three. One of the 12 shows up in the check
  as a visible miss (`bDocPrevHilite`, rank 6, smoothest under `pIntfacePal`).
- **512 of the 2,566 are contiguity, not citation.** Closing the engine-cited
  seeds over the archive graph reaches 2,054 of them directly; the other 512
  sit inside a block whose two ends are cited but are not themselves named by
  any code I found:

  | palette | block | reached by the graph | by contiguity |
  |---|---|---|---|
  | `pBookSysPal` | 591 | 193 | 398 |
  | `pTrapPal` | 990 | 883 | 107 |
  | `pDocumentPal` | 13 | 8 | 5 |
  | `pBPTPuzzlePal` | 79 | 77 | 2 |
  | the other eight | 893 | 893 | 0 |

  `pBookSysPal` is the weak one: the bookshelf and save/load screens build
  most of their page content dynamically from script, so only a third of the
  block is statically cited. The five `pDocumentPal` gaps are the second
  image of each multi-page document, which the viewer reaches by incrementing
  through the `0x615F7C` table rather than by literal.
- **`pShipPuzzlePal`'s dialog root** is `7097 sBookShelfBkGnd`, which belongs
  to the bookshelf screen. Either the game reuses that sprite as an inert
  dialog root or the field means something else on that path. It does not
  affect the mapping, which rests on `FUN_0055a3cf`'s control list, but it is
  unexplained.
- **Nothing in the inflated `.def` / `.tbl` game data names a palette.**
  Grepping all 35 PyroTechnix containers for the 13 palette names returns
  nothing; the only `Palette` tokens are `GameData/Models.def`'s per-character
  `*Palette.bmp` files, which are 3D model texture palettes on disk and have
  no relation to RTKRES PALETTE resources. The data-driven hypothesis was
  checked and is negative.

## Tools

| Path | Purpose |
|---|---|
| `tools/palettemap.py` | the table; `palette_for(name_or_id)`, `palette_id_for`, `BLOCKS`, `SEEDS`, `AMBIGUOUS`. Run it to print the per-palette bitmap census. |
| `tools/_probe_palcheck.py` | the coherence check and the PNG samples |
| `tools/_probe_resgraph.py` | validates the SPRITE / CEL / GROUP reference layouts |
| `tools/_probe_palsites.py` | every `RtSetPalette` / `Win_CreateDlg` site, by function |
| `tools/_probe_ctrlsites.py` | every control-creation resource literal, grouped by function |
| `tools/_probe_vtabpal.py` | the `.rdata` vtable scan |
| `tools/_probe_screenres.py`, `tools/_probe_cover.py` | call-graph seed collection and coverage measurement |
| `tools/_probe_tiers.py` | cited-vs-contiguity split per block |
| `tools/_probe_spriteref.py` | hexdumps of SPRITE / QUEUE / CEL / GROUP records |

The `_probe_*` scripts are one-off investigation passes and `.gitignore` keeps
them out of version control, so they will not survive a fresh clone;
`palettemap.py` is the maintained artefact and carries the citations in its
docstring.
