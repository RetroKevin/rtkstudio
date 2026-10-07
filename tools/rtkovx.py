"""Reader for Return to Krondor `.ovx` "binary overlay files".

An `.ovx` is not an image. It is a precomputed **coverage buffer**: a run-length
depth mask for one prerendered camera view, which the engine hands to
`t3dSetRenderContextCoverageBuffer` so that dynamic actors get occluded by the
static scene (see `FUN_0045cfd0` / `RtK.c:60163`).

Layout is taken straight out of the decompiled loader:

  FUN_004fedbe @ 004fedbe   RtK.c:167105  reads the whole member into one buffer
  FUN_0043afb1 @ 0043afb1   RtK.c:37314   zeroes the two 480-entry arrays, calls:
  FUN_004f5bcd @ 004f5bcd   RtK.c:160559  THE PARSER -- every offset below
  FUN_00454596 @ 00454596   RtK.c:54556   samples a row: proves the span fields
  FUN_004f5e39 @ 004f5e39   RtK.c:160657  proves field 2's anchor-end rule
  FUN_004f4a3f @ 004f4a3f   RtK.c:160141  merges two span lists; writes the same
                                          16-byte records back out

  offset  type   field
       0  u32    magic 0, must equal DAT_005f9298 == 0x26aa
       4  u32    magic 1, must equal DAT_005f929c == 0x26a9
       8  u32    width,  must equal 0x280 (640)
      12  u32    height, must equal 0x1e0 (480)
      16  u32    row index y of the first populated scanline
  then, while y < 480:
       0  u32    span count n for row y   (n >= 1 in every shipped file)
       4  n * 16 span records
             +0  i32    x_start, inclusive
             +4  i32    x_end,   exclusive
             +8  f32    reciprocal view depth 1/w at the anchor end
            +12  f32    d(1/w)/dx along the span
     ...  u32    row index y of the next populated scanline; >= 480 ends the
                 walk. The writer always emits 0x26a7, the fourth word of the
                 sentinel table at RtK.exe+0x5f9298.

Nothing follows the terminator: size == 20 + 8*rows + 16*spans exactly.

See docs/ovx-format.md.
"""

import argparse
import csv
import math
import struct
import zlib
from pathlib import Path

MAGIC0 = 0x26AA                 # DAT_005f9298
MAGIC1 = 0x26A9                 # DAT_005f929c
TERMINATOR = 0x26A7             # RtK.exe+0x5f92a4, fourth of the sentinel table
SCREEN_W = 0x280                # hard-coded in FUN_004f5bcd
SCREEN_H = 0x1E0
HEADER = 20
SPAN = 16


class OvxError(Exception):
    pass


class Span:
    """One horizontal run of covered pixels with a linear 1/w ramp.

    `base` is 1/w sampled at `anchor`, which is `x_end` when the slope is
    negative and `x_start` otherwise (FUN_004f5e39, FUN_004f4a3f:165199).
    """

    __slots__ = ('x_start', 'x_end', 'base', 'slope')

    def __init__(self, x_start, x_end, base, slope):
        self.x_start = x_start
        self.x_end = x_end
        self.base = base
        self.slope = slope

    @property
    def anchor(self):
        return self.x_end if self.slope < 0.0 else self.x_start

    def inv_depth(self, x):
        """1/w at screen column `x`. Mirrors FUN_00454596 exactly."""
        return (x - self.anchor) * self.slope + self.base

    @property
    def intercept(self):
        """1/w extrapolated to x == 0, i.e. the C of 1/w = A*x + C for this row."""
        return self.base - self.anchor * self.slope

    def __repr__(self):
        return ('Span(x=[%d,%d) 1/w=%.6g..%.6g slope=%.6g)'
                % (self.x_start, self.x_end, self.inv_depth(self.x_start),
                   self.inv_depth(self.x_end - 1), self.slope))


class Overlay:
    """A parsed `.ovx`. `rows[y]` is the span list for scanline y, possibly []."""

    __slots__ = ('magic', 'width', 'height', 'rows', 'first_row', 'terminator',
                 'size', 'name')

    def __init__(self, name=''):
        self.name = name
        self.magic = (0, 0)
        self.width = 0
        self.height = 0
        self.rows = [[] for _ in range(SCREEN_H)]
        self.first_row = 0
        self.terminator = 0
        self.size = 0

    @property
    def span_count(self):
        return sum(len(r) for r in self.rows)

    @property
    def row_count(self):
        return sum(1 for r in self.rows if r)

    @property
    def covered_pixels(self):
        return sum(s.x_end - s.x_start for r in self.rows for s in r)

    def inv_depth(self, x, y):
        """1/w at (x, y), or None where the overlay has no coverage.

        The linear scan and its early exit are FUN_00454596's, which is why the
        span list has to be sorted by x_start.
        """
        for s in self.rows[y]:
            if s.x_start > x:
                return None
            if x < s.x_end:
                return s.inv_depth(x)
        return None


