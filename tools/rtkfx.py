"""Combat tracks, .bex graphs, MagicResult editor, and LaunchFX catalog.

No .bex encoder — view + node list only. Spell and item text saves go
through the mod override of MagicResult.txt / MagicInvItem.txt.
"""

from __future__ import annotations

import re
from pathlib import Path

import rtkbex
import rtkdef
import rtkspx

GAME_DEF = "rtkgame.def"
MAGIC_RESULT = "magicresult.txt"
ITEM_CATALOG = "file/GameData/MagicInvItem.txt"
COLON_AT = 19
SPELL_FIELDS = (
    "Spell_Type", "Magic_Class", "Magic_Path", "Level", "SpellPt_Cost",
    "Range", "Duration", "Duration_Value", "Duration_LevelInc",
    "Resist_With", "Target_of_Spell", "Number_to_Effect",
    "Target_in_Range", "Resist_Base", "Roll_Handle", "Behavior_File",
)
LAUNCH_RE = re.compile(
    r'LaunchFX\s*\(\s*"([^"]+\.bex)"\s*(?:,\s*([^,\)]+))?(?:,\s*([^,\)]+))?',
    re.I)
_STOP = {"of", "the", "a", "an", "for", "and", "item"}


def _tokens(s):
    return frozenset(
        t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in _STOP
    )


def _expand_spell_name(name: str) -> str:
    s = re.sub(r"^Item_", "", name or "")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"\bWk\b", "Weak", s)
    s = re.sub(r"\bStr\b", "Strong", s)
    s = re.sub(r"\bPot\b", "Potion", s)
    return s


