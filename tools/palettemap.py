"""Which PALETTE resource each RTKRES BITMAP is meant to be drawn under.

Short answer: the association is **not** stored per bitmap. The engine realises
exactly one 236-colour palette at a time and the game names it per *screen*,
in code. This module is the recovered screen -> palette table plus the resource
id ranges each screen owns.

--------------------------------------------------------------------------
How the engine does it
--------------------------------------------------------------------------
`RtSetPalette(hRt, id)` (`Rtlib32.dll` export 245, `Rtlib32.c` 17533) posts an
internal message `0xb5` handled by `FUN_10001a0c`, which

    FUN_10013c92(id, 0x11)                     -- require resource type 17 = PALETTE
    FUN_10041f90(lib + 0x32cb, payload, 0x3b0) -- copy 944 bytes = 236 PALETTEENTRY
    SpriteChangePalette(sprite, 10, 0xec, ...) -- install at slots 10..245

so `RtSetPalette`'s second argument is a PALETTE *resource id*, and it replaces
the whole game range of the single global palette. Nothing else in the engine
selects a palette per bitmap: `SpriteRealizePalette` / `SpriteSelectPalette`
(`Rtlib32.c` 33108, 33130) both read one handle, `sprite + 0x46c`, created once
by `CreatePalette` at `Rtlib32.c` 33203. Bitmaps are blitted against whatever
is realised at the time.

The default is `pIntfacePal`. `FUN_1001e8a9` (`Rtlib32.c` 18253) seeds the
table from `GetSystemPaletteEntries` and then calls `ResLoadPalette`, which
reads **key resource 6** of the archive; key resource 6 is 944 bytes and is
byte-for-byte identical to PALETTE resource 0, `pIntfacePal`. `RtK.exe` has 28
`RtSetPalette` call sites: 16 pass a literal 0, i.e. restore that default when
a screen closes, 10 pass a literal 1..10, and 2 pass a value read from a C++
screen object (which is where 11 and 12 come from).

--------------------------------------------------------------------------
Where the per-screen choice is written down
--------------------------------------------------------------------------
Two places, both in `RtK.exe`:

1.  Direct call sites. Each pairs `RtSetPalette(hRt, P)` with the dialog it is
    opening. `Win_CreateDlg`'s third argument and `Win_CreateControl`'s third
    argument are SPRITE resource ids -- `WinCtrl_create` (`kronctrl.c` 1032 ->
    `Rtlib32`) calls `RtGetResType(hRt, id)` and bails out unless the type is
    `0x14` = SPRITE, then `RtLoad`s it. So the call site names both the palette
    and the screen's sprites.

2.  A C++ screen base class. Its vtable slot `+0x14` returns the screen's
    palette id as a constant and slot `+0x20` is the "build my controls"
    method (slot `+0x1c` is always `FUN_0052e785`, which is what does the
    `RtSetPalette`). Scanning `.rdata` for vtables with that shape finds the
    document, paper, credits and options screens.

One more table is read straight out of the image: the wilderness map's 44
nodes live at VA `0x00610A60`, 24 bytes each, walked by `FUN_0054a428`
(`RtK.c` 212190). Field `+0x00` is the node's sprite id and `+0x10` points at
`numPaths` (node, sprite id) pairs. That yields all 109 wilderness sprites.

--------------------------------------------------------------------------
From screens to bitmaps
--------------------------------------------------------------------------
The archive's own records carry the sprite -> bitmap edges, and they validate
exactly over the whole archive (see `tools/_probe_resgraph.py`):

    SPRITE  70 + 4*n bytes, n at +0x0c, n u32 refs from +0x26   1509/1509
    CEL     16 bytes, u32 at +0x00 is a BITMAP id                921/921
    GROUP   flat u32 array of SPRITE ids                           17/17

Closing the engine-cited seeds over that graph reaches each screen's bitmaps.
For the four maps and the two orb/door puzzles the result is a *perfectly
contiguous* id run with no gaps, which is the evidence that the archive is laid
out one screen at a time; that is what licenses `BLOCKS` below, whose bounds
are the screens' own first and last cited resources.

Everything outside a block keeps `pIntfacePal`.
"""

