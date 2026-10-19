"""M56: the auto-editor — montage lines proposed from the map of a source (cloud/thoughtmap.py).

The map already says, for every thought (unit) of the lecture, what it does (role), how strong it is
(punch 1–5), whether it stands alone or leans on an earlier thought (refers — the «сноска»), its
topic, how alive the voice is (energy) and where the same thought is said again (similar). This
module turns that into reels, deterministically (the LLM only described the units; invariant 1):

1. SEEDS: strong units (punch ≥ seed_punch) with a story role — thesis, conclusion, example,
   metaphor, question.
2. CLIP around a seed: the seed and every unit it leans on (refers, transitively); then units of the
   same topic — and the seed's «similar» units said elsewhere — by score (punch, voice energy, a
   role the story still lacks: an opener, an example, a payoff), each with what it leans on, while
   the clip fits max_sec and has at most max_pieces pieces. Kept only when it reaches min_sec and
   has an opener (thesis or question) or a payoff (conclusion).
3. ORDER: a question opens the clip (M59 allows it to come from anywhere — the «вопрос-петля»);
   the rest plays in source order (a unit always after the one it leans on). Pieces are the units'
   review references; adjacent ones join without a seam (M58).
4. HOOK: the shortest-sounding finished sentence (≤ hook_max_sec, ≥ hook_min_words) of the strongest
   payoff/question/metaphor unit of the clip → h: (the plan replays it in context or not, §2).
5. Plate t: = the opener's summary; caption d: = the payoff's summary (the LLM's words).
6. Clips sharing more than overlap_max of their units with a better clip are dropped; the best
   `clips` are kept. Every line is a proposal for the owner — the montage checks run at --apply.

Pure: the map's units and a sentence lookup in, proposals out.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Sequence

STORY = ("thesis", "conclusion", "example", "metaphor", "question")
OPENERS = ("thesis", "question")
PAYOFFS = ("conclusion",)
MIDDLE = ("example", "metaphor", "explanation")
HOOK_ROLES = ("conclusion", "question", "metaphor", "thesis")


@dataclass(frozen=True)
class AutoParams:
    clips: int = 5
    min_sec: float = 30.0
    target_sec: float = 60.0
    max_sec: float = 90.0
    max_pieces: int = 4
    min_punch: int = 3                # a unit weaker than this is never used
    seed_punch: int = 4               # a clip grows only around a unit at least this strong
    hook_max_sec: float = 6.0
    hook_min_words: int = 4
    overlap_max: float = 0.5
    use_filtered: bool = False        # take units of filtered blocks (head/tail/promo, x-refs)
    # M65: interesting, hooky reels
    loop: bool = True                 # open on a question the clip answers (from anywhere in the source)
    loop_max_sec: float = 20.0        # … a question unit at most this long
    prune: bool = True                # drop the weakest middle thoughts down to target_sec (+ prune_slack)
    prune_slack: float = 8.0
    hook_min_sec: float = 1.5         # a hook shorter than this is a fragment
    speed_slow_rate: float = 2.3      # words/s below this → @speed_slow
    speed_slow: float = 1.08
    speed_mid_rate: float = 2.6       # … below this → @speed_mid
    speed_mid: float = 1.05
    # M74 (owner: «начала дают мало контекста — "и второй момент, как я уже говорил…"»): the first sentence
    # a viewer hears after the hook must not lean on what was cut. False = the previous proposals.
    context_start: bool = False
    context_max_sec: float = 15.0     # … the thought right before may be added as context, at most this long
    context_drop_words: int = 5       # … a leaning first sentence of at most this many words may be dropped
    # M75 (M74 report: «Уйти.», «Контролер, да, допустим.», «Из чувства вины…» after its question was dropped):
    context_min_words: int = 0        # a start shorter than this (not a question) is a fragment; 0 = off
    # M76 (M75 report: 11h42 4 → 2 clips, Pxl 5 → 3 — starts that could be repaired were dropped):
    context_back: int = 1             # up to this many thoughts right before may be added as context (M74/M75: 1)
    context_later: bool = False       # the clip may start at a later sentence of its first thought that stands
    context_later_min_sec: float = 8.0   # … when at least this much of that thought is left
    # M83 (m80 hooks: all 5 cold opens were the clip's own first sentence — no teaser, the body went on from the
    # second one, «В инстинкты.», «А второй момент…»): the cold open is a line from later in the clip, replayed.
    hook_teaser: bool = False         # hook candidates only from hook_teaser_pos of the clip on, written h:B.N!
    hook_teaser_pos: float = 0.5      # … the sentence starts at least this fraction into the clip's sentences
    # M92 (m86: the model passed teasers «Это и есть доверие к себе», «Для меня это самый лучший отдых», «Но опять
    # подростковая часть…», «Он как-то хочет скриншот…»): a cold open pointing back is left out by the code.
    hook_no_pointer: bool = False
    # M91 (ending package, PLAN M1.7 B): the payoff is said in the close shot — the clip's last sentences
    # (at least close_last_sec of them, at most two) are written c:B.N.
    close_last: bool = False
    close_last_sec: float = 3.0
    # M115 (M1.9 C; M99: 62 of 65 endings of the owner's clips are «↘», one «→»): a clip does not end on a sentence
    # whose voice stays up — the speaker goes on. Needs end_tone in propose (the intonation map); False = as before.
    end_tone: bool = False


@dataclass
class Proposal:
    units: list[int]                  # play order
    pieces: str                       # "13.2-5 14.1 41.3-4"
    hook: str | None
    title: str
    caption: str
    score: int
    seconds: float
    notes: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)      # M61: all hook candidates, best first
    speed: float | None = None                          # M65: @speed by the clip's speech rate
    hook_texts: dict = field(default_factory=dict)      # M65: hook ref → (text, feature score) for ranking
    opener: int | None = None                           # M68: the thought that gives the title (t:)
    variant_of: int | None = None                       # M70: a short version of accepted clip M<n>
    bad_seams: int | None = None                        # M70: seams the model found jarring (None = not asked)
    unit_refs: dict = field(default_factory=dict)       # M74: a thought played without its first sentence → its refs
    hook_keep: bool = False                             # M83: the cold open is a teaser from later — h:B.N! (replayed)
    keys: list = field(default_factory=list)            # M88: [(B.N, word)] — k: words the subtitles highlight
    close: list = field(default_factory=list)           # M91: [B.N] — the last sentences in the close shot (c:)
    plate_mode: str = ""                                # M112: how the plate t: was written (hook | context; "" = not)

    def line(self, label: str) -> str:
        sp = f"@{self.speed:g}" if self.speed else ""
        parts = [f"M{label} {self.score}{sp}", self.pieces]
        if self.hook:
            parts.append(f"h:{self.hook}" + ("!" if self.hook_keep else ""))
        if self.close:
            parts.append("c:" + ",".join(self.close))
        if self.keys:
            parts.append("k:" + ";".join(f"{r}={w}" for r, w in self.keys))
        if self.title:
            parts.append(f"t: {self.title}")
        out = " | ".join(parts)
        if self.caption:
            out += f" | d: {self.caption}"
        return out


def _dur(u: dict) -> float:
    return float(u["t1"]) - float(u["t0"])


def eligible(u: dict, p: AutoParams) -> bool:
    if u.get("missing") or not u.get("refs") or u.get("role") in (None, "aside"):
        return False
    if u.get("filtered") and not p.use_filtered:
        return False
    return int(u.get("punch") or 0) >= p.min_punch


def leans_on(u: dict, by_id: dict) -> list[int]:
    """The chain of earlier units u leans on (refers, transitively), nearest first."""
    out, seen, cur = [], {u["id"]}, u
    while not cur.get("standalone", True) and cur.get("refers") in by_id and cur["refers"] not in seen:
        cur = by_id[cur["refers"]]
        seen.add(cur["id"])
        out.append(cur["id"])
    return out


def _pieces(units: Sequence[dict]) -> int:
    """Pieces after M58 joins: a unit right after the previous one in the source joins it."""
    n, prev = 0, None
    for u in units:
        if prev is None or u["id"] != prev["id"] + 1:
            n += 1
        prev = u
    return n


def _order(units: list[dict]) -> list[dict]:
    q = [u for u in units if u.get("role") == "question"]
    first = q[:1]
    rest = sorted((u for u in units if u not in first), key=lambda u: u["t0"])
    return first + rest


def _unit_score(u: dict, have: set[str]) -> float:
    s = 2.0 * int(u.get("punch") or 0) + float((u.get("voice") or {}).get("energy") or 50.0) / 25.0
    role = u.get("role")
    if role in OPENERS and not have & set(OPENERS):
        s += 2.0
    if role in PAYOFFS and "conclusion" not in have:
        s += 2.0
    if role in MIDDLE and not have & set(MIDDLE):
        s += 1.5
    return s


def build_clip(seed: dict, units: Sequence[dict], by_id: dict, p: AutoParams) -> list[dict] | None:
    chosen: dict[int, dict] = {}

    def add(u: dict) -> bool:
        group = [u] + [by_id[i] for i in leans_on(u, by_id)]
        if any(not eligible(g, p) and g["id"] not in chosen for g in group[1:]):
            # an earlier unit it leans on is unusable (filler / missing): this one cannot stand
            return False
        new = {g["id"]: g for g in group if g["id"] not in chosen}
        trial = {**chosen, **new}
        if sum(_dur(g) for g in trial.values()) > p.max_sec or _pieces(_order(list(trial.values()))) > p.max_pieces:
            return False
        chosen.update(new)
        return True

    if not add(seed):
        return None
    sims = {i for i, _ in (seed.get("similar") or [])}
    pool = [u for u in units if eligible(u, p) and u["id"] not in chosen
            and (u.get("topic") == seed.get("topic") or u["id"] in sims)]
    while sum(_dur(g) for g in chosen.values()) < p.target_sec and pool:
        have = {g.get("role") for g in chosen.values()}
        # prefer units close to what is chosen (fewer pieces), then the score
        pool.sort(key=lambda u: -_unit_score(u, have) + min(abs(u["t0"] - g["t0"]) for g in chosen.values()) / 500.0)
        u = pool.pop(0)
        add(u)
    clip = _order(list(chosen.values()))
    roles = {u.get("role") for u in clip}
    if sum(_dur(u) for u in clip) < p.min_sec or not roles & set(OPENERS + PAYOFFS):
        return None
    if clip[-1].get("role") == "question":
        return None                                   # never end on an open question
    return clip


_CONTRAST = ("на самом деле", "но ", "однако", "а вот", "парадокс", "наоборот", "вместо того", "не потому")
_STRONG = ("никогда", "всегда", "главное", "главная", "секрет", "ошибк", "важно", "самое", "страх", "боль",
           "любов", "счасть", "правд", "смерт", "деньг")
_YOU = ("вы", "вам", "вас", "ваш", "ваша", "ваше", "ваши", "ты", "тебе", "тебя", "твой", "твоя", "твоё", "твои")
_WEAK_START = ("и", "а", "это", "поэтому", "вот", "ну", "так", "то", "тоже", "потом", "тогда", "он", "она", "они")


def hook_score(text: str, sec: float, unit: dict | None = None) -> float:
    """M65: how likely a sentence makes a viewer stay (deterministic): a question, a contrast, a
    number, «вы», strong words, the voice's energy and the thought's strength; a sentence that leans
    back («И…», «Это…», «Поэтому…») or is a fragment scores low."""
    t = " " + " ".join((text or "").lower().replace("ё", "е").split()) + " "
    words = [w.strip(".,!?;:…—–«»\"'()") for w in t.split()]
    s = 0.0
    if t.rstrip().endswith("?"):
        s += 3.0
    if any(m in t for m in _CONTRAST):
        s += 2.0
    if any(ch.isdigit() for ch in t):
        s += 1.5
    if any(w in _YOU for w in words):
        s += 1.0
    if any(m in t for m in _STRONG):
        s += 1.0
    if words and words[0] in _WEAK_START and not t.rstrip().endswith("?"):
        s -= 2.0                          # «А вы знаете…?» is a fine opening; «И это так.» is not
    if 2.5 <= sec <= 6.0:
        s += 1.0
    elif sec < 1.5:
        s -= 2.0
    if unit:
        s += float((unit.get("voice") or {}).get("energy") or 50.0) / 50.0 + 0.5 * int(unit.get("punch") or 0)
    return round(s, 2)


# ── M74: a start that does not lean on what was cut ────────────────────────────────────────────────
# Phrases that point back to something the viewer did not hear (searched in the first 8 words) …
_BACK_PHRASES = ("как я уже говорил", "как я говорил", "как я уже сказал", "как я сказал", "как уже говорил",
                 "как уже было сказано", "как было сказано", "как мы говорили", "как мы уже", "о чем я говорил",
                 "о чем мы говорили", "второй момент", "третий момент", "следующий момент", "другой момент",
                 "во вторых", "в третьих", "кроме того", "к тому же", "помимо этого", "об этом", "про это",
                 "в этом случае", "то же самое", "тем более")
# … and first words that lean on the sentence before (connectors, pronouns, «второе»).
_BACK_START = frozenset({"и", "а", "но", "также", "тоже", "поэтому", "потому", "вот", "так", "значит", "то",
                         "это", "этот", "эта", "эти", "этого", "этим", "этом", "такой", "такая", "такое", "такие",
                         "он", "она", "оно", "они", "его", "ее", "их", "им", "там", "тогда", "потом", "затем",
                         "второе", "второй", "третье", "третий", "следующее", "причем", "ведь", "же", "который",
                         "которая", "которые", "однако", "или", "либо"})
_Q_OPEN_OK = frozenset({"и", "а", "но", "вот", "так", "ну"})   # «А что я сейчас чувствую?» opens fine


def _plain_words(text: str) -> list[str]:
    t = (text or "").lower().replace("ё", "е").replace("-", " ")
    return [w for w in ("".join(c if c.isalnum() else " " for c in t)).split() if w]


def back_reference(text: str) -> str | None:
    """M74: what in a sentence leans on something said before it — «как я уже говорил», «второй момент»,
    a first «И/Поэтому/Это…» — or None when it stands on its own. A question may open with «А/И/Вот…»."""
    words = _plain_words(text)
    if not words:
        return None
    head = " " + " ".join(words[:8]) + " "
    for ph in _BACK_PHRASES:
        if f" {ph} " in head:
            return f"«{ph}»"
    q = (text or "").rstrip().endswith("?")
    if words[0] in _BACK_START and not (q and words[0] in _Q_OPEN_OK):
        return f"«{words[0]}…»"
    return None


def teaser_pointer(text: str) -> str | None:
    """M92: what makes a cold open point back — it is heard first, with nothing before it: everything back_reference
    finds (a first «Это/Но/Он/Вот…», «второй момент», «как я говорил»), and «это» standing for an unsaid thing among
    the first three words («Для меня это самый лучший отдых») — but not «X — это …», a definition. None = stands."""
    import re as _re
    why = back_reference(text)
    if why:
        return why
    toks = _re.findall(r"\w+(?:-\w+)*|[—–-]", (text or "").lower().replace("ё", "е"))
    n = 0
    for i, t in enumerate(toks):
        if t in ("—", "–", "-"):
            continue
        n += 1
        if n > 3:
            break
        if t == "это" and not (i > 0 and toks[i - 1] in ("—", "–", "-")):
            return "«это» без предмета"
    return None


def _drop_first_ref(refs: str) -> str | None:
    """«13.2-5 14.1» → «13.3-5 14.1»; «13.2 14.1» → «14.1»; None when nothing is left."""
    pieces = refs.split()
    if not pieces:
        return None
    b, _, r = pieces[0].partition(".")
    a, _, z = r.partition("-")
    a_i, z_i = int(a), int(z or a)
    head = [f"{b}.{a_i + 1}" + (f"-{z_i}" if z_i > a_i + 1 else "")] if a_i < z_i else []
    return " ".join(head + pieces[1:]) or None


def keep_refs_until(refs: str, last: str) -> str | None:
    """«13.2-5 14.1-3» up to «14.2» → «13.2-5 14.1-2»; up to «13.4» → «13.2-4»; None when `last` is not in refs."""
    out = []
    lb, _, lk = last.partition(".")
    for piece in refs.split():
        b, _, r = piece.partition(".")
        a, _, z = r.partition("-")
        a_i, z_i = int(a), int(z or a)
        if b == lb and a_i <= int(lk) <= z_i:
            k = int(lk)
            out.append(f"{b}.{a_i}" + (f"-{k}" if k > a_i else ""))
            return " ".join(out)
        out.append(piece)
    return None


def fix_open_end(clip: list[dict], sentences, end_tone: Callable[[str], "str | None"], p: "AutoParams"
                 ) -> tuple[list[dict] | None, str | None, str | None]:
    """M115 (M1.9 C): one rule for every clip — it does not end on a sentence spoken «→», with the voice up (the
    intonation map: M99 — 62 of 65 endings of the owner's clips are «↘», one is «→»; inside clips 45 of 484 sentence
    ends are «→»). The text's full stop does not count, the voice does. The last thought loses its trailing sentences
    back to the latest finished one that is not «→», while the clip stays ≥ min_sec; otherwise the clip goes.
    «unsure» and «no pitch» endings stay (the plan reports them, as before). Returns (clip, note, None) — clip
    unchanged and note None when its ending is not «→» — or (None, None, why)."""
    last = clip[-1]
    rows = list(_sent_rows(sentences, last["refs"]))
    if not rows or end_tone(rows[-1][0]) != "open":
        return clip, None, None
    total = sum(_dur(u) for u in clip)
    cut = 0.0
    for k in range(len(rows) - 1, 0, -1):            # keep rows[:k]
        cut += float(rows[k][1] or 0.0)
        if total - cut < p.min_sec:
            break
        ref, _sec, _nw, complete, text = rows[k - 1]
        if complete and end_tone(ref) != "open":
            refs = keep_refs_until(last["refs"], ref)
            if refs:
                new_last = {**last, "refs": refs, "t1": float(last["t1"]) - cut}
                return (clip[:-1] + [new_last],
                        f"конец: «{(rows[-1][4] or rows[-1][0])[-50:]}» звучит с продолжением («→») — клип кончается на "
                        f"{ref} «{(text or ref)[-50:]}» (убрано фраз: {len(rows) - k})", None)
    return None, None, f"конец «{(rows[-1][4] or rows[-1][0])[-60:]}» звучит с продолжением («→»), укоротить нельзя"


Judge = Callable[[str, str, str], "tuple[bool, str] | None"]


def stands_alone(text: str, following: str, p: "AutoParams", judge: "Judge | None" = None,
                 core: str = "") -> str | None:
    """M74/M75: why a first sentence cannot open a clip, None = it can. Rules first (back_reference; a
    non-question shorter than context_min_words is a fragment — «Уйти.»), then the model, when given, on
    what rules cannot see («Хоть это…», an answer to an unheard question). The model only says yes/no;
    no answer = the rules' verdict (invariant 11: never a silent «fine» — the caller notes it)."""
    why = back_reference(text)
    if why:
        return f"ссылка назад {why}"
    n = len(_plain_words(text))
    if p.context_min_words and n < p.context_min_words and not (text or "").rstrip().endswith("?"):
        return f"обрывок ({n} сл.)"
    if judge is not None:
        verdict = judge(text, following, core)
        if verdict is not None and not verdict[0]:
            return f"не годится в начало (модель: {verdict[1] or 'нет'})"
    return None


