r"""R1a — нарезка без кропа: manifest → reels-out/<id>_raw.mp4 (горизонтальный, как есть).

Локальный тир. Исходник живёт ЛОКАЛЬНО (на машине рендера), в облако не уходит; манифест
приходит через Syncthing. Кроп (R1b) и субтитры (R3) — отдельные шаги, здесь изолирован рез.

Несущие решения:
- **Идентичность по содержимому, не по пути.** `manifest.source` — Mac-путь с машины облака,
  на машине рендера невалиден. Исходник ищется в локальной `inputs/` по `source_sha256`
  (имя из `source` — лишь подсказка для быстрого поиска). Нет файла с таким хэшем → ошибка.
- **Энкодер — рантайм-параметр, не хардкод.** Кодек берётся из env `RENDER_ENCODER`, иначе
  из `render.yaml` (дефолт libx264; на Windows — h264_amf). Тонкая настройка rate-control
  под аппаратные энкодеры (AMF/VAAPI) — шаг 6; здесь покрыт дефолтный libx264-путь.
- **Кроссплатформенность.** Все локальные пути — через `pathlib`, без строк с `/` или `\`.
  Путь к ffmpeg-бинарю конфигурируем (Windows: `D:\ffmpeg\bin\ffmpeg.exe` или из PATH).
- **fail-fast.** Нет inputs/ / нет исходника / нет ffmpeg / ffmpeg упал → RenderError с
  внятным сообщением, без голого traceback и без битого частичного выхода.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from pydantic import ValidationError

from autoreels.core import state
from autoreels.core.config import (
    AudioProcessing, Music, Palette, RenderConfig, SubtitlesConfig, Zoom, validate_profile,
)
from autoreels.core.progress import is_tty, render_bar
from autoreels.core.models import Crop, Manifest, Segment, SetupProfile
from autoreels.local.subtitles import build_ass, remap_to_output

# Имя файла манифеста в папке manifests/ (приходит по Syncthing с машины облака).
_MANIFEST_NAME = "manifest.json"

# Минимальная длительность клипа, ниже которой рендер пропускает с предупреждением.
# Защита от схлопнутых границ, прошедших в манифест (основная фильтрация — пост-snap в run).
_MIN_CLIP_RENDER_SEC = 2.0

# Кодеки, для которых -preset — родной параметр (софтверные x26x). Для аппаратных
# энкодеров (h264_amf/hevc_amf/av1_amf/nvenc) -preset невалиден (у AMF свой пресет).
_SOFTWARE_X26X = {"libx264", "libx265"}


def probe_encoder(codec: str, *, ffmpeg: str = "ffmpeg", run=None) -> bool:
    """True, если энкодер РЕАЛЬНО работает на этой машине (пробный encode 1 кадра).

    `ffmpeg -encoders` показывает СКОМПИЛИРОВАННЫЕ энкодеры, но не факт поддержки GPU:
    av1_amf есть в сборке, а на AMD RX 6000 инициализация AMF падает («CreateComponent
    (AMFVideoEncoderHW_AV1) failed error 11»). Поэтому — настоящий тестовый encode: 1 кадр
    lavfi → энкодер → null. rc 0 → доступен; ошибка/таймаут/нет ffmpeg → недоступен.
    `run` — точка подмены в тестах (не гоняем реальный ffmpeg)."""
    ffmpeg_bin = shutil.which(ffmpeg) or ffmpeg
    cmd = [
        ffmpeg_bin, "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1",
        "-frames:v", "1", "-c:v", codec, "-pix_fmt", "yuv420p",
        "-f", "null", "-",
    ]
    runner = run or (lambda c: subprocess.run(c, capture_output=True, text=True, timeout=30))
    try:
        return runner(cmd).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

# env-переопределение энкодера/профиля (рантайм-конфиг машины рендера поверх render.yaml).
_ENCODER_ENV = "RENDER_ENCODER"
_PROFILE_ENV = "RENDER_PROFILE"


def _is_hevc(codec: str) -> bool:
    """HEVC-семейство (по любому бэкенду): нужен тег hvc1 для совместимости соцсетей/Apple."""
    c = codec.lower()
    return "hevc" in c or "265" in c


def _fmt_time(sec: float) -> str:
    """Секунды → M:SS или H:MM:SS для прогресс-строки."""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _run_ffmpeg_with_progress(
    cmd: list[str],
    *,
    reel_id: str,
    idx: int,
    total: int,
    duration_sec: float,
    cwd: str | None = None,
    batch_encoded_secs: float = 0.0,
    batch_total_secs: float = 0.0,
    batch_wall_sec: float = 0.0,
    background: bool = False,
) -> tuple[int, str]:
    """Запустить ffmpeg с отображением прогресса.

    TTY: перезаписываемая строка с баром, elapsed, ETA.
    Non-TTY / background: одна строка старт + одна строка финиш на клип (нет \\r).
    Возвращает (returncode, stderr_text).
    """
    _CLEAR_EOL = "\033[K"
    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    header = f"клип {idx}/{total}: {reel_id} ({_fmt_time(duration_sec)})"
    tty = is_tty() and not background

    if not tty:
        # Non-TTY / background: plain subprocess, one start line, one done line.
        print(f"\n{header}…", flush=True)
        stderr_chunks: list[str] = []
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", cwd=cwd,
        )
        for line in proc.stderr:
            stderr_chunks.append(line)
        proc.wait()
        wall = time.time()  # approx; no clip_start in this path
        print(f"  ✓ {header} готово", flush=True)
        return proc.returncode, "".join(stderr_chunks)

    # TTY: -progress pipe:1 for live updates.
    prog_cmd = [cmd[0], "-progress", "pipe:1"] + cmd[1:]
    stderr_chunks = []

    proc = subprocess.Popen(
        prog_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", cwd=cwd,
    )

    def _drain_stderr() -> None:
        for line in proc.stderr:
            stderr_chunks.append(line)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    clip_start_wall = time.time()
    tick = 0
    print(f"\n{header}…", flush=True)
    for line in proc.stdout:
        key, _, val = line.strip().partition("=")
        if key == "out_time_ms":
            try:
                clip_elapsed = max(0.0, int(val) / 1_000_000)
                clip_pct = min(100, int(clip_elapsed / duration_sec * 100)) if duration_sec > 0 else 0
                total_encoded = batch_encoded_secs + clip_elapsed
                total_wall = batch_wall_sec + (time.time() - clip_start_wall)
                vps = total_encoded / total_wall if total_wall > 0 else 0.0
                remaining = max(0.0, batch_total_secs - total_encoded)
                eta = remaining / vps if vps > 0 else 0.0
                bar = render_bar(clip_pct)
                spin = _SPINNER[tick % len(_SPINNER)]
                tick += 1
                eta_str = f"  ETA ~{_fmt_time(eta)}" if eta > 1 else ""
                msg = (
                    f"  {bar} {clip_pct:3d}%  "
                    f"{_fmt_time(clip_elapsed)}/{_fmt_time(duration_sec)}"
                    f"  ел {_fmt_time(total_wall)}{eta_str}  {spin}"
                )
                width = shutil.get_terminal_size(fallback=(120, 24)).columns
                if len(msg) > width:
                    msg = msg[:width - 1] + "…"
                sys.stdout.write(f"\r{_CLEAR_EOL}{msg}")
                sys.stdout.flush()
            except (ValueError, ZeroDivisionError):
                pass
        elif key == "progress" and val.strip() == "end":
            bar = render_bar(100)
            total_wall = batch_wall_sec + (time.time() - clip_start_wall)
            sys.stdout.write(
                f"\r{_CLEAR_EOL}  {bar} 100%  "
                f"{_fmt_time(duration_sec)}/{_fmt_time(duration_sec)}"
                f"  ел {_fmt_time(total_wall)}"
            )
            sys.stdout.flush()

    proc.wait()
    t.join(timeout=2)
    print(flush=True)
    return proc.returncode, "".join(stderr_chunks)


class RenderError(Exception):
    """Рендер не удался (нет исходника/inputs/, нет ffmpeg, ffmpeg вернул ошибку)."""


class SourceNotFoundError(RenderError):
    """Исходник для манифеста не найден в inputs/ — видео заархивировано или удалено.

    Отдельный тип: cmd_render перехватывает его до общего RenderError и пропускает
    манифест с предупреждением, а не считает его ошибкой рендера.
    """


def load_manifest(manifests_dir: str | Path, *, name: str = _MANIFEST_NAME) -> Manifest:
    """Прочитать и провалидировать manifest.json из папки `manifests/`.

    Манифест — единственный контракт ОБЛАКО→ЛОКАЛЬ; приходит по Syncthing. Битый/неполный
    файл или нарушение схемы → RenderError на загрузке (fail-fast), без голого traceback.
    """
    path = Path(manifests_dir) / name
    if not path.is_file():
        raise RenderError(f"манифест не найден: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise RenderError(f"не удалось прочитать манифест {path}: {e}") from e
    try:
        return Manifest.model_validate_json(text)
    except ValidationError as e:
        raise RenderError(f"невалидный манифест {path}:\n{e}") from e


def _ts(seconds: float) -> str:
    """Таймкод для ffmpeg в секундах с миллисекундной точностью."""
    return f"{seconds:.3f}"


def _ts_dur(seconds: float) -> str:
    """Duration for a ffmpeg -t flag: floor to milliseconds so we never include the frame
    that falls exactly on the segment boundary (PTS = duration → not inside [0, duration))."""
    return f"{math.floor(seconds * 1000) / 1000:.3f}"


def _basename_hint(source: str) -> str:
    """Имя файла из `source` независимо от ОС-происхождения строки (POSIX или Windows).

    Это лишь подсказка для быстрого поиска в inputs/; идентичность исходника всё равно
    проверяется по sha256, не по имени.
    """
    win = PureWindowsPath(source).name      # режет и по '\', и по '/'
    posix = PurePosixPath(source).name
    # Берём более короткий результат: тот разделитель «сработал» и отрезал каталоги.
    return win if len(win) <= len(posix) else posix


def _sibling_ffprobe(ffmpeg_bin: str) -> str:
    """ffprobe рядом с резолвнутым ffmpeg (если есть), иначе 'ffprobe' из PATH."""
    sibling = Path(ffmpeg_bin).with_name("ffprobe" + Path(ffmpeg_bin).suffix)
    return str(sibling) if sibling.exists() else "ffprobe"


def _diagnose_crop_space(source: Path, manifest: Manifest, ffmpeg_bin: str) -> None:
    """Диагностика перед рендером: в каком пространстве применяется crop и его размеры ДО
    фильтра. crop-фильтр работает в ОТОБРАЖАЕМОМ кадре (autorotate до -vf). Если реальные
    отображаемые размеры разошлись с записанными в калибровке — предупреждаем (виден разъезд)."""
    from autoreels.core.calibration import _probe_frame_size_for_auto, frame_orientation
    c = manifest.setup.crop
    mf = tuple(manifest.setup.frame)
    head = f"рендер: crop {c.w}×{c.h}@{c.x},{c.y} в отображаемом кадре"
    try:
        disp = _probe_frame_size_for_auto(source, ffprobe=_sibling_ffprobe(ffmpeg_bin))
    except Exception:
        print(f"{head} {mf[0]}×{mf[1]} (по калибровке; ffprobe недоступен)", flush=True)
        return
    print(f"{head} {disp[0]}×{disp[1]} ({frame_orientation(*disp)}, autorotate→crop)", flush=True)
    if disp != mf:
        print(f"  ⚠ отображаемый кадр рендера {disp[0]}×{disp[1]} ≠ калибровки {mf[0]}×{mf[1]} — "
              f"кроп может разъехаться (перекалибруй это видео)", flush=True)


def resolve_source(manifest: Manifest, inputs_dir: str | Path) -> Path:
    """Найти исходник по `manifest.source_sha256` (идентичность по содержимому, не по пути).

    Порядок разрешения:
      1. `manifest.source_path` — абсолютный путь, откуда файл читали при анализе (in-place
         источник лежит там же). Быстрый путь: если файл на месте И хэш совпал — берём его.
      2. `inputs_dir` — сперва по имени-подсказке, затем скан по хэшу (inputs-поток).
      3. `<inputs_dir>-archive/` — то же (заархивированный inputs-источник).
    Совпадение — только по хэшу. Если записанный путь исчез или содержимое изменилось,
    (1) молча пропускается и файл ищется по хэшу в (2)/(3). Ничего не нашли → SourceNotFoundError.
    """
    want = manifest.source_sha256
    if not want:
        raise RenderError("в манифесте нет source_sha256 — нечем идентифицировать исходник")

    scheme = getattr(manifest, "source_hash_scheme", "full")
    hash_fn = state.file_sha256_partial if scheme == "partial-p1" else state.file_sha256

    # 1. Записанный абсолютный путь (in-place — реальное место файла).
    rec = getattr(manifest, "source_path", "")
    if rec:
        rp = Path(rec)
        if rp.is_file() and hash_fn(rp) == want:
            return rp

    # 2+3. inputs/ затем архив (inputs-archive/ рядом): по имени-подсказке, затем скан.
    inputs_dir = Path(inputs_dir)
    archive_dir = inputs_dir.parent / f"{inputs_dir.name}-archive"
    hint = _basename_hint(manifest.source)
    for d in (inputs_dir, archive_dir):
        if not d.is_dir():
            continue
        by_name = d / hint
        ordered: list[Path] = [by_name] if by_name.is_file() else []
        ordered += [p for p in sorted(d.iterdir()) if p.is_file() and p != by_name]
        for p in ordered:
            if hash_fn(p) == want:
                return p

    raise SourceNotFoundError(
        f"исходник не найден по sha256={want[:12]}…: ни по записанному пути "
        f"({rec or '—'}), ни в {inputs_dir}, ни в {archive_dir} "
        f"(имя-подсказка: {hint!r})"
    )


def _bitrate_to_bps(bitrate: str) -> int:
    """'7M'→7_000_000, '128k'→128_000, '900'→900. Для оценки размера и VBV-буфера."""
    s = bitrate.strip()
    mult = 1
    if s and s[-1] in "kK":
        mult, s = 1_000, s[:-1]
    elif s and s[-1] in "mM":
        mult, s = 1_000_000, s[:-1]
    return int(float(s) * mult)


def _bufsize(video_bitrate: str) -> str:
    """VBV-буфер = 2× целевого битрейта ('7M'→'14M'): потолок пиков без раздувания размера."""
    return f"{_bitrate_to_bps(video_bitrate) * 2 // 1_000_000}M"


def estimate_size_mb(*, video_bitrate: str, audio_bitrate: str, duration_sec: float) -> float:
    """Оценка размера выходного mp4 (МБ) = (видео+аудио битрейт) × длительность / 8.

    Быстрая прикидка для отчётов/логов «клип 30с ≈ 26 МБ». Реальный размер ±10-15%
    (контейнер, VBV-колебания), но порядок величины точный — этого хватает.
    """
    total_bps = _bitrate_to_bps(video_bitrate) + _bitrate_to_bps(audio_bitrate)
    return total_bps * duration_sec / 8 / (1024 * 1024)


def _is_amf(codec: str) -> bool:
    return codec.endswith("_amf")


def _video_quality_args(codec: str, preset: str, video_bitrate: str, pix_fmt: str, *,
                        quality: str | None = None, rate_control: str | None = None,
                        qp: int | None = None) -> list[str]:
    """Аргументы rate-control/качества/пиксформата видеоэнкодера.

    По умолчанию — целевой битрейт (`-b:v` + VBV `-maxrate`/`-bufsize`): предсказуемый размер
    одним проходом (важно для соцсетей и для AMF, который без rate-control раздувал файл).
    `-preset` — только у софтверных x26x (у AMF свой).

    Качество AMF (только *_amf): `-quality quality` — режим кодера (часто важнее битрейта);
    `rate_control='cqp'` → `-rc cqp -qp_i qp -qp_p qp+2` ВМЕСТО битрейта (лучше качество,
    размер непредсказуем). Диагностика: softness — от AMF, а не от 5 Мбит/с.
    """
    args: list[str] = []
    if codec in _SOFTWARE_X26X:
        # -g 30: ~1 s keyframe interval at 30 fps — suits streaming; libx264/x265 default (250) is
        # too sparse for cloud-streaming players that need a keyframe to seek/start quickly.
        args += ["-preset", preset, "-g", "30"]
    if _is_amf(codec) and quality:
        args += ["-quality", quality]
    if _is_amf(codec) and rate_control == "cqp" and qp is not None:
        # Постоянный QP: качество приоритетно, размер плавает (для hevc_hq).
        args += ["-rc", "cqp", "-qp_i", str(qp), "-qp_p", str(qp + 2), "-pix_fmt", pix_fmt]
    else:
        args += [
            "-b:v", video_bitrate,
            "-maxrate", video_bitrate,
            "-bufsize", _bufsize(video_bitrate),
            "-pix_fmt", pix_fmt,
        ]
    # HEVC в mp4 без тега hvc1 муксится как hev1 — Apple/Safari/часть соцсетей не проигрывают.
    if _is_hevc(codec):
        args += ["-tag:v", "hvc1"]
    return args


def build_cut_cmd(
    ffmpeg: str,
    source: str | Path,
    start: float,
    end: float,
    out: str | Path,
    *,
    codec: str,
    preset: str,
    cq: int = 23,
    video_bitrate: str = "7M",
    pix_fmt: str = "yuv420p",
    faststart: bool = True,
    audio_codec: str,
    audio_bitrate: str,
    vf: str | None = None,
    af: str | None = None,
    music_path: str | Path | None = None,
    filter_complex: str | None = None,
    quality: str | None = None,
    rate_control: str | None = None,
    qp: int | None = None,
    pre_roll: float = 0.0,
) -> list[str]:
    """Собрать команду ffmpeg: вырезать окно start→end из `source`.

    Без `vf` — рез КАК ЕСТЬ (R1a, горизонтальный <id>_raw.mp4). С `vf` — добавляется
    видеофильтр (R1b: `crop=…,scale=…` → вертикальный <id>.mp4). Чистая функция (без ФС) —
    единица, которую проверяют тесты сборки команды. Seek по входу (`-ss` до `-i`) +
    `-t` (длительность) — быстрый рез с перекодированием.

    Rate-control — целевой битрейт (`video_bitrate`) под соцсети: компактный файл сразу,
    без второго прохода. `faststart` кладёт moov-atom в начало (совместимость соцсетей).
    `cq` больше не влияет на команду (битрейт-режим), оставлен для совместимости вызовов.

    `pre_roll` — seek this many seconds before `start` so the decoder crosses a keyframe
    boundary and has settled by the time the first content frame arrives. trim=start={start}
    (video) / atrim=start={start} (audio) remove the pre-roll from the encoded output.
    Not applied to the filter_complex (music) path — timing offsets in that graph are relative
    to the source start and would need separate adjustments.
    """
    duration = round(end - start, 3)
    quality_args = _video_quality_args(codec, preset, video_bitrate, pix_fmt,
                                       quality=quality, rate_control=rate_control, qp=qp)
    if filter_complex and music_path:
        # Микс с музыкой: второй вход (`-stream_loop -1` — зациклить трек), filter_complex вместо
        # -vf/-af, явные -map выходов графа ([v]/[a]). Длину задаёт `-t` + amix duration=first.
        return [
            str(ffmpeg), "-y", "-loglevel", "error",
            "-ss", _ts(start),
            "-i", str(source),
            "-stream_loop", "-1", "-i", str(music_path),
            "-t", _ts(duration),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", codec, *quality_args,
            "-c:a", audio_codec, "-b:a", audio_bitrate,
            *(["-movflags", "+faststart"] if faststart else []),
            str(out),
        ]
    if filter_complex:
        # Single-window overlay (two-shot within window, no music). Pre-roll baked into the
        # filter_complex as trim=start={pr}; input seeked to start-pr.
        pr = min(pre_roll, start) if pre_roll > 0 else 0.0
        return [
            str(ffmpeg), "-y", "-loglevel", "error",
            "-ss", _ts(start - pr),
            "-i", str(source),
            "-t", _ts(duration),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", codec, *quality_args,
            "-c:a", audio_codec, "-b:a", audio_bitrate,
            *(["-movflags", "+faststart"] if faststart else []),
            str(out),
        ]
    # Decoder warm-up: seek pre_roll seconds before start; after input-side seek, ffmpeg resets
    # frame PTS to 0, so trim uses the relative offset (pr), not the source-absolute start time.
    # pr = 0 → identical to the old path.
    pr = min(pre_roll, start) if pre_roll > 0 else 0.0
    vf_trim = f"trim=start={_num(pr)},setpts=PTS-STARTPTS"
    af_trim = f"atrim=start={_num(pr)},asetpts=PTS-STARTPTS"
    vf_full = f"{vf_trim},{vf}" if (pr > 0 and vf) else (vf_trim if pr > 0 else vf)
    af_full = f"{af_trim},{af}" if (pr > 0 and af) else (af_trim if pr > 0 else af)
    return [
        str(ffmpeg), "-y", "-loglevel", "error",
        # autorotate (ПО УМОЛЧАНИЮ, без -noautorotate): rotation-метаданные применяются ДО
        # -vf, поэтому crop-фильтр видит кадр в ОТОБРАЖАЕМОМ пространстве — том же, что и
        # калибратор (тоже autorotate). Кадр НЕ поворачиваем сами (никакого transpose):
        # вертикальность рилса даёт кроп внутри отображаемого кадра.
        "-ss", _ts(start - pr),
        *(["-t", _ts_dur(pr + duration)] if pr > 0 else []),  # input-side limit
        "-i", str(source),
        "-t", _ts(duration),
        *(["-vf", vf_full] if vf_full else []),
        *(["-af", af_full] if af_full else []),
        "-c:v", codec,
        *quality_args,
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        *(["-movflags", "+faststart"] if faststart else []),
        str(out),
    ]


_FPS_FALLBACK = 30.0
_FPS_MAX_PLAUSIBLE = 1000.0  # rejects container timebases like 90000/1
# Decoder warm-up: seek this far before each window start so the decoder has settled before
# the first content frame arrives. Covers the ~1 s keyframe interval of typical phone footage
# with a 1 s safety margin. build_cut_cmd and build_concat_cmd both honour this.
_PRE_ROLL_SEC = 2.0


def _parse_fps_token(token: str) -> float:
    """Parse 'num/den' or 'num' fps token; returns 0.0 if unparseable or implausible."""
    token = token.strip().rstrip(",;")
    num, _, den = token.partition("/")
    try:
        fps = float(num) / float(den or "1")
    except (ValueError, ZeroDivisionError):
        return 0.0
    return fps if 0 < fps <= _FPS_MAX_PLAUSIBLE else 0.0


def _probe_source_fps(source, ffprobe: str) -> float:
    """Source video frame rate (frames/sec) via ffprobe.

    Reads avg_frame_rate first (correct for VFR sources); falls back to r_frame_rate when
    avg is 0/0.  Rejects implausible values (e.g. container timebase 90000/1).  On failure
    warns and returns _FPS_FALLBACK so a probe quirk never aborts a render.
    """
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=avg_frame_rate,r_frame_rate",
         "-of", "csv=p=0", str(source)],
        capture_output=True, text=True, check=False,
    ).stdout.strip()

    # csv=p=0 with two fields → "avg/den,r/den" on one line; newlines possible if stream
    # selection returns more than one row.  Split on both separators.
    import re as _re2
    tokens = [t for t in _re2.split(r"[,\n]", out) if t.strip()]
    fps = 0.0
    for tok in tokens:
        fps = _parse_fps_token(tok)
        if fps > 0:
            break

    if not fps > 0:
        import sys as _sys
        print(
            f"warning: could not determine frame rate for {Path(source).name!r} "
            f"(raw: {out!r}); using fallback {_FPS_FALLBACK} fps",
            file=_sys.stderr,
        )
        return _FPS_FALLBACK
    return fps


def _probe_duration_sec(path, ffprobe: str) -> float | None:
    """Container duration (seconds) of a rendered file, or None if it can't be read.

    Used only by the post-render playback-duration invariant — a read failure must not mask a
    real render, so it degrades to None (skip the check) rather than raising.
    """
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return None


def _snap_windows_to_frames(segments, fps: float):
    """Quantise each playback window's start/end onto the source frame grid (1/fps).

    Why: ffmpeg cuts video to whole frames but audio to the sample. A window whose length is not
    an integer number of frames therefore renders with up to one frame of audio-vs-video mismatch;
    concatenated windows accumulate that mismatch (measured: r11 drifted 0→−30→−33→−60 ms across
    three segments), then `-shortest` hides it by clamping only the TOTAL at the end — equal totals,
    desynced middle. Snapping every boundary onto the frame grid makes each window a whole number of
    frames, so its audio and video are the same length and nothing accumulates (measured: 0 ms at
    every boundary after the fix). Applied only on the multi-window path; a single window keeps the
    byte-identical fast -ss/-t cut.
    """
    return [s.model_copy(update={"start": round(s.start * fps) / fps,
                                 "end":   round(s.end   * fps) / fps})
            for s in segments]


def _expected_output_duration(windows, *, xfade_sec: float = 0.0, speed: float = 1.0,
                              seam_xfades=None) -> float:
    """Length ffmpeg emits for these playback windows — the single source of truth shared by the
    concat graph's xfade offsets (`_concat_segments_graph`) and the post-render duration invariant.

    Plain concat (xfade_sec=0 or a single window): bare sum of window durations.

    Xfade path: each xfade seam subtracts its duration from the running total.
    seam_xfades (list[float] of length N-1): per-seam override; takes precedence over xfade_sec.
    """
    if not windows:
        return 0.0
    out_len = windows[0].end - windows[0].start
    for k, w in enumerate(windows[1:]):
        out_len += w.end - w.start
        xf = seam_xfades[k] if seam_xfades is not None else xfade_sec
        if xf > 0:
            out_len -= xf
    return out_len / speed if speed else out_len


def _duration_within_tolerance(actual: float, expected: float, fps: float) -> bool:
    """True when a rendered clip's length matches the expected length closely enough.

    Tolerance is 2.5 frames at the source fps:
    - 1 frame: xfade boundary (offset + xf = left_input_duration at exact frame boundary;
      hevc_videotoolbox with VFR source can include one extra frame at the transition).
    - 1 frame: encoder artifact (hevc_videotoolbox sometimes writes the last frame with duration
      2/fps instead of 1/fps, inflating the container duration by one frame period).
    - 0.5 frame: rounding headroom so a 2-frame deviation never fails on floating-point dust.
    Smallest defect still caught: >2.5 frames = 83 ms at 30 fps — well below a lost tail (≥1.5 s)
    or any dropped-crossfade accumulation. Scales with fps.
    """
    return abs(actual - expected) <= 2.5 / fps + 1e-6


def _assert_windows_frame_aligned(windows, fps: float) -> None:
    """Sync invariant: every playback window spans a whole number of source frames.

    A frame-aligned window has equal audio and video length (video cut to whole frames, audio to
    the sample land on the same boundary), so per-segment audio and video match within one audio
    sample and no lip-sync drift can accumulate across the concat. This replaces the old end-of-file
    total-duration check, which `-shortest` made vacuous: it is verified on the exact windows handed
    to ffmpeg, so a boundary that is not frame-aligned fails the render instead of drifting silently.
    """
    for i, (_st, dur) in enumerate(windows):
        frames = dur * fps
        off = abs(frames - round(frames))
        if off > 1e-4:
            raise RenderError(
                f"segment {i}: {dur:.4f}s at {fps:.3f} fps = {frames:.4f} frames — not frame-aligned; "
                f"audio and video would differ by {off / fps * 1000:.1f} ms (lip-sync drift)"
            )


def _concat_segments_graph(segments, edge_fade_sec: float, *,
                           video_xfade_sec: float = 0.0,
                           pre_roll: float = 0.0,
                           segment_vfs: list[str] | None = None,
                           seam_xfades: list[float] | None = None,
                           segment_overlays: "list[tuple[str, str, str] | None] | None" = None,
                           ) -> tuple[str, str, str]:
    """Filtergraph prefix that joins N pre-seeked inputs (one per window) in playback order.

    Each window is a SEPARATE ffmpeg input, opened with its own input-side `-ss`/`-t` (see
    build_concat_cmd), so input i already carries exactly window i's frames: here we only reset the
    PTS (`setpts=PTS-STARTPTS`) and concat. Nothing is trimmed from a shared decode, so a cold-open
    hook that sits LATER in the source than the body no longer forces ffmpeg to buffer every frame
    between them — that unbounded buffering was the OOM on long cold opens.

    `pre_roll > 0`: build_concat_cmd has seeked each input up to `pre_roll` seconds before the
    window start so the decoder settles before the content frame arrives. After input-side seek,
    ffmpeg resets frame PTS to 0, so the pre-roll is stripped with `trim=start={pr}` (relative),
    where `pr = min(pre_roll, s.start)`, then `setpts=PTS-STARTPTS` resets the output to PTS=0.

    Video: when `video_xfade_sec > 0`, joins with a chain of xfade filters (one per seam) so the
    pose change is masked by a short dissolve; the output is shorter than the segment sum by
    (N−1)×video_xfade_sec. When 0, plain hard concat — byte-identical to the pre-xfade path.

    Audio is joined with plain concat (no crossfade) after micro edge fades (`edge_fade_sec`, default
    10 ms). Unlike a crossfade, edge fades do not overlap the sides → audio length = video sum (not
    the shorter xfade-adjusted length); -shortest in build_concat_cmd trims it to the video.
    Returns (prefix, [vseg], [aseg]).
    """
    n = len(segments)
    f = edge_fade_sec
    parts: list[str] = []
    for i, s in enumerate(segments):
        pr = min(pre_roll, s.start) if pre_roll > 0 else 0.0
        svf = segment_vfs[i] if segment_vfs else None
        ovl = segment_overlays[i] if segment_overlays else None
        if pr > 0:
            # Input-side seek resets PTS to 0; trim relative pre-roll seconds, then reset.
            vtrim = f"trim=start={_num(pr)},setpts=PTS-STARTPTS"
            achain = f"[{i}:a]atrim=start={_num(pr)},asetpts=PTS-STARTPTS"
        else:
            vtrim = "setpts=PTS-STARTPTS"
            achain = f"[{i}:a]asetpts=PTS-STARTPTS"
        if ovl:
            # Overlay: split → wide+close branches → overlay with enable expression.
            wide_vf_o, close_vf_o, enable_o = ovl
            parts.append(f"[{i}:v]{vtrim}[raw{i}]")
            parts.append(f"[raw{i}]split=2[wi{i}][ci{i}]")
            parts.append(f"[wi{i}]{wide_vf_o}[wo{i}]")
            parts.append(f"[ci{i}]{close_vf_o}[co{i}]")
            parts.append(f"[wo{i}][co{i}]overlay=enable='{enable_o}'[v{i}]")
        else:
            vchain = f"[{i}:v]{vtrim}"
            if svf:
                vchain += f",{svf}"
            parts.append(f"{vchain}[v{i}]")
        if f > 0:
            out_st = max(0.0, (s.end - s.start) - f)
            achain += f",afade=t=in:st=0:d={_num(f)},afade=t=out:st={_num(out_st)}:d={_num(f)}"
        parts.append(f"{achain}[a{i}]")
    # Video: seam_xfades (per-seam), uniform video_xfade_sec, or plain hard concat.
    # seam_xfades takes precedence when provided; 0.0 = hard cut, >0 = xfade.
    _use_seam_xf = seam_xfades is not None and n > 1
    _use_uniform_xf = not _use_seam_xf and video_xfade_sec > 0 and n > 1
    if _use_uniform_xf:
        # All-xfade chain (existing logic).
        out_len = segments[0].end - segments[0].start
        for k in range(n - 1):
            left = f"t{k - 1}" if k > 0 else "v0"
            right = f"v{k + 1}"
            label = "vseg" if k == n - 2 else f"t{k}"
            xf_offset = round(out_len - video_xfade_sec, 9)
            parts.append(
                f"[{left}][{right}]xfade=transition=fade"
                f":duration={_num(video_xfade_sec)}:offset={_num(xf_offset)}[{label}]"
            )
            out_len = xf_offset + (segments[k + 1].end - segments[k + 1].start)
    elif _use_seam_xf:
        # Per-seam: xfade where seam_xfades[k] > 0, hard cut where 0.0.
        out_len = segments[0].end - segments[0].start
        prev = "v0"
        for k in range(n - 1):
            xf = seam_xfades[k]  # type: ignore[index]
            right = f"v{k + 1}"
            label = "vseg" if k == n - 2 else f"t{k}"
            if xf > 0:
                xf_offset = round(out_len - xf, 9)
                parts.append(
                    f"[{prev}][{right}]xfade=transition=fade"
                    f":duration={_num(xf)}:offset={_num(xf_offset)}[{label}]"
                )
                out_len = xf_offset + (segments[k + 1].end - segments[k + 1].start)
            else:
                # setsar=1 sets timebase to 1/1000000; normalize back so xfade seams
                # that follow see matching timebases on both inputs (main vs right stream).
                parts.append(f"[{prev}][{right}]concat=n=2:v=1:a=0,settb=expr=1/90000[{label}]")
                out_len += segments[k + 1].end - segments[k + 1].start
            prev = label
    else:
        parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vseg]")
    parts.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aseg]")
    return ";".join(parts), "[vseg]", "[aseg]"


def build_concat_cmd(
    ffmpeg: str,
    source: str | Path,
    out: str | Path,
    *,
    windows: list[tuple[float, float]],
    filter_complex: str,
    codec: str,
    preset: str,
    video_bitrate: str = "7M",
    pix_fmt: str = "yuv420p",
    faststart: bool = True,
    audio_codec: str,
    audio_bitrate: str,
    music_path: str | Path | None = None,
    quality: str | None = None,
    rate_control: str | None = None,
    qp: int | None = None,
    xfade_fps: float = 0.0,
    duration_sec: float | None = None,
    pre_roll: float = 0.0,
) -> list[str]:
    """ffmpeg-команда для многосегментного клипа: КАЖДОЕ окно — отдельный вход с собственным
    input-side seek (`-ss start -t dur -i source`), а `filter_complex` только сбрасывает PTS и
    склеивает их в один проход энкодера. Раздельные входы декодируются независимо: холодный старт,
    чей хук лежит в исходнике ПОЗЖЕ тела, больше не заставляет ffmpeg буферизовать все кадры между
    ними (это была причина OOM). `windows` — список (start, duration) в порядке воспроизведения;
    input-side seek так же точен, как в build_cut_cmd (одиночное окно). С музыкой добавляется
    зациклённый вход после всех окон (его индекс = len(windows))."""
    quality_args = _video_quality_args(codec, preset, video_bitrate, pix_fmt,
                                       quality=quality, rate_control=rate_control, qp=qp)
    cmd = [str(ffmpeg), "-y", "-loglevel", "error"]
    n_win = len(windows)
    for i, (st, dur) in enumerate(windows):
        # When xfade is active, pad every non-last window by 1 frame so the xfade offset
        # lands strictly inside the left input for each seam: offset + xf < left_duration.
        # Padding propagates through the xfade chain (each [tN] output is 1 frame longer),
        # so every subsequent seam's left input also has 1 extra frame.  The last window is
        # never a left input — it goes straight to the final xfade as the right stream — so
        # padding it would leak into the output and lengthen the reel by 1 frame per seam.
        pad = 1 / xfade_fps if xfade_fps > 0 and n_win > 1 and i < n_win - 1 else 0.0
        # Decoder warm-up: seek pre_roll seconds before window start; _concat_segments_graph
        # strips the pre-roll via trim=start={pr} (relative, because input-side seek resets PTS).
        pr = min(pre_roll, st) if pre_roll > 0 else 0.0
        cmd += ["-ss", _ts(st - pr), "-t", _ts_dur(pr + dur + pad), "-i", str(source)]
    if music_path:
        cmd += ["-stream_loop", "-1", "-i", str(music_path)]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", codec, *quality_args,
        "-c:a", audio_codec, "-b:a", audio_bitrate,
        # Video is the authoritative timeline (subtitles map onto it); -shortest clamps the audio
        # to it so the two stream durations are equal. The edge-fade concat already makes the audio
        # the segment-sum length; this trims only loudnorm's trailing tail / the sub-frame remainder.
        "-shortest",
        # Trim to expected duration: hardware encoders (hevc_videotoolbox, hevc_amf) add 1 extra
        # frame per xfade seam; for N windows that is N-1 frames over the 2.5-frame invariant limit.
        *(["-t", _ts_dur(duration_sec)] if duration_sec else []),
        *(["-movflags", "+faststart"] if faststart else []),
        str(out),
    ]
    return cmd


def _rotate_vf(rotation_deg: float) -> str:
    """Фильтр выравнивания горизонта: `rotate=<рад>` (+ = по часовой, как CSS-превью калибратора),
    билинейная интерполяция (дефолт ffmpeg), чёрная заливка углов. Угол 0 → пустая строка (фильтр
    НЕ добавляем — не тратим обработку). Поворот ставится ПЕРЕД кропом: кроп берёт заполненную
    область повёрнутого кадра, а не пустые треугольники по углам."""
    if not rotation_deg:
        return ""
    rad = math.radians(rotation_deg)
    return f"rotate={rad:.6f}"


def _loudnorm_str(ap: AudioProcessing) -> str:
    """Строка loudnorm по конфигу (нормализация к target_lufs)."""
    return f"loudnorm=I={_num(ap.target_lufs)}:TP={_num(ap.true_peak)}:LRA={_num(ap.loudness_range)}"


def _audio_denoise_norm(ap: AudioProcessing) -> list[str]:
    """Речевая часть: шумоподавление (если вкл) → нормализация громкости (если вкл). Без фейда."""
    parts: list[str] = []
    if ap.denoise_enabled:
        parts.append(f"afftdn=nr={_num(ap.denoise_strength)}")
    if ap.loudnorm_enabled:
        parts.append(_loudnorm_str(ap))
    return parts


def _audio_fade_parts(ap: AudioProcessing, clip_duration: float) -> list[str]:
    """afade in/out (если фейд вкл). Хвост fade-out ложится на padding-«воздух» конца клипа."""
    if not (ap.fade_enabled and ap.fade_duration > 0):
        return []
    d = ap.fade_duration
    out_st = max(0.0, round(clip_duration - d, 3))
    return [f"afade=t=in:st=0:d={_num(d)}", f"afade=t=out:st={_num(out_st)}:d={_num(d)}"]


def _tail_window_has_speech(
    ffmpeg_bin: str | Path,
    source: str | Path,
    t_start: float,
    t_end: float,
    *,
    threshold_db: float = -35.0,
) -> bool:
    """Return True if the source audio window [t_start, t_end] contains speech.

    Uses ffmpeg volumedetect: if max_volume > threshold_db → speech present.
    Returns True (conservative) on error or when window is too short to measure.
    """
    import re as _re
    window = t_end - t_start
    if window < 0.02:
        return True  # too short to measure reliably — conservative
    cmd = [
        str(ffmpeg_bin), "-hide_banner", "-loglevel", "error",
        "-ss", f"{t_start:.6f}", "-i", str(source),
        "-t", f"{window:.6f}", "-ac", "1",
        "-af", "volumedetect", "-f", "null", "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stderr
        m = _re.search(r"max_volume:\s*([-\d.]+)\s*dB", out)
        if m:
            return float(m.group(1)) > threshold_db
    except Exception:
        pass
    return True  # conservative: assume speech on error


def _tail_speech_fade(reel, segs, speed: float,
                      guard: float = 0.12) -> tuple[float, float] | None:
    """(fade_start, fade_dur) on the OUTPUT timeline to silence a next-phrase word pulled into the
    trailing air, or None when the tail is clean (→ fallback to tail_fade_sec).

    Fade starts `guard` seconds before the intruder so natural air is heard up to that point;
    afade=out holds at silence after the fade, covering the remainder of the tail. If the intruder
    is closer than `guard` from the clip start, the fade is truncated to what fits."""
    nw_start = getattr(reel, "tail_next_word_start", None)
    if nw_start is None or not segs:
        return None
    last = segs[-1]
    if nw_start >= last.end:
        # intruder starts at or beyond the segment boundary (Whisper timestamp overflow) — clean tail
        return None
    offset = sum(s.end - s.start for s in segs[:-1])
    n_out = (nw_start - last.start + offset) / speed
    start = max(0.0, n_out - guard)
    dur = n_out - start
    return (start, dur) if dur > 1e-3 else None


def _intruded_end_src(fade_start_out: float, segs, speed: float,
                      last_word_t1: float | None, margin: float = 0.0) -> float:
    """Source-time end for an intruded-tail clip.

    Converts fade_start_out (output timeline) back to source time, then clamps so the cut
    never precedes last_word_t1 + margin: guard can land inside the final word when
    nw_start ≈ t1 (Whisper places the intruder adjacent to the last subtitle word).
    margin gives extra time for Whisper t1 shortfall.
    """
    offset = sum(s.end - s.start for s in segs[:-1])
    new_end = segs[-1].start + fade_start_out * speed - offset
    if last_word_t1 is not None:
        new_end = max(new_end, last_word_t1 + margin)
    return new_end


def _assert_end_covers_last_word(reel, segs, fps: float = 30.0) -> None:
    """Invariant: clip end must include the last subtitle word.

    Uses t0 + 1 frame as the minimum: Whisper t1 can overshoot when timestamps
    overlap (next word t0 < this word t1), so t1 is not a reliable lower bound in
    those cases.  t0 is reliable — as long as the clip reaches the word's start
    the word is audible.  A genuine truncation (hundreds of ms) still fails.
    """
    if not getattr(reel, "subtitles", None):
        return
    last = reel.subtitles[-1]
    tolerance = 1.0 / fps
    # Must cover at least the start of the last word (+ one frame grace for snap).
    if segs[-1].end < last.t0 - tolerance:
        raise RuntimeError(
            f"{getattr(reel, 'id', '?')}: clip end {segs[-1].end:.4f}s precedes "
            f"last subtitle word start {last.t0:.4f}s"
        )


def _audio_tail_fade_parts(ap: AudioProcessing, out_duration: float,
                           tail_fade: tuple[float, float] | None = None) -> list[str]:
    """Always-on audio-only fade-out. Separate from `_audio_fade_parts` (the optional symmetric
    in/out, off by default) and from the 10 ms segment edge fades. NO video fade — audio only.

    With `tail_fade=(start, dur)` (intruded tail from _tail_speech_fade): fade from `start` to
    `start+dur` so the intruder plays entirely under silence. Otherwise (clean tail): ride only the
    final `tail_fade_sec` so the clip ends softly while natural breath is audible before it.
    `out_duration` is the FINAL (post-speed) clip length. Placed last in the audio chain."""
    if tail_fade is not None:
        st, d = tail_fade
        return [f"afade=t=out:st={_num(max(0.0, round(st, 3)))}:d={_num(round(d, 3))}"] if d > 0 else []
    tf = getattr(ap, "tail_fade_sec", 0.25)
    if tf <= 0:
        return []
    out_st = max(0.0, round(out_duration - tf, 3))
    return [f"afade=t=out:st={_num(out_st)}:d={_num(tf)}"]


def _audio_filter_chain(ap: AudioProcessing, clip_duration: float, *, out_duration: float | None = None,
                        tail_fade: tuple[float, float] | None = None) -> str:
    """Аудиофильтры клипа (БЕЗ музыки). Порядок: шумоподавление → нормализация → фейд → tail-фейд.
    tail-фейд считается по ФИНАЛЬной длине (`out_duration`, по умолчанию = clip_duration); `tail_fade`
    (start, dur) заглушает слово следующей фразы, попавшее в хвост. Пусто только если всё выключено И
    tail-фейд отключён."""
    out_dur = clip_duration if out_duration is None else out_duration
    return ",".join(_audio_denoise_norm(ap) + _audio_fade_parts(ap, clip_duration)
                    + _audio_tail_fade_parts(ap, out_dur, tail_fade))


def _music_filter_complex(video_vf: str, ap: AudioProcessing, music: Music,
                          clip_duration: float, *, speed: float = 1.0,
                          vin: str = "[0:v]", ain: str = "[0:a]", music_in: str = "[1:a]",
                          tail_fade: tuple[float, float] | None = None) -> str:
    """filter_complex для микса речи с фоновой музыкой. Второй вход (`-i` музыки) зациклен на
    уровне демуксера (`-stream_loop -1`); длина берётся по речи (`amix duration=first`) — короткий
    трек играет по кругу, длинный обрезается. Порядок аудио: речь(шумоподавление→нормализация) →
    микс с музыкой(громкость+фейд[+ducking]) → финальная нормализация(анти-клиппинг) → фейд клипа.

    Выходы графа: `[v]` (видео = `video_vf`) и `[a]` (готовый звук). Музыка заметно тише голоса
    (`volume`); ducking (sidechaincompress) приглушает музыку, когда звучит речь. `vin`/`ain`/
    `music_in` — входные лейблы: по умолчанию сырой источник (`[0:v]`/`[0:a]`, музыка `[1:a]`),
    но многосегментный клип подаёт сюда уже склеенные `[vseg]`/`[aseg]`."""
    parts: list[str] = []
    parts.append(f"{vin}{video_vf}[v]" if video_vf else f"{vin}null[v]")

    speech = _audio_denoise_norm(ap)              # шумоподавление → нормализация речи
    _tempo_prefix = f"atempo={speed:.4g}," if speed != 1.0 else ""
    _src = ain                                    # входной лейбл речи ([0:a] или склейка [aseg])
    speech_prefix = _tempo_prefix + ((",".join(speech) + ",") if speech else "")

    # Музыка: громкость + фейд в начале/конце (fade-out ложится в конец по длине клипа).
    mfade = ""
    if music.fade_seconds > 0:
        f = music.fade_seconds
        out_st = max(0.0, round(clip_duration - f, 3))
        mfade = f",afade=t=in:st=0:d={_num(f)},afade=t=out:st={_num(out_st)}:d={_num(f)}"
    music_chain = f"volume={_num(music.volume)}{mfade}"

    if music.ducking:
        # Речь используется дважды (в микс и как сайдчейн-триггер) → split.
        parts.append(f"{_src}{speech_prefix}asplit=2[spmix][spsc]")
        parts.append(f"{music_in}{music_chain}[mu0]")
        parts.append("[mu0][spsc]sidechaincompress=threshold=0.03:ratio=8"
                     ":attack=20:release=250[mu]")
        mix_in = "[spmix][mu]"
    else:
        parts.append(f"{_src}{speech_prefix}anull[sp]" if speech_prefix else f"{_src}anull[sp]")
        parts.append(f"{music_in}{music_chain}[mu]")
        mix_in = "[sp][mu]"

    # Микс: normalize=0 — речь остаётся на полном уровне, музыка на своей громкости.
    tail = [f"{mix_in}amix=inputs=2:duration=first:dropout_transition=0:normalize=0"]
    post: list[str] = []
    if music.final_normalize:
        post.append(_loudnorm_str(ap))     # финальная нормализация микса (анти-клиппинг)
    post += _audio_fade_parts(ap, clip_duration)
    # Always-on audio tail fade, on the FINAL (post-speed) length of the mixed track.
    post += _audio_tail_fade_parts(ap, clip_duration / speed if speed else clip_duration, tail_fade)
    mix_str = tail[0] + ("".join("," + p for p in post))
    parts.append(f"{mix_str}[a]")
    return ";".join(parts)


def _video_fade_filter(ap: AudioProcessing, clip_duration: float) -> str:
    """Видео-фейд из/в чёрное (in+out) той же длины, что аудиофейд. Пусто, если фейд выключен.
    Ставится ПОСЛЕДНИМ в видеоцепочке (после субтитров) — фейдит уже готовый кадр целиком."""
    if not (ap.fade_enabled and ap.fade_duration > 0):
        return ""
    d = ap.fade_duration
    out_st = max(0.0, round(clip_duration - d, 3))
    return f"fade=t=in:st=0:d={_num(d)},fade=t=out:st={_num(out_st)}:d={_num(d)}"


def _zoom_vf(scale, zoom: Zoom, fps: float = 30.0, offset_sec: float = 0.0) -> str:
    """zoompan hook-зума ВМЕСТО статичного scale. Качество: сэмплит уже вырезанный ПОЛНОРАЗМЕРНЫЙ
    регион (вход фильтра) и выводит SW×SH — динамический кроп меньшей области, НЕ апскейл готового
    кадра. z(t) — трапеция по времени `ot`: наезд за duration → удержание → плавный возврат к 1 в
    пределах hook_seconds, дальше базовый кадр. Пусто, если зум выключен/scheme=none → обычный scale.

    fps: source frame rate — zoompan output fps must match source to prevent A/V drift.
    offset_sec: time in output clip (seconds) where the zoom gesture starts; 0 = clip start (hook).
    Запятые внутри выражения экранированы (`\\,`), чтобы filtergraph не разбил zoompan на фильтры.
    """
    if not zoom.enabled or zoom.scheme == "none" or zoom.percent <= 0:
        return ""
    sw, sh = scale
    p = zoom.percent / 100.0
    d = zoom.duration
    h = zoom.hook_seconds
    o = offset_sec
    if o == 0.0:
        # hook at clip start: compact form preserves backward compat in tests and logs
        z = f"1+{_num(p)}*max(0\\,min(ot/{_num(d)}\\,min(({_num(h)}-ot)/{_num(d)}\\,1)))"
    else:
        # z:N offset: trapezoid shifted by o seconds
        z = (f"1+{_num(p)}*max(0\\,"
             f"min((ot-{_num(o)})/{_num(d)}\\,"
             f"min(({_num(o + h)}-ot)/{_num(d)}\\,1)))")
    return (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={sw}x{sh}:fps={_num(fps)}")


def _crop_vf(setup: SetupProfile, zoom: Zoom | None = None, fps: float = 30.0,
             offset_sec: float = 0.0) -> str:
    """Видеофильтр выравнивания+кропа+скейла из профиля сетапа: `[rotate=…,]crop=w:h:x:y,scale=SW:SH`.

    Числа — данные манифеста (`setup.crop` + `setup.scale` + `setup.rotation_deg`), НЕ хардкод.
    Порядок: rotate → crop → scale. При включённом `zoom` статичный scale заменяется на zoompan
    (зум ИЗ полноразмерного региона, без апскейла готового кадра). Кроп один на все клипы.
    fps: source frame rate passed to zoompan; ignored when zoom is None/disabled.
    offset_sec: output-time start of zoom gesture (0 = hook at clip start).
    """
    c = setup.crop
    sw, sh = setup.scale
    rot = _rotate_vf(getattr(setup, "rotation_deg", 0.0) or 0.0)
    zoom_vf = _zoom_vf(setup.scale, zoom, fps, offset_sec) if zoom is not None else ""
    tail = zoom_vf if zoom_vf else f"scale={sw}:{sh},setsar=1"
    crop_scale = f"crop={c.w}:{c.h}:{c.x}:{c.y},{tail}"
    return f"{rot},{crop_scale}" if rot else crop_scale



def _close_crop(setup: SetupProfile, scale: float = 1.25, anchor_y: float = 0.35) -> Crop:
    """Close-shot crop rectangle: tighter by `scale`, horizontally centred, vertically anchored.

    anchor_y: the point at anchor_y × wide_height stays at anchor_y × close_height (head stays in
    frame). scale < 1.0 → clamped to 1.0 with a warning. Dimensions even; rectangle inside frame.
    """
    import sys as _sys
    if scale < 1.0:
        print(f"warning: close_shot_scale {scale} < 1.0 — clamped to 1.0", file=_sys.stderr)
        scale = 1.0
    c = setup.crop
    frame_w, frame_h = setup.frame
    ch = max(2, int(c.h / scale)) & ~1
    cw = max(2, round(ch * c.w / c.h / 2) * 2)
    cx = c.x + (c.w - cw) // 2
    cy = c.y + int(anchor_y * (c.h - ch))
    cx = max(0, min(cx, frame_w - cw))
    cy = max(0, min(cy, frame_h - ch))
    cw = min(cw, frame_w - cx) & ~1
    ch = min(ch, frame_h - cy) & ~1
    return Crop(x=cx, y=cy, w=max(2, cw), h=max(2, ch))


def _crop_vf_for_crop(setup: SetupProfile, crop: Crop) -> str:
    """Video filter for an arbitrary crop rectangle: [rotate,]crop=W:H:X:Y,scale=SW:SH."""
    sw, sh = setup.scale
    rot = _rotate_vf(getattr(setup, "rotation_deg", 0.0) or 0.0)
    crop_scale = f"crop={crop.w}:{crop.h}:{crop.x}:{crop.y},scale={sw}:{sh},setsar=1"
    return f"{rot},{crop_scale}" if rot else crop_scale


def _close_intervals_enable(intervals: list[list[float]]) -> str:
    """between(t,t0,t1)+... for ffmpeg overlay enable=; times are segment-relative (post-PTS-reset)."""
    return "+".join(f"between(t,{_num(t0)},{_num(t1)})" for t0, t1 in intervals)


def assign_close_shots(segs: list[Segment], close_ranges: list[tuple[float, float]]) -> list[Segment]:
    """Mark each segment as wide/close or set close_intervals for partial coverage.

    close_ranges: source-time (start, end) pairs for the close shot.
    Segments wholly inside a close range get shot='close'.
    Segments partially overlapping get close_intervals set (segment-relative times).
    No segment is split.
    """
    if not close_ranges:
        return segs
    result = []
    for seg in segs:
        seg_dur = seg.end - seg.start
        intervals: list[list[float]] = []
        for r_start, r_end in close_ranges:
            overlap_start = max(seg.start, r_start)
            overlap_end = min(seg.end, r_end)
            if overlap_end <= overlap_start:
                continue
            rel_start = overlap_start - seg.start
            rel_end = overlap_end - seg.start
            intervals.append([round(rel_start, 6), round(rel_end, 6)])
        if not intervals:
            result.append(seg)
        elif len(intervals) == 1 and intervals[0][0] <= 0 and intervals[0][1] >= seg_dur - 1e-6:
            result.append(seg.model_copy(update={"shot": "close", "close_intervals": []}))
        else:
            result.append(seg.model_copy(update={"shot": "wide", "close_intervals": intervals}))
    return result


def _snap_close_intervals(segs: list[Segment], fps: float) -> list[Segment]:
    """Snap each segment's close_intervals boundaries to the source frame grid (1/fps).

    Same grid as _snap_windows_to_frames so overlay enable= expressions align with decoded frames.
    """
    result = []
    for seg in segs:
        ci = getattr(seg, "close_intervals", [])
        if not ci:
            result.append(seg)
        else:
            snapped = [[round(t0 * fps) / fps, round(t1 * fps) / fps] for t0, t1 in ci]
            result.append(seg.model_copy(update={"close_intervals": snapped}))
    return result


def _seg_starts_close(seg: Segment, half_frame: float = 0.05) -> bool:
    """True if segment's visual opens as close: shot=close, or close_intervals[0][0] ≈ 0."""
    if seg.shot == "close":
        return True
    ci = seg.close_intervals
    return bool(ci) and ci[0][0] < half_frame


