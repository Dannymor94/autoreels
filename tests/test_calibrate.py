"""Команда `autoreels calibrate` — бэкенд на ЛОКАЛЬНОМ СЕРВЕРЕ (local/calibrate.py).

Транспорт: эфемерный localhost-сервер (stdlib http.server, без Flask). GET / отдаёт HTML,
POST /save принимает {display, display_size, frame_size} → finalize_selection → save →
ответ OK → сервер гасится. Живёт ОДНУ калибровку, не висит фоном; таймаут + Ctrl-C гасят.

Ядро (finalize/save/геометрия) НЕ трогается — только транспорт. UI (fetch POST) — отдельно.
ffmpeg/ffprobe мокаются; POST-хендлер дёргается напрямую (без браузера).
"""
import json
import threading
import time

import httpx
import pytest

from autoreels.core.calibration import RawSelection
from autoreels.local import calibrate as cal
from autoreels.local.calibrate import (
    CalibrateError,
    ManualCalibrator,
    build_calibration_html,
    build_frame_cmd,
    cmd_calibrate,
    extract_preview_frames,
    parse_frame_at,
    parse_probe,
    raw_selection_from_drop,
)


# ------------------------------------------------------------ извлечение кадра / probe

def test_build_frame_cmd_seeks_and_takes_one_frame():
    cmd = build_frame_cmd("ffmpeg", "/in/v.mp4", "/out/f.png", at_seconds=240.0)
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-ss") + 1] == "240.000"          # seek в середину
    assert "-frames:v" in cmd and cmd[cmd.index("-frames:v") + 1] == "1"
    assert cmd[-1] == "/out/f.png"


def test_parse_probe_reads_width_height_duration():
    assert parse_probe("3840\n2160\n480.0\n") == (3840, 2160, 480.0)


# -------------------------- поворот: калибратор и рендер в ЕДИНОМ (ОТОБРАЖАЕМОМ) пространстве

def test_calibration_frame_extract_autorotates_by_default():
    """Кадр калибровки извлекается С autorotate (нет -noautorotate) → ОТОБРАЖАЕМОЕ пространство,
    как человек видит видео и как рендерит crop-фильтр. Кадр сами не поворачиваем."""
    cmd = build_frame_cmd("ffmpeg", "/in/v.mp4", "/out/f.png", at_seconds=100.0)
    assert "-noautorotate" not in cmd


def test_render_and_calibration_same_displayed_space():
    """Рендер (crop-фильтр) и калибратор оба autorotate (без -noautorotate) → одно
    отображаемое пространство координат. rotation применяется ДО -vf (crop видит его)."""
    from autoreels.local.render import build_cut_cmd
    frame_cmd = build_frame_cmd("ffmpeg", "/v.mp4", "/f.png", at_seconds=10.0)
    cut_cmd = build_cut_cmd("ffmpeg", "/v.mp4", 0.0, 5.0, "/o.mp4", codec="libx264",
                            preset="medium", audio_codec="aac", audio_bitrate="128k", vf="crop=1:1:0:0")
    assert "-noautorotate" not in frame_cmd and "-noautorotate" not in cut_cmd
    # crop-фильтр идёт ПОСЛЕ -i → autorotate (вставляется ffmpeg до -vf) применяется раньше
    assert cut_cmd.index("-vf") > cut_cmd.index("-i")