import re
from pathlib import Path

__all__ = [
    "PALETTES", "DEFAULT_PALETTE", "BLOCKS", "SEEDS", "AMBIGUOUS",
    "palette_for", "palette_id_for", "resource_id", "resource_name",
    "asset_id", "load_header",
]

# PALETTE resources, in archive order. RTKRES.h ids 0..12.
PALETTES = [
    "pIntfacePal", "pTrapPal", "pMapPal", "pCataMapPal", "pHaldonMapPal",
    "pWildMapPal", "pBPTPuzzlePal", "pShipPuzzlePal", "pDoorPuzzlePal",
    "pBookSysPal", "pPugNarrativePal", "pDocumentPal", "pPaperPal",
]
PALETTE_ID = {n: i for i, n in enumerate(PALETTES)}

DEFAULT_PALETTE = "pIntfacePal"
"""Engine default. Archive key resource 6 == PALETTE 0 byte-for-byte, and it is
what `FUN_1001e8a9` loads at startup and what 12 `RtSetPalette(_, 0)` sites
restore."""


# --------------------------------------------------------------------------
# The table. Each entry: palette, inclusive id ranges, and the engine evidence.
# "cited" lists the resource ids that appear as literals in the named
# functions; the range bounds are those ids plus the start of the next screen.
# --------------------------------------------------------------------------
BLOCKS = [
    dict(
        palette="pMapPal",
        ranges=[(25, 57)],
        screen="Krondor city map",
        evidence="RtK.c FUN_00547680: RtSetPalette(hRt,2) then "
                 "Win_CreateDlg(...,0x19=25 sMap,...). Hotspot sprites "
                 "27,31,35,39,43,47,51 via FUN_004b9610 in the dialog proc "
                 "FUN_00547f70; exit sprite 55 (sKrondorExit). Closure over "
                 "those reaches bitmaps 26..57 with no gaps; 58 is the next "
                 "screen's root.",
        cited=[25, 27, 29, 31, 33, 35, 37, 39, 41, 43, 45, 47, 49, 51, 53, 55],
    ),
    dict(
        palette="pCataMapPal",
        ranges=[(58, 86)],
        screen="Catacombs map",
        evidence="RtK.c FUN_00547703: RtSetPalette(hRt,3) then "
                 "Win_CreateDlg(...,0x3a=58 sCatacomb,...); hotspots "
                 "60,64,68,72,76,80 and exit 84 in FUN_00548ab6 / "
                 "FUN_00548f47. Closure reaches 59..86 with no gaps.",
        cited=[58, 60, 62, 64, 66, 68, 70, 72, 74, 76, 78, 80, 82, 84],
    ),
    dict(
        palette="pHaldonMapPal",
        ranges=[(87, 119)],
        screen="Haldon Head map",
        evidence="RtK.c FUN_00547786: RtSetPalette(hRt,4) then "
                 "Win_CreateDlg(...,0x57=87 sHaldonHead,...); hotspots "
                 "89,93,97,101,105,109,113 and exit 117 in FUN_0054960f. "
                 "sHaldonHead's single sprite ref is 88 bHaldmap_, the asset "
                 "that first exposed the bug. Closure reaches 88..119, no "
                 "gaps.",
        cited=[87, 89, 91, 93, 95, 97, 99, 101, 103, 105, 107, 109, 111, 113,
               115, 117],
    ),
    dict(
        palette="pWildMapPal",
        ranges=[(120, 430)],
        screen="Wilderness map",
        evidence="RtK.c FUN_00547809: RtSetPalette(hRt,5) then "
                 "Win_CreateDlg(...,0x78=120 sWilderness,...); exit 122 in "
                 "FUN_0054a428, which also walks the 44-entry node table at "
                 "RtK.exe VA 0x00610A60 (24-byte records: +0x00 node sprite, "
                 "+0x0c numPaths, +0x10 path array of (node, sprite)). That "
                 "table names 109 sprites, 125..427. Closure reaches bitmaps "
                 "121..430 with no gaps; 431 tMsgText starts shared UI.",
        cited=[120, 122],
    ),
    dict(
        palette="pShipPuzzlePal",
        ranges=[(4716, 5351)],
        screen="Ship console puzzle",
        evidence="RtK.c FUN_004366c0 case 0x16, param_3&2: RtSetPalette"
                 "(hRt,7) then FUN_0055a190 -> dialog proc FUN_0055a1c4, "
                 "which registers script hooks 0x126c..0x126e = 4716..4718 "
                 "(xUpdatePuzzle, xUpdateInsertedPieces, "
                 "xSolvedDelayFinished). Its control builder FUN_0055a3cf "
                 "creates 88 controls spanning 4719 sPicture .. 5317 "
                 "sReal_28t; FUN_0055b309/FUN_0055b59c add 5333, 5339. "
                 "Closure reaches bitmaps 4720..5332 contiguously. 5352 "
                 "sTraps_Bkgnd starts the next screen.",
        cited=[4716, 4719, 4721, 4723, 4726, 5317, 5333, 5336, 5339],
    ),
    dict(
        palette="pTrapPal",
        ranges=[(5352, 6835)],
        screen="Trap disarming screen",
        evidence="RtK.c FUN_004366c0 case 0x12: RtSetPalette(hRt,1) then "
                 "FUN_00565c30, which creates 5352 sTraps_Bkgnd and 5718 "
                 "sTrap_ToolBox. FUN_0056604a creates 84 more controls "
                 "5354..6830 (sTrap_GearSink .. sTrap_Gate); FUN_005689fd "
                 "the five tools 5721..5734; FUN_0056a1b1/293/375 the "
                 "door/chest/desk covers 6774..6816. 6836 xPuzzle_HidePosts "
                 "starts the next screen.",
        cited=[5352, 5354, 5490, 5718, 5721, 5734, 6582, 6774, 6816, 6830],
    ),
    dict(
        palette="pBPTPuzzlePal",
        ranges=[(6836, 6969)],
        screen="Beam/orb puzzle",
        evidence="RtK.c FUN_004366c0 case 0x16, param_3&1: RtSetPalette"
                 "(hRt,6) then FUN_00558780 -> Win_CreateDlg(...,0x1ab6=6838 "
                 "sPuzzleBack,...). Dialog proc FUN_005587f2 creates "
                 "6840..6948 (sPuzzleDropArea .. sPuzzleOrb6). Closure "
                 "reaches bitmaps 6839..6961 with no gaps.",
        cited=[6838, 6840, 6842, 6848, 6888, 6948],
    ),
    dict(
        palette="pDoorPuzzlePal",
        ranges=[(6970, 7090)],
        screen="Door wheel puzzle",
        evidence="RtK.c FUN_004366c0 case 0x16, param_3&4: RtSetPalette"
                 "(hRt,8) then FUN_0053b190 -> Win_CreateDlg(...,0x1b3a=6970 "
                 "sDoorPuzBkGnd,...). Dialog proc FUN_0053b2b2 creates "
                 "6972..7068 (sDoorPuzOpen .. sWheel_5). Closure reaches "
                 "bitmaps 6971..7090 with no gaps; 7091 xBookSys_* is the "
                 "next screen.",
        cited=[6970, 6972, 6974, 7068],
    ),
    dict(
        palette="pBookSysPal",
        ranges=[(7091, 7713), (7918, 8107)],
        screen="Book shelf / save-load / options",
        evidence="RtK.c FUN_004366c0 case 0x19: RtSetPalette(hRt,9). The "
                 "bookshelf screens create 7099 sBookShelf (FUN_00534ebf), "
                 "7101..7126 (FUN_0053563c), 7534..7569 (FUN_00534ef3), "
                 "7604..7691 (FUN_005363bd), 7695..7697 (FUN_00537c6b), "
                 "7702..7709 (FUN_00538316, FUN_0053819b). The options "
                 "screens are the C++ class at vtable 0x005A6938, whose "
                 "palette getter FUN_00433c50 returns 9: builder "
                 "FUN_00432c38 creates 7918, 7922 and 8022..8103. The system "
                 "options class at 0x005A9F78 returns 9 conditionally "
                 "(FUN_0052a3c0) and creates 7918, 7920, 7941..8019.",
        cited=[7099, 7101, 7126, 7534, 7569, 7604, 7691, 7695, 7702, 7709,
               7918, 7920, 7922, 8022, 8103],
    ),
    dict(
        palette="pPugNarrativePal",
        ranges=[(7744, 7753), (7908, 7917)],
        screen="Pug narrative interludes and end credits",
        evidence="RtK.c FUN_0054d217: RtSetPalette(hRt,10) then "
                 "Win_CreateDlg(...,0x1e42=7746 sNarrateBackdrop,...); "
                 "FUN_0054d280 creates 7744..7752. The credits screen is the "
                 "C++ class at vtable 0x005A6880 whose palette getter "
                 "FUN_00432970 returns 10; builder FUN_00432221 creates "
                 "7908 sCreditsBack, 7912, 7914, 7916.",
        cited=[7744, 7746, 7748, 7750, 7752, 7908, 7912, 7914, 7916],
    ),
    dict(
        palette="pDocumentPal",
        ranges=[(7758, 7783)],
        screen="In-game document viewer (scanned pages)",
        evidence="C++ class at vtable 0x005A6CB0; palette getter "
                 "FUN_00437e50 returns 0xb. Its builder FUN_004379e0 opens "
                 "on 0x1e4c=7756 sDocBackdrop and then creates one control "
                 "per entry of a page list. That list is the (name, sprite) "
                 "table at RtK.exe VA 0x00615F7C: 7758 sDocJoraths1, 7760 "
                 "sDocNighthawks1, 7768 sDocGerards, 7770 sDocScribes, 7772 "
                 "sDocPromissories, 7774 sDocThievesMap, 7776 "
                 "sDocWoodcutters1, 7782 sWitchDoc. The range is closed over "
                 "the continuation pages that sit between them (7762..7766 "
                 "sDocNighthawks2-4, 7778..7780 sDocWoodcutters2-3).",
        cited=[7758, 7760, 7768, 7770, 7772, 7774, 7776, 7782],
    ),
    dict(
        palette="pPaperPal",
        ranges=[(7754, 7757), (7784, 7799)],
        screen="In-game text-page viewer (letters, book pages)",
        evidence="C++ class at vtable 0x005A6550; palette getter "
                 "FUN_00427a40 returns 0xc. Its builder FUN_00427701 calls "
                 "FUN_0052e785(this, 0x1e4c=7756 sDocBackdrop, 0x1e4a=7754 "
                 "sDocBack, 1) and creates 7788 sDocBody / 7789 tDocBody and "
                 "the page arrows 7790 sDocPrev, 7795 sDocNext. See "
                 "AMBIGUOUS: the frame and the arrows are shared with the "
                 "pDocumentPal viewer.",
        cited=[7754, 7756, 7788, 7790, 7795],
    ),
]