def _seg_ends_close(seg: Segment, half_frame: float = 0.05) -> bool:
    """True if segment's visual closes as close: shot=close, or close_intervals[-1][1] ≈ duration."""
    if seg.shot == "close":
        return True
    ci = seg.close_intervals
    if not ci:
        return False
    return ci[-1][1] > (seg.end - seg.start) - half_frame


def _num(x: float) -> str:
    """Короткая запись числа для ffmpeg: 1.0→'1', 1.15→'1.15' (без хвостовых нулей)."""
    return f"{x:g}"


# Точки кривой для теней/светов. Концы (0/0, 1/1) НЕ трогаем — крайние значения не выбивают
# детали в чёрном/белом. Двигаем узлы четвертьтона (0.25) и three-quarter (0.75).
_CURVE_LOW_X = 0.25
_CURVE_HIGH_X = 0.75
_CURVE_MAX_SHIFT = 0.15    # макс. сдвиг узла при |значении|=100 — мягко, без клиппинга


def _curve_point(x: float, value: int) -> str:
    """Узел кривой `x/y`: y = x + (value/100)·MAX_SHIFT, зажат в [0,1] (страховка от клиппинга)."""
    y = x + (value / 100.0) * _CURVE_MAX_SHIFT
    y = max(0.0, min(1.0, y))
    return f"{_num(round(x, 4))}/{_num(round(y, 4))}"


