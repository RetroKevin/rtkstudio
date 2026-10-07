"""A local web app for browsing and editing Return to Krondor's assets.

Serves on localhost only, from the standard library alone. The game install
is opened read-only; edits go into a mod project directory and are only
materialised when you build, which writes a modified copy elsewhere.

    python tools/viewer.py --game ".." --mod mods/example

Then open http://127.0.0.1:8765/.
"""

import argparse
import json
import mimetypes
import re
import subprocess
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app_paths
import encoders
import preview
from assetdb import AssetDB

WEB_ROOT = app_paths.web_root()
PAGE_SIZE = 200


class Server(ThreadingHTTPServer):
    """A server that refuses to share its port.

    http.server sets allow_reuse_address, and on Windows that lets a second
    instance bind a port something else is already listening on. Both then
    appear to start and connections land on either one, which is impossible
    to diagnose from the browser. Better to fail loudly on the second.
    """

    allow_reuse_address = False
    daemon_threads = True


class App:
    """Shared state behind the request handlers."""

    def __init__(self, game: Path, cache: Path, mod=None, rebuild=False):
        self.game = Path(game)
        self.db = AssetDB.open(self.game, cache, rebuild,
                               lambda what, n: print("  indexed %-18s %d" % (what, n)))
        import palettemap
        palettemap.load_header(self.game / "RTKRES.h")
        self.palettes = preview.Palettes(self.db)
        self.mod = mod
        self.lock = threading.Lock()
        self._chars = None
        self._backdrops = None
        self._items = None
        self._scenes = None
        self._ui = None
        self._combat = None
        self._traps = None
        self._fx = None
        self._alchemy = None
        self._shops = None
        self._dialog = None

    @property
    def characters(self):
        if self._chars is None:
            import rtkcharacter
            db = _Overridden(self.db, self.mod) if self.mod else self.db
            self._chars = rtkcharacter.CharacterIndex(db)
        return self._chars

    @property
    def items(self):
        if self._items is None:
            import rtkitems
            self._items = rtkitems.ItemCatalog.load(self.read(rtkitems.CATALOG_KEY))
        return self._items

    def invalidate_studios(self):
        self._scenes = None
        self._ui = None
        self._combat = None
        self._traps = None
        self._fx = None
        self._alchemy = None
        self._shops = None
        self._dialog = None
        self._items = None

    @property
    def scenes(self):
        if self._scenes is None:
            import rtkscene
            self._scenes = rtkscene.SceneIndex(self)
        return self._scenes

    @property
    def ui(self):
        if self._ui is None:
            import rtkui
            self._ui = rtkui.UIIndex(self)
        return self._ui

    @property
    def combat(self):
        if self._combat is None:
            import rtkcombat
            self._combat = rtkcombat.CombatIndex(self)
        return self._combat

    @property
    def traps(self):
        if self._traps is None:
            import rtktrap
            self._traps = rtktrap.TrapIndex(self)
        return self._traps

    @property
    def fx(self):
        if self._fx is None:
            import rtkfx
            self._fx = rtkfx.FxIndex(self)
        return self._fx

    @property
    def alchemy(self):
        if self._alchemy is None:
            import rtkalchemy
            self._alchemy = rtkalchemy.AlchemyIndex(self)
        return self._alchemy

    @property
    def shops(self):
        if self._shops is None:
            import rtkshops
            self._shops = rtkshops.ShopIndex(self)
        return self._shops

    @property
    def dialog(self):
        if self._dialog is None:
            import rtkdialog
            self._dialog = rtkdialog.DialogIndex(self)
        return self._dialog

    def read(self, key) -> bytes:
        """Asset bytes, preferring a mod override when one exists."""
        if self.mod is not None:
            data = self.mod.read_override(key)
            if data is not None:
                return data
        return self.db.read(key)

    def render(self, key, palette=None, transparent=False, remap=None,
               want_body=True):
        with self.lock:
            db = _Overridden(self.db, self.mod) if (
                self.mod is not None and self.mod.read_override(key) is not None
            ) else self.db
            return preview.render(db, key, palette, transparent=transparent,
                                  remap=remap, want_body=want_body)

    def list_backdrops(self):
        """640x480 .di_ paintings in t3d/Bkgnd/S########.t3d, grouped by scene."""
        if self._backdrops is not None:
            return self._backdrops
        by = {}
        for a in self.db.assets:
            if not a.name.lower().endswith(".di_"):
                continue
            parts = a.key.replace("\\", "/").split("/")
            scene = next((p for p in parts if re.match(r"^S\d{8}\.t3d$", p, re.I)), None)
            if scene is None:
                continue
            sid = Path(scene).stem.upper()
            stem = Path(a.name).stem
            m = re.match(r"^(\d{4})(\d{2})cm$", stem, re.I)
            label = "View %s" % m.group(2) if m else stem
            by.setdefault(sid, []).append({
                "key": a.key, "name": stem, "label": label,
            })
        scenes = []
        for sid in sorted(by):
            views = sorted(by[sid], key=lambda v: v["name"].lower())
            m = re.match(r"^S(\d{4})(\d{4})$", sid)
            if m:
                label = "Ch.%s scene %s" % (int(m.group(1)), m.group(2))
            else:
                label = sid
            scenes.append({
                "id": sid,
                "label": label,
                "views": views,
            })
        self._backdrops = scenes
        return scenes


class _Overridden:
    """Presents the AssetDB with mod overrides swapped in, for previewing."""

    def __init__(self, db, mod):
        self._db = db
        self._mod = mod

    def __getattr__(self, name):
        return getattr(self._db, name)

    def read(self, key):
        data = self._mod.read_override(key)
        return self._db.read(key) if data is None else data


def _clip_text(body, limit=400000):
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
    if len(text) <= limit:
        return text, False
    return text[:limit], True


