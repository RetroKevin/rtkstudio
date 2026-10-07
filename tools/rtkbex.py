"""Reader for Return to Krondor .bex files -- "binary FX info".

Recovered from RtK.exe's own loader, not from hexdumps:

    FUN_004fe2e7   out/decompiled/RtK.c:166659  opens Bex.t3d (or the loose
                   file), slurps the whole thing, hands the buffer to
                   FUN_0042d7a2; on failure logs
                   "FXLoadBinaryFXInfoSprites failed."
    FUN_0042d7a2   out/decompiled/RtK.c:29830   walks the entry stream to
                   pre-load each entry's sprite resource.  This is the
                   function that fixes the record stride.
    FUN_0042d433   out/decompiled/RtK.c:29628   the real parser: builds the
                   runtime FXINFO from the buffer.  Every on-disk field and
                   its runtime slot come from here.
    FUN_0042caf8   out/decompiled/RtK.c:29147   the matching destructor,
                   which confirms which runtime slots are heap pointers.
    FUN_0042cc3d   out/decompiled/RtK.c:29211   type -> runtime payload size.
    FUN_0042fb8d   out/decompiled/RtK.c:31060   the per-frame update, a
                   switch on the entry type.  This is what gives each type
                   its meaning and pins down individual payload fields.
    FUN_0042e59e / FUN_0042e62e   RtK.c:30428 / 30460   resolve the two
                   trailing id lists: activate-these / deactivate-these.
    FUN_0042e6c4   out/decompiled/RtK.c:30492   the 0x201.. actor selector.
    FUN_0042c81c   out/decompiled/RtK.c:28953   the FX_DAG_* attach point.

Line numbers are against out/decompiled/ as regenerated 2026-10-05; that tree
is rebuilt periodically, so the "// ===== FUN_0042d433 @ 0042d433 =====" banner
is the stable anchor.  tools/_lines.py re-derives any citation.

See docs/misc-formats.md.
"""

import struct
from pathlib import Path

HEADER_SIZE = 0x20
ENTRY_FIXED_SIZE = 0x30  # 12 dwords, FUN_0042d433's `for (iVar5 = 0xc; ...)`

# FUN_0042cc3d: the runtime payload struct size for each entry type.  The
# loader allocates this much, zero-fills it, then copies the on-disk payload
# (which may be shorter) over the front.
RUNTIME_PAYLOAD_SIZE = {
    1: 0x14, 2: 0x20, 3: 0xA4, 4: 0x08, 5: 0x90, 6: 0x10, 7: 0x4C,
    8: 0x10, 9: 0x58, 10: 0x18, 11: 0x0C, 12: 0x3C, 13: 0x50, 14: 0x38,
}

# Names are descriptive, taken from what FUN_0042fb8d's switch arm does.
# The shipped binaries carry no name table for these.
TYPE_NAMES = {
    1: "timer",
    2: "set_location",
    3: "motion",
    4: "end_fx",
    5: "spawn_fx",
    6: "scale",
    7: "attach_to_dag",
    8: "actor_visibility",
    9: "set_sprite",
    10: "trigger",
    11: "distance",
    12: "translucency",
    13: "send_event",
    14: "on_event",
}

# FUN_0042e25d / FUN_0042e352: the t3d user-defined message id a send_event
# entry carries, and the one an on_event entry matches against.
MSG_SEND_EVENT = 0x103E8
MSG_ON_EVENT = 0x107D0

# Table at 0x005d14b0 in RtK.exe: 23 {char *name, u32 code} pairs, counted by
# DAT_005d1568 == 0x17.  FUN_0042c81c strips the "FX_DAG_" prefix and turns
# '_' into '-', which yields exactly the joint names used by .trk tracks
# (see docs/track-format.md).
FX_DAG = {
    0: "NONE", 1: "SOURCE_DAG", 2: "TARGET_DAG", 3: "DUMMY01", 4: "KIL",
    5: "L_UPPERLE", 6: "L_CAL", 7: "L_FOO", 8: "R_UPPERLE", 9: "R_CAL",
    10: "R_FOO", 11: "TOPTORS", 12: "L_UPPERAR", 13: "L_LOWAR", 14: "L_HAN",
    15: "R_UPPERAR", 16: "R_LOWAR", 17: "R_HAN", 18: "NECK", 19: "HEAD",
    20: "MAINSHADO", 21: "LFOOTSHAD", 22: "RFOOTSHAD",
}

