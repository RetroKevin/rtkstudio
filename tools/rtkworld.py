"""Reader for Return to Krondor `Worlds/*.wlx` and `Worlds/*.ldx`.

Both use the same T3D FastFile container as `.trk` (magic `\\x02=PT`, version
0x15500), documented in docs/track-format.md and read by tools/rtktrack.py.
This module adds the two things `rtktrack` does not cover:

  1. **Header field 0x0c != 0.**  `rtkworld.wlx` is the only shipped file that
     sets it, and `rtktrack.Track` deliberately refuses rather than guess.
     `FUN_10022970` (out/decompiled/t3dll.c:27077) shows the field changes
     nothing at all about the byte layout -- see `FIELD_0C_MEANING` below.
  2. **Chunk types 0x21 and 0x22**, which no `.trk` uses:
     `FUN_10025800` (t3dll.c:29875) and `FUN_100258e0` (t3dll.c:29931).

Line numbers are against out/decompiled/ as regenerated 2026-10-05; the
"// ===== FUN_100258e0 @ 100258e0 =====" banner is the stable anchor, and
tools/_lines.py re-derives any citation.

See docs/world-format.md.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtktrack
from rtktrack import HEADER_SIZE, MAGIC, VERSION_BASE, unscramble

FIELD_0C_MEANING = """\
FUN_10022b80 (t3dll.c:27193) reads the 0x1c-byte header and binds field 0x0c
to the loader context at ctx+0x34 (t3dll.c:27217).  FUN_10022970 then branches
on it (t3dll.c:27134):

    if (local_18 == 0) {                      /* local_18 is ctx+0x34 */
  LAB_10022b23:
      ... read exactly header[0x08] chunks ...
    }
    if ((*(int *)(param_2 + 0x18) == 0) &&
        (local_10 = t3dAllocateMemory(local_18 << 6), local_10 != 0)) {
      iVar1 = t3dAllocateMemory(local_18 * 4);
      *(int *)(param_2 + 0x264) = iVar1;
      if (iVar1 != 0) goto LAB_10022b23;
    }

Both arms fall into the *same* chunk loop at LAB_10022b23, so the on-disk
format is identical either way.  The non-zero arm only pre-allocates two
runtime arrays: `field_0c * 0x40` bytes (kept at ctx+0x3c) and `field_0c * 4`
bytes (handed to the destination scene at +0x264).  The running index lives at
ctx+0x38 and is zeroed just before the loop (t3dll.c:27136).  FUN_100258e0,
the type-0x22 handler, is the consumer:

    if (ctx[0x38] < ctx[0x34]) {                   /* index < field_0c */
      obj = ctx[0x3c] + ctx[0x38] * 0x40;          /* the 0x40-byte slot */
      ...
      ctx[0x38] += 1;                              /* at t3dll.c:30371 */
    }

