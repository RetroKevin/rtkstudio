"""Alchemy bench, the forty ROM formulas, and potion catalog links.

The formula table at 0x612e28 is in the exe — this module documents it
and edits the authored catalog (`MagicInvItem.txt`) plus the spell
record a potion points at. Brew math is FUN_00556840.
"""

from __future__ import annotations

import re

import rtkitems

REAGENTS = [
    {"slot": 0, "name": "Essential Saltes", "unique_id": 132, "tool": "Dissolution Mixer",
     "price": 4, "weight": 0.05, "role": "Every formula"},
    {"slot": 1, "name": "Aqua Fortis", "unique_id": 130, "tool": "Infusion Bottle",
     "price": 15, "weight": 0.25, "role": "Weak aqua"},
    {"slot": 2, "name": "Aqua Regia", "unique_id": 131, "tool": "Infusion Bottle",
     "price": 45, "weight": 0.5, "role": "Strong aqua"},
    {"slot": 3, "name": "Powdered Fennel", "unique_id": 133, "tool": "Mortar and Pestle",
     "price": 2, "weight": 0.05, "role": "Powders"},
    {"slot": 4, "name": "Fire Lotus Dust", "unique_id": 134, "tool": "Mortar and Pestle",
     "price": 25, "weight": 0.05, "role": "Powders"},
    {"slot": 5, "name": "Vampire Ashes", "unique_id": 136, "tool": "Mortar and Pestle",
     "price": 150, "weight": 0.05, "role": "Powders"},
    {"slot": 6, "name": "Powdered Opal", "unique_id": 135, "tool": "Mortar and Pestle",
     "price": 75, "weight": 0.05, "role": "Powders"},
    {"slot": 7, "name": "Elixir of Bloodwine", "unique_id": 137, "tool": "Distillation Chamber",
     "price": 8, "weight": 0.5, "role": "Liquids"},
    {"slot": 8, "name": "Essence of Ergot", "unique_id": 138, "tool": "Distillation Chamber",
     "price": 15, "weight": 0.5, "role": "Liquids"},
    {"slot": 9, "name": "Tincture of Vitriol", "unique_id": 139, "tool": "Distillation Chamber",
     "price": 75, "weight": 0.5, "role": "Liquids"},
    {"slot": 10, "name": "True Copper", "unique_id": 140, "tool": "Crucible",
     "price": 85, "weight": 0.1, "role": "Metals"},
    {"slot": 11, "name": "True Lead", "unique_id": 142, "tool": "Crucible",
     "price": 25, "weight": 0.1, "role": "Metals"},
    {"slot": 12, "name": "True Gold", "unique_id": 143, "tool": "Crucible",
     "price": 245, "weight": 0.1, "role": "Metals"},
    {"slot": 13, "name": "True Iron", "unique_id": 141, "tool": "Crucible",
     "price": 40, "weight": 0.1, "role": "Metals"},
]

TOOLS = [
    {"name": "Crucible", "catalog": "Melting Pan", "price": 125, "weight": 5},
    {"name": "Dissolution Mixer", "catalog": "Dissolution Mixer", "price": 125, "weight": 6},
    {"name": "Distillation Chamber", "catalog": "Distillation Chamber", "price": 150, "weight": 4},
    {"name": "Infusion Bottle", "catalog": "Infusion Bottle", "price": 150, "weight": 2},
    {"name": "Mortar and Pestle", "catalog": "Base Labratory", "price": 275, "weight": 4},
    {"name": "Retrieval Apparatus", "catalog": "Retrieval Aparatus", "price": 350, "weight": 3},
]

