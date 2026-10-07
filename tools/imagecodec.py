"""The image *write* path: PNG in, game formats out.

Every other image tool in this repo reads. This one is the import side, so the
art can leave the game as a PNG, be edited in any paint program, and come back
as a file the engine's own loaders accept.

Four pieces:

  decode_png          read a PNG without Pillow -- indexed stays indexed,
                      greyscale and truecolour come back as RGB triples
  quantize / remap    get truecolour or foreign-palette pixels onto the fixed
                      256-entry palette the engine runs on
  encode_di_          write `.di_`, the compressed DIB (scene backdrops)
  encode_dib_bitmap   write an RTKRES type-1 BITMAP resource

Standard library only: `zlib` and `struct`. Nothing here writes to disk, and
nothing here needs the game install.

Format details are not re-derived here; they come from `docs/dib-format.md`,
`docs/rtkres-format.md` and `docs/bitmap-codec.md`, and the channel order
follows what `tools/rtkdib.py` and `tools/rtkres.py` already read. The one new
fact this module relies on is the stored-mode contract in
`DecompressBitmapData`, quoted in `encode_dib_bitmap`.
"""

import struct
import zlib

# --- PNG ----------------------------------------------------------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

GREY, TRUECOLOUR, INDEXED, GREY_ALPHA, RGBA = 0, 2, 3, 4, 6

# Samples per pixel, and the bit depths PNG allows, per colour type.
CHANNELS = {GREY: 1, TRUECOLOUR: 3, INDEXED: 1, GREY_ALPHA: 2, RGBA: 4}
DEPTHS = {
    GREY: (1, 2, 4, 8, 16),
    TRUECOLOUR: (8, 16),
    INDEXED: (1, 2, 4, 8),
    GREY_ALPHA: (8, 16),
    RGBA: (8, 16),
}

# Sub-byte greyscale scaled to 0..255: 1bpp doubles to 0/255, 2bpp to 0/85/
# 170/255, 4bpp to multiples of 17. Exactly PNG's own sample-depth scaling.
_GREY_SCALE = {1: 255, 2: 85, 4: 17}


def _chunks(data: bytes, check_crc: bool):
    """Walk the chunk stream, yielding (tag, payload) and stopping at IEND."""
    pos = len(PNG_SIGNATURE)
    end = len(data)
    while pos + 8 <= end:
        length = struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4:pos + 8]
        body_end = pos + 8 + length
        if body_end + 4 > end:
            raise ValueError("truncated %s chunk" % tag.decode("latin-1"))
        payload = data[pos + 8:body_end]
        if check_crc:
            want = struct.unpack_from(">I", data, body_end)[0]
            got = zlib.crc32(tag + payload) & 0xFFFFFFFF
            if got != want:
                raise ValueError("bad CRC in %s chunk" % tag.decode("latin-1"))
        yield tag, payload
        pos = body_end + 4
        if tag == b"IEND":
            return
    raise ValueError("no IEND chunk")


def _unfilter(raw: bytes, height: int, row_bytes: int, bpp: int) -> bytearray:
    """Reverse the five PNG scanline filters. `bpp` is bytes per pixel, >= 1."""
    out = bytearray(height * row_bytes)
    prev = bytes(row_bytes)
    pos = 0
    need = height * (row_bytes + 1)
    if len(raw) < need:
        raise ValueError("image data is %d bytes, need %d" % (len(raw), need))

    for y in range(height):
        ft = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + row_bytes])
        pos += 1 + row_bytes

        if ft == 0:
            pass
        elif ft == 1:  # Sub
            for i in range(bpp, row_bytes):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:  # Up
            if y:
                line = bytearray((a + b) & 0xFF for a, b in zip(line, prev))
        elif ft == 3:  # Average
            for i in range(bpp):
                line[i] = (line[i] + (prev[i] >> 1)) & 0xFF
            for i in range(bpp, row_bytes):
                line[i] = (line[i] + ((line[i - bpp] + prev[i]) >> 1)) & 0xFF
        elif ft == 4:  # Paeth
            for i in range(bpp):
                line[i] = (line[i] + prev[i]) & 0xFF
            for i in range(bpp, row_bytes):
                a = line[i - bpp]
                b = prev[i]
                c = prev[i - bpp]
                p = a + b - c
                pa = p - a
                if pa < 0:
                    pa = -pa
                pb = p - b
                if pb < 0:
                    pb = -pb
                pc = p - c
                if pc < 0:
                    pc = -pc
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                line[i] = (line[i] + pr) & 0xFF
        else:
            raise ValueError("unknown scanline filter %d on row %d" % (ft, y))

        out[y * row_bytes:(y + 1) * row_bytes] = line
        prev = line
    return out