class Handler(BaseHTTPRequestHandler):
    app: App = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # the default logger writes a line per request; far too noisy

    # ---- plumbing -------------------------------------------------------

    def _send(self, code, ctype, body: bytes, extra=None):
        extra = dict(extra or {})
        total = len(body)
        rng = self._range(total) if ctype.startswith(("audio/", "video/")) else None
        if rng is not None:
            start, end = rng
            extra["Content-Range"] = "bytes %d-%d/%d" % (start, end, total)
            extra.setdefault("Accept-Ranges", "bytes")
            body = body[start:end + 1]
            code = 206
        elif ctype.startswith(("audio/", "video/")):
            extra.setdefault("Accept-Ranges", "bytes")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _range(self, length):
        header = self.headers.get("Range") or ""
        if not header.startswith("bytes=") or length <= 0:
            return None
        spec = header.split("=", 1)[1].split(",")[0].strip()
        try:
            if spec.startswith("-"):
                start = max(0, length + int(spec))
                end = length - 1
            else:
                a, _, b = spec.partition("-")
                start = int(a) if a else 0
                end = int(b) if b else length - 1
        except ValueError:
            return None
        end = min(end, length - 1)
        if start < 0 or start > end:
            return None
        return start, end

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj).encode("utf-8"))

    def _error(self, code, message):
        self._json({"error": message}, code)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # ---- routing --------------------------------------------------------

    def do_GET(self):
        try:
            self._route_get()
        except KeyError as exc:
            self._error(404, "not found: %s" % exc)
        except Exception:
            traceback.print_exc()
            self._error(500, traceback.format_exc(limit=3))

    do_HEAD = do_GET

    def do_POST(self):
        try:
            self._route_post()
        except KeyError as exc:
            self._error(404, "not found: %s" % exc)
        except Exception:
            traceback.print_exc()
            self._error(500, traceback.format_exc(limit=3))

    def _route_get(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path

        if path == "/":
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])

        if path == "/api/palettes":
            return self._json({"names": self.app.palettes.names()})

        if path == "/api/palettes/table":
            name = unquote(q.get("name") or "")
            pal = self.app.palettes.get(name or None)
            return self._json({
                "name": name or self.app.palettes.DEFAULT,
                "palette": [list(c) for c in pal],
            })

        if path == "/api/counts":
            c = self.app.db.counts()
            c["game"] = str(self.app.game)
            c["palettes"] = self.app.palettes.names()
            c["mod"] = self.app.mod.describe() if self.app.mod else None
            return self._json(c)

        if path == "/api/history":
            if self.app.mod is None:
                return self._json({
                    "cursor": -1, "entries": [],
                    "can_undo": False, "can_redo": False,
                })
            return self._json(self.app.mod.history_state())

        if path == "/api/find":
            import rtkfind
            try:
                if (q.get("mode") or "") == "binary" or (q.get("kind") or "") == "binary":
                    doc = rtkfind.binary_search(self.app, unquote(q.get("q") or ""))
                else:
                    doc = rtkfind.search(
                        self.app, unquote(q.get("q") or ""), q.get("kind") or None)
            except ValueError as exc:
                return self._error(400, str(exc))
            return self._json(doc)

        if path == "/api/search":
            offset = int(q.get("offset", 0))
            limit = min(int(q.get("limit", PAGE_SIZE)), 1000)
            hits = self.app.db.search(q.get("q", ""), q.get("kind") or None,
                                      q.get("source") or None)
            page = hits[offset:offset + limit]
            overridden = self.app.mod.overridden() if self.app.mod else set()
            return self._json({
                "total": len(hits),
                "offset": offset,
                "items": [dict(a.as_dict(), modified=a.key in overridden)
                          for a in page],
            })

        if path == "/api/asset":
            key = unquote(q.get("key", ""))
            asset = self.app.db.get(key)
            if asset is None:
                raise KeyError(key)
            ctype, body, meta = self.app.render(
                key, q.get("palette") or None, want_body=False)
            meta["content_type"] = ctype
            meta["asset"] = asset.as_dict()
            meta["mode"] = encoders.mode_for(asset)
            meta["editable"] = bool(self.app.mod) and self.app.mod.can_edit(asset)
            meta["modified"] = bool(self.app.mod) and self.app.mod.read_override(key) is not None
            if ctype.startswith("text/"):
                meta["text"] = body.decode("utf-8", "replace")
            return self._json(meta)

        if path == "/api/diff":
            return self._asset_diff(unquote(q.get("key", "")))

        if path == "/api/preview":
            key = unquote(q.get("key", ""))
            remap = unquote(q.get("remap") or "") or None
            if q.get("original") == "1":
                ctype, body, _meta = preview.render(
                    self.app.db, key, q.get("palette") or None,
                    transparent=q.get("transparent") == "1", remap=remap)
            else:
                ctype, body, _meta = self.app.render(
                    key, q.get("palette") or None,
                    transparent=q.get("transparent") == "1",
                    remap=remap)
            return self._send(200, ctype, body)

        if path == "/api/download":
            key = unquote(q.get("key", ""))
            name = Path(self.app.db.get(key).name).name if self.app.db.get(key) else "asset.bin"
            return self._send(200, "application/octet-stream", self.app.read(key),
                              {"Content-Disposition": 'attachment; filename="%s"' % name})

        if path == "/api/character":
            return self._json({"characters": self.app.characters.list_characters(),
                               "default": "James"})

        if path == "/api/backdrops":
            return self._json({"scenes": self.app.list_backdrops()})

        if path == "/api/character/anims":
            name = q.get("name") or "James"
            return self._json({
                "character": name,
                "anims": self.app.characters.compatible_anims(name),
                "conversation_bind": self.app.characters.conversation_bind(name),
            })

        if path == "/api/character/kit":
            name = q.get("name") or "James"
            kit = self._armor_kit(q)
            saved = self.app.mod.read_kit(name) if self.app.mod else None
            regions = self._regions(q, (saved or {}).get("regions"))
            return self._json(self.app.characters.kit_info(
                name, armor_kit=kit, regions=regions))

        if path == "/api/character/pixels":
            key = unquote(q.get("key") or "")
            remap = unquote(q.get("remap") or "") or None
            raw = self.app.read(key)
            import preview
            pal = None
            if remap:
                try:
                    if remap.startswith(("t3d/", "file/", "res/")) or \
                            remap.lower().endswith(".bmp"):
                        pal = preview.bmp_palette(self.app.read(remap))
                    else:
                        pal = self.app.palettes.get(remap)
                except Exception:
                    pal = None
            if raw[:2] != b"BM" and pal is None:
                import palettemap
                asset = self.app.db.get(key)
                rid = palettemap.asset_id(asset)
                pal = self.app.palettes.get(
                    (palettemap.palette_for(rid) if rid is not None else None)
                    or "pIntfacePal")
            w, h, px, pal = preview.decode_pixels(raw, pal)
            return self._json({
                "key": key, "width": w, "height": h,
                "pixels": list(px),
                "palette": [list(c) for c in pal],
            })

        if path == "/api/items":
            kind = q.get("kind") or None
            sub = q.get("sub") or None
            clas = q.get("class") or None
            gear = unquote(q.get("gear") or "") or None
            slot = q.get("slot") or None
            query = unquote(q.get("q") or "")
            cat = self.app.items
            if gear:
                items = cat.match_gear(gear)
            elif slot:
                items = cat.match_slot(slot)
            else:
                items = cat.list(kind=kind, q=query, sub=sub, classification=clas)
            groups = cat.kind_groups()
            return self._json({
                "items": items,
                "kinds": [k["id"] for g in groups for k in g["kinds"]],
                "kind_groups": groups,
                "qualities": list(__import__("rtkitems").QUALITIES),
                "modifiers": __import__("rtkitems").modifier_catalog(),
                "icons": __import__("rtkitems").list_inventory_icons(self.app.ui),
            })

        if path == "/api/items/item":
            name = unquote(q.get("name") or "")
            rec = self.app.items.detail(name, ui=self.app.ui,
                                       character=q.get("character") or None)
            rec["mesh_scale"] = self._item_scale(name)
            return self._json(rec)

        if path == "/api/items/art":
            name = q.get("name") or "James"
            item = unquote(q.get("item") or "") or None
            gear = unquote(q.get("gear") or "") or None
            slot = q.get("slot") or None
            kit = self._armor_kit(q)
            sub = unquote(q.get("sub") or "") or None
            look_raw = q.get("look")
            look = None
            if look_raw not in (None, ""):
                try:
                    look = int(look_raw)
                except ValueError:
                    look = None
            sheets = []
            if item:
                sheets.extend(self.app.items.icon_sheets(
                    item, self.app.ui, character=name))
            art = {"character": name, "sheets": [], "palette": [],
                   "palette_key": ""}
            if gear or slot:
                try:
                    art = self.app.characters.item_art(
                        name, gear=gear, slot=slot, armor_kit=kit,
                        subcategory=sub, look_code=look)
                except KeyError:
                    pass
            seen = {s.get("key") for s in sheets if s.get("key")}
            for s in art.get("sheets") or []:
                if s.get("key") and s["key"] not in seen:
                    seen.add(s["key"])
                    sheets.append(s)
            art["sheets"] = sheets
            return self._json(art)

        if path == "/api/character/scene":
            name = q.get("name") or "James"
            anim = q.get("anim") or None
            if anim:
                anim = unquote(anim)
            kit = self._armor_kit(q)
            saved = self.app.mod.read_kit(name) if self.app.mod else None
            regions = self._regions(q, (saved or {}).get("regions"))
            weapon = unquote(q.get("weapon") or "") or None
            shield = unquote(q.get("shield") or "") or None
            sheathed = q.get("sheathed") == "1"
            item_scale = self._item_scale_query(q)
            item_slot = q.get("item_slot") or None
            palette = unquote(q.get("palette") or "") or None
            try:
                face_expr = int(q.get("face_expr") or 0)
            except ValueError:
                face_expr = 0
            return self._json(self.app.characters.scene(
                name, anim, kit=kit, weapon=weapon,
                shield=shield, sheathed=sheathed, regions=regions,
                item_scale=item_scale, item_slot=item_slot,
                palette=palette, face_expr=face_expr))

        if path == "/api/scenes":
            return self._json({"chapters": self.app.scenes.list_chapters()})

        if path == "/api/scenes/view":
            return self._json(self.app.scenes.view(
                q.get("chapter") or "1",
                unquote(q.get("scene") or ""),
                unquote(q.get("view") or "Vw1")))

        if path == "/api/scenes/mab":
            key = unquote(q.get("key") or "")
            return self._json(self.app.scenes.mab_info(key))

        if path == "/api/ui":
            return self._json({"screens": self.app.ui.list_screens()})

        if path == "/api/ui/screen":
            return self._json(self.app.ui.screen(
                unquote(q.get("id") or "0x3"),
                show_all=q.get("all") in ("1", "true", "yes")))

        if path == "/api/ui/catalog":
            try:
                limit = int(q.get("limit") or 80)
            except ValueError:
                limit = 80
            return self._json({
                "items": self.app.ui.catalog(
                    kind=unquote(q.get("kind") or "BITMAP"),
                    q=unquote(q.get("q") or ""),
                    limit=limit),
            })

        if path == "/api/combat":
            return self._json({"fights": self.app.combat.list_fights()})

        if path == "/api/combat/fight":
            return self._json(self.app.combat.fight(unquote(q.get("name") or "")))

        if path == "/api/combat/classes":
            return self._json({
                "characters": self.app.combat.list_classes(unquote(q.get("q") or "")),
            })

        if path == "/api/combat/character":
            return self._json(self.app.combat.character(unquote(q.get("name") or "")))

        if path == "/api/combat/models":
            return self._json({"models": self.app.combat.list_models()})

        if path == "/api/combat/sprites":
            name = unquote(q.get("name") or "")
            return self._json({
                "sprites": self.app.characters.model_sprites(name),
                "palettes": self.app.characters.list_palettes(),
                "head_sprites": self.app.characters.list_head_sprites(),
            })

        if path == "/api/combat/xp":
            import rtkcombat
            cls = unquote(q.get("class") or "Thief")
            try:
                pool = int(q.get("pool") or "0")
            except ValueError:
                pool = 0
            return self._json(rtkcombat.simulate_xp(cls, pool))

        if path == "/api/traps":
            return self._json(self.app.traps.list_layouts())

        if path == "/api/traps/instances":
            return self._json({
                "instances": self.app.traps.list_instances(unquote(q.get("q") or "")),
            })

        if path == "/api/fx/tracks":
            return self._json({"tracks": self.app.fx.list_tracks(unquote(q.get("q") or ""))})

        if path == "/api/fx/bex":
            key = unquote(q.get("key") or "")
            if key:
                return self._json(self.app.fx.bex(key))
            return self._json({"files": self.app.fx.list_bex(unquote(q.get("q") or ""))})

        if path == "/api/fx/sprites":
            return self._json({"sprites": self.app.fx.list_sprites(unquote(q.get("q") or ""))})

        if path == "/api/fx/sprite":
            return self._json(self.app.fx.sprite(unquote(q.get("name") or "")))

        if path == "/api/fx/spells":
            return self._json({"spells": self.app.fx.list_spells(unquote(q.get("q") or ""))})

        if path == "/api/fx/spell":
            return self._json(self.app.fx.spell(unquote(q.get("name") or "")))

        if path == "/api/fx/launches":
            return self._json({
                "launches": self.app.fx.list_launches(unquote(q.get("q") or "")),
            })

        if path == "/api/fx/items":
            return self._json({
                "items": self.app.fx.list_item_casts(unquote(q.get("q") or "")),
            })

        if path == "/api/alchemy":
            return self._json({
                "formulas": self.app.alchemy.list_formulas(),
                "bench": self.app.alchemy.bench(),
                "icons": self.app.alchemy.list_icons(),
            })

        if path == "/api/alchemy/formula":
            return self._json(self.app.alchemy.formula(int(q.get("id") or "0")))

        if path == "/api/alchemy/odds":
            import rtkalchemy
            try:
                skill = int(q.get("skill") or "0")
            except ValueError:
                skill = 0
            try:
                state = int(q.get("state") or "3")
            except ValueError:
                state = 3
            try:
                ring = int(q.get("ring") or "0")
            except ValueError:
                ring = 0
            try:
                roll = int(q.get("roll") or "1")
            except ValueError:
                roll = 1
            return self._json({
                "odds": rtkalchemy.brew_odds(skill, state, ring),
                "disaster": rtkalchemy.disaster_for(max(1, min(100, roll))),
                "states": rtkalchemy.STATES,
            })

        if path == "/api/shops":
            return self._json({"shops": self.app.shops.list_shops(unquote(q.get("q") or ""))})

        if path == "/api/shops/shop":
            return self._json(self.app.shops.shop(unquote(q.get("name") or "")))

        if path == "/api/shops/loadouts":
            return self._json({
                "loadouts": self.app.shops.list_loadouts(unquote(q.get("q") or "")),
            })

        if path == "/api/shops/loadout":
            return self._json(self.app.shops.loadout(unquote(q.get("name") or "")))

        if path == "/api/dialog":
            chapter = q.get("chapter")
            return self._json({
                "chapters": self.app.dialog.chapters(),
                "scenes": self.app.dialog.scenes(chapter if chapter not in (None, "") else None),
                "nodes": self.app.dialog.list(
                    q=unquote(q.get("q") or ""),
                    chapter=chapter if chapter not in (None, "") else None,
                    scene=unquote(q.get("scene") or ""),
                    role=unquote(q.get("role") or "")),
            })

        if path == "/api/dialog/node":
            ident = unquote(q.get("id") or q.get("name") or "")
            return self._json(self.app.dialog.node(ident))

        raise KeyError(path)

    def _route_post(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path

        if self.app.mod is None:
            return self._error(400, "no mod project; restart with --mod DIR")

        if path == "/api/override":
            key = unquote(q.get("key", ""))
            asset = self.app.db.get(key)
            if asset is None:
                raise KeyError(key)
            payload = self._body()
            as_text = q.get("text") == "1"
            # Index an image edit against whatever palette was on screen.
            pal = q.get("palette")
            palette = self.app.palettes.get(pal) if pal else None
            n = self.app.mod.write_override(asset, payload, as_text=as_text,
                                            original=self.app.db.read(key),
                                            palette=palette)
            self.app.invalidate_studios()
            return self._json({"ok": True, "key": key, "bytes": n,
                               "palette": pal})

        if path == "/api/revert":
            key = unquote(q.get("key", ""))
            self.app.mod.clear_override(key)
            self.app.invalidate_studios()
            return self._json({"ok": True, "key": key})

        if path == "/api/history/undo":
            return self._history_step("undo")

        if path == "/api/history/redo":
            return self._history_step("redo")

        if path == "/api/history/jump":
            doc = json.loads(self._body() or b"{}")
            return self._history_step("jump", doc.get("cursor", -1))

        if path == "/api/find/replace":
            return self._find_replace(json.loads(self._body() or b"{}"))

        if path == "/api/build":
            out = Path(q.get("out") or self.app.mod.default_output())
            report = self.app.mod.build(self.app.db, out)
            return self._json(report)

        if path == "/api/play":
            return self._play()

        if path == "/api/patch":
            mod = self.app.mod
            out = Path(q.get("out") or
                       Path("out/patches") / (mod.meta["name"] + ".rtkmod.zip"))
            return self._json(mod.export_patch(out))

        if path == "/api/meta":
            mod = self.app.mod
            mod.meta.update({k: v for k, v in q.items()
                             if k in ("name", "version", "description")})
            mod._save_meta()
            return self._json(mod.describe())

        if path == "/api/character/save":
            return self._char_save(json.loads(self._body() or b"{}"))

        if path == "/api/character/duplicate":
            return self._char_duplicate(json.loads(self._body() or b"{}"))

        if path == "/api/character/kit":
            return self._kit_save(json.loads(self._body() or b"{}"))

        if path == "/api/character/sheet":
            return self._sheet_save(json.loads(self._body() or b"{}"))

        if path == "/api/character/palette":
            return self._palette_save(json.loads(self._body() or b"{}"))

        if path == "/api/items/item":
            return self._item_save(json.loads(self._body() or b"{}"))

        if path == "/api/scenes/mab":
            return self._scene_mab_save(json.loads(self._body() or b"{}"))

        if path == "/api/scenes/save":
            return self._studio_fields_save(json.loads(self._body() or b"{}"))

        if path == "/api/scenes/teleport":
            return self._scene_teleport_save(json.loads(self._body() or b"{}"))

        if path == "/api/scenes/move":
            return self._scene_move_save(json.loads(self._body() or b"{}"))

        if path == "/api/scenes/viewsave":
            return self._scene_view_save(json.loads(self._body() or b"{}"))

        if path == "/api/combat/character":
            return self._combat_char_save(json.loads(self._body() or b"{}"))

        if path == "/api/combat/model":
            return self._combat_model_save(json.loads(self._body() or b"{}"))

        if path == "/api/combat/model/duplicate":
            return self._combat_model_duplicate(json.loads(self._body() or b"{}"))

        if path == "/api/traps/instance":
            return self._trap_save(json.loads(self._body() or b"{}"))

        if path == "/api/shops/shop":
            return self._shop_save(json.loads(self._body() or b"{}"))

        if path == "/api/shops/loadout":
            return self._loadout_save(json.loads(self._body() or b"{}"))

        if path == "/api/dialog/node":
            return self._dialog_save(json.loads(self._body() or b"{}"))

        if path == "/api/dialog/add":
            return self._dialog_add(json.loads(self._body() or b"{}"))

        if path == "/api/fx/spell":
            return self._spell_save(json.loads(self._body() or b"{}"))

        if path == "/api/fx/bex":
            return self._bex_sprite_save(json.loads(self._body() or b"{}"))

        if path == "/api/alchemy/item":
            return self._alchemy_item_save(json.loads(self._body() or b"{}"))

        if path == "/api/ui/layout":
            return self._ui_layout_save(json.loads(self._body() or b"{}"))

        if path == "/api/ui/ref":
            return self._ui_ref_save(json.loads(self._body() or b"{}"))

        if path == "/api/ui/cel":
            return self._ui_cel_save(json.loads(self._body() or b"{}"))

        if path == "/api/ui/hotspot":
            return self._ui_hotspot_save(json.loads(self._body() or b"{}"))

        if path == "/api/ui/queue":
            return self._ui_queue_save(json.loads(self._body() or b"{}"))

        if path == "/api/ui/text":
            return self._ui_text_save(json.loads(self._body() or b"{}"))

        if path == "/api/ui/action":
            return self._ui_action_save(json.loads(self._body() or b"{}"))

        raise KeyError(path)

    def _armor_kit(self, q):
        import rtkcharacter
        kit = {}
        for slot, _tokens, _label in rtkcharacter.ARMOR_SLOTS:
            raw = q.get("armor_" + slot) or q.get(slot)
            if raw is None:
                continue
            try:
                kit[slot] = int(raw)
            except ValueError:
                pass
        if not kit and q.get("armor"):
            try:
                n = int(q.get("armor"))
                kit = {s: n for s, _t, _l in rtkcharacter.ARMOR_SLOTS}
            except ValueError:
                pass
        return kit

    def _regions(self, q, saved=None):
        import rtkcharacter
        regions = rtkcharacter.CharacterIndex._norm_regions(saved)
        for rid, _lab, _tok in rtkcharacter.KIT_REGIONS:
            raw = q.get("scale_" + rid)
            raw_w = q.get("scale_" + rid + "_w")
            if raw is not None:
                try:
                    regions[rid]["length"] = rtkcharacter._clamp_scale(raw)
                except (TypeError, ValueError):
                    pass
            if raw_w is not None:
                try:
                    regions[rid]["width"] = rtkcharacter._clamp_scale(raw_w)
                except (TypeError, ValueError):
                    pass
        return regions

    def _kit_save(self, doc):
        import rtkcharacter
        name = doc.get("character") or "James"
        regions = rtkcharacter.CharacterIndex._norm_regions(doc.get("regions"))
        path = self.app.mod.write_kit(name, {"character": name, "regions": regions})
        return self._json({"ok": True, "character": name, "regions": regions,
                           "path": path})

    def _sheet_save(self, doc):
        import encoders
        import preview
        if self.app.mod is None:
            raise ValueError("no mod project; restart with --mod or the desktop app")
        key = doc.get("key") or ""
        asset = self.app.db.get(key)
        if asset is None:
            raise KeyError(key)
        original = self.app.read(key)
        width = int(doc.get("width") or 0)
        height = int(doc.get("height") or 0)
        pixels = bytes(max(0, min(255, int(p))) for p in (doc.get("pixels") or []))
        if width <= 0 or height <= 0 or len(pixels) != width * height:
            raise ValueError("pixel count %d != %dx%d" % (len(pixels), width, height))
        colors = doc.get("palette")
        pal = None
        if colors:
            pal = [tuple(c[:3]) for c in colors[:256]]
            if len(pal) < 256:
                pal = pal + [(0, 0, 0)] * (256 - len(pal))
        res_bitmap = (asset.restype == "BITMAP") or (original[:2] != b"BM")
        if res_bitmap:
            import struct
            import imagecodec
            flags = f12 = f16 = res_id = 0
            if len(original) >= 24:
                _w, _h, flags, f12, f16, res_id = struct.unpack_from("<6I", original)
            raw = imagecodec.encode_dib_bitmap(
                width, height, pixels, pal,
                flags=flags & ~0x80, field12=f12, field16=f16, res_id=res_id)
        else:
            if pal is None:
                _w, _h, _px, pal = preview.bmp_indexed(original)
            raw = encoders._windows_bmp(width, height, pixels, pal)
        n = self.app.mod.write_override(asset, raw, original=original)
        return self._json({"ok": True, "key": key, "bytes": n})

    def _palette_save(self, doc):
        import encoders
        key = doc.get("key") or ""
        asset = self.app.db.get(key)
        if asset is None:
            raise KeyError(key)
        colors = doc.get("palette") or []
        if len(colors) < 256:
            colors = list(colors) + [[0, 0, 0]] * (256 - len(colors))
        pal = [tuple(c[:3]) for c in colors[:256]]
        raw = encoders._windows_bmp(1, 1, bytes([0]), pal)
        n = self.app.mod.write_override(asset, raw, original=self.app.db.read(key))
        return self._json({"ok": True, "key": key, "bytes": n})

    def _item_scale(self, name):
        import rtkcharacter
        saved = self.app.mod.read_item(name) if self.app.mod else None
        return rtkcharacter._norm_item_scale((saved or {}).get("mesh_scale"))

    def _item_scale_query(self, q):
        import rtkcharacter
        raw = {}
        if q.get("iscale") is not None:
            raw["length"] = q.get("iscale")
        if q.get("iscale_w") is not None:
            raw["width"] = q.get("iscale_w")
        return rtkcharacter._norm_item_scale(raw) if raw else None

    def _item_save(self, doc):
        import rtkcharacter
        import rtkitems
        name = doc.get("name") or ""
        n = 0
        if doc.get("fields") is not None or doc.get("effects") is not None:
            text = self.app.items.apply(name, fields=doc.get("fields"),
                                        effects=doc.get("effects"),
                                        ready_effect=doc.get("ready_effect"),
                                        use_effect=doc.get("use_effect"))
            asset = self.app.db.get(rtkitems.CATALOG_KEY)
            if asset is None:
                raise KeyError(rtkitems.CATALOG_KEY)
            n = self.app.mod.write_override(
                asset, text.encode("latin-1", "replace"), as_text=True,
                original=self.app.db.read(rtkitems.CATALOG_KEY))
            self.app._items = None
        mesh_scale = None
        if doc.get("mesh_scale") is not None:
            mesh_scale = rtkcharacter._norm_item_scale(doc.get("mesh_scale"))
            saved = self.app.mod.read_item(name) or {"name": name}
            saved["mesh_scale"] = mesh_scale
            self.app.mod.write_item(name, saved)
        rec = self.app.items.detail(name, ui=self.app.ui)
        rec["mesh_scale"] = mesh_scale or self._item_scale(name)
        return self._json({"ok": True, "name": name, "bytes": n, "item": rec})

    def _play(self):
        if self.app.mod is None:
            return self._error(400, "No mod is open")
        try:
            doc = json.loads(self._body() or b"{}")
        except json.JSONDecodeError:
            doc = {}
        if not isinstance(doc, dict):
            doc = {}
        out = self.app.mod.default_output()
        report = self.app.mod.build(self.app.db, out)
        out = Path(report["output"])
        import rtklaunch
        import rtkframe
        try:
            game_exe = rtklaunch.game_binary(out)
            changed = rtklaunch.enable_developer(game_exe, self.app.db.game)
            tail = rtklaunch.launch_args(doc.get("chapter"), doc.get("scene"))
            exe = rtklaunch.launch_binary(out)
            rtkframe.launch(exe, tail, out)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return self._error(500, str(exc))
        report["exe"] = str(exe)
        report["args"] = tail
        report["developer_sites"] = changed
        frame = " The 640×480 frame is shown at 4:3, with black bars in the spare space."
        if tail:
            report["note"] = "Developer flag is on in this copy. Starting with %s.%s" % (
                " ".join(tail), frame)
        else:
            report["note"] = (
                "Developer flag is on in this copy. No scene was selected, "
                "so the game boots from the title." + frame
            )
        return self._json(report)

    def _asset_diff(self, key):
        asset = self.app.db.get(key)
        if asset is None:
            raise KeyError(key)
        if self.app.mod is None or self.app.mod.read_override(key) is None:
            return self._json({"key": key, "mode": "none"})
        kind = asset.kind
        if kind in ("image", "depth", "palette"):
            return self._json({"key": key, "mode": "image"})
        if kind not in ("text", "script"):
            return self._json({"key": key, "mode": "none"})
        _, original, _meta = preview.render(self.app.db, key)
        _, modified, _meta = preview.render(
            _Overridden(self.app.db, self.app.mod), key)
        left, cut_l = _clip_text(original)
        right, cut_r = _clip_text(modified)
        return self._json({
            "key": key, "mode": "text",
            "original": left, "modified": right,
            "truncated": cut_l or cut_r,
        })

    def _write_text(self, key, text, label=None):
        asset = self.app.db.get(key)
        if asset is None:
            raise KeyError(key)
        n = self.app.mod.write_override(
            asset, text.encode("latin-1", "replace"), as_text=True,
            original=self.app.db.read(key), label=label)
        self.app.invalidate_studios()
        return n

    def _find_replace(self, doc):
        import rtkfind
        find = doc.get("find") or ""
        repl = doc.get("replace")
        if repl is None:
            repl = ""
        try:
            texts, count = rtkfind.plan_replace(
                self.app, find, repl, doc.get("kind") or None)
        except ValueError as exc:
            self.app._items = None
            return self._error(400, str(exc))
        label = "Replace %s" % find
        try:
            with self.app.mod.transaction(label):
                for key, text in texts.items():
                    self._write_text(key, text)
        except ValueError as exc:
            self.app._items = None
            self.app.invalidate_studios()
            return self._error(400, str(exc))
        self.app._items = None
        self.app.invalidate_studios()
        return self._json({
            "ok": True, "fields": count, "files": len(texts), "label": label,
        })

    def _history_step(self, action, cursor=None):
        mod = self.app.mod
        try:
            if action == "undo":
                entry = mod.undo()
                label = entry["label"] if entry else ""
            elif action == "redo":
                entry = mod.redo()
                label = entry["label"] if entry else ""
            else:
                entry = mod.jump(cursor)
                if entry:
                    label = entry["label"]
                elif int(cursor) < 0:
                    label = "original"
                else:
                    label = "history"
        except ValueError as exc:
            return self._error(400, str(exc))
        self.app._chars = None
        self.app.invalidate_studios()
        state = mod.history_state()
        state["ok"] = True
        state["action"] = action
        state["label"] = label
        return self._json(state)

    def _scene_mab_save(self, doc):
        import rtkscene
        key = doc.get("key") or ""
        asset = self.app.db.get(key)
        if asset is None:
            raise KeyError(key)
        raw = self.app.read(key)
        raw = rtkscene.write_mab_tile(raw, int(doc["x"]), int(doc["y"]),
                                      int(doc["tile"]))
        n = self.app.mod.write_override(asset, raw, as_text=False,
                                        original=self.app.db.read(key),
                                        label="Walk tile %s,%s" % (doc.get("x"), doc.get("y")))
        self.app.invalidate_studios()
        info = rtkscene.parse_mab(raw)
        info["key"] = key
        return self._json({"ok": True, "key": key, "bytes": n, "mab": info})

    def _studio_fields_save(self, doc):
        key = doc.get("key") or ""
        text = self.app.scenes.save_fields(
            key, doc.get("kind") or "", doc.get("name") or "",
            doc.get("fields") or {},
            parent_kind=doc.get("parent_kind"),
            parent_name=doc.get("parent_name"))
        who = doc.get("name") or doc.get("kind") or "object"
        n = self._write_text(key, text, label="Edit %s" % who)
        return self._json({"ok": True, "key": key, "bytes": n})

    def _scene_teleport_save(self, doc):
        key = doc.get("key") or ""
        text = self.app.scenes.save_teleport(
            key, doc.get("kind") or "", doc.get("name") or "",
            doc.get("index") or 0,
            doc.get("scene"), doc.get("view"),
            fade=doc.get("fade"), add=bool(doc.get("add")),
            parent_kind=doc.get("parent_kind"),
            parent_name=doc.get("parent_name"))
        who = doc.get("name") or "teleport"
        n = self._write_text(key, text, label="Teleport %s" % who)
        return self._json({"ok": True, "key": key, "bytes": n})

    def _scene_move_save(self, doc):
        key = doc.get("key") or ""
        actor = doc.get("actor") or {}
        text = self.app.scenes.save_move(key, actor,
                                        doc.get("xyz") or [0, 0, 0])
        n = self._write_text(key, text, label="Move %s" % (actor.get("name") or "actor"))
        return self._json({"ok": True, "key": key, "bytes": n})

    def _scene_view_save(self, doc):
        key = doc.get("key") or ""
        scene_id = doc.get("scene") or ""
        view_id = doc.get("view") or ""
        if doc.get("poly") is not None:
            text = self.app.scenes.save_view_poly(
                key, scene_id, view_id, doc["poly"])
        else:
            text = self.app.scenes.save_view_fields(
                key, scene_id, view_id, doc.get("fields") or {})
        n = self._write_text(key, text, label="View %s" % (view_id or scene_id or "view"))
        return self._json({"ok": True, "key": key, "bytes": n})

    def _combat_char_save(self, doc):
        name = doc.get("name") or ""
        text = self.app.combat.save_character(
            name, fields=doc.get("fields") or {},
            stats=doc.get("stats"), inventory=doc.get("inventory"))
        n = self._write_text(self.app.combat.chars_key, text,
                             label="Character %s" % (name or "sheet"))
        self.app.invalidate_studios()
        rec = None
        try:
            rec = self.app.combat.character(name)
        except KeyError:
            pass
        return self._json({"ok": True, "name": name, "bytes": n, "character": rec})

    def _combat_model_save(self, doc):
        name = doc.get("name") or ""
        key = self.app.characters.models_key()
        if not key:
            raise KeyError("Models.def")
        try:
            text = self.app.characters.save_model(name, doc.get("fields") or doc)
        except ValueError as exc:
            return self._error(400, str(exc))
        n = self._write_text(key, text, label="Model %s" % (name or "sprites"))
        self.app.characters.reload_models()
        char_name = doc.get("character") or ""
        rec = None
        if char_name:
            try:
                rec = self.app.combat.character(char_name)
            except KeyError:
                pass
        return self._json({"ok": True, "name": name, "bytes": n, "character": rec})

    def _combat_model_duplicate(self, doc):
        source = doc.get("source") or ""
        new_name = (doc.get("name") or "").strip()
        key = self.app.characters.models_key()
        if not key:
            raise KeyError("Models.def")
        try:
            text = self.app.characters.duplicate_model(
                source, new_name, doc.get("fields") or doc)
        except ValueError as exc:
            return self._error(400, str(exc))
        char_name = doc.get("character") or ""
        rec = None
        with self.app.mod.transaction("Duplicate model %s" % new_name):
            n = self._write_text(key, text)
            self.app.characters.reload_models()
            if char_name:
                try:
                    # Point this CharacterDef at the new Models.def row.
                    ctext = self.app.combat.save_character(
                        char_name, stats={"Model": new_name})
                    self._write_text(self.app.combat.chars_key, ctext)
                    rec = self.app.combat.character(char_name)
                except KeyError:
                    pass
        return self._json({
            "ok": True, "source": source, "name": new_name,
            "bytes": n, "character": rec,
        })

    def _trap_save(self, doc):
        text = self.app.traps.save_instance(
            doc.get("key") or "", doc.get("kind") or "CharacterDef",
            doc.get("name") or "", doc.get("trap") or "None")
        n = self._write_text(doc.get("key") or "", text)
        return self._json({"ok": True, "bytes": n})

    def _shop_save(self, doc):
        name = doc.get("name") or ""
        text = None
        if doc.get("items") is not None:
            text = self.app.shops.save_shop_items(name, doc["items"])
        else:
            field = doc.get("field") or ""
            text = self.app.shops.save_shop_field(name, field, doc.get("value") or "")
        shop = self.app.shops.shop(name)
        n = self._write_text(shop["key"], text)
        return self._json({"ok": True, "name": name, "bytes": n})

    def _loadout_save(self, doc):
        name = doc.get("name") or ""
        text = self.app.shops.save_loadout(name, doc.get("items") or [])
        rec = self.app.shops.loadout(name)
        n = self._write_text(rec["key"], text)
        return self._json({"ok": True, "name": name, "bytes": n})

    def _dialog_save(self, doc):
        ident = doc.get("id") or doc.get("name") or ""
        text = self.app.dialog.save_node(
            ident, fields=doc.get("fields"), groups=doc.get("groups"),
            links=doc.get("links"), formations=doc.get("formations"),
            events=doc.get("events"), script=doc.get("script"))
        rec = self.app.dialog.node(ident)
        n = self._write_text(rec["key"], text)
        return self._json({
            "ok": True, "id": ident, "bytes": n,
            "node": self.app.dialog.node(ident),
        })

    def _dialog_add(self, doc):
        chapter = int(doc.get("chapter") or 0)
        scene = doc.get("scene") or ""
        name = doc.get("name") or ""
        text = self.app.dialog.add_node(
            chapter, scene, name, fields=doc.get("fields"),
            parent=doc.get("parent"))
        key = self.app.dialog.chapter_keys[chapter]
        n = self._write_text(key, text)
        ident = "%s:%s" % (chapter, name)
        rec = None
        try:
            rec = self.app.dialog.node(ident)
        except KeyError:
            pass
        return self._json({"ok": True, "id": ident, "bytes": n, "node": rec})

    def _bex_sprite_save(self, doc):
        key = doc.get("key") or ""
        raw = self.app.fx.save_bex_sprite(key, doc.get("entry_id"), doc.get("sprite") or "")
        asset = self.app.db.get(key)
        if asset is None:
            raise KeyError(key)
        n = self.app.mod.write_override(
            asset, raw, as_text=False, original=self.app.db.read(key))
        self.app.invalidate_studios()
        return self._json({"ok": True, "key": key, "bytes": n,
                           "bex": self.app.fx.bex(key)})

    def _spell_save(self, doc):
        name = doc.get("name") or ""
        text = self.app.fx.save_spell(
            name, fields=doc.get("fields") or {},
            effects=doc.get("effects"))
        n = self._write_text(self.app.fx.magic_key, text)
        return self._json({"ok": True, "name": name, "bytes": n,
                           "spell": self.app.fx.spell(name)})

    def _alchemy_item_save(self, doc):
        import rtkitems
        name = doc.get("name") or ""
        n = 0
        if name and (doc.get("fields") is not None or doc.get("effect_fields") is not None):
            text = self.app.alchemy.save_item(
                name, fields=doc.get("fields") or {},
                effect_fields=doc.get("effect_fields"))
            n = self._write_text(rtkitems.CATALOG_KEY, text)
        spell = doc.get("spell") or {}
        if spell.get("name"):
            text = self.app.fx.save_spell(
                spell["name"], fields=spell.get("fields") or {},
                effects=spell.get("effects"))
            n += self._write_text(self.app.fx.magic_key, text)
        return self._json({"ok": True, "name": name, "bytes": n})

    def _ui_layout_save(self, doc):
        name = doc.get("name") or ""
        if not name:
            raise ValueError("name required")
        out = self.app.ui.move_sprite(
            name,
            x=doc.get("x"),
            y=doc.get("y"),
            cel=doc.get("cel"),
            write_hot=doc.get("write_hot", True))
        self.app.invalidate_studios()
        return self._json({"ok": True, "name": name, **out})

    def _ui_ref_save(self, doc):
        n = self.app.ui.replace_ref(
            doc.get("sprite_key") or "",
            int(doc.get("index") or 0),
            int(doc.get("new_id") or 0))
        self.app.invalidate_studios()
        return self._json({"ok": True, "bytes": n})

    def _ui_cel_save(self, doc):
        n = self.app.ui.replace_cel_bitmap(
            doc.get("cel_key") or "",
            int(doc.get("bitmap_id") or 0))
        self.app.invalidate_studios()
        return self._json({"ok": True, "bytes": n})

    def _ui_hotspot_save(self, doc):
        n = self.app.ui.write_hotspot(
            doc.get("key") or "",
            int(doc.get("hx") or 0),
            int(doc.get("hy") or 0))
        self.app.invalidate_studios()
        return self._json({"ok": True, "bytes": n})

    def _ui_queue_save(self, doc):
        kwargs = {
            "key": doc.get("key") or "",
            "offset": int(doc.get("offset") or 0),
        }
        if doc.get("script") is not None:
            kwargs["script"] = int(str(doc.get("script")), 0)
        else:
            kwargs["first"] = int(doc.get("first") or 0)
            kwargs["last"] = int(doc.get("last") or 0)
            kwargs["delay"] = int(doc.get("delay") or 0)
        n = self.app.ui.write_queue(**kwargs)
        self.app.invalidate_studios()
        return self._json({"ok": True, "bytes": n})

    def _ui_action_save(self, doc):
        path = self.app.ui.save_action(doc.get("name") or "", doc)
        self.app.invalidate_studios()
        return self._json({"ok": True, "name": doc.get("name"), "path": path})

    def _ui_text_save(self, doc):
        n = self.app.ui.write_text(doc.get("key") or "", doc.get("dwords") or [])
        self.app.invalidate_studios()
        return self._json({"ok": True, "bytes": n})

    def _char_save(self, doc):
        import rtkcharacter
        import rtktrack
        key = doc["anim"]
        asset = self.app.characters._asset(key)
        if asset is None:
            raise KeyError(key)
        track = rtktrack.Track(Path(asset.name), self.app.read(key))
        rtkcharacter.apply_edit(track, doc.get("frames") or {})
        blob = track.to_bytes()
        n = self.app.mod.write_override(asset, blob, original=self.app.db.read(key)
                                        if self.app.db.get(key) else blob)
        self.app.characters.invalidate()
        return self._json({"ok": True, "key": key, "bytes": n})

    def _char_duplicate(self, doc):
        import rtktrack
        from assetdb import Asset
        src = doc["anim"]
        stem = (doc.get("stem") or "TKMOD01")[:7].ljust(7)
        asset = self.app.db.get(src)
        if asset is None:
            raise KeyError(src)
        track = rtktrack.Track(Path(asset.name), self.app.read(src))
        track.retag_stem(stem)
        blob = track.to_bytes(rebuild_names=True)
        rel = "Tracks/%s.trk" % stem
        new = Asset(key="file/%s" % rel, name=stem + ".trk", kind="anim",
                    source="file", container="", member=rel, size=len(blob))
        n = self.app.mod.write_override(new, blob, original=blob)
        self.app.characters.add_extra(new)
        return self._json({"ok": True, "key": new.key, "stem": stem, "bytes": n})

    # ---- static ---------------------------------------------------------

    def _static(self, rel):
        target = (WEB_ROOT / rel).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            raise KeyError(rel)
        if not target.is_file():
            raise KeyError(rel)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, ctype, target.read_bytes())


