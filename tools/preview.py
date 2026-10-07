"""Turn any asset's raw bytes into something a browser can display.

Every decoder in this repo is read-only and format-specific; this is the one
place that picks the right one and normalises the result to PNG, text, audio
or a hex dump. Nothing here writes to the game install.
"""

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import palettemap
import pyro_inflate
import rtkbitmap
import rtkdib
import rtkmedia
import rtkovx
import rtkres
import rtktext

HEX_BYTES = 2048


# --- PNG ----------------------------------------------------------------

def _chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def display_rgb(rgb, bits="565"):
    """One authored colour as the 16-bit frame shows it.

    FUN_10032ac3 stores the palette dword as peBlue, peGreen, peRed.
    The sprite blit then packs that dword. bits="565" is FUN_1003f014
    when sprite+0x27f8 is set, which is SpriteSetPixelFormat(5, 6, 5):
    the path taken when the back buffer's red mask is 0xF800. bits="555"
    is the other branch (red mask 0x7C00, format code 2). The 8-bit
    result replicates the packed bits into the low bits, which is how a
    16-bit pixel is shown on an 8-bit-per-channel display.
    """
    r, g, b = (int(rgb[0]) & 255, int(rgb[1]) & 255, int(rgb[2]) & 255)
    if bits == "555":
        r5, g5, b5 = r >> 3, g >> 3, b >> 3
        return ((r5 << 3) | (r5 >> 2),
                (g5 << 3) | (g5 >> 2),
                (b5 << 3) | (b5 >> 2))
    r5, g6, b5 = r >> 3, g >> 2, b >> 3
    return ((r5 << 3) | (r5 >> 2),
            (g6 << 2) | (g6 >> 4),
            (b5 << 3) | (b5 >> 2))


def display_palette(palette, bits="565"):
    """Preview colours. The stored PALETTEENTRY bytes are not changed."""
    return [display_rgb(c, bits) for c in palette]


def png_indexed(width, height, pixels, palette, stride=None,
                transparent_index=None) -> bytes:
    """8-bit palette-indexed PNG."""
    stride = stride or width
    raw = bytearray()
    for y in range(height):
        row = pixels[y * stride:y * stride + width]
        if len(row) < width:
            row = bytes(row) + bytes(width - len(row))
        raw.append(0)
        raw += row
    plte = bytearray()
    for rgb in palette:
        plte += bytes(rgb[:3])
    extra = b""
    if transparent_index is not None:
        extra = _chunk(b"tRNS", bytes([255] * transparent_index + [0]))
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
            + _chunk(b"PLTE", bytes(plte))
            + extra
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _chunk(b"IEND", b""))


