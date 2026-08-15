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


def frame_orientation(frame_w: int, frame_h: int) -> str:
    """Ориентация ОТОБРАЖАЕМОГО кадра: 'vertical' (h>w) / 'horizontal' (w>h) / 'square'."""
    if frame_h > frame_w:
        return "vertical"
    if frame_w > frame_h:
        return "horizontal"
    return "square"


def validate_crop_in_frame(crop: Crop, frame_w: int, frame_h: int) -> None:
    """Жёсткая проверка кропа против ОТОБРАЖАЕМЫХ размеров кадра (то, что видит человек и что
    видит crop-фильтр рендера после autorotate). Падает с числами (НЕ молча клампить):

    - вписан в кадр: x+w ≤ W, y+h ≤ H, x,y ≥ 0 — ловит рассинхрон пространств (ш/в перепутаны);
    - соотношение ≈ 9:16 — рилс вертикальный (кроп это подмножество/полоса, не поворот кадра).

    Поворот кадра мы НЕ применяем: вертикальность рилса — всегда кроп внутри отображаемого кадра.
    """
    if crop.x < 0 or crop.y < 0 or crop.x + crop.w > frame_w or crop.y + crop.h > frame_h:
        raise CalibrationError(
            f"кроп выходит за границы кадра: x={crop.x} y={crop.y} "
            f"right={crop.x + crop.w}/bottom={crop.y + crop.h} при кадре {frame_w}×{frame_h}. "
            f"Похоже координаты в другом пространстве (поворот/SAR) — перекалибруй."
        )
    ratio = crop.w / crop.h
    if abs(ratio - _ASPECT) > 0.02:
        raise CalibrationError(
            f"кроп не 9:16: {crop.w}×{crop.h} (соотношение {ratio:.3f}, ожидается {_ASPECT:.3f}). "
            f"Рилс вертикальный — рамка должна быть 9:16."
        )


def crop_orientation_warnings(crop: Crop, frame_w: int, frame_h: int) -> list[str]:
    """Мягкие предупреждения по ориентации (не падать, но подсветить вероятную ошибку рамки).

    Вертикальный кадр: кроп ≈ весь кадр (нечего приближать) или шире кадра. Горизонтальный:
    кроп занимает почти всю ширину (пользователь, вероятно, нарисовал горизонтальную рамку —
    из 16:9 нужна узкая вертикальная полоса)."""
    warns: list[str] = []
    orient = frame_orientation(frame_w, frame_h)
    if orient == "vertical":
        if crop.w > frame_w:
            warns.append(f"кроп шире кадра: {crop.w} > {frame_w}px")
        if crop.h >= 0.97 * frame_h:
            warns.append(
                f"кроп почти во весь кадр (высота {crop.h}/{frame_h}px) — приближать нечего"
            )
    elif orient == "horizontal":
        if crop.w >= 0.9 * frame_w:
            warns.append(
                f"из горизонтального кадра ({frame_w}×{frame_h}) кроп занимает почти всю ширину "
                f"({crop.w}px) — ожидалась узкая вертикальная полоса 9:16"
            )
    return warns


def finalize_selection(sel: RawSelection) -> Crop:
    """Сырая рамка из UI → финальный кроп: пересчёт в реальные px + 9:16 + в границах.

    Жёсткая валидация ДО клампа: если сырая рамка заметно вылезает за кадр (>2px допуска) —
    ошибка, а не молчаливый кламп (иначе рамка в чужом пространстве проходит и ломает рендер).
    """
    x, y, w, h = to_real_pixels(sel)
    fw, fh = sel.frame_size
    tol = 2
    if x + w > fw + tol or y + h > fh + tol or x < -tol or y < -tol:
        raise CalibrationError(
            f"рамка вне кадра: право={round(x + w)}/низ={round(y + h)} при кадре {fw}×{fh} — "
            f"вероятно координаты в другом пространстве (поворот/SAR)"
        )
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
        # Пространство координат — ОТОБРАЖАЕМОЕ: кадр калибровки извлечён с autorotate (как
        # видит человек), рендер тоже autorotate → crop-фильтр в том же повёрнутом кадре.
        # frame здесь = display-размеры (после rotation-метаданных). Поворот кадра не делаем —
        # вертикальность рилса достигается кропом.
        "rotation_applied": True,
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
    """Центральный кроп 9:16 из ОТОБРАЖАЕМОГО кадра: полная высота, ширина под аспект, x по центру.

    frame_size — отображаемые (после rotation) размеры, то же пространство, где рендерит crop-фильтр.
    Вертикальный кадр (h≥w*9/16): ширина = h*9/16 ≤ w → берём полную высоту, полосу по центру.
    Горизонтальный: та же формула даёт узкую вертикальную полосу. В обоих случаях кроп ВПИСАН
    в кадр (никогда не шире), потому что 9:16 всегда уже квадрата."""
    W, H = frame_size
    w = round(H * _ASPECT)
    if w > W:                       # экстремально узкий кадр (H*9/16 > W) — упираем в ширину
        w = W
    x = (W - w) // 2
    return Crop(x=x, y=0, w=w, h=H)


