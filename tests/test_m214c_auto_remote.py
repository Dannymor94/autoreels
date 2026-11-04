"""M214c: `arl auto … --on-remote` — the same command on gamebox (the video stays there), the texts back to the Mac."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from autoreels.local import remote as R

LINK = "https://disk.yandex.ru/d/Folder123"
CFG = SimpleNamespace(host="gamebox", root="/mnt/data/autoreels/", encoder="h264_vaapi", profile="h264", lock="")


def test_remote_argv_drops_the_flag_and_the_macs_paths():
    argv = ["auto", LINK, "--root", "/Users/x/ar", "--no-render", "--on-remote", "--cache-dir=/tmp/c", "--mode", "autocut"]
    assert R.remote_argv(argv) == ["auto", LINK, "--no-render", "--mode", "autocut"]


class _Run:
    def __init__(self, changed="", fail=None, rc=0):
        self.calls, self.changed, self.fail, self.rc = [], changed, fail, rc

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        joined = " ".join(map(str, argv))
        if self.fail and self.fail in joined:
            return SimpleNamespace(returncode=255, stdout="", stderr="ssh: connect to host gamebox: No route to host")
        if argv[:2] == ["ssh", "-t"]:
            return SimpleNamespace(returncode=self.rc, stdout="", stderr="")
        if argv[0] == "ssh" and "find" in joined and "tar" not in joined:
            return SimpleNamespace(returncode=0, stdout=self.changed, stderr="")
        return SimpleNamespace(returncode=0, stdout="a\0b\0" if argv[0] == "git" else "ok", stderr="")


def test_the_run_goes_there_in_this_terminal_and_the_texts_come_back(tmp_path):
    run = _Run(changed="manifests/v.json\ntranscripts/v.map.json\nreviews/v_auto_all_t.txt\n", rc=0)
    logs = []
    rc = R.auto_remote(CFG, root=tmp_path, argv=["auto", LINK, "--no-render", "--on-remote"], run=run, log=logs.append)
    assert rc == 0
    names = [c[0] if c[0] != "ssh" else " ".join(c[:2]) for c in run.calls]
    assert names[:4] == ["ssh gamebox", "git", "rsync", "ssh gamebox"]          # check, code list, code, mark
    remote = next(c for c in run.calls if c[:2] == ["ssh", "-t"])
    assert remote[2] == "gamebox" and "cd /mnt/data/autoreels && .venv/bin/python -m autoreels auto" in remote[3]
    assert LINK in remote[3] and "--no-render" in remote[3] and "--on-remote" not in remote[3]
    pull = run.calls[-1]
    assert pull[:2] == ["sh", "-c"] and "tar --null -cf - -T -" in pull[2] and str(tmp_path) in pull[2]
    assert "назад на Mac: 3 файлов — manifests 1, transcripts 1, reviews 1" in logs[-1]


def test_no_changed_texts_no_pull_and_the_remote_code_is_returned(tmp_path):
    run = _Run(changed="", rc=1)
    logs = []
    assert R.auto_remote(CFG, root=tmp_path, argv=["auto", LINK], run=run, log=logs.append) == 1
    assert not any(c[0] == "sh" for c in run.calls) and "изменённых текстов нет" in logs[-1]


def test_an_unreachable_remote_is_one_clear_error(tmp_path, capsys):
    from autoreels import __main__ as cli
    (tmp_path / "config").mkdir()
    import shutil
    shutil.copyfile("config/render.yaml", tmp_path / "config" / "render.yaml")
    rc = cli.cmd_auto_remote(["auto", LINK, "--on-remote"], root=tmp_path, run=_Run(fail="test -x"))
    assert rc == 1 and "No route to host" in capsys.readouterr().err


def test_main_hands_the_whole_command_over(monkeypatch):
    from autoreels import __main__ as cli
    seen = {}
    monkeypatch.setattr(cli, "cmd_auto_remote", lambda argv, root=None: seen.update(argv=argv) or 0)
    assert cli.main(["auto", LINK, "--no-render", "--on-remote"]) == 0
    assert seen["argv"] == ["auto", LINK, "--no-render", "--on-remote"]


def test_not_configured(tmp_path, capsys):
    from autoreels import __main__ as cli
    (tmp_path / "config").mkdir()
    text = open("config/render.yaml", encoding="utf-8").read().replace("  host: gamebox", '  host: ""')
    (tmp_path / "config" / "render.yaml").write_text(text, encoding="utf-8")
    assert cli.cmd_auto_remote(["auto", LINK], root=tmp_path) == 2
    assert "не настроена" in capsys.readouterr().err
