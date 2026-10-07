"""Reader for Return to Krondor .trk animation tracks (T3D FastFile variant).

Format recovered from t3dll.dll's own loader:

    FUN_10022b80   reads the 28-byte header and the XOR-scrambled name block
    FUN_10022970   then loops name_count times calling FUN_10022d60
    FUN_10022d60   reads an 8-byte {u32 size, u32 type} chunk header, pulls
                   `size` payload bytes via FUN_100265b0, and dispatches on
                   type -- 0x12 is a track definition, 0x13 is a track
    FUN_10024380   decodes a 0x12 payload: {i32 tag, i32 unk, i32 frames}
                   followed by frames * 8 floats
    FUN_10024460   decodes a 0x13 payload: {i32 tag, i32 def, i32 flags
                   [, i32 update_interval]}

So a .trk is a chunk stream, not a flat keyframe array. See
docs/track-format.md.
"""

import struct
from pathlib import Path

MAGIC = b"\x02=PT"
VERSION_BASE = 0x15500  # parser accepts VERSION_BASE and VERSION_BASE | 1

# DAT_1010f728 in t3dll.dll. The constant that follows it in memory is the
# file magic itself, which is a handy confirmation the address is right.
XOR_KEY = bytes.fromhex("953ac52a957a956a")

HEADER_SIZE = 28

CHUNK_TRACKDEF = 0x12
CHUNK_TRACK = 0x13
# One shipped track (TK0048M) also carries the two sound chunks.
CHUNK_WAVINFO = 0x1E
CHUNK_SOUNDDEF = 0x1F

# FUN_10024380 copies 8 source floats into the 9-float (0x24) runtime frame.
DISK_FRAME_SIZE = 32
TRACKDEF_HEADER_SIZE = 12

# t3dSetTrackDefaultReverse / t3dSetTrackDefaultInterpolate read bits 1 and 2
# of the flags word in FUN_10024460; bit 0 gates update_interval.
TRACK_FLAG_HAS_INTERVAL = 1
TRACK_FLAG_REVERSE = 2
TRACK_FLAG_INTERPOLATE = 4


def unscramble(data: bytes) -> bytes:
    """FUN_10022c80: XOR against the repeating 8-byte key."""
    return bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(data))


class Frame:
    """One keyframe. Field order here is the runtime 0x24 struct order."""

    __slots__ = ("quat", "translation", "scale")

    def __init__(self, quat, translation, scale):
        self.quat = quat
        self.translation = translation
        self.scale = scale

    def __repr__(self):
        return (f"Frame(quat={self.quat}, translation={self.translation}, "
                f"scale={self.scale})")


class TrackDef:
    """A 0x12 chunk: the keyframe array for one joint."""

    def __init__(self, name, unk, frames, offset):
        self.name = name
        self.unk = unk
        self.frames = frames
        self.offset = offset

    @property
    def joint(self):
        return _strip_suffix(self.name, "_TRACKDEF")

    def __repr__(self):
        return f"TrackDef({self.name!r}, frames={len(self.frames)})"


class TrackRef:
    """A 0x13 chunk: binds a name and playback defaults to a TrackDef."""

    def __init__(self, name, definition, flags, update_interval):
        self.name = name
        self.definition = definition
        self.flags = flags
        self.update_interval = update_interval

    @property
    def joint(self):
        return _strip_suffix(self.name, "_TRACK")

    @property
    def reverse(self):
        return bool(self.flags & TRACK_FLAG_REVERSE)

    @property
    def interpolate(self):
        return bool(self.flags & TRACK_FLAG_INTERPOLATE)

    def __repr__(self):
        return f"TrackRef({self.name!r}, flags={self.flags:#x})"


def _strip_suffix(name, suffix):
    if name and name.endswith(suffix):
        return name[: -len(suffix)]
    return name


class WavInfo:
    """A 0x1e chunk, per FUN_10025430: {i32 tag, u16 len} then a path of
    `len` bytes scrambled with the same XOR key as the name block."""

    def __init__(self, name, path):
        self.name = name
        self.path = path

    def __repr__(self):
        return f"WavInfo({self.name!r}, {self.path!r})"


