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
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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

    Нет файла → CalibrationError с подсказкой откалибровать (это и ОСТАНАВЛИВАЕТ run).
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
