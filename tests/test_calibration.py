"""Per-file кроп-калибровка — детерминированное ядро (core/calibration.py).

Determinism-first: UI/авто-детектор лишь ПРЕДЛАГАЕТ рамку (display-space); финальный кроп
(реальные px, точный 9:16, в границах кадра) считает код здесь — он и тестируется. Стор
привязан к sha256 видео (rename-proof, как resolve_source). Эти инварианты тесты защищают.
"""
import pytest

from autoreels.core.calibration import (
    CalibrationError,
    RawSelection,
    finalize_selection,
    load_calibration,
    save_calibration,
    snap_9_16,
    to_real_pixels,
)
from autoreels.core.models import Crop


# ----------------------------------------------------- пересчёт показ → реальные пиксели

def test_to_real_pixels_scales_display_box_to_frame():
    # кадр показан уменьшенным 3x (1280×720), реальный 3840×2160 → координаты ×3
    sel = RawSelection(x=10, y=20, w=30, h=40, display_size=(1280, 720), frame_size=(3840, 2160))
    assert to_real_pixels(sel) == (30.0, 60.0, 90.0, 120.0)


def test_to_real_pixels_identity_when_display_equals_frame():
    sel = RawSelection(x=100, y=50, w=200, h=400, display_size=(3840, 2160), frame_size=(3840, 2160))
    assert to_real_pixels(sel) == (100.0, 50.0, 200.0, 400.0)


# ------------------------------------------------------------------ удержание 9:16

def test_snap_9_16_enforces_aspect_ratio():
    # ширина пересчитывается из высоты под точный 9:16 (1080:1920)
    c = snap_9_16(1370, 280, 960, 1700, frame_size=(3840, 2160))
    assert (c.x, c.y, c.h) == (1370, 280, 1700)
    assert c.w == 956                       # round(1700 * 1080/1920) = round(956.25)
    assert abs(c.w / c.h - 1080 / 1920) < 0.002


def test_snap_9_16_clamps_box_inside_frame():
    # рамка вылезает за правый/нижний край → её задвигают внутрь кадра
    c = snap_9_16(3700, 2000, 600, 1067, frame_size=(3840, 2160))
    assert c.x >= 0 and c.y >= 0
    assert c.x + c.w <= 3840
    assert c.y + c.h <= 2160


# --------------------------------------------------------------- финализация (комбо)

def test_finalize_selection_combines_rescale_and_snap():
    # display-рамка на уменьшенном вдвое кадре → реальные px + 9:16 + в границах
    sel = RawSelection(x=685, y=140, w=478, h=850, display_size=(1920, 1080), frame_size=(3840, 2160))
    c = finalize_selection(sel)
    assert isinstance(c, Crop)
    assert c.x == 1370 and c.y == 280 and c.h == 1700
    assert c.w == 956                       # 9:16, из удвоенной высоты 1700
    assert c.x + c.w <= 3840 and c.y + c.h <= 2160


# ------------------------------------------------------- стор: привязка к sha256

SHA_A = "a" * 64
SHA_B = "b" * 64


def test_save_then_load_calibration_roundtrip(tmp_path):
    crop = Crop(x=1370, y=280, w=956, h=1700)
    save_calibration(
        tmp_path, source_name="PXL_test8min.mp4", source_sha256=SHA_A,
        crop=crop, frame=[3840, 2160], setup_label="tearoom_main",
    )
    setup = load_calibration(tmp_path, SHA_A)
    assert setup.crop.model_dump() == {"x": 1370, "y": 280, "w": 956, "h": 1700}
    assert setup.scale == [1080, 1920]
    assert setup.frame == [3840, 2160]
    assert setup.setup_id == "tearoom_main"     # метка из --setup → setup_id манифеста


def test_load_calibration_missing_raises_with_calibrate_hint(tmp_path):
    with pytest.raises(CalibrationError) as e:
        load_calibration(tmp_path, SHA_A)
    assert "calibrate" in str(e.value).lower()    # подсказывает откалибровать


def test_calibration_keyed_by_sha_not_name(tmp_path):
    # сохранили под sha A; запрос по другому sha B → не найдено (ключ — хэш, не имя)
    save_calibration(
        tmp_path, source_name="same_name.mp4", source_sha256=SHA_A,
        crop=Crop(x=0, y=0, w=956, h=1700), frame=[3840, 2160],
    )
    assert load_calibration(tmp_path, SHA_A) is not None
    with pytest.raises(CalibrationError):
        load_calibration(tmp_path, SHA_B)
