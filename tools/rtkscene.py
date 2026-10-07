"""Chapter / scene / view graph for the Scene studio.

Pairs Loc_All.def cameras with ChapterN.def instances, a 640x480 backdrop,
the matching .ovx coverage buffer, the scene .mab walk grid, and a read-only
.wlx collision overlay. Writes go through the caller's mod project.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import rtkdef
import rtkworld

TILE_SIZE = 18.0
MAB_HEADER = 64
MAB_FIELDS = 40


def _norm(v):
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / n, y / n, z / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _camera_basis(origin, aim):
    forward = _norm((aim[0] - origin[0], aim[1] - origin[1], aim[2] - origin[2]))
    world_up = (0.0, 0.0, 1.0)
    right = _norm(_cross(forward, world_up))
    if abs(right[0]) + abs(right[1]) + abs(right[2]) < 1e-6:
        right = _norm(_cross(forward, (0.0, 1.0, 0.0)))
    up = _cross(right, forward)
    return forward, right, up


def project_point(origin, aim, field, point, width=640, height=480):
    """Project world XYZ through a CCameraDef onto the 640x480 painting."""
    forward, right, up = _camera_basis(origin, aim)
    rel = (point[0] - origin[0], point[1] - origin[1], point[2] - origin[2])
    z = _dot(rel, forward)
    if z <= 1.0:
        return None
    x = _dot(rel, right)
    y = _dot(rel, up)
    fov = math.radians(field or 63.0)
    half = math.tan(fov * 0.5) or 1e-6
    sx = width * 0.5 + (x / z) * (width * 0.5 / half)
    sy = height * 0.5 - (y / z) * (width * 0.5 / half)
    return {"x": sx, "y": sy, "z": z}


def unproject_point(origin, aim, field, sx, sy, plane_z=0.0, width=640, height=480):
    """Ray from the painting through the camera onto world plane z = plane_z."""
    forward, right, up = _camera_basis(origin, aim)
    fov = math.radians(field or 63.0)
    half = math.tan(fov * 0.5) or 1e-6
    xz = (sx - width * 0.5) / (width * 0.5 / half)
    yz = (height * 0.5 - sy) / (width * 0.5 / half)
    direction = (
        xz * right[0] + yz * up[0] + forward[0],
        xz * right[1] + yz * up[1] + forward[1],
        xz * right[2] + yz * up[2] + forward[2],
    )
    if abs(direction[2]) < 1e-8:
        return None
    t = (plane_z - origin[2]) / direction[2]
    if t <= 0:
        return None
    return [
        origin[0] + t * direction[0],
        origin[1] + t * direction[1],
        plane_z,
    ]


def project_poly(camera, pts, width=640, height=480):
    if not camera or not pts:
        return []
    out = []
    for p in pts:
        scr = project_point(camera["origin"], camera["aim"], camera["field"],
                            p, width, height)
        if scr:
            out.append(scr)
    return out


def clamp_to_frame(x, y, width=640, height=480, margin=16):
    if margin <= x <= width - margin and margin <= y <= height - margin:
        return {"x": x, "y": y, "offscreen": False}
    cx, cy = width * 0.5, height * 0.5
    dx, dy = x - cx, y - cy
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return {"x": cx, "y": cy, "offscreen": True}
    tx = ((width * 0.5) - margin) / abs(dx) if dx else 1e9
    ty = ((height * 0.5) - margin) / abs(dy) if dy else 1e9
    t = min(tx, ty)
    return {"x": cx + dx * t, "y": cy + dy * t, "offscreen": True}


def marker_screen(camera, pts, xyz=None, width=640, height=480):
    """Screen point for a plate: on-canvas verts if any, else a frame pin."""
    screens = project_poly(camera, pts, width, height)
    on = [p for p in screens
          if 0 <= p["x"] <= width and 0 <= p["y"] <= height]
    if on:
        n = float(len(on))
        return {
            "x": sum(p["x"] for p in on) / n,
            "y": sum(p["y"] for p in on) / n,
            "z": min(p["z"] for p in on),
            "offscreen": False,
        }
    raw = None
    if xyz and camera:
        raw = project_point(camera["origin"], camera["aim"], camera["field"],
                            xyz, width, height)
    if raw is None and screens:
        n = float(len(screens))
        raw = {
            "x": sum(p["x"] for p in screens) / n,
            "y": sum(p["y"] for p in screens) / n,
            "z": min(p["z"] for p in screens),
        }
    if raw is None:
        return None
    pinned = clamp_to_frame(raw["x"], raw["y"], width, height)
    pinned["z"] = raw.get("z", 1)
    return pinned


def _aabb_xy(pts):
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _aabb_overlap(a, b):
    return (a is not None and b is not None and
            a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])


def parse_camdef(s):
    v = rtkdef.floats(s)
    if len(v) < 8:
        return None
    return {
        "origin": [v[0], v[1], v[2]],
        "aim": [v[3], v[4], v[5]],
        "roll": v[6],
        "field": v[7],
    }


def parse_poly(s):
    v = rtkdef.floats(s)
    pts = []
    for i in range(0, len(v) - 2, 3):
        pts.append([v[i], v[i + 1], v[i + 2]])
    return pts


def centroid(pts):
    if not pts:
        return [0.0, 0.0, 0.0]
    n = float(len(pts))
    return [sum(p[i] for p in pts) / n for i in range(3)]


def parse_mab(raw: bytes) -> dict:
    if not raw.startswith(b"CostMap v2"):
        raise ValueError("not a CostMap v2 .mab")
    if len(raw) < MAB_HEADER + MAB_FIELDS:
        raise ValueError("truncated .mab header")
    xmin, ymin, xmax, ymax, base = struct.unpack_from("<5f", raw, MAB_HEADER)
    # On disk the last three dwords of the 40-byte block are rows, cols,
    # and the authored tile size (always 18). Runtime copies of rows/cols
    # live at different offsets; see docs/scene-runtime.md.
    rows, cols, tile = struct.unpack_from("<3I", raw, MAB_HEADER + 28)
    rows, cols, tile = int(rows), int(cols), int(tile) or int(TILE_SIZE)
    start = MAB_HEADER + MAB_FIELDS
    need = rows * cols
    if need <= 0 or start + need > len(raw) + 1024:
        raise ValueError("implausible grid %dx%d" % (cols, rows))
    tiles = raw[start:start + need]
    if len(tiles) < need:
        tiles = tiles + b"?" * (need - len(tiles))
    return {
        "bounds": [xmin, ymin, xmax, ymax],
        "base_height": base,
        "rows": rows,
        "cols": cols,
        "tile_size": float(tile) if tile else TILE_SIZE,
        "tiles": tiles.decode("latin-1"),
    }


def write_mab_tile(raw: bytes, x: int, y: int, tile: int) -> bytes:
    info = parse_mab(raw)
    cols, rows = info["cols"], info["rows"]
    if not (0 <= x < cols and 0 <= y < rows):
        raise ValueError("tile %d,%d out of %dx%d" % (x, y, cols, rows))
    buf = bytearray(raw)
    buf[MAB_HEADER + MAB_FIELDS + y * cols + x] = tile & 0xFF
    return bytes(buf)


def world_to_cell(mab, wx, wy):
    xmin, ymin, xmax, ymax = mab["bounds"]
    cols, rows = mab["cols"], mab["rows"]
    cw = (xmax - xmin) / cols if cols else TILE_SIZE
    rh = (ymax - ymin) / rows if rows else TILE_SIZE
    if cw == 0 or rh == 0:
        return None
    x = int((wx - xmin) / cw)
    y = int((wy - ymin) / rh)
    if 0 <= x < cols and 0 <= y < rows:
        return {"x": x, "y": y}
    return None


class SceneIndex:
    def __init__(self, app):
        self.app = app
        self.db = app.db
        self.index = rtkdef.name_index(self.db)
        self.chapters = []
        self._scenes = {}
        self._by_num = {}
        self._load()

    def _read_text(self, key):
        return rtkdef.inflate_text(self.app.read(key))

    def _load(self):
        loc_keys = []
        for name, keys in self.index.items():
            if name == "loc_all.def":
                loc_keys.extend(keys)
        loc_keys.sort()
        for loc_key in loc_keys:
            parts = loc_key.replace("\\", "/").split("/")
            folder = next((p for p in parts if p.lower().startswith("chapter")),
                          "Chapter?")
            try:
                ch_num = int("".join(c for c in folder if c.isdigit()) or "0")
            except ValueError:
                ch_num = 0
            ch_def = rtkdef.find_name(self.index, folder + ".def")
            if ch_def is None:
                ch_def = rtkdef.find_suffix(self.db, "gamedata/%s/%s.def" % (
                    folder, folder))
            loc = rtkdef.parse_document(self._read_text(loc_key))
            inst = None
            if ch_def:
                try:
                    inst = rtkdef.parse_document(self._read_text(ch_def))
                except Exception:
                    inst = None
            scenes = []
            for sc in loc.walk("Scene"):
                views = []
                for vw in sc.walk("View"):
                    cam = parse_camdef(vw.field("CamDef"))
                    bg = (vw.field("BGDef") or "").split(",")[0].strip()
                    views.append({
                        "id": vw.name,
                        "num": int(rtkdef.floats(vw.field("id"))[0])
                        if vw.field("id") else None,
                        "active": vw.field("Active"),
                        "camera": cam,
                        "bg": Path(bg).stem if bg else "",
                        "bg_raw": bg,
                        "poly": parse_poly(vw.field("CamPoly")),
                    })
                rec = {
                    "id": sc.name,
                    "num": int(rtkdef.floats(sc.field("id"))[0])
                    if sc.field("id") else None,
                    "desc": sc.field("Desc"),
                    "level": sc.field("Level"),
                    "world": (sc.field("T3dWorld") or "").strip(),
                    "views": views,
                    "loc_key": loc_key,
                    "def_key": ch_def,
                }
                scenes.append(rec)
                self._scenes[(ch_num, sc.name.upper())] = rec
                if rec.get("num") is not None:
                    self._by_num[int(rec["num"])] = {
                        "chapter": ch_num,
                        "scene": rec["id"],
                        "desc": rec["desc"],
                        "views": rec["views"],
                    }
            self.chapters.append({
                "id": ch_num,
                "folder": folder,
                "loc_key": loc_key,
                "def_key": ch_def,
                "scenes": scenes,
            })

        self._instances = {}
        for ch in self.chapters:
            if not ch["def_key"]:
                continue
            try:
                doc = rtkdef.parse_document(self._read_text(ch["def_key"]))
            except Exception:
                continue
            for sd in doc.walk("SceneDef"):
                self._instances[(ch["id"], sd.name.upper())] = sd

    def list_chapters(self):
        return [{
            "id": ch["id"],
            "folder": ch["folder"],
            "loc_key": ch["loc_key"],
            "def_key": ch["def_key"],
            "scenes": [{
                "id": s["id"],
                "num": s["num"],
                "desc": s["desc"],
                "world": s["world"],
                "views": [{"id": v["id"], "num": v["num"], "bg": v["bg"],
                           "active": v["active"]} for v in s["views"]],
            } for s in ch["scenes"]],
        } for ch in self.chapters]

    def _scene(self, chapter, scene_id):
        rec = self._scenes.get((int(chapter), scene_id.upper()))
        if rec is None:
            raise KeyError("scene %s in chapter %s" % (scene_id, chapter))
        return rec

    def resolve_dest(self, scene_num, view_num=None):
        rec = self._by_num.get(int(scene_num)) if scene_num is not None else None
        if rec is None:
            return {
                "scene": int(scene_num) if scene_num is not None else None,
                "view": int(view_num) if view_num is not None else None,
                "label": "%s / %s" % (scene_num, view_num),
            }
        view = None
        if view_num is not None:
            view = next((v for v in rec["views"]
                         if v.get("num") == int(view_num)), None)
        label = rec["scene"]
        if rec.get("desc"):
            label = "%s — %s" % (rec["scene"], rec["desc"])
        if view:
            label = "%s / %s" % (label, view["id"])
        elif view_num is not None:
            label = "%s / view %s" % (label, view_num)
        return {
            "chapter": rec["chapter"],
            "scene": rec["scene"],
            "scene_num": int(scene_num),
            "view": view["id"] if view else None,
            "view_num": int(view_num) if view_num is not None else None,
            "desc": rec.get("desc") or "",
            "label": label,
        }

    def _annotate_exits(self, exits):
        out = []
        for ex in exits or []:
            dest = self.resolve_dest(ex.get("scene"), ex.get("view"))
            row = dict(ex)
            row["dest"] = dest
            row["label"] = dest.get("label") or (
                "%s / %s" % (ex.get("scene"), ex.get("view")))
            out.append(row)
        return out

    def _formation_centroid(self, block):
        for form in block.children:
            if form.kind.lower() != "formation":
                continue
            pts = []
            for line in form.lines:
                fm = rtkdef.FIELD_RE.match(line)
                if not fm:
                    continue
                xyz = rtkdef.floats(fm.group(2))
                if xyz:
                    pts.append((xyz + [0, 0, 0])[:3])
            if pts:
                return centroid(pts)
        return None

    def _collect_teleports(self, script, sd, dest_field="", seen=None):
        found = list(rtkdef.teleports(script))
        if sd is None:
            return found
        seen = set(seen or [])
        for name in rtkdef.conversation_names(script, dest_field):
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            conv = next((c for c in sd.walk("ConversationDef")
                         if c.name.lower() == key), None)
            if conv is None:
                continue
            found.extend(self._collect_teleports(
                conv.script, sd, conv.field("PotentialDest"), seen))
        return found

    def _resolve_exits(self, script, sd, dest_field=""):
        found = self._collect_teleports(script, sd, dest_field)
        uniq, keys = [], set()
        for ex in found:
            k = (ex.get("scene"), ex.get("view"))
            if k in keys:
                continue
            keys.add(k)
            uniq.append(ex)
        return self._annotate_exits(uniq)

    def _pair_backdrop(self, scene_id, bg_stem):
        if not bg_stem:
            return None
        key = rtkdef.find_name(self.index, bg_stem.lower() + ".di_")
        if key:
            return {"key": key, "name": bg_stem}
        for a in self.db.assets:
            if a.name.lower().startswith(bg_stem.lower()) and \
                    a.name.lower().endswith(".di_"):
                if scene_id.upper() in a.key.upper():
                    return {"key": a.key, "name": Path(a.name).stem}
        return None

    def _pair_ovx(self, chapter, scene_id, view_id):
        names = [
            "C%d%s%s.ovx" % (int(chapter), scene_id, view_id),
            "C%d%s%s.ovx" % (int(chapter), scene_id.upper(), view_id),
            "%s%s.ovx" % (scene_id, view_id),
        ]
        for name in names:
            key = rtkdef.find_name(self.index, name.lower())
            if key:
                return {"key": key, "name": Path(key).name}
        needle = (scene_id + view_id).lower()
        for a in self.db.assets:
            if a.name.lower().endswith(".ovx") and needle in a.name.lower():
                return {"key": a.key, "name": a.name}
        return None

    def _pair_mab(self, scene):
        sid = scene["id"]
        num = scene.get("num")
        world = Path(scene.get("world") or "").stem
        level = scene.get("level") or "1"
        try:
            level = str(int(float(str(level).split(",")[0])))
        except ValueError:
            level = str(level).strip() or "1"
        names = []
        if world:
            names.append("%s_%s.mab" % (world, level))
            names.append(world + ".mab")
        names.append(sid + ".mab")
        if num is not None:
            names.append("%d.mab" % num)
            names.append("%05d.mab" % num)
        for name in names:
            key = rtkdef.find_name(self.index, name.lower())
            if key:
                return key
        for a in self.db.assets:
            if a.name.lower().endswith(".mab") and sid.lower() in a.key.lower():
                return a.key
        return None

    def _pair_wlx(self, world_name):
        names = []
        if world_name:
            stem = Path(world_name).name
            names.append(stem.lower())
            if not stem.lower().endswith(".wlx"):
                names.append(stem.lower() + ".wlx")
        names.append("rtkworld.wlx")
        for name in names:
            key = rtkdef.find_name(self.index, name)
            if key:
                return key
        return None

    def _actors(self, chapter, scene, camera):
        sd = self._instances.get((int(chapter), scene["id"].upper()))
        actors = []
        if sd is None:
            return actors

        def add(kind, name, xyz, extra):
            pt = list(xyz) if xyz else [0, 0, 0]
            if len(pt) < 3:
                pt = (pt + [0, 0, 0])[:3]
            screen = extra.pop("screen", None)
            if screen is None and camera:
                screen = project_point(camera["origin"], camera["aim"],
                                       camera["field"], pt)
            rec = {
                "kind": kind,
                "name": name,
                "xyz": pt,
                "screen": screen,
                "source_key": scene["def_key"],
                "block_kind": extra.pop("block_kind", kind),
                "block_name": extra.pop("block_name", name),
            }
            rec.update(extra)
            actors.append(rec)

        for g in sd.walk("GroupDef"):
            members = []
            for sec in g.children:
                if sec.kind.lower() == "members":
                    members = list(sec.lines)
            formations = [c for c in g.children if c.kind.lower() == "formation"]
            placed = False
            for form in formations:
                for line in form.lines:
                    fm = rtkdef.FIELD_RE.match(line)
                    if not fm:
                        continue
                    xyz = rtkdef.floats(fm.group(2))
                    doorish = rtkdef.looks_like_door(g.name) or \
                        rtkdef.looks_like_door(fm.group(1)) or \
                        any(rtkdef.looks_like_door(m) for m in members)
                    exits = self._resolve_exits(g.script, sd)
                    add("npc", fm.group(1), xyz[:3], {
                        "facing": xyz[3] if len(xyz) > 3 else 0,
                        "group": g.name,
                        "formation": form.name,
                        "active": g.field("Active"),
                        "behavior": g.field("Behavior"),
                        "members": members,
                        "block_kind": "GroupDef",
                        "block_name": g.name,
                        "parent_kind": "SceneDef",
                        "parent_name": sd.name,
                        "movable": True,
                        "script": g.script,
                        "exits": exits,
                        "is_exit": bool(exits) or doorish,
                    })
                    placed = True
            if not placed:
                add("npc", g.name, [0, 0, 0], {
                    "group": g.name,
                    "active": g.field("Active"),
                    "members": members,
                    "block_kind": "GroupDef",
                    "block_name": g.name,
                    "parent_kind": "SceneDef",
                    "parent_name": sd.name,
                    "script": g.script,
                })

        for kind, label in (("TouchPlateDef", "touch"),
                            ("PressurePlateDef", "plate")):
            for pl in sd.walk(kind):
                poly = parse_poly(pl.field("Poly"))
                xyz = centroid(poly)
                exits = self._resolve_exits(pl.script, sd)
                doorish = rtkdef.looks_like_door(pl.name)
                add(label, pl.name, xyz, {
                    "poly": poly,
                    "poly_screen": project_poly(camera, poly),
                    "screen": marker_screen(camera, poly, xyz),
                    "active": pl.field("Active"),
                    "desc": pl.field("Desc"),
                    "range": pl.field("Range"),
                    "nav": pl.field("NavigationSensor"),
                    "script": pl.script,
                    "exits": exits,
                    "is_exit": bool(exits) or doorish,
                    "movable": True,
                    "block_kind": kind,
                    "block_name": pl.name,
                    "parent_kind": "SceneDef",
                    "parent_name": sd.name,
                })

        for cb in sd.walk("CombatDef"):
            arena = parse_poly(cb.field("Arena"))
            add("combat", cb.name, centroid(arena), {
                "arena": arena,
                "music": cb.field("CombatMusic"),
                "script": cb.script,
                "readonly": True,
                "block_kind": "CombatDef",
                "block_name": cb.name,
            })
            for form in cb.children:
                if form.kind.lower() != "formation":
                    continue
                for line in form.lines:
                    fm = rtkdef.FIELD_RE.match(line)
                    if not fm:
                        continue
                    xyz = rtkdef.floats(fm.group(2))
                    add("combatant", fm.group(1), xyz[:3], {
                        "facing": xyz[3] if len(xyz) > 3 else 0,
                        "combat": cb.name,
                        "formation": form.name,
                        "readonly": True,
                        "block_kind": "CombatDef",
                        "block_name": cb.name,
                    })

        for conv in sd.walk("ConversationDef"):
            exits = self._resolve_exits(
                conv.script, sd, conv.field("PotentialDest"))
            if not exits:
                continue
            xyz = self._formation_centroid(conv) or [0, 0, 0]
            add("exit", conv.name, xyz, {
                "menu": conv.field("MenuText"),
                "exits": exits,
                "is_exit": True,
                "script": conv.script,
                "block_kind": "ConversationDef",
                "block_name": conv.name,
                "parent_kind": "SceneDef",
                "parent_name": sd.name,
            })
        return actors

    def _world_overlay(self, key):
        if not key:
            return None
        try:
            w = rtkworld.World(key, data=self.app.read(key))
        except Exception as e:
            return {"key": key, "error": str(e), "objects": [], "lines": []}
        objects = []
        lines = []
        for obj in w.objects[:120]:
            aabb = None
            try:
                lo = [min(v[i] for v in obj.vertices) for i in range(3)]
                hi = [max(v[i] for v in obj.vertices) for i in range(3)]
                aabb = {"min": lo, "max": hi}
            except Exception:
                pass
            objects.append({
                "name": obj.name,
                "flags": obj.flags,
                "vertices": len(obj.vertices),
                "polygons": len(getattr(obj, "polygons", []) or []),
                "aabb": aabb,
            })
            polys = getattr(obj, "polygons", None) or []
            for poly in polys[:8]:
                ring = []
                for idx in (poly.indices or [])[:16]:
                    if 0 <= idx < len(obj.vertices):
                        ring.append(list(obj.vertices[idx]))
                if len(ring) >= 2:
                    lines.append({"name": obj.name, "points": ring})
            if not polys and obj.vertices:
                step = max(1, len(obj.vertices) // 24)
                lines.append({
                    "name": obj.name,
                    "points": [list(obj.vertices[i])
                               for i in range(0, len(obj.vertices), step)][:24],
                })
        return {
            "key": key,
            "names": list(getattr(w, "names", []) or []),
            "objects": objects,
            "lines": lines[:400],
            "bsps": len(getattr(w, "bsps", []) or []),
        }

    def view(self, chapter, scene_id, view_id):
        scene = self._scene(chapter, scene_id)
        view = next((v for v in scene["views"]
                     if v["id"].lower() == view_id.lower()
                     or str(v.get("num")) == str(view_id)), None)
        if view is None:
            raise KeyError("view %s" % view_id)
        camera = view.get("camera")
        backdrop = self._pair_backdrop(scene["id"], view.get("bg"))
        overlay = self._pair_ovx(chapter, scene["id"], view["id"])
        mab_key = self._pair_mab(scene)
        mab = None
        if mab_key:
            try:
                mab = parse_mab(self.app.read(mab_key))
                mab["key"] = mab_key
            except Exception as e:
                mab = {"key": mab_key, "error": str(e)}
        wlx_key = self._pair_wlx(scene.get("world"))
        wanted = Path(scene.get("world") or "").name.lower()
        world = self._world_overlay(wlx_key) if wlx_key else None
        if world is not None:
            world["authored"] = scene.get("world")
            if wanted and wlx_key and not wlx_key.lower().endswith(wanted):
                world["note"] = (
                    "Scene %s is not in the install; showing %s via rtkworld.py."
                    % (scene.get("world"), Path(wlx_key).name))
        actors = self._actors(chapter, scene, camera)
        current_box = _aabb_xy(view.get("poly") or [])
        views = []
        for vw in scene["views"]:
            poly = vw.get("poly") or []
            screen = project_poly(camera, poly)
            box = _aabb_xy(poly)
            current = vw["id"] == view["id"]
            views.append({
                "id": vw["id"],
                "num": vw.get("num"),
                "active": vw.get("active"),
                "bg": vw.get("bg"),
                "poly": poly,
                "screen": screen,
                "current": current,
                "linked": (not current) and _aabb_overlap(current_box, box),
                "camera": vw.get("camera"),
            })
        sd = self._instances.get((int(chapter), scene["id"].upper()))
        scene_exits = self._annotate_exits(
            rtkdef.teleports(sd.script) if sd is not None else [])
        cells = []
        if mab and camera and "tiles" in mab:
            xmin, ymin, xmax, ymax = mab["bounds"]
            cols, rows = mab["cols"], mab["rows"]
            cw = (xmax - xmin) / cols if cols else TILE_SIZE
            rh = (ymax - ymin) / rows if rows else TILE_SIZE
            tiles = mab["tiles"]
            # Project a stride of cells so the heatmap stays cheap.
            step = 1 if cols * rows <= 80 * 80 else 2
            for y in range(0, rows, step):
                for x in range(0, cols, step):
                    ch = tiles[y * cols + x]
                    wx = xmin + (x + 0.5) * cw
                    wy = ymin + (y + 0.5) * rh
                    scr = project_point(camera["origin"], camera["aim"],
                                        camera["field"], (wx, wy, mab.get(
                                            "base_height") or 0.0))
                    if scr:
                        cells.append({"x": x, "y": y, "ch": ch,
                                      "sx": scr["x"], "sy": scr["y"]})
        world_screen = []
        if world and camera:
            for line in world.get("lines") or []:
                pts = []
                for p in line["points"]:
                    scr = project_point(camera["origin"], camera["aim"],
                                        camera["field"], p)
                    if scr:
                        pts.append(scr)
                if len(pts) >= 2:
                    world_screen.append({"name": line["name"], "points": pts})
        return {
            "chapter": int(chapter),
            "scene": scene["id"],
            "scene_num": scene.get("num"),
            "desc": scene["desc"],
            "view": view["id"],
            "view_num": view.get("num"),
            "loc_key": scene.get("loc_key"),
            "def_key": scene.get("def_key"),
            "camera": camera,
            "backdrop": backdrop,
            "overlay": overlay,
            "mab": mab,
            "mab_cells": cells,
            "world": ({"key": wlx_key, "error": (world or {}).get("error"),
                       "objects": (world or {}).get("objects") or [],
                       "bsps": (world or {}).get("bsps") or 0,
                       "authored": (world or {}).get("authored"),
                       "note": (world or {}).get("note")}
                      if wlx_key else None),
            "world_screen": world_screen,
            "actors": actors,
            "views": views,
            "scene_exits": scene_exits,
        }

    def mab_info(self, key):
        info = parse_mab(self.app.read(key))
        info["key"] = key
        return info

    def save_fields(self, key, kind, name, fields: dict,
                    parent_kind=None, parent_name=None) -> str:
        text = self._read_text(key)
        for field, value in fields.items():
            text = rtkdef.replace_field(
                text, kind, name, field, str(value),
                parent_kind=parent_kind, parent_name=parent_name)
        return text

    def save_teleport(self, key, kind, name, index, scene, view, fade=None,
                      add=False, parent_kind=None, parent_name=None) -> str:
        text = self._read_text(key)
        if add:
            text = rtkdef.add_teleport(
                text, kind, name, int(scene), int(view), bool(fade),
                parent_kind, parent_name)
        else:
            text = rtkdef.replace_teleport(
                text, kind, name, int(index or 0), int(scene), int(view),
                fade, parent_kind, parent_name)
        return text

    def save_move(self, key, actor: dict, xyz) -> str:
        """Move a formation member or translate a plate polygon."""
        text = self._read_text(key)
        kind = (actor.get("block_kind") or actor.get("kind") or "").lower()
        if kind == "groupdef":
            facing = actor.get("facing")
            vals = list(xyz)[:3]
            if facing is not None:
                vals.append(facing)
            return rtkdef.replace_formation_xyz(
                text, actor.get("group") or actor.get("block_name"),
                actor.get("formation") or "default",
                actor.get("name"), vals)
        if kind in ("touchplatedef", "pressureplatedef"):
            old = actor.get("poly") or []
            if not old:
                raise ValueError("plate has no Poly")
            origin = centroid(old)
            delta = [xyz[i] - origin[i] for i in range(3)]
            moved = [[p[i] + delta[i] for i in range(3)] for p in old]
            return rtkdef.replace_field(
                text, actor.get("block_kind"), actor.get("block_name"),
                "Poly", rtkdef.format_xyz_list(moved),
                parent_kind=actor.get("parent_kind"),
                parent_name=actor.get("parent_name"))
        raise ValueError("cannot move %s" % actor.get("kind"))

    def save_view_poly(self, loc_key, scene_id, view_id, pts) -> str:
        return self.save_fields(
            loc_key, "View", view_id,
            {"CamPoly": rtkdef.format_xyz_list(pts)},
            parent_kind="Scene", parent_name=scene_id)

    def save_view_fields(self, loc_key, scene_id, view_id, fields: dict) -> str:
        return self.save_fields(
            loc_key, "View", view_id, fields,
            parent_kind="Scene", parent_name=scene_id)