# alchemy.md §5 — slot numbers from §3. Empty is omitted.
# Order: Saltes, aqua, then the rest.
FORMULAS = [
    (0, "Weak Potion of Healing", 1, 150, [0, 1, 3, 7]),
    (1, "Strong Potion of Healing", 3, 300, [0, 2, 3, 7]),
    (2, "Resin of Repair", 1, 240, [0, 1, 3, 10]),
    (3, "Resin of Total Repair", 3, 450, [0, 2, 3, 10]),
    (4, "Weak Potion of Abjuration", 3, 105, [0, 1, 3, 8]),
    (5, "Strong Potion of Abjuration", 4, 410, [0, 2, 3, 8]),
    (6, "Fire Oil", 3, 345, [0, 1, 4, 9, 10]),
    (7, "Strong Fire Oil", 5, 515, [0, 2, 4, 9, 10]),
    (8, "Weak Potion of the Beast", 3, 540, [0, 1, 6, 7, 11]),
    (9, "Strong Potion of the Beast", 5, 1140, [0, 2, 6, 7, 11]),
    (10, "Weak Lightning Shield", 2, 300, [0, 1, 4, 7, 13]),
    (11, "Strong Lightning Shield", 4, 600, [0, 2, 4, 7, 13]),
    (12, "Grease of Poison", 1, 225, [0, 1, 7, 11]),
    (13, "Grease of Deadly Poison", 3, 375, [0, 2, 7, 11]),
    (14, "Holy Balm, weak", 1, 275, [0, 1, 5, 9]),
    (15, "Holy Balm, strong", 3, 510, [0, 2, 5, 9]),
    (16, "Magical Blade Grease", 2, 465, [0, 1, 8, 10]),
    (17, "Enchanted Blade Grease", 4, 1200, [0, 2, 8, 10]),
    (18, "Resin of Quality", 3, 2250, [0, 1, 6, 10]),
    (19, "Resin of Maximum Quality", 5, 3800, [0, 2, 6, 10]),
    (20, "Potion of Spellcasting", 3, 690, [0, 1, 8, 12]),
    (21, "Great Potion of Spellcasting", 5, 1800, [0, 2, 8, 12]),
    (22, "Weak Potion of Magic", 3, 1500, [0, 1, 6, 8, 12]),
    (23, "Strong Potion of Magic", 5, 3000, [0, 2, 6, 8, 12]),
    (24, "Weak Potion of Regeneration", 2, 450, [0, 1, 3, 7, 12]),
    (25, "Strong Potion of Regeneration", 4, 1200, [0, 2, 3, 7, 12]),
    (26, "Potion of Strength", 2, 432, [0, 1, 7, 12]),
    (27, "Potion of Might", 3, 1025, [0, 2, 7, 12]),
    (28, "Weak Protection from Magic", 1, 345, [0, 1, 8, 13]),
    (29, "Strong Protection from Magic", 3, 825, [0, 2, 8, 13]),
    (30, "Weak Protection from Undead", 1, 240, [0, 1, 5, 13]),
    (31, "Strong Protection from Undead", 3, 345, [0, 2, 5, 13]),
    (32, "Weak Protection from Fire", 2, 285, [0, 1, 4, 13]),
    (33, "Strong Protection from Fire", 4, 630, [0, 2, 4, 13]),
    (34, "Weak Iron Skin", 2, 430, [0, 1, 9, 13]),
    (35, "Strong Iron Skin", 4, 1200, [0, 2, 9, 13]),
    (36, "Poison Antidote", 1, 150, [0, 1, 3, 7, 11]),
    (37, "Strong Antidote", 3, 375, [0, 2, 3, 7, 11]),
    (38, "Weak Potion of Striking", 2, 525, [0, 1, 9, 12]),
    (39, "Strong Potion of Striking", 4, 1050, [0, 2, 9, 12]),
]

STARTERS = {0, 32, 36}  # FUN_0054e02f

# alchemy.md §4 — disaster table, second roll 1–100
DISASTER = [
    (1, 7, ["Mortar and Pestle"]),
    (8, 15, ["Infusion Bottle"]),
    (16, 23, ["Crucible"]),
    (24, 31, ["Retrieval Apparatus"]),
    (32, 39, ["Distillation Chamber"]),
    (40, 43, ["Mortar and Pestle", "Infusion Bottle"]),
    (44, 47, ["Mortar and Pestle", "Crucible"]),
    (48, 51, ["Mortar and Pestle", "Retrieval Apparatus"]),
    (52, 55, ["Mortar and Pestle", "Distillation Chamber"]),
    (56, 59, ["Infusion Bottle", "Crucible"]),
    (60, 63, ["Infusion Bottle", "Retrieval Apparatus"]),
    (64, 67, ["Infusion Bottle", "Distillation Chamber"]),
    (68, 71, ["Crucible", "Retrieval Apparatus"]),
    (72, 75, ["Crucible", "Distillation Chamber"]),
    (76, 79, ["Retrieval Apparatus", "Distillation Chamber"]),
    (80, 81, ["Mortar and Pestle", "Infusion Bottle", "Crucible"]),
    (82, 83, ["Mortar and Pestle", "Infusion Bottle", "Retrieval Apparatus"]),
    (84, 85, ["Mortar and Pestle", "Infusion Bottle", "Distillation Chamber"]),
    (86, 87, ["Mortar and Pestle", "Crucible", "Retrieval Apparatus"]),
    (88, 89, ["Mortar and Pestle", "Crucible", "Distillation Chamber"]),
    (90, 91, ["Mortar and Pestle", "Retrieval Apparatus", "Distillation Chamber"]),
    (92, 93, ["Infusion Bottle", "Crucible", "Retrieval Apparatus"]),
    (94, 95, ["Infusion Bottle", "Crucible", "Distillation Chamber"]),
    (96, 97, ["Infusion Bottle", "Retrieval Apparatus", "Distillation Chamber"]),
    (98, 99, ["Crucible", "Retrieval Apparatus", "Distillation Chamber"]),
    (100, 100, ["Mortar and Pestle", "Infusion Bottle", "Crucible",
                "Retrieval Apparatus", "Distillation Chamber", "Dissolution Mixer"]),
]

