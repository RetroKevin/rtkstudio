"""Reader for T3D hierarchical sprites -- the joint hierarchy ("dag" tree).

A `.trk` holds per-joint local transforms and joint names but no parent links.
The parent links live in a chunk type `0x10` ("hierarchical sprite
definition") inside the `.adf` scene files, which use the same T3D FastFile
container as `.trk`.

Format recovered from t3dll.dll's own loader:

    FUN_10022d60   chunk dispatch: case 0x10 -> FUN_10024120,
                                   case 0x11 -> FUN_10024300
    FUN_10024120   decodes a 0x10 payload: {i32 tag, i32 flags, i32 numdags,
                   i32 volume_ref}, flag-gated center offset / bounding
                   radius, then `numdags` variable-length dag records
    FUN_1001ab60   the dag constructor; pins which payload word lands in
                   which runtime field of the 0x140-byte dag struct
    FUN_10019810   the recursive world-transform walker; proves the sub-dag
                   list is the *child* list and gives the composition order
    FUN_10024300   decodes a 0x11 payload: {i32 tag, i32 def_ref}

See docs/sprite-format.md.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtktrack
from rtktrack import (  # noqa: F401  (re-export)
    Frame, RawChunk, TrackDef, TrackRef, unscramble,
)

CHUNK_SIMPLEDEF = 0x04
CHUNK_SIMPLE = 0x05
CHUNK_SPRITE3DDEF = 0x08
CHUNK_SPRITE3D = 0x09
CHUNK_HSPRITEDEF = 0x10
CHUNK_HSPRITE = 0x11
CHUNK_BMINFO = 0x2C

# FUN_10023360: flags & 4 / & 8 consume extra words before the frame list.
SIMPLE_FLAG_HAS_A = 4
SIMPLE_FLAG_HAS_B = 8

# FUN_10024120 reads piVar1[0..3] then flag-gates two optional groups.
HSPRITEDEF_HEADER_SIZE = 16
# piVar11 = piVar9 + 5, so five words before the sub-dag index array.
DAG_HEADER_SIZE = 20

# `if ((*(byte *)(piVar1 + 1) & 1) == 0) { local_c = local_8 = local_4 = 0; }`
# else three words are consumed; those three become the definition's default
# instance position (param_5 -> piVar5[9..11] in FUN_10019bb0).
HSPRITE_FLAG_HAS_OFFSET = 1
# `if ((*(byte *)(piVar1 + 1) & 2) == 0) { local_1c = 0x3f800000; }`
# else one word is consumed; it becomes param_7 -> the bounding radius.
HSPRITE_FLAG_HAS_RADIUS = 2

# t3dGetHierarchicalSpriteDagByIndex: `*(int *)(param_1 + 0x20) + param_2 * 0x140`
RUNTIME_DAG_SIZE = 0x140

DAG_SUFFIX = "_DAG"
TRACK_SUFFIX = "_TRACK"


class Dag:
    """One node of the joint hierarchy.

    Disk record, from the loop at t3dll.c:28392-28420:

        +0x00  i32  name reference        -> FUN_1001ab60 param_2, dag+0x04
        +0x04  i32  unused by the loader  (zero in every shipped file)
        +0x08  i32  track reference       -> FUN_1001ab60 param_4, dag+0x14
        +0x0c  i32  sprite reference      -> FUN_1001ab60 param_3, dag+0x08
        +0x10  u32  numSubDags            -> dag+0xec
        +0x14  u32[numSubDags]            -> dag+0xf0, converted in place
                                            from index to `base + i*0x140`
    """

    __slots__ = ("index", "name", "unk", "track_ref", "sprite_ref",
                 "children", "parent", "track", "sprite", "joint", "_nameref")

    def __init__(self, index, name, unk, track_ref, sprite_ref, children,
                 nameref=0):
        self.index = index
        self.name = name
        self._nameref = nameref
        self.unk = unk
        self.track_ref = track_ref
        self.sprite_ref = sprite_ref
        self.children = children
        self.parent = None
        self.track = None
        self.sprite = None
        # Filled in by HSpriteDef once the shared tag prefix is known.
        self.joint = base_tag(name)

    @property
    def base(self):
        """The dag tag minus its `_DAG` suffix."""
        return base_tag(self.name)

    def __repr__(self):
        return (f"Dag({self.index}, {self.name!r}, parent={self.parent}, "
                f"children={self.children})")


class HSpriteDef:
    """A chunk `0x10`: a named joint hierarchy."""

    def __init__(self, name, flags, volume_ref, center_offset,
                 bounding_radius, dags, tagref=0):
        self.name = name
        self._tagref = tagref
        self.flags = flags
        self.volume_ref = volume_ref
        self.center_offset = center_offset
        self.bounding_radius = bounding_radius
        self.dags = dags
        # The tag prefix is a convention of the asset pipeline, not a field:
        # every dag in a definition is tagged `PREFIX + joint + "_DAG"` and
        # points at a track tagged `PREFIX + joint + "_TRACK"`, so the shared
        # prefix falls out as the longest common prefix of the dag tags.
        self.prefix = _common_prefix([d.base for d in dags])
        for d in dags:
            d.joint = d.base[len(self.prefix):] or d.base
        self._link_parents()

    def _link_parents(self):
        for d in self.dags:
            for c in d.children:
                if 0 <= c < len(self.dags):
                    self.dags[c].parent = d.index

    # -- topology ----------------------------------------------------------
    @property
    def roots(self):
        return [d.index for d in self.dags if d.parent is None]

    @property
    def root(self):
        """FUN_10019770 starts the world-transform walk at dag 0, so dag 0 is
        the root by construction."""
        return 0

    def check(self):
        """Returns a list of structural problems; empty means the hierarchy is
        a single-rooted tree with every index in range and no cycles."""
        problems = []
        n = len(self.dags)
        seen = [0] * n
        for d in self.dags:
            for c in d.children:
                if not 0 <= c < n:
                    problems.append(f"dag {d.index} child index {c} out of range")
                    continue
                seen[c] += 1
        for i, k in enumerate(seen):
            if k > 1:
                problems.append(f"dag {i} is listed as a child {k} times")
        roots = self.roots
        if len(roots) != 1:
            problems.append(f"{len(roots)} roots: {roots}")
        elif roots[0] != 0:
            problems.append(f"root is dag {roots[0]}, not dag 0")
        # Reachability from dag 0 both proves connectivity and, combined with
        # the single-parent check above, rules out cycles.
        order = self.walk()
        if len(order) != n:
            problems.append(f"{n - len(order)} dags unreachable from dag 0")
        return problems

    def walk(self, start=0):
        """Depth-first pre-order from `start`, the order FUN_10019810
        recurses in. Stops on revisit so a malformed cycle cannot hang."""
        out = []
        visited = set()
        stack = [start]
        while stack:
            i = stack.pop()
            if i in visited or not 0 <= i < len(self.dags):
                continue
            visited.add(i)
            out.append(i)
            stack.extend(reversed(self.dags[i].children))
        return out

    def depth(self, i):
        d = 0
        p = self.dags[i].parent
        while p is not None and d < len(self.dags):
            d += 1
            p = self.dags[p].parent
        return d

    @property
    def parents(self):
        """Parent index per dag; None for the root."""
        return [d.parent for d in self.dags]

    def joints(self):
        """{joint name -> dag index}, case-folded joint names."""
        return {d.joint.upper(): d.index for d in self.dags}

    def tag_consistency(self):
        """(agree, disagree, offenders): how many dags point at a track whose
        own tag is the dag's tag with `_DAG` swapped for `_TRACK`.

        The two tags are stored independently -- one in the 0x10 chunk, one in
        the 0x13 chunk it references -- so agreement is a real cross-check
        that the track reference field is the field we think it is. The test
        is deliberately prefix-independent.
        """
        agree = disagree = 0
        offenders = []
        for d in self.dags:
            tn = getattr(d.track, "name", None)
            if tn and base_tag(tn, TRACK_SUFFIX) == d.base:
                agree += 1
            else:
                disagree += 1
                offenders.append((d.name, tn))
        return agree, disagree, offenders

    def __repr__(self):
        return f"HSpriteDef({self.name!r}, dags={len(self.dags)})"


class HSprite:
    """A chunk `0x11`: an instance of a definition. FUN_10024300 reads
    `{i32 tag, i32 def_ref}` and calls t3dCreateHierarchicalSprite."""

    def __init__(self, name, def_ref, definition, tagref=0, unk=0):
        self.name = name
        self._tagref = tagref
        self.def_ref = def_ref
        self.definition = definition
        # A third word is on disk but FUN_10024300 never reads it. Zero in
        # all 98 shipped instances.
        self.unk = unk

    def __repr__(self):
        return f"HSprite({self.name!r}, def={self.definition!r})"


class SimpleSpriteDef:
    """Chunk 0x04: t3dDefineSimpleSprite. FUN_10023360.

    {i32 tag, i32 flags, i32 count} then optional extras (flags & 4, & 8)
    then `count` object references -- the frames. Those resolve to BMInfo
    (0x2c) entries whose scrambled name is the archive .bmp.
    """

    ctype = CHUNK_SIMPLEDEF

    def __init__(self, name, flags, frames, extra_a=0, extra_b=1, tagref=0,
                 frame_refs=None):
        self.name = name
        self.flags = flags
        self.frames = frames          # resolved objects, after _resolve
        self.frame_refs = frame_refs or []
        self.extra_a = extra_a
        self.extra_b = extra_b
        self._tagref = tagref

    def to_bytes(self):
        out = struct.pack("<3i", self._tagref, self.flags, len(self.frame_refs))
        if self.flags & SIMPLE_FLAG_HAS_A:
            out += struct.pack("<i", self.extra_a)
        if self.flags & SIMPLE_FLAG_HAS_B:
            out += struct.pack("<i", self.extra_b)
        for r in self.frame_refs:
            out += struct.pack("<i", r)
        return out

    def __repr__(self):
        return f"SimpleSpriteDef({self.name!r}, frames={len(self.frame_refs)})"


class SimpleSprite:
    """Chunk 0x05: t3dCreateSimpleSprite. FUN_10023430.

    Always 12 bytes: {i32 tag, i32 def_ref, i32 flags}.
    """

    ctype = CHUNK_SIMPLE

    def __init__(self, name, def_ref, flags, definition=None, tagref=0):
        self.name = name
        self.def_ref = def_ref
        self.flags = flags
        self.definition = definition
        self._tagref = tagref

    def to_bytes(self):
        return struct.pack("<3i", self._tagref, self.def_ref, self.flags)

    def __repr__(self):
        return f"SimpleSprite({self.name!r}, def={self.def_ref})"


class Poly:
    """One polygon of a 3D sprite definition."""

    __slots__ = ("indices", "tex_ref", "mat_flags", "uvs", "neighbours",
                 "texture", "mat_field0", "mat_index")

    def __init__(self, indices, tex_ref, mat_flags, uvs, neighbours,
                 mat_field0=0, mat_index=None):
        self.indices = indices
        self.tex_ref = tex_ref
        self.mat_flags = mat_flags
        self.uvs = uvs
        self.neighbours = neighbours
        self.texture = None
        self.mat_field0 = mat_field0
        self.mat_index = mat_index


class Sprite3DDef:
    """Chunk 0x08: t3dDefine3DSprite. FUN_10023ad0.

    Vertices are local to the dag that instances this definition. Material
    flag 0x08 holds a reference to the BMInfo / simple-sprite used as the
    texture; UVs live in the material when flags & 0x20.
    """

    ctype = CHUNK_SPRITE3DDEF

    def __init__(self, name, flags, verts, polys, volume_ref=0,
                 center=(0, 0, 0), radius=1.0, tagref=0, payload=None):
        self.name = name
        self.flags = flags
        self.verts = verts
        self.polys = polys
        self.volume_ref = volume_ref
        self.center = center
        self.radius = radius
        self._tagref = tagref
        # Original bytes, kept so identity rebuild of the *file* is unaffected
        # and so we never have to reverse every material flag to write.
        self.payload = payload

    def __repr__(self):
        return (f"Sprite3DDef({self.name!r}, verts={len(self.verts)}, "
                f"polys={len(self.polys)})")


class Sprite3D:
    """Chunk 0x09: t3dCreate3DSprite. FUN_10023ee0. Always 12 bytes."""

    ctype = CHUNK_SPRITE3D

    def __init__(self, name, def_ref, flags, definition=None, tagref=0):
        self.name = name
        self.def_ref = def_ref
        self.flags = flags
        self.definition = definition
        self._tagref = tagref

    def __repr__(self):
        return f"Sprite3D({self.name!r}, def={self.def_ref})"


class BMInfo:
    """Chunk 0x2c: t3dDefineBMInfoMIPMapped. FUN_100231b0.

    A tag plus one XOR-scrambled filename (the archive .bmp), then zero or
    more extra mip names, then pad to a 4-byte boundary.
    """

    ctype = CHUNK_BMINFO

    def __init__(self, name, flags, filename, mips=None, tagref=0):
        self.name = name
        self.flags = flags
        self.filename = filename
        self.mips = mips or []
        self._tagref = tagref

    def __repr__(self):
        return f"BMInfo({self.name!r}, {self.filename!r})"


def base_tag(name, suffix=DAG_SUFFIX):
    """Drop a trailing suffix from an object tag."""
    if name and name.endswith(suffix):
        return name[: -len(suffix)]
    return name or ""


def _common_prefix(strings):
    if not strings:
        return ""
    lo, hi = min(strings), max(strings)
    i = 0
    while i < len(lo) and i < len(hi) and lo[i] == hi[i]:
        i += 1
    return lo[:i]


class SpriteFile(rtktrack.Track):
    """A T3D FastFile read for its hierarchical sprites.

    Reuses the container layer proven byte-exact by tools/roundtrip_tracks.py
    and adds the two chunk types that carry the rig.
    """

    def _parse_chunks(self):
        self.hsprite_defs = []
        self.hsprites = []
        self.simple_defs = []
        self.simples = []
        self.sprite3d_defs = []
        self.sprite3ds = []
        self.bminfos = []
        # chunk offset -> parsed object, so a validator can line a rebuilt
        # payload back up against the original bytes.
        self._def_at = {}
        self._inst_at = {}
        raw = self.raw
        pos = self.data_offset
        for _ in range(self.name_count):
            if pos + 8 > len(raw):
                raise ValueError(f"chunk header past EOF at {pos}")
            size, ctype = struct.unpack_from("<II", raw, pos)
            body = pos + 8
            if body + size > len(raw):
                raise ValueError(f"chunk body past EOF at {body} (size {size})")
            self.chunks.append((pos, size, ctype))

            if ctype == rtktrack.CHUNK_TRACKDEF:
                obj = self._read_trackdef(raw, body, size)
                self.trackdefs.append(obj)
            elif ctype == rtktrack.CHUNK_TRACK:
                obj = self._read_track(raw, body, size)
                self.tracks.append(obj)
            elif ctype == CHUNK_HSPRITEDEF:
                obj = self._read_hspritedef(raw, body, size)
                self.hsprite_defs.append(obj)
                self._def_at[pos] = obj
            elif ctype == CHUNK_HSPRITE:
                obj = self._read_hsprite(raw, body, size)
                self.hsprites.append(obj)
                self._inst_at[pos] = obj
            elif ctype == CHUNK_SIMPLEDEF:
                obj = self._read_simpledef(raw, body, size)
                self.simple_defs.append(obj)
            elif ctype == CHUNK_SIMPLE:
                obj = self._read_simple(raw, body, size)
                self.simples.append(obj)
            elif ctype == CHUNK_SPRITE3DDEF:
                obj = self._read_sprite3ddef(raw, body, size)
                self.sprite3d_defs.append(obj)
            elif ctype == CHUNK_SPRITE3D:
                obj = self._read_sprite3d(raw, body, size)
                self.sprite3ds.append(obj)
            elif ctype == CHUNK_BMINFO:
                obj = self._read_bminfo(raw, body, size)
                self.bminfos.append(obj)
            else:
                obj = RawChunk(ctype, raw[body:body + size])
            self._objects.append(obj)
            pos = body + size
        self.end_offset = pos
        self.terminator = raw[pos:pos + 4]
        self._resolve_dag_refs()
        self._resolve_sprites()

    def _read_hspritedef(self, raw, body, size):
        tag, flags, ndags, volume_ref = struct.unpack_from("<4i", raw, body)
        off = body + HSPRITEDEF_HEADER_SIZE
        center_offset = (0.0, 0.0, 0.0)
        if flags & HSPRITE_FLAG_HAS_OFFSET:
            center_offset = struct.unpack_from("<3f", raw, off)
            off += 12
        bounding_radius = 1.0
        if flags & HSPRITE_FLAG_HAS_RADIUS:
            bounding_radius = struct.unpack_from("<f", raw, off)[0]
            off += 4

        end = body + size
        dags = []
        for i in range(ndags):
            if off + DAG_HEADER_SIZE > end:
                raise ValueError(f"dag {i} header past chunk end")
            nameref, unk, track_ref, sprite_ref, nsub = struct.unpack_from(
                "<5i", raw, off)
            off += DAG_HEADER_SIZE
            if nsub < 0 or off + 4 * nsub > end:
                raise ValueError(f"dag {i} sub-dag list ({nsub}) past chunk end")
            children = list(struct.unpack_from(f"<{nsub}i", raw, off)) if nsub else []
            off += 4 * nsub
            dags.append(Dag(i, self._tag(nameref), unk, track_ref, sprite_ref,
                            children, nameref))
        if off != end:
            raise ValueError(f"hspritedef trailing {end - off} bytes")
        return HSpriteDef(self._tag(tag), flags, volume_ref, center_offset,
                          bounding_radius, dags, tag)

    def _read_hsprite(self, raw, body, size):
        if size != 12:
            raise ValueError(f"hsprite chunk size {size} != 12")
        tag, def_ref, unk = struct.unpack_from("<3i", raw, body)
        return HSprite(self._tag(tag), def_ref, self._object(def_ref), tag, unk)

    def _read_simpledef(self, raw, body, size):
        tag, flags, count = struct.unpack_from("<3i", raw, body)
        off = body + 12
        extra_a, extra_b = 0, 1
        if flags & SIMPLE_FLAG_HAS_A:
            extra_a = struct.unpack_from("<i", raw, off)[0]
            off += 4
        if flags & SIMPLE_FLAG_HAS_B:
            extra_b = struct.unpack_from("<i", raw, off)[0]
            off += 4
        refs = list(struct.unpack_from("<%di" % count, raw, off)) if count else []
        off += 4 * count
        if off != body + size:
            raise ValueError("simpledef size %d != consumed %d" %
                             (size, off - body))
        return SimpleSpriteDef(self._tag(tag), flags, [], extra_a, extra_b,
                               tag, refs)

    def _read_simple(self, raw, body, size):
        if size != 12:
            raise ValueError("simple sprite size %d != 12" % size)
        tag, def_ref, flags = struct.unpack_from("<3i", raw, body)
        return SimpleSprite(self._tag(tag), def_ref, flags, None, tag)

    def _read_sprite3d(self, raw, body, size):
        if size != 12:
            raise ValueError("3d sprite size %d != 12" % size)
        tag, def_ref, flags = struct.unpack_from("<3i", raw, body)
        return Sprite3D(self._tag(tag), def_ref, flags, None, tag)

    def _read_bminfo(self, raw, body, size):
        tag, flags, extras = struct.unpack_from("<3i", raw, body)
        namelen = struct.unpack_from("<H", raw, body + 12)[0]
        filename = unscramble(raw[body + 14:body + 14 + namelen])
        filename = filename.split(b"\x00")[0].decode("latin-1")
        off = body + 14 + namelen
        mips = []
        for _ in range(extras):
            ln = struct.unpack_from("<H", raw, off)[0]
            off += 2
            s = unscramble(raw[off:off + ln]).split(b"\x00")[0].decode("latin-1")
            off += ln
            mips.append(s)
        # Payload is padded to a 4-byte boundary; the pad is zeros.
        return BMInfo(self._tag(tag), flags, filename, mips, tag)

    def _read_sprite3ddef(self, raw, body, size):
        end = body + size
        tag, flags, nverts, npolys, vol = struct.unpack_from("<5i", raw, body)
        off = body + 20
        center = (0.0, 0.0, 0.0)
        radius = 1.0
        if flags & 1:
            center = struct.unpack_from("<3f", raw, off)
            off += 12
        if flags & 2:
            radius = struct.unpack_from("<f", raw, off)[0]
            off += 4
        verts = [struct.unpack_from("<3f", raw, off + i * 12)
                 for i in range(nverts)]
        off += nverts * 12
        polys = []
        for _ in range(npolys):
            n = struct.unpack_from("<I", raw, off)[0]
            off += 4
            neigh = struct.unpack_from("<2i", raw, off)
            off += 8
            idx = list(struct.unpack_from("<%dI" % n, raw, off))
            off += n * 4
            off, mat_flags, tex, uvs, field0, color = self._read_material(raw, off)
            if flags & 0x40:
                off += 16
            polys.append(Poly(idx, tex, mat_flags, uvs, neigh, field0, color))
        if off != end:
            raise ValueError("3ddef size %d != consumed %d" % (size, off - body))
        return Sprite3DDef(self._tag(tag), flags, verts, polys, vol, center,
                           radius, tag, raw[body:end])

    def _read_material(self, raw, off):
        # FUN_10023810: two words then flag-gated extras.
        # flags&1 is a byte stored at material+0x10 — a palette index
        # used as the flat colour when there is no texture.
        field0, flags = struct.unpack_from("<2I", raw, off)
        off += 8
        tex = None
        uvs = []
        color = None
        if flags & 1:
            color = struct.unpack_from("<I", raw, off)[0] & 0xFF
            off += 4
        if flags & 2:
            off += 4
        if flags & 4:
            off += 4
        if flags & 8:
            tex = struct.unpack_from("<i", raw, off)[0]
            off += 4
        if flags & 0x10:
            off += 36
        if flags & 0x20:
            n = struct.unpack_from("<I", raw, off)[0]
            off += 4
            uvs = [struct.unpack_from("<2f", raw, off + i * 8) for i in range(n)]
            off += n * 8
        return off, flags, tex, uvs, field0, color

    def _object(self, ref):
        """A reference is either a negative byte offset into the name block or
        a positive 1-based index into the object table (FUN_10024120 lines
        28398-28411)."""
        if ref < 0:
            name = self._tag(ref)
            for obj in self._objects[1:]:
                if getattr(obj, "name", None) == name:
                    return obj
            return name
        if 0 < ref < len(self._objects):
            return self._objects[ref]
        return None

    def _resolve_dag_refs(self):
        for d in self.hsprite_defs:
            for dag in d.dags:
                dag.track = self._object(dag.track_ref)
                dag.sprite = self._object(dag.sprite_ref)

    def _resolve_sprites(self):
        for s in self.simple_defs:
            s.frames = [self._object(r) for r in s.frame_refs]
        for s in self.simples:
            s.definition = self._object(s.def_ref)
        for s in self.sprite3ds:
            s.definition = self._object(s.def_ref)
        for d in self.sprite3d_defs:
            for poly in d.polys:
                poly.texture = self._object(poly.tex_ref) if poly.tex_ref else None

    def __repr__(self):
        return (f"SpriteFile({self.path.name}, names={self.name_count}, "
                f"hsprite_defs={len(self.hsprite_defs)})")


def load_hierarchies(paths):
    """{definition tag -> HSpriteDef} over the given files, first wins.

    The `.adf` set contains byte-identical duplicates (the same scene file is
    present in more than one `.t3d` archive), so keying by tag de-duplicates.
    """
    out = {}
    for p in paths:
        try:
            sf = SpriteFile(p)
        except Exception:
            continue
        for d in sf.hsprite_defs:
            out.setdefault(d.name, d)
    return out


def find_adf(root=None):
    root = Path(root) if root else Path(__file__).resolve().parent.parent / "out" / "t3d"
    return sorted(Path(root).rglob("*.adf"))


def track_joints(track):
    """Joint names of a parsed .trk, case-folded.

    A `.trk` tags its chunks `STEM + joint + "_TRACKDEF"`, where STEM is the
    file name without extension -- the same fixed-width animation id that
    RtK.c FUN_0052b981 substitutes into the dag's default track tag.
    """
    stem = track.path.stem.upper()
    out = []
    for d in track.trackdefs:
        if not d.name:
            continue
        t = d.name.upper()
        if t.startswith(stem) and t.endswith("_TRACKDEF"):
            out.append(t[len(stem):-len("_TRACKDEF")])
    return out


def rest_pose(rig):
    """{joint -> Frame} from each dag's own single-frame default track.

    The `.adf` gives every dag a one-keyframe track; that keyframe is the
    bind pose, and its translation is the bone's offset from its parent.
    """
    out = {}
    for d in rig.dags:
        de = getattr(d.track, "definition", None)
        if de is not None and de.frames:
            out[d.joint.upper()] = de.frames[0]
    return out


def score_rig(track, rig, tol=1e-2):
    """How well a rig's bone offsets match a .trk's joint translations.

    Returns (n_agree, n_compared). A `.trk` stores a translation per joint
    per frame; for a joint that only rotates, that translation is the bone
    offset, and it must equal the rig's bind-pose offset. The two values live
    in different files, so a high agreement rate identifies the rig the
    animation was authored against.
    """
    rest = rest_pose(rig)
    agree = total = 0
    for d, j in zip(track.trackdefs, track_joints(track)):
        if j not in rest or not d.frames:
            continue
        total += 1
        a = rest[j].translation
        b = d.frames[0].translation
        if max(abs(x - y) for x, y in zip(a, b)) < tol:
            agree += 1
    return agree, total


def match_rig(track, hierarchies):
    """Pick the rig for a parsed `.trk`.

    Requires full joint coverage, then ranks the candidates by bind-pose
    bone-offset agreement (see `score_rig`). Returns
    (tag, HSpriteDef, n_agree, n_compared) or (None, None, 0, 0).
    """
    want = set(track_joints(track))
    best = None
    for tag, d in sorted(hierarchies.items()):
        if not want <= set(d.joints()):
            continue
        agree, total = score_rig(track, d)
        score = (-agree / total if total else 0.0, len(d.dags), tag)
        if best is None or score < best[0]:
            best = (score, tag, d, agree, total)
    if best is None:
        return None, None, 0, 0
    return best[1], best[2], best[3], best[4]


if __name__ == "__main__":
    args = sys.argv[1:] or [str(p) for p in find_adf()]
    for a in args:
        sf = SpriteFile(Path(a))
        for d in sf.hsprite_defs:
            print(f"{Path(a).name}: {d.name}  {len(d.dags)} dags  "
                  f"flags={d.flags:#x} radius={d.bounding_radius:g} "
                  f"problems={d.check() or 'none'}")
            for i in d.walk():
                dag = d.dags[i]
                track = getattr(dag.track, "name", dag.track)
                print(f"    {'  ' * d.depth(i)}{dag.joint:16} "
                      f"[{i:3}] track={track}")