def _unpack_bits(buf, width: int, height: int, row_bytes: int, depth: int) -> bytearray:
    """Expand 1/2/4-bit samples to one byte each. Rows are byte-aligned."""
    out = bytearray(width * height)
    mask = (1 << depth) - 1
    shifts = list(range(8 - depth, -1, -depth))
    for y in range(height):
        base = y * row_bytes
        o = y * width
        x = 0
        for i in range(row_bytes):
            v = buf[base + i]
            for s in shifts:
                if x >= width:
                    break
                out[o + x] = (v >> s) & mask
                x += 1
            if x >= width:
                break
    return out


def _grey_to_rgb(grey, count: int) -> bytes:
    """One grey byte per pixel -> RGB triples, via C-level strided assignment."""
    rgb = bytearray(count * 3)
    rgb[0::3] = grey
    rgb[1::3] = grey
    rgb[2::3] = grey
    return bytes(rgb)


def decode_png(data: bytes, check_crc: bool = True):
    """Decode a PNG to (width, height, palette_or_None, pixels).

    Indexed PNGs (colour type 3) come back as one palette index per pixel with
    `palette` set to the PLTE entries as (r, g, b) tuples -- so an indexed
    round trip through PNG is exact, which is what the editing workflow needs.

    Greyscale and truecolour PNGs (colour types 0, 2, 4, 6) come back with
    `palette` None and `pixels` as packed RGB triples, three bytes per pixel,
    top-down. Feed those to `quantize` to get indices.

    Accepted: colour types 0, 2, 3, 4 and 6; bit depths 1, 2, 4, 8 and 16.
    Sub-byte greyscale is scaled up to 0..255; 16-bit samples are truncated to
    their high byte, as PNG's own depth reduction does.

    **Alpha is dropped.** Colour types 4 and 6 lose their alpha channel, and
    tRNS is ignored, so a transparent pixel keeps whatever colour was stored
    under it. The engine's formats are 8-bit indexed with no alpha channel;
    transparency there is a palette index the blitter skips, so it has to be
    expressed as that index, not as PNG alpha.

    Interlaced (Adam7) PNGs are rejected -- re-save without interlacing.
    Chunk CRCs are checked; pass check_crc=False to tolerate broken ones.
    """
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG: bad signature %r" % data[:8])

    width = height = depth = colour = None
    palette = None
    idat = []
    seen_ihdr = False

    for tag, payload in _chunks(data, check_crc):
        if tag == b"IHDR":
            if len(payload) != 13:
                raise ValueError("IHDR is %d bytes, expected 13" % len(payload))
            (width, height, depth, colour, compression, filtering,
             interlace) = struct.unpack(">IIBBBBB", payload)
            seen_ihdr = True
            if width == 0 or height == 0:
                raise ValueError("zero-sized image %dx%d" % (width, height))
            if colour not in CHANNELS:
                raise ValueError("unsupported colour type %d" % colour)
            if depth not in DEPTHS[colour]:
                raise ValueError("bit depth %d is not legal for colour type %d"
                                 % (depth, colour))
            if compression != 0:
                raise ValueError("unknown compression method %d" % compression)
            if filtering != 0:
                raise ValueError("unknown filter method %d" % filtering)
            if interlace:
                raise ValueError(
                    "interlaced (Adam7) PNGs are not supported; re-save "
                    "without interlacing")
        elif tag == b"PLTE":
            if len(payload) % 3:
                raise ValueError("PLTE is %d bytes, not a multiple of 3"
                                 % len(payload))
            palette = [tuple(payload[i:i + 3]) for i in range(0, len(payload), 3)]
        elif tag == b"IDAT":
            idat.append(payload)
        elif tag == b"IEND":
            break
        elif not (tag[0] & 0x20):
            # Uppercase first letter == critical chunk. PNG says a decoder
            # must not guess at a critical chunk it does not know.
            raise ValueError("unsupported critical chunk %s"
                             % tag.decode("latin-1"))

    if not seen_ihdr:
        raise ValueError("no IHDR chunk")
    if not idat:
        raise ValueError("no IDAT chunk")
    if colour == INDEXED and palette is None:
        raise ValueError("indexed PNG with no PLTE chunk")

    raw = zlib.decompress(b"".join(idat))

    channels = CHANNELS[colour]
    bits = channels * depth
    row_bytes = (width * bits + 7) // 8
    bpp = max(1, bits // 8)
    buf = _unfilter(raw, height, row_bytes, bpp)

    if depth == 16:
        # Keep the high byte of every sample. Rows are a whole number of
        # samples wide at 16bpp, so one strided delete does the lot.
        del buf[1::2]
        row_bytes //= 2
        depth = 8

    count = width * height

    if colour == INDEXED:
        # At depth 8 a row is exactly `width` bytes, so the buffer is already
        # the pixel array; below that, rows are bit-packed and byte-aligned.
        pixels = (bytes(buf) if depth == 8
                  else bytes(_unpack_bits(buf, width, height, row_bytes, depth)))
        high = max(pixels) if pixels else 0
        if high >= len(palette):
            raise ValueError("pixel index %d is outside a %d-entry PLTE"
                             % (high, len(palette)))
        return width, height, palette, pixels

    if colour == GREY:
        if depth == 8:
            grey = bytes(buf)
        else:
            grey = bytes(_unpack_bits(buf, width, height, row_bytes, depth))
            grey = grey.translate(bytes((i * _GREY_SCALE[depth]) & 0xFF
                                        for i in range(256)))
        return width, height, None, _grey_to_rgb(grey, count)

    if colour == GREY_ALPHA:
        del buf[1::2]  # drop alpha
        return width, height, None, _grey_to_rgb(bytes(buf[:count]), count)

    if colour == RGBA:
        del buf[3::4]  # drop alpha
        return width, height, None, bytes(buf[:count * 3])

    return width, height, None, bytes(buf[:count * 3])  # TRUECOLOUR


# --- palette mapping ----------------------------------------------------

MAX_PALETTE = 256


def _rgb_list(palette):
    out = [tuple(e[:3]) for e in palette]
    if len(out) > MAX_PALETTE:
        raise ValueError("palette has %d entries, max %d" % (len(out), MAX_PALETTE))
    for r, g, b in out:
        if not (0 <= r < 256 and 0 <= g < 256 and 0 <= b < 256):
            raise ValueError("palette entry out of range: %r" % ((r, g, b),))
    return out


def _exact_map(pal):
    """rgb -> lowest index holding that colour."""
    exact = {}
    for i, rgb in enumerate(pal):
        exact.setdefault(rgb, i)
    return exact


def _nearest(pal, r: int, g: int, b: int) -> int:
    """Nearest entry in an already-normalised list of (r, g, b) triples."""
    best = 0
    best_d = 1 << 30
    for i, (pr, pg, pb) in enumerate(pal):
        dr = pr - r
        dg = pg - g
        db = pb - b
        d = dr * dr + dg * dg + db * db
        if d < best_d:
            best_d = d
            best = i
            if d == 0:
                break
    return best


def nearest_index(palette, r: int, g: int, b: int) -> int:
    """Index of the palette entry closest to (r, g, b) in squared RGB distance.

    Ties go to the lowest index, so the mapping is deterministic.
    """
    return _nearest(_rgb_list(palette), r, g, b)


def quantize(width, height, rgb: bytes, palette) -> bytes:
    """Map truecolour pixels onto a fixed palette, nearest colour.

    `rgb` is packed RGB triples, top-down, `width * height * 3` bytes -- what
    `decode_png` returns for a greyscale or truecolour PNG. The result is one
    index per pixel.

    Nearest means smallest squared distance in plain RGB, with ties going to
    the lowest index. Colours already in the palette map onto themselves
    exactly, so re-importing an unmodified export is lossless. There is no
    dithering: the engine's art is flat-shaded 8-bit and dithering a region a
    palette already covers only adds noise. Each distinct input colour is
    resolved once and cached, so cost tracks the number of distinct colours,
    not the pixel count.
    """
    pal = _rgb_list(palette)
    if not pal:
        raise ValueError("empty palette")
    n = width * height
    if len(rgb) != n * 3:
        raise ValueError("rgb is %d bytes, expected %d for %dx%d"
                         % (len(rgb), n * 3, width, height))

    cache = {}
    for colour, i in _exact_map(pal).items():
        cache[bytes(colour)] = i

    out = bytearray(n)
    get = cache.get
    for i in range(n):
        key = rgb[i * 3:i * 3 + 3]
        idx = get(key)
        if idx is None:
            idx = cache[key] = _nearest(pal, key[0], key[1], key[2])
        out[i] = idx
    return bytes(out)


def remap(pixels: bytes, src_palette, dst_palette) -> bytes:
    """Re-index an indexed image onto a different fixed palette.

    Builds a 256-byte translation table -- each source index resolves to the
    destination entry closest to the colour it stood for -- and applies it in
    one pass. Identical palettes give the identity table, so the common case
    costs nothing and loses nothing. Indices past the end of `src_palette`
    have no colour to stand for and map to 0.

    An index whose colour is unchanged keeps its own number even when another
    slot holds the same colour. Two slots sharing an RGB value are not
    interchangeable to the engine -- the blitter skips a specific index for
    transparency -- so collapsing them would be wrong, not merely untidy.
    """
    src = _rgb_list(src_palette)
    dst = _rgb_list(dst_palette)
    if not dst:
        raise ValueError("empty destination palette")

    exact = _exact_map(dst)
    table = bytearray(MAX_PALETTE)
    for i in range(MAX_PALETTE):
        if i >= len(src):
            table[i] = 0
            continue
        rgb = src[i]
        if i < len(dst) and dst[i] == rgb:
            table[i] = i
            continue
        hit = exact.get(rgb)
        table[i] = hit if hit is not None else _nearest(dst, *rgb)
    return bytes(pixels).translate(bytes(table))


# --- .di_ (compressed DIB) ---------------------------------------------

DI_SIGNATURE = b"\x89DI_\r\n\x1a\n"
DI_HEADER_SIZE = 0x14
DI_PALETTE_SIZE = 0x400
DI_PALETTE_ENTRIES = DI_PALETTE_SIZE // 4


def palette_block(palette) -> bytes:
    """256 PALETTEENTRY records: (red, green, blue, flags=0), 1024 bytes.

    Byte 0 is red -- `docs/dib-format.md` settles that from the call chain,
    and `rtkdib.CompressedDib` reads it that way. Short palettes are padded
    with black; the flags byte is 0 in all 1,585 shipped files.
    """
    pal = _rgb_list(palette)
    out = bytearray(DI_PALETTE_SIZE)
    for i, (r, g, b) in enumerate(pal[:DI_PALETTE_ENTRIES]):
        o = i * 4
        out[o] = r
        out[o + 1] = g
        out[o + 2] = b
    return bytes(out)


def encode_di_(width, height, pixels: bytes, palette, level: int = 9) -> bytes:
    """Build a `.di_` compressed-DIB file.

    `pixels` is 8-bit palette indices, exactly `width * height` bytes, in
    **top-down** row order with no stride padding -- `ReadCompressedDib` hands
    `width * height` to zlib's uncompress as the output length, so there is no
    room for padding and no flip (see `docs/dib-format.md`).

    Note the loader also checks the header's width and height against the
    dimensions the *caller* expects and refuses the file on mismatch, so a
    replacement backdrop has to keep the dimensions of the one it replaces --
    all 1,585 shipped files are 640x480.
    """
    if width <= 0 or height <= 0:
        raise ValueError("bad dimensions %dx%d" % (width, height))
    expected = width * height
    if len(pixels) != expected:
        raise ValueError("pixels is %d bytes, expected %d for %dx%d"
                         % (len(pixels), expected, width, height))
    body = zlib.compress(bytes(pixels), level)
    return (DI_SIGNATURE
            + struct.pack("<III", width, height, len(body))
            + palette_block(palette)
            + body)


# --- RTKRES type-1 BITMAP ----------------------------------------------

BITMAP_HEADER_SIZE = 24
M_STORED = 0x0000
M_END = 0xE000
CHUNK_MAX = 0x1FFF  # the control word's length field is 13 bits
FLAG_RLE = 0x80


def stride_for(width: int) -> int:
    """Windows DIB rows are padded to a dword: (width + 3) & ~3.

    `FUN_1002dd8e` computes it itself -- `*(uint *)(buf + 8) =
    *(int *)(buf + 4) + 3U & 0xfffffffc` -- so the file never stores it.
    """
    return (width + 3) & ~3


def _stored_stream(dib: bytes) -> bytes:
    """Wrap a byte buffer as stored chunks, terminated by the end marker.

    `DecompressBitmapData` (Rtlib32.dll) is explicit about what it accepts:

        if ((uVar1 & 0xe000) == 0xe000) return param_4 == 0;
        if ((uVar1 & 0xe000) == 0)    { if (param_4 < (uVar1 & 0x1fff)) return false;
                                        CopyHugeBytes(dest, src, len); }
        ...
        if (local_c == 0) break;        // -> return false

    Three constraints follow, and this function satisfies all three: no chunk
    may be empty, no chunk may run past the remaining output, and the stream
    must deliver *exactly* `stride * height` bytes before the end marker, or
    the end-of-data test returns false and the caller frees the bitmap.

    Stored mode is not a theoretical branch: 17 chunks in the shipped archive
    use it, one of them at the full 8,191-byte maximum.
    """
    out = bytearray()
    for off in range(0, len(dib), CHUNK_MAX):
        part = dib[off:off + CHUNK_MAX]
        out += struct.pack("<H", M_STORED | len(part))
        out += part
    out += struct.pack("<H", M_END)
    return bytes(out)


def encode_dib_bitmap(width, height, pixels: bytes, palette=None,
                      flags: int = 0, field12: int = 0, field16: int = 0,
                      res_id: int = 0) -> bytes:
    """Build an RTKRES type-1 BITMAP resource in uncompressed STORED mode.

    `pixels` is 8-bit palette indices in **top-down** row order, either tightly
    packed (`width * height`) or already padded to `stride_for(width)` per row
    (`stride * height`, what `rtkbitmap.decode_resource` returns). Padded input
    is preserved byte for byte; tight input is padded with zeros.

    The result is written bottom-up, because both of the engine's codecs fill a
    bottom-up Windows DIB and the buffer goes straight to GDI with a positive
    biHeight (see `docs/bitmap-codec.md`). Getting this backwards flips the
    image, so it is worth restating: the last row of the image is the first row
    in the file.

    `flags` bit 7 selects the codec and is always cleared here: clear means the
    chunked stream, which is the branch that understands stored chunks. Other
    flag bits and the three trailing header dwords are carried through so a
    re-encoded resource keeps whatever the original said.

    `palette` is accepted for symmetry with `encode_di_` and **ignored**: a
    BITMAP resource has no colour table. The engine runs one global 256-entry
    palette (key resource 6 == pIntfacePal) with scene-specific alternates
    swapped in at runtime, so the palette is a property of the scene, not of
    the bitmap -- `docs/bitmap-codec.md`, "There is no per-bitmap palette".

    Nothing here compresses, by design. Stored mode makes the LZW *encoder*
    unnecessary, and the only cost is file size; the loader treats a stored
    chunk and an LZW chunk identically once decoded.
    """
    if width <= 0 or height <= 0:
        raise ValueError("bad dimensions %dx%d" % (width, height))

    stride = stride_for(width)
    padded = stride * height
    tight = width * height
    pixels = bytes(pixels)

    if len(pixels) == padded:
        rows = [pixels[y * stride:(y + 1) * stride] for y in range(height)]
    elif len(pixels) == tight:
        pad = bytes(stride - width)
        rows = [pixels[y * width:(y + 1) * width] + pad for y in range(height)]
    else:
        raise ValueError("pixels is %d bytes, expected %d (tight) or %d "
                         "(stride-padded) for %dx%d"
                         % (len(pixels), tight, padded, width, height))

    dib = b"".join(reversed(rows))  # top-down image -> bottom-up DIB
    header = struct.pack("<6I", width, height, flags & ~FLAG_RLE,
                         field12 & 0xFFFFFFFF, field16 & 0xFFFFFFFF,
                         res_id & 0xFFFFFFFF)
    return header + _stored_stream(dib)


# --- convenience --------------------------------------------------------

def png_to_indexed(data: bytes, palette, check_crc: bool = True):
    """Read a PNG and return (width, height, pixels) on `palette`.

    The one call the import path actually needs: indexed PNGs are re-indexed
    with `remap` (identity when the palette matches, which is the case for an
    unmodified export), truecolour and greyscale go through `quantize`.
    """
    width, height, src_palette, pixels = decode_png(data, check_crc)
    if src_palette is None:
        pixels = quantize(width, height, pixels, palette)
    else:
        pixels = remap(pixels, src_palette, palette)
    return width, height, pixels