class FxIndex:
    def __init__(self, app):
        self.app = app
        self.index = rtkdef.name_index(app.db)
        self.game_key = rtkdef.find_name(self.index, GAME_DEF)
        self.magic_key = rtkdef.find_name(self.index, MAGIC_RESULT)
        self.tracks = []
        self.spells = []
        self.launches = []
        self.item_casts = []
        self.sprites = {}
        self._load()

    def _text(self, key):
        return rtkdef.inflate_text(self.app.read(key))

    def _load(self):
        if self.game_key:
            text = self._text(self.game_key)
            in_combat = False
            for line in text.splitlines():
                s = line.strip()
                if re.match(r"^CTrackGroup\s+Combat\b", s, re.I):
                    in_combat = True
                    continue
                if in_combat:
                    if re.match(r"^C(Track|Strike)", s, re.I) or \
                            (s and not s[0].isalnum() and s[0] != "."):
                        if s.lower().startswith("c") and " " in s and \
                                not s.lower().startswith("cmbt"):
                            in_combat = False
                            continue
                    if not s or s.lower() in ("end", "begin"):
                        if s.lower() == "end":
                            in_combat = False
                        continue
                    parts = [p.strip() for p in s.split(",")]
                    if not parts or not parts[0].lower().endswith(".trk"):
                        continue
                    fname = parts[0]
                    key = rtkdef.find_name(self.index, fname.lower())
                    self.tracks.append({
                        "file": fname,
                        "key": key,
                        "def": parts[1] if len(parts) > 1 else "",
                        "label": parts[-1] if len(parts) > 2 else fname,
                        "mask": parts[-2] if len(parts) > 2 else "",
                    })
        if self.magic_key:
            text = self._text(self.magic_key)
            current = {}
            spells = []

            def flush():
                if not current:
                    return
                spells.append({
                    "name": current.get("Spell_Name"),
                    "behavior": current.get("Behavior_File"),
                    "type": current.get("Spell_Type"),
                    "klass": current.get("Magic_Class"),
                    "path": current.get("Magic_Path"),
                    "level": current.get("Level"),
                    "cost": current.get("SpellPt_Cost"),
                    "fields": dict(current),
                })

            for line in text.splitlines():
                s = line.strip()
                m = rtkdef.FIELD_RE.match(s)
                if not m:
                    continue
                key, val = m.group(1), m.group(2).strip()
                if key.lower() == "spell_name" and current:
                    flush()
                    current = {}
                if key.lower() == "spell_end":
                    flush()
                    current = {}
                    continue
                if key.lower() in ("effect", "effect_end") or key.lower().startswith("effect_"):
                    continue
                if key in current:
                    sep = "\n" if key.lower() == "description" else " "
                    current[key] = current[key] + sep + val
                else:
                    current[key] = val
            flush()
            self.spells = [s for s in spells if s.get("name")]
            self._parse_effects()
        self._load_launches()
        self._load_item_casts()
        self._load_sprites()

    def _load_sprites(self):
        bmp_index = {}
        spx_files = []
        for a in self.app.db.assets:
            cont = (a.container or "").lower()
            if cont not in ("fx.t3d", "hicolorfx.t3d"):
                continue
            low = a.name.lower()
            if low.endswith(".bmp"):
                bmp_index.setdefault(Path(a.name).name.lower(), []).append(a)
            elif low.endswith(".spx") and cont == "fx.t3d":
                spx_files.append(a)
        for asset in spx_files:
            try:
                sf = rtkspx.SpriteFile(Path(asset.name), self.app.read(asset.key))
            except Exception:
                continue
            sheets = []
            seen = set()
            for info in sf.bminfos:
                fn = Path(info.filename or "").name
                if not fn:
                    continue
                keys = bmp_index.get(fn.lower()) or []
                eight = next((k for k in keys if (k.container or "").lower() == "fx.t3d"), None)
                hi = next((k for k in keys if (k.container or "").lower() == "hicolorfx.t3d"), None)
                if eight is None:
                    eight = keys[0] if keys else None
                if eight is None or eight.key in seen:
                    continue
                seen.add(eight.key)
                sheets.append({
                    "key": eight.key,
                    "name": fn,
                    "hicolor": hi.key if hi else None,
                })
            stem = Path(asset.name).stem
            rec = {
                "name": stem,
                "label": stem,
                "spx": asset.key,
                "sheets": sheets,
            }
            self.sprites[stem.lower()] = rec
            for tag in getattr(sf, "names", None) or []:
                if tag:
                    self.sprites.setdefault(tag.lower(), rec)

    def bex_by_name(self, name: str):
        """Resolve a Behavior_File / LaunchFX name to a parsed .bex."""
        raw = (name or "").strip()
        if not raw:
            return None
        key = rtkdef.find_name(self.index, raw.lower())
        if not key:
            key = rtkdef.find_name(self.index, Path(raw).name.lower())
        if not key:
            want = Path(raw).name.lower()
            for a in self.app.db.assets:
                if Path(a.name).name.lower() == want:
                    key = a.key
                    break
        if not key:
            return None
        return self.bex(key)

    def resolve_sprite(self, name):
        if not name or name.upper() == "PARENT":
            return None
        rec = self.sprites.get(name.lower())
        if rec:
            return rec
        want = name.lower()
        for key, rec in self.sprites.items():
            if key.startswith(want) or want.startswith(key):
                return rec
        return None

    def list_sprites(self, q=""):
        q = (q or "").lower()
        seen = set()
        out = []
        for rec in self.sprites.values():
            if rec["spx"] in seen:
                continue
            seen.add(rec["spx"])
            blob = (rec["name"] + " " + " ".join(s["name"] for s in rec["sheets"])).lower()
            if q and q not in blob:
                continue
            out.append({
                "name": rec["name"],
                "spx": rec["spx"],
                "sheets": len(rec["sheets"]),
                "preview": rec["sheets"][0]["key"] if rec["sheets"] else None,
            })
        out.sort(key=lambda r: r["name"].lower())
        return out

    def sprite(self, name: str):
        rec = self.resolve_sprite(name)
        if rec is None:
            raise KeyError(name)
        return dict(rec)

    def _parse_effects(self):
        if not self.magic_key:
            return
        text = self._text(self.magic_key)
        by_name = {s["name"]: s for s in self.spells}
        current = None
        effect = None
        for line in text.splitlines():
            s = line.strip()
            m = rtkdef.FIELD_RE.match(s)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip()
            if key.lower() == "spell_name":
                current = by_name.get(val)
                if current is not None:
                    current["effects"] = []
                effect = None
                continue
            if current is None:
                continue
            if key.lower() == "effect" and val.lower() == "begin":
                effect = {}
                current["effects"].append(effect)
                continue
            if key.lower() == "effect_end":
                effect = None
                continue
            if key.lower() == "spell_end":
                current = None
                effect = None
                continue
            if effect is not None:
                effect[key] = val

    def _load_launches(self):
        seen = []
        for name, keys in sorted(self.index.items()):
            if not name.endswith(".def"):
                continue
            key = keys[0]
            if "chapter" not in key.lower():
                continue
            try:
                text = self._text(key)
            except Exception:
                continue
            chapter = Path(key).parent.name
            for m in LAUNCH_RE.finditer(text):
                rec = {
                    "file": m.group(1),
                    "source": (m.group(2) or "").strip(),
                    "target": (m.group(3) or "").strip(),
                    "chapter": chapter,
                    "key": key,
                }
                seen.append(rec)
        self.launches = seen

    def _load_item_casts(self):
        try:
            cat = self.app.items
        except Exception:
            return
        out = []
        for it in cat.items:
            spell = None
            magic = None
            noncombat = None
            for line in it.get("lines") or []:
                s = line.strip()
                if s.lower().startswith("effect_spell"):
                    spell = s.split(":", 1)[1].strip()
                elif s.lower().startswith("effect_magic"):
                    magic = s.split(":", 1)[1].strip()
                elif s.lower().startswith("effect_noncombat"):
                    noncombat = s.split(":", 1)[1].strip()
            if not spell:
                continue
            out.append({
                "name": it.get("Item_Name"),
                "label": it.get("AS_Tag") or it.get("Item_Name"),
                "spell": spell,
                "resolved": self.find_spell_name(spell),
                "magic": magic,
                "noncombat": noncombat,
                "category": it.get("Category"),
            })
        self.item_casts = out

    def list_tracks(self, q=""):
        q = (q or "").lower()
        rows = self.tracks
        if q:
            rows = [t for t in rows if q in t["file"].lower()
                    or q in (t["label"] or "").lower()]
        return rows

    def list_bex(self, q=""):
        q = (q or "").lower()
        out = []
        for a in self.app.db.assets:
            if not a.name.lower().endswith(".bex") or a.name.lower() in (".bex", "bex"):
                continue
            if q and q not in a.name.lower() and q not in a.key.lower():
                continue
            out.append({"key": a.key, "name": Path(a.name).name, "size": a.size})
        out.sort(key=lambda r: r["name"].lower())
        return out[:400]

    def list_spells(self, q=""):
        q = (q or "").lower()
        rows = self.spells
        if q:
            rows = [s for s in rows
                    if q in (s.get("name") or "").lower()
                    or q in (s.get("behavior") or "").lower()
                    or q in (s.get("path") or "").lower()
                    or q in (s.get("type") or "").lower()]
        return [{
            "name": s.get("name"),
            "behavior": s.get("behavior"),
            "type": s.get("type"),
            "klass": s.get("klass"),
            "path": s.get("path"),
            "level": s.get("level"),
            "cost": s.get("cost"),
            "effects": len(s.get("effects") or []),
        } for s in rows]

    def find_spell_name(self, name: str):
        if not name:
            return None
        if any(s.get("name") == name for s in self.spells):
            return name
        want = _tokens(_expand_spell_name(name)) or _tokens(name)
        best = None
        score = 0.0
        for s in self.spells:
            have = _tokens(s.get("name"))
            if not have:
                continue
            if have == want:
                return s["name"]
            sc = len(want & have) / len(want | have) if want else 0
            if sc > score:
                best, score = s["name"], sc
        return best if score >= 0.55 else None

    def spell(self, name: str):
        resolved = self.find_spell_name(name)
        rec = next((s for s in self.spells if s.get("name") == resolved), None)
        if rec is None:
            raise KeyError(name)
        rec = dict(rec)
        fields = rec.get("fields") or {}
        rec["editable"] = {k: fields.get(k, "") for k in SPELL_FIELDS}
        rec["description"] = fields.get("Description", "")
        rec["combat_only_picture"] = bool(rec.get("behavior"))
        rec["note"] = (
            "FUN_004a5207 plays Behavior_File only in a fight. "
            "LaunchFX ignores that flag. No .bex encoder."
        )
        return rec

    def list_launches(self, q=""):
        q = (q or "").lower()
        rows = self.launches
        if q:
            rows = [r for r in rows
                    if q in r["file"].lower()
                    or q in (r.get("chapter") or "").lower()
                    or q in (r.get("source") or "").lower()]
        return rows

    def list_item_casts(self, q=""):
        q = (q or "").lower()
        rows = self.item_casts
        if q:
            rows = [r for r in rows
                    if q in (r["name"] or "").lower()
                    or q in (r.get("spell") or "").lower()]
        return rows

    def save_spell(self, name: str, fields: dict = None, effects=None) -> str:
        if not self.magic_key:
            raise KeyError("MagicResult.txt")
        text = self._text(self.magic_key)
        fields = dict(fields or {})
        if effects is not None:
            text = _replace_spell_effects(text, name, effects)
        for field, value in fields.items():
            if field.lower() == "description":
                text = _replace_spell_description(text, name, str(value))
            else:
                text = _replace_spell_field(text, name, field, str(value))
        return text

    def bex(self, key: str):
        raw = self.app.read(key)
        fx = rtkbex.FxInfo(key, data=raw)
        entries = []
        sprites = []
        seen = set()
        for e in fx.entries:
            params = e.params()
            rec = {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "type_name": e.type_name,
                "flags": e.flags,
                "active": bool(getattr(e, "active", e.flags & 1)),
                "repeat": e.repeat,
                "payload": len(e.payload or b""),
                "activate": list(e.activate or []),
                "deactivate": list(e.deactivate or []),
                "params": params,
            }
            entries.append(rec)
            spr = params.get("sprite")
            if spr and spr not in seen:
                seen.add(spr)
                resolved = self.resolve_sprite(spr)
                if resolved:
                    sprites.append(dict(resolved, used_as=spr))
                else:
                    sprites.append({
                        "name": spr, "used_as": spr, "spx": None, "sheets": [],
                    })
        return {
            "key": key,
            "name": Path(key).name,
            "entries": entries,
            "count": len(entries),
            "sprites": sprites,
            "sprite_names": [s["name"] for s in self.list_sprites()],
            "note": "Type-9 set_sprite names an FX.t3d sprite. Swap the name or edit the 8-bit sheets.",
        }

    def save_bex_sprite(self, key: str, entry_id, sprite: str) -> bytes:
        raw = self.app.read(key)
        fx = rtkbex.FxInfo(key, data=raw)
        fx.set_sprite(entry_id, sprite)
        return fx.to_bytes()