def context_start(clip: list[dict], by_id: dict, p: "AutoParams", sentences, *, seed_id: int | None = None,
                  loop_id: int | None = None, judge: "Judge | None" = None
                  ) -> tuple[list[dict] | None, list[str], str | None]:
    """M74: one rule for every clip — the first sentence after the hook stands on its own. When it does not
    (stands_alone), in this order:
    (a) a short leaning sentence (≤ context_drop_words) before one that stands is dropped — never a question
        (M75: its answer would be left as a fragment, Pxl «То есть, а из чего?» → «Из чувства вины…»);
    (b) the thought right before it in the source is added as context (≤ context_max_sec, standing itself;
        not for a loop question — that one simply goes); M76: up to context_back thoughts back, when the nearest
        does not stand but the one before it does (together ≤ context_max_sec);
    (b2) M76 (context_later): the clip starts at the first later sentence of that thought that stands — never an
        answer cut from its question — while at least context_later_min_sec of the thought is left;
    (c) a loop question, or an opening thought nothing else needs (not the seed), goes;
    otherwise the clip cannot start — (None, notes, why). Returns (clip, notes, None) when it can."""
    notes: list[str] = []
    # M78: what the clip is about (its seed and its payoff) — the model judges whether the start leads into it
    core = " ".join(dict.fromkeys(str(by_id[i].get("summary") or "") for i in (seed_id, clip[-1]["id"])
                                  if i in by_id)).strip()
    for _ in range(6):
        u = clip[0]
        rows = list(_sent_rows(sentences, u["refs"]))
        if not rows:
            return clip, notes, None
        first = rows[0][4] or rows[0][0]
        nxt = rows[1][4] if len(rows) > 1 else ""
        why = stands_alone(rows[0][4], nxt, p, judge, core)
        if not why:
            return clip, notes, None
        if (len(rows) >= 2 and rows[0][2] <= p.context_drop_words and not first.rstrip().endswith("?")
                and stands_alone(rows[1][4], rows[2][4] if len(rows) > 2 else "", p, judge, core) is None):
            refs = _drop_first_ref(u["refs"])
            if refs:
                clip = [{**u, "refs": refs, "t0": float(u["t0"]) + float(rows[0][1])}] + clip[1:]
                notes.append(f"начало: убрана фраза «{first[:60]}» ({why})")
                continue
        ids = {c["id"] for c in clip}
        if u["id"] != loop_id:
            ctx: list[dict] = []
            for back in range(1, max(1, p.context_back) + 1):
                prev = by_id.get(u["id"] - back)
                nxt_u = ctx[0] if ctx else u
                if (prev is None or prev["id"] in ids or prev.get("missing") or not prev.get("refs")
                        or (prev.get("filtered") and not p.use_filtered)
                        or float(nxt_u["t0"]) - float(prev["t1"]) > 3.0):
                    break
                ctx = [prev] + ctx
                if (sum(_dur(c) for c in ctx) > p.context_max_sec
                        or sum(_dur(c) for c in clip + ctx) > p.max_sec or _pieces(ctx + clip) > p.max_pieces + 1):
                    break
                prow = list(_sent_rows(sentences, prev["refs"]))
                after = prow[1][4] if len(prow) > 1 else (list(_sent_rows(sentences, nxt_u["refs"])) or [("",) * 5])[0][4]
                if prow and stands_alone(prow[0][4], after, p, judge, core) is None:
                    notes.append(f"начало: добавлен{'а мысль' if len(ctx) == 1 else 'ы мысли'} "
                                 + ", ".join(f"#{c['id']}" for c in ctx)
                                 + f" «{(prow[0][4] or '')[:50]}» перед «{first[:50]}» ({why}) — контекст")
                    return ctx + clip, notes, None
        if p.context_later and len(rows) >= 2:
            total = sum(float(r[1]) for r in rows)
            for k in range(1, len(rows)):
                if (rows[k - 1][4] or "").rstrip().endswith("?"):
                    continue                      # an answer is not cut from its question
                left = sum(float(r[1]) for r in rows[k:])
                if left < p.context_later_min_sec or sum(_dur(c) for c in clip) - (total - left) < p.min_sec:
                    break
                if stands_alone(rows[k][4], rows[k + 1][4] if k + 1 < len(rows) else "", p, judge, core) is None:
                    refs = u["refs"]
                    for _ in range(k):
                        refs = _drop_first_ref(refs) or refs
                    clip = [{**u, "refs": refs, "t0": float(u["t0"]) + (total - left)}] + clip[1:]
                    notes.append(f"начало: со фразы «{(rows[k][4] or '')[:50]}» — до неё убрано {k} "
                                 f"(«{first[:40]}…»: {why})")
                    break
            if clip[0] is not u:
                continue
        needed = {i for c in clip for i in leans_on(c, by_id)}
        if (len(clip) > 1 and (u["id"] == loop_id or (u["id"] != seed_id and u["id"] not in needed))
                and sum(_dur(c) for c in clip[1:]) >= p.min_sec):
            clip = clip[1:]
            notes.append(f"начало: мысль #{u['id']} «{first[:50]}» убрана ({why})")
            continue
        return None, notes, f"«{first[:70]}» — {why}"
    return None, notes, "начало не найдено"


