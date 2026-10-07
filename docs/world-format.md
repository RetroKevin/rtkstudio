# `Worlds/*.wlx` and `Worlds/*.ldx`

Reader: `tools/rtkworld.py`. Validator: `tools/validate_world.py`.

`.wlx` and `.ldx` are the same T3D FastFile container as `.trk`, documented in
`docs/track-format.md`. This document covers only what is specific to them:
header field `0x0c`, and the two chunk types no `.trk` uses.

**Result: `Worlds/rtkworld.wlx` parses.** 686 of its 688 payload bytes are
consumed by fields the engine demonstrably reads, the chunk stream ends on the
`ff ff ff ff` terminator, and the decoded contents are geometrically coherent.

> **On the line numbers below.** They are against `out/decompiled/` as it
> stands at the time of writing. `RtK.c` already shifted by ~300 lines while
> this work was in progress, so the stable anchor is the
> `// ===== FUN_100258e0 @ 100258e0 =====` banner, not the line number.
> `tools/lines.py t3dll.c FUN_100258e0` re-derives any citation.

---

## The one-line change `tools/rtktrack.py` would need

Delete the guard at lines 166–169:

```python
        if self.field_0c != 0:
            # FUN_10022970 takes a different branch (an object-table preload)
            # when this is non-zero. No shipped file does.
            raise ValueError(f"field_0c={self.field_0c} not supported")
```

**Header field `0x0c` has no effect on the byte layout.** It is a runtime
allocation count, so `rtktrack` can ignore it outright; deleting that guard
makes `rtktrack.Track` open `rtkworld.wlx` and walk both its chunks correctly.
Nothing else in the file needs to change for the container to parse.
(`rtktrack` will of course leave the 0x21 and 0x22 payloads untranslated,
which is what `tools/rtkworld.py` adds.) The branch comment is right that it
is an object-table preload; the "No shipped file does" is the part that
`Worlds/rtkworld.wlx` disproves.

While proving that, one separate pre-existing issue surfaced, which is *not*
required for `rtkworld.wlx` to parse but does affect it. Line 176 slices the
name list with the chunk count:

```python
        self.names = [s.decode("latin-1") for s in parts[:self.name_count]]
        #                                                  ^ header 0x08
        # should be self.field_18, i.e. header 0x18
```

`docs/track-format.md` records header `0x18` as "mirrors 0x08" and
`rtktrack.py` line 161 as "It mirrors name_count in every file", which is true
of every `.trk` and `.ldx` because each of their chunks is named.
`rtkworld.wlx` separates them: **2 chunks, 1 name**. Its header is

```
02 3d 50 54  00 55 01 00  02 00 00 00  01 00 00 00
 magic        version       chunks=2      field_0c=1
b0 02 00 00  0c 00 00 00  01 00 00 00
 max=688      names=12 B    field_18=1
```

and the 12-byte name block descrambles to `\0R000001\0\0\0\0`, i.e. exactly
one name for two chunks. So `0x18` is the number of names, not a mirror.
`FUN_10022b80` reads 0x1c bytes of header and never looks at `0x18` itself —
the name block is sized by `0x14` alone — so this is a refinement derived from
the data, not from the loader.

---

## Header field `0x0c`

### What it is

**The number of type-0x22 objects the file defines.** It is the capacity of a
runtime object table, and it changes nothing about the bytes on disk.

### Proof

`FUN_10022b80` (`out/decompiled/t3dll.c:27193`) reads the 0x1c-byte header and
binds field `0x0c` to the loader context at `ctx+0x34` (`t3dll.c:27217`).
`FUN_10022970` (`t3dll.c:27077`) then branches on it at `t3dll.c:27134`:

```c
if (local_18 == 0) {                      /* local_18 is ctx+0x34 */
LAB_10022b23:
    uVar4 = 1;
    if (local_20 != 0) {                  /* local_20 is ctx+0x2c, the chunk count */
      do {
        puVar2 = FUN_10022d60((int *)&local_4c);
        ...
      } while (uVar5 <= local_20);
    }
    goto LAB_100229ec;
}
if ((*(int *)(param_2 + 0x18) == 0) &&
   (local_10 = t3dAllocateMemory(local_18 << 6), local_10 != 0)) {
  iVar1 = t3dAllocateMemory(local_18 * 4);
  *(int *)(param_2 + 0x264) = iVar1;
  if (iVar1 != 0) goto LAB_10022b23;
}
```

