"""CombatDef browser plus Chars.tbl class / level / XP / loadout tools.

A new class bit cannot be invented without an exe change (combat.md §16).
Attribute indexes 0/6/7 are level, health, and spell points (encounters.md §4).
Indexes 1–5 are stored; labels follow the combat virtuals.
"""

from __future__ import annotations

import re

import rtkdef
import rtkshops

CLASS_BITS = {
    "None": 0, "Warrior": 1, "Thief": 2, "LPMage": 4, "Priest": 8,
    "NPC": 16, "Object": 32, "PassThru": 64, "Invisible": 128,
}
CLASS_NAMES = {v: k for k, v in CLASS_BITS.items()}
CLASS_ORDER = (
    "None", "Warrior", "Thief", "LPMage", "Priest",
    "NPC", "Object", "PassThru", "Invisible",
)

# encounters.md §4 / combat.md §3. 1–5 names are not in the parser.
ATTR_FIELDS = (
    ("level", "Level"),
    ("strength", "Strength"),
    ("agility", "Agility"),
    ("stamina", "Stamina"),
    ("reason", "Reason"),
    ("aura", "Aura"),
    ("health", "Health"),
    ("spell_points", "Spell points"),
)

# combat.md §3 — Skills line index, sheet name, who can raise it.
SKILL_FIELDS = (
    ("Brawling", "anyone", "weapon"),
    ("Bladed", "not a priest", "weapon"),
    ("Blunt", "anyone", "weapon"),
    ("Axe", "warrior only", "weapon"),
    ("2-Handed", "anyone", "weapon"),
    ("Bow", "not a mage or a priest", "weapon"),
    ("Defense", "anyone", "general"),
    ("Initiative", "anyone", "general"),
    ("Analyze", "not a warrior", "general"),
    ("Stealth", "anyone", "general"),
    ("Pick Lock", "thief only", "general"),
    ("Disarm Traps", "thief only", "general"),
    ("Perception", "anyone", "general"),
    ("Alchemy", "mage only", "general"),
    ("Evaluate", "anyone", "general"),
    ("Shield", "not a thief", "general"),
    ("Fire", "mage only", "path"),
    ("Mind", "mage only", "path"),
    ("Change", "mage only", "path"),
    ("Storms", "mage only", "path"),
    ("Life", "priest only", "path"),
    ("Divine", "priest only", "path"),
)
SKILL_LABELS = [row[0] for row in SKILL_FIELDS]

ATTACK_FIELDS = (
    ("ap0", "Attack 0"),
    ("ap1", "Attack 1"),
    ("hit", "Hit pair"),
    ("strikes", "Strikes / round"),
    ("damage", "Damage"),
    ("ap5", "Attack 5"),
    ("ap6", "Attack 6"),
)

EQUIP_SLOTS = (
    ("Hand", "Weapon"),
    ("Shield", "Shield"),
    ("Torso", "Chest"),
    ("Arms", "Arms"),
    ("Legs", "Legs"),
    ("OffHand", "Off hand"),
    ("Ring", "Ring"),
    ("Neck", "Neck"),
)
EQUIP_LOCS = {k.lower(): k for k, _ in EQUIP_SLOTS}
EQUIP_LOCS["pack"] = "Pack"

# encounters.md §7 — FUN_004ac160 tables. Last entry is the 999999 cap.
XP_TABLES = {
    "Thief": {  # base 3
        "base": 3,
        "advance": {
            2: 1000, 3: 1500, 4: 2250, 5: 3375, 6: 5062, 7: 7593,
            8: 11390, 9: 17085, 10: 25628, 11: 38443, 12: 57665,
            13: 86497, 14: 129746, 15: 194619, 16: 291929,
            17: 437893, 18: 999999,
        },
    },
    "LPMage": {  # base 2
        "base": 2,
        "advance": {
            1: 1000, 2: 2000, 3: 3000, 4: 4500, 5: 6750, 6: 10125,
            7: 15187, 8: 22781, 9: 34171, 10: 51257, 11: 76886,
            12: 115330, 13: 172995, 14: 999999,
        },
    },
    "Warrior": {
        "base": 3,
        "advance": {
            2: 1500, 3: 2250, 4: 3375, 5: 5062, 6: 7593, 7: 11390,
            8: 17085, 9: 25628, 10: 999999,
        },
    },
    "Priest": {
        "base": 3,
        "advance": {
            2: 8000, 3: 12000, 4: 18500, 5: 27000, 6: 40500, 7: 60750,
            8: 91125, 9: 136687, 10: 205031, 11: 307546, 12: 461320,
            13: 691980, 14: 999999,
        },
    },
}

# combat.md §14 — inclusive Rand ranges.
LEVEL_GAIN = {
    "Warrior": {"hp": (10, 15), "sp": None},
    "Thief": {"hp": (8, 12), "sp": None},
    "LPMage": {"hp": (5, 8), "sp": (4, 6)},
    "Priest": {"hp": (9, 13), "sp": (3, 5)},
}

