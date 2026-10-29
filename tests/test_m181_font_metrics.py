"""M181 (owner on prew_isaev_anna r11: the plate «КАК ПРИВИВАЮТСЯ ЖИЗНЕННЫЕ ЦЕННОСТИ» ran off both edges): lines are
fitted by the font's real advance widths (config/fonts/*.json) when subtitles.yaml font_metrics names one; "" or a
missing file = the old len × size × char_width_ratio estimate."""
import json

from autoreels.local import subtitles as S

# Arial Bold-like capitals are ~0.72 em; the old ratio 0.55 put 25 capitals at 990 px (< 1000) — really ~1300 px
METRICS = {"units_per_em": 2048, "default": 1479,
           "widths": {**{c: 1479 for c in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"}, " ": 569}}


def test_old_estimate_without_metrics():
    assert S._estimate_width("АБВ", 72, 0.55) == 3 * 72 * 0.55
    assert S._wrap_ass("КАК ПРИВИВАЮТСЯ ЖИЗНЕННЫЕ ЦЕННОСТИ", max_px=1000, font_size=72,
                       char_width_ratio=0.55) == "КАК ПРИВИВАЮТСЯ ЖИЗНЕННЫЕ\\NЦЕННОСТИ"


def test_metrics_wrap_the_plate_inside_the_frame():
    out = S._wrap_ass("КАК ПРИВИВАЮТСЯ ЖИЗНЕННЫЕ ЦЕННОСТИ", max_px=1000, font_size=72, char_width_ratio=0.55,
                      metrics=METRICS)
    assert out.split("\\N") == ["КАК ПРИВИВАЮТСЯ", "ЖИЗНЕННЫЕ ЦЕННОСТИ"]   # 748 px and 956 px, each inside 1000


def test_font_metrics_from_config(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(METRICS), encoding="utf-8")

    class Cfg:
        font_metrics = str(p)
    assert S.font_metrics(Cfg())["units_per_em"] == 2048

    class Off:
        font_metrics = ""
    assert S.font_metrics(Off()) is None

    class Missing:
        font_metrics = str(tmp_path / "nope.json")
    assert S.font_metrics(Missing()) is None


def test_group_words_uses_metrics():
    from autoreels.core.models import Word
    ws = [Word(word=w, t0=i * 0.3, t1=i * 0.3 + 0.25) for i, w in enumerate("ПРИВИВАЮТСЯ ЖИЗНЕННЫЕ ЦЕННОСТИ".split())]
    old = S.group_words(ws, words_per_line=3, max_text_width_px=1000, font_size=72, char_width_ratio=0.55,
                        break_pause_sec=1.0)
    new = S.group_words(ws, words_per_line=3, max_text_width_px=1000, font_size=72, char_width_ratio=0.55,
                        break_pause_sec=1.0, metrics=METRICS)
    assert [len(g) for g in old] == [2, 1] and [len(g) for g in new] == [1, 2]