def curves_filter(curves) -> str:
    """`curves` (тени/света) → ffmpeg curves. Шкала снаружи -100..+100, внутри — точки кривой.

    shadows +N поднимает узел четвертьтона (x=0.25) — вытягивает тени; highlights -N прибирает
    узел three-quarter (x=0.75) — приглушает света. Концы 0/0 и 1/1 ФИКСИРОВАНЫ (без клиппинга
    в чёрном/белом). 0/0 по обоим → пустая строка (curves не добавляется, нейтрально)."""
    s = int(getattr(curves, "shadows", 0) or 0)
    h = int(getattr(curves, "highlights", 0) or 0)
    if s == 0 and h == 0:
        return ""
    pts = ["0/0"]
    if s != 0:
        pts.append(_curve_point(_CURVE_LOW_X, s))
    if h != 0:
        pts.append(_curve_point(_CURVE_HIGH_X, h))
    pts.append("1/1")
    return "curves=all='" + " ".join(pts) + "'"


def palette_filter(palette: Palette) -> str:
    """Строка ffmpeg-фильтров цветокоррекции пресета: `curves→eq→colortemperature→unsharp`.

    Порядок ФИКСИРОВАН: сначала тональный диапазон (curves), потом общая коррекция (eq) и
    температура, резкость (unsharp) — ПОСЛЕДНЕЙ (по финальной картинке). Нейтральные значения
    (дефолты) опускаются; neutral-пресет даёт пустую строку — команда рендера не меняется.
    Вся цепочка встаёт ПОСЛЕ crop/scale и ДО ass-субтитров (субтитры цветокором не затрагиваются).
    """
    parts: list[str] = []
    curves = curves_filter(palette.curves)
    if curves:
        parts.append(curves)
    eq = palette.eq
    eq_terms: list[str] = []
    if eq.contrast != 1.0:
        eq_terms.append(f"contrast={_num(eq.contrast)}")
    if eq.brightness != 0.0:
        eq_terms.append(f"brightness={_num(eq.brightness)}")
    if eq.saturation != 1.0:
        eq_terms.append(f"saturation={_num(eq.saturation)}")
    if eq.gamma != 1.0:
        eq_terms.append(f"gamma={_num(eq.gamma)}")
    if eq_terms:
        parts.append("eq=" + ":".join(eq_terms))
    if palette.colortemperature is not None:
        parts.append(f"colortemperature=temperature={palette.colortemperature}")
    u = palette.unsharp
    if u.enabled:                      # unsharp ПОСЛЕДНИМ — резкость по финальной картинке
        parts.append(
            f"unsharp=luma_msize_x={u.luma_msize_x}:luma_msize_y={u.luma_msize_y}"
            f":luma_amount={_num(u.luma_amount)}"
        )
    return ",".join(parts)


