# PyroTechnix container (`.def`, `.rtk`, `.tbl`, and some `.txt`)

A thin wrapper around gzip used for the game's text data files.

```
"(c) 1998 PyroTechnix,Inc." 0x1A   <raw gzip stream>
```

That is 25 ASCII bytes followed by a SUB byte (`0x1A`, the DOS end-of-text
marker that makes `TYPE file` stop before the binary tail), then a plain gzip
member. Nothing is encrypted; `gzip.decompress` on the remainder is enough.

The container is also documented by [`nickgal/rtk-cli`](https://github.com/nickgal/rtk-cli).

## Results on this release

`tools/pyro_inflate.py` scans the install tree and inflates every file bearing
the signature. Across the 3,935 files in the GOG release, 35 are containers:

| | |
|---|---|
| files inflated | 35 |
| failures | 0 |
| compressed | 1,260,044 bytes |
| inflated | 10,582,744 bytes |

## What comes out

The payloads are human-readable source, comments intact. They are not a
decompilation — this is the original authored text, merely compressed.

- `GameData/RtkGame.def` (60 KB → 530 KB) — global rules, inventory and
  item definitions, written with C preprocessor directives (`#define
  MAX_ITEMS_CAN_CARRY 40`, `INV_CLASSLIMIT_*` bit flags, and so on).
- `GameData/Chapter{0..10}/Chapter*.def` — per-chapter content. These are the
  largest: `Chapter3.def` inflates to 1.19 MB, `Chapter1.def` to 1.07 MB.
- `GameData/Chapter*/Loc_All.def` — per-chapter localisation strings.
- `GameData/*.tbl` — character, shop and conversation tables.
- `*.rtk` — saved games and the in-game books, same container.

## Grammar sketch

The `.def` files use `begin` / `end` blocks (5,516 and 5,542 of them across
the chapter files) with a leading keyword per block. The most common block
heads give a good sense of the engine's model:

| Count | Keyword |
|---|---|
| 3,472 | `View` |
| 988 | `LightDarkDef` |
| 545 | `Desc` |
| 533 | `Scene`, `AmbientLight`, `Fog`, `Level` |
| 223 | `SceneDef`, `SceneRef` |
| 168 | `TimerDef` |

Scenes are declared with `SceneDef` and referenced by id (`SceneRef
S00010001`), so chapter files are essentially a scene graph plus timers,
lighting and descriptive text.

This, rather than the 39 tiny SCRIPT resources in `RTKRES`, is where the
game's logic actually lives.