CHARS_NAME = "chars.tbl"


def class_token(raw: str) -> str:
    token = (raw or "").split(",")[0].strip()
    return token if token in CLASS_BITS else token


def simulate_xp(cls: str, pool: int):
    table = XP_TABLES.get(cls)
    if table is None:
        return {"class": cls, "pool": pool, "level": None,
                "next": 999999, "note": "no threshold table (combat.md §16)"}
    level = table["base"]
    nxt = table["advance"].get(level, 999999)
    for lv, need in sorted(table["advance"].items()):
        if lv < level:
            continue
        if pool >= need and need < 999999:
            level = lv + 1
            nxt = table["advance"].get(level, 999999)
        else:
            nxt = need
            break
    return {
        "class": cls,
        "pool": pool,
        "level": level,
        "next": nxt,
        "table": table["advance"],
        "gains": LEVEL_GAIN.get(cls),
    }


class CombatIndex:
    def __init__(self, app):
        self.app = app
        self.index = rtkdef.name_index(app.db)
        self.chars_key = rtkdef.find_name(self.index, CHARS_NAME)
        self.fights = []
        self.characters = []
        self._load()

    def _text(self, key):
        return rtkdef.inflate_text(self.app.read(key))

    def _load(self):
        self.fights = []
        self.characters = []
        for name, keys in sorted(self.index.items()):
            if not name.endswith(".def"):
                continue
            if "chapter" not in keys[0].replace("\\", "/").lower():
                continue
            key = keys[0]
            try:
                doc = rtkdef.parse_document(self._text(key))
            except Exception:
                continue
            scene = None
            for sd in doc.walk("SceneDef"):
                scene = sd.name
                for cb in sd.walk("CombatDef"):
                    groups = []
                    for ch in cb.children:
                        if ch.kind.lower() == "groups":
                            groups = list(ch.lines)
                    forms = []
                    for ch in cb.children:
                        if ch.kind.lower() != "formation":
                            continue
                        members = []
                        for line in ch.lines:
                            fm = rtkdef.FIELD_RE.match(line)
                            if fm:
                                xyz = rtkdef.floats(fm.group(2))
                                members.append({
                                    "name": fm.group(1),
                                    "xyz": xyz[:3],
                                    "facing": xyz[3] if len(xyz) > 3 else 0,
                                })
                        forms.append({"name": ch.name, "members": members})
                    self.fights.append({
                        "name": cb.name,
                        "scene": scene,
                        "key": key,
                        "music": cb.field("CombatMusic"),
                        "groups": groups,
                        "formations": forms,
                        "arena": rtkscene_poly(cb.field("Arena")),
                        "script": cb.script,
                    })
        if self.chars_key:
            doc = rtkdef.parse_document(self._text(self.chars_key))
            for ch in doc.walk("CharacterDef"):
                self.characters.append(self._summarize(ch))

    def _summarize(self, ch):
        parsed = parse_class(ch.field("Class"))
        attrs = parse_csv_nums(ch.field("Attribute"), 8)
        skills = parse_csv_nums(ch.field("Skills"), 22)
        attack = parse_attack(ch.field("AttackParam"))
        inv = classify_inventory(rtkshops.parse_inventory(ch), self._item_lookup())
        level = int(attrs[0]) if attrs else 0
        health = int(attrs[6]) if len(attrs) > 6 else 0
        spell = int(attrs[7]) if len(attrs) > 7 else 0
        pool = 0
        try:
            pool = int(float(ch.field("Experience") or 0))
        except (TypeError, ValueError):
            pool = 0
        return {
            "name": ch.name,
            "chapter": ch.field("Chapter"),
            "class": ch.field("Class"),
            "class_token": parsed["token"],
            "class_bit": parsed["bit"],
            "generic": parsed["generic"],
            "style_aggressive": parsed["aggressive"],
            "style_defensive": parsed["defensive"],
            "attribute": attrs,
            "attributes": attr_map(attrs),
            "level": level,
            "health": health,
            "spell_points": spell,
            "experience": pool,
            "kill_xp": level * (health + 2 * spell),
            "attack": ch.field("AttackParam"),
            "attack_fields": attack,
            "skills": ch.field("Skills"),
            "skill_values": skills,
            "magic": ch.field("Magic"),
            "armor": ch.field("ArmorParam"),
            "nationality": ch.field("Nationality"),
            "model": ch.field("Model"),
            "model_type": ch.field("Model_Type"),
            "trap": ch.field("Trap"),
            "inventory": inv,
            "equipped": [it for it in inv if it.get("equipped")],
            "loot": [it for it in inv if not it.get("equipped")],
            "key": self.chars_key,
        }

    def _item_lookup(self):
        try:
            cat = self.app.items
        except Exception:
            return {}
        out = {}
        for it in getattr(cat, "items", []) or []:
            name = it.get("Item_Name") or ""
            if name:
                out[name.lower()] = cat.summary(it)
        return out

    def list_fights(self):
        return [{k: f[k] for k in
                 ("name", "scene", "key", "music", "groups")}
                for f in self.fights]

    def fight(self, name: str):
        rec = next((f for f in self.fights if f["name"] == name), None)
        if rec is None:
            raise KeyError(name)
        return rec

    def list_classes(self, q=""):
        q = (q or "").lower()
        rows = self.characters
        if q:
            rows = [c for c in rows if q in c["name"].lower()
                    or q in (c["class"] or "").lower()
                    or q in (c.get("model") or "").lower()]
        return [{
            "name": c["name"], "class": c["class"], "class_token": c["class_token"],
            "level": c["level"], "health": c["health"], "model": c["model"],
            "equipped": len(c.get("equipped") or []),
            "loot": len(c.get("loot") or []),
        } for c in rows]

    def list_models(self):
        chars = self.app.characters
        out = []
        for rec in (chars.models or {}).values():
            has = chars.has_rig(rec)
            adf = (rec.get("adf") or "").lower()
            kind = "character" if has else (
                "container" if "container2d" in adf else "prop")
            out.append({
                "name": rec["name"], "adf": rec.get("adf") or "",
                "has_rig": has, "type": kind,
                "hs_def": chars.resolve_hs_def(rec),
                "head_sprite": rec.get("head_sprite") or "",
                "palette": rec.get("palette_bmp") or "",
                "look": rec.get("look"),
            })
        out.sort(key=lambda r: r["name"].lower())
        return out

    def character(self, name: str):
        rec = next((c for c in self.characters if c["name"] == name), None)
        if rec is None:
            raise KeyError(name)
        rec = dict(rec)
        rec["xp"] = simulate_xp(rec["class_token"], rec.get("experience") or 0)
        rec["attr_fields"] = [{"id": i, "key": k, "label": lab}
                              for i, (k, lab) in enumerate(ATTR_FIELDS)]
        rec["skill_fields"] = [
            {"id": i, "label": lab, "who": who, "group": grp}
            for i, (lab, who, grp) in enumerate(SKILL_FIELDS)
        ]
        rec["attack_labels"] = [{"key": k, "label": lab}
                                for k, lab in ATTACK_FIELDS]
        rec["equip_slots"] = [{"id": sid, "label": lab} for sid, lab in EQUIP_SLOTS]
        rec["class_names"] = list(CLASS_ORDER)
        rec["models"] = self.list_models()
        rec["model_resolved"] = self.app.characters.resolve_model_name(rec.get("model"))
        rec["sprites"] = self.app.characters.model_sprites(
            rec.get("model_resolved") or rec.get("model") or "")
        rec["palettes"] = self.app.characters.list_palettes()
        rec["head_sprites"] = self.app.characters.list_head_sprites()
        return rec

    def save_model(self, name, fields) -> str:
        return self.app.characters.save_model(name, fields)

    def duplicate_model(self, source, new_name, fields=None) -> str:
        return self.app.characters.duplicate_model(source, new_name, fields)

    def save_character(self, name: str, fields=None, stats=None,
                       inventory=None) -> str:
        if not self.chars_key:
            raise KeyError("Chars.tbl")
        assembled = dict(fields or {})
        st = stats or {}
        if st.get("attributes") is not None:
            assembled["Attribute"] = format_nums(
                [st["attributes"].get(k, 0) for k, _ in ATTR_FIELDS])
        if st.get("skills") is not None:
            vals = st["skills"]
            if isinstance(vals, dict):
                vals = [vals.get(str(i), vals.get(i, 0)) for i in range(22)]
            assembled["Skills"] = format_nums(vals)
        if st.get("attack") is not None:
            assembled["AttackParam"] = format_attack(st["attack"])
        if st.get("class_token") is not None:
            assembled["Class"] = format_class(
                st.get("class_token"), st.get("generic"),
                st.get("style_aggressive"), st.get("style_defensive"))
        if st.get("experience") is not None:
            assembled["Experience"] = str(int(st.get("experience") or 0))
        for key in ("Model", "Model_Type", "Trap", "Magic", "ArmorParam",
                    "Nationality", "Chapter"):
            if st.get(key) is not None:
                assembled[key] = st.get(key)
            if st.get(key.lower()) is not None:
                assembled[key] = st.get(key.lower())
        text = self._text(self.chars_key)
        for field, value in assembled.items():
            if value is None:
                continue
            text = rtkdef.replace_field(text, "CharacterDef", name, field,
                                        str(value))
        if inventory is not None:
            lines = serialize_inventory(inventory)
            try:
                text = rtkdef.replace_section(
                    text, "CharacterDef", name, "InventoryItems", lines)
            except ValueError:
                text = _insert_inventory(text, name, lines)
        return text


