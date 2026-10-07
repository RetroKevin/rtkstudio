"""A mod project: an override layer over the game, plus a builder.

A project is a directory you can keep in version control and hand to someone
else. It holds only what you changed:

    mods/example/
        mod.json             name, version, description
        overrides.json        asset key -> override file, with provenance
        overrides/*.bin       the replacement asset, already in game format

Nothing here touches the install. `build()` writes a complete, playable copy
of the game somewhere else with the overrides folded in, and `export_patch()`
zips the project alone so it can be distributed and applied to someone else's
own copy.
"""

import copy
import hashlib
import json
import re
import shutil
import sys
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import encoders

SKIP_DIRS = {"_decomp"}
SAFE = re.compile(r"[^A-Za-z0-9._-]+")
HISTORY_CAP = 50


def _slug(key: str) -> str:
    """A filesystem-safe name for an asset key, kept readable and unique."""
    stem = SAFE.sub("_", key).strip("_")[:80]
    return "%s-%s" % (stem, hashlib.sha1(key.encode("utf-8")).hexdigest()[:8])


def _check_output(out: Path, game: Path):
    """Guard the one thing that must never happen: writing over the install.

    The repo itself lives inside the install directory, so "under the game"
    is not the test. What matters is whether the build could land on a file
    the copy walk would also visit, and that walk skips SKIP_DIRS.
    """
    if out == game or out in game.parents:
        raise ValueError("refusing to build over the game install at %s" % game)
    if game in out.parents and not (SKIP_DIRS & set(out.relative_to(game).parts)):
        raise ValueError(
            "build output %s is inside the game install; put it under %s/"
            % (out, "/".join(sorted(SKIP_DIRS))))