STATES = {
    0: "Unknown — page skipped",
    1: "Recipe / starter — no roll",
    2: "Discovered on the blank page — roll, disaster 0.1",
    3: "Blank experiment page — roll, disaster 0.2",
}

SLOT_BY_ID = {r["slot"]: r for r in REAGENTS}


def brew_odds(skill: int, state: int, ring=0):
    """FUN_00556840. skill is the sheet value (+ ring if applied)."""
    skill = int(skill) + int(ring or 0)
    if state == 1:
        return {
            "skill": skill, "state": state, "weight": 0,
            "success": "always (state 1 skips the roll)",
            "plain_fail": "never", "disaster": "never",
            "note": "Level and ingredients still have to pass.",
        }
    weight = 0.2 if state == 3 else 0.1
    if skill >= 101:
        return {
            "skill": skill, "state": state, "weight": weight,
            "success": "1–101 (skill ≥ 101)",
            "plain_fail": "never", "disaster": "never",
        }
    success = max(0, min(101, skill))
    margin = 100 - skill
    cut = int(margin * weight)  # toward zero
    disaster_from = 100 - cut
    plain_hi = disaster_from - 1
    return {
        "skill": skill, "state": state, "weight": weight,
            "success": "1-%d" % success if success else "none",
            "plain_fail": ("%d-%d" % (success + 1, plain_hi)) if plain_hi > success else "none",
            "disaster": "%d-101" % disaster_from,
            "cut": cut,
            "note": "Uniform 1-101. 101 always misses a skill of 100.",
    }


def disaster_for(roll: int):
    for lo, hi, tools in DISASTER:
        if lo <= roll <= hi:
            return {"roll": roll, "tools": tools}
    return {"roll": roll, "tools": []}


def _norm(s):
    return "".join(c for c in (s or "").lower() if c.isalnum())


_STOP = {"of", "the", "a", "an", "for", "and"}


def _tokens(s):
    return frozenset(
        t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in _STOP
    )


