"""arl label (cloud/label.py): LLM draft of the review lines, checked by deterministic code."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.blocks import _block_fingerprint, parse_compact_answer
from autoreels.cloud.label import (
    LabelParams, build_wblocks, check_clip, label_source, parse_answer, render_window, windows,
)
from autoreels.core.models import Word

REPO_ROOT = Path(__file__).resolve().parents[1]
P = LabelParams(min_sec=2.0, max_sec=60.0)


def _words(spec):
    """[(text, dur)] → Words 0.1 s apart."""
    out, t = [], 0.0
    for text, dur in spec:
        out.append(Word(word=text, t0=round(t, 3), t1=round(t + dur, 3)))
        t += dur + 0.1
    return out


def _sentence(n_words: int, last: str = "конец.", dur: float = 0.5):
    return [(f"слово{i}", dur) for i in range(n_words - 1)] + [(last, dur)]


def _two_blocks(*, junction=False, open_words=()):
    """Block 1: three sentences (the last unfinished when junction=True); block 2: three."""
    s = (_sentence(4, "один.") + _sentence(4, "два.") + _sentence(4, "три" if junction else "три.")
         + _sentence(4, "четыре.") + _sentence(4, "пять.") + _sentence(4, "шесть."))
    w = _words(s)
    b1 = SimpleNamespace(start=w[0].t0, end=w[12].t0)
    b2 = SimpleNamespace(start=w[12].t0, end=w[-1].t1 + 0.01)
    tone = (lambda x: ("open", "") if x.word in open_words else ("final", ""))
    return w, build_wblocks([b1, b2], w, tone)


# ── render ───────────────────────────────────────────────────────────────────────────────────

def test_render_window_ids_and_markers():
    w, wb = _two_blocks(junction=True, open_words=("два.",))
    txt = render_window(wb, P)
    assert "BLOCK 1 ·" in txt and "BLOCK 2 ·" in txt
    assert "1.2 (" in txt and "два. ↗" in txt            # voice up
    assert "1.3 …→ (" in txt                             # unfinished in the text
    assert "2.1 (" in txt


def test_windows_cover_every_run_of_three_blocks():
    wb = [SimpleNamespace(seq=i) for i in range(1, 12)]
    wins = windows(wb, 4, 3)
    seqs = [[x.seq for x in win] for win in wins]
    assert seqs[0] == [1, 2, 3, 4] and seqs[1] == [3, 4, 5, 6]
    for a in range(1, 12):
        for n in (1, 2, 3):
            run = set(range(a, min(a + n, 12)))
            assert any(run <= set(s) for s in seqs), run


# ── checks ───────────────────────────────────────────────────────────────────────────────────

def _clip(**kw):
    c = {"blocks": [1], "start": "1.1", "end": "1.3", "cut": [], "close": ["1.3"],
         "keys": {"1.3": "три"}, "title": "Заголовок", "caption": "Подпись. #психология #тест", "score": 85}
    c.update(kw)
    return c


def test_check_clip_writes_review_line():
    w, wb = _two_blocks()
    ch = check_clip(_clip(cut=["1.2"]), wb, w, P)
    assert ch.problems == []
    assert ch.line == "1 85 | s:1 | e:3 | x:2 | c:3 | k:3=три | t: Заголовок | d: Подпись. #психология #тест"


def test_line_round_trips_through_review_parser():
    w, wb = _two_blocks()
    ch = check_clip(_clip(blocks=[1, 2], end="2.2", cut=["1.3"], close=["2.2"], keys={"2.2": "пять"}), wb, w, P)
    assert ch.problems == []
    _, entries, errors, ignored = parse_compact_answer(ch.line + "\n")
    assert errors == [] and ignored == 0
    e = entries[0]
    assert (e.seq, e.score, e.merge_fwd, e.s, e.e, e.x, e.c) == (1, 85, 1, 1, 5, (3,), (5,))
    assert e.k == ((5, ("пять",)),) and e.title == "Заголовок"


@pytest.mark.parametrize("kw, needle", [
    ({"end": "1.2"}, "voice stays up"),
    ({"start": "1.3"}, "right after a sentence ending with the voice up"),
    ({"cut": ["1.1"]}, "not strictly inside"),
    ({"keys": {"1.3": "нет"}}, "is not a word of 1.3"),
    ({"close": ["2.1"]}, "not a played sentence"),
    ({"title": "x" * 80}, "at most"),
    ({"caption": ""}, "caption is missing"),
])
def test_check_clip_reports_rule_breaks(kw, needle):
    w, wb = _two_blocks(open_words=("два.",))
    ch = check_clip(_clip(**kw), wb, w, P)
    assert any(needle in p for p in ch.problems), ch.problems


@pytest.mark.parametrize("kw, needle", [
    ({"blocks": [1, 3]}, "only blocks"),
    ({"blocks": [2, 1]}, "not consecutive"),
    ({"start": "1.3", "end": "1.1"}, "comes after"),
    ({"end": "2.9"}, "is not a sentence"),
])
def test_check_clip_refuses_unwritable_clips(kw, needle):
    w, wb = _two_blocks()
    ch = check_clip(_clip(**kw), wb, w, P)
    assert ch.line is None and any(needle in p for p in ch.problems), ch.problems


def test_length_is_checked_on_played_speech():
    w, wb = _two_blocks()
    ch = check_clip(_clip(), wb, w, LabelParams(min_sec=30.0, max_sec=60.0))
    assert any("length" in p for p in ch.problems)


def test_junction_sentence_is_one_review_sentence():
    """Block 1 ends unfinished: its tail and block 2's first sentence are review sentence 3."""
    w, wb = _two_blocks(junction=True)
    ch = check_clip(_clip(blocks=[1, 2], end="2.3", cut=["2.1"], close=["2.3"], keys={}), wb, w, P)
    assert ch.problems == []
    assert "| s:1 | e:5 | x:3 |" in ch.line                # cutting either part cuts the whole sentence
    bad = check_clip(_clip(blocks=[1], end="1.3", close=[], keys={}), wb, w, P)
    assert any("unfinished in the text" in p for p in bad.problems)
    mid = check_clip(_clip(blocks=[2], start="2.2", end="2.3", close=[], keys={}), wb, w, P)
    assert mid.problems == [] or all("unfinished" not in p for p in mid.problems)
    first = check_clip(_clip(blocks=[2], start="2.1", end="2.3", close=[], keys={}), wb, w, P)
    assert any("mid-sentence" in p for p in first.problems)