def parse(data, name=''):
    """Walk `data` exactly as FUN_004f5bcd does. Raises OvxError on any mismatch."""
    o = Overlay(name)
    o.size = len(data)
    if len(data) < HEADER:
        raise OvxError('%d bytes is shorter than the %d-byte header' % (len(data), HEADER))
    m0, m1, w, h, y = struct.unpack_from('<5I', data, 0)
    o.magic = (m0, m1)
    o.width = w
    o.height = h
    o.first_row = y
    # the four guards of FUN_004f5bcd, in its own order
    if m0 != MAGIC0:
        raise OvxError('Error reading binary overlay file signature: word 0 is 0x%x' % m0)
    if m1 != MAGIC1:
        raise OvxError('Error reading binary overlay file signature: word 1 is 0x%x' % m1)
    if w != SCREEN_W:
        raise OvxError('Invalid width in binary overlay file: %d' % w)
    if h != SCREEN_H:
        raise OvxError('Invalid height in binary overlay file: %d' % h)

    pos = HEADER
    prev = -1
    while y < SCREEN_H:
        if y <= prev:
            raise OvxError('row index %d does not advance past %d' % (y, prev))
        prev = y
        if pos + 4 > len(data):
            raise OvxError('span count for row %d runs past EOF' % y)
        n, = struct.unpack_from('<I', data, pos)
        pos += 4
        if pos + n * SPAN + 4 > len(data):
            raise OvxError('row %d: %d spans run past EOF' % (y, n))
        spans = []
        for i in range(n):
            x0, x1 = struct.unpack_from('<2i', data, pos)
            base, slope = struct.unpack_from('<2f', data, pos + 8)
            spans.append(Span(x0, x1, base, slope))
            pos += SPAN
        o.rows[y] = spans
        y, = struct.unpack_from('<I', data, pos)
        pos += 4
    o.terminator = y
    if pos != len(data):
        raise OvxError('%d bytes left after the terminator' % (len(data) - pos))
    return o


# -- sources ---------------------------------------------------------------

def iter_archive_members(game):
    """Yield (archive_name, entry_name, bytes) for every .ovx in `game`/*.t3d."""
    import rtkt3d
    for path in sorted(Path(game).glob('*.t3d')):
        try:
            ff = rtkt3d.FastFile(str(path))
        except rtkt3d.T3DError:
            continue
        for e in ff.entries:
            if e.name.lower().endswith('.ovx'):
                yield path.name, e.name, ff.read(e)


def iter_loose_files(root):
    """Yield (parent_dir, filename, bytes) for every .ovx under `root`."""
    for p in sorted(Path(root).rglob('*.ovx')):
        yield p.parent.name, p.name, p.read_bytes()


# -- PNG output ------------------------------------------------------------

def _chunk(tag, data):
    body = tag + data
    return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))


# index 0 is "no coverage"; 1..255 ramp dark (far) to white (near)
DEPTH_PALETTE = [(255, 0, 255)] + [(v, v, v) for v in range(1, 256)]


