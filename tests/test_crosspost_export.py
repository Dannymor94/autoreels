"""M90: the rendered clips of a source → a content plan for crosspost («Импорт плана»: a media folder and a table
«файл;текст;тип», UTF-8 with BOM, «;»)."""
from __future__ import annotations

import csv
import io

from autoreels import __main__ as cli
from tests.test_montage import _source


def test_crosspost_export_folder_and_table(tmp_path, capsys):
    _source(tmp_path)                                         # manifests/v.json, source v.mp4
    g = tmp_path / "reels-out" / "v" / "_gate" / "m86"
    g.mkdir(parents=True)
    (g / "r01.mp4").write_bytes(b"clip1")
    (g / "r01.txt").write_text("Маска защищает ребёнка.\n\n#психология\n", encoding="utf-8")
    (g / "r01.cover.jpg").write_bytes(b"jpg")
    (g / "r02.mp4").write_bytes(b"clip2")                     # no text: crosspost refuses a post without one
    (g / "r03.ERROR.mp4").write_bytes(b"bad")
    (g / "r10.mp4").write_bytes(b"clip10")
    (g / "r10.txt").write_text("Десятый.", encoding="utf-8")
    (g / "r01_raw.mp4").write_bytes(b"raw")                   # not a clip for publishing
    assert cli.cmd_crosspost("v", root=tmp_path, gate="m86") == 0
    out = capsys.readouterr().out
    exp = tmp_path / "export" / "crosspost"
    assert (exp / "v" / "r01.mp4").read_bytes() == b"clip1" and (exp / "v" / "r01.cover.jpg").is_file()
    assert not (exp / "v" / "r02.mp4").exists() and not (exp / "v" / "r01_raw.mp4").exists()
    raw = (exp / "v_m86.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")                    # BOM: crosspost reads utf-8-sig first
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    assert rows == [["файл", "текст", "тип"], ["v/r01.mp4", "Маска защищает ребёнка.\n\n#психология", "пост"],
                    ["v/r10.mp4", "Десятый.", "пост"]]          # natural order: r01 < r10
    assert "пропущен r02: нет подписи" in out and "пропущен r03: [ERROR]" in out and "клипов 2" in out
    assert cli.cmd_crosspost("v", root=tmp_path, gate="m86", reels="r10") == 0      # re-export, one clip
    assert list(csv.reader(io.StringIO((exp / "v_m86.csv").read_text(encoding="utf-8-sig")), delimiter=";"))[1:] == [
        ["v/r10.mp4", "Десятый.", "пост"]]
    assert cli.cmd_crosspost("v", root=tmp_path, gate="nope") == 1                  # no such folder