so **header field 0x0c is the number of type-0x22 objects the file defines**
(the capacity of the object table); a 0x22 chunk returns NULL -- which aborts
the whole load -- once the table is full.  `rtkworld.wlx` sets it to 1 and
contains exactly one 0x22 chunk."""

CHUNK_BSP = 0x21
CHUNK_OBJECT = 0x22
CHUNK_LIGHTDEF = 0x1B

# FUN_10025800: 7 dwords on disk scattered into an 8-dword runtime node.
BSP_NODE_WORDS = 7

# FUN_10023810's `puVar3[1]` bit flags, which gate the optional words of a
# polygon's material block.
MAT_HAS_BYTE = 0x01
MAT_HAS_FIELD2 = 0x02
MAT_HAS_FIELD3 = 0x04
MAT_HAS_TEXTURE = 0x08
MAT_HAS_UV_BASIS = 0x10
MAT_HAS_UV_LIST = 0x20

# FUN_100258e0's uses of the polygon's own leading flag word.
POLY_FLAG_OBJECT_PLANE = 0x01   # copy this polygon's plane to the object
POLY_FLAG_EXPLICIT_PLANE = 0x02  # 4 floats follow instead of being computed

# FUN_100258e0's uses of the object's flag word (payload dword 1).  Bit 0
# selects an explicit bounding sphere instead of the one FUN_100262d0
# (t3dll.c:30466) derives from the vertex cloud -- AABB centre plus the
# root-sum-square of the per-axis max deviations.  Bits 3 and 5 are copied to
# runtime slots but consume no stream bytes.
OBJ_FLAG_EXPLICIT_SPHERE = 0x01  # 4 floats {cx, cy, cz, r} near the end
OBJ_FLAG_EXTRA_1 = 0x02
OBJ_FLAG_EXTRA_2 = 0x04
OBJ_FLAG_BIT3 = 0x08
OBJ_FLAG_BIT5 = 0x20

# FUN_100258e0's uses of a segment's leading flag word.
SEG_FLAG_ONE = 0x01
SEG_FLAG_SCRAMBLED_BLOB = 0x04

# The segment "kind" values FUN_100258e0 accepts; anything else aborts the
# chunk (`goto LAB_10026099`).
SEG_KINDS = {9, 0xC, 0xE, 0x12, -15}


class Cursor:
    """A dword cursor over a chunk payload, so the reader can mirror the
    loader's pointer arithmetic one-for-one and then assert where it stopped.
    """

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def i32(self, n=1):
        v = struct.unpack_from("<%di" % n, self.data, self.pos)
        self.pos += 4 * n
        return v[0] if n == 1 else list(v)

    def f32(self, n=1):
        v = struct.unpack_from("<%df" % n, self.data, self.pos)
        self.pos += 4 * n
        return v[0] if n == 1 else list(v)

    def u16(self):
        v = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def raw(self, nbytes):
        v = self.data[self.pos:self.pos + nbytes]
        self.pos += nbytes
        return v

    @property
    def remaining(self):
        return len(self.data) - self.pos


class BspNode:
    """One node of a 0x21 chunk.  FUN_10025800 copies disk words 0..3 to the
    runtime node's first four slots, word 4 to slot 6, and turns words 5 and 6
    into pointers `base + idx * 8 - 8`, i.e. 1-based node indices with 0 as
    the null link."""

    __slots__ = ("plane", "field4", "front", "back")

    def __init__(self, plane, field4, front, back):
        self.plane = plane
        self.field4 = field4
        self.front = front      # 1-based node index, 0 = none
        self.back = back

    def __repr__(self):
        return "BspNode(plane=%s, field4=%d, front=%d, back=%d)" % (
            tuple(round(v, 4) for v in self.plane), self.field4,
            self.front, self.back)


class Bsp:
    """A 0x21 chunk."""

    def __init__(self, cur):
        self.field0 = cur.i32()
        count = cur.i32()
        self.nodes = []
        for _ in range(count):
            plane = cur.f32(4)
            field4 = cur.i32()
            front = cur.i32()
            back = cur.i32()
            self.nodes.append(BspNode(plane, field4, front, back))

    def __repr__(self):
        return "Bsp(%d nodes, field0=%d)" % (len(self.nodes), self.field0)


class Material:
    """The flag-gated block FUN_10023810 reads after a polygon's indices."""

    def __init__(self, cur, resolve):
        self.field0 = cur.i32()
        self.flags = cur.i32()
        self.byte_field = cur.i32() if self.flags & MAT_HAS_BYTE else None
        self.field2 = cur.i32() if self.flags & MAT_HAS_FIELD2 else None
        self.field3 = cur.f32() if self.flags & MAT_HAS_FIELD3 else None
        self.texture = None
        if self.flags & MAT_HAS_TEXTURE:
            self.texture = resolve(cur.i32())
        self.uv_basis = cur.f32(9) if self.flags & MAT_HAS_UV_BASIS else None
        self.uvs = None
        if self.flags & MAT_HAS_UV_LIST:
            n = cur.i32()
            self.uvs = [tuple(cur.f32(2)) for _ in range(n)]
        self.bit6 = bool(self.flags & 0x40)

    def __repr__(self):
        return "Material(flags=%#x, texture=%r)" % (self.flags, self.texture)


class Polygon:
    def __init__(self, cur, resolve):
        self.flags = cur.i32()
        n = cur.i32()
        self.indices = list(cur.i32(n)) if n != 1 else [cur.i32()]
        self.material = Material(cur, resolve)
        self.plane = None
        if self.flags & POLY_FLAG_EXPLICIT_PLANE:
            self.plane = cur.f32(4)

    def __repr__(self):
        return "Polygon(flags=%#x, indices=%s)" % (self.flags, self.indices)


