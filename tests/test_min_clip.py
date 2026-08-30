"""Post-snap min_clip_duration guard: filter, rescue, diagnose, render protection.

Инварианты:
- клип короче min_clip_duration не попадает в манифест;
- схлопнутый момент сначала пытается расшириться до границы фразы;
- отброшенные считаются и логируются;
- рендер пропускает клип короче _MIN_CLIP_RENDER_SEC с предупреждением.
"""
from pathlib import Path

import pytest

from autoreels.cloud import select as S
from autoreels.cloud.snap import try_rescue_clip
from autoreels.core.models import Reel, Word

ROOT = Path(__file__).resolve().parents[1]

MIN_DUR = 8.0
MAX_DUR = 59.0
MIN_PAUSE = 1.5
MAX_MICRO = 0.4
HANGING = ["и", "а", "но", "что", "это"]


def _reel(start: float, end: float, *, r0_start=None, r0_end=None) -> Reel:
    r = Reel(id="r01", start=start, end=end, score=80, hook="h", title="t", description="d")
    r.r0_start = r0_start
    r.r0_end = r0_end
    return r


def _words(*triples: tuple[str, float, float]) -> list[Word]:
    return [Word(word=w, t0=t0, t1=t1) for w, t0, t1 in triples]


# --------------------------------------------------------------- diagnose_collapse

def test_diagnose_snap_collapsed():
    """R0 был 20с, после snap/padding схлопнулся до 1с → упоминает схлопывание."""
    r = _reel(10.0, 11.0, r0_start=10.0, r0_end=30.0)
    msg = S.diagnose_collapse(r)
    assert "схлопнул" in msg
    assert "20" in msg      # R0-длина упомянута


def test_diagnose_r0_was_already_short():
    """R0 вернул 1.5с, финал тоже 1.5с → проблема при выборке, не при snap."""
    r = _reel(10.0, 11.5, r0_start=10.0, r0_end=12.0)  # R0=2с, финал=1.5с
    msg = S.diagnose_collapse(r)
    assert "выборке" in msg or "коротк" in msg


def test_diagnose_no_r0_coords():
    """r0_start=None → диагностика невозможна, отчёт об этом."""
    r = _reel(10.0, 11.0)           # r0_start/r0_end=None
    msg = S.diagnose_collapse(r)
    assert "не сохранены" in msg or "r0_start" in msg.lower()


# --------------------------------------------------------------- try_rescue_clip

def test_rescue_extends_to_sentence_end():
    """Слово с точкой на 18с → конец клипа продлевается до 18с."""
    r = _reel(10.0, 11.0)
    words = _words(
        ("слово",  10.0, 10.5),
        ("дальше", 13.0, 13.5),
        ("конец.", 17.5, 18.0),   # sentence end: .
        ("после",  22.0, 22.5),
    )
    ok = try_rescue_clip(r, words, min_duration=MIN_DUR, max_duration=MAX_DUR,
                         min_pause=MIN_PAUSE, max_micro_pause=MAX_MICRO, hanging_words=HANGING)
    assert ok is True
    assert r.end == pytest.approx(18.0)
    assert r.end - r.start >= MIN_DUR


def test_rescue_uses_relaxed_when_no_strict_phrase_end():
    """Нет строгого конца фразы (пауза > 1.5с), но есть пауза > 0.4с → relaxed-rescue."""
    r = _reel(10.0, 11.0)
    # Слова с паузой 0.6с (> max_micro=0.4, < min_pause=1.5) после 18с
    words = _words(
        ("слово",  10.0, 10.5),
        ("текст",  13.0, 13.5),
        ("что",    17.0, 17.5),   # hanging — не конец мысли
        ("дальше", 18.0, 18.5),   # пауза 0.0 до следующего — не фраза
        ("стоп",   19.0, 19.5),   # пауза 0.5с после него (> MAX_MICRO)
        ("след",   20.1, 20.5),   # gap=0.6с — relaxed-конец мысли
    )
    ok = try_rescue_clip(r, words, min_duration=MIN_DUR, max_duration=MAX_DUR,
                         min_pause=MIN_PAUSE, max_micro_pause=MAX_MICRO, hanging_words=HANGING)
    assert ok is True
    assert r.end - r.start >= MIN_DUR


def test_rescue_fails_no_phrase_end_in_range():
    """Ни одного конца фразы в [r.end, start+max_duration] → rescue не удался."""
    r = _reel(10.0, 11.0)
    # Слова непрерывно без пауз/пунктуации на промежутке 11-14с
    words = [Word(word=f"w{i}", t0=11.0 + i * 0.4, t1=11.0 + i * 0.4 + 0.3)
             for i in range(6)]
    original_end = r.end
    ok = try_rescue_clip(r, words, min_duration=MIN_DUR, max_duration=MAX_DUR,
                         min_pause=MIN_PAUSE, max_micro_pause=MAX_MICRO, hanging_words=HANGING)
    assert ok is False
    assert r.end == original_end     # не мутировали


