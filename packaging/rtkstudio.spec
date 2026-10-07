# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone studio (Windows and Linux).

Build on the target OS (no cross-compile):

    pip install -r requirements-desktop.txt
    pyinstaller packaging/rtkstudio.spec

Output is dist/rtkstudio/ (onedir). Zip that folder to ship.
Flip CONSOLE to True for a debug build that keeps a terminal.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# False = --windowed (no console). True = debug terminal.
CONSOLE = False

ROOT = Path(SPECPATH).resolve().parent
TOOLS = ROOT / "tools"
WEB = TOOLS / "web"

hidden = [
    "app_paths",
    "assetdb",
    "encoders",
    "imagecodec",
    "modproject",
    "palettemap",
    "preview",
    "pyro_inflate",
    "rtkalchemy",
    "rtkbex",
    "rtkbitmap",
    "rtkcharacter",
    "rtkcombat",
    "rtkdef",
    "rtkdialog",
    "rtkfind",
    "rtklaunch",
    "rtkframe",
    "rtkdib",
    "rtkfx",
    "rtkgameshot",
    "rtkitems",
    "rtkmedia",
    "rtkovx",
    "rtkres",
    "rtkres_write",
    "rtkscene",
    "rtkshops",
    "rtkspx",
    "rtkt3d",
    "rtkt3d_write",
    "rtktext",
    "rtktrap",
    "rtktrack",
    "rtkui",
    "rtkworld",
    "tkinter",
    "tkinter.filedialog",
    "viewer",
]
hidden += collect_submodules("webview", on_error="ignore")
# pywebview backends: Edge WebView2 on Windows (pythonnet), GTK on Linux.
hidden += [
    "bottle",
    "proxy_tools",
]
if sys.platform == "win32":
    hidden += [
        "clr",
        "clr_loader",
        "pythonnet",
    ]

datas = [(str(WEB), "web")]
datas += [(str(ROOT / "packaging" / "rtkstudio.ico"), ".")]
datas += collect_data_files("webview")
datas += [
    (str(TOOLS / "rtkframe" / "rtkframe.exe"), "rtkframe"),
    (str(TOOLS / "rtkframe" / "rtkframe.dll"), "rtkframe"),
]

a = Analysis(
    [str(TOOLS / "desktop.py")],
    pathex=[str(TOOLS)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rtkstudio",
    icon=str(ROOT / "packaging" / "rtkstudio.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="rtkstudio",
)