Both arms fall into the **same** chunk loop at `LAB_10022b23`, which reads
exactly `header[0x08]` chunks either way. The non-zero arm only pre-allocates
two runtime arrays first: `field_0c * 0x40` bytes (kept at `ctx+0x3c`) and
`field_0c * 4` bytes (handed to the destination scene at `+0x264`). The
running index lives at `ctx+0x38` and is zeroed just before the loop
(`t3dll.c:27136`).

`FUN_100258e0`, the type-0x22 handler, is the consumer (`t3dll.c:29965`):

```c
if (*(uint *)(param_1 + 0x38) < *(uint *)(param_1 + 0x34)) {
  piVar12 = (int *)(*(int *)(param_1 + 0x3c) + *(uint *)(param_1 + 0x38) * 0x40);
  ...
  *(int *)(param_1 + 0x38) = *(int *)(param_1 + 0x38) + 1;   /* t3dll.c:30371 */
  return local_1c;
}
else {
  local_1c = (int *)0x0;     /* table full -> NULL -> the whole load fails */
}
```

So each 0x22 chunk claims the next `0x40`-byte slot, and when the table is
full the handler returns NULL, which aborts the load. That is why the field
must equal the 0x22 count exactly — too small and the file will not load at
all.

A secondary consequence worth noting: because the zero arm never allocates the
table, **a file with `field_0c == 0` cannot contain a 0x22 chunk** —
`ctx+0x34` would be 0 and the very first object would fail the bounds test.
The two features are therefore inseparable, which the sweep below confirms.

### Validation

`tools/validate_world.py` walks every T3D FastFile in the game install:

```
T3D FastFiles scanned      : 2089
non-FastFile files skipped : 10818
chunk walks that complete  : 2089/2089
field_0c histogram         : {0: 2088, 1: 1}
chunk type histogram       : {0x04: 468, 0x05: 29506, 0x06: 142, 0x08: 1806,
                              0x09: 1704, 0x10: 98, 0x11: 98, 0x12: 32652,
                              0x13: 32652, 0x14: 134, 0x19: 516, 0x1a: 516,
                              0x1b: 25, 0x1e: 1, 0x1f: 1, 0x21: 1, 0x22: 1,
                              0x2c: 8589}
files with field_0c != 0 or a 0x21/0x22 chunk:
    ('Worlds\rtkworld.wlx', 1, [0x21, 0x22])
```

`rtkworld.wlx` is the only file in the game with `field_0c != 0`, the only one
with a 0x21 chunk, and the only one with a 0x22 chunk — and it has exactly one
of each, with `field_0c == 1`. The prediction and the data agree on a sample
of one, which is all the game provides; the proof rests on the decompiled
branch, not on the count.

And the `.ldx` files still read identically through the untouched `rtktrack`:

```
=== Worlds/ parsed with tools/rtkworld.py ===
  flames.ldx    f0c=0 chunks=1  names=1  lightdefs=1  ends=708/712 term=True unconsumed=0
  fxblue.ldx    f0c=0 chunks=1  names=1  lightdefs=1  ends=80/84   term=True unconsumed=0
  fxgreen.ldx   f0c=0 chunks=1  names=1  lightdefs=1  ends=80/84   term=True unconsumed=0
  fxlblue.ldx   f0c=0 chunks=1  names=1  lightdefs=1  ends=84/88   term=True unconsumed=0
  fxlight.ldx   f0c=0 chunks=1  names=1  lightdefs=1  ends=292/296 term=True unconsumed=0
  fxorange.ldx  f0c=0 chunks=1  names=1  lightdefs=1  ends=80/84   term=True unconsumed=0
  fxpurple.ldx  f0c=0 chunks=1  names=1  lightdefs=1  ends=80/84   term=True unconsumed=0
  fxred.ldx     f0c=0 chunks=1  names=1  lightdefs=1  ends=76/80   term=True unconsumed=0
  fxyellow.ldx  f0c=0 chunks=1  names=1  lightdefs=1  ends=80/84   term=True unconsumed=0
  lights.ldx    f0c=0 chunks=14 names=14 lightdefs=14 ends=976/980 term=True unconsumed=0
  rtkworld.wlx  f0c=1 chunks=2  names=1  objects=1 bsps=1 ends=780/784 term=True unconsumed=2
  sample.ldx    f0c=0 chunks=1  names=1  lightdefs=1  ends=392/396 term=True unconsumed=0
  strobe.ldx    f0c=0 chunks=1  names=1  lightdefs=1  ends=248/252 term=True unconsumed=0
  parsed 13, failed 0

=== same .ldx files via tools/rtktrack.py (unchanged) ===
  identical header/chunk reading: 12 agree, 0 differ
  rtktrack on rtkworld.wlx: rejected with 'field_0c=1 not supported'
```

