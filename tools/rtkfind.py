"""Search across the records the studios already parse, and replace text.

Record search covers characters, items, dialog, scenes, Models.def rows,
and shops. Replace rewrites display fields only (not record names) and the
caller writes the resulting files inside one undo transaction.

Binary mode scans text assets for a latin-1 string or a hex byte pattern.
It does not rewrite those bytes.
"""

from __future__ import annotations

import re
from pathlib import Path

import rtkdef

TEXT_EXTS = {".def", ".tbl", ".txt", ".rtk", ".h", ".trx", ".ktx", ".trm"}
HIT_LIMIT = 120
BINARY_LIMIT = 40
BINARY_SCAN_CAP = 800
BINARY_FILE_CAP = 4_000_000
REPLACE_CAP = 400


def search(app, q, kind=None, limit=HIT_LIMIT):
    q = (q or "").strip()
    _require_query(q)
    kind = (kind or "").strip().lower() or None
    if kind == "binary":
        return binary_search(app, q)
    hits = _collect(app, q, kind)
    hits.sort(key=lambda h: (h["kind"], (h.get("name") or "").lower()))
    public = []
    for hit in hits[:limit]:
        row = {k: v for k, v in hit.items() if k != "edits"}
        row["replaceable"] = bool(hit.get("edits"))
        public.append(row)
    return {"q": q, "kind": kind or "", "mode": "records",
            "total": len(hits), "hits": public}


def binary_search(app, q, limit=BINARY_LIMIT):
    q = (q or "").strip()
    _require_query(q)
    needle, exact = _needle(q)
    hits = []
    scanned = 0
    for asset in app.db.assets:
        if len(hits) >= limit or scanned >= BINARY_SCAN_CAP:
            break
        ext = Path(asset.name).suffix.lower()
        if ext not in TEXT_EXTS:
            continue
        if asset.size and asset.size > BINARY_FILE_CAP:
            continue
        scanned += 1
        try:
            raw = app.read(asset.key)
        except Exception:
            continue
        at = _find_bytes(raw, needle, exact)
        if at < 0:
            continue
        hits.append({
            "kind": "binary",
            "name": asset.name,
            "id": asset.key,
            "label": asset.name,
            "snippet": _snippet(raw, at, len(needle)),
            "replaceable": False,
        })
    return {"q": q, "kind": "binary", "mode": "binary",
            "total": len(hits), "scanned": scanned, "hits": hits}


def plan_replace(app, find, repl, kind=None):
    """{asset key -> new text} for every display field that contains `find`."""
    find = (find or "").strip()
    _require_query(find)
    if repl is None:
        raise ValueError("replace text required")
    kind = (kind or "").strip().lower() or None
    if kind == "binary":
        raise ValueError("binary search does not replace")
    edits = []
    seen = set()
    for hit in _collect(app, find, kind):
        for ed in hit.get("edits") or []:
            token = (ed["key"], ed["store"], ed.get("block"), ed["name"], ed["field"])
            if token in seen:
                continue
            if find.lower() not in (ed.get("value") or "").lower():
                continue
            seen.add(token)
            edits.append(ed)
    if not edits:
        raise ValueError("nothing to replace")
    if len(edits) > REPLACE_CAP:
        raise ValueError("too many fields (%d); narrow the kind" % len(edits))
    texts = {}
    def_ops = {}
    item_ops = []
    for ed in edits:
        if ed["store"] == "item":
            item_ops.append(ed)
        else:
            def_ops.setdefault(ed["key"], []).append(ed)
    for key, ops in def_ops.items():
        text = rtkdef.inflate_text(app.read(key))
        for op in ops:
            new_val = _ireplace(op["value"], find, repl)
            text = rtkdef.replace_field(
                text, op["block"], op["name"], op["field"], new_val,
                parent_kind=op.get("parent_kind"),
                parent_name=op.get("parent_name"))
        texts[key] = text
    if item_ops:
        cat = app.items
        for op in item_ops:
            new_val = _ireplace(op["value"], find, repl)
            cat.apply(op["name"], {op["field"]: new_val})
        texts[item_ops[0]["key"]] = cat.to_text()
    return texts, len(edits)


