"""M213: arl auto <public Yandex Disk link> — the file downloads into inputs/, goes on as a video file, and after the
summary the owner is asked before the source is deleted (no terminal — kept; a failed run — kept)."""
from __future__ import annotations

import pytest

from tests.test_auto import _stub

LINK = "https://disk.yandex.ru/i/AbCdEf123"


def _setup(tmp_path, monkeypatch, *, run_ok=True):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    got = tmp_path / "inputs" / "v.mp4"

    def download(url, inputs_dir):
        assert url == LINK and inputs_dir == tmp_path / "inputs"
        got.parent.mkdir(parents=True, exist_ok=True)
        got.write_bytes(b"V" * 2048)
        return got
    seen = []
    monkeypatch.setattr(cli, "cmd_run", lambda v, **k: seen.append(v) or mpath)
    calls = _stub(monkeypatch, tmp_path, fail=None if run_ok else "prepare")
    return cli, download, got, seen, calls


@pytest.mark.parametrize("answer,deleted", [("y", True), ("да", True), ("", False), ("n", False)])
def test_the_link_downloads_runs_and_asks_before_deleting(tmp_path, monkeypatch, capsys, answer, deleted):
    cli, download, got, seen, calls = _setup(tmp_path, monkeypatch)
    asked = []
    rc = cli.cmd_auto([LINK], root=tmp_path, render=False, download=download,
                      ask=lambda q: asked.append(q) or answer)
    out = capsys.readouterr().out
    assert rc == 0 and seen == [got] and [c[0] for c in calls][:1] == ["prepare"]
    assert len(asked) == 1 and "Удалить исходник v.mp4" in asked[0] and "[y/N]" in asked[0]
    assert got.exists() is (not deleted)
    assert ("исходник удалён" in out) is deleted and ("исходник оставлен" in out) is (not deleted)


def test_keep_and_yes_and_no_terminal(tmp_path, monkeypatch, capsys):
    cli, download, got, seen, calls = _setup(tmp_path, monkeypatch)
    assert cli.cmd_auto([LINK], root=tmp_path, render=False, download=download, delete_source="keep") == 0
    assert got.exists()
    assert cli.cmd_auto([LINK], root=tmp_path, render=False, download=download, delete_source="yes") == 0
    assert not got.exists()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.cmd_auto([LINK], root=tmp_path, render=False, download=download) == 0      # ask, no terminal
    assert got.exists() and "нет терминала" in capsys.readouterr().out


def test_a_failed_run_keeps_its_source_and_a_dead_link_goes_on(tmp_path, monkeypatch, capsys):
    cli, download, got, seen, calls = _setup(tmp_path, monkeypatch, run_ok=False)
    asked = []
    rc = cli.cmd_auto([LINK], root=tmp_path, render=False, download=download, ask=lambda q: asked.append(q) or "y")
    assert rc == 1 and got.exists() and not asked
    assert "прогон не дошёл до конца" in capsys.readouterr().out

    def dead(url, inputs_dir):
        raise RuntimeError("ссылка не открывается")
    rc = cli.cmd_auto([LINK], root=tmp_path, render=False, download=dead, ask=lambda q: "y")
    out = capsys.readouterr().out
    assert rc == 1 and "скачивание" in out and "ссылка не открывается" in out


def test_a_local_file_is_never_offered_for_deletion(tmp_path, monkeypatch):
    cli, download, got, seen, calls = _setup(tmp_path, monkeypatch)
    video = tmp_path / "own.mp4"
    video.write_bytes(b"VIDEO")
    asked = []
    assert cli.cmd_auto([str(video)], root=tmp_path, render=False, ask=lambda q: asked.append(q) or "y") == 0
    assert video.exists() and not asked