STANDALONE_SYSTEM = (
    "A short vertical video is cut from the middle of a Russian talk. After a 3-second teaser it starts with the "
    "FIRST SENTENCE below; the viewer has heard NOTHING of the talk before it. You also get what the clip is about. "
    "Answer three things. subject: what the first sentence is about, in at most 5 Russian words — empty if a viewer "
    "could not tell. alone: true if it makes sense on its own — no pronoun or «это/так/вот/тот» pointing to "
    "something not said, not an answer to a question the viewer did not hear, not a fragment or a filler («да, "
    "допустим»), not a continuation of an enumeration, no term used as if it had been introduced before («перенос», "
    "«этот метод»). leads: true if it leads into what the clip is about — not a side detail, an aside, or a remark "
    "about the room, the furniture or the setting. The following sentence only helps you understand the first. "
    "Answer only with JSON: {\"subject\": \"<words>\", \"alone\": true|false, \"leads\": true|false, "
    "\"why\": \"<at most 8 Russian words>\"}."
)


HOOK_JUDGE_SYSTEM = (
    "A short vertical video (a reel) cut from a Russian talk opens with a TEASER LINE — the first thing the viewer "
    "hears, 2–5 seconds, before the clip proper. The viewer has heard nothing else. You also get what the clip is "
    "about. Answer three things. subject: what the line is about, in at most 5 Russian words — empty if a viewer "
    "could not tell. alone: true if it makes sense on its own — no pronoun or «это/так/вот/тот» pointing to something "
    "not said, not an answer to a question the viewer did not hear, not a fragment or a filler, no term used as if it "
    "had been introduced before. leads: true if it is about what the clip is about and makes the viewer want the "
    "answer — not a side detail, an aside, or a remark about the room, the furniture or the setting. Answer only with "
    "JSON: {\"subject\": \"<words>\", \"alone\": true|false, \"leads\": true|false, \"why\": \"<at most 8 Russian "
    "words>\"}."
)


