"""Deterministic hashtag derivation from a reel's spoken words.

Algorithm:
1. Extract content words from reel.subtitles (not stopwords, length > 2).
2. Lemmatise with pymorphy3 when available (soft dependency — no ImportError if absent).
3. Count frequencies; sort descending.
4. Prepend `hashtags_always` (fixed tags from config), then most-frequent clip tags.
5. Deduplicate (first occurrence wins), cap at `hashtags_max`.
6. Return as list of "#word" strings.
"""
from __future__ import annotations

import re
from collections import Counter

_WORD_RE = re.compile(r"[а-яёА-ЯЁa-zA-Z]{3,}")

_STOPWORDS = frozenset({
    "и", "в", "не", "на", "я", "что", "тот", "это", "он", "она", "с", "как",
    "а", "то", "все", "так", "его", "но", "да", "ты", "к", "у", "же", "вы",
    "за", "бы", "по", "только", "её", "мне", "было", "вот", "от", "меня",
    "ещё", "нет", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли",
    "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь",
    "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей",
    "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя",
    "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего", "раз",
    "тоже", "себе", "под", "будет", "ж", "тогда", "кто", "этот", "того",
    "потому", "этого", "какой", "совсем", "ним", "здесь", "этом", "один",
    "почти", "мой", "тем", "чтобы", "нее", "сейчас", "были", "куда", "зачем",
    "всех", "никогда", "можно", "при", "наконец", "два", "об", "другой",
    "хоть", "после", "над", "больше", "через", "эти", "нас", "про", "всего",
    "них", "какая", "много", "разве", "три", "эту", "моя", "впрочем",
    "хорошо", "свою", "этой", "перед", "иногда", "лучше", "чуть", "том",
    "нельзя", "такой", "им", "более", "всегда", "конечно", "всю", "между",
    "значит", "вроде", "этим", "буду", "рядом", "видеть", "идти", "идет",
    "просто", "очень", "уже", "этих", "свой", "они", "нам", "этому",
})

_morph = None


def _lemma(word: str) -> str:
    """Lemmatise with pymorphy3 if available; otherwise return lowercase word."""
    global _morph
    if _morph is None:
        try:
            import pymorphy3
            _morph = pymorphy3.MorphAnalyzer()
        except ImportError:
            _morph = False  # type: ignore[assignment]
    if _morph is False:
        return word.lower()
    try:
        return _morph.parse(word)[0].normal_form
    except Exception:
        return word.lower()


def derive_hashtags(
    words: list,
    *,
    hashtags_always: list[str],
    hashtags_max: int = 5,
) -> list[str]:
    """Return deduplicated hashtag list from clip words + fixed always-tags.

    Args:
        words: list of Word objects (with .word attribute) from reel.subtitles.
        hashtags_always: fixed tags applied to every clip (from config); already formatted
            with or without #; normalised here. Prepended before frequency-derived tags.
        hashtags_max: total cap (always + derived).

    Returns:
        List of "#tag" strings, most-specific first, capped at hashtags_max.
    """
    # Normalise always-tags: strip leading #, lowercase
    always = [t.lstrip("#").lower().strip() for t in hashtags_always if t.strip()]
    # Extract + lemmatise content words from subtitles
    raw_words = [w.word for w in words if hasattr(w, "word")]
    content: list[str] = []
    for raw in raw_words:
        for tok in _WORD_RE.findall(raw):
            lower = tok.lower()
            if lower not in _STOPWORDS:
                content.append(_lemma(tok))

    # Most frequent first (stable: Counter preserves insertion order on ties in 3.7+)
    freq = Counter(content)
    derived = [lemma for lemma, _ in freq.most_common() if lemma not in _STOPWORDS]

    # Combine: always-tags first, then derived; deduplicate (first occurrence wins)
    seen: set[str] = set()
    result: list[str] = []
    for tag in always + derived:
        if tag and tag not in seen:
            seen.add(tag)
            result.append(f"#{tag}")
            if len(result) >= hashtags_max:
                break

    return result
