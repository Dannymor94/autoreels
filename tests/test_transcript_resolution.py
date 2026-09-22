"""Transcript resolution must match the manifest's params_key, never the pkey-less orphan.

Regression guard for the bug where diagnose-cuts/resnap loaded a stale empty-initial_prompt
orphan (<hash>.transcript.json) instead of the params-keyed transcript the run built the
manifest from — inflating phantom mid-word HARD cuts (read) and corrupting boundaries (resnap
write). See docs/audit-hard-cuts.md.
"""
import json
from pathlib import Path

from autoreels import __main__ as cli
from autoreels.core import state
from autoreels.cloud.transcribe import params_key
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Word

REPO_ROOT = Path(__file__).resolve().parents[1]

# Two DIFFERENT transcriptions of the same audio: the orphan lacks punctuation (as Whisper does
# without initial_prompt), the params-keyed one has it. Resolving the wrong one flips the verdict.
ORPHAN_WORDS = [{"word": "сигнал", "t0": 0.0, "t1": 0.5}, {"word": "в", "t0": 0.6, "t1": 0.8}]
KEYED_WORDS = [{"word": "сигнал", "t0": 0.0, "t1": 0.5}, {"word": "теле.", "t0": 0.6, "t1": 1.0}]

_META = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "ph1"}
KEY = params_key(_META)


def _setup(tmp_path, *, write_orphan, write_keyed, manifest_key, reels, keyed_meta=_META):
    """Lay out cache (audio + chosen transcript variants) and a manifest. Returns (manifests, cache)."""
    manifests = tmp_path / "manifests"; manifests.mkdir()
    cache = tmp_path / "cache"; cache.mkdir()
    sha = "d" * 64
    audio = cache / f"{sha}.mp3"; audio.write_bytes(b"MP3")
    ah = state.audio_hash(audio)
    if write_orphan:
        (cache / f"{ah}.transcript.json").write_text(
            json.dumps({"language": "ru", "words": ORPHAN_WORDS}), encoding="utf-8")
    if write_keyed:
        key = params_key(keyed_meta)
        (cache / f"{ah}.{key}.transcript.json").write_text(
            json.dumps({"language": "ru", "words": KEYED_WORDS, **keyed_meta}), encoding="utf-8")
    m = Manifest(source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
                 duration_preset="shorts",
                 setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                                    scale=[1080, 1920], frame=[1920, 1080]),
                 run_key="rk", transcript_params_key=manifest_key, reels=reels)
    (manifests / "v.json").write_text(m.model_dump_json(), encoding="utf-8")
    return manifests, cache


def _reel_with_r0():
    return Reel(id="r01", start=99.0, end=99.0, r0_start=0.0, r0_end=1.0, score=80,
                hook="h", title="Заголовок", description="о", reason="r", topic="x",
                subtitles=[Word(word="сигнал", t0=0.0, t1=0.5)])


# 1. Both variants present → the params-keyed one wins, never the orphan.
def test_resolves_params_keyed_over_orphan(tmp_path):
    manifests, cache = _setup(tmp_path, write_orphan=True, write_keyed=True,
                              manifest_key=KEY, reels=[_reel_with_r0()])
    m = Manifest.model_validate_json((manifests / "v.json").read_text(encoding="utf-8"))
    tr, expected = cli._resolve_transcript(m, cache, audio_format="mp3")
    assert expected == KEY
    assert tr is not None
    assert [w.word for w in tr.words] == ["сигнал", "теле."]      # keyed variant, not the orphan


# 2. Only the orphan present → diagnose skips (clear message) and resnap refuses to write.
def test_only_orphan_diagnose_skips_and_resnap_refuses(tmp_path, capsys):
    manifests, cache = _setup(tmp_path, write_orphan=True, write_keyed=False,
                              manifest_key=KEY, reels=[_reel_with_r0()])
    before = (manifests / "v.json").read_text(encoding="utf-8")

    rc = cli.cmd_diagnose_cuts(root=REPO_ROOT, manifests_dir=manifests, cache_dir=cache)
    err = capsys.readouterr().err
    assert rc == 0
    assert "нет транскрипта" in err and KEY in err and "пропуск" in err   # skipped, not measured

    cli.cmd_resnap("v.mp4", root=REPO_ROOT, manifests_dir=manifests, cache_dir=cache,
                   push=False, pull_first=False)
    err = capsys.readouterr().err
    assert "ОТКАЗАН" in err
    assert (manifests / "v.json").read_text(encoding="utf-8") == before   # NOT written