def judge_hooks(pr: "Proposal", judge: "Judge", core: str = "", *, top: int = 6,
                log: Callable[[str], None] = print) -> list[str]:
    """M81 (owner: IMG r03/r06 «начинаются с фразы про кресло — мало информативна»; M78 judged only the first sentence
    of the body, the cold open is heard before it): the model's yes/no on the first `top` hook candidates with the
    same three questions (subject, alone, leads into the clip). A rejected candidate leaves the list before the
    model ranks the rest (invariant 1: it only filters the code's candidates); no answer = kept. When none of them
    passes, the clip has no cold open — the body starts the reel. Returns the notes written."""
    notes: list[str] = []
    cands = list(pr.hooks)
    kept: list[str] = []
    dropped: list[str] = []
    for ref in cands[:top]:
        text = (pr.hook_texts.get(ref) or ("", 0))[0]
        if not text:
            kept.append(ref)
            continue
        v = judge(text, "", core)
        if v is not None and not v[0]:
            dropped.append(f"h:{ref} «{text[:50]}» — {v[1] or 'нет'}")
        else:
            kept.append(ref)
    rest = cands[top:]
    if dropped:
        notes.append("крючки отброшены моделью: " + "; ".join(dropped))
    if not kept:
        pr.hooks, pr.hook = [], None
        notes.append(f"крючок: ни один из первых {min(top, len(cands))} не прошёл проверку — сборка без крючка")
    else:
        pr.hooks = kept + rest
        pr.hook = kept[0]
    pr.notes.extend(notes)
    return notes


def make_judge(provider, *, log: Callable[[str], None] = print, system: str | None = None,
               label: str = "First sentence", store=None) -> "Judge":
    """M75: the model's yes/no on «does this first sentence stand on its own» — cached per sentence, one retry,
    None when there is no usable answer (the rules' verdict then stands). M86: `label` names the line in the
    request («Teaser line» for a cold open; the following sentence is then sent only when given); `store` — a
    persistent mapping (hash of the prompt and the request → [ok, why]): the same line asked the same way gets
    the same answer in every run (a borderline start no longer flips between runs); no answer is not stored."""
    import hashlib as _hashlib
    import json as _json
    import re as _re
    cache: dict = {}
    sys_text = system or STANDALONE_SYSTEM

    def judge(text: str, following: str = "", core: str = ""):
        key = (text, following, core)
        if key in cache:
            return cache[key]
        if label == "First sentence":
            msg = (f"First sentence: «{text}»\nFollowing sentence: «{following}»"
                   + (f"\nThe clip is about: {core}" if core else ""))
        else:
            msg = (f"{label}: «{text}»" + (f"\nFollowing sentence: «{following}»" if following else "")
                   + (f"\nThe clip is about: {core}" if core else ""))
        skey = _hashlib.sha256((sys_text + "\n\n" + msg).encode("utf-8")).hexdigest()[:32] if store is not None else ""
        if store is not None and skey in store:
            v = store[skey]
            cache[key] = (bool(v[0]), str(v[1])) if isinstance(v, (list, tuple)) and len(v) == 2 else None
            if cache[key] is not None:
                return cache[key]
        out = None
        for _ in range(2):
            try:
                raw = provider.complete([{"role": "system", "content": sys_text},
                                         {"role": "user", "content": msg}], temperature=0.0)
            except Exception as exc:  # noqa: BLE001 — no model: the rules decide
                log(f"  начало: модель не ответила ({type(exc).__name__})")
                break
            m = _re.search(r"\{.*\}", raw or "", _re.S)
            try:
                obj = _json.loads(m.group(0)) if m else {}
            except ValueError:
                continue
            why = str(obj.get("why") or "").strip()[:60]
            if isinstance(obj.get("alone"), bool) and isinstance(obj.get("leads"), bool):
                # M78: two questions and a named subject — any «no» (or no subject) rejects the start
                subj = str(obj.get("subject") or "").strip()
                if not subj:
                    out = (False, why or "не ясно, о чём фраза")
                elif not obj["alone"]:
                    out = (False, why or "непонятно без предыдущего")
                elif not obj["leads"]:
                    out = (False, why or f"не про тему ролика («{subj[:30]}»)")
                else:
                    out = (True, subj[:40])
                break
            if isinstance(obj.get("ok"), bool):
                out = (obj["ok"], why)
                break
        cache[key] = out
        if store is not None and out is not None:
            store[skey] = [bool(out[0]), str(out[1])]
        return out

    judge.cache = cache   # type: ignore[attr-defined]
    return judge


# M86: the cold open is judged as a teaser, not as a start (M85: «И никогда, ребятки, не поздно.» and «Поздно — это
# когда уже завтра заказан священник.» were rejected for leaving a question open — which is the teaser's job).
HOOK_TEASER_SYSTEM = (
    "A short vertical video (a reel) cut from a Russian talk opens with a TEASER LINE taken from later in the clip: "
    "it is heard first, cold, 2–5 seconds, and the clip then answers it or pays it off. You get the teaser line and "
    "what the clip is about, with the words of its ending. Answer three things. subject: what the line is about, in "
    "at most 5 Russian words — empty only if a viewer could not tell even roughly. alone: false only when the line "
    "points back to something not said — a pronoun or «это/так/вот/тот» standing for an unsaid thing, an answer to "
    "a question the viewer did not hear, «второй момент», «как я говорил», a fragment or a filler; an open question, "
    "a provocative claim, a punchline or a paradox is GOOD — leaving the viewer wanting the answer is what a teaser "
    "is for; «это» used as «is» in a definition («Поздно — это когда…») is not a pointer. leads: true if the clip "
    "develops, answers or pays off the line (judge by the words of the ending, not by the summary alone); false for a "
    "remark about the room, the furniture or the setting, or an aside the clip does not develop. Answer only with "
    "JSON: {\"subject\": \"<words>\", \"alone\": true|false, \"leads\": true|false, \"why\": \"<at most 8 "
    "Russian words>\"}."
)


def owner_examples(rows: Sequence[dict], kind: str, n: int) -> tuple[list[str], list[str]]:
    """M86 (learning, stage 1): lines from the owner's own verdicts (reviews/verdicts.jsonl, M82) → (rejected, kept),
    the latest `n` of each, no repeats. kind «hook»: the cold open of a montage clip (draft note «крючок: «…»»),
    rejected when the verdict is drop/fix with the reason «крючок»; kind «start»: the first sentence (note
    «начало: «…»»), rejected with the reason «начало». Kept: verdict ok. Real data with its origin (invariant 11)."""
    tag, reason = ("крючок: «", "крючок") if kind == "hook" else ("начало: «", "начало")
    bad: list[str] = []
    good: list[str] = []
    for r in rows:
        if r.get("kind") != "montage":
            continue
        text = ""
        for note in r.get("draft_notes") or []:
            if note.startswith(tag) and note.endswith("»"):
                text = note[len(tag):-1].strip()
        if not text:
            continue
        verdict, reasons = r.get("verdict"), [str(x).lower() for x in r.get("reasons") or []]
        target = bad if verdict in ("drop", "fix") and reason in reasons else good if verdict == "ok" else None
        if target is not None:
            if text in target:
                target.remove(text)
            target.append(text)
    return bad[-n:] if n > 0 else [], good[-n:] if n > 0 else []


def with_examples(system: str, bad: Sequence[str], good: Sequence[str], what: str) -> str:
    """M86: the channel owner's verdicts appended to a judge's prompt — real lines he rejected or kept as a `what`."""
    if not bad and not good:
        return system
    out = system + f"\nThe channel owner's own verdicts on earlier reels — judge new lines the same way."
    if bad:
        out += f"\nRejected as a {what}: " + "; ".join(f"«{t}»" for t in bad)
    if good:
        out += f"\nKept as a {what}: " + "; ".join(f"«{t}»" for t in good)
    return out


def _sent_rows(sentences, refs):
    """sentences(refs) rows → (ref, sec, nwords, complete, text) (text optional in older callers)."""
    for row in sentences(refs):
        ref, sec, nwords, complete = row[:4]
        yield ref, sec, nwords, complete, (row[4] if len(row) > 4 else "")


def _hook_cands(clip: Sequence[dict], sentences, p: AutoParams) -> list[tuple[str, float, str]]:
    """(ref, score, text) of every hook candidate, best first: finished sentences of hook length of the
    clip's thoughts. When a question opens the clip (the loop), its own sentences are left out — the
    cold open then teases the answer instead of repeating the question. M83 (`hook_teaser`): only sentences
    that start at least `hook_teaser_pos` into the clip (by the length of its sentences in play order) — a
    teaser of what is coming, never the start the clip opens with anyway."""
    skip = clip[0]["id"] if clip and clip[0].get("role") == "question" and len(clip) > 1 else None
    rows = [(u, list(_sent_rows(sentences, u["refs"]))) for u in clip]
    total = sum(float(r[1] or 0.0) for _, rs in rows for r in rs)
    out = []
    at = 0.0
    for u, rs in rows:
        for ref, sec, nwords, complete, text in rs:
            start, at = at, at + float(sec or 0.0)
            if u["id"] == skip or int(u.get("punch") or 0) < p.min_punch:
                continue
            if p.hook_teaser and (total <= 0 or start / total < p.hook_teaser_pos):
                continue                  # M83: in the first part — the clip plays it at once, it teases nothing
            if p.hook_teaser and p.hook_no_pointer and teaser_pointer(text):
                continue                  # M92: heard cold, a line pointing back explains nothing
            if complete and nwords >= p.hook_min_words and p.hook_min_sec <= sec <= p.hook_max_sec:
                bonus = 1.0 if u.get("role") in HOOK_ROLES else 0.0
                if p.context_start and back_reference(text):
                    bonus -= 3.0          # M74: a cold open that points back («как я говорил») explains nothing
                out.append((ref, hook_score(text, sec, u) + bonus, text))
    return sorted(out, key=lambda x: -x[1])


