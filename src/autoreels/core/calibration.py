"""Per-file кроп-калибровка: геометрия (показ→реальные px, 9:16) + стор по sha256.

Кроп теперь привязан к КОНКРЕТНОМУ видео (у каждого своя ручная калибровка), а не к
постоянному профилю сетапа. `calibrate` (local/, UI) ПРОИЗВОДИТ калибровку; `run` её
ЧИТАЕТ и кладёт в манифест. Между ними этот стор: `calibrations/<sha256>.json` —
ключ по содержимому видео (rename-proof, как identity в resolve_source).

Determinism-first: UI/авто-детектор лишь ПРЕДЛАГАЕТ рамку (RawSelection в display-space);
финальный кроп (реальные px, точный 9:16, в границах кадра) считает детерминированный код
здесь — он же и тестируется. Замена ручного калибратора на авто встанет за тот же
интерфейс (`Calibrator.propose`), `run` не меняется.

ТЕХ-ДОЛГ (зафиксировано, НЕ делать сейчас): сохранение из браузера реализуется через
download+watch (страница скачивает `<sha>.calib.json`, команда `calibrate` ловит его в
Downloads/). Это компромисс из-за serverless HTML без бэкенда. Если на реальном потоке
ручное перетаскивание из Downloads окажется муторным — перейти на эфемерный localhost-
сервер: страница POST'ит координаты, файл пишется сразу, без Downloads.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from pydantic import ValidationError

from autoreels.core.models import Crop, SetupProfile

# Целевое вертикальное разрешение 9:16 — единственно допустимое (как в core/config).
TARGET_SCALE = [1080, 1920]
_ASPECT = TARGET_SCALE[0] / TARGET_SCALE[1]   # 1080/1920 = 9/16 = 0.5625


class CalibrationError(Exception):
    """Кроп не откалиброван / битая калибровка. Останавливает run (fail-fast)."""


@dataclass(frozen=True)
class RawSelection:
    """Сырая рамка из UI (или авто-детектора): display-space + размеры показа и кадра.

    Это то, что ПРЕДЛАГАЕТ калибратор; финал считает код (to_real_pixels → snap_9_16).
    """

    x: float
    y: float
    w: float
    h: float
    display_size: tuple[int, int]    # размер кадра как он показан (м.б. уменьшен)
    frame_size: tuple[int, int]      # реальный размер исходника (напр. 3840×2160)


class Calibrator(Protocol):
    """Интерфейс калибровки: кадр → сырая рамка. Ручной (UI) сейчас, авто-детект потом."""

    def propose(self, frame_png: Path, frame_size: tuple[int, int]) -> RawSelection: ...


# ------------------------------------------------------------------------ геометрия

def to_real_pixels(sel: RawSelection) -> tuple[float, float, float, float]:
    """Пересчитать display-рамку в реальные пиксели исходника (кадр мог быть уменьшен)."""
    dw, dh = sel.display_size
    fw, fh = sel.frame_size
    sx, sy = fw / dw, fh / dh
    return (sel.x * sx, sel.y * sy, sel.w * sx, sel.h * sy)


def snap_9_16(x: float, y: float, w: float, h: float, *, frame_size: tuple[int, int]) -> Crop:
    """Привести рамку к точному 9:16 и вписать в кадр (детерминированный финал).

    Якорь — высота (вертикальный кроп): ширина пересчитывается из высоты под 9:16.
    Затем рамка задвигается внутрь кадра и округляется до целых пикселей.
    """
    fw, fh = frame_size
    h = min(round(h), fh)
    w = min(round(h * _ASPECT), fw)
    x = max(0, min(round(x), fw - w))
    y = max(0, min(round(y), fh - h))
    return Crop(x=x, y=y, w=w, h=h)


def finalize_selection(sel: RawSelection) -> Crop:
    """Сырая рамка из UI → финальный кроп: пересчёт в реальные px + 9:16 + в границах."""
    x, y, w, h = to_real_pixels(sel)
    return snap_9_16(x, y, w, h, frame_size=sel.frame_size)


# --------------------------------------------------------------- стор (ключ = sha256)

def calibration_path(calibrations_dir: str | Path, source_sha256: str) -> Path:
    """Путь к калибровке видео: <calibrations_dir>/<sha256>.json."""
    return Path(calibrations_dir) / f"{source_sha256}.json"


def save_calibration(
    calibrations_dir: str | Path,
    *,
    source_name: str,
    source_sha256: str,
    crop: Crop,
    frame,
    setup_label: str | None = None,
) -> Path:
    """Записать калибровку для файла (ключ — sha256). `setup_label` → setup_id манифеста."""
    calibrations_dir = Path(calibrations_dir)
    calibrations_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "source_name": source_name,
        "source_sha256": source_sha256,
        "setup_label": setup_label or Path(source_name).stem,
        "crop": crop.model_dump(),
        "scale": TARGET_SCALE,
        "frame": list(frame),
    }
    path = calibration_path(calibrations_dir, source_sha256)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_calibration(calibrations_dir: str | Path, source_sha256: str) -> SetupProfile:
    """Прочитать калибровку видео по sha256 → SetupProfile для манифеста.

    Нет файла → CalibrationError с подсказкой откалибровать.
    """
    path = calibration_path(calibrations_dir, source_sha256)
    if not path.is_file():
        raise CalibrationError(
            f"кроп не откалиброван (sha256={source_sha256[:12]}…) — "
            f"сначала: autoreels calibrate <video>"
        )
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise CalibrationError(f"битая калибровка {path}: {e}") from e
    try:
        return SetupProfile(
            setup_id=rec.get("setup_label") or "calibrated",
            crop=Crop.model_validate(rec["crop"]),
            scale=rec.get("scale", TARGET_SCALE),
            frame=rec["frame"],
        )
    except (KeyError, ValidationError) as e:
        raise CalibrationError(f"невалидная калибровка {path}: {e}") from e


# ----------------------------------------------------------------- авто-кроп (центр)

def auto_crop(frame_size: tuple[int, int]) -> Crop:
    """Центральный кроп 9:16 из кадра: полная высота, ширина под аспект, x по центру."""
    W, H = frame_size
    w = round(H * _ASPECT)
    x = (W - w) // 2
    return Crop(x=x, y=0, w=w, h=H)


def _probe_frame_size_for_auto(video: str | Path, *, ffprobe: str = "ffprobe") -> tuple[int, int]:
    """ffprobe → (width, height) исходника. Точка подмены в тестах."""
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=False,
    )
    try:
        parts = proc.stdout.strip().split(",")
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError) as e:
        raise CalibrationError(f"не удалось определить размер кадра {video}: {proc.stderr.strip()}") from e


def load_or_auto_calibrate(
    calibrations_dir: str | Path,
    source_sha256: str,
    source_name: str,
    *,
    get_frame_size: Callable[[], tuple[int, int]],
) -> SetupProfile:
    """Вернуть SetupProfile: ручная калибровка (если есть) или авто-кроп по центру.

    Авто-кроп сохраняется с `"auto": true` — ручной `calibrate` его перезапишет.
    Сообщение пользователю: чтобы не молчать про центр-кроп.
    """
    calibrations_dir = Path(calibrations_dir)
    path = calibration_path(calibrations_dir, source_sha256)
    if path.is_file():
        return load_calibration(calibrations_dir, source_sha256)

    print(
        "кроп не откалиброван → авто-кроп по центру "
        "(autoreels calibrate <video> для ручной настройки)",
        flush=True,
    )
    frame_size = get_frame_size()
    crop = auto_crop(frame_size)
    calibrations_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "source_name": source_name,
        "source_sha256": source_sha256,
        "setup_label": "auto",
        "crop": crop.model_dump(),
        "scale": TARGET_SCALE,
        "frame": list(frame_size),
        "auto": True,
    }
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return SetupProfile(
        setup_id="auto",
        crop=crop,
        scale=TARGET_SCALE,
        frame=list(frame_size),
    )
