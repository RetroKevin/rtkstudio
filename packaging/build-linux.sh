#!/bin/sh
# Build dist/rtkstudio/rtkstudio on the machine where it will run.
# PyInstaller cannot cross-compile, so this has to run on Linux.
set -eu
cd "$(dirname "$0")/.."

if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y gcc pkg-config libgirepository1.0-dev libcairo2-dev \
        gir1.2-gtk-3.0 python3-tk python3-venv
    sudo apt-get install -y gir1.2-webkit2-4.1 || sudo apt-get install -y gir1.2-webkit2-4.0
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y gcc pkgconf cairo-gobject-devel gobject-introspection-devel \
        gtk3 python3-tkinter python3-devel
    sudo dnf install -y webkit2gtk4.1 || sudo dnf install -y webkit2gtk4.0
else
    echo "Install GTK 3, WebKitGTK, Python 3, and tkinter, then re-run this script."
fi

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "PyGObject>=3.48"
python -m pip install -r requirements-desktop.txt
python -m PyInstaller packaging/rtkstudio.spec --noconfirm
cp packaging/LINUX.txt dist/rtkstudio/LINUX.txt
echo "Built dist/rtkstudio/rtkstudio"