REPO = app_paths.repo_dir()


def bind_server(game, cache, mod=None, port=8765, rebuild=False):
    """Index the install and listen. Returns (server, url)."""
    cached = Path(cache).is_file()
    print("indexing %s" % game, flush=True)
    if not cached or rebuild:
        print("  no usable index yet, scanning the install "
              "(a few seconds)", flush=True)
    Handler.app = App(game, cache, mod, rebuild)
    print("%d assets ready" % Handler.app.db.counts()["total"], flush=True)
    if mod:
        print("mod project: %s (%d edits)" % (mod.root, len(mod.index)), flush=True)
    server = Server(("127.0.0.1", port), Handler)
    bound = server.server_address[1]
    url = "http://127.0.0.1:%d/" % bound
    return server, url


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # Everything defaults relative to the repo, not the shell's working
    # directory, so the viewer behaves the same wherever it is launched from.
    ap.add_argument("--game", type=Path, default=None,
                    help="game install (default: last used, or the folder above the repo)")
    ap.add_argument("--mod", type=Path, help="mod project directory (enables editing)")
    ap.add_argument("--cache", type=Path, default=None,
                    help="asset index cache (default: out/assetdb.json, or the user data dir when frozen)")
    ap.add_argument("--rebuild", action="store_true", help="re-index the install")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    game = app_paths.resolve_game(args.game)
    if game is None or not app_paths.looks_like_game(game):
        hint = game or app_paths.repo_dir().parent
        print("No RTKRES.bin under %s -- is that the game install?" % hint)
        print("Pass the right one with --game \"C:\\path\\to\\Return To Krondor\".")
        return 2
    game = game.resolve()

    mod = None
    if args.mod:
        import modproject
        mod = modproject.ModProject(args.mod)

    cache = args.cache or app_paths.assetdb_cache()
    try:
        server, url = bind_server(game, cache, mod, args.port, args.rebuild)
    except OSError as exc:
        print("\nCannot listen on port %d: %s" % (args.port, exc))
        print("Something else is already using it -- most likely another copy")
        print("of this viewer. Open http://127.0.0.1:%d/ to check, or start"
              % args.port)
        print("this one on a different port with --port %d." % (args.port + 1))
        return 1

    print("serving %s   (ctrl-c to stop)" % url, flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