def test_display_size_from_stream_swaps_on_rotation():
    """Отображаемые размеры: coded ш×в + rotation-метаданные → при ±90° меняем ш/в местами."""
    from autoreels.core.calibration import display_size_from_stream
    # телефон снял вертикально: coded 2688×1512 + display-matrix rotation -90 → показ 1512×2688
    st_rot = {"width": 2688, "height": 1512,
              "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}
    assert display_size_from_stream(st_rot) == (1512, 2688)
    # горизонтальное без поворота — как есть
    assert display_size_from_stream({"width": 3840, "height": 2160}) == (3840, 2160)
    # старый файл с tag rotate=90
    assert display_size_from_stream({"width": 1920, "height": 1080,
                                     "tags": {"rotate": "90"}}) == (1080, 1920)


# ------------------------------------------------ жёсткая валидация: границы + соотношение 9:16

def test_validate_crop_in_frame_bounds_and_aspect():
    from autoreels.core.calibration import validate_crop_in_frame, CalibrationError
    from autoreels.core.models import Crop
    # выход за границы отображаемого кадра → ошибка с числами
    with pytest.raises(CalibrationError) as e:
        validate_crop_in_frame(Crop(x=0, y=0, w=1512, h=2800), 1512, 2688)
    assert "2800" in str(e.value) and "1512×2688" in str(e.value)
    # не 9:16 (пользователь/пространство перепутаны) → ошибка
    with pytest.raises(CalibrationError):
        validate_crop_in_frame(Crop(x=0, y=0, w=1400, h=700), 1512, 2688)
    # нормальный вертикальный 9:16 внутри кадра — не бросает
    validate_crop_in_frame(Crop(x=96, y=170, w=1320, h=2347), 1512, 2688)


def test_frame_orientation():
    from autoreels.core.calibration import frame_orientation
    assert frame_orientation(1512, 2688) == "vertical"
    assert frame_orientation(3840, 2160) == "horizontal"
    assert frame_orientation(1080, 1080) == "square"


def test_crop_orientation_warnings():
    from autoreels.core.calibration import crop_orientation_warnings
    from autoreels.core.models import Crop
    # вертикальный кадр, кроп почти во весь кадр — нечего приближать
    warns = crop_orientation_warnings(Crop(x=0, y=0, w=1512, h=2688), 1512, 2688)
    assert any("приближать" in w for w in warns)
    # горизонтальный кадр, кроп занимает почти всю ширину — вероятно нарисовали горизонтальную рамку
    warns = crop_orientation_warnings(Crop(x=0, y=0, w=3800, h=2160), 3840, 2160)
    assert any("вертикальн" in w for w in warns)
    # разумное приближение спикера в вертикали — без предупреждений
    assert crop_orientation_warnings(Crop(x=96, y=170, w=1320, h=2347), 1512, 2688) == []


def test_finalize_selection_rejects_out_of_bounds():
    """Сырая рамка вылезает за кадр (координаты в другом пространстве) → ошибка, не молчаливый кламп."""
    from autoreels.core.calibration import finalize_selection, CalibrationError, RawSelection
    sel = RawSelection(x=100, y=100, w=300, h=2800,     # y+h=2900 > 2688 (real=display)
                       display_size=(1512, 2688), frame_size=(1512, 2688))
    with pytest.raises(CalibrationError):
        finalize_selection(sel)


def test_cmd_calibrate_rejects_crop_out_of_displayed_frame(tmp_path, monkeypatch):
    """cmd_calibrate кросс-проверяет сохранённый кроп против ОТОБРАЖАЕМЫХ размеров (display,
    rotation-aware) → отклоняет рассинхрон пространств и удаляет битую калибровку."""
    from autoreels.core.calibration import save_calibration
    from autoreels.core.models import Crop
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(cal, "probe_frame", lambda v, *, ffprobe="ffprobe": (2688, 1512, 480.0))
    # отображаемое (после rotation) — вертикальное 1512×2688
    monkeypatch.setattr(cal, "_probe_frame_size_for_auto", lambda v, **k: (1512, 2688))
    monkeypatch.setattr(cal, "extract_reference_frame",
                        lambda v, out, *, at_seconds, ffmpeg="ffmpeg": out)

    calib_dir = tmp_path / "calibrations"

    class _BadCropCalibrator:
        def __init__(self):
            # кроп вылезает по высоте за отображаемый кадр: y+h=224+2600=2824 > 2688
            self.saved_path = save_calibration(
                calib_dir, source_name="v.mp4", source_sha256="d" * 64,
                crop=Crop(x=96, y=224, w=1462, h=2600), frame=[1512, 2688], setup_label="v")
        def propose(self, frame_png, frame_size):
            return None

    bad = _BadCropCalibrator()
    with pytest.raises(CalibrateError) as e:
        cmd_calibrate(video, root=tmp_path, calibrator=bad)
    assert "1512×2688" in str(e.value) or "границы" in str(e.value)
    assert not bad.saved_path.exists()                  # битая калибровка удалена


# ------------------------------------------------------------ выбор кадра для калибровки

def test_parse_frame_at_percent():
    assert parse_frame_at("50%", 480.0) == 240.0
    assert parse_frame_at("25%", 480.0) == 120.0


def test_parse_frame_at_seconds():
    assert parse_frame_at("120", 480.0) == 120.0
    assert parse_frame_at("120s", 480.0) == 120.0        # суффикс 's' допустим


def test_parse_frame_at_default_is_not_first_frame():
    """Дефолт (None) — из середины (~40%), НЕ первый кадр (0с)."""
    at = parse_frame_at(None, 480.0)
    assert at > 0                                         # не первый кадр
    assert 0.3 * 480 <= at <= 0.5 * 480                  # в диапазоне 30-50%


def test_parse_frame_at_clamps_to_end():
    """Позиция за концом видео зажимается внутрь (seek не в пустоту)."""
    assert parse_frame_at("100%", 480.0) < 480.0
    assert parse_frame_at("999", 480.0) < 480.0


def test_parse_frame_at_invalid_raises():
    for bad in ("abc", "50x", "%"):
        with pytest.raises(CalibrateError):
            parse_frame_at(bad, 480.0)


def test_parse_frame_at_negative_raises():
    with pytest.raises(CalibrateError):
        parse_frame_at("-10", 480.0)


def test_extract_preview_frames_positions(tmp_path, monkeypatch):
    """Сетка извлекает кадры из опорных точек (10/25/50/75%) + главный; помечает главный."""
    seen = []
    monkeypatch.setattr(cal, "extract_reference_frame",
                        lambda v, out, *, at_seconds, ffmpeg="ffmpeg": seen.append(at_seconds) or out)
    frames = extract_preview_frames("v.mp4", tmp_path, "a" * 64, 480.0, main_at=192.0)
    ats = sorted(f["at"] for f in frames)
    assert 48.0 in ats and 120.0 in ats and 240.0 in ats and 360.0 in ats   # 10/25/50/75%
    assert 192.0 in ats                                                       # главный (40%)
    assert sum(1 for f in frames if f["is_main"]) == 1                        # ровно один главный
    assert next(f for f in frames if f["is_main"])["at"] == 192.0


def test_build_calibration_html_has_preview_grid():
    """С ≥2 превью-кадрами HTML несёт сетку (JS + base64 каждого)."""
    frames = [{"label": "10%", "b64": "AAA", "main": False},
              {"label": "40%", "b64": "BBB", "main": True}]
    html = build_calibration_html("MAIN", (3840, 2160), sha="a" * 64,
                                  source_name="v.mp4", preview_frames=frames)
    assert "renderThumbs" in html and "thumbs" in html
    assert '"10%"' in html and '"40%"' in html and "BBB" in html


def test_build_calibration_html_single_frame_empty_grid():
    """Без превью — сетка пуста (одиночный кадр как раньше)."""
    html = build_calibration_html("MAIN", (3840, 2160), sha="a" * 64, source_name="v.mp4")
    assert "const FRAMES = [];" in html
    import re
    assert re.findall(r"__[A-Z_]+__", html) == []        # все плейсхолдеры подставлены


def test_raw_selection_from_drop_builds_selection():
    drop = {"display": {"x": 685, "y": 140, "w": 478, "h": 850},
            "display_size": [1920, 1080], "frame_size": [3840, 2160]}
    sel = raw_selection_from_drop(drop, frame_size=(3840, 2160))
    assert (sel.x, sel.y, sel.w, sel.h) == (685, 140, 478, 850)
    assert sel.display_size == (1920, 1080) and sel.frame_size == (3840, 2160)


# --------------------------------------------------- POST-хендлер: finalize → save (прямо)

def test_handle_save_finalizes_and_saves(tmp_path):
    calib = tmp_path / "calibrations"
    cal_obj = ManualCalibrator(
        sha="a" * 64, source_name="v.mp4", calib_dir=calib, setup_label="tearoom_main",
    )
    cal_obj.frame_size = (3840, 2160)                       # обычно ставит propose
    body = json.dumps({
        "display": {"x": 685, "y": 140, "w": 478, "h": 850},
        "display_size": [1920, 1080], "frame_size": [3840, 2160],
    }).encode("utf-8")

    resp = cal_obj._handle_save(body)

    assert resp["ok"] is True
    # финал ядра: display×2 → реальные px + 9:16
    assert resp["crop"] == {"x": 1370, "y": 280, "w": 956, "h": 1700}
    saved = calib / ("a" * 64 + ".json")
    assert saved.exists() and cal_obj.saved_path == saved
    rec = json.loads(saved.read_text(encoding="utf-8"))
    assert rec["crop"] == {"x": 1370, "y": 280, "w": 956, "h": 1700}
    assert rec["setup_label"] == "tearoom_main"


def test_handle_save_bad_payload_raises(tmp_path):
    cal_obj = ManualCalibrator(sha="a" * 64, source_name="v.mp4", calib_dir=tmp_path)
    cal_obj.frame_size = (3840, 2160)
    with pytest.raises((KeyError, ValueError, json.JSONDecodeError)):
        cal_obj._handle_save(b"{not json")


def test_handle_save_uses_browser_frame_size_natural(tmp_path):
    """frame сохраняется в РАЗМЕРЕ ИЗ БРАУЗЕРА (натуральный кадр), не в ffprobe-кодированном —
    иначе при SAR/повороте кроп в других пикселях, чем рендер."""
    calib = tmp_path / "calibrations"
    cal_obj = ManualCalibrator(sha="a" * 64, source_name="v.mp4", calib_dir=calib)
    cal_obj.frame_size = (2688, 1512)                       # ffprobe (кодированный)
    body = json.dumps({
        "display": {"x": 100, "y": 0, "w": 300, "h": 533},
        "display_size": [1000, 562], "frame_size": [1512, 2688],   # браузер: натуральный (повёрнут)
    }).encode("utf-8")
    resp = cal_obj._handle_save(body)
    rec = json.loads((calib / ("a" * 64 + ".json")).read_text(encoding="utf-8"))
    assert rec["frame"] == [1512, 2688]                    # натуральный из браузера, не 2688×1512


def test_narrow_crop_warning_triggers_below_30pct():
    """Санити: ширина < 30% кадра → предупреждение (реальный кейс 718/2688 = 27%)."""
    from autoreels.local.calibrate import narrow_crop_warning
    from autoreels.core.models import Crop
    w = narrow_crop_warning(Crop(x=278, y=224, w=718, h=1276), [2688, 1512])
    assert w is not None and "27%" in w and "узкий" in w


def test_narrow_crop_warning_ok_for_full_height_9_16():
    """Полновысотный 9:16 из 16:9 (~31.6% ширины) — норма, без предупреждения."""
    from autoreels.local.calibrate import narrow_crop_warning
    from autoreels.core.models import Crop
    assert narrow_crop_warning(Crop(x=919, y=0, w=850, h=1512), [2688, 1512]) is None


def test_handle_save_warns_on_narrow_crop(tmp_path, capsys):
    """Узкий кроп при сохранении → предупреждение в stdout и в ответе."""
    cal_obj = ManualCalibrator(sha="a" * 64, source_name="v.mp4", calib_dir=tmp_path / "c")
    cal_obj.frame_size = (2688, 1512)
    body = json.dumps({
        "display": {"x": 100, "y": 80, "w": 258, "h": 459},   # ~26% ширины при display==frame
        "display_size": [2688, 1512], "frame_size": [2688, 1512],
    }).encode("utf-8")
    resp = cal_obj._handle_save(body)
    assert "warning" in resp and "узкий" in resp["warning"]
    assert "узкий" in capsys.readouterr().out


def test_handle_save_persists_rotation_deg(tmp_path):
    """rotation_deg из payload попадает в calibrations/<sha>.json и в ответ."""
    calib = tmp_path / "calibrations"
    cal_obj = ManualCalibrator(sha="a" * 64, source_name="v.mp4", calib_dir=calib)
    cal_obj.frame_size = (3840, 2160)
    body = json.dumps({
        "display": {"x": 685, "y": 140, "w": 478, "h": 850},
        "display_size": [1920, 1080], "frame_size": [3840, 2160],
        "rotation_deg": 2.5,
    }).encode("utf-8")

    resp = cal_obj._handle_save(body)

    assert resp["rotation_deg"] == 2.5
    rec = json.loads((calib / ("a" * 64 + ".json")).read_text(encoding="utf-8"))
    assert rec["rotation_deg"] == 2.5


def test_handle_save_no_rotation_defaults_zero(tmp_path):
    """Payload без rotation_deg → сохраняется 0 (обратная совместимость)."""
    calib = tmp_path / "calibrations"
    cal_obj = ManualCalibrator(sha="a" * 64, source_name="v.mp4", calib_dir=calib)
    cal_obj.frame_size = (3840, 2160)
    body = json.dumps({
        "display": {"x": 685, "y": 140, "w": 478, "h": 850},
        "display_size": [1920, 1080], "frame_size": [3840, 2160],
    }).encode("utf-8")
    cal_obj._handle_save(body)
    rec = json.loads((calib / ("a" * 64 + ".json")).read_text(encoding="utf-8"))
    assert rec["rotation_deg"] == 0.0


def test_handle_save_warns_when_rotation_pushes_crop_out(tmp_path):
    """Полновысотный кроп + большой угол → предупреждение о пустых углах в ответе."""
    calib = tmp_path / "calibrations"
    cal_obj = ManualCalibrator(sha="a" * 64, source_name="v.mp4", calib_dir=calib)
    cal_obj.frame_size = (3840, 2160)
    body = json.dumps({
        "display": {"x": 1312, "y": 0, "w": 1215, "h": 2160},   # во всю высоту
        "display_size": [3840, 2160], "frame_size": [3840, 2160],
        "rotation_deg": 8.0,
    }).encode("utf-8")
    resp = cal_obj._handle_save(body)
    assert "warning" in resp and "угол" in resp["warning"].lower()


def test_html_scales_by_natural_size_not_ffprobe():
    """JS считает масштаб по img.naturalWidth (истинный размер PNG), не по ffprobe-FW,
    и шлёт натуральный размер как frame_size — фикс SAR/поворота."""
    html = build_calibration_html("B64", (2688, 1512), sha="a" * 64, source_name="v.mp4")
    assert "img.naturalWidth" in html and "s=DW/NW" in html
    assert "frame_size:[NW,NH]" in html


# ----------------------------------------------- реальный сервер: GET html + POST /save

def test_server_serves_html_and_post_save_saves_then_stops(tmp_path):
    calib = tmp_path / "calibrations"
    frame_png = tmp_path / "f.png"
    frame_png.write_bytes(b"\x89PNG fake")
    cal_obj = ManualCalibrator(
        sha="b" * 64, source_name="v.mp4", calib_dir=calib, setup_label="lbl",
        host="127.0.0.1", port=0, timeout_sec=5, open_browser=False,
    )

    result = {}
    th = threading.Thread(target=lambda: result.update(sel=cal_obj.propose(frame_png, (3840, 2160))))
    th.start()
    try:
        base = _wait_for_server(cal_obj)
        # GET / отдаёт HTML с кадром
        html = httpx.get(base + "/", timeout=5).text
        assert "data:image/png;base64," in html
        # POST /save → 200 OK + сохранение
        r = httpx.post(base + "/save", json={
            "display": {"x": 685, "y": 140, "w": 478, "h": 850},
            "display_size": [1920, 1080], "frame_size": [3840, 2160],
        }, timeout=5)
        assert r.status_code == 200 and r.json()["ok"] is True
    finally:
        th.join(timeout=5)

    assert result["sel"].frame_size == (3840, 2160)         # propose вернул рамку
    assert (calib / ("b" * 64 + ".json")).exists()          # сохранено
    # сервер погашен — порт больше не отвечает
    with pytest.raises(httpx.HTTPError):
        httpx.get(base + "/", timeout=1)


def test_manual_calibrator_times_out_without_save(tmp_path):
    frame_png = tmp_path / "f.png"
    frame_png.write_bytes(b"png")
    cal_obj = ManualCalibrator(
        sha="c" * 64, source_name="v.mp4", calib_dir=tmp_path / "calibrations",
        host="127.0.0.1", port=0, timeout_sec=0.2, open_browser=False,
    )
    with pytest.raises(CalibrateError):
        cal_obj.propose(frame_png, (3840, 2160))


# ----------------------------------------------------------------- HTML (стаб, POST/save)

def test_build_calibration_html_embeds_frame_and_posts_to_save():
    html = build_calibration_html("BASE64DATA", (3840, 2160), sha="a" * 64, source_name="v.mp4")
    assert "BASE64DATA" in html and "data:image/png;base64," in html
    assert "3840" in html and "2160" in html
    assert "/save" in html                                   # UI шлёт fetch POST, не download


# ----------------------------------------------------------------- cmd_calibrate (оркестр)

class _FakeCalibrator:
    """Возвращает заданную рамку (без сервера). saved_path нет → сохраняет cmd_calibrate."""

    def __init__(self, sel):
        self._sel = sel
        self.frame_seen = None

    def propose(self, frame_png, frame_size):
        self.frame_seen = (frame_png, frame_size)
        return self._sel


def test_cmd_calibrate_saves_finalized_calibration(tmp_path, monkeypatch):
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"some-video-bytes")
    monkeypatch.setattr(cal, "probe_frame", lambda v, *, ffprobe="ffprobe": (3840, 2160, 480.0))
    monkeypatch.setattr(cal, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))
    monkeypatch.setattr(cal, "extract_reference_frame",
                        lambda v, out, *, at_seconds, ffmpeg="ffmpeg": out)
    sel = RawSelection(x=685, y=140, w=478, h=850, display_size=(1920, 1080), frame_size=(3840, 2160))
    fake = _FakeCalibrator(sel)

    path = cmd_calibrate(video, setup_label="tearoom_main", root=tmp_path, calibrator=fake)

    from autoreels.core import state
    from autoreels.core.calibration import load_calibration
    # Ключ = partial-p1 (тот же, что использует run/load_or_auto_calibrate), НЕ полный sha256.
    key = state.file_sha256_cached_fast(video, tmp_path / "data" / "cache")
    setup = load_calibration(tmp_path / "calibrations", key)
    assert setup.setup_id == "tearoom_main"
    assert setup.crop.model_dump() == {"x": 1370, "y": 280, "w": 956, "h": 1700}
    assert path.exists()