def _render_segments(
    manifest: Manifest,
    *,
    inputs_dir: str | Path,
    out_dir: str | Path,
    render_cfg: RenderConfig,
    ffmpeg: str,
    encoder: str | None,
    vf: str | None,
    suffix: str,
    palette_vf: str = "",
    music_path: str | Path | None = None,
    profile: str | None = None,
    progress: Callable[[str], None] | None = None,
    emit_text: bool = False,
    subtitles_cfg: SubtitlesConfig | None = None,
    background: bool = False,
    zoom_cfg: "Zoom | None" = None,
) -> list[Path]:
    """Общий цикл резки сегментов. `vf` — видеофильтр (None=рез как есть, R1a),
    `suffix` — хвост имени выхода (`_raw` для горизонтального, `` для вертикального).
    `profile` — кодек-профиль (h264|hevc|av1), переопределяет активный из конфига.
    `progress` — колбэк, вызывается с id reel перед его рендером (видимый прогресс CLI).
    `emit_text` — класть рядом с клипом <id>.txt (title/description для публикации)."""
    # Абсолютные пути обязательны: при cwd=tmp_ass_dir (ass-фильтр) ffmpeg резолвит
    # относительные пути от tmp_ass_dir, а не от рабочей директории autoreels.
    source = resolve_source(manifest, inputs_dir).resolve()

    ffmpeg_bin = shutil.which(ffmpeg)
    if ffmpeg_bin is None:
        raise RenderError(
            f"ffmpeg не найден (искали '{ffmpeg}'); укажите путь к бинарю "
            f"(Windows: D:\\ffmpeg\\bin\\ffmpeg.exe) или добавьте его в PATH"
        )

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    enc = render_cfg.encoder
    aud = render_cfg.audio
    ap = render_cfg.audio_processing
    music = render_cfg.music
    # Профиль: явный аргумент > env RENDER_PROFILE > активный из конфига. Кодек+битрейт —
    # из профиля; но явный encoder (флаг/env) может переопределить только кодек (Mac-дев:
    # AMF-кодека нет → подменяем на libx26x, битрейт профиля сохраняется).
    profile_name = profile or os.environ.get(_PROFILE_ENV) or enc.profile
    validate_profile(profile_name, enc.profiles, where=f"{_PROFILE_ENV}/--profile")
    active = enc.profiles[profile_name]
    codec = encoder or os.environ.get(_ENCODER_ENV) or active.codec
    video_bitrate = active.bitrate

    if vf:                                   # только при кропе (R1b); сырой рез (R1a) без crop
        _diagnose_crop_space(source, manifest, ffmpeg_bin)

    # .ass живут в tempdir: после ffmpeg убираются автоматически, в out_dir не остаются.
    _fps_holder: list[float] = []   # source fps probed once, only if a multi-window reel needs it
    def _fps() -> float:
        if not _fps_holder:
            _fps_holder.append(_probe_source_fps(source, _sibling_ffprobe(ffmpeg_bin)))
        return _fps_holder[0]


    with tempfile.TemporaryDirectory(prefix="autoreels_ass_") as _tmp_ass:
        tmp_ass_dir = Path(_tmp_ass)
        outputs: list[Path] = []
        total = len(manifest.reels)
        batch_total_secs = sum(
            r.playback_duration() for r in manifest.reels
            if r.playback_duration() >= _MIN_CLIP_RENDER_SEC
        )
        batch_encoded_secs = 0.0
        batch_start_wall = time.time()
        for idx, reel in enumerate(manifest.reels, 1):
            try:
                reel.check_segments()   # never render a reel whose segments desynced from its bounds
            except ValueError as e:
                raise RenderError(str(e)) from e
            segs = reel.playback_windows()   # cold-open hook (if any) + body windows
            if len(segs) > 1:
                # Frame-align every window so its audio and video have identical length — otherwise
                # the per-window sub-frame mismatch accumulates into lip-sync drift across the concat
                # (see _snap_windows_to_frames). Single-window reels keep the byte-identical -ss/-t cut.
                segs = _snap_windows_to_frames(segs, _fps())
            # Snap close_intervals to the same frame grid so overlay enable= expressions land on
            # decoded frames. Done for both multi-window and single-window close paths.
            if any(getattr(s, "close_intervals", []) for s in segs):
                segs = _snap_close_intervals(segs, _fps())
            clip_dur = sum(s.end - s.start for s in segs)   # == playback_duration() for single-window
            # Snap video_xfade to frame grid for multi-window reels (fps already probed above).
            # Single-window reels never use the multi-window path, so xfade is always 0 there.
            _xfade_actual = 0.0
            if len(segs) > 1:
                _x = getattr(ap, "video_xfade_sec", 0.0)
                if _x > 0:
                    _xfade_actual = round(_x * _fps()) / _fps()

            # --- M1.7 step 1: two-shot path (feature-off → no change to vf or segs) ---
            _ts_on = getattr(render_cfg, "two_shot", False) and vf and manifest.setup is not None
            _ts_seg_vfs: list[str] | None = None
            _ts_seam_xfades: list[float] | None = None
            _ts_seg_overlays: "list[tuple[str, str, str] | None] | None" = None
            _effective_vf = vf  # the crop vf to use for base_vf; replaced for single-window close
            if _ts_on:
                _cscale = getattr(render_cfg, "close_shot_scale", 1.25)
                _canchy = getattr(render_cfg, "close_shot_anchor_y", 0.35)
                _ccrop = _close_crop(manifest.setup, scale=_cscale, anchor_y=_canchy)
                _close_vf_str = _crop_vf_for_crop(manifest.setup, _ccrop)
                if len(segs) > 1:
                    # Per-segment crops go into the prefix; vtail gets palette+ass+vfade only.
                    _ts_seg_vfs = [_close_vf_str if s.shot == "close" else vf for s in segs]  # type: ignore[list-item]
                    _ts_xf = getattr(render_cfg, "two_shot_xfade", False)
                    _half_f = 0.5 / _fps()
                    _ts_seam_xfades = [
                        (_xfade_actual if _ts_xf else 0.0)
                        if _seg_ends_close(segs[k], _half_f) != _seg_starts_close(segs[k + 1], _half_f)
                        else _xfade_actual
                        for k in range(len(segs) - 1)
                    ]
                    _effective_vf = None  # crops are in segment_vfs; vtail uses palette only
                    # Segments with close_intervals: overlay instead of plain seg_vf.
                    _has_ci = any(getattr(s, "close_intervals", []) for s in segs)
                    if _has_ci:
                        _ts_seg_overlays = [
                            (vf, _close_vf_str, _close_intervals_enable(s.close_intervals))  # type: ignore[arg-type]
                            if getattr(s, "close_intervals", []) else None
                            for s in segs
                        ]
                        # Segments with overlay get None in seg_vfs (overlay subgraph handles crop).
                        _ts_seg_vfs = [
                            None if getattr(s, "close_intervals", []) else
                            (_close_vf_str if s.shot == "close" else vf)
                            for s in segs
                        ]
                elif segs[0].shot == "close":
                    _effective_vf = _close_vf_str

            # Zoom vf: always built per-reel so zoompan runs at probed source fps (prevents A/V
            # drift). Also positions the gesture at z: sentence offset when set.
            # Skipped when two-shot overrides vf management for this reel.
            if zoom_cfg is not None and zoom_cfg.enabled and not _ts_on:
                _z_speed = getattr(reel, "speed", 1.0) or 1.0
                _z_src_t0 = getattr(reel, "zoom_source_t0", None)
                _z_offset = 0.0  # default: hook at clip start
                if _z_src_t0 is not None:
                    # Convert source timestamp to output time (accounts for speed + xfade).
                    _z_acc = 0.0
                    for _zi, _zs in enumerate(segs):
                        if _zs.start <= _z_src_t0 < _zs.end:
                            _z_offset = (_z_src_t0 - _zs.start + _z_acc) / _z_speed
                            break
                        _z_acc += _zs.end - _zs.start
                        if _xfade_actual > 0 and _zi < len(segs) - 1:
                            _z_acc -= _xfade_actual
                _effective_vf = _crop_vf(manifest.setup, zoom_cfg, _fps(), _z_offset)

            if clip_dur < _MIN_CLIP_RENDER_SEC:
                print(
                    f"  ⚠ {reel.id}: {clip_dur:.1f}с < {_MIN_CLIP_RENDER_SEC}с — "
                    f"пропущен (схлопывание границ; манифест стоит пересобрать)",
                    flush=True,
                )
                continue
            if progress is not None:
                progress(reel.id)
            out = out_dir / f"{reel.id}{suffix}.mp4"
            # Субтитры (R3): на каждый reel свой .ass; ass-фильтр ПОСЛЕ crop/scale
            # (в координатах финального кадра 1080×1920). Слова берутся из reel.subtitles.
            # Цветокор (палитра) — ПОСЛЕ crop/scale, ДО ass. Порядок: crop→scale→eq/unsharp→ass.
            # Two-shot: _effective_vf is None when per-segment crops go into the prefix — vtail
            # then only carries palette+ass+vfade (crops are already in segment_vfs).
            base_vf = _effective_vf  # type: ignore[assignment]
            if _effective_vf and palette_vf:
                base_vf = f"{_effective_vf},{palette_vf}"
            elif not _effective_vf and palette_vf:
                base_vf = palette_vf
            reel_vf = base_vf
            # Speed-up via setpts (video) + atempo (audio); both applied before other filters.
            _reel_speed = getattr(reel, "speed", 1.0)
            if _reel_speed != 1.0:
                _pts = f"setpts=PTS/{_reel_speed:.4g}"
                reel_vf = f"{_pts},{reel_vf}" if reel_vf else _pts
            ass_cwd: str | None = None
            _title = getattr(reel, "title_overlay", "") or ""
            if subtitles_cfg is not None and (reel.subtitles or _title):
                # Remap word times onto the concatenated, speed-adjusted output timeline (gap words
                # dropped). For a single span at speed 1 this equals a shift by reel.start, so the
                # output is identical to the pre-segments renderer. A title plate (Part 4) is drawn
                # on top for the first seconds when the reel carries title_overlay.
                # Pass xfade_actual so each segment's subtitle offset is shifted back by the dissolve.
                ass_words = remap_to_output(reel.subtitles, segs, speed=_reel_speed,
                                            xfade_sec=_xfade_actual)
                ass_filename = f"{reel.id}.ass"
                ass_path = tmp_ass_dir / ass_filename
                _kw_on = getattr(render_cfg, "subtitle_keywords", False)
                if not _kw_on and any(getattr(w, "emph", False) for w in reel.subtitles):
                    import sys as _sys
                    print(f"  warning ({reel.id}): has k: keywords but subtitle_keywords=False"
                          " — highlighting skipped", file=_sys.stderr)
                ass_path.write_text(
                    build_ass(ass_words, cfg=subtitles_cfg, clip_start=0.0, title=_title,
                              enable_keywords=_kw_on),
                    encoding="utf-8",
                )
                # Передаём ffmpeg только имя файла (без пути) + cwd=tmp_ass_dir.
                # Абсолютный путь в ass= фильтре ломается на Windows: двоеточие (C:)
                # и бэкслэши — синтаксис filtergraph; относительный путь безопасен.
                ass_filter = f"ass={ass_filename}"
                reel_vf = f"{base_vf},{ass_filter}" if base_vf else ass_filter
                ass_cwd = str(tmp_ass_dir)
            # Обработка звука + фейд. Видео-фейд — ПОСЛЕ субтитров (фейдит готовый кадр целиком).
            # Длина клипа = сумма сегментов (для многосегментного — без вырезанных пауз).
            _lw_margin = getattr(ap, "last_word_margin_sec", 0.2)
            _tail_fade = _tail_speech_fade(reel, segs, _reel_speed or 1.0,
                                           guard=getattr(ap, "intrusion_guard_sec", 0.12))
            if _tail_fade is not None:
                # Intruded tail: extend clip to last_t1 + margin so the final syllable isn't cut;
                # keep _tail_fade active — it mutes the intruder and holds silence in the margin window.
                _fade_st, _ = _tail_fade
                _spd = _reel_speed or 1.0
                _last_t1 = reel.subtitles[-1].t1 if reel.subtitles else None
                _new_end = _intruded_end_src(_fade_st, segs, _spd, _last_t1, margin=_lw_margin)
                # Snap UP (ceil) so the frame boundary never lands inside the margin.
                _new_end = math.ceil(_new_end * _fps()) / _fps()
                if _new_end > segs[-1].start:
                    segs = list(segs[:-1]) + [segs[-1].model_copy(update={"end": _new_end})]
                    clip_dur = sum(s.end - s.start for s in segs)
            elif reel.subtitles:
                # Clean tail: ensure end >= last_t1 + margin (Whisper t1 ends slightly early).
                # Guard: when overlapping Whisper timestamps clamped the manifest end below
                # last_t1, a naive extension would pull in the next sentence.  Check actual
                # audio energy before extending; if speech is present, keep the current end.
                # Frame-snap the extension for multi-window reels (single-window don't snap).
                _last_t1 = reel.subtitles[-1].t1
                _min_end = _last_t1 + _lw_margin
                if segs[-1].end < _min_end:
                    if not _tail_window_has_speech(ffmpeg_bin, source,
                                                   segs[-1].end, _min_end):
                        if len(segs) > 1:
                            _min_end = round(_min_end * _fps()) / _fps()
                        segs = list(segs[:-1]) + [segs[-1].model_copy(update={"end": _min_end})]
                        clip_dur = sum(s.end - s.start for s in segs)
                    # else: speech in tail → next sentence already started; keep manifest end
            _assert_end_covers_last_word(reel, segs, _fps_holder[0] if _fps_holder else 30.0)
            # clip_duration = video output length, accounting for xfade overlap at each seam.
            # Audio is plain concat (no crossfade) and is trimmed to this by -shortest. Computed from
            # the final post-snap `segs` by the same helper the invariant checks against, so the
            # expected length always matches what the concat graph emits (no re-derivation drift).
            clip_duration = _expected_output_duration(segs, xfade_sec=_xfade_actual,
                                                        seam_xfades=_ts_seam_xfades)
            vfade = _video_fade_filter(ap, clip_duration)
            if vfade:
                reel_vf = f"{reel_vf},{vfade}" if reel_vf else vfade
            # Музыка: filter_complex со вторым входом (микс речи+музыки). Без музыки — обычный -af.
            reel_fc = None
            reel_af = None
            # Final (post-speed) length: the tail fade must land on the real end of the clip.
            _out_dur = clip_duration / _reel_speed if _reel_speed else clip_duration
            if music_path:
                reel_fc = _music_filter_complex(reel_vf or "", ap, music, clip_duration, speed=_reel_speed,
                                                tail_fade=_tail_fade)
            else:
                # atempo goes FIRST; the fade st (in _out_dur / post-speed time) then lands correctly.
                reel_af = _audio_filter_chain(ap, clip_duration, out_duration=_out_dur,
                                              tail_fade=_tail_fade) or None
                if _reel_speed != 1.0:
                    _tempo = f"atempo={_reel_speed:.4g}"
                    reel_af = f"{_tempo},{reel_af}" if reel_af else _tempo
            # Single-window close_intervals: build overlay filter_complex (within-window shot change).
            if len(segs) == 1 and _ts_on and not reel_fc and _reel_speed == 1.0:
                _ci1 = getattr(segs[0], "close_intervals", [])
                if _ci1:
                    _pr1 = min(_PRE_ROLL_SEC, segs[0].start)
                    _vtrim1 = (f"trim=start={_num(_pr1)},setpts=PTS-STARTPTS"
                               if _pr1 > 0 else "setpts=PTS-STARTPTS")
                    _atrim1 = (f"atrim=start={_num(_pr1)},asetpts=PTS-STARTPTS"
                               if _pr1 > 0 else "asetpts=PTS-STARTPTS")
                    _enable1 = _close_intervals_enable(_ci1)
                    # post-overlay chain: palette → ass → vfade (no crop — overlay outputs scaled video)
                    _post_parts1: list[str] = []
                    if palette_vf:
                        _post_parts1.append(palette_vf)
                    if ass_cwd:
                        _post_parts1.append(f"ass={reel.id}.ass")
                    _vfade1 = _video_fade_filter(ap, clip_duration)
                    if _vfade1:
                        _post_parts1.append(_vfade1)
                    _post1 = ",".join(_post_parts1)
                    _v_fc = [
                        f"[0:v]{_vtrim1}[raw1]",
                        "[raw1]split=2[wi1][ci1]",
                        f"[wi1]{vf}[wo1]",
                        f"[ci1]{_close_vf_str}[co1]",
                        f"[wo1][co1]overlay=enable='{_enable1}'[vm1]",
                        f"[vm1]{_post1}[v]" if _post1 else "[vm1]null[v]",
                    ]
                    _a_fc_str = f"[0:a]{_atrim1}"
                    if reel_af:
                        _a_fc_str += f",{reel_af}"
                    _a_fc_str += "[a]"
                    reel_fc = ";".join(_v_fc) + ";" + _a_fc_str
            if len(segs) == 1:
                cmd = build_cut_cmd(
                    ffmpeg_bin, source, segs[0].start, segs[0].end, out,
                    codec=codec, preset=enc.preset,
                    video_bitrate=video_bitrate, pix_fmt=enc.pix_fmt, faststart=enc.faststart,
                    audio_codec=aud.codec, audio_bitrate=aud.bitrate,
                    vf=(None if reel_fc else reel_vf), af=(None if reel_fc else reel_af),
                    music_path=music_path, filter_complex=reel_fc,
                    quality=active.quality, rate_control=active.rate_control, qp=active.qp,
                    pre_roll=_PRE_ROLL_SEC,
                )
            else:
                # Multi-window: concat the windows (cold open + body) in a single encode. Each
                # window is its OWN input with input-side seek (build_concat_cmd), so decodes are
                # independent — a cold-open hook later in the source than the body no longer buffers
                # every frame in between (was an OOM). Input i supplies [i:v]/[i:a]; music is [n:a].
                prefix, vseg, aseg = _concat_segments_graph(segs, ap.audio_edge_fade_sec,
                                                             video_xfade_sec=_xfade_actual,
                                                             pre_roll=_PRE_ROLL_SEC,
                                                             segment_vfs=_ts_seg_vfs,
                                                             seam_xfades=_ts_seam_xfades,
                                                             segment_overlays=_ts_seg_overlays)
                windows = [(w.start, w.end - w.start) for w in segs]
                _assert_windows_frame_aligned(windows, _fps())   # per-segment A/V sync (no lip drift)
                if music_path:
                    music_fc = _music_filter_complex(reel_vf or "", ap, music, clip_duration,
                                                     speed=_reel_speed, vin=vseg, ain=aseg,
                                                     music_in=f"[{len(segs)}:a]", tail_fade=_tail_fade)
                    fc = f"{prefix};{music_fc}"
                else:
                    vtail = f"{vseg}{reel_vf}[v]" if reel_vf else f"{vseg}null[v]"
                    atail = f"{aseg}{reel_af}[a]" if reel_af else f"{aseg}anull[a]"
                    fc = f"{prefix};{vtail};{atail}"
                cmd = build_concat_cmd(
                    ffmpeg_bin, source, out, windows=windows, filter_complex=fc,
                    codec=codec, preset=enc.preset,
                    video_bitrate=video_bitrate, pix_fmt=enc.pix_fmt, faststart=enc.faststart,
                    audio_codec=aud.codec, audio_bitrate=aud.bitrate,
                    music_path=music_path,
                    quality=active.quality, rate_control=active.rate_control, qp=active.qp,
                    xfade_fps=_fps() if (
                        _xfade_actual > 0 or
                        (_ts_seam_xfades and any(x > 0 for x in _ts_seam_xfades))
                    ) else 0.0,
                    duration_sec=_out_dur,
                    pre_roll=_PRE_ROLL_SEC,
                )
            clip_dur_s = clip_duration  # actual output length (xfade-adjusted for multi-window)
            returncode, stderr_text = _run_ffmpeg_with_progress(
                cmd, reel_id=reel.id, idx=idx, total=total,
                duration_sec=clip_dur_s, cwd=ass_cwd,
                batch_encoded_secs=batch_encoded_secs,
                batch_total_secs=batch_total_secs,
                batch_wall_sec=time.time() - batch_start_wall,
                background=background,
            )
            batch_encoded_secs += clip_dur_s
            if returncode != 0:
                out.unlink(missing_ok=True)         # не оставлять битый частичный выход
                stderr = stderr_text.strip() or "(пустой stderr)"
                raise RenderError(
                    f"ffmpeg не смог обработать reel {reel.id} "
                    f"({_ts(reel.start)}→{_ts(reel.end)}, код {returncode}): {stderr}"
                )
            outputs.append(out)
            # Invariant: the file must last the length _expected_output_duration derived from the
            # final post-snap windows — the same values fed to the concat graph. Tolerance is 1.5
            # frames at source fps (see _duration_within_tolerance); a larger drift means a stage
            # changed the duration the windows do not describe (the class of bug that lost the tail).
            _inv_fps = _fps_holder[0] if _fps_holder else 30.0
            _actual = _probe_duration_sec(out, _sibling_ffprobe(ffmpeg_bin)) if out.exists() else None
            if _actual is not None and not _duration_within_tolerance(_actual, _out_dur, _inv_fps):
                raise RenderError(
                    f"{reel.id}: rendered {_actual:.3f}s but windows imply {_out_dur:.3f}s "
                    f"(Δ{_actual - _out_dur:+.3f}s > 2.5 frames) — a render stage changed the "
                    f"duration the windows do not describe"
                )
            if emit_text:
                _write_sidecar_text(out, reel, render_cfg)
        return outputs


