"""M202: the models' answers kept per request (record / replay) and the autocut accounting — every candidate of the pool
is shown with the place it went to (m200: «Алгоритм или эмпатия» left as «похожи», a number in the console only)."""
from __future__ import annotations

import json

import pytest

from autoreels.cloud import llmcache
from autoreels.cloud.providers import ProviderError, ProviderPool


class _Model:
    model_id = "fake:m"

    def __init__(self):
        self.asked = 0

    def complete(self, messages, *, temperature=0.0):
        self.asked += 1
        return f"ответ {self.asked}"

    def describe(self):
        return "модели: fake"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(llmcache.ENV, raising=False)
    llmcache.reset()
    yield
    llmcache.reset()


MSG = [{"role": "system", "content": "s"}, {"role": "user", "content": "вопрос"}]


def test_off_is_the_provider_itself(tmp_path):
    m = _Model()
    assert llmcache.wrap(m, mode="off", cache_dir=tmp_path) is m


def test_record_asks_once_and_returns_the_kept_answer(tmp_path):
    m = _Model()
    c = llmcache.wrap(m, mode="record", cache_dir=tmp_path)
    assert c.complete(MSG) == "ответ 1" and c.complete(MSG) == "ответ 1" and m.asked == 1
    assert c.complete(MSG, temperature=0.5) == "ответ 2"            # another request, another key
    assert (c.hits, c.writes, c.misses) == (1, 2, 0) and c.describe() == "модели: fake"
    assert any("из кэша 1, записано 2, промахов 0" in ln for ln in c.usage_lines())


def test_replay_answers_only_from_the_cache_and_counts_misses(tmp_path):
    llmcache.wrap(_Model(), mode="record", cache_dir=tmp_path).complete(MSG)
    m = _Model()
    r = llmcache.wrap(m, mode="replay", cache_dir=tmp_path)
    assert r.complete(MSG) == "ответ 1" and m.asked == 0
    with pytest.raises(ProviderError, match="replay: ответа нет"):
        r.complete([{"role": "user", "content": "другой вопрос"}])
    assert m.asked == 0 and llmcache.totals() == (1, 1, 1)


def test_key_is_the_model_and_the_request(tmp_path):
    k = llmcache.request_key
    assert k("a", MSG, 0.0) == k("a", [dict(x) for x in MSG], 0.0)
    assert len({k("a", MSG, 0.0), k("b", MSG, 0.0), k("a", MSG, 0.1), k("a", MSG[:1], 0.0)}) == 4


def test_a_broken_file_is_no_answer(tmp_path):
    c = llmcache.wrap(_Model(), mode="record", cache_dir=tmp_path)
    c.complete(MSG)
    (f,) = list(tmp_path.rglob("*.json"))
    f.write_text("{oops", encoding="utf-8")
    m = _Model()
    with pytest.raises(ProviderError):
        llmcache.wrap(m, mode="replay", cache_dir=tmp_path).complete(MSG)
    assert llmcache.wrap(m, mode="record", cache_dir=tmp_path).complete(MSG) == "ответ 1"
    assert json.loads(f.read_text(encoding="utf-8"))["answer"] == "ответ 1"


def test_the_environment_overrides_the_config_and_a_typo_is_an_error(monkeypatch):
    assert llmcache.mode_of("off") == "off"
    monkeypatch.setenv(llmcache.ENV, "Replay")
    assert llmcache.mode_of("off") == "replay"
    monkeypatch.setenv(llmcache.ENV, "replya")
    with pytest.raises(ProviderError, match="допустимо"):
        llmcache.mode_of("off")


def test_make_pool_is_wrapped_only_when_the_cache_is_on(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    r0 = cli.load_r0_config("config/r0.yaml")
    assert r0.llm_cache.mode == "record"                                         # M206: the repo config keeps answers
    monkeypatch.setenv(llmcache.ENV, "off")
    assert isinstance(cli._make_pool(r0, "sonnet"), ProviderPool)               # off: exactly as before M202
    monkeypatch.setenv(llmcache.ENV, "replay")
    p = cli._make_pool(r0.model_copy(update={"llm_cache": r0.llm_cache.model_copy(update={"dir": str(tmp_path)})}),
                       "sonnet")
    assert isinstance(p, llmcache.CachedLLM) and p.ident == "anthropic:claude-sonnet-5-5" and p.dir == tmp_path


def test_the_run_fails_when_replay_missed(tmp_path, capsys):
    from autoreels import __main__ as cli
    assert cli._llm_cache_verdict() is False and capsys.readouterr().out == ""   # cache off: no line, as before
    r = llmcache.wrap(_Model(), mode="replay", cache_dir=tmp_path)
    with pytest.raises(ProviderError):
        r.complete(MSG)
    assert cli._llm_cache_verdict() is True
    out = capsys.readouterr().out
    assert "промахов 1" in out and "НЕ воспроизведён" in out and "ARL_LLM_CACHE=record" in out


def _scenario_project(tmp_path):
    """The fake source of test_scenario: one thought of the map; the scenarist writes two reels of its halves."""
    from autoreels import __main__ as cli
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 1 ")
                   .replace("  hook_llm: auto ", "  hook_llm: none "), encoding="utf-8")
    r0 = cli.load_r0_config(cfg)
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    ss = merge_group_sentences([kept[1]], tx.words)
    n = len(ss)
    assert n >= 2
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps({"version": 1, "stem": "v", "source_sha256": "f" * 64,
        "units": [{"id": 1, "t0": ss[0][0].t0, "t1": ss[-1][-1].t1, "role": "thesis", "punch": 4,
                   "refs": f"2.1-{n}", "topic": 1, "standalone": True, "summary": "тезис"}]}), encoding="utf-8")
    h = n // 2
    first = f"2.1-{h}" if h > 1 else "2.1"
    second = f"2.{h + 1}-{n}" if n > h + 1 else f"2.{n}"

    class Fake:
        model_id = "fake:scenarist"

        def complete(self, messages, temperature=0.0):
            return f"M | {first} | t: Первая половина | why: a\nM | {second} | t: Вторая половина | why: b"
    return cli, Fake, first, second


def test_autocut_shows_a_too_close_candidate_with_its_reason(tmp_path, capsys):
    cli, Fake, first, second = _scenario_project(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"                 # M206: the repo config closes by sound — here by the map
    import re
    cfg.write_text(re.sub(r"(?m)^  close_by: \w+", "  close_by: units", cfg.read_text(encoding="utf-8")), encoding="utf-8")
    rc = cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, scenario=True,
                         scenario_provider=Fake(), out=str(tmp_path / "reviews" / "v_close.txt"))
    out = capsys.readouterr().out
    assert rc == 0 and "(похожи на принятые: 1)" in out
    assert f"  ≈ {second} — " in out and "M1" in out and "учёт кандидатов" not in out


def test_autocut_lists_the_candidates_it_never_reached(tmp_path, capsys):
    cli, Fake, first, second = _scenario_project(tmp_path)
    rc = cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, scenario=True, clips=1,
                         scenario_provider=Fake(), out=str(tmp_path / "reviews" / "v_one.txt"))
    out = capsys.readouterr().out
    text = (tmp_path / "reviews" / "v_one.txt").read_text(encoding="utf-8")
    assert rc == 0 and "(не дошла очередь: 1)" in out and f"  … {second} — не дошла очередь (уже принято 1)" in out
    assert "# --- не дошла очередь: уже принято 1" in text and f"#! M 94 | {second} |" in text   # 2nd of the model
    assert "учёт кандидатов" not in out
