"""Decoder for the RTKRES BITMAP compression (resource type 1).

Reimplemented from Rtlib32.dll's DecompressBitmapData / FUN_10041f2a /
FUN_10041d60. Three nested layers:

  chunk     u16 control word: top 3 bits select the method, low 13 bits give
            the chunk's compressed byte length.
  subblock  compressed chunks contain sub-blocks, each prefixed with a u16
            length. Every sub-block is an independent LZW stream.
  lzw       MSB-first LZW, fixed code width per chunk, dictionary seeded with
            the 256 literals, no clear code.

The original reads bits through a rotating table of 8 precomputed masks
(FUN_10041a70). Those are just the leftover-bit masks for each bit phase of
the chosen code width, so a plain MSB-first bit reader is equivalent.
"""

import struct

# DecompressBitmapData: control word -> method
M_STORED = 0x0000
M_W10 = 0x4000
M_W11 = 0x6000
M_W12 = 0x8000
M_END = 0xE000
LEN_MASK = 0x1FFF

WIDTH_FOR = {M_W10: 10, M_W11: 11, M_W12: 12}

TABLE_SIZE = 0x139D  # FUN_10041c6c allocates this many dictionary slots


class _Bits:
    """MSB-first bit reader."""

    __slots__ = ("data", "pos", "acc", "nbits")

    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.acc = 0
        self.nbits = 0

    def read(self, width):
        while self.nbits < width:
            if self.pos >= len(self.data):
                return None
            self.acc = (self.acc << 8) | self.data[self.pos]
            self.pos += 1
            self.nbits += 8
        self.nbits -= width
        code = (self.acc >> self.nbits) & ((1 << width) - 1)
        self.acc &= (1 << self.nbits) - 1
        return code


def lzw_decode(src: bytes, width: int, limit: int) -> bytearray:
    """Decode one LZW sub-block. `limit` caps the output size."""
    end_code = (1 << width) - 1
    # FUN_10041d60 stops growing the dictionary once next_code passes
    # (1 << width) - 2, freezing it rather than resetting.
    max_code = end_code - 1

    prefix = [0] * TABLE_SIZE
    suffix = bytearray(TABLE_SIZE)
    length = bytearray(TABLE_SIZE)  # extra chars beyond the first
    next_code = 0x100

    out = bytearray()
    bits = _Bits(src)

    code = bits.read(width)
    if code is None or code >= 0x100:
        return out
    out.append(code)
    old_code = code
    first_char = code

    while len(out) < limit:
        code = bits.read(width)
        if code is None or code == end_code:
            break

        if code < next_code:
            emit, first_char = _string_of(code, prefix, suffix, length)
        else:
            # KwKwK: the code is the one we are about to define.
            emit, first_char = _string_of(old_code, prefix, suffix, length)
            emit.append(first_char)
        out += emit

        if next_code <= max_code:
            prefix[next_code] = old_code
            suffix[next_code] = first_char
            length[next_code] = (length[old_code] + 1) & 0xFF
            next_code += 1
        old_code = code

    return out[:limit]


def _string_of(code, prefix, suffix, length):
    """Expand a dictionary code; returns (bytes, first character)."""
    if code < 0x100:
        return bytearray([code]), code
    n = length[code]
    buf = bytearray(n + 1)
    cur = code
    for i in range(n, 0, -1):
        buf[i] = suffix[cur]
        cur = prefix[cur]
    buf[0] = cur & 0xFF
    return buf, cur & 0xFF


