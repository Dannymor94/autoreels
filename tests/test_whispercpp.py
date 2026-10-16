"""M62: whisper.cpp on gamebox as a transcription backend, Groq prompt leaks, arl tx-compare."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
