"""A single index over every asset in the game, whatever container it lives in.

Three sources are flattened into one address space so the viewer and the mod
builder can refer to anything by one string:

    res/0088_bHaldmap_          a resource in RTKRES.bin / RTKRES.000
    t3d/C0.t3d/000101cm.di_     a member of a .t3d FastFile archive
    file/Worlds/rtkworld.wlx    a loose file in the install

Enumerating means opening 144 archives and the resource index, so the result
is cached as JSON. The game install is only ever read.
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtkres
import rtkt3d

# Extensions that are loose game data worth indexing. Installer leftovers
# (.dat, .zip, .info, .lnk, .log, .inf) and Windows packaging are skipped.
LOOSE_EXTS = {
    ".trk", ".trx", ".trm", ".wav", ".avi", ".def", ".tbl", ".rtk",
    ".mab", ".wlx", ".ldx", ".bmp", ".dib", ".txt", ".h",
}

SKIP_DIRS = {"_decomp"}

# How each asset is previewed and whether an encoder exists for it.
KIND_BY_EXT = {
    ".di_": "image", ".bmp": "image", ".dib": "image", ".kgi": "image",
    ".ovx": "depth",
    ".trk": "anim", ".trx": "text", ".trm": "text",
    ".adf": "rig", ".spx": "rig", ".grx": "rig",
    ".ktx": "text", ".mab": "text", ".txt": "text", ".h": "text",
    ".def": "script", ".tbl": "script", ".rtk": "script",
    ".bex": "fx",
    ".wlx": "world", ".ldx": "world",
    ".wav": "audio", ".avi": "video",
}

# RTKRES "TEXT" and "SCRIPT" are not text. TEXT is a fixed 44-byte interface
# widget record (all 352 of them) and SCRIPT an 8-byte pair; none of the 391
# is printable. They belong to the same interface system as the sprite types,
# so they get their own kind rather than being offered a text editor.
KIND_BY_RESTYPE = {
    "BITMAP": "image", "PALETTE": "palette", "TEXT": "widget",
    "SCRIPT": "widget", "SPRITE": "sprite", "CEL": "sprite",
    "GROUP": "sprite", "QUEUE": "sprite",
}


class Asset:
    """One addressable thing, plus enough metadata to list and filter it."""

    __slots__ = ("key", "name", "kind", "source", "container", "member",
                 "size", "restype")

    def __init__(self, key, name, kind, source, container, member, size,
                 restype=None):
        self.key = key
        self.name = name
        self.kind = kind
        self.source = source          # "res" | "t3d" | "file"
        self.container = container    # archive path, or "" for loose files
        self.member = member          # member name / resource id / rel path
        self.size = size
        self.restype = restype

    def as_dict(self):
        d = {s: getattr(self, s) for s in self.__slots__}
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, d):
        return cls(d["key"], d["name"], d["kind"], d["source"],
                   d["container"], d["member"], d["size"], d.get("restype"))

    def __repr__(self):
        return "<Asset %s %s %d bytes>" % (self.key, self.kind, self.size)


class AssetDB:
    """The index. Build once, then query."""

    def __init__(self, game: Path, assets=None):
        # Resolve immediately. The cache records this path and compares it on
        # load, so "..", "../", and the absolute path have to agree or every
        # run rebuilds and rewrites the cache in its own spelling. It also
        # means a loose asset still reads correctly from another directory.
        self.game = Path(game).resolve()
        self.assets = assets or []
        self._by_key = {a.key: a for a in self.assets}
        self._res = None
        self._archives = {}

    # ---- building -------------------------------------------------------

    @classmethod
    def build(cls, game: Path, progress=None):
        game = Path(game).resolve()
        files = cls._walk(game)
        if progress:
            progress("files on disk", len(files))
        assets = []
        assets += cls._scan_resources(game, progress)
        assets += cls._scan_archives(game, progress, files)
        assets += cls._scan_loose(game, progress, files)
        return cls(game, assets)

    @staticmethod
    def _scan_resources(game, progress):
        index = game / "RTKRES.bin"
        if not index.exists():
            return []
        res = rtkres.ResFile(index)
        names = {}
        header = game / "RTKRES.h"
        if header.exists():
            names = rtkres.load_names(header)
        out = []
        for e in res.entries:
            label = names[e.id][0] if e.id in names else "res%05d" % e.id
            typename = rtkres.TYPE_CODES.get(e.type_code, "TYPE%d" % e.type_code)
            out.append(Asset(
                key="res/%05d_%s" % (e.id, label),
                name=label,
                kind=KIND_BY_RESTYPE.get(typename, "binary"),
                source="res",
                container="RTKRES.bin",
                member=str(e.id),
                size=e.size,
                restype=typename,
            ))
        res.close()
        if progress:
            progress("resources", len(out))
        return out

    @staticmethod
    def _walk(game):
        """Every file in the install, skipping SKIP_DIRS as we go.

        Pruning matters: this repo lives inside the install and `out/` holds
        tens of thousands of derived files, including whole rebuilt copies of
        the game. Filtering after an rglob still pays to stat all of them.
        """
        found = []
        for dirpath, dirnames, filenames in os.walk(game):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            base = Path(dirpath)
            found.extend(base / f for f in filenames)
        return sorted(found)

    @staticmethod
    def _scan_archives(game, progress, files=None):
        out = []
        files = AssetDB._walk(game) if files is None else files
        for path in [p for p in files if p.suffix.lower() == ".t3d"]:
            try:
                arc = rtkt3d.open_archive(path)
            except Exception:
                continue
            rel = path.relative_to(game).as_posix()
            for entry in arc:
                ext = Path(entry.name).suffix.lower()
                if not ext and entry.name.startswith("."):
                    # Bex.t3d holds a member named ".bex" -- an empty stem, so
                    # pathlib reads it as a dotfile with no suffix.
                    ext = entry.name.lower()
                out.append(Asset(
                    key="t3d/%s/%s" % (rel, entry.name),
                    name=entry.name,
                    kind=KIND_BY_EXT.get(ext, "binary"),
                    source="t3d",
                    container=rel,
                    member=entry.name,
                    size=entry.size,
                ))
        if progress:
            progress("archive members", len(out))
        return out

    @staticmethod
    def _scan_loose(game, progress, files=None):
        out = []
        files = AssetDB._walk(game) if files is None else files
        for path in files:
            ext = path.suffix.lower()
            if ext not in LOOSE_EXTS:
                continue
            rel = path.relative_to(game).as_posix()
            out.append(Asset(
                key="file/%s" % rel,
                name=path.name,
                kind=KIND_BY_EXT.get(ext, "binary"),
                source="file",
                container="",
                member=rel,
                size=path.stat().st_size,
            ))
        if progress:
            progress("loose files", len(out))
        return out

    # ---- persistence ----------------------------------------------------

    def save(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "game": str(self.game),
            "assets": [a.as_dict() for a in self.assets],
        }), encoding="utf-8")

    @classmethod
    def load(cls, path: Path):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(Path(doc["game"]),
                   [Asset.from_dict(d) for d in doc["assets"]])

    @classmethod
    def open(cls, game: Path, cache: Path, rebuild=False, progress=None):
        """Load the cached index, rebuilding when missing or stale."""
        cache = Path(cache)
        if not rebuild and cache.exists():
            try:
                db = cls.load(cache)
                if Path(db.game) == Path(game).resolve():
                    return db
            except Exception:
                pass
        db = cls.build(game, progress)
        db.save(cache)
        return db

    # ---- querying -------------------------------------------------------

    def get(self, key):
        return self._by_key.get(key)

    def search(self, text="", kind=None, source=None, limit=None):
        text = text.lower()
        hits = []
        for a in self.assets:
            if text and text not in a.key.lower():
                continue
            if kind and a.kind != kind:
                continue
            if source and a.source != source:
                continue
            hits.append(a)
            if limit and len(hits) >= limit:
                break
        return hits

    def counts(self):
        return {
            "total": len(self.assets),
            "by_kind": dict(Counter(a.kind for a in self.assets).most_common()),
            "by_source": dict(Counter(a.source for a in self.assets).most_common()),
        }

    # ---- reading --------------------------------------------------------

    def read(self, key) -> bytes:
        """Raw bytes of one asset, straight out of its container."""
        a = self.get(key)
        if a is None:
            raise KeyError(key)
        if a.source == "file":
            return (self.game / a.member).read_bytes()
        if a.source == "t3d":
            arc = self._archives.get(a.container)
            if arc is None:
                arc = rtkt3d.open_archive(self.game / a.container)
                self._archives[a.container] = arc
            for entry in arc:
                if entry.name == a.member:
                    return arc.read(entry)
            raise KeyError("%s not in %s" % (a.member, a.container))
        if self._res is None:
            self._res = rtkres.ResFile(self.game / "RTKRES.bin")
        for e in self._res.entries:
            if str(e.id) == a.member:
                return self._res.read_raw(e)
        raise KeyError(key)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, type=Path)
    ap.add_argument("--cache", type=Path, default=Path("out/assetdb.json"))
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--search", default="")
    ap.add_argument("--kind")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args(argv)

    def note(what, n):
        print("  indexed %-18s %d" % (what, n))

    db = AssetDB.open(args.game, args.cache, args.rebuild, note)
    c = db.counts()
    print("total assets : %d" % c["total"])
    print("by source    : %s" % c["by_source"])
    print("by kind      : %s" % c["by_kind"])
    if args.search or args.kind:
        hits = db.search(args.search, args.kind, limit=args.limit)
        print("\nmatches (first %d):" % args.limit)
        for a in hits:
            print("  %-52s %-8s %9d" % (a.key, a.kind, a.size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