# FUN_0042e6c4 (`param_1 & 0x200`, then `switch (param_1 - 0x201)`) plus the
# three extra codes the type-2 arm of FUN_0042fb8d tests for.
SELECTOR = {
    0x201: "self",            # userdata[0]: the FX actor's own rpg id
    0x202: "fx_source",       # instance+0x08, the caster
    0x203: "fx_target",       # instance+0x10, the victim
    0x204: "userdata_1",
    0x205: "userdata_1_owner",
    0x206: "userdata_2",
    0x207: "self_location",
    0x208: "userdata_1_location",
    0x209: "userdata_2_location",
}

# Entry flag bits, from FUN_0042fb8d / FUN_0042e59e / FUN_0042e62e.
FLAG_ACTIVE = 1     # the update loop only runs entries with this set
FLAG_STARTED = 4    # set by the handler on its first tick; 0 on disk


def _cstr(data, pos):
    end = data.index(b"\x00", pos)
    return data[pos:end].decode("latin-1"), end + 1


class Entry:
    """One FX node.  `fields` is the raw 12-dword block exactly as stored."""

    __slots__ = ("offset", "name", "fields", "payload", "activate",
                 "deactivate")

    def __init__(self, offset, name, fields, payload, activate, deactivate):
        self.offset = offset
        self.name = name
        self.fields = fields
        self.payload = payload
        self.activate = activate
        self.deactivate = deactivate

    # fields[5] and fields[8..11] are overwritten by FUN_0042d433 with heap
    # pointers and counts, so they carry no information; they are zero in
    # every shipped file.
    @property
    def id(self):
        return self.fields[0]

    @property
    def type(self):
        return self.fields[1]

    @property
    def type_name(self):
        return TYPE_NAMES.get(self.type, "type_%d" % self.type)

    @property
    def flags(self):
        return self.fields[2]

    @property
    def active(self):
        return bool(self.flags & FLAG_ACTIVE)

    @property
    def repeat(self):
        """Decremented by the timer and distance arms of FUN_0042fb8d."""
        return self.fields[3]

    @property
    def payload_size(self):
        return self.fields[6]

    def runtime_payload(self):
        """The payload as the loader hands it to the handlers: zero-extended
        to FUN_0042cc3d's size for this type."""
        want = RUNTIME_PAYLOAD_SIZE.get(self.type, len(self.payload))
        return self.payload.ljust(want, b"\x00")

    def u16(self, off):
        return struct.unpack_from("<H", self.runtime_payload(), off)[0]

    def i32(self, off):
        return struct.unpack_from("<i", self.runtime_payload(), off)[0]

    def f32(self, off):
        return struct.unpack_from("<f", self.runtime_payload(), off)[0]

    def pstr(self, off, limit=0x40):
        p = self.runtime_payload()[off:off + limit]
        return p.split(b"\x00")[0].decode("latin-1")

    def params(self):
        """The payload fields that the decompiled handlers actually read.

        Only these are claimed; the rest of each payload is either zero in
        every shipped file or is runtime scratch that the handler fills in.
        """
        t = self.type
        p = {}
        if t == 1:                                  # FUN_0042fb8d case 1
            p["mode"] = self.i32(0)                 # 2 => duration from FUN_0042d096
            p["duration_scale"] = self.f32(8)
            p["duration_ms"] = self.i32(0x0C)
        elif t == 2:                                # case 2
            p["selector"] = self.i32(0x1C)
        elif t == 3:                                # case 3 -> FUN_0042e9ad
            p["selector"] = self.u16(0)
            p["dag"] = self.i32(4)
            p["spin"] = self.f32(0xA0)
        elif t == 5:                                # case 5
            p["fx_file"] = self.pstr(0)
            p["selector"] = self.u16(0x48)
            p["dag"] = self.i32(0x4C)
        elif t == 6:                                # case 6
            p["step"] = self.f32(0)
            p["limit"] = self.f32(4)
            p["relative"] = self.i32(0x0C)
        elif t == 7:                                # case 7
            p["selector"] = self.u16(0)
            p["dag"] = self.i32(4)
        elif t == 8:                                # case 8
            p["selector"] = self.u16(0)
            p["invisible"] = self.i32(4)
        elif t == 9:                                # case 9
            p["selector"] = self.u16(0)
            p["sprite"] = self.pstr(0x38, 0x20)
        elif t == 11:                               # case 0xb
            p["step"] = self.f32(0)
            p["scale"] = self.f32(4)
        elif t == 12:                               # case 0xc
            p["from_level"] = self.i32(0x24)
            p["to_level"] = self.i32(0x28)
            p["rate"] = self.f32(0x2C)
        elif t == 13:                               # case 0xd -> FUN_0042fa00
            p["message"] = self.i32(0)
            p["recipient"] = self.i32(4)
            p["event"] = self.i32(0x34)
        elif t == 14:                               # FUN_0042e25d / FUN_0042e352
            p["message"] = self.i32(0)
            p["event"] = self.i32(0x34)
        if "dag" in p:
            p["dag_name"] = FX_DAG.get(p["dag"], str(p["dag"]))
        if "selector" in p:
            p["selector_name"] = SELECTOR.get(p["selector"], str(p["selector"]))
        return p

    def __repr__(self):
        return "Entry(%d, %s, %r, payload=%d, act=%s, deact=%s)" % (
            self.id, self.type_name, self.name, self.payload_size,
            self.activate, self.deactivate)


