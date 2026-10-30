"""M116: Claude as a provider (--llm haiku | sonnet), the reasoning local model (--llm local-think), the judge cache keyed
by the answering model, the judge log and arl judge-bench, voice hints for k: (M1.9 D), a Groq variant in tx-compare."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from autoreels.cloud import providers as P


class _Resp:
    def __init__(self, code=200, body=None, headers=None, text=""):
        self.status_code, self._body, self.headers = code, body, headers or {}
        self.text = text or (json.dumps(body) if body is not None else "")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._body


def _msg(text="{\"ok\": true}", tin=120, tout=9):
    # the Messages API envelope (docs: content blocks + usage); a recorded one is added as a fixture by the m116 run
    return {"id": "msg_x", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
            "usage": {"input_tokens": tin, "output_tokens": tout}}


def test_claude_provider_sends_system_apart_and_counts_the_price(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    seen = []

    def post(url, json=None, headers=None, timeout=None):
        seen.append((url, json, headers))
        return _Resp(200, _msg())
    llm = P.AnthropicLLM(model="claude-haiku-5-5", prices=(0.10, 0.50), post_fn=post)
    out = llm.complete([{"role": "system", "content": "Будь краток."}, {"role": "user", "content": "Привет"}])
    assert out == "{\"ok\": true}"
    url, payload, headers = seen[0]
    assert url == P.ANTHROPIC_MESSAGES_URL and headers["x-api-key"] == "sk-test" and "anthropic-version" in headers
    assert payload["system"] == "Будь краток." and payload["messages"] == [{"role": "user", "content": "Привет"}]
    assert payload["model"] == "claude-haiku-5-5" and payload["max_tokens"] == 2048 and payload["temperature"] == 0.0
    assert (llm.calls, llm.tokens_in, llm.tokens_out) == (1, 120, 9)
    assert llm.cost() == pytest.approx((120 * 0.10 + 9 * 0.50) / 1e6)
    assert llm.model_id == "anthropic:claude-haiku-5-5" and "запросов 1" in llm.usage_line()
    pool = P.ProviderPool([llm])
    assert pool.model_id == "anthropic:claude-haiku-5-5" and pool.usage_lines() == [llm.usage_line()]


def test_claude_provider_errors_map_to_the_pool_kinds(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mk = lambda r: P.AnthropicLLM(model="m", post_fn=lambda *a, **k: r)  # noqa: E731
    with pytest.raises(P.ProviderThrottled) as e:
        mk(_Resp(429, {"error": {}}, {"retry-after": "7"})).complete([{"role": "user", "content": "x"}])
    assert e.value.retry_after == 7.0
    with pytest.raises(P.ProviderModelNotFound):
        mk(_Resp(404, {"error": {}})).complete([{"role": "user", "content": "x"}])
    with pytest.raises(P.ProviderError, match="ANTHROPIC_API_KEY"):
        mk(_Resp(401, {"error": {}})).complete([{"role": "user", "content": "x"}])
    with pytest.raises(P.ProviderEmptyResponse):
        mk(_Resp(200, _msg(text=""))).complete([{"role": "user", "content": "x"}])
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(P.ProviderError, match="нет ANTHROPIC_API_KEY"):
        mk(_Resp(200, _msg())).complete([{"role": "user", "content": "x"}])


def test_claude_provider_drops_temperature_when_the_model_refuses_it(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    sent = []

    def post(url, json=None, headers=None, timeout=None):
        sent.append(dict(json))
        if "temperature" in json:
            return _Resp(400, {"error": {"message": "temperature is not supported"}},
                         text='{"error":{"message":"temperature is not supported"}}')
        return _Resp(200, _msg())
    llm = P.AnthropicLLM(model="m", post_fn=post)
    assert llm.complete([{"role": "user", "content": "x"}]) == "{\"ok\": true}"
    assert "temperature" in sent[0] and "temperature" not in sent[1]
    llm.complete([{"role": "user", "content": "y"}])
    assert "temperature" not in sent[2]                              # remembered


def test_local_reasoning_model_strips_the_reasoning_and_has_its_own_id():
    posts = []

    def post(url, json=None, timeout=None):
        posts.append(json)
        return _Resp(200, {"choices": [{"message": {"content": "<think>\nдолго думаю {не json}\n</think>\n{\"ok\": false}"}}]})
    think = P.LocalLLM(url="http://x/v1", no_think=False, max_output_tokens=6000, post_fn=post)
    assert think.complete([{"role": "user", "content": "q"}]) == "{\"ok\": false}"
    assert "chat_template_kwargs" not in posts[0] and posts[0]["messages"][-1]["content"] == "q"
    assert posts[0]["max_tokens"] == 6000
    plain = P.LocalLLM(url="http://x/v1", post_fn=post)
    assert think.model_id == "local:local+think" and plain.model_id == "local:local"


def test_make_pool_modes(monkeypatch):
    from autoreels import __main__ as cli
    r0 = cli.load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml")
    pool = cli._make_pool(r0, "sonnet")
    assert pool.model_id == "anthropic:claude-sonnet-5-5"
    member = pool._members[0].provider
    assert member._prices == (2.0, 10.0)
    seen = {}
    monkeypatch.setattr(cli, "build_pool", lambda cfg, local="off": seen.update(cfg=cfg, local=local) or "pool")
    assert cli._make_pool(r0, "local-think") == "pool"
    assert seen["local"] == "only" and seen["cfg"].local_llm.no_think is False
    assert seen["cfg"].local_llm.max_output_tokens == r0.local_llm.think_max_output_tokens
    assert r0.local_llm.no_think is True                             # the loaded config is not changed
    cli._make_pool(r0, "cloud")
    assert seen["local"] == "off" and seen["cfg"] is r0


def test_parse_judge():
    from autoreels.cloud.autocut import parse_judge
    assert parse_judge('{"subject": "страх", "alone": true, "leads": true, "why": ""}') == (True, "страх")
    assert parse_judge('```json\n{"subject": "", "alone": true, "leads": true}\n```')[0] is False
    assert parse_judge('{"subject": "x", "alone": false, "leads": true, "why": "это"}') == (False, "это")
    assert parse_judge('<think>{"subject": "y"}</think>{"ok": true, "why": "ясно"}') == (True, "ясно")
    assert parse_judge("не знаю") is None and parse_judge('{"subject": "x"}') is None


def test_judge_store_is_keyed_by_the_answering_model_and_the_log_gets_every_judgment():
    """M116: a cached answer of one model is never handed to another (the m112/m115 cloud runs reused the answers the
    gamebox model gave in m106/m107); the judge log carries the exact prompt for arl judge-bench."""
    from autoreels.cloud.autocut import make_judge

    class Prov:
        def __init__(self, mid, ans):
            self.model_id, self.ans, self.calls = mid, ans, 0

        def complete(self, messages, temperature=0.0):
            self.calls += 1
            return self.ans
    store, rows = {}, []
    a = Prov("groq:q", '{"subject": "страх", "alone": true, "leads": true}')
    b = Prov("anthropic:h", '{"subject": "страх", "alone": false, "leads": true, "why": "это"}')
    ja = make_judge(a, store=store, jlog=rows.append, log=lambda m: None)
    assert ja("Страх нас защищает.", "Дальше.") == (True, "страх")
    assert ja("Страх нас защищает.", "Дальше.") == (True, "страх") and a.calls == 1
    jb = make_judge(b, store=store, jlog=rows.append, log=lambda m: None)
    assert jb("Страх нас защищает.", "Дальше.") == (False, "это") and b.calls == 1   # not a's cached answer
    assert len(store) == 2
    assert [(r["model"], r["ok"], r["cached"]) for r in rows] == [("groq:q", True, False), ("groq:q", True, True),
                                                                   ("anthropic:h", False, False)]
    assert rows[0]["msg"].startswith("First sentence: «Страх нас защищает.»") and rows[0]["system"]
    jc = make_judge(Prov("groq:q", "{}"), store=store, log=lambda m: None)   # same model, next run: from the store
    assert jc("Страх нас защищает.", "Дальше.") == (True, "страх")


def test_judge_bench_asks_the_logged_requests_again(tmp_path, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    _source(tmp_path)
    log = tmp_path / "j.jsonl"
    rows = [{"stem": "v", "label": "First sentence", "model": "groq:q", "system": "S", "msg": "First sentence: «А.»",
             "ok": True, "why": "а", "cached": False},
            {"stem": "v", "label": "First sentence", "model": "groq:q", "system": "S", "msg": "First sentence: «А.»",
             "ok": True, "why": "а", "cached": True},                                  # the same request: asked once
            {"stem": "v", "label": "Teaser line", "model": "groq:q", "system": "T", "msg": "Teaser line: «Б.»",
             "ok": False, "why": "б", "cached": False}]
    log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    class Prov:
        model_id = "anthropic:h"

        def __init__(self):
            self.seen = []

        def complete(self, messages, temperature=0.0):
            self.seen.append(messages)
            return '{"ok": true, "why": "да"}' if messages[0]["content"] == "S" else "мусор"
    prov = Prov()
    assert cli.cmd_judge_bench(str(log), llm="haiku", root=tmp_path, provider=prov) == 0
    out = capsys.readouterr().out
    res = [json.loads(x) for x in (tmp_path / "j.haiku.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(res) == 2 and len(prov.seen) == 3                     # the unusable answer asked twice
    assert res[0]["ok"] is True and res[0]["ref_ok"] is True and res[0]["model"] == "anthropic:h"
    assert res[1]["ok"] is None and res[1]["ref_ok"] is False
    assert "First sentence: ответов 1/1, «да» 100%, совпало с журналом 1/1" in out
    assert "Teaser line: ответов 0/1" in out
    assert cli.cmd_judge_bench(str(tmp_path / "nope.jsonl"), root=tmp_path, provider=prov) == 1


def test_voice_stressed_words_and_the_hint_in_the_keyword_request():
    """M116 (M1.9 D): a content word drawn out by the voice (duration per letter ≥ ratio × the sentence's median; not
    the last word) is shown to the model; without hints the request is byte for byte the M88 one."""
    from autoreels.cloud.autocut import KEYWORDS_SYSTEM, KEYWORDS_VOICE_NOTE, pick_keywords, voice_stressed
    from autoreels.core.models import Word
    ws = [Word(word=w, t0=float(i), t1=float(i) + 0.3) for i, w in enumerate("Это очень важное решение для жизни.".split())]
    durs = {0: 0.15, 1: 0.25, 2: 0.9, 3: 0.4, 4: 0.1, 5: 0.9}      # «важное» drawn out; «жизни.» is last — not a hint
    dur_of = lambda w: durs.get(int(w.t0))                            # noqa: E731
    assert voice_stressed(ws, dur_of) == ["важное"]
    assert voice_stressed(ws, dur_of, ratio=3.0) == []
    assert voice_stressed(ws[:2], dur_of) == []                       # too few measured words

    class Prov:
        def __init__(self):
            self.msgs = []

        def complete(self, messages, temperature=0.0):
            self.msgs.append(messages)
            return '{"keys": [{"s": 1, "word": "важное"}]}'
    rows = [("3.1", "Это очень важное решение для жизни."), ("3.2", "И всё.")]
    p1 = Prov()
    assert pick_keywords(rows, p1, n=1, voiced=[["важное"], []]) == [("3.1", "важное")]
    assert p1.msgs[0][0]["content"] == KEYWORDS_SYSTEM.format(n=1) + KEYWORDS_VOICE_NOTE
    assert "1. Это очень важное решение для жизни. [voice: важное]\n2. И всё." in p1.msgs[0][1]["content"]
    p2 = Prov()
    pick_keywords(rows, p2, n=1, voiced=[[], []])
    p3 = Prov()
    pick_keywords(rows, p3, n=1)
    assert p2.msgs[0] == p3.msgs[0] and p3.msgs[0][0]["content"] == KEYWORDS_SYSTEM.format(n=1)


def test_tx_compare_groq_variant_needs_a_tag_and_keeps_the_manifest_transcript(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from autoreels.cloud import chunk_transcribe
    from autoreels.core.models import Manifest, Transcript
    from tests.test_montage import REPO_ROOT, _source
    import shutil
    mpath = _source(tmp_path)
    shutil.copy(REPO_ROOT / "config" / "transcribe.yaml", tmp_path / "config" / "transcribe.yaml")
    (tmp_path / "config" / "render.yaml").write_text((REPO_ROOT / "config" / "render.yaml").read_text(encoding="utf-8"),
                                                     encoding="utf-8")
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    groq = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    assert cli.cmd_tx_compare([str(mpath)], root=tmp_path, cache_dir=str(tmp_path / "cache"), groq_prompt="") == 1
    assert "нужен --tag" in capsys.readouterr().err
    monkeypatch.setattr(chunk_transcribe, "should_chunk", lambda *a, **k: False)
    monkeypatch.setattr(chunk_transcribe, "_probe_duration", lambda *a, **k: 60.0)

    class Fake:
        _initial_prompt = ""

        def transcribe(self, audio, *, language=None):
            return Transcript(language="ru", words=list(groq.words)[:200])

        def describe(self):
            return {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": ""}
    before = sorted(p.name for p in (tmp_path / "cache").iterdir())
    assert cli.cmd_tx_compare([str(mpath)], root=tmp_path, cache_dir=str(tmp_path / "cache"), groq_prompt="",
                              tag="noprompt", backend=Fake()) == 0
    out = capsys.readouterr().out
    assert "Groq: initial_prompt пустой" in out and "конец предложения на 100 слов" in out
    assert (tmp_path / "transcripts" / "v.groq-noprompt.transcript.json").is_file()
    assert (tmp_path / "transcripts" / "v.txcompare-groq-noprompt.json").is_file()
    after = sorted(p.name for p in (tmp_path / "cache").iterdir())
    assert after == sorted(before + ["_variants"])                    # the variant went to the side cache only
    assert cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()),
                                          tmp_path / "cache").words == groq.words


def test_claude_provider_reads_a_recorded_answer():
    """M116: a real Messages API answer (tests/fixtures/anthropic_messages_envelope.json — recorded by the m116 run,
    provenance inside) goes through the provider as it came: text, usage, and the judge's parser."""
    from autoreels.cloud.autocut import parse_judge
    d = json.loads((Path(__file__).parent / "fixtures" / "anthropic_messages_envelope.json").read_text(encoding="utf-8"))
    body = d["response"]
    llm = P.AnthropicLLM(model=body.get("model", "claude-haiku-5-5"), prices=(0.10, 0.50),
                         api_key="k", post_fn=lambda *a, **k: _Resp(200, body))
    text = llm.complete([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
    assert d["provenance"] and text.strip() and llm.tokens_in > 0 and llm.tokens_out > 0
    assert parse_judge(text) is not None