def _write_sidecar_text(clip_path: Path, reel, render_cfg=None) -> None:
    """Publish sidecars next to the rendered clip.

    <reel>.txt          — ready-to-paste: caption (description), blank line, hashtags.
    <reel>.transcript.txt — spoken words from subtitles, plain, no timecodes.

    Both are always written (overwriting stale versions). utf-8.
    """
    from autoreels.local.hashtags import derive_hashtags
    hashtags_always = getattr(render_cfg, "hashtags_always", []) if render_cfg else []
    hashtags_max = getattr(render_cfg, "hashtags_max", 5) if render_cfg else 5
    tags = derive_hashtags(reel.subtitles, hashtags_always=hashtags_always, hashtags_max=hashtags_max)
    caption = (reel.description or "").strip()
    tags_str = " ".join(tags)
    if caption and tags_str:
        txt_content = f"{caption}\n\n{tags_str}\n"
    elif caption:
        txt_content = f"{caption}\n"
    elif tags_str:
        txt_content = f"{tags_str}\n"
    else:
        txt_content = ""
    if txt_content:
        clip_path.with_suffix(".txt").write_text(txt_content, encoding="utf-8")
    transcript = " ".join(w.word for w in reel.subtitles).strip()
    if transcript:
        clip_path.with_name(clip_path.stem + ".transcript.txt").write_text(
            transcript + "\n", encoding="utf-8"
        )


