"""Классификация концов клипов для diagnose-cuts (ядро — чистые функции)."""
from autoreels.cloud.diagnose import classify_end, summarize
from autoreels.core.models import Word

HANG = ["и", "а", "но", "что", "это", "как", "то", "есть", "вот"]
CFG = dict(min_pause=1.5, max_micro_pause=0.4, tail_pad_sec=0.7, hanging_words=HANG)


def _w(t0, t1, word):
    return Word(word=word, t0=t0, t1=t1)


def test_clean_on_sentence_punct():
    words = [_w(0, 0.5, "всё"), _w(0.5, 1.0, "понятно."), _w(2.0, 2.5, "Дальше")]
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "CLEAN" and d.end_type == "фраза(.!?)"


def test_clean_on_long_pause():
    words = [_w(0, 0.5, "слово"), _w(0.5, 1.0, "конец"), _w(3.0, 3.5, "потом")]  # пауза 2.0 ≥ 1.5
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "CLEAN" and "пауза" in d.end_type


def test_clean_on_end_of_speech():
    words = [_w(0, 0.5, "слово"), _w(0.5, 1.0, "последнее")]                    # нет next
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "CLEAN" and d.end_type == "конец речи"


def test_hard_on_hanging_word():
    words = [_w(0, 0.5, "нереализованный"), _w(0.5, 1.0, "это"), _w(1.4, 1.9, "всего")]
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "HARD" and d.end_type == "висячее"


def test_hard_on_comma_word():
    words = [_w(0, 0.5, "смотри"), _w(0.5, 1.0, "внимательно,"), _w(1.6, 2.0, "дальше")]
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "HARD" and d.end_type == "запятая"


def test_hard_on_mid_word():
    words = [_w(0, 0.5, "мы"), _w(0.5, 1.0, "делаем"), _w(1.1, 1.6, "дальше")]   # gap 0.1 < 0.4
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "HARD" and d.end_type == "мид-слово"


def test_soft_on_medium_pause():
    words = [_w(0, 0.5, "слово"), _w(0.5, 1.0, "думал"), _w(1.7, 2.2, "потом")]  # gap 0.7 ∈ [0.4,1.5)
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "SOFT" and abs(d.pause_after - 0.7) < 1e-6


def test_cause_pad_tail_overshoot():
    """Конец на слове после чистой фразы, перелёт ≈ tail_pad → причина PAD-хвост."""
    words = [_w(0, 0.5, "фраза."), _w(0.6, 0.7, "И"), _w(0.7, 1.0, "вот")]      # «фраза.» конец в 0.5
    # клип кончается в 1.05 (перелёт +0.55 за «фраза.» 0.5), последнее слово «вот» gap None→конец речи
    words.append(_w(1.2, 1.3, "ещё"))
    d = classify_end("r01", 0.0, 1.05, words, **CFG)
    assert d.verdict == "HARD"
    assert "PAD-хвост" in d.cause


def test_cause_snap_fallback_no_clean_boundary():
    """Сплошная речь без пунктуации/паузы ≥1.5 → причина snap-fallback."""
    words = [_w(0, 0.5, "мы"), _w(0.5, 1.0, "делаем"), _w(1.1, 1.6, "это"), _w(1.7, 2.2, "дальше")]
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "HARD"
    assert "snap-fallback" in d.cause


def test_classify_overlapping_next_word_after_sentence_is_clean():
    """Whisper-перекрытие таймкодов: след. слово начинается ВНУТРИ конца предложения
    («психосоматика.» 0.0–1.0, «И» 0.96–1.04) — клип кончается на «.», «И» лишь захватило край.
    Конец = фраза, CLEAN (не HARD висячее из-за артефакта)."""
    words = [_w(0.0, 1.0, "психосоматика."), _w(0.96, 1.04, "И"), _w(1.04, 1.3, "вот")]
    d = classify_end("r", 0.0, 1.0, words, **CFG)
    assert d.verdict == "CLEAN" and d.end_type == "фраза(.!?)"


def test_summarize_counts_and_causes():
    diags = [
        classify_end("r1", 0, 1.0, [_w(0, 1.0, "понятно.")], **CFG),                      # CLEAN
        classify_end("r2", 0, 1.0, [_w(0, 1.0, "это"), _w(1.4, 1.9, "всего")], **CFG),    # HARD висячее
        classify_end("r3", 0, 1.0, [_w(0, 1.0, "думал"), _w(1.7, 2.2, "п")], **CFG),      # SOFT
    ]
    s = summarize(diags)
    assert s["clean"] == 1 and s["soft"] == 1 and s["hard"] == 1
    assert sum(s["causes"].values()) == 1                # одна HARD-причина


# Part F: diagnose-cuts reports PLAYBACK duration; the source span (with removed gaps) is shown
# separately for a multi-segment reel.
def test_diag_table_shows_playback_duration_and_span(capsys):
    from autoreels import __main__ as cli
    from autoreels.core.models import Reel, Segment

    words = [_w(0.0, 4.8, "речь"), _w(10.0, 14.8, "продолжение.")]
    single = Reel(id="r01", start=0.0, end=4.8, score=80, hook="h", title="t", description="d")
    multi = Reel(id="r02", start=0.0, end=14.8, score=80, hook="h", title="t", description="d",
                 segments=[Segment(start=0.0, end=4.8), Segment(start=10.0, end=14.8)])
    diags = [classify_end(r.id, r.start, r.end, words, **CFG) for r in (single, multi)]
    cli._print_diag_table("v", diags, [single, multi])
    out = capsys.readouterr().out
    lines = {ln.split()[0]: ln for ln in out.splitlines() if ln.strip().startswith("r0")}
    # single-window: playback == span, no span note
    assert "4.8с" in lines["r01"] and "span" not in lines["r01"]
    # multi-window: playback 9.6s shown; source span 14.8s and window count noted separately
    assert "9.6с" in lines["r02"]
    assert "span 14.8с" in lines["r02"] and "2 окон" in lines["r02"]


def test_diag_table_cold_open_reel_shows_replay_not_negative_cut(capsys):
    # A cold-open reel replays its hook before the body → playback is LONGER than the span; the note
    # must say +cold-open, never a nonsensical negative "removed" figure.
    from autoreels import __main__ as cli
    from autoreels.core.models import Reel, Segment

    words = [_w(0.0, 4.8, "тело."), _w(10.0, 14.8, "продолжение.")]
    r = Reel(id="r09", start=0.0, end=4.8, score=80, hook="h", title="t", description="d",
             cold_open=Segment(start=2.0, end=4.0))          # 2s hook replayed first
    d = classify_end(r.id, r.start, r.end, words, **CFG)
    cli._print_diag_table("v", [d], [r])
    row = next(ln for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("r09"))
    assert "6.8с" in row                                     # playback = body 4.8 + hook 2.0
    assert "+cold-open 2.0с" in row and "вырезано" not in row and "−-" not in row