So the 12 `.ldx` are a control group: `rtkworld.py` is not a fork that drifted,
it reads them byte-identically to the module that already worked.

---

## Chunk 0x21 — the BSP tree

Handler: `FUN_10025800` (`out/decompiled/t3dll.c:29875`).

```
i32    field0           not read by the handler; 0 in the one real file
i32    node_count
node   nodes[node_count]      28 bytes each
```

Each node is 7 dwords on disk, scattered into an 8-dword runtime node
(`t3dll.c:29903-29921`):

| Disk | Type | Runtime slot | Meaning |
|---|---|---|---|
| `0`–`3` | f32 × 4 | `0`–`3` | the splitting plane — *inferred*, see below |
| `4` | i32 | `6` | unknown |
| `5` | i32 | `4` | **front child**, a 1-based node index; 0 = none |
| `6` | i32 | `5` | **back child**, same |

The child encoding is the proof that this is a tree. The handler turns each
index into a pointer as `base + idx * 8 - 8`, i.e. the classic 1-based index
with 0 reserved for the null link:

```c
if (puVar6[5] == 0) { *puVar5 = 0; }
else { *puVar5 = puVar4 + puVar6[5] * 8 + -8; }
```

It also allocates `(node_count + 1) * 0x20` bytes and 32-byte-aligns the base,
which fixes the runtime node at 8 dwords and so the on-disk node at 7.

**The plane is inferred, not proven.** `FUN_10025800` only copies those four
dwords; it never interprets them. Three things support the reading: the
structure is a binary tree with four leading floats, the one real node holds
`(0.0, 1.0, 0.0, 0.0)` — a unit normal and a zero constant, which is a plane
and is not plausible as anything else — and the sibling polygon and segment
code in the same file uses exactly this 4-float `{nx, ny, nz, d}` layout with
`t3dCalculateNormalToEdgePolygon` as the computed alternative. I did not find
the traversal function that consumes the tree, so the field order within the
plane (normal-then-constant versus constant-then-normal) rests on the sample
alone.

---

## Chunk 0x22 — a world object

Handler: `FUN_100258e0` (`out/decompiled/t3dll.c:29931`). The runtime object
is tagged `0x13` and occupies the `0x40`-byte table slot discussed above.

### Fixed header, 8 dwords

Proven by `local_24 = (uint *)(local_10 + 8)` (`t3dll.c:29972`) — the
handler's stream cursor starts eight dwords into the payload — and by the
individual copies at `t3dll.c:30065-30069`.

| Dword | Meaning | Proof |
|---|---|---|
| `0` | **name reference** | `t3dll.c:29975`; negative = byte offset into the name block, positive = object-table index, 0 = unnamed (and then `t3dAddEntryToDictionary` is skipped, `t3dll.c:30368`) |
| `1` | **flags** | see the table below |
| `2` | **object reference** | `t3dll.c:30052`; resolved via `t3dGetPointerFromDictionary` when negative, via `ctx[0x30] + ref * 4` when positive, then `t3dShareObject`'d |
| `3` | **vertex count** | `t3dll.c:30065`, used as `count * 0xc` bytes and `count * 3` dwords |
| `4` | unknown | `t3dll.c:30066`, copied to a runtime slot |
| `5` | **polygon count** | `t3dll.c:30067`, used as `count * 100` bytes of runtime polygons |
| `6` | **segment count** | `t3dll.c:30068`, used as `count * 0x18` bytes |
| `7` | unknown | `t3dll.c:30069` |

### Variable part, in stream order

```
f32    vertices[vertex_count][3]
poly   polygons[polygon_count]
seg    segments[segment_count]
u16    n;  u16 blob[n]
f32    sphere[4]        only if flags & 0x01
i32    extra1           only if flags & 0x02
i32    extra2           only if flags & 0x04
i32    n;  u8 user_data[n]        XOR-scrambled with the name-block key
```

### Object flag bits

| Bit | Effect |
|---|---|
| `0x01` | an explicit bounding sphere `{cx, cy, cz, r}` follows, instead of the one `FUN_100262d0` (`t3dll.c:30466`) derives from the vertex cloud |
| `0x02` | one extra dword follows (`t3dll.c:30330`) |
| `0x04` | one more extra dword follows (`t3dll.c:30334`) |
| `0x08` | copied to a runtime slot; **consumes no stream bytes** (`t3dll.c:30051`) |
| `0x20` | copied to a runtime slot; **consumes no stream bytes** (`t3dll.c:30318`) |