def test_calibrate_key_matches_run_lookup_not_autocrop(tmp_path, monkeypatch):
    """Регресс: ручная калибровка находится по ключу run (partial-p1) — не падает в автокроп.

    Раньше cmd_calibrate сохранял под полным sha256, а run искал по partial-p1 → кроп
    не находился и молча применялся автокроп, несмотря на ручную настройку."""
    from autoreels.core import state
    from autoreels.core.calibration import load_or_auto_calibrate

    video = tmp_path / "PXL_test.mp4"
    video.write_bytes(b"video-content-bytes" * 500)
    monkeypatch.setattr(cal, "probe_frame", lambda v, *, ffprobe="ffprobe": (3840, 2160, 480.0))
    monkeypatch.setattr(cal, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))
    monkeypatch.setattr(cal, "extract_reference_frame",
                        lambda v, out, *, at_seconds, ffmpeg="ffmpeg": out)
    sel = RawSelection(x=685, y=140, w=478, h=850, display_size=(1920, 1080), frame_size=(3840, 2160))
    cmd_calibrate(video, setup_label="main", root=tmp_path, calibrator=_FakeCalibrator(sel))

    run_sha = state.file_sha256_cached_fast(video, tmp_path / "data" / "cache")
    auto = {"n": 0}
    setup = load_or_auto_calibrate(
        tmp_path / "calibrations", run_sha, video.name,
        get_frame_size=lambda: (auto.__setitem__("n", auto["n"] + 1) or (3840, 2160)),
    )
    assert auto["n"] == 0                     # автокроп НЕ вызывался — нашлась ручная
    assert setup.setup_id == "main"


