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


def _gate(tmp_path):
    g = tmp_path / "reels-out" / "v" / "_gate" / "m112"
    g.mkdir(parents=True)
    for rid in ("r01", "r02", "r03"):
        (g / f"{rid}.mp4").write_bytes(rid.encode())
        (g / f"{rid}.txt").write_text(f"Подпись {rid}.", encoding="utf-8")
    (g / "r02.post.txt").write_text("Пост r02.", encoding="utf-8")
    return g


def _rows(tmp_path, name="v_m112.csv"):
    return list(csv.reader(io.StringIO((tmp_path / "export" / "crosspost" / name).read_text(encoding="utf-8-sig")),
                           delimiter=";"))[1:]


def test_export_sends_only_the_clips_the_owner_kept(tmp_path, capsys):
    """M112 (invariant 6): phase 2 of arl auto — only the gate's clips with the owner's «оставить» go to crosspost;
    the latest verdict on a clip wins; verdicts of another gate or source do not count; none approved = no export."""
    import json
    _source(tmp_path)
    _gate(tmp_path)
    assert cli.cmd_export("v", root=tmp_path, gate="m112") == 1                    # no verdicts yet
    assert "одобренных клипов нет" in capsys.readouterr().err
    assert not (tmp_path / "export" / "crosspost" / "v_m112.csv").exists()
    rows = [{"stem": "v", "gate": "m112", "rid": "r01", "verdict": "fix"},
            {"stem": "v", "gate": "m112", "rid": "r02", "verdict": "ok"},
            {"stem": "v", "gate": "m112", "rid": "r03", "verdict": "drop"},
            {"stem": "v", "gate": "other", "rid": "r03", "verdict": "ok"},
            {"stem": "w", "gate": "m112", "rid": "r03", "verdict": "ok"},
            {"stem": "v", "gate": "m112", "rid": "r01", "verdict": "ok"}]           # changed mind on r01
    (tmp_path / "reviews").mkdir(exist_ok=True)
    (tmp_path / "reviews" / "verdicts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert cli.cmd_export("v", root=tmp_path, gate="m112") == 0
    out = capsys.readouterr().out
    assert "оставить 2, убрать 1, переделать 0" in out and "клипов 2" in out
    assert _rows(tmp_path) == [["v/r01.mp4", "Подпись r01.", "пост"], ["v/r02.mp4", "Пост r02.", "пост"]]
    assert not (tmp_path / "export" / "crosspost" / "v" / "r03.mp4").exists()


def test_export_records_the_sheet_decisions_first(tmp_path, capsys):
    """M112: --decisions <file from the review sheet> = arl review-apply, then the export; the gate comes from the
    file; decisions of another source are refused before anything is written."""
    _source(tmp_path)
    _gate(tmp_path)
    (tmp_path / "reviews").mkdir(exist_ok=True)
    (tmp_path / "reviews" / "v_auto_m56.txt").write_text(
        "# fingerprint: abc\nM1 85 | 2.2-4 | t: А\nM2 80 | 3.1-2 | t: Б\nM3 70 | 4.1-2 | t: В\n", encoding="utf-8")
    dec = tmp_path / "v_decisions.txt"
    dec.write_text("# stem: v\n# review: reviews/v_auto_m56.txt\n# gate: m112\n# decided: 2026-10-19\n"
                   "r01 | montage M1 | ok\nr02 | montage M2 | drop | причины: крючок\nr03 | montage M3 | ok\n",
                   encoding="utf-8")
    other = tmp_path / "w_decisions.txt"
    other.write_text(dec.read_text(encoding="utf-8").replace("# stem: v", "# stem: w"), encoding="utf-8")
    assert cli.cmd_export("v", root=tmp_path, decisions=str(other)) == 1
    assert "решения для «w»" in capsys.readouterr().err
    assert not (tmp_path / "reviews" / "verdicts.jsonl").exists()
    assert cli.cmd_export("v", root=tmp_path, decisions=str(dec), gate="nope") == 1
    assert "гейта «m112»" in capsys.readouterr().err
    assert cli.cmd_export("v", root=tmp_path, decisions=str(dec)) == 0
    out = capsys.readouterr().out
    assert "записано 3" in out and "оставить 2, убрать 1" in out
    assert _rows(tmp_path) == [["v/r01.mp4", "Подпись r01.", "пост"], ["v/r03.mp4", "Подпись r03.", "пост"]]


def test_export_command_is_wired(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_export", lambda m, **k: seen.update(m=m, **k) or 0)
    assert cli.main(["export", "v", "--decisions", "d.txt", "--gate", "g"]) == 0
    assert seen["m"] == "v" and seen["decisions"] == "d.txt" and seen["gate"] == "g"
