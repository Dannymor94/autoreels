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


# --------------------------------------------------------------- авто-кроп (centre)

from autoreels.core.calibration import auto_crop, load_or_auto_calibrate  # noqa: E402


def test_auto_crop_is_centered_horizontally():
    # 3840×2160: ширина кропа = round(2160 * 9/16) = 1215, x = (3840-1215)//2 = 1312
    c = auto_crop((3840, 2160))
    assert c.x == (3840 - c.w) // 2
    assert c.y == 0
    assert c.h == 2160


def test_auto_crop_exact_9_16_aspect():
    c = auto_crop((3840, 2160))
    assert abs(c.w / c.h - 1080 / 1920) < 0.002


def test_auto_crop_full_height():
    for frame in [(1920, 1080), (3840, 2160), (2560, 1440)]:
        c = auto_crop(frame)
        assert c.h == frame[1]


def test_load_or_auto_calibrate_uses_manual_if_exists(tmp_path):
    crop = Crop(x=1370, y=280, w=956, h=1700)
    save_calibration(tmp_path, source_name="v.mp4", source_sha256=SHA_A,
                     crop=crop, frame=[3840, 2160], setup_label="my_room")
    called = []
    setup = load_or_auto_calibrate(tmp_path, SHA_A, "v.mp4",
                                   get_frame_size=lambda: called.append(1) or (3840, 2160))
    assert called == []            # ffprobe не вызван: ручная калибровка есть
    assert setup.crop.model_dump() == {"x": 1370, "y": 280, "w": 956, "h": 1700}
    assert setup.setup_id == "my_room"


def test_load_or_auto_calibrate_creates_center_crop_when_no_calibration(tmp_path):
    setup = load_or_auto_calibrate(tmp_path, SHA_A, "v.mp4",
                                   get_frame_size=lambda: (3840, 2160))
    expected = auto_crop((3840, 2160))
    assert setup.crop.model_dump() == expected.model_dump()
    assert setup.frame == [3840, 2160]
    # и файл сохранён — повторный load_calibration работает
    from autoreels.core.calibration import load_calibration as _lc
    assert _lc(tmp_path, SHA_A).crop.model_dump() == expected.model_dump()


def test_auto_calibration_saved_with_auto_flag(tmp_path):
    import json
    from autoreels.core.calibration import calibration_path
    load_or_auto_calibrate(tmp_path, SHA_A, "v.mp4",
                           get_frame_size=lambda: (3840, 2160))
    rec = json.loads(calibration_path(tmp_path, SHA_A).read_text(encoding="utf-8"))
    assert rec.get("auto") is True


def test_manual_calibrate_overwrites_auto(tmp_path):
    # сначала авто-кроп
    load_or_auto_calibrate(tmp_path, SHA_A, "v.mp4",
                           get_frame_size=lambda: (3840, 2160))
    # потом ручная перезаписывает
    manual_crop = Crop(x=100, y=50, w=900, h=1600)
    save_calibration(tmp_path, source_name="v.mp4", source_sha256=SHA_A,
                     crop=manual_crop, frame=[3840, 2160], setup_label="manual")
    setup = load_calibration(tmp_path, SHA_A)
    assert setup.crop.model_dump() == {"x": 100, "y": 50, "w": 900, "h": 1600}
    assert setup.setup_id == "manual"