def depth_image(o, lo=None, hi=None):
    """Render the overlay as 640x480 palette indices. Returns (pixels, lo, hi).

    The ramp is logarithmic in 1/w between the 1st and 99th percentile of the
    overlay's own span endpoints -- scene depth spans two or three decades, so
    a linear ramp collapses everything but the nearest surface to black.
    """
    vals = [v for r in o.rows for s in r
            for v in (s.inv_depth(s.x_start), s.inv_depth(s.x_end - 1)) if v > 0.0]
    if lo is None or hi is None:
        if not vals:
            lo = hi = 0.0
        else:
            vals.sort()
            lo = vals[len(vals) // 100]
            hi = vals[-1 - len(vals) // 100]
    llo = math.log(lo) if lo > 0.0 else 0.0
    scale = 254.0 / ((math.log(hi) - llo) or 1.0) if hi > 0.0 else 0.0
    rows = []
    for y in range(SCREEN_H):
        row = bytearray(SCREEN_W)
        for s in o.rows[y]:
            a = max(0, s.x_start)
            b = min(SCREEN_W, s.x_end)
            if b <= a:
                continue
            i0 = _level(s.inv_depth(a), llo, scale)
            i1 = _level(s.inv_depth(b - 1), llo, scale)
            if i0 == i1:
                row[a:b] = bytes([i0]) * (b - a)
            else:
                step = (i1 - i0) / (b - a - 1)
                row[a:b] = bytes(i0 + int(step * (x - a) + 0.5) for x in range(a, b))
        rows.append(bytes(row))
    return rows, lo, hi


def _level(v, llo, scale):
    if v <= 0.0:
        return 1
    i = 1 + int(scale * (math.log(v) - llo))
    return 1 if i < 1 else (255 if i > 255 else i)


def write_depth_png(path, rows):
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type: none
        raw += row
    plte = bytearray()
    for r, g, b in DEPTH_PALETTE:
        plte += bytes((r, g, b))
    png = b'\x89PNG\r\n\x1a\n'
    png += _chunk(b'IHDR', struct.pack('>IIBBBBB', SCREEN_W, SCREEN_H, 8, 3, 0, 0, 0))
    png += _chunk(b'PLTE', bytes(plte))
    png += _chunk(b'IDAT', zlib.compress(bytes(raw), 6))
    png += _chunk(b'IEND', b'')
    Path(path).write_bytes(png)


# -- validation ------------------------------------------------------------

PLAUSIBLE_INV_DEPTH = 10.0      # 1/w; the whole corpus lives inside [-0.48, 0.66]
PLAUSIBLE_SLOPE = 0.01          # per pixel; corpus max is 2.0e-3


class Counters(dict):
    def __iadd__(self, key):
        self[key] = self.get(key, 0) + 1
        return self

    def bump(self, key, n=1):
        self[key] = self.get(key, 0) + n


def check(o, data, c):
    """Content-level checks. Bumps counters in `c`; returns a list of failures."""
    bad = []

    # 1. the size formula must close with zero slack
    expect = HEADER + 8 * o.row_count + SPAN * o.span_count
    if expect != len(data):
        bad.append('size %d != 20 + 8*%d + 16*%d = %d'
                   % (len(data), o.row_count, o.span_count, expect))
    else:
        c += 'size formula exact'

    # 2. the sentinel the writer actually emits
    if o.terminator == TERMINATOR:
        c += 'terminator == 0x26a7'
    else:
        c += 'terminator != 0x26a7'

    for y in range(SCREEN_H):
        spans = o.rows[y]
        if not spans:
            continue
        prev_end = 0
        for s in spans:
            # 3a. a handful of overlays carry a record that is all zero except
            # x_start. FUN_00454596 can never match it (x < 0 is never true),
            # so the engine ignores it; so do we. It still has to sit in
            # x_start order or it would cut the scan short.
            if s.x_end == 0 and s.base == 0.0 and s.slope == 0.0:
                c += 'degenerate span (all zero but x_start)'
                if s.x_start < prev_end:
                    bad.append('row %d: degenerate span at x_start %d breaks order'
                               % (y, s.x_start))
                continue
            # 3b. span geometry
            if not (0 <= s.x_start < s.x_end <= SCREEN_W + 1):
                bad.append('row %d: bad span x=[%d,%d)' % (y, s.x_start, s.x_end))
            if s.x_end > SCREEN_W:
                c += 'span x_end > 640'
            # 4. sorted and non-overlapping: required by FUN_00454596's early exit
            if s.x_start < prev_end:
                c += 'span overlaps its predecessor'
            prev_end = s.x_end

            # 5. the float32 model must give a usable depth line
            v0 = s.inv_depth(s.x_start)
            v1 = s.inv_depth(s.x_end - 1)
            if not (math.isfinite(v0) and math.isfinite(v1) and math.isfinite(s.slope)):
                bad.append('row %d: non-finite depth line %r' % (y, s))
            elif (abs(v0) < PLAUSIBLE_INV_DEPTH and abs(v1) < PLAUSIBLE_INV_DEPTH
                    and abs(s.slope) < PLAUSIBLE_SLOPE):
                c += 'float32 model: depth line in range'
            else:
                c += 'float32 model: depth line OUT of range'
            if v0 <= 0.0 or v1 <= 0.0:
                c += 'span with non-positive 1/w'

    return bad


def check_rejected_models(data, o, c):
    """Count how the layouts listed in docs/ovx-format.md as rejected actually fare."""
    pos = HEADER
    y = o.first_row
    while y < SCREEN_H:
        n, = struct.unpack_from('<I', data, pos)
        pos += 4
        run_end = 0
        for i in range(n):
            xf0, xf1 = struct.unpack_from('<2f', data, pos)
            bi, si = struct.unpack_from('<2i', data, pos + 8)
            pos += SPAN
            span = o.rows[y][i]
            # REJECTED: fields 0/1 as float32
            if ((xf0 == 0.0 or abs(xf0) < 1e-30) and (xf1 == 0.0 or abs(xf1) < 1e-30)):
                c += 'rejected x-as-float32: denormal'
            else:
                c += 'rejected x-as-float32: normal'
            # REJECTED: fields 2/3 as int32
            anchor = span.x_end if si < 0 else span.x_start
            iv0 = (span.x_start - anchor) * si + bi
            iv1 = (span.x_end - 1 - anchor) * si + bi
            if 0 < iv0 < 10 ** 6 and 0 < iv1 < 10 ** 6:
                c += 'rejected int32 depth: in range'
            else:
                c += 'rejected int32 depth: OUT of range'
            # REJECTED: fields 2/3 swapped, i.e. (slope, base)
            sw_slope, sw_base = span.base, span.slope
            sw_anchor = span.x_end if sw_slope < 0 else span.x_start
            sv0 = (span.x_start - sw_anchor) * sw_slope + sw_base
            sv1 = (span.x_end - 1 - sw_anchor) * sw_slope + sw_base
            if (0.0 < sv0 < PLAUSIBLE_INV_DEPTH and 0.0 < sv1 < PLAUSIBLE_INV_DEPTH
                    and abs(sw_slope) < PLAUSIBLE_SLOPE):
                c += 'rejected swapped base/slope: in range'
            else:
                c += 'rejected swapped base/slope: OUT of range'
            # REJECTED: field 1 as a run length rather than an exclusive end
            if span.x_start < run_end:
                c += 'rejected x1-as-length: run overlaps predecessor'
            run_end = span.x_start + span.x_end
            if run_end > SCREEN_W + 1:
                c += 'rejected x1-as-length: run past 641'
        y, = struct.unpack_from('<I', data, pos)
        pos += 4


def vertical_continuity(o, out):
    """Relative 1/w mismatch between every overlapping span pair in rows y, y+1.

    Rows are stored as independent records, so agreement here cannot be an
    artefact of the parse: it only happens if the fields mean what we claim.
    """
    for y in range(SCREEN_H - 1):
        a, b = o.rows[y], o.rows[y + 1]
        if not a or not b:
            continue
        i = j = 0
        while i < len(a) and j < len(b):
            lo = max(a[i].x_start, b[j].x_start)
            hi = min(a[i].x_end, b[j].x_end)
            if lo < hi:
                x = (lo + hi - 1) // 2
                va, vb = a[i].inv_depth(x), b[j].inv_depth(x)
                m = max(abs(va), abs(vb))
                if m > 1e-9:
                    out.append(abs(va - vb) / m)
            if a[i].x_end <= b[j].x_end:
                i += 1
            else:
                j += 1


# Candidate readings of a span record, as (slope, intercept) of its 1/w line.
# 'engine' is the one FUN_004f5e39 uses; the rest are the models this project
# tried and rejected. See docs/ovx-format.md.
LINE_MODELS = {
    'engine': lambda s: (s.slope, s.base - s.slope * (s.x_end if s.slope < 0 else s.x_start)),
    'anchor always x_start': lambda s: (s.slope, s.base - s.slope * s.x_start),
    'anchor always x_end': lambda s: (s.slope, s.base - s.slope * s.x_end),
    'swapped base/slope': lambda s: (s.base, s.slope - s.base * (s.x_end if s.base < 0 else s.x_start)),
}


def planarity(o, out, model='engine'):
    """Second difference of the recovered depth-line intercept across rows.

    1/w is affine in screen space over a plane, so spans sharing one exact
    slope must have an intercept that is linear in y, and its second difference
    over three consecutive rows must vanish. This is what discriminates the
    anchor rule of field 2 from the naive alternatives.
    """
    fn = LINE_MODELS[model]
    by_slope = {}
    for y in range(SCREEN_H):
        for s in o.rows[y]:
            slope, intercept = fn(s)
            if slope == 0.0:
                continue
            by_slope.setdefault(struct.pack('<f', slope), {}).setdefault(y, intercept)
    for per_y in by_slope.values():
        ys = sorted(per_y)
        for k in range(1, len(ys) - 1):
            if ys[k - 1] != ys[k] - 1 or ys[k + 1] != ys[k] + 1:
                continue
            cs = [per_y[ys[k + d]] for d in (-1, 0, 1)]
            scale = max(abs(v) for v in cs) or 1.0
            out.append(abs(cs[0] - 2 * cs[1] + cs[2]) / scale)


def _pct(v, q):
    return v[min(len(v) - 1, int(q * len(v)))] if v else float('nan')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--game', type=Path,
                     help='game install directory; reads .ovx out of its *.t3d archives')
    src.add_argument('--dir', type=Path,
                     help='directory tree of already-extracted .ovx files')
    ap.add_argument('--out', type=Path,
                    help='also write one depth-map PNG per overlay here')
    ap.add_argument('--limit', type=int, default=0, help='stop after N overlays')
    args = ap.parse_args()

    source = (iter_archive_members(args.game) if args.game
              else iter_loose_files(args.dir))

    writer = None
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        fh = (args.out / 'overlays.csv').open('w', newline='', encoding='utf-8')
        writer = csv.writer(fh)
        writer.writerow(['source', 'entry', 'bytes', 'rows', 'spans',
                         'covered_px', 'coverage', 'inv_depth_lo', 'inv_depth_hi', 'png'])

    counters = Counters()
    bytes_in = 0
    n = ok = 0
    failures = []
    content_fail = []
    vcont = []
    plane = {k: [] for k in LINE_MODELS}
    for group, name, data in source:
        n += 1
        bytes_in += len(data)
        try:
            o = parse(data, name)
        except OvxError as exc:
            failures.append('%s/%s: %s' % (group, name, exc))
            continue
        ok += 1
        counters.bump('rows', o.row_count)
        counters.bump('spans', o.span_count)
        counters.bump('covered_px', o.covered_pixels)
        if o.span_count == 0:
            counters += 'empty overlay (no populated rows)'
        bad = check(o, data, counters)
        check_rejected_models(data, o, counters)
        vertical_continuity(o, vcont)
        for model in LINE_MODELS:
            planarity(o, plane[model], model)
        if bad:
            content_fail.append('%s/%s: %s' % (group, name, '; '.join(bad)))

        if writer is not None:
            rows, lo, hi = depth_image(o)
            png = '%s.png' % Path(name).stem
            write_depth_png(args.out / png, rows)
            writer.writerow([group, name, len(data), o.row_count, o.span_count,
                             o.covered_pixels,
                             '%.4f' % (o.covered_pixels / (SCREEN_W * SCREEN_H)),
                             '%.8g' % lo, '%.8g' % hi, png])
        if args.limit and n >= args.limit:
            break

    if writer is not None:
        fh.close()

    print('overlays found       : %d (%d bytes)' % (n, bytes_in))
    print('parsed ok            : %d' % ok)
    print('parse errors         : %d' % len(failures))
    print('content-check failures: %d' % len(content_fail))
    for line in (failures + content_fail)[:10]:
        print('   FAIL', line)
    print()
    print('populated rows       : %d' % counters.get('rows', 0))
    print('span records         : %d' % counters.get('spans', 0))
    print('covered pixels       : %d of %d (%.1f%%)'
          % (counters.get('covered_px', 0), n * SCREEN_W * SCREEN_H,
             100.0 * counters.get('covered_px', 0) / max(1, n * SCREEN_W * SCREEN_H)))
    print()
    for k in sorted(counters):
        if k in ('rows', 'spans', 'covered_px'):
            continue
        print('  %-44s %d' % (k, counters[k]))
    print()
    vcont.sort()
    print('vertical 1/w continuity over %d overlapping span pairs:' % len(vcont))
    for q in (0.5, 0.9, 0.99, 0.999):
        print('    p%-6s %.3e' % (q, _pct(vcont, q)))
    print('    fraction < 1%%  %.5f' % (sum(1 for v in vcont if v < 0.01) / max(1, len(vcont))))
    print()
    print('planarity, |2nd difference of intercept| / scale, per candidate reading:')
    for model, vals in plane.items():
        vals.sort()
        print('  %-22s n=%-8d median %.3e  p90 %.3e  p99 %.3e  frac<1e-4 %.5f'
              % (model, len(vals), _pct(vals, 0.5), _pct(vals, 0.9), _pct(vals, 0.99),
                 sum(1 for v in vals if v < 1e-4) / max(1, len(vals))))
    return 1 if (failures or content_fail) else 0


if __name__ == '__main__':
    raise SystemExit(main())
