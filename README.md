# RtKStudio

RtKStudio is a desktop modding tool for **Return to Krondor**. It opens a
game install you already own, lets you browse and edit that install, and
stores every change in a mod project of your own.

The window is a set of studios: assets, characters, items, scenes, interface,
dialog, combat, traps, effects, alchemy, and shops. A build writes a separate
copy of the game with your edits applied. The install you started from is
left untouched, except **Fix folder paths** and **Repair launch settings**,
which write `RTKRONDOR.INI` and keep a backup.

## Disclaimer

This repository contains **no game files**. There is no executable from the
game, no resource archive, no picture, no audio, no script, and no extracted
export. You obtain those files yourself, from a legal copy you own.

The authors and contributors are **not liable** for how you use this program,
or for how you use any game files, mods, or copies you make with it. The
software is provided as is, without warranty. See [LICENSE.txt](LICENSE.txt).

This build was developed and tested against the **GOG release, version
1.00.6**. That is the version it knows. Trouble with any other version,
re-release, dump, or copy is outside this project. Those cases are not a
defect in RtKStudio and they are not something the authors are responsible
for.

Return to Krondor is a commercial game (Sierra / PyroTechnix, 1998). GOG,
Sierra, and PyroTechnix are their owners' names. This project is not
affiliated with them.

## What you need

- A legal GOG install of Return to Krondor **v1.00.6**.
- The install folder must contain `RTKRES.bin`. GOG also ships `RTKRES.h`
  beside it. The studio uses that header for resource names.
- Windows 10 or 11, with the Edge WebView2 runtime. That runtime is already
  present on current Windows 10 and 11. Or Linux, using the Linux download
  below. The editor runs there. The game executable does not.

The program looks for an install in this order:

1. The folder you picked last time.
2. The folder the program is in, then the folder above it.
3. Common GOG and Steam locations (`GOG Games\Return To Krondor`, GOG Galaxy,
   and a Steam `steamapps\common\Return to Krondor`).

If none of those contain `RTKRES.bin`, a folder dialog asks you to select the
install. Point it at the folder that contains `RTKRES.bin`, not at a single
file inside it.

## Download and first launch

Both builds are on the releases page of this same repository. The gold K
with a wrench is the studio. It is the editor, not the game.

**Windows.** Download `RtKStudio-1.2.0-windows.zip`, unpack it, and run
`rtkstudio.exe`.

**Linux.** Download `RtKStudio-1.2.0-linux-x64.tar.gz`, unpack it, and follow
`LINUX.txt` in that folder. In short:

```sh
sudo apt install gir1.2-gtk-3.0 gir1.2-webkit2-4.1
chmod +x rtkstudio
./rtkstudio
```

That archive is built on Ubuntu 24.04. It runs on Ubuntu 24.04, Ubuntu 26.04,
and other systems with glibc 2.39 or newer, after WebKitGTK 4.1 is installed.
Ubuntu 22.04 and other distributions should build it on that machine instead:

```sh
sh packaging/build-linux.sh
```

The game install is the Windows GOG copy either way. On Linux, point the
editor at the folder that contains `RTKRES.bin`. Build and Export patch work
there. Play starts `RtK.exe`, which is a Windows program, so use Play on
Windows.

On the first launch, choose the GOG install if the program does not find it.
The choice is remembered. The studio then indexes the install. That index is
a cache on your machine. It is not part of this repository.

Edits are on as soon as the window is open. They go to a mod project under
your user data, not into the GOG folder.

Video previews use VLC or ffmpeg if one of them is on `PATH`. They are not
bundled.

## The one rule

**The install is never modified.**

Saving an edit writes a file into the mod project. **Build modded copy**
makes a new folder and fills it with a copy of your game plus those edits.
**Play** launches that copy. **Export patch** zips the mod project alone.

Deleting the build folder leaves you with the original install.

## Studios

The bar across the top switches studios. Theme, scale, and pane layout are
remembered in the browser storage of the window.

| Studio | What it edits |
| --- | --- |
| Assets | Every file the install contains: resource archive, `.t3d` archives, and loose files. Search by file, or inside records (characters, items, dialog, scenes, shops). Preview images, text, audio, models, and depth. Replace an image from a PNG, replace audio from a WAVE file, or replace raw bytes. |
| Character | The 3D figure. Click a body part, change its size, and open that part's pixel art. |
| Items | Weapons, shields, armor, rings, and amulets from `MagicInvItem.txt`. Bag icons, and the pixels that hang on the model. |
| Scene | Chapter, scene, and view. Walk-into regions and teleport plates. Drag to move, then save. |
| UI | The 640×480 screens. Click a control to see which dialog it is and what the click does. Drag to move. |
| Dialog | Conversation trees in the chapter scripts. Choice labels, and when a line is allowed to play. |
| Combat | In-scene combat definitions, and the character sheet, model, and bag in `Chars.tbl`. |
| Traps | Trap and lock fields on a character, and script trap types. |
| Effects | Spell and skill pictures, and the sprites they swap in. |
| Alchemy | The bench formulas, potion icons, and the pictures a fight plays. |
| Shops | Shop stock, and the inventories characters start with. |

Undo, Redo, and History sit on the mod bar. One save is one history step.
The step count is capped.

### Pictures and palettes

Authored art is 8-bit. The game draws it through the 16-bit frame, so the
studio's previews, chips, and the character view show that displayed color.
The bytes written back into a mod are the authored palette entries, not the
preview.

An RTKRES bitmap does not carry its own palette. The studio picks the palette
of the screen that draws it, using the resource id. Save an indexed PNG when
you paint, so duplicate colors stay in the slot you chose. Details are in
[docs/image-write.md](docs/image-write.md) and
[docs/palette-map.md](docs/palette-map.md).