# 3. resnap guard: file's stamped identity disagrees with the manifest's key → refuse, no write.
def test_resnap_guard_rejects_params_key_mismatch(tmp_path, capsys):
    # File lives at <ah>.<KEY>.transcript.json (so it resolves by the manifest key) but its
    # internal stamp yields a DIFFERENT key — a mislabelled/legacy cache file.
    mislabel_meta = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "OTHER"}
    other_key = params_key(mislabel_meta)
    assert other_key != KEY
    manifests = tmp_path / "manifests"; manifests.mkdir()
    cache = tmp_path / "cache"; cache.mkdir()
    sha = "d" * 64
    audio = cache / f"{sha}.mp3"; audio.write_bytes(b"MP3")
    ah = state.audio_hash(audio)
    (cache / f"{ah}.{KEY}.transcript.json").write_text(       # filename says KEY
        json.dumps({"language": "ru", "words": KEYED_WORDS, **mislabel_meta}),  # stamp says OTHER
        encoding="utf-8")
    m = Manifest(source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
                 duration_preset="shorts",
                 setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                                    scale=[1080, 1920], frame=[1920, 1080]),
                 run_key="rk", transcript_params_key=KEY, reels=[_reel_with_r0()])
    (manifests / "v.json").write_text(m.model_dump_json(), encoding="utf-8")
    before = (manifests / "v.json").read_text(encoding="utf-8")

    cli.cmd_resnap("v.mp4", root=REPO_ROOT, manifests_dir=manifests, cache_dir=cache,
                   push=False, pull_first=False)
    err = capsys.readouterr().err
    assert "расходится" in err and KEY in err and other_key in err     # names both keys
    assert (manifests / "v.json").read_text(encoding="utf-8") == before   # NOT written


# 4. New manifests actually record the transcript identity so resolution/guard have data to work with.
def test_assemble_manifest_records_transcript_params_key():
    from autoreels.cloud.transcribe import transcript_identity
    from autoreels.core.models import Transcript
    tr = Transcript(language="ru", words=[], **_META)
    m = cli._assemble_manifest("v.mp4", [], sha="a" * 64, setup=SetupProfile(
        setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700), scale=[1080, 1920], frame=[1920, 1080]),
        duration_preset="shorts", transcript_params_key=transcript_identity(tr))
    assert m.transcript_params_key == KEY


# ==================================================================================================
# Part E: resolve by source_sha256 first (stable across audio re-extraction) + backfill path handling
# ==================================================================================================
from autoreels.core.models import Transcript


def test_resolve_transcript_prefers_source_sha256_over_audio_hash(tmp_path):
    # The transcript is stamped with source_sha256 + the manifest's params_key, but its FILENAME is
    # keyed by a stale audio hash and no mp3 exists → the audio-hash chain finds nothing. source_sha256
    # (stable across re-extraction) still links it. Guard preserved: params_key must still match.
    cache = tmp_path / "cache"; cache.mkdir()
    sha = "d" * 64
    (cache / "STALEHASH.someotherkey.transcript.json").write_text(
        json.dumps({"language": "ru", "words": KEYED_WORDS, "source_sha256": sha, **_META}),
        encoding="utf-8")
    m = Manifest(source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
                 duration_preset="shorts",
                 setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                                    scale=[1080, 1920], frame=[1920, 1080]),
                 run_key="rk", transcript_params_key=KEY, reels=[_reel_with_r0()])
    tr, expected = cli._resolve_transcript(m, cache, audio_format="mp3")
    assert expected == KEY
    assert tr is not None and [w.word for w in tr.words] == ["сигнал", "теле."]