TEASER_PROBE_POS = 1 / 3      # M106: the «what if the teaser could come from this far on» count in the note (a measure)


def teaser_misses(clip: Sequence[dict], sentences, p: AutoParams) -> tuple[int, dict[str, int]]:
    """M106 (m105: 3 of 5 clips of PXL_20260729_copy without a cold open, the reason unseen): the sentences from
    hook_teaser_pos of the clip on, and why each is not a teaser — the first rule of _hook_cands it fails, in its
    order: (number of sentences there, {reason: count})."""
    skip = clip[0]["id"] if clip and clip[0].get("role") == "question" and len(clip) > 1 else None
    rows = [(u, list(_sent_rows(sentences, u["refs"]))) for u in clip]
    total = sum(float(r[1] or 0.0) for _, rs in rows for r in rs)
    at, n, why = 0.0, 0, {}
    for u, rs in rows:
        for _ref, sec, nwords, complete, text in rs:
            start, at = at, at + float(sec or 0.0)
            if total <= 0 or start / total < p.hook_teaser_pos:
                continue
            n += 1
            if u["id"] == skip:
                r = "вопрос-петля"
            elif int(u.get("punch") or 0) < p.min_punch:
                r = "слабая мысль"
            elif p.hook_no_pointer and teaser_pointer(text):
                r = "ссылка назад"
            elif not complete:
                r = "незаконченная"
            elif nwords < p.hook_min_words:
                r = f"короче {p.hook_min_words} слов"
            elif float(sec or 0.0) < p.hook_min_sec:
                r = f"короче {p.hook_min_sec:g} с"
            elif float(sec or 0.0) > p.hook_max_sec:
                r = f"длиннее {p.hook_max_sec:g} с"
            else:
                r = "прошла"
            why[r] = why.get(r, 0) + 1
    return n, why


def _hooks(clip: Sequence[dict], sentences, p: AutoParams) -> list[str]:
    """Hook candidates, best first (M61: the check falls back to the next one when the plan skips one)."""
    return [r for r, _, _ in _hook_cands(clip, sentences, p)]


def _hook(clip, sentences, p) -> str | None:
    h = _hooks(clip, sentences, p)
    return h[0] if h else None


def _loop_question(clip: list[dict], units: Sequence[dict], by_id: dict, p: AutoParams,
                   taken: set[int]) -> dict | None:
    """M65: a question the clip answers — one a chosen thought leans on, else one of the clip's topic
    (or «similar» to its seed); short, standalone enough, not used elsewhere."""
    ids = {u["id"] for u in clip}
    leaned = {i for u in clip for i in leans_on(u, by_id)}
    topics = {u.get("topic") for u in clip}
    sims = {i for u in clip for i, _ in (u.get("similar") or [])}
    best, best_s = None, 0.0
    for q in units:
        if (q.get("role") != "question" or q["id"] in ids or q["id"] in taken or not eligible(q, p)
                or _dur(q) > p.loop_max_sec):
            continue
        s = 3.0 * (q["id"] in leaned) + 1.5 * (q.get("topic") in topics) + 1.0 * (q["id"] in sims)
        if s <= 0:
            continue
        s += 0.5 * int(q.get("punch") or 0)
        if s > best_s:
            best, best_s = q, s
    return best


def _prune(clip: list[dict], by_id: dict, p: AutoParams) -> tuple[list[dict], list[int]]:
    """M65: drop the weakest middle thoughts (not the opener, not the payoff, nothing another chosen
    thought leans on) while the clip is longer than target_sec + prune_slack and stays ≥ min_sec."""
    dropped: list[int] = []
    while sum(_dur(u) for u in clip) > p.target_sec + p.prune_slack and len(clip) > 2:
        needed = {i for u in clip for i in leans_on(u, by_id)}
        middle = [u for u in clip[1:-1] if u["id"] not in needed]
        if not middle:
            break
        weak = min(middle, key=lambda u: (int(u.get("punch") or 0),
                                          float((u.get("voice") or {}).get("energy") or 50.0)))
        if sum(_dur(u) for u in clip) - _dur(weak) < p.min_sec:
            break
        clip = [u for u in clip if u is not weak]
        dropped.append(weak["id"])
    return clip, dropped


def _speed(clip: Sequence[dict], p: AutoParams) -> float | None:
    """M65: @speed by the clip's speech rate (map voice.rate, words/s, weighted by duration)."""
    rated = [(float((u.get("voice") or {}).get("rate") or 0.0), _dur(u)) for u in clip]
    tot = sum(d for r, d in rated if r > 0)
    if tot <= 0:
        return None
    rate = sum(r * d for r, d in rated if r > 0) / tot
    if rate < p.speed_slow_rate:
        return p.speed_slow
    if rate < p.speed_mid_rate:
        return p.speed_mid
    return None


def propose(units: Sequence[dict], p: AutoParams = AutoParams(),
            sentences: Callable[[str], list[tuple[str, float, int, bool]]] | None = None,
            no_start: list | None = None, judge: "Judge | None" = None,
            end_tone: Callable[[str], "str | None"] | None = None, open_end: list | None = None) -> list[Proposal]:
    """Best `p.clips` proposals. `sentences(refs)` → [(B.k, seconds, words, finished)] of a unit's
    references (for the hook); None = no hook. `no_start` (M74) collects (pieces, why) of clips that found
    no start standing on its own; `judge` (M75) — the model's yes/no on a first sentence (make_judge).
    M115: `end_tone(B.k)` → «final» | «open» | «unsure» | None — the voice at the end of that sentence; with
    p.end_tone a clip does not end «→» (fix_open_end); `open_end` collects (pieces, why) of the clips that went."""
    by_id = {u["id"]: u for u in units}
    seeds = sorted((u for u in units if eligible(u, p) and u.get("role") in STORY
                    and int(u.get("punch") or 0) >= p.seed_punch),
                   key=lambda u: (-int(u["punch"]), -float((u.get("voice") or {}).get("energy") or 50.0), u["t0"]))
    out: list[Proposal] = []
    used_seeds: set[int] = set()
    for seed in seeds:
        if seed["id"] in used_seeds:
            continue
        clip = build_clip(seed, units, by_id, p)
        if clip is None:
            continue
        extra_notes: list[str] = []
        loop_id = None
        if p.loop and clip[0].get("role") != "question":
            taken = {i for o in out for i in o.units}
            q = _loop_question(clip, units, by_id, p, taken)
            if q is not None and sum(_dur(u) for u in clip) + _dur(q) <= p.max_sec \
                    and _pieces([q] + clip) <= p.max_pieces + 1:
                clip = [q] + clip
                loop_id = q["id"]
                extra_notes.append(f"вопрос-петля: #{q['id']} «{q.get('summary') or ''}» открывает, ответ — в конце")
        if p.prune:
            clip, dropped = _prune(clip, by_id, p)
            if dropped:
                extra_notes.append("убраны слабые мысли из середины: " + ", ".join(f"#{i}" for i in dropped))
        unit_refs: dict = {}
        if p.context_start and sentences:
            clip2, cnotes, why = context_start(clip, by_id, p, sentences, seed_id=seed["id"], loop_id=loop_id,
                                               judge=judge)
            if clip2 is None:
                if no_start is not None:
                    no_start.append((" ".join(u["refs"] for u in clip), why))
                continue
            clip = clip2
            extra_notes += cnotes
            unit_refs = {u["id"]: u["refs"] for u in clip if u["refs"] != by_id[u["id"]]["refs"]}
            _r0 = list(_sent_rows(sentences, clip[0]["refs"]))
            if _r0:
                extra_notes.append(f"начало: «{(_r0[0][4] or _r0[0][0])[:80]}»")
        if p.end_tone and end_tone is not None and sentences:
            clip3, enote, ewhy = fix_open_end(clip, sentences, end_tone, p)
            if clip3 is None:
                gone = (" ".join(u["refs"] for u in clip), ewhy)
                if open_end is not None and gone not in open_end:     # another seed may build the same clip
                    open_end.append(gone)
                continue
            if enote:
                clip = clip3
                extra_notes.append(enote)
                unit_refs = {**unit_refs, clip[-1]["id"]: clip[-1]["refs"]}
        ids = [u["id"] for u in clip]
        if any(len(set(ids) & set(o.units)) > p.overlap_max * min(len(ids), len(o.units))
               or ids[-1] == o.units[-1] for o in out):
            continue                      # M61: nor two clips with the same payoff (IMG_6848 M1/M4)
        used_seeds.update(i for i in ids if by_id[i].get("role") in STORY)
        secs = sum(_dur(u) for u in clip)
        roles = [u.get("role") for u in clip]
        punch = sum(int(u.get("punch") or 0) for u in clip) / len(clip)
        energy = sum(float((u.get("voice") or {}).get("energy") or 50.0) for u in clip) / len(clip)
        cover = 5 * bool(set(roles) & set(OPENERS)) + 5 * bool(set(roles) & set(MIDDLE)) + 5 * ("conclusion" in roles)
        loop = clip[0].get("role") == "question" and clip[-1].get("role") in PAYOFFS
        over = max(0.0, secs - p.target_sec)
        score = 15 * punch + 0.15 * energy + cover - 4 * (_pieces(clip) - 1) + 10 * loop - 0.2 * over
        opener = next((u for u in clip if u.get("role") in OPENERS), clip[0])
        payoff = next((u for u in reversed(clip) if u.get("role") in PAYOFFS), clip[-1])
        notes = [f"#{u['id']} {u.get('role')}★{u.get('punch')} {u['refs']} — {u.get('summary') or ''}" for u in clip]
        notes += extra_notes
        cands = _hook_cands(clip, sentences, p) if sentences else []
        close: list[str] = []
        if p.close_last and sentences:                  # M91: the payoff in the close shot
            rows = [r for u in clip for r in _sent_rows(sentences, u["refs"])]
            acc = 0.0
            for ref, sec, _nw, _c, _t in reversed(rows):
                if len(close) == 2 or (close and acc >= p.close_last_sec):
                    break
                close.insert(0, ref)
                acc += float(sec or 0.0)
        if p.hook_teaser and sentences and not cands:
            n2, why2 = teaser_misses(clip, sentences, p)
            parts = ", ".join(f"{k} — {v}" for k, v in sorted(why2.items(), key=lambda kv: -kv[1]))
            probe = len(_hook_cands(clip, sentences, replace(p, hook_teaser_pos=TEASER_PROBE_POS)))
            notes.append(f"крючок: во второй части клипа (с {p.hook_teaser_pos:.0%}) нет фразы для тизера — "
                         f"сборка без крючка (фраз там {n2}{': ' + parts if parts else ''}; "
                         f"с {TEASER_PROBE_POS:.0%} клипа нашлось бы {probe})")
        if clip[0].get("role") == "question" and clip[0]["t0"] > min(u["t0"] for u in clip):
            notes.append("вопрос из более позднего места открывает клип (вопрос-петля)")
        out.append(Proposal(
            units=ids, pieces=" ".join(u["refs"] for u in clip),
            hook=cands[0][0] if cands else None, hooks=[r for r, _, _ in cands],
            hook_texts={r: (t, sc) for r, sc, t in cands}, speed=_speed(clip, p),
            # M93: the post text d: is the payoff's summary even when the payoff is the opening thought — a clip
            # without it has no <rid>.txt and crosspost refuses a post without text (Pxl 112938952 r02 in m88)
            title=_clean(opener.get("summary")), caption=_clean(payoff.get("summary") or opener.get("summary")),
            opener=opener["id"], unit_refs=unit_refs, hook_keep=p.hook_teaser, close=close,
            score=max(40, min(95, round(score))), seconds=round(secs, 1), notes=notes))
    out.sort(key=lambda o: -o.score)
    return out[:p.clips]


