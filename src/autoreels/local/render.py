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

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

from pydantic import ValidationError

from autoreels.core import state
from autoreels.core.config import RenderConfig
from autoreels.core.models import Manifest

# Имя файла манифеста в папке manifests/ (приходит по Syncthing с машины облака).
_MANIFEST_NAME = "manifest.json"

# Кодеки, для которых -preset/-crf — родной rate-control. Для аппаратных энкодеров
# (h264_amf/h264_vaapi/nvenc) эти флаги невалидны; их настройка — шаг 6.
_SOFTWARE_X26X = {"libx264", "libx265"}

# env-переопределение энкодера (рантайм-конфиг машины рендера поверх render.yaml).
_ENCODER_ENV = "RENDER_ENCODER"


class RenderError(Exception):
    """Рендер не удался (нет исходника/inputs/, нет ffmpeg, ffmpeg вернул ошибку)."""


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

    for p in ordered:
        if state.file_sha256(p) == want:
            return p

    raise RenderError(
        f"исходник не найден в {inputs_dir}: нет файла с sha256={want[:12]}… "
        f"(имя-подсказка из манифеста: {hint!r})"
    )


def _video_quality_args(codec: str, preset: str, cq: int) -> list[str]:
    """Аргументы качества/скорости видеоэнкодера.

    Покрыт дефолтный libx264(+x265) путь (-preset/-crf). Для аппаратных энкодеров
    rate-control задаётся на шаге 6 — здесь им отдаём только кодек (дефолтное качество),
    чтобы не подсовывать невалидные для AMF/VAAPI флаги.
    """
    if codec in _SOFTWARE_X26X:
        return ["-preset", preset, "-crf", str(cq)]
    return []


def build_cut_cmd(
    ffmpeg: str,
    source: str | Path,
    start: float,
    end: float,
    out: str | Path,
    *,
    codec: str,
    preset: str,
    cq: int,
    audio_codec: str,
    audio_bitrate: str,
) -> list[str]:
    """Собрать команду ffmpeg: вырезать окно start→end из `source` КАК ЕСТЬ (без кропа).

    Чистая функция (без обращений к ФС) — единица, которую проверяют тесты сборки команды.
    Seek по входу (`-ss` до `-i`) + `-t` (длительность) — быстрый рез с перекодированием.
    """
    duration = round(end - start, 3)
    return [
        str(ffmpeg), "-y", "-loglevel", "error",
        "-ss", _ts(start),
        "-i", str(source),
        "-t", _ts(duration),
        "-c:v", codec,
        *_video_quality_args(codec, preset, cq),
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        str(out),
    ]


def render_cut(
    manifest: Manifest,
    *,
    inputs_dir: str | Path,
    out_dir: str | Path,
    render_cfg: RenderConfig,
    ffmpeg: str = "ffmpeg",
    encoder: str | None = None,
) -> list[Path]:
    """Для каждого reel вырезать окно из локального исходника → `out_dir`/<id>_raw.mp4.

    Энкодер: явный `encoder` > env `RENDER_ENCODER` > `render_cfg.encoder.codec`. Возвращает
    пути готовых сырых клипов (горизонтальный исходник, без кропа и субтитров).
    """
    source = resolve_source(manifest, inputs_dir)

    ffmpeg_bin = shutil.which(ffmpeg)
    if ffmpeg_bin is None:
        raise RenderError(
            f"ffmpeg не найден (искали '{ffmpeg}'); укажите путь к бинарю "
            f"(Windows: D:\\ffmpeg\\bin\\ffmpeg.exe) или добавьте его в PATH"
        )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    codec = encoder or os.environ.get(_ENCODER_ENV) or render_cfg.encoder.codec
    enc = render_cfg.encoder
    aud = render_cfg.audio

    outputs: list[Path] = []
    for reel in manifest.reels:
        out = out_dir / f"{reel.id}_raw.mp4"
        cmd = build_cut_cmd(
            ffmpeg_bin, source, reel.start, reel.end, out,
            codec=codec, preset=enc.preset, cq=enc.cq,
            audio_codec=aud.codec, audio_bitrate=aud.bitrate,
        )
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            out.unlink(missing_ok=True)             # не оставлять битый частичный выход
            stderr = proc.stderr.strip() or "(пустой stderr)"
            raise RenderError(
                f"ffmpeg не смог вырезать reel {reel.id} "
                f"({_ts(reel.start)}→{_ts(reel.end)}, код {proc.returncode}): {stderr}"
            )
        outputs.append(out)
    return outputs
