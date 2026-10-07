"""Validation sweep for the T3D hierarchical sprite / joint hierarchy.

Checks, in order:

  1. container parse over every .adf / .spx / .grx
  2. chunk-type census, and which types carry a 0x10
  3. byte-exact re-serialisation of every 0x10 and 0x11 payload
  4. structural checks: single root at dag 0, every child index in range,
     every dag exactly one parent, every dag reachable from dag 0
  5. tag consistency: dag tag prefix+joint+_TRACK == the referenced track's
     own tag (two independently stored name sets)
  6. GameData/Models.def names an HS_DEF tag per character model; every one
     of those must resolve to a definition we parsed
  7. every joint name in every .trk must resolve to a dag in some rig
  8. consensus: where several rigs cover a .trk's joint set, do they induce
     the same sub-tree?

Run:  python tools/validate_sprites.py
"""

import gzip
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtkspx
import rtktrack

ROOT = Path(__file__).resolve().parent.parent
T3D = ROOT / "out" / "t3d"
INSTALL = ROOT.parent


# ---------------------------------------------------------------- re-serialise
def reserialise_hspritedef(d):
    """Rebuild a 0x10 payload from the parsed fields only."""
    out = struct.pack("<4i", d._tagref, d.flags, len(d.dags), d.volume_ref)
    if d.flags & rtkspx.HSPRITE_FLAG_HAS_OFFSET:
        out += struct.pack("<3f", *d.center_offset)
    if d.flags & rtkspx.HSPRITE_FLAG_HAS_RADIUS:
        out += struct.pack("<f", d.bounding_radius)
    for dag in d.dags:
        out += struct.pack("<5i", dag._nameref, dag.unk, dag.track_ref,
                           dag.sprite_ref, len(dag.children))
        out += struct.pack(f"<{len(dag.children)}i", *dag.children)
    return out


# ------------------------------------------------------------------- induced
def induced_tree(rig, joints):
    """{joint -> nearest ancestor inside `joints`, or None}."""
    idx = rig.joints()
    keep = {idx[j] for j in joints}
    out = {}
    for j in joints:
        p = rig.dags[idx[j]].parent
        while p is not None and p not in keep:
            p = rig.dags[p].parent
        out[j] = rig.dags[p].joint.upper() if p is not None else None
    return out


def models_def_tags():
    """HS_DEF tags named by GameData/Models.def.

    The file is a 26-byte PyroTechnix banner followed by a gzip stream.
    """
    p = INSTALL / "GameData" / "Models.def"
    if not p.exists():
        return {}
    raw = p.read_bytes()
    text = gzip.decompress(raw[raw.find(b"\x1f\x8b\x08"):]).decode("latin-1")
    out = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        fields = [f.strip() for f in rest.split(",")]
        if len(fields) >= 3 and fields[0].lower().endswith(".adf"):
            out[name.strip()] = (fields[0], fields[2])
    return out


