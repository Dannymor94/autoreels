"""Статусы проекта + идемпотентность (хэши/кэш).

Ловушка из Meeting→Tasks (размножение задач) — здесь та же: повторный прогон не должен
плодить дубли и перетранскрибировать. Поэтому ключи кэша детерминированы по содержимому.

R0_SPEC §9:
- транскрипт кэшируется по **хэшу аудио** → Whisper не дёргается повторно;
- ключ прогона = хэш(source + duration_preset + версия рубрики) — добавится на шаге 5.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

_HASH_CHUNK = 1 << 20  # 1 МиБ


def file_sha256(path: str | Path) -> str:
    """sha256 содержимого файла (потоково). Единая основа всех ключей идемпотентности."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_cache_key(path: Path) -> str:
    """Ключ записи кэша хэша: sha256(resolved_path + size + mtime_ns)."""
    st = path.stat()
    raw = f"{path.resolve()!s}\0{st.st_size}\0{st.st_mtime_ns}"
    return hashlib.sha256(raw.encode()).hexdigest()


def file_sha256_cached(path: str | Path, cache_dir: str | Path) -> str:
    """sha256 содержимого файла с диск-кэшем по (путь, размер, mtime).

    Кэш: cache_dir/sha256/<key>.txt. При совпадении ключа (файл не изменился)
    возвращает сохранённый хэш без перечитывания — критично для многогигабайтных видео.
    """
    path = Path(path)
    sha_cache = Path(cache_dir) / "sha256"
    sha_cache.mkdir(parents=True, exist_ok=True)
    entry = sha_cache / f"{_sha256_cache_key(path)}.txt"
    if entry.is_file():
        cached = entry.read_text().strip()
        if len(cached) == 64:  # валидный sha256 hex
            return cached
    result = file_sha256(path)
    entry.write_text(result)
    return result


def audio_hash(path: str | Path) -> str:
    """Ключ кэша транскрипта = хэш содержимого аудио (R0_SPEC §9)."""
    return file_sha256(path)


_PARTIAL_HEAD = 8 * 1024 * 1024   # 8 МБ с начала
_PARTIAL_MID  = 1 * 1024 * 1024   # 1 МБ из середины (страховка от одинаковых заголовков)
_PARTIAL_TAIL = 8 * 1024 * 1024   # 8 МБ с конца


def file_sha256_partial(path: str | Path) -> str:
    """Быстрый хэш крупного файла: sha256(head‖mid‖tail‖size_le64).

    Читает начало, середину и конец — несколько МБ вместо всего файла.
    Середина защищает от сценария «одна камера, разные сессии» с общим заголовком.
    """
    path = Path(path)
    size = path.stat().st_size
    h = hashlib.sha256()
    with path.open("rb") as f:
        h.update(f.read(min(_PARTIAL_HEAD, size)))
        mid_offset = max(0, size // 2 - _PARTIAL_MID // 2)
        if mid_offset > _PARTIAL_HEAD:
            f.seek(mid_offset)
            h.update(f.read(_PARTIAL_MID))
        tail_offset = max(0, size - _PARTIAL_TAIL)
        if tail_offset > mid_offset + _PARTIAL_MID or tail_offset > _PARTIAL_HEAD:
            f.seek(tail_offset)
            h.update(f.read(_PARTIAL_TAIL))
    h.update(size.to_bytes(8, "little"))
    return h.hexdigest()


def file_sha256_cached_fast(path: str | Path, cache_dir: str | Path) -> str:
    """Частичный хэш с диск-кэшем (как file_sha256_cached, но partial-алгоритм).

    Кэш-файл содержит 'p1:<hex>' — отличает от старых full-sha записей при чтении.
    Возвращает только 64-char hex — именно это кладётся в манифест/калибровку.
    """
    path = Path(path)
    sha_cache = Path(cache_dir) / "sha256"
    sha_cache.mkdir(parents=True, exist_ok=True)
    entry = sha_cache / f"{_sha256_cache_key(path)}.txt"
    if entry.is_file():
        cached = entry.read_text().strip()
        if cached.startswith("p1:") and len(cached) == 67:   # "p1:" + 64 hex
            return cached[3:]
    result = file_sha256_partial(path)
    entry.write_text(f"p1:{result}")
    return result


def transcript_cache_path(cache_dir: str | Path, audio_path: str | Path) -> Path:
    """Путь к кэшу транскрипта: <cache_dir>/<audio_hash>.transcript.json."""
    return Path(cache_dir) / f"{audio_hash(audio_path)}.transcript.json"
