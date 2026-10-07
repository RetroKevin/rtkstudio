"""Reader/extractor for Return to Krondor `.t3d` T3D FastFile archives.

The layout is taken straight out of the decompiled loader in `t3dll.dll`:

  t3dFastFileInit @ 100176a0   opens the file and tries FUN_10017750, then FUN_10017800
  FUN_10017750                 variant A: 16-byte magic header, 8-byte directory entries
  FUN_10017800                 variant B: 4-byte header, 17-byte directory entries
  FUN_10017990 / FUN_10017a20  name lookup; proves size == next_entry.offset - offset
  FUN_10017d90 / FUN_10017db0  index -> name; proves where the name lives
  FUN_10017a00 / FUN_10017aa0  bsearch comparators (stricmp -> case-insensitive sort)

See docs/t3d-format.md.
"""

import os
import struct
import sys

MAGIC_A = b'\x02=\xff\xff'      # DAT_1010f2c4 in t3dll.dll
HEADER_A = 16
ENTRY_A = 8
ENTRY_B = 17


class T3DError(Exception):
    pass


class Entry:
    __slots__ = ('index', 'name', 'offset', 'size')

    def __init__(self, index, name, offset, size):
        self.index = index
        self.name = name
        self.offset = offset
        self.size = size

    def __repr__(self):
        return 'Entry(%r, off=%d, size=%d)' % (self.name, self.offset, self.size)