def png_rgb(width, height, rgb: bytes) -> bytes:
    """24-bit truecolour PNG from packed RGB triples."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgb[y * width * 3:(y + 1) * width * 3]
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _chunk(b"IEND", b""))


# --- palettes -----------------------------------------------------------

class Palettes:
    """RTKRES palettes, loaded once and reused for every bitmap preview."""

    DEFAULT = "pIntfacePal"

    def __init__(self, db):
        self.db = db
        self._tables = None

    def tables(self):
        if self._tables is None:
            self._tables = {}
            for a in self.db.search(kind="palette"):
                try:
                    entries = rtkres.parse_palette(self.db.read(a.key))
                    self._tables[a.name] = rtkres.palette_to_256(entries)
                except Exception:
                    continue
        return self._tables

    def get(self, name=None):
        t = self.tables()
        if name and name in t:
            return t[name]
        if self.DEFAULT in t:
            return t[self.DEFAULT]
        return [(i, i, i) for i in range(256)]

    def names(self):
        return sorted(self.tables())


# --- windows BMP --------------------------------------------------------

def bmp_palette(data: bytes):
    """256 RGB triples from an 8-bit Windows BMP colour table."""
    if data[:2] != b"BM" or len(data) < 54 + 1024:
        raise ValueError("not an 8-bit BMP")
    return [(data[54 + i * 4 + 2], data[54 + i * 4 + 1], data[54 + i * 4])
            for i in range(256)]


def decode_pixels(data: bytes, palette=None):
    """(width, height, tight top-down indices, palette) for BMP or RTKRES."""
    if data[:2] == b"BM":
        return bmp_indexed(data)
    import rtkbitmap
    width, height, stride, packed = rtkbitmap.decode_resource(data)
    pixels = b"".join(bytes(packed[y * stride:y * stride + width])
                      for y in range(height))
    table = palette or [(i, i, i) for i in range(256)]
    return width, height, pixels, table


def bmp_indexed(data: bytes):
    """8-bit BMP → (width, height, index-bytes top-down, palette)."""
    if data[:2] != b"BM":
        raise ValueError("not a BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    if bpp != 8:
        raise ValueError("need an 8-bit BMP, got %d" % bpp)
    bottom_up = height > 0
    height = abs(height)
    stride = ((width * bpp + 31) // 32) * 4
    body = data[offset:]
    rows = [body[y * stride:(y + 1) * stride] for y in range(height)]
    if bottom_up:
        rows.reverse()
    flat = b"".join(bytes(r[:width]) for r in rows)
    return width, height, flat, bmp_palette(data)


def bmp_to_png(data: bytes, transparent=False, palette=None,
               for_display=True) -> bytes:
    """Re-wrap an uncompressed Windows BMP; browsers render BMP unevenly.

    `palette` replaces the file's own colour table. Character skins share
    one mesh ADF and get their colours from Models.def's *Palette.bmp.
    """
    if data[:2] != b"BM":
        raise ValueError("not a BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    bottom_up = height > 0
    height = abs(height)
    stride = ((width * bpp + 31) // 32) * 4
    body = data[offset:]

    rows = []
    for y in range(height):
        rows.append(body[y * stride:(y + 1) * stride])
    if bottom_up:
        rows.reverse()

    if bpp == 8:
        pal = palette or bmp_palette(data)
        if for_display:
            pal = display_palette(pal)
        flat = b"".join(bytes(r[:width]) for r in rows)
        return png_indexed(width, height, flat, pal,
                           transparent_index=0 if transparent else None)

    out = bytearray()
    for r in rows:
        if bpp == 24:
            for x in range(width):
                b, g, rr = r[x * 3:x * 3 + 3]
                out += bytes((rr, g, b))
        elif bpp == 16:
            for x in range(width):
                v = struct.unpack_from("<H", r, x * 2)[0]
                # 555, matching the engine's own thumbnails.
                out += bytes((((v >> 10) & 31) * 255 // 31,
                              ((v >> 5) & 31) * 255 // 31,
                              (v & 31) * 255 // 31))
        else:
            raise ValueError("unsupported depth %d" % bpp)
    return png_rgb(width, height, bytes(out))


def rgb555_to_png(data: bytes, width: int, height: int) -> bytes:
    px = struct.unpack("<%dH" % (len(data) // 2), data)
    out = bytearray()
    for v in px[:width * height]:
        out += bytes((((v >> 10) & 31) * 255 // 31,
                      ((v >> 5) & 31) * 255 // 31,
                      (v & 31) * 255 // 31))
    return png_rgb(width, height, bytes(out))


# --- dispatch -----------------------------------------------------------

def render(db, key, palette=None, transparent=False, remap=None, want_body=True):
    """Return (content_type, body, meta) for one asset."""
    asset = db.get(key)
    if asset is None:
        raise KeyError(key)
    raw = db.read(key)
    ext = Path(asset.name).suffix.lower()
    meta = {"key": key, "kind": asset.kind, "size": len(raw),
            "source": asset.source, "container": asset.container}
    remap_pal = None
    if remap:
        try:
            remap_pal = bmp_palette(db.read(remap))
        except Exception:
            remap_pal = None

    try:
        if asset.kind == "image":
            return _image(db, asset, raw, ext, meta, palette, transparent,
                          remap_pal)
        if asset.kind == "depth":
            o = rtkovx.parse(raw, asset.name)
            meta.update(width=o.width, height=o.height, rows=o.row_count,
                        spans=o.span_count, covered=o.covered_pixels)
            return "image/png", _ovx_png(o), meta
        if asset.kind in ("text", "script"):
            return _text(asset, raw, ext, meta)
        if asset.kind == "audio":
            extra = rtkmedia.wav_meta(raw)
            if extra.get("codec") == "MS ADPCM":
                extra["preview"] = "MS ADPCM decoded to PCM"
            else:
                extra["preview"] = extra.get("codec") or "audio"
            meta.update(extra)
            if want_body:
                body, extra = rtkmedia.playable_wav(raw)
                meta.update(extra)
                return "audio/wav", body, meta
            return "audio/wav", b"", meta
        if asset.kind == "video":
            if want_body:
                ctype, body, extra = rtkmedia.playable_avi(raw)
                meta.update(extra)
                return ctype, body, meta
            ctype, extra = rtkmedia.video_preview_meta(raw)
            meta.update(extra)
            return ctype, b"", meta
        if asset.kind == "palette":
            entries = rtkres.parse_palette(raw)
            table = rtkres.palette_to_256(entries)
            meta.update(entries=len(entries))
            return "image/png", _palette_png(display_palette(table)), meta
        if asset.kind in ("anim", "rig", "world", "fx"):
            return _structured(asset, raw, meta)
        if asset.kind == "widget":
            return _widget(db, asset, raw, meta)
    except Exception as exc:
        meta["error"] = "%s: %s" % (type(exc).__name__, exc)

    return "text/plain; charset=utf-8", hexdump(raw).encode("utf-8"), meta


def _widget(db, asset, raw, meta):
    """RTKRES TEXT/SCRIPT records: fixed-width binary, not strings.

    No field meaning has been traced from the engine, so this prints the
    words as they are instead of inventing names. Two things are established
    by surveying all 352 TEXT records: every one is 44 bytes, and word 1 is
    the same 0x800001db in all of them, so it is a constant tag rather than a
    per-widget value. Word 2 takes 28 different 0x8000xxxx values whose low
    bits do all land on real resource ids, which is suggestive of a reference
    but is not proof -- so any name shown below is a hint, not a finding.
    """
    words = struct.unpack_from("<%di" % (len(raw) // 4), raw) if len(raw) % 4 == 0 else ()
    meta["note"] = "binary %s record, %d bytes; fields untraced" % (
        asset.restype, len(raw))
    byid = getattr(db, "_byid_cache", None)
    if byid is None:
        byid = {int(a.member): a for a in db.assets if a.source == "res"}
        try:
            db._byid_cache = byid
        except AttributeError:
            pass
    lines = ["%s %s: %d bytes" % (asset.restype, asset.name, len(raw)),
             "field meanings are untraced; 0x8000xxxx lookups are a guess", ""]
    for i, w in enumerate(words):
        u = w & 0xFFFFFFFF
        hint = ""
        if u >> 28 == 8:
            target = byid.get(u & 0x0FFFFFFF)
            hint = "   -> %s?" % target.name if target else "   -> unresolved"
        lines.append("  [%2d] %11d  %#010x%s" % (i, w, u, hint))
    lines += ["", "--- raw ---", hexdump(raw, 256)]
    return "text/plain; charset=utf-8", "\n".join(lines).encode("utf-8"), meta


def _structured(asset, raw, meta):
    """A readable summary for the container formats, with a hex tail."""
    import rtkbex
    import rtkspx
    import rtktrack
    import rtkworld

    path = Path(asset.name)
    lines = []
    if asset.kind == "anim":
        t = rtktrack.Track(path, raw)
        meta.update(joints=len(t.joints), frames=t.frames)
        lines.append("track %s" % path.name)
        lines.append("  version    %#x" % t.version)
        lines.append("  chunks     %d" % len(t.chunks))
        lines.append("  joints     %d" % len(t.joints))
        lines.append("  max frames %d" % t.frames)
        lines.append("")
        lines.append("joints:")
        lines += ["  %s" % j for j in t.joints]
    elif asset.kind == "rig":
        s = rtkspx.SpriteFile(path, raw)
        defs = getattr(s, "hsprite_defs", []) or []
        meta.update(names=len(s.names), hierarchies=len(defs))
        lines.append("sprite file %s" % path.name)
        lines.append("  names        %d" % len(s.names))
        lines.append("  chunk types  %s" % sorted({c[2] for c in s.chunks}
                                                  if s.chunks and len(s.chunks[0]) > 2 else []))
        lines.append("  hierarchies  %d" % len(defs))
        for hs in defs:
            lines.append("")
            lines.append("hierarchy %s: %d dags" % (getattr(hs, "name", "?"),
                                                    len(getattr(hs, "dags", []))))
            for d in getattr(hs, "dags", [])[:60]:
                kids = getattr(d, "children", [])
                lines.append("  %-20s children=%s" % (getattr(d, "name", "?"), list(kids)))
    elif asset.kind == "world":
        w = rtkworld.World(path, raw) if _accepts_data(rtkworld.World) else None
        if w is None:
            raise ValueError("world reader needs a path")
        meta.update(objects=len(getattr(w, "objects", [])),
                    bsps=len(getattr(w, "bsps", [])))
        lines.append("world file %s" % path.name)
        lines.append("  names    %s" % w.names)
        lines.append("  objects  %d" % len(getattr(w, "objects", [])))
        lines.append("  bsp      %d" % len(getattr(w, "bsps", [])))
    else:
        fx = rtkbex.FxInfo(path, raw) if _accepts_data(rtkbex.FxInfo) else None
        if fx is None:
            raise ValueError("fx reader needs a path")
        entries = getattr(fx, "entries", [])
        meta.update(entries=len(entries))
        lines.append("fx graph %s: %d entries" % (path.name, len(entries)))
        for e in entries[:80]:
            lines.append("  %-24s type=%-3s" % (getattr(e, "name", "?"),
                                                getattr(e, "type", "?")))

    lines.append("")
    lines.append("--- raw ---")
    lines.append(hexdump(raw, 512))
    return "text/plain; charset=utf-8", "\n".join(lines).encode("utf-8"), meta


def _accepts_data(cls):
    import inspect
    try:
        return "data" in inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        return False


def _image(db, asset, raw, ext, meta, palette, transparent=False,
           remap_palette=None):
    if ext == ".di_":
        dib = rtkdib.CompressedDib(Path(asset.name), raw)
        meta.update(width=dib.width, height=dib.height, bpp=8,
                    codec="zlib + 256-entry palette")
        return "image/png", png_indexed(dib.width, dib.height, dib.pixels,
                                        display_palette(dib.palette)), meta
    if ext in (".bmp", ".dib"):
        meta.update(codec="Windows BMP")
        return "image/png", bmp_to_png(raw, transparent=transparent,
                                       palette=remap_palette, for_display=True), meta
    if ext == ".kgi":
        meta.update(width=192, height=155, codec="raw RGB555")
        return "image/png", rgb555_to_png(raw, 192, 155), meta

    # RTKRES BITMAP. These carry no palette of their own: the engine realises
    # one palette per screen and blits whatever is current against it, so the
    # right table comes from which screen the bitmap belongs to.
    width, height, stride, pixels = rtkbitmap.decode_resource(raw)
    chosen, source = palette, "chosen"
    if not chosen:
        # palette_for falls back to the engine default for any known resource,
        # so its return value alone cannot say whether a screen was actually
        # found. Only the 2,566 bitmaps in _MAP have positive evidence; the
        # rest are the default by absence of a RtSetPalette on a reaching
        # path, which is a much weaker claim and should not look the same.
        rid = palettemap.asset_id(asset)
        mapped = rid is not None and rid in palettemap._MAP
        chosen = (palettemap.palette_for(rid) if rid is not None else None) or Palettes.DEFAULT
        source = "screen map" if mapped else "engine default"
    table = _palettes(db).get(chosen)
    meta.update(width=width, height=height, stride=stride, palette=chosen,
                palette_source=source, codec="LZW / RLE")
    alt = palettemap.AMBIGUOUS.get(palettemap.asset_id(asset))
    if alt:
        meta["palette_note"] = "drawn under both %s" % " and ".join(alt)
    return "image/png", png_indexed(width, height, pixels,
                                    display_palette(table), stride), meta


def _palettes(db):
    """One Palettes per database -- parsing 13 palettes per preview is waste."""
    cache = getattr(db, "_palette_cache", None)
    if cache is None:
        cache = Palettes(db)
        try:
            db._palette_cache = cache
        except AttributeError:
            pass
    return cache


def _ovx_png(o):
    # depth_image returns (rows, lo, hi); rows are palette indices into the
    # module's own near/far ramp.
    rows, _lo, _hi = rtkovx.depth_image(o)
    return png_indexed(o.width, o.height, b"".join(rows), rtkovx.DEPTH_PALETTE)


def _palette_png(table, swatch=24):
    width = swatch * 16
    height = swatch * 16
    rgb = bytearray()
    for y in range(height):
        for x in range(width):
            rgb += bytes(table[(y // swatch) * 16 + (x // swatch)][:3])
    return png_rgb(width, height, bytes(rgb))


def _text(asset, raw, ext, meta):
    if ext in (".def", ".tbl", ".rtk", ".txt"):
        try:
            raw = pyro_inflate.inflate(raw)
            meta["codec"] = "PyroTechnix gzip, inflated"
        except Exception:
            pass
    if ext == ".ktx":
        meta["codec"] = "narration text; bytes > 0x7f render as space"
        return "text/plain; charset=utf-8", rtktext.normalise(raw).encode("utf-8"), meta
    meta["lines"] = raw.count(b"\n") + 1
    return "text/plain; charset=utf-8", raw.decode("latin-1").encode("utf-8"), meta


def _wav_meta(raw):
    return rtkmedia.wav_meta(raw)


def hexdump(data: bytes, limit=HEX_BYTES) -> str:
    out = []
    view = data[:limit]
    for off in range(0, len(view), 16):
        chunk = view[off:off + 16]
        hexs = " ".join("%02x" % b for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append("%08x  %-47s  |%s|" % (off, hexs, text))
    if len(data) > limit:
        out.append("... %d more bytes" % (len(data) - limit))
    return "\n".join(out)