def rtkscene_poly(s):
    v = rtkdef.floats(s)
    return [[v[i], v[i + 1], v[i + 2]] for i in range(0, len(v) - 2, 3)]


def parse_csv_nums(raw, n):
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            out.append(0)
            continue
        try:
            out.append(int(float(part)))
        except ValueError:
            out.append(0)
    if len(out) < n:
        out.extend([0] * (n - len(out)))
    return out[:n]


def parse_class(raw):
    parts = [p.strip() for p in (raw or "").split(",")]
    token = parts[0] if parts else ""
    generic = any(p.lower() == "generic" for p in parts[1:])
    nums = []
    for p in parts[1:]:
        try:
            nums.append(int(float(p)))
        except ValueError:
            pass
    return {
        "token": token if token in CLASS_BITS else token,
        "bit": CLASS_BITS.get(token),
        "generic": generic,
        "aggressive": nums[0] if nums else 0,
        "defensive": nums[1] if len(nums) > 1 else 0,
    }


def format_class(token, generic=False, aggressive=0, defensive=0):
    parts = [token or "None"]
    if generic:
        parts.append("Generic")
    agg, deff = int(aggressive or 0), int(defensive or 0)
    if agg or deff:
        parts.append(str(agg))
        if deff:
            parts.append(str(deff))
    return ", ".join(parts)


