"""M37: the owner's review of rendered clips — sheet (local/review_sheet.py), decisions → draft and
rework by the owner's note (cloud/label.py), CLI review-sheet / review-apply."""
import json
import shutil
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.blocks import parse_compact_answer
from autoreels.cloud.label import (
    ClipLine, Decision, LabelParams, apply_decisions, clip_lines, match_reels, parse_decisions,
    redo_fixes, redo_line,
)
from autoreels.local.review_sheet import Card, build_sheet

from tests.test_label import REPO_ROOT, Scripted, _blocks, _c, _source

P1 = LabelParams(min_sec=1.0, max_sec=99.0, window_blocks=4)


# ── decisions file ───────────────────────────────────────────────────────────────────────────

def test_parse_decisions_reads_header_and_verdicts():
    text = ("# stem: IMG_6848\n# review: reviews/IMG_6848_auto.txt\n# decided: 2026-10-10\n"
            "r01 | line 3 | ok\n"
            "r02 | line 12 | fix | закончить на «работает»\n"
            "R03 | LINE 17 | Drop | скучно\n"
            "# r04 | line 21 | не решено\n")
    head, ds, errors = parse_decisions(text)
    assert errors == []
    assert head == {"stem": "IMG_6848", "review": "reviews/IMG_6848_auto.txt", "decided": "2026-10-10"}
    assert ds == [Decision("r01", 3, "ok"), Decision("r02", 12, "fix", "закончить на «работает»"),
                  Decision("r03", 17, "drop", "скучно")]


@pytest.mark.parametrize("line, needle", [
    ("r01 line 3 ok", "не понял"),
    ("r01 | line 3 | maybe", "не понял"),
    ("r01 | line 3 | fix", "без замечания"),
    ("r01 | line 3 | fix |   ", "без замечания"),
])
def test_parse_decisions_reports_bad_lines(line, needle):
    _, ds, errors = parse_decisions(line + "\n")
    assert ds == [] and len(errors) == 1 and needle in errors[0]


def test_parse_decisions_refuses_two_verdicts_for_one_line():
    _, ds, errors = parse_decisions("r01 | line 3 | ok\nr02 | line 3 | drop\n")
    assert len(ds) == 1 and "уже решена" in errors[0]


# ── decisions → draft ────────────────────────────────────────────────────────────────────────

DRAFT = ("# fingerprint: abc\n"
         "2 80 | s:1 | e:3 | t: Т | d: П\n"
         "#   5 s: б2с1 …\n"
         "4 80+ | s:1 | e:6 | t: Т2 | d: П2\n"
         "6 70 | t: Т3\n")


def test_apply_decisions_marks_drops_and_notes_and_is_idempotent():
    ds = [Decision("r01", 2, "ok"), Decision("r02", 4, "fix", "короче"), Decision("r03", 6, "drop", "скучно")]
    new, msgs = apply_decisions(DRAFT, ds, date="2026-10-10")
    lines = new.splitlines()
    assert lines[1] == "# ✓ владелец (r01 2026-10-10)" and lines[2].startswith("2 80 |")
    i = lines.index("# ✎ владелец (r02 2026-10-10): короче")
    assert lines[i + 1].startswith("4 80+ |")
    assert lines[-1] == "#- 6 70 | t: Т3  ← убрано владельцем (r03 2026-10-10): скучно"
    _, entries, errors, _ = parse_compact_answer(new)
    assert errors == [] and [e.seq for e in entries] == [2, 4]       # the dropped line is gone
    again, msgs2 = apply_decisions(new, ds, date="2026-10-10")
    assert again == new
    assert any("строки 6 в черновике нет" in m for m in msgs2)


def test_apply_decisions_reports_a_line_that_is_not_in_the_draft():
    new, msgs = apply_decisions(DRAFT, [Decision("r09", 99, "drop")])
    assert new == DRAFT and "строки 99 в черновике нет" in msgs[0]


# ── clip ↔ review line ───────────────────────────────────────────────────────────────────────

