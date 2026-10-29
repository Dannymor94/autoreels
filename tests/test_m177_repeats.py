"""M177 (m176: 105 clips — label clips of arl auto repeating montage clips): a clip sharing more than
autocut.combined_overlap_max of its played seconds with a kept clip (montage first) is a repeat; 1 = off."""
from pathlib import Path
from types import SimpleNamespace

from autoreels import __main__ as cli
from autoreels.core.models import Segment


def _r(rid, spans, montage=False):
    segs = [Segment(start=a, end=b) for a, b in spans]
    return SimpleNamespace(id=rid, flags=["montage"] if montage else [], effective_segments=lambda segs=segs: segs)


def test_off_and_distinct():
    a, b = _r("r01", [(0, 30)]), _r("r02", [(10, 40)], montage=True)
    assert cli._auto_repeats([a, b], 1.0) == []
    assert cli._auto_repeats([_r("r01", [(0, 30)]), _r("r02", [(50, 80)], montage=True)], 0.3) == []


def test_label_clip_repeating_a_montage_clip_goes_montage_stays():
    lab, mon = _r("r01", [(0, 30)]), _r("r05", [(5, 20), (100, 120)], montage=True)
    out = cli._auto_repeats([lab, mon], 0.3)
    assert [x[0] for x in out] == ["r01"] and "repeats r05" in out[0][1] and "50%" in out[0][1]


def test_two_label_clips_the_first_stays():
    out = cli._auto_repeats([_r("r01", [(0, 30)]), _r("r02", [(20, 40)])], 0.3)
    assert [x[0] for x in out] == ["r02"]                      # 10 of 20 s = 50 %
    assert cli._auto_repeats([_r("r01", [(0, 30)]), _r("r02", [(25, 45)])], 0.3) == []   # 5 of 20 s = 25 %


def test_repo_config_on():
    r0 = cli.load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml")
    assert 0 < r0.autocut.combined_overlap_max < 1


def test_arl_auto_apply_drops_the_repeat(tmp_path, monkeypatch, capsys):
    from autoreels.core.models import Manifest
    from tests.test_m176_combined_draft import _draft
    rpath = _draft(tmp_path, "2 80\nM 85 | 2.2-4 5.1-3\n")
    monkeypatch.setattr(cli, "_auto_repeats", lambda reels, m: [(r.id, "repeats rX: 90% of its seconds")
                                                                for r in reels if "montage" not in r.flags])
    rc = cli._blocks_do_apply(str(rpath), root=tmp_path, cache_dir=str(tmp_path / "cache"), labeler="auto",
                              drop_refused=True)
    out = capsys.readouterr()
    assert rc == 0, out.err[-1500:]
    man = Manifest.model_validate_json((tmp_path / "reviews" / "v.review.json").read_text())
    assert [("montage" in r.flags) for r in man.reels] == [True] and "repeats rX" in out.out


def test_m185_clips_left_are_numbered_without_gaps(tmp_path, monkeypatch, capsys):
    """M185 (owner on m183: «почему они так пронумерованы, нет 1»): after clips leave the combined draft of arl auto
    the rest is r01, r02, … again."""
    from autoreels.core.models import Manifest
    from tests.test_m176_combined_draft import _draft
    rpath = _draft(tmp_path, "2 80\n3 80\nM 85 | 2.2-4 5.1-3\n")
    monkeypatch.setattr(cli, "_auto_repeats", lambda reels, m: [(reels[0].id, "repeats rX: 90% of its seconds")])
    rc = cli._blocks_do_apply(str(rpath), root=tmp_path, cache_dir=str(tmp_path / "cache"), labeler="auto",
                              drop_refused=True)
    assert rc == 0, capsys.readouterr().err[-1500:]
    man = Manifest.model_validate_json((tmp_path / "reviews" / "v.review.json").read_text())
    assert [r.id for r in man.reels] == [f"r{i:02d}" for i in range(1, len(man.reels) + 1)] and len(man.reels) >= 1
