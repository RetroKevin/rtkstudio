"""UI studio: compose and edit a 640×480 screen from SPRITE → CEL → BITMAP.

Layout overlays live in the mod (`ui/layouts.json`). SPRITE ref lists,
CEL bitmaps, QUEUE timings, and BITMAP hotspots are rewritten in place
and stored as overrides. Pixel edits go through the existing bitmap path.
Positions come from ui.md when known, then the overlay, then the
centered-sprite + hotspot formula (ui.md §2).
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import palettemap

# Frame origin in sprite space (RtSetScreenRes 640×480).
FRAME_OX, FRAME_OY = 319, 239

# ui.md §§4–6 — top-left + size in frame pixels. Chrome rides every sheet.
PLACED = {
    "sMain_StatusBar": (0, 433, 640, 81),
    "sMain_MenuBtn": (7, 456, 117, 21),
    "sMain_MenuBack": (23, 222, 227, 226),
    "sMain_Book": (54, 231, 160, 35),
    "sMain_Options": (49, 268, 168, 33),
    "sMain_Journal": (50, 303, 167, 34),
    "sMain_Rest": (49, 337, 166, 35),
    "sMain_Maps": (52, 374, 161, 32),
    "sMain_Exit": (52, 408, 162, 40),
    "sMain_SideBar": (582, 0, 58, 416),
    "sMain_AttributesTab": (600, -1, 40, 79),
    "sMain_SpellsTab": (601, 83, 39, 80),
    "sMain_InventoryTab": (602, 168, 38, 78),
    "sMain_PartyTab": (600, 249, 40, 82),
    "sMain_ExitTab": (598, 332, 42, 83),
    "sMain_ExitConfirm": (184, 163, 272, 153),
    "sMain_ExitWSave": (216, 184, 207, 17),
    "sMain_ExitWoSave": (215, 230, 207, 17),
    "sMain_ExitReturn": (216, 276, 207, 17),
    "sAttr_Bkgnd": (0, 0, 640, 480),
    "sSpellsBkDrop": (0, 0, 640, 480),
    "sSpells": (-1, 0, 597, 416),
    "sInv_BottomCover": (9, 366, 640, 81),
    "sInventory": (0, 0, 597, 416),
    "sInventoryPanel": (205, 5, 192, 300),
    "sInventoryDefaultMode": (208, 331, 190, 82),
    "sInventoryLootingChestMode": (208, 331, 190, 82),
    "sInventoryLootingBodyMode": (208, 331, 190, 82),
    "sInventoryLootingGroundMode": (208, 331, 190, 82),
    "sParty_Bkgnd": (0, 0, 640, 480),
    "sParty_Panel_Buttons": (422, 375, 163, 37),
    "sShopping_Main": (0, 0, 597, 416),
    "sShopping_QuantityPopup": (200, 89, 230, 199),
    "sConvBackHuge": (156, 30, 350, 400),
    "sConvBackBig": (156, 80, 350, 299),
    "sConvBackTiny": (156, 180, 350, 120),
    "sMisc_IDMenu": (79, 9, 481, 411),
    "sMisc_AssessBtn": (121, 375, 89, 17),
    "sMisc_NPCMenu": (232, 185, 178, 110),
    "sMisc_Enemy1_Back": (206, 106, 230, 268),
    "sMisc_Enemy2_Back": (203, 121, 230, 237),
    "sMap": (0, 0, 640, 480),
    "sCatacomb": (0, 0, 640, 480),
    "sHaldonHead": (0, 0, 640, 480),
    "sWilderness": (0, 0, 640, 480),
    "sTraps_Bkgnd": (0, 0, 640, 480),
    "sPuzzleBack": (0, 0, 640, 480),
    "sDoorPuzBkGnd": (0, 0, 640, 480),
    "sBookShelf": (0, 0, 640, 480),
    "sMsgBackground": (0, 0, 32, 32),
    "sJournalFrame": (0, 0, 640, 480),
    "sOptionsBackdrop": (0, 0, 640, 480),
    "sDocBackdrop": (0, 0, 640, 480),
    "sBookWinSave": (0, 0, 640, 480),
}

CHROME = (
    "sMain_StatusBar", "sMain_MenuBtn", "sMain_SideBar",
    "sMain_AttributesTab", "sMain_SpellsTab", "sMain_InventoryTab",
    "sMain_PartyTab", "sMain_ExitTab",
)

SCREENS = [
    {"id": "0x0", "name": "Frame (status + sidebar)",
     "palette": "pIntfacePal", "prefixes": ("smain_",),
     "roots": CHROME, "chrome": False,
     "opener": "FUN_004366c0", "proc": "FUN_00545eb8",
     "does": "No dialog. Resolves the party and installs the status bar, sidebar, and menu.",
     "aliases": ()},
    {"id": "0x1", "name": "Spells",
     "palette": "pIntfacePal", "prefixes": ("sspells", "bspells"),
     "roots": ("sSpellsBkDrop", "sSpells"), "chrome": True,
     "opener": "FUN_005471ef", "does": "Spells sheet. Sidebar radio 0x9a.",
     "aliases": ()},
    {"id": "0x3", "name": "Inventory",
     "palette": "pIntfacePal",
     "prefixes": ("sinv_", "sinventory", "binv_", "binventory"),
     "roots": ("sInv_BottomCover", "sInventory", "sInventoryPanel"),
     "chrome": True,
     "opener": "FUN_005471a8",
     "does": "Inventory sheet. 0x5 is DoLooting / a container click; 0x9 is the right-click region menu.",
     "aliases": ("0x5", "0x6", "0x7", "0x9", "0xa", "0xb")},
    {"id": "0x4", "name": "Party",
     "palette": "pIntfacePal", "prefixes": ("sparty_", "bparty_"),
     "roots": ("sParty_Bkgnd",), "chrome": True,
     "opener": "FUN_0054729f",
     "does": "Party sheet, only if resting is allowed (FUN_00547236).",
     "aliases": ()},
    {"id": "0xc", "name": "Attributes",
     "palette": "pIntfacePal", "prefixes": ("sattr_", "battr_"),
     "roots": ("sAttr_Bkgnd",), "chrome": True,
     "opener": "FUN_00547161",
     "does": "Attributes sheet. 0xc is also the NPC click that is not a direct conversation.",
     "aliases": ("0xd", "0xe")},
    {"id": "0x8", "name": "Shop",
     "palette": "pIntfacePal", "prefixes": ("sshopping", "bshopping"),
     "roots": ("sShopping_Main",), "chrome": True,
     "opener": "FUN_0055b6ff", "does": "Shop, same shape as inventory.",
     "aliases": ()},
    {"id": "0x12", "name": "Lock and trap",
     "palette": "pTrapPal", "prefixes": ("strap", "btrap", "straps"),
     "roots": ("sTraps_Bkgnd",), "chrome": False, "limit": 80,
     "opener": "FUN_00565c30", "proc": "FUN_0056604a",
     "does": "Lock and trap. Gear click is control 0x6f; tools are 0x95–0x99.",
     "aliases": ()},
    {"id": "0x13", "name": "Conversation (huge)",
     "palette": "pIntfacePal", "prefixes": ("sconv", "bconv"),
     "roots": ("sConvBackHuge",), "chrome": True,
     "opener": "FUN_0053a522", "does": "Huge bubble, forced to 10 lines. Dialog 0x1b38.",
     "aliases": ()},
    {"id": "0x14", "name": "Conversation (sized)",
     "palette": "pIntfacePal", "prefixes": ("sconv", "bconv"),
     "roots": ("sConvBackBig",), "chrome": True,
     "opener": "FUN_005383b0",
     "does": "Sized bubble from the line-count table. Dialog 0x1b3a. Choice rows are script-driven.",
     "aliases": ()},
    {"id": "0x15", "name": "Conversation (tiny)",
     "palette": "pIntfacePal", "prefixes": ("sconv", "bconv"),
     "roots": ("sConvBackTiny",), "chrome": True,
     "opener": "FUN_00539eb5", "does": "Tiny bubble, 3 lines. Dialog 0x1b39.",
     "aliases": ()},
    {"id": "0x16a", "name": "Beam puzzle",
     "palette": "pBPTPuzzlePal", "prefixes": ("spuzzle", "bpuzzle"),
     "roots": ("sPuzzleBack",), "chrome": False, "limit": 80,
     "opener": "FUN_00558780", "does": "Interface 0x16 bit 1. Palette 6.",
     "aliases": ("0x16",)},
    {"id": "0x16b", "name": "Ship console",
     "palette": "pShipPuzzlePal", "prefixes": ("spicture", "sreal_"),
     "roots": (), "chrome": False, "limit": 80,
     "id_range": (4716, 5351),
     "opener": "FUN_0055a190",
     "does": "Interface 0x16 bit 2. Scripts xUpdatePuzzle, xUpdateInsertedPieces, xSolvedDelayFinished.",
     "aliases": ("0x16",)},
    {"id": "0x16c", "name": "Door wheel",
     "palette": "pDoorPuzzlePal", "prefixes": ("sdoorpuz", "swheel_"),
     "roots": ("sDoorPuzBkGnd",), "chrome": False,
     "opener": "FUN_0053b190", "does": "Interface 0x16 bit 4. Palette 8.",
     "aliases": ("0x16",)},
    {"id": "0x17a", "name": "Krondor map",
     "palette": "pMapPal", "prefixes": ("skrondor",),
     "roots": ("sMap",), "chrome": False, "id_range": (25, 57),
     "opener": "FUN_005473c0",
     "does": "Travel map 0x17. Hotspot → destination is in the four map dialog procs (interactions.md).",
     "aliases": ("0x17",)},
    {"id": "0x17b", "name": "Catacombs map",
     "palette": "pCataMapPal", "prefixes": ("scatacomb",),
     "roots": ("sCatacomb",), "chrome": False, "id_range": (58, 86),
     "opener": "FUN_005473c0", "does": "Travel map 0x17, catacombs.",
     "aliases": ("0x17",)},
    {"id": "0x17c", "name": "Haldon Head map",
     "palette": "pHaldonMapPal", "prefixes": ("shaldon", "bhald"),
     "roots": ("sHaldonHead",), "chrome": False, "id_range": (87, 119),
     "opener": "FUN_005473c0", "does": "Travel map 0x17, Haldon Head.",
     "aliases": ("0x17",)},
    {"id": "0x17d", "name": "Wilderness map",
     "palette": "pWildMapPal", "prefixes": ("swilderness",),
     "roots": ("sWilderness",), "chrome": False, "id_range": (120, 430),
     "limit": 60,
     "opener": "FUN_005473c0", "does": "Travel map 0x17, wilderness.",
     "aliases": ("0x17",)},
    {"id": "0x19", "name": "Book / save / options",
     "palette": "pBookSysPal",
     "prefixes": ("sbook", "bbook", "ssave", "sopt", "sshelf"),
     "roots": ("sBookShelf",), "chrome": False, "limit": 80,
     "opener": "FUN_00534ebf", "proc": "FUN_00534ef3",
     "does": "Palette 9 only. Shelf, save window, and options are built by the §9 callers.",
     "aliases": ()},
    {"id": "misc", "name": "Identify / NPC menus",
     "palette": "pIntfacePal", "prefixes": ("smisc_", "bmisc_"),
     "roots": ("sMisc_IDMenu", "sMisc_NPCMenu"), "chrome": True,
     "opener": "FUN_0054aa30",
     "does": "Identify (Assess / Use / Drop / Exit) and the attack / speak menu.",
     "aliases": ()},
    {"id": "journal", "name": "Journal",
     "palette": "pBookSysPal", "prefixes": ("sjournal", "bjournal"),
     "roots": ("sJournalFrame",), "chrome": False,
     "opener": "FUN_00438802",
     "does": "Journal. Tabs are four bitmaps each (bJournalTab0A–D).",
     "aliases": ()},
    {"id": "options", "name": "Options",
     "palette": "pBookSysPal",
     "prefixes": ("soptions", "ssysoptions", "sgameoptions", "bopt"),
     "roots": ("sOptionsBackdrop",), "chrome": False, "limit": 120,
     "opener": "FUN_0052e785",
     "does": "System and game options. Browse rows light the current line; radios are ordinary cel slots.",
     "aliases": ()},
    {"id": "document", "name": "Document viewer",
     "palette": "pDocumentPal", "prefixes": ("sdoc", "bdoc"),
     "roots": ("sDocBackdrop",), "chrome": False,
     "opener": "FUN_004379e0",
     "does": "Document viewer. Prev/next are four-bitmap type-4 buttons; the page sprite swaps, no queue.",
     "aliases": ()},
]


CTRL_TYPES = {
    0: "static", 1: "push", 2: "push", 3: "toggle",
    4: "push", 5: "radio", 8: "push",
}

ACTION_KINDS = (
    "static", "open_menu", "open_screen", "open_dialog", "close",
    "play_queue", "choice", "select", "tool", "quit", "save_quit",
    "unknown",
)


def _act(cid, kind, does, **kw):
    rec = {"control_id": cid, "kind": kind, "does": does, "source": "docs",
           "clickable": kind not in ("static",)}
    rec.update(kw)
    return rec


# ui.md §§4–9, traps.md §2 — sprite → Win_CreateControl id and click.
ACTIONS = {
    "sMain_StatusBar": _act(None, "static",
                            "Session chrome. Child of sMenu_ClickArea. Slides up 32px while the sidebar is open."),
    "sMain_MenuBtn": _act(0x65, "open_menu",
                          "Opens sMain_MenuBack.",
                          type=1, opens_sprite="sMain_MenuBack"),
    "sMain_MenuBack": _act(None, "static",
                           "Menu popup. Hidden until the menu button is down."),
    "sMain_Book": _act(0x68, "open_screen",
                       "Opens the save window (FUN_0043bb6b → FUN_00535dec). Same bit-0 enable test as Options / Journal / Maps.",
                       type=1, opens="0x19",
                       enabled_when="bit 0 of DAT_00628d6c+0x4bc2c and a named chapter"),
    "sMain_Options": _act(0x6b, "open_screen",
                          "FUN_00529740(1), system options.",
                          type=1, opens="options",
                          enabled_when="bit 0 of DAT_00628d6c+0x4bc2c"),
    "sMain_Journal": _act(0x6d, "open_screen",
                          "Opens the journal.",
                          type=1, opens="journal",
                          enabled_when="bit 0 of DAT_00628d6c+0x4bc2c"),
    "sMain_Rest": _act(0x6c, "open_screen",
                       "Opens the party sheet when FUN_00547236 is true.",
                       type=1, opens="0x4",
                       enabled_when="FUN_00547236 (rest allowed)"),
    "sMain_Maps": _act(0x6e, "open_screen",
                       "FUN_005473c0, the travel map.",
                       type=1, opens="0x17a",
                       enabled_when="bit 0 and DAT_00628d6c+0x4bbd4"),
    "sMain_Exit": _act(0x6f, "open_dialog",
                       "Opens the quit confirm (sMain_ExitConfirm).",
                       type=1, opens_sprite="sMain_ExitConfirm"),
    "sMain_AttributesTab": _act(0x97, "open_screen",
                                "Type-5 radio. Shows sAttr_Bkgnd, hides the other sheets.",
                                type=5, opens="0xc"),
    "sMain_SpellsTab": _act(0x9a, "open_screen",
                            "Type-5 radio. Shows sSpellsBkDrop.",
                            type=5, opens="0x1"),
    "sMain_InventoryTab": _act(0x98, "open_screen",
                               "Type-5 radio. Shows sInv_BottomCover.",
                               type=5, opens="0x3"),
    "sMain_PartyTab": _act(0x99, "open_screen",
                           "Type-5 radio. Opens the party sheet (no root sprite).",
                           type=5, opens="0x4",
                           enabled_when="FUN_00547236"),
    "sMain_ExitTab": _act(0x9b, "close",
                          "Closes the sidebar.", type=5),
    "sMain_SideBar": _act(None, "static",
                          "58×416 strip at level 12000. Parent of the five tabs."),
    "sMain_ExitConfirm": _act(None, "static",
                              "Quit confirm panel. FUN_00546e35."),
    "sMain_ExitWSave": _act(0x9e, "save_quit",
                            "Save and quit, only if a save exists.", type=1,
                            enabled_when="a save exists"),
    "sMain_ExitWoSave": _act(0x9c, "quit",
                             "Quit without saving (FUN_0050c7fa).", type=1),
    "sMain_ExitReturn": _act(0x9d, "close",
                             "Close the confirm and reopen the menu.", type=1),
    "sAttr_Bkgnd": _act(None, "static",
                        "Attributes sheet root. Arrows, point pool, done and reset are sAttr_* children."),
    "sSpellsBkDrop": _act(None, "static", "Spells sheet full-frame black."),
    "sSpells": _act(None, "static",
                    "Spell book. Character tabs/heads and the six group rows are children."),
    "sInv_BottomCover": _act(None, "static",
                             "Inventory root strip. The bag behind the panel is a 7×64 GridCreate."),
    "sInventory": _act(None, "static", "Inventory sheet picture, 597×416."),
    "sInventoryPanel": _act(None, "static", "Character panel on the inventory sheet."),
    "sParty_Bkgnd": _act(None, "static",
                         "Party sheet background. Built by the party procedure; the sheet itself has no root sprite."),
    "sParty_Book": _act(0x42e, "play_queue",
                        "Disables this control and plays qParty_Book_Open (cels 1–30 @ 83ms), then xParty_Book_Open_Finished.",
                        type=1, queue="qParty_Book_Open",
                        script="xParty_Book_Open_Finished"),
    "sParty_RecipePageTurn": _act(None, "play_queue",
                                  "Page flip. qFlipPageForwards is cels 0–4; qFlipPageBackwards is 4–0.",
                                  queue="qFlipPageForwards"),
    "sShopping_Main": _act(None, "static", "Shop sheet, same shape as inventory."),
    "sShopping_QuantityPopup": _act(None, "open_dialog",
                                    "Quantity popup on a shop buy/sell."),
    "sConvBackHuge": _act(None, "static",
                          "Huge conversation bubble. Choice rows are sConvChoice1–11."),
    "sConvBackBig": _act(None, "static", "Sized conversation bubble."),
    "sConvBackTiny": _act(None, "static", "Tiny conversation bubble."),
    "sMisc_IDMenu": _act(None, "static",
                         "Identify menu. Assess / Use / Drop / Exit along the bottom."),
    "sMisc_AssessBtn": _act(None, "select",
                            "Assess the current item (FUN_0054aa30).", type=1),
    "sMisc_NPCMenu": _act(None, "static", "Attack / speak menu."),
    "sMisc_AttackBtn": _act(None, "select", "Attack the NPC.", type=1),
    "sMisc_SpeakBtn": _act(None, "select", "Start a conversation.", type=1),
    "sBookShelf": _act(None, "static",
                       "Title shelf root. Clicks are message 0x100 in FUN_00534ef3."),
    "sBookShelfExit": _act(0x7d3, "quit", "Quit confirm. No queue.", type=1),
    "sBookShelfDeletePlayer": _act(0x7d4, "select",
                                   "FUN_00535c01(1), delete mode. Cursor queues qBookSys_Delete_Norm / _Hot.",
                                   type=1),
    "sBookShelfCancelDelete": _act(0x7d5, "close",
                                   "FUN_00535c01(0). Created hidden, shown in delete mode.",
                                   type=1, flags=0x400),
    "sBookShelfOptions": _act(0x7d6, "play_queue",
                              "sBookShelfSysOptionsOpen / qBookShelfSysOptionsOpen → xBookSys_SysOptionsFinished.",
                              type=1, opens="options",
                              queue="qBookShelfSysOptionsOpen",
                              script="xBookSys_SysOptionsFinished"),
    "sBookShelfNewPlayer": _act(0x7d7, "play_queue",
                                "sBookShelfNewBookOpen / qBookSysNewBookOpen → xBookSys_NewOpenFinished (game options).",
                                type=1, opens="options",
                                queue="qBookSysNewBookOpen",
                                script="xBookSys_NewOpenFinished"),
    "sBookShelfCredits": _act(0x7d8, "open_dialog",
                              "FUN_004320c3, the credits screen. No queue.",
                              type=1),
    "sBookWinOptions": _act(0x3ec, "open_screen",
                            "FUN_00432a50(1), game options with the book-name field disabled.",
                            type=1, opens="options"),
    "sBookWinExitToShelf": _act(0x3ef, "open_screen",
                                "FUN_00537af9. Shows the shelf, or builds it if needed.",
                                type=1, opens="0x19"),
    "sBookWinReturnToGame": _act(0x3f0, "close",
                                 "Return to the chapter. Disabled when no chapter is loaded.",
                                 type=1,
                                 enabled_when="DAT_00628d6c+0x18 != 0"),
    "sOptionsBackdrop": _act(None, "static",
                             "Shared options root (FUN_0052e785). Child is system or game background."),
    "sJournalFrame": _act(None, "static", "Journal root. Tabs swap the page; no queue."),
    "sDocBackdrop": _act(None, "static",
                         "Document viewer root. Prev/next are type-4 buttons; the page sprite swaps."),
    "sTraps_Bkgnd": _act(None, "static",
                         "Lock-and-trap root. Gear click is 0x6f in FUN_0056604a."),
    "sTrap_GearSink": _act(0x6f, "tool",
                           "Gear click. Freezes the gear queue and reads the cell as an angle for the disarm/neutral windows.",
                           type=1),
}

for _n in range(1, 11):
    ACTIONS["sBookShelfBook%d" % _n] = _act(
        0x7d8 + _n, "play_queue",
        "Open save slot %d. Queue finish is xBookSys_OpenFinished → the save window." % _n,
        type=1, opens="0x19", script="xBookSys_OpenFinished")
for _n in range(1, 12):
    ACTIONS["sConvChoice%d" % _n] = _act(
        None, "choice",
        "Conversation choice %d. The bubble procedure writes the line; the conversation script decides which rows exist." % _n,
        type=1)
for _name, _does in (
        ("sMisc_UseBtn", "Use the identified item."),
        ("sMisc_DropBtn", "Drop the identified item."),
        ("sMisc_ExitBtn", "Close the identify menu."),
        ("sMisc_IDExit", "Close the identify menu."),
):
    ACTIONS[_name] = _act(None, "select" if "Exit" not in _name else "close",
                          _does, type=1)


def _parse_sprite_refs(raw: bytes):
    if len(raw) < 0x2A:
        return []
    n = struct.unpack_from("<I", raw, 0x0C)[0]
    if n <= 0 or n > 512:
        return []
    need = 0x26 + 4 * n
    if len(raw) < need:
        n = max(0, (len(raw) - 0x26) // 4)
    return list(struct.unpack_from("<%dI" % n, raw, 0x26)) if n else []


def _parse_cel(raw: bytes):
    if len(raw) < 16:
        return None
    bmp, _a, hx, hy = struct.unpack_from("<IIii", raw, 0)
    return bmp, hx, hy


def _bmp_header(raw: bytes):
    if len(raw) < 20:
        return None
    w, h = struct.unpack_from("<II", raw, 0)
    hx, hy = struct.unpack_from("<ii", raw, 12)
    if w <= 0 or h <= 0 or w > 2048 or h > 2048:
        return None
    return w, h, hx, hy


def _frame_box(w, h, hx, hy, sx=0, sy=0):
    sl = sx - (w - 1) // 2 + hx
    st = sy - (h - 1) // 2 + hy
    return sl + FRAME_OX, st + FRAME_OY, w, h


def hotspot_for_box(x, y, w, h, sx=0, sy=0):
    """Inverse of _frame_box: bitmap hotspot that lands at frame (x, y)."""
    hx = int(x) - FRAME_OX - sx + (w - 1) // 2
    hy = int(y) - FRAME_OY - sy + (h - 1) // 2
    return hx, hy


def parse_queue(raw: bytes, by_id=None):
    cmds = []
    i = 0
    n = len(raw or b"")
    while i + 2 <= n:
        op = struct.unpack_from("<H", raw, i)[0]
        if op == 1 and i + 22 <= n:
            first, last = struct.unpack_from("<II", raw, i + 2)
            delay = struct.unpack_from("<h", raw, i + 14)[0]
            cmds.append({
                "op": 1, "kind": "cels", "offset": i,
                "first": int(first), "last": int(last), "delay": int(delay),
                "var_first": bool(raw[i + 0x12]),
                "var_last": bool(raw[i + 0x13]),
            })
            i += 22
            continue
        if op == 0x15 and i + 16 <= n:
            sid = struct.unpack_from("<I", raw, i + 8)[0]
            rec = (by_id or {}).get(sid)
            name = rec["name"] if rec else str(sid)
            cmds.append({
                "op": 0x15, "kind": "script", "offset": i,
                "script": int(sid), "name": name,
                "sound": "sound" in name.lower(),
            })
            i += 16
            continue
        cmds.append({"op": op, "kind": "unknown", "offset": i})
        break
    return cmds


def write_queue_cels(raw: bytes, offset: int, first, last, delay) -> bytes:
    if offset < 0 or offset + 22 > len(raw):
        raise ValueError("queue command out of range")
    if struct.unpack_from("<H", raw, offset)[0] != 1:
        raise ValueError("not a cel-range command")
    buf = bytearray(raw)
    struct.pack_into("<II", buf, offset + 2, int(first), int(last))
    struct.pack_into("<h", buf, offset + 14, int(delay))
    return bytes(buf)


def write_queue_script(raw: bytes, offset: int, script_id) -> bytes:
    if offset < 0 or offset + 16 > len(raw):
        raise ValueError("queue command out of range")
    if struct.unpack_from("<H", raw, offset)[0] != 0x15:
        raise ValueError("not a script command")
    buf = bytearray(raw)
    struct.pack_into("<I", buf, offset + 8, int(script_id))
    return bytes(buf)


def parse_text(raw: bytes):
    """TEXT is eleven dwords (ui.md §8). Which one is the string id is unknown."""
    if len(raw or b"") < 44:
        return []
    return list(struct.unpack_from("<11I", raw, 0))


def write_text_dwords(raw: bytes, dwords) -> bytes:
    buf = bytearray(raw or b"")
    if len(buf) < 44:
        buf.extend(b"\x00" * (44 - len(buf)))
    for i, value in enumerate(list(dwords or [])[:11]):
        struct.pack_into("<I", buf, i * 4, int(value))
    return bytes(buf)


def parse_script(raw: bytes):
    if len(raw or b"") < 8:
        return []
    return list(struct.unpack_from("<II", raw, 0))


class UIIndex:
    def __init__(self, app):
        self.app = app
        self.by_id = {}
        self.by_name = {}
        self._index()

    def _index(self):
        for a in self.app.db.assets:
            if a.source != "res":
                continue
            try:
                rid = int(a.member)
            except (TypeError, ValueError):
                m = re.match(r"res/(\d+)_", a.key.replace("\\", "/"))
                rid = int(m.group(1)) if m else None
            if rid is None:
                continue
            rec = {"id": rid, "asset": a, "name": a.name, "restype": a.restype,
                   "key": a.key}
            self.by_id[rid] = rec
            self.by_name[a.name.lower()] = rec

    def _raw(self, rec):
        return self.app.read(rec["key"])

    def _follow_bitmap(self, rec):
        """Return (bitmap_rec, w, h, hx, hy) for a SPRITE, CEL, or BITMAP."""
        if rec is None:
            return None
        rt = rec["restype"]
        if rt == "BITMAP":
            hdr = _bmp_header(self._raw(rec))
            if not hdr:
                return None
            w, h, hx, hy = hdr
            return rec, w, h, hx, hy
        if rt == "CEL":
            parsed = _parse_cel(self._raw(rec))
            if not parsed:
                return None
            bmp_id, hx, hy = parsed
            bmp = self.by_id.get(bmp_id)
            if not bmp or bmp["restype"] != "BITMAP":
                return None
            hdr = _bmp_header(self._raw(bmp))
            if not hdr:
                return None
            w, h, bhx, bhy = hdr
            return bmp, w, h, hx if hx else bhx, hy if hy else bhy
        if rt == "SPRITE":
            for ref in _parse_sprite_refs(self._raw(rec)):
                child = self.by_id.get(ref)
                got = self._follow_bitmap(child)
                if got:
                    return got
        return None

    def sprite_cells(self, name):
        """Resource ids in a SPRITE, in UniqueID / paper-doll order."""
        rec = self._lookup(name)
        if rec is None or rec["restype"] != "SPRITE":
            return []
        return _parse_sprite_refs(self._raw(rec))

    def follow_res(self, rid):
        rec = self.by_id.get(rid)
        if rec is None:
            return None
        got = self._follow_bitmap(rec)
        if not got:
            return {"name": rec["name"], "key": rec["key"], "id": rec["id"]}
        bmp = got[0]
        return {
            "name": bmp["name"],
            "key": bmp["key"],
            "id": bmp["id"],
            "source": rec["name"],
        }

    def _lookup(self, name):
        return self.by_name.get(name.lower())

    def _collect(self, spec):
        names = set()
        if spec.get("chrome"):
            names.update(CHROME)
        names.update(spec.get("roots") or ())
        prefixes = tuple(p.lower() for p in (spec.get("prefixes") or ()))
        lo_hi = spec.get("id_range")
        for rec in self.by_id.values():
            if rec["restype"] != "SPRITE":
                continue
            n = rec["name"].lower()
            if prefixes and any(n.startswith(p) for p in prefixes):
                names.add(rec["name"])
            if lo_hi and lo_hi[0] <= rec["id"] <= lo_hi[1] and \
                    rec["restype"] == "SPRITE":
                names.add(rec["name"])
        return names

    def layouts(self):
        return self._json_file("ui/layouts.json")

    def _json_file(self, rel, default=None):
        mod = getattr(self.app, "mod", None)
        if not mod:
            return default if default is not None else {}
        path = Path(mod.root) / rel
        if not path.is_file():
            return default if default is not None else {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default if default is not None else {}

    def _write_json_file(self, rel, data) -> str:
        mod = getattr(self.app, "mod", None)
        if not mod:
            raise ValueError("no mod project")
        path = Path(mod.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        return str(path)

    def save_layouts(self, updates: dict) -> str:
        data = self.layouts()
        for name, rec in (updates or {}).items():
            cur = dict(data.get(name) or {})
            cur.update(rec or {})
            data[name] = cur
        return self._write_json_file("ui/layouts.json", data)

    def actions_overlay(self):
        return self._json_file("ui/actions.json")

    def save_action(self, name, fields) -> str:
        if not name:
            raise ValueError("name required")
        allowed = ("control_id", "type", "flags", "kind", "does", "opens",
                   "opens_sprite", "enabled_when", "queue", "script")
        patch = {}
        for key in allowed:
            if key not in (fields or {}):
                continue
            val = fields[key]
            if key == "control_id":
                if val in (None, "", "none"):
                    patch[key] = None
                else:
                    patch[key] = int(str(val), 0)
            elif key in ("type", "flags"):
                patch[key] = int(str(val), 0) if val not in (None, "") else 0
            else:
                patch[key] = val
        data = self.actions_overlay()
        cur = dict(data.get(name) or {})
        cur.update(patch)
        data[name] = cur
        return self._write_json_file("ui/actions.json", data)

    def infer_action(self, name, queues=None, scripts=None):
        n = (name or "").lower()
        rec = {"source": "inferred", "clickable": False, "kind": "unknown",
               "does": "No documented click. The handler lives in the dialog procedure."}
        if any(p in n for p in ("bkgnd", "backdrop", "bkdrop", "background",
                                "cover", "panel", "frame")):
            rec.update(kind="static", does="Background / chrome. Not a click.")
            return rec
        if "choice" in n:
            rec.update(kind="choice", clickable=True, type=1,
                       does="Conversation (or menu) choice. The script fills the caption.")
            return rec
        if n.endswith("tab") or "_tab_" in n or n.endswith("head") or "_head_" in n:
            rec.update(kind="select", clickable=True, type=5,
                       does="Radio / character tab. Checking it shows this sheet or character.")
            return rec
        if any(p in n for p in ("exit", "return", "cancel", "done", "close")):
            rec.update(kind="close", clickable=True, type=1, does="Close or go back.")
            return rec
        if any(p in n for p in ("prev", "next", "page", "flip")):
            rec.update(kind="select", clickable=True, type=4, does="Page control.")
        if "btn" in n or "button" in n:
            rec.update(kind="select", clickable=True, type=1,
                       does=rec.get("does") if rec.get("clickable") else "Push button.")
        qnames = [q.get("name") for q in (queues or []) if q.get("name")]
        snames = [s.get("name") for s in (scripts or []) if s.get("name")]
        for q in queues or []:
            for cmd in q.get("commands") or []:
                if cmd.get("kind") == "script" and cmd.get("name"):
                    snames.append(cmd["name"])
        if qnames:
            rec.update(kind="play_queue", clickable=True,
                       queue=qnames[0],
                       script=snames[0] if snames else rec.get("script"),
                       does="Plays %s%s." % (
                           qnames[0],
                           (", then " + snames[0]) if snames else ""))
        return rec

    def action_for(self, name, queues=None, scripts=None):
        base = dict(ACTIONS.get(name) or self.infer_action(name, queues, scripts))
        overmap = getattr(self, "_act_over", None)
        if overmap is None:
            overmap = self.actions_overlay()
        over = (overmap or {}).get(name) or {}
        if over:
            base.update(over)
            base["source"] = "overlay"
        if queues and not base.get("queue"):
            base["queue"] = queues[0].get("name")
        if not base.get("script"):
            for q in queues or []:
                for cmd in q.get("commands") or []:
                    if cmd.get("kind") == "script" and cmd.get("name"):
                        base["script"] = cmd["name"]
                        break
        cid = base.get("control_id")
        if isinstance(cid, str) and cid:
            try:
                base["control_id"] = int(cid, 0)
            except ValueError:
                pass
        t = base.get("type")
        base["type_name"] = CTRL_TYPES.get(int(t), "static") if t is not None else (
            "static" if base.get("kind") == "static" else "")
        if base.get("control_id") is not None:
            base["clickable"] = True
        return base

    def _refs(self, rec):
        cells, queues, texts, scripts, other = [], [], [], [], []
        if rec is None or rec["restype"] != "SPRITE":
            return cells, queues, texts, scripts, other
        for i, rid in enumerate(_parse_sprite_refs(self._raw(rec))):
            child = self.by_id.get(rid)
            if child is None:
                other.append({"id": rid, "name": str(rid), "kind": "?",
                              "ref": i})
                continue
            item = {
                "id": rid, "name": child["name"], "kind": child["restype"],
                "key": child["key"], "ref": i,
            }
            rt = child["restype"]
            if rt in ("BITMAP", "CEL"):
                got = self._follow_bitmap(child)
                if got:
                    bmp, w, h, hx, hy = got
                    item.update({
                        "bitmap": bmp["name"], "bitmap_key": bmp["key"],
                        "bitmap_id": bmp["id"], "w": w, "h": h,
                        "hot": [hx, hy],
                    })
                cells.append(item)
            elif rt == "QUEUE":
                item["commands"] = parse_queue(self._raw(child), self.by_id)
                queues.append(item)
            elif rt == "TEXT":
                item["dwords"] = parse_text(self._raw(child))
                texts.append(item)
            elif rt == "SCRIPT":
                item["sound"] = "sound" in child["name"].lower()
                item["words"] = parse_script(self._raw(child))
                scripts.append(item)
            else:
                other.append(item)
        return cells, queues, texts, scripts, other

    def _sounds(self, queues, scripts):
        names = []
        for q in queues or []:
            for cmd in q.get("commands") or []:
                if cmd.get("sound") or "sound" in (cmd.get("name") or "").lower():
                    names.append(cmd.get("name") or "")
        for s in scripts or []:
            if s.get("sound"):
                names.append(s.get("name") or "")
        found = []
        seen = set()
        tokens = set()
        for n in names:
            for part in re.findall(r"[A-Za-z]{3,}", n):
                tokens.add(part.lower())
        for a in self.app.db.assets:
            stem = Path(a.name).stem.lower()
            ext = Path(a.name).suffix.lower()
            if ext not in (".wav", ".mp3") and a.kind != "audio":
                continue
            if tokens and not any(t in stem or stem in t for t in tokens):
                continue
            if a.key in seen:
                continue
            seen.add(a.key)
            found.append({"key": a.key, "name": a.name})
            if len(found) >= 12:
                break
        return {"scripts": [n for n in names if n], "waves": found}

    def _node(self, name, palette, overlay=None, cel=0):
        rec = self._lookup(name)
        if rec is None:
            return None
        over = (overlay or {}).get(name) or {}
        if over.get("cel") is not None:
            cel = over.get("cel")
        cells, queues, texts, scripts, other = self._refs(rec)
        pick = None
        if cells:
            idx = max(0, min(int(cel or 0), len(cells) - 1))
            pick = cells[idx]
            got = None
            if pick.get("bitmap_key"):
                bmp = self.by_id.get(pick.get("bitmap_id"))
                if bmp:
                    got = self._follow_bitmap(bmp if bmp["restype"] == "BITMAP"
                                              else self.by_id.get(pick["id"]))
            if got is None:
                got = self._follow_bitmap(rec)
        else:
            idx = 0
            got = self._follow_bitmap(rec)
        if not got:
            # Still return a node so queues/text-only sprites show up.
            ox = int(over["x"]) if over.get("x") is not None else 8
            oy = int(over["y"]) if over.get("y") is not None else 8
            return {
                "name": rec["name"], "id": rec["id"], "kind": rec["restype"],
                "key": rec["key"], "palette": palette,
                "x": ox, "y": oy, "w": 32, "h": 32, "hot": [0, 0],
                "placed": name in PLACED, "cel": int(cel or 0),
                "cells": cells, "queues": queues, "texts": texts,
                "scripts": scripts, "other": other,
                "sounds": self._sounds(queues, scripts),
                "pos_source": "overlay" if over.get("x") is not None else "placeholder",
                "movable": True,
                "action": self.action_for(rec["name"], queues, scripts),
            }
        bmp, w, h, hx, hy = got
        if over.get("x") is not None and over.get("y") is not None:
            box = (int(over["x"]), int(over["y"]), w, h)
            source = "overlay"
        elif name in PLACED:
            x, y, pw, ph = PLACED[name]
            box = (x, y, w or pw, h or ph)
            source = "authored"
        elif w >= 640 and h >= 400:
            box = (0, 0, w, h)
            source = "fullframe"
        else:
            box = _frame_box(w, h, hx, hy)
            source = "hotspot"
        x, y, bw, bh = box
        if pick:
            bmp_key = pick.get("bitmap_key") or bmp["key"]
            bmp_name = pick.get("bitmap") or bmp["name"]
        else:
            bmp_key, bmp_name = bmp["key"], bmp["name"]
        return {
            "name": rec["name"],
            "id": rec["id"],
            "kind": rec["restype"],
            "key": rec["key"],
            "bitmap_key": bmp_key,
            "bitmap": bmp_name,
            "palette": palette,
            "x": int(x), "y": int(y), "w": int(bw), "h": int(bh),
            "hot": [hx, hy],
            "placed": name in PLACED,
            "pos_source": source,
            "cel": int(over.get("cel") or idx or 0),
            "cells": cells,
            "queues": queues,
            "texts": texts,
            "scripts": scripts,
            "other": other,
            "sounds": self._sounds(queues, scripts),
            "movable": True,
            "action": self.action_for(rec["name"], queues, scripts),
        }

    def list_screens(self):
        out = []
        for spec in SCREENS:
            names = self._collect(spec)
            out.append({
                "id": spec["id"],
                "name": spec["name"],
                "opener": spec.get("opener") or spec.get("palette"),
                "does": spec.get("does") or "",
                "aliases": list(spec.get("aliases") or ()),
                "sprites": len(names),
                "hotspots": [],
            })
        return out

    def screen(self, sid: str, show_all=False):
        spec = next((s for s in SCREENS if s["id"] == sid), None)
        if spec is None:
            raise KeyError(sid)
        palette = spec.get("palette") or "pIntfacePal"
        overlay = self.layouts()
        self._act_over = self.actions_overlay()
        names = self._collect(spec)
        nodes = []
        for name in names:
            node = self._node(name, palette, overlay)
            if node:
                nodes.append(node)
        nodes.sort(key=lambda n: (-(n["w"] * n["h"]), n["name"].lower()))
        limit = None if show_all else spec.get("limit")
        drawn = nodes if not limit else nodes[:limit]
        have = {n["name"] for n in drawn}
        for root in spec.get("roots") or ():
            if root in have:
                continue
            node = self._node(root, palette, overlay)
            if node:
                drawn.insert(0, node)
        texts = []
        queues = []
        buttons = []
        for n in drawn:
            texts.extend(n.get("texts") or [])
            queues.extend(n.get("queues") or [])
            act = n.get("action") or {}
            if act.get("clickable"):
                buttons.append({
                    "name": n["name"],
                    "control_id": act.get("control_id"),
                    "kind": act.get("kind"),
                    "does": act.get("does"),
                    "opens": act.get("opens"),
                    "source": act.get("source"),
                })
        buttons.sort(key=lambda b: (
            b.get("control_id") is None, b.get("control_id") or 0, b["name"]))
        return {
            "id": spec["id"],
            "name": spec["name"],
            "palette": palette,
            "opener": spec.get("opener") or "",
            "proc": spec.get("proc") or "",
            "does": spec.get("does") or "",
            "aliases": list(spec.get("aliases") or ()),
            "kinds": list(ACTION_KINDS),
            "screens": [{"id": s["id"], "name": s["name"]} for s in SCREENS],
            "hotspots": [{"id": n["name"], "x": n["x"], "y": n["y"],
                          "w": n["w"], "h": n["h"], "label": n["name"]}
                         for n in drawn],
            "sprites": drawn,
            "buttons": buttons,
            "texts": texts,
            "queues": queues,
            "note": (
                "Click a control to see what the dialog procedure does with "
                "it. Control ids live in the EXE; the overlay keeps your "
                "notes. QUEUE finish scripts are live game data."
            ),
        }

    def catalog(self, kind="BITMAP", q="", limit=80):
        q = (q or "").lower()
        matches = []
        for rec in self.by_id.values():
            if rec["restype"] != kind:
                continue
            if q and q not in rec["name"].lower() and q not in str(rec["id"]):
                continue
            matches.append(rec)
        matches.sort(key=lambda r: r["name"].lower())
        out = []
        for rec in matches[:int(limit or 80)]:
            item = {"id": rec["id"], "name": rec["name"], "key": rec["key"],
                    "kind": rec["restype"]}
            if kind == "BITMAP":
                hdr = _bmp_header(self._raw(rec))
                if hdr:
                    item["w"], item["h"] = hdr[0], hdr[1]
            out.append(item)
        return out

    def write_raw(self, key, raw: bytes) -> int:
        asset = self.app.db.get(key)
        if asset is None:
            raise KeyError(key)
        if self.app.mod is None:
            raise ValueError("no mod project")
        n = self.app.mod.write_override(
            asset, raw, original=self.app.db.read(key))
        return n

    def replace_ref(self, sprite_key, index, new_id) -> int:
        rec = next((r for r in self.by_id.values() if r["key"] == sprite_key),
                   None)
        if rec is None:
            raise KeyError(sprite_key)
        raw = bytearray(self._raw(rec))
        refs = _parse_sprite_refs(raw)
        if index < 0 or index >= len(refs):
            raise ValueError("ref %d out of %d" % (index, len(refs)))
        struct.pack_into("<I", raw, 0x26 + 4 * int(index), int(new_id))
        return self.write_raw(sprite_key, bytes(raw))

    def replace_cel_bitmap(self, cel_key, bitmap_id) -> int:
        rec = next((r for r in self.by_id.values() if r["key"] == cel_key), None)
        if rec is None or rec["restype"] != "CEL":
            raise KeyError(cel_key)
        raw = bytearray(self._raw(rec))
        if len(raw) < 4:
            raise ValueError("truncated CEL")
        struct.pack_into("<I", raw, 0, int(bitmap_id))
        return self.write_raw(cel_key, bytes(raw))

    def write_hotspot(self, key, hx, hy) -> int:
        rec = next((r for r in self.by_id.values() if r["key"] == key), None)
        if rec is None:
            raise KeyError(key)
        raw = bytearray(self._raw(rec))
        if rec["restype"] == "BITMAP":
            if len(raw) < 20:
                raise ValueError("truncated BITMAP")
            struct.pack_into("<ii", raw, 12, int(hx), int(hy))
        elif rec["restype"] == "CEL":
            if len(raw) < 16:
                raise ValueError("truncated CEL")
            struct.pack_into("<ii", raw, 8, int(hx), int(hy))
        else:
            raise ValueError("hotspot only on BITMAP or CEL")
        return self.write_raw(key, bytes(raw))

    def write_queue(self, key, offset, first=None, last=None, delay=None,
                    script=None) -> int:
        rec = next((r for r in self.by_id.values() if r["key"] == key), None)
        if rec is None or rec["restype"] != "QUEUE":
            raise KeyError(key)
        raw = self._raw(rec)
        op = struct.unpack_from("<H", raw, int(offset))[0] if int(offset) + 2 <= len(raw) else -1
        if script is not None or op == 0x15:
            raw = write_queue_script(raw, int(offset), script if script is not None else 0)
        else:
            raw = write_queue_cels(raw, int(offset), first, last, delay)
        return self.write_raw(key, raw)

    def write_text(self, key, dwords) -> int:
        rec = next((r for r in self.by_id.values() if r["key"] == key), None)
        if rec is None or rec["restype"] != "TEXT":
            raise KeyError(key)
        raw = write_text_dwords(self._raw(rec), dwords)
        return self.write_raw(key, raw)

    def move_sprite(self, name, x=None, y=None, cel=None, write_hot=True):
        """Remember frame position / shown cel and, when asked, bake a hotspot."""
        rec = self._lookup(name)
        updates = {}
        if x is not None:
            updates["x"] = int(x)
        if y is not None:
            updates["y"] = int(y)
        if cel is not None:
            updates["cel"] = int(cel)
        path = self.save_layouts({name: updates}) if updates else None
        wrote = None
        if write_hot and rec is not None and x is not None and y is not None:
            cells, _q, _t, _s, _o = self._refs(rec)
            target = None
            if cells:
                idx = 0
                if cel is not None and 0 <= int(cel) < len(cells):
                    idx = int(cel)
                target = self.by_id.get(cells[idx].get("id"))
            if target is None:
                target = rec
            if target and target["restype"] in ("BITMAP", "CEL"):
                got = self._follow_bitmap(target)
                if got:
                    _bmp, w, h, _hx, _hy = got
                    hx, hy = hotspot_for_box(x, y, w, h)
                    wrote = self.write_hotspot(target["key"], hx, hy)
        return {"layout": path, "hotspot": wrote}