def too_close(pr: "Proposal", accepted: Sequence["Proposal"], max_shared: int = 0) -> str | None:
    """M68: a viewer sees two reels of one source side by side — no two may open on the same thought
    (11h42 r01/r03: both «Вы не сломаны, просто не изучали себя») nor reuse more than max_shared
    thoughts (Pxl 112938952 M3/M5 shared 33.7 34.1-3). Returns the reason, None = distinct enough."""
    for i, o in enumerate(accepted, 1):
        if pr.opener is not None and pr.opener == o.opener:
            return f"то же начало, что у M{i} (#{pr.opener})"
        if pr.title and _norm_title(pr.title) == _norm_title(o.title):   # M78: «жёсткий» = «жесткий»
            return f"тот же заголовок, что у M{i}"
        shared = sorted(set(pr.units) & set(o.units))
        if len(shared) > max_shared:
            return f"общие мысли с M{i}: " + ", ".join(f"#{u}" for u in shared)
    return None


def _norm_title(t) -> str:
    return " ".join(_plain_words(str(t or "")))


def _clean(s) -> str:
    return " ".join(str(s or "").replace("|", " ").split())[:90]



HOOK_SYSTEM = (
    "You pick the opening line (the cold open) of a short vertical video (a reel, 30–60 s) cut from a "
    "Russian talk. The first 2–3 seconds decide whether a viewer stays. Prefer a line that opens a "
    "question in the viewer's head or promises a payoff: a surprising claim, a contrast, a concrete "
    "number, a direct «вы», a strong feeling. Avoid lines that depend on what came before («Это…», "
    "«Поэтому…»), greetings and fragments. Answer only with JSON: {\"best\": <number>, \"why\": \"<at most 12 "
    "Russian words>\"}."
)


def rank_hooks(pr: "Proposal", provider, *, top: int = 6, log: Callable[[str], None] = print) -> bool:
    """M65: the LLM picks the best of the top hook candidates (invariant 1: it only ranks the
    deterministic candidates; an answer outside them is retried once, then the code's order stays).
    Returns True when the order changed."""
    import json as _json
    import re as _re
    cands = pr.hooks[:top]
    if len(cands) < 2:
        return False
    rows = [f"{i + 1}. {pr.hook_texts.get(r, ('', 0))[0]}" for i, r in enumerate(cands)]
    msg = (f"Reel: «{pr.title}». Thoughts: " + "; ".join(n.split(" — ", 1)[-1] for n in pr.notes[:6]) +
           "\nCandidates:\n" + "\n".join(rows))
    for _ in range(2):
        try:
            raw = provider.complete([{"role": "system", "content": HOOK_SYSTEM}, {"role": "user", "content": msg}],
                                    temperature=0.0)
        except Exception as exc:  # noqa: BLE001 — no model: the code's order stays
            log(f"  крючок: модель не ответила ({type(exc).__name__})")
            return False
        m = _re.search(r"\{.*\}", raw or "", _re.S)
        try:
            obj = _json.loads(m.group(0)) if m else {}
            best = int(obj.get("best"))
        except (ValueError, TypeError):
            continue
        if 1 <= best <= len(cands):
            chosen = cands[best - 1]
            why = str(obj.get("why") or "").strip()[:80]
            if chosen != pr.hooks[0]:
                pr.hooks = [chosen] + [h for h in pr.hooks if h != chosen]
                pr.hook = chosen
                pr.notes.append(f"крючок выбран моделью: h:{chosen}" + (f" — {why}" if why else ""))
                return True
            return False
    log("  крючок: ответ модели вне кандидатов — порядок кода")
    return False


# ── M88: key words of the subtitles ────────────────────────────────────────────────────────────────

KEYWORDS_SYSTEM = (
    "You mark the key words in the subtitles of a short vertical video (a reel cut from a Russian talk): the words "
    "the speaker stresses and the viewer should remember. You get the clip's sentences, numbered. Pick at most {n} "
    "sentences that carry the main point and in each of them ONE word, written exactly as in that sentence: the word "
    "that carries the meaning — a noun, a verb, a number or a strong adjective; never a pronoun, a conjunction, a "
    "particle, a filler or a function word. Answer only with JSON: {{\"keys\": [{{\"s\": <number>, \"word\": "
    "\"<word>\"}}]}}."
)
_KEY_STOP = frozenset("это этот эта эти так вот что как все всё они она оно его ее её мы вы ты он я там тут где "
                      "когда тогда если чтобы потому поэтому тоже также уже еще ещё просто очень какой какая "
                      "такой такая быть есть был была было который которая которые "
                      # M93 (m88: «себя» marked in two clips): reflexive and possessive pronouns carry no meaning
                      "себя себе собой свой своя свое своё свои своего своей мой моя мое моё мои твой наш ваш "
                      "меня мне тебя тебе нас нам вас вам него нее неё них нему ней ним".split())


def _kw_norm(w: str) -> str:
    """The k: matching rule of --apply (case, ё, edge punctuation ignored) — the form written into k:."""
    return w.lower().replace("ё", "е").strip(".,!?;:—–-\"'«»()[]")