# --------------------------------------------------------------------------- helpers

# --------------------------------------------------- webbrowser: URL в stdout всегда

def _post_save(base: str):
    return httpx.post(base + "/save", json={
        "display": {"x": 685, "y": 140, "w": 478, "h": 850},
        "display_size": [1920, 1080], "frame_size": [3840, 2160],
    }, timeout=5)


def test_propose_prints_url_prominently_even_when_webbrowser_raises(tmp_path, capsys, monkeypatch):
    """URL должен появиться в stdout с маркером >>> — даже если webbrowser.open() падает."""
    import autoreels.local.calibrate as _cal_mod

    frame_png = tmp_path / "f.png"
    frame_png.write_bytes(b"\x89PNG fake")
    cal_obj = ManualCalibrator(
        sha="d" * 64, source_name="v.mp4", calib_dir=tmp_path / "calibrations",
        host="127.0.0.1", port=0, timeout_sec=5, open_browser=True,
    )
    monkeypatch.setattr(_cal_mod.webbrowser, "open", lambda url: (_ for _ in ()).throw(OSError("no browser")))

    result = {}
    th = threading.Thread(target=lambda: result.update(sel=cal_obj.propose(frame_png, (3840, 2160))))
    th.start()
    try:
        base = _wait_for_server(cal_obj)
        _post_save(base)
    finally:
        th.join(timeout=5)

    out = capsys.readouterr().out
    assert ">>>" in out, "URL-маркер >>> не найден в stdout"
    assert "http://127.0.0.1" in out


