"""M52: the clip as text on the review sheet — the owner turns sentences on/off, picks the hook,
listens to the new version and saves «edit» with new s:/e:/x:/h:; review-apply writes them.

1. edit_line: only s:/e:/x:/h: change; score, merge markers, c:/k:/f:, t:/d: stay byte for byte.
2. decisions: «edit» with fields parses, without fields is an error; apply writes the line and an
   owner mark, twice = once; the edited line counts as the owner's approved example.
3. edit_model: the group's sentences in the review numbering, played = s..e minus x, hook.
4. the sheet: an editable card has the editor, the «Правка» choice and its data in #clips;
   preview files: the span is in the name, the command is audio-only or a 480 px video.
5. CLI: review-apply prints the draft check of an edited line without changing it.
"""
import json
import subprocess
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.label import (
    ClipLine, Decision, apply_decisions, approved_entries, edit_line, edit_model, parse_decisions,
)
from autoreels.local.review_sheet import Card, build_sheet, preview_cmd, preview_name, preview_span

from tests.test_label import _blocks


# ── 1. the line ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, fields, want", [
    ("12 85 | s:2 | e:9 | x:5 | c:4 | k:3=слово | t: Заголовок | d: Подпись", "s:3 e:8 h:6",
     "12 85 | s:3 e:8 h:6 | c:4 | k:3=слово | t: Заголовок | d: Подпись"),
    ("7 80+ | e:6 | h:2! | t: X", "s:1 e:5 x:3 h:2", "7 80+ | s:1 e:5 x:3 h:2! | t: X"),
    ("7 80 | h:2- | t: X", "s:1 e:5 h:4", "7 80 | s:1 e:5 h:4 | t: X"),
    ("4 70", "s:2 e:4", "4 70 | s:2 e:4"),
    ("4 70 | s:1 | f:0 | t: Шаг s:3 и e:4 | d: x:5", "s:2 e:4 x:3", "4 70 | s:2 e:4 x:3 | f:0 | t: Шаг s:3 и e:4 | d: x:5"),
    ("5 75 | x:2-3, 6 | d: только подпись", "s:1 e:7 x:2-3", "5 75 | s:1 e:7 x:2-3 | d: только подпись"),
    ("6 80 s:2 e:5 t: без разделителей", "s:2 e:4", "6 80 | s:2 e:4 | t: без разделителей"),
])
def test_edit_line_replaces_only_the_sentence_fields(raw, fields, want):
    assert edit_line(raw, fields) == want


def test_edited_line_reads_back_as_the_owners_choice():
    from autoreels.cloud.blocks import parse_compact_answer
    new = edit_line("12 85+ | s:2 | e:9 | c:4 | t: Т | d: П", "s:3 e:8 x:5-6 h:7")
    _, (e,), errors, _ = parse_compact_answer(new + "\n")
    assert errors == [] and (e.seq, e.score, e.merge_fwd) == (12, 85, 1)
    assert (e.s, e.e, e.x, e.hook, e.c, e.title, e.description) == (3, 8, (5, 6), 7, (4,), "Т", "П")


# ── 2. decisions ─────────────────────────────────────────────────────────────────────────────

def test_parse_edit_decisions():
    head, ds, errors = parse_decisions("# review: r.txt\nr03 | line 9 | edit | s:2 e:7 x:4,6 h:6 | короче\n"
                                       "r04 | line 11 | edit | s:1 e:3\n")
    assert errors == []
    assert ds == [Decision("r03", 9, "edit", "короче", "s:2 e:7 x:4,6 h:6"), Decision("r04", 11, "edit", "", "s:1 e:3")]


@pytest.mark.parametrize("line", ["r01 | line 3 | edit", "r01 | line 3 | edit | короче",
                                  "r01 | line 3 | edit | e:4 x:2", "r01 | line 3 | edit | s:1 t:Т"])
def test_edit_without_fields_is_an_error(line):
    _, ds, errors = parse_decisions(line + "\n")
    assert ds == [] and "без полей" in errors[0]


DRAFT = ("# fingerprint: abc\n"
         "2 80 | s:1 | e:3 | t: Т | d: П\n"
         "#   5 s: б2с1 …\n"
         "4 80+ | s:1 | e:6 | t: Т2 | d: П2\n")


def test_apply_edit_writes_the_line_and_an_owner_mark_once():
    d = [Decision("r02", 4, "edit", "конец раньше", "s:2 e:5 x:3")]
    new, msgs = apply_decisions(DRAFT, d, date="2026-10-13")
    assert "4 80+ | s:2 e:5 x:3 | t: Т2 | d: П2" in new.splitlines()
    assert "# ✔ переделано владельцем на листе (r02 2026-10-13): s:2 e:5 x:3 — конец раньше" in new
    assert "2 80 | s:1 | e:3 | t: Т | d: П" in new and "правка владельца" in msgs[0]
    again, _ = apply_decisions(new, d, date="2026-10-13")
    assert again == new
    approved = approved_entries(new, owner_file=False)
    assert [e.seq for e in approved] == [4]


# ── 3. the text model ────────────────────────────────────────────────────────────────────────