def _spell_span(text: str, name: str):
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        m = rtkdef.FIELD_RE.match(line.strip())
        if m and m.group(1).lower() == "spell_name" and m.group(2).strip() == name:
            start = i
            break
    if start is None:
        raise KeyError(name)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        s = lines[i].strip()
        m = rtkdef.FIELD_RE.match(s)
        if m and m.group(1).lower() == "spell_end":
            end = i + 1
            break
        if m and m.group(1).lower() == "spell_name":
            end = i
            break
    return lines, start, end


def _fmt(key: str, val: str) -> str:
    pad = max(1, COLON_AT - len(key))
    return f"{key}{' ' * pad}: {val}\n"


def _replace_spell_field(text: str, name: str, field: str, value: str) -> str:
    lines, start, end = _spell_span(text, name)
    found = False
    for i in range(start, end):
        m = rtkdef.FIELD_RE.match(lines[i].strip())
        if m and m.group(1).lower() == field.lower():
            lines[i] = _fmt(m.group(1), value)
            found = True
            break
    if not found:
        lines.insert(end - 1, _fmt(field, value))
    return "".join(lines)


def _replace_spell_description(text: str, name: str, value: str) -> str:
    lines, start, end = _spell_span(text, name)
    paras = [p.strip() for p in str(value).split("\n") if p.strip()]
    out = []
    skipped = False
    inserted = False
    for i, line in enumerate(lines):
        if i < start or i >= end:
            out.append(line)
            continue
        m = rtkdef.FIELD_RE.match(line.strip())
        if m and m.group(1).lower() == "description":
            if not skipped:
                skipped = True
            continue
        if skipped and not inserted:
            for p in paras:
                out.append(_fmt("Description", p))
            inserted = True
        out.append(line)
    if not inserted:
        block = [_fmt("Description", p) for p in paras]
        out[end - 1:end - 1] = block
    return "".join(out)


def _replace_spell_effects(text: str, name: str, effects) -> str:
    lines, start, end = _spell_span(text, name)
    keep = []
    skip = False
    insert_at = None
    for i in range(start, end):
        m = rtkdef.FIELD_RE.match(lines[i].strip())
        key = m.group(1).lower() if m else ""
        val = (m.group(2) or "").strip().lower() if m else ""
        if key == "effect" and val == "begin":
            skip = True
            if insert_at is None:
                insert_at = len(keep)
            continue
        if key == "effect_end":
            skip = False
            continue
        if skip:
            continue
        if key == "behavior_file" and insert_at is None:
            insert_at = len(keep)
        if key == "spell_end" and insert_at is None:
            insert_at = len(keep)
        keep.append(lines[i])
    if insert_at is None:
        insert_at = len(keep)
    block = []
    for eff in effects or []:
        block.append(_fmt("Effect", "Begin"))
        for k, v in (eff or {}).items():
            if v in (None, ""):
                continue
            block.append(_fmt(str(k), str(v)))
        block.append(_fmt("Effect_End", ""))
    keep[insert_at:insert_at] = block
    return "".join(lines[:start] + keep + lines[end:])