Bit 0 is worth spelling out because it is what makes the sphere identifiable.
`FUN_100262d0` computes the axis-aligned bounding box of the vertices, takes
its centre, then takes the root-sum-square of the per-axis maximum deviations
from that centre (`t3dll.c:30550-30554`). That is a bounding sphere, so the
four floats the flag substitutes for it are a bounding sphere too.

### Polygon

```
i32    flags
i32    index_count
i32    indices[index_count]
<material block>              FUN_10023810, t3dll.c:27921
f32    plane[4]               only if flags & 0x02
```

The runtime polygon is 25 dwords (`count * 100` bytes, stride `+ 0x19`).

| Flag | Effect |
|---|---|
| `0x01` | copy this polygon's plane to the parent object (`t3dll.c:30142`) |
| `0x02` | four explicit plane floats follow; otherwise `t3dCalculateNormalToPolygon` derives them (`t3dll.c:30132`) |

That if/else is what proves the four floats are a plane: the engine's own
alternative to reading them is computing the polygon normal.

The material block is read by `FUN_10023810` (`t3dll.c:27921`) and is itself
flag-gated on its second dword:

| Bit | Field |
|---|---|
| `0x01` | one dword |
| `0x02` | one dword |
| `0x04` | one float |
| `0x08` | a texture reference (name-block offset or object index) |
| `0x10` | nine floats — a UV basis |
| `0x20` | a length-prefixed list of UV pairs |
| `0x40` | a flag only; consumes nothing |

### Segment

```
i32    flags
i32    ref
i32    kind
<kind-dependent>
i32    n;  u8 blob[n]         only if flags & 0x04, XOR-scrambled
```

`ref` is a 1-based object-table index stored as `ref - 1`, with **0 meaning
"this object"** — the handler substitutes the running object index `ctx+0x38`
in that case (`t3dll.c:30191`). `flags & 0x01` sets a runtime boolean
(`t3dll.c:30265`); `flags & 0x04` appends the scrambled blob
(`t3dll.c:30272`).

`kind` dispatches at `t3dll.c:30200`. Anything not in this table jumps to the
failure label and aborts the chunk:

| `kind` | Extra stream bytes | Handling |
|---|---|---|
| `9` | 1 dword: a vertex index | `t3dll.c:30260`; the handler advances the cursor by 4 dwords total |
| `0xC` | 2 dwords: two vertex indices | `t3dll.c:30242`; caches the distance between them |
| `0xE` | `1 + n` dwords: a count then `n` vertex indices | `FUN_10024b60` with a NULL override and `param_7 = 0`, so the plane is **computed** by `t3dCalculateNormalToEdgePolygon` |
| `0x12` | 1 dword: a polygon index | `t3dll.c:30222`; `FUN_10024b60` is handed that polygon's own index array as its stream, so nothing more comes off the wire |
| `-15` | `1 + n + 4` dwords | as `0xE`, but `param_7` is `kind == -0xf`, so four explicit plane floats follow the indices (`t3dll.c:29112`) |

`FUN_10024b60` (`t3dll.c:29058`) builds a closed ring of `n` edges from `n`
indices, wrapping the last back to the first, caching each edge's length, and
finally records the dominant axis of the plane normal as 1, 2 or 3 by
magnitude (`t3dll.c:29138-29147`). That last detail is a second, independent
confirmation that slots 3–5 are a normal.

---

## What `rtkworld.wlx` actually contains

