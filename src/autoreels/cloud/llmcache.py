"""M202: the answers of the models, kept per request — a run can be replayed byte for byte.

Owner (2026-11-02): «максимально детерминированно». m200 showed why: one `arl auto` gave another draft when the paid
model stopped answering (plates, k:, seams fell back silently), and an A/B of code ran on whatever the models said that
day. With `llm_cache` (config/r0.yaml) or the environment variable ARL_LLM_CACHE:
  off    — as before (nothing kept, nothing read);
  record — an answer already kept is returned without a request; a new one is asked and kept;
  replay — only kept answers; a request with none is a miss (ProviderError), counted, and `arl auto` ends with code 1:
           the run was not reproduced. An A/B of code on replay differs only by the code.
The key is the model id + the messages + the temperature (sha256), the file data/cache/llm/<2>/<key>.json. A changed
prompt, example or upstream text is a new key — in replay a miss, as it should be: the request is not the same.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from autoreels.cloud.providers import ProviderError

MODES = ("off", "record", "replay")
ENV = "ARL_LLM_CACHE"

_live: list["CachedLLM"] = []          # every wrapper of this process — the totals of a run


def mode_of(config_mode: str) -> str:
    """The environment variable over the config; an unknown value is an error, not a silent «off»."""
    m = (os.environ.get(ENV) or config_mode or "off").strip().lower()
    if m not in MODES:
        raise ProviderError(f"{ENV}/llm_cache.mode: «{m}» — допустимо {', '.join(MODES)}")
    return m


def request_key(ident: str, messages: list[dict], temperature: float) -> str:
    blob = json.dumps({"id": ident, "t": float(temperature), "m": messages}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CachedLLM:
    """A provider (or pool) whose answers are kept per request. Everything but complete() and usage_lines() is the
    wrapped provider's (describe, preflight, model_id, name …)."""

    def __init__(self, inner, *, mode: str, cache_dir: Path, ident: str | None = None):
        self._inner = inner
        self.mode = mode
        self.dir = Path(cache_dir)
        self.ident = ident or getattr(inner, "model_id", "") or type(inner).__name__
        self.hits = self.writes = self.misses = 0
        _live.append(self)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def complete(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        key = request_key(self.ident, messages, temperature)
        path = self._path(key)
        if path.is_file():
            try:
                answer = json.loads(path.read_text(encoding="utf-8"))["answer"]
                self.hits += 1
                return answer
            except (ValueError, KeyError, OSError):
                pass                       # a broken file is no answer: replay misses, record asks again
        if self.mode == "replay":
            self.misses += 1
            raise ProviderError(f"replay: ответа нет в кэше моделей ({self.ident}, {key[:12]})")
        answer = self._inner.complete(messages, temperature=temperature)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"id": self.ident, "answer": answer}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        self.writes += 1
        return answer

    def usage_lines(self) -> list[str]:
        inner = list(getattr(self._inner, "usage_lines", lambda: [])())
        if self.hits or self.writes or self.misses:
            inner.append(f"кэш моделей ({self.mode}, {self.ident}): из кэша {self.hits}, записано {self.writes}, "
                         f"промахов {self.misses}")
        return inner


def wrap(provider, *, mode: str, cache_dir: Path, ident: str | None = None):
    """off → the provider itself (nothing changes); record / replay → CachedLLM."""
    if mode == "off" or provider is None:
        return provider
    return CachedLLM(provider, mode=mode, cache_dir=cache_dir, ident=ident)


def totals() -> tuple[int, int, int]:
    """(from the cache, written, misses) of every wrapper of this process."""
    return (sum(c.hits for c in _live), sum(c.writes for c in _live), sum(c.misses for c in _live))


def reset() -> None:
    _live.clear()