def _require_query(q):
    if not q:
        raise ValueError("type a search")
    if len(q) < 2 and not q.isdigit():
        raise ValueError("type at least 2 characters")


def _contains(hay, q):
    return q.lower() in (hay or "").lower()


def _num_eq(value, q):
    if not q.isdigit():
        return False
    try:
        return int(value) == int(q)
    except (TypeError, ValueError):
        return False


def _ireplace(text, find, repl):
    return re.sub(re.escape(find), lambda _m: repl, text or "", flags=re.I)


def _needle(q):
    body = q[4:].strip() if q.lower().startswith("hex:") else q
    compact = re.sub(r"\s+", "", body)
    if re.fullmatch(r"[0-9a-fA-F]{4,}", compact) and len(compact) % 2 == 0 and (
            q.lower().startswith("hex:") or " " in body):
        return bytes.fromhex(compact), True
    return q.encode("latin-1", "replace"), False


def _find_bytes(raw, needle, exact):
    if exact:
        return raw.find(needle)
    low = raw.lower()
    return low.find(needle.lower())


def _snippet(raw, at, n):
    start = max(0, at - 24)
    end = min(len(raw), at + n + 24)
    chunk = raw[start:end].decode("latin-1", "replace")
    return chunk.replace("\r", " ").replace("\n", " ")


def _edit(store, key, name, field, value, block="", parent_kind=None, parent_name=None):
    return {
        "store": store,
        "key": key,
        "block": block,
        "name": name,
        "field": field,
        "value": value or "",
        "parent_kind": parent_kind,
        "parent_name": parent_name,
    }


def _push(out, kind, name, snippet, edits, **extra):
    if not snippet and not extra.get("force"):
        return
    row = {
        "kind": kind,
        "name": name,
        "id": extra.get("id") or name,
        "label": extra.get("label") or name,
        "snippet": snippet,
        "chapter": extra.get("chapter"),
        "scene": extra.get("scene") or "",
        "view": extra.get("view") or "",
        "itemKind": extra.get("itemKind") or "",
        "character": extra.get("character") or "",
        "edits": edits,
    }
    out.append(row)


def _collect(app, q, kind):
    out = []
    if kind in (None, "character"):
        _characters(app, q, out)
    if kind in (None, "item"):
        _items(app, q, out)
    if kind in (None, "dialog"):
        _dialog(app, q, out)
    if kind in (None, "scene"):
        _scenes(app, q, out)
    if kind in (None, "model"):
        _models(app, q, out)
    if kind in (None, "shop"):
        _shops(app, q, out)
    return out


def _characters(app, q, out):
    for c in app.combat.characters:
        edits = []
        bits = []
        if _contains(c.get("name"), q):
            bits.append(c["name"])
        if _contains(c.get("class_token") or c.get("class"), q):
            bits.append(c.get("class_token") or "")
        if _contains(c.get("model"), q):
            bits.append("model " + (c.get("model") or ""))
        if _contains(c.get("nationality"), q):
            bits.append(c.get("nationality") or "")
            edits.append(_edit(
                "def", c.get("key"), c["name"], "Nationality",
                c.get("nationality"), block="CharacterDef"))
        if _num_eq(c.get("level"), q):
            bits.append("level " + str(c.get("level")))
        if _num_eq(c.get("health"), q):
            bits.append("health " + str(c.get("health")))
        if _num_eq(c.get("spell_points"), q):
            bits.append("spell " + str(c.get("spell_points")))
        if _num_eq(c.get("experience"), q):
            bits.append("exp " + str(c.get("experience")))
        if not bits:
            continue
        _push(out, "character", c["name"], " · ".join(bits), edits,
              label=c["name"])


