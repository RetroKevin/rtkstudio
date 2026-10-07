"""Writer/repacker for Return to Krondor `.t3d` T3D FastFile archives.

Companion to the read-only `tools/rtkt3d.py`.  Everything here is derived from
the decompiled loader in `t3dll.dll` plus a sweep over all 144 shipped
archives; nothing is guessed.  Use `python tools/lines.py t3dll.c <FUN_name>`
to locate a cited function, `python tools/show_func.py` to print it.

Loader facts this writer reproduces (variant A -- every shipped archive is
variant A, version 0x15700):

  FUN_10017750   reads a 0x10 header, `strncmp(hdr, DAT_1010f2c4, 4)`, then
                 maps `name_bytes + 0x10 + count * 8` bytes.  That mapped
                 region is the header + directory + name pool, so
                     data_start == 0x10 + count * 8 + name_bytes
                 and the header's two trailing dwords are
                     +0x08 count   (entries, *including* the sentinel)
                     +0x0c name_bytes (size of the name pool)
  FUN_10017990   handle.start = entry[0], handle.end = (entry+8)[0],
                 handle.size = end - start.  A member's size is the *next*
                 entry's offset minus its own, so the last directory entry is
                 a sentinel whose offset is the file size and which owns no
                 data.  Members therefore tile the data region with no
                 padding and no gaps.
  FUN_10017d90   name_ptr = entry + *(int *)(entry + 4): the second dword of
                 each 8-byte entry is a *self-relative* offset to a NUL
                 terminated name.
  FUN_10017a00   the bsearch comparator, `_stricmp(name_a, name_b)`.  MSVC's
                 _stricmp folds to lower case, so the directory must be sorted
                 by `name.lower()` or lookups fail.

One thing the loader does not constrain, recovered from the shipped files
instead: the *name pool* is ordered by `name.upper()`, not by `name.lower()`.
The two orderings differ only where '_' (0x5f) meets a letter, because
'_' sorts before 'a'..'z' but after 'A'..'Z'.  139 of the 144 archives have no
such name pair and so cannot tell the two apart; 5 (Chars, FX, HiColorChars,
HiColorFX, Tracks) do, and they all follow the upper-case ordering.  Getting
this wrong costs byte-exactness on exactly those 5 archives.

See docs/t3d-write.md.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rtkt3d

MAGIC = rtkt3d.MAGIC_A       # b'\x02=\xff\xff', DAT_1010f2c4 in t3dll.dll
VERSION = 0x15700            # every shipped .t3d
HEADER = rtkt3d.HEADER_A     # 16
ENTRY = rtkt3d.ENTRY_A       # 8


class T3DWriteError(Exception):
    pass


# -- name collation --------------------------------------------------------
#
# Both orderings are plain byte sorts after an ASCII-only case fold, which is
# what C's tolower/toupper do in the "C" locale.  bytes.lower()/.upper() touch
# only A-Z/a-z, so they match exactly; str.lower()/.upper() would not (they
# would fold non-ASCII, and 'SS'-expand some code points).  Every name in
# every shipped archive is printable ASCII, so this is lossless in practice.

def _dir_key(name):
    """Sort key for the directory: MSVC _stricmp folds to lower case."""
    return name.encode('latin-1').lower()


def _pool_key(name):
    """Sort key for the name pool: the packer folded to upper case."""
    return name.encode('latin-1').upper()


# -- building --------------------------------------------------------------

def build(members, version=VERSION):
    """Serialise `members` -- an iterable of (name, bytes) -- into a `.t3d`.

    Member order on input is irrelevant; the directory and the name pool are
    each sorted into the order the format requires.
    """
    items = [(str(name), bytes(data)) for name, data in members]

    seen = {}
    for name, _ in items:
        key = _dir_key(name)
        if key in seen:
            raise T3DWriteError(
                'duplicate member name %r vs %r (the loader bsearches '
                'case-insensitively, so these would collide)' % (name, seen[key]))
        seen[key] = name
        if '\x00' in name:
            raise T3DWriteError('member name %r contains NUL' % name)
        try:
            name.encode('latin-1')
        except UnicodeEncodeError:
            raise T3DWriteError('member name %r is not encodable as latin-1' % name)

    items.sort(key=lambda m: _dir_key(m[0]))

    # Name pool: every name once, NUL terminated, in upper-case-fold order.
    pool = bytearray()
    pool_off = {}
    for name, _ in sorted(items, key=lambda m: _pool_key(m[0])):
        pool_off[name] = len(pool)
        pool += name.encode('latin-1') + b'\x00'

    count = len(items) + 1              # + the sentinel
    dir_start = HEADER
    pool_start = dir_start + count * ENTRY
    data_start = pool_start + len(pool)

    out = bytearray(struct.pack('<4sIII', MAGIC, version, count, len(pool)))

    cursor = data_start
    for i, (name, data) in enumerate(items):
        entry_pos = dir_start + i * ENTRY
        rel = (pool_start + pool_off[name]) - entry_pos
        out += struct.pack('<II', cursor, rel)
        cursor += len(data)
    # Sentinel: offset == EOF (so the last real member gets its size), and a
    # name pointer of 0.  All 144 shipped archives store 0 here.
    out += struct.pack('<II', cursor, 0)

    out += pool
    for _, data in items:
        out += data

    if len(out) != cursor:
        raise T3DWriteError('internal: wrote %d bytes, sentinel says %d'
                            % (len(out), cursor))
    return bytes(out)


# -- the mod-builder entry point -------------------------------------------

def rebuild(src, dst, replacements):
    """Write a new .t3d, substituting member name -> new bytes.

    `replacements` maps the member name exactly as `rtkt3d` reports it to its
    new raw stored bytes.  Unlisted members are copied through unchanged.
    Returns a report dict with counts and the new size.

    Replacement payloads may be any size; every offset, the member count, the
    name-pool size and the sentinel are recomputed from scratch.
    """
    src = os.fspath(src)
    dst = os.fspath(dst)

    ff = rtkt3d.FastFile(src)
    problems = ff.validate()
    if problems:
        raise T3DWriteError('source %s is not a clean archive: %s'
                            % (src, '; '.join(problems[:3])))
    if ff.variant != 'A':
        raise T3DWriteError('source %s is variant %s; only variant A is '
                            'written (no shipped archive uses variant B)'
                            % (src, ff.variant))

    names = [e.name for e in ff]
    missing = sorted(set(replacements) - set(names))

    members = []
    replaced = 0
    bytes_in = bytes_out = 0
    for e in ff:
        old = ff.read(e)
        bytes_in += len(old)
        if e.name in replacements:
            new = bytes(replacements[e.name])
            replaced += 1
        else:
            new = old
        bytes_out += len(new)
        members.append((e.name, new))

    blob = build(members, version=ff.version)

    parent = os.path.dirname(os.path.abspath(dst))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dst, 'wb') as fh:
        fh.write(blob)

    src_size = len(ff.data)
    ff.data = None

    return {
        'src': src,
        'dst': dst,
        'members': len(members),
        'replaced': replaced,
        'copied': len(members) - replaced,
        'missing': missing,
        'src_size': src_size,
        'size': len(blob),
        'size_delta': len(blob) - src_size,
        'member_bytes_in': bytes_in,
        'member_bytes_out': bytes_out,
        'header_bytes': HEADER + (len(members) + 1) * ENTRY,
        'name_pool_bytes': struct.unpack_from('<I', blob, 12)[0],
        'identical': len(blob) == src_size and not replaced,
    }


# -- convenience -----------------------------------------------------------

def rebuild_identity(src, dst):
    """Rebuild with no substitutions; the result must equal `src` byte for byte."""
    return rebuild(src, dst, {})


def verify(path, expected):
    """Re-open `path` with the reader and check it against {name: bytes}.

    Returns a list of problem strings; empty means every member read back
    exactly as given.
    """
    ff = rtkt3d.FastFile(os.fspath(path))
    problems = list(ff.validate())
    got = {}
    for e in ff:
        got[e.name] = ff.read(e)
    ff.data = None
    for name in sorted(set(expected) - set(got)):
        problems.append('missing member %r' % name)
    for name in sorted(set(got) - set(expected)):
        problems.append('unexpected member %r' % name)
    for name in sorted(set(got) & set(expected)):
        if got[name] != expected[name]:
            problems.append('member %r: %d bytes back, %d expected%s'
                            % (name, len(got[name]), len(expected[name]),
                               '' if len(got[name]) != len(expected[name])
                               else ' (same length, different content)'))
    return problems


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description='Return to Krondor .t3d repacker')
    ap.add_argument('src', help='source .t3d')
    ap.add_argument('dst', help='destination .t3d (never inside the game install)')
    ap.add_argument('-r', '--replace', action='append', default=[],
                    metavar='NAME=FILE',
                    help='substitute member NAME with the contents of FILE')
    args = ap.parse_args(argv)

    repl = {}
    for spec in args.replace:
        if '=' not in spec:
            ap.error('--replace needs NAME=FILE, got %r' % spec)
        name, _, fn = spec.partition('=')
        with open(fn, 'rb') as fh:
            repl[name] = fh.read()

    rep = rebuild(args.src, args.dst, repl)
    if rep['missing']:
        print('WARNING: not in archive: %s' % ', '.join(rep['missing']))
    print('%s -> %s' % (rep['src'], rep['dst']))
    print('  members %d (replaced %d, copied %d)'
          % (rep['members'], rep['replaced'], rep['copied']))
    print('  size %d -> %d (%+d)' % (rep['src_size'], rep['size'], rep['size_delta']))
    return 1 if rep['missing'] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
