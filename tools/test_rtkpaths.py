"""Relative [Directories] paths become absolute, and the rest of the ini stays."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtkpaths

STEAM = """[Directories]
GameDataDir=.\\GameData\\
WorldDir=.\\Worlds\\
BGDir=.\\Bkgnd\\
TrackDir=.\\Tracks\\
AudioDir=.\\Audio\\
SFXAudioDir=.\\Audio\\
CinematDir=.\\Cinemats\\
[Audio]
MasterVolume=1.000000
MusicEnabled=1
"""

FOLDERS = ("GameData", "Worlds", "Bkgnd", "Tracks", "Audio", "Cinemats")


def _install(root: Path) -> None:
    for name in FOLDERS:
        (root / name).mkdir()
    (root / "RTKRONDOR.INI").write_bytes(STEAM.replace("\n", "\r\n").encode("ascii"))


def test_relative_becomes_absolute():
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp)
        _install(game)
        before = (game / "RTKRONDOR.INI").read_bytes()
        report = rtkpaths.apply_directories(game, platform="win32")
        assert report["wrote"] is True
        assert "TrackDir" in report["changed"]
        text = (game / "RTKRONDOR.INI").read_bytes().decode("mbcs")
        assert "MasterVolume=1.000000" in text
        assert "MusicEnabled=1" in text
        track = str((game / "Tracks").resolve()) + "\\"
        assert "TrackDir=%s" % track in text
        assert ".\\Tracks\\" not in text
        assert (game / rtkpaths.BACKUP_NAME).read_bytes() == before
        again = rtkpaths.apply_directories(game, platform="win32")
        assert again["wrote"] is False
        assert (game / rtkpaths.BACKUP_NAME).read_bytes() == before
        assert (game / "FixDirectories.bat").is_file()
        assert (game / "FixDirectories.ps1").is_file()


def test_proton_form_is_clean_relative():
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp)
        _install(game)
        report = rtkpaths.apply_directories(game, platform="linux", helper=False)
        assert report["wrote"] is True
        text = (game / "RTKRONDOR.INI").read_text(encoding="utf-8")
        assert "TrackDir=Tracks/" in text
        assert ".\\Tracks\\" not in text
        assert not (game / "FixDirectories.bat").exists()


def test_matching_absolute_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp)
        _install(game)
        rtkpaths.apply_directories(game, platform="win32")
        stamped = (game / "RTKRONDOR.INI").read_bytes()
        report = rtkpaths.inspect_directories(game, platform="win32")
        assert report["needs_fix"] is False
        assert report["missing_folders"] == []
        rtkpaths.apply_directories(game, platform="win32")
        assert (game / "RTKRONDOR.INI").read_bytes() == stamped


def test_existing_absolute_on_another_drive_is_kept():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        game = root / "install"
        other = root / "gog"
        _install(game)
        _install(other)
        lines = ["[Directories]"]
        for key, folder in rtkpaths.DIRECTORY_FOLDERS:
            lines.append("%s=%s\\" % (key, other / folder))
        lines.append("[Audio]")
        lines.append("MusicEnabled=1")
        (game / "RTKRONDOR.INI").write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
        report = rtkpaths.inspect_directories(game, platform="win32")
        assert report["needs_fix"] is False
        before = (game / "RTKRONDOR.INI").read_bytes()
        applied = rtkpaths.apply_directories(game, platform="win32")
        assert applied["wrote"] is False
        assert (game / "RTKRONDOR.INI").read_bytes() == before


def test_build_copy_retargets_even_when_the_source_path_exists():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        game = root / "install"
        _install(game)
        report = rtkpaths.apply_directories(game, platform="win32", force=True, helper=False)
        assert report["wrote"] is True
        text = (game / "RTKRONDOR.INI").read_text(encoding="mbcs")
        assert "TrackDir=%s\\" % (game / "Tracks").resolve() in text


def test_period_in_a_folder_name_uses_a_junction():
    import os
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        game = root / "GOG.com" / "Return to Krondor"
        links = root / "links"
        links.mkdir()
        link = links / "RtK"
        _install(game)
        try:
            report = rtkpaths.apply_directories(
                game, platform="win32", clean_dir=links, helper=False)
            assert report["wrote"] is True
            assert report["dotted"] == "GOG.com"
            text = (game / "RTKRONDOR.INI").read_bytes().decode("mbcs")
            assert "GOG.com" not in text
            assert "TrackDir=%s\\" % (link / "Tracks") in text
            assert link.is_dir()
            again = rtkpaths.apply_directories(
                game, platform="win32", clean_dir=links, helper=False)
            assert again["wrote"] is False
        finally:
            if link.exists():
                os.rmdir(link)


def test_missing_tracks_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp)
        _install(game)
        (game / "Tracks").rmdir()
        report = rtkpaths.inspect_directories(game, platform="win32")
        assert "Tracks" in report["missing_folders"]
        assert report["needs_fix"] is True


if __name__ == "__main__":
    test_relative_becomes_absolute()
    test_proton_form_is_clean_relative()
    test_matching_absolute_is_left_alone()
    test_missing_tracks_is_reported()
    print("ok")
