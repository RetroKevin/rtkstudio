"""Round-trip every shipped image through `tools/imagecodec.py`.

Five sweeps, all counted rather than sampled:

  1. `.di_`      decode with rtkdib -> encode_di_ -> decode again; plus a PNG
                 leg, a quantize leg and a remap leg on the same pixels.
  2. BITMAP      decode with rtkbitmap -> encode_dib_bitmap (stored mode) ->
                 decode again; plus the same PNG leg.
  3. on disk     read back the PNGs already exported under `out/png` and
                 `out/dib` -- files this module did not write -- and check
                 them against the archive, not against themselves.
  4. foreign     decode PNGs from outside the project (Ghidra's icons and
                 docs) and compare every sampled pixel against Tk's own PNG
                 reader, an independent decoder. This is what actually tests
                 the scanline filters: the corpus uses all five.
  5. synthetic   one PNG per (colour type, bit depth, filter) combination, to
                 cover the variants no corpus here happens to contain, plus
                 the inputs that must be rejected.

Nothing is written outside `out/`, and the game install is only ever read.

    python tools/validate_imagecodec.py
"""

import argparse
import csv
import glob
import os
import struct
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import imagecodec as ic
import preview
import rtkbitmap
import rtkdib
from rtkres import ResFile, palette_to_256, parse_palette

REPO = Path(__file__).resolve().parents[1]
KEY_BOOT_PALETTE = 6  # key resource 6 == pIntfacePal, the engine's boot palette

_STATE = {}


# --- helpers ------------------------------------------------------------

def crop(pixels, width, height, stride):
    """The visible w*h pixels of a stride-padded buffer."""
    if stride == width:
        return bytes(pixels[:width * height])
    return b"".join(bytes(pixels[y * stride:y * stride + width])
                    for y in range(height))


def rgb_of(pixels, palette):
    """Render indexed pixels to packed RGB triples, for the quantize leg."""
    table = [bytes(c[:3]) for c in palette]
    return b"".join([table[i] for i in pixels])


def boot_palette(res):
    off, size = res.keys[KEY_BOOT_PALETTE]
    return palette_to_256(parse_palette(res.raw[off:off + size]))


# --- sweep 1: .di_ ------------------------------------------------------

def _init_dib(dib_png_dir):
    _STATE["dib_png_dir"] = Path(dib_png_dir) if dib_png_dir else None


def check_di(path_and_stem):
    path, has_png = path_and_stem
    r = Counter()
    r["files"] += 1
    try:
        src = rtkdib.CompressedDib(Path(path))
    except Exception as exc:
        r["decode_error"] += 1
        return r, ["%s: read failed: %s" % (path, exc)]

    notes = []
    w, h, pal, px = src.width, src.height, src.palette, src.pixels
    if len(set(pal)) < len(pal):
        r["duplicate_palette"] += 1

    # leg A: encode_di_ -> rtkdib
    blob = ic.encode_di_(w, h, px, pal)
    back = rtkdib.CompressedDib(Path(path), blob)
    if (back.width, back.height) != (w, h):
        notes.append("%s: dimensions changed" % path)
    elif back.pixels != px:
        notes.append("%s: di_ pixels differ" % path)
    elif back.palette != pal:
        notes.append("%s: di_ palette differs" % path)
    else:
        r["di_exact"] += 1
    r["di_bytes"] += len(blob)

    # leg B: PNG written here, read back by decode_png
    png = preview.png_indexed(w, h, px, pal)
    pw, ph, ppal, ppx = ic.decode_png(png)
    if (pw, ph) == (w, h) and ppx == px and ppal == pal:
        r["png_exact"] += 1
    else:
        notes.append("%s: png leg differs" % path)

    # leg C: PNG on disk, written by rtkdib.write_png in an earlier run
    if has_png:
        disk = _STATE["dib_png_dir"] / (Path(path).stem + ".png")
        dw, dh, dpal, dpx = ic.decode_png(disk.read_bytes())
        r["disk_png"] += 1
        if (dw, dh) == (w, h) and dpx == px and dpal == pal:
            r["disk_png_exact"] += 1
        else:
            notes.append("%s: on-disk png differs" % disk)

    # leg D: render to truecolour, quantize back onto the same palette
    rgb = rgb_of(px, pal)
    q = ic.quantize(w, h, rgb, pal)
    if q == px:
        r["quantize_exact"] += 1
    else:
        # A palette with duplicate colours makes some indices unreachable:
        # the nearest match is a different index holding the same RGB. That is
        # still lossless, so check the colours rather than the indices.
        bad = [i for i in range(len(px)) if pal[q[i]] != pal[px[i]]]
        if bad:
            notes.append("%s: quantize changed %d colours" % (path, len(bad)))
        else:
            r["quantize_same_colour"] += 1

    # leg E: remap onto the same palette must be the identity, duplicate
    # colours included -- indices are not interchangeable to the engine.
    if ic.remap(px, pal, pal) == px:
        r["remap_identity"] += 1
    else:
        notes.append("%s: remap is not the identity" % path)

    return r, notes