def parse_attack(raw):
    parts = [p.strip() for p in (raw or "").split(",")]
    while len(parts) < 7:
        parts.append("")
    return {key: parts[i] for i, (key, _lab) in enumerate(ATTACK_FIELDS)}


def format_attack(fields):
    return ",".join(str((fields or {}).get(key, "") or "") for key, _ in ATTACK_FIELDS)


def attr_map(attrs):
    out = {}
    for i, (key, _lab) in enumerate(ATTR_FIELDS):
        out[key] = int(attrs[i]) if i < len(attrs) else 0
    return out


def format_nums(values):
    return ",".join(str(int(v or 0)) for v in values)


def classify_inventory(items, catalog=None):
    catalog = catalog or {}
    out = []
    for it in items or []:
        fields = dict(it.get("fields") or {})
        name = it.get("name") or fields.get("Def") or ""
        loc = (fields.get("Location") or fields.get("Location_Active")
               or fields.get("Slot") or "")
        qty = it.get("quantity") or fields.get("Quantity") or fields.get("Qty") or ""
        loc_key = (loc or "").strip()
        equipped = loc_key.lower() in EQUIP_LOCS and loc_key.lower() != "pack"
        slot = EQUIP_LOCS.get(loc_key.lower(), loc_key) if equipped else ""
        rec = {
            "name": name,
            "quantity": str(qty) if qty not in (None, "") else "",
            "location": slot or loc_key,
            "equipped": equipped,
            "raw": it.get("raw") or "",
            "label": (catalog.get(name.lower()) or {}).get("label") or name,
            "kind": (catalog.get(name.lower()) or {}).get("kind") or "",
            "preview": (catalog.get(name.lower()) or {}).get("preview") or {},
        }
        out.append(rec)
    return out


def serialize_inventory(items):
    lines = []
    for it in items or []:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        loc = (it.get("location") or "").strip()
        qty = str(it.get("quantity") or "").strip()
        if loc and loc.lower() not in ("", "pack"):
            lines.append("Def : " + name)
            lines.append("Location : " + loc)
            if qty:
                lines.append("Quantity : " + qty)
        elif it.get("raw") and "," in (it.get("raw") or ""):
            lines.append(it["raw"])
        elif qty:
            lines.append("%s,%s" % (name, qty))
        else:
            lines.append(name)
    return lines


def _insert_inventory(text, name, body_lines):
    lines = text.splitlines()
    header = None
    for i, line in enumerate(lines):
        if rtkdef._header_match(line, "CharacterDef", name):
            header = i
            break
    if header is None:
        raise ValueError("no CharacterDef %s" % name)
    depth = 0
    end = None
    for i in range(header + 1, len(lines)):
        s = lines[i].strip().lower()
        if s in rtkdef.BEGIN:
            depth += 1
        elif s in rtkdef.END:
            if depth <= 0:
                end = i
                break
            depth -= 1
    if end is None:
        raise ValueError("unclosed CharacterDef %s" % name)
    indent = re.match(r"^(\s*)", lines[end]).group(1)
    block = [indent + "    InventoryItems"]
    for row in body_lines:
        block.append(indent + "      " + row)
    block.append(indent + "    End")
    return "\n".join(lines[:end] + block + lines[end:]) + (
        "\n" if text.endswith("\n") else "")
