"""Trap / lock studio: ROM layout table plus authored instance flags.

The 21-slot layout at DAT_00616f20 is binary in the exe, not a loose file.
Editable surface is CharacterDef.Trap and script SetTrapType / OnFail.
"""

from __future__ import annotations

import re

import rtkdef

# inventory.md — None plus 7 names × 3 mechanisms.
MECHANISMS = ("Wire", "Plate", "Hook")
NAMES = ("Serpent", "Dagger", "Venom", "Needle", "Blade", "Ember", "Fire")

LAYOUTS = []
for mech_i, mech in enumerate(MECHANISMS):
    for name_i, name in enumerate(NAMES):
        LAYOUTS.append({
            "id": mech_i * 7 + name_i,
            "name": name,
            "mechanism": mech,
            "label": "%s %s" % (name, mech),
        })

# inventory.md §10 — tool drop controls on interface 0x12.
TOOLS = [
    {"control": "0x95", "mode": 4, "name": "Probe"},
    {"control": "0x96", "mode": 5, "name": "Lockpick"},
    {"control": "0x97", "mode": None, "name": "Disarm pick 1"},
    {"control": "0x98", "mode": None, "name": "Disarm pick 2"},
    {"control": "0x99", "mode": None, "name": "Disarm pick 3"},
]


def layout_by_name(label: str):
    raw = (label or "").strip()
    if raw.lower() in ("", "none", "-1"):
        return {"id": -1, "name": "None", "mechanism": None, "label": "None"}
    compact = raw.replace(" ", "").lower()
    for row in LAYOUTS:
        if row["label"].lower() == raw.lower() or row["name"].lower() == raw.lower():
            return row
        if compact in (
            (row["name"] + row["mechanism"]).lower(),
            (row["mechanism"] + row["name"]).lower(),
            ("%s %s" % (row["name"], row["mechanism"])).lower().replace(" ", ""),
        ):
            return row
    try:
        n = int(raw)
    except ValueError:
        return {"id": None, "name": raw, "mechanism": None, "label": raw}
    if n == -1:
        return {"id": -1, "name": "None", "mechanism": None, "label": "None"}
    for row in LAYOUTS:
        if row["id"] == n:
            return row
    return {"id": n, "name": raw, "mechanism": None, "label": raw}


class TrapIndex:
    def __init__(self, app):
        self.app = app
        self.index = rtkdef.name_index(app.db)
        self.chars_key = rtkdef.find_name(self.index, "chars.tbl")
        self.instances = []
        self._load()

    def _text(self, key):
        return rtkdef.inflate_text(self.app.read(key))

    def _load(self):
        if self.chars_key:
            doc = rtkdef.parse_document(self._text(self.chars_key))
            for ch in doc.walk("CharacterDef"):
                trap = ch.field("Trap")
                if trap and trap.lower() not in ("", "none"):
                    self.instances.append({
                        "name": ch.name,
                        "source": "Chars.tbl",
                        "key": self.chars_key,
                        "block_kind": "CharacterDef",
                        "block_name": ch.name,
                        "trap": trap,
                        "layout": layout_by_name(trap),
                        "model_type": ch.field("Model_Type"),
                        "script": ch.script,
                    })
        set_re = re.compile(r"SetTrapType\s*\(\s*\"?([^\"\)]+)\"?\s*\)", re.I)
        for name, keys in sorted(self.index.items()):
            if not name.endswith(".def") or "chapter" not in keys[0].lower():
                continue
            key = keys[0]
            try:
                doc = rtkdef.parse_document(self._text(key))
            except Exception:
                continue
            scene = None
            for sd in doc.walk("SceneDef"):
                scene = sd.name
                for block in sd.children:
                    hits = set_re.findall(block.script or "")
                    trapped = (block.field("IsTrapped") or
                               block.field("Trapped") or "")
                    if not hits and not trapped:
                        continue
                    label = hits[0] if hits else trapped
                    self.instances.append({
                        "name": block.name,
                        "kind": block.kind,
                        "scene": scene,
                        "key": key,
                        "block_kind": block.kind,
                        "block_name": block.name,
                        "trap": label,
                        "layout": layout_by_name(label),
                        "script": block.script,
                        "source": "script",
                    })

    def list_layouts(self):
        return {
            "layouts": LAYOUTS,
            "tools": TOOLS,
            "interface": "0x12",
            "note": "DAT_00616f20 is in the exe; edit instance text, not the ROM table.",
        }

    def list_instances(self, q=""):
        q = (q or "").lower()
        rows = self.instances
        if q:
            rows = [r for r in rows
                    if q in r["name"].lower()
                    or q in (r.get("scene") or "").lower()
                    or q in (r.get("trap") or "").lower()]
        return rows

    def save_instance(self, key, kind, name, trap: str) -> str:
        text = self._text(key)
        return rtkdef.replace_field(text, kind, name, "Trap", trap)
