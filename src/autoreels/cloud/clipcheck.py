"""M199 (замер, ничего не решает): четыре проверки готового клипа, которые слепые судьи m192b назвали главными
недостатками автоматики, — пока только числа, без влияния на сборку.

1. hook_hang — холодный старт кончается словом, после которого ждут продолжения (предлог, союз, частица, местоимение):
   «…вы забыли свою силу, Вы» — судьи: «тизер обрывается на „Вы“».
2. plate_cover — какая доля предложений клипа говорит словами плашки и есть ли они в начале или выводе: плашка
   «Кружки или бережное пространство?» над клипом, где «кружки» — одна боковая фраза.
3. start_morph — первая фраза тела без опоры: глагол без подлежащего («Всем говорит…», «Как было, так и было»)
   или местоимение 3-го лица раньше любого существительного («Он надевает маски…»).
4. seam_shared — у соседних кусков сборки нет ни одного общего содержательного слова (стык из разных мыслей).

Морфология — pymorphy3 (офлайн, детерминированная; `pip install pymorphy3`); без неё проверка 3 не делается (None),
а 1, 2, 4 идут по спискам слов и основам из 5 букв. Все функции чистые: на вход — словари review.json.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Sequence

_STOPS = ".!?…"
# when pymorphy3 is missing: words that leave a phrase hanging at its end
_HANG_WORDS = frozenset({
    "и", "а", "но", "или", "либо", "что", "чтобы", "как", "когда", "если", "потому", "поэтому", "то", "так", "же",
    "ли", "не", "ни", "бы", "в", "во", "на", "с", "со", "к", "ко", "о", "об", "от", "до", "по", "за", "из", "у",
    "для", "при", "про", "без", "через", "над", "под", "между", "вы", "ты", "он", "она", "оно", "они", "мы", "я",
    "это", "этот", "эта", "эти", "тот", "та", "те", "который", "которая", "которые", "вот", "ну", "даже", "уже"})
_HANG_POS = frozenset({"PREP", "CONJ", "PRCL", "NPRO"})
_CONTENT_POS = frozenset({"NOUN", "VERB", "INFN", "ADJF", "ADJS", "ADVB", "PRTF", "PRTS", "GRND", "COMP", "PRED"})
_PRON3 = frozenset({"он", "она", "оно", "они"})
_PARENTHETICAL = frozenset({"бывать", "казаться", "получаться", "оказываться", "считаться", "выходить"})


@lru_cache(maxsize=1)
def _morph():
    try:
        import pymorphy3
    except ImportError:
        return None
    return pymorphy3.MorphAnalyzer()


def has_morph() -> bool:
    return _morph() is not None


def _norm(w: str) -> str:
    return "".join(c for c in (w or "").lower().replace("ё", "е") if c.isalnum())


@lru_cache(maxsize=50000)
def _parse(w: str):
    m = _morph()
    return m.parse(w)[0] if (m is not None and w) else None


def _lemma(w: str) -> str | None:
    """A content word's lemma (pymorphy3) or its first 5 letters; None for a function word / short word."""
    n = _norm(w)
    if not n:
        return None
    p = _parse(n)
    if p is not None:
        return p.normal_form if (p.tag.POS in _CONTENT_POS and len(n) >= 3) else None
    return n[:5] if len(n) >= 5 else None


def lemmas(words: Sequence[str]) -> set[str]:
    return {x for x in (_lemma(w) for w in words) if x}


def sentences(words: Sequence[str]) -> list[list[str]]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if w.rstrip().endswith(tuple(_STOPS)):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# ── the clip as text, from a review.json reel ─────────────────────────────────────────────────────

def _windows(reel: dict) -> list[tuple[float, float]]:
    segs = reel.get("segments") or [{"start": reel["start"], "end": reel["end"], "window_cut": False}]
    pieces: list[list[float]] = []
    for s in segs:
        if s.get("window_cut") and pieces:
            pieces[-1][1] = s["end"]                       # a filler cut continues the same piece
        else:
            pieces.append([s["start"], s["end"]])
    return [(a, b) for a, b in pieces]


def clip_parts(reel: dict) -> dict:
    """{"hook": [words], "pieces": [[words] per body piece in play order], "body": [words]}. A teaser replayed in
    the body has its words once in the subtitles — they count in the hook and in their body piece."""
    subs = sorted(reel.get("subtitles") or [], key=lambda w: w["t0"])
    co = reel.get("cold_open")
    hook = [w["word"] for w in subs if co and co["start"] - 0.05 <= w["t0"] < co["end"]]
    pieces = [[w["word"] for w in subs if a - 0.05 <= w["t0"] < b] for a, b in _windows(reel)]
    return {"hook": hook, "pieces": pieces, "body": [w for p in pieces for w in p]}


