"""Turn an edit back into the asset's own on-disk format.

`preview.py` is the read direction: game bytes in, something viewable out.
This is the write direction, and it is deliberately the only place that
decides how an edit becomes game bytes. Every encoder either reproduces the
container exactly or refuses; nothing writes to the game install.

Three ways in, depending on what the asset is:
  text    the edited text, re-encoded (and re-wrapped if it was compressed)
  image   a PNG from any paint program, re-indexed onto the game's palette
  raw     replacement bytes used verbatim, which always works
"""

import gzip
import io
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyro_inflate

TEXT_EXTS = {".ktx", ".trx", ".trm", ".txt", ".h", ".def", ".tbl", ".rtk", ".mab"}
PYRO_EXTS = {".def", ".tbl", ".rtk", ".txt"}
IMAGE_EXTS = {".di_", ".bmp", ".dib"}


class EncodeError(ValueError):
    pass


def supports(asset) -> bool:
    """Everything can be replaced wholesale; this reports the smart paths."""
    ext = Path(asset.name).suffix.lower()
    return ext in TEXT_EXTS or ext in IMAGE_EXTS or ext == ".wav" or \
        ext == ".trk" or asset.restype == "BITMAP"


def mode_for(asset) -> str:
    """Which editor the UI should offer: 'text', 'image', 'audio' or 'raw'.

    Note that RTKRES's TEXT and SCRIPT types are binary widget records, not
    strings, so they deliberately fall through to 'raw'.
    """
    ext = Path(asset.name).suffix.lower()
    if ext in TEXT_EXTS:
        return "text"
    if ext in IMAGE_EXTS or asset.restype == "BITMAP":
        return "image"
    if ext == ".wav":
        return "audio"
    if ext == ".trk":
        return "anim"
    return "raw"


def encode(asset, payload: bytes, original: bytes = None, as_text=False,
           palette=None) -> bytes:
    """Encode one edit into the bytes that belong in the container.

    `palette` is the 256-entry table the edit should be indexed against. It
    matters for RTKRES bitmaps, which carry no palette of their own and are
    only correct against the PALETTE resource the scene realises -- so the
    caller passes whichever palette the user was actually looking at.
    """
    ext = Path(asset.name).suffix.lower()

    if as_text:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        return encode_text(text, ext, original)

    if payload[:8] == b"\x89PNG\r\n\x1a\n":
        return encode_image(asset, payload, original, palette)

    if ext == ".wav" and payload[:4] != b"RIFF":
        raise EncodeError("expected a RIFF/WAVE file, got %r" % payload[:4])

    return payload


# --- text ---------------------------------------------------------------

def encode_text(text: str, ext: str, original: bytes = None) -> bytes:
    """Re-encode edited text, restoring the container the original used."""
    body = text.replace("\r\n", "\n").encode("latin-1", "replace")
    if original is not None and original.startswith(pyro_inflate.SIG):
        return pyro_inflate.SIG + _gzip(body)
    if ext in PYRO_EXTS and original is None:
        return pyro_inflate.SIG + _gzip(body)
    return body


def _gzip(body: bytes) -> bytes:
    """A deterministic gzip stream: no mtime, no name, so builds reproduce."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as fh:
        fh.write(body)
    return buf.getvalue()


# --- images -------------------------------------------------------------

def encode_image(asset, png: bytes, original: bytes = None,
                 target=None) -> bytes:
    """Re-encode a PNG into whichever image format the asset uses."""
    try:
        import imagecodec
    except ImportError as exc:  # the image write path is a separate module
        raise EncodeError("image encoding needs tools/imagecodec.py (%s)" % exc)

    ext = Path(asset.name).suffix.lower()
    width, height, palette, pixels = imagecodec.decode_png(png)
    # An asset with its own embedded palette wins; otherwise use the one the
    # caller was viewing, which is the only thing that makes an RTKRES bitmap
    # come out right.
    target = _target_palette(original, ext) or target

    if palette is None:
        if target is None:
            raise EncodeError("need an indexed PNG: no palette to quantize onto")
        pixels = imagecodec.quantize(width, height, pixels, target)
    elif target is not None and list(palette) != list(target):
        pixels = imagecodec.remap(pixels, palette, target)
    else:
        target = list(palette)

    if ext == ".di_":
        return imagecodec.encode_di_(width, height, pixels, target)
    if asset.restype == "BITMAP":
        # A BITMAP header is six dwords; only the first three are understood.
        # Carry the original's trailing fields across rather than zeroing
        # them, since nothing has established that they are ignored.
        flags = f12 = f16 = res_id = 0
        if original is not None and len(original) >= 24:
            _w, _h, flags, f12, f16, res_id = struct.unpack_from("<6I", original)
        return imagecodec.encode_dib_bitmap(width, height, pixels, target,
                                            flags=flags, field12=f12,
                                            field16=f16, res_id=res_id)
    if ext in (".bmp", ".dib"):
        return _windows_bmp(width, height, pixels, target)
    raise EncodeError("no image encoder for %s" % (ext or asset.restype))


def _target_palette(original: bytes, ext: str):
    """Keep the asset's own palette so it still matches the rest of the scene."""
    if original is None:
        return None
    try:
        if ext == ".di_":
            import rtkdib
            return rtkdib.CompressedDib(Path("x.di_"), original).palette
        if ext in (".bmp", ".dib") and original[:2] == b"BM":
            off = struct.unpack_from("<I", original, 10)[0]
            used = struct.unpack_from("<I", original, 46)[0] or 256
            quads = original[54:54 + used * 4]
            return [(quads[i * 4 + 2], quads[i * 4 + 1], quads[i * 4]) for i in range(used)]
    except Exception:
        return None
    return None


def _windows_bmp(width, height, pixels, palette) -> bytes:
    """A plain 8-bit Windows BMP: bottom-up rows, 4-byte aligned stride."""
    palette = (list(palette) + [(0, 0, 0)] * 256)[:256]
    stride = (width + 3) & ~3
    rows = [bytes(pixels[y * width:(y + 1) * width]).ljust(stride, b"\0")
            for y in range(height - 1, -1, -1)]
    bits = b"".join(rows)
    quads = b"".join(bytes((b, g, r, 0)) for r, g, b in palette)
    offset = 14 + 40 + len(quads)
    header = b"BM" + struct.pack("<IHHI", offset + len(bits), 0, 0, offset)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 8, 0,
                       len(bits), 2835, 2835, 256, 0)
    return header + info + quads + bits