class SoundDef:
    """A 0x1f chunk, per FUN_10025480. Fields past the fixed four are
    flag-gated; only the fixed part is decoded here."""

    def __init__(self, name, flags, field2, wav_ref, extra):
        self.name = name
        self.flags = flags
        self.field2 = field2
        self.wav_ref = wav_ref
        self.extra = extra

    def __repr__(self):
        return f"SoundDef({self.name!r}, flags={self.flags:#x})"


class RawChunk:
    def __init__(self, ctype, payload):
        self.ctype = ctype
        self.payload = payload

    def __repr__(self):
        return f"RawChunk({self.ctype:#x}, {len(self.payload)} bytes)"


class Track:
    def __init__(self, path: Path, data: bytes = None):
        self.path = Path(path)
        raw = self.path.read_bytes() if data is None else data
        self.raw = raw
        if raw[:4] != MAGIC:
            raise ValueError(f"bad magic {raw[:4]!r}")

        # FUN_10022b80 reads 0x1c bytes but only binds six of them.
        # `name_count` at 0x08 is really the CHUNK count and `field_18` at
        # 0x18 the name count. They are equal in all 917 .trk, so the two
        # readings are indistinguishable there; Worlds/rtkworld.wlx separates
        # them (2 chunks, 1 name). The attribute keeps its name because the
        # chunk loop and the public API are built on it.
        (self.version, self.name_count, self.field_0c, self.max_chunk_size,
         self.name_bytes, self.field_18) = struct.unpack_from("<6I", raw, 4)
        if self.version & 0xFFFFFFFE != VERSION_BASE:
            raise ValueError(f"unsupported version {self.version:#x}")
        # field_0c is the number of type-0x22 world objects the file defines.
        # Both arms of the branch in FUN_10022970 fall into the same chunk
        # loop; the non-zero arm only pre-allocates the object table, so the
        # byte layout is unaffected. Only Worlds/rtkworld.wlx sets it, and
        # tools/rtkworld.py handles the 0x21/0x22 chunks it unlocks.

        self.name_block = unscramble(
            raw[HEADER_SIZE:HEADER_SIZE + self.name_bytes])
        # The block opens with a NUL sentinel, then field_18 NUL-terminated
        # strings, then slack bytes left over from the allocation.
        parts = self.name_block.split(b"\x00")[1:]
        self.names = [s.decode("latin-1") for s in parts[:self.field_18]]

        self.data_offset = HEADER_SIZE + self.name_bytes
        self.chunks = []
        self.trackdefs = []
        self.tracks = []
        self.sounds = []
        self._objects = [None]  # FUN_10022970 keeps a 1-based object table
        self._parse_chunks()

    # -- name references ---------------------------------------------------
    def _tag(self, ref):
        """FUN_10024380/FUN_10024460 resolve a tag as `name_block - ref`, so a
        negative ref is a byte offset into the name block. The block opens
        with a NUL, so offset 0 is the empty string and ref 0 can mean
        untagged -- which is exactly what FUN_10024460 tests for."""
        if ref >= 0:
            return None
        off = -ref
        end = self.name_block.find(b"\x00", off)
        if end < 0:
            end = len(self.name_block)
        return self.name_block[off:end].decode("latin-1")

    # -- chunk stream ------------------------------------------------------
    def _parse_chunks(self):
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

            if ctype == CHUNK_TRACKDEF:
                obj = self._read_trackdef(raw, body, size)
                self.trackdefs.append(obj)
            elif ctype == CHUNK_TRACK:
                obj = self._read_track(raw, body, size)
                self.tracks.append(obj)
            elif ctype == CHUNK_WAVINFO:
                obj = self._read_wavinfo(raw, body, size)
                self.sounds.append(obj)
            elif ctype == CHUNK_SOUNDDEF:
                obj = self._read_sounddef(raw, body, size)
                self.sounds.append(obj)
            else:
                obj = RawChunk(ctype, raw[body:body + size])
            self._objects.append(obj)
            pos = body + size
        self.end_offset = pos
        self.terminator = raw[pos:pos + 4]

    def _read_trackdef(self, raw, body, size):
        tag, unk, count = struct.unpack_from("<iii", raw, body)
        want = TRACKDEF_HEADER_SIZE + count * DISK_FRAME_SIZE
        if want != size:
            raise ValueError(f"trackdef size {size} != 12 + {count}*32 = {want}")
        frames = []
        off = body + TRACKDEF_HEADER_SIZE
        for i in range(count):
            # Disk order is scale, translation, quaternion. FUN_10024380
            # scatters src[0]->dst[7], src[1..3]->dst[4..6], src[4..7]->dst[0..3].
            f = struct.unpack_from("<8f", raw, off + i * DISK_FRAME_SIZE)
            frames.append(Frame(f[4:8], f[1:4], f[0]))
        return TrackDef(self._tag(tag), unk, frames, body)

    def _read_track(self, raw, body, size):
        if size not in (12, 16):
            raise ValueError(f"track chunk size {size} not 12 or 16")
        tag, defref, flags = struct.unpack_from("<iii", raw, body)
        interval = None
        if flags & TRACK_FLAG_HAS_INTERVAL and size >= 16:
            interval = struct.unpack_from("<i", raw, body + 12)[0]
        if defref >= 0:
            definition = self._objects[defref] if defref < len(self._objects) else None
        else:
            name = self._tag(defref)
            definition = next((d for d in self.trackdefs if d.name == name), None)
        return TrackRef(self._tag(tag), definition, flags, interval)

    def _read_wavinfo(self, raw, body, size):
        tag = struct.unpack_from("<i", raw, body)[0]
        length = struct.unpack_from("<H", raw, body + 4)[0]
        text = unscramble(raw[body + 6:body + 6 + length])
        return WavInfo(self._tag(tag), text.split(b"\x00")[0].decode("latin-1"))

    def _read_sounddef(self, raw, body, size):
        tag, flags, field2, wav_ref = struct.unpack_from("<4i", raw, body)
        extra = raw[body + 16:body + size]
        return SoundDef(self._tag(tag), flags, field2, wav_ref, extra)

    # -- convenience -------------------------------------------------------
    @property
    def joints(self):
        """Joint names in file order, from the _TRACKDEF chunk tags."""
        return [d.joint for d in self.trackdefs]

    def joint_frames(self):
        """{joint name -> [Frame, ...]} for every track definition."""
        return {d.joint: d.frames for d in self.trackdefs}

    @property
    def frames(self) -> int:
        """Longest per-joint keyframe count in the file."""
        return max((len(d.frames) for d in self.trackdefs), default=0)

    def to_bytes(self, rebuild_names=False) -> bytes:
        """Re-serialise. Identity when `rebuild_names` is false: all 917
        shipped .trk files come back byte-exact (see roundtrip_tracks.py).
        """
        if rebuild_names:
            block, offsets = _pack_names(self._all_names())
        else:
            block = self.name_block
            offsets = _name_offsets(block)

        def ref(name):
            if name is None:
                return 0
            return -offsets[name]

        out = bytearray()
        name_bytes = len(block)
        name_count = max(0, len(self._objects) - 1)
        field_18 = len(self.names) if not rebuild_names else sum(
            1 for n in self._all_names() if n)
        out += struct.pack("<4s6I", MAGIC, self.version, name_count,
                           self.field_0c, self.max_chunk_size, name_bytes,
                           field_18 if not rebuild_names else field_18)
        out += unscramble(block)

        index = {id(o): i for i, o in enumerate(self._objects)}
        for obj in self._objects[1:]:
            if isinstance(obj, TrackDef):
                body = struct.pack("<3i", ref(obj.name), obj.unk, len(obj.frames))
                for f in obj.frames:
                    body += struct.pack("<8f", f.scale, *f.translation, *f.quat)
                ctype = CHUNK_TRACKDEF
            elif isinstance(obj, TrackRef):
                defref = index[id(obj.definition)]
                body = struct.pack("<3i", ref(obj.name), defref, obj.flags)
                if obj.update_interval is not None:
                    body += struct.pack("<i", obj.update_interval)
                ctype = CHUNK_TRACK
            elif isinstance(obj, WavInfo):
                text = obj.path.encode("latin-1") + b"\x00"
                pad = (-(6 + len(text))) % 4
                body = (struct.pack("<iH", ref(obj.name), len(text))
                        + unscramble(text) + bytes(pad))
                ctype = CHUNK_WAVINFO
            elif isinstance(obj, SoundDef):
                body = (struct.pack("<4i", ref(obj.name), obj.flags, obj.field2,
                                    obj.wav_ref) + obj.extra)
                ctype = CHUNK_SOUNDDEF
            else:
                body = obj.payload
                ctype = obj.ctype
            out += struct.pack("<II", len(body), ctype) + body

        out += self.terminator or b"\xff\xff\xff\xff"
        return bytes(out)

    def _all_names(self):
        seen = []
        for obj in self._objects[1:]:
            n = getattr(obj, "name", None)
            if n and n not in seen:
                seen.append(n)
        for n in self.names:
            if n and n not in seen:
                seen.append(n)
        return seen

    def retag_stem(self, new_stem: str):
        """Rewrite the 7-character animation id the engine binds by
        (FUN_0052b981 overwrites the first 7 chars of each dag track tag)."""
        new_stem = new_stem[:7].ljust(7)
        old = self.path.stem[:7]
        def sub(name):
            if not name:
                return name
            if name.upper().startswith(old.upper()):
                return new_stem + name[len(old):]
            return name
        for obj in self._objects[1:]:
            if getattr(obj, "name", None):
                obj.name = sub(obj.name)
        self.names = [sub(n) for n in self.names]
        self.path = self.path.with_name(new_stem + self.path.suffix)
        return new_stem

    def from_edit(self, frames):
        """Apply `{joint: [{q:[w,x,y,z], t:[x,y,z]}, ...]}` (engine quat)."""
        for joint, keys in (frames or {}).items():
            for i, key in enumerate(keys):
                q = key.get("q") if isinstance(key, dict) else None
                t = key.get("t") if isinstance(key, dict) else None
                if q is None and t is None:
                    continue
                self.set_frame(joint, i, quat=q, translation=t)
        return self

    def set_frame(self, joint, index, quat=None, translation=None):
        joint = joint.upper()
        stem = self.path.stem.upper()
        for d in self.trackdefs:
            name = (d.name or "").upper()
            extracted = None
            if name.startswith(stem) and name.endswith("_TRACKDEF"):
                extracted = name[len(stem):-len("_TRACKDEF")]
            if extracted != joint and (d.joint or "").upper() != joint:
                continue
            if not d.frames or index >= len(d.frames):
                raise ValueError("frame %d out of range for %s" % (index, joint))
            f = d.frames[index]
            if quat is not None:
                f.quat = tuple(quat)
            if translation is not None:
                f.translation = tuple(translation)
            return
        raise KeyError(joint)

    def __repr__(self):
        return (f"Track({self.path.name}, version={self.version:#x}, "
                f"chunks={self.name_count}, names={len(self.names)}, "
                f"defs={len(self.trackdefs)}, "
                f"max_frames={self.frames})")


def _name_offsets(block):
    offsets = {}
    pos = 1
    while pos < len(block):
        end = block.find(b"\x00", pos)
        if end < 0:
            break
        s = block[pos:end].decode("latin-1")
        offsets.setdefault(s, pos)
        pos = end + 1
    return offsets


def _pack_names(names):
    block = bytearray(b"\x00")
    offsets = {}
    for n in names:
        offsets[n] = len(block)
        block += n.encode("latin-1") + b"\x00"
    while len(block) % 4:
        block.append(0)
    return bytes(block), offsets


def read_trx(path: Path):
    """The sibling .trx is plain text: a wav name, then integer pairs."""
    lines = Path(path).read_text(errors="replace").splitlines()
    wav = lines[0].strip() if lines else ""
    counts = lines[1].split() if len(lines) > 1 else []
    entries = int(counts[0]) if counts else 0
    frames = int(counts[1]) if len(counts) > 1 else 0
    pairs = []
    for ln in lines[2:]:
        parts = ln.split()
        if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
            pairs.append((int(parts[0]), int(parts[1])))
    return {"wav": wav, "entries": entries, "frames": frames, "pairs": pairs}