def test_clip_lines_follow_apply_groups_and_carry_preview_and_marks():
    w, wb = _blocks(6)
    text = ("# ✓ владелец (r01 2026-10-01)\n2 80 | t: Т\n#   5 s: превью\n"
            "4 80+ | t: Т2\n6 | t: без оценки\n")
    ls = clip_lines(text, wb)
    assert [(l.seq, l.blocks) for l in ls] == [(2, (2,)), (4, (4, 5))]
    assert ls[0].preview == "5 s: превью" and ls[0].marks == ("# ✓ владелец (r01 2026-10-01)",)
    assert ls[1].t0 == wb[3].block.start and ls[1].t1 == wb[4].block.end
    # a '-' line joins the block before it: the anchor is the scored line of the group
    ls2 = clip_lines("4 -80 | t: Т\n", wb)
    assert [(l.seq, l.blocks) for l in ls2] == [(4, (3, 4))]


def test_match_reels_by_where_the_clip_plays():
    lines = [ClipLine(2, "2 80", (2,), 10.0, 20.0), ClipLine(4, "4 80+", (4, 5), 30.0, 50.0)]
    m = match_reels([("r01", [(11.0, 15.0), (16.0, 19.5)]),
                     ("r02", [(31.0, 48.0)]),
                     ("r03", [(60.0, 70.0)]),          # nowhere in the draft
                     ("r04", [(32.0, 40.0)])],         # line 4 is already taken by r02
                    lines)
    assert m["r01"].seq == 2 and m["r02"].seq == 4 and m["r03"] is None and m["r04"] is None
    # mostly outside the line's span → not that line
    assert match_reels([("r01", [(18.0, 30.0)])], lines)["r01"] is None


# ── rework by the owner's note ───────────────────────────────────────────────────────────────

def _noted(note="только первая фраза"):
    return ("# fingerprint: abc\n"
            f"# ✎ владелец (r01 2026-10-10): {note}\n"
            "2 80 | s:1 | e:3 | t: Т | d: П\n"
            "#   5 s: старое превью\n"
            "5 80 | t: Т5 | d: П5\n")


def test_redo_replaces_the_line_keeps_the_old_one_and_is_idempotent():
    w, wb = _blocks(6)
    prov = Scripted([{"clips": [_c([2], "2.1", "2.2")]}])
    new, done, failed = redo_fixes(_noted(), wb, w, prov, system="S", p=P1, log=lambda m: None)
    assert (done, failed) == (1, 0)
    ask = prov.calls[0][-1]["content"]
    assert "Owner's note: только первая фраза" in ask and '"start": "2.1"' in ask and "BLOCK 2" in ask
    lines = new.splitlines()
    i = lines.index("# ✔ переделано по замечанию владельца (r01 2026-10-10): только первая фраза")
    assert lines[i + 1] == "2 80 | s:1 | e:2 | t: Т | d: П"
    assert lines[i + 2].startswith("#   ") and "старое превью" not in new
    assert lines[i + 3] == "#~ было: 2 80 | s:1 | e:3 | t: Т | d: П"
    assert lines[-1] == "5 80 | t: Т5 | d: П5"
    again, d2, f2 = redo_fixes(new, wb, w, Scripted([]), system="S", p=P1, log=lambda m: None)
    assert again == new and (d2, f2) == (0, 0)
    # the same decision applied again does not bring the note back
    same, _ = apply_decisions(new, [Decision("r01", 2, "fix", "только первая фраза")], date="2026-10-10")
    assert same == new


def test_redo_that_fails_the_checks_keeps_the_note_and_says_why_then_a_retry_succeeds():
    w, wb = _blocks(6)
    over = {"clips": [_c([3, 4], "3.1", "4.3")]}         # block 4 is free, fine…
    taken = {"clips": [_c([4, 5], "4.1", "5.3")]}        # …but 5 belongs to another line
    text = _noted().replace("2 80 | s:1", "3 80 | s:1").replace("#   5 s: старое превью\n", "")
    new, done, failed = redo_fixes(text, wb, w, Scripted([taken, taken]), system="S", p=P1,
                                   log=lambda m: None)
    assert (done, failed) == (0, 1)
    assert "# ✎ владелец (r01 2026-10-10)" in new and "3 80 | s:1 | e:3 | t: Т | d: П" in new
    fail = [l for l in new.splitlines() if l.startswith("#! правка r01 2026-10-10:")]
    assert len(fail) == 1 and "only blocks [2, 3, 4]" in fail[0]   # block 5 is not even offered
    # later (providers back): the failure line is replaced by the rework, not piled up
    new2, done2, failed2 = redo_fixes(new, wb, w, Scripted([over]), system="S", p=P1, log=lambda m: None)
    assert (done2, failed2) == (1, 0)
    assert "#! правка" not in new2 and "3 80+ | s:1 | e:6 | t: Т | d: П" in new2