# --- sweep 2: RTKRES BITMAP --------------------------------------------

def _init_bitmaps(game, png_dir, manifest):
    res = ResFile(Path(game) / "RTKRES.bin")
    _STATE["res"] = res
    _STATE["pal"] = boot_palette(res)
    _STATE["png_dir"] = Path(png_dir) if png_dir else None
    _STATE["manifest"] = manifest


def check_bitmap(rid):
    res = _STATE["res"]
    pal = _STATE["pal"]
    e = res.entries[rid]
    r = Counter()
    r["files"] += 1
    notes = []

    data = res.read_raw(e)
    if len(data) < ic.BITMAP_HEADER_SIZE:
        r["skipped"] += 1
        return r, notes
    w, h, flags, f12, f16, own_id = struct.unpack_from("<6I", data, 0)
    if not w or not h:
        r["skipped"] += 1
        return r, notes
    r["rle" if flags & ic.FLAG_RLE else "lzw"] += 1

    try:
        W, H, stride, px = rtkbitmap.decode_resource(data)
    except Exception as exc:
        r["decode_error"] += 1
        return r, ["res %d: decode failed: %s" % (rid, exc)]

    # leg A: encode_dib_bitmap -> rtkbitmap, full stride-padded buffer
    blob = ic.encode_dib_bitmap(w, h, px, flags=flags, field12=f12,
                                field16=f16, res_id=own_id)
    W2, H2, stride2, px2 = rtkbitmap.decode_resource(blob)
    if (W2, H2, stride2) != (W, H, stride):
        notes.append("res %d: geometry changed" % rid)
    elif bytes(px2) != bytes(px):
        notes.append("res %d: bitmap pixels differ" % rid)
    else:
        r["bmp_exact"] += 1
    r["bmp_bytes"] += len(blob)
    r["src_bytes"] += len(data)

    # The header the engine reads back must match the one it read in, apart
    # from the codec bit we are allowed to change.
    hdr = struct.unpack_from("<6I", blob, 0)
    if hdr == (w, h, flags & ~ic.FLAG_RLE, f12, f16, own_id):
        r["header_preserved"] += 1
    else:
        notes.append("res %d: header fields changed: %r" % (rid, hdr))

    visible = crop(px, w, h, stride)

    # leg B: PNG written here, read back, then re-encoded from the tight
    # buffer -- the path an edited PNG actually takes.
    png = preview.png_indexed(w, h, px, pal, stride)
    pw, ph, ppal, ppx = ic.decode_png(png)
    if (pw, ph) == (w, h) and ppx == visible and ppal == pal:
        r["png_exact"] += 1
    else:
        notes.append("res %d: png leg differs" % rid)

    reenc = ic.encode_dib_bitmap(pw, ph, ppx)
    _, _, stride3, px3 = rtkbitmap.decode_resource(reenc)
    if crop(px3, pw, ph, stride3) == visible:
        r["png_import_exact"] += 1
    else:
        notes.append("res %d: png import differs" % rid)

    # leg C: the PNG exported by tools/export_bitmaps.py in an earlier run
    name = _STATE["manifest"].get(rid)
    if name:
        path = _STATE["png_dir"] / name
        if path.exists():
            dw, dh, dpal, dpx = ic.decode_png(path.read_bytes())
            r["disk_png"] += 1
            if (dw, dh) == (w, h) and dpx == visible:
                r["disk_png_exact"] += 1
            else:
                notes.append("res %d: on-disk png differs (%s)" % (rid, name))

    return r, notes


# --- sweep 3: the t3d .bmp textures ------------------------------------

def _init_bmp(palette):
    _STATE["pal"] = palette


