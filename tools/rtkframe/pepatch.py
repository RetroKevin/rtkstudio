"""Patch the GOG 1.00.6 RtK.exe so it loads rtkframe.dll at startup.

The original file is kept as RtK.exe.original. The stub jumps to the
unpatched entry point 0x00577e80, so this only matches that image.
"""

from __future__ import annotations

import shutil
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUB_PATH = HERE / "stub.bin"
DLL_PATH = HERE / "rtkframe.dll"

ORIG_ENTRY = 0x177E80
SECTION_NAME = b".frame\0\0"
FILE_ALIGN = 0x200
SECT_ALIGN = 0x1000


def _align(value: int, boundary: int) -> int:
    return (value + boundary - 1) & ~(boundary - 1)


def _pe(blob: bytes):
    if blob[:2] != b"MZ":
        raise RuntimeError("not a PE file")
    e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
    if blob[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        raise RuntimeError("not a PE file")
    coff = e_lfanew + 4
    nsec = struct.unpack_from("<H", blob, coff + 2)[0]
    opt_size = struct.unpack_from("<H", blob, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", blob, opt)[0]
    if magic != 0x10B:
        raise RuntimeError("RtK.exe is not a 32-bit PE")
    entry = struct.unpack_from("<I", blob, opt + 16)[0]
    image_base = struct.unpack_from("<I", blob, opt + 28)[0]
    sect_align = struct.unpack_from("<I", blob, opt + 32)[0]
    file_align = struct.unpack_from("<I", blob, opt + 36)[0]
    size_image = struct.unpack_from("<I", blob, opt + 56)[0]
    size_headers = struct.unpack_from("<I", blob, opt + 60)[0]
    sec = opt + opt_size
    sections = []
    for i in range(nsec):
        o = sec + i * 40
        name = blob[o:o + 8]
        vsz, va, rsz, raw = struct.unpack_from("<IIII", blob, o + 8)
        sections.append((name, vsz, va, rsz, raw, o))
    return {
        "e_lfanew": e_lfanew,
        "coff": coff,
        "opt": opt,
        "nsec": nsec,
        "entry": entry,
        "image_base": image_base,
        "sect_align": sect_align,
        "file_align": file_align,
        "size_image": size_image,
        "size_headers": size_headers,
        "sec": sec,
        "sections": sections,
    }


def apply(exe: Path) -> str:
    """Patch ``exe`` and copy rtkframe.dll beside it. Returns a short status."""
    exe = Path(exe)
    if not exe.is_file():
        raise FileNotFoundError(exe)
    if not STUB_PATH.is_file() or not DLL_PATH.is_file():
        raise FileNotFoundError("stub.bin and rtkframe.dll must sit beside the patcher")
    stub = STUB_PATH.read_bytes()
    blob = bytearray(exe.read_bytes())
    info = _pe(blob)
    if info["image_base"] != 0x400000:
        raise RuntimeError("unexpected image base")
    if any(name.startswith(b".frame") for name, *_ in info["sections"]):
        _install_dll(exe)
        return "already patched"
    if info["entry"] != ORIG_ENTRY or info["nsec"] != 4:
        raise RuntimeError(
            "this RtK.exe is not the GOG 1.00.6 image the frame stub jumps into")
    if info["sect_align"] != SECT_ALIGN or info["file_align"] != FILE_ALIGN:
        raise RuntimeError("unexpected section alignment")
    header_end = info["sec"] + (info["nsec"] + 1) * 40
    if header_end > info["size_headers"]:
        raise RuntimeError("PE header has no room for another section")

    _, vsz, va, _, _, _ = info["sections"][-1]
    new_rva = _align(va + vsz, SECT_ALIGN)
    raw_ptr = _align(len(blob), FILE_ALIGN)
    raw_size = _align(len(stub), FILE_ALIGN)
    new_image = _align(new_rva + len(stub), SECT_ALIGN)

    backup = exe.with_name(exe.name + ".original")
    if not backup.exists():
        backup.write_bytes(blob)

    if raw_ptr > len(blob):
        blob.extend(b"\0" * (raw_ptr - len(blob)))
    blob.extend(stub)
    blob.extend(b"\0" * (raw_size - len(stub)))

    hdr = info["sec"] + info["nsec"] * 40
    blob[hdr:hdr + 8] = SECTION_NAME
    struct.pack_into("<IIIIIIHHI", blob, hdr + 8,
                     len(stub), new_rva, raw_size, raw_ptr, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<H", blob, info["coff"] + 2, info["nsec"] + 1)
    struct.pack_into("<I", blob, info["opt"] + 16, new_rva)
    struct.pack_into("<I", blob, info["opt"] + 56, new_image)
    struct.pack_into("<I", blob, info["opt"] + 64, 0)

    exe.write_bytes(blob)
    _install_dll(exe)
    return "patched %s (original kept as %s)" % (exe.name, backup.name)


def _install_dll(exe: Path) -> None:
    dest = exe.parent / "rtkframe.dll"
    if not dest.exists() or dest.read_bytes() != DLL_PATH.read_bytes():
        shutil.copyfile(DLL_PATH, dest)


def restore(exe: Path) -> str:
    exe = Path(exe)
    backup = exe.with_name(exe.name + ".original")
    if not backup.is_file():
        raise FileNotFoundError(backup)
    shutil.copyfile(backup, exe)
    dll = exe.parent / "rtkframe.dll"
    if dll.is_file():
        dll.unlink()
    return "restored %s from %s" % (exe.name, backup.name)