def test_redo_line_reports_unanswered_provider():
    w, wb = _blocks(6)
    ch, probs = redo_line("2 80 | t: Т | d: П", "короче", wb, w, Scripted([RuntimeError("429")]),
                          system="S", p=P1)
    assert ch is None and "429" in probs[0]


# ── sheet ────────────────────────────────────────────────────────────────────────────────────

def test_sheet_has_a_card_per_clip_and_escapes_text():
    cards = [Card("r01", "r01.mp4", 41.6, title="<b>Заголовок</b>", caption="a & b", text="слова",
                  warnings=["dangling start"], seq=3, line="3 85 | t: <x>", preview="40 s: …"),
             Card("r02", None, 30.0, seq=None)]
    html = build_sheet("IMG</script>", cards, review_ref="reviews/x_auto.txt", manifest_ref="manifests/x.json",
                       key="k1", notes=["заметка"])
    assert html.count('<section class="card"') == 2
    assert 'data-rid="r01" data-seq="3"' in html and 'src="r01.mp4"' in html
    assert "&lt;b&gt;Заголовок&lt;/b&gt;" in html and "a &amp; b" in html and "3 85 | t: &lt;x&gt;" in html
    assert "<b>Заголовок" not in html and "IMG</script>" not in html
    assert 'data-rid="r02">' in html and "клип не отрендерен" in html
    r02 = html[html.index('data-rid="r02"'):]
    assert 'type="radio"' not in r02.split("</section>")[0]
    assert "Без строки черновика: r02" in html and "заметка" in html
    meta = html[html.index('<script id="meta"'):]
    meta = meta[meta.index(">") + 1:meta.index("</script>")]
    assert json.loads(meta)["stem"] == "IMG</script>"


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────

def _manifest_with_reels(mpath, spans):
    from autoreels.core.models import Manifest, Reel
    m = Manifest.model_validate_json(mpath.read_text(encoding="utf-8"))
    reels = [Reel(id=f"r{i:02d}", start=a, end=b, score=80, hook="h", title="", description=f"подпись {i}")
             for i, (a, b) in enumerate(spans, 1)]
    return m.model_copy(update={"reels": reels})


def test_cmd_review_sheet_writes_page_next_to_clips(tmp_path, capsys):
    mpath, cache = _source(tmp_path)
    r0 = cli.load_r0_config(REPO_ROOT / "config" / "r0.yaml")
    from autoreels.core.models import Manifest
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), cache)
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    b1 = kept[0]
    shown = _manifest_with_reels(mpath, [(b1.start + 0.5, b1.end - 0.5), (10_000.0, 10_030.0)])
    clips = tmp_path / "clips.json"
    clips.write_text(shown.model_dump_json(), encoding="utf-8")
    draft = tmp_path / "v_auto.txt"
    draft.write_text("# head\n1 80 | t: Т | d: П\n", encoding="utf-8")
    out = tmp_path / "out"
    (out / "v").mkdir(parents=True)
    (out / "v" / "r01.mp4").write_bytes(b"")
    rc = cli.cmd_review_sheet(str(mpath), root=REPO_ROOT, cache_dir=str(cache), review=str(draft),
                              manifest_file=str(clips), out_dir=str(out))
    assert rc == 0
    html = (out / "v" / "_review.html").read_text(encoding="utf-8")
    assert 'data-rid="r01" data-seq="1"' in html and 'src="r01.mp4"' in html
    assert 'data-rid="r02">' in html                     # no line → no decision controls
    o = capsys.readouterr().out
    assert "клипов 2, с видео 1, со строкой черновика 1" in o and "r02: строка черновика не найдена" in o
    # a missing draft is an error, nothing written
    assert cli.cmd_review_sheet(str(mpath), root=REPO_ROOT, cache_dir=str(cache),
                                review=str(tmp_path / "none.txt"), out_dir=str(tmp_path / "o2")) == 1
    assert not (tmp_path / "o2").exists()