def test_resolve_transcript_source_match_still_requires_params_key(tmp_path):
    # source_sha256 matches but the stamp yields a DIFFERENT key → not taken by the source branch
    # (orphan guard). mp3 present so the fallback runs and reports the expected key it looked for.
    cache = tmp_path / "cache"; cache.mkdir()
    sha = "d" * 64
    (cache / f"{sha}.mp3").write_bytes(b"MP3")
    other = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "OTHER"}
    (cache / "x.transcript.json").write_text(
        json.dumps({"language": "ru", "words": KEYED_WORDS, "source_sha256": sha, **other}),
        encoding="utf-8")
    m = Manifest(source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
                 duration_preset="shorts",
                 setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                                    scale=[1080, 1920], frame=[1920, 1080]),
                 run_key="rk", transcript_params_key=KEY, reels=[_reel_with_r0()])
    tr, expected = cli._resolve_transcript(m, cache, audio_format="mp3")
    assert tr is None and expected == KEY        # wrong key + no mp3 → nothing taken


# ---- _resolve_cached_transcript (blocks path) ----

def _manifest_e(sha="s" * 64, pkey=""):
    return Manifest(source="v.mp4", source_sha256=sha, duration_preset="shorts",
                    setup=SetupProfile(setup_id="s", crop=Crop(x=0, y=0, w=10, h=20),
                                       scale=[1080, 1920], frame=[1920, 1080]),
                    run_key="rk", transcript_params_key=pkey)


def _write_tx(cache, name, *, sha256="", provider="groq", model="whisper", words=(("hi", 0.0, 0.5),)):
    t = Transcript(language="ru", source_sha256=sha256, provider=provider, model=model,
                   words=[Word(word=w, t0=a, t1=b) for w, a, b in words])
    (cache / name).write_text(t.model_dump_json(), encoding="utf-8")


def test_cached_resolves_by_source_sha256_when_audio_orphaned(tmp_path):
    cache = tmp_path / "cache"; cache.mkdir()
    _write_tx(cache, "STALEHASH.abc123.transcript.json", sha256="s" * 64)
    got = cli._resolve_cached_transcript(_manifest_e(sha="s" * 64), cache)
    assert got is not None and got.source_sha256 == "s" * 64


def test_cached_prefers_matching_params_key(tmp_path):
    cache = tmp_path / "cache"; cache.mkdir()
    _write_tx(cache, "h1.transcript.json", sha256="s" * 64, provider="groq", model="whisper-a")
    _write_tx(cache, "h2.transcript.json", sha256="s" * 64, provider="groq", model="whisper-b")
    want = cli.transcript_identity(Transcript(language="ru", provider="groq", model="whisper-b"))
    got = cli._resolve_cached_transcript(_manifest_e(sha="s" * 64, pkey=want), cache)
    assert got is not None and got.model == "whisper-b"


def test_cached_falls_back_to_audio_hash_for_legacy(tmp_path, monkeypatch):
    cache = tmp_path / "cache"; cache.mkdir()
    (cache / f"{'s' * 64}.mp3").write_bytes(b"audio")
    monkeypatch.setattr(state, "audio_hash", lambda p: "AH")
    _write_tx(cache, "AH.transcript.json", sha256="", words=(("legacy", 0.0, 0.4),))
    got = cli._resolve_cached_transcript(_manifest_e(sha="s" * 64), cache)
    assert got is not None and got.words[0].word == "legacy"


def test_cached_returns_none_when_nothing_matches(tmp_path):
    cache = tmp_path / "cache"; cache.mkdir()
    _write_tx(cache, "other.transcript.json", sha256="d" * 64)
    assert cli._resolve_cached_transcript(_manifest_e(sha="s" * 64), cache) is None


# ---- E.3: backfill-source-sha accepts a path and a bare name, no data/cache/ doubling ----

def test_backfill_accepts_path_without_doubling(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "data" / "cache"; cache.mkdir(parents=True)
    _write_tx(cache, "x.transcript.json", sha256="a" * 64)       # already stamped → skip branch
    monkeypatch.chdir(tmp_path)
    rc = cli.cmd_backfill_source_sha(["data/cache/x.transcript.json"], cache_dir=cache, root=tmp_path)
    out = capsys.readouterr()
    assert rc == 0 and "not found" not in (out.out + out.err) and "skip" in out.out


def test_backfill_accepts_bare_name(tmp_path, capsys):
    cache = tmp_path / "data" / "cache"; cache.mkdir(parents=True)
    _write_tx(cache, "x.transcript.json", sha256="a" * 64)
    rc = cli.cmd_backfill_source_sha(["x.transcript.json"], cache_dir=cache, root=tmp_path)
    out = capsys.readouterr()
    assert rc == 0 and "not found" not in (out.out + out.err) and "skip" in out.out
