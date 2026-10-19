"""M62: whisper.cpp on gamebox as a transcription backend, Groq prompt leaks, arl tx-compare."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from autoreels.cloud.transcribe import WhisperCppBackend, parse_whispercpp_json, transcribe
from autoreels.cloud.txcheck import TxCheckParams, check, compare_words, prompt_patterns
from autoreels.core.config import WhisperCppParams
from autoreels.core.models import Transcript, Word

SAMPLE = {"result": {"language": "ru"}, "transcription": [
    {"offsets": {"from": 0, "to": 400}, "text": " Привет"},
    {"offsets": {"from": 400, "to": 450}, "text": ","},
    {"offsets": {"from": 500, "to": 900}, "text": " мир"},
    {"offsets": {"from": 900, "to": 950}, "text": "."},
    {"offsets": {"from": 1000, "to": 2000}, "text": " [музыка]"},
    {"offsets": {"from": 2000, "to": 2500}, "text": " Дальше."},
]}


def test_parse_whispercpp_words():
    tr = parse_whispercpp_json(SAMPLE)
    assert [(w.word, w.t0, w.t1) for w in tr.words] == [("Привет,", 0.0, 0.45), ("мир.", 0.5, 0.95),
                                                       ("Дальше.", 2.0, 2.5)]
    assert tr.language == "ru"


def test_commands_over_ssh_and_locally():
    be = WhisperCppBackend(WhisperCppParams())
    steps = be.commands(Path("/c/abc.mp3"), Path("/t/abc.wav"), Path("/t/abc.json"))
    assert [s[0] for s in steps] == ["ffmpeg", "ssh", "scp", "ssh", "scp", "ssh"]
    run = steps[3][2]
    assert run.startswith("source ~/llama.env") and "-ml 1 -sow -oj -mc 0 --vad -vm $W/ggml-silero" in run
    assert steps[4] == ["scp", "-q", "gamebox:~/autoreels_tx/abc.json", "/t/abc.json"]
    loc = WhisperCppBackend(WhisperCppParams(host="", env="", vad_model="")).commands(
        Path("/c/abc.mp3"), Path("/t/abc.wav"), Path("/t/abc.json"))
    assert [s[0] for s in loc] == ["ffmpeg", "bash"] and "--vad" not in loc[1][2] and "-of /t/abc" in loc[1][2]
    assert be.describe() == {"provider": "whispercpp", "model": "ggml-large-v3-turbo.bin+vad+mc0", "prompt_hash": ""}


def _fake_run(seen):
    def run(argv):
        seen.append(argv)
        if argv[0] == "scp" and argv[-1].endswith(".json"):
            Path(argv[-1]).write_text(json.dumps(SAMPLE), encoding="utf-8")
    return run


def test_backend_transcribes_without_chunking(tmp_path):
    seen = []
    be = WhisperCppBackend(WhisperCppParams(), run=_fake_run(seen))
    audio = tmp_path / ("a" * 64 + ".mp3")
    audio.write_bytes(b"AUDIO")
    chunking = SimpleNamespace(enabled=True)                    # would probe and split for Groq
    tr = transcribe(audio, tmp_path / "cache", backend=be, chunking_cfg=chunking)
    assert [w.word for w in tr.words] == ["Привет,", "мир.", "Дальше."]
    assert tr.provider == "whispercpp" and tr.prompt_hash == ""
    assert sum(1 for a in seen if a[0] == "ssh" and "whisper-cli" in a[2]) == 1
    assert list((tmp_path / "cache").glob("*.transcript.json"))


def test_prompt_leak_pieces_are_known_inventions():
    prompt = ("Тема сегодняшней беседы — психология принятия решений. Специалисты выделяют несколько "
              "ключевых факторов. Каждый из них влияет на результат по-своему.")
    pats = prompt_patterns(prompt)
    assert "каждый из них влияет на" in pats and "них влияет на результат посвоему" in pats
    words = [Word(word=w, t0=100 + i * 0.4, t1=100 + i * 0.4 + 0.3)
             for i, w in enumerate("ну и вот них влияет на результат по-своему, понимаете".split())]
    rep = check(words, None, TxCheckParams(known=tuple(pats)))
    assert len(rep["known"]) == 1 and "результат" in rep["known"][0]["text"]


def test_compare_words():
    mk = lambda s, t0=0.0: [Word(word=w, t0=t0 + i, t1=t0 + i + 0.5) for i, w in enumerate(s.split())]
    ref = mk("каждый из них влияет на результат. Дальше говорим")
    other = mk("человеческую систему с разных уровней. Дальше говорим")
    c = compare_words(ref, other)
    assert c["ref_words"] == 8 and c["other_words"] == 7 and c["matched"] == 2
    assert c["longest"][0]["ref"].startswith("каждый") and c["longest"][0]["other"].startswith("человеческую")
    assert c["ref_sent_ends"] == 12.5


def test_cmd_tx_compare_keeps_the_groq_transcript(tmp_path, capsys):
    from autoreels import __main__ as cli
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    import shutil
    from tests.test_montage import REPO_ROOT
    mpath = _source(tmp_path)
    shutil.copy(REPO_ROOT / "config" / "transcribe.yaml", tmp_path / "config" / "transcribe.yaml")
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    groq = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")

    class Fake:
        def transcribe(self, audio, *, language=None):
            ws = list(groq.words)
            return Transcript(language="ru", words=ws[:100] + ws[120:])          # 20 words missing
        def describe(self):
            return {"provider": "whispercpp", "model": "fake", "prompt_hash": ""}
    before = sorted(p.name for p in (tmp_path / "cache").iterdir())
    assert cli.cmd_tx_compare([str(mpath)], root=tmp_path, cache_dir=str(tmp_path / "cache"), backend=Fake()) == 0
    out = capsys.readouterr().out
    assert f"== {mpath.stem} (локально:" in out and "совпало" in out and "выдумки на речи" in out
    rep = json.loads((tmp_path / "transcripts" / f"{mpath.stem}.txcompare.json").read_text(encoding="utf-8"))
    assert rep["compare"]["only_ref"] == 20 and rep["compare"]["only_other"] == 0
    assert (tmp_path / "transcripts" / f"{mpath.stem}.local.transcript.json").is_file()
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == before           # cache untouched
    assert cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()),
                                          tmp_path / "cache").words == groq.words


def test_prompt_option_goes_to_whisper_and_into_the_key():
    be = WhisperCppBackend(WhisperCppParams(prompt="Привет, мир. Как дела?"))
    run = be.commands(Path("/c/a.mp3"), Path("/t/a.wav"), Path("/t/a.json"))[3][2]
    assert "--prompt 'Привет, мир. Как дела?'" in run
    assert be.describe()["prompt_hash"] and WhisperCppBackend(WhisperCppParams()).describe()["prompt_hash"] == ""


def test_tx_use_switches_the_source_and_back(tmp_path, capsys):
    """M64: one command switches a source between transcripts; what was built from the old one goes to
    the archive and comes back on the way back; owner files are only warned about."""
    from autoreels import __main__ as cli
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    td, rv = tmp_path / "transcripts", tmp_path / "reviews"
    td.mkdir(exist_ok=True)
    m0 = Manifest.model_validate_json(mpath.read_text())
    groq = cli._resolve_cached_transcript(m0, tmp_path / "cache")
    local = Transcript(language="ru", words=list(groq.words)[:50], provider="whispercpp", model="turbo+vad+mc0")
    (td / "v.local.transcript.json").write_text(local.model_dump_json(), encoding="utf-8")
    for n in ("v.speechmap.json", "v.align.json", "v.map.json"):
        (td / n).write_text("{}", encoding="utf-8")
    (rv / "v_auto.txt").write_text("draft", encoding="utf-8")
    (rv / "v_spec.txt").write_text("owner", encoding="utf-8")
    assert cli.cmd_tx_use("v", "local", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    out = capsys.readouterr().out
    m1 = Manifest.model_validate_json(mpath.read_text())
    assert m1.transcript_params_key and m1.transcript_params_key != m0.transcript_params_key
    assert len(cli._resolve_cached_transcript(m1, tmp_path / "cache").words) == 50
    assert not (td / "v.align.json").exists() and not (rv / "v_auto.txt").exists()
    assert "v_spec.txt" in out and (rv / "v_spec.txt").exists()
    (td / "v.align.json").write_text('{"new": 1}', encoding="utf-8")       # built on the local transcript
    assert cli.cmd_tx_use("v", "groq", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    out = capsys.readouterr().out
    m2 = Manifest.model_validate_json(mpath.read_text())
    assert cli._resolve_cached_transcript(m2, tmp_path / "cache").words == groq.words
    assert (td / "v.align.json").read_text() == "{}" and (rv / "v_auto.txt").read_text() == "draft"   # restored
    assert "возвращено из архива" in out
    assert cli.cmd_tx_use("v", "groq", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    assert "уже на этой расшифровке" in capsys.readouterr().out
    assert cli.cmd_tx_use("v", "local-x", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 1


def test_a_prompt_is_not_dropped_by_mc_zero():
    """M64b: with -mc 0 whisper.cpp throws the prompt away — the «p1» variant came out word for word the
    same as the plain one. A prompt runs with prompt_context instead."""
    be = WhisperCppBackend(WhisperCppParams(prompt="Итак, начнём. Что это значит?"))
    run = be.commands(Path("/c/a.mp3"), Path("/t/a.wav"), Path("/t/a.json"))[3][2]
    assert "-mc 64" in run and "-mc 0" not in run and be.describe()["model"].endswith("+mc64")
    plain = WhisperCppBackend(WhisperCppParams()).commands(Path("/c/a.mp3"), Path("/t/a.wav"), Path("/t/a.json"))[3][2]
    assert "-mc 0" in plain


def test_groq_sentence_ends_go_onto_the_same_local_words():
    """M64c: local has more words and fewer inventions, Groq more sentence ends — take both."""
    from autoreels.cloud.txcheck import transfer_punctuation
    mk = lambda s, t0=0.0: [Word(word=w, t0=t0 + i, t1=t0 + i + 0.5) for i, w in enumerate(s.split())]
    local = mk("мы говорили о детстве это важно потому что всё оттуда ты знаешь мне иногда напоминает")
    groq = mk("Мы говорили о детстве. Это важно, потому что всё оттуда. Субтитры создавал DimaTorzok")
    out, added = transfer_punctuation(local, groq)
    assert added == 2
    assert [w.word for w in out][:9] == ["мы", "говорили", "о", "детстве.", "Это", "важно", "потому", "что", "всё"]
    assert out[9].word == "оттуда." and out[10].word == "Ты"                 # capital after the new end
    assert [w.t0 for w in out] == [w.t0 for w in local]                       # times untouched
    assert out[-1].word == "напоминает"                                       # the invented stretch matched nothing


def test_cmd_tx_punct_writes_a_variant_ready_for_tx_use(tmp_path, capsys):
    from autoreels import __main__ as cli
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    groq = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    bare = [w.model_copy(update={"word": w.word.rstrip(".").lower()}) for w in groq.words]
    (tmp_path / "transcripts" / "v.local.transcript.json").write_text(
        Transcript(language="ru", words=bare, provider="whispercpp", model="turbo").model_dump_json(), encoding="utf-8")
    assert cli.cmd_tx_punct("v", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    out = capsys.readouterr().out
    t = Transcript.model_validate_json((tmp_path / "transcripts" / "v.local-gp.transcript.json").read_text())
    assert sum(w.word.endswith(".") for w in t.words) == sum(w.word.endswith(".") for w in groq.words)
    assert t.model == "turbo+groqpunct" and "добавлено" in out and "tx-use" in out
    assert cli.cmd_tx_use("v", "local-gp", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0


def test_tx_use_refuses_when_the_map_is_from_another_transcript(tmp_path, capsys):
    """M67: switching on top of mixed-up files would bury the mix-up in the archive."""
    import json
    from autoreels import __main__ as cli
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    groq = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    (tmp_path / "transcripts" / "v.local.transcript.json").write_text(
        Transcript(language="ru", words=groq.words, provider="whispercpp", model="turbo").model_dump_json(), encoding="utf-8")
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps({"transcript_key": "someone-else", "units": []}))
    assert cli.cmd_tx_use("v", "local", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 1
    assert "карта от расшифровки someone-else" in capsys.readouterr().err
    assert (tmp_path / "transcripts" / "v.map.json").is_file()            # nothing moved


def test_compare_words_sentence_end_agreement():
    """M111: on the matched words — how many of Groq's sentence ends the local transcript has too."""
    mk = lambda s: [Word(word=w, t0=i, t1=i + 0.5) for i, w in enumerate(s.split())]
    ref = mk("Мы пришли. Сели пить чай. Потом ушли домой.")
    other = mk("мы пришли сели пить чай. Потом ушли. Домой.")
    sa = compare_words(ref, other)["sent_agree"]
    assert (sa["ref"], sa["other"], sa["both"]) == (3, 3, 2)
    assert sa["recall"] == 66.7 and sa["precision"] == 66.7