class FastFile:
    """A parsed `.t3d` archive. `variant` is 'A' or 'B'."""

    def __init__(self, path, data=None):
        self.path = path
        self.data = data if data is not None else open(path, 'rb').read()
        self.variant = None
        self.version = None
        self.raw_count = 0          # directory entry count *including* the sentinel
        self.name_bytes = None      # variant A only
        self.entries = []
        self.problems = []
        self._parse()

    # -- parsing ---------------------------------------------------------

    def _parse(self):
        d = self.data
        if len(d) >= HEADER_A and d[:4] == MAGIC_A:
            self.variant = 'A'
            self._parse_a()
        else:
            self.variant = 'B'
            self._parse_b()

    def _parse_a(self):
        d = self.data
        # FUN_10017750: ReadFile(hdr, 0x10); strncmp(hdr, DAT_1010f2c4, 4);
        # MapViewOfFile(..., name_bytes + 0x10 + count * 8)
        magic, version, count, name_bytes = struct.unpack_from('<4sIII', d, 0)
        self.version = version
        self.raw_count = count
        self.name_bytes = name_bytes
        if count < 1:
            raise T3DError('entry count %d < 1' % count)
        dir_start = HEADER_A
        dir_end = dir_start + count * ENTRY_A
        head_region = dir_end + name_bytes
        if dir_end > len(d):
            raise T3DError('directory (%d bytes) runs past EOF' % (count * ENTRY_A))
        if head_region > len(d):
            raise T3DError('header region %d runs past EOF %d' % (head_region, len(d)))
        self.head_region = head_region
        self.name_block = (dir_end, head_region)

        raw = []
        for i in range(count):
            pos = dir_start + i * ENTRY_A
            off, name_rel = struct.unpack_from('<II', d, pos)
            raw.append((pos, off, name_rel))
        self.raw_dir = raw

        # FUN_10017990 writes handle.start = e[0], handle.end = e[2] (the *next*
        # entry's offset field), handle.size = end - start.  So the final entry is
        # a sentinel and there are count-1 real files -- which is exactly why
        # t3dFastFileGetListOfFiles loops while (i < count - 1).
        for i in range(count - 1):
            pos, off, name_rel = raw[i]
            size = raw[i + 1][1] - off
            # FUN_10017d90: name = *(int*)(entry + 4) + entry  (self-relative)
            nameptr = pos + name_rel
            name = self._cstr(nameptr)
            self.entries.append(Entry(i, name, off, size))

    def _parse_b(self):
        d = self.data
        # FUN_10017800: ReadFile(&count, 4); MapViewOfFile(..., count * 0x11 + 4)
        if len(d) < 4:
            raise T3DError('file too short for any header')
        (count,) = struct.unpack_from('<I', d, 0)
        self.raw_count = count
        if count < 1:
            raise T3DError('no magic and entry count %d < 1' % count)
        head_region = 4 + count * ENTRY_B
        if head_region > len(d):
            raise T3DError('no magic (not variant A) and variant B header region '
                           '%d runs past EOF %d' % (head_region, len(d)))
        self.head_region = head_region
        raw = []
        for i in range(count):
            pos = 4 + i * ENTRY_B
            (off,) = struct.unpack_from('<I', d, pos)
            name = d[pos + 4:pos + 4 + 13].split(b'\x00')[0]
            raw.append((pos, off, name))
        self.raw_dir = raw
        for i in range(count - 1):
            pos, off, name = raw[i]
            self.entries.append(Entry(i, name.decode('latin-1'),
                                      off, raw[i + 1][1] - off))

    def _cstr(self, pos):
        d = self.data
        if pos < 0 or pos >= len(d):
            raise T3DError('name pointer %d out of bounds' % pos)
        end = d.find(b'\x00', pos)
        if end < 0:
            raise T3DError('unterminated name at %d' % pos)
        return d[pos:end].decode('latin-1')

    # -- access ----------------------------------------------------------

    def read(self, entry):
        return self.data[entry.offset:entry.offset + entry.size]

    def __len__(self):
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    # -- validation ------------------------------------------------------

    def validate(self):
        """Return a list of problem strings; empty means every check passed."""
        p = []
        d = self.data
        n = len(d)
        if self.variant == 'A':
            # Note: FUN_10017750 never looks at the version field. This check is
            # ours, by analogy with the .trk parser FUN_10022b80 which does gate
            # on (version & ~1) == 0x15500. Every shipped .t3d reports 0x15700.
            if self.version is not None and (self.version & 0xfffffffe) != 0x15700:
                p.append('unexpected version 0x%x' % self.version)
            # the mapped header region must be exactly where the first file starts
            if self.raw_dir[0][1] != self.head_region:
                p.append('first data offset %d != header region %d'
                         % (self.raw_dir[0][1], self.head_region))
        # sentinel must be EOF
        sent = self.raw_dir[-1][1]
        if sent != n:
            p.append('sentinel offset %d != file size %d' % (sent, n))
        # offsets monotonic, sizes positive, ranges in bounds
        prev = None
        for e in self.entries:
            if e.size < 0:
                p.append('%s: negative size %d' % (e.name, e.size))
            if e.offset < self.head_region:
                p.append('%s: offset %d inside header region' % (e.name, e.offset))
            if e.offset + e.size > n:
                p.append('%s: range %d+%d past EOF %d' % (e.name, e.offset, e.size, n))
            if prev is not None and e.offset < prev:
                p.append('%s: offset %d not monotonic' % (e.name, e.offset))
            prev = e.offset
        # entries must tile the data region exactly
        total = sum(e.size for e in self.entries)
        if total != n - self.head_region:
            p.append('sizes total %d != data region %d' % (total, n - self.head_region))
        # names sorted case-insensitively (bsearch via stricmp)
        for a, b in zip(self.entries, self.entries[1:]):
            if a.name.lower() > b.name.lower():
                p.append('names not sorted: %r > %r' % (a.name, b.name))
                break
        if self.variant == 'A':
            # names must tile the name block exactly
            nb_start, nb_end = self.name_block
            used = set()
            for e in self.entries:
                pos = self.raw_dir[e.index][0] + self.raw_dir[e.index][2]
                if not (nb_start <= pos < nb_end):
                    p.append('%s: name at %d outside name block [%d,%d)'
                             % (e.name, pos, nb_start, nb_end))
                    continue
                for k in range(pos, pos + len(e.name) + 1):
                    used.add(k)
            if len(used) != nb_end - nb_start:
                p.append('name block coverage %d of %d bytes'
                         % (len(used), nb_end - nb_start))
        self.problems = p
        return p


def open_archive(path):
    return FastFile(path)


# -- inner file type sniffing ---------------------------------------------

def sniff(buf):
    """Best-effort identification of an extracted member by content."""
    if not buf:
        return 'empty'
    if buf[:4] == b'\x02=PT':
        return 'T3D track container'
    if buf[:4] == MAGIC_A:
        return 'T3D FastFile (nested .t3d)'
    # signature checked by RtK.exe (literal \x89DI_\r\n\x1a\n at .exe+0x1fa755)
    if buf[:8] == b'\x89DI_\r\n\x1a\n':
        return 'T3D DI_ image'
    # FUN_004f5bcd in RtK.exe: two magic dwords, then width/height
    if buf[:8] == b'\xaa&\x00\x00\xa9&\x00\x00':
        return 'T3D binary overlay (.ovx)'
    if buf[:2] == b'BM':
        return 'Windows BMP'
    if buf[:4] == b'RIFF':
        return 'RIFF/' + buf[8:12].decode('latin-1', 'replace')
    if buf[:3] == b'ID3' or buf[:2] == b'\xff\xfb':
        return 'MP3'
    if buf[:4] == b'\x89PNG':
        return 'PNG'
    if buf[:2] == b'\xff\xd8':
        return 'JPEG'
    if buf[:4] == b'FORM':
        return 'IFF/' + buf[8:12].decode('latin-1', 'replace')
    if buf[:2] == b'MZ':
        return 'DOS/PE executable'
    if buf[:4] == b'\x00\x00\x01\xba' or buf[:4] == b'\x00\x00\x01\xb3':
        return 'MPEG'
    # printable text heuristic
    sample = buf[:512]
    printable = sum(1 for c in sample if 32 <= c < 127 or c in (9, 10, 13))
    if printable == len(sample):
        return 'text'
    return 'raw:' + ' '.join('%02x' % b for b in buf[:4])


