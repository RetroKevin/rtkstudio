# The modkit: browsing, editing and patching

Everything else in this repo reads the game. This is the part that writes.

It is built around one rule: **the install is never modified.** Edits are
kept in a mod project directory beside the repo, and a build produces a
complete, separate copy of the game with those edits folded in. If you delete
the output directory you are back where you started.

## Running it

```powershell
# read-only browsing
python tools/viewer.py

# browsing plus editing, with edits kept in mods/example
python tools/viewer.py --mod mods/example
```

It serves on `http://127.0.0.1:8765/`, binds to loopback only, and opens your
browser. No arguments are needed: `--game` defaults to the directory above
the repo and the cache lives beside the repo, so it works the same whichever
directory you launch it from. Pass `--game` if your install is elsewhere.

The first run scans the install, which takes about half a second, and caches
the result in `out/assetdb.json`. Later runs load that in about 40 ms. Pass
`--rebuild` after changing the install, and `--port` if 8765 is taken.

**If it looks stuck on "indexing".** It shouldn't any more, but the two
causes were worth fixing and are worth knowing:

- *The cache recorded whichever spelling of the path you passed.* `--game ".."`
  and the absolute path are the same directory but compared unequal, so two
  tools using different spellings each forced a rebuild and overwrote the
  cache for the other. Paths are resolved before comparison now.
- *The scan walked `_decomp` and threw the results away.* The repo sits
  inside the install, and `out/` holds tens of thousands of derived files —
  including whole rebuilt copies of the game — so the walk paid to stat
  33,136 files it then discarded. It prunes as it goes now, which took a
  cold scan from 3.6 s to 0.5 s.

A third problem produced no error at all: `http.server` sets
`allow_reuse_address`, and on Windows that lets a second instance bind a port
something else is already listening on. Two viewers would both appear to
start and requests would land on either one. The server now refuses to share
its port and says so.

## One address space

`tools/assetdb.py` flattens the three places assets live into a single key,
so everything downstream refers to anything by one string:

| key | where it lives |
| --- | --- |
| `res/00088_bHaldmap_` | a resource in `RTKRES.bin` / `RTKRES.000` |
| `t3d/C0.t3d/000101cm.di_` | a member of a `.t3d` FastFile archive |
| `file/Worlds/rtkworld.wlx` | a loose file in the install |

That comes to **22,545 assets**: 10,674 members across the 144 `.t3d`
archives, 8,108 resources and 3,763 loose files. The index classifies each
into a kind — image, sprite, text, anim, depth, audio, widget, fx, rig,
script, video, palette, world — which is what the viewer filters on and what
decides how a thing is previewed.

**`widget` exists because of a mistake worth recording.** RTKRES has resource
types named `TEXT` and `SCRIPT`, and the obvious reading is that they hold
text. They do not. All 352 `TEXT` resources are fixed 44-byte binary records
and `SCRIPT` is an 8-byte pair; not one of the 391 is printable. Classifying
them as text made the viewer render them as mojibake *and* offer a text
editor that silently destroyed the record — which it duly did to resource 13
during testing, before this was caught. They are now their own kind,
previewed as a labelled word dump and editable only as raw bytes.

## Previewing

`tools/preview.py` is the one place that picks a decoder and normalises the
result to something a browser can show: PNG for images, depth overlays and
palettes; text for scripts and narration; the raw stream for audio and video;
a structured summary plus a hex tail for the container formats. Anything it
cannot interpret degrades to a hex dump rather than failing.

Two notes worth knowing:

- **Bitmaps get their palette from the screen that draws them.** RTKRES has
  5,089 bitmaps and 13 palettes, and the bitmaps carry no palette of their
  own — the engine realises one palette at a time and blits whatever is
  current against it. The viewer picks the palette recovered from the
  engine's `RtSetPalette` call sites, which resolves **2,566 of the 5,089**;
  the remaining 2,523 fall back to the boot palette `pIntfacePal`.

  The detail line says which of those happened, because they are not equally
  trustworthy. "from the screen that draws it" means there is positive
  evidence. "engine default — no screen palette found" means only that no
  `RtSetPalette` was found on a path reaching that bitmap, which is an
  absence of evidence, not evidence of absence. For those, try the dropdown.
  See [`palette-map.md`](palette-map.md).
- **`.ktx` narration preview is lossy.** Bytes above `0x7f` render as spaces,
  so editing a `.ktx` that contains them will not round-trip those bytes.

## Editing

`tools/encoders.py` is the only place that decides how an edit becomes game
bytes. Which editor the UI offers depends on the asset:

- **text** — edit in place. The original container is restored on save, so a
  `.def`, `.tbl` or `.rtk` is re-wrapped in its PyroTechnix gzip envelope.
  The gzip is written with `mtime=0` so builds are reproducible.
- **image** — upload a PNG from any paint program, then it is encoded back
  to `.di_` or an RTKRES bitmap. A `.di_` carries its own palette and is
  re-indexed onto that. An RTKRES bitmap does not, so it is indexed against
  **the palette you were viewing when you saved** — which is why picking the
  right one in the dropdown matters before you edit, not just to look at it.
- **audio** — upload a RIFF/WAVE file.
- **anim** — the 3D pane on a `.trk` or character `.adf`. Characters are
  hierarchical sprites (a skeleton with 2D artwork on each bone). Pick a
  character (default James — conversation tracks are not bound to one
  person), swap any compatible `.trk`, scrub, and edit a joint's rotation
  and translation. **Save** writes the track through
  `rtktrack.Track.to_bytes()` into the mod. **Duplicate as new** copies it
  under a new 7-character stem as `file/Tracks/{stem}.trk`. Register the
  stem in `ConversationTracks.tbl` if you want the game to play it as
  dialogue; otherwise it is a raw extra the viewer can play and a build
  will copy. `.trx` lip-sync is a separate text file and is not rewritten
  here.
- **raw** — upload replacement bytes, stored verbatim. This always works, for
  any asset, and is the fallback for formats with no encoder.

Nothing is written to the install at any point. Saving an edit writes one
file into the mod project.

Two things to know before editing art, both measured rather than assumed
(see [`image-write.md`](image-write.md)):

- **Save indexed PNGs, not truecolour.** 1,572 of the 1,585 backdrop
  palettes contain the same RGB in more than one slot, and the engine does
  not treat duplicate slots as interchangeable. An indexed PNG preserves
  which slot you meant; a truecolour one can only be quantized back by
  colour, which picks an arbitrary one of the duplicates.
- **Re-encoded RTKRES bitmaps get bigger.** There is a decoder for both
  shipped codecs but no *compressor*, so edits are written in the format's
  uncompressed stored mode. One bitmap is unremarkable; re-encoding the
  whole archive would take it from 48.9 MB to 94.9 MB. `.di_` has no such
  problem — it is zlib either way, and re-encoding all 1,585 at level 9 is
  slightly smaller than shipped.

## The mod project

A project is a directory you can keep in version control and hand to someone
else. It holds only what you changed:

```
mods/example/
    mod.json          name, version, description
    overrides.json    asset key -> override file, size, sha1, provenance
    overrides/*.bin   the replacement asset, already in game format
```

Overrides are stored **already encoded**, so building does not re-run an
encoder and a project built today builds the same way later.

## Building

**Build modded copy** writes a complete, playable copy of the game somewhere
else — by default `out/builds/<mod name>`. Unaffected files are copied
straight through; containers holding an edited member are rebuilt from the
original plus the overrides.

The output path is guarded. The repo itself lives *inside* the install
directory, so "is the output under the game?" is not the test. What matters
is whether the build could land on a file the copy walk also visits, and that
walk skips `_decomp`. So `out/builds/example` is allowed and
`../GameData` is refused.

A build of the 850 MB install takes a few seconds and produces 3,935 files.
Verifying one against the install with a full SHA-1 comparison showed exactly
one file differing — the one that was edited — and zero files in the install
with a recent modification time.

## Patches and DLC

**Export patch** zips the mod project alone, without any game data, into
`out/patches/<name>.rtkmod.zip`. That archive contains `mod.json`,
`overrides.json` and the changed assets, and nothing else — for the example
above, 66 KB. Someone else applies it to their own copy with
`ModProject.import_patch()` followed by a build.

This is the honest distribution boundary: a patch carries **your** changes.
Anything derived from the shipped assets is still Sierra's, so a patch is
appropriate to share only where the changed bytes are your own work.

## Command line

The same thing without the browser:

```powershell
python tools/modproject.py --mod mods/example status
python tools/modproject.py --mod mods/example --game ".." build --out out/builds/example
python tools/modproject.py --mod mods/example patch
```

## Limits

- `.ktx` text above `0x7f` does not survive a text round-trip, as above.
- There is no bitmap *compressor*, so re-encoded RTKRES bitmaps are stored
  uncompressed, as above.
- There is no encoder for `.ovx`, `.bex`, `.adf`, `.spx`, `.grx` or the
  sprite resource types. These can still be replaced with raw bytes, but
  nothing validates the result.
- Animations (`.trk`) re-serialise byte-exact, so the data path is proven,
  but there is no animation *editor* — only raw replacement.
- The `.avi` cutscenes are GOG's XviD re-encodes, not original assets.