class FxInfo:
    """A whole .bex file."""

    def __init__(self, path, data=None):
        self.path = Path(path)
        raw = self.path.read_bytes() if data is None else data
        self.raw = raw
        if len(raw) < HEADER_SIZE:
            raise ValueError("file shorter than the 0x20-byte header")
        self.header = struct.unpack_from("<8I", raw, 0)
        # Only header[1] is meaningful.  FUN_0042d433 copies all eight dwords
        # into the runtime struct and then overwrites slots 6 and 7 with the
        # file-name and entry-array pointers, so the on-disk values of the
        # other six are whatever the exporter happened to have in memory --
        # zero in 357/368 files, 0xcdcdcdcd (MSVC uninitialised fill) in two,
        # and stale string bytes in a handful more.
        self.entry_count = self.header[1]
        self.entries = []
        pos = HEADER_SIZE
        for _ in range(self.entry_count):
            start = pos
            name, pos = _cstr(raw, pos)
            fields = struct.unpack_from("<12i", raw, pos)
            pos += ENTRY_FIXED_SIZE
            size = fields[6]
            if size < 0 or pos + size > len(raw):
                raise ValueError("payload size %d out of range at %d"
                                 % (size, pos))
            payload = raw[pos:pos + size]
            pos += size
            activate, pos = self._read_list(raw, pos)
            deactivate, pos = self._read_list(raw, pos)
            self.entries.append(
                Entry(start, name, fields, payload, activate, deactivate))
        self.end_offset = pos

    @staticmethod
    def _read_list(raw, pos):
        n = struct.unpack_from("<i", raw, pos)[0]
        pos += 4
        if n < 0 or pos + 4 * n > len(raw):
            raise ValueError("id list count %d out of range at %d" % (n, pos))
        vals = list(struct.unpack_from("<%di" % n, raw, pos)) if n else []
        return vals, pos + 4 * n

    def by_id(self, entry_id):
        """FUN_0042cbde: linear search on the entry id."""
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None

    def roots(self):
        """Entries that start active -- where the effect begins."""
        return [e for e in self.entries if e.active]

    def __len__(self):
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def __repr__(self):
        return "FxInfo(%s, entries=%d)" % (self.path.name, len(self.entries))

    def set_sprite(self, entry_id, name: str):
        """Rewrite a type-9 sprite string at payload +0x38 (32 bytes)."""
        e = self.by_id(int(entry_id))
        if e is None or e.type != 9:
            raise KeyError(entry_id)
        blob = (name or "").encode("latin-1")[:0x1F]
        payload = bytearray(e.payload)
        if len(payload) < 0x58:
            payload.extend(b"\x00" * (0x58 - len(payload)))
        payload[0x38:0x58] = blob.ljust(0x20, b"\x00")
        e.payload = bytes(payload)
        fields = list(e.fields)
        fields[6] = len(e.payload)
        e.fields = tuple(fields)
        return e

    def to_bytes(self) -> bytes:
        header = list(self.header)
        header[1] = len(self.entries)
        out = bytearray(struct.pack("<8I", *header))
        for e in self.entries:
            out += e.name.encode("latin-1") + b"\x00"
            fields = list(e.fields)
            fields[6] = len(e.payload)
            out += struct.pack("<12i", *fields)
            out += e.payload
            out += struct.pack("<i", len(e.activate))
            if e.activate:
                out += struct.pack("<%di" % len(e.activate), *e.activate)
            out += struct.pack("<i", len(e.deactivate))
            if e.deactivate:
                out += struct.pack("<%di" % len(e.deactivate), *e.deactivate)
        return bytes(out)


def dump(path):
    fx = FxInfo(path)
    out = ["%s: %d entries" % (fx.path.name, len(fx))]
    for e in fx.entries:
        bits = ["#%d" % e.id, e.type_name]
        if e.name:
            bits.append(repr(e.name))
        if e.active:
            bits.append("ACTIVE")
        if e.repeat:
            bits.append("repeat=%d" % e.repeat)
        for k, v in e.params().items():
            bits.append("%s=%r" % (k, v))
        if e.activate:
            bits.append("->on%s" % e.activate)
        if e.deactivate:
            bits.append("->off%s" % e.deactivate)
        out.append("  " + " ".join(bits))
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        print(dump(arg))