```
World(rtkworld.wlx, version=0x15500, chunks=2, field_0c=1, objects=1, bsps=1)
  names: ['R000001']
  max_chunk_size=688 (actual max 688)
  chunk stream ends at 780 of 784, terminator b'\xff\xff\xff\xff'
  unconsumed payload bytes per chunk: {0: 0, 1: 2}
  Bsp(1 nodes, field0=0)
    BspNode(plane=(0.0, 1.0, 0.0, 0.0), field4=1, front=0, back=0)
  WorldObject('R000001', flags=0x0, 8 vertices, 6 polygons, 6 segments)
    bounds [-100000.0, -100000.0, -100000.0] .. [100000.0, 100000.0, 100000.0]
    p0   Polygon(flags=0x1, indices=[0, 1, 2, 3]) Material(flags=0x7)
    p1   Polygon(flags=0x0, indices=[4, 7, 6, 5]) Material(flags=0x7)
    p2   Polygon(flags=0x0, indices=[4, 5, 1, 0]) Material(flags=0x7)
    p3   Polygon(flags=0x0, indices=[5, 6, 2, 1]) Material(flags=0x7)
    p4   Polygon(flags=0x0, indices=[6, 7, 3, 2]) Material(flags=0x7)
    p5   Polygon(flags=0x0, indices=[4, 0, 3, 7]) Material(flags=0x7)
    s0   Segment(ref=0, kind=-15, indices=[0, 1, 2, 3]) plane=[0, 0,  1,   0]
    s1   Segment(ref=0, kind=-15, indices=[4, 7, 6, 5]) plane=[0, 0, -1, 200]
    s2   Segment(ref=0, kind=-15, indices=[4, 5, 1, 0]) plane=[1, 0,  0,   0]
    s3   Segment(ref=0, kind=-15, indices=[5, 6, 2, 1]) plane=[0, -1, 0, 200]
    s4   Segment(ref=0, kind=-15, indices=[6, 7, 3, 2]) plane=[-1, 0, 0, 200]
    s5   Segment(ref=0, kind=-15, indices=[4, 0, 3, 7]) plane=[0, 1,  0,   0]
    trailing: u16_blob=b'' sphere=None extra=None,None user_data=b''
```

This is a **single untextured box, 200000 units on a side, centred on the
origin, with its faces pointing inward** — the outer shell of the world, and
almost certainly a placeholder. Several things cross-check:

- The 8 vertices are the exact corners of `[-100000, 100000]³`, in a
  consistent order (`z = -100000` face first, then `z = +100000`).
- The 6 polygons are 6 quads using each vertex exactly 3 times, which is the
  only way to close a box.
- The 6 segment planes carry **unit** normals, one per axis direction, each
  pointing into the box: the `z = -100000` face gets `(0, 0, +1)`, the
  `z = +100000` face gets `(0, 0, -1)`, and so on. Nothing about my field
  layout forces normals to come out unit-length or axis-aligned, so this is
  real validation rather than arithmetic.
- `max_chunk_size = 688` in the header equals the largest chunk actually
  present, as it does in all 2,089 FastFiles.
- Only polygon 0 has `flags & 1`, so exactly one polygon donates its plane to
  the object — which is what you would expect, since the flag overwrites a
  single slot.

686 of the 688 bytes of the 0x22 payload are consumed. The 2 left over are
`00 00`, which is consistent with the exporter padding to a 4-byte boundary:
the final field is the `i32` user-data length (zero here), and the chunk
stream resumes at a multiple of 4 either way.

---

## Open questions

- **The segments' fourth plane float is 0 or 200**, not `±100000`. The field
  *is* the plane constant — `FUN_10024b60`'s alternative is
  `t3dCalculateNormalToEdgePolygon`, so there is no doubt about what the
  engine does with it — but these particular values describe a box spanning
  `[0, 200]` per axis, not the `[-100000, 100000]` box the vertices describe.
  The normals match the faces; only the constants do not. The most likely
  explanation is that the file is a placeholder whose planes were authored at
  a different scale and never recomputed, and the engine would not notice
  because every polygon here has `flags & 2` clear, so the *polygon* planes
  are computed at load time. I cannot prove that from the binary.
- **BSP node disk word 4** (runtime slot 6) is `1` in the one real node. No
  consumer traced.
- **Object header dwords 4 and 7** are copied to runtime slots that nothing
  traced reads. Both are 0 in the one real object, so the data does not help.
- **Which function traverses the 0x21 tree.** `FUN_10025800` stores the root
  at `*(ctx[4] + 0xc)`; I did not find the reader, which is why the node plane
  is labelled inferred above.
- **Segment kinds 9, 0xC and 0x12 are untested.** Their stream consumption is
  read straight out of `FUN_100258e0`, but no shipped file uses them — all six
  segments in the only 0x22 chunk are kind `-15`. The kind-9 arm in particular
  is easy to get wrong: unlike every other arm it does not re-base the cursor,
  and advances by 4 dwords total rather than 3 plus its payload.
- **Material flag bits 0x01–0x04 and the 0x10 UV basis** are likewise
  untraced beyond their widths, since the one real material has flags `0x7`
  and no texture.
- **`field_0c` is only ever 0 or 1** in shipped data. The branch proves it is
  a count, but no file exercises a value above 1.