def rle_decode(src: bytes, width: int, stride: int, height: int) -> bytearray:
    """Decode the flags & 0x80 scanline RLE (FUN_1002f1ec).

    The payload opens with a row offset table of `height` u16 entries, then a
    byte-oriented opcode stream. The table is a random-access index for the
    blitter, not something the decoder needs: FUN_1002f1ec seeks to
    `data + height * 2` -- which is exactly `table[height - 1]` -- and then
    runs straight through. The entries *descend*, so decoding sequentially
    walks the rows from table index height-1 down to 0; see `decode_resource`
    on why that is the bottom-up DIB order.

    Opcodes:

        0x00        end of scanline; skip to the next row at `stride`
        0x01..0x7f  run: length is the opcode, value is the next byte
        0x80..0xfe  literal of (0xff ^ opcode) bytes
        0xff        literal whose length is taken from the next byte
    """
    out = bytearray(stride * height)
    pos = height * 2  # skip the row offset table
    row = 0

    while row < height and pos < len(src):
        dst = row * stride
        end = dst + width
        while pos < len(src):
            op = src[pos]
            pos += 1
            if op == 0:
                break
            if op < 0x80:
                if pos >= len(src):
                    break
                value = src[pos]
                pos += 1
                n = min(op, end - dst)
                if n > 0:
                    out[dst:dst + n] = bytes([value]) * n
                    dst += n
            else:
                n = op ^ 0xFF
                if op == 0xFF:
                    if pos >= len(src):
                        break
                    n = src[pos]
                    pos += 1
                chunk = src[pos:pos + n]
                pos += n
                keep = min(len(chunk), end - dst)
                if keep > 0:
                    out[dst:dst + keep] = chunk[:keep]
                    dst += keep
        row += 1
        if pos < len(src) and src[pos] == 0:
            break
    return out


def flip_vertical(pixels: bytes, stride: int, height: int) -> bytearray:
    """Reverse scanline order: bottom-up DIB buffer -> top-down image."""
    out = bytearray(stride * height)
    for y in range(height):
        src = (height - 1 - y) * stride
        out[y * stride:(y + 1) * stride] = pixels[src:src + stride]
    return out


def decode_resource(data: bytes, top_down: bool = True):
    """Decode a whole BITMAP resource. Returns (width, height, stride, pixels).

    Both codecs fill a **bottom-up Windows DIB**: the first scanline they emit
    is the lowest one on screen. The engine hands the buffer straight to
    StretchDIBits / SetDIBitsToDevice / CreateDIBSection with a *positive*
    biHeight (FUN_10039acd, FUN_10018a83, FUN_1003..., all reading height from
    runtime offset 0xc), and a positive biHeight is GDI's bottom-up case. The
    RLE row table confirms it independently: its entries descend, so the row
    the decoder emits first is the one the table calls row height-1.

    `top_down` (the default) reverses the scanlines so the result is an
    ordinary top-down image. Pass False to get the buffer byte-for-byte as the
    engine builds it.
    """
    width, height, flags = struct.unpack_from("<3I", data, 0)
    stride = (width + 3) & ~3
    payload = data[24:]
    if flags & 0x80:
        pixels = rle_decode(payload, width, stride, height)
    else:
        pixels = decompress(payload, stride * height)
    if top_down:
        pixels = flip_vertical(pixels, stride, height)
    return width, height, stride, pixels


def decompress(src: bytes, expected: int) -> bytearray:
    """Run the full chunk/sub-block/LZW pipeline for `expected` output bytes."""
    out = bytearray()
    pos = 0
    while pos + 2 <= len(src):
        ctrl = struct.unpack_from("<H", src, pos)[0]
        pos += 2
        method = ctrl & 0xE000
        clen = ctrl & LEN_MASK

        if method == M_END:
            break
        if method == M_STORED:
            out += src[pos:pos + clen]
        elif method in WIDTH_FOR:
            width = WIDTH_FOR[method]
            blk, end = pos, pos + clen
            while blk + 2 <= end:
                sublen = struct.unpack_from("<H", src, blk)[0]
                blk += 2
                if sublen == 0:
                    break
                out += lzw_decode(src[blk:blk + sublen], width,
                                  max(expected - len(out), 0))
                blk += sublen
        else:
            raise ValueError(f"unknown method {method:#06x} at {pos - 2}")

        pos += clen
        if expected and len(out) >= expected:
            break
    return out
