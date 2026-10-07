"""Hardware Driver guids are cleared. A GOG-style Engine=1 with no Driver stays."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtklaunchcfg

BASE = """[Directories]
TrackDir=D:\\GoG\\Return To Krondor\\Tracks\\
[Options]
CombatStats=1
"""


def _write(folder: Path, graphics: str) -> None:
    text = (BASE + "[Graphics]\n" + graphics).replace("\n", "\r\n")
    if not text.endswith("\r\n"):
        text += "\r\n"
    (folder / "RTKRONDOR.INI").write_bytes(text.encode("ascii"))


def test_scaling_note_names_dpi():
    assert rtklaunchcfg.scaling_note(96) is None
    text = rtklaunchcfg.scaling_note(144)
    assert text is not None and "150%" in text and "12 points" in text


def test_hardware_guid_becomes_software():
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp)
        _write(game, "Gamma=1.000000\nEngine=1\nDriver={12345678-1234-1234-1234-1234567890AB}\nDriverDesc=NVIDIA\n")
        before = (game / "RTKRONDOR.INI").read_bytes()
        report = rtklaunchcfg.apply_launch(game)
        assert report["wrote"] is True
        text = (game / "RTKRONDOR.INI").read_bytes().decode("mbcs")
        assert "Engine=0" in text
        assert "Driver=" not in text
        assert "TrackDir=D:\\GoG\\Return To Krondor\\Tracks\\" in text
        assert "CombatStats=1" in text
        assert "Playback=1" in text
        assert (game / rtklaunchcfg.BACKUP_NAME).read_bytes() == before
        again = rtklaunchcfg.apply_launch(game)
        assert again["wrote"] is False
        assert again["needs_repair"] is False


def test_engine_without_driver_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp)
        _write(game, "Gamma=1.000000\nEngine=1\n")
        before = (game / "RTKRONDOR.INI").read_bytes()
        report = rtklaunchcfg.inspect_launch(game)
        assert report["needs_repair"] is False
        applied = rtklaunchcfg.apply_launch(game)
        assert applied["wrote"] is False
        assert (game / "RTKRONDOR.INI").read_bytes() == before


if __name__ == "__main__":
    test_hardware_guid_becomes_software()
    test_engine_without_driver_is_left_alone()
    print("ok")