class Segment:
    """One record of the object's third array.  FUN_100258e0 reads
    `{u32 flags, u32 ref, i32 kind}` and then dispatches on `kind`; for the
    0xe / 0x12 / -15 kinds the work is done by FUN_10024b60 (t3dll.c:29058),
    which consumes `count` vertex indices and, when called with a null
    override and the -15 flag, four more floats (the plane).

    `ref` is a 1-based object-table index stored as `ref - 1`, with 0 meaning
    "this object" -- FUN_100258e0 substitutes the running object index ctx+0x38
    in that case (t3dll.c:30191).
    """

    def __init__(self, cur):
        self.flags = cur.i32()
        self.ref = cur.i32()
        self.kind = cur.i32()
        self.indices = []
        self.polygon = None
        self.plane = None
        self.blob = None
        if self.kind in (0xE, -15):
            n = cur.i32()
            self.indices = list(cur.i32(n)) if n > 1 else (
                [cur.i32()] if n else [])
            if self.kind == -15:
                # FUN_10024b60's param_7 is `kind == -0xf`, and param_6 is
                # NULL here, so the plane is read from the stream.
                self.plane = cur.f32(4)
        elif self.kind == 0x12:
            # FUN_10024b60 is handed the already-parsed polygon's own index
            # array as param_2, not the chunk stream, so only the polygon
            # index comes off the wire (t3dll.c:30227).
            self.polygon = cur.i32()
        elif self.kind == 0xC:
            # Two vertex indices; the handler derives the distance between
            # them (t3dll.c:30249).
            self.indices = list(cur.i32(2))
        elif self.kind == 9:
            # One vertex index.  The handler advances the stream by 4 dwords
            # total, i.e. the 3 header dwords plus this one (t3dll.c:30262).
            self.indices = [cur.i32()]
        else:
            raise ValueError("segment kind %d is not one of %s"
                             % (self.kind, sorted(SEG_KINDS)))
        if self.flags & SEG_FLAG_SCRAMBLED_BLOB:
            n = cur.i32()
            if n:
                self.blob = unscramble(cur.raw(n))

    def __repr__(self):
        return "Segment(flags=%#x, ref=%d, kind=%d, indices=%s)" % (
            self.flags, self.ref, self.kind, self.indices)


class WorldObject:
    """A 0x22 chunk, per FUN_100258e0 (out/decompiled/t3dll.c:29931).

    The eight-dword fixed header is proven by `local_24 = local_10 + 8`
    (t3dll.c:29972), which is where the handler's stream cursor starts; the
    individual slots by the copies at t3dll.c:30065-30069.
    """

    def __init__(self, cur, resolve):
        self.name_ref = cur.i32()
        self.name = resolve(self.name_ref, as_name=True)
        self.flags = cur.i32()
        self.object_ref = cur.i32()
        vertex_count = cur.i32()
        self.field4 = cur.i32()
        polygon_count = cur.i32()
        segment_count = cur.i32()
        self.field7 = cur.i32()
        self.vertices = [tuple(cur.f32(3)) for _ in range(vertex_count)]
        self.polygons = [Polygon(cur, resolve) for _ in range(polygon_count)]
        self.segments = [Segment(cur) for _ in range(segment_count)]
        # The trailing fields, in the order FUN_100258e0 reads them.
        n = cur.u16()
        self.u16_blob = cur.raw(n * 2)
        self.sphere = cur.f32(4) \
            if self.flags & OBJ_FLAG_EXPLICIT_SPHERE else None
        self.extra1 = cur.i32() if self.flags & OBJ_FLAG_EXTRA_1 else None
        self.extra2 = cur.i32() if self.flags & OBJ_FLAG_EXTRA_2 else None
        n = cur.i32()
        # FUN_10022c80 is the same XOR descrambler the name block uses.  Note
        # the loader never advances its cursor past this blob (t3dll.c:30345),
        # because nothing follows it; we do, so that payload_slack is honest.
        self.user_data = unscramble(cur.raw(n)) if n else b""

    def bounds(self):
        if not self.vertices:
            return None
        lo = [min(v[i] for v in self.vertices) for i in range(3)]
        hi = [max(v[i] for v in self.vertices) for i in range(3)]
        return lo, hi

    def __repr__(self):
        return ("WorldObject(%r, flags=%#x, %d vertices, %d polygons, "
                "%d segments)" % (self.name, self.flags, len(self.vertices),
                                  len(self.polygons), len(self.segments)))


class RawChunk:
    def __init__(self, ctype, payload):
        self.ctype = ctype
        self.payload = payload

    def __repr__(self):
        return "RawChunk(%#x, %d bytes)" % (self.ctype, len(self.payload))


