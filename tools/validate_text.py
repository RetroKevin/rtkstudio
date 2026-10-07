"""Validate tools/rtktext.py over every .ktx in the extracted asset tree.

The claim being tested is narrow: a .ktx is plain text, every byte is either
printable ASCII or part of a CRLF pair or one of two cp1252 punctuation
characters, and the only in-band structure is the handful of backslash tags
the engine's viewers split on.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rtktext import ALIGN, DWELL_RE, Text, normalise  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KNOWN_TAGS = set("psowlcr")


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else ROOT / "out" / "t3d"
    files = sorted(root.glob("**/*.ktx"))

    sizes = []
    bytes_seen = Counter()
    ascii_clean = 0
    cp1252 = Counter()
    crlf_only = 0
    nul_free = 0
    tags = Counter()
    unknown_tags = Counter()
    pages = Counter()
    with_heading = 0
    with_extra = 0
    dwells = Counter()
    aligns = Counter()
    roundtrip = 0
    errors = []
    dirs = Counter()

    for f in files:
        raw = f.read_bytes()
        sizes.append(len(raw))
        bytes_seen.update(raw)
        dirs[f.parent.name] += 1
        if all(b < 0x80 for b in raw):
            ascii_clean += 1
        for b in raw:
            if b >= 0x80:
                cp1252[hex(b)] += 1
        if raw.count(b"\r\n") * 2 == raw.count(b"\r") + raw.count(b"\n"):
            crlf_only += 1
        if b"\x00" not in raw:
            nul_free += 1
        txt = normalise(raw)
        for m in re.finditer(r"\\(.)", txt, re.S):
            tags[m.group(1)] += 1
            if m.group(1) not in KNOWN_TAGS:
                unknown_tags[m.group(1)] += 1
        try:
            t = Text(f)
        except Exception as exc:  # noqa: BLE001
            errors.append((f.name, repr(exc)))
            continue
        pages[len(t.pages)] += 1
        for p in t.pages:
            if p.heading is not None:
                with_heading += 1
            if p.extra is not None:
                with_extra += 1
            dwells[p.dwell_ms] += 1
            aligns[p.align] += 1
        # Re-joining the pages on the page-break tag must give the loader's
        # own normalised text back, byte for byte.
        if "\\p".join(p.text for p in t.pages) == t.text:
            roundtrip += 1

    print("root                 :", root)
    print("files                :", len(files))
    print("directories          :", dict(dirs))
    print("sizes                : min=%d max=%d total=%d"
          % (min(sizes), max(sizes), sum(sizes)))
    print("distinct byte values :", len(bytes_seen))
    print("pure 7-bit ASCII     : %d/%d" % (ascii_clean, len(files)))
    print("bytes >= 0x80        : %s  (the loader rewrites each to 0x20)"
          % dict(cp1252))
    print("line endings CRLF    : %d/%d (no bare CR or LF anywhere)"
          % (crlf_only, len(files)))
    print("NUL-free             : %d/%d" % (nul_free, len(files)))
    print("control bytes present:",
          {hex(k): v for k, v in sorted(bytes_seen.items()) if k < 0x20})
    print("backslash tags       :", dict(tags))
    print("unrecognised tags    :", dict(unknown_tags))
    print("pages per file       :", dict(sorted(pages.items())))
    print("pages with a heading : %d" % with_heading)
    print("pages with an \\o part: %d" % with_extra)
    print("dwell values         :", dict(dwells))
    print("alignments           :", dict(aligns))
    print("page rejoin exact    : %d/%d" % (roundtrip, len(files)))
    print("parse errors         :", errors)
    print()
    print("known tags           :", sorted(KNOWN_TAGS),
          "(align subset %s)" % sorted(k[1] for k in ALIGN))
    print("dwell pattern        :", DWELL_RE.pattern)
    return 1 if errors or unknown_tags else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
