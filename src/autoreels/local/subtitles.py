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


def remap_to_output(words: list[Word], segments, speed: float = 1.0, *,
                    xfade_sec: float = 0.0) -> list[Word]:
    """Remap word times onto the concatenated, speed-adjusted output timeline of a reel.

    Each word keeps its offset within its segment plus the accumulated duration of preceding
    segments, all divided by `speed` (render compresses the whole clip by the same factor); a word
    whose start falls in a removed gap (outside every segment) is dropped. For a single segment
    [s, e] at speed 1 this is a plain shift by s — identical to feeding raw words to build_ass with
    clip_start=s — so callers pass the remapped words with clip_start=0.

    `xfade_sec`: when the video has a crossfade at each segment seam (xfade filter), each
    subsequent segment starts `xfade_sec` earlier in the output timeline. Pass the actual
    (frame-snapped) xfade duration used in the filtergraph so subtitles land on the right frames.
    """
    out: list[Word] = []
    offset = 0.0
    segs = list(segments)
    for i, seg in enumerate(segs):
        for w in words:
            if seg.start <= w.t0 < seg.end:
                out.append(w.model_copy(update={
                    "t0": (w.t0 - seg.start + offset) / speed,
                    "t1": (w.t1 - seg.start + offset) / speed,
                }))
        offset += seg.end - seg.start
        if xfade_sec > 0 and i < len(segs) - 1:
            offset -= xfade_sec   # xfade overlaps: next seg starts xfade_sec earlier in output
    return out


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


def _wrap_ass(text: str, *, max_px: int, font_size: int, char_width_ratio: float) -> str:
    """Greedily wrap `text` into lines that fit `max_px` (estimated width), joined with ASS \\N.

    WrapStyle is 2 (no auto-wrap — \\N only), so a long title plate would otherwise run off the
    frame; this packs it into fitting lines. A single over-wide word stays on its own line."""
    words = text.split()
    out: list[str] = []
    cur: list[str] = []
    for w in words:
        if cur and _estimate_width(" ".join(cur + [w]), font_size, char_width_ratio) > max_px:
            out.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        out.append(" ".join(cur))
    return "\\N".join(out)


def _keyword_style_line(cfg: SubtitlesConfig) -> str:
    """Keyword style: same geometry as Default but with keyword_color and keyword_bold."""
    primary = ass_color(cfg.keyword_color)
    outline = ass_color(cfg.outline_color)
    if cfg.fill_enabled:
        border_style = 3
        back = ass_color(cfg.fill_color, alpha=_alpha_from_opacity(cfg.fill_opacity))
    else:
        border_style = 1
        back = ass_color("000000")
    bold = -1 if cfg.keyword_bold else 0
    align = _ALIGN.get(cfg.alignment, 2)
    fields = [
        "Keyword", cfg.font, cfg.font_size, primary, primary, outline, back,
        bold, 0, 0, 0, 100, 100, 0, 0, border_style, cfg.outline_width, cfg.shadow,
        align, 40, 40, cfg.position_v, 1,
    ]
    return "Style: " + ",".join(str(x) for x in fields)


def _title_style_line(cfg: SubtitlesConfig) -> str:
    """Title-plate style: a filled box (BackColour) at the top of the frame (alignment 8), sized by
    title_font_size (0 → font_size), MarginV measured from the top. Distinct from the subtitle
    Default style and positioned above the subtitle zone so the two never overlap."""
    primary = ass_color(cfg.text_color)
    outline = ass_color(cfg.outline_color)
    back = ass_color(cfg.fill_color, alpha=_alpha_from_opacity(cfg.fill_opacity))
    size = cfg.title_font_size or cfg.font_size
    bold = -1 if cfg.bold else 0
    fields = [
        "Title", cfg.font, size, primary, primary, outline, back,
        bold, 0, 0, 0, 100, 100, 0, 0, 3, cfg.outline_width, 0,
        8, 40, 40, cfg.title_position_v, 1,     # alignment 8 = top-centre; MarginV from top
    ]
    return "Style: " + ",".join(str(x) for x in fields)


