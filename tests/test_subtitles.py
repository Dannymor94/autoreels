"""R3: word-level → группировка → ASS (local/subtitles.py). Стиль из subtitles.yaml.

Группировка поп-апом по 2–3 слова (без karaoke), детерминированная подгонка по ширине,
тайминг группы = от t0 первого до t1 последнего слова, паузы не тянутся. ASS-цвета —
&HAABBGGRR (порядок байт инвертируется из RRGGBB). uppercase/позиция/обводка — из конфига.
"""
from pathlib import Path

from autoreels.core.config import load_subtitles_config
from autoreels.core.models import Word
from autoreels.local.subtitles import (
    ass_color,
    build_ass,
    group_words,
    words_in_window,
)

ROOT = Path(__file__).resolve().parents[1]
CFG = load_subtitles_config(ROOT / "config" / "subtitles.yaml")


def _w(t0: float, t1: float, word: str = "сло") -> Word:
    return Word(word=word, t0=t0, t1=t1)


def _style_fields(ass: str) -> list[str]:
    line = next(ln for ln in ass.splitlines() if ln.startswith("Style: Default,"))
    return line[len("Style: "):].split(",")


def _dialogues(ass: str) -> list[tuple[str, str, str]]:
    out = []
    for ln in ass.splitlines():
        if ln.startswith("Dialogue:"):
            parts = ln[len("Dialogue:"):].split(",", 9)   # 10 полей, текст — последний
            out.append((parts[1].strip(), parts[2].strip(), parts[9]))
    return out


# ------------------------------------------------------------------ цвет ASS (байты)

def test_ass_color_inverts_rrggbb_to_bbggrr():
    assert ass_color("FF8800") == "&H000088FF"      # RR=FF GG=88 BB=00 → 00 88 FF
    assert ass_color("FFFFFF") == "&H00FFFFFF"


def test_ass_color_alpha_prefix():
    # непрозрачность бокса → альфа AA (00=непрозрачно, FF=прозрачно)
    assert ass_color("000000", alpha=0x66) == "&H66000000"


# --------------------------------------------------------------------- группировка

def test_group_words_by_count():
    words = [_w(i, i + 0.4, "x") for i in range(6)]
    groups = group_words(words, words_per_line=3, max_text_width_px=1000,
                         font_size=72, char_width_ratio=0.55, break_pause_sec=1.0)
    assert [len(g) for g in groups] == [3, 3]


def test_group_timing_first_to_last_word():
    words = [_w(10.0, 10.4, "a"), _w(10.5, 11.0, "b"), _w(11.1, 11.6, "c")]
    [g] = group_words(words, words_per_line=3, max_text_width_px=1000,
                     font_size=72, char_width_ratio=0.55, break_pause_sec=0.4)
    assert g[0].t0 == 10.0 and g[-1].t1 == 11.6      # окно группы = первое.t0 … последнее.t1


def test_wide_group_uses_fewer_words():
    # длинные слова: трое в строку не влезают в max_text_width_px → группа дробится
    words = [_w(i, i + 0.4, "оченьдлинноеслово") for i in range(3)]
    groups = group_words(words, words_per_line=3, max_text_width_px=500,
                        font_size=72, char_width_ratio=0.55, break_pause_sec=1.0)
    assert all(len(g) < 3 for g in groups)           # детерминированно меньше слов
    assert sum(len(g) for g in groups) == 3          # ни одно слово не потеряно


def test_single_overlong_word_kept_alone():
    # одно слово шире лимита нельзя разбить — остаётся как есть (не ломаем)
    words = [_w(0.0, 0.5, "архисупердлинноенеделимоеслово")]
    groups = group_words(words, words_per_line=3, max_text_width_px=200,
                        font_size=72, char_width_ratio=0.55, break_pause_sec=0.4)
    assert groups == [words]


# ----------------------------------------------- группировка: разрыв по паузе (R3-fix)

def test_group_breaks_on_pause():
    # большая пауза между словами → они в РАЗНЫХ группах (граница фразы), не склейка
    words = [_w(0.0, 0.5, "конецфразы"), _w(2.0, 2.5, "началофразы")]   # пауза 1.5с
    groups = group_words(words, words_per_line=3, max_text_width_px=1000,
                         font_size=72, char_width_ratio=0.55, break_pause_sec=0.4)
    assert [len(g) for g in groups] == [1, 1]           # не [2]


def test_no_pause_groups_by_count():
    # слова подряд без паузы → группируются по words_per_line как раньше
    words = [_w(i * 0.5, i * 0.5 + 0.5, "x") for i in range(6)]   # стык в стык, пауза 0
    groups = group_words(words, words_per_line=3, max_text_width_px=1000,
                         font_size=72, char_width_ratio=0.55, break_pause_sec=0.4)
    assert [len(g) for g in groups] == [3, 3]