class World(rtktrack.Track):
    """The same container as `rtktrack.Track`, minus the field_0c veto, plus
    the 0x21 and 0x22 chunk handlers.

    Deliberately re-implements `__init__` instead of patching `rtktrack`:
    that module is owned elsewhere.  Everything reusable -- the magic, the
    version check, the XOR key and `unscramble`, and `_tag` -- is imported
    from it.
    """

    def __init__(self, path, data: bytes = None):
        self.path = Path(path)
        raw = self.path.read_bytes() if data is None else data
        self.raw = raw
        if raw[:4] != MAGIC:
            raise ValueError("bad magic %r" % (raw[:4],))
        (self.version, self.chunk_count, self.field_0c, self.max_chunk_size,
         self.name_bytes, self.field_18) = struct.unpack_from("<6I", raw, 4)
        if self.version & 0xFFFFFFFE != VERSION_BASE:
            raise ValueError("unsupported version %#x" % self.version)

        self.name_block = unscramble(
            raw[HEADER_SIZE:HEADER_SIZE + self.name_bytes])
        # Header 0x08 is the chunk count and header 0x18 is the *name* count.
        # Every .trk has one name per chunk so the two agree there; rtkworld
        # .wlx has 2 chunks and 1 name, which separates them.
        parts = self.name_block.split(b"\x00")[1:]
        self.names = [s.decode("latin-1") for s in parts[:self.field_18]]
        self.name_count = self.chunk_count   # for rtktrack API compatibility

        self.data_offset = HEADER_SIZE + self.name_bytes
        self.chunks = []
        self.objects = []
        self.bsps = []
        self.lightdefs = []
        self.trackdefs = []
        self.tracks = []
        self.sounds = []
        self._objects = [None]
        self.payload_slack = {}
        self._parse_chunks()

    def _resolve(self, ref, as_name=False):
        """The three-case name/object reference shared by every handler."""
        if ref < 0:
            return self._tag(ref)
        if as_name or ref == 0:
            return None
        return (self._objects[ref]
                if ref < len(self._objects) else ref)

    def _parse_chunks(self):
        raw = self.raw
        pos = self.data_offset
        for _ in range(self.chunk_count):
            if pos + 8 > len(raw):
                raise ValueError("chunk header past EOF at %d" % pos)
            size, ctype = struct.unpack_from("<II", raw, pos)
            body = pos + 8
            if body + size > len(raw):
                raise ValueError("chunk body past EOF at %d (size %d)"
                                 % (body, size))
            payload = raw[body:body + size]
            self.chunks.append((pos, size, ctype))
            cur = Cursor(payload)
            if ctype == CHUNK_BSP:
                obj = Bsp(cur)
                self.bsps.append(obj)
            elif ctype == CHUNK_OBJECT:
                obj = WorldObject(cur, self._resolve)
                self.objects.append(obj)
            else:
                obj = RawChunk(ctype, payload)
                if ctype == CHUNK_LIGHTDEF:
                    self.lightdefs.append(obj)
                cur.pos = len(payload)
            self.payload_slack[len(self.chunks) - 1] = cur.remaining
            self._objects.append(obj)
            pos = body + size
        self.end_offset = pos
        self.terminator = raw[pos:pos + 4]

    def __repr__(self):
        return ("World(%s, version=%#x, chunks=%d, field_0c=%d, "
                "objects=%d, bsps=%d)" % (
                    self.path.name, self.version, self.chunk_count,
                    self.field_0c, len(self.objects), len(self.bsps)))


def read(path):
    return World(path)


def dump(path):
    w = World(path)
    out = [repr(w),
           "  names: %s" % (w.names,),
           "  max_chunk_size=%d (actual max %d)" % (
               w.max_chunk_size,
               max((s for _, s, _ in w.chunks), default=0)),
           "  chunk stream ends at %d of %d, terminator %r" % (
               w.end_offset, len(w.raw), w.terminator),
           "  unconsumed payload bytes per chunk: %s" % (w.payload_slack,)]
    for b in w.bsps:
        out.append("  %r" % b)
        for n in b.nodes:
            out.append("    %r" % n)
    for o in w.objects:
        out.append("  %r" % o)
        lo, hi = o.bounds() or ([], [])
        out.append("    bounds %s .. %s" % (lo, hi))
        for i, v in enumerate(o.vertices):
            out.append("    v%-3d %s" % (i, v))
        for i, p in enumerate(o.polygons):
            out.append("    p%-3d %r %r" % (i, p, p.material))
        for i, s in enumerate(o.segments):
            out.append("    s%-3d %r plane=%s" % (i, s, s.plane))
        out.append("    trailing: u16_blob=%r sphere=%s extra=%s,%s "
                   "user_data=%r" % (o.u16_blob, o.sphere, o.extra1,
                                     o.extra2, o.user_data))
    return "\n".join(out)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(FIELD_0C_MEANING)
        raise SystemExit(0)
    for a in args:
        print(dump(a))