def build_ass(words: list[Word], *, cfg: SubtitlesConfig, clip_start: float,
              play_res: tuple[int, int] = (1080, 1920), title: str = "",
              enable_keywords: bool = False, fx: dict | None = None, title_start: float = 0.0) -> str:
    """Собрать .ass из слов сегмента: Style из конфига + Dialogue по группам поп-апом.

    Времена Dialogue — относительно начала клипа (clip_start вычитается). uppercase из конфига.
    `title` (Part 4) непусто → плашка сверху (стиль Title) на первые cfg.title_lead_sec секунд с
    фейдом, над зоной субтитров (не пересекается). Пусто → плашки нет. `title_start` (M74) — секунда клипа,
    с которой плашка появляется (начало тела после крючка); 0 → побайтово прежний вывод.
    `enable_keywords=True` активирует стиль Keyword для слов с `w.emph=True`. False → побайтово
    идентично pre-M1.7 (стиль Keyword не добавляется, теги не вставляются).
    `fx` (M55, Reel.fx; None/{} → побайтово прежний вывод):
      karaoke  — группа выводится по словам: на каждое слово своя строка, текущее слово цветом
                 cfg.karaoke_color; fade только у первой (появление) и последней (уход) строки;
      callouts — [{"t": секунды клипа, "text": …}]: фраза крупно (стиль Callout) над субтитрами
                 на callout_sec с появлением через рост масштаба;
      progress — тонкая полоса внизу, заполняется за `progress_sec` (длина клипа).
    """
    fx = fx or {}
    _karaoke = bool(fx.get("karaoke"))
    _callouts = [c for c in (fx.get("callouts") or []) if str(c.get("text", "")).strip()]
    _progress = float(fx.get("progress_sec") or 0.0) if fx.get("progress") else 0.0
    pw, ph = play_res
    groups = group_words(
        words, words_per_line=cfg.words_per_line, max_text_width_px=cfg.max_text_width_px,
        font_size=cfg.font_size, char_width_ratio=cfg.char_width_ratio,
        break_pause_sec=cfg.subtitle_break_pause_sec,
    )
    _has_kw = enable_keywords and any(w.emph for w in words)
    _cont = fx.get("continue") if fx.get("continue") and str(fx["continue"].get("text", "")).strip() else None
    styles = [_style_line(cfg)]
    if title or _cont:
        styles.append(_title_style_line(cfg))
    if _has_kw:
        styles.append(_keyword_style_line(cfg))
    if _callouts:
        styles.append(_callout_style_line(cfg))
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
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if title:
        ttext = title.upper() if cfg.uppercase else title
        tsize = cfg.title_font_size or cfg.font_size
        ttext = _wrap_ass(ttext, max_px=cfg.max_text_width_px, font_size=tsize,
                          char_width_ratio=cfg.char_width_ratio)   # wrap so a long title never clips
        fi = fo = cfg.title_fade_ms
        ttext = f"{{\\fad({fi},{fo})}}" + ttext
        _ts = max(0.0, float(title_start or 0.0))
        lines.append(f"Dialogue: 0,{_ass_time(_ts)},{_ass_time(_ts + cfg.title_lead_sec)},Title,,0,0,0,,{ttext}")
    if _cont:     # M97: «Продолжение →» over the last seconds of a clip whose thought goes on (open_thought)
        ctext = str(_cont["text"]).strip()
        ctext = ctext.upper() if cfg.uppercase else ctext
        lines.append(f"Dialogue: 1,{_ass_time(float(_cont['t']))},{_ass_time(float(_cont['end']))},Title,,0,0,0,,"
                     f"{{\\fad({cfg.title_fade_ms},0)}}{ctext}")
    if _progress > 0:
        lines.append(_progress_line(cfg, _progress, pw, ph))
    for c in _callouts:
        lines.append(_callout_line(cfg, float(c["t"]), str(c["text"]), float(fx.get("callout_sec") or 2.0)))
    for g in groups:
        if _karaoke:
            lines.extend(_karaoke_lines(g, cfg, clip_start, _has_kw))
            continue
        if _has_kw:
            parts: list[str] = []
            for i, w in enumerate(g):
                if i > 0:
                    parts.append(" ")
                wtext = w.word.upper() if cfg.uppercase else w.word
                if w.emph:
                    # Punctuation stays outside the highlight so it renders in Default style.
                    body = wtext.rstrip(".,!?;:…—–")
                    trail = wtext[len(body):]
                    parts.append(f"{{\\rKeyword}}{body}{{\\r}}{trail}")
                else:
                    parts.append(wtext)
            text = "".join(parts)
        else:
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