def test_pause_breaks_group_before_words_per_line():
    # конец фразы (пауза) обрывает группу, даже если в ней меньше words_per_line слов
    words = [_w(0.0, 0.3, "a"), _w(0.4, 0.7, "b"),      # a,b подряд (пауза 0.1 < порог)
             _w(2.0, 2.3, "c")]                          # c после паузы 1.3с → новая группа
    groups = group_words(words, words_per_line=3, max_text_width_px=1000,
                         font_size=72, char_width_ratio=0.55, break_pause_sec=0.4)
    assert [len(g) for g in groups] == [2, 1]           # [a,b] | [c], не [a,b,c]


def test_width_and_pause_whichever_first():
    # ширина + пауза вместе: что наступит раньше, то и обрывает.
    # короткие слова (по ширине влезли бы 4), но пауза после 2-го рубит раньше ширины
    words = [_w(0.0, 0.3, "a"), _w(0.35, 0.6, "b"),
             _w(2.0, 2.3, "c"), _w(2.35, 2.6, "d")]      # пауза 1.4с после b
    groups = group_words(words, words_per_line=4, max_text_width_px=2000,
                         font_size=72, char_width_ratio=0.55, break_pause_sec=0.4)
    assert [len(g) for g in groups] == [2, 2]           # пауза наступила раньше переполнения


# --------------------------------------------------- отбор слов сегмента по окну

def test_words_in_window_selected_by_segment_start_end():
    words = [_w(9.5, 9.9, "before"), _w(10.0, 10.4, "in1"),
             _w(11.0, 11.5, "in2"), _w(12.0, 12.4, "after")]
    sel = words_in_window(words, 10.0, 12.0)         # [start, end): in1, in2; не before/after
    assert [w.word for w in sel] == ["in1", "in2"]


# ----------------------------------------------------------------- ASS-генерация

def test_ass_style_uses_config_font_size_position_alignment():
    ass = build_ass([_w(0.0, 0.5, "тест")], cfg=CFG, clip_start=0.0)
    f = _style_fields(ass)
    assert f[1] == CFG.font                          # Fontname
    assert f[2] == str(CFG.font_size)                # Fontsize
    assert f[18] == "2"                              # Alignment center (нижний центр)
    assert f[21] == str(CFG.position_v)              # MarginV из конфига


def test_ass_primary_colour_from_config_color():
    ass = build_ass([_w(0.0, 0.5, "x")], cfg=CFG, clip_start=0.0)
    assert _style_fields(ass)[3] == ass_color(CFG.text_color)   # верный порядок байт


def test_ass_uppercase_applied_when_configured():
    ass = build_ass([_w(0.0, 0.5, "привет")], cfg=CFG, clip_start=0.0)
    text = _dialogues(ass)[0][2]
    assert "ПРИВЕТ" in text and "привет" not in text


def test_ass_dialogue_times_relative_to_clip_start():
    # слово в абсолютных 30.5–31.0, клип начинается с 30.0 → 0:00:00.50 .. 0:00:01.00
    ass = build_ass([_w(30.5, 31.0, "x")], cfg=CFG, clip_start=30.0)
    start, end, _ = _dialogues(ass)[0]
    assert start == "0:00:00.50" and end == "0:00:01.00"


def test_ass_pause_between_groups_not_stretched():
    # две группы с паузой: 0.0–1.0 и 3.0–4.0 → два события, пауза 1.0–3.0 НЕ показывается
    words = [_w(0.0, 0.3, "a"), _w(0.4, 1.0, "b"),       # группа 1
             _w(3.0, 3.3, "c"), _w(3.4, 4.0, "d")]       # группа 2 (после паузы)
    ass = build_ass(words, cfg=CFG.model_copy(update={"words_per_line": 2}), clip_start=0.0)
    dlg = _dialogues(ass)
    assert len(dlg) == 2
    assert dlg[0][1] == "0:00:01.00"                 # первая кончается на 1.0
    assert dlg[1][0] == "0:00:03.00"                 # вторая стартует на 3.0 (пауза пустая)


def test_ass_borderstyle_outline_when_fill_disabled():
    ass = build_ass([_w(0.0, 0.5, "x")], cfg=CFG.model_copy(update={"fill_enabled": False}),
                    clip_start=0.0)
    assert _style_fields(ass)[15] == "1"             # BorderStyle 1 = обводка+тень


def test_ass_borderstyle_box_with_opacity_when_fill_enabled():
    cfg = CFG.model_copy(update={"fill_enabled": True, "fill_color": "112233", "fill_opacity": 60})
    f = _style_fields(build_ass([_w(0.0, 0.5, "x")], cfg=cfg, clip_start=0.0))
    assert f[15] == "3"                              # BorderStyle 3 = подложка-бокс
    assert f[6] == ass_color("112233", alpha=0x66)   # BackColour = fill_color + альфа из opacity
