"""Машинно-локальная история прогонов (JSONL, append-only, НЕ в git — как transcripts/).

Заменяет «файл ушёл в архив = обработан» долговечной записью: на вопрос «я это уже
гонял?» отвечает история, а не расположение файла. Пишется на КАЖДЫЙ прогон, включая
ранние падения (краш до манифеста — тоже история) и пропуски битых файлов.

Одна строка = один прогон. Рост ограничен `cap` (по умолчанию 500): при превышении
старые строки отбрасываются на записи, о чём сообщается один раз.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_CAP = 500
_ENV_PATH = "AUTOREELS_HISTORY_PATH"   # тест/оверрайд пути файла (изоляция от реального data/)
_ENV_CAP = "AUTOREELS_HISTORY_CAP"     # оверрайд лимита записей

# Допустимые исходы (для справки/валидации фильтра): ok | zero-harvest | failed | skipped.
OUTCOMES = ("ok", "zero-harvest", "failed", "skipped")


def resolve_path(explicit: str | Path | None = None, root: str | Path | None = None) -> Path:
    """Путь файла истории: явный аргумент > env AUTOREELS_HISTORY_PATH > <root>/data/history.jsonl."""
    if explicit:
        return Path(explicit)
    env = os.environ.get(_ENV_PATH)
    if env:
        return Path(env)
    root = Path(root) if root is not None else Path.cwd()
    return root / "data" / "history.jsonl"


def _cap(explicit: int | None = None) -> int:
    if explicit is not None:
        return explicit
    env = os.environ.get(_ENV_CAP)
    if env and env.isdigit():
        return int(env)
    return DEFAULT_CAP


def _iso(now: float | None = None) -> str:
    t = now if now is not None else time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def append_run(
    path: str | Path,
    *,
    source: str,
    source_path: str | Path,
    sha256: str,
    duration_sec: float,
    outcome: str,
    reel_count: int,
    selection_source: str,
    manifest_path: str | Path,
    cap: int | None = None,
    now: float | None = None,
) -> dict:
    """Дописать одну запись прогона; при превышении cap — обрезать до последних cap (сообщив один раз).

    Не роняет вызывающего: запись истории вспомогательна, ошибка ФС не должна валить прогон.
    """
    rec = {
        "ts": _iso(now),
        "source": source,
        "source_path": str(source_path),
        "sha256": sha256 or "",
        "duration_sec": round(float(duration_sec), 2),
        "outcome": outcome,
        "reel_count": int(reel_count),
        "selection_source": selection_source or "auto",
        "manifest": str(manifest_path or ""),
    }
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _trim(path, _cap(cap))
    except OSError as e:  # запись истории вспомогательна — не роняем прогон из-за ФС
        print(f"⚠ не удалось записать историю ({path}): {e}", flush=True)
    return rec


def _trim(path: Path, cap: int) -> None:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) <= cap:
        return
    dropped = len(lines) - cap
    path.write_text("\n".join(lines[-cap:]) + "\n", encoding="utf-8")
    print(f"история: обрезана до последних {cap} записей (удалено {dropped})", flush=True)


def read_runs(
    path: str | Path, *, limit: int | None = None, outcome: str | None = None
) -> list[dict]:
    """Записи новейшими первыми. Битые строки пропускаются. `outcome` — опциональный фильтр."""
    path = Path(path)
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if outcome and rec.get("outcome") != outcome:
            continue
        out.append(rec)
    out.reverse()                       # newest first
    if limit is not None:
        out = out[:limit]
    return out


if __name__ == "__main__":  # ponytail: минимальная self-check без фреймворка
    import tempfile

    d = Path(tempfile.mkdtemp())
    hp = d / "h.jsonl"
    for i in range(7):
        append_run(hp, source=f"v{i}.mp4", source_path=f"/x/v{i}.mp4", sha256="a" * 64,
                   duration_sec=1.5, outcome="ok" if i % 2 else "failed",
                   reel_count=i, selection_source="auto", manifest_path="m.json",
                   cap=5, now=1_700_000_000 + i)
    runs = read_runs(hp)
    assert len(runs) == 5, runs                     # обрезано до cap=5
    assert runs[0]["source"] == "v6.mp4", runs[0]   # новейший первым
    assert [r["source"] for r in read_runs(hp, limit=2)] == ["v6.mp4", "v5.mp4"]
    only_ok = read_runs(hp, outcome="ok")
    assert only_ok and all(r["outcome"] == "ok" for r in only_ok)
    print("history self-check ok")