class ModProject:
    def __init__(self, root: Path, name=None):
        self.root = Path(root)
        self.overrides_dir = self.root / "overrides"
        self.overrides_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.root / "mod.json"
        self.index_path = self.root / "overrides.json"
        if not self.meta_path.exists():
            self.meta = {"name": name or self.root.name, "version": "0.1.0",
                         "description": "", "created": time.strftime("%Y-%m-%d")}
            self._save_meta()
        else:
            self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.index = (json.loads(self.index_path.read_text(encoding="utf-8"))
                      if self.index_path.exists() else {})
        self.history_dir = self.root / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.root / "history.json"
        self._txn = None
        self._restoring = False
        self._cursor = -1
        self._entries = []
        self._load_history()

    def _save_meta(self):
        self.meta_path.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")

    def _save_index(self):
        self.index_path.write_text(json.dumps(self.index, indent=2, sort_keys=True),
                                   encoding="utf-8")

    def describe(self):
        kits = 0
        kdir = self.root / "kits"
        if kdir.is_dir():
            kits = len(list(kdir.glob("*.json")))
        items = 0
        idir = self.root / "items"
        if idir.is_dir():
            items = len(list(idir.glob("*.json")))
        return dict(self.meta, root=str(self.root), overrides=len(self.index),
                    kits=kits, items=items,
                    undo=self.can_undo(), redo=self.can_redo(),
                    history=len(self._entries))

    def _kit_path(self, char_name):
        safe = SAFE.sub("_", char_name).strip("_") or "kit"
        return self.root / "kits" / (safe + ".json")

    def read_kit(self, char_name):
        path = self._kit_path(char_name)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def write_kit(self, char_name, doc):
        path = self._kit_path(char_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return str(path)

    def _item_path(self, name):
        safe = SAFE.sub("_", name).strip("_") or "item"
        return self.root / "items" / (safe + ".json")

    def read_item(self, name):
        path = self._item_path(name)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def write_item(self, name, doc):
        path = self._item_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return str(path)

    # ---- the override layer ---------------------------------------------

    def overridden(self):
        return set(self.index)

    def can_edit(self, asset) -> bool:
        return encoders.supports(asset)

    def read_override(self, key):
        rec = self.index.get(key)
        if rec is None:
            return None
        path = self.overrides_dir / rec["file"]
        return path.read_bytes() if path.is_file() else None

    def write_override(self, asset, payload: bytes, as_text=False, original=None,
                       palette=None, label=None) -> int:
        """Encode `payload` into the asset's own format and store it.

        Outside a transaction this is one undo step. Inside one, every
        write until commit shares that step. Restoring history does not
        record another step.
        """
        encoded = encoders.encode(asset, payload, original=original,
                                  as_text=as_text, palette=palette)
        if self._restoring:
            return self._store_encoded(asset, encoded)
        before_bytes = self.read_override(asset.key)
        if before_bytes == encoded:
            return len(encoded)
        before_index = copy.deepcopy(self.index.get(asset.key))
        n = self._store_encoded(asset, encoded)
        after_index = copy.deepcopy(self.index.get(asset.key))
        auto = self._txn is None
        if auto:
            self.begin(label or asset.key)
        self._note_change(asset.key, before_bytes, before_index,
                          encoded, after_index)
        if auto:
            self.commit()
        return n

    def _store_encoded(self, asset, encoded: bytes) -> int:
        name = _slug(asset.key) + ".bin"
        (self.overrides_dir / name).write_bytes(encoded)
        self.index[asset.key] = {
            "file": name,
            "kind": asset.kind,
            "source": asset.source,
            "container": asset.container,
            "member": asset.member,
            "original_size": asset.size,
            "size": len(encoded),
            "sha1": hashlib.sha1(encoded).hexdigest(),
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save_index()
        return len(encoded)

    def clear_override(self, key, label=None):
        if key not in self.index:
            return
        if self._restoring:
            self._drop_override(key)
            return
        before_bytes = self.read_override(key)
        before_index = copy.deepcopy(self.index.get(key))
        self._drop_override(key)
        auto = self._txn is None
        if auto:
            self.begin(label or ("Revert " + key))
        self._note_change(key, before_bytes, before_index, None, None)
        if auto:
            self.commit()

    def _drop_override(self, key):
        rec = self.index.pop(key, None)
        if rec:
            path = self.overrides_dir / rec["file"]
            if path.is_file():
                path.unlink()
            self._save_index()

    # ---- undo stack ------------------------------------------------------

    def _load_history(self):
        if not self.history_path.is_file():
            return
        try:
            doc = json.loads(self.history_path.read_text(encoding="utf-8"))
        except Exception:
            return
        self._entries = list(doc.get("entries") or [])
        try:
            self._cursor = int(doc.get("cursor", -1))
        except (TypeError, ValueError):
            self._cursor = -1
        if self._cursor < -1:
            self._cursor = -1
        if self._cursor >= len(self._entries):
            self._cursor = len(self._entries) - 1

    def _save_history(self):
        doc = {"cursor": self._cursor, "entries": self._entries}
        self.history_path.write_text(
            json.dumps(doc, indent=2), encoding="utf-8")

    def _blob_put(self, data: bytes) -> str:
        digest = hashlib.sha1(data).hexdigest()
        folder = self.history_dir / "blobs"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (digest + ".bin")
        if not path.is_file():
            path.write_bytes(data)
        return digest + ".bin"

    def _blob_get(self, name):
        if not name:
            return None
        path = self.history_dir / "blobs" / name
        if not path.is_file():
            raise FileNotFoundError(name)
        return path.read_bytes()

    def begin(self, label="edit"):
        if self._txn is not None:
            return
        self._txn = {
            "label": label or "edit",
            "changes": {},
            "order": [],
        }

    def _note_change(self, key, before_bytes, before_index, after_bytes,
                     after_index):
        changes = self._txn["changes"]
        if key not in changes:
            changes[key] = {
                "key": key,
                "before": self._blob_put(before_bytes) if before_bytes is not None else None,
                "before_index": before_index,
                "after": None,
                "after_index": None,
            }
            self._txn["order"].append(key)
        rec = changes[key]
        if after_bytes is None:
            rec["after"] = None
            rec["after_index"] = None
        else:
            rec["after"] = self._blob_put(after_bytes)
            rec["after_index"] = after_index

    def commit(self):
        txn = self._txn
        self._txn = None
        if not txn or not txn["order"]:
            return None
        self._entries = self._entries[:self._cursor + 1]
        entry = {
            "id": time.strftime("%Y%m%d-%H%M%S") + "-%d" % (len(self._entries) + 1),
            "label": txn["label"],
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "changes": [txn["changes"][k] for k in txn["order"]],
        }
        self._entries.append(entry)
        self._cursor = len(self._entries) - 1
        self._trim_history()
        self._save_history()
        return entry

    def rollback(self):
        txn = self._txn
        self._txn = None
        if not txn:
            return
        for key in reversed(txn["order"]):
            ch = txn["changes"][key]
            self._restore(key, ch["before"], ch["before_index"])

    @contextmanager
    def transaction(self, label="edit"):
        """Group every override write in the block into one undo step."""
        if self._txn is not None:
            yield
            return
        self.begin(label)
        try:
            yield
        except Exception:
            self.rollback()
            raise
        else:
            self.commit()

    def _trim_history(self):
        while len(self._entries) > HISTORY_CAP:
            self._entries.pop(0)
            self._cursor -= 1
        if self._cursor < -1:
            self._cursor = -1
        if self._cursor >= len(self._entries):
            self._cursor = len(self._entries) - 1
        used = set()
        for entry in self._entries:
            for ch in entry.get("changes") or []:
                if ch.get("before"):
                    used.add(ch["before"])
                if ch.get("after"):
                    used.add(ch["after"])
        if self._txn:
            for ch in self._txn["changes"].values():
                if ch.get("before"):
                    used.add(ch["before"])
                if ch.get("after"):
                    used.add(ch["after"])
        folder = self.history_dir / "blobs"
        if folder.is_dir():
            for path in folder.glob("*.bin"):
                if path.name not in used:
                    path.unlink()

    def _restore(self, key, blob, index_rec):
        self._restoring = True
        try:
            if blob is None or index_rec is None:
                self._drop_override(key)
                return
            data = self._blob_get(blob)
            rec = copy.deepcopy(index_rec)
            path = self.overrides_dir / rec["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            rec["size"] = len(data)
            rec["sha1"] = hashlib.sha1(data).hexdigest()
            rec["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.index[key] = rec
            self._save_index()
        finally:
            self._restoring = False

    def can_undo(self):
        return self._txn is None and self._cursor >= 0

    def can_redo(self):
        return self._txn is None and self._cursor + 1 < len(self._entries)

    def undo(self):
        if self._txn is not None:
            raise RuntimeError("transaction open")
        if self._cursor < 0:
            raise ValueError("nothing to undo")
        entry = self._entries[self._cursor]
        for ch in reversed(entry["changes"]):
            self._restore(ch["key"], ch.get("before"), ch.get("before_index"))
        self._cursor -= 1
        self._save_history()
        return entry

    def redo(self):
        if self._txn is not None:
            raise RuntimeError("transaction open")
        if self._cursor + 1 >= len(self._entries):
            raise ValueError("nothing to redo")
        self._cursor += 1
        entry = self._entries[self._cursor]
        for ch in entry["changes"]:
            self._restore(ch["key"], ch.get("after"), ch.get("after_index"))
        self._save_history()
        return entry

    def jump(self, cursor):
        cursor = int(cursor)
        if cursor < -1 or cursor >= len(self._entries):
            raise ValueError("history index out of range")
        last = None
        while self._cursor > cursor:
            last = self.undo()
        while self._cursor < cursor:
            last = self.redo()
        return last

    def history_state(self):
        return {
            "cursor": self._cursor,
            "can_undo": self.can_undo(),
            "can_redo": self.can_redo(),
            "entries": [
                {
                    "i": i,
                    "label": e.get("label") or "",
                    "time": e.get("time") or "",
                    "keys": [c.get("key") or "" for c in e.get("changes") or []],
                    "current": i == self._cursor,
                }
                for i, e in enumerate(self._entries)
            ],
        }

    # ---- building --------------------------------------------------------

    def default_output(self) -> Path:
        return Path("out/builds") / self.meta.get("name", self.root.name)

    def build(self, db, out: Path) -> dict:
        """Write a complete modded copy of the game to `out`."""
        out = Path(out).resolve()
        game = Path(db.game).resolve()
        _check_output(out, game)

        # Group overrides by the container that has to be rewritten.
        res_repl, t3d_repl, loose = {}, {}, {}
        missing = []
        for key, rec in self.index.items():
            data = self.read_override(key)
            if data is None:
                missing.append(key)
                continue
            if rec["source"] == "res":
                res_repl[int(rec["member"])] = data
            elif rec["source"] == "t3d":
                t3d_repl.setdefault(rec["container"], {})[rec["member"]] = data
            else:
                loose[rec["member"]] = data

        rebuilt = set(t3d_repl)
        if res_repl:
            rebuilt |= {"RTKRES.bin", "RTKRES.000"}

        copied = skipped = 0
        for src in game.rglob("*"):
            if SKIP_DIRS & set(src.parts) or not src.is_file():
                continue
            rel = src.relative_to(game).as_posix()
            if rel in rebuilt or rel in loose:
                skipped += 1
                continue
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1

        for rel, data in loose.items():
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)

        report = {"output": str(out), "copied": copied, "regenerated": skipped,
                  "loose_written": len(loose), "containers": {},
                  "missing_overrides": missing}

        for rel, repl in t3d_repl.items():
            import rtkt3d_write
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            report["containers"][rel] = rtkt3d_write.rebuild(game / rel, dst, repl)

        if res_repl:
            import rtkres_write
            (out).mkdir(parents=True, exist_ok=True)
            report["containers"]["RTKRES"] = rtkres_write.rebuild(
                game / "RTKRES.bin", out / "RTKRES.bin", out / "RTKRES.000", res_repl)

        # The copy must look up Tracks and the other folders inside itself.
        # An ini copied from Steam still has .\Tracks\, and one copied from
        # a GOG install still has that machine's absolute paths.
        try:
            import rtkpaths
            report["directories"] = rtkpaths.apply_directories(
                out, backup=False, helper=False, force=True)
        except OSError as exc:
            report["directories"] = {"error": str(exc)}

        return report

    def export_patch(self, dst: Path) -> dict:
        """Zip the project on its own, for distribution as a patch."""
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        extras = 0
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(self.meta_path, "mod.json")
            z.write(self.index_path, "overrides.json")
            for rec in self.index.values():
                path = self.overrides_dir / rec["file"]
                if path.is_file():
                    z.write(path, "overrides/" + rec["file"])
            for folder in ("kits", "items"):
                root = self.root / folder
                if not root.is_dir():
                    continue
                for path in root.rglob("*"):
                    if path.is_file():
                        z.write(path, path.relative_to(self.root).as_posix())
                        extras += 1
        return {"patch": str(dst), "entries": len(self.index),
                "sidecar": extras, "bytes": dst.stat().st_size}

    @staticmethod
    def import_patch(zip_path: Path, root: Path) -> "ModProject":
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(root)
        return ModProject(root)


def main(argv=None) -> int:
    import argparse
    from assetdb import AssetDB

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mod", required=True, type=Path)
    ap.add_argument("--game", type=Path)
    ap.add_argument("--cache", type=Path, default=Path("out/assetdb.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path)
    p = sub.add_parser("patch")
    p.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    mod = ModProject(args.mod)
    if args.cmd == "status":
        print(json.dumps(mod.describe(), indent=2))
        for key, rec in sorted(mod.index.items()):
            print("  %-50s %8d -> %8d" % (key, rec["original_size"], rec["size"]))
        return 0
    if args.cmd == "patch":
        out = args.out or (mod.root.parent / (mod.meta["name"] + ".rtkmod.zip"))
        print(json.dumps(mod.export_patch(out), indent=2))
        return 0

    if not args.game:
        ap.error("build needs --game")
    db = AssetDB.open(args.game, args.cache)
    print(json.dumps(mod.build(db, args.out or mod.default_output()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
