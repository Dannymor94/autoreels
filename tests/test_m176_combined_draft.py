"""M176 (m175: 5 of 7 sources lost every label clip in arl auto): (1) a refused automatic clip (no room after its last
word, a short shot) leaves the combined draft alone instead of refusing the whole draft — only with drop_refused (arl
auto); the line check keeps refusing; (2) the combined draft numbers the autocut montage lines after the label
draft's own, so no «label used twice»."""
from __future__ import annotations

from autoreels import __main__ as cli
from autoreels.cloud.blocks import _block_fingerprint
from autoreels.core.models import Manifest
from tests.test_montage import _source


def _draft(tmp_path, body):
    mpath = _source(tmp_path)
    r0 = cli.load_r0_config(tmp_path / "config" / "r0.yaml")
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    rpath = tmp_path / "reviews" / "v_auto.txt"
    rpath.write_text(f"# source: {mpath}\n# fingerprint: {_block_fingerprint(kept)}\n# blocks: {len(kept)}\n"
                     f"# format: compact\n{body}", encoding="utf-8")
    return rpath


def _refuse_first(monkeypatch):
    monkeypatch.setattr(cli, "_no_room_errors", lambda reels: [(reels[0].id, "no room after last word «x»")])


def test_refused_clip_refuses_the_draft_without_the_switch(tmp_path, monkeypatch, capsys):
    rpath = _draft(tmp_path, "2 80\nM 85 | 2.2-4 5.1-3\n")
    _refuse_first(monkeypatch)
    rc = cli._blocks_do_apply(str(rpath), root=tmp_path, cache_dir=str(tmp_path / "cache"), labeler="auto")
    assert rc == 1 and "automatic clip needs another end" in capsys.readouterr().err


def test_refused_clip_leaves_alone_with_the_switch(tmp_path, monkeypatch, capsys):
    rpath = _draft(tmp_path, "2 80\nM 85 | 2.2-4 5.1-3\n")
    _refuse_first(monkeypatch)
    rc = cli._blocks_do_apply(str(rpath), root=tmp_path, cache_dir=str(tmp_path / "cache"), labeler="auto",
                              drop_refused=True)
    out = capsys.readouterr()
    assert rc == 0, out.err[-1500:]
    man = Manifest.model_validate_json((tmp_path / "reviews" / "v.review.json").read_text())
    assert len(man.reels) == 1 and "montage" in man.reels[0].flags
    assert "убран из черновика" in out.out


def test_merge_numbers_autocut_lines_after_the_label_drafts(tmp_path):
    lab = tmp_path / "a_auto.txt"
    lab.write_text("# head\n# fingerprint: x\n\n2 80\nM1 90 | 1.1-2\nM2 88 | 3.1\n", encoding="utf-8")
    ac = tmp_path / "a_auto_m56.txt"
    ac.write_text("# autocut head\n\n# комментарий\nM1 95 | 4.1-3 | h:4.2!\nM2 91 | 5.1\n", encoding="utf-8")
    out = tmp_path / "a_all.txt"
    assert cli._merge_drafts(lab, ac, out) == 2
    txt = out.read_text(encoding="utf-8")
    assert "M3 95 | 4.1-3 | h:4.2!" in txt and "M4 91 | 5.1" in txt and "# комментарий" in txt
    from autoreels.cloud.montage import parse_montage
    _, errs = parse_montage(txt)
    assert not [e for e in errs if "used twice" in e[1]]


def test_merge_without_montage_in_the_label_draft_is_unchanged(tmp_path):
    lab = tmp_path / "a_auto.txt"
    lab.write_text("# head\n\n2 80\n", encoding="utf-8")
    ac = tmp_path / "a_auto_m56.txt"
    ac.write_text("# autocut head\n\nM1 95 | 4.1-3\n", encoding="utf-8")
    out = tmp_path / "a_all.txt"
    cli._merge_drafts(lab, ac, out)
    assert "\nM1 95 | 4.1-3" in out.read_text(encoding="utf-8")
