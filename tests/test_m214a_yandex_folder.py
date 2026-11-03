"""M214a: arl auto <public Yandex Disk folder link> — the folder's videos one by one (download → the whole run →
its file goes, if the owner said so ONCE at the start → the next); a /d/ link to a single file is a single file."""
from __future__ import annotations

from autoreels import __main__ as cli
from tests.test_auto import _stub

FOLDER = "https://disk.yandex.ru/d/CFGY7HK8UrWECQ"
ITEMS = [{"name": "b.mp4", "path": "/b.mp4", "type": "file", "mime_type": "video/mp4", "size": 3_000_000_000},
         {"name": "notes.txt", "path": "/notes.txt", "type": "file", "mime_type": "text/plain", "size": 10},
         {"name": "a.mov", "path": "/a.mov", "type": "file", "mime_type": "video/quicktime", "size": 1_000_000_000},
         {"name": "sub", "path": "/sub", "type": "dir"}]


def api(kind="dir", items=ITEMS, page=None):
    def get_json(suffix, public_key, *, token=None, path=None, extra=None):
        if kind != "dir":
            return {"type": "file", "name": "one.mp4", "mime_type": "video/mp4", "size": 5}
        if extra:
            off, lim = int(extra.get("offset", 0)), int(page or extra.get("limit", 200))
            return {"type": "dir", "name": "лекции", "_embedded": {"items": items[off:off + lim], "total": len(items)}}
        return {"type": "dir", "name": "лекции"}
    return get_json


def test_folder_listing_keeps_videos_by_name_across_pages():
    vids = cli._yandex_folder_videos(FOLDER, get_json=api(page=1))
    assert [v["path"] for v in vids] == ["/a.mov", "/b.mp4"] and vids[1]["size"] == 3_000_000_000


def _run(tmp_path, monkeypatch, answer, *, tty=True, kind="dir"):
    import shutil
    from pathlib import Path
    from tests.test_montage import _source
    tmp_path.mkdir(parents=True, exist_ok=True)
    mpath = _source(tmp_path)

    def run(v, **k):                                     # the manifest is named after the video, as arl run does
        m = mpath.with_name(f"{Path(v).stem}.json")
        if m != mpath:
            shutil.copyfile(mpath, m)
        return m
    monkeypatch.setattr(cli, "cmd_run", run)
    _stub(monkeypatch, tmp_path)
    log, asked = [], []

    def download(url, inputs_dir, path=None):
        present = sorted(p.name for p in inputs_dir.glob("*.m*")) if inputs_dir.exists() else []
        log.append((path, present))
        f = inputs_dir / ((path or "/one.mp4").lstrip("/"))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"V")
        return f
    if not tty:
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    rc = cli.cmd_auto([FOLDER], root=tmp_path, render=False, download=download, yandex_api=api(kind),
                      ask=(lambda q: asked.append(q) or answer) if tty else None)
    return rc, log, asked, tmp_path / "inputs"


def test_yes_once_deletes_each_video_before_the_next_downloads(tmp_path, monkeypatch, capsys):
    rc, log, asked, inputs = _run(tmp_path, monkeypatch, "y")
    out = capsys.readouterr().out
    assert rc == 0 and [p for p, _ in log] == ["/a.mov", "/b.mp4"]
    assert log[1][1] == []                                  # a.mov was gone before b.mp4 came: one video on disk
    assert len(asked) == 1 and "В папке 2 видео (4.0 ГБ)" in asked[0]
    assert not list(inputs.glob("*.m*")) and "папка Я.Диска «лекции» — видео 2" in out


def test_no_or_no_terminal_keeps_every_video_and_asks_nothing_more(tmp_path, monkeypatch, capsys):
    rc, log, asked, inputs = _run(tmp_path, monkeypatch, "n")
    assert rc == 0 and len(asked) == 1 and sorted(p.name for p in inputs.glob("*.m*")) == ["a.mov", "b.mp4"]
    assert log[1][1] == ["a.mov"]
    rc, log, asked, inputs = _run(tmp_path / "x", monkeypatch, None, tty=False)
    assert rc == 0 and sorted(p.name for p in inputs.glob("*.m*")) == ["a.mov", "b.mp4"]
    assert "нет терминала" in capsys.readouterr().out


def test_a_d_link_to_one_file_is_a_single_file(tmp_path, monkeypatch):
    rc, log, asked, inputs = _run(tmp_path, monkeypatch, "y", kind="file")
    assert rc == 0 and [p for p, _ in log] == [None] and len(asked) == 1 and "Удалить исходник one.mp4" in asked[0]
    assert not (inputs / "one.mp4").exists()


def test_link_kinds():
    assert cli._yandex_link_is_folder_kind(FOLDER) and not cli._yandex_link_is_folder_kind("https://disk.yandex.ru/i/x")
