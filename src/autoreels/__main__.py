"""CLI-склейка тиров: две команды по границе ОБЛАКО/ЛОКАЛЬ (M0 шаг 8).

Убирает терминал-ритуал (ручная активация venv, многострочные `python -c`, ручные пути,
`source .env`, невидимый прогресс). Без субтитров — R3 встанет одним блоком между select
и render (этапы `run` оформлены как отдельные функции-блоки именно ради этого).

    autoreels run [video]            # без аргумента → batch: все inputs/*.mp4
    autoreels render                 # системник: manifests/*.json → reels-out/

Граница тиров: `run` живёт в облачном конвейере (аудио/текст), `render` — локальный ffmpeg.
Видео между тирами не ходит: манифест несёт source_sha256, render ищет файл в inputs/.

Манифест: manifests/<stem>.json (имя по видео, batch-совместимость).
Архив: inputs-archive/ — после успеха видео перемещается, идемпотентно.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue as _queue
import shutil
import sys
import threading as _threading
import time
from dataclasses import dataclass
from pathlib import Path

from autoreels.cloud.compress import compress_transcript
from autoreels.cloud.diagnose import classify_end, summarize
from autoreels.cloud.extract_audio import ExtractAudioError, extract_audio
from autoreels.cloud.providers import ProviderError, build_pool
from autoreels.cloud.select import (
    FLAG_TOO_LONG, FLAG_TOO_SHORT,
    SelectError, apply_top_n, detect_host_turns, diagnose_collapse,
    filter_dangling_start, filter_min_clip_duration, flag_durations, select, _stage_interview_snap,
)
from autoreels.cloud.chunk_transcribe import renumber_reels
from autoreels.cloud.snap import apply_padding, snap_segments, trim_hanging_subtitles, try_rescue_clip
from autoreels.cloud.trim import trim_too_long
from autoreels.cloud.transcribe import (
    TranscriptionError,
    _backend_meta,
    get_backend,
    params_key,
    transcribe,
    transcript_identity,
)
from autoreels.cloud.transcribe_formats import to_json, to_srt, to_text, to_vtt
from autoreels.core import history, state
from autoreels.core.env import MissingKeyError, require_key
from autoreels.core.calibration import (
    CalibrationError,
    _probe_frame_size_for_auto,
    auto_crop,
    calibration_path,
    load_calibration,
    load_or_auto_calibrate,
    save_calibration,
    validate_crop_in_frame,
)
from autoreels.core.config import (
    ConfigError,
    load_r0_config,
    load_render_config,
    load_subtitles_config,
    load_transcribe_config,
    validate_profile,
)
from autoreels.core.models import Manifest, Transcript
from autoreels.local.calibrate import (
    CalibrateError, InputInvalid, cmd_calibrate, validate_input,
)
from autoreels.local.render import (
    RenderError, SourceNotFoundError, load_manifest, probe_encoder, render_crop,
    render_preview,
)
from autoreels.local.subtitles import words_in_window

class RunError(Exception):
    """Приём исходника не удался: не видео (по расширению) или коллизия имени в inputs/.

    Отдельный тип (не FileNotFoundError — файл-то есть): CLI ловит его в _KNOWN_ERRORS
    и печатает внятное сообщение вместо голого traceback.
    """


class ZeroHarvestError(Exception):
    """Транскрипт непустой, но R0 не нашёл ни одного рила.

    Источник остаётся в inputs/ — нужна ручная проверка (плохой материал или
    слишком строгий порог). Отличается от пустого транскрипта (тишина/пустышка)
    — тот архивируется автоматически.
    """


class AlreadyProcessedError(Exception):
    """run_key источника уже есть в манифесте → повторный прогон не нужен (--force прогонит).

    Заменяет «файл ушёл в архив, значит готово» контентной проверкой (инвариант #4):
    тот же source+preset → тот же run_key → пропуск, а не повторный недетерминированный R0.
    """


class ManualManifestError(Exception):
    """Автопрогон стёр бы манифест с ручной выборкой (selection_source=human) → отказ.

    Двадцать минут ручной разметки не должны молча пропасть под авто-R0. --force
    перезапишет, предупредив, сколько рилов выбрасывается.
    """


# Ошибки тиров, которые CLI превращает во внятное сообщение (а не голый traceback).
class FFmpegNotFoundError(Exception):
    """ffmpeg не найден (ни флаг/env/render.local.yaml, ни PATH, ни типичные пути).

    Сообщение перечисляет, где искали, и как задать путь (флаг / env / render.local.yaml)."""


_KNOWN_ERRORS = (
    ExtractAudioError,
    TranscriptionError,
    ProviderError,
    SelectError,
    RenderError,
    ConfigError,
    CalibrationError,
    CalibrateError,
    RunError,
    FFmpegNotFoundError,
    MissingKeyError,
    FileNotFoundError,
)

# Расширения, которые считаем видео при приёме исходника по явному пути. Список — лишь
# ранний дружелюбный отсев (ffmpeg остаётся глубоким валидатором на этапе extract_audio).
_VIDEO_EXTS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
    ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts",
}
# Аудио — принимает только `transcribe` (для контента из подкастов/записей). `run`/`render`
# работают с видео, поэтому `_ingest_source` держит планку `_VIDEO_EXTS`.
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma"}
_MEDIA_EXTS = _VIDEO_EXTS | _AUDIO_EXTS

# Расширения, которые batch-сканер принимает из inputs/ (case-insensitive).
# Подмножество _VIDEO_EXTS — форматы, реально встречающиеся у пользователей.
_BATCH_SCAN_EXTS = {".mp4", ".mov", ".mkv"}


def _scan_inputs(inputs_dir: Path) -> list[Path]:
    """Вернуть отсортированный список видеофайлов в inputs_dir.

    Правила:
    - Расширения .mp4/.mov/.mkv принимаются без учёта регистра (.MP4, .MOV, .MKV — ОК).
    - Скрытые файлы (имя начинается с '.') всегда пропускаются (.DS_Store, .hidden.mp4).
    - Фильтр по размеру/длительности не применяется (те не нужны на этапе перечисления).
    """
    if not inputs_dir.is_dir():
        return []
    return sorted(
        p for p in inputs_dir.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() in _BATCH_SCAN_EXTS
    )


def _report_empty_inputs(inputs_dir: Path) -> None:
    """Диагностическое сообщение, когда inputs_dir не содержит видеофайлов.

    Печатает абсолютный путь сканированного каталога, текущую рабочую директорию и
    список файлов, которые есть, но не прошли фильтр — с причиной (до 10 штук).
    """
    inputs_abs = inputs_dir.resolve()
    print(f"inputs/ пуст — нечего обрабатывать", flush=True)
    print(f"  сканировался: {inputs_abs}", flush=True)
    print(f"  cwd:          {Path.cwd()}", flush=True)
    if not inputs_dir.is_dir():
        print(f"  каталог не существует", flush=True)
        return
    entries = [p for p in inputs_dir.iterdir() if p.is_file()]
    print(f"  файлов в каталоге: {len(entries)}", flush=True)
    missed = [p for p in entries if p.suffix.lower() not in _BATCH_SCAN_EXTS or p.name.startswith(".")]
    for p in missed[:10]:
        if p.name.startswith("."):
            reason = "скрытый файл"
        else:
            reason = f"расширение {p.suffix!r} не в {sorted(_BATCH_SCAN_EXTS)}"
        print(f"    {p.name} — {reason}", flush=True)


def _validate_media(path: Path, *, exts: set[str]) -> Path:
    """Проверить, что путь — существующий файл с медиа-расширением; вернуть resolve().

    Общая валидация для `_ingest_source` (видео) и `transcribe` (видео+аудио). Ошибки:
    нет файла / каталог → FileNotFoundError; чужое расширение → RunError.
    """
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"файл не найден: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"не файл (это каталог?): {path}")
    if path.suffix.lower() not in exts:
        raise RunError(
            f"не похоже на медиа: {path.name} "
            f"(ожидалось расширение из {', '.join(sorted(exts))})"
        )
    return path.resolve()


# --------------------------------------------------------------------------- .env

# Отчёт о загрузке .env (путь, найденные ключи, .env.txt) — заполняется _load_env(), читается
# командой `doctor` и preflight'ом run для внятных сообщений вместо 401 из глубины.
_ENV_REPORT = None


def _load_env() -> None:
    """Подхватить .env в окружение УСТОЙЧИВО: чистка CRLF/кавычек/пробелов, поиск от корня
    проекта, детект .env.txt (закрывает ручной `source .env` и Windows-грабли с 401)."""
    global _ENV_REPORT
    from autoreels.core import env as _envmod

    _ENV_REPORT = _envmod.load_env(root=_project_root())


def _run_key(source_sha256: str, duration_preset: str) -> str:
    """Детерминированный ключ прогона от source+preset (полноценная версия рубрики — M1)."""
    return hashlib.sha256(f"{source_sha256}:{duration_preset}".encode()).hexdigest()[:16]


def _load_manifest_or_none(path: Path) -> "Manifest | None":
    """Прочитать манифест, вернуть None на битом/невалидном (чужой JSON в manifests/ не роняет прогон)."""
    try:
        return Manifest.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — битый/чужой файл в manifests/ не должен ронять batch
        return None


def _guard_already_processed(video: Path, sha: str, duration_preset: str,
                             manifests_dir: Path, *, force: bool) -> None:
    """Проверка ДО дорогого анализа (extract/Whisper/R0). Заменяет «ушло в архив = готово».

    Порядок (сначала защита ручного труда, потом дедуп):
    1. Манифест, который этот прогон ПЕРЕЗАПИСАЛ бы (manifests/<stem>.json — тот же выход),
       с selection_source=human → ManualManifestError (без force). С force — предупреждаем,
       сколько рилов выбрасываем, и прогоняем.
    2. run_key (sha+preset) уже встречается в любом манифесте → AlreadyProcessedError (без force).
    `--force` прогоняет всегда.
    """
    manifests_dir = Path(manifests_dir)
    # 1. Ручная выборка на том же выходном пути (перезапись стёрла бы её).
    target = manifests_dir / f"{Path(video).stem}.json"
    existing = _load_manifest_or_none(target) if target.is_file() else None
    if existing is not None and existing.selection_source == "human":
        n = len(existing.reels)
        if not force:
            raise ManualManifestError(
                f"{target.name} — ручная выборка ({n} рилов, selection_source=human); "
                f"автопрогон её бы стёр. Проверьте вручную, затем --force для перезаписи."
            )
        print(f"  ⚠ --force: перезаписываю ручную выборку {target.name} "
              f"(выбрасываю {n} рилов)", flush=True)
        return  # force над ручным: прогоняем, дедуп ниже пропускаем
    # 2. Дедуп по run_key (контентная идентичность + preset).
    if force:
        return
    run_key = _run_key(sha, duration_preset)
    for mf in sorted(manifests_dir.glob("*.json")):
        m = _load_manifest_or_none(mf)
        if m is not None and m.run_key == run_key:
            raise AlreadyProcessedError(
                f"{Path(video).name} уже обработан (run_key={run_key}) → {mf.name}; "
                f"--force прогонит заново"
            )


# ----------------------------------------------------- приём исходника (путь → inputs/)

def _path_inside(path: Path, base: Path) -> bool:
    """Лежит ли `path` внутри каталога `base` (по абсолютным путям)? Ошибка резолва → False."""
    try:
        Path(path).expanduser().resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False


def _ingest_source(video: Path, inputs_dir: Path) -> Path:
    """Втянуть исходник в inputs/ так, чтобы `render` нашёл его по sha256.

    `run` может получить путь куда угодно (`arl run ~/Downloads/лекция.mp4`), но `render`
    ищет исходник только в `inputs/`. Поэтому внешний путь копируется в `inputs/<имя>`
    (оригинал не трогаем — не move и не symlink: symlink на Windows требует прав, а move
    унёс бы чужой файл). Путь уже внутри `inputs/` — используется как есть.

    Возвращает путь внутри `inputs/`, который дальше идёт в `cmd_run`. Ошибки:
    - несуществующий путь / это каталог → FileNotFoundError;
    - расширение не видео → RunError (ранний отсев до ffmpeg);
    - в `inputs/` уже другой файл с тем же именем → RunError (без тихой перезаписи).
    """
    video = _validate_media(video, exts=_VIDEO_EXTS)
    inputs_dir = Path(inputs_dir).resolve()

    # Уже внутри inputs/ → ничего не копируем.
    try:
        video.relative_to(inputs_dir)
        return video
    except ValueError:
        pass

    inputs_dir.mkdir(parents=True, exist_ok=True)
    dest = inputs_dir / video.name
    if dest.exists():
        if state.file_sha256_partial(video) == state.file_sha256_partial(dest):
            return dest                                   # тот же файл — идемпотентно
        raise RunError(
            f"в inputs/ уже есть другой файл с именем {video.name!r} — "
            f"переименуйте исходник или уберите старый ({dest})"
        )

    print(f"копирую в inputs/: {video.name}…", flush=True)
    shutil.copy2(video, dest)
    return dest


# ----------------------------------------------------- приём по URL (yt-dlp → inputs/)

def _is_url(arg: str) -> bool:
    """http/https-ссылка → True; всё остальное (пути, C:\\…, file://, ftp://) → локальный путь."""
    from urllib.parse import urlparse

    try:
        return urlparse(arg).scheme in ("http", "https")
    except (ValueError, AttributeError):
        return False


def _sanitize_filename(title: str, *, maxlen: int = 80) -> str:
    """Заголовок ролика → безопасное имя файла.

    Оставляем буквы (в т.ч. кириллицу — `str.isalnum` их пропускает), цифры, `_` и `-`.
    Эмодзи/слэши/спецсимволы/пробелы → разделитель, схлопываются в один `_`, обрезка до
    `maxlen`. Заголовок целиком из эмодзи → пустая строка (вызывающий откатится на id).
    """
    import re

    kept: list[str] = []
    for ch in title:
        if ch in "_-" or ch.isalnum():
            kept.append(ch)
        else:
            kept.append(" ")           # всё небезопасное (вкл. эмодзи, /, пробелы) → разрыв
    s = re.sub(r"\s+", "_", "".join(kept).strip())
    s = re.sub(r"_+", "_", s).strip("_-")
    return s[:maxlen].strip("_-")


def _download_url(
    url: str,
    inputs_dir: Path,
    *,
    ytdlp: str = "yt-dlp",
    which=None,
    run=None,
) -> Path:
    """Скачать видео по ссылке в `inputs/` и вернуть путь (дальше — обычный конвейер).

    yt-dlp — опциональная внешняя зависимость (`pip install 'autoreels[url]'`); зовём как
    подпроцесс. Ограничение 1080p (вертикаль всё равно кропается — 4K избыточен),
    `--no-playlist` (строго одно видео). Прогресс yt-dlp идёт в stderr → виден вживую;
    stdout несёт путь и заголовок (`--print`) для переименования.

    Имя: `<санитизированный_заголовок>_<id>.<ext>` (заголовок всё из эмодзи → просто `<id>`).
    yt-dlp вернул код ≠ 0 (битая/приватная/гео-блок ссылка, не видео) → RunError.
    """
    import subprocess

    which = which or shutil.which
    run = run or subprocess.run

    exe = which(ytdlp)
    if exe is None:
        raise RunError(
            "URL-режим требует yt-dlp. Установите: pip install 'autoreels[url]' "
            "(или pip install yt-dlp)"
        )

    inputs_dir = Path(inputs_dir)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(inputs_dir / "%(id)s.%(ext)s")

    cmd = [
        exe,
        "--no-playlist",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "-o", out_tmpl,
        "--print", "after_move:filepath",
        "--print", "after_move:%(title)s",
        url,
    ]

    print(f"скачиваю: {url}", flush=True)
    # stdout=PIPE — ловим путь+заголовок; stderr наследуется → прогресс yt-dlp виден вживую.
    result = run(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8")

    if result.returncode != 0:
        raise RunError(
            f"yt-dlp не смог скачать {url} (код {result.returncode}) — "
            f"проверьте ссылку: битая / недоступна / приватная / гео-блок / не видео"
        )

    lines = [ln for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise RunError(f"yt-dlp не сообщил путь скачанного файла для {url}")

    id_path = Path(lines[0].strip())
    if not id_path.exists():
        raise RunError(f"yt-dlp сообщил путь, которого нет: {id_path}")
    title = lines[1].strip() if len(lines) > 1 else ""

    safe = _sanitize_filename(title)
    stem = id_path.stem                       # это <id> (из шаблона %(id)s)
    new_name = f"{safe}_{stem}{id_path.suffix}" if safe else id_path.name
    final = inputs_dir / new_name
    if final != id_path:
        id_path.replace(final)                # перезаписывает при повторе — идемпотентно
    print(f"скачано → inputs/{final.name}", flush=True)
    return final


# ----------------------------------------------------- приём с Яндекс.Диска (public API)

_YANDEX_HOSTS = {"disk.yandex.ru", "disk.yandex.com", "yadi.sk"}
_YANDEX_PUBLIC_API = "https://cloud-api.yandex.net/v1/disk/public/resources"


def _is_yandex_disk(url: str) -> bool:
    """Публичная ссылка Я.Диска (disk.yandex.ru / disk.yandex.com / yadi.sk)?"""
    from urllib.parse import urlparse

    try:
        host = urlparse(url).netloc.lower()
    except (ValueError, AttributeError):
        return False
    host = host.removeprefix("www.")
    return host in _YANDEX_HOSTS


def _yandex_filename(name: str, url: str) -> str:
    """Имя ролика Я.Диска → безопасное имя в inputs/: `<sanitized>_<hash8>.<ext>`.

    Хэш от public_key ([:8]) страхует от коллизий (две разные ссылки с одинаковым
    именем файла) и даёт идемпотентность (та же ссылка → то же имя). Заголовок пуст
    после санитизации (весь из эмодзи) → фолбэк `yadisk_<hash8>`.
    """
    import hashlib

    ext = Path(name).suffix or ".mp4"
    safe = _sanitize_filename(Path(name).stem)
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    base = f"{safe}_{h}" if safe else f"yadisk_{h}"
    return f"{base}{ext}"


def _yandex_api_get(suffix: str, public_key: str, *, token: str | None = None) -> dict:
    """GET JSON с public API Я.Диска. suffix='' — метаданные, '/download' — ссылка.

    Публичным ресурсам токен не нужен; token (OAuth) — только для приватных (не MVP).
    Модульный уровень → monkeypatch httpx.get в тестах. Ошибки API/сети → RunError.
    """
    import httpx

    headers = {"Authorization": f"OAuth {token}"} if token else {}
    try:
        resp = httpx.get(
            _YANDEX_PUBLIC_API + suffix,
            params={"public_key": public_key},
            headers=headers, timeout=30, follow_redirects=True,
        )
    except httpx.HTTPError as e:
        raise RunError(f"сеть недоступна при запросе к Я.Диску: {e}") from e
    if resp.status_code == 404:
        raise RunError(f"ссылка Я.Диска не найдена (удалена/приватная): {public_key}")
    if resp.status_code >= 400:
        raise RunError(f"Я.Диск API вернул {resp.status_code} для {public_key}")
    return resp.json()


def _yandex_public_meta(url: str, *, get_json=None, token: str | None = None) -> dict:
    """Метаданные публичного ресурса: name / type (file|dir) / mime_type / size."""
    get_json = get_json or _yandex_api_get
    return get_json("", url, token=token)


def _yandex_download_href(url: str, *, get_json=None, token: str | None = None) -> str:
    """Свежая ВРЕМЕННАЯ ссылка на скачивание (истекает за минуты — не кэшировать)."""
    get_json = get_json or _yandex_api_get
    href = get_json("/download", url, token=token).get("href")
    if not href:
        raise RunError(f"Я.Диск не вернул ссылку на скачивание для {url}")
    return href


def _httpx_stream_download(href: str, part_path: Path, *, resume_from: int, total: int | None) -> None:
    """Скачать `href` в `part_path` потоково (httpx), с читаемым прогрессом (%/ГБ/скорость/ETA).

    resume_from>0 → докачка: заголовок `Range: bytes=N-`, дозапись в конец. Если сервер
    проигнорировал Range (ответ 200, не 206) — начинаем файл заново (иначе дублируем байты).
    Полный контроль над форматом прогресса (в отличие от сырой таблицы curl). HTTP≥400 → RunError.
    """
    import time

    import httpx

    from autoreels.core.progress import print_download_progress

    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
    with httpx.stream("GET", href, headers=headers, timeout=None, follow_redirects=True) as resp:
        if resp.status_code >= 400:
            raise RunError(f"скачивание не удалось: HTTP {resp.status_code}")
        # Сервер отдал полный файл вместо диапазона → пишем с нуля, не дописываем.
        resuming = resume_from > 0 and resp.status_code == 206
        mode = "ab" if resuming else "wb"
        downloaded = resume_from if resuming else 0

        start = time.monotonic()
        last_print = 0.0
        with open(part_path, mode) as f:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                f.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_print >= 0.5:
                    elapsed = now - start
                    speed = (downloaded - (resume_from if resuming else 0)) / elapsed if elapsed > 0 else 0
                    print_download_progress(downloaded, total, speed)
                    last_print = now


def _download_yandex_disk(
    url: str,
    inputs_dir: Path,
    *,
    get_json=None,
    download=None,
    token: str | None = None,
    max_stalls: int = 8,
    retry_pause_sec: float = 3.0,
) -> Path:
    """Скачать файл с публичной ссылки Я.Диска в `inputs/` (httpx-стрим) → путь для конвейера.

    Поток: метаданные (тип/видео/размер, дёшево до гигабайтов) → цикл докачки, где на
    КАЖДОЙ попытке берётся СВЕЖИЙ временный download URL (старый протухает на 31 ГБ) и
    поток докачивает `.part` с текущего смещения (`Range`). Целостность — по размеру из
    метаданных. Прогресс — читаемая строка (%/ГБ/скорость/ETA).

    Устойчивость к обрывам (Яндекс троттлит большие файлы и рвёт соединение — «Connection
    reset by peer»): обрыв соединения (`httpx.HTTPError`) ловится, качаем дальше со свежей
    ссылки с места обрыва. Сдаёмся только после `max_stalls` попыток ПОДРЯД без прогресса
    (а не после N всего) — пока байты идут, докачка продолжается сколько нужно.

    Только файлы (/i/). Папка (/d/, type=='dir') — предупредить и выйти (batch — будущее).
    """
    import os
    import time

    import httpx

    from autoreels.core.progress import _gb, print_download_done

    get_json = get_json or _yandex_api_get
    download = download or _httpx_stream_download
    token = token or os.environ.get("YANDEX_DISK_TOKEN")

    meta = _yandex_public_meta(url, get_json=get_json, token=token)
    rtype = meta.get("type")
    if rtype == "dir":
        raise RunError(
            "ссылка Я.Диска ведёт на папку (/d/…), а нужен один файл (/i/…). "
            "Batch с папки Я.Диска — будущее расширение, пока не поддерживается."
        )
    if rtype != "file":
        raise RunError(f"неизвестный тип ресурса Я.Диска: {rtype!r}")

    name = meta.get("name") or "video.mp4"
    mime = meta.get("mime_type", "") or ""
    if not (mime.startswith("video/") or Path(name).suffix.lower() in _VIDEO_EXTS):
        raise RunError(f"файл по ссылке Я.Диска не видео: {name} (mime {mime!r})")

    inputs_dir = Path(inputs_dir)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    dest = inputs_dir / _yandex_filename(name, url)
    if dest.exists():
        print(f"уже скачано → inputs/{dest.name}", flush=True)
        return dest
    part = dest.with_name(dest.name + ".part")

    size = meta.get("size") if isinstance(meta.get("size"), int) else None
    if size and size > (1 << 30):     # >1 ГБ — честно предупредить про троттлинг
        print(
            f"файл {name}: {size / (1 << 30):.1f} ГБ. Публичные ссылки Я.Диск троттлит — "
            f"большой файл может качаться долго (докачка при обрывах включена).",
            flush=True,
        )

    started = time.monotonic()
    stalls = 0
    while True:
        href = _yandex_download_href(url, get_json=get_json, token=token)   # свежий каждый раз
        resume_from = part.stat().st_size if part.exists() else 0
        if resume_from:
            pct = f" ({100 * resume_from // size}%)" if size else ""
            print(f"докачиваю с {_gb(resume_from)} ГБ{pct} со свежей ссылки…", flush=True)

        interrupted = False
        try:
            download(href, part, resume_from=resume_from, total=size)
        except (RunError, OSError, httpx.HTTPError) as e:
            interrupted = True
            print(f"\nобрыв связи: {e} — переподключаюсь…", flush=True)

        got = part.stat().st_size if part.exists() else 0
        complete = part.exists() and (got == size if size is not None else not interrupted)
        if complete:
            part.replace(dest)
            print_download_done(got, time.monotonic() - started)
            print(f"скачано → inputs/{dest.name}", flush=True)
            return dest

        # Прогресс есть → сбрасываем счётчик застоя; иначе приближаемся к сдаче.
        if got > resume_from:
            stalls = 0
        else:
            stalls += 1
            if stalls >= max_stalls:
                raise RunError(
                    f"не удалось скачать с Я.Диска: {url} — "
                    f"{max_stalls} попыток подряд без прогресса "
                    f"(ссылка недоступна / жёсткий троттлинг / нет сети)"
                )
        if retry_pause_sec:
            time.sleep(retry_pause_sec)


# ----------------------------------------------------- архив (общий хелпер)

def _archive_video(video: Path, archive_dir: Path) -> None:
    """Переместить видео в inputs-archive/ после успеха. Идемпотентно: уже там → skip."""
    dest = archive_dir / video.name
    if dest.exists():
        return
    if video.exists():
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(video), str(dest))
        print(f"архивирован: {video.name} → {archive_dir}", flush=True)


# ----------------------------------------------------- этапы конвейера `run` (блоки)

def _stage_extract_audio(video, *, render_cfg, cache_dir, ffmpeg, source_sha=None):
    # Прогресс печатает сам extract_audio (живой бар по времени ffmpeg) — здесь без
    # статичной строки, иначе она осталась бы висеть над баром.
    return extract_audio(video, render_cfg.audio_extract, cache_dir,
                         ffmpeg=ffmpeg, source_sha=source_sha)


def _stage_transcribe(audio, *, transcribe_cfg, cache_dir, r0_cfg=None, audio_cfg=None,
                      ffmpeg="ffmpeg", force=False):
    print("транскрипция…" + (" (--force-transcribe)" if force else ""), flush=True)
    backend = get_backend(transcribe_cfg)
    chunking_cfg = r0_cfg.chunking if r0_cfg is not None else None
    return transcribe(
        audio, cache_dir,
        backend=backend,
        language=transcribe_cfg.language,
        chunking_cfg=chunking_cfg,
        audio_cfg=audio_cfg,
        ffmpeg=ffmpeg,
        force=force,
    )


def _stage_compress(transcript, *, r0_cfg):
    print("сжатие транскрипта…", flush=True)
    return compress_transcript(
        transcript, pause_sec=r0_cfg.sentence_pause_sec, max_sentence_sec=r0_cfg.max_sentence_sec
    )


def _stage_select(compressed, *, r0_cfg, root, provider=None):
    """R0-выбор. Returns (reels, dedup_disc, failed_chunks).

    `provider` — заранее собранный пул (cmd_run строит его и валидирует ДО транскрипции);
    если None — собираем здесь (standalone-путь).
    """
    print("выбор моментов…", flush=True)
    root = Path(root) if root is not None else _project_root()
    system_text = (root / r0_cfg.prompts.system).read_text(encoding="utf-8")
    fewshot = json.loads((root / r0_cfg.prompts.fewshot).read_text(encoding="utf-8"))
    if provider is None:
        provider = build_pool(r0_cfg)
    dedup_disc: list[dict] = []
    failed_chunks: list[dict] = []
    reels = select(
        compressed, system_text=system_text, fewshot=fewshot,
        provider=provider, r0_cfg=r0_cfg, _dropped=dedup_disc,
        _failed_chunks=failed_chunks,
    )
    return reels, dedup_disc, failed_chunks


def _write_failed_chunks(failed_chunks: list[dict], manifest_path: Path) -> None:
    if not failed_chunks:
        return
    sidecar = manifest_path.with_suffix("").with_suffix(".failed_chunks.json")
    sidecar.write_text(json.dumps(failed_chunks, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_discarded(discarded: list[dict], manifest_path: Path) -> None:
    if not discarded:
        return
    sidecar = manifest_path.with_suffix("").with_suffix(".discarded.json")
    sidecar.write_text(json.dumps(discarded, ensure_ascii=False, indent=2), encoding="utf-8")


def _stage_snap(reels, transcript, *, r0_cfg):
    """R4: подтянуть границы reel к словам/паузам транскрипта (код, не LLM)."""
    print("подтяжка границ к словам…", flush=True)
    snap_segments(
        reels, transcript.words,
        tail_sec=r0_cfg.tail_sec, window_sec=r0_cfg.snap_window_sec,
        max_duration=r0_cfg.max_duration,
        min_pause_for_phrase_end=r0_cfg.min_pause_for_phrase_end,
        max_micro_pause=r0_cfg.max_micro_pause,
        hanging_words=r0_cfg.hanging_words,
        max_end_search_sec=r0_cfg.max_end_search_sec,
        min_clip_duration=r0_cfg.min_clip_duration,
    )
    return reels


def _stage_padding(reels, transcript, *, r0_cfg):
    """Добавить «воздух» до/после слов клипа (lead_pad_sec / tail_pad_sec)."""
    print("паддинг границ…", flush=True)
    video_duration = transcript.words[-1].t1 if transcript.words else None
    apply_padding(
        reels, transcript.words,
        tail_pad_sec=r0_cfg.tail_pad_sec,
        lead_pad_sec=r0_cfg.lead_pad_sec,
        max_duration=r0_cfg.max_duration,
        video_duration=video_duration,
        hanging_words=r0_cfg.hanging_words,
    )
    return reels


def _stage_trim(reels, transcript, *, r0_cfg):
    """Политика too_long: trim/drop/keep сегменты длиннее max_duration (код, не LLM)."""
    policy = getattr(r0_cfg, "too_long_policy", "keep")
    if policy == "keep":
        return reels
    n_before = len(reels)
    trim_too_long(
        reels, transcript.words,
        max_duration=r0_cfg.max_duration,
        pause_sec=r0_cfg.sentence_pause_sec,
        policy=policy,
    )
    n_after = len(reels)
    if policy == "drop" and n_after < n_before:
        print(f"too_long drop: убрано {n_before - n_after} сегментов", flush=True)
    elif policy == "trim":
        trimmed = sum(1 for r in reels if "too_long" not in r.flags)
        print(f"too_long trim: обрезано по паузе", flush=True)
    return reels


def _stage_min_clip_filter(reels, transcript, *, r0_cfg) -> tuple[list, list[dict]]:
    """Пост-snap: убрать клипы короче min_clip_duration, попытавшись расширить до фразы.

    Для каждого короткого клипа:
      1. Диагностирует причину (R0 вернул коротко / snap схлопнул).
      2. Пробует расширить конец до ближайшей границы мысли (try_rescue_clip).
      3. Если расширение даёт >= min_clip_duration → клип спасён (остаётся).
      4. Иначе → отброшен, причина логируется в sidecar.

    Returns (kept_reels, discarded_entries).
    """
    from autoreels.local.subtitles import words_in_window
    min_dur = r0_cfg.min_clip_duration
    words = transcript.words
    kept: list = []
    disc: list[dict] = []

    for r in reels:
        if r.end - r.start >= min_dur or "human_merged" in r.flags:
            kept.append(r)
            continue

        before_rescue_end = r.end
        reason = diagnose_collapse(r)

        rescued = try_rescue_clip(
            r, words,
            min_duration=min_dur,
            max_duration=r0_cfg.max_duration,
            min_pause=r0_cfg.min_pause_for_phrase_end,
            max_micro_pause=r0_cfg.max_micro_pause,
            hanging_words=r0_cfg.hanging_words,
        )
        if rescued:
            print(
                f"  ↑ {r.id}: расширен {before_rescue_end - r.start:.1f}с → "
                f"{r.end - r.start:.1f}с ({reason})",
                flush=True,
            )
            kept.append(r)
        else:
            print(f"  ✗ {r.id}: отброшен — {reason}", flush=True)
            cw = words_in_window(words, r.start, r.end)
            first_8 = " ".join(w.word for w in cw[:8])
            disc.append({"id": r.id, "score": r.score, "reason": f"too_short: {reason}", "first_words": first_8})

    if disc:
        print(f"min_clip_filter: отброшено {len(disc)} коротких клипов", flush=True)

    return kept, disc


def _stage_meaningful_sec_recheck(reels, transcript, *, r0_cfg) -> tuple[list, list[dict]]:
    """Re-apply min_meaningful_sec floor after snap+padding; also recomputes too_long/too_short.

    snap() may shorten a clip that passed the pre-snap 18s filter down to 8-17s. _stage_min_clip_filter
    only guards the 8s floor, so clips between 8s and 18s slip through. This catches them.
    Also clears stale R0-boundary flags and re-sets them from final boundaries.
    """
    floor = r0_cfg.min_meaningful_sec
    kept = []
    disc = []
    for r in reels:
        if "human_merged" in r.flags:
            kept.append(r)
            continue
        dur = r.end - r.start
        if dur < floor:
            r0_dur = (r.r0_end - r.r0_start) if r.r0_start is not None else None
            if r0_dur is not None:
                reason = f"too_short_after_snap: R0={r0_dur:.1f}s → final={dur:.1f}s < {floor:.0f}s"
            else:
                reason = f"too_short_after_snap: {dur:.1f}s < {floor:.0f}s floor"
            cw = words_in_window(transcript.words, r.start, r.end)
            first_8 = " ".join(w.word for w in cw[:8])
            disc.append({"id": r.id, "score": r.score, "reason": reason, "first_words": first_8})
        else:
            kept.append(r)
    if disc:
        print(f"meaningful_sec_recheck: снято {len(disc)} (snap < {floor:.0f}s)", flush=True)
    # Recompute too_long/too_short from final boundaries (R0-era flags are stale post-snap).
    for r in kept:
        r.flags = [f for f in r.flags if f not in (FLAG_TOO_LONG, FLAG_TOO_SHORT)]
    flag_durations(kept, min_duration=r0_cfg.min_duration, max_duration=r0_cfg.max_duration)
    return kept, disc


def _stage_speech_density(reels, transcript, *, r0_cfg) -> tuple[list, list[dict]]:
    """Fix 1: плотность речи на ГОТОВОМ клипе (после всех границ), ДО субтитров.

    Клип ниже final_speech_density_min: сперва пробуем срезать по единой длинной паузе
    (≥ speech_density_split_gap_sec) и оставить более длинную половину, если та укладывается
    в [min_clip_duration, max_duration]. Не вышло → снять с причиной low_speech_density в sidecar.
    Плотность каждого клипа печатается ДО и ПОСЛЕ — эффект виден. Применяется и к human_merged:
    r08 (ручная выборка) — ровно тот клип, что надо чинить.
    Returns (kept, discarded).
    """
    from autoreels.cloud.snap import clip_speech_density, split_clip_at_largest_gap
    from autoreels.local.subtitles import words_in_window

    floor = getattr(r0_cfg, "final_speech_density_min", 0.0)
    words = getattr(transcript, "words", None)
    if floor <= 0 or not words:
        return reels, []

    gap = r0_cfg.speech_density_split_gap_sec
    kept: list = []
    disc: list[dict] = []
    print(f"плотность речи финальных клипов (порог {floor:.0%}, срез по паузе ≥{gap:.0f}с):", flush=True)
    for r in reels:
        d0 = clip_speech_density(r.start, r.end, words)
        if d0 >= floor:
            print(f"  · {r.id}: {d0:.0%} ({r.end - r.start:.1f}с) — ок", flush=True)
            kept.append(r)
            continue
        split = split_clip_at_largest_gap(
            r.start, r.end, words,
            min_gap=gap, min_duration=r0_cfg.min_clip_duration, max_duration=r0_cfg.max_duration,
        )
        if split is not None:
            old_dur = r.end - r.start
            r.start, r.end = split
            d1 = clip_speech_density(r.start, r.end, words)
            r.end_snap_reason = "split_low_density"
            print(f"  ✂ {r.id}: {d0:.0%} ({old_dur:.1f}с) → срез по паузе → "
                  f"{d1:.0%} ({r.end - r.start:.1f}с)", flush=True)
            kept.append(r)
        else:
            cw = words_in_window(words, r.start, r.end)
            first_8 = " ".join(w.word for w in cw[:8])
            print(f"  ✗ {r.id}: {d0:.0%} ({r.end - r.start:.1f}с) — единой паузы ≥{gap:.0f}с нет → снят",
                  flush=True)
            disc.append({"id": r.id, "score": r.score,
                         "reason": f"low_speech_density: {d0:.2f} < {floor:.2f}",
                         "first_words": first_8})
    if disc:
        print(f"speech_density: снято {len(disc)} клип(ов) с низкой плотностью речи", flush=True)
    return kept, disc


def _stage_subtitles(reels, transcript):
    """R3: привязать word-level транскрипта к каждому reel."""
    print("субтитры: привязка слов к сегментам…", flush=True)
    for reel in reels:
        reel.subtitles = words_in_window(transcript.words, reel.start, reel.end)
    return reels


def _assemble_manifest(video, reels, *, sha, setup, duration_preset, source_kind="",
                       transcript_params_key=""):
    """Собрать манифест: кроп/setup_id — из калибровки (setup), source_sha256 — от файла.

    transcript_params_key — отпечаток транскрипта, на котором собран манифест: даёт
    resnap/diagnose найти ТОТ ЖЕ транскрипт, а не «сироту» без params_key."""
    return Manifest(
        source=Path(video).name,
        source_path=str(Path(video).resolve()),   # абсолютный путь, откуда читали (in-place — реальное место)
        source_sha256=sha,
        source_hash_scheme="partial-p1",
        duration_preset=duration_preset,
        setup=setup,
        run_key=_run_key(sha, duration_preset),
        reels=reels,
        source_kind=source_kind,
        transcript_params_key=transcript_params_key,
    )


def _write_manifest(manifest, manifests_dir) -> Path:
    """Записать манифест как manifests/<stem>.json (имя по видео, batch-совместимость)."""
    manifests_dir = Path(manifests_dir)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(manifest.source).stem
    path = manifests_dir / f"{stem}.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


# ----------------------------------------------------------- авто-коммит манифеста (per-video)

def _git_flag(specific_env: str) -> bool:
    """Флаг git-действия: AUTOREELS_GIT_<PULL|PUSH> (специфичный) > AUTOREELS_GIT_SYNC (общий) >
    дефолт (вкл). Позволяет разделить чтение и запись: на системнике (только рендер) удобно
    PUSH=0 (push упирается в аутентификацию и мешает), PULL=1 (тянуть свежие манифесты)."""
    v = os.environ.get(specific_env)
    if v == "1":
        return True
    if v == "0":
        return False
    s = os.environ.get("AUTOREELS_GIT_SYNC")   # общий рубильник (обратная совместимость)
    if s == "1":
        return True
    if s == "0":
        return False
    return True


def _should_git_pull() -> bool:
    """Тянуть ли свежие манифесты/калибровки перед работой (AUTOREELS_GIT_PULL, дефолт вкл)."""
    return _git_flag("AUTOREELS_GIT_PULL")


def _should_git_push() -> bool:
    """Пушить ли свои изменения (AUTOREELS_GIT_PUSH, дефолт вкл). На системнике удобно =0."""
    return _git_flag("AUTOREELS_GIT_PUSH")


def _git_pull(root, *, what: str = "свежие данные") -> None:
    """git pull --ff-only ПЕРЕД работой (подтянуть калибровки/манифесты с другой машины).

    Не роняет команду при ошибке (нет сети/конфликт/нет remote) — предупреждаем и работаем с
    локальными файлами. Точка синхронизации: run на Mac тянет калибровки, render — манифесты."""
    if not _should_git_pull():
        return
    import subprocess
    root = Path(root) if root is not None else _project_root()
    try:
        pull = _run_git(["pull", "--ff-only"], root=root, timeout=180)
    except subprocess.TimeoutExpired:
        print("  ⚠ git pull завис (таймаут) — работаю с локальными файлами",
              file=sys.stderr, flush=True)
        return
    except OSError as e:
        print(f"  ⚠ git недоступен: {e} — работаю с локальными файлами",
              file=sys.stderr, flush=True)
        return
    if pull.returncode != 0:
        detail = " ".join((pull.stderr or "").split())[:160] or "(без деталей)"
        print(f"  ⚠ git pull не прошёл ({what}): {detail} — работаю с локальными файлами",
              file=sys.stderr, flush=True)
        return
    combined = f"{pull.stdout}{pull.stderr}".lower()
    if "up to date" in combined or "актуальн" in combined:
        print(f"  ✓ git pull: уже актуально ({what})", flush=True)
    else:
        print(f"  ✓ git pull: подтянул {what}", flush=True)


def _run_git(args, *, root, timeout=None):
    """Запустить git в репозитории `root` НЕинтерактивно (не зависать на вводе).

    GIT_TERMINAL_PROMPT=0 — не спрашивать логин/пароль (сразу ошибка вместо ожидания ввода).
    GIT_SSH_COMMAND=…BatchMode=yes — ssh падает, а не ждёт ввода passphrase (иначе push висит).
    ConnectTimeout — не висеть на недоступном хосте; `timeout` — жёсткий потолок на весь вызов.
    """
    import subprocess
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=10")
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, env=env, timeout=timeout,
    )


def _pull_rebase_before_push(root, *, what: str) -> str | None:
    """Перед push влить удалённые изменения через `pull --rebase --autostash` — не плодя merge.

    Обе машины пишут в manifests/calibrations, поэтому «слепой» push после чужого коммита
    отвергается (non-fast-forward). Rebase перекладывает локальные коммиты поверх удалённых.
    Возврат:
    - None → можно пушить: rebase прошёл, ЛИБО транзиентная ошибка (нет сети/upstream) — тогда
      push сам сообщит свою ошибку, не блокируем здесь;
    - СТРОКА → конфликт в общих файлах (изменены и тут, и на другой машине): rebase ОТМЕНЁН
      (`--abort`, рабочее дерево чистое, локальные коммиты целы), push НЕ делается, строка —
      внятная инструкция человеку (а не сырой вывод git)."""
    import subprocess
    try:
        rb = _run_git(["pull", "--rebase", "--autostash"], root=root, timeout=180)
    except (subprocess.TimeoutExpired, OSError):
        return None   # транзиентно — пусть push попробует и сам разберётся
    if rb.returncode == 0:
        return None
    combined = f"{rb.stdout}\n{rb.stderr}".lower()
    if "conflict" not in combined:
        return None   # не конфликт (нет upstream/сети/rebase невозможен) — push сам сообщит
    # Конфликт: откатываем rebase, чтобы дерево осталось чистым (локальные коммиты на месте).
    try:
        _run_git(["rebase", "--abort"], root=root, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return (
        f"git-конфликт при синхронизации ({what}): файл изменён и здесь, и на другой машине. "
        f"Rebase отменён — рабочее дерево чистое, локальные изменения целы. Разреши вручную: "
        f"git pull --rebase → устрани конфликт → git push. Подсказка: манифест после сборки "
        f"иммутабелен, автокроп в calibrations/ не хранится — при сомнении бери версию машины "
        f"анализа (где шёл arl run/calibrate)."
    )


def _commit_push_manifest(manifest_path, n_reels: int, *, root, calibration_path=None) -> None:
    """Закоммитить и запушить манифест (+ калибровку кропа этого видео) сразу после видео.

    Per-video (не в конце пачки): упади прогон на следующем видео — уже готовые манифесты
    УЖЕ на системнике. Калибровка кропа коммитится вместе с манифестом, чтобы уехать на
    системник (status там видит кроп; calibrations/ теперь версионируются). Ошибка git
    (нет сети, конфликт, passphrase) НЕ роняет прогон: предупреждаем и продолжаем.
    """
    if not _should_git_push():
        return   # push выключен (напр. системник: только рендер, PUSH=0) — манифест уже локально
    import subprocess
    root = Path(root) if root is not None else _project_root()
    manifest_path = Path(manifest_path)
    stem = manifest_path.stem
    paths = [str(manifest_path)]
    if calibration_path is not None and Path(calibration_path).is_file():
        paths.append(str(calibration_path))

    def _warn(reason: str) -> None:
        detail = " ".join(reason.split())[:200] or "(без деталей)"
        print(
            f"  ⚠ манифест {stem} сохранён локально, git-push не прошёл: {detail} — "
            f"запушь вручную (git push)",
            file=sys.stderr, flush=True,
        )

    try:
        add = _run_git(["add", "--", *paths], root=root)
        if add.returncode != 0:
            _warn(add.stderr)
            return
        commit = _run_git(
            ["commit", "-m", f"manifest: {stem} ({n_reels} reels)", "--", *paths],
            root=root,
        )
        nothing_new = "nothing to commit" in f"{commit.stdout}{commit.stderr}".lower()
        if commit.returncode != 0 and not nothing_new:
            _warn(f"{commit.stdout} {commit.stderr}")
            return
        # Перед push влить удалённое через rebase (обе машины пишут в manifests → чужой коммит
        # отверг бы наш push). Конфликт → внятная инструкция, дерево остаётся чистым.
        conflict = _pull_rebase_before_push(root, what=f"манифест {stem}")
        if conflict:
            print(f"  ⚠ {conflict}", file=sys.stderr, flush=True)
            return
        # Пушим даже при nothing-to-commit: вдруг прошлый push не прошёл, локаль впереди remote.
        push = _run_git(["push"], root=root, timeout=180)
        if push.returncode != 0:
            _warn(push.stderr)
            return
        if not nothing_new:
            print(f"  ✓ манифест {stem} запушен ({n_reels} reels) → на системнике: arl r",
                  flush=True)
    except subprocess.TimeoutExpired:
        _warn("git завис (таймаут) — проверь сеть/доступ к remote или SSH-passphrase")
    except OSError as e:
        _warn(f"git недоступен: {e}")


def _commit_push_calibrations(*, root) -> None:
    """Синхронизировать калибровки кропа в git: add calibrations/ → commit → push.

    Калибруешь на Mac (arl c / меню) → калибровки уезжают на системник (там arl r = git pull),
    и status видит ручной кроп. _work/ (кадры-PNG) в .gitignore и не попадают. Ошибка git не
    роняет команду — калибровки уже на диске, предупреждаем и продолжаем."""
    if not _should_git_push():
        return   # push выключен (PUSH=0/SYNC=0) — калибровки уже на диске, не пушим
    import subprocess
    root = Path(root) if root is not None else _project_root()
    if not (root / "calibrations").is_dir():
        return

    def _warn(reason: str) -> None:
        detail = " ".join(reason.split())[:200] or "(без деталей)"
        print(
            f"  ⚠ калибровки сохранены локально, git-push не прошёл: {detail} — "
            f"запушь вручную (git push)",
            file=sys.stderr, flush=True,
        )

    try:
        add = _run_git(["add", "--", "calibrations"], root=root)
        if add.returncode != 0:
            _warn(add.stderr)
            return
        commit = _run_git(
            ["commit", "-m", "calibrations: sync crop settings", "--", "calibrations"], root=root
        )
        nothing_new = "nothing to commit" in f"{commit.stdout}{commit.stderr}".lower()
        if commit.returncode != 0 and not nothing_new:
            _warn(f"{commit.stdout} {commit.stderr}")
            return
        conflict = _pull_rebase_before_push(root, what="калибровки")
        if conflict:
            print(f"  ⚠ {conflict}", file=sys.stderr, flush=True)
            return
        push = _run_git(["push"], root=root, timeout=180)
        if push.returncode != 0:
            _warn(push.stderr)
            return
        if not nothing_new:
            print("  ✓ калибровка сохранена и отправлена → на Mac: arl run "
                  "(подтянет калибровки и построит манифесты)", flush=True)
    except subprocess.TimeoutExpired:
        _warn("git завис (таймаут) — проверь сеть/доступ к remote или SSH-passphrase")
    except OSError as e:
        _warn(f"git недоступен: {e}")


# ------------------------------------------------------------- разрешение пути к ffmpeg

def _ffmpeg_candidates() -> list[str]:
    """Типичные места ffmpeg вне PATH. Windows-пути безвредны на Unix (is_file→False) и
    наоборот — порядок зависит от ОС (сначала «родные» пути машины)."""
    win = [r"D:\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe",
           r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]
    unix = ["/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/bin/ffmpeg"]
    return (win + unix) if os.name == "nt" else (unix + win)


@dataclass
class ToolResolution:
    """Как разрешён внешний бинарь (ffmpeg/ffprobe) — ЕДИНЫЙ результат для рантайма и doctor.

    `path` — что реально запускать (абсолютный путь или голое имя). `source` — откуда взят:
    flag | binary_env (FFMPEG_BINARY/FFPROBE_BINARY) | render_env (RENDER_*) | config | path |
    candidate (автопоиск типичных мест) | sibling (сосед ffmpeg) | default. `in_path` — резолвится
    ли ГОЛОЕ имя через PATH. Ключ к честности doctor: если path задан явно ИЛИ in_path — запуск
    надёжен; если найден автопоиском (candidate/sibling) при in_path=False — хрупко (не «✓»)."""
    name: str          # "ffmpeg" | "ffprobe"
    path: str          # что запускать
    source: str        # flag | binary_env | render_env | config | path | candidate | sibling | default
    in_path: bool      # разрешается ли голое имя через PATH


def resolve_ffmpeg_ex(cli_flag=None, *, render_cfg, which=None, candidates=None, is_file=None) -> ToolResolution:
    """ЕДИНЫЙ резолвер ffmpeg (рантайм и doctor зовут его — не могут разойтись). Приоритет:
    флаг > FFMPEG_BINARY > RENDER_FFMPEG > render.local.yaml/render.yaml (config) > PATH > автопоиск.

    FFMPEG_BINARY — абсолютный путь к бинарю: устойчивее к обновлениям Windows, после которых
    PATH теряется. Возвращает ToolResolution (path + откуда + есть ли в PATH) — doctor по нему
    решает «✓» (явно/в PATH) или «⚠» (нашли автопоиском, но в PATH нет → хрупко)."""
    which = which if which is not None else shutil.which
    is_file = is_file if is_file is not None else (lambda p: Path(str(p)).is_file())
    candidates = candidates if candidates is not None else _ffmpeg_candidates()
    in_path = which("ffmpeg") is not None

    if cli_flag:
        return ToolResolution("ffmpeg", cli_flag, "flag", in_path)
    if os.environ.get("FFMPEG_BINARY"):
        return ToolResolution("ffmpeg", os.environ["FFMPEG_BINARY"], "binary_env", in_path)
    if os.environ.get("RENDER_FFMPEG"):
        return ToolResolution("ffmpeg", os.environ["RENDER_FFMPEG"], "render_env", in_path)
    config_value = getattr(render_cfg, "ffmpeg", "ffmpeg")
    if config_value and config_value != "ffmpeg":
        return ToolResolution("ffmpeg", config_value, "config", in_path)
    if in_path:
        return ToolResolution("ffmpeg", "ffmpeg", "path", True)
    for cand in candidates:
        if is_file(cand):
            return ToolResolution("ffmpeg", cand, "candidate", False)
    searched = ["ffmpeg (в PATH)"] + list(candidates)
    raise FFmpegNotFoundError(
        "ffmpeg не найден. Искал: " + ", ".join(searched) + ".\n"
        "Задай путь одним из способов (приоритет сверху вниз):\n"
        "  • флаг:  --ffmpeg D:\\ffmpeg\\bin\\ffmpeg.exe\n"
        "  • env:   FFMPEG_BINARY=D:\\ffmpeg\\bin\\ffmpeg.exe  (устойчиво к потере PATH)\n"
        "  • файл:  config/render.local.yaml → ffmpeg: D:\\ffmpeg\\bin\\ffmpeg.exe\n"
        "или установи ffmpeg в PATH."
    )


def resolve_ffmpeg(cli_flag=None, *, render_cfg, which=None, candidates=None, is_file=None) -> str:
    """Путь к ffmpeg (тонкая обёртка над resolve_ffmpeg_ex — для вызывающих, которым нужен только путь)."""
    return resolve_ffmpeg_ex(
        cli_flag, render_cfg=render_cfg, which=which, candidates=candidates, is_file=is_file
    ).path


def resolve_ffprobe_ex(cli_flag=None, *, ffmpeg=None, which=None, is_file=None) -> ToolResolution:
    """ЕДИНЫЙ резолвер ffprobe. Приоритет: флаг > FFPROBE_BINARY > RENDER_FFPROBE > PATH >
    сосед резолвнутого ffmpeg > голое «ffprobe». Возвращает ToolResolution (для honest-doctor)."""
    which = which if which is not None else shutil.which
    is_file = is_file if is_file is not None else (lambda p: Path(str(p)).is_file())
    in_path = which("ffprobe") is not None

    if cli_flag:
        return ToolResolution("ffprobe", cli_flag, "flag", in_path)
    if os.environ.get("FFPROBE_BINARY"):
        return ToolResolution("ffprobe", os.environ["FFPROBE_BINARY"], "binary_env", in_path)
    if os.environ.get("RENDER_FFPROBE"):
        return ToolResolution("ffprobe", os.environ["RENDER_FFPROBE"], "render_env", in_path)
    if in_path:
        return ToolResolution("ffprobe", "ffprobe", "path", True)
    if ffmpeg and (("/" in ffmpeg) or ("\\" in ffmpeg)):
        sibling = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
        if is_file(sibling):
            return ToolResolution("ffprobe", str(sibling), "sibling", False)
    return ToolResolution("ffprobe", "ffprobe", "default", False)


def resolve_ffprobe(cli_flag=None, *, ffmpeg=None, which=None, is_file=None) -> str:
    """Путь к ffprobe (тонкая обёртка над resolve_ffprobe_ex)."""
    return resolve_ffprobe_ex(cli_flag, ffmpeg=ffmpeg, which=which, is_file=is_file).path


def _preflight_tools(ffmpeg: str, ffprobe: str, *, which=None) -> None:
    """Проверить, что ffmpeg И ffprobe СУЩЕСТВУЮТ (в PATH или по заданному пути) — ДО тяжёлой
    работы (хэш гигабайтных файлов). Иначе пайплайн падает сырым «[WinError 2] Не удаётся найти
    указанный файл» глубоко внутри (после того как впустую прочитаны десятки ГБ), и непонятно,
    что не найдено — пользователь думает на видеофайл, а на деле нет утилиты в PATH.

    Не найдено → FFmpegNotFoundError с ИМЕНЕМ утилиты и подсказкой `arl doctor` (main ловит её
    в _KNOWN_ERRORS и печатает чистое сообщение). Точка подмены `which` — для тестов."""
    which = which if which is not None else shutil.which
    for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        if which(path) is None:
            raise FFmpegNotFoundError(
                f"{name} не найден (искал '{path}' в PATH) — установи {name} или добавь в PATH. "
                f"Проверь окружение: arl doctor"
            )


def _project_root() -> Path:
    """Корень репозитория (где config/render.local.yaml, aliases.sh) — по расположению пакета.
    Команды находят машинный конфиг ffmpeg независимо от cwd: после autoload `arl` (и любой
    CLI-вызов) стартует из ПРОИЗВОЛЬНОЙ директории, а render.local.yaml лежит в проекте."""
    return Path(__file__).resolve().parents[2]


def _cli_resolve_ffmpeg_ex(flag, *, root=None) -> ToolResolution:
    """ToolResolution для ffmpeg в CLI-командах (run/transcribe/calibrate/doctor), которые сами
    render_cfg не грузят. ЕДИНАЯ точка резолва: и рантайм, и doctor зовут её → не разъезжаются.

    Конфиг (render.yaml + машинный render.local.yaml) читается из КОРНЯ ПРОЕКТА, а не из cwd —
    иначе после autoload (`arl` из любой папки) render.local.yaml с путём ffmpeg не находился,
    и резолв падал в 'ffmpeg' → [WinError 2] на извлечении аудио. Пробуем root (если задан явно),
    затем корень проекта; если ни там ни там — дефолт (резолв учтёт флаг/env/PATH/автопоиск)."""
    from types import SimpleNamespace
    tried = []
    if root is not None and str(root) != ".":
        tried.append(Path(root))
    tried.append(_project_root())
    for base in tried:
        try:
            return resolve_ffmpeg_ex(flag, render_cfg=load_render_config(base / "config" / "render.yaml"))
        except (ConfigError, OSError):
            continue
    return resolve_ffmpeg_ex(flag, render_cfg=SimpleNamespace(ffmpeg="ffmpeg"))


def _cli_resolve_ffmpeg(flag, *, root=None) -> str:
    """Путь к ffmpeg для CLI-команд (обёртка над _cli_resolve_ffmpeg_ex — где нужен только путь)."""
    return _cli_resolve_ffmpeg_ex(flag, root=root).path


# ------------------------------------------------------------------------- команды

def _should_auto_render(render_cfg, *, failed_chunks: list) -> tuple[bool, str]:
    """Returns (ok, skip_reason). skip_reason empty when ok=True."""
    if render_cfg.role == "analyze":
        return False, "role=analyze запрещает рендер на этой машине"
    if failed_chunks:
        return False, f"провалилось {len(failed_chunks)} чанков — рендер пропущен"
    return True, ""


def cmd_run(
    video,
    *,
    root=None,
    calibrations_dir=None,
    manifests_dir=None,
    cache_dir=None,
    archive_dir=None,
    transcripts_dir=None,
    ffmpeg: str = "ffmpeg",
    push: bool = False,
    pull_first: bool = True,
    force: bool = False,
    force_transcribe: bool = False,
    auto_render: bool = False,
    archive: bool = True,
    history_path=None,
    _render_queue=None,
) -> Path:
    """Обёртка над `_cmd_run_impl`, дописывающая КАЖДЫЙ прогон в историю (core.history).

    История пишется на любом исходе — ok / zero-harvest / failed / skipped — включая ранний
    краш (до манифеста: sha ещё не посчитан, пишем пустой). Пропуски-дедупы (AlreadyProcessed)
    и отказ над ручным манифестом (ManualManifest) в историю НЕ пишутся: это «ничего не делали,
    и правильно», а не событие прогона. Детали успеха (рилы, selection) читаются из записанного
    манифеста — он и есть источник истины.
    """
    root = Path(root) if root is not None else _project_root()
    hist_path = history.resolve_path(history_path, root)
    manifests_dir_r = Path(manifests_dir) if manifests_dir else root / "manifests"
    t0 = time.monotonic()
    outcome = "ok"
    sha = ""
    reels = 0
    selection = "auto"
    manifest_out = ""
    record = True

    def _from_manifest(mf: Path) -> None:
        nonlocal sha, reels, selection, manifest_out
        if mf.is_file():
            manifest_out = str(mf)
            try:
                m = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
                sha, reels, selection = m.source_sha256, len(m.reels), (m.selection_source or "auto")
            except Exception:  # noqa: BLE001 — детали для истории не критичны
                pass

    try:
        path = _cmd_run_impl(
            video, root=root, calibrations_dir=calibrations_dir, manifests_dir=manifests_dir,
            cache_dir=cache_dir, archive_dir=archive_dir, transcripts_dir=transcripts_dir,
            ffmpeg=ffmpeg, push=push, pull_first=pull_first, force=force,
            force_transcribe=force_transcribe, auto_render=auto_render, archive=archive,
            _render_queue=_render_queue,
        )
        outcome = "ok"
        _from_manifest(path)
        return path
    except (AlreadyProcessedError, ManualManifestError):
        record = False
        raise
    except InputInvalid:
        outcome = "skipped"
        raise
    except ZeroHarvestError:
        outcome = "zero-harvest"
        _from_manifest(manifests_dir_r / f"{Path(video).stem}.json")  # манифест уже записан до raise
        raise
    except Exception:
        outcome = "failed"
        raise
    finally:
        if record:
            history.append_run(
                hist_path, source=Path(video).name, source_path=str(Path(video).resolve()),
                sha256=sha, duration_sec=time.monotonic() - t0, outcome=outcome,
                reel_count=reels, selection_source=selection, manifest_path=manifest_out,
            )


def _cmd_run_impl(
    video,
    *,
    root=None,
    calibrations_dir=None,
    manifests_dir=None,
    cache_dir=None,
    archive_dir=None,
    transcripts_dir=None,
    ffmpeg: str = "ffmpeg",
    push: bool = False,
    pull_first: bool = True,
    force: bool = False,
    force_transcribe: bool = False,
    auto_render: bool = False,
    archive: bool = True,
    _render_queue=None,
) -> Path:
    """ОБЛАЧНЫЙ тир: одно видео → manifests/<stem>.json (+ архив источника, если archive=True).

    `push=True` → сразу закоммитить+запушить манифест (per-video sync на системник);
    ошибка git не роняет прогон. По умолчанию False (git не трогается).
    `pull_first=True` → git pull ПЕРЕД стартом (подтянуть свежие калибровки с системника,
    чтобы не строить манифест на старом кропе). Batch тянет один раз и зовёт с pull_first=False.
    `archive=True` → после успеха видео уходит в inputs-archive/ (поток inputs/). Для in-place
    источников (файл дан путём вне inputs/) вызывающий ставит archive=False — файл не двигается.

    Кроп per-file: берётся из `calibrations/<sha256>.json` (пишет `autoreels calibrate`).
    Нет калибровки → авто-кроп по центру (9:16, полная высота) с сообщением.
    Попутно (без доп. работы) сохраняет текст транскрипта в transcripts/<stem>.txt —
    он уже посчитан для R0, отдельный `transcribe` на то же видео не нужен.
    """
    root = Path(root) if root is not None else _project_root()
    if pull_first:
        _git_pull(root, what="калибровки")     # свежие ручные калибровки с системника
    cfg = root / "config"
    render_cfg = load_render_config(cfg / "render.yaml")
    r0_cfg = load_r0_config(cfg / "r0.yaml")
    transcribe_cfg = load_transcribe_config(cfg / "transcribe.yaml")
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    archive_dir = Path(archive_dir) if archive_dir else root / "inputs-archive"
    transcripts_dir = Path(transcripts_dir) if transcripts_dir else root / "transcripts"

    # ПОРЯДОК ПРОВЕРОК: окружение → файл → тяжёлая работа. Сначала преflight утилит: ffmpeg и
    # ffprobe должны СУЩЕСТВОВАТЬ ДО того, как посчитан хэш 14-гигабайтного файла (иначе на пачке
    # впустую читаются десятки ГБ, прежде чем всплывёт «нет ffmpeg»). Внятная FFmpegNotFoundError
    # с именем утилиты — вместо сырого WinError 2 из глубины extract_audio.
    ffprobe = resolve_ffprobe(None, ffmpeg=ffmpeg)
    _preflight_tools(ffmpeg, ffprobe)
    # Затем валидация ФАЙЛА — до хэша/калибровки/аудио. Битый/пустой/недокачанный ловим сразу
    # (InputInvalid), не тратя sha по гигабайтам. Наверх летит InputInvalid — batch отнесёт его к
    # «пропущено» (SKIPPED), а не «ошибка».
    validate_input(Path(video), ffprobe=ffprobe)

    size_gb = Path(video).stat().st_size / (1 << 30)
    print(f"считаю хэш видео ({size_gb:.1f} ГБ)…", flush=True)
    sha = state.file_sha256_cached_fast(video, cache_dir)
    print("хэш готов.", flush=True)
    # Гард ДО дорогой работы (калибровка/аудио/Whisper/R0): уже обработан по run_key →
    # пропуск; ручную выборку (selection_source=human) авто-прогон не стирает без --force.
    _guard_already_processed(video, sha, r0_cfg.duration_preset, manifests_dir, force=force)
    setup = load_or_auto_calibrate(
        calibrations_dir, sha, Path(video).name,
        get_frame_size=lambda: _probe_frame_size_for_auto(video, ffprobe=ffprobe),
    )

    # Жёсткая валидация при сборке манифеста: кроп проверяется против ОТОБРАЖАЕМЫХ (display,
    # после rotation-метаданных) размеров кадра — ровно то пространство, в котором рендер
    # применит crop-фильтр (autorotate по умолчанию). Приводим к ОДНОМУ пространству перед
    # сравнением: и калибровка (rotation_applied=true), и probe — отображаемые размеры.
    disp_w, disp_h = _probe_frame_size_for_auto(video, ffprobe=ffprobe)
    c = setup.crop
    print(f"отображаемый кадр видео (после rotation): {disp_w}×{disp_h}; "
          f"кроп калибровки: {c.w}×{c.h}@{c.x},{c.y} в кадре {setup.frame}", flush=True)
    try:
        validate_crop_in_frame(setup.crop, disp_w, disp_h)
    except CalibrationError as e:
        # Рассинхрон пространств. Если записанный в калибровке кадр совпадает с ПЕРЕВЁРНУТЫМ
        # отображаемым — калибровка и rotation детектились по-разному (калибратор/рендер vs run).
        cal_frame = tuple(setup.frame) if setup.frame else None
        swapped = cal_frame == (disp_h, disp_w)
        hint = ("  калибровка в ПЕРЕВЁРНУТОМ пространстве относительно рендера "
                f"(кадр калибровки {cal_frame} = swap отображаемого {disp_w}×{disp_h}).\n"
                if swapped else "")
        raise CalibrationError(
            f"калибровка не годится для этого видео: {e}\n"
            f"{hint}"
            f"  калибровка: кроп {c.w}×{c.h}@{c.x},{c.y}, кадр {setup.frame}\n"
            f"  видео сейчас: отображаемый кадр {disp_w}×{disp_h}\n"
            f"  → перекалибруй это видео (autoreels calibrate). Автокроп НЕ подставляю."
        ) from e
    print(f"калибровка валидна в отображаемом пространстве ✓ (setup={setup.setup_id})", flush=True)

    print(f"=== run: {Path(video).name} (setup={setup.setup_id}) ===", flush=True)
    # Пул провайдеров + префлайт моделей ДО дорогой транскрипции: неверная model/
    # openrouter_model отсеивается сразу, а не 404-ом на 2-м R0-чанке после Whisper.
    provider = build_pool(r0_cfg)
    provider.preflight()
    from autoreels.core import memtrace
    memtrace.mark("run start")
    audio = _stage_extract_audio(video, render_cfg=render_cfg, cache_dir=cache_dir,
                                 ffmpeg=ffmpeg, source_sha=sha)
    memtrace.mark("after extract_audio")
    transcript = _stage_transcribe(
        audio, transcribe_cfg=transcribe_cfg, cache_dir=cache_dir,
        r0_cfg=r0_cfg, audio_cfg=render_cfg.audio_extract, ffmpeg=ffmpeg,
        force=force_transcribe,
    )
    memtrace.mark("after transcribe")
    # Попутно: сохранить читаемый текст для контента (транскрипт уже есть — R0 его считал).
    tx_path = _write_transcript_file(
        transcript, stem=Path(video).stem, fmt="text", out_dir=transcripts_dir, r0_cfg=r0_cfg
    )
    print(f"транскрипт для контента → {tx_path}", flush=True)
    compressed = _stage_compress(transcript, r0_cfg=r0_cfg)
    memtrace.mark("after compress")
    reels, dedup_disc, failed_chunks = _stage_select(compressed, r0_cfg=r0_cfg, root=root, provider=provider)
    memtrace.mark("after select (R0)")
    for r in reels:                        # сохранить R0-границы ДО snap → для resnap без LLM
        r.r0_start, r.r0_end = r.start, r.end
    reels = _stage_snap(reels, transcript, r0_cfg=r0_cfg)
    memtrace.mark("after snap")
    tx_words = getattr(transcript, "words", [])
    dangling_disc: list = []
    # Interview: enforce host-turn clip boundaries.
    host_turns = (
        detect_host_turns(tx_words)
        if getattr(r0_cfg, "source_kind", "lecture") == "interview"
        else []
    )
    if host_turns:
        reels, interview_disc = _stage_interview_snap(reels, host_turns, tx_words=tx_words, r0_cfg=r0_cfg)
        n_host_cut = sum(1 for r in reels if r.end_snap_reason == "before_host_turn")
        n_host_start = sum(1 for r in reels if r.start_snap_reason == "host_question_included")
        if n_host_cut or n_host_start or interview_disc:
            print(
                f"  interview snap: before_host_turn={n_host_cut}"
                f", host_question_included={n_host_start}"
                f", too_short_dropped={len(interview_disc)}",
                flush=True,
            )
        dangling_disc += interview_disc
    # Dangling-start gate: runs after interview_snap so that the START rule pulling r.start
    # back to a host question (which may itself end in an ellipsis) is also repaired.
    reels, post_dangling_disc = filter_dangling_start(
        reels, tx_words,
        dangling_words=getattr(r0_cfg, "dangling_words", None),
        min_duration=r0_cfg.min_clip_duration,
        max_start_repair_sec=getattr(r0_cfg, "max_start_repair_sec", 6.0),
    )
    repaired = sum(1 for r in reels if "start_repaired" in r.flags)
    dropped_dangling = len(post_dangling_disc)
    if dropped_dangling or repaired:
        print(
            f"  dangling_start: снято {dropped_dangling}, отремонтировано {repaired}",
            flush=True,
        )
    dangling_disc += post_dangling_disc
    # Compute ends_on_host_turn diagnostic on all kept reels (False for lecture; measurable for interview).
    for r in reels:
        r0_s = r.r0_start if r.r0_start is not None else r.start
        r.ends_on_host_turn = any(ts > r0_s and ts <= r.end for ts, te in host_turns)
    reels, topn_disc = apply_top_n(
        reels, max_reels=r0_cfg.max_reels, transcript_words=tx_words,
    )
    discarded = dedup_disc + dangling_disc + topn_disc
    reels = renumber_reels(reels)
    reels = _stage_padding(reels, transcript, r0_cfg=r0_cfg)
    reels = _stage_trim(reels, transcript, r0_cfg=r0_cfg)
    reels, short_disc = _stage_min_clip_filter(reels, transcript, r0_cfg=r0_cfg)
    discarded += short_disc
    reels, meaningful_disc = _stage_meaningful_sec_recheck(reels, transcript, r0_cfg=r0_cfg)
    discarded += meaningful_disc
    reels, density_disc = _stage_speech_density(reels, transcript, r0_cfg=r0_cfg)
    discarded += density_disc
    reels = _stage_subtitles(reels, transcript)
    memtrace.mark("after subtitles")
    trim_hanging_subtitles(reels, hanging_words=getattr(r0_cfg, "hanging_words", []))
    manifest = _assemble_manifest(
        video, reels, sha=sha, setup=setup, duration_preset=r0_cfg.duration_preset,
        source_kind=getattr(r0_cfg, "source_kind", ""),
        transcript_params_key=transcript_identity(transcript),
    )
    path = _write_manifest(manifest, manifests_dir)
    memtrace.mark("after manifest assembly")
    _write_discarded(discarded, path)
    _write_failed_chunks(failed_chunks, path)
    discard_info = f", сброшено кандидатов: {len(discarded)}" if discarded else ""
    chunk_info = f", провалилось чанков: {len(failed_chunks)}" if failed_chunks else ""
    print(f"манифест собран: {len(manifest.reels)} reels{discard_info}{chunk_info} → {path}", flush=True)

    # Zero-harvest: непустой транскрипт, но рилов нет → источник остаётся в inputs/.
    # Пустой транскрипт (тишина) → архивируем.
    is_empty_transcript = not compressed.strip()
    if not manifest.reels:
        if is_empty_transcript:
            if archive:
                print(f"⊘ транскрипт пуст (тишина) — архивируем {Path(video).name}", flush=True)
                _archive_video(Path(video), archive_dir)
            else:
                print(f"⊘ транскрипт пуст (тишина) — {Path(video).name} (in-place, не двигаем)", flush=True)
        else:
            raise ZeroHarvestError(
                f"R0 не нашёл ни одного рила (транскрипт непустой) — "
                f"источник оставлен на месте для ручной проверки: {Path(video).name}"
            )
    else:
        if push:
            # Калибровку кропа этого видео шлём вместе с манифестом — чтобы уехала на системник.
            _commit_push_manifest(path, len(manifest.reels), root=root,
                                  calibration_path=calibration_path(calibrations_dir, sha))
        if archive:
            _archive_video(Path(video), archive_dir)
        if auto_render:
            _ok, _reason = _should_auto_render(render_cfg, failed_chunks=failed_chunks)
            if _ok:
                if _render_queue is not None:
                    _render_queue.put(path)
                    print(f"  ▶ манифест поставлен в очередь рендера: {path.name}", flush=True)
                else:
                    print(f"\n▶ авто-рендер манифеста {path.name}…", flush=True)
                    cmd_render(root=root, manifests_dir=manifests_dir, pull_first=False)
            else:
                print(f"  авто-рендер пропущен: {_reason}", flush=True)
    return path


# Расширение выходного файла по формату транскрипта.
_TRANSCRIBE_EXT = {"text": "txt", "srt": "srt", "vtt": "vtt", "json": "json"}


def _render_transcript(transcript, *, fmt: str, r0_cfg) -> str:
    """Транскрипт → строка выбранного формата (детерминированный код, без LLM)."""
    sent_pause = r0_cfg.sentence_pause_sec
    # Абзац = смена мысли: пауза заметно длиннее, чем разрыв предложений. Конфига под это
    # нет → берём кратно sentence_pause_sec (эвристика, отдельный порог не плодим).
    para_pause = getattr(r0_cfg, "paragraph_pause_sec", None) or sent_pause * 5
    if fmt == "text":
        return to_text(transcript, sentence_pause_sec=sent_pause, paragraph_pause_sec=para_pause)
    if fmt == "srt":
        return to_srt(transcript, sentence_pause_sec=sent_pause)
    if fmt == "vtt":
        return to_vtt(transcript, sentence_pause_sec=sent_pause)
    if fmt == "json":
        return to_json(transcript)
    raise RunError(f"неизвестный формат транскрипта: {fmt}")


def _write_transcript_file(transcript, *, stem: str, fmt: str, out_dir, r0_cfg) -> Path:
    """Записать транскрипт в out_dir/<stem>.<ext> в выбранном формате. Общий для run и transcribe."""
    rendered = _render_transcript(transcript, fmt=fmt, r0_cfg=r0_cfg)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{stem}.{_TRANSCRIBE_EXT[fmt]}"
    out.write_text(rendered, encoding="utf-8")
    return out


def cmd_transcribe(
    source=None,
    *,
    fmt: str = "text",
    root=None,
    out_dir=None,
    cache_dir=None,
    ffmpeg: str = "ffmpeg",
    from_cache: str | None = None,
) -> Path:
    """Отдельная транскрибация: видео/аудио → чистый текст (или srt/vtt/json) для контента.

    Переиспользует облачный конвейер извлечения аудио + Whisper (чанкинг длинных видео —
    внутри `transcribe`). Рендер не задействован: источник читается на месте, результат —
    в `transcripts/<stem>.<ext>`. Дефолт `text` — связный текст с абзацами, без таймкодов.

    from_cache: sha256-хэш аудиофайла (64 hex-символа). Если задан — транскрипт читается
    из data/cache/<hash>.transcript.json напрямую, без извлечения аудио и вызова Whisper.
    Нужен когда видео на другой машине, но транскрипт уже закэширован локально.
    source в этом режиме необязателен — используется только для именования выходного файла.
    """
    root = Path(root) if root is not None else _project_root()
    cfg = root / "config"
    r0_cfg = load_r0_config(cfg / "r0.yaml")
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"
    out_dir = Path(out_dir) if out_dir else root / "transcripts"

    if from_cache is not None:
        # Имя кэша теперь <hash>[.<params_key>].transcript.json — берём точное совпадение,
        # иначе самый свежий вариант с этим хэшем (напр. праймленый перекрывает старый).
        exact = cache_dir / f"{from_cache}.transcript.json"
        if exact.exists():
            cache_path = exact
        else:
            cands = sorted(cache_dir.glob(f"{from_cache}.*.transcript.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            if not cands:
                raise RunError(f"транскрипт не найден в кэше: {exact}")
            cache_path = cands[0]
        transcript = Transcript.model_validate_json(cache_path.read_text(encoding="utf-8"))
        stem = Path(source).stem if source else from_cache[:16]
        print(f"=== transcribe: из кэша {from_cache[:16]}… (format={fmt}) ===", flush=True)
        out = _write_transcript_file(transcript, stem=stem, fmt=fmt,
                                     out_dir=out_dir, r0_cfg=r0_cfg)
        print(f"транскрипт готов ({len(transcript.words)} слов) → {out}", flush=True)
        return out

    render_cfg = load_render_config(cfg / "render.yaml")
    transcribe_cfg = load_transcribe_config(cfg / "transcribe.yaml")
    source = Path(source)

    print(f"=== transcribe: {source.name} (format={fmt}) ===", flush=True)
    # source_sha (partial-хэш содержимого) — тот же ключ аудио-кэша, что и в run → общий кэш
    # извлечённого аудио: transcribe после run не пере-извлекает mp3, и наоборот.
    sha = state.file_sha256_cached_fast(source, cache_dir)
    audio = _stage_extract_audio(source, render_cfg=render_cfg, cache_dir=cache_dir,
                                 ffmpeg=ffmpeg, source_sha=sha)
    transcript = _stage_transcribe(
        audio, transcribe_cfg=transcribe_cfg, cache_dir=cache_dir,
        r0_cfg=r0_cfg, audio_cfg=render_cfg.audio_extract, ffmpeg=ffmpeg,
    )
    out = _write_transcript_file(transcript, stem=source.stem, fmt=fmt,
                                 out_dir=out_dir, r0_cfg=r0_cfg)
    print(f"транскрипт готов ({len(transcript.words)} слов) → {out}", flush=True)
    return out


def cmd_run_batch(
    *,
    root=None,
    inputs_dir=None,
    calibrations_dir=None,
    manifests_dir=None,
    cache_dir=None,
    archive_dir=None,
    transcripts_dir=None,
    ffmpeg: str = "ffmpeg",
    push: bool = False,
    force: bool = False,
    force_transcribe: bool = False,
    auto_render: bool = False,
    parallel_render: bool = True,
    history_path=None,
) -> tuple[list[str], list[tuple[str, Exception]], list[tuple[str, str]], list[tuple[str, str]]]:
    """Batch: обработать все видео в inputs/ по очереди. Один упал → остальные продолжают.

    inputs-поток НЕ меняется: источники архивируются как раньше (archive=True по умолчанию).

    `root=None` → корень проекта из `_project_root()` (по расположению пакета, НЕ по cwd).
    Явный `root=<путь>` переопределяет дефолт — для тестов и нестандартных раскладок.
    `push=True` → каждый успешный манифест сразу коммитится+пушится (per-video, не в конце):
    упади прогон на середине — уже готовые манифесты УЖЕ на системнике.
    `parallel_render=True` → рендер запускается в фоновом потоке сразу после анализа каждого
    источника, не дожидаясь следующего анализа. Не более одного активного рендера одновременно.
    Возвращает (ok_names, failed_list, skipped_list, zero_harvest_list):
    failed = [(name, exc), …] (реальные ошибки, включая ошибки рендера);
    skipped = [(name, причина), …] (битые/пустые файлы — их НЕ архивируем, остаются в inputs/);
    zero_harvest = [(name, причина), …] (непустой транскрипт, но 0 рилов — источник в inputs/).
    """
    root = Path(root) if root is not None else _project_root()
    # Преflight утилит ОДИН раз до всей пачки: нет ffmpeg/ffprobe → падаем сразу с внятным
    # сообщением, не прочитав ни одного гигабайта (на 6 файлах впустую читалось ~40 ГБ хэшей,
    # прежде чем всплывало «нет ffmpeg»). Летит наверх (не в per-file try) → одно сообщение.
    _preflight_tools(ffmpeg, resolve_ffprobe(None, ffmpeg=ffmpeg))
    _git_pull(root, what="калибровки")          # один pull на всю пачку (не на каждое видео)
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    manifests_dir_resolved = Path(manifests_dir) if manifests_dir else root / "manifests"
    videos = _scan_inputs(inputs_dir)
    if not videos:
        _report_empty_inputs(inputs_dir)
        return [], [], [], []

    ok: list[str] = []
    failed: list[tuple[str, Exception]] = []
    skipped: list[tuple[str, str]] = []
    zero_harvest: list[tuple[str, str]] = []

    # Background render worker: at most one render at a time.
    # ponytail: single worker thread + queue — two ffmpeg on one GPU is slower than one.
    render_q: _queue.Queue | None = None
    render_failed: list[tuple[str, Exception]] = []
    worker: _threading.Thread | None = None

    if auto_render and parallel_render:
        render_q = _queue.Queue()

        def _render_worker() -> None:
            while True:
                item = render_q.get()
                if item is None:
                    render_q.task_done()
                    break
                mf_path = item
                stem = mf_path.stem
                try:
                    print(f"\n[рендер] ▶ {stem}…", flush=True)
                    cmd_render(
                        root=root, manifests_dir=manifests_dir_resolved, pull_first=False,
                        _manifest_paths=[mf_path], background=True, _raise_on_failure=True,
                    )
                    print(f"[рендер] ✓ {stem}", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"\n[рендер] ✗ {stem}: {e}", file=sys.stderr, flush=True)
                    render_failed.append((f"{stem} (рендер)", e))
                finally:
                    render_q.task_done()

        worker = _threading.Thread(target=_render_worker, daemon=True, name="render-worker")
        worker.start()

    for v in videos:
        try:
            cmd_run(
                v, root=root, calibrations_dir=calibrations_dir, manifests_dir=manifests_dir,
                cache_dir=cache_dir, archive_dir=archive_dir, transcripts_dir=transcripts_dir,
                ffmpeg=ffmpeg, push=push, pull_first=False, force=force,
                force_transcribe=force_transcribe,
                auto_render=auto_render, history_path=history_path, _render_queue=render_q,
            )
            ok.append(v.name)
        except AlreadyProcessedError as e:       # run_key совпал — уже обработан, пропуск
            print(f"\n✓ {v.name}: {e}", flush=True)
            skipped.append((v.name, str(e)))
        except ManualManifestError as e:         # ручная выборка — не стираем без --force
            print(f"\n✋ {v.name}: {e}", file=sys.stderr, flush=True)
            skipped.append((v.name, str(e)))
        except InputInvalid as e:               # битый/пустой файл — пропуск, НЕ ошибка
            print(f"\n⊘ пропущен {v.name}: {e}", file=sys.stderr, flush=True)
            skipped.append((v.name, str(e)))
        except ZeroHarvestError as e:           # транскрипт непустой, но рилов нет
            print(f"\n⚠ нулевой урожай {v.name}: {e}", file=sys.stderr, flush=True)
            zero_harvest.append((v.name, str(e)))
        except Exception as e:  # noqa: BLE001
            print(f"\n[ОШИБКА] {v.name}: {e}", file=sys.stderr, flush=True)
            failed.append((v.name, e))

    if worker is not None:
        render_q.put(None)        # sentinel: worker exits after draining queue
        render_q.join()           # wait until sentinel is processed (all renders done)
        worker.join()
        failed.extend(render_failed)

    parts = [f"{len(ok)} ok"]
    if zero_harvest:
        parts.append(f"{len(zero_harvest)} нулевой урожай")
    if skipped:
        parts.append(f"{len(skipped)} пропущено")
    parts.append(f"{len(failed)} ошибок")
    print(f"\n=== batch run: {' / '.join(parts)} ===", flush=True)
    for name, err in failed:
        print(f"  ✗ {name}: {err}", file=sys.stderr)
    for name, reason in zero_harvest:
        print(f"  ⚠ {name}: {reason}", file=sys.stderr)
    for name, reason in skipped:
        print(f"  ⊘ {name}: {reason}", file=sys.stderr)
    if zero_harvest:
        print(f"\n⚠ {len(zero_harvest)} видео без рилов — транскрипт непустой, "
              f"но R0 ничего не нашёл; файлы оставлены в inputs/ для ручной проверки", flush=True)
    if skipped:
        print(f"\n⚠ пропущено {len(skipped)} файла(ов) — не обработаны, оставлены в inputs/ "
              f"(причина у каждого выше: битый / уже обработан / ручная выборка); "
              f"проверь inputs/", flush=True)
    return ok, failed, skipped, zero_harvest


def _missing_reels(manifest: Manifest, out_dir: Path) -> list:
    """Вернуть reel-объекты из манифеста, для которых ещё нет выходного mp4.

    Выходной файл: out_dir/<reel.id>.mp4  (render_crop без суффикса — вертикальный рез).
    """
    return [r for r in manifest.reels if not (out_dir / f"{r.id}.mp4").exists()]


# Фоллбэк энкодеров: менее→более совместимый с GPU. av1 (нужен RX 7000+) → hevc → h264.
_ENCODER_FALLBACK_CHAIN = ["av1", "hevc", "h264"]


def _encoder_unavailable_msg(codec: str, prof_name: str) -> str:
    hint = " (аппаратный AV1 нужен AMD RX 7000+ / свежий GPU)" if "av1" in codec else ""
    return (
        f"энкодер {codec} (профиль {prof_name}) не поддерживается этой машиной{hint}. "
        f"Выбери другой профиль: arl → 9 или --profile hevc|h264 "
        f"(или убери --no-fallback для автоподбора)."
    )


def _preflight_encoder(prof_name, enc, render_cfg, *, ffmpeg, fallback, explicit_encoder):
    """Проверить энкодер ДО рендера пачки (пробный encode). Недоступен → фоллбэк по цепочке
    (av1→hevc→h264) с уведомлением, либо внятная ошибка. Возвращает (prof_name, codec)."""
    if probe_encoder(enc, ffmpeg=ffmpeg):
        return prof_name, enc
    # Выбранный недоступен. Явный --encoder или нестандартный профиль → без профиль-фоллбэка.
    if not fallback or explicit_encoder or prof_name not in _ENCODER_FALLBACK_CHAIN:
        raise RenderError(_encoder_unavailable_msg(enc, prof_name))
    # Фоллбэк к более совместимому профилю.
    for p in _ENCODER_FALLBACK_CHAIN[_ENCODER_FALLBACK_CHAIN.index(prof_name) + 1:]:
        codec = render_cfg.encoder.profiles[p].codec
        if probe_encoder(codec, ffmpeg=ffmpeg):
            print(f"\n  ⚠ {enc} не поддерживается этим GPU — фоллбэк на профиль {p} ({codec})",
                  flush=True)
            return p, codec
    raise RenderError(
        f"ни один энкодер не доступен (пробовал {prof_name} → … → h264) — "
        f"проверь ffmpeg/GPU или задай софтверный --encoder libx264"
    )


_MUSIC_EXTS = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac", ".opus")


def _resolve_music_track(music_cfg, root, *, flag=None) -> str | None:
    """Абсолютный путь к фоновому треку или None (музыка выключена/трек не найден).

    Приоритет: флаг --music > конфиг. Имя трека ищется как есть (абсолютный путь) или в music/.
    `random` в конфиге → случайный файл из music/. Отсутствие файла — предупреждение, не ошибка
    (рендер продолжается без музыки). Детерминизм: случайный трек — единственная не-детерминантная
    точка, осознанно (разнообразие фона); границы/тексты/кроп от этого не зависят."""
    music_dir = Path(root) / "music"

    def _find(name: str) -> Path | None:
        p = Path(name)
        if p.is_file():
            return p
        cand = music_dir / name
        return cand if cand.is_file() else None

    if flag:
        track = _find(flag)
        if track is None:
            print(f"  ⚠ музыка: трек «{flag}» не найден (ни как путь, ни в music/) — без музыки",
                  file=sys.stderr, flush=True)
        return str(track.resolve()) if track else None

    if not music_cfg.enabled:
        return None
    if music_cfg.random:
        tracks = sorted(p for p in music_dir.glob("*") if p.suffix.lower() in _MUSIC_EXTS) \
            if music_dir.is_dir() else []
        if not tracks:
            print(f"  ⚠ музыка: music.random, но в {music_dir}/ нет треков — без музыки",
                  file=sys.stderr, flush=True)
            return None
        import random
        return str(random.choice(tracks).resolve())
    if music_cfg.file:
        track = _find(music_cfg.file)
        if track is None:
            print(f"  ⚠ музыка: трек «{music_cfg.file}» из конфига не найден — без музыки",
                  file=sys.stderr, flush=True)
        return str(track.resolve()) if track else None
    print("  ⚠ музыка включена, но не задан файл (music.file / music.random / --music) — без музыки",
          file=sys.stderr, flush=True)
    return None


def cmd_render(
    *,
    manifests_dir=None,
    inputs_dir=None,
    out_dir=None,
    archive_dir=None,
    calibrations_dir=None,
    root=None,
    ffmpeg: str | None = None,
    encoder=None,
    profile=None,
    palette=None,
    zoom: bool | None = None,
    music=None,
    fallback: bool = True,
    allow_stale: bool = False,
    auto_recrop: bool = True,
    pull_first: bool = True,
    _manifest_paths: list | None = None,
    background: bool = False,
    _raise_on_failure: bool = False,
) -> list[Path]:
    """ЛОКАЛЬНЫЙ тир: manifests/*.json → reels-out/ (batch по всем манифестам).

    Каждый манифест рендерится независимо. Три исхода:
    - все клипы уже есть в reels-out/<stem>/ → пропуск «✓ уже готово»;
    - исходник не найден в inputs/ → пропуск «⊘ нет видео»;
    - рендер упал → ошибка в сводке.

    Манифесты в manifests/ НЕ трогаются — git ими управляет (Mac→системник через pull).
    Идемпотентность обеспечивается проверкой выходных файлов, а не перемещением манифеста.
    """
    root = Path(root) if root is not None else _project_root()
    if pull_first:
        _git_pull(root, what="манифесты")       # свежие манифесты с Mac (после run)
    render_cfg = load_render_config(root / "config" / "render.yaml")
    if render_cfg.role == "analyze":
        print(
            '⊘ рендер недоступен на этой машине: role = "analyze" '
            "(config/render.local.yaml) — смените на \"both\" или \"render\"",
            file=sys.stderr,
        )
        return []
    subtitles_cfg = load_subtitles_config(root / "config" / "subtitles.yaml")
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    out_dir = Path(out_dir) if out_dir else root / "reels-out"
    archive_dir = Path(archive_dir) if archive_dir else root / "inputs-archive"
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"

    manifest_files = _manifest_paths if _manifest_paths is not None else _glob_manifests(manifests_dir)
    if not manifest_files:
        print("manifests/ пуст — нечего рендерить", flush=True)
        return []

    # Профиль кодека: флаг > env RENDER_PROFILE > активный из конфига. Опечатка → fail-fast.
    prof_name = profile or os.environ.get("RENDER_PROFILE") or render_cfg.encoder.profile
    validate_profile(prof_name, render_cfg.encoder.profiles, where="--profile/RENDER_PROFILE")
    # Палитра (цветокор): флаг > env RENDER_PALETTE переопределяют ВСЁ; иначе per-video из
    # манифеста (setup.palette, выбрана в калибраторе) > активная из конфига. Разрешается
    # per-manifest внутри цикла (у каждого видео может быть своя палитра).
    pal_override = palette or os.environ.get("RENDER_PALETTE")
    if pal_override and pal_override not in render_cfg.palettes:
        known = ", ".join(render_cfg.palettes)
        raise SystemExit(f"неизвестная палитра '{pal_override}'. Доступны: {known}")
    # Фоновая музыка: --music <файл> > конфиг (music.file/random). None → без музыки.
    music_path = _resolve_music_track(render_cfg.music, root, flag=music)
    # Отображаемый кодек: явный encoder переопределяет кодек профиля (Mac-дев без AMF).
    enc = encoder or os.environ.get("RENDER_ENCODER") or render_cfg.encoder.profiles[prof_name].codec
    # ffmpeg: флаг > env RENDER_FFMPEG > render.local.yaml > render.yaml → автопоиск.
    effective_ffmpeg = resolve_ffmpeg(ffmpeg, render_cfg=render_cfg)
    # Префлайт энкодера: проверяем ДО рендера пачки (иначе av1_amf на неподдерживающем GPU
    # роняет все манифесты на первом клипе). Недоступен → фоллбэк av1→hevc→h264 или ошибка.
    explicit_encoder = bool(encoder or os.environ.get("RENDER_ENCODER"))
    prof_name, enc = _preflight_encoder(
        prof_name, enc, render_cfg, ffmpeg=effective_ffmpeg,
        fallback=fallback, explicit_encoder=explicit_encoder,
    )
    all_outputs: list[Path] = []
    skipped_no_video: list[str] = []
    skipped_done: list[str] = []
    skipped_stale: list[str] = []
    failed: list[tuple[str, Exception]] = []

    for mf in manifest_files:
        try:
            manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
            stem = Path(manifest.source).stem
            out_dir_final = out_dir / stem

            # Рассинхрон: калибровка новее манифеста (кроп в манифесте устарел). Рендерить —
            # значит выжечь СТАРЫЙ кроп. desync ≠ None ⇒ калибровка ЕСТЬ (иначе сравнивать не с чем).
            desync = _manifest_calibration_desync(manifest, calibrations_dir)
            if desync and not allow_stale:
                if auto_recrop:
                    # Калибровка есть и детерминирована (без LLM, секунды) → применяем сразу,
                    # тем же кодом, что recrop, и продолжаем рендер обновлённым кропом.
                    try:
                        new_setup = _recrop_setup(
                            manifest, calibrations_dir=calibrations_dir, inputs_dir=inputs_dir,
                            archive_dir=archive_dir,
                            ffprobe=resolve_ffprobe(None, ffmpeg=effective_ffmpeg),
                        )
                    except CalibrationError as e:
                        # Нечего применить (нет валидной калибровки) → блокируем как раньше.
                        print(f"\n  ⛔ ПРОПУСК {stem}: {desync}\n     не удалось авто-применить "
                              f"калибровку: {e}. arl recrop / arl r --allow-stale",
                              file=sys.stderr, flush=True)
                        skipped_stale.append(mf.name)
                        continue
                    # Применяем свежий кроп ТОЛЬКО В ПАМЯТИ для этого рендера. Манифест на диске
                    # не трогаем: после сборки он иммутабелен (пишет только анализ, рендер читает).
                    # Иначе рендер-машина коммитит манифесты и на двух машинах начинаются git-
                    # конфликты. Обновить сам манифест — отдельным arl recrop на машине анализа.
                    manifest = manifest.model_copy(update={"setup": new_setup})
                    c = new_setup.crop
                    print(f"  ↻ {stem}: кроп устарел — применяю свежую калибровку "
                          f"{c.w}×{c.h}@{c.x},{c.y} в кадре {new_setup.frame} ТОЛЬКО для этого "
                          f"рендера (манифест не меняю; обновить его — arl recrop на машине анализа)",
                          flush=True)
                    # дальше рендерим обновлённым (в памяти) manifest (не continue)
                else:
                    # --no-auto-recrop: строгая блокировка (не трогаем манифест).
                    print(f"\n  ⛔ ПРОПУСК {stem}: {desync}\n     кроп в манифесте "
                          f"{manifest.setup.crop.model_dump()} — старый. Обнови: arl recrop, "
                          f"затем arl r. Форс старым кропом: arl r --allow-stale",
                          file=sys.stderr, flush=True)
                    skipped_stale.append(mf.name)
                    continue

            # Идемпотентность: пропускаем манифесты, для которых все клипы уже есть
            missing = _missing_reels(manifest, out_dir_final)
            if not missing:
                print(f"✓ {stem}: все {len(manifest.reels)} клипов уже готовы — пропуск",
                      flush=True)
                skipped_done.append(mf.name)
                continue

            # Рендерим только недостающие клипы (при частичном завершении)
            render_manifest = manifest if len(missing) == len(manifest.reels) else (
                manifest.model_copy(update={"reels": missing})
            )
            n_missing = len(missing)
            n_total = len(manifest.reels)
            label = f"{n_missing}/{n_total} клипов" if n_missing < n_total else f"{n_total} клипов"
            # Палитра этого видео: флаг/env > setup.palette (калибратор) > конфиг. Неизвестную —
            # игнорируем с предупреждением (не роняем весь рендер из-за опечатки в манифесте).
            eff_pal = pal_override or manifest.setup.palette or render_cfg.palette
            if eff_pal not in render_cfg.palettes:
                print(f"  ⚠ палитра «{eff_pal}» неизвестна — беру {render_cfg.palette}",
                      file=sys.stderr, flush=True)
                eff_pal = render_cfg.palette
            pal_tag = "" if eff_pal == "neutral" else f", палитра {eff_pal}"
            zoom_on = render_cfg.zoom.enabled if zoom is None else zoom
            zoom_tag = ", зум" if zoom_on else ""
            music_tag = f", музыка {Path(music_path).name}" if music_path else ""
            print(f"=== render: {mf.name} ({label}, {prof_name}/{enc}{pal_tag}{zoom_tag}{music_tag}) "
                  f"→ {out_dir_final} ===", flush=True)
            outputs = render_crop(
                render_manifest, inputs_dir=inputs_dir, out_dir=out_dir_final,
                render_cfg=render_cfg, ffmpeg=effective_ffmpeg,
                encoder=(enc if explicit_encoder else None),   # префлайт мог сменить профиль
                profile=prof_name, palette=eff_pal, zoom=zoom, music_path=music_path,
                subtitles_cfg=subtitles_cfg, background=background,
            )
            all_outputs.extend(outputs)
            print(f"готово: {len(outputs)} клипов → {out_dir_final}", flush=True)
            _archive_video(inputs_dir / Path(manifest.source).name, archive_dir)
        except SourceNotFoundError:
            print(f"⊘ пропущен {mf.stem}: исходник не найден в inputs/", flush=True)
            skipped_no_video.append(mf.name)
        except Exception as e:  # noqa: BLE001
            print(f"\n[ОШИБКА] {mf.name}: {e}", file=sys.stderr, flush=True)
            failed.append((mf.name, e))

    total = len(manifest_files)
    skipped = skipped_no_video + skipped_done + skipped_stale
    if total > 1 or failed or skipped:
        ok = total - len(failed) - len(skipped)
        parts = [f"{ok} отрендерено"]
        if skipped_done:
            names = ", ".join(s.removesuffix(".json") for s in skipped_done)
            parts.append(f"{len(skipped_done)} уже готово ({names})")
        if skipped_stale:
            names = ", ".join(s.removesuffix(".json") for s in skipped_stale)
            parts.append(f"{len(skipped_stale)} устарел кроп, нечем обновить ({names})")
        if skipped_no_video:
            names = ", ".join(s.removesuffix(".json") for s in skipped_no_video)
            parts.append(f"{len(skipped_no_video)} нет видео ({names})")
        if failed:
            parts.append(f"{len(failed)} ошибок")
        print(f"\n=== batch render: {' / '.join(parts)} ===", flush=True)
        for name, err in failed:
            print(f"  ✗ {name}: {err}", file=sys.stderr)
    if _raise_on_failure and failed:
        _, first_exc = failed[0]
        raise first_exc
    return all_outputs


def cmd_preview(
    manifest_arg=None,
    *,
    palettes=None,
    seconds: float = 6.0,
    reel_id=None,
    zoom=None,
    root=None,
    manifests_dir=None,
    inputs_dir=None,
    out_dir=None,
    ffmpeg: str | None = None,
    encoder=None,
    profile=None,
) -> int:
    """Короткий фрагмент одного клипа в НЕСКОЛЬКИХ палитрах — подобрать цветокор/зум быстро, без
    полного рендера всех клипов. `arl preview <манифест> --palettes neutral,vivid,sharp` →
    reels-out/_preview/<id>__<palette>.mp4 рядом для сравнения. Без --palettes — все пресеты.
    `zoom`: None (из конфига) | "on" | "off" | "compare" (рендерит оба варианта — с зумом и без)."""
    root = Path(root) if root is not None else _project_root()
    render_cfg = load_render_config(root / "config" / "render.yaml")
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    out_dir = Path(out_dir) if out_dir else root / "reels-out" / "_preview"

    if manifest_arg:
        mf = Path(manifest_arg)
        if not mf.is_file():
            mf = manifests_dir / f"{Path(manifest_arg).stem}.json"
    else:
        candidates = _glob_manifests(manifests_dir)
        if not candidates:
            print("manifests/ пуст — нечего превьюить", file=sys.stderr, flush=True)
            return 1
        mf = candidates[0]
    if not mf.is_file():
        print(f"нет манифеста «{manifest_arg}» — сначала arl run", file=sys.stderr, flush=True)
        return 1

    manifest = load_manifest(mf.parent, name=mf.name)
    pal_list = palettes if palettes else list(render_cfg.palettes)
    unknown = [p for p in pal_list if p not in render_cfg.palettes]
    if unknown:
        known = ", ".join(render_cfg.palettes)
        print(f"неизвестные палитры: {', '.join(unknown)}. Доступны: {known}",
              file=sys.stderr, flush=True)
        return 1

    prof_name = profile or os.environ.get("RENDER_PROFILE") or render_cfg.encoder.profile
    validate_profile(prof_name, render_cfg.encoder.profiles, where="--profile/RENDER_PROFILE")
    explicit_encoder = bool(encoder or os.environ.get("RENDER_ENCODER"))
    enc = (encoder or os.environ.get("RENDER_ENCODER")
           or render_cfg.encoder.profiles[prof_name].codec)
    effective_ffmpeg = resolve_ffmpeg(ffmpeg, render_cfg=render_cfg)

    # Варианты зума: compare → оба (с зумом/без) с тегом в имени; on/off → один; None → из конфига.
    if zoom == "compare":
        zoom_variants = [(True, "zoom"), (False, "flat")]
    elif zoom in ("on", "off"):
        zoom_variants = [(zoom == "on", "")]
    else:
        zoom_variants = [(None, "")]

    out_dir.mkdir(parents=True, exist_ok=True)
    zoom_note = {"compare": " · зум: с/без", "on": " · зум", "off": " · без зума"}.get(zoom, "")
    print(f"=== preview: {mf.stem} · палитры {', '.join(pal_list)} · {seconds:g}с{zoom_note} "
          f"→ {out_dir} ===", flush=True)
    try:
        outputs = []
        for z_enabled, ztag in zoom_variants:
            outputs += render_preview(
                manifest, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
                ffmpeg=effective_ffmpeg, palettes=pal_list, seconds=seconds, reel_id=reel_id,
                profile=prof_name, encoder=(enc if explicit_encoder else None),
                zoom=z_enabled, ztag=ztag,
                progress=lambda rid: print(f"  · {rid}", flush=True),
            )
    except (RenderError, SourceNotFoundError) as e:
        print(f"[ОШИБКА] {e}", file=sys.stderr, flush=True)
        return 1
    print(f"готово: {len(outputs)} превью → {out_dir}", flush=True)
    for p in outputs:
        print(f"  {p.name}", flush=True)
    return 0


def _find_source_video(source_name, *, inputs_dir, archive_dir):
    """Найти видеофайл по имени в inputs/ или архиве (для probe размера при автокропе)."""
    for d in (inputs_dir, archive_dir):
        p = Path(d) / source_name
        if p.is_file():
            return p
    return None


def _recrop_setup(manifest, *, calibrations_dir, inputs_dir, archive_dir, ffprobe="ffprobe"):
    """Свежий setup для манифеста: калибровка по sha (или автокроп по отображаемому кадру).

    Кроп валидируется В ОТОБРАЖАЕМОМ кадре (границы + 9:16). Автокроп требует видео на диске —
    иначе CalibrationError (нечем определить размер кадра). `ffprobe` — резолвнутый путь (не
    голое имя): иначе автокроп-ветка падает WinError 2, если ffprobe не в PATH. Reels не участвуют."""
    def _frame_size():
        video = _find_source_video(manifest.source, inputs_dir=inputs_dir, archive_dir=archive_dir)
        if video is None:
            raise CalibrationError(
                f"нет калибровки и видео «{manifest.source}» недоступно (ни inputs/, ни архив) — "
                f"нечем считать автокроп"
            )
        return _probe_frame_size_for_auto(video, ffprobe=ffprobe)

    setup = load_or_auto_calibrate(
        calibrations_dir, manifest.source_sha256, manifest.source, get_frame_size=_frame_size
    )
    validate_crop_in_frame(setup.crop, setup.frame[0], setup.frame[1])
    return setup


def cmd_recrop(
    video=None,
    *,
    root=None,
    manifests_dir=None,
    calibrations_dir=None,
    inputs_dir=None,
    archive_dir=None,
    push: bool = True,
    pull_first: bool = True,
) -> int:
    """Обновить ТОЛЬКО кроп в существующем манифесте по свежей калибровке — БЕЗ пересчёта R0.

    Смена калибровки не должна гнать LLM заново (границы клипов, тексты, субтитры не меняются —
    меняется лишь crop). Эта команда читает калибровку по sha видео (или автокроп), обновляет
    setup (crop/scale/frame) в манифесте и всё; reels байт-в-байт те же. Без <video> — batch по
    всем манифестам с устаревшим кропом. Валидация: кроп в отображаемом кадре, 9:16. Авто-push."""
    root = Path(root) if root is not None else _project_root()
    if pull_first:
        _git_pull(root, what="калибровки")
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    archive_dir = Path(archive_dir) if archive_dir else root / "inputs-archive"

    # Резолвнутый ffprobe (не голое имя) для автокроп-ветки _recrop_setup — иначе WinError 2,
    # если ffprobe не в PATH. Ручная калибровка ffprobe не зовёт; резолв best-effort (не роняем
    # recrop, если ffmpeg не найден — там, где кроп ручной, ffprobe и не понадобится).
    try:
        _ff = _cli_resolve_ffmpeg(None, root=root)
    except FFmpegNotFoundError:
        _ff = None
    recrop_ffprobe = resolve_ffprobe(None, ffmpeg=_ff)

    if video is not None:
        mf = manifests_dir / f"{Path(video).stem}.json"
        if not mf.is_file():
            print(f"нет манифеста для {Path(video).stem} — сначала arl run", file=sys.stderr, flush=True)
            return 1
        targets = [mf]
    else:
        targets = _glob_manifests(manifests_dir)
        if not targets:
            print("manifests/ пуст — нечего рекропить", flush=True)
            return 0

    updated: list[str] = []
    skipped: list[str] = []
    synced: list[str] = []
    for mf in targets:
        try:
            manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ битый манифест {mf.name}: {e}", file=sys.stderr, flush=True)
            skipped.append(mf.name)
            continue
        stem = Path(manifest.source).stem
        try:
            new_setup = _recrop_setup(manifest, calibrations_dir=calibrations_dir,
                                      inputs_dir=inputs_dir, archive_dir=archive_dir,
                                      ffprobe=recrop_ffprobe)
        except CalibrationError as e:
            print(f"  ⚠ пропуск {stem}: {e}", file=sys.stderr, flush=True)
            skipped.append(mf.name)
            continue

        old = manifest.setup.crop
        old_frame = list(manifest.setup.frame)
        new_frame = list(new_setup.frame)
        old_rot = float(getattr(manifest.setup, "rotation_deg", 0.0) or 0.0)
        new_rot = float(getattr(new_setup, "rotation_deg", 0.0) or 0.0)
        old_pal = getattr(manifest.setup, "palette", None)
        new_pal = getattr(new_setup, "palette", None)
        same_crop = old.model_dump() == new_setup.crop.model_dump()
        same_frame = old_frame == new_frame
        same_rot = old_rot == new_rot
        same_pal = old_pal == new_pal
        if same_crop and same_frame and same_rot and same_pal:
            # Явно сообщаем «уже синхронно» (и в batch) — иначе «0 обновлено» выглядит как баг.
            rot_note = f", поворот {old_rot:g}°" if old_rot else ""
            print(f"  = {stem}: кроп уже совпадает с калибровкой ({old.w}×{old.h}@{old.x},{old.y}, "
                  f"кадр {old_frame}{rot_note}) — без изменений", flush=True)
            synced.append(mf.name)
            continue

        # Смена пространства (кадр перевёрнут: кодированное ↔ отображаемое) — однозначно устарел.
        space = ""
        if old_frame != new_frame:
            space = (f"  [пространство изменилось: кадр {old_frame} → {new_frame}"
                     + ("; кодированное→отображаемое" if old_frame == new_frame[::-1] else "") + "]")

        # Обновляем ТОЛЬКО setup; reels/тексты/субтитры остаются те же объекты → байт-в-байт.
        _write_manifest(manifest.model_copy(update={"setup": new_setup}), manifests_dir)
        c = new_setup.crop
        rot_note = ""
        if old_rot != new_rot:
            rot_note = f", поворот {old_rot:g}°→{new_rot:g}°"
        elif new_rot:
            rot_note = f", поворот {new_rot:g}°"
        print(f"  ✓ {stem}: кроп {old.w}×{old.h}@{old.x},{old.y} → {c.w}×{c.h}@{c.x},{c.y} "
              f"в кадре {new_frame}{rot_note} (R0 не пересчитывался){space}", flush=True)
        updated.append(mf.name)
        if push:
            _commit_push_manifest(manifests_dir / f"{stem}.json", len(manifest.reels), root=root)

    if video is None or len(targets) > 1:
        parts = [f"{len(updated)} обновлено"]
        if synced:
            parts.append(f"{len(synced)} уже синхронно")
        if skipped:
            parts.append(f"{len(skipped)} пропущено")
        print(f"\n=== recrop: {' / '.join(parts)} ===", flush=True)
    if updated:
        print("  → кроп обновлён; границы клипов НЕ изменились (recrop трогает только кроп). "
              "Дальше: arl r (render).", flush=True)
    return 0


def _resnap_reels(reels, transcript, r0_cfg) -> None:
    """Пересчитать границы клипов из сохранённых R0-границ: сброс start/end к r0_start/r0_end,
    затем snap → padding → trim текущим кодом. Мутирует reels; тексты/субтитры не трогает."""
    for r in reels:
        r.start, r.end = r.r0_start, r.r0_end
    snap_segments(reels, transcript.words, tail_sec=r0_cfg.tail_sec,
                  window_sec=r0_cfg.snap_window_sec, max_duration=r0_cfg.max_duration,
                  min_pause_for_phrase_end=r0_cfg.min_pause_for_phrase_end,
                  max_micro_pause=r0_cfg.max_micro_pause, hanging_words=r0_cfg.hanging_words,
                  max_end_search_sec=r0_cfg.max_end_search_sec,
                  min_clip_duration=r0_cfg.min_clip_duration)
    apply_padding(reels, transcript.words, tail_pad_sec=r0_cfg.tail_pad_sec,
                  lead_pad_sec=r0_cfg.lead_pad_sec, max_duration=r0_cfg.max_duration,
                  video_duration=transcript.words[-1].t1 if transcript.words else None,
                  hanging_words=r0_cfg.hanging_words)
    trim_too_long(reels, transcript.words, max_duration=r0_cfg.max_duration,
                  pause_sec=r0_cfg.sentence_pause_sec, policy=r0_cfg.too_long_policy)


def _last_words_before(words, end_sec: float, n: int = 5) -> str:
    """Last n word tokens with t0 < end_sec (for dry-run boundary preview)."""
    tokens = [w.word for w in words if w.t0 < end_sec]
    return " ".join(tokens[-n:]) if tokens else ""


def cmd_resnap(
    video=None,
    *,
    root=None,
    manifests_dir=None,
    cache_dir=None,
    push: bool = True,
    pull_first: bool = True,
    dry_run: bool = False,
) -> int:
    """Пересчитать ГРАНИЦЫ клипов из сохранённых R0-границ (snap→padding→trim текущим кодом),
    БЕЗ повторного R0/LLM. Для проверки правок snap/padding без пересборки манифеста.

    Выбор моментов (R0), тексты, субтитры — НЕ трогаются: те же r0_start/r0_end прогоняются
    заново детерминированным слоем. Транскрипт берётся из кэша (как diagnose-cuts). Без <video>
    — batch по всем манифестам. Манифест без r0_start (снят до фичи) → нужен один полный run.

    --dry-run: печатает что изменится (per-reel: старые/новые границы, причина snap, последние
    слова), ничего не пишет и не пушит. При пустом transcript_params_key делает best-effort
    резолв через текущий конфиг с предупреждением — запись в этом случае по-прежнему отказана."""
    root = Path(root) if root is not None else _project_root()
    if pull_first:
        _git_pull(root, what="манифесты")
    r0_cfg = load_r0_config(root / "config" / "r0.yaml")
    render_cfg = load_render_config(root / "config" / "render.yaml")
    audio_format = render_cfg.audio_extract.format
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"

    if video is not None:
        mf = manifests_dir / f"{Path(video).stem}.json"
        if not mf.is_file():
            print(f"нет манифеста для «{Path(video).stem}» — сначала arl run", file=sys.stderr, flush=True)
            return 1
        targets = [mf]
    else:
        targets = _glob_manifests(manifests_dir)
        if not targets:
            print("manifests/ пуст — нечего пересчитывать", flush=True)
            return 0

    updated: list[str] = []
    skipped: list[str] = []
    no_r0: list[str] = []
    refused: list[str] = []
    for mf in targets:
        try:
            manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ битый манифест {mf.name}: {e}", file=sys.stderr, flush=True)
            skipped.append(mf.name)
            continue
        stem = Path(manifest.source).stem
        if not manifest.reels or any(r.r0_start is None or r.r0_end is None for r in manifest.reels):
            print(f"  ⚠ {stem}: нет сохранённых R0-границ (манифест снят до фичи resnap) — нужен "
                  f"ОДИН полный run (arl run), дальше resnap бесплатен", file=sys.stderr, flush=True)
            no_r0.append(mf.name)
            continue
        # Идентичность транскрипта ОБЯЗАТЕЛЬНА для записи: без записанного params_key нельзя
        # проверить, что резолвим тот же транскрипт → отказ (порча границ хуже отсутствия правки).
        # dry-run исключение: можно preview с best-effort транскриптом + предупреждение.
        used_fallback_transcript = False
        if not manifest.transcript_params_key:
            if not dry_run:
                print(f"  ⚠ {stem}: манифест без transcript_params_key (снят до этого фикса) — resnap "
                      f"ОТКАЗАН: нельзя проверить транскрипт. Нужен ОДИН полный run (arl run), "
                      f"дальше resnap безопасен", file=sys.stderr, flush=True)
                refused.append(mf.name)
                continue
            # dry-run: best-effort — попробовать текущий конфиг как запасной вариант
            config_pkey = _config_params_key(root)
            transcript, expected = _resolve_transcript(manifest, cache_dir,
                                                       audio_format=audio_format,
                                                       config_pkey=config_pkey)
            if transcript is None:
                print(f"  ⚠ {stem}: dry-run, transcript_params_key пуст и транскрипт не найден "
                      f"(params_key={config_pkey or '—'}) — пропуск",
                      file=sys.stderr, flush=True)
                skipped.append(mf.name)
                continue
            print(f"  ℹ {stem}: dry-run — transcript_params_key пуст, использован транскрипт "
                  f"текущего конфига ({config_pkey}); запись по-прежнему отказана",
                  file=sys.stderr, flush=True)
            used_fallback_transcript = True
        else:
            # Резолв ТОЛЬКО по записанному ключу (config_pkey="" не подставляем — иначе можно уехать
            # на транскрипт текущего конфига, если он сменился после сборки манифеста).
            transcript, expected = _resolve_transcript(manifest, cache_dir, audio_format=audio_format)
            if transcript is None:
                why = ("нет аудио в кэше" if expected is None
                       else f"нет транскрипта с params_key={expected}")
                print(f"  ⚠ {stem}: {why} (тот, на котором собран манифест) — resnap ОТКАЗАН",
                      file=sys.stderr, flush=True)
                refused.append(mf.name)
                continue
            # Guard: имя файла говорит params_key X, но stamped-мета внутри — Y? Не писать.
            actual = transcript_identity(transcript)
            if actual != manifest.transcript_params_key:
                if dry_run:
                    print(f"  ⚠ {stem}: dry-run — params_key расходится (манифест="
                          f"{manifest.transcript_params_key}, транскрипт={actual or '—'}); "
                          f"preview всё равно показан, запись отказана",
                          file=sys.stderr, flush=True)
                    used_fallback_transcript = True
                else:
                    print(f"  ⚠ {stem}: params_key транскрипта расходится (манифест="
                          f"{manifest.transcript_params_key}, транскрипт={actual or '—'}) — resnap ОТКАЗАН",
                          file=sys.stderr, flush=True)
                    refused.append(mf.name)
                    continue

        reels = [r.model_copy(deep=True) for r in manifest.reels]
        _resnap_reels(reels, transcript, r0_cfg)
        n_changed = sum(1 for a, b in zip(manifest.reels, reels)
                        if (round(a.start, 3), round(a.end, 3)) != (round(b.start, 3), round(b.end, 3)))

        if dry_run:
            print(f"\n  [dry-run] {stem}: {n_changed}/{len(reels)} клипов изменятся", flush=True)
            for old_r, new_r in zip(manifest.reels, reels):
                old_start, old_end = round(old_r.start, 3), round(old_r.end, 3)
                new_start, new_end = round(new_r.start, 3), round(new_r.end, 3)
                changed = (old_start, old_end) != (new_start, new_end)
                marker = "→" if changed else "·"
                snap = new_r.end_snap_reason or "—"
                tail = _last_words_before(transcript.words, new_r.end)
                print(f"    {marker} {old_r.id}  {old_start:.3f}–{old_end:.3f}  "
                      f"→ {new_start:.3f}–{new_end:.3f}  snap={snap}  «{tail}»",
                      flush=True)
            skipped.append(mf.name)  # не считаем как updated (ничего не записано)
            continue

        if used_fallback_transcript:
            print(f"  ⚠ {stem}: запись отказана (fallback-транскрипт в non-dry-run — "
                  f"это не должно происходить)", file=sys.stderr, flush=True)
            refused.append(mf.name)
            continue

        _write_manifest(manifest.model_copy(update={"reels": reels}), manifests_dir)
        print(f"  ✓ {stem}: границы пересчитаны из R0 без LLM "
              f"({n_changed}/{len(reels)} клипов сдвинулись; тексты/субтитры/выбор те же)", flush=True)
        updated.append(mf.name)
        if push:
            _commit_push_manifest(manifests_dir / f"{stem}.json", len(reels), root=root)

    if video is None or len(targets) > 1:
        parts = [f"{len(updated)} пересчитано"]
        if no_r0:
            parts.append(f"{len(no_r0)} без R0-границ (нужен run)")
        if refused:
            parts.append(f"{len(refused)} отказано (транскрипт не подтверждён)")
        if skipped:
            parts.append(f"{len(skipped)} пропущено")
        print(f"\n=== resnap: {' / '.join(parts)} ===", flush=True)
    if updated:
        print("  → границы обновлены (R0 не пересчитывался). Дальше: arl r (render).", flush=True)
    return 0


_SIDECAR_SUFFIXES = (
    ".discarded.json",        # discarded candidates + blocks.discarded.json (suffix-match covers both)
    ".failed_chunks.json",
    ".blocks.topk_cut.json",
    ".blocks.json",           # block set sidecar written by cmd_blocks
)


def _glob_manifests(d: Path) -> list[Path]:
    """Sorted manifest paths in dir d, excluding sidecar files."""
    return sorted(p for p in d.glob("*.json")
                  if not any(p.name.endswith(s) for s in _SIDECAR_SUFFIXES))


def _auto_discover_manifests(root=None) -> list[Path]:
    """Glob manifests/*.json relative to project root (cwd-independent)."""
    manifests_dir = (Path(root) if root else _project_root()) / "manifests"
    return _glob_manifests(manifests_dir)


def cmd_dump_clips(manifests, *, out, root=None) -> int:
    """Выгрузить тексты клипов в JSON-фикстуры для разметки — БЕЗ ретранскрипции/LLM/ffmpeg/сети.

    Один клип → один файл <source_stem>__<index>.json. Текст восстанавливается ТОЛЬКО из
    word-level субтитров манифеста. Манифест не изменяется (инвариант неизменности).
    Фикстуру с проставленным label повторный прогон не трогает (ручная разметка переживает).
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    r0_cfg = load_r0_config((Path(root) if root else _project_root()) / "config" / "r0.yaml")

    written = skipped = 0
    n_cap = 0
    trunc_counts: dict = {}
    manifest_records_truncation = False   # манифест не хранит способ обрезки момента

    for mf in manifests:
        mf = Path(mf)
        try:
            manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  skip {mf.name}: {exc}", file=sys.stderr, flush=True)
            continue
        stem = Path(manifest.source).stem
        preset_max = r0_cfg.presets[manifest.duration_preset].max
        for i, r in enumerate(manifest.reels, 1):
            clip_id = f"{stem}__{i}"
            dest = out / f"{clip_id}.json"
            if dest.is_file():
                try:
                    prev = json.loads(dest.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    prev = {}
                if prev.get("label") is not None:
                    skipped += 1
                    continue
            duration = r.end - r.start
            hit_cap = abs(duration - preset_max) <= 1.0
            was_truncated = None   # манифест не фиксирует «pause» / «hard_time»
            if hit_cap:
                n_cap += 1
            trunc_counts[was_truncated] = trunc_counts.get(was_truncated, 0) + 1
            dest.write_text(json.dumps({
                "id": clip_id,
                "source": manifest.source,
                "start": r.start,
                "end": r.end,
                "duration": duration,
                "text": " ".join(w.word for w in r.subtitles),
                "hit_duration_cap": hit_cap,
                "was_truncated": was_truncated,
                "label": None,
                "label_note": None,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1

    # Orphan cleanup: delete unlabelled fixtures for processed stems whose index > reel count.
    stem_reel_counts: dict[str, int] = {}
    for mf in manifests:
        mf = Path(mf)
        try:
            manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        stem_reel_counts[Path(manifest.source).stem] = len(manifest.reels)
    deleted_orphans = 0
    for stem, reel_count in stem_reel_counts.items():
        idx = reel_count + 1
        while True:
            candidate = out / f"{stem}__{idx}.json"
            if not candidate.is_file():
                break
            try:
                prev = json.loads(candidate.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                prev = {}
            if prev.get("label") is None:
                candidate.unlink()
                print(f"  удалён orphan: {candidate.name}", flush=True)
                deleted_orphans += 1
            idx += 1

    total = written + skipped
    print(f"\n=== dump-clips: {written} записано / {skipped} пропущено (label) / {total} всего"
          f"{f' / {deleted_orphans} orphan удалено' if deleted_orphans else ''} ===",
          flush=True)
    print(f"  hit_duration_cap: {n_cap}", flush=True)
    trunc_line = ", ".join(f"{k}: {v}" for k, v in trunc_counts.items())
    print(f"  was_truncated: {trunc_line or '(нет клипов)'}", flush=True)
    if not manifest_records_truncation:
        print("  примечание: манифест НЕ хранит способ обрезки момента → was_truncated всегда null",
              flush=True)
    return 0


def _blocks_do_apply(review_path: str, *, root=None, cache_dir=None, manifests_dir=None, source: str | None = None, install: bool = False, render: bool = False, speed: float | None = None) -> int:
    """Build a manifest from a scored review file (M1.6 stage 4-alt).

    Entry point into the downstream pipeline is identical to after _stage_select in cmd_run:
    snap → filter_dangling_start → interview_snap → apply_top_n → renumber → padding →
    trim → min_clip_filter → subtitles → trim_hanging_subtitles → manifest.

    source: the manifest or transcript the review was exported from; overrides the '# source:'
    header in the review file (required when the header is absent; error when both present and
    different).
    """
    import json as _json
    import math as _math

    import re as _re

    from autoreels.cloud.blocks import (
        candidate_blocks, filter_blocks, score_block,
        parse_review, parse_compact_answer, merge_blocks, resolve_merge_groups, make_dataset_row,
    )
    from autoreels.cloud.compress import compress_transcript
    from autoreels.cloud.snap import trim_hanging_subtitles
    from autoreels.cloud.chunk_transcribe import renumber_reels
    from autoreels.core.models import Reel

    root = Path(root) if root is not None else _project_root()
    rpath = Path(review_path)
    # Bare filename (no directory) → look in reviews/ by default.
    if not rpath.is_absolute() and rpath.parent == Path("."):
        rpath = root / "reviews" / rpath
    review_content = rpath.read_text(encoding="utf-8")

    # Format detection: verbose has "[ N ] ... id=..." headers; everything else is compact answer.
    _is_compact = not _re.search(r"^\[\s*\d+\s*\].*\bid=", review_content, _re.MULTILINE)
    ignored_count = 0
    if _is_compact:
        source_ref, entries, errors, ignored_count = parse_compact_answer(review_content)
    else:
        source_ref, entries, errors = parse_review(review_content)

    for lineno, msg in errors:
        print(f"  review:{lineno}: {msg}", file=sys.stderr)
    if ignored_count:
        print(f"  ({ignored_count} lines skipped — not score lines)")

    # Resolve effective source: CLI arg takes precedence; header is fallback; conflict → refuse.
    if source_ref and source:
        # Normalise to absolute for comparison (different path spellings = same file)
        def _abs(p: str) -> Path:
            q = Path(p)
            return q if q.is_absolute() else (root / q)
        if _abs(source_ref).resolve() != _abs(source).resolve():
            print(
                f"error: source conflict — argument {source!r} ≠ header {source_ref!r}; "
                f"remove one or make them point to the same file",
                file=sys.stderr,
            )
            return 1
        effective_source = source
    elif source:
        effective_source = source
    elif source_ref:
        effective_source = source_ref
    else:
        print(
            "error: source not given — pass as argument (arl blocks <source> --apply <file>) "
            "or add '# source: <path>' to the review file",
            file=sys.stderr,
        )
        return 1

    source_file = Path(effective_source)
    if not source_file.is_absolute():
        source_file = root / effective_source

    if not source_file.exists():
        print(f"error: source not found: {source_file}", file=sys.stderr)
        return 1

    r0_cfg = load_r0_config(root / "config" / "r0.yaml")
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"

    # Load manifest + transcript.
    # Source can be a manifest (.json) or a cached transcript (.transcript.json).
    manifest: Manifest | None = None
    manifest_path: Path = source_file   # used for output filename stem
    transcript: Transcript | None = None

    if source_file.name.endswith(".transcript.json"):
        # Source is a transcript — load it directly, then look up a matching manifest.
        # Resolution chain: transcript.source_sha256 (stamped at transcription time) →
        # manifest in manifests/ with the same source_sha256.
        # For legacy transcripts (source_sha256=""), there is no reliable link; refuse clearly.
        transcript = Transcript.model_validate_json(source_file.read_text(encoding="utf-8"))
        matched_sha256 = transcript.source_sha256
        if not matched_sha256:
            print(
                f"error: transcript {source_file.name} has no source_sha256 stamp "
                f"(created before this field was added). "
                f"Missing fields: source, source_sha256, setup, run_key, duration_preset. "
                f"Run 'arl backfill-source-sha {source_file}' to add the link, "
                f"or re-run transcription so it is stamped automatically.",
                file=sys.stderr,
            )
            return 1
        # Find a manifest with this source_sha256 in manifests/.
        _mdir = Path(manifests_dir) if manifests_dir else root / "manifests"
        cands = [p for p in _glob_manifests(_mdir)
                 if not p.name.endswith(".review.json")]
        matched: list[tuple[Path, Manifest]] = []
        for p in cands:
            try:
                m = Manifest.model_validate_json(p.read_text(encoding="utf-8"))
                if m.source_sha256 == matched_sha256:
                    matched.append((p, m))
            except Exception:  # noqa: BLE001
                pass
        if not matched:
            print(
                f"error: no manifest in {_mdir} has source_sha256={matched_sha256[:16]}… "
                f"(from transcript {source_file.name}). "
                f"Missing fields: source, setup, run_key, duration_preset. "
                f"Run arl run first to produce a base manifest, then re-apply.",
                file=sys.stderr,
            )
            return 1
        # Most-recently modified manifest wins.
        manifest_path, manifest = max(matched, key=lambda t: t[0].stat().st_mtime)
    else:
        # Source is a manifest.
        manifest = Manifest.model_validate_json(source_file.read_text(encoding="utf-8"))

        # Load transcript from cache.
        audio = cache_dir / f"{manifest.source_sha256}.mp3"
        if audio.is_file():
            ahash = state.audio_hash(audio)
            pkey = manifest.transcript_params_key
            if pkey:
                exact = cache_dir / f"{ahash}.{pkey}.transcript.json"
                if exact.exists():
                    transcript = Transcript.model_validate_json(exact.read_text(encoding="utf-8"))
            if transcript is None:
                cands_tx = sorted(
                    cache_dir.glob(f"{ahash}*.transcript.json"),
                    key=lambda p: p.stat().st_mtime, reverse=True,
                )
                if cands_tx:
                    transcript = Transcript.model_validate_json(cands_tx[0].read_text(encoding="utf-8"))

    if transcript is None:
        print(f"error: transcript not found for {manifest_path.name}", file=sys.stderr)
        return 1

    # Stages 1-3: blocks → filter → score (heuristic scores needed for dataset)
    compressed = compress_transcript(
        transcript, pause_sec=r0_cfg.sentence_pause_sec, max_sentence_sec=r0_cfg.max_sentence_sec,
    )
    all_blocks = candidate_blocks(
        compressed,
        min_sec=r0_cfg.min_meaningful_sec,
        max_sec=r0_cfg.max_duration,
        min_pause_for_phrase_end=r0_cfg.min_pause_for_phrase_end,
        block_target_sec=getattr(r0_cfg, "block_target_sec", 40.0),
    )
    total_duration = all_blocks[-1].end if all_blocks else 0.0
    bf = r0_cfg.blocks_filter
    _source_kind = manifest.source_kind or r0_cfg.source_kind
    sc_affirmations = r0_cfg.host_affirmations if _source_kind == "interview" else []
    kept, dropped_blks = filter_blocks(
        all_blocks,
        total_duration=total_duration,
        head_skip_sec=bf.head_skip_sec,
        tail_skip_sec=bf.tail_skip_sec,
        speech_density_min=bf.speech_density_min,
        repetition_unique_ratio_min=bf.repetition_unique_ratio_min,
        artefact_markers=bf.artefact_markers,
        promo_keywords=bf.promo_keywords,
        signoff_phrases=bf.signoff_phrases,
        host_affirmations=sc_affirmations,
        min_sec=r0_cfg.min_meaningful_sec,
        max_sec=r0_cfg.max_duration,
    )
    bs_cfg = r0_cfg.block_scoring
    seq_to_block = {}
    for i, b in enumerate(kept, 1):
        b.heuristic_score, b.score_breakdown = score_block(b, bs_cfg)
        seq_to_block[i] = b

    # Process review entries → Reels.
    # seq_to_block maps 1..N to kept blocks by position; the verbose format also carries the
    # block id, which we cross-check to catch a stale review (blocks changed since export).
    seq_to_entry = {e.seq: e for e in entries}
    reels: list = []
    dataset_rows: list[dict] = []
    compact_lookup_errors = 0

    # Determine which seqs are eligible to merge/select (drop stale verbose ids, flag compact OOB).
    eligible: set[int] = set(seq_to_block)
    if _is_compact:
        for e in entries:
            if e.score is not None and e.seq not in seq_to_block:
                print(f"  error: block {e.seq} out of range (1-{len(kept)})", file=sys.stderr)
                compact_lookup_errors += 1
    else:
        for e in entries:
            if e.block_id and e.seq in seq_to_block and seq_to_block[e.seq].id != e.block_id:
                print(f"  warning: block {e.block_id[:8]}… (seq {e.seq}) does not match kept "
                      f"block (filtered or id mismatch) — skipped", file=sys.stderr)
                eligible.discard(e.seq)

    active = {s: seq_to_block[s] for s in eligible}
    _manual_max = getattr(r0_cfg, "manual_max_duration_sec", 180.0)
    groups, over_max = resolve_merge_groups(list(entries), active, _manual_max)
    for g in over_max:
        span = active[g[-1]].end - active[g[0]].start
        print(
            f"  error: merge {'+'.join(str(s) for s in g)} span ({span:.1f}s) exceeds "
            f"manual_max_duration_sec ({_manual_max:.0f}s) — refused",
            file=sys.stderr,
        )
    if over_max:
        return 1

    for g in groups:
        # Score = the EARLIEST scored block in the group (deterministic anchor).
        scored = [(s, seq_to_entry[s].score) for s in g
                  if s in seq_to_entry and seq_to_entry[s].score is not None]
        if not scored:
            continue                                   # no selection in this group → not a clip
        _anchor_seq, score = scored[0]
        block = merge_blocks([active[s] for s in g])
        is_merged = len(g) > 1
        if is_merged:
            block.heuristic_score, block.score_breakdown = score_block(block, bs_cfg)
            print(f"  + merged blocks {'+'.join(str(s) for s in g)}: {block.duration:.1f}s")

        reel = Reel(
            id=block.id,
            start=block.start,
            end=block.end,
            score=score,
            hook=block.text.split(".")[0][:300].strip() or block.text[:100],
            title="",
            description="",
            reason="human review",
        )
        reel.r0_start = reel.start
        reel.r0_end = reel.end
        if is_merged:
            reel.flags.append("human_merged")
        # Determine per-clip speed: marker > --speed arg > config default
        _entry_speed = seq_to_entry[_anchor_seq].speed if _anchor_seq in seq_to_entry else None
        _cfg_speed = getattr(r0_cfg, "speed", 1.0)
        _clip_speed = _entry_speed if _entry_speed is not None else (speed if speed is not None else _cfg_speed)
        _span = reel.end - reel.start
        _final_dur = _span / _clip_speed
        # Human merges are measured against manual_max_duration_sec (e.g. 180s), not the
        # preset ceiling (90s).  Auto-speed only kicks in when the span is above the manual
        # ceiling even at the requested speed.
        if _final_dur > _manual_max:
            _needed = _span / _manual_max
            if _needed > 1.3:
                _over = _span / 1.3 - _manual_max
                print(
                    f"  error: block(s) {'+'.join(str(s) for s in g)} span {_span:.1f}s needs "
                    f"{_needed:.2f}x to fit under manual ceiling {_manual_max:.0f}s "
                    f"(max allowed 1.3x; overshoots by {_over:.1f}s at 1.3x)",
                    file=sys.stderr,
                )
                return 1
            _auto = _math.ceil(_needed * 100) / 100
            if _clip_speed < _auto:
                _clip_speed = _auto
            print(
                f"  speed {'+'.join(str(s) for s in g)}: {_span:.1f}s → "
                f"{_span / _clip_speed:.1f}s at {_clip_speed:.2f}x (ceiling {_manual_max:.0f}s)",
                file=sys.stderr,
            )
        reel._clip_speed = _clip_speed   # stash for post-pipeline subtitle rescaling
        reels.append(reel)
        dataset_rows.append(make_dataset_row(block, score, manifest_path.stem))

    if _is_compact and compact_lookup_errors > 0 and len(reels) == 0:
        print(
            "error: answer references blocks not in this manifest — "
            f"manifest has {len(kept)} blocks (1-{len(kept)}), check source",
            file=sys.stderr,
        )
        return 1

    print(f"review: {len(reels)} blocks selected")

    # Downstream pipeline (entry point = after _stage_select in cmd_run)
    reels = _stage_snap(reels, transcript, r0_cfg=r0_cfg)
    tx_words = getattr(transcript, "words", [])
    host_turns = detect_host_turns(tx_words) if _source_kind == "interview" else []
    if host_turns:
        reels, _ = _stage_interview_snap(reels, host_turns, tx_words=tx_words, r0_cfg=r0_cfg)
    # Run after interview_snap: the START rule can pull r.start back to a host question that
    # itself ends in an ellipsis — the dangling fix must see the final post-snap start.
    reels, _ = filter_dangling_start(
        reels, tx_words,
        dangling_words=getattr(r0_cfg, "dangling_words", None),
        min_duration=r0_cfg.min_clip_duration,
    )
    # Human review: all selections are intentional — top-N must not drop any of them.
    reels, _ = apply_top_n(reels, max_reels=None, transcript_words=tx_words)
    reels = renumber_reels(reels)
    reels = _stage_padding(reels, transcript, r0_cfg=r0_cfg)
    reels = _stage_trim(reels, transcript, r0_cfg=r0_cfg)
    reels, _ = _stage_min_clip_filter(reels, transcript, r0_cfg=r0_cfg)
    reels, _ = _stage_meaningful_sec_recheck(reels, transcript, r0_cfg=r0_cfg)
    reels, density_disc = _stage_speech_density(reels, transcript, r0_cfg=r0_cfg)
    reels = _stage_subtitles(reels, transcript)
    trim_hanging_subtitles(reels, hanging_words=getattr(r0_cfg, "hanging_words", []))

    # Apply per-clip speed: rescale subtitle timings, stamp reel.speed.
    from autoreels.core.models import Word as _Word
    for reel in reels:
        _spd = getattr(reel, "_clip_speed", 1.0)
        if _spd != 1.0:
            reel.subtitles = [
                _Word(
                    word=w.word,
                    t0=reel.start + (w.t0 - reel.start) / _spd,
                    t1=reel.start + (w.t1 - reel.start) / _spd,
                )
                for w in reel.subtitles
            ]
        reel.speed = _spd

    # Assemble manifest with selection_source="human".
    # Stamp transcript_params_key from the transcript actually used (mirrors cmd_run at
    # _assemble_manifest). If the source manifest already carries a key it is preserved
    # only if the transcript loaded matches it; otherwise we stamp what we have.
    # source_path carried forward so downstream tools can locate the file.
    out_manifest = Manifest(
        source=manifest.source,
        source_path=manifest.source_path,
        source_sha256=manifest.source_sha256,
        source_hash_scheme=manifest.source_hash_scheme,
        source_kind=manifest.source_kind,
        duration_preset=manifest.duration_preset,
        setup=manifest.setup,
        run_key=manifest.run_key,
        transcript_params_key=transcript_identity(transcript),
        selection_source="human",
        reels=reels,
    )
    reviews_dir = root / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    out_path = reviews_dir / f"{manifest_path.stem}.review.json"
    out_path.write_text(out_manifest.model_dump_json(indent=2), encoding="utf-8")
    _write_discarded(density_disc, out_path)   # low_speech_density → sidecar рядом с ревью-манифестом
    print(f"manifest → {out_path} ({len(reels)} reels, selection_source=human)")

    # Install: copy to manifests/ so render picks up the human selection.
    # --render implies --install.
    if render:
        install = True
    manifests_dir = root / "manifests"
    installed_path = manifests_dir / f"{manifest_path.stem}.json"
    if install:
        import shutil as _shutil
        manifests_dir.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(out_path, installed_path)
        _write_discarded(density_disc, installed_path)   # и рядом с установленным манифестом
        print(f"installed → {installed_path}  (рендер будет использовать этот манифест)")
    else:
        print(
            f"  Чтобы рендерить эту выборку: arl blocks --apply <файл> --install\n"
            f"    (заменит {installed_path})"
        )

    if render:
        render_cfg = load_render_config(root / "config" / "render.yaml")
        if render_cfg.role == "analyze":
            print("  рендер пропущен: role=analyze запрещает рендер на этой машине",
                  file=sys.stderr)
            return 0
        cmd_render(root=root, _manifest_paths=[installed_path], pull_first=False)

    # Write dataset rows, deduplicating by (block_id, source).
    # A re-apply updates rows rather than appending duplicates.
    if dataset_rows:
        ds_dir = root / "data" / "blocks_dataset"
        ds_dir.mkdir(parents=True, exist_ok=True)
        ds_path = ds_dir / f"{manifest_path.stem}.jsonl"
        existing: dict[tuple, dict] = {}
        if ds_path.exists():
            for line in ds_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = _json.loads(line)
                    existing[(row["block_id"], row["source"])] = row
                except Exception:
                    pass
        before = len(existing)
        for row in dataset_rows:
            existing[(row["block_id"], row["source"])] = row
        collapsed = before - max(0, before - len(dataset_rows))
        if collapsed:
            print(f"dataset: {collapsed} duplicate rows collapsed")
        with ds_path.open("w", encoding="utf-8") as f:
            for row in existing.values():
                f.write(_json.dumps(row, ensure_ascii=False) + "\n")
        print(f"dataset: {len(dataset_rows)} rows written → {ds_path} ({len(existing)} total)")

    return 0


def cmd_blocks(
    target: str | None,
    *,
    root=None,
    cache_dir=None,
    scored: bool = False,
    review: bool = False,
    out: str | None = None,
    apply_review: str | None = None,
    install: bool = False,
    render: bool = False,
    compact: bool = False,
    speed: float | None = None,
) -> int:
    """Print candidate blocks with stage-2 filter verdicts (M1.6 stage 1+2).

    Loads the transcript, compresses it sentence-by-sentence, segments into candidate blocks
    (stage 1), then applies the deterministic pre-filter (stage 2).
    Writes a .blocks.dropped.json sidecar next to the manifest (when target is a manifest).
    Accepts a manifest (.json) or a transcript cache file (.transcript.json).

    --review: export a human-editable review file (stage 4-alt).
    --apply FILE: import a scored review file and build a manifest.
    """
    import json as _json
    import statistics

    from autoreels.cloud.blocks import (
        candidate_blocks, filter_blocks, score_block, topk_filter,
        export_review, export_compact_review, parse_review as _parse_review,
        make_dataset_row, _make_merged_block,
    )
    from autoreels.cloud.compress import compress_transcript

    root = Path(root) if root is not None else _project_root()
    if apply_review:
        return _blocks_do_apply(apply_review, root=root, cache_dir=cache_dir, source=target, install=install, render=render, speed=speed)

    if target is None:
        print("error: target required (or use --apply <review.md>)", file=sys.stderr)
        return 1

    target_path = Path(target)

    r0_cfg = load_r0_config(root / "config" / "r0.yaml")

    # Load transcript: transcript cache file → direct load; manifest → look up by sha + pkey
    transcript: Transcript | None = None
    manifest_path: Path | None = None
    manifest: Manifest | None = None
    if target_path.name.endswith(".transcript.json"):
        transcript = Transcript.model_validate_json(target_path.read_text(encoding="utf-8"))
    elif target_path.suffix == ".json":
        try:
            manifest = Manifest.model_validate_json(target_path.read_text(encoding="utf-8"))
            manifest_path = target_path
        except Exception as exc:
            print(f"ошибка разбора манифеста: {exc}", file=sys.stderr)
            return 1
        _cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"
        # Resolve: audio file (named by source_sha256) → audio content hash → transcript
        audio = _cache_dir / f"{manifest.source_sha256}.mp3"
        if audio.is_file():
            ahash = state.audio_hash(audio)
            pkey = manifest.transcript_params_key
            if pkey:
                exact = _cache_dir / f"{ahash}.{pkey}.transcript.json"
                if exact.exists():
                    transcript = Transcript.model_validate_json(
                        exact.read_text(encoding="utf-8")
                    )
            if transcript is None:
                cands = sorted(
                    _cache_dir.glob(f"{ahash}*.transcript.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if cands:
                    transcript = Transcript.model_validate_json(
                        cands[0].read_text(encoding="utf-8")
                    )
                    # Warn: using fallback (oldest/newest) because params_key is missing.
                    # A manifest without transcript_params_key was built before this field existed
                    # (legacy) — not corrupt, just old. Blocks/filter results are reliable only if
                    # the fallback transcript is the right one. Run `arl backfill-params-key` to fix.
                    used_pkey = transcript_identity(transcript) or "(orphan — no stamped metadata)"
                    if not pkey:
                        print(
                            f"  ⚠ {target_path.name}: transcript_params_key пуст (легаси-манифест) "
                            f"— использован последний транскрипт ({cands[0].name[:40]}…, "
                            f"params_key={used_pkey}). "
                            f"Для надёжной привязки: arl backfill-params-key",
                            file=sys.stderr,
                        )
    else:
        print(f"ошибка: ожидается .json (манифест) или .transcript.json: {target}",
              file=sys.stderr)
        return 1

    if transcript is None:
        print(f"ошибка: транскрипт не найден для {target}", file=sys.stderr)
        return 1

    compressed = compress_transcript(
        transcript,
        pause_sec=r0_cfg.sentence_pause_sec,
        max_sentence_sec=r0_cfg.max_sentence_sec,
    )
    all_blocks = candidate_blocks(
        compressed,
        min_sec=r0_cfg.min_meaningful_sec,
        max_sec=r0_cfg.max_duration,
        min_pause_for_phrase_end=r0_cfg.min_pause_for_phrase_end,
        block_target_sec=getattr(r0_cfg, "block_target_sec", 40.0),
    )

    total_duration = all_blocks[-1].end if all_blocks else 0.0
    bf = r0_cfg.blocks_filter
    # SC detection (host affirmations + dash signal) only makes sense for interview material.
    # Prefer manifest.source_kind (per-video) over r0_cfg.source_kind (config default).
    _source_kind = manifest.source_kind if manifest is not None else r0_cfg.source_kind
    sc_affirmations = r0_cfg.host_affirmations if _source_kind == "interview" else []
    kept, dropped = filter_blocks(
        all_blocks,
        total_duration=total_duration,
        head_skip_sec=bf.head_skip_sec,
        tail_skip_sec=bf.tail_skip_sec,
        speech_density_min=bf.speech_density_min,
        repetition_unique_ratio_min=bf.repetition_unique_ratio_min,
        artefact_markers=bf.artefact_markers,
        promo_keywords=bf.promo_keywords,
        signoff_phrases=bf.signoff_phrases,
        host_affirmations=sc_affirmations,
        min_sec=r0_cfg.min_meaningful_sec,
        max_sec=r0_cfg.max_duration,
    )

    # Build verdict map for output (all_blocks order preserved)
    drop_map: dict[str, str] = {b.id: r for b, r in dropped}

    # Always score all blocks (needed for sidecar; also pre-computes for --scored display below).
    bs_cfg_for_sidecar = getattr(r0_cfg, "block_scoring", None)
    if bs_cfg_for_sidecar is not None:
        for b in all_blocks:
            if b.heuristic_score == 0.0:
                b.heuristic_score, b.score_breakdown = score_block(b, bs_cfg_for_sidecar)

    # Write block-set sidecar next to the manifest (always, not only when --scored or --review).
    # Text omitted — recoverable from transcript by timecode; keeps the file small.
    if manifest_path is not None:
        sidecar_blocks = manifest_path.with_suffix(".blocks.json")
        sidecar_blocks_data = [
            {
                "id": b.id,
                "start": b.start,
                "end": b.end,
                "boundary_reason": b.boundary_reason,
                "verdict": drop_map.get(b.id, "KEPT"),
                "heuristic_score": round(b.heuristic_score, 2),
            }
            for b in all_blocks
        ]
        sidecar_blocks.write_text(
            _json.dumps(sidecar_blocks_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  → блок-сайдкар: {sidecar_blocks.name} "
              f"({len(all_blocks)} блоков, {sidecar_blocks.stat().st_size} байт)", flush=True)

    boundary_counts: dict[str, int] = {}
    drop_reason_counts: dict[str, int] = {}
    durations: list[float] = []
    sc_flag_count = 0
    for i, b in enumerate(all_blocks, 1):
        words = b.text.split()
        snippet = " ".join(words[:8]) + ("…" if len(words) > 8 else "")
        verdict = drop_map.get(b.id, "KEPT")
        flag = " [SC]" if getattr(b, "has_internal_speaker_change", False) else ""
        print(
            f"{i:3d} [{b.boundary_reason:13s}] {b.duration:5.1f}s  [{verdict:<12s}]{flag}  {snippet}",
            flush=True,
        )
        if verdict == "KEPT":
            boundary_counts[b.boundary_reason] = boundary_counts.get(b.boundary_reason, 0) + 1
            durations.append(b.duration)
            if b.has_internal_speaker_change:
                sc_flag_count += 1
        else:
            drop_reason_counts[verdict] = drop_reason_counts.get(verdict, 0) + 1

    # Write sidecar (naming mirrors .discarded.json — excluded by corpus tests' filter)
    if manifest_path is not None and dropped:
        sidecar = manifest_path.with_suffix(".blocks.discarded.json")
        sidecar_data = [
            {
                "id": b.id,
                "start": b.start,
                "end": b.end,
                "boundary_reason": b.boundary_reason,
                "reason": r,
                "first_words": " ".join(b.text.split()[:8]),
            }
            for b, r in dropped
        ]
        sidecar.write_text(_json.dumps(sidecar_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Stage 4-alt: export review file (only when --review)
    if review and kept:
        if out:
            out_path = Path(out)
        else:
            stem = manifest_path.stem if manifest_path else target_path.stem
            reviews_dir = root / "reviews"
            reviews_dir.mkdir(parents=True, exist_ok=True)
            out_path = reviews_dir / f"{stem}.review.md"
        # Warn if an existing review file already has scores — regenerating would discard them.
        if out_path.exists():
            _, _ex_entries, _ = _parse_review(out_path.read_text(encoding="utf-8"))
            if any(e.score is not None for e in _ex_entries):
                print(
                    f"  ВНИМАНИЕ: {out_path.name} уже содержит оценки — "
                    "перезапись сотрёт результаты ревью",
                    file=sys.stderr,
                )
        if compact:
            review_content = export_compact_review(
                kept, source_ref=str(target_path), filter_removed_count=len(dropped),
            )
        else:
            review_content = export_review(
                kept, source_ref=str(target_path), filter_removed_count=len(dropped),
            )
        out_path.write_text(review_content, encoding="utf-8")
        print(f"\nreview: {len(kept)} блоков → {out_path}  ({len(review_content)} chars)")
        if compact:
            print(f"  ↑ вставьте файл целиком в любой чат (промпт включён); "
                  f"ответ сохраните и передайте: arl blocks --apply <файл>")
        print(f"  ({len(dropped)} блоков удалено фильтрами — используйте arl blocks без --review для деталей)")
        return 0

    # Stage 3: heuristic scoring display (scores already computed above for the sidecar)
    topk_cut: list = []
    if scored and kept:
        bs_cfg = r0_cfg.block_scoring
        kept_scored, topk_cut = topk_filter(
            kept, chunk_window_sec=bs_cfg.chunk_window_sec, top_k=bs_cfg.top_k_per_chunk
        )

        # Print sorted by score descending
        print("\n--- SCORED (top-K kept, sorted by heuristic_score) ---")
        topk_cut_ids = {b.id for b in topk_cut}
        all_scored = sorted(kept, key=lambda b: b.heuristic_score, reverse=True)
        for rank, b in enumerate(all_scored, 1):
            verdict = "CUT(topk)" if b.id in topk_cut_ids else "KEPT"
            bd = b.score_breakdown
            words = b.text.split()
            snippet = " ".join(words[:10]) + ("…" if len(words) > 10 else "")
            print(
                f"{rank:3d} [{b.heuristic_score:5.1f}] {b.start:6.1f}-{b.end:6.1f}s "
                f"({b.duration:4.1f}s) [{verdict}]"
            )
            print(
                f"     +dur:{bd['duration']:.1f} +ends:{bd['ends_sentence']:.0f} "
                f"+open:{bd['opens_sentence']:.0f} +q:{bd['question']:.0f} "
                f"+contr:{bd['contrarian']:.0f} +lex:{bd['lexical']:.1f} "
                f"-dang:{-bd['dangling_ref']:.0f} -sc:{-bd['speaker_change']:.0f} "
                f"-dens:{-bd['density_penalty']:.0f}"
            )
            print(f"     {snippet}")

        if manifest_path is not None and topk_cut:
            sidecar_topk = manifest_path.with_suffix(".blocks.topk_cut.json")
            sidecar_topk.write_text(
                _json.dumps(
                    [
                        {
                            "id": b.id,
                            "start": b.start,
                            "end": b.end,
                            "boundary_reason": b.boundary_reason,
                            "heuristic_score": round(b.heuristic_score, 2),
                            "score_breakdown": b.score_breakdown,
                            "first_words": " ".join(b.text.split()[:8]),
                        }
                        for b in topk_cut
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        print(
            f"\nScoring: {len(kept)} блоков оценено → kept after top-K: {len(kept_scored)}, "
            f"cut by top-K: {len(topk_cut)}"
        )

    # Summary
    if all_blocks:
        print(f"\nВсего: {len(all_blocks)} блоков → Удержано: {len(kept)}, Удалено: {len(dropped)}")
        if drop_reason_counts:
            print(f"Удалено по причинам: {dict(sorted(drop_reason_counts.items()))}")
        if durations:
            print(
                f"Длительность (kept): min={min(durations):.1f}s, "
                f"median={statistics.median(durations):.1f}s, "
                f"max={max(durations):.1f}s"
            )
            print(f"По границам (kept): {dict(sorted(boundary_counts.items()))}")
        if sc_flag_count:
            print(f"Флаг speaker_change внутри блока: {sc_flag_count}")
    else:
        print("Блоков нет.")
    return 0


def cmd_resume(*, root=None, ffmpeg=None, encoder=None, profile=None) -> int:
    """Продолжить прерванное: доделать рендер недостающих клипов + сообщить о недокачках.

    Тяжёлые шаги проекта идемпотентны и «продолжаемы» by design: render дорисовывает
    недостающие клипы, докачка Я.Диска возобновляется по той же ссылке, run переиспользует
    кэш. Эта команда сводит их: локально чинит рендер, а по остальному даёт подсказку.
    """
    root = Path(root) if root is not None else _project_root()
    inputs = root / "inputs"
    manifests_dir = root / "manifests"
    out_root = root / "reels-out"
    did_something = False

    parts = sorted(inputs.glob("*.part")) if inputs.is_dir() else []
    if parts:
        did_something = True
        print(f"⚠ прерванные загрузки: {len(parts)} .part-файл(ов) в inputs/ —", flush=True)
        print("  повтори ту же ссылку (меню п.5 или arl run <url>): "
              "докачается с места обрыва.", flush=True)
        for p in parts:
            print(f"   • {p.name}", flush=True)

    pending: list[str] = []
    for mf in (_glob_manifests(manifests_dir) if manifests_dir.is_dir() else []):
        try:
            m = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
            if _missing_reels(m, out_root / Path(m.source).stem):
                pending.append(mf.name)
        except Exception:  # noqa: BLE001
            continue
    if pending:
        did_something = True
        print(f"дорендериваю {len(pending)} манифест(ов) с недостающими клипами…", flush=True)
        cmd_render(root=root, ffmpeg=ffmpeg, encoder=encoder, profile=profile)

    if not did_something:
        print("нечего продолжать — всё готово (нет .part и недорендеренных манифестов).",
              flush=True)
    return 0


def cmd_backfill_pkey(
    manifest_path: str,
    transcript_path: str | None = None,
    *,
    root=None,
    cache_dir=None,
    force: bool = False,
) -> int:
    """Stamp transcript_params_key on a manifest that lacks it.

    For manifests built before the field was added (legacy, selection_source="human" or LLM)
    or by an old --apply that did not stamp the key. Verifies the transcript is the right one
    by audio hash (if the mp3 is in cache) then writes the manifest in place.

    Refuses when:
    - the transcript has no stamped metadata (orphan, can't produce a valid key)
    - audio is in cache and audio_hash does not match the transcript filename prefix
    - manifest already has a non-empty transcript_params_key (unless --force)
    """
    root = Path(root) if root is not None else _project_root()
    _cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"
    audio_format: str | None = None  # resolved lazily when needed

    mpath = Path(manifest_path)
    if not mpath.is_absolute():
        mpath = root / mpath
    if not mpath.exists():
        print(f"ошибка: манифест не найден: {mpath}", file=sys.stderr)
        return 1

    try:
        manifest = Manifest.model_validate_json(mpath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"ошибка: не удалось разобрать манифест: {e}", file=sys.stderr)
        return 1

    stem = Path(manifest.source).stem

    if manifest.transcript_params_key and not force:
        print(
            f"  ⚠ {stem}: transcript_params_key уже установлен "
            f"({manifest.transcript_params_key}) — пропуск. "
            f"Передай --force чтобы перезаписать.",
            file=sys.stderr,
        )
        return 1

    # Resolve transcript
    if transcript_path is not None:
        tpath = Path(transcript_path)
        try:
            tr = Transcript.model_validate_json(tpath.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"ошибка: не удалось загрузить транскрипт: {e}", file=sys.stderr)
            return 1
    else:
        # Auto-discover from cache — load render.yaml only when needed
        render_cfg = load_render_config(root / "config" / "render.yaml")
        audio_format = render_cfg.audio_extract.format
        audio = _cache_dir / f"{manifest.source_sha256}.{audio_format}"
        if not audio.is_file():
            print(
                f"  ⚠ {stem}: mp3 не найден в кэше ({audio.name}) — "
                f"передай путь к транскрипту явно: arl backfill-params-key {mpath.name} <transcript>",
                file=sys.stderr,
            )
            return 1
        ahash = state.audio_hash(audio)
        tr, _ = _resolve_transcript(manifest, _cache_dir, audio_format=audio_format,
                                    config_pkey=_config_params_key(root))
        if tr is None:
            print(
                f"  ⚠ {stem}: транскрипт не найден в кэше (audio_hash={ahash[:16]}…) — "
                f"передай путь явно: arl backfill-params-key {mpath.name} <transcript>",
                file=sys.stderr,
            )
            return 1
        tpath = None

    # Verify transcript has stamped metadata
    new_pkey = transcript_identity(tr)
    if not new_pkey:
        print(
            f"  ⚠ {stem}: транскрипт не содержит штампованных мета-данных (orphan — "
            f"нет model/provider/prompt_hash) — нельзя получить надёжный params_key. "
            f"Нужен транскрипт с атрибутами модели (снятый после фичи штампования).",
            file=sys.stderr,
        )
        return 1

    # Audio-hash verification: if mp3 is in cache, check the transcript file name prefix.
    # Resolve audio_format lazily; fall back to "mp3" if render.yaml unavailable.
    if audio_format is None:
        try:
            render_cfg = load_render_config(root / "config" / "render.yaml")
            audio_format = render_cfg.audio_extract.format
        except Exception:  # noqa: BLE001
            audio_format = "mp3"
    audio = _cache_dir / f"{manifest.source_sha256}.{audio_format}"
    if audio.is_file() and transcript_path is not None:
        ahash = state.audio_hash(audio)
        tname = Path(transcript_path).name
        if not tname.startswith(ahash):
            print(
                f"  ⚠ {stem}: audio_hash={ahash[:16]}… не совпадает с префиксом транскрипта "
                f"({tname[:40]}) — ОТКАЗАН. Транскрипт не от этого источника.",
                file=sys.stderr,
            )
            return 1
    elif audio.is_file():
        # Auto-discovered — verified by _resolve_transcript above (same ahash lookup)
        pass
    else:
        # No mp3 in cache — can't verify by audio hash.
        print(
            f"  ⚠ {stem}: mp3 не найден в кэше — верификация по audio_hash пропущена. "
            f"Убедись, что транскрипт действительно от этого видео.",
            file=sys.stderr,
        )

    # Write manifest with stamped key
    updated = manifest.model_copy(update={"transcript_params_key": new_pkey})
    mpath.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"  ✓ {stem}: transcript_params_key установлен ({new_pkey})",
        flush=True,
    )
    return 0


def cmd_backfill_source_sha(
    transcript_paths: list[str],
    *,
    cache_dir: str | None = None,
    root=None,
    force: bool = False,
) -> int:
    """Stamp source_sha256 on legacy transcripts that lack it.

    Resolves by matching the transcript filename prefix (= sha256 of mp3 content at
    transcription time) to the mp3 files currently in cache.  Refuses when the mp3's
    current content hash does not match the transcript filename prefix (mp3 was
    re-extracted and the link is broken — re-run arl run to create a fresh transcript).

    Returns 0 only when every transcript was stamped or already had the field.
    """
    _root = Path(root) if root else _project_root()
    _cache = Path(cache_dir) if cache_dir else _root / "data" / "cache"

    errors = 0
    for tpath_str in transcript_paths:
        tpath = Path(tpath_str)
        if not tpath.is_absolute():
            tpath = _cache / tpath_str
        if not tpath.exists():
            print(f"  error: not found: {tpath}", file=sys.stderr)
            errors += 1
            continue

        tr = Transcript.model_validate_json(tpath.read_text(encoding="utf-8"))
        if tr.source_sha256 and not force:
            print(f"  skip {tpath.name}: source_sha256 already set ({tr.source_sha256[:16]}…)")
            continue

        # Extract audio_hash from the filename: {ahash}[.{pkey}].transcript.json
        stem = tpath.stem  # removes .json → "...transcript"
        if stem.endswith(".transcript"):
            stem = stem[:-len(".transcript")]
        ahash = stem.split(".")[0]

        # Scan mp3 files: find the one whose content hash matches ahash.
        found_sha: str | None = None
        for mp3 in _cache.glob("*.mp3"):
            if state.audio_hash(mp3) == ahash:
                found_sha = mp3.stem
                break

        if found_sha is None:
            print(
                f"  error: {tpath.name}: no mp3 in {_cache} has audio_hash={ahash[:16]}… "
                f"(mp3 was re-extracted or is missing). "
                f"Re-run 'arl run' to produce a fresh stamped transcript.",
                file=sys.stderr,
            )
            errors += 1
            continue

        updated = tr.model_copy(update={"source_sha256": found_sha})
        tpath.write_text(updated.model_dump_json(), encoding="utf-8")
        print(f"  ✓ {tpath.name}: source_sha256={found_sha[:16]}…")

    return 0 if errors == 0 else 1


def cmd_migrate_calibrations(
    *,
    root=None,
    inputs_dir=None,
    archive_dir=None,
    calibrations_dir=None,
    cache_dir=None,
) -> int:
    """Перенести РУЧНЫЕ калибровки со старого ключа (полный sha256) на актуальный partial-p1.

    До фикса cmd_calibrate писал кроп под полным sha256, а run ищет по partial-p1 → ручной
    кроп игнорировался (автокроп). Эта миграция находит видео по source_name (в inputs/ и
    inputs-archive/), считает его partial-ключ и перекладывает ручную калибровку туда
    (перекрывая автокроп — ручная важнее). Авто-калибровки не трогает. Идемпотентно.
    """
    root = Path(root) if root is not None else _project_root()
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    archive_dir = Path(archive_dir) if archive_dir else root / "inputs-archive"
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"

    # Имя файла → путь (inputs приоритетнее архива, но по содержимому они одинаковы).
    videos: dict[str, Path] = {}
    for d in (archive_dir, inputs_dir):
        if d.is_dir():
            for v in d.glob("*.mp4"):
                videos[v.name] = v

    migrated = 0
    for cf in sorted(calibrations_dir.glob("*.json")):
        try:
            rec = json.loads(cf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if rec.get("auto") or rec.get("setup_label") == "auto":
            continue  # авто не мигрируем
        name = rec.get("source_name")
        video = videos.get(name) if name else None
        if video is None:
            continue  # видео недоступно — сопоставить ключ не с чем
        partial = state.file_sha256_cached_fast(video, cache_dir)
        if cf.stem == partial:
            continue  # уже под актуальным ключом
        rec["source_sha256"] = partial
        (calibrations_dir / f"{partial}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  ✓ {name}: ручная калибровка → актуальный ключ {partial[:12]}…", flush=True)
        migrated += 1

    if migrated == 0:
        print("миграция калибровок: всё уже на актуальных ключах.", flush=True)
    else:
        print(f"миграция калибровок: перенесено {migrated}. "
              f"Перепроверь run/render — теперь возьмётся ручной кроп.", flush=True)
    return 0


# ---------------------------------------------------------------------- калибровка (batch)

def _calibration_kind(calibrations_dir: Path, sha: str) -> str:
    """Вернуть 'manual', 'auto', 'none' или 'corrupt' для видео по sha256."""
    path = calibration_path(calibrations_dir, sha)
    if not path.is_file():
        return "none"
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        return "auto" if rec.get("auto") or rec.get("setup_label") == "auto" else "manual"
    except Exception:  # noqa: BLE001
        return "corrupt"


def _manifest_calibration_desync(manifest, calibrations_dir) -> str | None:
    """Кроп в манифесте разошёлся с текущей калибровкой видео → манифест устарел.

    Кроп едет на системник ВНУТРИ манифеста (calibrations/ локальны, в .gitignore — системнику
    не нужны). Если видео откалибровали уже ПОСЛЕ run — калибровка обновилась, а манифест нет:
    рендер возьмёт старый кроп из манифеста. Возвращает текст «нужен повторный run» или None
    (синхронно, либо файла калибровки нет — сравнивать не с чем)."""
    path = calibration_path(Path(calibrations_dir), manifest.source_sha256)
    if not path.is_file():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        calib_crop = rec["crop"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None
    calib_rot = float(rec.get("rotation_deg", 0.0) or 0.0)
    manifest_rot = float(getattr(manifest.setup, "rotation_deg", 0.0) or 0.0)
    calib_pal = rec.get("palette")
    manifest_pal = getattr(manifest.setup, "palette", None)
    if (manifest.setup.crop.model_dump() == calib_crop and manifest_rot == calib_rot
            and manifest_pal == calib_pal):
        return None
    stem = Path(manifest.source).stem
    calib_is_manual = not (rec.get("auto") or rec.get("setup_label") == "auto")
    if manifest.setup.setup_id == "auto" and calib_is_manual:
        return (f"манифест {stem} создан с автокропом, но появилась ручная калибровка "
                f"→ arl recrop (обновить кроп без пересчёта R0)")
    return (f"манифест {stem}: кроп устарел (калибровка изменилась) "
            f"→ arl recrop (обновить кроп без пересчёта R0)")


def _manifest_sync_mark(video, manifests_dir, calibrations_dir) -> str:
    """Короткая метка состояния синхронизации для status: есть ли манифест и не устарел ли кроп.

    «манифест ✓» — синхронно; «манифест устарел → run» — калибровка новее (нужен run на Mac);
    «нет манифеста → run» — видео ещё не прогнано; «манифест повреждён» — не читается."""
    stem = Path(video).stem
    mf = Path(manifests_dir) / f"{stem}.json"
    if not mf.is_file():
        return "нет манифеста → run"
    try:
        manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return "манифест повреждён"
    if _manifest_calibration_desync(manifest, Path(calibrations_dir)):
        return "кроп устарел → recrop"
    return "манифест ✓"


def _warn_if_manifest_stale(video, *, root, calibrations_dir=None) -> str | None:
    """После calibrate: если для видео УЖЕ есть манифест с устаревшим кропом → предупредить.

    Ручная калибровка после run не применяется сама — манифест несёт старый (авто)кроп.
    Печатает предупреждение в stderr, возвращает его текст (или None, если манифеста нет/синхрон)."""
    root = Path(root) if root is not None else _project_root()
    stem = Path(video).stem
    mf = root / "manifests" / f"{stem}.json"
    if not mf.is_file():
        return None
    try:
        manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    cal_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"
    msg = _manifest_calibration_desync(manifest, cal_dir)
    if msg:
        print(f"\n  ⚠ {msg}", file=sys.stderr, flush=True)
    return msg


def _ask_batch_action(name: str, kind: str) -> str:
    """Интерактивный промпт для одного видео в calibrate --all. Точка подмены в тестах.

    manual — уже откалиброван вручную: предложить перекалибровать, Enter = оставить (быстрый
    проход по уже-готовым). auto/none — как раньше.
    """
    if kind == "manual":
        prompt = f"  {name}: кроп уже есть (ручной). [к]алибровать заново / Enter — оставить: "
        valid = ("к", "п", "k", "p", "")
        norm = {"k": "к", "p": "п", "": "п"}
        hint = "введите к или Enter"
    elif kind == "auto":
        prompt = f"  {name}: автокроп уже зафиксирован. [к]алибровать вручную / [п]ропустить? "
        valid = ("к", "п", "k", "p")
        norm = {"k": "к", "p": "п"}
        hint = "введите к или п"
    else:
        prompt = f"  {name}: кропа нет. [к]алибровать / [а]втокроп / [п]ропустить? "
        valid = ("к", "а", "п", "k", "a", "p")
        norm = {"k": "к", "a": "а", "p": "п"}
        hint = "введите к, а или п"
    while True:
        ans = input(prompt).strip().lower()
        if ans in valid:
            return norm.get(ans, ans)
        print(f"  {hint}")


def cmd_calibrate_batch(
    *,
    root=None,
    inputs_dir=None,
    calibrations_dir=None,
    cache_dir=None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> None:
    """Интерактивная калибровка пачки: проходит по inputs/*.mp4.

    Для КАЖДОГО видео (в т.ч. уже откалиброванного вручную) спрашивает, что делать —
    так браузер-калибратор доступен из меню даже когда все видео уже с кропом (иначе
    «Калибровать всё» молча ничего не делало). к → браузер; а → автокроп; п/Enter → оставить.
    В конце — сводка, чтобы всегда была видна реакция на выбор пункта меню.
    """
    root = Path(root) if root is not None else _project_root()
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"

    videos = sorted(inputs_dir.glob("*.mp4")) if inputs_dir.is_dir() else []
    if not videos:
        print("inputs/ пуст — нечего калибровать")
        return

    print(f"калибровка кропа: {len(videos)} видео в inputs/ "
          f"(к — браузер, а — автокроп, Enter — оставить как есть)", flush=True)

    failed: list[str] = []
    calibrated = 0   # открыли браузер / сохранили автокроп
    kept = 0         # оставили как есть (пропуск)
    for video in videos:
        # Изоляция per-video: битое/нечитаемое видео (напр. «moov atom not found» —
        # недокачанный/повреждённый mp4) не должно ронять весь обход. Ctrl-C (BaseException,
        # отмена калибровки) НЕ ловим — он должен прерывать, как и раньше.
        try:
            sha = state.file_sha256_cached_fast(video, cache_dir)
            kind = _calibration_kind(calibrations_dir, sha)
            if kind == "corrupt":
                print(f"  ⚠ {video.name}: повреждённый файл калибровки — пропуск "
                      f"(удалите {calibration_path(calibrations_dir, sha)} и повторите)")
                kept += 1
                continue

            action = _ask_batch_action(video.name, kind)

            if action == "п":
                kept += 1
                continue

            if action == "а":
                frame_size = _probe_frame_size_for_auto(video, ffprobe=ffprobe)
                crop = auto_crop(frame_size)
                save_calibration(
                    calibrations_dir,
                    source_name=video.name,
                    source_sha256=sha,
                    crop=crop,
                    frame=frame_size,
                    setup_label="auto",
                )
                print(f"  ⚙ автокроп зафиксирован: {video.name}")
                calibrated += 1

            elif action == "к":
                cmd_calibrate(video, setup_label=None, ffmpeg=ffmpeg, ffprobe=ffprobe)
                _warn_if_manifest_stale(video, root=root, calibrations_dir=calibrations_dir)
                calibrated += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ {video.name}: пропущен (не удалось обработать) — {e}",
                  file=sys.stderr, flush=True)
            failed.append(video.name)
            continue

    print(f"\nкалибровка завершена: {calibrated} обработано, {kept} оставлено без изменений"
          + (f", {len(failed)} с ошибками ({', '.join(failed)})" if failed else ""),
          flush=True)


# ------------------------------------------------------------------ diagnose-cuts (обрывы фраз)

def _config_params_key(root) -> str:
    """params_key, которым транскрибирует ТЕКУЩИЙ config/transcribe.yaml (для резолва легаси-
    манифестов без записанного отпечатка). Совпадает с pkey, который ставит cmd_run."""
    tcfg = load_transcribe_config(Path(root) / "config" / "transcribe.yaml")
    return params_key(_backend_meta(get_backend(tcfg)))


def _resolve_transcript(manifest, cache_dir, *, audio_format="mp3", config_pkey=""):
    """Загрузить транскрипт, на котором СОБРАН манифест, — строго по params_key.

    Приоритет: manifest.transcript_params_key (авторитетно) → config_pkey (легаси best-effort,
    только для read-only диагностики). НИКОГДА не откатывается к «сироте» без params_key
    (<hash>.transcript.json): другая пунктуация → фантомные обрывы при чтении и порча границ
    при resnap-записи. Возвращает (Transcript|None, expected_pkey).

    Резолв резнапа (запись) должен звать с config_pkey="" → только записанный в манифесте ключ."""
    audio = Path(cache_dir) / f"{manifest.source_sha256}.{audio_format}"
    if not audio.is_file():
        return None, None
    expected = manifest.transcript_params_key or config_pkey
    if not expected:                       # нет отпечатка — резолвить нечем (сироту не берём)
        return None, expected
    tp = state.transcript_cache_path(cache_dir, audio, expected)
    if not tp.is_file():
        return None, expected
    try:
        return Transcript.model_validate_json(tp.read_text(encoding="utf-8")), expected
    except Exception:  # noqa: BLE001
        return None, expected


def _rerun_reels(transcript, r0_cfg, root):
    """Честный пере-прогон детерминированного слоя от кэш-транскрипта: compress → select(LLM)
    → snap → pad → trim. Возвращает reels как в реальном run (для before/after по СВОДКЕ)."""
    compressed = compress_transcript(
        transcript, pause_sec=r0_cfg.sentence_pause_sec,
        max_sentence_sec=getattr(r0_cfg, "max_sentence_sec", None))
    system_text = (Path(root) / r0_cfg.prompts.system).read_text(encoding="utf-8")
    fewshot = json.loads((Path(root) / r0_cfg.prompts.fewshot).read_text(encoding="utf-8"))
    provider = build_pool(r0_cfg)
    provider.preflight()
    reels = select(compressed, system_text=system_text, fewshot=fewshot,
                   provider=provider, r0_cfg=r0_cfg)
    reels, _ = apply_top_n(reels, max_reels=r0_cfg.max_reels)
    snap_segments(reels, transcript.words, tail_sec=r0_cfg.tail_sec,
                  window_sec=r0_cfg.snap_window_sec, max_duration=r0_cfg.max_duration,
                  min_pause_for_phrase_end=r0_cfg.min_pause_for_phrase_end,
                  max_micro_pause=r0_cfg.max_micro_pause, hanging_words=r0_cfg.hanging_words,
                  max_end_search_sec=r0_cfg.max_end_search_sec,
                  min_clip_duration=r0_cfg.min_clip_duration)
    apply_padding(reels, transcript.words, tail_pad_sec=r0_cfg.tail_pad_sec,
                  lead_pad_sec=r0_cfg.lead_pad_sec, max_duration=r0_cfg.max_duration,
                  video_duration=transcript.words[-1].t1 if transcript.words else None,
                  hanging_words=r0_cfg.hanging_words)
    trim_too_long(reels, transcript.words, max_duration=r0_cfg.max_duration,
                  pause_sec=r0_cfg.sentence_pause_sec, policy=r0_cfg.too_long_policy)
    return reels


def _print_diag_table(stem, diags) -> None:
    print(f"\n### {stem}")
    print(f"  {'id':<4}{'dur':>6}  {'последние слова':<34}{'тип конца':<13}{'пауза':>6}  "
          f"{'вердикт':<8} причина")
    for d in diags:
        pa = f"{d.pause_after:.2f}" if d.pause_after is not None else "—"
        mark = {"CLEAN": "✓ ", "SOFT": "· ", "HARD": "⛔ "}.get(d.verdict, "")
        print(f"  {d.reel_id:<4}{d.duration:>5.1f}с {d.last_words[-33:]:<34}{d.end_type:<13}"
              f"{pa:>6}  {mark}{d.verdict:<5}{d.cause}")


def cmd_diagnose_cuts(target=None, *, root=None, rerun=False, cache_dir=None,
                      manifests_dir=None) -> int:
    """Классифицировать концы клипов: CLEAN / SOFT / HARD (обрыв) с причиной — быстрая проверка
    после правок snap/padding/рубрики.

    По умолчанию — анализ существующих манифестов (без LLM). `--rerun` — честный пере-прогон R0
    от кэш-транскрипта (для before/after: границы готового манифеста уже пост-snap+padding,
    сравнивать по ним НЕЛЬЗЯ — предупреждаем)."""
    root = Path(root) if root is not None else _project_root()
    r0_cfg = load_r0_config(root / "config" / "r0.yaml")
    render_cfg = load_render_config(root / "config" / "render.yaml")
    audio_format = render_cfg.audio_extract.format
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"

    if target:
        mf = manifests_dir / f"{Path(target).stem}.json"
        if not mf.is_file():
            print(f"нет манифеста для «{Path(target).stem}» в {manifests_dir}", file=sys.stderr, flush=True)
            return 1
        manifest_files = [mf]
    else:
        manifest_files = _glob_manifests(manifests_dir)
        if not manifest_files:
            print("manifests/ пуст — нечего диагностировать", flush=True)
            return 0

    if rerun:
        print("⚠ --rerun: честный пере-прогон R0 от кэш-транскрипта (реальный LLM). Это "
              "before/after по СВОДКЕ, НЕ по клипам: R0 недетерминирован и выбирает другие "
              "моменты. Сравнивать концы одних и тех же reel с манифестом нельзя — границы "
              "манифеста уже пост-snap+padding (дают ложные срабатывания).", flush=True)

    cfg = dict(min_pause=r0_cfg.min_pause_for_phrase_end, max_micro_pause=r0_cfg.max_micro_pause,
               tail_pad_sec=r0_cfg.tail_pad_sec, hanging_words=r0_cfg.hanging_words)
    config_pkey = _config_params_key(root)
    total = {"clean": 0, "soft": 0, "hard": 0, "causes": {}}
    analyzed = 0
    for mf in manifest_files:
        try:
            manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ битый манифест {mf.name}: {e}", file=sys.stderr, flush=True)
            continue
        transcript, expected = _resolve_transcript(
            manifest, cache_dir, audio_format=audio_format, config_pkey=config_pkey)
        if transcript is not None and not manifest.transcript_params_key:
            # Legacy manifest (built before transcript_params_key was added): best-effort fallback.
            # Not corrupt — just old. Diagnose results are reliable if the fallback is the right
            # transcript. Run `arl backfill-params-key` to pin the key.
            print(f"  ⚠ {mf.stem}: transcript_params_key пуст (легаси-манифест) — "
                  f"использован транскрипт конфига (params_key={expected}); "
                  f"для надёжной привязки: arl backfill-params-key",
                  file=sys.stderr, flush=True)
        if transcript is None:
            # НЕ подставляем «сироту»: неверное измерение хуже отсутствия измерения.
            why = ("нет аудио в кэше" if expected is None
                   else f"нет транскрипта с params_key={expected} (тот, на котором собран манифест)")
            print(f"  ⚠ {mf.stem}: {why} — пропуск", file=sys.stderr, flush=True)
            continue
        if rerun:
            print(f"  … пере-прогон R0: {mf.stem}", flush=True)
            reels = _rerun_reels(transcript, r0_cfg, root)
        else:
            reels = manifest.reels
        diags = [classify_end(r.id, r.start, r.end, transcript.words,
                              stored_reason=r.end_snap_reason, **cfg) for r in reels]
        _print_diag_table(mf.stem, diags)
        s = summarize(diags)
        for k in ("clean", "soft", "hard"):
            total[k] += s[k]
        for c, n in s["causes"].items():
            total["causes"][c] = total["causes"].get(c, 0) + n
        analyzed += 1

    if analyzed:
        n = total["clean"] + total["soft"] + total["hard"]
        print(f"\n=== ИТОГО ({'пере-прогон R0' if rerun else 'манифесты'}): "
              f"{total['clean']} clean · {total['soft']} soft · {total['hard']} HARD  из {n} клипов ===",
              flush=True)
        if total["causes"]:
            parts = ", ".join(f"{c}={n}" for c, n in sorted(total["causes"].items()))
            print(f"    причины HARD: {parts}", flush=True)
        if total["soft"]:
            print("    (soft = пауза 0.4–1.5с на нормальном слове — естественный вдох, приемлемо)",
                  flush=True)
    return 0


# --------------------------------------------------------------------------- status

def _print_history_table(runs: list[dict], *, indent: str = "  ") -> None:
    """Компактная таблица прогонов (новейшие первыми): время · исход · рилы · выборка · источник."""
    mark = {"ok": "✓", "zero-harvest": "∅", "failed": "✗", "skipped": "⊘"}
    print(f"{indent}{'время':<19}  {'исход':<12} {'рилы':>4}  {'выборка':<7}  источник")
    for r in runs:
        m = mark.get(r.get("outcome", ""), "?")
        oc = f"{m} {r.get('outcome', '?')}"
        print(f"{indent}{r.get('ts', ''):<19}  {oc:<12} {r.get('reel_count', 0):>4}  "
              f"{(r.get('selection_source') or 'auto'):<7}  {r.get('source', '')}")


def cmd_history(*, root=None, limit: int | None = None, outcome: str | None = None,
                history_path=None) -> int:
    """Полная история прогонов (JSONL под data/), новейшие первыми. `--limit`/`--outcome` фильтруют."""
    root = Path(root) if root is not None else _project_root()
    path = history.resolve_path(history_path, root)
    runs = history.read_runs(path, limit=limit, outcome=outcome)
    if not runs:
        suffix = f" (outcome={outcome})" if outcome else ""
        print(f"история пуста{suffix} — ещё ничего не прогонялось ({path})")
        return 0
    print(f"─── история прогонов ({len(runs)}{f', outcome={outcome}' if outcome else ''}) ───")
    _print_history_table(runs)
    print("────────────────────────────────────────────────────")
    return 0


def cmd_status(*, root=None, history_path=None, history_tail: int = 10) -> int:
    """Сводка текущего состояния проекта: inputs / manifests / reels-out / archive + предупреждения."""
    root = Path(root) if root is not None else _project_root()
    inputs_dir      = root / "inputs"
    manifests_dir   = root / "manifests"
    reels_out_dir   = root / "reels-out"
    archive_dir     = root / "inputs-archive"
    calibrations_dir = root / "calibrations"

    inputs    = sorted(inputs_dir.glob("*.mp4"))      if inputs_dir.is_dir()    else []
    manifests = _glob_manifests(manifests_dir) if manifests_dir.is_dir() else []
    rendered  = [d for d in reels_out_dir.iterdir() if d.is_dir()] \
                if reels_out_dir.is_dir() else []
    archived  = sorted(archive_dir.glob("*.mp4"))     if archive_dir.is_dir()   else []

    print("─── autoreels status ───────────────────────────────")
    print(f"  {_machine_settings_line(root)}")
    print(f"  inputs/          {len(inputs):>3} видео  (ждут run)")
    print(f"  manifests/       {len(manifests):>3} манифеста  (готовы к рендеру)")
    print(f"  reels-out/       {len(rendered):>3} папок  (отрендеренные видео)")
    print(f"  inputs-archive/  {len(archived):>3} архивных видео")

    cache_dir = root / "data" / "cache"

    # Per-file таблица: кроп + состояние синхронизации манифеста (нужен ли повторный run).
    if inputs:
        print()
        print("  ┌─ inputs/ ────────────────────────────────────────")
        for v in inputs:
            try:
                sha = state.file_sha256_cached_fast(v, cache_dir)
                kind = _calibration_kind(calibrations_dir, sha)
            except Exception:  # noqa: BLE001
                kind = "none"
            if kind == "manual":
                mark = "✓ кроп (ручной)"
            elif kind == "auto":
                mark = "⚙ автокроп"
            elif kind == "corrupt":
                mark = "⚠ калибровка повреждена"
            else:
                mark = "⚙ автокроп (нет калибровки)"
            print(f"  │ {v.name:<30}  {mark} · {_manifest_sync_mark(v, manifests_dir, calibrations_dir)}")
        print("  └──────────────────────────────────────────────────")

    # Предупреждения: манифесты без видео
    warnings: list[str] = []
    for mf in manifests:
        try:
            m = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
            src_name = Path(m.source).name
            in_inputs  = (inputs_dir  / src_name).is_file()
            in_archive = (archive_dir / src_name).is_file()
            if not in_inputs and not in_archive:
                warnings.append(
                    f"  ⚠ манифест без видео: {mf.name} "
                    f"(нет ни в inputs/, ни в inputs-archive/)"
                )
            desync = _manifest_calibration_desync(m, calibrations_dir)
            if desync:
                warnings.append(f"  ⚠ {desync}")
        except Exception:  # noqa: BLE001
            warnings.append(f"  ⚠ битый манифест: {mf.name}")

    if warnings:
        print()
        for w in warnings:
            print(w)

    # Хвост истории прогонов: последние N (не зависит от расположения файлов — отвечает на
    # «что я гонял недавно?», в т.ч. по in-place источникам, которых нет ни в inputs/, ни в архиве).
    recent = history.read_runs(history.resolve_path(history_path, root), limit=history_tail)
    if recent:
        print()
        print(f"  ┌─ последние прогоны ({len(recent)}) ─ полный список: arl history ─────")
        _print_history_table(recent, indent="  │ ")
        print("  └──────────────────────────────────────────────────")

    print("────────────────────────────────────────────────────")
    return 0


# --------------------------------------------------------------------------- doctor

# Имя env-переменной явного бинаря для подсказок doctor.
_TOOL_BINARY_ENV = {"ffmpeg": "FFMPEG_BINARY", "ffprobe": "FFPROBE_BINARY"}
# Источники, при которых путь задан ЯВНО (запуск надёжен независимо от PATH).
_EXPLICIT_TOOL_SOURCES = ("flag", "binary_env", "render_env", "config")


def _tool_status_line(res: ToolResolution, *, version_line: str | None, runnable: bool) -> str:
    """ЧЕСТНАЯ строка doctor по ToolResolution. «✓» — только если путь задан явно ИЛИ имя есть
    в PATH (ровно то, что делает рантайм: он зовёт этот же резолвнутый путь). Если бинарь найден
    лишь автопоиском (candidate/sibling), а в PATH его нет — это «⚠», а не «✓»: голое имя не
    разрешится, и держится всё на угаданном пути (хрупко, PATH после обновления Windows теряется)."""
    tool = res.name
    env = _TOOL_BINARY_ENV[tool]
    if not runnable:
        return f"  {tool:<16} ⚠ путь '{res.path}' задан, но бинарь не запускается — проверь путь"
    if res.source in _EXPLICIT_TOOL_SOURCES:
        where = {"flag": f"--{tool}", "binary_env": env,
                 "render_env": f"RENDER_{tool.upper()}", "config": "render.local.yaml"}[res.source]
        return f"  {tool:<16} ✓ {res.path}  (задан явно: {where})  ·  {version_line}"
    if res.in_path:
        return f"  {tool:<16} ✓ {res.path} (в PATH)  ·  {version_line}"
    if res.source in ("candidate", "sibling"):
        folder = str(Path(res.path).parent)
        return (f"  {tool:<16} ⚠ найден в {folder}, но каталога нет в PATH — по имени не "
                f"запустится, держится на автопоиске (хрупко). Добавь в PATH или задай {env}={res.path}")
    return (f"  {tool:<16} ⚠ не в PATH и путь не задан — запуск упадёт. "
            f"Добавь в PATH или задай {env}=<путь к бинарю>")


def _doctor_tool_line(tool: str, root, *, runner=None) -> str:
    """Строка doctor для ffmpeg/ffprobe через ЕДИНЫЙ резолвер (тот же, что и рантайм) + `-version`.

    Резолв идёт через _cli_resolve_ffmpeg_ex/resolve_ffprobe_ex — рантайм зовёт их же, поэтому
    doctor не может показать «найдено», когда рантайм упадёт. `runner` — точка подмены (тесты)."""
    import subprocess
    runner = runner or (lambda p: subprocess.run([p, "-version"], capture_output=True, text=True, timeout=10))
    try:
        if tool == "ffmpeg":
            res = _cli_resolve_ffmpeg_ex(None, root=root)
        else:
            res = resolve_ffprobe_ex(None, ffmpeg=_cli_resolve_ffmpeg(None, root=root))
    except FFmpegNotFoundError:
        env = _TOOL_BINARY_ENV[tool]
        return (f"  {tool:<16} ⚠ не найден (ни PATH, ни {env}, ни render.local.yaml, ни автопоиск) — "
                f"после обновлений Windows ffmpeg часто выпадает из PATH")
    version_line, runnable = None, False
    try:
        out = runner(res.path)
        blob = (getattr(out, "stdout", "") or getattr(out, "stderr", "") or "")
        version_line = blob.splitlines()[0] if blob.strip() else "(без вывода -version)"
        runnable = True
    except (OSError, subprocess.SubprocessError):
        runnable = False
    return _tool_status_line(res, version_line=version_line, runnable=runnable)


def cmd_doctor(*, root=None, probe=None, environ=None) -> int:
    """Преflight окружения: по пунктам печатает, что найдено и что сломано — ДО тяжёлой работы.

    Проверяет: .env (абсолютный путь / .env.txt), ключи провайдеров (ТОЛЬКО префикс, не секрет),
    live-доступность Groq/OpenRouter (короткий GET /models → 200/401/403/таймаут), ffmpeg/ffprobe
    (версия), python + entry-point, git-синк (флаги), каталоги проекта. Ничего не меняет, rc=0
    (диагностика, не гейт) — но чётко подсвечивает поломки, чтобы run/render не падали молча."""
    import sys as _sys
    from autoreels.cloud.providers import (
        GROQ_MODELS_URL, OPENROUTER_MODELS_URL, interpret_provider_status, probe_provider,
    )
    from autoreels.core.env import clean_key, key_prefix, scan_env

    environ = environ if environ is not None else os.environ
    probe = probe or (lambda url, api_key: probe_provider(url, api_key=api_key))
    root = Path(root) if root is not None else _project_root()

    print("─── autoreels doctor ───────────────────────────────")

    # 1) .env: откуда прочитан (абсолютный путь) + предупреждение про .env.txt
    rep = scan_env(root)
    if rep.path:
        print(f"  .env             {rep.path}")
    else:
        searched = ", ".join(str(p) for p in rep.searched) or str(root / ".env")
        print(f"  .env             ⚠ не найден (искал: {searched})")
    if rep.dotenv_txt:
        print(f"  ⚠ найден {rep.dotenv_txt.name} — Windows прячет расширения; переименуй в .env")

    # 2) ключи (только ПРЕФИКС) + live-проверка провайдера
    providers = [
        ("GROQ_API_KEY", "Groq", GROQ_MODELS_URL, True),
        ("OPENROUTER_API_KEY", "OpenRouter", OPENROUTER_MODELS_URL, False),
    ]
    for key_name, label, url, required in providers:
        val = clean_key(key_name, environ=environ)
        if not val:
            if required:
                print(f"  {key_name:<18} ⚠ НЕ ЗАДАН — R0/Whisper работать не будут (нужен для run)")
            else:
                print(f"  {key_name:<18} · не задан — распределение на OpenRouter выключено (опц.)")
            continue
        status = probe(url, val)
        _short, human = interpret_provider_status(status)
        icon = "✓" if status == 200 else "⚠"
        empty = "  ⚠ в .env пустой после очистки" if key_name in rep.empty_keys else ""
        print(f"  {key_name:<18} {key_prefix(val)}  → {label}: {icon} {human}{empty}")

    # 3) ffmpeg / ffprobe
    print(_doctor_tool_line("ffmpeg", root))
    print(_doctor_tool_line("ffprobe", root))

    # 4) python + entry-point (на Windows Py3.14 console-script иногда не кладётся в PATH)
    py = f"{_sys.version_info.major}.{_sys.version_info.minor}.{_sys.version_info.micro}"
    ep = shutil.which("autoreels")
    ep_note = (f"✓ entry-point autoreels в PATH ({ep})" if ep
               else "⚠ entry-point не в PATH — используй `python -m autoreels`")
    print(f"  python           {py}  ·  {ep_note}")

    # 5) git-синк (флаги двухмашинной синхронизации)
    sync = environ.get("AUTOREELS_GIT_SYNC")
    extra = f"  (AUTOREELS_GIT_SYNC={sync})" if sync is not None else ""
    print(f"  git-синк         pull {'вкл' if _should_git_pull() else 'ВЫКЛ'} · "
          f"push {'вкл' if _should_git_push() else 'ВЫКЛ'}{extra}")

    # 6) machine role
    try:
        _rcfg = load_render_config(root / "config" / "render.yaml")
        _role = _rcfg.role
        _encoder_profile = _rcfg.encoder.profile
    except Exception:
        _role = "both"
        _encoder_profile = "?"
    _CPU_ENCODERS = {"libx264", "libx265", "libsvtav1"}
    print(f"  role             {_role}")
    if _role in ("render", "both") and _encoder_profile in _CPU_ENCODERS:
        print(f"  ⚠ профиль {_encoder_profile!r} — CPU-кодировщик, рендер будет долгим (часы)")

    # 7) каталоги проекта
    for name in ("inputs", "manifests", "calibrations"):
        d = root / name
        if d.is_dir():
            n = sum(1 for _ in d.glob("*") if _.is_file())
            print(f"  {name:<15}  ✓ есть · {n} файлов")
        else:
            print(f"  {name:<15}  · нет (создастся при работе)")

    print("────────────────────────────────────────────────────")
    return 0


# ----------------------------------------------------------------------- smart hint

def _next_hint(root=".") -> str | None:
    """Подсказка следующего шага по состоянию проекта.

    Возвращает одну строку вида «→ arl go» или None если не очевидно что делать.
    Видео в inputs/ приоритетнее манифестов: сначала run, потом render.
    """
    root = Path(root) if root is not None else _project_root()
    inputs = list((root / "inputs").glob("*.mp4")) if (root / "inputs").is_dir() else []
    manifests = _glob_manifests(root / "manifests") if (root / "manifests").is_dir() else []

    if inputs:
        n = len(inputs)
        return f"→ {n} видео ждут обработки:  arl go"
    if manifests:
        n = len(manifests)
        return f"→ {n} манифест(а) готовы к рендеру:  arl r  (на системнике)"
    return None


# ----------------------------------------------------------------------------- меню

# Пункты меню: (цифра, action-токен, подпись, подсказка, ГРУППА). Сгруппировано по смыслу
# (действия / подготовка / качество / настройки / прочее), чтобы 13 пунктов вперемешку не
# путали. digit→action СТАБИЛЬНА; адаптивность (подсветка/пометки) — только оформление.
_MENU_ITEMS: list[tuple[str, str, str, str, str]] = [
    ("1", "go",         "Обработать видео из inputs/",
                        "анализ → манифест + транскрипт (сохраняется в transcripts/)", "ОСНОВНОЕ"),
    ("13", "go_render", "Анализ + рендер",
                        "анализ и сразу рендер на этой машине", "ОСНОВНОЕ"),
    ("2", "path",       "Обработать по ссылке или пути",
                        "URL / Яндекс.Диск / файл на диске", "ОСНОВНОЕ"),
    ("3", "render",     "Отрендерить манифесты",       "→ готовые рилсы", "ОСНОВНОЕ"),
    ("4", "calibrate",  "Калибровка кадра",
                        "кроп + палитра + горизонт в одном окне", "ПОДГОТОВКА"),
    ("5", "transcribe", "Только транскрипт",
                        "без рилсов — текст для контента (рилсы уже кладут транскрипт сами)",
                        "ПОДГОТОВКА"),
    ("6", "diagnose",   "Диагностика границ фраз",      "CLEAN/SOFT/HARD по клипам + причина",
                        "КАЧЕСТВО"),
    ("7", "resnap",     "Пересчитать границы",          "snap/padding из R0-границ, без LLM",
                        "КАЧЕСТВО"),
    ("12", "dumpclips",      "Выгрузить тексты клипов",      "→ фикстуры для разметки (tests/fixtures/clips/)",
                             "КАЧЕСТВО"),
    ("14", "review_export", "Экспорт блоков для ревью",    "blocks --review [--compact] → reviews/<stem>.review.md",
                             "КАЧЕСТВО"),
    ("15", "review_apply",  "Применить ревью",              "blocks --apply --install → manifest (human) · verbose и compact",
                             "КАЧЕСТВО"),
    ("8", "settings",   "Настройки рендера",            "профиль, палитра, музыка, звук",
                        "НАСТРОЙКИ"),
    ("9", "status",     "Статус",                        "", "ПРОЧЕЕ"),
    ("10", "resume",    "Продолжить прерванное",         "доделать рендер, докачки", "ПРОЧЕЕ"),
    ("11", "help",      "Справка",                        "", "ПРОЧЕЕ"),
    ("0", "quit",       "Выход",                          "", "ПРОЧЕЕ"),
]

# Подменю «Настройки рендера» (пункт 8): (цифра, токен, подпись, подсказка). back/пусто — назад.
_SETTINGS_ITEMS: list[tuple[str, str, str, str]] = [
    ("1", "profile", "Профиль кодека",       "скорость / качество / совместимость"),
    ("2", "palette", "Палитра по умолчанию", "neutral | vivid | soft | sharp"),
    ("3", "music",   "Фоновая музыка",        "вкл/выкл + трек из music/"),
    ("4", "audio",   "Нормализация звука",    "loudnorm -14 LUFS вкл/выкл"),
    ("0", "back",    "← Назад в меню",        ""),
]

# ЕДИНЫЙ ИСТОЧНИК диспетчеризации: action-токен пункта → его цель. Меню живёт в двух местах
# (Python рисует пункты и резолвит цифру→токен; bash-обёртка arl исполняет токен). Чтобы они
# не разъезжались, цель каждого токена описана здесь ОДИН раз, а тест сверяет, что каждый
# нарисованный пункт есть и здесь, и в bash-диспетчере (aliases.sh). Значение — либо имя
# РЕАЛЬНОЙ CLI-подкоманды (проверяется по argparse), либо «вид» для пунктов без прямой команды:
#   "interactive" — bash сам спрашивает ввод (ссылка/путь) и дальше зовёт CLI;
#   "config"      — сохранение настройки через `menu --set-*` (не отдельная подкоманда);
#   "meta"        — управление самим меню (выход/назад), CLI-команды нет.
# Добавил пункт в отрисовку, но забыл сюда или в bash-диспетчер → параметрический тест падает.
_MENU_CLI_TARGET: dict[str, str] = {
    "go": "run",
    "go_render": "run",
    "path": "interactive",
    "render": "render",
    "calibrate": "calibrate",
    "transcribe": "transcribe",
    "diagnose": "diagnose-cuts",
    "resnap": "resnap",
    "dumpclips":     "dump-clips",
    "review_export": "blocks",
    "review_apply":  "blocks",
    "settings": "interactive",
    "status": "status",
    "resume": "resume",
    "help": "help",
    "quit": "meta",
}
_SETTINGS_CLI_TARGET: dict[str, str] = {
    "profile": "config",
    "palette": "config",
    "music": "config",
    "audio": "config",
    "back": "meta",
}

# Профили рендера для меню: имя → человекочитаемое описание (кодек+битрейт — в render.yaml).
_RENDER_PROFILE_DESC = {
    "hevc":    "быстро · компактный ~18 МБ/клип (дефолт)",
    "hevc_hq": "быстро · лучше качество, крупнее файл (~40 МБ)",
    "h264":    "быстро · совместимый ~25 МБ",
    "h264_hq": "быстро · лучше+совместимый, крупный файл (~55 МБ)",
    "hevc_sw": "МЕДЛЕННО · максимум качества (софт libx265, для избранных)",
    "av1":     "быстро · экспериментально ~14 МБ",
}

# Текстовые псевдонимы выхода (кроме цифры 0) — удобство: q/exit/quit/выход.
_MENU_QUIT_ALIASES = {"q", "quit", "exit", "выход"}


_CLASSIFY_LABELS = {
    "yandex": "→ Яндекс.Диск",
    "url": "→ URL (yt-dlp: YouTube и пр.)",
    "path": "→ локальный файл",
}


def _classify_source(arg: str) -> str:
    """Распознать источник: 'yandex' / 'url' / 'path' (единый источник истины для меню)."""
    if _is_url(arg):
        return "yandex" if _is_yandex_disk(arg) else "url"
    return "path"


def _classify_label(arg: str) -> str:
    """Человеко-читаемая метка распознанного источника («→ Яндекс.Диск» и т.п.)."""
    return _CLASSIFY_LABELS[_classify_source(arg)]


def _menu_action(choice: str) -> str | None:
    """Парсинг выбора пользователя → action-токен (или None, если ввод невалиден).

    Стабильная карта: цифра пункта → его action; q/exit/quit/выход → quit. Мусор,
    пустая строка, число вне диапазона → None (bash повторит запрос / попадёт в *).
    """
    c = (choice or "").strip().lower()
    if c in _MENU_QUIT_ALIASES:
        return "quit"
    for num, action, _label, _hint, _group in _MENU_ITEMS:
        if c == num:
            return action
    return None


def _settings_action(choice: str) -> str | None:
    """Выбор в подменю настроек → токен (profile/palette/music/audio/back) или None.
    Пустой ввод (Enter) и q/exit/выход → back (промпт обещает «Enter — назад»)."""
    c = (choice or "").strip().lower()
    if c == "" or c in _MENU_QUIT_ALIASES:
        return "back"
    for num, action, _label, _hint in _SETTINGS_ITEMS:
        if c == num:
            return action
    return None


def _menu_state(root=".") -> dict[str, int]:
    """Счётчики состояния для шапки меню: inputs / manifests / rendered."""
    root = Path(root) if root is not None else _project_root()
    inputs = len(list((root / "inputs").glob("*.mp4"))) if (root / "inputs").is_dir() else 0
    manifests = len(_glob_manifests(root / "manifests")) if (root / "manifests").is_dir() else 0
    reels_out = root / "reels-out"
    rendered = len([d for d in reels_out.iterdir() if d.is_dir()]) if reels_out.is_dir() else 0
    return {"inputs": inputs, "manifests": manifests, "rendered": rendered}


def _recommended_action(state: dict[str, int]) -> str | None:
    """Рекомендуемый следующий шаг по состоянию: видео → go; иначе манифесты → render."""
    if state.get("inputs", 0) > 0:
        return "go"
    if state.get("manifests", 0) > 0:
        return "render"
    return None


def _current_render_profile(root=".") -> str:
    """Активный профиль рендера: env RENDER_PROFILE > render.local.yaml > render.yaml.

    Устойчиво к отсутствию/битому конфигу (шапка меню/статуса не должна падать) → 'hevc'."""
    env = os.environ.get("RENDER_PROFILE")
    if env:
        return env
    try:
        return load_render_config(Path(root) / "config" / "render.yaml").encoder.profile
    except (ConfigError, OSError):
        return "hevc"


def _current_ffmpeg_display(root=".") -> str:
    """Строка ffmpeg для шапки: резолвнутый путь/команда или пометка «не найден»."""
    try:
        return _cli_resolve_ffmpeg(None, root=root)
    except FFmpegNotFoundError:
        return "не найден (задай в render.local.yaml)"


def _profile_availability(root=".") -> dict:
    """{профиль: доступен ли его энкодер на этой машине} (пробный encode). Пусто — проверить
    нельзя (нет ffmpeg/конфига): тогда меню не помечает — не пугать ложным «недоступно»."""
    try:
        render_cfg = load_render_config(Path(root) / "config" / "render.yaml")
        ffmpeg = _cli_resolve_ffmpeg(None, root=root)
    except (ConfigError, OSError, FFmpegNotFoundError):
        return {}
    avail = {}
    for name in _RENDER_PROFILE_DESC:
        prof = render_cfg.encoder.profiles.get(name)
        if prof is not None:
            avail[name] = probe_encoder(prof.codec, ffmpeg=ffmpeg)
    return avail


def _machine_settings_line(root=".") -> str:
    """Строка машинных настроек для шапки: «роль both | профиль: hevc | ffmpeg: D:\\…»."""
    try:
        _rcfg = load_render_config(Path(root) / "config" / "render.yaml")
        _role = _rcfg.role
        _auto = " · авто-рендер" if _rcfg.auto_render else ""
    except Exception:
        _role = "both"
        _auto = ""
    return (f"настройки: роль {_role}{_auto}  |  профиль {_current_render_profile(root)}  |  "
            f"палитра {_current_render_palette(root)}  |  ffmpeg {_current_ffmpeg_display(root)}")


def set_render_profile(name: str, *, root=".") -> Path:
    """Сохранить профиль рендера в config/render.local.yaml (машинная настройка, не в git).

    Deep-merge в encoder.profile — прочие ключи (ffmpeg и т.п.) сохраняются. Применяется ко
    всем последующим рендерам на этой машине. Неизвестный профиль → ConfigError (fail-fast)."""
    import yaml
    if name not in _RENDER_PROFILE_DESC:
        known = ", ".join(_RENDER_PROFILE_DESC)
        raise ConfigError(f"неизвестный профиль '{name}'; допустимо: {known}")
    local = Path(root) / "config" / "render.local.yaml"
    data = {}
    if local.is_file():
        data = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
    encoder = data.get("encoder")
    if not isinstance(encoder, dict):
        encoder = {}
        data["encoder"] = encoder
    encoder["profile"] = name
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return local


def _render_palettes(root=".") -> dict:
    """{имя палитры: label} из render.yaml (+ render.local). Пусто при битом/отсутствующем конфиге."""
    try:
        cfg = load_render_config(Path(root) / "config" / "render.yaml")
    except (ConfigError, OSError):
        return {}
    return {name: pal.label for name, pal in cfg.palettes.items()}


def _current_render_palette(root=".") -> str:
    """Активная палитра: env RENDER_PALETTE > render.local.yaml > render.yaml. Фолбэк 'neutral'."""
    env = os.environ.get("RENDER_PALETTE")
    if env:
        return env
    try:
        return load_render_config(Path(root) / "config" / "render.yaml").palette
    except (ConfigError, OSError):
        return "neutral"


def set_render_palette(name: str, *, root=".") -> Path:
    """Сохранить палитру цветокора в config/render.local.yaml (машинная настройка, не в git).

    Deep-merge в поле palette — прочие ключи сохраняются. Неизвестная палитра → ConfigError."""
    import yaml
    known = _render_palettes(root)
    if known and name not in known:
        raise ConfigError(f"неизвестная палитра '{name}'; допустимо: {', '.join(known)}")
    local = Path(root) / "config" / "render.local.yaml"
    data = {}
    if local.is_file():
        data = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
    data["palette"] = name
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return local


# ------------------------------------------------------- настройки: музыка / звук (render.local)

def _load_local_yaml(root):
    import yaml
    local = Path(root) / "config" / "render.local.yaml"
    data = {}
    if local.is_file():
        data = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
    return local, data


def _save_local_yaml(local, data):
    import yaml
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def list_music_tracks(root=".") -> list[str]:
    """Имена файлов-треков в music/ (по расширениям). Пусто, если папки/треков нет."""
    d = Path(root) / "music"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.glob("*") if p.suffix.lower() in _MUSIC_EXTS)


def _current_music(root=".") -> tuple[bool, str | None]:
    """(включена ли музыка, имя трека) — env не участвует, только конфиг."""
    try:
        m = load_render_config(Path(root) / "config" / "render.yaml").music
        return bool(m.enabled), m.file
    except (ConfigError, OSError):
        return False, None


def set_render_music(value: str, *, root=".") -> Path:
    """Настроить фоновую музыку в render.local.yaml. value: 'off' → выкл; иначе имя трека → вкл
    с этим файлом. Deep-merge в секцию music (прочие ключи сохраняются)."""
    local, data = _load_local_yaml(root)
    music = data.get("music")
    if not isinstance(music, dict):
        music = {}
        data["music"] = music
    if value == "off":
        music["enabled"] = False
    else:
        music["enabled"] = True
        music["file"] = value
    _save_local_yaml(local, data)
    return local


def _current_audio_norm(root=".") -> bool:
    """Включена ли нормализация громкости (loudnorm) — из конфига."""
    try:
        return bool(load_render_config(Path(root) / "config" / "render.yaml")
                    .audio_processing.loudnorm_enabled)
    except (ConfigError, OSError):
        return True


def set_audio_normalization(on: bool, *, root=".") -> Path:
    """Вкл/выкл нормализацию громкости (loudnorm) в render.local.yaml (audio_processing)."""
    local, data = _load_local_yaml(root)
    ap = data.get("audio_processing")
    if not isinstance(ap, dict):
        ap = {}
        data["audio_processing"] = ap
    ap["loudnorm_enabled"] = bool(on)
    _save_local_yaml(local, data)
    return local


def _settings_render(root=".") -> str:
    """Текст подменю «Настройки рендера»: пункты с ТЕКУЩИМИ значениями."""
    prof = _current_render_profile(root)
    pal = _current_render_palette(root)
    mus_on, mus_file = _current_music(root)
    mus = f"вкл · {mus_file}" if (mus_on and mus_file) else ("вкл" if mus_on else "выкл")
    norm = "вкл" if _current_audio_norm(root) else "выкл"
    cur = {"profile": prof, "palette": pal, "music": mus, "audio": norm}
    lines = ["── Настройки рендера ─────────────────────────────────"]
    for num, action, label, hint in _SETTINGS_ITEMS:
        val = f": {cur[action]}" if action in cur else ""
        note = f"  ({hint})" if hint else ""
        lines.append(f"  {num}) {label}{val}{note}")
    lines.append("──────────────────────────────────────────────────────")
    return "\n".join(lines)


def _menu_render(root=".", *, platform: str | None = None) -> str:
    """Собрать текст адаптивного меню: шапка-состояние + пункты с подсветкой ▶.

    `platform` (sys.platform, инъекция для тестов) помечает пункты, неактуальные машине:
    run/go нужен Groq (обычно Mac), render — обычно системник Windows.
    """
    if platform is None:
        platform = sys.platform
    st = _menu_state(root)
    rec = _recommended_action(st)
    is_mac = platform == "darwin"
    is_win = platform == "win32"

    if is_win:
        border_top = "=== autoreels ======================================="
        border_mid = "---------------------------------------------------"
        marker_char = ">"
    else:
        border_top = "═══ autoreels ═══════════════════════════════════════"
        border_mid = "─────────────────────────────────────────────────────"
        marker_char = "▶"

    lines: list[str] = []
    lines.append(border_top)
    lines.append(
        f"  inputs: {st['inputs']} ждут  |  манифесты: {st['manifests']}  |  "
        f"готово: {st['rendered']}"
    )
    lines.append(f"  {_machine_settings_line(root)}")
    lines.append("")
    current_profile = _current_render_profile(root)
    current_palette = _current_render_palette(root)
    try:
        _menu_role = load_render_config(Path(root) / "config" / "render.yaml").role
    except Exception:
        _menu_role = "both"
    current_group = None
    for num, action, label, hint, group in _MENU_ITEMS:
        # Hide render-related items when role=analyze; hide go_render when role=analyze/render only.
        if action == "render" and _menu_role == "analyze":
            continue
        if action == "go_render" and _menu_role not in ("both", "render"):
            continue
        if group != current_group:                 # заголовок группы (действия/настройки/…)
            if current_group is not None:
                lines.append("")
            lines.append(f"  {group}")
            current_group = group
        marker = marker_char if action == rec else " "
        # Пункт настроек показывает текущий профиль/палитру прямо в подсказке.
        if action == "settings":
            note = f"  (профиль {current_profile} · палитра {current_palette})"
        else:
            note = f"  ({hint})" if hint else ""
        # Пометка неактуальных машине пунктов (не блокируем — только подсказка).
        if action == "go" and not is_mac:
            note += "  · нужен Groq (обычно Mac)"
        elif action == "render" and is_mac:
            note += "  · рендер обычно на системнике"
        rec_tag = "  <- рекомендую" if (action == rec and is_win) else ("  ← рекомендую" if action == rec else "")
        lines.append(f"  {marker} {num}) {label}{note}{rec_tag}")
    lines.append("")
    lines.append(border_mid)
    return "\n".join(lines)


# ----------------------------------------------------------------------- install-aliases

def _find_aliases_sh() -> Path:
    """Найти aliases.sh рядом с пакетом (корень репо)."""
    return Path(__file__).parent.parent.parent / "aliases.sh"


def _detect_shell_profile() -> Path:
    """Угадать профиль shell по $SHELL; фолбэк — ~/.bashrc."""
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        return Path.home() / ".zshrc"
    return Path.home() / ".bashrc"


def _posix_path_for_shell(path) -> str:
    """Путь для `source` в bash-профиле. На Windows (Git Bash/MSYS) — в POSIX-форме:
    `D:\\autoreels\\aliases.sh` → `/d/autoreels/aliases.sh`. Иначе backslashes Windows-пути
    съедаются как escape-последовательности в bash-строке ~/.bashrc и путь ломается
    (`source D:autoreelsaliases.sh` → файл не найден). Mac/Linux — путь как есть."""
    s = str(path)
    is_windows_path = "\\" in s or (len(s) >= 2 and s[1] == ":" and s[0].isalpha())
    if not is_windows_path:
        return s                                   # уже POSIX (Mac/Linux)
    import shutil as _sh
    import subprocess as _sp
    cyg = _sh.which("cygpath")                      # штатный конвертер Git Bash/MSYS
    if cyg:
        try:
            out = _sp.run([cyg, "-u", s], capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, _sp.SubprocessError):
            pass
    # Вручную: буква диска → /<буква>, backslash → slash.
    s = s.replace("\\", "/")
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        rest = s[2:]
        if not rest.startswith("/"):
            rest = "/" + rest
        return f"/{s[0].lower()}{rest}"
    return s


def cmd_install_aliases(
    *,
    profile_path: Path | None = None,
    aliases_path: Path | None = None,
    dry_run: bool = False,
    confirm: bool = True,
) -> int:
    """Дописать source-строку в профиль shell (один раз на машину).

    После этого алиасы из aliases.sh обновляются через git pull — без
    ручной правки профиля.
    """
    if aliases_path is None:
        aliases_path = _find_aliases_sh()
    if profile_path is None:
        profile_path = _detect_shell_profile()

    if not aliases_path.is_file():
        print(f"ошибка: aliases.sh не найден: {aliases_path}", file=sys.stderr)
        return 1

    # POSIX-путь: на Git Bash/MSYS Windows-путь с backslashes ломается в ~/.bashrc.
    source_line = f"source {_posix_path_for_shell(aliases_path.resolve())}"

    if dry_run:
        print(f"Добавит в {profile_path}:")
        print(f"  {source_line}")
        return 0

    existing = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    lines = existing.splitlines()

    def _refs_aliases(line: str) -> bool:
        """Строка автозагрузки aliases.sh (в т.ч. БИТАЯ: `source D:autoreelsaliases.sh`)."""
        st = line.strip()
        return "aliases.sh" in st and (st.startswith("source ") or st.startswith(". "))

    alias_lines = [l for l in lines if _refs_aliases(l)]
    correct_present = any(l.strip() == source_line for l in alias_lines)
    broken = [l for l in alias_lines if l.strip() != source_line]   # старые/битые записи

    if correct_present and not broken:
        print(f"✓ уже установлено в {profile_path}")
        return 0

    if confirm:
        if broken:
            print(f"В {profile_path} найдена битая/старая запись автозагрузки:")
            for b in broken:
                print(f"  ✗ {b.strip()}")
            print("Заменить на корректную:")
        else:
            print(f"Добавить в {profile_path}:")
        print(f"  {source_line}")
        ans = input("Продолжить? [д/н]: ").strip().lower()
        if ans not in ("д", "y", "yes"):
            print("отменено")
            return 0

    # Переписываем профиль: убираем ВСЕ строки автозагрузки aliases.sh (битые/дубли),
    # дописываем одну корректную POSIX-строку. Идемпотентно и чинит битую запись.
    kept = [l for l in lines if not _refs_aliases(l)]
    new_text = "\n".join(kept).rstrip("\n")
    new_text = (new_text + "\n") if new_text else ""
    new_text += f"{source_line}\n"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(new_text, encoding="utf-8")

    if broken:
        print(f"✓ исправлена запись автозагрузки в {profile_path}")
    else:
        print(f"✓ добавлено в {profile_path}")
    print(f"  Перезапусти shell или выполни: source {profile_path}")
    return 0


# ----------------------------------------------------------------------------- main

_CHEATSHEET = """\
autoreels — длинное видео → вертикальные Reels 9:16

Команды:
  status              состояние: исходники, кроп, манифесты, готовые рилсы
  calibrate <видео>   визуальная калибровка кропа (браузер)
  calibrate --all     пройтись по всем некалиброванным (интерактивно)
  run <видео>         анализ → манифест (Mac, нужен Groq; длинное → чанкинг авто)
  render              рендер по манифесту → reels-out/ (системник, AMF)
  help                расширенная справка: цикл, папки, частые случаи

Рабочий цикл:
  1. autoreels status                         # что где, нужен ли кроп
  2. autoreels calibrate --all                # настроить кадры (или пропустить → автокроп)
  3. autoreels run inputs/видео.mp4           # → manifests/<имя>.json
  4. autoreels render                         # → reels-out/<имя>/ (профиль hevc)

Папки: inputs/ · manifests/ · reels-out/ · inputs-archive/
autoreels <команда> --help — детали и флаги.\
"""

_HELP_EXTENDED = """\
autoreels — длинное talking-head видео → вертикальные Reels 9:16

━━━ КОРОТКИЕ КОМАНДЫ (autoreels install-aliases → работают в любом терминале) ━━

  arl              интерактивное меню (выбор цифрой, без ввода команд)
  arl menu         то же меню
  arl go           run всех видео + git push манифестов  (Mac, нужен Groq)
  arl go --no-push run без push
  arl r            render (git pull внутри; блокирует устаревший кроп)  (системник)
  arl rc [видео]   recrop: обновить кроп в манифесте по свежей калибровке (без R0)
  arl rs [видео]   resnap: пересчитать границы клипов из R0-границ (snap/padding, без LLM)
  arl dc [--rerun] diagnose-cuts: проверить обрывы фраз (CLEAN/SOFT/HARD + причина)

  ручной ревью (меню 14/15, или CLI напрямую):
    arl blocks <манифест> --review           подробный файл (редактировать в текстовом редакторе)
    arl blocks <манифест> --review --compact компактный: одна строка на блок + промпт → вставить в чат
    arl blocks --apply <файл> --install      применить ответ (оба формата; --install → manifests/)
    arl blocks --apply <файл> --render       применить + рендер сразу (подразумевает --install)
  arl s            status
  arl c            calibrate --all
  arl t <ист>      транскрибация (видео/аудио/url → текст для контента)
  arl h            эта справка
  arl <...>        передаёт команду в autoreels напрямую

  Команда называется arl (не ar — ar занят системным Unix-архиватором).

  Меню адаптивно: в шапке — состояние (inputs/манифесты/готово), ▶ помечает
  рекомендуемый шаг. Пункты 5 (обработать) и 6 (транскрибировать) после выбора
  спрашивают источник — ссылку (URL/Яндекс.Диск/YouTube) или путь к файлу, и
  показывают, что распознано. Пустой ввод — отмена. «0» или q — выход.

  Энкодер и путь к ffmpeg — в config/render.yaml (не нужны флаги):
    ffmpeg: ffmpeg              # Mac; Windows: D:\ffmpeg\bin\ffmpeg.exe
    encoder → codec: h264_amf  # Windows AMD; h264_nvenc NVIDIA; libx264 CPU

  Git-синхронизация (env, дефолт вкл): AUTOREELS_GIT_PULL=1 тянуть свежее,
    AUTOREELS_GIT_PUSH=1 пушить своё, AUTOREELS_GIT_SYNC=0 выключить оба.
    Системник (только рендер): AUTOREELS_GIT_PUSH=0 — тянет манифесты, не пушит.

━━━ ВСЕ КОМАНДЫ autoreels ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  status [--root .]
    Сводка состояния: inputs/ (ждут run), manifests/ (готовы к рендеру),
    reels-out/ (готовые клипы), inputs-archive/ (заархивированные).
    Per-file таблица кропа: ✓ ручной / ⚙ автокроп / ⚠ повреждён.

  calibrate <видео> [--setup МЕТКА] [--port 8765] [--ffmpeg путь] [--ffprobe путь]
    Визуальная калибровка кропа (9:16) одного видео — UI в браузере.
    Сохраняет профиль в calibrations/<sha256>.json.

  calibrate --all [--ffmpeg путь] [--ffprobe путь]
    Интерактивный обход всех inputs/*.mp4 без ручной калибровки.
    Для каждого спрашивает: [к]алибровать (браузер) / [а]втокроп / [п]ропустить.
    Уже откалиброванные вручную — пропускаются молча.

  run [видео|url] [--ffmpeg путь]
    Облачный тир (Mac, нужен Groq): аудио → Groq Whisper → транскрипт →
    Groq LLM → manifests/<имя>.json. GROQ_API_KEY задаётся в .env.
    Аргумент — путь куда угодно (напр. ~/Downloads/лекция.mp4): файл копируется
    в inputs/ (оригинал остаётся), дальше обычный конвейер.
    Аргумент — http/https-ссылка: скачивается в inputs/, затем обычный конвейер.
      • YouTube и пр. — yt-dlp (1080p max, --no-playlist); pip install 'autoreels[url]'.
      • Яндекс.Диск (disk.yandex.ru/i/…, yadi.sk) — public API + curl (без доп. пакетов;
        только файлы /i/, не папки /d/; большие файлы Я.Диск троттлит — качается долго).
    Без аргумента: batch по всем inputs/*.mp4.
    После успеха видео перемещается в inputs-archive/.

  transcribe <видео|аудио|url> [--format text|srt|vtt|json] [--ffmpeg путь]
    Отдельная транскрибация под контент (посты/статьи из сказанного).
    Источник — как у run (путь/аудио/http/Яндекс.Диск); длинное чанкится.
    text (дефолт) — связный текст, абзацы по паузам, без таймкодов;
    srt/vtt — субтитры с таймкодами; json — сырой word-level.
    Результат → transcripts/<имя>.<ext>. Нужен GROQ_API_KEY.

  render [--encoder КОДЕК] [--ffmpeg путь]
    Локальный тир (системник): manifests/*.json → reels-out/<стем>/<id>.mp4.
    Без флагов — берёт encoder и ffmpeg из config/render.yaml.
    Идемпотентен: уже готовые mp4 пропускаются; нет видео → предупреждение ⊘.

  resume
    Продолжить прерванное: дорендеривает манифесты с недостающими клипами
    и сообщает о недокачанных .part в inputs/ (повтори ту же ссылку — докачается).

  install-aliases [--dry-run] [--yes]
    Дописать source aliases.sh в профиль shell (~/.zshrc / ~/.bashrc).

  help
    Эта справка.

━━━ РАБОЧИЙ ЦИКЛ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ЭТАП 1 — подготовка (обычно Mac):

    1. Положить видео в inputs/
    2. arl s                 # (= autoreels status) — что видит: исходники, кропы
    3. arl c                 # (= calibrate --all)  — настроить кадры

  ЭТАП 2 — анализ (Mac, нужен Groq):

    4. arl go                # run всех видео → manifests/ + git push
       # (длинное >15 мин → чанкинг Whisper автоматически)

  ЭТАП 3 — рендер (системник Windows):

    5. arl r                 # git pull + render → reels-out/<имя>/
       # каждый клип: <id>.mp4 + <id>.txt с текстом поста

━━━ ВАЖНЫЕ ЗАМЕТКИ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  • Groq доступен НЕ везде (регион): run — только там где Groq работает (Mac);
    render Groq не нужен — идёт на любой машине.
  • Видео нужно на ОБЕИХ машинах: Mac (для run) и системник (для render).
    Манифест передаётся через git push/pull или Syncthing — видео не передаётся.
  • Нет ручной калибровки → автокроп 9:16 по центру кадра (run — молча).
  • Длинное видео → чанкинг включается автоматически (порог: 15 мин или 20 МБ).
  • Сегменты >90 с → обрезаются по ближайшей паузе (config: too_long_policy: trim).
  • Прогресс скачивания обновляет одну строку (\\r). Если терминал плодит строки —
    AUTOREELS_FORCE_TTY=1; для лога в файл — AUTOREELS_NO_TTY=1.

━━━ ПАПКИ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  inputs/           исходные видео (mp4, gitignore — гигабайты)
  inputs-archive/   видео после обработки (перемещаются автоматически)
  manifests/        JSON-задания для рендера (git-tracked: Mac → системник)
  reels-out/        готовые вертикальные клипы (gitignore)
  calibrations/     профили кропа по sha256 (gitignore)
  data/cache/       кэш аудио и транскриптов (gitignore)
  config/           r0.yaml, render.yaml, subtitles.yaml — все настройки

━━━ КОРОТКИЙ АЛИАС ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Один раз на каждой машине:
    autoreels install-aliases           # сам допишет source-строку в ~/.zshrc
  Или вручную добавь в ~/.zshrc (Mac) / ~/.bashrc (Windows Git Bash):
    source /путь/к/autoreels/aliases.sh

  Дальше алиасы обновляются через git pull (правишь aliases.sh, коммитишь).
  Затем: arl status · arl calibrate --all · arl run · arl render
\
"""


def cmd_models(*, root=None) -> int:
    """Показать доступные модели на Groq и OpenRouter, проверить сконфигурированные.

    Для Groq — проверка по каталогу (/models).
    Для OpenRouter — каталог + пинг каждой настроенной модели (проверяет shared-pool доступ,
    как это делает build_pool). Присутствие в каталоге не гарантирует доступ через shared pool.

    Возвращает 0 только если все настроенные модели доступны.
    Возвращает 1 если хотя бы одна отсутствует в каталоге или заблокирована shared pool.
    """
    from autoreels.cloud.providers import (
        GROQ_MODELS_URL, OPENROUTER_MODELS_URL, _list_models,
        _openrouter_shared_pool_blocked,
    )

    root = Path(root) if root is not None else _project_root()
    cfg_path = root / "config" / "r0.yaml"
    try:
        r0_cfg = load_r0_config(cfg_path)
        groq_configured = {"Groq model": r0_cfg.model}
        or_configured = {
            "OpenRouter model": r0_cfg.openrouter_model,
            **{f"OpenRouter fallback {i+1}": m
               for i, m in enumerate(r0_cfg.openrouter_fallback_models)},
        }
    except (ConfigError, OSError) as e:
        print(f"не удалось прочитать конфиг: {e}", file=sys.stderr)
        return 1

    groq_key = os.environ.get("GROQ_API_KEY")
    or_key = os.environ.get("OPENROUTER_API_KEY")

    groq_models = _list_models(
        GROQ_MODELS_URL,
        headers={"Authorization": f"Bearer {groq_key}"} if groq_key else {},
    ) if groq_key else None

    or_models_raw = _list_models(
        OPENROUTER_MODELS_URL,
        headers={"Authorization": f"Bearer {or_key}"} if or_key else {},
    )
    or_models = {m for m in (or_models_raw or set()) if m.endswith(":free")}

    # Print Groq live list
    if groq_key is None:
        print("Groq: нет GROQ_API_KEY — пропускаю")
    elif groq_models is None:
        print("Groq: недоступен (сеть/ошибка)")
    else:
        print(f"Groq ({len(groq_models)} моделей):")
        for m in sorted(groq_models):
            print(f"  {m}")

    print()

    # Print OpenRouter :free list
    if or_models_raw is None:
        print("OpenRouter: недоступен (сеть/ошибка)")
    else:
        print(f"OpenRouter free ({len(or_models)} бесплатных моделей):")
        for m in sorted(or_models):
            print(f"  {m}")

    print()

    # Check configured models: Groq — catalogue only; OpenRouter — catalogue + shared-pool ping
    problems: list[str] = []
    print("Сконфигурированные модели:")

    for label, model in groq_configured.items():
        if groq_models is None:
            status = "? (провайдер недоступен)"
        elif model in groq_models:
            status = "✓ OK"
        else:
            status = "✗ ОТСУТСТВУЕТ"
            problems.append(f"{label}: {model}")
        print(f"  {label}: {model}  [{status}]")

    for label, model in or_configured.items():
        if or_models_raw is None:
            status = "? (провайдер недоступен)"
        elif model not in or_models_raw:
            status = "✗ ОТСУТСТВУЕТ"
            problems.append(f"{label}: {model}")
        else:
            # Catalogue presence confirmed — now ping to verify shared-pool access
            if or_key:
                reason = _openrouter_shared_pool_blocked(model, or_key)
                if reason:
                    status = f"✗ НЕДОСТУПНА (shared pool / BYOK): {reason}"
                    problems.append(f"{label}: {model}")
                else:
                    status = "✓ OK"
            else:
                status = "? (нет OPENROUTER_API_KEY — пинг невозможен)"
        print(f"  {label}: {model}  [{status}]")

    if problems:
        print("\nПроблемные модели:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("Обнови config/r0.yaml (model / openrouter_model / openrouter_fallback_models).",
              file=sys.stderr)
        return 1
    return 0


def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="autoreels",
        description="Длинное talking-head видео → вертикальные Reels 9:16.",
        add_help=True,
    )
    sub = p.add_subparsers(dest="cmd", required=False)

    sub.add_parser("help", help="расширенная справка: полный цикл, папки, частые случаи")

    pm = sub.add_parser(
        "menu",
        help="печать интерактивного меню (цикл рисует bash-обёртка arl menu)",
        description=(
            "Печатает адаптивное меню (шапка-состояние + пункты с подсветкой ▶).\n"
            "Сам цикл (чтение цифры, запуск операций, возврат) — в bash-функции arl menu;\n"
            "эта подкоманда — «мозги»: рендер меню и разбор выбора.\n\n"
            "  autoreels menu                 — напечатать меню\n"
            "  autoreels menu --resolve 1     — цифра → action-токен (go/render/…/quit)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pm.add_argument("--resolve", default=None,
                    help="разобрать выбор пользователя в action-токен и выйти")
    pm.add_argument("--classify", default=None,
                    help="распознать источник (url/яндекс/путь) и напечатать метку")
    pm.add_argument("--set-profile", default=None, dest="set_profile",
                    help="сохранить профиль рендера (hevc|h264|av1) в render.local.yaml")
    pm.add_argument("--profiles", action="store_true",
                    help="напечатать доступные профили рендера с описанием")
    pm.add_argument("--set-palette", default=None, dest="set_palette",
                    help="сохранить палитру цветокора (neutral|vivid|soft|sharp) в render.local.yaml")
    pm.add_argument("--palettes", action="store_true",
                    help="напечатать доступные палитры цветокора с описанием")
    pm.add_argument("--settings", action="store_true",
                    help="напечатать подменю настроек рендера (профиль/палитра/музыка/звук)")
    pm.add_argument("--resolve-setting", default=None, dest="resolve_setting",
                    help="разобрать выбор в подменю настроек → токен (profile/palette/music/audio/back)")
    pm.add_argument("--music-tracks", action="store_true", dest="music_tracks",
                    help="напечатать список треков в music/")
    pm.add_argument("--set-music", default=None, dest="set_music",
                    help="настроить фоновую музыку: 'off' или имя трека из music/")
    pm.add_argument("--set-audio", default=None, dest="set_audio", choices=["on", "off"],
                    help="вкл/выкл нормализацию громкости (loudnorm)")
    pm.add_argument("--root", default=None, help="корень проекта (по умолчанию: проект)")

    ps = sub.add_parser(
        "status",
        help="сводка состояния: inputs / manifests / reels-out / archive + предупреждения",
        description=(
            "Показывает текущее состояние проекта:\n"
            "  • сколько видео ждут run (inputs/)\n"
            "  • сколько манифестов готовы к рендеру (manifests/)\n"
            "  • сколько папок уже отрендерено (reels-out/)\n"
            "  • сколько видео заархивировано (inputs-archive/)\n"
            "  • предупреждения: манифесты без видео, видео без калибровки\n\n"
            "Пример: autoreels status"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ps.add_argument("--root", default=None, help="корень проекта (по умолчанию: проект)")

    phist = sub.add_parser(
        "history",
        help="история прогонов (что уже гонялось) — не зависит от расположения файлов",
        description=(
            "Показывает историю прогонов из data/history.jsonl (append-only, не в git):\n"
            "  время · исход (ok/zero-harvest/failed/skipped) · рилы · выборка · источник.\n"
            "Отвечает на «я это уже обрабатывал?» без опоры на то, где лежит файл.\n\n"
            "Примеры:\n"
            "  autoreels history                 последние прогоны\n"
            "  autoreels history --limit 50      больше строк\n"
            "  autoreels history --outcome failed  только падения"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    phist.add_argument("--root", default=None, help="корень проекта (по умолчанию: проект)")
    phist.add_argument("--limit", type=int, default=None, help="сколько последних записей показать")
    phist.add_argument("--outcome", default=None, choices=list(history.OUTCOMES),
                       help="фильтр по исходу: ok | zero-harvest | failed | skipped")

    pdoc = sub.add_parser(
        "doctor",
        help="преflight окружения: .env, ключи, провайдеры (200/401/403), ffmpeg, git, каталоги",
        description=(
            "Проверяет окружение ДО тяжёлой работы и печатает по пунктам, что найдено/сломано:\n"
            "  • .env — откуда прочитан (абсолютный путь) или не найден; предупреждение про .env.txt\n"
            "  • ключи GROQ_API_KEY / OPENROUTER_API_KEY — только ПРЕФИКС (gsk_abcd…), не секрет\n"
            "  • live-проверка провайдеров: короткий запрос → 200 доступен / 401 ключ протух /\n"
            "    403 регион заблокирован / таймаут нет сети\n"
            "  • ffmpeg и ffprobe: найдены в PATH? версия?\n"
            "  • python: версия, работает ли entry-point autoreels или нужен python -m\n"
            "  • git-синк: pull/push вкл/выкл (AUTOREELS_GIT_SYNC/PULL/PUSH)\n"
            "  • каталоги inputs/manifests/calibrations: есть, сколько файлов\n\n"
            "Ничего не меняет. Пример: autoreels doctor"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pdoc.add_argument("--root", default=None, help="корень проекта (по умолчанию: проект)")

    pc = sub.add_parser(
        "calibrate",
        help="визуальная калибровка кропа (per-file или --all для пачки)",
        description=(
            "Открывает UI в браузере для настройки кадра кропа (9:16) конкретного видео.\n"
            "Сохраняет профиль в calibrations/<sha256>.json.\n"
            "Без калибровки run делает автокроп 9:16 по центру кадра с предупреждением.\n\n"
            "--all / --pending: интерактивный обход inputs/*.mp4 — спрашивает только для\n"
            "видео без ручной калибровки (к=браузер / а=автокроп / п=пропустить).\n\n"
            "Пример: autoreels calibrate inputs/лекция.mp4 --setup tearoom_main\n"
            "Пачка:  autoreels calibrate --all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pc.add_argument("video", nargs="?", default=None,
                    help="путь к видео для калибровки (не нужен с --all)")
    pc.add_argument("--all", dest="all", action="store_true", default=False,
                    help="интерактивный обход всех inputs/*.mp4 без ручной калибровки")
    pc.add_argument("--pending", dest="all", action="store_true",
                    help="псевдоним --all")
    pc.add_argument("--setup", default=None,
                    help="метка сетапа — имя позиции съёмки (→ setup_id в манифесте)")
    pc.add_argument("--ffmpeg", default=None,
                    help="путь к ffmpeg (иначе env RENDER_FFMPEG / render.local.yaml / автопоиск)")
    pc.add_argument("--ffprobe", default=None,
                    help="путь к ffprobe (иначе env RENDER_FFPROBE / PATH / рядом с ffmpeg)")
    pc.add_argument("--root", default=None,
                    help="корень проекта (по умолчанию: проект)")
    pc.add_argument("--port", type=int, default=8765,
                    help="порт localhost-сервера калибровки (по умолчанию: 8765)")
    pc.add_argument("--frame-at", default=None, dest="frame_at",
                    help="кадр для калибровки: '50%%' (доля длительности) или секунда ('120'). "
                         "По умолчанию ~40%% (не первый кадр); в браузере есть превью-сетка")

    pr = sub.add_parser(
        "run",
        help="транскрипция + выбор моментов → manifests/<стем>.json (облачный тир, нужен Groq)",
        description=(
            "Облачный тир: видео → аудио → Groq Whisper → транскрипт → Groq LLM → манифест.\n"
            "Нужен GROQ_API_KEY в .env. Видео за пределы машины не уходит.\n"
            "<видео> — путь куда угодно: файл вне inputs/ копируется в inputs/ (оригинал\n"
            "остаётся на месте), дальше обычный конвейер.\n"
            "<url> — ссылка: скачивается в inputs/, затем конвейер.\n"
            "  YouTube/пр. → yt-dlp (1080p, --no-playlist; pip install 'autoreels[url]');\n"
            "  Яндекс.Диск (disk.yandex.ru/i/…, yadi.sk) → public API + curl (файлы, не папки).\n"
            "Без аргумента: batch-обработка всех inputs/*.mp4.\n"
            "После успеха видео перемещается в inputs-archive/.\n\n"
            "Пример: autoreels run inputs/лекция.mp4\n"
            "Извне:  autoreels run ~/Downloads/лекция.mp4\n"
            "YouTube: autoreels run https://youtu.be/XXXX\n"
            "Я.Диск: autoreels run https://disk.yandex.ru/i/XXXX\n"
            "Batch:   autoreels run"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pr.add_argument("video", nargs="?", default=None, metavar="видео|url",
                    help="путь к видео (в т.ч. вне inputs/ — скопируется) или http/https-"
                         "ссылка (yt-dlp); без аргумента — batch: все *.mp4 из inputs/")
    pr.add_argument("--ffmpeg", default=None,
                    help="путь к ffmpeg (иначе env RENDER_FFMPEG / render.local.yaml / автопоиск)")
    pr.add_argument("--no-push", action="store_true",
                    help="не коммитить/пушить манифесты в git (по умолчанию каждый успешный "
                         "манифест сразу пушится на системник)")
    pr.add_argument("--force", action="store_true",
                    help="прогнать заново, даже если источник уже обработан (run_key совпал) "
                         "или манифест содержит ручную выборку (selection_source=human) — "
                         "перезапишет её, предупредив, сколько рилов выбрасывается")
    pr.add_argument("--force-transcribe", action="store_true",
                    help="перетранскрибировать безусловно, игнорируя кэш транскрипта и чанков "
                         "(нужно после смены initial_prompt/модели, если кэш уже прогрет)")
    pr.add_argument("--render", dest="auto_render", action="store_true",
                    help="после успешного анализа сразу запустить рендер (если role позволяет)")
    pr.add_argument("--no-parallel-render", dest="parallel_render", action="store_false",
                    help="не рендерить в фоне: ждать окончания рендера перед следующим "
                         "анализом (для слабых машин; по умолчанию фоновый рендер включён)")
    pr.set_defaults(parallel_render=True)

    ptx = sub.add_parser(
        "transcribe",
        help="видео/аудио/url → чистый текст (или srt/vtt/json) для генерации контента",
        description=(
            "Отдельная транскрибация под контент (посты/статьи из сказанного).\n"
            "Источник — как у run: путь (в т.ч. аудио), http/https, Яндекс.Диск.\n"
            "Длинное видео чанкится автоматически. Нужен GROQ_API_KEY.\n\n"
            "Форматы (--format):\n"
            "  text (дефолт) — связный текст, абзацы по паузам, БЕЗ таймкодов;\n"
            "  srt / vtt     — субтитры с таймкодами (плееры/YouTube);\n"
            "  json          — сырой word-level {word,t0,t1}.\n"
            "Результат → transcripts/<имя>.<ext>.\n\n"
            "Пример: autoreels transcribe inputs/лекция.mp4\n"
            "Субтитры: autoreels transcribe podcast.mp3 --format srt"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ptx.add_argument("source", nargs="?", default=None, metavar="видео|аудио|url",
                     help="путь к видео/аудио, http/https или ссылка Яндекс.Диска; "
                          "при --from-cache — необязателен (используется только для именования)")
    ptx.add_argument("--from-cache", default=None, metavar="HASH",
                     help="sha256-хэш аудио (64 hex-символа): читать транскрипт из кэша "
                          "без извлечения аудио и вызова Whisper. "
                          "Полезно когда видео на другой машине, а транскрипт уже закэширован.")
    ptx.add_argument("--format", choices=["text", "srt", "vtt", "json"], default="text",
                     help="формат вывода (по умолчанию: text — под контент)")
    ptx.add_argument("--ffmpeg", default=None,
                     help="путь к ffmpeg (иначе env RENDER_FFMPEG / render.local.yaml / автопоиск)")

    pd = sub.add_parser(
        "render",
        help="manifests/*.json → reels-out/ (локальный тир, ffmpeg)",
        description=(
            "Локальный тир: все манифесты в manifests/ → вертикальные mp4 в reels-out/.\n"
            "Идемпотентен: уже готовые клипы пропускаются; нет видео — предупреждение ⊘.\n"
            "Устаревший кроп (калибровка новее) авто-обновляется по калибровке (↻, без LLM);\n"
            "--no-auto-recrop — строго блокировать; --allow-stale — рендерить старый кроп.\n"
            "Кодек — профилем: hevc (дефолт, компактный) | h264 (совместимый) | av1 (эксп.).\n"
            "Профили нацелены на AMF (системник Windows AMD) — достаточно --ffmpeg.\n\n"
            "Пример: autoreels render --profile hevc\n"
            "Windows: autoreels render --ffmpeg D:\\ffmpeg\\bin\\ffmpeg.exe"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd.add_argument("--profile", default=None,
                    help="кодек-профиль: h264 (совместимый) | hevc (компактный, дефолт) | av1 (эксп.)")
    pd.add_argument("--palette", default=None,
                    help="палитра цветокора: neutral (дефолт) | vivid | soft | sharp")
    pd.add_argument("--zoom", choices=["on", "off"], default=None,
                    help="эффект зума (hook): on|off переопределяет config zoom.enabled")
    pd.add_argument("--music", default=None,
                    help="фоновая музыка: путь к треку или имя файла в music/ (переопределяет config)")
    pd.add_argument("--encoder", default=None,
                    help="видеокодек ffmpeg (переопределяет кодек профиля; h264_amf — AMD, libx264 — CPU)")
    pd.add_argument("--ffmpeg", default=None,
                    help="путь к ffmpeg (иначе env RENDER_FFMPEG / render.local.yaml / автопоиск)")
    pd.add_argument("--no-fallback", action="store_true", dest="no_fallback",
                    help="не подбирать доступный энкодер автоматически (av1→hevc→h264); "
                         "недоступный выбранный → ошибка")
    pd.add_argument("--allow-stale", action="store_true", dest="allow_stale",
                    help="рендерить даже если кроп в манифесте устарел (калибровка новее); "
                         "по умолчанию устаревший кроп авто-обновляется по калибровке")
    pd.add_argument("--no-auto-recrop", action="store_true", dest="no_auto_recrop",
                    help="не авто-применять калибровку при устаревшем кропе (строго блокировать, "
                         "как раньше — обновлять вручную через arl recrop)")

    ppv = sub.add_parser(
        "preview",
        help="короткий фрагмент клипа в нескольких палитрах — подобрать цветокор без полного рендера",
        description=(
            "Рендерит ОДИН короткий фрагмент (по умолч. 6с) первого клипа манифеста в НЕСКОЛЬКИХ\n"
            "палитрах — быстрое сравнение цветокора, вместо рендера всех 13 клипов.\n"
            "Выход: reels-out/_preview/<id>__<палитра>.mp4 (субтитры не выжигаются — чистый цвет).\n\n"
            "Пример: autoreels preview лекция --palettes neutral,vivid,sharp\n"
            "Все пресеты: autoreels preview лекция"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ppv.add_argument("manifest", nargs="?", default=None, metavar="манифест",
                     help="имя/стем/путь манифеста (без аргумента — первый в manifests/)")
    ppv.add_argument("--palettes", default=None,
                     help="список палитр через запятую (по умолчанию — все пресеты)")
    ppv.add_argument("--seconds", type=float, default=6.0,
                     help="длина фрагмента в секундах (5–8 удобно; по умолчанию 6)")
    ppv.add_argument("--reel", default=None, dest="reel",
                     help="id клипа для превью (по умолчанию — первый в манифесте)")
    ppv.add_argument("--zoom", choices=["on", "off", "compare"], default=None,
                     help="эффект зума: on|off|compare (compare рендерит оба — с зумом и без)")
    ppv.add_argument("--profile", default=None, help="кодек-профиль (как у render)")
    ppv.add_argument("--encoder", default=None, help="видеокодек ffmpeg (как у render)")
    ppv.add_argument("--ffmpeg", default=None,
                     help="путь к ffmpeg (иначе env RENDER_FFMPEG / render.local.yaml / автопоиск)")

    prs = sub.add_parser(
        "resume",
        help="продолжить прерванное: доделать рендер недостающих клипов + подсказки по докачкам",
        description=(
            "Продолжает прерванную работу за счёт идемпотентности проекта:\n"
            "  • дорендеривает манифесты с недостающими клипами (render идемпотентен);\n"
            "  • сообщает о .part в inputs/ (недокачанные — повтори ту же ссылку).\n\n"
            "Пример: autoreels resume"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    prs.add_argument("--profile", default=None, help="кодек-профиль (как у render): h264|hevc|av1")
    prs.add_argument("--encoder", default=None, help="видеокодек ffmpeg (как у render)")
    prs.add_argument("--ffmpeg", default=None, help="путь к ffmpeg (иначе из render.yaml)")

    prc = sub.add_parser(
        "recrop",
        help="обновить только кроп в существующем манифесте по свежей калибровке (без R0)",
        description=(
            "Обновляет ТОЛЬКО crop в манифесте по актуальной калибровке — без пересчёта R0\n"
            "(LLM, чанки, квоты). Границы клипов, тексты, субтитры не меняются. Нужно после\n"
            "перекалибровки, когда манифест уже построен: не гнать run заново.\n"
            "Без <видео> — batch по всем манифестам с устаревшим кропом. Авто-push.\n\n"
            "Пример: autoreels recrop            # все устаревшие\n"
            "        autoreels recrop video.mp4  # одно видео"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    prc.add_argument("video", nargs="?", default=None, metavar="видео",
                     help="конкретное видео (иначе — все манифесты с устаревшим кропом)")
    prc.add_argument("--no-push", action="store_true", dest="no_push",
                     help="не пушить обновлённый манифест в git")

    pdc = sub.add_parser(
        "diagnose-cuts",
        help="классифицировать концы клипов: CLEAN/SOFT/HARD (обрыв фразы) с причиной",
        description=(
            "Проверка обрывов фраз после правок snap/padding/рубрики. По каждому клипу — тип\n"
            "конца (фраза/пауза/висячее/запятая/мид-слово), вердикт CLEAN/SOFT/HARD и причина\n"
            "HARD (PAD-хвост / snap-fallback). Быстро, без LLM — по существующим манифестам.\n\n"
            "--rerun — честный пере-прогон R0 от кэш-транскрипта (before/after по СВОДКЕ после\n"
            "правок; границы готового манифеста уже пост-snap+padding, по ним сравнивать нельзя).\n\n"
            "Пример: autoreels diagnose-cuts            # все манифесты\n"
            "        autoreels diagnose-cuts video.mp4  # одно\n"
            "        autoreels diagnose-cuts --rerun    # честный пере-прогон R0"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pdc.add_argument("target", nargs="?", default=None, metavar="видео|манифест",
                     help="конкретное видео/манифест (иначе — все манифесты)")
    pdc.add_argument("--rerun", action="store_true",
                     help="честный пере-прогон R0 от кэш-транскрипта (для before/after по сводке)")

    prn = sub.add_parser(
        "resnap",
        help="пересчитать границы клипов из сохранённых R0-границ (snap→padding→trim, без LLM)",
        description=(
            "Пересчитывает ГРАНИЦЫ клипов из сохранённых R0-границ (r0_start/r0_end) текущим\n"
            "кодом snap→padding→trim — БЕЗ повторного R0/LLM/квот. Для проверки правок\n"
            "snap/padding без пересборки: те же моменты, тексты, субтитры — меняются лишь границы.\n"
            "Транскрипт берётся из кэша. Без <видео> — batch по всем манифестам.\n"
            "Манифест без r0_start (снят до фичи) → нужен ОДИН полный run, дальше resnap бесплатен.\n\n"
            "Пример: autoreels resnap            # все манифесты\n"
            "        autoreels resnap video.mp4  # одно"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    prn.add_argument("video", nargs="?", default=None, metavar="видео",
                     help="конкретное видео (иначе — все манифесты)")
    prn.add_argument("--no-push", action="store_true", dest="no_push",
                     help="не пушить обновлённый манифест в git")
    prn.add_argument("--dry-run", action="store_true", dest="dry_run", default=False,
                     help="показать что изменится (per-reel: границы, snap-причина, последние слова), "
                          "ничего не записывать и не пушить")

    sub.add_parser(
        "migrate-calibrations",
        help="перенести ручные калибровки со старого ключа (полный sha) на актуальный",
        description=(
            "Разовая миграция: ручные калибровки, сохранённые до фикса ключа (под полным\n"
            "sha256), переносятся на актуальный partial-p1 ключ — чтобы run брал ручной\n"
            "кроп, а не автокроп. Видео ищутся по имени в inputs/ и inputs-archive/.\n\n"
            "Пример: autoreels migrate-calibrations"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    pi = sub.add_parser(
        "install-aliases",
        help="дописать source aliases.sh в профиль shell (~/.zshrc / ~/.bashrc)",
        description=(
            "Один раз на каждой машине: дописывает строку\n"
            "  source /путь/к/autoreels/aliases.sh\n"
            "в профиль shell (~/.zshrc на Mac, ~/.bashrc на Windows Git Bash).\n"
            "После этого короткие команды (arl …) обновляются через git pull.\n\n"
            "Пример: autoreels install-aliases\n"
            "Без изменений: autoreels install-aliases --dry-run"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pi.add_argument("--dry-run", action="store_true", default=False,
                    help="показать что добавит, ничего не менять")
    pi.add_argument("--yes", action="store_true", default=False,
                    help="не спрашивать подтверждения")

    pdcl = sub.add_parser(
        "dump-clips",
        help="выгрузить тексты клипов в JSON-фикстуры (для разметки; без ретранскрипции)",
        description=(
            "Экспорт текстов клипов из манифестов в JSON-фикстуры (tests/fixtures/clips/).\n"
            "Текст берётся ТОЛЬКО из word-level субтитров манифеста — без LLM/Whisper/ffmpeg/сети.\n"
            "Манифест не изменяется. Фикстуру с проставленным label повторный прогон не трогает.\n"
            "Без путей — все манифесты из manifests/.\n\n"
            "Пример: autoreels dump-clips manifests/lecture.json --out tests/fixtures/clips/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pdcl.add_argument("manifests", nargs="*", default=None, metavar="манифест",
                      help="манифест(ы) (иначе — все из manifests/)")
    pdcl.add_argument("--out", default="tests/fixtures/clips", metavar="каталог",
                      help="каталог для фикстур (по умолчанию tests/fixtures/clips)")
    pdcl.add_argument("--root", default=None, help="корень проекта (по умолчанию: проект)")

    pmod = sub.add_parser(
        "models",
        help="показать доступные модели на Groq/OpenRouter и проверить сконфигурированные",
        description=(
            "Запрашивает живые списки моделей у Groq и OpenRouter (:free).\n"
            "Показывает, какие настроенные модели есть в списке, а каких нет.\n"
            "Выходит с кодом 1, если хотя бы одна сконфигурированная модель отсутствует.\n\n"
            "Пример: autoreels models"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pmod.add_argument("--root", default=None, help="корень проекта (по умолчанию: проект)")

    pbl = sub.add_parser(
        "blocks",
        help="показать блоки-кандидаты из транскрипта (M1.6 stage 1, без LLM)",
        description=(
            "Детерминированная нарезка транскрипта на блоки-кандидаты для R0-скоринга.\n"
            "Принимает манифест (.json) или файл транскрипта (.transcript.json).\n"
            "Код определяет границы; LLM оценивает блоки только на следующем этапе.\n\n"
            "Примеры:\n"
            '  autoreels blocks "manifests/2026-08-08 10h 59m 38s.json"\n'
            "  autoreels blocks data/cache/sha256.transcript.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pbl.add_argument(
        "target", nargs="?",
        help="манифест (.json) или транскрипт (.transcript.json); не нужен при --apply",
    )
    pbl.add_argument("--root", default=None, help="корень проекта (по умолчанию: проект)")
    pbl.add_argument(
        "--scored",
        action="store_true",
        help="score kept blocks by heuristic and apply top-K per window (M1.6 stage 3)",
    )
    pbl.add_argument(
        "--review",
        action="store_true",
        help="export a human-editable review file (M1.6 stage 4-alt); requires target = manifest",
    )
    pbl.add_argument(
        "--out",
        default=None,
        metavar="FILE",
        help="output path for --review (default: reviews/<manifest>.review.md)",
    )
    pbl.add_argument(
        "--apply",
        default=None,
        metavar="REVIEW_FILE",
        help="import a scored review file and build a manifest (M1.6 stage 4-alt); "
             "bare filename resolved against reviews/ by default",
    )
    pbl.add_argument(
        "--install",
        action="store_true",
        help="copy the resulting manifest to manifests/ (replacing the automatic one); "
             "implies --apply",
    )
    pbl.add_argument(
        "--render",
        action="store_true",
        help="render immediately after apply; implies --install",
    )
    pbl.add_argument(
        "--speed",
        type=float,
        default=None,
        metavar="FACTOR",
        help="default playback speed for all clips (1.0-1.3 policy; atempo itself accepts 0.5-100); "
             "overrides r0.yaml speed; auto-applied when span exceeds manual_max_duration_sec",
    )
    pbl.add_argument(
        "--compact",
        action="store_true",
        help="export one-line-per-block format with embedded prompt, for pasting into a chat; "
             "use with --review",
    )

    pbp = sub.add_parser(
        "backfill-params-key",
        help="stamp transcript_params_key on a manifest that lacks it (one-off repair for legacy/human manifests)",
        description=(
            "Sets transcript_params_key on a manifest built before this field was added,\n"
            "or by an old --apply that did not stamp it. Verifies by audio hash when the mp3\n"
            "is in cache; warns and proceeds when it is not. Refuses an orphan transcript (no\n"
            "stamped metadata) or a hash mismatch.\n\n"
            "Пример: autoreels backfill-params-key manifests/video.json\n"
            "        autoreels backfill-params-key manifests/video.json path/to/audio.transcript.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pbp.add_argument("manifest", metavar="манифест",
                     help="манифест для обновления (.json)")
    pbp.add_argument("transcript", nargs="?", default=None, metavar="транскрипт",
                     help="путь к .transcript.json (если не задан — ищет в data/cache/)")
    pbp.add_argument("--force", action="store_true", default=False,
                     help="перезаписать существующий transcript_params_key")
    pbp.add_argument("--root", default=None, help="корень проекта (по умолчанию: авто)")

    pbss = sub.add_parser(
        "backfill-source-sha",
        help="stamp source_sha256 on legacy transcripts that lack it (one-off repair)",
        description=(
            "Adds source_sha256 to transcript .json files created before this field was introduced.\n"
            "Matches by computing sha256 of the mp3 content and comparing to the transcript\n"
            "filename prefix (= audio_hash = sha256(mp3_content) at transcription time).\n"
            "Refuses when the mp3's current content hash doesn't match (mp3 was re-extracted).\n\n"
            "Пример: autoreels backfill-source-sha data/cache/*.transcript.json\n"
            "        autoreels backfill-source-sha data/cache/72a9c867.ba7fe.transcript.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pbss.add_argument(
        "transcripts", nargs="+", metavar="транскрипт",
        help="один или несколько .transcript.json файлов",
    )
    pbss.add_argument("--cache-dir", default=None, help="путь к кэшу (по умолчанию: data/cache)")
    pbss.add_argument("--root", default=None, help="корень проекта (по умолчанию: авто)")
    pbss.add_argument("--force", action="store_true", default=False,
                      help="перезаписать source_sha256 даже если уже установлен")

    return p


def main(argv=None) -> int:
    """Точка входа CLI. Автоподхват .env, диспетч по команде, ошибки тиров → код 1 + сообщение."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except AttributeError:
            pass

    _load_env()
    args = _build_parser().parse_args(argv)

    # Resolve --root once at the CLI boundary so all dispatch paths get a Path.
    if hasattr(args, "root"):
        args.root = Path(args.root) if args.root is not None else _project_root()

    if args.cmd is None:
        cmd_status()
        hint = _next_hint()
        if hint:
            print(f"\n{hint}")
        else:
            print("\nautoreels help — полная справка и цикл работы")
        return 0

    if args.cmd == "help":
        print(_HELP_EXTENDED)
        return 0

    if args.cmd == "menu":
        if args.classify is not None:
            print(_classify_label(args.classify))
        elif args.resolve is not None:
            print(_menu_action(args.resolve) or "invalid")
        elif args.profiles:
            cur = _current_render_profile(root=args.root)
            avail = _profile_availability(root=args.root)
            for name, desc in _RENDER_PROFILE_DESC.items():
                mark = " (текущий)" if name == cur else ""
                # None/True → не помечаем; только явно False → «недоступно на этом GPU».
                unavail = " — НЕДОСТУПНО на этом GPU" if avail.get(name) is False else ""
                print(f"{name}{mark} — {desc}{unavail}")
        elif args.set_profile is not None:
            try:
                path = set_render_profile(args.set_profile, root=args.root)
            except ConfigError as e:
                print(f"ошибка: {e}", file=sys.stderr)
                return 1
            print(f"✓ профиль рендера: {args.set_profile} → {path} "
                  f"(применится ко всем последующим рендерам)")
        elif args.palettes:
            cur = _current_render_palette(root=args.root)
            for name, desc in _render_palettes(root=args.root).items():
                mark = " (текущая)" if name == cur else ""
                print(f"{name}{mark} — {desc}")
        elif args.set_palette is not None:
            try:
                path = set_render_palette(args.set_palette, root=args.root)
            except ConfigError as e:
                print(f"ошибка: {e}", file=sys.stderr)
                return 1
            print(f"✓ палитра рендера: {args.set_palette} → {path} "
                  f"(применится ко всем последующим рендерам)")
        elif args.settings:
            print(_settings_render(root=args.root))
        elif args.resolve_setting is not None:
            print(_settings_action(args.resolve_setting) or "invalid")
        elif args.music_tracks:
            tracks = list_music_tracks(root=args.root)
            if tracks:
                for t in tracks:
                    print(t)
            else:
                print("(в music/ нет треков — положи .mp3/.m4a/.wav и т.п.)")
        elif args.set_music is not None:
            path = set_render_music(args.set_music, root=args.root)
            state = "выключена" if args.set_music == "off" else f"включена · {args.set_music}"
            print(f"✓ музыка {state} → {path}")
        elif args.set_audio is not None:
            path = set_audio_normalization(args.set_audio == "on", root=args.root)
            print(f"✓ нормализация громкости {'вкл' if args.set_audio == 'on' else 'выкл'} → {path}")
        else:
            print(_menu_render(root=args.root))
        return 0

    if args.cmd == "status":
        return cmd_status(root=args.root)

    if args.cmd == "history":
        return cmd_history(root=args.root, limit=args.limit, outcome=args.outcome)

    if args.cmd == "doctor":
        return cmd_doctor(root=args.root)

    try:
        if args.cmd == "calibrate":
            if args.all:
                _ff = _cli_resolve_ffmpeg(args.ffmpeg, root=args.root)
                cmd_calibrate_batch(root=args.root, ffmpeg=_ff,
                                    ffprobe=resolve_ffprobe(args.ffprobe, ffmpeg=_ff))
                _commit_push_calibrations(root=args.root)     # калибровки → git (для системника)
            elif args.video:
                _ff = _cli_resolve_ffmpeg(args.ffmpeg, root=args.root)
                cmd_calibrate(Path(args.video), setup_label=args.setup, ffmpeg=_ff,
                              ffprobe=resolve_ffprobe(args.ffprobe, ffmpeg=_ff), port=args.port,
                              frame_at=args.frame_at)
                _warn_if_manifest_stale(Path(args.video), root=args.root)
                _commit_push_calibrations(root=args.root)     # калибровки → git (для системника)
            else:
                print("ошибка: укажите видео или используйте --all", file=sys.stderr)
                return 1
        elif args.cmd == "run":
            # Ключ проверяем ПЕРВЫМ делом: без GROQ_API_KEY весь конвейер бессмыслен (Whisper+R0).
            # Внятная ошибка с путём .env и подсказкой doctor — вместо 401 из глубины после аудио.
            require_key("GROQ_API_KEY", _ENV_REPORT)
            ffmpeg = _cli_resolve_ffmpeg(args.ffmpeg)   # флаг>env>local.yaml>render.yaml>автопоиск
            if args.video:
                inputs_dir = _project_root() / "inputs"
                # in-place по умолчанию для файла, данного путём: не копируем в inputs/ и не
                # архивируем — источник обрабатывается там, где лежит (крупные файлы 14 ГБ не
                # дублируем). Исключения, сохраняющие сегодняшнее поведение (архивация вкл.):
                #   • URL/Яндекс.Диск — качаем в inputs/ (это и есть inputs-поток);
                #   • путь, УЖЕ указывающий внутрь inputs/ — трактуем как inputs-источник.
                archive = True
                if _is_url(args.video):
                    if _is_yandex_disk(args.video):
                        video = _download_yandex_disk(args.video, inputs_dir)
                    else:
                        video = _download_url(args.video, inputs_dir)
                elif _path_inside(Path(args.video), inputs_dir):
                    video = _ingest_source(Path(args.video), inputs_dir)   # no-op копия: уже в inputs/
                else:
                    video = _validate_media(Path(args.video), exts=_VIDEO_EXTS)  # in-place, абсолютный путь
                    archive = False
                try:
                    cmd_run(video, ffmpeg=ffmpeg, push=not args.no_push,
                            force=args.force, archive=archive,
                            force_transcribe=args.force_transcribe,
                            auto_render=getattr(args, "auto_render", False))
                except AlreadyProcessedError as e:
                    print(f"✓ {e}", flush=True)          # уже обработан — не ошибка
                    return 0
                except ManualManifestError as e:
                    print(f"✋ {e}", file=sys.stderr)     # ручная выборка — отказ до --force
                    return 1
                except InputInvalid as e:
                    print(f"⊘ пропущен {Path(video).name}: {e}\n"
                          f"  файл битый/пустой — перекачай/пересними и повтори", file=sys.stderr)
                    return 1
            else:
                _, failed, _skipped, zero_harvest = cmd_run_batch(
                    ffmpeg=ffmpeg, push=not args.no_push,
                    force=args.force,
                    force_transcribe=args.force_transcribe,
                    auto_render=getattr(args, "auto_render", False),
                    parallel_render=getattr(args, "parallel_render", True),
                )
                if failed or zero_harvest:
                    return 1
        elif args.cmd == "transcribe":
            # Режим --from-cache: транскрипт из кэша без видео и Whisper → ffmpeg не нужен.
            # source опционален (только для именования файла).
            if args.from_cache:
                cmd_transcribe(
                    args.source, fmt=args.format, ffmpeg=args.ffmpeg,
                    from_cache=args.from_cache,
                )
            else:
                ffmpeg = _cli_resolve_ffmpeg(args.ffmpeg)
                # Источник — как у run, но локальный файл читается НА МЕСТЕ (рендера нет →
                # копировать в inputs/ незачем); url/Яндекс.Диск скачиваются в inputs/.
                if _is_url(args.source):
                    if _is_yandex_disk(args.source):
                        src = _download_yandex_disk(args.source, _project_root() / "inputs")
                    else:
                        src = _download_url(args.source, _project_root() / "inputs")
                else:
                    src = _validate_media(Path(args.source), exts=_MEDIA_EXTS)
                cmd_transcribe(src, fmt=args.format, ffmpeg=ffmpeg)
        elif args.cmd == "render":
            zoom_flag = {"on": True, "off": False}.get(args.zoom)   # None = из конфига
            cmd_render(encoder=args.encoder, ffmpeg=args.ffmpeg, profile=args.profile,
                       palette=args.palette, zoom=zoom_flag, music=args.music,
                       fallback=not args.no_fallback, allow_stale=args.allow_stale,
                       auto_recrop=not args.no_auto_recrop)
        elif args.cmd == "preview":
            pals = [p.strip() for p in args.palettes.split(",") if p.strip()] if args.palettes else None
            return cmd_preview(args.manifest, palettes=pals, seconds=args.seconds,
                               reel_id=args.reel, zoom=args.zoom, encoder=args.encoder,
                               ffmpeg=args.ffmpeg, profile=args.profile)
        elif args.cmd == "resume":
            return cmd_resume(encoder=args.encoder, ffmpeg=args.ffmpeg, profile=args.profile)
        elif args.cmd == "recrop":
            return cmd_recrop(args.video, push=not args.no_push)
        elif args.cmd == "resnap":
            return cmd_resnap(args.video, push=not args.no_push, dry_run=args.dry_run)
        elif args.cmd == "diagnose-cuts":
            return cmd_diagnose_cuts(args.target, rerun=args.rerun)
        elif args.cmd == "dump-clips":
            manifests = [Path(m) for m in args.manifests] if args.manifests \
                else _auto_discover_manifests(root=args.root if args.root != "." else None)
            if not manifests:
                print("manifests/ пуст — нечего выгружать", flush=True)
                return 0
            return cmd_dump_clips(manifests, out=args.out, root=args.root if args.root != "." else None)
        elif args.cmd == "models":
            return cmd_models(root=args.root)
        elif args.cmd == "blocks":
            return cmd_blocks(
                args.target, root=args.root, scored=args.scored,
                review=args.review, out=args.out, apply_review=args.apply,
                install=args.install, render=args.render, compact=args.compact,
                speed=args.speed,
            )
        elif args.cmd == "migrate-calibrations":
            return cmd_migrate_calibrations()
        elif args.cmd == "backfill-params-key":
            return cmd_backfill_pkey(
                args.manifest, args.transcript,
                root=args.root if hasattr(args, "root") and args.root else None,
                force=args.force,
            )
        elif args.cmd == "backfill-source-sha":
            return cmd_backfill_source_sha(
                args.transcripts,
                cache_dir=args.cache_dir if hasattr(args, "cache_dir") else None,
                root=args.root if hasattr(args, "root") and args.root else None,
                force=args.force,
            )
        elif args.cmd == "install-aliases":
            return cmd_install_aliases(
                aliases_path=_find_aliases_sh(),
                profile_path=_detect_shell_profile(),
                dry_run=args.dry_run,
                confirm=not args.yes,
            )
    except _KNOWN_ERRORS as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