def test_cmd_review_apply_writes_draft_with_backup_and_refuses_bad_files(tmp_path, capsys):
    draft = tmp_path / "v_auto.txt"
    draft.write_text(DRAFT, encoding="utf-8")
    dec = tmp_path / "v_decisions.txt"
    dec.write_text(f"# stem: v\n# review: {draft}\nr01 | line 2 | ok\nr03 | line 6 | drop | скучно\n",
                   encoding="utf-8")
    assert cli.cmd_review_apply(str(dec), root=tmp_path) == 0
    assert (tmp_path / "v_auto.txt.bak").read_text(encoding="utf-8") == DRAFT
    text = draft.read_text(encoding="utf-8")
    assert "# ✓ владелец (r01 " in text and "#- 6 70 | t: Т3  ← убрано владельцем (r03 " in text
    assert "оставить 1, убрать 1, переделать 0" in capsys.readouterr().out
    # applying again changes nothing
    assert cli.cmd_review_apply(str(dec), root=tmp_path) == 0
    assert draft.read_text(encoding="utf-8") == text
    # a broken decisions file is not applied at all
    bad = tmp_path / "bad.txt"
    bad.write_text(f"# review: {draft}\nr02 | line 4 | fix\n", encoding="utf-8")
    assert cli.cmd_review_apply(str(bad), root=tmp_path) == 1
    assert draft.read_text(encoding="utf-8") == text
    nohead = tmp_path / "nohead.txt"
    nohead.write_text("r01 | line 2 | ok\n", encoding="utf-8")
    assert cli.cmd_review_apply(str(nohead), root=tmp_path) == 1


def test_cmd_review_apply_redo_reworks_noted_lines(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for d in ("config", "prompts"):
        shutil.copytree(REPO_ROOT / d, root / d)
    mpath, cache = _source(tmp_path)
    (root / "manifests").mkdir()
    shutil.copy(mpath, root / "manifests" / "v.json")
    r0 = cli.load_r0_config(root / "config" / "r0.yaml")
    from autoreels.core.models import Manifest
    from autoreels.cloud.blocks import _block_fingerprint
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), cache)
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    draft = root / "v_auto.txt"
    draft.write_text(f"# fingerprint: {_block_fingerprint(kept)}\n2 80 | t: Т | d: П\n", encoding="utf-8")
    dec = tmp_path / "d.txt"
    dec.write_text("# stem: v\n# review: v_auto.txt\nr01 | line 2 | fix | убери последнюю фразу\n",
                   encoding="utf-8")

    class Silent:
        name = "silent"

        def __init__(self):
            self.calls = []

        def complete(self, messages, temperature=0.0):
            self.calls.append(messages)
            return '{"clips": []}'

    prov = Silent()
    assert cli.cmd_review_apply(str(dec), root=root, cache_dir=str(cache), redo=True, provider=prov) == 0
    text = draft.read_text(encoding="utf-8")
    assert prov.calls and "Owner's note: убери последнюю фразу" in prov.calls[0][-1]["content"]
    assert "# ✎ владелец (r01 " in text and "#! правка r01 " in text      # no answer → note kept
    # another set of blocks: the rework is refused (decisions are still written)
    draft.write_text("# fingerprint: 0000\n2 80 | t: Т | d: П\n", encoding="utf-8")
    assert cli.cmd_review_apply(str(dec), root=root, cache_dir=str(cache), redo=True, provider=Silent()) == 1
    assert "# ✎ владелец (r01 " in draft.read_text(encoding="utf-8")


def test_cli_wiring():
    parser = cli._build_parser()
    a = parser.parse_args(["review-sheet", "IMG_6848", "--gate", "g1", "--review", "x.txt"])
    assert (a.cmd, a.gate, a.review) == ("review-sheet", "g1", "x.txt")
    b = parser.parse_args(["review-apply", "d.txt", "--redo"])
    assert (b.cmd, b.decisions, b.redo) == ("review-apply", "d.txt", True)
