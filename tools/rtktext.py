"""Reader for Return to Krondor .ktx files -- the in-game narration/text cues.

A .ktx is plain 8-bit text with no header and no container.  Everything below
comes from the engine's own loader and viewers:

    FUN_004ff07c   out/decompiled/RtK.c:167196  the loader.  Opens `Ktx.t3d`
                   (or `C<n>.t3d` for the chapter variant), reads
                   t3dFastFileGetEOF() bytes straight into a std::string,
                   then walks every byte and overwrites any byte > 0x7f with
                   0x20 via FUN_0058c2c4 (`str[i] = ch`, RtK.c:264002).
                   On failure: "Failed to load text file: %s".
    FUN_00428112   out/decompiled/RtK.c:25990   the document/book viewer.
                   Splits the loaded text on the literal "\\p" (the string
                   constant at 0x005d0288 in RtK.exe) into pages.
    FUN_0042800a   out/decompiled/RtK.c:25947   splits a page on "\\s"
                   (0x005d0284) into a heading and a body.
    FUN_0054d7c1   out/decompiled/RtK.c:214124  the chapter-page builder;
                   splits on "\\s" (0x00612a88) and "\\o" (0x00612a8c).
    FUN_0054da94   out/decompiled/RtK.c:214231  reads the text between "\\w"
                   (0x00612a94) and ":" (0x00612a90) and runs it through
                   atoi (FUN_005753c0); the result is the page's dwell time,
                   defaulting to the caller's value (10000 for the chapter
                   pages after the first).
    FUN_004eb090   out/decompiled/RtK.c:154011  the text-box alignment:
                   "\\l" / "\\c" / "\\r" (0x005f8484 / 0x5f8488 / 0x5f848c)
                   set the alignment field to 1 / 2 / 3, default 1.

Line numbers are against out/decompiled/ as regenerated 2026-10-05; the
"// ===== FUN_004ff07c @ 004ff07c =====" banner is the stable anchor, and
tools/_lines.py re-derives any citation.

See docs/misc-formats.md.
"""

import re
from pathlib import Path

PAGE_BREAK = "\\p"
HEADING_SPLIT = "\\s"
EXTRA_SPLIT = "\\o"
DWELL_RE = re.compile(r"\\w([^:]*):")

ALIGN = {"\\l": "left", "\\c": "center", "\\r": "right"}
ALIGN_DEFAULT = "left"
DWELL_DEFAULT = 10000  # FUN_0054da94's fallback for pages after the first


def normalise(raw: bytes) -> str:
    """FUN_004ff07c's own normalisation: any byte above 0x7f becomes a space.

    Nothing else is touched -- not even the CRLF pairs.  The shipped files
    contain 15 occurrences of 0x92 (cp1252 right single quote) and 3 of 0x96
    (en dash), so those characters are displayed as spaces in-game.
    """
    return bytes(0x20 if b > 0x7F else b for b in raw).decode("ascii")


def decode_cp1252(raw: bytes) -> str:
    """What the authors meant, rather than what the engine shows."""
    return raw.decode("cp1252")


class Page:
    """One `\\p`-delimited page."""

    __slots__ = ("text", "heading", "body", "extra", "dwell_ms", "align")

    def __init__(self, text):
        self.text = text
        self.align = ALIGN_DEFAULT
        for tag, name in ALIGN.items():
            if tag in text:
                self.align = name
        m = DWELL_RE.search(text)
        self.dwell_ms = None
        if m:
            digits = m.group(1).strip()
            self.dwell_ms = int(digits) if digits.lstrip("-").isdigit() \
                else DWELL_DEFAULT
        stripped = DWELL_RE.sub("", text)
        for tag in ALIGN:
            stripped = stripped.replace(tag, "")
        if HEADING_SPLIT in stripped:
            head, rest = stripped.split(HEADING_SPLIT, 1)
            self.heading = head
        else:
            head, rest = None, stripped
            self.heading = None
        if EXTRA_SPLIT in rest:
            rest, self.extra = rest.split(EXTRA_SPLIT, 1)
        else:
            self.extra = None
        self.body = rest

    @property
    def paragraphs(self):
        """Blank-line separated blocks, CRLF normalised."""
        norm = self.body.replace("\r\n", "\n")
        return [p.strip("\n") for p in re.split(r"\n{2,}", norm) if p.strip()]

    @property
    def lines(self):
        return self.body.replace("\r\n", "\n").split("\n")

    def __repr__(self):
        return "Page(%d chars, %d paragraphs, dwell=%r, align=%s)" % (
            len(self.text), len(self.paragraphs), self.dwell_ms, self.align)


class Text:
    def __init__(self, path, data=None):
        self.path = Path(path)
        self.raw = self.path.read_bytes() if data is None else data
        self.text = normalise(self.raw)
        self.authored = decode_cp1252(self.raw)
        self.pages = [Page(p) for p in self.text.split(PAGE_BREAK)]

    @property
    def plain(self):
        """All body text, markup removed, CRLF normalised."""
        out = []
        for p in self.pages:
            for part in (p.heading, p.body, p.extra):
                if part and part.strip():
                    out.append(part.replace("\r\n", "\n").strip())
        return "\n\n".join(out)

    def __repr__(self):
        return "Text(%s, %d bytes, %d pages)" % (
            self.path.name, len(self.raw), len(self.pages))


def read(path):
    return Text(path)


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        t = Text(arg)
        print(t)
        for i, p in enumerate(t.pages):
            print("  page %d: %r" % (i, p))
            for para in p.paragraphs:
                print("    | " + para.replace("\n", "\n    | "))