def build_cover_ass(title: str, *, cfg: SubtitlesConfig, play_res: tuple[int, int] = (1080, 1920)) -> str:
    """M89: the cover's plate — the reel's title in the Title style, shown from the first frame without a fade (a
    cover is one frame: the reel's fade-in would leave it invisible). Empty title → no Dialogue."""
    pw, ph = play_res
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {pw}", f"PlayResY: {ph}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
         "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
         "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"),
        _title_style_line(cfg), "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    t = " ".join((title or "").split())
    if t:
        ttext = t.upper() if cfg.uppercase else t
        ttext = _wrap_ass(ttext, max_px=cfg.max_text_width_px, font_size=cfg.title_font_size or cfg.font_size,
                          char_width_ratio=cfg.char_width_ratio)
        lines.append(f"Dialogue: 0,{_ass_time(0.0)},{_ass_time(3600.0)},Title,,0,0,0,,{ttext}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- M55: attention effects

def _tag_color(rrggbb: str) -> str:
    """RRGGBB → the colour form of an override tag (&HBBGGRR&)."""
    return "&H" + ass_color(rrggbb)[4:] + "&"


def _word_text(w: Word, cfg: SubtitlesConfig, kw: bool, hl: str | None) -> str:
    """One word of a group: uppercase per config; a keyword keeps its Keyword style; the word being
    spoken (hl = ASS colour) is painted over everything (punctuation outside both)."""
    wtext = w.word.upper() if cfg.uppercase else w.word
    body = wtext.rstrip(".,!?;:…—–")
    trail = wtext[len(body):]
    if hl:
        return f"{{\\1c{hl}}}{body}{{\\r}}{trail}"
    if kw and w.emph:
        return f"{{\\rKeyword}}{body}{{\\r}}{trail}"
    return wtext


def _karaoke_lines(g: list[Word], cfg: SubtitlesConfig, clip_start: float, kw: bool) -> list[str]:
    """The group as one Dialogue per word: the same line of text, the current word in
    karaoke_color. Word starts are made monotonic inside [group start, group end] (Whisper times
    may overlap); a word that gets no time of its own is merged into the previous one. The lines
    abut exactly (same centisecond string), so the text never blinks between words."""
    g0, g1 = g[0].t0, g[-1].t1
    starts: list[float] = []
    for i, w in enumerate(g):
        t = g0 if i == 0 else min(max(w.t0, starts[-1]), g1)
        starts.append(t)
    marks = [_ass_time(t - clip_start) for t in starts] + [_ass_time(g1 - clip_start)]
    color = _tag_color(cfg.karaoke_color)
    spans = [(i, marks[i], marks[i + 1]) for i in range(len(g)) if marks[i] != marks[i + 1]]
    if not spans:
        spans = [(0, marks[0], marks[-1])]
    fade_in, fade_out = _fade_ms(g1 - g0, cfg.fade_in_ms, cfg.fade_out_ms)
    out: list[str] = []
    for n, (i, a, b) in enumerate(spans):
        text = " ".join(_word_text(w, cfg, kw, color if j == i else None) for j, w in enumerate(g))
        fi = fade_in if n == 0 else 0
        fo = fade_out if n == len(spans) - 1 else 0
        if fi or fo:
            text = f"{{\\fad({fi},{fo})}}" + text
        out.append(f"Dialogue: 0,{a},{b},Default,,0,0,0,,{text}")
    return out


def _callout_style_line(cfg: SubtitlesConfig) -> str:
    """Callout: big bold text in callout_color, bottom-centre, lifted above the subtitle line."""
    size = cfg.callout_font_size or int(round(cfg.font_size * 1.5))
    fields = [
        "Callout", cfg.font, size, ass_color(cfg.callout_color), ass_color(cfg.callout_color),
        ass_color(cfg.outline_color), ass_color("000000"),
        -1, 0, 0, 0, 100, 100, 0, 0, 1, cfg.outline_width + 2, cfg.shadow,
        2, 40, 40, cfg.position_v + cfg.callout_lift, 1,
    ]
    return "Style: " + ",".join(str(x) for x in fields)


def _callout_line(cfg: SubtitlesConfig, t: float, text: str, dur: float) -> str:
    """A callout at clip second t for dur seconds: fades in while growing 85 % → 100 %."""
    size = cfg.callout_font_size or int(round(cfg.font_size * 1.5))
    body = text.upper() if cfg.uppercase else text
    body = _wrap_ass(body.strip(), max_px=cfg.max_text_width_px, font_size=size,
                     char_width_ratio=cfg.char_width_ratio)
    tag = "{\\fad(150,250)\\fscx85\\fscy85\\t(0,200,\\fscx100\\fscy100)}"
    return f"Dialogue: 2,{_ass_time(t)},{_ass_time(t + dur)},Callout,,0,0,0,,{tag}{body}"


def _progress_line(cfg: SubtitlesConfig, dur: float, pw: int, ph: int) -> str:
    """A thin bar along the bottom edge that fills left → right over dur seconds (a vector shape
    revealed by an animated clip rectangle)."""
    h = cfg.progress_height
    y = ph - h
    ms = int(round(dur * 1000))
    col = _tag_color(cfg.progress_color)
    tag = (f"{{\\an7\\pos(0,{y})\\bord0\\shad0\\1c{col}\\alpha&H30&"
           f"\\clip(0,{y},0,{ph})\\t(0,{ms},\\clip(0,{y},{pw},{ph}))\\p1}}")
    return (f"Dialogue: 1,{_ass_time(0.0)},{_ass_time(dur)},Default,,0,0,0,,"
            f"{tag}m 0 0 l {pw} 0 {pw} {h} 0 {h}{{\\p0}}")
