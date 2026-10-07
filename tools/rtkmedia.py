"""Turn shipped .wav / .avi into something a browser can play.

Most RtK waves are MS ADPCM; Chromium only plays PCM. The GOG cutscenes
are XviD. This module decodes ADPCM itself and transcodes AVI through
ffmpeg or VLC when one of those is on the machine. Cached under out/preview/.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import app_paths

REPO = app_paths.repo_dir()


def _cache():
    return app_paths.preview_cache()

ADAPT = (
    230, 230, 230, 230, 307, 409, 512, 614,
    768, 614, 512, 409, 307, 230, 230, 230,
)

DEFAULT_COEF = (
    (256, 0), (512, -256), (0, 0), (192, 64),
    (240, 0), (460, -208), (392, -232),
)


def _chunks(raw: bytes, magic: bytes):
    if raw[:4] != b"RIFF" or raw[8:12] != magic:
        raise ValueError("not a RIFF/%s" % magic.decode("ascii", "replace"))
    off = 12
    while off + 8 <= len(raw):
        tag = raw[off:off + 4]
        size = struct.unpack_from("<I", raw, off + 4)[0]
        payload = raw[off + 8:off + 8 + size]
        yield tag, payload
        off += 8 + size + (size & 1)


def wav_meta(raw: bytes) -> dict:
    if len(raw) < 12 or raw[:4] != b"RIFF":
        return {}
    fmt = None
    for tag, payload in _chunks(raw, b"WAVE"):
        if tag == b"fmt ":
            fmt = payload
            break
    if not fmt or len(fmt) < 16:
        return {}
    tag, ch, rate, _avg, align, bits = struct.unpack_from("<HHI IHH", fmt, 0)
    rec = {
        "codec": {1: "PCM", 2: "MS ADPCM"}.get(tag, "tag %d" % tag),
        "channels": ch,
        "sample_rate": rate,
        "bits": bits,
        "block_align": align,
    }
    if tag == 2 and len(fmt) >= 20:
        rec["samples_per_block"] = struct.unpack_from("<H", fmt, 18)[0]
    return rec


def _pcm_wav(samples, rate: int, channels: int) -> bytes:
    data = struct.pack("<%dh" % len(samples), *samples)
    fmt = struct.pack("<HHI IHH", 1, channels, rate,
                      rate * channels * 2, channels * 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + \
        b"fmt " + struct.pack("<I", 16) + fmt + \
        b"data" + struct.pack("<I", len(data)) + data


def _nibble_signed(n):
    return n - 16 if n >= 8 else n


def _adpcm_sample(nibble, s1, s2, coef1, coef2, delta):
    pred = (s1 * coef1 + s2 * coef2) >> 8
    sample = pred + _nibble_signed(nibble) * delta
    if sample > 32767:
        sample = 32767
    elif sample < -32768:
        sample = -32768
    delta = (delta * ADAPT[nibble]) >> 8
    if delta < 16:
        delta = 16
    return sample, s1, delta


def _decode_ms_adpcm(fmt: bytes, data: bytes) -> tuple:
    tag, ch, rate, _avg, align, bits = struct.unpack_from("<HHI IHH", fmt, 0)
    extra = fmt[16:]
    samples_per_block = 0
    coefs = list(DEFAULT_COEF)
    if len(extra) >= 6:
        # extra: cbSize(2) + samplesPerBlock(2) + nCoef(2) + coef pairs
        samples_per_block, ncoef = struct.unpack_from("<HH", extra, 2)
        coefs = []
        off = 6
        for _ in range(ncoef):
            if off + 4 > len(extra):
                break
            coefs.append(struct.unpack_from("<hh", extra, off))
            off += 4
    if not samples_per_block:
        samples_per_block = ((align - (7 * ch)) * 2) // ch + 2
    if not coefs:
        coefs = list(DEFAULT_COEF)

    out = []
    off = 0
    while off + align <= len(data):
        block = data[off:off + align]
        off += align
        if ch == 1:
            pred = block[0]
            delta, s1, s2 = struct.unpack_from("<hhh", block, 1)
            if pred >= len(coefs):
                pred = 0
            c1, c2 = coefs[pred]
            out.extend((s2, s1))
            for b in block[7:]:
                for nib in ((b >> 4) & 0xF, b & 0xF):
                    s1, s2, delta = _adpcm_sample(nib, s1, s2, c1, c2, delta)
                    out.append(s1)
        else:
            pred_l, pred_r = block[0], block[1]
            delta_l, delta_r, s1_l, s1_r, s2_l, s2_r = struct.unpack_from(
                "<hhhhhh", block, 2)
            if pred_l >= len(coefs):
                pred_l = 0
            if pred_r >= len(coefs):
                pred_r = 0
            cl1, cl2 = coefs[pred_l]
            cr1, cr2 = coefs[pred_r]
            out.extend((s2_l, s2_r, s1_l, s1_r))
            for b in block[14:]:
                nib_l, nib_r = (b >> 4) & 0xF, b & 0xF
                s1_l, s2_l, delta_l = _adpcm_sample(
                    nib_l, s1_l, s2_l, cl1, cl2, delta_l)
                s1_r, s2_r, delta_r = _adpcm_sample(
                    nib_r, s1_r, s2_r, cr1, cr2, delta_r)
                out.extend((s1_l, s1_r))
    return out, rate, ch


def playable_wav(raw: bytes) -> tuple[bytes, dict]:
    """Return a PCM WAVE the browser can play, plus codec notes."""
    meta = wav_meta(raw)
    fmt = data = None
    for tag, payload in _chunks(raw, b"WAVE"):
        if tag == b"fmt ":
            fmt = payload
        elif tag == b"data":
            data = payload
    if not fmt or data is None:
        return raw, meta
    tag = struct.unpack_from("<H", fmt, 0)[0]
    if tag == 1:
        meta["preview"] = "PCM"
        return raw, meta
    if tag != 2:
        meta["preview"] = "unsupported codec"
        return raw, meta
    samples, rate, ch = _decode_ms_adpcm(fmt, data)
    meta["preview"] = "MS ADPCM decoded to PCM"
    return _pcm_wav(samples, rate, ch), meta


def _avi_lists(raw: bytes, start: int, end: int):
    off = start
    while off + 8 <= end:
        tag = raw[off:off + 4]
        size = struct.unpack_from("<I", raw, off + 4)[0]
        inner_end = min(off + 8 + size, end)
        if tag in (b"LIST", b"RIFF"):
            yield from _avi_lists(raw, off + 12, inner_end)
        else:
            yield tag, raw[off + 8:inner_end]
        off = inner_end + (size & 1)


def avi_info(raw: bytes) -> dict:
    info = {"video": None, "audio": None, "streams": []}
    if raw[8:12] != b"AVI ":
        return info
    stream_i = -1
    for tag, payload in _avi_lists(raw, 12, len(raw)):
        if tag == b"strh" and len(payload) >= 8:
            stream_i += 1
            kind = payload[:4].decode("latin-1", "replace")
            handler = payload[4:8].decode("latin-1", "replace")
            rec = {"index": stream_i, "type": kind, "handler": handler}
            info["streams"].append(rec)
            if kind == "vids":
                info["video"] = rec
            elif kind == "auds":
                info["audio"] = rec
        elif tag == b"strf" and info["streams"]:
            rec = info["streams"][-1]
            if rec["type"] == "vids" and len(payload) >= 20:
                rec["width"], rec["height"] = struct.unpack_from("<II", payload, 4)
                rec["fourcc"] = payload[16:20].decode("latin-1", "replace")
            elif rec["type"] == "auds" and len(payload) >= 16:
                rec["format"], rec["channels"], rec["rate"] = \
                    struct.unpack_from("<HHI", payload, 0)
                rec["bits"] = struct.unpack_from("<H", payload, 14)[0]
                rec["fmt"] = payload
    return info


def extract_avi_wav(raw: bytes) -> bytes | None:
    info = avi_info(raw)
    aud = info.get("audio")
    if not aud or not aud.get("fmt"):
        return None
    idx = aud["index"]
    chunk_id = ("%02d" % idx).encode("ascii") + b"wb"
    parts = []
    for tag, payload in _avi_lists(raw, 12, len(raw)):
        if tag == chunk_id:
            parts.append(payload)
    if not parts:
        return None
    data = b"".join(parts)
    fmt = aud["fmt"]
    if len(fmt) < 16:
        return None
    tag = struct.unpack_from("<H", fmt, 0)[0]
    body = b"RIFF" + struct.pack("<I", 20 + len(fmt) + len(data)) + b"WAVE" + \
        b"fmt " + struct.pack("<I", len(fmt)) + fmt + \
        b"data" + struct.pack("<I", len(data)) + data
    if tag == 2:
        pcm, _meta = playable_wav(body)
        return pcm
    return body


def _tool_paths():
    found = []
    for name in ("ffmpeg", "ffmpeg.exe"):
        p = shutil.which(name)
        if p:
            found.append(("ffmpeg", p))
    for p in (
        REPO / "out" / "ffmpeg" / "ffmpeg.exe",
        REPO / "out" / "ffmpeg" / "bin" / "ffmpeg.exe",
        app_paths.user_data() / "ffmpeg" / "ffmpeg.exe",
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
    ):
        if p.is_file():
            found.append(("ffmpeg", str(p)))
    vlc = Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe")
    if vlc.is_file():
        found.append(("vlc", str(vlc)))
    vlc32 = Path(r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe")
    if vlc32.is_file():
        found.append(("vlc", str(vlc32)))
    which_vlc = shutil.which("vlc")
    if which_vlc:
        found.append(("vlc", which_vlc))
    return found


def _cache_path(raw: bytes, suffix: str) -> Path:
    folder = _cache()
    digest = hashlib.sha1(raw[:65536] + struct.pack("<I", len(raw))).hexdigest()[:16]
    return folder / (digest + suffix)


def _run(cmd, timeout=180):
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _transcode_ffmpeg(ffmpeg: str, src: Path, dest: Path) -> bool:
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        str(dest),
    ]
    r = _run(cmd)
    if r.returncode == 0 and dest.is_file() and dest.stat().st_size > 32:
        return True
    dest.unlink(missing_ok=True)
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-c:v", "libvpx", "-b:v", "800k",
        "-c:a", "libvorbis",
        str(dest.with_suffix(".webm")),
    ]
    r = _run(cmd)
    webm = dest.with_suffix(".webm")
    if r.returncode == 0 and webm.is_file() and webm.stat().st_size > 32:
        if dest != webm:
            dest.unlink(missing_ok=True)
        webm.replace(dest)
        return True
    webm.unlink(missing_ok=True)
    return False


def _transcode_vlc(vlc: str, src: Path, dest: Path) -> bool:
    dest_posix = dest.resolve().as_posix()
    sout = (
        "#transcode{vcodec=h264,vb=800,acodec=mp4a,ab=96,channels=2}"
        ":standard{access=file,mux=mp4,dst='%s'}" % dest_posix
    )
    cmd = [
        vlc, "-I", "dummy", "--quiet", "--no-loop", "--play-and-exit",
        str(src), "--sout", sout, "vlc://quit",
    ]
    r = _run(cmd, timeout=180)
    return r.returncode == 0 and dest.is_file() and dest.stat().st_size > 32


def has_transcoder() -> bool:
    return bool(_tool_paths())


def cached_video(raw: bytes):
    path = _cache_path(raw, ".mp4")
    if path.is_file() and path.stat().st_size > 32:
        return path
    return None


def video_preview_meta(raw: bytes) -> tuple[str, dict]:
    info = avi_info(raw)
    meta = {
        "fourcc": (info.get("video") or {}).get("fourcc") or "avi",
        "width": (info.get("video") or {}).get("width"),
        "height": (info.get("video") or {}).get("height"),
    }
    if info.get("audio"):
        meta["audio_codec"] = {
            1: "PCM", 2: "MS ADPCM", 85: "MP3",
        }.get(info["audio"].get("format"), "tag %s" % info["audio"].get("format"))
        meta["audio_rate"] = info["audio"].get("rate")
    if cached_video(raw):
        meta["preview"] = "transcoded H.264 (cached)"
        return "video/mp4", meta
    if has_transcoder():
        meta["preview"] = "XviD — transcoding on first play"
        return "video/mp4", meta
    if info.get("audio"):
        meta["preview"] = "XviD — audio only (install ffmpeg for picture)"
        return "audio/wav", meta
    meta["preview"] = "XviD — no decoder (install ffmpeg or VLC)"
    return "video/x-msvideo", meta


def playable_avi(raw: bytes) -> tuple[str, bytes, dict]:
    """Return (content_type, body, meta). Prefers H.264 MP4, else extracted audio."""
    info = avi_info(raw)
    meta = {
        "fourcc": (info.get("video") or {}).get("fourcc") or "avi",
        "width": (info.get("video") or {}).get("width"),
        "height": (info.get("video") or {}).get("height"),
    }
    if info.get("audio"):
        meta["audio_codec"] = {
            1: "PCM", 2: "MS ADPCM", 85: "MP3",
        }.get(info["audio"].get("format"), "tag %s" % info["audio"].get("format"))
        meta["audio_rate"] = info["audio"].get("rate")

    cached = _cache_path(raw, ".mp4")
    if cached.is_file() and cached.stat().st_size > 32:
        meta["preview"] = "transcoded H.264 (cached)"
        return "video/mp4", cached.read_bytes(), meta

    tools = _tool_paths()
    src = tmp_dest = None
    try:
        tmp = Path(tempfile.gettempdir())
        src = tmp / (cached.stem + ".avi")
        tmp_dest = tmp / (cached.stem + ".mp4")
        src.write_bytes(raw)
        tmp_dest.unlink(missing_ok=True)
        for kind, path in tools:
            ok = False
            if kind == "ffmpeg":
                ok = _transcode_ffmpeg(path, src, tmp_dest)
            elif kind == "vlc":
                ok = _transcode_vlc(path, src, tmp_dest)
            if ok:
                shutil.move(str(tmp_dest), str(cached))
                meta["preview"] = "transcoded H.264 via %s" % kind
                return "video/mp4", cached.read_bytes(), meta
    except Exception as exc:
        meta["transcode_error"] = str(exc)
    finally:
        if src is not None:
            src.unlink(missing_ok=True)
        if tmp_dest is not None:
            tmp_dest.unlink(missing_ok=True)

    wav = extract_avi_wav(raw)
    if wav:
        meta["preview"] = "XviD — audio extracted; install ffmpeg for picture"
        return "audio/wav", wav, meta
    meta["preview"] = "XviD — no decoder (install ffmpeg or VLC)"
    return "video/x-msvideo", raw, meta
