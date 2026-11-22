"""M232-A5: opt-in, rescue-only clause hooks for deterministic autocut."""

from dataclasses import asdict, replace
import inspect

from autoreels.cloud.autocut import AutoParams, propose
from autoreels.core.config import AutocutConfig
from tests.test_autocut import U


def _fixture(*, whole_hook=False):
    units = [U(1, 0, 30, "thesis", 5, "1.1-2")]

    def sentences(_refs):
        return [
            ("1.1", 16, 18, False, "Первая часть слишком длинной фразы без точки"),
            ("1.2", 3 if whole_hook else 14, 7, whole_hook,
             "Мы можем построить настоящее доверие с собой"),
        ]

    calls = []

    def clauses(ref):
        calls.append(ref)
        return [(3, 9, 3.2, "Когда мы доверяем себе всё становится иначе")]

    params = AutoParams(clips=1, min_sec=20, target_sec=30, max_sec=60,
                        loop=False, prune=False, hook_teaser=True, hook_teaser_pos=0.5)
    return units, sentences, clauses, calls, params


def test_propose_signature_accepts_clauses_and_new_flag_is_independent():
    """T4: new input and a separate flag; legacy scenarist flag is not activation."""
    assert "clauses" in inspect.signature(propose).parameters
    assert AutoParams().hook_clauses_autocut is False
    assert AutocutConfig().hook_clauses_autocut is False
    assert AutocutConfig.model_validate({"hook_clauses_autocut": True}).hook_clauses_autocut is True


def test_propose_q3_rescue_clause_hook():
    """T1: no whole hook → choose legal clause only with the new opt-in."""
    units, sentences, clauses, calls, params = _fixture()
    (off,) = propose(units, params, sentences)
    assert off.hook is None and off.hooks == []
    (legacy,) = propose(units, replace(params, hook_clauses=True), sentences, clauses=clauses)
    assert asdict(legacy) == asdict(off) and calls == []
    (on,) = propose(units, replace(params, hook_clauses_autocut=True), sentences, clauses=clauses)
    assert on.hook == "1.2@3-9" and on.hooks == ["1.2@3-9"]
    assert on.hook_keep is True and "h:1.2@3-9!" in on.line("1")
    assert on.hook_texts[on.hook][0] == "Когда мы доверяем себе всё становится иначе"
    assert calls == ["1.2"]


def test_propose_q3_keeps_full_sentence_hook_exactly():
    """O2: existing full hooks win without invoking or ranking any clauses."""
    units, sentences, clauses, calls, params = _fixture(whole_hook=True)
    (off,) = propose(units, params, sentences)
    assert off.hook == "1.2"
    (on,) = propose(units, replace(params, hook_clauses_autocut=True), sentences, clauses=clauses)
    assert asdict(on) == asdict(off)
    assert calls == []


def test_propose_q3_clause_never_comes_from_first_half():
    """Even with legacy hook_teaser disabled, the clause cannot bypass teaser_pos."""
    units, sentences, clauses, calls, params = _fixture()

    def only_early(ref):
        calls.append(ref)
        return [(2, 8, 3.2, "Но только ранний фрагмент тут годится")] if ref == "1.1" else []

    (on,) = propose(units, replace(params, hook_teaser=False, hook_clauses_autocut=True),
                    sentences, clauses=only_early)
    assert on.hook is None
    assert calls == ["1.2"]


def test_propose_q3_no_callback_preserves_off_parity():
    units, sentences, clauses, calls, params = _fixture()
    (off,) = propose(units, params, sentences)
    (on,) = propose(units, replace(params, hook_clauses_autocut=True), sentences)
    assert asdict(on) == asdict(off) and calls == []


def test_propose_q3_new_hook_uses_unchanged_apply_parser_and_judge():
    from autoreels.cloud.autocut import judge_hooks
    from autoreels.cloud.montage import parse_montage

    units, sentences, clauses, _calls, params = _fixture()
    (on,) = propose(units, replace(params, hook_clauses_autocut=True), sentences, clauses=clauses)
    parsed, errors = parse_montage(on.line("1") + "\n")
    assert not errors and len(parsed) == 1
    assert parsed[0].hook == (1, 2) and parsed[0].hook_words == (3, 9)
    assert parsed[0].hook_keep
    judge_hooks(on, lambda *_args: (False, "synthetic veto"), "synthetic", log=lambda _: None)
    assert on.hook is None and on.hooks == [] and any("synthetic veto" in note for note in on.notes)


def test_m232_a5_cli_flag_wiring_keeps_scenarist_flag_independent(tmp_path, monkeypatch):
    """Real cmd_autocut parsing and wiring, without owner media or a live provider."""
    from autoreels.cloud import autocut as ac_mod
    from tests.test_m231_trace import _montage_project

    project = _montage_project(tmp_path)
    align = tmp_path / "transcripts" / "v.align.json"
    align.write_text('{"version":1,"words":[],"source_sha256":"' + "f" * 64 + '"}', encoding="utf-8")
    seen = []

    def spy_propose(_units, params, _sentences, **kwargs):
        seen.append((params.hook_clauses, params.hook_clauses_autocut,
                     "clauses" in kwargs, callable(kwargs.get("clauses"))))
        return []

    monkeypatch.setattr(ac_mod, "propose", spy_propose)
    call = lambda over=None: project["cli"].cmd_autocut(  # noqa: E731
        "v", root=tmp_path, cache_dir=tmp_path / "cache", check=False, ac_over=over)
    assert call() == 0
    assert call(["hook_clauses_autocut=true"]) == 0
    # The weak-seed probe is separate and not part of this bounded A5 contract.
    assert seen == [(True, False, False, False)] * 2 + [
        (True, True, True, True), (True, True, False, False)]