def pick_keywords(rows: Sequence[tuple[str, str]], provider, *, n: int,
                  log: Callable[[str], None] = print) -> list[tuple[str, str]]:
    """M88: the model marks at most `n` key words — one per sentence — in the clip's sentences [(B.N, text)] (play
    order). Grounded (invariant 2): the word must be a word of that very sentence (the k: matching rule — case, ё,
    punctuation ignored), at least 3 letters, not a pronoun or a function word; anything else is dropped. One retry
    when the answer is not JSON; no model or no usable answer = no k: (the clip as before)."""
    import json as _json
    import re as _re
    if n <= 0 or not rows:
        return []
    msg = "Sentences:\n" + "\n".join(f"{i}. {t}" for i, (_r, t) in enumerate(rows, 1))
    for _ in range(2):
        try:
            raw = provider.complete([{"role": "system", "content": KEYWORDS_SYSTEM.format(n=n)},
                                     {"role": "user", "content": msg}], temperature=0.0)
        except Exception as exc:  # noqa: BLE001 — no model: no k:
            log(f"  ключевые слова: модель не ответила ({type(exc).__name__})")
            return []
        m = _re.search(r"\{.*\}", raw or "", _re.S)
        try:
            obj = _json.loads(m.group(0)) if m else None
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            continue
        out: dict[int, str] = {}
        for k in obj.get("keys") or []:
            if not isinstance(k, dict):
                continue
            try:
                i = int(str(k.get("s")).strip().rstrip("."))
            except ValueError:
                continue
            word = _kw_norm(str(k.get("word") or ""))
            if (not (1 <= i <= len(rows)) or i in out or sum(c.isalpha() for c in word) < 3 or word in _KEY_STOP
                    or not all(c.isalnum() or c == "-" for c in word)):
                continue
            if word not in {_kw_norm(w) for w in rows[i - 1][1].split()}:
                continue                              # not a word of that sentence — not grounded
            out[i] = word
            if len(out) >= n:
                break
        return [(rows[i - 1][0], out[i]) for i in sorted(out)]
    log("  ключевые слова: ответ модели не JSON — без k:")
    return []


# ── M70: hook headline, seam coherence, short versions ─────────────────────────────────────────────

def _norm_word(w: str) -> str:
    return "".join(c for c in w.lower().replace("ё", "е") if c.isalnum())


def grounded_title(title: str, text: str, *, max_chars: int = 60, max_words: int = 9) -> str | None:
    """M70: the plate headline the model wrote is used only when it stays in the clip's words (invariant 2):
    at most max_chars / max_words, no number the clip does not say, and at least 60 % of its content
    words (5+ letters) share their first 5 letters with a word of the clip. Returns why not, None = ok."""
    t = " ".join((title or "").split())
    if not t:
        return "пусто"
    if len(t) > max_chars:
        return f"длиннее {max_chars} знаков"
    words = [_norm_word(w) for w in t.split()]
    words = [w for w in words if w]
    if not 2 <= len(words) <= max_words:
        return f"слов {len(words)} (нужно 2–{max_words})"
    src = {_norm_word(w) for w in (text or "").split()}
    src.discard("")
    nums = {w for w in src if w.isdigit()}
    for w in words:
        if w.isdigit() and w not in nums:
            return f"число {w}, которого нет в ролике"
    content = [w for w in words if len(w) >= 5 and not w.isdigit()]
    if content:
        stems = {w[:5] for w in src if len(w) >= 5}
        hit = sum(1 for w in content if w[:5] in stems)
        if hit < 0.6 * len(content):
            return f"слова не из ролика ({hit} из {len(content)})"
    return None


_FIRST_PERSON = {"я", "мой", "моя", "мое", "мои", "мне", "меня", "мной", "моего", "моей", "моих"}


def title_problem(title: str, clip_text: str, core_text: str = "") -> str | None:
    """M71: hard rules every plate headline passes (one algorithm for every clip, not a taste):
    grounded in the clip (grounded_title), about the clip's core — at least one content word shared with
    its opener or payoff (core_text) — not about the speaker (no «я/мой…»), not a lecture plan
    («сначала… потом…»). Returns why not, None = usable."""
    why = grounded_title(title, clip_text)
    if why:
        return why
    words = [_norm_word(w) for w in title.split()]
    if any(w in _FIRST_PERSON for w in words):
        return "про говорящего («я/мой»), а не про зрителя"
    if "сначала" in words and "потом" in words:
        return "план лекции («сначала… потом…»)"
    if core_text:
        core = {_norm_word(w)[:5] for w in core_text.split() if len(_norm_word(w)) >= 5}
        if not any(len(w) >= 5 and w[:5] in core for w in words):
            return "не про начало и не про вывод ролика"
    return None


_TY = {"ты", "тебя", "тебе", "тобой", "твой", "твоя", "твое", "твои", "твоего", "твоей", "твоих"}
_CONTRAST_T = ("или", "против", "вместо", "лучше", "хуже", "а не", "не ", "но ")


def title_form(title: str) -> str:
    """M73: the shape of a headline — «question» or «statement» (for variety within one source)."""
    t = (title or "").rstrip()
    w = [_norm_word(x) for x in t.split()[:1]]
    return "question" if t.endswith("?") or (w and w[0] in _WH) else "statement"   # M77: «Почему мы…» asks too


def title_score(title: str, core_text: str = "", used_forms: Sequence[str] = ()) -> float:
    """M71/M73: one attention score for every plate headline. Signals, each small and general:
    a question (+1.5), a contrast (+1.5), «вы» (+0.5), strong words (+1), a number (+1); specific to this clip —
    content words shared with its opening or conclusion (+1 each, at most 2), a headline with fewer than two
    content words is generic (−1.5); one register — «ты» against the talk's «вы» (−1); a weak start «И…/Это…»
    (−2); 3–7 words (+1), more than 40 characters (−2); the same shape as headlines already chosen for this
    source (−1 for each), so one source does not get five «Вы…?» in a row."""
    t = " ".join((title or "").split())
    low = " " + t.lower().replace("ё", "е") + " "
    words = [_norm_word(w) for w in t.split()]
    words = [w for w in words if w]
    content = [w for w in words if len(w) >= 5 and not w.isdigit()]
    s = 0.0
    if t.rstrip().endswith("?"):
        s += 1.5
    if any(m in low for m in _CONTRAST_T) and len(words) >= 3:
        s += 1.5
    if any(w in _YOU for w in words):
        s += 0.5
    if any(m in low for m in _STRONG):
        s += 1.0
    if any(ch.isdigit() for ch in t):
        s += 1.0
    if core_text:
        core = {_norm_word(w)[:5] for w in core_text.split() if len(_norm_word(w)) >= 5}
        s += min(2, sum(1 for w in content if w[:5] in core))
    if len(content) < 2:
        s -= 1.5
    if any(w in _TY for w in words):
        s -= 1.0
    if words and words[0] in _WEAK_START and not t.rstrip().endswith("?"):
        s -= 2.0
    s += 1.0 if 3 <= len(words) <= 7 else 0.0
    s -= 2.0 if len(t) > 40 else 0.0
    s -= 1.0 * sum(1 for f in used_forms if f == title_form(t))
    return round(s, 2)


TITLE_SYSTEM = (
    "You write the headline shown in big letters during the first 3 seconds of a short vertical video (a reel) "
    "cut from a Russian talk. Its only job: make a viewer stay to get the answer the clip gives. Write THREE "
    "different headlines: a question to the viewer, a claim addressed to «вы», a contrast of two things. Rules: "
    "use only what the clip says (its own words where possible; no new facts, names or numbers); about the "
    "clip's main point — what it opens with or concludes, naming its own key words (not a generic «кто вы?»); "
    "about the viewer, never the speaker (no «я», «мой»); address the viewer as «вы», never «ты»; "
    "no lecture plan («сначала… потом…»); at most 7 Russian words and 40 characters; no quotes, emoji or "
    "hashtags. Answer only with JSON: {\"titles\": [\"<headline>\", \"<headline>\", \"<headline>\"]}."
)


_WH = frozenset({"как", "почему", "зачем", "что", "чем", "когда", "откуда", "где", "куда", "какой", "какая",
                 "какие", "каким", "сколько", "кто", "чего", "чему"})


def plate_score(title: str, core_text: str = "", used_forms: Sequence[str] = ()) -> float:
    """M74 (owner: «начала дают мало контекста»): the plate appears when the body starts, right after the hook —
    its job is to say WHAT the clip is about, the hook already pulled the viewer in. One score for every clip:
    specific — content words shared with the clip's opening or conclusion (+1 each, at most 3), fewer than two
    content words is no subject at all (−2); a question that names the subject («Почему мы боимся отказа»)
    is fine, a yes/no or «вы»-question is a second hook (−1.5); addressing the viewer (−0.5); a weak start
    «И…/Это…» (−2); 2–6 words (+1), more than 40 characters (−2); M77: the shape (question / statement) already
    chosen for other clips of the source, −1 for each — so a source mixes plates that name and plates that ask."""
    t = " ".join((title or "").split())
    words = [_norm_word(w) for w in t.split()]
    words = [w for w in words if w]
    content = [w for w in words if len(w) >= 5 and not w.isdigit()]
    s = 0.0
    if core_text:
        core = {_norm_word(w)[:5] for w in core_text.split() if len(_norm_word(w)) >= 5}
        s += min(3, sum(1 for w in content if w[:5] in core))
    if len(content) < 2:
        s -= 2.0
    you = any(w in _YOU for w in words)
    if t.rstrip().endswith("?") and (not words or words[0] not in _WH or you):
        s -= 1.5
    if you:
        s -= 0.5
    if words and words[0] in _WEAK_START:
        s -= 2.0
    s += 1.0 if 2 <= len(words) <= 6 else 0.0
    s -= 2.0 if len(t) > 40 else 0.0
    s -= 1.0 * sum(1 for f in used_forms if f == title_form(t))     # M77 (owner: «свобода — где-то текст, где-то вопрос»)
    return round(s, 2)


