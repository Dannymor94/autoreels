"""M94: the post published under a reel — a detailed description and hashtags (owner: «нужно делать подробное
описание видео для постинга»).

The model writes; the code decides (invariant 1). The description must stay in the reel's own words (invariant 2):
no number the reel does not say, at least half of its content words share their first five letters with a word of
the reel, no hashtags or «|» inside, a length and a number of sentences in the configured range. A hashtag is one
word (letters/digits), its stem said in the reel. One retry with the reason; else no description (the render's
caption stays). Pure: text in, text out — the CLI (arl describe) does the I/O.
M101 (m94: both posts the owner saw went «Почему…? Вы поймете, что…» — a template, the same in every post of a feed):
the post says the thought, it does not announce it — a stock phrase («вы поймете», «в этом видео»…) the reel does not
say itself is a reason to reject; a post (or an article section) over the size loses its last sentences in code
before the check (fit_post) — the model's extra sentence is not a reason to throw the post away.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Sequence

DESCRIBE_SYSTEM = (
    "You write the post published under a short vertical video (a reel) cut from a Russian talk. You get the reel's "
    "caption (its point) and its full spoken text. Write in Russian. The post: {smin}–{smax} sentences, at most "
    "{max_chars} characters. The first sentence makes the reader want to watch — a question or a strong claim from the "
    "reel; then the reel's thought itself in the speaker's own ideas, images and words — say it, do not announce it "
    "(never «вы поймете», «вы узнаете», «в этом видео»); address the reader as «вы» where it fits. "
    "Never invent facts, names, numbers, stories or promises that are not in the reel; no emojis, no hashtags in the "
    "text, no quotes of whole sentences. Then {ntags} hashtags: single Russian words (lower case, no spaces) naming "
    "what the reel is about, each said in the reel. Answer only with JSON: {{\"text\": \"<post>\", \"hashtags\": "
    "[\"<word>\", …]}}."
)


# M101: stock phrases of post copy that announce the thought instead of saying it (normalised: lower case, ё → е,
# words only). Rejected unless the reel itself says them.
STOCK_PHRASES = ("вы поймете", "вы узнаете", "вы откроете для себя", "узнайте", "в этом видео", "в этом ролике",
                 "в этом рилсе", "в этом посте", "в этом выпуске", "из этого видео", "из этого ролика", "это видео",
                 "этот ролик", "смотрите до конца", "досмотрите", "не пропустите")
_SENT = re.compile(r"(?<=[.!?…])\s+")


def _plain(text: str) -> str:
    return " " + " ".join(re.sub(r"[^\w]+", " ", (text or "").lower().replace("ё", "е")).split()) + " "


def _sentences(text: str) -> list[str]:
    return [x for x in _SENT.split(" ".join((text or "").split())) if x.strip()]


def fit_post(text: str, *, smax: int = 5, max_chars: int = 700) -> str:
    """The text cut to whole sentences from its start: at most smax of them, at most max_chars characters. Nothing
    fits (the first sentence alone is too long) — the text as is (the check then says why)."""
    out: list[str] = []
    for x in _sentences(text):
        if len(out) >= smax or len(" ".join(out + [x])) > max_chars:
            break
        out.append(x)
    return " ".join(out) if out else " ".join((text or "").split())


def _norm(w: str) -> str:
    return "".join(c for c in w.lower().replace("ё", "е") if c.isalnum())


def _stems(text: str) -> set[str]:
    return {w[:5] for w in (_norm(x) for x in (text or "").split()) if len(w) >= 5}


def check_post(text: str, source: str, *, smin: int = 3, smax: int = 5, max_chars: int = 700) -> str | None:
    """Why the description cannot be used, None = fine (grounded in the reel, the configured size)."""
    t = " ".join((text or "").split())
    if not t:
        return "пусто"
    if len(t) > max_chars:
        return f"длиннее {max_chars} знаков ({len(t)})"
    if "|" in t or "#" in t:
        return "в тексте «|» или хэштег"
    plain, said = _plain(t), _plain(source)
    for ph in STOCK_PHRASES:
        if f" {ph} " in plain and f" {ph} " not in said:
            return f"шаблонная фраза «{ph}» — скажите саму мысль"
    n = len(_sentences(t))
    if not smin <= n <= smax:
        return f"предложений {n} (нужно {smin}–{smax})"
    src_words = {_norm(w) for w in (source or "").split()}
    for w in (_norm(x) for x in t.split()):
        if w.isdigit() and w not in src_words:
            return f"число {w}, которого нет в ролике"
    content = [w for w in (_norm(x) for x in t.split()) if len(w) >= 5 and not w.isdigit()]
    if content:
        stems = _stems(source)
        hit = sum(1 for w in content if w[:5] in stems)
        if hit < 0.5 * len(content):
            return f"слова не из ролика ({hit} из {len(content)})"
    return None


def check_hashtags(tags: Sequence, source: str, *, n: int = 3) -> list[str]:
    """The hashtags that can be used (without «#», lower case): one word of letters/digits, 3–30 characters, its
    first five letters said in the reel (a short word: said as is); no repeats; at most n. M104 (m101: «#себе»):
    not a pronoun or a function word — the stop list of the key words (cloud/autocut._KEY_STOP)."""
    from autoreels.cloud.autocut import _KEY_STOP
    stems, words = _stems(source), {_norm(w) for w in (source or "").split()}
    out: list[str] = []
    for t in tags or []:
        w = _norm(str(t).lstrip("#"))
        if not 3 <= len(w) <= 30 or w in out or w.isdigit() or w in _KEY_STOP:
            continue
        if (w[:5] in stems) if len(w) >= 5 else (w in words):
            out.append(w)
        if len(out) >= n:
            break
    return out


def describe_clip(provider, caption: str, transcript: str, *, smin: int = 3, smax: int = 5, max_chars: int = 700,
                  ntags: int = 3, log: Callable[[str], None] = print,
                  why_out: list | None = None) -> tuple[str, list[str]] | None:
    """(description, hashtags) the model wrote and the code accepted (cut to the size first, fit_post); one retry
    told why; None = no usable answer (the last reason is appended to why_out, when given)."""
    system = DESCRIBE_SYSTEM.format(smin=smin, smax=smax, max_chars=max_chars, ntags=ntags)
    msg = f"Caption: {caption or '—'}\nSpoken text: {transcript}"
    why = ""
    for _ in range(2):
        user = msg + (f"\nThe previous answer was rejected: {why}. Write it again." if why else "")
        try:
            raw = provider.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                    temperature=0.0)
        except Exception as exc:  # noqa: BLE001 — no model: no description
            log(f"  описание: модель не ответила ({type(exc).__name__})")
            return None
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            obj = json.loads(m.group(0)) if m else None
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            why = "not JSON"
            continue
        raw_text = " ".join(str(obj.get("text") or "").split())
        text = fit_post(raw_text, smax=smax, max_chars=max_chars)
        why = check_post(text, transcript, smin=smin, smax=smax, max_chars=max_chars) or ""
        if not why:
            if text != raw_text:
                log(f"  описание: сокращено до {len(_sentences(text))} предл. ({len(text)} знаков)")
            return text, check_hashtags(obj.get("hashtags") or [], transcript, n=ntags)
    log(f"  описание: не принято ({why})")
    if why_out is not None:
        why_out.append(why)
    return None


def post_text(description: str, tags: Sequence[str], always: Sequence[str] = ()) -> str:
    """The post as published: the description, a blank line, the hashtags (fixed ones first, no repeats)."""
    seen: list[str] = []
    for t in list(always) + list(tags):
        w = _norm(str(t).lstrip("#"))
        if w and w not in seen:
            seen.append(w)
    return description.strip() + ("\n\n" + " ".join(f"#{w}" for w in seen) if seen else "") + "\n"