def _rotation_from_stream(stream: dict) -> int:
    """Угол поворота из ffprobe-стрима: display-matrix side_data (совр. ffmpeg) или tag rotate
    (старые файлы). Нормализуется в целые градусы; направление знака не важно (берём abs%180)."""
    rot = 0
    tags = stream.get("tags") or {}
    if "rotate" in tags:
        try:
            rot = int(float(tags["rotate"]))
        except (TypeError, ValueError):
            pass
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    return rot


def display_size_from_stream(stream: dict) -> tuple[int, int]:
    """Кодированные width/height + rotation → ОТОБРАЖАЕМЫЕ (что видит человек, что даёт
    ffmpeg autorotate). При повороте на ±90° меняем ш/в местами. Чистая функция (тестируема)."""
    w, h = int(stream["width"]), int(stream["height"])
    if abs(_rotation_from_stream(stream)) % 180 == 90:
        w, h = h, w
    return (w, h)


def _probe_frame_size_for_auto(video: str | Path, *, ffprobe: str = "ffprobe") -> tuple[int, int]:
    """ffprobe → ОТОБРАЖАЕМЫЕ (display, после rotation-метаданных) width×height исходника.

    Это единое пространство координат калибратора и рендера: ffmpeg по умолчанию autorotate,
    и калибровка, и crop-фильтр видят кадр в этой ориентации. НЕ кодированное (иначе для
    телефонных видео с rotation ш/в перепутаны). Точка подмены в тестах."""
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_streams", "-of", "json", str(video)],
        capture_output=True, text=True, check=False,
    )
    try:
        streams = json.loads(proc.stdout or "{}").get("streams") or []
        return display_size_from_stream(streams[0])
    except (json.JSONDecodeError, IndexError, KeyError, ValueError) as e:
        raise CalibrationError(f"не удалось определить размер кадра {video}: {proc.stderr.strip()}") from e


def _read_calibration_meta(path: Path) -> dict:
    """Сырой JSON калибровки (для диагностики: kind/rotation_applied/frame/source_name)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_or_auto_calibrate(
    calibrations_dir: str | Path,
    source_sha256: str,
    source_name: str,
    *,
    get_frame_size: Callable[[], tuple[int, int]],
) -> SetupProfile:
    """Вернуть SetupProfile: ручная калибровка (если есть по ключу) или авто-кроп по центру.

    ЯВНО логирует исход (найдена/не найдена/какая) — откат на автокроп НЕ должен быть молчаливым.
    Защита: если по ключу калибровки нет, но в каталоге есть РУЧНАЯ калибровка для видео с тем же
    именем файла — это почти наверняка «тот самый» файл под другим хэшем (файл изменился/пересжат).
    В этом случае ПАДАЕМ, а не подменяем ручную настройку автокропом (инвариант «не молча»).
    """
    calibrations_dir = Path(calibrations_dir)
    path = calibration_path(calibrations_dir, source_sha256)
    print(f"ищу калибровку по ключу sha={source_sha256[:12]}… в {calibrations_dir}", flush=True)
    if path.is_file():
        rec = _read_calibration_meta(path)
        setup = load_calibration(calibrations_dir, source_sha256)
        kind = "авто" if rec.get("auto") else "РУЧНАЯ"
        rot = rec.get("rotation_applied")
        c = setup.crop
        print(f"калибровка найдена ({kind}): {path.name}  "
              f"кроп {c.w}×{c.h}@{c.x},{c.y}, кадр {setup.frame}, rotation_applied={rot}", flush=True)
        return setup

    # По ключу не найдена — показать, что искали и что вообще есть в каталоге.
    existing = sorted(calibrations_dir.glob("*.json")) if calibrations_dir.is_dir() else []
    print(f"калибровка НЕ найдена по ключу sha={source_sha256[:12]}…", flush=True)
    if existing:
        print(f"  калибровки в каталоге: {', '.join(p.name for p in existing)}", flush=True)
    # Есть ли РУЧНАЯ калибровка для файла с этим же именем? Тогда это «тот самый» видос под
    # другим хэшем — не подменяем автокропом молча, а требуем перекалибровать именно его.
    for p in existing:
        meta = _read_calibration_meta(p)
        if not meta.get("auto") and meta.get("source_name") == source_name:
            raise CalibrationError(
                f"есть ручная калибровка для «{source_name}» ({p.name}), но под ДРУГИМ хэшем "
                f"(искали {source_sha256[:12]}…). Видеофайл изменился/пересжат после калибровки "
                f"или это другая копия. Перекалибруй именно это видео: autoreels calibrate "
                f"«{source_name}». Автокроп НЕ подставляю (ручная настройка важнее)."
            )

    frame_size = get_frame_size()
    print(
        f"кроп не откалиброван → авто-кроп 9:16 по центру в ОТОБРАЖАЕМОМ кадре "
        f"{frame_size[0]}×{frame_size[1]} (autoreels calibrate <video> для ручной настройки)",
        flush=True,
    )
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
