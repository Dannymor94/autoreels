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
import tempfile
import threading
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from pydantic import ValidationError

from autoreels.core import state
from autoreels.core.config import (
    AudioProcessing, Music, Palette, RenderConfig, SubtitlesConfig, Zoom, validate_profile,
)
from autoreels.core.models import Manifest, SetupProfile
from autoreels.local.subtitles import build_ass

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
) -> tuple[int, str]:
    """Запустить ffmpeg с отображением прогресса через -progress pipe:1.

    Печатает «клип N/M: id (D:DD)…» затем обновляемую строку «\\r  T/D (P%)».
    Возвращает (returncode, stderr_text).
    """
    prog_cmd = [cmd[0], "-progress", "pipe:1"] + cmd[1:]
    stderr_chunks: list[str] = []

    proc = subprocess.Popen(
        prog_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=cwd,
    )

    def _drain_stderr() -> None:
        for line in proc.stderr:
            stderr_chunks.append(line)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    print(f"\nклип {idx}/{total}: {reel_id} ({_fmt_time(duration_sec)})…", flush=True)
    for line in proc.stdout:
        key, _, val = line.strip().partition("=")
        if key == "out_time_ms":
            try:
                elapsed = max(0.0, int(val) / 1_000_000)
                pct = min(100, int(elapsed / duration_sec * 100)) if duration_sec > 0 else 0
                print(
                    f"\r  {_fmt_time(elapsed)}/{_fmt_time(duration_sec)} ({pct}%)",
                    end="", flush=True,
                )
            except (ValueError, ZeroDivisionError):
                pass
        elif key == "progress" and val.strip() == "end":
            print(
                f"\r  {_fmt_time(duration_sec)}/{_fmt_time(duration_sec)} (100%)",
                end="", flush=True,
            )

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
    """Найти исходник в `inputs_dir` по `manifest.source_sha256`.

    Mac-путь из `manifest.source` игнорируется (на машине рендера невалиден) — используется
    как подсказка по имени для быстрого пути. Файл с нужным хэшем не найден → RenderError.
    """
    inputs_dir = Path(inputs_dir)
    if not inputs_dir.is_dir():
        raise RenderError(f"папка inputs/ не найдена: {inputs_dir}")

    want = manifest.source_sha256
    if not want:
        raise RenderError("в манифесте нет source_sha256 — нечем идентифицировать исходник")

    # Порядок проверки: сначала файл с тем же именем (подсказка), затем остальные файлы
    # папки — чтобы не хэшировать всю inputs/, когда имя уцелело.
    hint = _basename_hint(manifest.source)
    by_name = inputs_dir / hint
    ordered: list[Path] = []
    if by_name.is_file():
        ordered.append(by_name)
    for p in sorted(inputs_dir.iterdir()):
        if p.is_file() and p != by_name:
            ordered.append(p)

    scheme = getattr(manifest, "source_hash_scheme", "full")
    hash_fn = state.file_sha256_partial if scheme == "partial-p1" else state.file_sha256
    for p in ordered:
        if hash_fn(p) == want:
            return p

    raise SourceNotFoundError(
        f"исходник не найден в {inputs_dir}: нет файла с sha256={want[:12]}… "
        f"(имя-подсказка из манифеста: {hint!r})"
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
        args += ["-preset", preset]
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
) -> list[str]:
    """Собрать команду ffmpeg: вырезать окно start→end из `source`.

    Без `vf` — рез КАК ЕСТЬ (R1a, горизонтальный <id>_raw.mp4). С `vf` — добавляется
    видеофильтр (R1b: `crop=…,scale=…` → вертикальный <id>.mp4). Чистая функция (без ФС) —
    единица, которую проверяют тесты сборки команды. Seek по входу (`-ss` до `-i`) +
    `-t` (длительность) — быстрый рез с перекодированием.

    Rate-control — целевой битрейт (`video_bitrate`) под соцсети: компактный файл сразу,
    без второго прохода. `faststart` кладёт moov-atom в начало (совместимость соцсетей).
    `cq` больше не влияет на команду (битрейт-режим), оставлен для совместимости вызовов.
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
    return [
        str(ffmpeg), "-y", "-loglevel", "error",
        # autorotate (ПО УМОЛЧАНИЮ, без -noautorotate): rotation-метаданные применяются ДО
        # -vf, поэтому crop-фильтр видит кадр в ОТОБРАЖАЕМОМ пространстве — том же, что и
        # калибратор (тоже autorotate). Кадр НЕ поворачиваем сами (никакого transpose):
        # вертикальность рилса даёт кроп внутри отображаемого кадра.
        "-ss", _ts(start),
        "-i", str(source),
        "-t", _ts(duration),
        *(["-vf", vf] if vf else []),
        *(["-af", af] if af else []),
        "-c:v", codec,
        *quality_args,
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        *(["-movflags", "+faststart"] if faststart else []),
        str(out),
    ]


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


def _audio_filter_chain(ap: AudioProcessing, clip_duration: float) -> str:
    """Аудиофильтры клипа (БЕЗ музыки). Порядок: шумоподавление → нормализация → фейд.
    Пусто — всё выключено (команда без -af)."""
    return ",".join(_audio_denoise_norm(ap) + _audio_fade_parts(ap, clip_duration))


def _music_filter_complex(video_vf: str, ap: AudioProcessing, music: Music,
                          clip_duration: float) -> str:
    """filter_complex для микса речи с фоновой музыкой. Второй вход (`-i` музыки) зациклен на
    уровне демуксера (`-stream_loop -1`); длина берётся по речи (`amix duration=first`) — короткий
    трек играет по кругу, длинный обрезается. Порядок аудио: речь(шумоподавление→нормализация) →
    микс с музыкой(громкость+фейд[+ducking]) → финальная нормализация(анти-клиппинг) → фейд клипа.

    Выходы графа: `[v]` (видео = `video_vf`) и `[a]` (готовый звук). Музыка заметно тише голоса
    (`volume`); ducking (sidechaincompress) приглушает музыку, когда звучит речь."""
    parts: list[str] = []
    parts.append(f"[0:v]{video_vf}[v]" if video_vf else "[0:v]null[v]")

    speech = _audio_denoise_norm(ap)              # шумоподавление → нормализация речи
    speech_prefix = (",".join(speech) + ",") if speech else ""

    # Музыка: громкость + фейд в начале/конце (fade-out ложится в конец по длине клипа).
    mfade = ""
    if music.fade_seconds > 0:
        f = music.fade_seconds
        out_st = max(0.0, round(clip_duration - f, 3))
        mfade = f",afade=t=in:st=0:d={_num(f)},afade=t=out:st={_num(out_st)}:d={_num(f)}"
    music_chain = f"volume={_num(music.volume)}{mfade}"

    if music.ducking:
        # Речь используется дважды (в микс и как сайдчейн-триггер) → split.
        parts.append(f"[0:a]{speech_prefix}asplit=2[spmix][spsc]")
        parts.append(f"[1:a]{music_chain}[mu0]")
        parts.append("[mu0][spsc]sidechaincompress=threshold=0.03:ratio=8"
                     ":attack=20:release=250[mu]")
        mix_in = "[spmix][mu]"
    else:
        parts.append(f"[0:a]{speech_prefix}anull[sp]" if speech_prefix else "[0:a]anull[sp]")
        parts.append(f"[1:a]{music_chain}[mu]")
        mix_in = "[sp][mu]"

    # Микс: normalize=0 — речь остаётся на полном уровне, музыка на своей громкости.
    tail = [f"{mix_in}amix=inputs=2:duration=first:dropout_transition=0:normalize=0"]
    post: list[str] = []
    if music.final_normalize:
        post.append(_loudnorm_str(ap))     # финальная нормализация микса (анти-клиппинг)
    post += _audio_fade_parts(ap, clip_duration)
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


def _zoom_vf(scale, zoom: Zoom) -> str:
    """zoompan hook-зума ВМЕСТО статичного scale. Качество: сэмплит уже вырезанный ПОЛНОРАЗМЕРНЫЙ
    регион (вход фильтра) и выводит SW×SH — динамический кроп меньшей области, НЕ апскейл готового
    кадра. z(t) — трапеция по времени `ot`: наезд за duration → удержание → плавный возврат к 1 в
    пределах hook_seconds, дальше базовый кадр. Пусто, если зум выключен/scheme=none → обычный scale.

    Запятые внутри выражения экранированы (`\\,`), чтобы filtergraph не разбил zoompan на фильтры.
    """
    if not zoom.enabled or zoom.scheme == "none" or zoom.percent <= 0:
        return ""
    sw, sh = scale
    p = zoom.percent / 100.0
    d = zoom.duration
    h = zoom.hook_seconds
    # трапеция 0→1→0: rise за d, плато, fall за d в конце hook-окна, дальше 0 (clip max→0)
    z = f"1+{_num(p)}*max(0\\,min(ot/{_num(d)}\\,min(({_num(h)}-ot)/{_num(d)}\\,1)))"
    return (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={sw}x{sh}:fps={zoom.fps}")


def _crop_vf(setup: SetupProfile, zoom: Zoom | None = None) -> str:
    """Видеофильтр выравнивания+кропа+скейла из профиля сетапа: `[rotate=…,]crop=w:h:x:y,scale=SW:SH`.

    Числа — данные манифеста (`setup.crop` + `setup.scale` + `setup.rotation_deg`), НЕ хардкод.
    Порядок: rotate → crop → scale. При включённом `zoom` статичный scale заменяется на zoompan
    (зум ИЗ полноразмерного региона, без апскейла готового кадра). Кроп один на все клипы.
    """
    c = setup.crop
    sw, sh = setup.scale
    rot = _rotate_vf(getattr(setup, "rotation_deg", 0.0) or 0.0)
    zoom_vf = _zoom_vf(setup.scale, zoom) if zoom is not None else ""
    tail = zoom_vf if zoom_vf else f"scale={sw}:{sh}"
    crop_scale = f"crop={c.w}:{c.h}:{c.x}:{c.y},{tail}"
    return f"{rot},{crop_scale}" if rot else crop_scale



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
    with tempfile.TemporaryDirectory(prefix="autoreels_ass_") as _tmp_ass:
        tmp_ass_dir = Path(_tmp_ass)
        outputs: list[Path] = []
        total = len(manifest.reels)
        for idx, reel in enumerate(manifest.reels, 1):
            clip_dur = reel.end - reel.start
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
            base_vf = vf
            if vf and palette_vf:
                base_vf = f"{vf},{palette_vf}"
            reel_vf = base_vf
            ass_cwd: str | None = None
            if subtitles_cfg is not None and reel.subtitles:
                ass_filename = f"{reel.id}.ass"
                ass_path = tmp_ass_dir / ass_filename
                ass_path.write_text(
                    build_ass(reel.subtitles, cfg=subtitles_cfg, clip_start=reel.start),
                    encoding="utf-8",
                )
                # Передаём ffmpeg только имя файла (без пути) + cwd=tmp_ass_dir.
                # Абсолютный путь в ass= фильтре ломается на Windows: двоеточие (C:)
                # и бэкслэши — синтаксис filtergraph; относительный путь безопасен.
                ass_filter = f"ass={ass_filename}"
                reel_vf = f"{base_vf},{ass_filter}" if base_vf else ass_filter
                ass_cwd = str(tmp_ass_dir)
            # Обработка звука + фейд. Видео-фейд — ПОСЛЕ субтитров (фейдит готовый кадр целиком).
            clip_duration = reel.end - reel.start
            vfade = _video_fade_filter(ap, clip_duration)
            if vfade:
                reel_vf = f"{reel_vf},{vfade}" if reel_vf else vfade
            # Музыка: filter_complex со вторым входом (микс речи+музыки). Без музыки — обычный -af.
            reel_fc = None
            reel_af = None
            if music_path:
                reel_fc = _music_filter_complex(reel_vf or "", ap, music, clip_duration)
            else:
                reel_af = _audio_filter_chain(ap, clip_duration) or None
            cmd = build_cut_cmd(
                ffmpeg_bin, source, reel.start, reel.end, out,
                codec=codec, preset=enc.preset,
                video_bitrate=video_bitrate, pix_fmt=enc.pix_fmt, faststart=enc.faststart,
                audio_codec=aud.codec, audio_bitrate=aud.bitrate,
                vf=(None if reel_fc else reel_vf), af=reel_af,
                music_path=music_path, filter_complex=reel_fc,
                quality=active.quality, rate_control=active.rate_control, qp=active.qp,
            )
            returncode, stderr_text = _run_ffmpeg_with_progress(
                cmd, reel_id=reel.id, idx=idx, total=total,
                duration_sec=reel.end - reel.start,
                cwd=ass_cwd,
            )
            if returncode != 0:
                out.unlink(missing_ok=True)         # не оставлять битый частичный выход
                stderr = stderr_text.strip() or "(пустой stderr)"
                raise RenderError(
                    f"ffmpeg не смог обработать reel {reel.id} "
                    f"({_ts(reel.start)}→{_ts(reel.end)}, код {returncode}): {stderr}"
                )
            outputs.append(out)
            if emit_text:
                _write_sidecar_text(out, reel)
        return outputs


def _write_sidecar_text(clip_path: Path, reel) -> None:
    """Текст публикации рядом с клипом: <id>.txt = title, пустая строка, description.

    Это НЕ субтитры (их вшивает R3) — это заголовок и описание поста (description уже
    несёт хэштеги по схеме R0). utf-8. Пусто и там, и там — файл не создаём.
    """
    if not (reel.title or reel.description):
        return
    txt_path = clip_path.with_suffix(".txt")
    txt_path.write_text(f"{reel.title}\n\n{reel.description}\n", encoding="utf-8")


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
) -> list[Path]:
    """R1a: для каждого reel вырезать окно из исходника КАК ЕСТЬ → `out_dir`/<id>_raw.mp4.

    Кодек+битрейт — из активного `profile` (h264|hevc|av1); явный `encoder` (флаг/env)
    переопределяет только кодек. Возвращает пути сырых клипов (горизонтальный, без кропа/субтитров).
    """
    return _render_segments(
        manifest, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
        ffmpeg=ffmpeg, encoder=encoder, vf=None, suffix="_raw", profile=profile,
        progress=progress,
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
    return _render_segments(
        manifest, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
        ffmpeg=ffmpeg, encoder=encoder, vf=_crop_vf(manifest.setup, zoom_cfg), suffix="",
        palette_vf=palette_vf, music_path=music_path,
        profile=profile, progress=progress, emit_text=True, subtitles_cfg=subtitles_cfg,
    )


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
            ffmpeg=ffmpeg, encoder=encoder, vf=_crop_vf(mini.setup, zoom_cfg), suffix="",
            palette_vf=palette_vf, profile=profile, progress=progress,
        ))
    return outputs