def main():
    print("== 1/2. container parse and chunk census")
    files = {ext: sorted(T3D.rglob("*." + ext)) for ext in ("adf", "spx", "grx")}
    census = {}
    parsed = {}
    for ext, fs in files.items():
        types = Counter()
        ok = errs = 0
        tails = Counter()
        withdef = 0
        for f in fs:
            try:
                sf = rtkspx.SpriteFile(f)
            except Exception as e:
                errs += 1
                print(f"   ERROR {f.name}: {e}")
                continue
            ok += 1
            parsed[f] = sf
            types.update(c[2] for c in sf.chunks)
            tails[sf.terminator.hex()] += 1
            if sf.hsprite_defs:
                withdef += 1
        census[ext] = types
        print(f"   .{ext:3} {len(fs):4} files  parsed {ok:4}  errors {errs}  "
              f"files with a 0x10 chunk: {withdef}")
        print(f"        terminator: {dict(tails)}")
        print(f"        chunk types: "
              f"{ {hex(k): v for k, v in sorted(types.items())} }")

    defs_total = sum(len(sf.hsprite_defs) for sf in parsed.values())
    inst_total = sum(len(sf.hsprites) for sf in parsed.values())
    print(f"   0x10 chunks: {defs_total}   0x11 chunks: {inst_total}")

    print("\n== 3. byte-exact re-serialisation of 0x10 / 0x11 payloads")
    exact = diff = 0
    for f, sf in parsed.items():
        for off, size, ctype in sf.chunks:
            if ctype == rtkspx.CHUNK_HSPRITEDEF:
                orig = sf.raw[off + 8:off + 8 + size]
                d = sf._def_at[off]
                if reserialise_hspritedef(d) == orig:
                    exact += 1
                else:
                    diff += 1
                    print(f"   DIFF {f.name} 0x10 @{off}")
            elif ctype == rtkspx.CHUNK_HSPRITE:
                orig = sf.raw[off + 8:off + 8 + size]
                h = sf._inst_at[off]
                rebuilt = struct.pack("<3i", h._tagref, h.def_ref, h.unk)
                if rebuilt == orig:
                    exact += 1
                else:
                    diff += 1
                    print(f"   DIFF {f.name} 0x11 @{off} size={size}")
    print(f"   byte-exact: {exact}   mismatched: {diff}")

    # unique rigs
    rigs = {}
    dupes = 0
    for f in sorted(parsed):
        for d in parsed[f].hsprite_defs:
            if d.name in rigs:
                dupes += 1
            else:
                rigs[d.name] = d
    print(f"\n   unique definitions by tag: {len(rigs)} "
          f"(+{dupes} duplicate copies across archives)")

    print("\n== 4. structural checks")
    clean = 0
    problems = []
    ndag = Counter()
    nsub = Counter()
    unk = Counter()
    flags = Counter()
    for t, d in sorted(rigs.items()):
        p = d.check()
        if p:
            problems.append((t, p))
        else:
            clean += 1
        ndag[len(d.dags)] += 1
        flags[d.flags] += 1
        for dag in d.dags:
            nsub[len(dag.children)] += 1
            unk[dag.unk] += 1
    print(f"   single-rooted acyclic tree, root == dag 0 : {clean}/{len(rigs)}")
    for t, p in problems:
        print(f"   PROBLEM {t}: {p}")
    print(f"   total dags: {sum(unk.values())}")
    print(f"   definition flags       : {dict(flags)}")
    print(f"   dag word @+0x04        : {dict(unk)}")
    print(f"   children-per-dag hist  : {dict(sorted(nsub.items()))}")
    print(f"   dags-per-definition    : {dict(sorted(ndag.items()))}")

    print("\n== 5. tag consistency (dag tag vs the track tag it points at)")
    agree = disagree = 0
    for t, d in sorted(rigs.items()):
        a, b, offenders = d.tag_consistency()
        agree += a
        disagree += b
        if b:
            print(f"   {t}: {b} dag(s) disagree -> {offenders}")
    print(f"   dag tag with _DAG->_TRACK == referenced track's own tag: "
          f"{agree}/{agree + disagree}")
    print(f"   derived tag prefix length hist: "
          f"{dict(Counter(len(d.prefix) for d in rigs.values()))}")

    print("\n== 6. GameData/Models.def cross-check")
    md = models_def_tags()
    hit = miss = nonhier = 0
    missing = []
    for name, (adf, tag) in sorted(md.items()):
        tag_u = tag.upper()
        if tag_u in rigs or tag_u + "_HS_DEF" in rigs:
            hit += 1
        elif tag_u.endswith("_3DSPRITEDEF") or tag_u == "NULLSPRITE":
            nonhier += 1
        else:
            miss += 1
            if len(missing) < 10:
                missing.append((name, adf, tag))
    print(f"   model entries: {len(md)}")
    print(f"   entries naming an _HS_DEF tag, resolved : {hit}")
    print(f"   entries naming a non-hierarchical sprite: {nonhier} "
          f"(_3DSPRITEDEF / NULLSPRITE -- static props, no rig)")
    print(f"   entries naming an _HS_DEF we did NOT find: {miss} {missing}")

    print("\n== 7/8. .trk joint resolution and rig consensus")
    jointsets = {t: set(d.joints()) for t, d in rigs.items()}
    groups = [("loose Tracks/", sorted((INSTALL / "Tracks").glob("*.trk"))),
              ("archived .t3d", sorted(T3D.rglob("*.trk")))]
    for label, fs in groups:
        covered = uncovered = 0
        unanim = split = 0
        ncand = Counter()
        unresolved_joints = Counter()
        dissent = Counter()
        cache = {}
        for p in fs:
            try:
                tk = rtktrack.Track(p)
            except Exception:
                continue
            joints = set(rtkspx.track_joints(tk))
            if not joints:
                continue
            key = frozenset(joints)
            if key not in cache:
                cands = sorted(t for t, s in jointsets.items() if joints <= s)
                if cands:
                    maps = {t: induced_tree(rigs[t], joints) for t in cands}
                    base = defaultdict(list)
                    for t in cands:
                        base[tuple(sorted(maps[t].items()))].append(t)
                    cache[key] = (cands, base, maps)
                else:
                    best = max(jointsets, key=lambda t: len(joints & jointsets[t]))
                    cache[key] = (None, joints - jointsets[best], None)
            cands, info, _ = cache[key]
            if cands is None:
                uncovered += 1
                for j in info:
                    unresolved_joints[j] += 1
                continue
            covered += 1
            ncand[len(cands)] += 1
            if len(info) == 1:
                unanim += 1
            else:
                split += 1
                variants = sorted(info.values(), key=len, reverse=True)
                dissent[(len(cands), len(variants[0]),
                         tuple(t for g in variants[1:] for t in g))] += 1
        print(f"   {label}: {len(fs)} files")
        print(f"      every joint resolves to a dag : {covered}")
        print(f"      some joint in no rig          : {uncovered}")
        if unresolved_joints:
            print(f"      unresolved joint names        : "
                  f"{unresolved_joints.most_common(10)}")
        print(f"      covering-rig count hist       : {dict(sorted(ncand.items()))}")
        print(f"      all covering rigs agree       : {unanim}")
        print(f"      covering rigs disagree        : {split}")
        for (n, maj, odd), k in dissent.most_common():
            print(f"      {k:4} files: {maj}/{n} rigs agree, dissenters {list(odd)}")

    print("\n== 9. bone offsets: .adf rest pose vs .trk translations")
    # The .adf gives each dag a single-frame default track -- the bind pose.
    # The .trk stores its own per-joint translation. The two files are stored
    # independently, so if their bone offsets agree the .trk joints and the
    # .adf dags are provably the same skeleton.
    for rigtag in ("A1CA1CJAMES_HS_DEF", "B6CB6CDEMON_HS_DEF"):
        rig = rigs[rigtag]
        rest = {}
        for dg in rig.dags:
            de = getattr(dg.track, "definition", None)
            if de is not None and de.frames:
                rest[dg.joint.upper()] = de.frames[0].translation
        tight = loose_ = nojoint = 0
        worst = []
        for p in sorted((INSTALL / "Tracks").glob("*.trk")):
            try:
                tk = rtktrack.Track(p)
            except Exception:
                continue
            for d, j in zip(tk.trackdefs, rtkspx.track_joints(tk)):
                if j not in rest:
                    nojoint += 1
                    continue
                dv = max(abs(a - b) for a, b in
                         zip(rest[j], d.frames[0].translation))
                if dv < 1e-2:
                    tight += 1
                else:
                    loose_ += 1
                    worst.append((round(dv, 3), j))
        tot = tight + loose_
        agree_j = Counter(j for _, j in worst)
        print(f"   rig {rigtag}")
        print(f"      joint-frame0 offsets compared : {tot}")
        print(f"      agree within 0.01 units       : {tight} "
              f"({100.0 * tight / max(1, tot):.2f}%)")
        print(f"      differ by more                : {loose_} "
              f"-> joints {dict(agree_j)}")
        if worst:
            print(f"      largest difference            : "
                  f"{max(w[0] for w in worst)} units")

    print("\n== 10. rig selection by bone-offset score, then tree unanimity")
    # Ranking covering rigs by bind-pose agreement (check 9) and keeping only
    # the top scorers is a purely measured selection. If every rig left in
    # that group induces the same sub-tree, the hierarchy a .trk should be
    # exported with is determined by the data, not chosen.
    for label, fs in groups:
        unanim = split = skipped = 0
        groupsizes = Counter()
        offenders = Counter()
        cache = {}
        for p in fs:
            try:
                tk = rtktrack.Track(p)
            except Exception:
                continue
            joints = set(rtkspx.track_joints(tk))
            if not joints:
                continue
            cands = sorted(t for t, s in jointsets.items() if joints <= s)
            if not cands:
                skipped += 1
                continue
            scored = []
            for t in cands:
                a, n = rtkspx.score_rig(tk, rigs[t])
                scored.append((a / n if n else 0.0, t))
            top = max(s for s, _ in scored)
            keep = [t for s, t in scored if s == top]
            groupsizes[len(keep)] += 1
            trees = {tuple(sorted(induced_tree(rigs[t], joints).items()))
                     for t in keep}
            if len(trees) == 1:
                unanim += 1
            else:
                split += 1
                # record which joints the top group fails to agree on
                per = defaultdict(set)
                for t in keep:
                    for j, par in induced_tree(rigs[t], joints).items():
                        per[j].add(par)
                offenders[tuple(sorted(j for j, v in per.items()
                                       if len(v) > 1))] += 1
        print(f"   {label}:")
        print(f"      top-scoring group is tree-unanimous : {unanim}")
        print(f"      top-scoring group disagrees         : {split}")
        print(f"      no covering rig (skipped)           : {skipped}")
        print(f"      top-group size hist                 : "
              f"{dict(sorted(groupsizes.items()))}")
        for joints_, k in offenders.most_common(5):
            print(f"      {k:4} files disagree only on: {list(joints_)}")

    print("\n== the standard humanoid tree (majority over covering rigs)")
    tk = rtktrack.Track(INSTALL / "Tracks" / "TK0005M.trk")
    joints = rtkspx.track_joints(tk)
    cands = sorted(t for t, s in jointsets.items() if set(joints) <= s)
    votes = defaultdict(Counter)
    who = defaultdict(lambda: defaultdict(list))
    for t in cands:
        m = induced_tree(rigs[t], set(joints))
        for j, par in m.items():
            votes[j][par] += 1
            who[j][par].append(t)
    for j in joints:
        tot = sum(votes[j].values())
        par, n = votes[j].most_common(1)[0]
        extra = ""
        if n != tot:
            odd = [(k, who[j][k]) for k in votes[j] if k != par]
            extra = f"   <-- dissent {odd}"
        print(f"   {j:12} parent={str(par):12} {n}/{tot}{extra}")


if __name__ == "__main__":
    main()