SEEDS = {b["palette"]: tuple(b["cited"]) for b in BLOCKS}

AMBIGUOUS = {
    # Both document viewers open on the same frame and page arrows, so these
    # are realised under whichever of the two palettes is current. The table
    # below resolves them to pPaperPal because that class creates all of them
    # as literals while the pDocumentPal class creates only 7756/7790/7795.
    7756: ("pPaperPal", "pDocumentPal"),   # sDocBackdrop
    7757: ("pPaperPal", "pDocumentPal"),   # cDocBackdrop
    7790: ("pPaperPal", "pDocumentPal"),   # sDocPrev + its 4 bitmaps
    7791: ("pPaperPal", "pDocumentPal"),
    7792: ("pPaperPal", "pDocumentPal"),
    7793: ("pPaperPal", "pDocumentPal"),
    7794: ("pPaperPal", "pDocumentPal"),
    7795: ("pPaperPal", "pDocumentPal"),   # sDocNext + its 4 bitmaps
    7796: ("pPaperPal", "pDocumentPal"),
    7797: ("pPaperPal", "pDocumentPal"),
    7798: ("pPaperPal", "pDocumentPal"),
    7799: ("pPaperPal", "pDocumentPal"),
}

UNRESOLVED_NOTE = """\
Resource ids 7714..7743 (the character-pick screen, built by FUN_00556c92)
and 7800..7907 (inventory-select and the journal) are left at the default.
The journal is positively confirmed as pIntfacePal -- its C++ class at vtable
0x005A6EB8 has palette getter FUN_004CEA00, which returns 0. The character-pick
screen has no RtSetPalette on any path reaching it, which also means
pIntfacePal, but by absence of evidence rather than by a positive statement.
"""


