"""Shop defs and starting inventories on Chars.tbl.

Item catalog / mesh / pixels stay in the Item editor.
"""

from __future__ import annotations

import re

import rtkdef

SHOP_FILES = ("krondorshops.def", "haldonshops.def", "itemsshop.tbl")


def _parse_store_line(line: str):
    parts = [p.strip() for p in line.split(",")]
    if not parts or not parts[0]:
        return None
    name = parts[0]
    markup = None
    qty = None
    if len(parts) > 1:
        try:
            markup = float(parts[1])
        except ValueError:
            markup = parts[1]
    if len(parts) > 2 and parts[2] != "":
        try:
            qty = int(float(parts[2]))
        except ValueError:
            qty = parts[2]
    return {"name": name, "markup": markup, "quantity": qty, "raw": line}


def parse_shops(text: str, key: str) -> list:
    shops = []
    current = None
    in_items = False
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^Shop\s+(.+?)\s*$", s, re.I)
        if m and m.group(1).strip().lower() == "definition file":
            continue
        if m:
            if current:
                shops.append(current)
            current = {
                "name": m.group(1).strip(),
                "key": key,
                "fields": {},
                "items": [],
            }
            in_items = False
            continue
        if current is None:
            continue
        if s.lower() == "storeitems":
            in_items = True
            continue
        if s.lower() == "end":
            if in_items and current["items"]:
                # shop-level end
                shops.append(current)
                current = None
                in_items = False
                continue
            in_items = False
            if current:
                shops.append(current)
                current = None
            continue
        if in_items:
            rec = _parse_store_line(s)
            if rec:
                current["items"].append(rec)
            continue
        fm = rtkdef.FIELD_RE.match(s)
        if fm:
            current["fields"][fm.group(1)] = fm.group(2).strip()
    if current:
        shops.append(current)
    return shops


def parse_inventory(block) -> list:
    items = []
    for ch in block.children:
        if ch.kind.lower() != "inventoryitems":
            continue
        pending = None
        for line in ch.lines:
            fm = rtkdef.FIELD_RE.match(line)
            if fm:
                if pending is None:
                    pending = {"name": "", "fields": {}}
                key, val = fm.group(1), fm.group(2).strip()
                if key.lower() == "def":
                    if pending.get("name") and pending["name"] != val:
                        items.append(pending)
                        pending = {"name": val, "fields": {}}
                    else:
                        pending["name"] = val
                pending["fields"][key] = val
            else:
                if pending:
                    items.append(pending)
                    pending = None
                # Compact "Lockpicks" or "Antidote - Weak,1,1"
                parts = [p.strip() for p in line.split(",")]
                items.append({
                    "name": parts[0],
                    "quantity": parts[1] if len(parts) > 1 else "",
                    "fields": {},
                    "raw": line,
                })
        if pending:
            items.append(pending)
    return items


class ShopIndex:
    def __init__(self, app):
        self.app = app
        self.index = rtkdef.name_index(app.db)
        self.shops = []
        self.loadouts = []
        self._load()

    def _text(self, key):
        return rtkdef.inflate_text(self.app.read(key))

    def _load(self):
        for name in SHOP_FILES:
            key = rtkdef.find_name(self.index, name)
            if not key:
                continue
            try:
                self.shops.extend(parse_shops(self._text(key), key))
            except Exception:
                continue
        chars = rtkdef.find_name(self.index, "chars.tbl")
        if chars:
            doc = rtkdef.parse_document(self._text(chars))
            for ch in doc.walk("CharacterDef"):
                inv = parse_inventory(ch)
                if not inv:
                    continue
                self.loadouts.append({
                    "name": ch.name,
                    "key": chars,
                    "class": ch.field("Class"),
                    "model": ch.field("Model"),
                    "items": inv,
                })

    def list_shops(self, q=""):
        q = (q or "").lower()
        rows = []
        for s in self.shops:
            rec = {
                "name": s["name"],
                "key": s["key"],
                "city": s["fields"].get("City"),
                "gold": s["fields"].get("Gold"),
                "haggle": s["fields"].get("HaggleVar"),
                "items": len(s["items"]),
            }
            if q and q not in rec["name"].lower() and q not in (rec["city"] or "").lower():
                continue
            rows.append(rec)
        return rows

    def shop(self, name: str):
        rec = next((s for s in self.shops if s["name"] == name), None)
        if rec is None:
            raise KeyError(name)
        return rec

    def list_loadouts(self, q=""):
        q = (q or "").lower()
        rows = self.loadouts
        if q:
            rows = [r for r in rows if q in r["name"].lower()]
        return [{"name": r["name"], "key": r["key"], "class": r["class"],
                 "model": r["model"], "items": len(r["items"])} for r in rows]

    def loadout(self, name: str):
        rec = next((r for r in self.loadouts if r["name"] == name), None)
        if rec is None:
            raise KeyError(name)
        return rec

    def save_shop_field(self, name: str, field: str, value: str) -> str:
        shop = self.shop(name)
        text = self._text(shop["key"])
        return rtkdef.replace_field(text, "Shop", name, field, value)

    def save_shop_items(self, name: str, lines: list) -> str:
        shop = self.shop(name)
        text = self._text(shop["key"])
        return rtkdef.replace_section(text, "Shop", name, "StoreItems", lines)

    def save_loadout(self, name: str, lines: list) -> str:
        rec = self.loadout(name)
        text = self._text(rec["key"])
        return rtkdef.replace_section(
            text, "CharacterDef", name, "InventoryItems", lines)