### What still has no encoder

These can be replaced by uploading raw bytes. The studio does not check that
the replacement is a valid file of that type.

- `.ovx` depth overlays
- `.bex` behavior graphs, beyond the fields the effects studio already edits
- `.adf` / `.spx` / `.grx` sprite containers, beyond the character and item editors
- `.ktx` narration bytes above `0x7f` do not survive a text round-trip

## Building, patches, and Play

**Build modded copy** copies your install to a new folder and rebuilds only
the archives that contain an edit (`RTKRES.bin` / `RTKRES.000`, or a `.t3d`).
Everything else is copied through. The output is refused if it would land on
top of the install.

From the packaged program, that folder is `out\builds\<mod name>` in the
working directory. Double-clicking `rtkstudio.exe` uses the folder the exe is
in, so the build appears next to the program as `out\builds\default`.

**Export patch** writes `out\patches\<mod name>.rtkmod.zip`. The zip holds
`mod.json`, `overrides.json`, and the files you changed. It does not hold the
rest of the game. That is the archive to keep, and the only archive that is
reasonable to hand to someone else.

A patch is still your responsibility. If a changed file is a modified piece
of the original game, you do not gain the right to publish those bytes by
running this tool. Share a patch when the changed material is your own work.
Do not upload a build folder. A build is a full copy of the game.

Apply someone else's patch by unpacking it into a mod directory and building
against your own install:

```powershell
python tools/modproject.py --mod path\to\their-mod --game "D:\GOG\Return To Krondor" build --out out\builds\their-mod
```

**Play** builds that separate copy, turns on the game's developer start
options in that copy, and launches the copy. From the scene studio it can
start at the open chapter and scene. Play refuses to write the developer
change onto the installed `RtK.exe`. Only the copy is touched. Play is a
Windows action, because it starts `RtK.exe`.

Playing the original GOG game on a modern widescreen monitor is a different
project: [return-to-krondor-display](https://github.com/RetroKevin/return-to-krondor-display).
That patch is not part of RtKStudio, and RtKStudio does not include it.

## Where files go

| What | Packaged program on Windows | Running from source |
| --- | --- | --- |
| Last install, and which mod is open | `%LOCALAPPDATA%\RtKStudio\config.json` | same file |
| Mod project | `%LOCALAPPDATA%\RtKStudio\mods\default` | `--mod`, or the same default |
| Asset index | `%LOCALAPPDATA%\RtKStudio\assetdb.json` | `out\assetdb.json` in this repo |
| Modded game | `out\builds\<name>` in the working directory | same |
| Patch zip | `out\patches\<name>.rtkmod.zip` | same |

On Linux those three user-data files live under `~/.local/share/rtkstudio/`
instead of `%LOCALAPPDATA%\RtKStudio`.

A mod directory looks like this:

```
mods/default/
    mod.json           name, version, description
    overrides.json     which asset each file replaces
    overrides/         the replacement, already in game format
    history.json       undo stack
    kits/              character body edits
    items/             item mesh scale and related notes
```

The command line does the same work without the window:

```powershell
python tools/modproject.py --mod path\to\mod status
python tools/modproject.py --mod path\to\mod --game "D:\GOG\Return To Krondor" build --out out\builds\my-mod
python tools/modproject.py --mod path\to\mod patch --out out\patches\my-mod.rtkmod.zip
```

## Run from source

Python 3.11 or newer.

```powershell
pip install -r requirements-desktop.txt
python tools/desktop.py --game "D:\GOG\Return To Krondor"
```

`--game` is optional after the first successful launch.

The browser path binds `http://127.0.0.1:8765/` and does not open a mod
unless you pass one:

```powershell
python tools/viewer.py --game "D:\GOG\Return To Krondor" --mod mods\my-mod
```

On Linux, install WebKitGTK (`gir1.2-webkit2-4.1` on Ubuntu 24.04 and Debian,
`gir1.2-webkit2-4.0` on Ubuntu 22.04, `webkit2gtk4.1` on Fedora) and
`python3-tk` for the folder dialog, then run the same command. Or run
`sh packaging/build-linux.sh`, which installs those packages and produces
`dist/rtkstudio/rtkstudio`.

## Build the Windows program

Build on Windows. PyInstaller does not cross-compile.

```powershell
pip install -r requirements-desktop.txt
pyinstaller packaging/rtkstudio.spec
```

Zip the folder `dist\rtkstudio\` and ship that folder. Do not put a game
install, `out\`, or a build of the game inside the zip.

Set `CONSOLE = True` at the top of `packaging/rtkstudio.spec` and rebuild if
you need the terminal for a problem report.

## Format notes

The files under [docs/](docs/) describe the formats the studios read and
write. They are notes about structure. They are not a copy of the game, and
they are not required to use the window. A few of them mention research
scripts that are not in this repository. The studios run without those
scripts.

Start with [docs/desktop.md](docs/desktop.md), [docs/modkit.md](docs/modkit.md),
and [docs/image-write.md](docs/image-write.md). The per-subject notes are
[items](docs/items.md), [inventory](docs/inventory.md),
[dialog](docs/dialog.md), [combat](docs/combat.md), [traps](docs/traps.md),
[effects](docs/effects.md), [alchemy](docs/alchemy.md), [ui](docs/ui.md),
[scenes](docs/scene-runtime.md), and [animations](docs/animations.md).

## License

RtKStudio is MIT. See [LICENSE.txt](LICENSE.txt).

three.js r128, used for the character and scene views, is MIT. It is vendored
at `tools/web/vendor/` so the studios work offline. See
`tools/web/vendor/NOTICE.txt`.