# --------------------------------------------------------------------------
# id <-> name, from the RTKRES.h the game ships next to RTKRES.bin.
# The studio calls load_header once it knows which install was opened.
# Nothing in this file is a copy of that header.
# --------------------------------------------------------------------------
_DEFINE = re.compile(r"#define\s+(\S+)\s+(\d+)\s*//\s*(\d+)\s+(\w+)")

_NAME_TO_ID = {}
_ID_TO_NAME = {}
_ID_TO_TYPE = {}


def load_header(path) -> bool:
    """Fill the name tables from an install's RTKRES.h. Returns False if missing."""
    path = Path(path)
    if not path.is_file():
        return False
    found, ids, types = {}, {}, {}
    for name, i, _, ty in _DEFINE.findall(path.read_text(errors="replace")):
        i = int(i)
        found[name] = i
        ids[i] = name
        types[i] = ty
    if not found:
        return False
    _NAME_TO_ID.clear()
    _NAME_TO_ID.update(found)
    _ID_TO_NAME.clear()
    _ID_TO_NAME.update(ids)
    _ID_TO_TYPE.clear()
    _ID_TO_TYPE.update(types)
    return True


def resource_id(key):
    """Accept an id or a RTKRES.h name; return the numeric id or None."""
    if isinstance(key, int):
        return key
    s = str(key).strip()
    if s.isdigit():
        return int(s)
    return _NAME_TO_ID.get(s)


