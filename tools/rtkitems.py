"""MagicInvItem.txt: the live item catalog.

Fourteen engine families, split in the studio into worn gear (weapons,
shields, armor, rings, amulets), magic texts, alchemy, and bag items.
Combat rolls Weapon_Damage and Ready / Use effect values from this
text; the 3D props in Chars.t3d are only the meshes. Edits rewrite the
table and go through the mod override path — the install is not touched.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyro_inflate

CATALOG_KEY = "file/GameData/MagicInvItem.txt"
COLON_AT = 19
QUALITIES = ("Poor", "Average", "Good", "Excellent", "Magical")
QUALITY_POINTS = {
    "Poor": "100", "Average": "200", "Good": "300",
    "Excellent": "400", "Magical": "500",
}
GEAR_SUB = {
    "dagger": "Dagger", "shortsword": "Shortsword", "broadsword": "Broadsword",
    "greatsword": "Greatsword", "rapier": "Rapier", "mace": "Mace",
    "warhammer": "Warhammer", "bow": "Longbow", "axe": "Battleaxe",
    "onehandaxe": "Battleaxe", "club": "Club", "scimitar": "Scimitar",
    "staff": "Quarterstaff", "wand": "Wand",
    "shldwood": "Shield", "shldrun1": "Shield", "shldgold": "Shield",
    "objpotion": "Potion",
}
SLOT_CLASS = {
    "torso": "Torso", "back": "Torso", "arms": "Arms",
    "legs": "Legs", "body": "Torso", "face": "Head",
}
ITEM_SLOTS = ("Pack", "Hand", "Torso", "Arms", "Legs", "Ring", "Neck")
KIND_GROUPS = (
    ("Worn", (
        ("weapon", "Weapons"),
        ("shield", "Shields"),
        ("armor", "Armor"),
        ("ring", "Rings"),
        ("amulet", "Amulets"),
    )),
    ("Magic", (
        ("scroll", "Scrolls"),
        ("wand", "Wands"),
        ("book", "Books"),
        ("recipe", "Recipes"),
    )),
    ("Alchemy", (
        ("potion", "Potions"),
        ("reagent", "Reagents"),
        ("tool", "Brewing tools"),
    )),
    ("Bag", (
        ("money", "Gold & cash gems"),
        ("gem", "Other stones"),
        ("key", "Keys"),
        ("picks", "Lockpicks"),
        ("document", "Documents"),
    )),
)
_KIND_FROM_CAT = {
    "Weapon": "weapon", "Armor": "armor", "Amulet": "amulet",
    "Book": "book", "Document": "document", "Key": "key",
    "Picks": "picks", "Potion": "potion", "Ring": "ring",
    "Scroll": "scroll", "Wand": "wand", "Recipe": "recipe",
}
WORN_KINDS = ("weapon", "shield", "armor", "ring", "amulet")
USE_KINDS = ("potion", "scroll", "wand", "book", "recipe", "amulet")
PREVIEW_KINDS = (
    "weapon", "shield", "armor", "wand", "ring", "amulet", "potion",
)
HOLD_GEAR = {
    "wand": ("wand",),
    "potion": ("objpotion",),
}
SHIELD_GEARS = ("shldwood", "shldrun1", "shldgold")


def shield_gear(item):
    """Which of the three Chars.t3d shield skins this row should wear.

    The meshes are wood / rune / gold (SHIELDWD, SHIELDRN, SHIELDGD).
    Mundane grades share the pine board. Named magical rows pick a
    painted skin; cursed stays on the cheap wood picture.
    """
    blob = " ".join((
        (item or {}).get("Item_Name") or "",
        (item or {}).get("AS_Tag") or "",
        (item or {}).get("UA_Tag") or "",
    )).lower()
    if "cursed" in blob:
        return "shldwood"
    if "agility" in blob:
        return "shldgold"
    if "enchant" in blob:
        return "shldrun1"
    return "shldwood"
DAMAGE_RE = re.compile(r"Rand\(\s*(\d+)\s*-\s*(\d+)\s*\)", re.I)

# Live catalog ids from the name/id table at PTR_s_Arrow_005f2c48.
# FUN_004942db builds the inventory "Users :" line from these.
CATEGORY_IDS = {
    "Weapon": 0, "Armor": 1, "Alchemy": 2, "Amulet": 3, "Book": 4,
    "Document": 5, "Gem": 6, "Key": 7, "Picks": 8, "Potion": 9,
    "Ring": 10, "Scroll": 11, "Wand": 12, "Recipe": 13,
}
SUBCATEGORY_IDS = {
    "Arrow": 0, "Battleaxe": 1, "Broadsword": 2, "Club": 3, "Dagger": 4,
    "Greatsword": 5, "Longbow": 6, "Mace": 7, "Quarterstaff": 8,
    "Rapier": 9, "Scimitar": 10, "Shortsword": 11, "Warhammer": 12,
    "Monster": 13, "Chainmail": 14, "Leather": 15, "Plate": 16,
    "Shield": 17, "Equipment": 18, "Ingredient": 19, "Single_Use": 20,
    "Multi_Use": 21, "Potion": 22, "Oil": 23, "Grease": 24, "Resin": 25,
    "UseByMage": 26, "UseByPriest": 27, "UseByAll": 28, "UseByMagic": 29,
    "LucasKey": 30, "SkullKey": 31, "PetesKey": 32, "YusefKey": 33,
    "SkeletonKey": 34, "SlavePenKey": 35, "NecromancerKey": 36,
    "MagicKey": 37, "Money": 38, "Catalyst": 39,
}
USER_CLASSES = ("Warrior", "Thief", "Priest", "Mage")
PARTY_BY_CLASS = {
    "Warrior": ("William",),
    "Thief": ("James",),
    "Priest": ("Solon",),
    "Mage": ("Jazhara", "Kendaric"),
}
PARTY_ORDER = ("James", "Jazhara", "William", "Kendaric", "Solon")
# Extra class bits on a weapon subcategory. Warrior is always on.
_WEAPON_EXTRA = {
    0: (1,),          # Arrow: Thief
    2: (1,),          # Broadsword
    3: (1, 2),        # Club: Thief, Priest
    4: (1, 3),        # Dagger: Thief, Mage
    6: (1,),          # Longbow
    7: (1, 2),        # Mace
    8: (1, 2, 3),     # Quarterstaff: everyone
    9: (1,),          # Rapier
    10: (1,),         # Scimitar
    11: (1,),         # Shortsword
    12: (2,),         # Warhammer: Priest
}

# Closed item-enchantment table at 0x5f30f0. FUN_004f8407 looks these
# up; an unknown word becomes Modifier_Attack. LearnPotion_* is a Use
# recipe unlock, not a worn bonus, so the gear editor omits it.
ITEM_MODIFIERS = (
    ("Attribute_Strength", "Attributes"),
    ("Attribute_Agility", "Attributes"),
    ("Attribute_Bladed", "Skills"),
    ("Attribute_Bow", "Skills"),
    ("Attribute_Shield", "Skills"),
    ("Attribute_Analyze", "Skills"),
    ("Attribute_Perception", "Skills"),
    ("Attribute_Alchemy", "Skills"),
    ("Modifier_PickLock", "Skills"),
    ("Modifier_DisarmTrap", "Skills"),
    ("Modifier_Attack", "Combat"),
    ("Modifier_MissileAttack", "Combat"),
    ("Modifier_Defense", "Combat"),
    ("Modifier_Armor", "Combat"),
    ("Strikes_Round", "Combat"),
    ("Strikes_LeftFree", "Combat"),
    ("Strikes_WithBladed", "Combat"),
    ("Strikes_WithBow", "Combat"),
    ("Critical_HitChance", "Combat"),
    ("Critical_Immune", "Combat"),
    ("Critical_Cursed", "Combat"),
    ("Weapon_DemonBlade", "Combat"),
    ("Damage_Normal", "Damage"),
    ("Damage_Undead", "Damage"),
    ("Damage_Poison", "Damage"),
    ("Damage_FireNormal", "Damage"),
    ("Damage_FireSpell", "Damage"),
    ("Damage_IgnoreArmor", "Damage"),
    ("Damage_IgnoreMetalic", "Damage"),
    ("Damage_ArmorBlock", "Damage"),
    ("Damage_BlockNormal", "Protection"),
    ("Damage_BlockMissile", "Protection"),
    ("Damage_BlockFireNorm", "Protection"),
    ("Damage_BlockFireSpell", "Protection"),
    ("Damage_BlockLightning", "Protection"),
    ("Immune_Poison", "Protection"),
    ("Immune_Paralysis", "Protection"),
    ("Immune_LightningSpells", "Protection"),
    ("Armor_Enchanted", "Flags"),
    ("Armor_Special", "Flags"),
    ("Armor_ShieldRing", "Flags"),
    ("Attribute_PathFlames", "Magic"),
    ("Attribute_PathMind", "Magic"),
    ("Attribute_PathStorm", "Magic"),
    ("Attribute_PathChange", "Magic"),
    ("Path_FireIncDamage", "Magic"),
    ("Path_ChangeIncLevel", "Magic"),
    ("Magic_CasterLevel", "Magic"),
    ("Magic_GrantSpellPt", "Magic"),
    ("Magic_SpellPtCost", "Magic"),
    ("Magic_ResistMindSpells", "Magic"),
    ("Magic_QuickFlames", "Magic"),
    ("Magic_QuickStorm", "Magic"),
    ("Magic_QuickChange", "Magic"),
    ("Magic_QuickMental", "Magic"),
    ("Health_Grant", "Other"),
    ("Health_AmuletSung", "Other"),
    ("Dispel_Blindness", "Other"),
    ("Dispel_Confusion", "Other"),
    ("Dispel_Stunning", "Other"),
    ("Item_QualityImprove", "Other"),
    ("Item_QualityRestore", "Other"),
    ("Item_QualityUpgrade", "Other"),
    ("Item_QualityMakeExcellent", "Other"),
)
_MOD_BY_NAME = {n: g for n, g in ITEM_MODIFIERS}

# RTKRES inventory icons. UniqueID pairs 152/153 … 190/191 share one
# bitmap (weak and strong). Names are from RTKRES.h after sInventoryItem.
_POTION_PAIR_ICONS = {
    152: "bphealing",
    154: "brepair",
    156: "babjuration",
    158: "bfireoil",
    160: "bbeast",
    162: "bfireshield",
    164: "bpoison",
    166: "bholybalm",
    168: "bmagicblade",
    170: "bquality",
    172: "bmannaboost",
    174: "bmagic",
    176: "bregeneration",
    178: "bstrength",
    180: "bmagicprotection",
    182: "bprotectionundead",
    184: "bprotectionfire",
    186: "bironskin",
    188: "bantidote",
    190: "bstriking",
}
_UID_ICONS = {
    130: "bAquaFortis",
    131: "bAquaRegia",
    132: "bEssentialSaltes",
    133: "bFennel",
    134: "bFireLotus",
    135: "bPowderedOpal",
    136: "bVampireAshes",
    137: "bElixirBloodwine",
    138: "bEssenceErgot",
    139: "bTinctureVitriol",
    140: "bTrueCopper",
    141: "bTrueIron",
    142: "bTrueLead",
    143: "bTrueGold",
    144: "bFlask",
    151: "bz_p01",
    268: "bpoison",
}
_NAME_ICONS = {
    "crucible": "bCrucible",
    "melting pan": "bCrucible",
    "base labratory": "bBaseLab",
    "mortar and pestle": "bBaseLab",
    "distillation chamber": "bStill",
    "infusion bottle": "bInfusion",
    "dissolution mixer": "bDisolition",
    "retrieval aparatus": "bRetrieval",
    "retrieval apparatus": "bRetrieval",
}
INVENTORY_ICON_NAMES = (
    list(_POTION_PAIR_ICONS.values())
    + ["bz_p01"]
    + list(dict.fromkeys(_UID_ICONS.values()))
    + list(dict.fromkeys(_NAME_ICONS.values()))
)


INVENTORY_SPRITE = "sInventoryItem"
UNASSESSED_POTION_CELL = 0x10b
PAPER_DOLL_SLOTS = {
    "amulet": ("Neck",),
    "ring": ("LeftRing", "RightRing"),
}


def item_uid(item):
    try:
        return int(str((item or {}).get("UniqueID") or "").strip())
    except ValueError:
        return None


def paper_doll_cell(uid):
    """FUN_0053e982: UniqueID to a local index on the paper-doll sprite."""
    uid = int(uid)
    if uid < 0x105:
        if uid < 0xfa:
            if uid < 0xcd:
                if uid < 0xc0:
                    if uid < 0x97:
                        if uid < 0x7c:
                            if uid > 0x4b:
                                return uid - 0x4c
                            return uid
                        return uid - 0x7c
                    return uid - 0x97
                return uid - 0xc0
            return uid - 0xcd
        return uid - 0xfa
    return uid - 0x105


def bag_cell(uid, assessed=True):
    """sInventoryItem cell. Unassessed potions share one mystery-flask."""
    uid = int(uid)
    if (not assessed) and ((0x96 < uid < 0xc0) or uid == 0x10c):
        return UNASSESSED_POTION_CELL
    return uid


def resolve_icon(item, ui, assessed=True):
    """Bag bitmap for a catalog row. UniqueID indexes sInventoryItem."""
    if ui is None:
        return None
    uid = item_uid(item)
    if uid is None:
        return None
    cell = bag_cell(uid, assessed=assessed)
    cells = ui.sprite_cells(INVENTORY_SPRITE)
    if cell < 0 or cell >= len(cells):
        return None
    rec = ui.follow_res(cells[cell])
    if rec is None:
        return None
    rec = dict(rec)
    rec["cell"] = cell
    rec["unique_id"] = uid
    return rec


def list_inventory_icons(ui):
    """Every distinct bag bitmap hanging off sInventoryItem."""
    if ui is None:
        return []
    seen = set()
    out = []
    for rid in ui.sprite_cells(INVENTORY_SPRITE):
        rec = ui.follow_res(rid)
        if rec is None or rec["key"] in seen:
            continue
        seen.add(rec["key"])
        out.append({"name": rec["name"], "key": rec["key"], "id": rec["id"]})
    return out


def paper_doll_icons(item, ui, kind, character=None):
    """Inventory paper-doll bitmaps. Rings and amulets only; not 3D meshes."""
    if ui is None:
        return []
    slots = PAPER_DOLL_SLOTS.get(kind) or ()
    uid = item_uid(item)
    if not slots or uid is None:
        return []
    idx = paper_doll_cell(uid)
    chars = (character,) if character else PARTY_ORDER
    out = []
    seen = set()
    for ch in chars:
        for slot in slots:
            rec = None
            cells = ui.sprite_cells("s%s%s" % (ch, slot))
            if 0 <= idx < len(cells):
                rec = ui.follow_res(cells[idx])
            if rec is None or rec["key"] in seen:
                continue
            seen.add(rec["key"])
            out.append({
                "name": rec["name"],
                "key": rec["key"],
                "id": rec["id"],
                "character": ch,
                "slot": slot,
                "cell": idx,
            })
    return out


def icon_name(item):
    """RTKRES bitmap name for an inventory icon, or None."""
    try:
        uid = int(str((item or {}).get("UniqueID") or "").strip())
    except ValueError:
        uid = None
    if uid in _UID_ICONS:
        return _UID_ICONS[uid]
    if uid is not None and 152 <= uid <= 191:
        base = uid if uid % 2 == 0 else uid - 1
        if base in _POTION_PAIR_ICONS:
            return _POTION_PAIR_ICONS[base]
    for key in (
        (item or {}).get("Item_Name"),
        (item or {}).get("AS_Tag"),
        (item or {}).get("UA_Tag"),
    ):
        stem = _NAME_ICONS.get((key or "").strip().lower())
        if stem:
            return stem
    return None


def users_of(item, assessed=True):
    """Who the inventory 'Users :' line lists for this row (FUN_004942db).

    The equip path does not enforce this. Mage here is the LPMage class.
    Unassessed rings, amulets, books, and scrolls hide UseBy* until identified.
    """
    cat = CATEGORY_IDS.get(item.get("Category") or "", -1)
    sub = SUBCATEGORY_IDS.get(item.get("SubCategory") or "", -1)
    flags = [False, False, False, False]

    def useby(default):
        if not assessed:
            return list(default)
        if sub == 26:
            return [False, False, False, True]
        if sub == 27:
            return [False, False, True, False]
        if sub == 29:
            return [False, False, True, True]
        return [True, True, True, True]

    if cat == 0:
        flags[0] = True
        for i in _WEAPON_EXTRA.get(sub, ()):
            flags[i] = True
    elif cat == 1:
        flags[0] = True
        flags[2] = True
        flags[1] = sub == 15
    elif cat in (2, 13, 12):
        flags[3] = True
    elif cat == 3:
        flags = useby([True, True, True, True])
    elif cat in (4, 11):
        flags = useby([False, False, True, True])
    elif cat in (5, 6, 9, 10):
        flags = [True, True, True, True]
    elif cat in (7, 8):
        flags[1] = True
    else:
        flags = [True, True, True, True]

    classes = [USER_CLASSES[i] for i, on in enumerate(flags) if on]
    allowed = set()
    for name in classes:
        allowed.update(PARTY_BY_CLASS[name])
    party = [p for p in PARTY_ORDER if p in allowed]
    return {
        "classes": classes,
        "party": party,
        "all": len(classes) == 4,
    }


def default_modify(name):
    """Value vs Ratio for a new row. Ratio 125 is +25% of the live stat."""
    n = name or ""
    if n.startswith("Attribute_"):
        return "Ratio"
    if n.startswith("Immune_") or n.startswith("Armor_") or n.startswith("Dispel_"):
        return "Value"
    if n.startswith("Damage_Block") or n.startswith("Damage_Ignore"):
        return "Ratio"
    if n in ("Damage_Undead", "Damage_FireNormal", "Damage_FireSpell",
             "Critical_HitChance", "Strikes_Round"):
        return "Ratio"
    return "Value"


def default_mod_value(name, modify=None):
    how = modify or default_modify(name)
    if how == "Ratio":
        return "125"
    if (name or "").startswith(("Armor_", "Immune_", "Critical_Immune",
                                "Strikes_LeftFree", "Dispel_")):
        return "1"
    if name == "Modifier_Attack" or name == "Modifier_Defense":
        return "15"
    if name == "Damage_Normal":
        return "4"
    return "1"


def modifier_catalog():
    """Names the gear editor may put on a Ready block."""
    return [{
        "name": name,
        "group": group,
        "modify": default_modify(name),
        "value": default_mod_value(name),
    } for name, group in ITEM_MODIFIERS]


def _effect_named(effects, name):
    want = (name or "").strip()
    for e in effects or []:
        if (e.get("name") or "").strip() == want:
            return e
    return None


def _inflate(raw: bytes) -> str:
    if raw.startswith(pyro_inflate.SIG):
        return pyro_inflate.inflate(raw).decode("latin-1")
    return raw.decode("latin-1", "replace")


def _fmt(key, value, indent=0):
    pad = "  " * indent
    return pad + key.ljust(COLON_AT - len(pad)) + ": " + str(value)


def _split_kv(line):
    if ":" not in line:
        return None
    left, right = line.split(":", 1)
    indent = len(line) - len(line.lstrip())
    return indent, left.strip(), right.strip()


class ItemCatalog:
    """In-memory MagicInvItem.txt with field-level rewrite."""

    def __init__(self, header, items):
        self.header = header
        self.items = items
        self.by_name = {it["Item_Name"]: it for it in items}

    @classmethod
    def load(cls, raw: bytes):
        text = _inflate(raw)
        lines = text.splitlines()
        header = []
        items = []
        block = []
        for line in lines:
            if not block and not line.strip().startswith("Item_Name"):
                header.append(line)
                continue
            block.append(line)
            if line.strip().startswith("End_Item"):
                items.append(_item_from_lines(block))
                block = []
        if block:
            items.append(_item_from_lines(block))
        return cls(header, items)

    def kind_of(self, item):
        if item.get("SubCategory") == "Shield":
            return "shield"
        cat = item.get("Category") or ""
        sub = item.get("SubCategory") or ""
        if cat == "Alchemy":
            return "tool" if sub == "Equipment" else "reagent"
        if cat == "Gem":
            return "money" if sub == "Money" else "gem"
        return _KIND_FROM_CAT.get(cat, cat.lower() or "other")

    def kind_groups(self):
        counts = {}
        for it in self.items:
            k = self.kind_of(it)
            counts[k] = counts.get(k, 0) + 1
        groups = []
        for title, items in KIND_GROUPS:
            groups.append({
                "label": title,
                "kinds": [{"id": kid, "label": lab, "count": counts.get(kid, 0)}
                          for kid, lab in items],
            })
        return groups

    def list(self, kind=None, q="", sub=None, classification=None):
        q = (q or "").lower()
        out = []
        for it in self.items:
            k = self.kind_of(it)
            if kind and k != kind:
                continue
            if sub and it.get("SubCategory") != sub:
                continue
            if classification and it.get("Classification") != classification:
                continue
            label = it.get("AS_Tag") or it.get("UA_Tag") or it["Item_Name"]
            blob = " ".join((
                it["Item_Name"], label, it.get("UA_Tag") or "",
                it.get("SubCategory") or "", it.get("Quality_Original") or "",
            )).lower()
            if q and q not in blob:
                continue
            out.append(self.summary(it))
        return out

    def summary(self, it):
        dmg = it.get("Weapon_Damage") or ""
        m = DAMAGE_RE.search(dmg)
        return {
            "name": it["Item_Name"],
            "label": it.get("AS_Tag") or it.get("UA_Tag") or it["Item_Name"],
            "kind": self.kind_of(it),
            "category": it.get("Category") or "",
            "subcategory": it.get("SubCategory") or "",
            "classification": it.get("Classification") or "",
            "quality": it.get("Quality_Original") or "",
            "price": it.get("Price") or "",
            "encumbrance": it.get("Encumbrance") or "",
            "damage": dmg,
            "damage_min": int(m.group(1)) if m else None,
            "damage_max": int(m.group(2)) if m else None,
            "active": it.get("Location_Active") or "",
            "preview": self.preview_of(it),
        }

    def preview_of(self, it):
        """Which 3D prop / armor slot to hang on a character for this row."""
        kind = self.kind_of(it)
        sub = it.get("SubCategory") or ""
        gears = []
        for stem, mapped in GEAR_SUB.items():
            if mapped == sub and stem not in gears:
                gears.append(stem)
        rec = {
            "kind": kind,
            "gear": "",
            "gears": [],
            "slot": "",
            "slots": [],
        }
        if kind == "weapon":
            rec["gears"] = [g for g in gears if not g.startswith("shld")]
            rec["gear"] = rec["gears"][0] if rec["gears"] else ""
        elif kind == "shield":
            rec["gears"] = list(gears) or list(SHIELD_GEARS)
            rec["gear"] = shield_gear(it)
            if rec["gear"] not in rec["gears"]:
                rec["gears"] = [rec["gear"]] + list(rec["gears"])
        elif kind == "armor":
            clas = it.get("Classification") or ""
            rec["slots"] = [s for s, c in SLOT_CLASS.items() if c == clas]
            rec["slot"] = rec["slots"][0] if rec["slots"] else ""
        elif kind in HOLD_GEAR:
            rec["gears"] = list(HOLD_GEAR[kind])
            rec["gear"] = rec["gears"][0]
            rec["hold"] = True
        elif kind in PAPER_DOLL_SLOTS:
            rec["paper_doll"] = True
        return rec

    def detail(self, name, ui=None, character=None):
        it = self.by_name.get(name)
        if it is None:
            raise KeyError(name)
        rec = self.summary(it)
        rec["ua_tag"] = it.get("UA_Tag") or ""
        rec["as_tag"] = it.get("AS_Tag") or ""
        rec["description"] = "\n".join(it.get("Description") or [])
        rec["stored"] = it.get("Location_Stored") or ""
        rec["quality_points"] = it.get("Quality_Points") or ""
        rec["unique_id"] = it.get("UniqueID") or ""
        rec["effects"] = list(it.get("effects") or [])
        rec["ready"] = _effect_named(rec["effects"], "Ready")
        rec["use"] = _effect_named(rec["effects"], "Use")
        rec["has_use"] = rec["use"] is not None
        rec["aggregate"] = str(it.get("Aggregate") or "").lower() in (
            "true", "1", "yes")
        rec["qualities"] = list(QUALITIES)
        rec["slots"] = list(ITEM_SLOTS)
        rec["users"] = users_of(it)
        rec["modifiers"] = modifier_catalog()
        rec["icon"] = resolve_icon(it, ui) if ui is not None else (
            {"name": icon_name(it)} if icon_name(it) else None)
        rec["paper_doll"] = paper_doll_icons(
            it, ui, rec["kind"]) if ui is not None else []
        rec["preview_3d"] = rec["kind"] in PREVIEW_KINDS or bool(
            (rec.get("preview") or {}).get("gears"))
        rec["edit_ready"] = rec["kind"] in WORN_KINDS or rec["ready"] is not None
        rec["edit_use"] = rec["kind"] in USE_KINDS or rec["has_use"]
        return rec

    def icon_sheets(self, name, ui, character=None):
        """Creator sheets: bag icon, then paper-doll jewelry if any."""
        rec = self.detail(name, ui=ui, character=None)
        sheets = []
        seen = set()
        icon = rec.get("icon") or {}
        if icon.get("key") and icon["key"] not in seen:
            seen.add(icon["key"])
            sheets.append({
                "key": icon["key"],
                "name": "bag: " + icon["name"],
                "slot": "bag",
                "region": "item",
            })
        for doll in rec.get("paper_doll") or []:
            if doll["key"] in seen:
                continue
            seen.add(doll["key"])
            sheets.append({
                "key": doll["key"],
                "name": "%s %s" % (doll["character"], doll["slot"]),
                "slot": "doll",
                "region": "item",
            })
        return sheets

    def match_gear(self, stem):
        sub = GEAR_SUB.get((stem or "").lower())
        if not sub:
            return []
        return self.list(sub=sub)

    def match_slot(self, slot):
        clas = SLOT_CLASS.get(slot)
        if not clas:
            return []
        return self.list(kind="armor", classification=clas)

    def apply(self, name, fields=None, effects=None, effect_fields=None,
              ready_effect=None, use_effect=None):
        """Rewrite one row. Returns the full catalog text."""
        it = self.by_name.get(name)
        if it is None:
            raise KeyError(name)
        lines = list(it["lines"])
        fields = dict(fields or {})
        if "Weapon_Damage_min" in fields or "Weapon_Damage_max" in fields:
            cur = DAMAGE_RE.search(it.get("Weapon_Damage") or "") 
            lo = fields.pop("Weapon_Damage_min", cur.group(1) if cur else "1")
            hi = fields.pop("Weapon_Damage_max", cur.group(2) if cur else "2")
            fields["Weapon_Damage"] = "Rand(%s-%s)" % (int(lo), int(hi))
        if fields.get("Quality_Original") in QUALITY_POINTS:
            fields.setdefault("Quality_Points",
                              QUALITY_POINTS[fields["Quality_Original"]])
        agg = fields.pop("Aggregate", None)
        if "Description" in fields:
            desc = fields.pop("Description")
            if isinstance(desc, str):
                desc = [ln for ln in desc.replace("\r\n", "\n").split("\n") if ln]
            lines = _replace_descriptions(lines, desc)
        for key, val in fields.items():
            if val is None:
                continue
            lines = _replace_field(lines, key, val)
        if agg is not None:
            if str(agg).lower() in ("1", "true", "yes"):
                lines = _replace_field(lines, "Aggregate", "True")
            else:
                lines = _remove_field(lines, "Aggregate")
        if ready_effect is not None:
            lines = _replace_named_effect(lines, "Ready", ready_effect)
        elif effects:
            lines = _replace_effect_values(lines, effects)
        if use_effect is not None:
            lines = _replace_named_effect(lines, "Use", use_effect)
        if effect_fields:
            lines = _replace_effect_fields(lines, effect_fields)
        fresh = _item_from_lines(lines)
        it.update(fresh)
        it["effects"] = fresh["effects"]
        it["Description"] = fresh["Description"]
        it["lines"] = fresh["lines"]
        return self.to_text()

    def to_text(self):
        parts = list(self.header)
        if parts and parts[-1] != "":
            pass
        for it in self.items:
            parts.extend(it["lines"])
        text = "\n".join(parts)
        if not text.endswith("\n"):
            text += "\n"
        return text


def _item_from_lines(lines):
    fields = {}
    desc = []
    effects = []
    effect = None
    modifier = None
    name = ""
    for line in lines:
        kv = _split_kv(line)
        if kv is None:
            continue
        indent, key, val = kv
        if key == "Item_Name":
            name = val
            fields[key] = val
        elif key == "Description":
            desc.append(val)
        elif key == "Effect":
            effect = {"name": val, "modifiers": []}
            modifier = None
        elif key == "End_Effect":
            if effect:
                effects.append(effect)
            effect = None
            modifier = None
        elif key == "Effect_Modifier":
            modifier = {"name": val, "modify": "", "value": ""}
            if effect is not None:
                effect["modifiers"].append(modifier)
        elif key == "End_Modifier":
            modifier = None
        elif key == "Effect_Desc" and effect is not None:
            effect.setdefault("descs", []).append(val)
            effect["desc"] = "\n".join(effect["descs"])
        elif key == "Effect_Value" and modifier is not None:
            modifier["value"] = val
        elif key == "Effect_Modify" and modifier is not None:
            modifier["modify"] = val
        elif key == "Effect_CastLimit" and effect is not None:
            effect["cast_limit"] = val
        elif key == "Effect_CastMax" and effect is not None:
            effect["cast_max"] = val
        elif key == "Effect_Spell" and effect is not None:
            effect["spell"] = val
        elif key == "Effect_NonCombat" and effect is not None:
            effect["noncombat"] = val
        elif key == "Effect_Magic" and effect is not None:
            effect["magic"] = val
        elif indent == 0 and key not in ("End_Item",):
            fields[key] = val
    rec = dict(fields)
    rec["Item_Name"] = name
    rec["Description"] = desc
    rec["effects"] = effects
    rec["lines"] = list(lines)
    return rec


def _replace_field(lines, key, value):
    out = []
    found = False
    for line in lines:
        kv = _split_kv(line)
        if kv and kv[0] == 0 and kv[1] == key and not found:
            out.append(_fmt(key, value, 0))
            found = True
            continue
        out.append(line)
    if not found:
        end = next((i for i, ln in enumerate(out)
                    if ln.strip().startswith("End_Item")), len(out))
        out.insert(end, _fmt(key, value, 0))
    return out


def _replace_descriptions(lines, paragraphs):
    out = []
    skipped = False
    inserted = False
    for line in lines:
        kv = _split_kv(line)
        if kv and kv[1] == "Description":
            if not skipped:
                skipped = True
            continue
        if skipped and not inserted:
            for para in paragraphs:
                out.append(_fmt("Description", para, 0))
            inserted = True
        out.append(line)
    if not inserted:
        end = next((i for i, ln in enumerate(out)
                    if ln.strip().startswith("End_Item")), len(out))
        block = [_fmt("Description", para, 0) for para in paragraphs]
        out[end:end] = block
    return out


def _replace_effect_fields(lines, updates):
    """Replace Effect_* keys inside the first Effect block."""
    updates = {k: v for k, v in (updates or {}).items() if k and v is not None}
    if not updates:
        return lines
    out = []
    in_effect = False
    found = {k: False for k in updates}
    for line in lines:
        kv = _split_kv(line)
        if kv and kv[1] == "Effect" and not in_effect:
            in_effect = True
            out.append(line)
            continue
        if kv and kv[1] == "End_Effect" and in_effect:
            for key, val in updates.items():
                if not found[key]:
                    out.append(_fmt(key, val, 1))
            in_effect = False
            out.append(line)
            continue
        if in_effect and kv and kv[1] in updates:
            indent = kv[0] // 2 if kv[0] else 1
            out.append(_fmt(kv[1], updates[kv[1]], indent))
            found[kv[1]] = True
            continue
        out.append(line)
    return out


def _named_effect_block(kind, effect):
    kind = (kind or "Ready").strip() or "Ready"
    mods = []
    for m in (effect or {}).get("modifiers") or []:
        name = (m.get("name") or "").strip()
        if not name:
            continue
        mods.append({
            "name": name,
            "modify": (m.get("modify") or default_modify(name)).strip() or "Value",
            "value": "" if m.get("value") is None else str(m.get("value")),
        })
    spell = ((effect or {}).get("spell") or "").strip()
    if kind == "Ready" and not mods:
        return []
    if kind != "Ready" and not mods and not spell:
        return []
    desc = (effect or {}).get("desc")
    if isinstance(desc, str):
        paras = [ln for ln in desc.replace("\r\n", "\n").split("\n") if ln.strip()]
    else:
        paras = [str(x) for x in (desc or []) if str(x).strip()]
    if not paras:
        bits = []
        if spell:
            bits.append(spell)
        for m in mods:
            bits.append("%s %s %s" % (m["name"], m["modify"], m["value"]))
        paras = ["; ".join(bits)] if bits else [kind]
    out = [_fmt("Effect", kind, 0)]
    for para in paras:
        out.append(_fmt("Effect_Desc", para, 1))
    magic = ((effect or {}).get("magic") or "").strip()
    if spell:
        out.append(_fmt("Effect_Magic", magic or "CastOnUse", 1))
        out.append(_fmt("Effect_Spell", spell, 2))
        out.append(_fmt("End_Magic", "End", 1))
    for m in mods:
        out.append(_fmt("Effect_Modifier", m["name"], 1))
        out.append(_fmt("Effect_Modify", m["modify"], 2))
        out.append(_fmt("Effect_Value", m["value"] if m["value"] != "" else "0", 2))
        out.append(_fmt("End_Modifier", "End", 1))
    if kind == "Ready":
        limit = (effect or {}).get("cast_limit") or "Unlimited"
        cmax = (effect or {}).get("cast_max") or "-1"
    else:
        limit = (effect or {}).get("cast_limit") or ("Unlimited" if not spell else "Limited")
        cmax = (effect or {}).get("cast_max")
        if cmax in (None, ""):
            cmax = "1" if spell else "-1"
    out.append(_fmt("Effect_CastLimit", limit, 1))
    out.append(_fmt("Effect_CastMax", cmax, 1))
    nc = (effect or {}).get("noncombat")
    if nc not in (None, ""):
        out.append(_fmt("Effect_NonCombat", nc, 1))
    out.append(_fmt("End_Effect", "End", 0))
    return out


def _replace_named_effect(lines, kind, effect):
    """Replace or insert one Effect block by name (Ready / Use)."""
    kind = (kind or "Ready").strip() or "Ready"
    block = _named_effect_block(kind, effect)
    start = end = None
    for i, line in enumerate(lines):
        kv = _split_kv(line)
        if kv and kv[1] == "Effect" and kv[2].strip() == kind:
            start = i
            for j in range(i + 1, len(lines)):
                kv2 = _split_kv(lines[j])
                if kv2 and kv2[1] == "End_Effect":
                    end = j
                    break
            break
    if start is not None and end is not None:
        return lines[:start] + block + lines[end + 1:]
    if not block:
        return lines
    end_item = next((i for i, ln in enumerate(lines)
                     if ln.strip().startswith("End_Item")), len(lines))
    return lines[:end_item] + block + lines[end_item:]


def _replace_ready_effect(lines, effect):
    return _replace_named_effect(lines, "Ready", effect)


def _remove_field(lines, key):
    out = []
    skipped = False
    for line in lines:
        kv = _split_kv(line)
        if kv and kv[0] == 0 and kv[1] == key and not skipped:
            skipped = True
            continue
        out.append(line)
    return out


def _replace_effect_values(lines, updates):
    """updates: [{modifier, value}] or [{index, value}]."""
    by_name = {u.get("modifier"): u for u in updates if u.get("modifier")}
    out = []
    current = None
    for line in lines:
        kv = _split_kv(line)
        if kv and kv[1] == "Effect_Modifier":
            current = kv[2]
        elif kv and kv[1] == "End_Modifier":
            current = None
        elif kv and kv[1] == "Effect_Value" and current and current in by_name:
            indent = kv[0] // 2
            out.append(_fmt("Effect_Value", by_name[current]["value"], indent))
            continue
        elif kv and kv[1] == "Effect_Desc" and updates:
            desc = next((u.get("desc") for u in updates if u.get("desc")), None)
            if desc:
                out.append(_fmt("Effect_Desc", desc, kv[0] // 2))
                continue
        out.append(line)
    return out