def test_propose_url_contains_real_port(tmp_path, capsys):
    """URL в stdout должен содержать РЕАЛЬНЫЙ порт (не хардкод 8765)."""
    frame_png = tmp_path / "f.png"
    frame_png.write_bytes(b"\x89PNG fake")
    cal_obj = ManualCalibrator(
        sha="f" * 64, source_name="v.mp4", calib_dir=tmp_path / "calibrations",
        host="127.0.0.1", port=0,          # port=0 → ОС выдаст случайный порт, точно не 8765
        timeout_sec=5, open_browser=False,
    )

    result = {}
    th = threading.Thread(target=lambda: result.update(sel=cal_obj.propose(frame_png, (3840, 2160))))
    th.start()
    try:
        base = _wait_for_server(cal_obj)
        real_port = cal_obj.port
        _post_save(base)
    finally:
        th.join(timeout=5)

    out = capsys.readouterr().out
    assert str(real_port) in out, f"реальный порт {real_port} не найден в stdout: {out!r}"


def test_propose_prints_url_without_browser_open(tmp_path, capsys):
    """URL напечатан явно при open_browser=False — не зависит от webbrowser."""
    frame_png = tmp_path / "f.png"
    frame_png.write_bytes(b"\x89PNG fake")
    cal_obj = ManualCalibrator(
        sha="e" * 64, source_name="v.mp4", calib_dir=tmp_path / "calibrations",
        host="127.0.0.1", port=0, timeout_sec=5, open_browser=False,
    )

    result = {}
    th = threading.Thread(target=lambda: result.update(sel=cal_obj.propose(frame_png, (3840, 2160))))
    th.start()
    try:
        base = _wait_for_server(cal_obj)
        _post_save(base)
    finally:
        th.join(timeout=5)

    out = capsys.readouterr().out
    assert "http://127.0.0.1" in out


def _wait_for_server(cal_obj, timeout=5.0) -> str:
    """Дождаться, пока propose поднимет сервер, вернуть базовый URL."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cal_obj.port:
            base = f"http://{cal_obj.host}:{cal_obj.port}"
            try:
                httpx.get(base + "/", timeout=1)
                return base
            except httpx.HTTPError:
                pass
        time.sleep(0.02)
    raise AssertionError("сервер калибровки не поднялся")