def resource_name(rid):
    return _ID_TO_NAME.get(rid)


def asset_id(asset):
    """Numeric RTKRES id for a studio asset, when it is a resource.

    The member id is enough. The name table is only needed when a caller
    has a RTKRES.h symbol and no id.
    """
    if asset is None:
        return None
    if getattr(asset, "source", None) == "res":
        member = getattr(asset, "member", None)
        if member is not None and str(member).isdigit():
            return int(member)
    return resource_id(getattr(asset, "name", ""))


# id -> palette, built once from BLOCKS
_MAP = {}
for _b in BLOCKS:
    for _lo, _hi in _b["ranges"]:
        for _r in range(_lo, _hi + 1):
            _MAP[_r] = _b["palette"]


def palette_for(key):
    """Palette resource name for a bitmap (or any resource).

    Returns the screen palette if the resource falls in a screen block, the
    engine default `pIntfacePal` for any other known resource, and None if the
    name or id is not a resource of this archive.
    """
    rid = resource_id(key)
    if rid is None:
        return None
    if _ID_TO_NAME and rid not in _ID_TO_NAME:
        return None
    return _MAP.get(rid, DEFAULT_PALETTE)


def palette_id_for(key):
    """Same, as a PALETTE resource id (0..12), or None."""
    name = palette_for(key)
    return None if name is None else PALETTE_ID[name]


if __name__ == "__main__":
    from collections import Counter
    counts = Counter()
    for rid, ty in _ID_TO_TYPE.items():
        if ty == "BITMAP":
            counts[palette_for(rid)] += 1
    total = sum(counts.values())
    print(f"{total} BITMAP resources")
    for name in PALETTES:
        print(f"  {name:18s} {counts.get(name, 0):5d}")
    print(f"  {'non-default total':18s} "
          f"{total - counts[DEFAULT_PALETTE]:5d}")