class AlchemyIndex:
    def __init__(self, app):
        self.app = app

    def _catalog(self):
        return self.app.items

    def _match_item(self, label):
        cat = self._catalog()
        want = _norm(label)
        want_tok = _tokens(label)
        best = None
        best_score = 0
        for it in cat.items:
            names = (it.get("AS_Tag"), it.get("Item_Name"), it.get("UA_Tag"))
            for n in names:
                if _norm(n) == want:
                    return it
            for n in names:
                if not n:
                    continue
                score = 0
                have = _tokens(n)
                if want_tok and have:
                    if want_tok == have:
                        return it
                    score = len(want_tok & have) / len(want_tok | have)
                if want in _norm(n) or _norm(n) in want:
                    score = max(score, 0.72)
                if score > best_score:
                    best, best_score = it, score
        return best if best_score >= 0.7 else None

    def _item_brief(self, it):
        if not it:
            return None
        spell = None
        for line in it.get("lines") or []:
            if "Effect_Spell" in line and ":" in line:
                spell = line.split(":", 1)[1].strip()
                break
        magic = None
        try:
            magic = self.app.fx.find_spell_name(spell)
        except Exception:
            magic = None
        use = next((e for e in (it.get("effects") or [])
                    if (e.get("name") or "").lower() == "use"), None)
        use = use or ((it.get("effects") or [None])[0])
        return {
            "name": it.get("Item_Name"),
            "label": it.get("AS_Tag") or it.get("Item_Name"),
            "unique_id": (it.get("UniqueID") or "").strip(),
            "price": it.get("Price"),
            "category": it.get("Category"),
            "classification": it.get("Classification"),
            "effect_spell": spell or (use or {}).get("spell"),
            "magic_result": magic,
            "behavior": self._spell_behavior(magic),
            "effect_desc": (use or {}).get("desc") or "",
            "effect_noncombat": (use or {}).get("noncombat") or "",
            "effect_cast_max": (use or {}).get("cast_max") or "",
            "effect_magic": (use or {}).get("magic") or "",
            "effect_summary": self._spell_summary(magic),
            "effects": list(it.get("effects") or []),
            "icon": self._icon(it),
        }

    def _icon(self, it):
        rec = rtkitems.resolve_icon(it, self.app.ui)
        if rec:
            return rec
        name = rtkitems.icon_name(it)
        if not name:
            return None
        hit = self.app.ui.by_name.get(name.lower())
        if hit is None:
            return None
        return {"name": hit["name"], "key": hit["key"], "id": hit["id"]}

    def list_icons(self):
        seen = set()
        out = []
        for name in rtkitems.INVENTORY_ICON_NAMES:
            rec = self.app.ui.by_name.get(name.lower())
            if rec is None or rec["key"] in seen:
                continue
            seen.add(rec["key"])
            out.append({"name": rec["name"], "key": rec["key"], "id": rec["id"]})
        return out

    def _spell_behavior(self, spell_name):
        if not spell_name:
            return ""
        try:
            rec = next((s for s in self.app.fx.spells
                        if s.get("name") == spell_name), None)
        except Exception:
            return ""
        return (rec or {}).get("behavior") or ""

    def _spell_summary(self, spell_name):
        if not spell_name:
            return ""
        try:
            rec = next((s for s in self.app.fx.spells
                        if s.get("name") == spell_name), None)
        except Exception:
            return ""
        bits = []
        for eff in (rec or {}).get("effects") or []:
            t = (eff.get("Effect_AttrType") or "").strip()
            v = (eff.get("Effect_AttrValue") or "").strip()
            if t:
                bits.append((t + " " + v).strip())
        return "; ".join(bits)

    def list_formulas(self):
        out = []
        for rec, name, level, price, slots in FORMULAS:
            it = self._match_item(name)
            reagents = [SLOT_BY_ID[s]["name"] for s in slots if s in SLOT_BY_ID]
            tools = sorted({SLOT_BY_ID[s]["tool"] for s in slots if s in SLOT_BY_ID})
            out.append({
                "id": rec, "name": name, "level": level, "price": price,
                "slots": slots, "reagents": reagents, "tools": tools,
                "starter": rec in STARTERS,
                "item": self._item_brief(it),
            })
        return out

    def formula(self, fid: int):
        rec = next((f for f in self.list_formulas() if f["id"] == int(fid)), None)
        if rec is None:
            raise KeyError(fid)
        rec = dict(rec)
        rec["note"] = "Formula records live in RtK.exe at 0x612e28. Edit the catalog row and MagicResult, not the ROM table."
        rec["spell"] = None
        rec["picture"] = None
        it = rec.get("item") or {}
        name = it.get("magic_result") or it.get("effect_spell")
        if name:
            try:
                rec["spell"] = self.app.fx.spell(name)
            except KeyError:
                rec["spell"] = None
        behavior = None
        if rec.get("spell"):
            behavior = rec["spell"].get("behavior") or (
                (rec["spell"].get("editable") or {}).get("Behavior_File"))
        if behavior:
            try:
                rec["picture"] = self.app.fx.bex_by_name(behavior)
            except Exception:
                rec["picture"] = None
        return rec

    def bench(self):
        cat = self._catalog()
        reagents = []
        for r in REAGENTS:
            it = self._match_item(r["name"])
            reagents.append(dict(r, item=self._item_brief(it)))
        tools = []
        for t in TOOLS:
            it = self._match_item(t["name"]) or self._match_item(t["catalog"])
            tools.append(dict(t, item=self._item_brief(it)))
        recipes = []
        for it in cat.items:
            if it.get("Category") != "Recipe":
                continue
            recipes.append(self._item_brief(it))
        flask = self._match_item("Flask")
        return {
            "reagents": reagents,
            "tools": tools,
            "recipes": recipes,
            "flask": self._item_brief(flask),
            "columns": ["James", "Jazhara", "William / Kendaric", "Solon"],
            "class_bit": "LPMage = 4",
            "skill_index": 13,
            "starters": [FORMULAS[i][1] for i in STARTERS],
            "note": "Only Jazhara and Kendaric may brew. Column 2 is whoever of William/Kendaric is first in the party list.",
        }

    def save_item(self, name, fields: dict = None, effect_fields: dict = None) -> str:
        return self._catalog().apply(name, fields=fields, effect_fields=effect_fields)