def test_edit_model_is_the_groups_sentences_with_the_lines_choice():
    w, wb = _blocks(4)              # 3 sentences per block, 4 words each
    ln = ClipLine(2, "2 80+ | s:2 | e:5 | x:3 | h:4 | t: Т", (2, 3), wb[1].block.start, wb[2].block.end)
    m = edit_model(ln, wb, w)
    assert m["seq"] == 2 and m["hook"] == 4
    assert [s["n"] for s in m["sentences"]] == [1, 2, 3, 4, 5, 6]
    assert [s["played"] for s in m["sentences"]] == [False, True, False, True, True, False]
    assert m["sentences"][0]["text"].endswith("б2с1.") and m["sentences"][5]["text"].endswith("б3с3.")
    s1 = m["sentences"][0]
    assert s1["a"] == wb[1].sents[0].words[0].t0 and s1["complete"] and not s1["open"]
    plain = edit_model(ClipLine(1, "1 80", (1,), 0, 0), wb, w)
    assert all(s["played"] for s in plain["sentences"]) and plain["hook"] is None
    assert edit_model(ClipLine(3, "-3 80", (2, 3), 0, 0), wb, w) is None


# ── 4. the sheet ─────────────────────────────────────────────────────────────────────────────

def _model():
    return {"seq": 3, "hook": None, "media": "_preview/r01-9.00-31.50.m4a", "offset": 9.0,
            "sentences": [{"n": 1, "text": "Раз.", "a": 10.0, "b": 12.0, "complete": True, "open": False, "played": True},
                          {"n": 2, "text": "Два", "a": 12.5, "b": 30.5, "complete": False, "open": True, "played": False}]}


def test_editable_card_has_the_editor_and_the_edit_choice():
    cards = [Card("r01", "r01.mp4", 20.0, seq=3, line="3 80", edit=_model()),
             Card("r02", "r02.mp4", 20.0, seq=5, line="5 80")]
    html = build_sheet("v", cards, review_ref="r", manifest_ref="m", key="k")
    r01 = html[html.index('data-rid="r01"'):].split("</section>")[0]
    r02 = html[html.index('data-rid="r02"'):].split("</section>")[0]
    assert 'class="ed"' in r01 and 'value="edit"' in r01 and '<audio class="pv" src="_preview/r01-9.00-31.50.m4a"' in r01
    assert 'class="ed"' not in r02 and 'value="edit"' not in r02 and 'value="fix"' in r02
    data = html[html.index('<script id="clips"'):]
    data = json.loads(data[data.index(">") + 1:data.index("</script>")])
    assert list(data) == ["r01"] and data["r01"]["offset"] == 9.0 and data["r01"]["sentences"][1]["open"]


def test_video_preview_card_and_no_media_note():
    m = _model() | {"media": "_preview/r01-9.00-31.50.mp4"}
    html = build_sheet("v", [Card("r01", None, 20.0, seq=3, line="3 80", edit=m)], review_ref="r", manifest_ref="m", key="k")
    assert '<video class="pv" src="_preview/r01-9.00-31.50.mp4"' in html
    html2 = build_sheet("v", [Card("r01", None, 20.0, seq=3, line="3 80", edit=_model() | {"media": ""})],
                        review_ref="r", manifest_ref="m", key="k")
    assert "нет файла предпросмотра" in html2 and 'data-act="play"' not in html2


def test_preview_span_name_and_command():
    span = preview_span(_model())
    assert span == (9.0, 31.5)
    assert preview_name("r01", span, "audio") == "_preview/r01-9.00-31.50.m4a"
    assert preview_name("r01", span, "video") == "_preview/r01-9.00-31.50.mp4"
    a = preview_cmd("ffmpeg", "/src.mov", span, "/o.m4a", "audio")
    assert a[a.index("-ss") + 1] == "9.000" and a[a.index("-t") + 1] == "22.500" and "-vn" in a and "-c:v" not in a
    v = preview_cmd("ffmpeg", "/src.mov", span, "/o.mp4", "video")
    assert "scale=480:-2" in v and v[v.index("-c:v") + 1] == "libx264" and "-vn" not in v
    vt = preview_cmd("ffmpeg", "/src.mov", span, "/o.mp4", "video", vcodec="h264_videotoolbox")
    assert "-crf" not in vt and "500k" in vt


def test_preview_files_are_cut_from_the_source(tmp_path):
    import shutil
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg")
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=300", "-t", "6", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(src)], check=True)
    for kind in ("audio", "video"):
        out = tmp_path / ("o." + ("mp4" if kind == "video" else "m4a"))
        r = subprocess.run(preview_cmd("ffmpeg", src, (1.0, 4.0), out, kind), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,channels",
                                "-show_entries", "format=duration", "-of", "json", str(out)],
                               capture_output=True, text=True, check=True)
        info = json.loads(probe.stdout)
        types = sorted(s["codec_type"] for s in info["streams"])
        assert types == (["audio", "video"] if kind == "video" else ["audio"])
        assert abs(float(info["format"]["duration"]) - 3.0) < 0.15
        if kind == "video":
            assert next(s for s in info["streams"] if s["codec_type"] == "video")["width"] == 480


# ── 5. CLI ───────────────────────────────────────────────────────────────────────────────────

def test_cmd_review_apply_edit_counts_and_writes(tmp_path, capsys):
    draft = tmp_path / "v_auto.txt"
    draft.write_text(DRAFT, encoding="utf-8")
    dec = tmp_path / "v_decisions.txt"
    dec.write_text(f"# stem: v\n# review: {draft}\nr01 | line 2 | edit | s:2 e:3\n", encoding="utf-8")
    assert cli.cmd_review_apply(str(dec), root=tmp_path) == 0
    assert "2 80 | s:2 e:3 | t: Т | d: П" in draft.read_text(encoding="utf-8")
    assert "правка 1" in capsys.readouterr().out