# ── answer parsing ───────────────────────────────────────────────────────────────────────────

def test_parse_answer_tolerates_reasoning_and_fences():
    raw = '<think>hmm {"x": 1}</think>Вот:\n```json\n{"clips": [{"blocks": [1]}]}\n```'
    assert parse_answer(raw) == {"clips": [{"blocks": [1]}]}
    assert parse_answer("no json here") is None
    assert parse_answer('{"segments": []}') is None


# ── the driver ───────────────────────────────────────────────────────────────────────────────

class Scripted:
    name = "scripted"

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def complete(self, messages, temperature=0.0):
        self.calls.append(messages)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)


def test_broken_clip_is_sent_back_once_then_written():
    w, wb = _two_blocks(open_words=("два.",))
    bad = {"clips": [_clip(end="1.2")]}
    good = {"clips": [_clip()]}
    prov = Scripted([bad, good])
    res = label_source(wb, w, prov, system="S", p=P, log=lambda m: None)
    assert len(prov.calls) == 2
    assert "voice stays up" in prov.calls[1][-1]["content"]
    assert res.lines[0].startswith("1 85 | s:1 | e:3") and res.clips_ok == 1


def test_still_broken_after_repair_is_a_flagged_comment():
    w, wb = _two_blocks(open_words=("два.",))
    bad = {"clips": [_clip(end="1.2")]}
    res = label_source(wb, w, Scripted([bad, bad]), system="S", p=P, log=lambda m: None)
    assert res.clips_ok == 0 and res.clips_flagged == 1
    assert res.lines[0].startswith("#! 1 85") and "voice stays up" in res.lines[0]