def check_bmp(path):
    """Import a plain Windows BMP from the t3d containers.

    These are the 3D engine's texture maps -- a different asset class from the
    RTKRES BITMAP resources, and the thing the "5,600 bitmaps" count refers
    to. They are read through `preview.bmp_to_png`, so the PNG arriving at
    `decode_png` is one this module did not produce, and the 8-bit ones carry
    their own colour table while the 16- and 24-bit ones have to be quantized.
    """
    r = Counter()
    r["files"] += 1
    notes = []
    data = Path(path).read_bytes()
    bw, bh = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    r["bpp%d" % bpp] += 1

    try:
        png = preview.bmp_to_png(data, for_display=False)
        w, h, pal, px = ic.decode_png(png)
    except Exception as exc:
        r["decode_error"] += 1
        return r, ["%s: %s: %s" % (path, type(exc).__name__, exc)]

    if (w, h) != (bw, abs(bh)):
        notes.append("%s: %dx%d from PNG, %dx%d in the BMP header"
                     % (path, w, h, bw, abs(bh)))
        return r, notes
    r["dims_ok"] += 1

    if pal is not None:
        r["indexed"] += 1
        blob = ic.encode_dib_bitmap(w, h, px)
        _, _, stride, back = rtkbitmap.decode_resource(blob)
        if crop(back, w, h, stride) == px:
            r["bmp_exact"] += 1
        else:
            notes.append("%s: BITMAP round trip differs" % path)
        di = ic.encode_di_(w, h, px, pal)
        d2 = rtkdib.CompressedDib(Path(path), di)
        if d2.pixels == px and d2.palette[:len(pal)] == pal:
            r["di_exact"] += 1
        else:
            notes.append("%s: di_ round trip differs" % path)
        return r, notes

    # Truecolour: there is nothing to round-trip exactly, so check the
    # property quantize actually promises -- that each pixel gets a nearest
    # entry -- by brute-forcing a sample against the palette independently.
    r["truecolour"] += 1
    pal256 = _STATE["pal"]
    q = ic.quantize(w, h, px, pal256)
    blob = ic.encode_dib_bitmap(w, h, q)
    _, _, stride, back = rtkbitmap.decode_resource(blob)
    if crop(back, w, h, stride) == q:
        r["bmp_exact"] += 1
    else:
        notes.append("%s: quantized BITMAP round trip differs" % path)

    n = w * h
    step = max(1, n // 25)
    for i in range(0, n, step):
        o = i * 3
        want = (px[o], px[o + 1], px[o + 2])
        best = min((pr - want[0]) ** 2 + (pg - want[1]) ** 2 + (pb - want[2]) ** 2
                   for pr, pg, pb in pal256)
        pr, pg, pb = pal256[q[i]]
        got = ((pr - want[0]) ** 2 + (pg - want[1]) ** 2 + (pb - want[2]) ** 2)
        r["sampled"] += 1
        if got == best:
            r["nearest_ok"] += 1
        else:
            notes.append("%s: pixel %d is not nearest (%d vs %d)"
                         % (path, i, got, best))
        r["sum_sq_error"] += got
    return r, notes


# --- sweep 4: foreign PNGs vs Tk ---------------------------------------

def sweep_foreign(files, log):
    try:
        import tkinter
    except Exception as exc:  # pragma: no cover - tkinter ships with CPython
        log("foreign PNG sweep skipped: no tkinter (%s)" % exc)
        return 0

    root = tkinter.Tk()
    root.withdraw()

    variants = Counter()
    filters = Counter()
    agree = mismatch = failed = 0
    pixels = 0

    for f in files:
        data = Path(f).read_bytes()
        w0, h0, depth, colour = struct.unpack_from(">IIBB", data, 16)
        variants[(colour, depth)] += 1
        try:
            idat = b"".join(p for t, p in ic._chunks(data, True) if t == b"IDAT")
            raw = zlib.decompress(idat)
            row = (w0 * ic.CHANNELS[colour] * depth + 7) // 8
            for y in range(h0):
                filters[raw[y * (row + 1)]] += 1
        except Exception:
            pass

        try:
            w, h, pal, px = ic.decode_png(data)
        except Exception as exc:
            failed += 1
            log("  FAIL %s: %s" % (f, exc))
            continue
        img = tkinter.PhotoImage(file=str(f))
        if (img.width(), img.height()) != (w, h):
            mismatch += 1
            log("  DIMS %s: %dx%d vs Tk %dx%d" % (f, w, h, img.width(), img.height()))
            del img
            continue
        step_x = max(1, w // 24)
        step_y = max(1, h // 24)
        bad = 0
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                want = img.get(x, y)
                if pal is None:
                    o = (y * w + x) * 3
                    got = (px[o], px[o + 1], px[o + 2])
                else:
                    got = pal[px[y * w + x]]
                pixels += 1
                if tuple(want) != tuple(got):
                    bad += 1
        del img
        if bad:
            mismatch += 1
            log("  PIXELS %s: %d of the sampled pixels differ" % (f, bad))
        else:
            agree += 1

    root.destroy()
    log("foreign PNGs           : %d" % len(files))
    log("  agree with Tk        : %d" % agree)
    log("  disagree             : %d" % mismatch)
    log("  decode_png failed    : %d" % failed)
    log("  pixels compared      : %d" % pixels)
    log("  variants (type,depth): %s"
        % ", ".join("t%d/d%d x%d" % (c, d, n) for (c, d), n in sorted(variants.items())))
    log("  scanline filters     : %s"
        % ", ".join("%s=%d" % (("none", "sub", "up", "avg", "paeth")[k], v)
                    for k, v in sorted(filters.items())))
    return mismatch + failed


# --- sweep 5: synthetic variants ---------------------------------------

def _chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def _png(width, height, depth, colour, samples, filter_type):
    """Minimal PNG writer used only by the tests, one filter type throughout.

    `samples` is a flat list of ints, one per sample, already in the bit depth
    given. Forward filters are written straight from the PNG spec so the
    decoder's inverse is checked against the definition, not against itself.
    """
    channels = ic.CHANNELS[colour]
    row_bits = width * channels * depth
    row_bytes = (row_bits + 7) // 8
    bpp = max(1, channels * depth // 8)

    rows = []
    for y in range(height):
        row = bytearray(row_bytes)
        if depth == 16:
            for i in range(width * channels):
                struct.pack_into(">H", row, i * 2, samples[y * width * channels + i])
        elif depth == 8:
            for i in range(width * channels):
                row[i] = samples[y * width * channels + i]
        else:
            per = 8 // depth
            for i in range(width * channels):
                v = samples[y * width * channels + i]
                shift = 8 - depth * (i % per + 1)
                row[i // per] |= (v & ((1 << depth) - 1)) << shift
        rows.append(bytes(row))

    raw = bytearray()
    prev = bytes(row_bytes)
    for row in rows:
        out = bytearray(row_bytes)
        for i in range(row_bytes):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            x = row[i]
            if filter_type == 0:
                out[i] = x
            elif filter_type == 1:
                out[i] = (x - a) & 0xFF
            elif filter_type == 2:
                out[i] = (x - b) & 0xFF
            elif filter_type == 3:
                out[i] = (x - ((a + b) >> 1)) & 0xFF
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                out[i] = (x - pr) & 0xFF
        raw.append(filter_type)
        raw += out
        prev = row

    chunks = [_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                          depth, colour, 0, 0, 0))]
    if colour == ic.INDEXED:
        plte = bytearray()
        for i in range(1 << depth):
            plte += bytes(((i * 11) & 0xFF, (i * 29) & 0xFF, (255 - i) & 0xFF))
        chunks.append(_chunk(b"PLTE", bytes(plte)))
    chunks.append(_chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
    chunks.append(_chunk(b"IEND", b""))
    return ic.PNG_SIGNATURE + b"".join(chunks)


def sweep_synthetic(log):
    W, H = 13, 5  # odd width, so sub-byte rows end mid-byte
    passed = failed = 0

    def check(label, cond):
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            log("  FAIL %s" % label)

    for colour in (ic.GREY, ic.TRUECOLOUR, ic.INDEXED, ic.GREY_ALPHA, ic.RGBA):
        for depth in ic.DEPTHS[colour]:
            channels = ic.CHANNELS[colour]
            top = (1 << depth) - 1
            samples = []
            for y in range(H):
                for x in range(W):
                    for c in range(channels):
                        samples.append((x * 7 + y * 13 + c * 29) % (top + 1))
            for ft in range(5):
                blob = _png(W, H, depth, colour, samples, ft)
                w, h, pal, px = ic.decode_png(blob)
                label = "colour %d depth %d filter %d" % (colour, depth, ft)
                if (w, h) != (W, H):
                    check(label + " dimensions", False)
                    continue

                if colour == ic.INDEXED:
                    want = bytes(samples)
                    check(label, pal is not None and px == want
                          and len(pal) == (1 << depth))
                    continue

                # Expected RGB after dropping alpha and scaling the depth.
                want = bytearray()
                for i in range(W * H):
                    chunk = samples[i * channels:(i + 1) * channels]
                    if depth == 16:
                        chunk = [v >> 8 for v in chunk]
                    elif depth < 8:
                        chunk = [v * ic._GREY_SCALE[depth] for v in chunk]
                    if colour in (ic.GREY, ic.GREY_ALPHA):
                        want += bytes((chunk[0],) * 3)
                    else:
                        want += bytes(chunk[:3])
                check(label, pal is None and px == bytes(want))

    # Rejections.
    good = _png(4, 2, 8, ic.TRUECOLOUR, list(range(24)), 0)

    bad = bytearray(good)
    bad[28] = 1  # IHDR interlace byte
    bad[29:33] = struct.pack(">I", zlib.crc32(bad[12:29]) & 0xFFFFFFFF)
    try:
        ic.decode_png(bytes(bad))
        check("interlaced rejected", False)
    except ValueError as exc:
        check("interlaced rejected", "interlac" in str(exc))

    bad = bytearray(good)
    bad[-5] ^= 0xFF  # corrupt the IEND payload area -> CRC mismatch
    try:
        ic.decode_png(bytes(bad))
        check("bad CRC rejected", False)
    except ValueError as exc:
        check("bad CRC rejected", "CRC" in str(exc))

    try:
        ic.decode_png(b"\x89PNG\r\n\x1a\nrubbish")
        check("truncated rejected", False)
    except ValueError:
        check("truncated rejected", True)

    try:
        ic.decode_png(b"not a png at all")
        check("non-PNG rejected", False)
    except ValueError:
        check("non-PNG rejected", True)

    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
    blank = _chunk(b"IDAT", zlib.compress(bytes(2 * (1 + 6)))) + _chunk(b"IEND", b"")
    try:
        ic.decode_png(ic.PNG_SIGNATURE + ihdr + _chunk(b"ZZZZ", b"x") + blank)
        check("unknown critical chunk rejected", False)
    except ValueError:
        check("unknown critical chunk rejected", True)

    # An ancillary chunk in the same place must be ignored instead.
    ancillary = ic.PNG_SIGNATURE + ihdr + _chunk(b"zTXt", b"x") + blank
    try:
        w, h, pal, px = ic.decode_png(ancillary)
        check("ancillary chunk ignored", (w, h, pal, px) == (2, 2, None, bytes(12)))
    except ValueError as exc:
        check("ancillary chunk ignored: %s" % exc, False)

    # Multiple IDAT chunks are legal and must concatenate.
    body = zlib.compress(bytes([0, 1, 2, 3, 4, 5, 6, 0, 7, 8, 9, 10, 11, 12]))
    split = (ic.PNG_SIGNATURE + ihdr + _chunk(b"IDAT", body[:3])
             + _chunk(b"IDAT", body[3:]) + _chunk(b"IEND", b""))
    w, h, pal, px = ic.decode_png(split)
    check("split IDAT", px == bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]))

    # Quantization behaviour: exact hits, nearest, and lowest index on a tie.
    pal = [(0, 0, 0), (10, 0, 0), (255, 255, 255)]
    check("quantize exact", ic.quantize(3, 1, b"\x00\x00\x00\x0a\x00\x00"
                                        b"\xff\xff\xff", pal) == b"\x00\x01\x02")
    check("quantize nearest", ic.quantize(1, 1, bytes((250, 250, 250)), pal) == b"\x02")
    check("quantize tie -> lowest", ic.quantize(1, 1, bytes((5, 0, 0)), pal) == b"\x00")
    check("quantize length guard", _raises(ic.quantize, 2, 1, b"\x00", pal))

    # remap: shift a palette by the engine's 10 system colours. The filler
    # entries are a colour the source palette does not contain, because an
    # exact match always wins and would otherwise resolve to index 0.
    src = [(i, 0, 0) for i in range(8)]
    dst = [(200, 200, 200)] * 10 + src
    moved = ic.remap(bytes(range(8)), src, dst)
    check("remap shifts indices", moved == bytes(range(10, 18)))
    check("remap identity", ic.remap(bytes(range(8)), src, src) == bytes(range(8)))

    # Encoder guards.
    check("encode_di_ length guard", _raises(ic.encode_di_, 4, 4, b"\x00" * 15,
                                             [(0, 0, 0)]))
    check("encode_dib_bitmap length guard",
          _raises(ic.encode_dib_bitmap, 5, 4, b"\x00" * 19))
    check("encode_dib_bitmap accepts tight and padded",
          ic.encode_dib_bitmap(5, 4, b"\x01" * 20)
          == ic.encode_dib_bitmap(5, 4, b"\x01" * 5 + b"\x00" * 3
                                  + (b"\x01" * 5 + b"\x00" * 3) * 3))

    # Stored chunks must never be empty and must terminate exactly.
    blob = ic.encode_dib_bitmap(8192, 1, bytes(8192))
    stream = blob[ic.BITMAP_HEADER_SIZE:]
    ctrls = []
    pos = 0
    while pos + 2 <= len(stream):
        ctrl = struct.unpack_from("<H", stream, pos)[0]
        pos += 2
        if ctrl & 0xE000 == 0xE000:
            ctrls.append(("end", 0))
            break
        ctrls.append(("stored", ctrl & ic.CHUNK_MAX))
        pos += ctrl & ic.CHUNK_MAX
    check("chunking: no empty chunk", all(n for kind, n in ctrls if kind == "stored"))
    check("chunking: ends with end marker", ctrls[-1][0] == "end")
    check("chunking: covers exactly stride*height",
          sum(n for kind, n in ctrls if kind == "stored") == 8192)
    check("chunking: respects the 13-bit limit",
          all(n <= ic.CHUNK_MAX for kind, n in ctrls if kind == "stored"))

    # Bottom-up orientation, stated as a test so it cannot drift.
    top_down = bytes([1, 1, 1, 1, 2, 2, 2, 2])  # row 0 = ones, row 1 = twos
    raw = ic.encode_dib_bitmap(4, 2, top_down)[ic.BITMAP_HEADER_SIZE + 2:]
    check("bottom-up in the file", raw[:4] == b"\x02\x02\x02\x02")
    _, _, st, back = rtkbitmap.decode_resource(ic.encode_dib_bitmap(4, 2, top_down))
    check("bottom-up survives the decoder", bytes(back) == top_down)

    # .di_ needs no flip: the loader reads width*height top-down.
    blob = ic.encode_di_(4, 2, top_down, [(0, 0, 0)] * 256)
    check("di_ stays top-down",
          rtkdib.CompressedDib(Path("synthetic.di_"), blob).pixels == top_down)
    check("di_ palette is PALETTEENTRY",
          ic.palette_block([(1, 2, 3)])[:4] == b"\x01\x02\x03\x00")

    log("synthetic checks      : %d" % (passed + failed))
    log("  passed              : %d" % passed)
    log("  failed              : %d" % failed)
    return failed


# --- samples to look at -------------------------------------------------

def emit_samples(game, src, out_dir, log):
    """Write a few real round trips to disk, including an edited one.

    The sweeps all work in memory and compare bytes; these files exist so the
    result can be looked at. An orientation bug survives a byte comparison
    only if both directions are wrong, but it cannot survive someone noticing
    that the edit landed in the wrong corner.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    backdrops = sorted(src.rglob("*.di_"))
    if backdrops:
        path = backdrops[0]
        d = rtkdib.CompressedDib(path)
        blob = ic.encode_di_(d.width, d.height, d.pixels, d.palette)
        (out_dir / "roundtrip.di_").write_bytes(blob)
        back = rtkdib.CompressedDib(out_dir / "roundtrip.di_")
        (out_dir / "roundtrip_di.png").write_bytes(
            preview.png_indexed(back.width, back.height, back.pixels, back.palette))
        written += ["roundtrip.di_", "roundtrip_di.png"]

        # Invert the top-left quadrant, re-import, reload: the edit has to
        # come back in the top-left quadrant.
        w, h, pal, px = ic.decode_png((out_dir / "roundtrip_di.png").read_bytes())
        edited = bytearray(px)
        for y in range(h // 2):
            row = y * w
            for x in range(w // 2):
                edited[row + x] = 255 - edited[row + x]
        (out_dir / "edited.di_").write_bytes(ic.encode_di_(w, h, bytes(edited), pal))
        reloaded = rtkdib.CompressedDib(out_dir / "edited.di_")
        (out_dir / "edited_di.png").write_bytes(
            preview.png_indexed(w, h, reloaded.pixels, pal))
        written += ["edited.di_", "edited_di.png"]
        log("  edited backdrop reloads identically: %s"
            % (reloaded.pixels == bytes(edited)))

    res = ResFile(game / "RTKRES.bin")
    pal = boot_palette(res)
    entry = next((e for e in res.entries if e.type == "BITMAP" and e.size > 4096), None)
    if entry is not None:
        data = res.read_raw(entry)
        w, h, flags, f12, f16, rid = struct.unpack_from("<6I", data, 0)
        _, _, stride, px = rtkbitmap.decode_resource(data)
        blob = ic.encode_dib_bitmap(w, h, px, flags=flags, field12=f12,
                                    field16=f16, res_id=rid)
        (out_dir / "roundtrip_bitmap.bin").write_bytes(blob)
        w2, h2, stride2, px2 = rtkbitmap.decode_resource(
            (out_dir / "roundtrip_bitmap.bin").read_bytes())
        (out_dir / "roundtrip_bitmap.png").write_bytes(
            preview.png_indexed(w2, h2, px2, pal, stride2))
        written += ["roundtrip_bitmap.bin", "roundtrip_bitmap.png"]
    res.close()

    log("samples -> %s" % out_dir)
    for name in written:
        log("  %s" % name)


def _raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ValueError:
        return True
    except Exception:
        return False
    return False


# --- driver -------------------------------------------------------------

def run_pool(jobs, init, init_args, fn, items, log, label):
    totals = Counter()
    notes = []
    t0 = time.time()
    if jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs, initializer=init, initargs=init_args) as pool:
            for r, n in pool.imap_unordered(fn, items, chunksize=8):
                totals += r
                notes += n
    else:
        init(*init_args)
        for item in items:
            r, n = fn(item)
            totals += r
            notes += n
    log("%s: %d items in %.1fs" % (label, len(items), time.time() - t0))
    return totals, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", type=Path, default=REPO.parent,
                    help="game install, read only (default: the repo's parent)")
    ap.add_argument("--src", type=Path, default=REPO / "out" / "t3d",
                    help="directory to scan for .di_ files")
    ap.add_argument("--bitmap-png", type=Path, default=REPO / "out" / "png",
                    help="PNGs from a previous tools/export_bitmaps.py run")
    ap.add_argument("--dib-png", type=Path, default=REPO / "out" / "dib",
                    help="PNGs from a previous tools/rtkdib.py run")
    ap.add_argument("--foreign", type=Path, default=REPO / "ghidra",
                    help="tree of third-party PNGs to decode")
    ap.add_argument("--report", type=Path, default=REPO / "out" / "imagecodec-report.txt")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--limit", type=int, default=0, help="first N items per sweep")
    ap.add_argument("--samples", type=Path, default=REPO / "out" / "imagecodec",
                    help="where to write the round trips meant to be looked at")
    ap.add_argument("--skip", default="",
                    help="comma-separated: di,bmp,foreign,synthetic,samples")
    args = ap.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    lines = []

    def log(msg=""):
        print(msg, flush=True)
        lines.append(msg)

    failures = 0
    log("imagecodec validation")
    log("  repo    : %s" % REPO)
    log("  game    : %s (read only)" % args.game)
    log("  jobs    : %d" % args.jobs)
    log()

    # --- sweep 1
    if "di" not in skip:
        paths = sorted(str(p) for p in args.src.rglob("*.di_"))
        stems = Counter(Path(p).stem for p in paths)
        items = [(p, stems[Path(p).stem] == 1
                  and (args.dib_png / (Path(p).stem + ".png")).exists())
                 for p in paths]
        if args.limit:
            items = items[:args.limit]
        totals, notes = run_pool(args.jobs, _init_dib, (str(args.dib_png),),
                                 check_di, items, log, "sweep 1  .di_")
        n = totals["files"]
        log(".di_ files             : %d" % n)
        log("  decode errors        : %d" % totals["decode_error"])
        log("  encode_di_ exact     : %d / %d" % (totals["di_exact"], n))
        log("  PNG round trip exact : %d / %d" % (totals["png_exact"], n))
        log("  exported PNG matches : %d / %d"
            % (totals["disk_png_exact"], totals["disk_png"]))
        log("  quantize recovers    : %d exact, %d same colour via a duplicate"
            % (totals["quantize_exact"], totals["quantize_same_colour"]))
        log("  remap identity       : %d / %d" % (totals["remap_identity"], n))
        log("  palettes with dupes  : %d" % totals["duplicate_palette"])
        log("  bytes written        : %d" % totals["di_bytes"])
        for m in notes[:20]:
            log("  ! %s" % m)
        failures += len(notes)
        log()

    # --- sweep 2
    if "bmp" not in skip:
        res = ResFile(args.game / "RTKRES.bin")
        ids = [e.id for e in res.entries if e.type == "BITMAP"]
        res.close()
        manifest = {}
        csv_path = args.bitmap_png / "bitmaps.csv"
        if csv_path.exists():
            with csv_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    manifest[int(row["id"])] = row["file"]
        if args.limit:
            ids = ids[:args.limit]
        totals, notes = run_pool(args.jobs, _init_bitmaps,
                                 (str(args.game), str(args.bitmap_png), manifest),
                                 check_bitmap, ids, log, "sweep 2  BITMAP")
        n = totals["files"]
        log("BITMAP resources       : %d (rle %d, lzw %d, skipped %d)"
            % (n, totals["rle"], totals["lzw"], totals["skipped"]))
        log("  decode errors        : %d" % totals["decode_error"])
        log("  stored mode exact    : %d / %d" % (totals["bmp_exact"], n))
        log("  header preserved     : %d / %d" % (totals["header_preserved"], n))
        log("  PNG round trip exact : %d / %d" % (totals["png_exact"], n))
        log("  PNG -> resource exact: %d / %d" % (totals["png_import_exact"], n))
        log("  exported PNG matches : %d / %d"
            % (totals["disk_png_exact"], totals["disk_png"]))
        log("  size: %d bytes stored vs %d shipped (%.1fx)"
            % (totals["bmp_bytes"], totals["src_bytes"],
               totals["bmp_bytes"] / max(1, totals["src_bytes"])))
        for m in notes[:20]:
            log("  ! %s" % m)
        failures += len(notes)
        log()

    # --- sweep 3
    if "bmp" not in skip:
        res = ResFile(args.game / "RTKRES.bin")
        pal256 = boot_palette(res)
        res.close()
        files = sorted(str(p) for p in args.src.rglob("*.bmp"))
        if args.limit:
            files = files[:args.limit]
        totals, notes = run_pool(args.jobs, _init_bmp, (pal256,), check_bmp,
                                 files, log, "sweep 3  t3d .bmp")
        n = totals["files"]
        log("t3d .bmp textures      : %d (8bpp %d, 16bpp %d, 24bpp %d)"
            % (n, totals["bpp8"], totals["bpp16"], totals["bpp24"]))
        log("  decode errors        : %d" % totals["decode_error"])
        log("  dimensions agree     : %d / %d" % (totals["dims_ok"], n))
        log("  indexed -> BITMAP    : %d / %d" % (totals["bmp_exact"], n))
        log("  indexed -> .di_      : %d / %d" % (totals["di_exact"], totals["indexed"]))
        log("  quantize is nearest  : %d / %d sampled pixels in %d truecolour files"
            % (totals["nearest_ok"], totals["sampled"], totals["truecolour"]))
        if totals["sampled"]:
            log("  RMS colour shift     : %.2f (RGB distance, 0..441)"
                % ((totals["sum_sq_error"] / totals["sampled"]) ** 0.5))
        for m in notes[:20]:
            log("  ! %s" % m)
        failures += len(notes)
        log()

    # --- sweep 4
    if "foreign" not in skip:
        files = sorted(glob.glob(str(args.foreign / "**" / "*.png"), recursive=True))
        if args.limit:
            files = files[:args.limit]
        t0 = time.time()
        failures += sweep_foreign(files, log)
        log("  elapsed              : %.1fs" % (time.time() - t0))
        log()

    # --- sweep 5
    if "synthetic" not in skip:
        failures += sweep_synthetic(log)
        log()

    if "samples" not in skip:
        emit_samples(args.game, args.src, args.samples, log)
        log()

    log("FAILURES: %d" % failures)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("report -> %s" % args.report)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
