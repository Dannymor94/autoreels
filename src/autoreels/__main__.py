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
import shutil
import sys
from pathlib import Path

from autoreels.cloud.compress import compress_transcript
from autoreels.cloud.diagnose import classify_end, summarize
from autoreels.cloud.extract_audio import ExtractAudioError, extract_audio
from autoreels.cloud.providers import ProviderError, build_pool
from autoreels.cloud.select import SelectError, select
from autoreels.cloud.snap import apply_padding, snap_segments
from autoreels.cloud.trim import trim_too_long
from autoreels.cloud.transcribe import TranscriptionError, get_backend, transcribe
from autoreels.cloud.transcribe_formats import to_json, to_srt, to_text, to_vtt
from autoreels.core import state
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
from autoreels.local.calibrate import CalibrateError, cmd_calibrate
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

def _load_env(dotenv_path: str | Path | None = None) -> None:
    """Подхватить .env в окружение (закрывает ручной `source .env`, долг 5a)."""
    from dotenv import load_dotenv

    load_dotenv(str(dotenv_path) if dotenv_path is not None else None)


def _run_key(source_sha256: str, duration_preset: str) -> str:
    """Детерминированный ключ прогона от source+preset (полноценная версия рубрики — M1)."""
    return hashlib.sha256(f"{source_sha256}:{duration_preset}".encode()).hexdigest()[:16]


# ----------------------------------------------------- приём исходника (путь → inputs/)

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


def _stage_transcribe(audio, *, transcribe_cfg, cache_dir, r0_cfg=None, audio_cfg=None, ffmpeg="ffmpeg"):
    print("транскрипция…", flush=True)
    backend = get_backend(transcribe_cfg)
    chunking_cfg = r0_cfg.chunking if r0_cfg is not None else None
    return transcribe(
        audio, cache_dir,
        backend=backend,
        language=transcribe_cfg.language,
        chunking_cfg=chunking_cfg,
        audio_cfg=audio_cfg,
        ffmpeg=ffmpeg,
    )


def _stage_compress(transcript, *, r0_cfg):
    print("сжатие транскрипта…", flush=True)
    return compress_transcript(
        transcript, pause_sec=r0_cfg.sentence_pause_sec, max_sentence_sec=r0_cfg.max_sentence_sec
    )


def _stage_select(compressed, *, r0_cfg, root, provider=None):
    """R0-выбор. `provider` — заранее собранный пул (cmd_run строит его и валидирует ДО
    транскрипции); если None — собираем здесь (standalone-путь)."""
    print("выбор моментов…", flush=True)
    root = Path(root)
    system_text = (root / r0_cfg.prompts.system).read_text(encoding="utf-8")
    fewshot = json.loads((root / r0_cfg.prompts.fewshot).read_text(encoding="utf-8"))
    if provider is None:
        provider = build_pool(r0_cfg)
    return select(
        compressed, system_text=system_text, fewshot=fewshot,
        provider=provider, r0_cfg=r0_cfg,
    )


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
        prefer_longer_below_ratio=r0_cfg.prefer_longer_below_ratio,
        max_extra_sentences=r0_cfg.max_extra_sentences,
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


def _stage_subtitles(reels, transcript):
    """R3: привязать word-level транскрипта к каждому reel."""
    print("субтитры: привязка слов к сегментам…", flush=True)
    for reel in reels:
        reel.subtitles = words_in_window(transcript.words, reel.start, reel.end)
    return reels