def test_unanswered_window_is_reported_not_dropped():
    w, wb = _two_blocks()
    res = label_source(wb, w, Scripted([RuntimeError("429"), ]), system="S", p=P, log=lambda m: None)
    assert res.windows_failed == 1 and res.lines == ["# blocks 1–2: no answer (RuntimeError: 429)"]
    res2 = label_source(wb, w, Scripted(["not json", "still not"]), system="S", p=P, log=lambda m: None)
    assert res2.lines == ["# blocks 1–2: no answer (no valid JSON after a retry)"]


def _blocks(n_blocks: int):
    spec = []
    for b in range(n_blocks):
        for k in range(3):
            spec += _sentence(4, f"б{b + 1}с{k + 1}.")
    w = _words(spec)
    blocks = [SimpleNamespace(start=w[12 * b].t0, end=(w[12 * (b + 1)].t0 if b + 1 < n_blocks else w[-1].t1 + 1))
              for b in range(n_blocks)]
    return w, build_wblocks(blocks, w, None)


def _c(blocks, start, end):
    return {"blocks": blocks, "start": start, "end": end, "title": "Т", "caption": "П", "score": 80}


def test_clip_at_window_edge_is_decided_by_the_next_window():
    """Window 1–4 sees a thought starting in block 4 only partly; window 3–6 sees it whole."""
    w, wb = _blocks(6)
    p = LabelParams(min_sec=1.0, max_sec=99.0, window_blocks=4)
    prov = Scripted([{"clips": [_c([4], "4.1", "4.3")]}, {"clips": [_c([4, 5], "4.1", "5.3")]}])
    res = label_source(wb, w, prov, system="S", p=p, log=lambda m: None)
    assert [l for l in res.lines if not l.startswith("#")] == ["4 80+ | s:1 | e:6 | t: Т | d: П"]


def test_deferred_clip_is_kept_when_the_next_window_is_silent():
    w, wb = _blocks(6)
    p = LabelParams(min_sec=1.0, max_sec=99.0, window_blocks=4)
    prov = Scripted([{"clips": [_c([4], "4.1", "4.3")]}, {"clips": []}])
    res = label_source(wb, w, prov, system="S", p=p, log=lambda m: None)
    assert [l for l in res.lines if not l.startswith("#")] == ["4 80 | s:1 | e:3 | t: Т | d: П"]


def test_overlapping_proposals_keep_the_first():
    w, wb = _blocks(6)
    p = LabelParams(min_sec=1.0, max_sec=99.0, window_blocks=4)
    prov = Scripted([{"clips": [_c([2, 3], "2.1", "3.3")]}, {"clips": [_c([3], "3.1", "3.3")]}])
    res = label_source(wb, w, prov, system="S", p=p, log=lambda m: None)
    assert [l for l in res.lines if not l.startswith("#")] == ["2 80+ | s:1 | e:6 | t: Т | d: П"]


# ── real accepted labels ─────────────────────────────────────────────────────────────────────

def _img_groups():
    data = json.loads((REPO_ROOT / "tests" / "fixtures" / "label_img6848_v7.json").read_text(encoding="utf-8"))
    return data["groups"]


@pytest.mark.parametrize("g", _img_groups(), ids=lambda g: f"block{g['seqs'][0]}")
def test_owner_accepted_img6848_lines_round_trip(g):
    """The 8 accepted IMG_6848 clips, written as the labeller's JSON, give back the owner's exact
    review lines (merges, junction sentences, cuts) and pass every check."""
    words = [Word(word=a, t0=b, t1=c) for a, b, c in g["words"]]
    opens = {round(t, 3) for t in g["open_t0"]}
    tone = lambda w: ("open", "") if round(w.t0, 3) in opens else ("final", "")  # noqa: E731
    blocks = [SimpleNamespace(start=a, end=b) for a, b in g["blocks"]]
    wb = build_wblocks(blocks, words, tone, seqs=g["seqs"])
    ch = check_clip(g["clip"], wb, words, LabelParams())
    assert ch.problems == []
    assert ch.line == g["line"]


