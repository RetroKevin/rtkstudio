"""Validation sweep for the `.t3d` write path (tools/rtkt3d_write.py).

Two phases, both run over every `.t3d` in the game install:

  1. identity  -- rebuild with an empty `replacements` dict and require the
                  output to equal the source byte for byte.  This is the bar:
                  if a field were unmodelled, identity would not hold.
  2. mutation  -- substitute members with larger and with smaller payloads
                  (and a zero-byte one), rebuild, re-open with the reader and
                  require every member to come back exactly as handed in.
  3. negative  -- rebuild with deliberately wrong name-pool orderings and
     control     require them to *fail*, so phase 1 is not passing by accident.

Nothing is written to the game install; output goes under `out/t3d-write/`.

    python tools/validate_t3d_write.py
    python tools/validate_t3d_write.py --keep        # keep rebuilt archives
    python tools/validate_t3d_write.py --game DIR
"""

import argparse
import hashlib
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rtkt3d
import rtkt3d_write

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.dirname(ROOT)
OUT = os.path.join(ROOT, 'out', 't3d-write')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read(path):
    with open(path, 'rb') as fh:
        return fh.read()


def pick_targets(ff):
    """Choose members to mutate: largest, smallest non-empty, a `.bex`-style
    extension-only name if present, plus the first and last by directory order."""
    entries = sorted(ff, key=lambda e: e.size)
    picks = {}

    def add(label, e):
        if e is not None and e.name not in picks:
            picks[e.name] = label

    add('smallest', entries[0])
    add('largest', entries[-1])
    add('median', entries[len(entries) // 2])
    add('first-in-dir', ff.entries[0])
    add('last-in-dir', ff.entries[-1])
    for e in ff:
        # the extension-only name (e.g. Bex.t3d's '.bex'): an empty stem, which
        # glob() hides but the archive stores like any other name
        if e.name.startswith('.'):
            add('extension-only-name', e)
            break
    return picks


def mutate(name, buf, label, n):
    """Deterministic replacement payload; alternates grow / shrink / empty."""
    mode = n % 3
    if mode == 0:                                   # grow
        pad = b'GROW' * 1024 + name.encode('latin-1', 'replace')
        return buf + pad, 'grow +%d' % len(pad)
    if mode == 1:                                   # shrink
        keep = len(buf) // 3
        return buf[:keep], 'shrink -%d' % (len(buf) - keep)
    return b'', 'empty -%d' % len(buf)              # zero bytes


def phase_identity(paths, outdir, keep):
    print('== phase 1: identity rebuild ==')
    exact = 0
    failed = []
    total_in = total_out = 0
    members = 0
    t0 = time.time()
    for i, path in enumerate(paths, 1):
        src = read(path)
        dst = os.path.join(outdir, 'identity', os.path.basename(path))
        rep = rtkt3d_write.rebuild_identity(path, dst)
        got = read(dst)
        members += rep['members']
        total_in += len(src)
        total_out += len(got)
        if got == src:
            exact += 1
        else:
            where = next((k for k in range(min(len(src), len(got)))
                          if src[k] != got[k]), min(len(src), len(got)))
            failed.append((path, len(src), len(got), where))
            print('  BYTE-DIFF %-22s src=%d out=%d first diff at %d'
                  % (os.path.basename(path), len(src), len(got), where))
        if not keep:
            os.remove(dst)
        if i % 25 == 0 or i == len(paths):
            print('  %3d/%d  byte-exact %d' % (i, len(paths), exact))
    dt = time.time() - t0
    print('  archives %d  byte-exact %d  mismatched %d  members %d'
          % (len(paths), exact, len(failed), members))
    print('  bytes in %d  bytes out %d  (%.1fs)' % (total_in, total_out, dt))
    return exact, failed, members


def phase_mutation(paths, outdir, keep):
    print()
    print('== phase 2: substitution rebuild + re-read ==')
    ok = 0
    failed = []
    subs = 0
    grew = shrank = emptied = 0
    t0 = time.time()
    n = 0
    for i, path in enumerate(paths, 1):
        ff = rtkt3d.FastFile(path)
        picks = pick_targets(ff)
        expected = {e.name: ff.read(e) for e in ff}
        repl = {}
        for name, label in picks.items():
            new, how = mutate(name, expected[name], label, n)
            n += 1
            repl[name] = new
            expected[name] = new
            subs += 1
            if how.startswith('grow'):
                grew += 1
            elif how.startswith('shrink'):
                shrank += 1
            else:
                emptied += 1
        ff.data = None

        dst = os.path.join(outdir, 'mutated', os.path.basename(path))
        rep = rtkt3d_write.rebuild(path, dst, repl)
        probs = list(rtkt3d_write.verify(dst, expected))
        if rep['missing']:
            probs.append('replacements not found: %s' % rep['missing'])
        if rep['replaced'] != len(repl):
            probs.append('replaced %d of %d' % (rep['replaced'], len(repl)))
        if rep['size'] != os.path.getsize(dst):
            probs.append('report size %d != on-disk %d' % (rep['size'],
                                                           os.path.getsize(dst)))
        # the report's own arithmetic must close
        want = (rep['header_bytes'] + rep['name_pool_bytes']
                + rep['member_bytes_out'])
        if want != rep['size']:
            probs.append('header %d + names %d + data %d != size %d'
                         % (rep['header_bytes'], rep['name_pool_bytes'],
                            rep['member_bytes_out'], rep['size']))
        if probs:
            failed.append((path, probs))
            print('  FAIL %-22s %s' % (os.path.basename(path), probs[:3]))
        else:
            ok += 1
        if not keep:
            os.remove(dst)
        if i % 25 == 0 or i == len(paths):
            print('  %3d/%d  clean %d' % (i, len(paths), ok))
    dt = time.time() - t0
    print('  archives %d  clean %d  failed %d' % (len(paths), ok, len(failed)))
    print('  substitutions %d  (grew %d, shrank %d, emptied %d)  (%.1fs)'
          % (subs, grew, shrank, emptied, dt))
    return ok, failed, subs


def phase_named_cases(outdir, keep):
    """Explicit, named edge cases with hard numbers, not just the sweep."""
    print()
    print('== phase 3: named edge cases ==')
    results = []

    def case(label, path, repl):
        if not os.path.exists(path):
            results.append((label, 'SKIP (no %s)' % path))
            return
        ff = rtkt3d.FastFile(path)
        expected = {e.name: ff.read(e) for e in ff}
        ff.data = None
        expected.update(repl)
        dst = os.path.join(outdir, 'cases',
                           label.replace(' ', '_') + '.t3d')
        rep = rtkt3d_write.rebuild(path, dst, repl)
        probs = rtkt3d_write.verify(dst, expected)
        results.append((label, 'OK  %d members, %d -> %d bytes (%+d)'
                        % (rep['members'], rep['src_size'], rep['size'],
                           rep['size_delta'])
                        if not probs else 'FAIL %s' % probs[:3]))
        if not keep:
            os.remove(dst)
        return rep

    bex = os.path.join(GAME, 'Bex.t3d')
    if os.path.exists(bex):
        ff = rtkt3d.FastFile(bex)
        by = {e.name: ff.read(e) for e in ff}
        ff.data = None
        if '.bex' in by:
            case('.bex grow', bex, {'.bex': by['.bex'] + b'X' * 100000})
            case('.bex shrink', bex, {'.bex': by['.bex'][:7]})
            case('.bex empty', bex, {'.bex': b''})
        else:
            results.append(('.bex cases', 'SKIP (no extension-only member)'))

    tracks = os.path.join(GAME, 'Tracks.t3d')
    if os.path.exists(tracks):
        ff = rtkt3d.FastFile(tracks)
        by = {e.name: ff.read(e) for e in ff}
        ff.data = None
        # pivots.trk is the one shipped zero-byte member; grow it from nothing
        if 'pivots.trk' in by and len(by['pivots.trk']) == 0:
            case('zero-byte member grown', tracks,
                 {'pivots.trk': b'\x02=PT' + b'\x00' * 4096})
        # Tracks is one of the 5 archives whose name pool is ordered by
        # upper-case fold; mutate it hard to be sure the pool stays put
        names = sorted(by)[:40]
        case('upper-fold pool archive, 40 subs', tracks,
             {n: by[n][: max(1, len(by[n]) // 2)] for n in names})

    # smallest archive: replace every single member
    small = min((p for p in rtkt3d.find_archives(GAME)),
                key=os.path.getsize, default=None)
    if small:
        ff = rtkt3d.FastFile(small)
        by = {e.name: ff.read(e) for e in ff}
        ff.data = None
        case('replace every member (%s)' % os.path.basename(small), small,
             {n: (b'!' * (i * 7)) for i, n in enumerate(sorted(by))})

    for label, msg in results:
        print('  %-34s %s' % (label, msg))
    return results


def phase_negative_control(paths):
    """Prove the name-pool ordering is load-bearing, not a coincidence.

    The pool is ordered by `name.upper()`, the directory by `name.lower()`.
    Rebuild everything with the two obvious-but-wrong pool orderings and count
    how many archives stop being byte-exact.  If a wrong model also scored
    144/144 the test below would be vacuous.
    """
    print()
    print('== phase 4: negative control on name-pool ordering ==')
    right = rtkt3d_write._pool_key
    models = [
        ('upper fold (the model)', right),
        ('lower fold', rtkt3d_write._dir_key),
        ('directory order', None),
    ]
    scores = []
    try:
        for label, key in models:
            if key is None:
                # pool emitted in directory order: same key as the directory,
                # which is a stable sort, so the pool follows the dir exactly
                rtkt3d_write._pool_key = rtkt3d_write._dir_key
            else:
                rtkt3d_write._pool_key = key
            exact = 0
            broken = []
            for path in paths:
                ff = rtkt3d.FastFile(path)
                src = ff.data
                members = [(e.name, ff.read(e)) for e in ff]
                blob = rtkt3d_write.build(members, version=ff.version)
                if blob == src:
                    exact += 1
                else:
                    broken.append(os.path.basename(path))
                ff.data = None
            scores.append((label, exact, broken))
            print('  %-24s byte-exact %3d/%d  broken: %s'
                  % (label, exact, len(paths), broken[:6] if broken else '-'))
    finally:
        rtkt3d_write._pool_key = right

    probs = []
    if scores[0][1] != len(paths):
        probs.append('the model itself is not byte-exact')
    for label, exact, _ in scores[1:]:
        if exact == len(paths):
            probs.append('%r is also byte-exact, so the sweep proves nothing '
                         'about pool ordering' % label)
    for p in probs:
        print('  FAIL %s' % p)
    return probs


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', default=GAME, help='game install root (read only)')
    ap.add_argument('--out', default=OUT, help='output dir (default out/t3d-write)')
    ap.add_argument('--keep', action='store_true', help='keep rebuilt archives')
    ap.add_argument('--limit', type=int, help='only the first N archives')
    args = ap.parse_args(argv)

    game = os.path.abspath(args.game)
    outdir = os.path.abspath(args.out)
    if os.path.commonpath([outdir, game]) == game and not outdir.startswith(ROOT):
        ap.error('refusing to write inside the game install')

    paths = rtkt3d.find_archives(game)
    if args.limit:
        paths = paths[:args.limit]
    if not paths:
        ap.error('no .t3d archives under %s' % game)

    for sub in ('identity', 'mutated', 'cases'):
        os.makedirs(os.path.join(outdir, sub), exist_ok=True)

    print('game install : %s (read only)' % game)
    print('output       : %s' % outdir)
    print('archives     : %d' % len(paths))
    print()

    exact, id_fail, members = phase_identity(paths, outdir, args.keep)
    ok, mut_fail, subs = phase_mutation(paths, outdir, args.keep)
    phase_named_cases(outdir, args.keep)
    ctl_fail = phase_negative_control(paths)

    if not args.keep:
        shutil.rmtree(outdir, ignore_errors=True)

    print()
    print('=' * 72)
    print('identity    : %d/%d archives byte-exact  (%d members)'
          % (exact, len(paths), members))
    print('substitution: %d/%d archives verified    (%d substitutions)'
          % (ok, len(paths), subs))
    bad = len(id_fail) + len(mut_fail) + len(ctl_fail)
    print('result      : %s' % ('PASS' if bad == 0 else 'FAIL (%d)' % bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
