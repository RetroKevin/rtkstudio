"""Validate tools/rtkbex.py against every .bex in the extracted asset tree.

Checks that are structural proofs rather than plausibility arguments:

  * the entry walk consumes the file exactly -- no leftover bytes, no overrun
  * every payload size equals FUN_0042cc3d's runtime size for that type
    (or is shorter, which the loader explicitly tolerates by zero-filling)
  * every id in the activate/deactivate lists resolves to an entry id
  * the runtime-only field slots (FUN_0042d433 overwrites them) are zero
  * send_event / on_event payloads carry the message ids the engine tests for
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rtkbex import (FX_DAG, MSG_ON_EVENT, MSG_SEND_EVENT,  # noqa: E402
                    RUNTIME_PAYLOAD_SIZE, SELECTOR, FxInfo)

ROOT = Path(__file__).resolve().parents[1]


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else ROOT / "out" / "t3d"
    files = sorted(root.glob("**/*.bex"))

    parsed = 0
    empty = 0
    errors = []
    exact = 0
    entries = 0
    types = Counter()
    payload_exact = 0
    payload_short = Counter()
    payload_over = []
    refs_ok = 0
    refs_bad = []
    zero_slots = Counter()
    hdr_other = Counter()
    active_per_file = Counter()
    msg_ok = Counter()
    dag_seen = Counter()
    sel_seen = Counter()
    unknown_dag = Counter()
    unknown_sel = Counter()
    fx_refs = Counter()
    sprite_refs = Counter()
    name_by_type = defaultdict(Counter)

    for f in files:
        if f.stat().st_size == 0:
            empty += 1
            continue
        try:
            fx = FxInfo(f)
        except Exception as exc:  # noqa: BLE001
            errors.append((f.name, repr(exc)))
            continue
        parsed += 1
        if fx.end_offset == len(fx.raw):
            exact += 1
        hdr_other[tuple(i for i in (0, 2, 3, 4, 5, 6, 7)
                        if fx.header[i] != 0)] += 1
        ids = {e.id for e in fx.entries}
        active_per_file[len(fx.roots())] += 1
        for e in fx.entries:
            entries += 1
            types[e.type] += 1
            want = RUNTIME_PAYLOAD_SIZE.get(e.type)
            if want is None:
                payload_over.append((f.name, e.type, e.payload_size))
            elif e.payload_size == want:
                payload_exact += 1
            elif e.payload_size < want:
                payload_short[(e.type, want - e.payload_size)] += 1
            else:
                payload_over.append((f.name, e.type, e.payload_size))
            bad = [v for v in e.activate + e.deactivate if v not in ids]
            if bad:
                refs_bad.append((f.name, e.id, bad))
            else:
                refs_ok += 1
            zero_slots[tuple(i for i in (4, 5, 7, 8, 9, 10, 11)
                             if e.fields[i] != 0)] += 1
            name_by_type[e.type][e.name] += 1
            p = e.params()
            if e.type == 13:
                msg_ok[("send_event", p["message"] == MSG_SEND_EVENT)] += 1
            if e.type == 14:
                msg_ok[("on_event", p["message"] == MSG_ON_EVENT)] += 1
            if "dag" in p:
                dag_seen[p["dag"]] += 1
                if p["dag"] not in FX_DAG:
                    unknown_dag[p["dag"]] += 1
            if "selector" in p:
                sel_seen[p["selector"]] += 1
                if p["selector"] not in SELECTOR:
                    unknown_sel[p["selector"]] += 1
            if e.type == 5:
                fx_refs[p["fx_file"].lower()] += 1
            if e.type == 9:
                sprite_refs[p["sprite"]] += 1

    # Which payload dwords are ever non-zero, per type.  The loader's
    # handlers only read a handful of offsets; everything else should be a
    # runtime slot, and runtime slots must be zero on disk.
    nonzero = defaultdict(set)
    for f in files:
        if f.stat().st_size == 0:
            continue
        try:
            fx = FxInfo(f)
        except Exception:  # noqa: BLE001
            continue
        for e in fx:
            p = e.runtime_payload()
            for w in range(len(p) // 4):
                if p[w * 4:w * 4 + 4] != b"\x00\x00\x00\x00":
                    nonzero[e.type].add(w * 4)

    stems = {f.stem.lower() for f in files}
    resolved = sum(n for k, n in fx_refs.items()
                   if k.rsplit(".", 1)[0] in stems)

    print("root               :", root)
    print("files              :", len(files))
    print("empty (skipped)    :", empty)
    print("parsed ok          :", parsed)
    print("parse errors       :", len(errors))
    for e in errors[:10]:
        print("   ", e)
    print("walk ends exactly  : %d/%d" % (exact, parsed))
    print("entries            :", entries)
    print("types              :", dict(sorted(types.items())))
    print("payload == cc3d sz : %d/%d" % (payload_exact, entries))
    print("payload short by   :", dict(payload_short))
    print("payload oversize   :", payload_over[:10])
    print("id lists resolve   : %d/%d" % (refs_ok, entries))
    print("  unresolved       :", refs_bad[:10])
    print("non-zero runtime slots:", dict(zero_slots))
    print("non-zero hdr slots :", dict(hdr_other))
    print("active entries/file:", dict(sorted(active_per_file.items())))
    print("event msg ids      :", dict(msg_ok))
    print("FX_DAG codes used  :",
          {FX_DAG.get(k, k): v for k, v in sorted(dag_seen.items())})
    print("unknown FX_DAG     :", dict(unknown_dag))
    print("selectors used     :",
          {SELECTOR.get(k, hex(k)): v for k, v in sorted(sel_seen.items())})
    print("unknown selectors  :", dict(unknown_sel))
    print("spawn_fx refs      : %d distinct, %d/%d resolve to a shipped .bex"
          % (len(fx_refs), resolved, sum(fx_refs.values())))
    print("set_sprite names   : %d distinct, top %s"
          % (len(sprite_refs), sprite_refs.most_common(6)))
    print("named entries      :",
          {t: sum(n for k, n in c.items() if k) for t, c in
           sorted(name_by_type.items())})
    print("payload dwords ever non-zero, by type:")
    for t in sorted(nonzero):
        print("   type %2d size %#-5x %s"
              % (t, RUNTIME_PAYLOAD_SIZE[t],
                 ["%#x" % o for o in sorted(nonzero[t])]))
    return 1 if errors or refs_bad or payload_over or exact != parsed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