def test_fewshot_is_real_and_consistent():
    data = json.loads((REPO_ROOT / "prompts" / "label_fewshot.json").read_text(encoding="utf-8"))
    assert "IMG_6848" in data["provenance"]
    msgs = data["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"] * (len(msgs) // 2)
    for u, a in zip(msgs[::2], msgs[1::2]):
        ans = parse_answer(a["content"])
        assert ans and ans["clips"]
        for c in ans["clips"]:
            for sid in [c["start"], c["end"], *c.get("cut", []), *c.get("close", [])]:
                assert f"\n{sid} " in "\n" + u["content"] or f"\n{sid} …→" in "\n" + u["content"]


def test_config_and_cli_wiring():
    cfg = cli.load_r0_config(REPO_ROOT / "config" / "r0.yaml")
    assert cfg.label.window_blocks >= cfg.label.max_clip_blocks
    assert (REPO_ROOT / cfg.label.system).is_file() and (REPO_ROOT / cfg.label.fewshot).is_file()
    parser = cli._build_parser()
    a = parser.parse_args(["label", "IMG_6848", "--force"])
    assert a.cmd == "label" and a.force and a.root is None
    b = parser.parse_args(["blocks", "--apply", "reviews/x_auto.txt", "--labeler", "auto"])
    assert b.labeler == "auto"


# ── the command ──────────────────────────────────────────────────────────────────────────────

def _source(tmp_path):
    from autoreels.core.models import Crop, Manifest, SetupProfile
    import random
    rnd = random.Random(7)
    syll = ["ка", "ро", "ми", "ту", "ле", "на", "во", "си", "да", "жу"]
    words, t = [], 40.0
    for i in range(80):                       # 80 sentences of distinct pseudo-words
        n = rnd.randint(5, 9)
        for k in range(n):
            tok = "".join(rnd.choice(syll) for _ in range(rnd.randint(2, 4)))
            words.append({"word": tok + ("." if k == n - 1 else ""), "t0": round(t, 2), "t1": round(t + 0.4, 2)})
            t += 0.5
        t += 2.0 if i % 8 == 7 else 0.6
    cache = tmp_path / "cache"
    cache.mkdir()
    sha = "d" * 64
    (cache / "x.transcript.json").write_text(json.dumps(
        {"language": "ru", "words": words, "source_sha256": sha, "provider": "groq",
         "model": "whisper-large-v3", "prompt_hash": "p"}), encoding="utf-8")
    (tmp_path / "manifests").mkdir()
    m = Manifest(source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1", source_path="/v.mp4",
                 duration_preset="shorts",
                 setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700), scale=[1080, 1920],
                                    frame=[1920, 1080]),
                 run_key="rk", source_kind="lecture", reels=[])
    mpath = tmp_path / "manifests" / "v.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    return mpath, cache


def test_cmd_label_writes_a_draft_apply_can_read(tmp_path, capsys):
    mpath, cache = _source(tmp_path)
    out = tmp_path / "v_auto.txt"

    class Empty:
        name = "empty"

        def complete(self, messages, temperature=0.0):
            return '{"clips": []}'

    rc = cli.cmd_label(str(mpath), root=REPO_ROOT, cache_dir=str(cache), out=str(out), provider=Empty())
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    from autoreels.core.models import Manifest, Transcript
    r0 = cli.load_r0_config(REPO_ROOT / "config" / "r0.yaml")
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), cache)
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    assert f"# fingerprint: {_block_fingerprint(kept)}" in text
    assert "# format: compact" in text and "--labeler auto" in text
    src, entries, errors, _ = parse_compact_answer(text)
    assert src and src.endswith("v.json") and entries == [] and errors == []
    # an existing draft (maybe edited by the owner) is not overwritten without --force
    assert cli.cmd_label(str(mpath), root=REPO_ROOT, cache_dir=str(cache), out=str(out), provider=Empty()) == 1
    assert cli.cmd_label(str(mpath), root=REPO_ROOT, cache_dir=str(cache), out=str(out), provider=Empty(),
                         force=True) == 0