PLATE_SYSTEM = (
    "A short vertical video (a reel) cut from a Russian talk opens with a hook line; right after it, when the clip "
    "proper starts, a plate in big letters tells the viewer what the clip is about. Write THREE different plates: "
    "the subject as a short phrase (a colon is fine: «Тревога: откуда она берётся»), the question the clip answers "
    "starting with Как/Почему/Что/Зачем («Почему мы боимся отказа»), the clip's main point in a few words. Rules: "
    "name the clip's own key words from its opening or conclusion (no new facts, names or numbers); about the "
    "subject, not about the speaker (no «я», «мой») and not a question to the viewer («вы…?»); no lecture plan "
    "(«сначала… потом…»); 2–6 Russian words, at most 40 characters; no quotes, emoji or hashtags. Answer only with "
    "JSON: {\"titles\": [\"<plate>\", \"<plate>\", \"<plate>\"]}."
)


def headline(pr: "Proposal", provider, clip_text: str, *, core_text: str = "",
             used_forms: list | None = None, log: Callable[[str], None] = print, mode: str = "hook") -> bool:
    """M70/M71: the model proposes three headlines; the code drops those that break title_problem and
    keeps the best by title_score — the current plate (the opener's summary) competes too, so a weaker
    proposal never replaces it (invariant 1: the model proposes, the code picks). Returns True when the
    title changed. M74 mode «context»: the plate says what the clip is about (PLATE_SYSTEM, plate_score) —
    it comes after the hook, which already does the pulling."""
    import json as _json
    import re as _re
    ctx = mode == "context"
    system, score = (PLATE_SYSTEM, plate_score) if ctx else (TITLE_SYSTEM, title_score)
    msg = f"Clip text:\n{clip_text[:1800]}\n\nOpening and conclusion:\n{core_text[:600]}\n\nCurrent plate: «{pr.title}»."
    try:
        raw = provider.complete([{"role": "system", "content": system}, {"role": "user", "content": msg}],
                                temperature=0.0)
    except Exception as exc:  # noqa: BLE001 — no model: the summary stays
        log(f"  заголовок: модель не ответила ({type(exc).__name__})")
        return False
    m = _re.search(r"\{.*\}", raw or "", _re.S)
    try:
        obj = _json.loads(m.group(0)) if m else {}
    except ValueError:
        obj = {}
    props = obj.get("titles") or ([obj["title"]] if obj.get("title") else [])
    cands: list[tuple[float, str]] = []
    dropped: list[str] = []
    for t in props:
        t = " ".join(str(t or "").split()).strip(" «»\"'")
        if not t:
            continue
        why = title_problem(t, clip_text, core_text)
        if why:
            dropped.append(f"«{t}» — {why}")
        else:
            cands.append((score(t, core_text, used_forms or ()), t))
    base = score(pr.title, core_text, used_forms or ()) if pr.title else -99.0
    best = max(cands, key=lambda c: c[0]) if cands else None
    chosen = best[1] if best and best[0] > base else pr.title
    if used_forms is not None and chosen:
        used_forms.append(title_form(chosen))
    if best and best[0] > base:
        pr.notes.append(f"{'плашка-контекст' if ctx else 'заголовок-крючок'}: «{best[1]}» (балл {best[0]:g}; было «{pr.title}», {base:g})"
                        + (f"; отброшены: {'; '.join(dropped)}" if dropped else ""))
        pr.title = best[1]
        return True
    pr.notes.append((f"плашка осталась «{pr.title}» (балл {base:g})" if ctx else
                     f"заголовок остался «{pr.title}» (балл {base:g})")
                    + (f"; варианты слабее: {', '.join(f'«{t}» {sc:g}' for sc, t in cands)}" if cands else "")
                    + (f"; отброшены: {'; '.join(dropped)}" if dropped else ""))
    return False


def seam_pairs(pr: "Proposal", by_id: dict, sentences) -> list[tuple[str, str]]:
    """(last sentence before, first sentence after) of every seam of the clip in play order — two
    thoughts that are not neighbours in the source (neighbours are played as one piece, M58)."""
    out = []
    for a, b in zip(pr.units, pr.units[1:]):
        if b == a + 1 or a not in by_id or b not in by_id:
            continue
        ra = list(_sent_rows(sentences, pr.unit_refs.get(a) or by_id[a]["refs"]))
        rb = list(_sent_rows(sentences, pr.unit_refs.get(b) or by_id[b]["refs"]))
        if ra and rb:
            out.append((ra[-1][4] or ra[-1][0], rb[0][4] or rb[0][0]))
    return out


SEAM_SYSTEM = (
    "A short video is cut from a Russian talk: pieces from different places are joined. For every seam you get "
    "the last sentence before it (A) and the first sentence after it (B). Decide whether a listener hears B as a "
    "natural continuation of A: no pronoun or «это/поэтому/так» pointing to something that was cut, no abrupt "
    "jump to another subject. Answer only with JSON: {\"seams\": [{\"n\": <number>, \"ok\": true|false, "
    "\"why\": \"<at most 10 Russian words>\"}]} with an entry for EVERY seam."
)


def check_seams(pr: "Proposal", pairs: Sequence[tuple[str, str]], provider, *,
                log: Callable[[str], None] = print) -> int | None:
    """M70: the model judges every seam (invariant 11: each seam must get an answer — one retry, then
    the clip stays unjudged, never «fine»). Sets pr.bad_seams; the code only moves clips with a jarring
    seam behind the clean ones (invariant 1). Returns the count, None = no full answer."""
    import json as _json
    import re as _re
    if not pairs:
        pr.bad_seams = 0
        return 0
    rows = "\n".join(f"{i}. A: «{a}»\n   B: «{b}»" for i, (a, b) in enumerate(pairs, 1))
    for _ in range(2):
        try:
            raw = provider.complete([{"role": "system", "content": SEAM_SYSTEM},
                                     {"role": "user", "content": f"Seams:\n{rows}"}], temperature=0.0)
        except Exception as exc:  # noqa: BLE001
            log(f"  стыки: модель не ответила ({type(exc).__name__})")
            return None
        m = _re.search(r"\{.*\}", raw or "", _re.S)
        try:
            items = (_json.loads(m.group(0)) if m else {}).get("seams") or []
        except ValueError:
            continue
        got = {}
        for it in items:
            try:
                n = int(it.get("n"))
            except (TypeError, ValueError, AttributeError):
                continue
            if 1 <= n <= len(pairs) and isinstance(it.get("ok"), bool):
                got[n] = (it["ok"], str(it.get("why") or "").strip()[:80])
        if len(got) == len(pairs):
            bad = [(n, w) for n, (ok, w) in sorted(got.items()) if not ok]
            pr.bad_seams = len(bad)
            for n, w in bad:
                a, b = pairs[n - 1]
                pr.notes.append(f"стык {n} рвётся (модель): «…{a[-50:]}» → «{b[:50]}…»" + (f" — {w}" if w else ""))
            return len(bad)
    log("  стыки: ответ модели неполный — сборка не оценена")
    return None


def short_variant(pr: "Proposal", by_id: dict, p: AutoParams, sentences, *, short_sec: float = 25.0,
                  short_min_sec: float = 15.0, label: int = 0) -> "Proposal | None":
    """M70: a shorter cut of an accepted clip — the weakest middle thoughts dropped down to short_sec
    (opener, payoff and what they lean on stay, as in _prune). None when it cannot get within
    short_sec + 5 s or drops nothing."""
    from dataclasses import replace as _replace
    clip = [({**by_id[i], "refs": pr.unit_refs[i]} if i in pr.unit_refs else by_id[i]) for i in pr.units if i in by_id]
    if len(clip) != len(pr.units):
        return None
    short, dropped = _prune(clip, by_id, _replace(p, target_sec=short_sec, prune_slack=0.0, min_sec=short_min_sec))
    secs = sum(_dur(u) for u in short)
    if not dropped or secs > short_sec + 5.0 or secs < short_min_sec:
        return None
    cands = _hook_cands(short, sentences, p) if sentences else []
    refs = [r for r, _, _ in cands]
    hook = pr.hook if pr.hook in refs else (refs[0] if refs else None)
    return Proposal(units=[u["id"] for u in short], pieces=" ".join(u["refs"] for u in short), hook=hook,
                    title=pr.title, caption=pr.caption, score=pr.score, seconds=round(secs, 1),
                    notes=[f"короткая версия M{label}: убраны " + ", ".join(f"#{i}" for i in dropped)],
                    hooks=[hook] + [r for r in refs if r != hook] if hook else refs,
                    hook_texts={r: (t, sc) for r, sc, t in cands}, speed=_speed(short, p),
                    opener=pr.opener, variant_of=label, hook_keep=pr.hook_keep, close=list(pr.close),
                    unit_refs={i: r for i, r in pr.unit_refs.items() if i in {u["id"] for u in short}})
