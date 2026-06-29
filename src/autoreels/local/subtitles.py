"""R3: word-level → группировка поп-апом → ASS (стиль из subtitles.yaml).

Группировка детерминированная: по `words_per_line` слов в строку, но меньше, если строка
не влезает по ширине (оценка без рендера: len(text)·font_size·char_width_ratio). Тайминг
группы = от t0 первого слова до t1 последнего; паузы между группами не показываются (нет
Dialogue — нечего тянуть). Без karaoke-подсветки слова (простой поп-ап группы; karaoke — M1).

ASS-цвета: формат &HAABBGGRR — байты RR/GG/BB ИНВЕРТИРУЮТСЯ относительно RRGGBB конфига,
AA — альфа (00 непрозрачно, FF прозрачно). Координаты — в кропнутом кадре 1080×1920.
"""
from __future__ import annotations

from autoreels.core.config import SubtitlesConfig
from autoreels.core.models import Word

# alignment (нижний ряд numpad ASS): center=2, left=1, right=3.
_ALIGN = {"center": 2, "left": 1, "right": 3}


def ass_color(rrggbb: str, *, alpha: int = 0) -> str:
    """RRGGBB (конфиг) → ASS &HAABBGGRR. Порядок байт инвертируется, альфа спереди."""
    rr, gg, bb = rrggbb[0:2], rrggbb[2:4], rrggbb[4:6]
    return f"&H{alpha:02X}{bb}{gg}{rr}".upper()


def _alpha_from_opacity(opacity_pct: int) -> int:
    """% непрозрачности → ASS-альфа (00 непрозрачно, FF прозрачно)."""
    return round((100 - opacity_pct) / 100 * 255)


def words_in_window(words: list[Word], start: float, end: float) -> list[Word]:
    """Слова сегмента: чьё НАЧАЛО попадает в [start, end) — появляются внутри клипа."""
    return [w for w in words if start <= w.t0 < end]


def _estimate_width(text: str, font_size: int, char_width_ratio: float) -> float:
    return len(text) * font_size * char_width_ratio


def group_words(words: list[Word], *, words_per_line: int, max_text_width_px: int,
                font_size: int, char_width_ratio: float, break_pause_sec: float) -> list[list[Word]]:
    """Слова → группы по `words_per_line`; группа обрывается раньше, если:

    - пауза до следующего слова `(next.t0 − cur.t1) > break_pause_sec` (граница фразы) — слово
      после паузы начинает НОВУЮ группу, чтобы хвост одной фразы не липнул к началу следующей;
    - строка не влезает по ширине (оценка без рендера).
    Что наступит раньше, то и рвёт. Одно слово шире лимита разбить нельзя — остаётся одно.
    """
    groups: list[list[Word]] = []
    i = 0
    n = len(words)
    while i < n:
        group: list[Word] = []
        for j in range(words_per_line):
            if i + j >= n:
                break
            w = words[i + j]
            if group:                       # для первого слова группы проверок нет — оно влезает всегда
                if w.t0 - group[-1].t1 > break_pause_sec:
                    break                   # пауза = граница фразы → закрываем группу
                text = " ".join(x.word for x in group + [w])
                if _estimate_width(text, font_size, char_width_ratio) > max_text_width_px:
                    break                   # добавление слова переполняет строку → закрываем группу
            group.append(w)
        groups.append(group)
        i += len(group)
    return groups


# Макс. доля длительности группы под суммарный fade — чтобы короткие группы не «мигали»
# полупрозрачными (fade не успевает раскрыться). Сверх неё fade ужимается пропорционально.
_FADE_MAX_SHARE = 0.4


def _fade_ms(group_duration_sec: float, fade_in_ms: int, fade_out_ms: int) -> tuple[int, int]:
    """fade_in/out (мс) под длительность группы. Если сумма > dur·_FADE_MAX_SHARE — ужать оба
    пропорционально под бюджет (детерминированно, не на глаз). 0/0 → (0, 0)."""
    total = fade_in_ms + fade_out_ms
    if total <= 0:
        return 0, 0
    budget = group_duration_sec * 1000 * _FADE_MAX_SHARE
    if total > budget:
        scale = budget / total
        return round(fade_in_ms * scale), round(fade_out_ms * scale)
    return fade_in_ms, fade_out_ms


def _ass_time(seconds: float) -> str:
    """Секунды → H:MM:SS.cc (центисекунды) — формат времени ASS."""
    cs = int(round(max(0.0, seconds) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _style_line(cfg: SubtitlesConfig) -> str:
    primary = ass_color(cfg.text_color)
    outline = ass_color(cfg.outline_color)
    if cfg.fill_enabled:
        border_style = 3                    # подложка-бокс из BackColour
        back = ass_color(cfg.fill_color, alpha=_alpha_from_opacity(cfg.fill_opacity))
    else:
        border_style = 1                    # обводка текста + тень
        back = ass_color("000000")          # цвет тени
    bold = -1 if cfg.bold else 0
    align = _ALIGN.get(cfg.alignment, 2)
    fields = [
        "Default", cfg.font, cfg.font_size, primary, primary, outline, back,
        bold, 0, 0, 0, 100, 100, 0, 0, border_style, cfg.outline_width, cfg.shadow,
        align, 40, 40, cfg.position_v, 1,
    ]
    return "Style: " + ",".join(str(x) for x in fields)


def build_ass(words: list[Word], *, cfg: SubtitlesConfig, clip_start: float,
              play_res: tuple[int, int] = (1080, 1920)) -> str:
    """Собрать .ass из слов сегмента: Style из конфига + Dialogue по группам поп-апом.

    Времена Dialogue — относительно начала клипа (clip_start вычитается). uppercase из конфига.
    """
    pw, ph = play_res
    groups = group_words(
        words, words_per_line=cfg.words_per_line, max_text_width_px=cfg.max_text_width_px,
        font_size=cfg.font_size, char_width_ratio=cfg.char_width_ratio,
        break_pause_sec=cfg.subtitle_break_pause_sec,
    )
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {pw}",
        f"PlayResY: {ph}",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
         "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
         "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"),
        _style_line(cfg),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for g in groups:
        text = " ".join(w.word for w in g)
        if cfg.uppercase:
            text = text.upper()
        start = _ass_time(g[0].t0 - clip_start)
        end = _ass_time(g[-1].t1 - clip_start)
        fade_in, fade_out = _fade_ms(g[-1].t1 - g[0].t0, cfg.fade_in_ms, cfg.fade_out_ms)
        if fade_in or fade_out:
            text = f"{{\\fad({fade_in},{fade_out})}}" + text   # override-блок перед текстом группы
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"