def test_whispercpp_overrides_check_names_and_types():
    """M111: `--wc key=value` changes only the named whispercpp fields; an empty value turns VAD off;
    an unknown field or a bad type is an error, not silently ignored."""
    from autoreels.__main__ import _whispercpp_overrides
    base = WhisperCppParams()
    w = _whispercpp_overrides(base, ["model=$W/ggml-large-v3.bin", "vad_model=", "max_context=-1"])
    assert (w.model, w.vad_model, w.max_context) == ("$W/ggml-large-v3.bin", "", -1)
    assert w.threads == base.threads and w.host == base.host
    run = WhisperCppBackend(w).commands(Path("/c/a.mp3"), Path("/t/a.wav"), Path("/t/a.json"))[3][2]
    assert "ggml-large-v3.bin" in run and "--vad" not in run and "-mc -1" in run
    for bad in (["modle=x"], ["threads=many"], ["model"]):
        with pytest.raises(ValueError):
            _whispercpp_overrides(base, bad)


def test_cmd_tx_compare_wc_needs_a_tag(tmp_path, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source, REPO_ROOT
    import shutil
    mpath = _source(tmp_path)
    shutil.copy(REPO_ROOT / "config" / "transcribe.yaml", tmp_path / "config" / "transcribe.yaml")
    assert cli.cmd_tx_compare([str(mpath)], root=tmp_path, cache_dir=str(tmp_path / "cache"),
                              wc=["vad_model="]) == 1
    assert "нужен --tag" in capsys.readouterr().err
    assert not (tmp_path / "transcripts" / f"{mpath.stem}.local.transcript.json").exists()