def _items(app, q, out):
    cat = app.items
    key = None
    import rtkitems
    key = rtkitems.CATALOG_KEY
    for it in cat.items:
        name = it.get("Item_Name") or ""
        label = it.get("AS_Tag") or it.get("UA_Tag") or name
        edits = []
        bits = []
        if _contains(name, q) or _contains(label, q):
            bits.append(label)
        if _contains(it.get("SubCategory"), q):
            bits.append(it.get("SubCategory") or "")
        if _num_eq(it.get("Price"), q):
            bits.append("price " + str(it.get("Price")))
        for field in ("UA_Tag", "AS_Tag"):
            val = it.get(field) or ""
            if val and _contains(val, q):
                edits.append(_edit("item", key, name, field, val))
                if val not in bits:
                    bits.append(field + " " + val)
        if not bits:
            continue
        _push(out, "item", name, " · ".join(bits), edits,
              label=label, itemKind=cat.kind_of(it))


def _dialog(app, q, out):
    for n in app.dialog.nodes:
        edits = []
        bits = []
        if _contains(n.get("name"), q):
            bits.append(n["name"])
        if _contains(n.get("scene"), q):
            bits.append(n.get("scene") or "")
        menu = n.get("menu_text") or ""
        journal = n.get("journal_text") or ""
        if menu and _contains(menu, q):
            bits.append(menu)
            edits.append(_edit(
                "def", n.get("key"), n["name"], "MenuText", menu,
                block="ConversationDef"))
        if journal and _contains(journal, q):
            bits.append(journal)
            edits.append(_edit(
                "def", n.get("key"), n["name"], "JournalText", journal,
                block="ConversationDef"))
        if _num_eq(n.get("chapter"), q):
            bits.append("chapter " + str(n.get("chapter")))
        if not bits:
            continue
        _push(out, "dialog", n["name"], " · ".join(bits)[:180], edits,
              id=n.get("id"), label=n["name"],
              chapter=n.get("chapter"), scene=n.get("scene") or "")


def _scenes(app, q, out):
    for ch in app.scenes.chapters:
        for sc in ch["scenes"]:
            edits = []
            bits = []
            if _contains(sc.get("id"), q):
                bits.append(sc["id"])
            desc = sc.get("desc") or ""
            if desc and _contains(desc, q):
                bits.append(desc)
                edits.append(_edit(
                    "def", sc.get("loc_key"), sc["id"], "Desc", desc,
                    block="Scene"))
            if _num_eq(sc.get("num"), q):
                bits.append("#" + str(sc.get("num")))
            view = ""
            for vw in sc.get("views") or []:
                if _contains(vw.get("id"), q) or _contains(vw.get("bg"), q):
                    bits.append(vw.get("id") or "")
                    view = vw.get("id") or view
            if not bits:
                continue
            _push(out, "scene", sc["id"], " · ".join(bits)[:180], edits,
                  label=sc["id"], chapter=ch["id"], scene=sc["id"], view=view)


def _models(app, q, out):
    chars = app.characters
    users = {}
    for c in app.combat.characters:
        model = c.get("model") or ""
        resolved = chars.resolve_model_name(model) or model
        users.setdefault(resolved.lower(), c["name"])
        users.setdefault(model.lower(), c["name"])
    for rec in chars.models.values():
        bits = []
        name = rec.get("name") or ""
        if _contains(name, q):
            bits.append(name)
        if _contains(rec.get("adf"), q):
            bits.append(rec.get("adf") or "")
        if _contains(rec.get("palette_bmp"), q):
            bits.append(rec.get("palette_bmp") or "")
        if _contains(rec.get("head_sprite"), q):
            bits.append(rec.get("head_sprite") or "")
        if _num_eq(rec.get("look"), q):
            bits.append("look " + str(rec.get("look")))
        if not bits:
            continue
        _push(out, "model", name, " · ".join(bits), [],
              label=name, character=users.get(name.lower(), ""))


def _shops(app, q, out):
    for s in app.shops.shops:
        edits = []
        bits = []
        if _contains(s.get("name"), q):
            bits.append(s["name"])
        city = (s.get("fields") or {}).get("City") or ""
        gold = (s.get("fields") or {}).get("Gold") or ""
        if city and _contains(city, q):
            bits.append(city)
            edits.append(_edit(
                "def", s.get("key"), s["name"], "City", city, block="Shop"))
        if _num_eq(gold, q):
            bits.append("gold " + str(gold))
        if not bits:
            continue
        _push(out, "shop", s["name"], " · ".join(bits), edits, label=s["name"])
