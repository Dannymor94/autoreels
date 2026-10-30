"""M100: a longread (Telegraph, through crosspost's «статья») from a topic of the source map — the talk's own
thoughts written as text (v1.0 «текстовый контент-пайплайн на полных транскриптах»).

Two steps, each a short model answer (the free tier caps an answer at ~900 tokens): a plan — the title and 3–5
sections, each built from named thoughts of the topic — then every section written from the words of its thoughts.
The model proposes; the code keeps only what stays in the talk (invariant 2): the title shares its content words
with the topic, a section uses only thoughts of the topic, a section's text passes the same grounding as a post
(cloud/postcopy.check_post: no number the talk does not say, at least half its content words from the talk, a
size; M101: cut to the size in code first, no stock phrases). A section that fails twice is left out; an article
with fewer than two sections is not written. Pure.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

from autoreels.cloud.postcopy import check_post, fit_post

PLAN_SYSTEM = (
    "You plan a longread article for Telegraph from one topic of a Russian talk. You get the topic and its thoughts "
    "(number, summary). Write in Russian: a title (at most 70 characters, from the talk's own words, no clickbait) and "
    "{smin}–{smax} sections in a logical order; each section: a heading (at most 60 characters) and the numbers of the "
    "thoughts it is built from, in order — only numbers from the list, each number in at most one section. Answer "
    "only with JSON: {{\"title\": \"…\", \"sections\": [{{\"heading\": \"…\", \"units\": [3, 4]}}]}}."
)
SECTION_SYSTEM = (
    "You write one section of a longread article in Russian from what a speaker said in a talk. You get the section "
    "heading and the speaker's words. Write {pmin}–{pmax} sentences (at most {max_chars} characters) of clear written "
    "Russian that keep his ideas, images and examples; address the reader as «вы» where it fits. Never invent facts, "
    "names, numbers, stories or advice that are not in his words; no headings, lists, emojis or hashtags. Answer only "
    "with JSON: {{\"text\": \"…\"}}."
)


@dataclass
class Article:
    title: str
    sections: list = field(default_factory=list)      # [(heading, text)]

    def body(self) -> str:
        """The body crosspost's «статья» reads: one paragraph per line (headings are paragraphs of their own)."""
        out = []
        for h, t in self.sections:
            out += [h, t]
        return "\n".join(out)

    def markdown(self) -> str:
        return f"# {self.title}\n\n" + "\n\n".join(f"## {h}\n\n{t}" for h, t in self.sections) + "\n"


def _ask(provider, system: str, user: str, log: Callable[[str], None]) -> dict | None:
    try:
        raw = provider.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                temperature=0.0)
    except Exception as exc:  # noqa: BLE001 — no model: no article
        log(f"  статья: модель не ответила ({type(exc).__name__})")
        return None
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        obj = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def pick_topics(the_map: dict, n: int, *, min_units: int = 3) -> list[tuple[dict, list[dict]]]:
    """The n largest real topics of a map — (topic, its thoughts in time order); a thought counts when it is not an
    aside, is described and has strength ≥ 3; topics with fewer than min_units such thoughts are left out."""
    units = {u["id"]: u for u in the_map.get("units") or []}
    out = []
    for t in the_map.get("topics") or []:
        if int(t.get("id") or 0) <= 0:
            continue
        us = sorted((units[i] for i in t.get("units") or [] if i in units and units[i].get("role") not in (None, "aside")
                     and not units[i].get("missing") and int(units[i].get("punch") or 0) >= 3), key=lambda u: u["t0"])
        if len(us) >= min_units:
            out.append((t, us))
    out.sort(key=lambda x: -len(x[1]))
    return out[:n]


def write_article(provider, topic_name: str, units: Sequence[dict], *, smin: int = 3, smax: int = 5,
                  pmin: int = 2, pmax: int = 8, max_chars: int = 900,
                  log: Callable[[str], None] = print) -> Article | None:
    """The article of one topic, or None (no usable plan, or fewer than two sections passed)."""
    from autoreels.cloud.autocut import grounded_title
    by_id = {int(u["id"]): u for u in units}
    rows = "\n".join(f"{u['id']}. {u.get('summary') or ''}" for u in units)
    plan = _ask(provider, PLAN_SYSTEM.format(smin=smin, smax=smax), f"Topic: {topic_name}\nThoughts:\n{rows}", log)
    if not plan:
        log("  статья: план не получен")
        return None
    source_all = " ".join(str(u.get("text") or "") for u in units)
    title = " ".join(str(plan.get("title") or "").split())[:70]
    if grounded_title(title, source_all + " " + topic_name, max_chars=70, max_words=12):
        title = topic_name                                  # the model's title left the talk: the topic's own name
    art = Article(title=title)
    used: set[int] = set()
    for sec in (plan.get("sections") or [])[:smax]:
        if not isinstance(sec, dict):
            continue
        ids = []
        for x in sec.get("units") or []:
            try:
                i = int(str(x).lstrip("#"))
            except ValueError:
                continue
            if i in by_id and i not in used:
                ids.append(i)
        heading = " ".join(str(sec.get("heading") or "").split())[:60]
        if not ids:
            continue
        words = " ".join(str(by_id[i].get("text") or "") for i in ids)
        if not heading or grounded_title(heading, words + " " + topic_name, max_chars=60, max_words=10):
            heading = " ".join(str(by_id[ids[0]].get("summary") or topic_name).split())[:60].rstrip(".")
        system = SECTION_SYSTEM.format(pmin=pmin, pmax=pmax, max_chars=max_chars)
        why, text = "", ""
        for _ in range(2):
            user = f"Heading: {heading}\nThe speaker's words: {words}" + (
                f"\nThe previous answer was rejected: {why}. Write it again." if why else "")
            obj = _ask(provider, system, user, log)
            text = fit_post(" ".join(str((obj or {}).get("text") or "").split()), smax=pmax, max_chars=max_chars)
            why = check_post(text, words, smin=pmin, smax=pmax, max_chars=max_chars) if obj else "not JSON"
            if not why:
                break
        if why:
            log(f"  статья «{title}»: раздел «{heading}» не принят ({why})")
            continue
        used.update(ids)
        art.sections.append((heading, text))
    if len(art.sections) < 2:
        log(f"  статья «{title}»: разделов {len(art.sections)} — не пишется")
        return None
    return art