def find_archives(root):
    out = []
    for dp, dn, fn in os.walk(root):
        if '_decomp' in dp:
            continue
        for f in fn:
            if f.lower().endswith('.t3d'):
                out.append(os.path.join(dp, f))
    return sorted(out)


def main(argv):
    import argparse
    import collections
    import csv
    ap = argparse.ArgumentParser(description='Return to Krondor .t3d FastFile tool')
    ap.add_argument('archives', nargs='*', help='.t3d files, or use --scan')
    ap.add_argument('--scan', metavar='DIR', help='recursively find .t3d under DIR')
    ap.add_argument('-l', '--list', action='store_true', help='list entries')
    ap.add_argument('-x', '--extract', metavar='DIR', help='extract into DIR')
    ap.add_argument('-m', '--manifest', metavar='CSV', help='write manifest CSV')
    ap.add_argument('-t', '--types', action='store_true',
                    help='summarise detected inner file types')
    ap.add_argument('--root', help='base dir for relative source paths in manifest')
    args = ap.parse_args(argv)

    paths = list(args.archives)
    if args.scan:
        paths += find_archives(args.scan)
    if not paths:
        ap.error('no archives given (pass paths or --scan DIR)')
    root = args.root or (args.scan if args.scan else None)

    rows = []
    ok = bad = 0
    total_entries = 0
    total_bytes = 0
    variants = collections.Counter()
    versions = collections.Counter()
    types = collections.Counter()
    type_bytes = collections.Counter()
    for path in paths:
        try:
            ff = FastFile(path)
            probs = ff.validate()
        except Exception as exc:
            bad += 1
            print('FAIL %s: %s' % (path, exc))
            continue
        if probs:
            bad += 1
            print('PROBLEM %s (variant %s):' % (path, ff.variant))
            for s in probs[:10]:
                print('   ', s)
        else:
            ok += 1
        total_entries += len(ff)
        variants[ff.variant] += 1
        versions['0x%x' % (ff.version or 0)] += 1
        src = os.path.relpath(path, root) if root else path
        sub = (src[:-4] if src.lower().endswith('.t3d') else src)
        sub = sub.replace('\\', '_').replace('/', '_')
        if args.list:
            print('%s  variant %s  version 0x%x  %d entries' %
                  (path, ff.variant, ff.version or 0, len(ff)))
            for e in ff:
                print('   %-32s %10d %10d' % (e.name, e.offset, e.size))
        outdir = None
        if args.extract:
            outdir = os.path.join(args.extract, sub)
            os.makedirs(outdir, exist_ok=True)
        for e in ff:
            buf = ff.read(e)
            if len(buf) != e.size:
                raise T3DError('%s:%s short read' % (path, e.name))
            t = sniff(buf) if (args.types or args.manifest) else ''
            types[t] += 1
            type_bytes[t] += e.size
            outpath = ''
            if outdir:
                safe = e.name.replace('/', '_').replace('\\', '_')
                outpath = os.path.join(outdir, safe)
                with open(outpath, 'wb') as fh:
                    fh.write(buf)
                total_bytes += len(buf)
            rows.append((src, e.name, e.offset, e.size, t, outpath))
        ff.data = None

    if args.manifest:
        mandir = os.path.dirname(os.path.abspath(args.manifest))
        with open(args.manifest, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['archive', 'entry', 'offset', 'size',
                        'detected_type', 'output_path'])
            for src, name, off, size, t, op in rows:
                w.writerow([src, name, off, size, t,
                            os.path.relpath(op, mandir) if op else ''])
    if args.types:
        print()
        print('detected inner types:')
        for k, v in types.most_common():
            print('   %-34s %7d  %12d bytes' % (k, v, type_bytes[k]))
    print()
    print('archives clean=%d problem/fail=%d  entries=%d  variants=%s  versions=%s'
          % (ok, bad, total_entries, dict(variants), dict(versions)))
    if args.extract:
        print('bytes written: %d (%.2f MB)' % (total_bytes, total_bytes / 1048576.0))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