def _write_index_md(manifest: Manifest, out_dir: Path, render_cfg=None) -> None:
    """Write index.md to out_dir listing every reel: number, duration, title, caption, hashtags."""
    from autoreels.local.hashtags import derive_hashtags
    hashtags_always = getattr(render_cfg, "hashtags_always", []) if render_cfg else []
    hashtags_max = getattr(render_cfg, "hashtags_max", 5) if render_cfg else 5
    lines = [f"# {Path(manifest.source).stem}\n"]
    for i, reel in enumerate(manifest.reels, 1):
        dur = reel.playback_duration()
        mins, secs = divmod(int(dur), 60)
        dur_str = f"{mins}:{secs:02d}"
        title = (getattr(reel, "title_overlay", "") or reel.title or "").strip()
        caption = (reel.description or "").strip()
        tags = derive_hashtags(reel.subtitles, hashtags_always=hashtags_always, hashtags_max=hashtags_max)
        tags_str = " ".join(tags)
        lines.append(f"## {i}. [{dur_str}] {title or reel.id}")
        if caption:
            lines.append(f"\n{caption}")
        if tags_str:
            lines.append(f"\n{tags_str}")
        lines.append("")
    (out_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


def render_cut(
    manifest: Manifest,
    *,
    inputs_dir: str | Path,
    out_dir: str | Path,
    render_cfg: RenderConfig,
    ffmpeg: str = "ffmpeg",
    encoder: str | None = None,
    profile: str | None = None,
    progress: Callable[[str], None] | None = None,
    background: bool = False,
) -> list[Path]:
    """R1a: для каждого reel вырезать окно из исходника КАК ЕСТЬ → `out_dir`/<id>_raw.mp4.

    Кодек+битрейт — из активного `profile` (h264|hevc|av1); явный `encoder` (флаг/env)
    переопределяет только кодек. Возвращает пути сырых клипов (горизонтальный, без кропа/субтитров).
    """
    return _render_segments(
        manifest, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
        ffmpeg=ffmpeg, encoder=encoder, vf=None, suffix="_raw", profile=profile,
        progress=progress, background=background,
    )


def render_crop(
    manifest: Manifest,
    *,
    inputs_dir: str | Path,
    out_dir: str | Path,
    render_cfg: RenderConfig,
    ffmpeg: str = "ffmpeg",
    encoder: str | None = None,
    profile: str | None = None,
    palette: str | None = None,
    zoom: bool | None = None,
    music_path: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
    subtitles_cfg: SubtitlesConfig | None = None,
    background: bool = False,
) -> list[Path]:
    """R1b+R3: вырезать окно, применить кроп-профиль, цветокор и (опц.) выжечь субтитры → <id>.mp4.

    Кроп+скейл (`setup.crop` + `setup.scale`) — данные манифеста, один на все клипы. Если
    передан `subtitles_cfg` и у reel есть слова — на клип накладывается ASS (после crop/scale).
    `palette` — имя пресета палитры (переопределяет `render_cfg.palette`); цветокор встаёт
    между scale и субтитрами. `zoom` — bool-переопределение `render_cfg.zoom.enabled` (None =
    из конфига). Выход — вертикальный 1080×1920, отдельно от <id>_raw.mp4 (R1a).
    """
    pal_name = palette if palette is not None else render_cfg.palette
    palette_vf = palette_filter(render_cfg.palettes[pal_name])
    zoom_cfg = render_cfg.zoom
    if zoom is not None and zoom != zoom_cfg.enabled:
        zoom_cfg = zoom_cfg.model_copy(update={"enabled": zoom})
    outputs = _render_segments(
        manifest, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
        ffmpeg=ffmpeg, encoder=encoder, vf=_crop_vf(manifest.setup), suffix="",
        palette_vf=palette_vf, music_path=music_path,
        profile=profile, progress=progress, emit_text=True, subtitles_cfg=subtitles_cfg,
        background=background, zoom_cfg=zoom_cfg,
    )
    _write_index_md(manifest, Path(out_dir).resolve(), render_cfg)
    return outputs


def render_preview(
    manifest: Manifest,
    *,
    inputs_dir: str | Path,
    out_dir: str | Path,
    render_cfg: RenderConfig,
    ffmpeg: str = "ffmpeg",
    palettes: list[str],
    seconds: float = 6.0,
    reel_id: str | None = None,
    profile: str | None = None,
    encoder: str | None = None,
    zoom: bool | None = None,
    ztag: str = "",
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    """Короткий фрагмент (`seconds` с начала клипа) в НЕСКОЛЬКИХ палитрах — подбор цветокора
    без полного рендера всех клипов. Один файл на палитру: `<id>__<palette>[__<ztag>].mp4`.

    Берётся первый reel (или `reel_id`), окно укорачивается до `seconds`. Кроп+скейл — как в
    боевом рендере; цветокор — из каждого пресета. `zoom` (bool|None) переопределяет
    `render_cfg.zoom.enabled` — для сравнения «с зумом / без»; `ztag` добавляется в имя файла.
    Субтитры НЕ выжигаются (чистое сравнение). Возвращает пути в порядке `palettes`.
    """
    if not manifest.reels:
        raise RenderError("в манифесте нет клипов — нечего превьюить")
    reel = manifest.reels[0]
    if reel_id is not None:
        reel = next((r for r in manifest.reels if r.id == reel_id), None)
        if reel is None:
            raise RenderError(f"клип '{reel_id}' не найден в манифесте")
    short_end = min(reel.end, reel.start + seconds)
    zoom_cfg = render_cfg.zoom
    if zoom is not None and zoom != zoom_cfg.enabled:
        zoom_cfg = zoom_cfg.model_copy(update={"enabled": zoom})
    outputs: list[Path] = []
    for pal in palettes:
        if pal not in render_cfg.palettes:
            known = ", ".join(render_cfg.palettes)
            raise RenderError(f"неизвестная палитра '{pal}'; допустимо: {known}")
        palette_vf = palette_filter(render_cfg.palettes[pal])
        clip_id = f"{reel.id}__{pal}" + (f"__{ztag}" if ztag else "")
        preview_reel = reel.model_copy(update={"id": clip_id, "end": short_end,
                                               "subtitles": None})
        mini = manifest.model_copy(update={"reels": [preview_reel]})
        outputs.extend(_render_segments(
            mini, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
            ffmpeg=ffmpeg, encoder=encoder, vf=_crop_vf(mini.setup), suffix="",
            palette_vf=palette_vf, profile=profile, progress=progress,
            zoom_cfg=zoom_cfg,
        ))
    return outputs