def _assemble_manifest(video, reels, *, sha, setup, duration_preset):
    """Собрать манифест: кроп/setup_id — из калибровки (setup), source_sha256 — от файла."""
    return Manifest(
        source=Path(video).name,
        source_sha256=sha,
        source_hash_scheme="partial-p1",
        duration_preset=duration_preset,
        setup=setup,
        run_key=_run_key(sha, duration_preset),
        reels=reels,
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
    root = Path(root)
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
    root = Path(root)
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
    root = Path(root)
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


def resolve_ffmpeg(cli_flag=None, *, render_cfg, which=None, candidates=None, is_file=None) -> str:
    """Разрешить путь к ffmpeg. Приоритет: флаг > env RENDER_FFMPEG > render.local.yaml >
    render.yaml (последние два — уже слиты в `render_cfg.ffmpeg` через deep-merge).

    Явно заданный источник возвращается как есть (существование проверит downstream —
    так пути с другой машины не роняют резолв). Если НИЧЕГО не задано (или дефолт «ffmpeg»):
    сначала PATH, затем автопоиск типичных мест (работает без настройки), затем —
    FFmpegNotFoundError с перечнем, где искали, и как задать путь."""
    which = which if which is not None else shutil.which
    is_file = is_file if is_file is not None else (lambda p: Path(str(p)).is_file())
    candidates = candidates if candidates is not None else _ffmpeg_candidates()

    config_value = getattr(render_cfg, "ffmpeg", "ffmpeg")
    explicit = cli_flag or os.environ.get("RENDER_FFMPEG") or (
        config_value if config_value and config_value != "ffmpeg" else None
    )
    if explicit:
        return explicit
    if which("ffmpeg"):
        return "ffmpeg"
    for cand in candidates:
        if is_file(cand):
            return cand
    searched = ["ffmpeg (в PATH)"] + list(candidates)
    raise FFmpegNotFoundError(
        "ffmpeg не найден. Искал: " + ", ".join(searched) + ".\n"
        "Задай путь одним из способов (приоритет сверху вниз):\n"
        "  • флаг:  --ffmpeg D:\\ffmpeg\\bin\\ffmpeg.exe\n"
        "  • env:   RENDER_FFMPEG=D:\\ffmpeg\\bin\\ffmpeg.exe\n"
        "  • файл:  config/render.local.yaml → ffmpeg: D:\\ffmpeg\\bin\\ffmpeg.exe\n"
        "или установи ffmpeg в PATH."
    )


def resolve_ffprobe(cli_flag=None, *, ffmpeg=None, which=None, is_file=None) -> str:
    """Разрешить ffprobe: флаг > env RENDER_FFPROBE > PATH > сосед резолвнутого ffmpeg.

    ffprobe почти всегда лежит рядом с ffmpeg — если его нет в PATH, берём соседний бинарь
    по каталогу ffmpeg. Иначе — «ffprobe» (downstream даст ошибку, если и его нет)."""
    which = which if which is not None else shutil.which
    is_file = is_file if is_file is not None else (lambda p: Path(str(p)).is_file())
    explicit = cli_flag or os.environ.get("RENDER_FFPROBE")
    if explicit:
        return explicit
    if which("ffprobe"):
        return "ffprobe"
    if ffmpeg and (("/" in ffmpeg) or ("\\" in ffmpeg)):
        sibling = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
        if is_file(sibling):
            return str(sibling)
    return "ffprobe"


def _project_root() -> Path:
    """Корень репозитория (где config/render.local.yaml, aliases.sh) — по расположению пакета.
    Команды находят машинный конфиг ffmpeg независимо от cwd: после autoload `arl` (и любой
    CLI-вызов) стартует из ПРОИЗВОЛЬНОЙ директории, а render.local.yaml лежит в проекте."""
    return Path(__file__).resolve().parents[2]


def _cli_resolve_ffmpeg(flag, *, root=None) -> str:
    """Разрешить ffmpeg для CLI-команд (run/transcribe/calibrate), которые сами render_cfg
    не грузят. Внятная FFmpegNotFoundError, если не найден (ловится в main → чистое сообщение).

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
            return resolve_ffmpeg(flag, render_cfg=load_render_config(base / "config" / "render.yaml"))
        except (ConfigError, OSError):
            continue
    return resolve_ffmpeg(flag, render_cfg=SimpleNamespace(ffmpeg="ffmpeg"))


# ------------------------------------------------------------------------- команды

def cmd_run(
    video,
    *,
    root=".",
    calibrations_dir=None,
    manifests_dir=None,
    cache_dir=None,
    archive_dir=None,
    transcripts_dir=None,
    ffmpeg: str = "ffmpeg",
    push: bool = False,
    pull_first: bool = True,
) -> Path:
    """ОБЛАЧНЫЙ тир: одно видео → manifests/<stem>.json + архив источника.

    `push=True` → сразу закоммитить+запушить манифест (per-video sync на системник);
    ошибка git не роняет прогон. По умолчанию False (git не трогается).
    `pull_first=True` → git pull ПЕРЕД стартом (подтянуть свежие калибровки с системника,
    чтобы не строить манифест на старом кропе). Batch тянет один раз и зовёт с pull_first=False.

    Кроп per-file: берётся из `calibrations/<sha256>.json` (пишет `autoreels calibrate`).
    Нет калибровки → авто-кроп по центру (9:16, полная высота) с сообщением.
    После записи манифеста видео перемещается в inputs-archive/.
    Попутно (без доп. работы) сохраняет текст транскрипта в transcripts/<stem>.txt —
    он уже посчитан для R0, отдельный `transcribe` на то же видео не нужен.
    """
    root = Path(root)
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

    size_gb = Path(video).stat().st_size / (1 << 30)
    print(f"считаю хэш видео ({size_gb:.1f} ГБ)…", flush=True)
    sha = state.file_sha256_cached_fast(video, cache_dir)
    print("хэш готов.", flush=True)
    setup = load_or_auto_calibrate(
        calibrations_dir, sha, Path(video).name,
        get_frame_size=lambda: _probe_frame_size_for_auto(video),
    )

    # Жёсткая валидация при сборке манифеста: кроп проверяется против ОТОБРАЖАЕМЫХ (display,
    # после rotation-метаданных) размеров кадра — ровно то пространство, в котором рендер
    # применит crop-фильтр (autorotate по умолчанию). Приводим к ОДНОМУ пространству перед
    # сравнением: и калибровка (rotation_applied=true), и probe — отображаемые размеры.
    disp_w, disp_h = _probe_frame_size_for_auto(video)
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
    audio = _stage_extract_audio(video, render_cfg=render_cfg, cache_dir=cache_dir,
                                 ffmpeg=ffmpeg, source_sha=sha)
    transcript = _stage_transcribe(
        audio, transcribe_cfg=transcribe_cfg, cache_dir=cache_dir,
        r0_cfg=r0_cfg, audio_cfg=render_cfg.audio_extract, ffmpeg=ffmpeg,
    )
    # Попутно: сохранить читаемый текст для контента (транскрипт уже есть — R0 его считал).
    tx_path = _write_transcript_file(
        transcript, stem=Path(video).stem, fmt="text", out_dir=transcripts_dir, r0_cfg=r0_cfg
    )
    print(f"транскрипт для контента → {tx_path}", flush=True)
    compressed = _stage_compress(transcript, r0_cfg=r0_cfg)
    reels = _stage_select(compressed, r0_cfg=r0_cfg, root=root, provider=provider)
    for r in reels:                        # сохранить R0-границы ДО snap → для resnap без LLM
        r.r0_start, r.r0_end = r.start, r.end
    reels = _stage_snap(reels, transcript, r0_cfg=r0_cfg)
    reels = _stage_padding(reels, transcript, r0_cfg=r0_cfg)
    reels = _stage_trim(reels, transcript, r0_cfg=r0_cfg)
    reels = _stage_subtitles(reels, transcript)
    manifest = _assemble_manifest(
        video, reels, sha=sha, setup=setup, duration_preset=r0_cfg.duration_preset
    )
    path = _write_manifest(manifest, manifests_dir)
    print(f"манифест собран: {len(manifest.reels)} reels → {path}", flush=True)
    if push:
        # Калибровку кропа этого видео шлём вместе с манифестом — чтобы уехала на системник.
        _commit_push_manifest(path, len(manifest.reels), root=root,
                              calibration_path=calibration_path(calibrations_dir, sha))
    _archive_video(Path(video), archive_dir)
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
    root=".",
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
    root = Path(root)
    cfg = root / "config"
    r0_cfg = load_r0_config(cfg / "r0.yaml")
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"
    out_dir = Path(out_dir) if out_dir else root / "transcripts"

    if from_cache is not None:
        cache_path = cache_dir / f"{from_cache}.transcript.json"
        if not cache_path.exists():
            raise RunError(f"транскрипт не найден в кэше: {cache_path}")
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
    root=".",
    inputs_dir=None,
    calibrations_dir=None,
    manifests_dir=None,
    cache_dir=None,
    archive_dir=None,
    transcripts_dir=None,
    ffmpeg: str = "ffmpeg",
    push: bool = False,
) -> tuple[list[str], list[tuple[str, Exception]]]:
    """Batch: обработать все *.mp4 в inputs/ по очереди. Один упал → остальные продолжают.

    `push=True` → каждый успешный манифест сразу коммитится+пушится (per-video, не в конце):
    упади прогон на середине — уже готовые манифесты УЖЕ на системнике.
    Возвращает (ok_names, failed_list) где failed_list = [(name, exc), ...].
    """
    root = Path(root)
    _git_pull(root, what="калибровки")          # один pull на всю пачку (не на каждое видео)
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    videos = sorted(inputs_dir.glob("*.mp4"))
    if not videos:
        print("inputs/ пуст — нечего обрабатывать", flush=True)
        return [], []

    ok: list[str] = []
    failed: list[tuple[str, Exception]] = []
    for v in videos:
        try:
            cmd_run(
                v, root=root, calibrations_dir=calibrations_dir, manifests_dir=manifests_dir,
                cache_dir=cache_dir, archive_dir=archive_dir, transcripts_dir=transcripts_dir,
                ffmpeg=ffmpeg, push=push, pull_first=False,
            )
            ok.append(v.name)
        except Exception as e:  # noqa: BLE001
            print(f"\n[ОШИБКА] {v.name}: {e}", file=sys.stderr, flush=True)
            failed.append((v.name, e))

    print(f"\n=== batch run: {len(ok)} ok / {len(failed)} failed ===", flush=True)
    for name, err in failed:
        print(f"  ✗ {name}: {err}", file=sys.stderr)
    return ok, failed


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
    root=".",
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
) -> list[Path]:
    """ЛОКАЛЬНЫЙ тир: manifests/*.json → reels-out/ (batch по всем манифестам).

    Каждый манифест рендерится независимо. Три исхода:
    - все клипы уже есть в reels-out/<stem>/ → пропуск «✓ уже готово»;
    - исходник не найден в inputs/ → пропуск «⊘ нет видео»;
    - рендер упал → ошибка в сводке.

    Манифесты в manifests/ НЕ трогаются — git ими управляет (Mac→системник через pull).
    Идемпотентность обеспечивается проверкой выходных файлов, а не перемещением манифеста.
    """
    root = Path(root)
    if pull_first:
        _git_pull(root, what="манифесты")       # свежие манифесты с Mac (после run)
    render_cfg = load_render_config(root / "config" / "render.yaml")
    subtitles_cfg = load_subtitles_config(root / "config" / "subtitles.yaml")
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    out_dir = Path(out_dir) if out_dir else root / "reels-out"
    archive_dir = Path(archive_dir) if archive_dir else root / "inputs-archive"
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"

    manifest_files = sorted(manifests_dir.glob("*.json"))
    if not manifest_files:
        print("manifests/ пуст — нечего рендерить", flush=True)
        return []

    # Профиль кодека: флаг > env RENDER_PROFILE > активный из конфига. Опечатка → fail-fast.
    prof_name = profile or os.environ.get("RENDER_PROFILE") or render_cfg.encoder.profile
    validate_profile(prof_name, render_cfg.encoder.profiles, where="--profile/RENDER_PROFILE")
    # Палитра (цветокор): флаг > env RENDER_PALETTE > активная из конфига (render.local.yaml).
    pal_name = palette or os.environ.get("RENDER_PALETTE") or render_cfg.palette
    if pal_name not in render_cfg.palettes:
        known = ", ".join(render_cfg.palettes)
        raise SystemExit(f"неизвестная палитра '{pal_name}'. Доступны: {known}")
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
                        new_setup = _recrop_setup(manifest, calibrations_dir=calibrations_dir,
                                                  inputs_dir=inputs_dir, archive_dir=archive_dir)
                    except CalibrationError as e:
                        # Нечего применить (нет валидной калибровки) → блокируем как раньше.
                        print(f"\n  ⛔ ПРОПУСК {stem}: {desync}\n     не удалось авто-применить "
                              f"калибровку: {e}. arl recrop / arl r --allow-stale",
                              file=sys.stderr, flush=True)
                        skipped_stale.append(mf.name)
                        continue
                    manifest = manifest.model_copy(update={"setup": new_setup})
                    _write_manifest(manifest, manifests_dir)          # локально
                    c = new_setup.crop
                    print(f"  ↻ {stem}: кроп обновлён по калибровке (был устаревший) → "
                          f"{c.w}×{c.h}@{c.x},{c.y} в кадре {new_setup.frame} — продолжаю рендер",
                          flush=True)
                    # push по общим правилам (AUTOREELS_GIT_PUSH=0/SYNC=0 → только локально, без ошибок)
                    _commit_push_manifest(manifests_dir / f"{stem}.json", len(manifest.reels), root=root)
                    # дальше рендерим обновлённым manifest (не continue)
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
            pal_tag = "" if pal_name == "neutral" else f", палитра {pal_name}"
            zoom_on = render_cfg.zoom.enabled if zoom is None else zoom
            zoom_tag = ", зум" if zoom_on else ""
            music_tag = f", музыка {Path(music_path).name}" if music_path else ""
            print(f"=== render: {mf.name} ({label}, {prof_name}/{enc}{pal_tag}{zoom_tag}{music_tag}) "
                  f"→ {out_dir_final} ===", flush=True)
            outputs = render_crop(
                render_manifest, inputs_dir=inputs_dir, out_dir=out_dir_final,
                render_cfg=render_cfg, ffmpeg=effective_ffmpeg,
                encoder=(enc if explicit_encoder else None),   # префлайт мог сменить профиль
                profile=prof_name, palette=pal_name, zoom=zoom, music_path=music_path,
                subtitles_cfg=subtitles_cfg,
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
    return all_outputs


def cmd_preview(
    manifest_arg=None,
    *,
    palettes=None,
    seconds: float = 6.0,
    reel_id=None,
    zoom=None,
    root=".",
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
    root = Path(root)
    render_cfg = load_render_config(root / "config" / "render.yaml")
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    out_dir = Path(out_dir) if out_dir else root / "reels-out" / "_preview"

    if manifest_arg:
        mf = Path(manifest_arg)
        if not mf.is_file():
            mf = manifests_dir / f"{Path(manifest_arg).stem}.json"
    else:
        candidates = sorted(manifests_dir.glob("*.json"))
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


def _recrop_setup(manifest, *, calibrations_dir, inputs_dir, archive_dir):
    """Свежий setup для манифеста: калибровка по sha (или автокроп по отображаемому кадру).

    Кроп валидируется В ОТОБРАЖАЕМОМ кадре (границы + 9:16). Автокроп требует видео на диске —
    иначе CalibrationError (нечем определить размер кадра). Reels/тексты не участвуют."""
    def _frame_size():
        video = _find_source_video(manifest.source, inputs_dir=inputs_dir, archive_dir=archive_dir)
        if video is None:
            raise CalibrationError(
                f"нет калибровки и видео «{manifest.source}» недоступно (ни inputs/, ни архив) — "
                f"нечем считать автокроп"
            )
        return _probe_frame_size_for_auto(video)

    setup = load_or_auto_calibrate(
        calibrations_dir, manifest.source_sha256, manifest.source, get_frame_size=_frame_size
    )
    validate_crop_in_frame(setup.crop, setup.frame[0], setup.frame[1])
    return setup


def cmd_recrop(
    video=None,
    *,
    root=".",
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
    root = Path(root)
    if pull_first:
        _git_pull(root, what="калибровки")
    manifests_dir = Path(manifests_dir) if manifests_dir else root / "manifests"
    calibrations_dir = Path(calibrations_dir) if calibrations_dir else root / "calibrations"
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "inputs"
    archive_dir = Path(archive_dir) if archive_dir else root / "inputs-archive"

    if video is not None:
        mf = manifests_dir / f"{Path(video).stem}.json"
        if not mf.is_file():
            print(f"нет манифеста для {Path(video).stem} — сначала arl run", file=sys.stderr, flush=True)
            return 1
        targets = [mf]
    else:
        targets = sorted(manifests_dir.glob("*.json"))
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
                                      inputs_dir=inputs_dir, archive_dir=archive_dir)
        except CalibrationError as e:
            print(f"  ⚠ пропуск {stem}: {e}", file=sys.stderr, flush=True)
            skipped.append(mf.name)
            continue

        old = manifest.setup.crop
        old_frame = list(manifest.setup.frame)
        new_frame = list(new_setup.frame)
        old_rot = float(getattr(manifest.setup, "rotation_deg", 0.0) or 0.0)
        new_rot = float(getattr(new_setup, "rotation_deg", 0.0) or 0.0)
        same_crop = old.model_dump() == new_setup.crop.model_dump()
        same_frame = old_frame == new_frame
        same_rot = old_rot == new_rot
        if same_crop and same_frame and same_rot:
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
                  prefer_longer_below_ratio=r0_cfg.prefer_longer_below_ratio,
                  max_extra_sentences=r0_cfg.max_extra_sentences)
    apply_padding(reels, transcript.words, tail_pad_sec=r0_cfg.tail_pad_sec,
                  lead_pad_sec=r0_cfg.lead_pad_sec, max_duration=r0_cfg.max_duration,
                  video_duration=transcript.words[-1].t1 if transcript.words else None,
                  hanging_words=r0_cfg.hanging_words)
    trim_too_long(reels, transcript.words, max_duration=r0_cfg.max_duration,
                  pause_sec=r0_cfg.sentence_pause_sec, policy=r0_cfg.too_long_policy)


def cmd_resnap(
    video=None,
    *,
    root=".",
    manifests_dir=None,
    cache_dir=None,
    push: bool = True,
    pull_first: bool = True,
) -> int:
    """Пересчитать ГРАНИЦЫ клипов из сохранённых R0-границ (snap→padding→trim текущим кодом),
    БЕЗ повторного R0/LLM. Для проверки правок snap/padding без пересборки манифеста.

    Выбор моментов (R0), тексты, субтитры — НЕ трогаются: те же r0_start/r0_end прогоняются
    заново детерминированным слоем. Транскрипт берётся из кэша (как diagnose-cuts). Без <video>
    — batch по всем манифестам. Манифест без r0_start (снят до фичи) → нужен один полный run."""
    root = Path(root)
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
        targets = sorted(manifests_dir.glob("*.json"))
        if not targets:
            print("manifests/ пуст — нечего пересчитывать", flush=True)
            return 0

    updated: list[str] = []
    skipped: list[str] = []
    no_r0: list[str] = []
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
        transcript = _transcript_for_manifest(manifest, cache_dir, audio_format=audio_format)
        if transcript is None:
            print(f"  ⚠ {stem}: кэш-транскрипт не найден (видео не прогонялось здесь) — пропуск",
                  file=sys.stderr, flush=True)
            skipped.append(mf.name)
            continue

        reels = [r.model_copy(deep=True) for r in manifest.reels]
        _resnap_reels(reels, transcript, r0_cfg)
        n_changed = sum(1 for a, b in zip(manifest.reels, reels)
                        if (round(a.start, 3), round(a.end, 3)) != (round(b.start, 3), round(b.end, 3)))
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
        if skipped:
            parts.append(f"{len(skipped)} пропущено")
        print(f"\n=== resnap: {' / '.join(parts)} ===", flush=True)
    if updated:
        print("  → границы обновлены (R0 не пересчитывался). Дальше: arl r (render).", flush=True)
    return 0


def cmd_resume(*, root=".", ffmpeg=None, encoder=None, profile=None) -> int:
    """Продолжить прерванное: доделать рендер недостающих клипов + сообщить о недокачках.

    Тяжёлые шаги проекта идемпотентны и «продолжаемы» by design: render дорисовывает
    недостающие клипы, докачка Я.Диска возобновляется по той же ссылке, run переиспользует
    кэш. Эта команда сводит их: локально чинит рендер, а по остальному даёт подсказку.
    """
    root = Path(root)
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
    for mf in (sorted(manifests_dir.glob("*.json")) if manifests_dir.is_dir() else []):
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


def cmd_migrate_calibrations(
    *,
    root=".",
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
    root = Path(root)
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
    if manifest.setup.crop.model_dump() == calib_crop and manifest_rot == calib_rot:
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
    root = Path(root)
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
    root=".",
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
    root = Path(root)
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

def _transcript_for_manifest(manifest, cache_dir, *, audio_format="mp3"):
    """Кэш-транскрипт видео по цепочке source_sha → cache/<sha>.<fmt> → audio_hash → transcript.json.
    Возвращает Transcript или None (нет аудио/транскрипта в кэше — видео не прогонялось здесь)."""
    audio = Path(cache_dir) / f"{manifest.source_sha256}.{audio_format}"
    if not audio.is_file():
        return None
    tp = state.transcript_cache_path(cache_dir, audio)
    if not tp.is_file():
        return None
    try:
        return Transcript.model_validate_json(tp.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


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
    snap_segments(reels, transcript.words, tail_sec=r0_cfg.tail_sec,
                  window_sec=r0_cfg.snap_window_sec, max_duration=r0_cfg.max_duration,
                  min_pause_for_phrase_end=r0_cfg.min_pause_for_phrase_end,
                  max_micro_pause=r0_cfg.max_micro_pause, hanging_words=r0_cfg.hanging_words,
                  prefer_longer_below_ratio=r0_cfg.prefer_longer_below_ratio,
                  max_extra_sentences=r0_cfg.max_extra_sentences)
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


def cmd_diagnose_cuts(target=None, *, root=".", rerun=False, cache_dir=None,
                      manifests_dir=None) -> int:
    """Классифицировать концы клипов: CLEAN / SOFT / HARD (обрыв) с причиной — быстрая проверка
    после правок snap/padding/рубрики.

    По умолчанию — анализ существующих манифестов (без LLM). `--rerun` — честный пере-прогон R0
    от кэш-транскрипта (для before/after: границы готового манифеста уже пост-snap+padding,
    сравнивать по ним НЕЛЬЗЯ — предупреждаем)."""
    root = Path(root)
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
        manifest_files = sorted(manifests_dir.glob("*.json"))
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
    total = {"clean": 0, "soft": 0, "hard": 0, "causes": {}}
    analyzed = 0
    for mf in manifest_files:
        try:
            manifest = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ битый манифест {mf.name}: {e}", file=sys.stderr, flush=True)
            continue
        transcript = _transcript_for_manifest(manifest, cache_dir, audio_format=audio_format)
        if transcript is None:
            print(f"  ⚠ {mf.stem}: кэш-транскрипт не найден (видео не прогонялось здесь) — пропуск",
                  file=sys.stderr, flush=True)
            continue
        if rerun:
            print(f"  … пере-прогон R0: {mf.stem}", flush=True)
            reels = _rerun_reels(transcript, r0_cfg, root)
        else:
            reels = manifest.reels
        diags = [classify_end(r.id, r.start, r.end, transcript.words, **cfg) for r in reels]
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

def cmd_status(*, root=".") -> int:
    """Сводка текущего состояния проекта: inputs / manifests / reels-out / archive + предупреждения."""
    root = Path(root)
    inputs_dir      = root / "inputs"
    manifests_dir   = root / "manifests"
    reels_out_dir   = root / "reels-out"
    archive_dir     = root / "inputs-archive"
    calibrations_dir = root / "calibrations"

    inputs    = sorted(inputs_dir.glob("*.mp4"))      if inputs_dir.is_dir()    else []
    manifests = sorted(manifests_dir.glob("*.json"))  if manifests_dir.is_dir() else []
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
    input_stems = {v.stem for v in inputs} | {v.stem for v in archived}
    for mf in manifests:
        try:
            m = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
            stem = Path(m.source).stem
            if stem not in input_stems:
                warnings.append(f"  ⚠ манифест без видео: {mf.name} (нет inputs/{m.source})")
            desync = _manifest_calibration_desync(m, calibrations_dir)
            if desync:
                warnings.append(f"  ⚠ {desync}")
        except Exception:  # noqa: BLE001
            warnings.append(f"  ⚠ битый манифест: {mf.name}")

    if warnings:
        print()
        for w in warnings:
            print(w)

    print("────────────────────────────────────────────────────")
    return 0


# ----------------------------------------------------------------------- smart hint

def _next_hint(root=".") -> str | None:
    """Подсказка следующего шага по состоянию проекта.

    Возвращает одну строку вида «→ arl go» или None если не очевидно что делать.
    Видео в inputs/ приоритетнее манифестов: сначала run, потом render.
    """
    root = Path(root)
    inputs = list((root / "inputs").glob("*.mp4")) if (root / "inputs").is_dir() else []
    manifests = list((root / "manifests").glob("*.json")) if (root / "manifests").is_dir() else []

    if inputs:
        n = len(inputs)
        return f"→ {n} видео ждут обработки:  arl go"
    if manifests:
        n = len(manifests)
        return f"→ {n} манифест(а) готовы к рендеру:  arl r  (на системнике)"
    return None


# ----------------------------------------------------------------------------- меню

# Пункты меню: (цифра, action-токен, подпись, короткая подсказка). Нумерация СТАБИЛЬНА —
# адаптивность (подсветка/пометки) влияет только на оформление, не на digit→action.
_MENU_ITEMS: list[tuple[str, str, str, str]] = [
    ("1", "go",         "Обработать видео из inputs/", "run всех + git push"),
    ("2", "render",     "Отрендерить манифесты",       "git pull + render"),
    ("3", "status",     "Статус",                       ""),
    ("4", "calibrate",  "Калибровка кропа (все)",       ""),
    ("5", "path",       "Обработать по ссылке или пути к файлу",
                        "URL, Яндекс.Диск, YouTube или файл на диске"),
    ("6", "transcribe", "Транскрибировать (для контента)",
                        "источник: ссылка или файл → текст"),
    ("7", "resume",     "Продолжить прерванное",
                        "доделать рендер, докачки"),
    ("8", "help",       "Справка",                       ""),
    ("9", "profile",    "Профиль рендера",               "hevc | h264 | av1"),
    ("10", "diagnose",  "Диагностика обрывов фраз",      "CLEAN/SOFT/HARD по клипам + причина"),
    ("11", "resnap",    "Пересчитать границы (resnap)",  "snap/padding из R0-границ, без LLM"),
    ("12", "palette",   "Палитра рендера",               "neutral | vivid | soft | sharp"),
    ("0", "quit",       "Выход",                         ""),
]

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
    for num, action, _label, _hint in _MENU_ITEMS:
        if c == num:
            return action
    return None


def _menu_state(root=".") -> dict[str, int]:
    """Счётчики состояния для шапки меню: inputs / manifests / rendered."""
    root = Path(root)
    inputs = len(list((root / "inputs").glob("*.mp4"))) if (root / "inputs").is_dir() else 0
    manifests = len(list((root / "manifests").glob("*.json"))) if (root / "manifests").is_dir() else 0
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
    """Строка машинных настроек для шапки: «профиль: hevc | ffmpeg: D:\\…» — видно, чем рендерит."""
    return (f"настройки: профиль {_current_render_profile(root)}  |  "
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
    for num, action, label, hint in _MENU_ITEMS:
        marker = marker_char if action == rec else " "
        # Пункт профиля/палитры показывает ТЕКУЩЕЕ значение прямо в подписи.
        if action == "profile":
            label = f"{label}: {current_profile}"
        elif action == "palette":
            label = f"{label}: {current_palette}"
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
  • Сегменты >59 с → обрезаются по ближайшей паузе (config: too_long_policy: trim).
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
    pm.add_argument("--root", default=".", help="корень проекта (по умолчанию: .)")

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
    ps.add_argument("--root", default=".", help="корень проекта (по умолчанию: .)")

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
    pc.add_argument("--root", default=".",
                    help="корень проекта (по умолчанию: .)")
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
        else:
            print(_menu_render(root=args.root))
        return 0

    if args.cmd == "status":
        return cmd_status(root=args.root)

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
            ffmpeg = _cli_resolve_ffmpeg(args.ffmpeg)   # флаг>env>local.yaml>render.yaml>автопоиск
            if args.video:
                if _is_url(args.video):
                    if _is_yandex_disk(args.video):
                        video = _download_yandex_disk(args.video, Path("inputs"))
                    else:
                        video = _download_url(args.video, Path("inputs"))
                else:
                    video = _ingest_source(Path(args.video), Path("inputs"))
                cmd_run(video, ffmpeg=ffmpeg, push=not args.no_push)
            else:
                _, failed = cmd_run_batch(ffmpeg=ffmpeg, push=not args.no_push)
                if failed:
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
                        src = _download_yandex_disk(args.source, Path("inputs"))
                    else:
                        src = _download_url(args.source, Path("inputs"))
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
            return cmd_resnap(args.video, push=not args.no_push)
        elif args.cmd == "diagnose-cuts":
            return cmd_diagnose_cuts(args.target, rerun=args.rerun)
        elif args.cmd == "migrate-calibrations":
            return cmd_migrate_calibrations()
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