def test_start_after_an_out_of_order_hallucination_is_mid_sentence():
    """IMG_6848 r10 (M35): Whisper put a hallucinated sentence out of time order before a block;
    the block's sentence 2 starts «себя, и вот…» while the real previous word is «любит».
    --apply refused it (_check_first_subtitle_word); the labeller must flag it first."""
    raw = [("Он", 0.0, 0.3), ("любит", 0.4, 1.0),                         # real speech, cut by a block border
           ("Возможно,", 1.1, 1.12), ("вы", 1.12, 1.14), ("решений.", 1.14, 1.16),  # hallucination
           ("себя,", 1.05, 1.5), ("и", 1.6, 1.7), ("вот", 1.8, 2.0), ("если", 2.1, 2.3), ("слово.", 2.4, 2.8),
           ("Потом", 3.0, 3.3), ("всё", 3.4, 3.6), ("хорошо.", 3.7, 4.0)]
    w = [Word(word=a, t0=b, t1=c) for a, b, c in raw]
    blk = SimpleNamespace(start=1.05, end=5.0)
    wb = build_wblocks([blk], w, None)
    assert [s.text.split()[0] for s in wb[0].sents] == ["Возможно,", "себя,", "Потом"]
    ch = check_clip({"blocks": [1], "start": "1.2", "end": "1.3", "title": "Т", "caption": "П"},
                    wb, w, LabelParams(min_sec=0.5, max_sec=60))
    assert any("starts mid-sentence" in p and "любит себя," in p for p in ch.problems), ch.problems
    ok = check_clip({"blocks": [1], "start": "1.3", "end": "1.3", "title": "Т", "caption": "П"},
                    wb, w, LabelParams(min_sec=0.1, max_sec=60))
    assert not any("mid-sentence" in p for p in ok.problems), ok.problems


# ── an existing draft: --check and --retry ───────────────────────────────────────────────────

def test_check_draft_comments_out_broken_lines_and_keeps_the_rest():
    w, wb = _two_blocks(open_words=("два.",))
    good = "1 85 | s:1 | e:3 | c:3 | k:3=три | t: Т | d: П"
    bad = "2 80 | s:1 | e:3"                      # block 2 sentence 1 follows «три.» — fine; end ok
    voice_up = "1 80 | s:1 | e:2"                 # ends on «два.» ↗
    text = "# head\n" + good + "\n#   note\n" + voice_up + "\n"
    from autoreels.cloud.label import check_draft
    new, flagged = check_draft(text, wb, w, P)
    lines = new.splitlines()
    assert lines[0] == "# head" and lines[1] == good and lines[2] == "#   note"
    assert lines[3].startswith("#! 1 80 | s:1 | e:2  ← ") and "voice stays up" in lines[3]
    assert flagged == [(1, [lines[3].split("← ")[1]])]
    again, flagged2 = check_draft(new, wb, w, P)        # idempotent
    assert again == new and flagged2 == []
    ok, _ = check_draft(bad + "\n", wb, w, P)
    assert ok == bad + "\n"


def test_check_draft_allows_owner_lines_without_title():
    w, wb = _two_blocks()
    from autoreels.cloud.label import check_draft
    new, flagged = check_draft("1 85 | s:1 | e:3\n", wb, w, P)
    assert flagged == [] and new == "1 85 | s:1 | e:3\n"


def test_owner_accepted_spec_passes_the_draft_check():
    """Every accepted IMG_6848 line, read back from review numbering, passes --check."""
    from autoreels.cloud.label import check_draft
    for g in _img_groups():
        words = [Word(word=a, t0=b, t1=c) for a, b, c in g["words"]]
        opens = {round(t, 3) for t in g["open_t0"]}
        tone = lambda w: ("open", "") if round(w.t0, 3) in opens else ("final", "")  # noqa: E731
        wb = build_wblocks([SimpleNamespace(start=a, end=b) for a, b in g["blocks"]], words, tone, seqs=g["seqs"])
        new, flagged = check_draft(g["line"] + "\n", wb, words, LabelParams())
        assert flagged == [], (g["line"], flagged)


