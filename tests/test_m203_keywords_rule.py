"""M203: k: without a model — the last sentence, then the first, then the middle; no questions; the last content word
(or the word the voice draws out). Measured on the owner's own marks (manifests: 68 clips, 135 words)."""
from __future__ import annotations

import pytest

from autoreels.cloud import autocut as A
from autoreels.cloud.autocut import keywords_rule

ROWS = [("1.1", "Первая фраза про страдание."), ("1.2", "Зачем это всё?"),
        ("1.3", "Средняя мысль о дыхании."), ("1.4", "И вот это главное открытие!")]


def test_last_then_first_then_middle_in_play_order():
    assert keywords_rule(ROWS, n=1) == [("1.4", "открытие")]
    assert keywords_rule(ROWS, n=2) == [("1.1", "страдание"), ("1.4", "открытие")]
    assert keywords_rule(ROWS, n=9) == [("1.1", "страдание"), ("1.3", "дыхании"), ("1.4", "открытие")]  # «?» skipped
    assert keywords_rule(ROWS, n=0) == [] and keywords_rule([], n=3) == []


def test_grounded_words_only_and_one_word_per_lemma():
    rows = [("2.1", "Расслабьте свои ноги, расслабьте руки."), ("2.2", "Это всё так, вот."),
            ("2.3", "Просто расслабьте.")]
    out = keywords_rule(rows, n=3)
    # last sentence first: «расслабьте»; then the first sentence: its last content word «руки»; 2.2 is stop words only
    assert out == [("2.1", "руки"), ("2.3", "расслабьте")]
    rows2 = [("3.1", "Дышите и расслабьте."), ("3.2", "Просто расслабьте.")]
    assert keywords_rule(rows2, n=2) == [("3.1", "дышите"), ("3.2", "расслабьте")]   # the lemma is taken: the word before
    for ref, w in out:                                             # every word is a word of its own sentence
        assert w in {A._kw_norm(x) for x in dict(rows)[ref].split()}


def test_the_voice_wins_only_with_a_word_of_the_sentence():
    assert keywords_rule(ROWS, n=1, voiced=[[], [], [], ["главное"]]) == [("1.4", "главное")]
    assert keywords_rule(ROWS, n=1, voiced=[[], [], [], ["нет-такого"]]) == [("1.4", "открытие")]


def test_without_pymorphy_the_stop_list_still_holds(monkeypatch):
    monkeypatch.setattr(A, "_kw_morph_cache", [None])
    out = keywords_rule([("1.1", "Мы идём туда, где есть свет."), ("1.2", "А они там.")], n=2)
    assert out == [("1.1", "свет")]                                 # «они там» — stop words, nothing left


def _project(tmp_path, source: str):
    from tests.test_m202_replay_accounting import _scenario_project
    cli, Fake, first, second = _scenario_project(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    import re
    text = cfg.read_text(encoding="utf-8")
    assert len(re.findall(r"(?m)^  keywords_source: \w+", text)) == 1
    cfg.write_text(re.sub(r"(?m)^  keywords_source: \w+", f"  keywords_source: {source}", text), encoding="utf-8")
    return cli, Fake


@pytest.mark.parametrize("source,has_k", [("model", False), ("rule", True), ("fallback", True)])
def test_autocut_marks_k_without_a_model_only_when_asked(tmp_path, capsys, source, has_k):
    cli, Fake = _project(tmp_path, source)
    out = tmp_path / "reviews" / "v_k.txt"
    rc = cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, scenario=True,
                         scenario_provider=Fake(), out=str(out))       # hook_llm: none — no model for the rest
    text = out.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.startswith("M")]
    assert rc == 0 and lines
    assert any(" | k:" in ln for ln in lines) is has_k
    assert ("k: по правилу (без модели)" in text) is has_k


def test_code_default_is_the_model_and_the_repo_config_is_the_owners_rule():
    from autoreels import __main__ as cli
    from autoreels.core.config import AutocutConfig
    assert AutocutConfig().keywords_source == "model" and AutocutConfig().keywords_rule_voice is False
    ac = cli.load_r0_config("config/r0.yaml").autocut      # M204: owner 2026-11-02 — the rule, at most 2 words
    assert ac.keywords_source == "rule" and ac.keywords_max == 2 and ac.keywords_rule_voice is False


def test_the_measurement_tool_beats_the_random_floor(capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("kw_rule_check", "tools/kw_rule_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--n", "2"]) == 0
    out = capsys.readouterr().out
    rule = next(ln for ln in out.splitlines() if ln.strip().startswith("rule "))
    rnd = next(ln for ln in out.splitlines() if ln.strip().startswith("random"))
    pct = lambda ln: int(ln.rsplit("—", 1)[1].strip().split()[0])  # noqa: E731
    assert "клипов с k: 56, слов владельца 135" in out and pct(rule) >= 2 * pct(rnd)
