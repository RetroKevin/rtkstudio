"""Characters: Models.def + a .adf rig + a .trk, as a scene the viewer can draw.

A character is a hierarchical sprite. Each bone (dag) instances a 3D sprite
whose polygons reference BMInfo filenames in the same .t3d archive. A .trk
supplies per-joint local TRS; conversation tracks are not bound to one
character and play on any rig that covers their joints.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_gltf
import pyro_inflate
import rtkspx
import rtktrack

DEFAULT_CHARACTER = "James"
INTERVAL_MS = export_gltf.DEFAULT_INTERVAL_MS

# FUN_004427e0 / 42a7d / 42bfb / 42da9 each retarget one simple-sprite
# def. Tokens match the sprite tag; FACE is expression, AMLG is combined.
KIT_REGIONS = (
    ("head", "Head", ("HEAD", "NECK")),
    ("torso", "Torso", ("KIL", "TOPTORS")),
    ("arms", "Arms", ("UPPERAR", "LOWAR", "HAN")),
    ("legs", "Legs", ("UPPERLE", "CAL", "FOO")),
)
DEFAULT_REGIONS = {rid: {"length": 1.0, "width": 1.0} for rid, _l, _t in KIT_REGIONS}
SLOT_REGION = {
    "face": "head", "torso": "torso", "back": "torso", "body": "torso",
    "arms": "arms", "legs": "legs",
}


def region_for_joint(joint):
    """Body-region id for a dag name, or None (weapons / shadows)."""
    u = (joint or "").upper()
    if not u or "SHAD" in u or u.startswith("WEAPON"):
        return None
    if "TUNIC" in u:
        return "torso"
    if "KNEE" in u:
        return "legs"
    for rid, _label, toks in KIT_REGIONS:
        if any(tok in u for tok in toks):
            return rid
    return None


def _clamp_scale(v):
    return max(0.25, min(3.0, float(v)))


def _norm_item_scale(scale):
    out = {"length": 1.0, "width": 1.0}
    if not scale:
        return out
    try:
        if isinstance(scale, dict):
            out["length"] = _clamp_scale(scale.get("length", scale.get("size", 1.0)))
            out["width"] = _clamp_scale(scale.get("width", 1.0))
        else:
            s = _clamp_scale(scale)
            out = {"length": s, "width": s}
    except (TypeError, ValueError):
        pass
    return out


def _region_lw(regions, rid):
    if not rid:
        return 1.0, 1.0
    rec = (regions or {}).get(rid, 1.0)
    if isinstance(rec, dict):
        return _clamp_scale(rec.get("length", 1.0)), _clamp_scale(rec.get("width", 1.0))
    s = _clamp_scale(rec)
    return s, s


def _scale3(vec, s):
    return [float(vec[0]) * s, float(vec[1]) * s, float(vec[2]) * s]


def _parent_dag(rig, dag):
    if dag.parent is None:
        return None
    try:
        return rig.dags[dag.parent]
    except (IndexError, TypeError):
        return None


def _lengthens_chain(rig, dag):
    """Scale this joint's T only when it is a bone *inside* a region.

    The socket onto another region (NECK on the torso, thigh on the
    pelvis) stays put so a taller head does not lift off the shoulders.
    Children still follow through the hierarchy, and in-region links
    (elbow, knee) stretch so the chain stays connected.
    """
    rid = region_for_joint(dag.joint)
    if not rid:
        return False
    parent = _parent_dag(rig, dag)
    if parent is None:
        return False
    return region_for_joint(parent.joint) == rid


def _bounds(center, radius, flags):
    """Bounding sphere from an ADF definition. Flag 2 is the radius word."""
    if not (flags & 2) or not radius:
        return None
    return {
        "center": [float(center[0]), float(center[1]), float(center[2])],
        "radius": float(radius),
    }


def _scale_positions(pos, length, width):
    """Stretch a card: longest AABB axis follows length, the others width."""
    if not pos or (length == 1.0 and width == 1.0):
        return pos
    xs, ys, zs = pos[0::3], pos[1::3], pos[2::3]
    ext = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    axis = max(range(3), key=lambda i: ext[i])
    out = []
    for i in range(0, len(pos), 3):
        v = [pos[i], pos[i + 1], pos[i + 2]]
        for a in range(3):
            v[a] *= length if a == axis else width
        out.extend(v)
    return out


ARMOR_SLOTS = (
    ("torso", ("FRNT", "FRONT", "TORS"), "Torso"),
    ("back", ("BACK",), "Back"),
    ("legs", ("LEG",), "Legs"),
    ("arms", ("ARM",), "Arms"),
    ("body", ("AMLG",), "Body"),
    ("face", ("FACE",), "Face"),
)

# FACE sheets are look * expressions (Alan 36×7, Goblin 6×7, James 1×7).
FACE_EXPR_DEFAULT = 7
CONTAINER_NOTE = (
    "Container2D.adf is a 120-byte NULLSPRITE stub. Doors, desks, cages, "
    "and painted chests use the scene backdrop as their picture; this actor "
    "is the click target. Open / closed / locked is swapped at runtime on "
    "whatever simple sprite the scene bound — this ADF has none. Treasure "
    "Chest / Baby / Sign Post use their own ADFs and do have sprites."
)


def _intish(s):
    if s is None:
        return None
    m = re.match(r"[-+]?\d+(?:\.\d+)?", str(s).strip())
    if not m:
        return None
    try:
        return int(float(m.group(0)))
    except ValueError:
        return None


def look_kit(look, face_expr=0, face_stride=FACE_EXPR_DEFAULT):
    """Models.def look → armor kit frames on a shared ADF."""
    if look is None:
        return {}
    try:
        look = int(look)
    except (TypeError, ValueError):
        return {}
    if look < 0:
        return {}
    try:
        face_expr = int(face_expr or 0)
    except (TypeError, ValueError):
        face_expr = 0
    try:
        face_stride = int(face_stride or FACE_EXPR_DEFAULT)
    except (TypeError, ValueError):
        face_stride = FACE_EXPR_DEFAULT
    if face_stride < 1:
        face_stride = 1
    kit = {slot: look for slot, _t, _l in ARMOR_SLOTS if slot != "face"}
    kit["face"] = look * face_stride + max(0, face_expr)
    return kit


def face_stride_of(sf):
    """FACE frames / body frames, or 7."""
    if sf is None:
        return FACE_EXPR_DEFAULT
    face_n = body_n = 0
    for de in getattr(sf, "simple_defs", None) or []:
        name = (getattr(de, "name", None) or "").upper()
        n = len(getattr(de, "frames", None) or [])
        if "FACE" in name:
            face_n = max(face_n, n)
        elif any(tok in name for tok in ("AMLG", "FRONT", "FRNT", "BACK")):
            body_n = max(body_n, n)
    if body_n and face_n and face_n % body_n == 0:
        return face_n // body_n
    return FACE_EXPR_DEFAULT


def model_kind(rec, has_rig=False, sf=None):
    adf = (rec.get("adf") or "").lower()
    hs = (rec.get("hs_def") or "").upper()
    has_mesh = False
    has_simple = False
    if sf is not None:
        has_mesh = any(getattr(d, "verts", None)
                       for d in getattr(sf, "sprite3d_defs", None) or [])
        has_simple = bool(getattr(sf, "simple_defs", None))
    if has_rig:
        return "character"
    if "container2d" in adf:
        return "container"
    if has_mesh or "3DSPRITE" in hs:
        return "prop"
    if hs == "NULLSPRITE" and not has_simple and not has_mesh:
        return "container"
    return "prop" if (has_simple or has_mesh) else "container"

# Frame names end in a material code: A1FRNT10 / A1BACK20 / A1LEG__3.
# The leading A1 is the character prefix, so only trailing digits count.
# Tens place is the usual kit (10 leather, 20 chain, 30 plate); some
# limbs only store the ones digit (LEG__2, ARM_03).
_SUB_LOOKS = (
    ("leather", (10, 1)),
    ("chainmail", (20, 2)),
    ("chain", (20, 2)),
    ("plate", (30, 3)),
)


def armor_look_code(label):
    """Trailing digits of a simple-sprite frame name (A1FRNT20 -> 20)."""
    s = label or ""
    i = len(s)
    while i > 0 and s[i - 1].isdigit():
        i -= 1
    tail = s[i:]
    if not tail:
        return None
    return int(tail)


def match_armor_look(options, subcategory=None, prefer_code=None):
    """Pick a per-slot frame index. The same index is not portable across slots."""
    if not options:
        return 0
    coded = []
    for o in options:
        if isinstance(o, dict):
            coded.append((o.get("i", 0), armor_look_code(o.get("label"))))
        else:
            coded.append((o, armor_look_code(str(o))))

    def pick(want):
        if want is None:
            return None
        for idx, code in coded:
            if code == want:
                return idx
        # 10/20/30 <-> 1/2/3. Never treat 20 as 0 (20 % 10).
        if want >= 10:
            ones = want // 10
            for idx, code in coded:
                if code == ones:
                    return idx
            tens = want // 10
            for idx, code in coded:
                if code is not None and code // 10 == tens:
                    return idx
        elif want:
            tens_equiv = want * 10
            for idx, code in coded:
                if code == tens_equiv:
                    return idx
            for idx, code in coded:
                if code is not None and code // 10 == want:
                    return idx
        return None

    hit = pick(prefer_code)
    if hit is not None:
        return hit
    sub = (subcategory or "").lower()
    for key, wants in _SUB_LOOKS:
        if key in sub:
            for want in wants:
                hit = pick(want)
                if hit is not None:
                    return hit
            break
    first = options[0]
    return first.get("i", 0) if isinstance(first, dict) else 0

# FUN_00443c46 dag indices. FUN_0044540b rows are
# {name, file, sheathe_slot, hold_slot}.
_DAG_SLOTS = (
    "WEAPONLEFTSIDE", "WEAPONRIGHT", "WEAPONLEFT", "WEAPONBACK",
    "WEAPONSHIELD", "WEAPONBOWHOLDER", "WEAPONSHHOLDER",
)
_ATTACH = {
    "onehandaxe": (1, 0), "shortsword": (1, 0), "staff": (1, 3),
    "dagger": (1, 0), "club": (1, 0), "scimitar": (1, 1),
    "broadsword": (1, 0), "greatsword": (0, 3), "mace": (1, 3),
    "warhammer": (1, 3), "bow": (1, 3), "rapier": (1, 0),
    "axe": (1, 0), "broom": (1, 0), "wand": (1, 0), "mug": (2, 6),
    "objpotion": (1, 0),
}
_PROP_SKIP = (
    "grid", "hotspot", "marker", "mk_combat", "mkr_active",
    "obj", "head", "sign", "baby", "wire",
)
_PROP_KEEP = ("objpotion",)
_PROP_LABELS = {
    "onehandaxe": "One-hand axe",
    "shortsword": "Short sword",
    "greatsword": "Greatsword",
    "broadsword": "Broadsword",
    "shldwood": "Wooden shield",
    "shldrun1": "Rune shield",
    "shldgold": "Gold shield",
    "warhammer": "Warhammer",
    "wand": "Wand",
    "objpotion": "Potion flask",
}


def parse_models_def(text: str):
    """{display name -> dict} from the inflated Models.def."""
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("ModelGroup") or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        name = name.strip()
        parts = [p.strip() for p in rest.split(",")]
        if len(parts) < 3:
            continue
        hs = parts[2] if len(parts) > 2 else ""
        # Sailor #1 shipped `-1. NO_HEAD_SWAP` (period, no comma).
        tail = ""
        if len(parts) > 9:
            tail = parts[9].strip()
        elif len(parts) > 8 and "NO_HEAD" in parts[8].upper():
            tail = "NO_HEAD_SWAP"
        look = _intish(parts[6]) if len(parts) > 6 else None
        head_frame = _intish(parts[8]) if len(parts) > 8 else None
        out[name] = {
            "name": name,
            "adf": parts[0],
            "sph": parts[1] if len(parts) > 1 else "",
            "hs_def": hs,
            "actor": parts[3] if len(parts) > 3 else "",
            "size": parts[4] if len(parts) > 4 else "0",
            "palette_bmp": parts[5] if len(parts) > 5 else "",
            "look": look,
            "flag7": _intish(parts[7]) if len(parts) > 7 else 0,
            "head_frame": head_frame,
            "head_sprite": "" if not tail or tail.upper() == "NO_HEAD_SWAP" else tail,
            "no_head_swap": (not tail) or tail.upper() == "NO_HEAD_SWAP",
            "hierarchical": "_HS_DEF" in hs,
        }
    return out


def models_def_key(db):
    for a in getattr(db, "assets", []) or []:
        if Path(a.name).name.lower() == "models.def":
            return a.key
    return None


def load_models_text(db_or_game) -> str:
    if hasattr(db_or_game, "assets") and hasattr(db_or_game, "read"):
        key = models_def_key(db_or_game)
        if key:
            import rtkdef
            return rtkdef.inflate_text(db_or_game.read(key))
        game = getattr(db_or_game, "game", None)
        if game:
            return load_models_text(Path(game))
        raise FileNotFoundError("Models.def")
    path = Path(db_or_game) / "GameData" / "Models.def"
    raw = path.read_bytes()
    try:
        return pyro_inflate.inflate(raw).decode("latin-1")
    except Exception:
        return raw.decode("latin-1")


def load_models(db_or_game):
    return parse_models_def(load_models_text(db_or_game))


def format_models_line(rec, indent="  "):
    look = rec.get("look")
    if look is None:
        look = -1
    flag7 = rec.get("flag7")
    if flag7 is None:
        flag7 = 0
    hf = rec.get("head_frame")
    if hf is None:
        hf = -1
    head = rec.get("head_sprite") or "NO_HEAD_SWAP"
    if rec.get("no_head_swap") and not rec.get("head_sprite"):
        head = "NO_HEAD_SWAP"
    size = rec.get("size")
    if size is None or size == "":
        size = "0"
    return (
        "%s%s : %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
        % (indent, rec["name"], rec.get("adf") or "", rec.get("sph") or "",
           rec.get("hs_def") or "", rec.get("actor") or "", size,
           rec.get("palette_bmp") or "Palette.bmp", look, flag7, hf, head)
    )


def _model_newline(text):
    return "\r\n" if "\r\n" in text else "\n"


def replace_model_line(text, name, updates):
    models = parse_models_def(text)
    rec = models.get(name)
    if rec is None:
        by = {k.lower(): k for k in models}
        key = by.get((name or "").lower())
        rec = models.get(key) if key else None
        if rec is None:
            raise KeyError(name)
        name = rec["name"]
    rec = dict(rec)
    for k, v in (updates or {}).items():
        if v is None:
            continue
        rec[k] = v
    if rec.get("head_sprite") in ("", "NO_HEAD_SWAP") or rec.get("no_head_swap"):
        if rec.get("head_sprite") in ("", "NO_HEAD_SWAP"):
            rec["head_sprite"] = ""
            rec["no_head_swap"] = True
        else:
            rec["no_head_swap"] = False
    nl = _model_newline(text)
    out = []
    found = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if (stripped and not stripped.startswith("ModelGroup")
                and not stripped.startswith("#") and ":" in stripped):
            n = stripped.split(":", 1)[0].strip()
            if n == name:
                indent = raw[:len(raw) - len(raw.lstrip())] or "  "
                out.append(format_models_line(rec, indent).rstrip("\r\n"))
                found = True
                continue
        out.append(raw)
    if not found:
        raise KeyError(name)
    body = nl.join(out)
    if text.endswith(("\n", "\r\n")):
        body += nl
    return body


def add_model_line(text, rec, after=None):
    existing = parse_models_def(text)
    name = (rec.get("name") or "").strip()
    if not name:
        raise ValueError("model name required")
    if name in existing or name.lower() in {k.lower() for k in existing}:
        raise ValueError("model %s already exists" % name)
    nl = _model_newline(text)
    lines = text.splitlines()
    insert_at = len(lines)
    indent = "  "
    if after:
        for i, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped.split(":", 1)[0].strip() == after:
                insert_at = i + 1
                indent = raw[:len(raw) - len(raw.lstrip())] or "  "
                break
    lines.insert(insert_at, format_models_line(rec, indent).rstrip("\r\n"))
    body = nl.join(lines)
    if text.endswith(("\n", "\r\n")) or True:
        body += nl
    return body


class CharacterIndex:
    """Lazy cache of Models.def, rigs, and compatible tracks."""

    def __init__(self, db):
        self.db = db
        self.models = load_models(db)
        self._rigs = None
        self._adf_key = {}
        self._bmp_key = {}
        self._track_assets = None
        self._compat = {}
        self._tj = {}
        self._extras = []  # newly added tracks not in the original index
        self._props = None

    def _index_assets(self):
        if self._bmp_key:
            return
        for a in self.db.assets:
            low = a.name.lower()
            if a.kind == "rig" and low.endswith(".adf") and "hicolor" not in a.key.lower():
                self._adf_key.setdefault(low, a.key)
            if low.endswith(".bmp"):
                self._bmp_key.setdefault(low, a.key)
                self._bmp_key.setdefault(Path(a.name).name.lower(), a.key)

    @property
    def rigs(self):
        if self._rigs is None:
            self._index_assets()
            paths = []
            for name, rec in self.models.items():
                key = self._adf_key.get(rec["adf"].lower())
                if key:
                    # SpriteFile wants a path; use a dummy and pass bytes.
                    rec["_adf_key"] = key
            adfs = []
            seen = set()
            for rec in self.models.values():
                key = rec.get("_adf_key")
                if not key or key in seen:
                    continue
                seen.add(key)
                adfs.append(key)
            self._rigs = {}
            self._files = {}
            for key in adfs:
                try:
                    sf = rtkspx.SpriteFile(Path(self.db.get(key).name),
                                           self.db.read(key))
                except Exception:
                    continue
                self._files[key] = sf
                for d in sf.hsprite_defs:
                    self._rigs.setdefault(d.name, (d, key, sf))
        return self._rigs

    def resolve_model_name(self, name):
        """Chars.tbl Model -> Models.def display name."""
        if not name:
            return None
        if name in self.models:
            return name
        by = {k.lower(): k for k in self.models}
        hit = by.get(name.lower())
        if hit:
            return hit
        stripped = re.sub(r"[\s#]+\d+$", "", name).strip()
        if stripped.lower() in by:
            return by[stripped.lower()]
        return None

    def get_model(self, name):
        key = self.resolve_model_name(name)
        return self.models.get(key) if key else None

    def reload_models(self):
        """Re-read Models.def (including mod overrides) without reparsing ADFs."""
        self.models = load_models(self.db)
        self._index_assets()
        for rec in self.models.values():
            key = self._adf_key.get((rec.get("adf") or "").lower())
            if key:
                rec["_adf_key"] = key

    def models_key(self):
        return models_def_key(self.db)

    def list_palettes(self):
        self.rigs
        out = []
        seen = set()
        for rec in self.models.values():
            name = rec.get("palette_bmp") or ""
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            key = self.bmp_key(name, rec.get("_adf_key"))
            out.append({"name": name, "key": key})
        out.sort(key=lambda r: r["name"].lower())
        return out

    def list_head_sprites(self):
        self.rigs
        seen = set()
        out = [{"name": "NO_HEAD_SWAP", "tag": ""}]
        for rec in self.models.values():
            h = rec.get("head_sprite") or ""
            if h and h.upper() not in seen:
                seen.add(h.upper())
                out.append({"name": h, "tag": h})
        for sf in getattr(self, "_files", {}).values():
            for d in getattr(sf, "sprite3d_defs", None) or []:
                n = getattr(d, "name", "") or ""
                if "HEAD" in n.upper() and n.upper() not in seen:
                    seen.add(n.upper())
                    out.append({"name": n, "tag": n})
        return out

    def save_model(self, name, fields) -> str:
        return replace_model_line(load_models_text(self.db), name,
                                  self._model_fields(fields))

    def duplicate_model(self, source, new_name, fields=None) -> str:
        src = self.get_model(source)
        if src is None:
            raise KeyError(source)
        rec = {k: src.get(k) for k in (
            "adf", "sph", "hs_def", "actor", "size", "palette_bmp",
            "look", "flag7", "head_frame", "head_sprite", "no_head_swap")}
        rec["name"] = (new_name or "").strip()
        rec.update(self._model_fields(fields))
        return add_model_line(load_models_text(self.db), rec, after=src["name"])

    @staticmethod
    def _model_fields(fields):
        fields = dict(fields or {})
        if "palette" in fields and "palette_bmp" not in fields:
            fields["palette_bmp"] = fields.pop("palette")
        elif "palette" in fields:
            fields.pop("palette")
        head = fields.get("head_sprite")
        if head is not None:
            if str(head).upper() in ("", "NO_HEAD_SWAP"):
                fields["head_sprite"] = ""
                fields["no_head_swap"] = True
            else:
                fields["no_head_swap"] = False
        allowed = (
            "adf", "sph", "hs_def", "actor", "size", "palette_bmp",
            "look", "flag7", "head_frame", "head_sprite", "no_head_swap",
        )
        return {k: fields[k] for k in allowed if k in fields}

    def resolve_hs_def(self, rec):
        """Models.def often stores a truncated tag (J1CJ1CALAN, no _HS_DEF)."""
        self.rigs
        tag = (rec or {}).get("hs_def") or ""
        if tag and tag in self.rigs:
            return tag
        if tag and tag + "_HS_DEF" in self.rigs:
            return tag + "_HS_DEF"
        key = (rec or {}).get("_adf_key")
        if not key:
            adf = (rec or {}).get("adf") or ""
            key = self._adf_key.get(adf.lower())
        sf = self._files.get(key) if key else None
        if sf and sf.hsprite_defs:
            return sf.hsprite_defs[0].name
        return tag

    def has_rig(self, rec):
        tag = self.resolve_hs_def(rec)
        return bool(tag and tag in self.rigs)

    def list_characters(self):
        self.rigs  # force
        out = []
        for rec in self.models.values():
            tag = self.resolve_hs_def(rec)
            info = self.rigs.get(tag)
            if info is None:
                continue
            out.append({
                "name": rec["name"],
                "adf": rec["adf"],
                "hs_def": tag,
                "palette": rec["palette_bmp"],
                "has_rig": True,
                "dags": len(info[0].dags),
            })
        return out

    def invalidate(self):
        self._compat = {}

    def add_extra(self, asset):
        self._extras.append(asset)
        self.invalidate()

    def _tracks(self):
        if self._track_assets is None:
            self._track_assets = [a for a in self.db.assets if a.kind == "anim"]
        return self._track_assets + self._extras

    def _asset(self, key):
        asset = self.db.get(key)
        if asset is not None:
            return asset
        return next((a for a in self._extras if a.key == key), None)

    def _resolve_anim(self, anim_key):
        """Accept a full asset key or a 7-character stem like TK0005M."""
        if not anim_key:
            return None
        if self._asset(anim_key) is not None:
            return anim_key
        stem = Path(anim_key).stem.upper()
        for a in self._tracks():
            if Path(a.name).stem.upper() == stem:
                return a.key
        return anim_key

    def compatible_anims(self, char_name):
        rec = self.get_model(char_name)
        if rec is None:
            raise KeyError(char_name)
        resolved = rec["name"]
        if resolved in self._compat:
            return self._compat[resolved]
        info = self.rigs.get(self.resolve_hs_def(rec))
        if info is None:
            self._compat[resolved] = []
            return []
        rig = info[0]
        joints = set(rig.joints())
        hits = []
        for a in self._tracks():
            want, nframes = self._track_info(a)
            if want and want <= joints:
                hits.append({"key": a.key, "name": a.name,
                             "frames": nframes, "joints": len(want)})
        hits.sort(key=lambda x: x["name"])
        self._compat[resolved] = hits
        return hits

    def conversation_bind(self, char_name, tol_z=3.0):
        """True if this rig's pelvis height matches conversation tracks (James)."""
        rec = self.get_model(char_name)
        james = self.models.get("James")
        if rec is None or james is None:
            return False
        info = self.rigs.get(self.resolve_hs_def(rec))
        jinfo = self.rigs.get(james["hs_def"])
        if info is None or jinfo is None:
            return False
        kil = rtkspx.rest_pose(info[0]).get("KIL")
        jkil = rtkspx.rest_pose(jinfo[0]).get("KIL")
        if kil is None or jkil is None:
            return False
        return abs(float(kil.translation[2]) - float(jkil.translation[2])) <= tol_z

    def _track_info(self, asset):
        cached = self._tj.get(asset.key)
        if cached is not None:
            return cached
        try:
            tk = rtktrack.Track(Path(asset.name), self.db.read(asset.key))
            info = (set(rtkspx.track_joints(tk)), tk.frames)
        except Exception:
            info = (set(), 0)
        self._tj[asset.key] = info
        return info

    def bmp_key(self, filename, adf_key):
        self._index_assets()
        if not filename:
            return None
        low = filename.lower()
        # Prefer a bitmap in the same archive as the .adf.
        prefix = adf_key.rsplit("/", 1)[0] + "/" if adf_key.startswith("t3d/") else ""
        if prefix:
            for a in self.db.assets:
                if a.key.startswith(prefix) and a.name.lower() == low:
                    return a.key
        return self._bmp_key.get(low) or self._bmp_key.get(Path(filename).name.lower())

    def _prop_files(self):
        """Every handheld 3D sprite ADF in Chars.t3d (hs=0, has verts)."""
        if self._props is not None:
            return self._props
        self.rigs
        self._props = {}
        for name, key in self._adf_key.items():
            if "chars.t3d" not in key.lower():
                continue
            stem = Path(name).stem.lower()
            if stem not in _PROP_KEEP and any(
                    stem.startswith(p) or p in stem for p in _PROP_SKIP):
                continue
            try:
                sf = rtkspx.SpriteFile(Path(name), self.db.read(key))
            except Exception:
                continue
            if sf.hsprite_defs:
                continue
            defn = next((d for d in sf.sprite3d_defs if d.verts), None)
            if defn is None:
                continue
            kind = "shield" if stem.startswith("shld") or "shield" in stem else "weapon"
            hold_i, sheathe_i = _ATTACH.get(stem, (1, 0) if kind == "weapon" else (4, 6))
            hold = _DAG_SLOTS[hold_i] if 0 <= hold_i < len(_DAG_SLOTS) else "WEAPONRIGHT"
            sheathe = _DAG_SLOTS[sheathe_i] if 0 <= sheathe_i < len(_DAG_SLOTS) else "WEAPONLEFTSIDE"
            if kind == "shield":
                hold, sheathe = "WEAPONSHIELD", "WEAPONSHHOLDER"
            self._props[stem] = {
                "id": stem,
                "name": _PROP_LABELS.get(stem, stem.replace("_", " ").title()),
                "kind": kind,
                "hold": hold,
                "sheathe": sheathe,
                "defn": defn,
                "adf_key": key,
            }
        return self._props

    @staticmethod
    def _simple_def(tex):
        if isinstance(tex, rtkspx.SimpleSpriteDef):
            return tex
        if isinstance(tex, rtkspx.SimpleSprite):
            return tex.definition
        return None

    @classmethod
    def _slot_for_tex(cls, tex):
        de = cls._simple_def(tex)
        name = (getattr(de, "name", None) or "").upper()
        if not name:
            return None
        for slot, tokens, _label in ARMOR_SLOTS:
            if any(tok in name for tok in tokens):
                return slot
        return None

    def _tex_filename(self, tex, kit=None):
        if isinstance(tex, rtkspx.BMInfo):
            return tex.filename
        de = self._simple_def(tex)
        if de is None or not de.frames:
            return None
        slot = self._slot_for_tex(tex)
        frame = 0
        if slot and kit:
            try:
                frame = int(kit.get(slot, 0) or 0)
            except (TypeError, ValueError):
                frame = 0
            frame = max(0, min(frame, len(de.frames) - 1))
        return getattr(de.frames[frame], "filename", None)

    def _armor_slots(self, rig):
        """Per-limb frame lists from the simple sprites on this rig."""
        found = {slot: {} for slot, _t, _l in ARMOR_SLOTS}
        nframes = {slot: 0 for slot, _t, _l in ARMOR_SLOTS}
        for dag in rig.dags:
            defn = getattr(getattr(dag, "sprite", None), "definition", None)
            if defn is None:
                continue
            for poly in defn.polys:
                tex = getattr(poly, "texture", None)
                slot = self._slot_for_tex(tex)
                de = self._simple_def(tex)
                if slot is None or de is None:
                    continue
                nframes[slot] = max(nframes[slot], len(de.frames))
                for i, fr in enumerate(de.frames):
                    fn = getattr(fr, "filename", None) or ""
                    if i not in found[slot] and fn:
                        found[slot][i] = Path(fn).stem
        out = []
        for slot, _tokens, label in ARMOR_SLOTS:
            n = nframes[slot]
            if n < 1:
                continue
            out.append({
                "id": slot,
                "label": label,
                "options": [{"i": i, "label": found[slot].get(i) or "%s %d" % (label, i)}
                            for i in range(n)],
            })
        return out

    def gear(self, char_name):
        rec = self.get_model(char_name)
        if rec is None:
            raise KeyError(char_name)
        info = self.rigs.get(self.resolve_hs_def(rec))
        if info is None:
            raise KeyError(char_name)
        rig = info[0]
        joints = {(d.joint or "").upper() for d in rig.dags}
        items = []
        for rec in sorted(self._prop_files().values(), key=lambda r: r["name"]):
            items.append({
                "id": rec["id"],
                "name": rec["name"],
                "kind": rec["kind"],
                "hold": rec["hold"],
                "sheathe": rec["sheathe"],
                "can_hold": rec["hold"] in joints,
                "can_sheathe": rec["sheathe"] in joints,
            })
        return {
            "slots": self._armor_slots(rig),
            "weapons": [g for g in items if g["kind"] == "weapon"],
            "shields": [g for g in items if g["kind"] == "shield"],
        }

    @staticmethod
    def _norm_regions(regions):
        out = {rid: dict(DEFAULT_REGIONS[rid]) for rid, _l, _t in KIT_REGIONS}
        for k, v in (regions or {}).items():
            key = str(k)
            if key not in out:
                continue
            try:
                if isinstance(v, dict):
                    out[key]["length"] = _clamp_scale(v.get("length", v.get("size", 1.0)))
                    out[key]["width"] = _clamp_scale(v.get("width", 1.0))
                else:
                    s = _clamp_scale(v)
                    out[key] = {"length": s, "width": s}
            except (TypeError, ValueError):
                pass
        return out

    def kit_info(self, char_name, armor_kit=None, regions=None):
        """Sheets, palette, and size sliders for the creator panel."""
        rec = self.get_model(char_name)
        if rec is None:
            raise KeyError(char_name)
        info = self.rigs.get(self.resolve_hs_def(rec))
        if info is None:
            raise KeyError(char_name)
        rig, adf_key, _sf = info
        armor_kit = {k: int(v) for k, v in (armor_kit or {}).items()
                     if str(v).lstrip("-").isdigit()}
        pal, pal_key = self._palette_table(rec.get("palette_bmp"), adf_key)
        sheets = []
        seen = set()
        for dag in rig.dags:
            if "SHAD" in (dag.joint or "").upper():
                continue
            defn = getattr(getattr(dag, "sprite", None), "definition", None)
            if defn is None:
                continue
            for poly in defn.polys:
                tex = getattr(poly, "texture", None)
                fn = self._tex_filename(tex, armor_kit)
                key = self.bmp_key(fn, adf_key)
                if not key or key in seen:
                    continue
                seen.add(key)
                slot = self._slot_for_tex(tex) or "other"
                label = next((l for s, _t, l in ARMOR_SLOTS if s == slot), slot)
                frame = 0
                if slot in armor_kit:
                    try:
                        frame = int(armor_kit[slot])
                    except (TypeError, ValueError):
                        frame = 0
                sheets.append({
                    "key": key,
                    "name": Path(fn).name if fn else Path(key).name,
                    "slot": slot,
                    "label": label,
                    "frame": frame,
                    "joint": dag.joint or "",
                    "region": SLOT_REGION.get(slot) or region_for_joint(dag.joint),
                })
        return {
            "character": char_name,
            "palette_key": pal_key or "",
            "palette": [list(c) for c in pal] if pal else [],
            "regions": self._norm_regions(regions),
            "region_defs": [{"id": rid, "label": lab} for rid, lab, _t in KIT_REGIONS],
            "sheets": sheets,
        }

    def resolve_armor_kit(self, char_name, armor_kit=None, subcategory=None,
                          slots=None, prefer_code=None):
        """Fill per-slot frame indices from a material name or look code."""
        gear = self.gear(char_name)
        by = {s["id"]: s for s in gear["slots"]}
        kit = {k: int(v) for k, v in (armor_kit or {}).items()
               if str(v).lstrip("-").isdigit()}
        wanted = [s for s in (slots or []) if s]
        if not wanted:
            wanted = [s["id"] for s in gear["slots"]]
        if subcategory or prefer_code is not None:
            for s in wanted:
                rec = by.get(s)
                if rec:
                    kit[s] = match_armor_look(
                        rec["options"], subcategory, prefer_code)
        return kit

    def item_art(self, char_name, gear=None, slot=None, armor_kit=None,
                 subcategory=None, look_code=None):
        """Bitmap sheets for a handheld prop or armor slot(s)."""
        rec = self.get_model(char_name)
        if rec is None:
            raise KeyError(char_name)
        info = self.rigs.get(self.resolve_hs_def(rec))
        if info is None:
            raise KeyError(char_name)
        _rig, adf_key, _sf = info
        pal, pal_key = self._palette_table(rec.get("palette_bmp"), adf_key)
        gear = (gear or "").lower() or None
        slot = (slot or "").lower() or None
        if gear:
            stems = [s.strip() for s in gear.split(",") if s.strip()]
            sheets = []
            used = []
            for stem in stems:
                prop = self._prop_files().get(stem)
                if prop is None:
                    if len(stems) == 1:
                        raise KeyError(stem)
                    continue
                used.append(stem)
                sheets.extend(self._sheets_from_def(
                    prop["defn"], prop["adf_key"],
                    label=prop["name"], joint=prop["hold"],
                    slot="item", region="item"))
            if not used:
                raise KeyError(stems[0] if stems else gear)
            return {
                "character": char_name,
                "gear": used[0],
                "gears": used,
                "slot": "",
                "palette_key": "",
                "palette": [],
                "sheets": sheets,
            }
        if slot:
            wanted = [s.strip() for s in slot.split(",") if s.strip()]
            armor_kit = self.resolve_armor_kit(
                char_name, armor_kit, subcategory=subcategory,
                slots=wanted, prefer_code=look_code)
            kit = self.kit_info(char_name, armor_kit=armor_kit)
            wanted_set = set(wanted)
            sheets = [s for s in kit["sheets"] if s.get("slot") in wanted_set]
            for s in sheets:
                s["region"] = "item"
            return {
                "character": char_name,
                "gear": "",
                "slot": wanted[0] if wanted else slot,
                "slots": wanted,
                "armor_kit": armor_kit,
                "palette_key": kit.get("palette_key") or "",
                "palette": kit.get("palette") or [],
                "sheets": sheets,
            }
        return {
            "character": char_name,
            "gear": "",
            "slot": "",
            "palette_key": pal_key or "",
            "palette": [list(c) for c in pal] if pal else [],
            "sheets": [],
        }

    def _sheets_from_def(self, defn, adf_key, label, joint="", slot="item",
                         region="item"):
        sheets = []
        seen = set()
        for poly in getattr(defn, "polys", None) or []:
            tex = getattr(poly, "texture", None)
            fn = self._tex_filename(tex, None)
            key = self.bmp_key(fn, adf_key)
            if not key or key in seen:
                continue
            seen.add(key)
            sheets.append({
                "key": key,
                "name": Path(fn).name if fn else Path(key).name,
                "slot": slot,
                "label": label,
                "frame": 0,
                "joint": joint or "",
                "region": region,
            })
        return sheets

    def scene(self, char_name, anim_key=None, kit=None, weapon=None,
              shield=None, sheathed=False, regions=None, item_scale=None,
              item_slot=None, palette=None, face_expr=0):
        rec = self.get_model(char_name)
        if rec is None:
            raise KeyError(char_name)
        info = self.rigs.get(self.resolve_hs_def(rec))
        if info is None:
            return self.scene_prop(rec, kit=kit, palette=palette)
        rig, adf_key, sf = info
        rest = rtkspx.rest_pose(rig)
        kit = {k: int(v) for k, v in (kit or {}).items()
               if str(v).lstrip("-").isdigit()}
        if not kit:
            kit = look_kit(rec.get("look"), face_expr, face_stride_of(sf))
        regions = self._norm_regions(regions)
        item_scale = _norm_item_scale(item_scale)
        il, iw = item_scale["length"], item_scale["width"]
        item_slot = (item_slot or "").lower() or None
        item_slots = {s.strip() for s in (item_slot or "").split(",") if s.strip()}
        pal_name = palette or rec.get("palette_bmp")
        pal, pal_key = self._palette_table(pal_name, adf_key)

        anim_key = self._resolve_anim(anim_key)

        track = None
        if anim_key:
            asset = self._asset(anim_key)
            if asset is None:
                raise KeyError(anim_key)
            track = rtktrack.Track(Path(asset.name), self.db.read(anim_key))

        nodes = []
        meshes = []
        mesh_of = {}
        by_joint = {}
        for dag in rig.dags:
            frame = rest.get(dag.joint.upper())
            rid = region_for_joint(dag.joint)
            length, width = _region_lw(regions, rid)
            trans = list(frame.translation) if frame else [0, 0, 0]
            if length != 1.0 and _lengthens_chain(rig, dag):
                trans = _scale3(trans, length)
            node = {
                "i": dag.index,
                "name": dag.name,
                "joint": dag.joint,
                "parent": dag.parent,
                "children": list(dag.children),
                "translation": trans,
                "rotation": list(export_gltf._quat_xyzw(frame.quat)) if frame else [0, 0, 0, 1],
                "scale": frame.scale if frame else 1.0,
                "mesh": None,
                "region": rid,
            }
            by_joint[(dag.joint or "").upper()] = dag
            for mesh in self._meshes_for_dag(dag, adf_key, kit, pal, pal_key):
                if mesh.get("positions") and (length != 1.0 or width != 1.0):
                    mesh["positions"] = _scale_positions(
                        mesh["positions"], length, width)
                if (item_slots and mesh.get("slot") in item_slots
                        and mesh.get("positions") and (il != 1.0 or iw != 1.0)):
                    mesh["positions"] = _scale_positions(
                        mesh["positions"], il, iw)
                mesh["region"] = rid
                node["mesh"] = len(meshes)
                mesh_of[dag.index] = len(meshes)
                meshes.append(mesh)
            nodes.append(node)

        for item_id in (weapon, shield):
            if not item_id:
                continue
            for mesh in self._meshes_for_gear(item_id, by_joint, sheathed):
                if mesh.get("positions") and (il != 1.0 or iw != 1.0):
                    mesh["positions"] = _scale_positions(
                        mesh["positions"], il, iw)
                mesh["item"] = item_id
                meshes.append(mesh)

        anim = None
        if track is not None:
            anim = self._anim(rig, track, anim_key, regions)

        return {
            "character": char_name,
            "rig": rig.name,
            "adf": adf_key,
            "palette": pal_name or rec["palette_bmp"],
            "palette_key": pal_key or "",
            "kit": kit,
            "regions": regions,
            "weapon": weapon or "",
            "shield": shield or "",
            "sheathed": bool(sheathed),
            "item_scale": item_scale,
            "item_slot": item_slot or "",
            "gear": self.gear(char_name),
            "nodes": nodes,
            "meshes": meshes,
            "anim": anim,
            "collision": _bounds(rig.center_offset, rig.bounding_radius, rig.flags),
            "note": "conversation tracks are not bound to one character; "
                    "this rig is the one Models.def names for %s" % rec["name"],
            "resolved": rec["name"],
        }

    def scene_prop(self, rec, kit=None, palette=None):
        """A Models.def row that is a 3D sprite (chest, pack), not a skeleton."""
        self.rigs
        adf_key = rec.get("_adf_key") or self._adf_key.get(
            (rec.get("adf") or "").lower())
        sf = self._files.get(adf_key) if adf_key else None
        if sf is None:
            raise KeyError("no mesh for %s (%s)" % (rec["name"], rec.get("hs_def")))
        want = (rec.get("hs_def") or "").upper()
        defn = next((d for d in sf.sprite3d_defs
                     if d.verts and d.name.upper() == want), None)
        if defn is None:
            defn = next((d for d in sf.sprite3d_defs if d.verts), None)
        if defn is None:
            raise KeyError("no 3D sprite for %s" % rec["name"])
        kit = {k: int(v) for k, v in (kit or {}).items()
               if str(v).lstrip("-").isdigit()}
        if not kit:
            look = rec.get("look")
            if look is not None and int(look) >= 0:
                kit = look_kit(look, face_stride=1)
        pal_name = palette or rec.get("palette_bmp")
        pal, pal_key = self._palette_table(pal_name, adf_key)
        meshes = self._meshes_from_def(defn, adf_key, "DUMMY01", kit, pal, pal_key)
        node = {
            "i": 0, "name": defn.name, "joint": "DUMMY01", "parent": None,
            "children": [], "translation": [0, 0, 0],
            "rotation": [0, 0, 0, 1], "scale": 1.0,
            "mesh": 0 if meshes else None, "region": None,
        }
        return {
            "character": rec["name"],
            "rig": "",
            "adf": adf_key,
            "palette": pal_name or rec.get("palette_bmp") or "",
            "palette_key": pal_key or "",
            "kit": kit,
            "regions": {},
            "weapon": "",
            "shield": "",
            "sheathed": False,
            "item_scale": {"length": 1.0, "width": 1.0},
            "item_slot": "",
            "gear": {"slots": [], "weapons": [], "shields": []},
            "nodes": [node],
            "meshes": meshes,
            "anim": None,
            "collision": _bounds(defn.center, defn.radius, defn.flags),
            "resolved": rec["name"],
            "kind": "prop",
            "note": "static 3D sprite from Models.def (no hierarchical rig)",
        }

    def model_sprites(self, name):
        """Simple-sprite sheets and optional head 3D sprite on a Models.def row."""
        rec = self.get_model(name)
        if rec is None:
            return {"name": name, "sheets": [], "head_sprite": ""}
        self.rigs
        adf_key = rec.get("_adf_key") or self._adf_key.get(
            (rec.get("adf") or "").lower())
        sf = self._files.get(adf_key) if adf_key else None
        stride = face_stride_of(sf)
        kind = model_kind(rec, self.has_rig(rec), sf)
        sheets = []
        if sf is not None:
            seen = set()
            for de in getattr(sf, "simple_defs", None) or []:
                frames = []
                for fr in getattr(de, "frames", None) or []:
                    fn = getattr(fr, "filename", None) or ""
                    key = self.bmp_key(fn, adf_key) if fn else None
                    frames.append({
                        "filename": fn,
                        "key": key,
                        "name": Path(fn).stem if fn else "",
                    })
                if de.name in seen:
                    continue
                seen.add(de.name)
                slot = None
                uname = (de.name or "").upper()
                for sid, tokens, _lab in ARMOR_SLOTS:
                    if any(tok in uname for tok in tokens):
                        slot = sid
                        break
                sheets.append({
                    "name": de.name,
                    "kind": "simple",
                    "slot": slot,
                    "frames": frames,
                })
            head = rec.get("head_sprite") or ""
            if head:
                defn = next((d for d in sf.sprite3d_defs
                             if d.name.upper() == head.upper()), None)
                if defn is not None:
                    sheets.append({
                        "name": head,
                        "kind": "head",
                        "slot": "head",
                        "frames": [],
                    })
        pal_key = self.bmp_key(rec.get("palette_bmp"), adf_key)
        return {
            "name": rec["name"],
            "adf": rec.get("adf") or "",
            "sph": rec.get("sph") or "",
            "actor": rec.get("actor") or "",
            "hs_def": self.resolve_hs_def(rec),
            "has_rig": self.has_rig(rec),
            "kind": kind,
            "palette": rec.get("palette_bmp") or "",
            "palette_key": pal_key or "",
            "look": rec.get("look"),
            "flag7": rec.get("flag7"),
            "head_frame": rec.get("head_frame"),
            "head_sprite": rec.get("head_sprite") or "",
            "no_head_swap": bool(rec.get("no_head_swap")),
            "face_stride": stride,
            "face_expr": 0,
            "note": CONTAINER_NOTE if kind == "container" else "",
            "sheets": sheets,
        }

    def _meshes_for_gear(self, item_id, by_joint, sheathed):
        prop = self._prop_files().get(str(item_id).lower())
        if prop is None:
            return []
        hold, sheathe = prop["hold"], prop["sheathe"]
        joint = sheathe if sheathed else hold
        if joint not in by_joint:
            joint = hold if hold in by_joint else sheathe
        if joint not in by_joint:
            return []
        return self._meshes_from_def(prop["defn"], prop["adf_key"],
                                     by_joint[joint].joint, None)

    def _palette_table(self, filename, adf_key):
        """Models.def *Palette.bmp colour table, or (None, None)."""
        key = self.bmp_key(filename, adf_key)
        if not key:
            return None, None
        try:
            import preview
            return preview.bmp_palette(self.db.read(key)), key
        except Exception:
            return None, key

    def _meshes_for_dag(self, dag, adf_key, kit=None, pal=None, pal_key=None):
        joint = (dag.joint or "").upper()
        # LFOOTSHAD / RFOOTSHAD / MAINSHADO are ground blobs. The game
        # updates those dags on a separate shadow path (FUN_004b7f7e);
        # as untextured cards they sit at the bind-pose feet and look
        # like extra geometry on the legs.
        if "SHAD" in joint:
            return []
        spr = dag.sprite
        defn = getattr(spr, "definition", None)
        if defn is None or not getattr(defn, "verts", None):
            return []
        return self._meshes_from_def(defn, adf_key, dag.joint, kit, pal, pal_key)

    def _meshes_from_def(self, defn, adf_key, joint, kit=None,
                         pal=None, pal_key=None):
        """One mesh per texture (or flat colour). Verts are v+center.

        Materials always store 4 UV slots even on triangles
        (FUN_10023810); use the first nidx. Untextured polys use the
        flags&1 byte as a palette index into Models.def's *Palette.bmp.
        """
        cx, cy, cz = getattr(defn, "center", (0.0, 0.0, 0.0))
        groups = {}
        for poly in defn.polys:
            tex = getattr(poly, "texture", None)
            tex_key = self.bmp_key(self._tex_filename(tex, kit), adf_key)
            color = None
            if tex_key:
                gkey = ("tex", tex_key)
            else:
                idx = getattr(poly, "mat_index", None)
                if pal is None or idx is None or not (0 <= idx < len(pal)):
                    continue
                color = list(pal[idx])
                gkey = ("col", tuple(color))
            g = groups.get(gkey)
            if g is None:
                g = {"positions": [], "uvs": [], "indices": [],
                     "texture": tex_key, "color": color,
                     "slot": self._slot_for_tex(tex),
                     "remap": pal_key if tex_key and pal_key else None}
                groups[gkey] = g
            base = len(g["positions"]) // 3
            nuv = poly.uvs or []
            for i, vi in enumerate(poly.indices):
                if not (0 <= vi < len(defn.verts)):
                    continue
                v = defn.verts[vi]
                g["positions"].extend((v[0] + cx, v[1] + cy, v[2] + cz))
                uv = nuv[i] if i < len(nuv) else (0.0, 0.0)
                g["uvs"].extend(uv)
            n = len(poly.indices)
            for i in range(1, n - 1):
                g["indices"].extend((base, base + i, base + i + 1))
        out = []
        collision_used = False
        for g in groups.values():
            if not g["indices"]:
                continue
            rec = {
                "joint": joint,
                "positions": g["positions"],
                "uvs": g["uvs"],
                "indices": g["indices"],
                "texture": g["texture"],
                "color": g["color"],
                "remap": g["remap"],
                "slot": g.get("slot"),
            }
            if not collision_used and (getattr(defn, "flags", 0) & 2):
                rec["collision"] = {
                    "center": [float(c) for c in defn.center],
                    "radius": float(defn.radius),
                }
                collision_used = True
            out.append(rec)
        return out

    def _anim(self, rig, track, key, regions=None):
        joints = {j: d for j, d in zip(rtkspx.track_joints(track),
                                       track.trackdefs)}
        interval = next((t.update_interval for t in track.tracks
                         if t.update_interval), INTERVAL_MS)
        regions = self._norm_regions(regions)
        channels = {}
        nframes = 0
        for dag in rig.dags:
            td = joints.get(dag.joint.upper())
            if td is None or not td.frames:
                continue
            nframes = max(nframes, len(td.frames))
            rid = region_for_joint(dag.joint)
            length, _width = _region_lw(regions, rid)
            ts = [list(f.translation) for f in td.frames]
            if length != 1.0 and _lengthens_chain(rig, dag):
                ts = [_scale3(t, length) for t in ts]
            channels[dag.joint] = {
                "r": [list(export_gltf._quat_xyzw(f.quat)) for f in td.frames],
                "t": ts,
            }
        return {
            "key": key,
            "name": Path(key).name,
            "interval_ms": interval,
            "frames": nframes,
            "joints": channels,
        }


def apply_edit(track, frames):
    """`frames` is {joint: [{q:[w,x,y,z], t:[x,y,z]}, ...]} engine quat order."""
    return track.from_edit(frames)