def test_rescue_does_not_exceed_max_duration():
    """Конец фразы за пределами start+max_duration → не используется."""
    r = _reel(10.0, 11.0)
    # Конец предложения на 70с, но 10+59=69 < 70 → за пределами
    words = _words(("конец.", 69.5, 70.0))
    ok = try_rescue_clip(r, words, min_duration=MIN_DUR, max_duration=MAX_DUR,
                         min_pause=MIN_PAUSE, max_micro_pause=MAX_MICRO, hanging_words=HANGING)
    assert ok is False
    assert r.end == 11.0


# --------------------------------------------------------------- filter_min_clip_duration

def test_filter_drops_clip_below_min():
    """Клип < min_clip_duration отбраковывается."""
    short = _reel(0.0, 5.0)    # 5с < 8с
    ok = _reel(0.0, 20.0)      # 20с — ОК
    result = S.filter_min_clip_duration([short, ok], min_clip_duration=8.0)
    assert ok in result
    assert short not in result


def test_filter_keeps_clip_at_threshold():
    """Клип ровно на пороге min_clip_duration — остаётся."""
    r = _reel(0.0, 8.0)        # ровно 8с
    result = S.filter_min_clip_duration([r], min_clip_duration=8.0)
    assert r in result


def test_filter_min_clip_duration_config_field():
    """R0Config содержит поле min_clip_duration с разумным дефолтом."""
    from autoreels.core.config import load_r0_config
    cfg = load_r0_config(ROOT / "config" / "r0.yaml")
    assert hasattr(cfg, "min_clip_duration")
    assert 4.0 <= cfg.min_clip_duration <= 15.0   # разумный диапазон


# --------------------------------------------------------------- render guard

def test_render_skips_clip_below_min_and_does_not_call_ffmpeg(tmp_path, monkeypatch):
    """Клип в манифесте короче _MIN_CLIP_RENDER_SEC → ffmpeg не вызывается для него."""
    from autoreels.local import render
    from autoreels.local.render import _MIN_CLIP_RENDER_SEC, render_cut
    from autoreels.core.config import load_render_config
    from autoreels.core.models import Crop, Manifest, SetupProfile
    from autoreels.core import state

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    fake_video = inputs / "lecture.mp4"
    fake_video.write_bytes(b"fake-video-bytes")
    sha = state.file_sha256_partial(fake_video)

    setup = SetupProfile(
        setup_id="s", crop=Crop(x=0, y=0, w=100, h=100),
        scale=[1080, 1920], frame=[1920, 1080],
    )
    short = Reel(id="r01", start=10.0, end=10.0 + _MIN_CLIP_RENDER_SEC - 0.5,
                 score=80, hook="h", title="t", description="d")   # below threshold
    ok = Reel(id="r02", start=100.0, end=130.0,
              score=80, hook="h", title="t", description="d")      # 30s — fine
    m = Manifest(source="lecture.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
                 duration_preset="shorts", setup=setup, run_key="rk", reels=[short, ok])

    calls: list = []

    class _FakeProc:
        def __init__(self, cmd, **kw):
            if "ffprobe" not in str(cmd[0]):
                calls.append(cmd)
            self.returncode = 0
            self.stdout = iter([])
            self.stderr = iter([])
        def wait(self): return 0

    monkeypatch.setattr(render.shutil, "which", lambda b: "/fake/ffmpeg")
    monkeypatch.setattr(render.subprocess, "Popen", _FakeProc)

    render_cfg = load_render_config(ROOT / "config" / "render.yaml",
                                    local_path=tmp_path / "nolocal.yaml")
    outputs = render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    assert len(calls) == 1, f"ожидали 1 вызов ffmpeg (только r02), получили {len(calls)}"
    assert len(outputs) == 1
    assert "r02" in str(outputs[0])


def test_render_skips_do_not_count_in_outputs(tmp_path, monkeypatch):
    """Пропущенный клип НЕ появляется в списке outputs render_cut."""
    from autoreels.local import render
    from autoreels.local.render import render_cut, _MIN_CLIP_RENDER_SEC
    from autoreels.core.config import load_render_config
    from autoreels.core.models import Crop, Manifest, SetupProfile
    from autoreels.core import state

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    fake_video = inputs / "v.mp4"
    fake_video.write_bytes(b"v")
    sha = state.file_sha256_partial(fake_video)
    setup = SetupProfile(setup_id="s", crop=Crop(x=0, y=0, w=100, h=100),
                         scale=[1080, 1920], frame=[1920, 1080])
    # Все клипы короткие → ни один не рендерится
    all_short = [Reel(id=f"r{i:02d}", start=i * 10.0, end=i * 10.0 + 0.5,
                      score=80, hook="h", title="t", description="d") for i in range(3)]
    m = Manifest(source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
                 duration_preset="shorts", setup=setup, run_key="rk", reels=all_short)

    monkeypatch.setattr(render.shutil, "which", lambda b: "/fake/ffmpeg")
    monkeypatch.setattr(render.subprocess, "Popen",
                        lambda cmd, **kw: type("P", (), {
                            "returncode": 0, "stdout": iter([]), "stderr": iter([]),
                            "wait": lambda s: 0})())

    render_cfg = load_render_config(ROOT / "config" / "render.yaml",
                                    local_path=tmp_path / "nolocal.yaml")
    outputs = render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)
    assert outputs == []