def test_retry_fills_unanswered_windows_without_overlapping_the_draft():
    from autoreels.cloud.label import retry_draft, unanswered_windows, used_blocks
    w, wb = _blocks(6)
    p = LabelParams(min_sec=1.0, max_sec=99.0, window_blocks=4)
    text = ("# head\n2 80+ | s:1 | e:6 | t: Т | d: П\n"
            "# blocks 3–6: no answer (ProviderError: бюджет ожидания 600с исчерпан)\n")
    assert unanswered_windows(text) == [(3, 6)] and used_blocks(text) == {2, 3}
    prov = Scripted([{"clips": [_c([3], "3.1", "3.3"), _c([5], "5.1", "5.3")]}])
    new, done, still = retry_draft(text, wb, w, prov, system="S", p=p, log=lambda m: None)
    assert (done, still) == (1, 0)
    body = [l for l in new.splitlines() if l and not l.startswith("#")]
    assert body == ["2 80+ | s:1 | e:6 | t: Т | d: П", "5 80 | s:1 | e:3 | t: Т | d: П"]
    assert "no answer" not in new
    prov2 = Scripted([RuntimeError("429")])
    same, done2, still2 = retry_draft(text, wb, w, prov2, system="S", p=p, log=lambda m: None)
    assert (done2, still2) == (0, 1) and "no answer" in same


def test_cmd_label_check_rewrites_draft_with_backup(tmp_path):
    mpath, cache = _source(tmp_path)
    out = tmp_path / "v_auto.txt"

    class Empty:
        name = "empty"

        def complete(self, messages, temperature=0.0):
            return '{"clips": []}'

    assert cli.cmd_label(str(mpath), root=REPO_ROOT, cache_dir=str(cache), out=str(out), provider=Empty()) == 0
    text = out.read_text(encoding="utf-8") + "1 80 | s:1 | e:99\n"
    out.write_text(text, encoding="utf-8")
    assert cli.cmd_label(str(mpath), root=REPO_ROOT, cache_dir=str(cache), out=str(out), check=True) == 0
    assert "#! 1 80 | s:1 | e:99  ← " in out.read_text(encoding="utf-8")
    assert (tmp_path / "v_auto.txt.bak").read_text(encoding="utf-8") == text
    missing = tmp_path / "none.txt"
    assert cli.cmd_label(str(mpath), root=REPO_ROOT, cache_dir=str(cache), out=str(missing), check=True) == 1


def test_exhausted_providers_stop_the_run_and_mark_the_rest_for_retry():
    w, wb = _blocks(10)
    p = LabelParams(min_sec=1.0, max_sec=99.0, window_blocks=4)
    prov = Scripted([{"clips": []}, RuntimeError("budget"), RuntimeError("budget")])
    res = label_source(wb, w, prov, system="S", p=p, log=lambda m: None)
    assert len(prov.calls) == 3                       # windows 1–4, 3–6, 5–8; 7–10 not asked
    assert res.windows_failed == 3
    assert res.lines[-1] == "# blocks 7–10: no answer (stopped: providers exhausted — arl label --retry later)"
    from autoreels.cloud.label import unanswered_windows
    assert unanswered_windows("\n".join(res.lines)) == [(3, 6), (5, 8), (7, 10)]


def test_block_start_reclaims_the_word_rounding_left_out():
    """IMG_6848 «Когда» (681.295 s, block start 681.3) / 10h59 19 seams (M35): the rounded block start
    left the block's first word in no block — gone from review text, clip text and subtitles."""
    blocks = [SimpleNamespace(start=600.0, end=678.3, duration=78.3),
              SimpleNamespace(start=681.3, end=700.0, duration=18.7)]
    words = [Word(word="что...", t0=678.0, t1=678.3), Word(word="Когда", t0=681.295, t1=681.375),
             Word(word="инсайт", t0=681.375, t1=682.0)]
    assert cli._reclaim_block_first_words(blocks, words) == 1
    assert blocks[1].start == 681.295 and blocks[1].duration == pytest.approx(700.0 - 681.295)
    assert blocks[0].start == 600.0                      # nothing within the step before it
    # a word inside the previous block is never taken
    b2 = [SimpleNamespace(start=0.0, end=10.04, duration=10.04), SimpleNamespace(start=10.05, end=20.0, duration=9.95)]
    assert cli._reclaim_block_first_words(b2, [Word(word="x", t0=10.02, t1=10.04)]) == 0
