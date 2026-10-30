"""M124: two Groq passes — words without the prompt, sentence ends with it (cloud/transcribe.py GroqDualBackend)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from autoreels.cloud.transcribe import GroqBackend, GroqDualBackend, get_backend, params_key

FIX = json.loads((Path(__file__).parent / "fixtures" / "groq_whisper_word.json").read_text(encoding="utf-8"))


def test_dual_takes_the_words_without_the_prompt_and_the_ends_with_it(tmp_path):
    plain = FIX                                                     # a recorded Groq answer (no prompt, no marks)
    marked = copy.deepcopy(FIX)                                     # the prompted pass: the same words, with ends
    marked["words"][5]["word"] = "вскликнул."
    marked["words"][20]["word"] += "?"
    marked["words"].insert(10, {"word": "Каждый", "start": 3.0, "end": 3.1})     # a prompt leak: matches nothing
    calls = []

    def req(path, lang):
        calls.append(path)
        return plain if len(calls) == 1 else marked
    b = GroqDualBackend(model="whisper-large-v3", initial_prompt="Тема беседы.", request_fn=req)
    tr = b.transcribe(tmp_path / "a.mp3", language="ru")
    assert len(calls) == 2 and len(tr.words) == len(plain["words"]) and b.last_marks == 2
    assert tr.words[5].word == "вскликнул." and tr.words[20].word.endswith("?")
    assert [(w.t0, w.t1) for w in tr.words] == [(float(w["start"]), float(w["end"])) for w in plain["words"]]
    assert "Каждый" not in {w.word for w in tr.words}
    assert tr.words[6].word[0].isupper()                           # the next word after a new end gets a capital
    assert b._initial_prompt == ""                                  # nothing for the chunker's leak filter


def test_dual_is_cached_apart_and_chosen_by_the_config():
    from autoreels.core.config import load_transcribe_config
    d = GroqDualBackend(model="whisper-large-v3", initial_prompt="Тема.")
    g = GroqBackend(model="whisper-large-v3", initial_prompt="Тема.")
    assert d.describe()["provider"] == "groq-dual" and params_key(d.describe()) != params_key(g.describe())
    cfg = load_transcribe_config(Path(__file__).parents[1] / "config" / "transcribe.yaml")
    assert type(get_backend(cfg)).__name__ == ("GroqDualBackend" if cfg.groq.dual else "GroqBackend")
    on = cfg.model_copy(update={"groq": cfg.groq.model_copy(update={"dual": True}), "backend": "groq"})
    assert isinstance(get_backend(on), GroqDualBackend)


def test_tx_compare_groq_dual_variant_takes_the_configured_prompt(tmp_path, monkeypatch, capsys):
    import shutil
    from autoreels import __main__ as cli
    from autoreels.cloud import chunk_transcribe
    from autoreels.cloud import transcribe as tmod
    from autoreels.core.config import load_transcribe_config
    from autoreels.core.models import Manifest, Transcript
    from tests.test_montage import REPO_ROOT, _source
    mpath = _source(tmp_path)
    shutil.copy(REPO_ROOT / "config" / "transcribe.yaml", tmp_path / "config" / "transcribe.yaml")
    (tmp_path / "config" / "render.yaml").write_text((REPO_ROOT / "config" / "render.yaml").read_text(encoding="utf-8"),
                                                     encoding="utf-8")
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    groq = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    monkeypatch.setattr(chunk_transcribe, "should_chunk", lambda *a, **k: False)
    monkeypatch.setattr(chunk_transcribe, "_probe_duration", lambda *a, **k: 60.0)
    made = {}

    class FakeDual:
        _initial_prompt = ""

        def __init__(self, *, model, initial_prompt):
            made["prompt"] = initial_prompt

        def transcribe(self, audio, *, language=None):
            return Transcript(language="ru", words=list(groq.words)[:200])

        def describe(self):
            return {"provider": "groq-dual", "model": "whisper-large-v3", "prompt_hash": "x"}
    monkeypatch.setattr(tmod, "GroqDualBackend", FakeDual)
    assert cli.cmd_tx_compare([str(mpath)], root=tmp_path, cache_dir=str(tmp_path / "cache"), groq_dual=True) == 1
    assert cli.cmd_tx_compare([str(mpath)], root=tmp_path, cache_dir=str(tmp_path / "cache"), groq_dual=True,
                              tag="dual") == 0
    assert made["prompt"] == load_transcribe_config(tmp_path / "config" / "transcribe.yaml").groq.initial_prompt
    assert (tmp_path / "transcripts" / "v.groq-dual.transcript.json").is_file()