# ── 1. the cold open ends where more is expected ──────────────────────────────────────────────────

def hook_hang(hook: Sequence[str]) -> str | None:
    """Why the cold open sounds cut off, None = it ends on a word that can close a phrase."""
    if not hook:
        return None
    last = hook[-1]
    if last.rstrip().endswith(tuple(_STOPS)):
        return None
    n = _norm(last)
    p = _parse(n)
    if p is not None:
        if p.tag.POS in _HANG_POS:
            return f"кончается на «{last}» ({p.tag.POS})"
        return None
    return f"кончается на «{last}»" if n in _HANG_WORDS else None


# ── 2. the plate speaks the clip's words ──────────────────────────────────────────────────────────

def plate_cover(title: str, body: Sequence[str]) -> dict | None:
    """{"share": доля предложений со словом плашки, "core": слово плашки в первых или последних двух, "hits": n,
    "sents": n}; None — у плашки нет содержательных слов (или нет плашки)."""
    tl = lemmas((title or "").split())
    if not tl:
        return None
    ss = sentences(body)
    hits = [bool(lemmas(s) & tl) for s in ss]
    core = any(hits[:2]) or any(hits[-2:])
    return {"share": round(sum(hits) / len(ss), 2) if ss else 0.0, "core": core, "hits": sum(hits), "sents": len(ss)}


# ── 3. the first sentence has nothing to stand on ─────────────────────────────────────────────────

def start_morph(sentence: Sequence[str]) -> str | None:
    """Why the body's first sentence leans on what the viewer did not hear (pymorphy3), None = stands / no morph.
    (a) its first clause (up to the first comma) has a finite verb in the 3rd person or the past and no subject — no
    noun / pronoun in the nominative, no 1st/2nd-person verb; (b) a 3rd-person pronoun comes before any noun."""
    if _morph() is None or not sentence:
        return None
    if sentence[-1].rstrip().endswith("?"):
        return None                                    # a question opens fine
    clause = []
    for w in sentence:
        clause.append(w)
        if w.rstrip().endswith((",", ";", ":", "—")):
            break
    tags = [(_norm(w), _parse(_norm(w))) for w in clause if _norm(w)]
    verb, after = None, None
    for i, (n, p) in enumerate(tags):
        if p is not None and p.tag.POS == "VERB" and "Impe" not in p.tag and ("3per" in p.tag or "past" in p.tag):
            verb, after = p, (tags[i + 1][1] if i + 1 < len(tags) else None)
            break
    if verb is not None and verb.normal_form in _PARENTHETICAL:
        verb = None                                    # «Бывает, что…», «Оказывается, …» — a parenthetical verb
    if verb is not None and after is not None and after.tag.POS in ("ADVB", "PRED", "ADJS") \
            and ("neut" in verb.tag or "3per" in verb.tag) and "plur" not in verb.tag:
        verb = None                                    # «Было интересно», «Стало легче» — impersonal, stands
    if verb is not None:
        subj = any(p is not None and p.tag.case == "nomn" and p.tag.POS in ("NOUN", "NPRO", "ADJF", "PRTF", "NUMR")
                   for _, p in tags)
        if not subj and not any(p is not None and p.tag.POS == "VERB" and ("1per" in p.tag or "2per" in p.tag)
                                for _, p in tags):
            return f"глагол «{verb.word}» без подлежащего"
    for n, p in [(_norm(w), _parse(_norm(w))) for w in sentence if _norm(w)]:
        if p is None:
            continue
        if p.tag.POS == "NOUN":
            break
        if p.tag.POS == "NPRO" and p.normal_form in _PRON3:
            return f"«{n}» раньше любого существительного — о ком?"
    return None


# ── 4. neighbouring pieces share no content word ──────────────────────────────────────────────────

def seam_shared(pieces: Sequence[Sequence[str]]) -> list[int]:
    """Content words shared by each pair of neighbouring body pieces (one number per seam)."""
    ls = [lemmas(p) for p in pieces if p]
    return [len(a & b) for a, b in zip(ls, ls[1:])]


def check_reel(reel: dict) -> dict:
    parts = clip_parts(reel)
    ss = sentences(parts["body"])
    return {
        "rid": reel.get("id"),
        "title": reel.get("title_overlay") or "",
        "hook": " ".join(parts["hook"]),
        "first": " ".join(ss[0]) if ss else "",
        "hook_hang": hook_hang(parts["hook"]),
        "plate": plate_cover(reel.get("title_overlay") or "", parts["body"]),
        "start_morph": start_morph(ss[0]) if ss else None,
        "seams": seam_shared(parts["pieces"]),
    }
