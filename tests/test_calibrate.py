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
    monkeypatch.setattr(cal, "extract_reference_frame",
                        lambda v, out, *, at_seconds, ffmpeg="ffmpeg": out)
    sel = RawSelection(x=685, y=140, w=478, h=850, display_size=(1920, 1080), frame_size=(3840, 2160))
    fake = _FakeCalibrator(sel)

    path = cmd_calibrate(video, setup_label="tearoom_main", root=tmp_path, calibrator=fake)

    from autoreels.core import state
    from autoreels.core.calibration import load_calibration
    setup = load_calibration(tmp_path / "calibrations", state.file_sha256(video))
    assert setup.setup_id == "tearoom_main"
    assert setup.crop.model_dump() == {"x": 1370, "y": 280, "w": 956, "h": 1700}
    assert path.exists()


# --------------------------------------------------------------------------- helpers

# --------------------------------------------------- webbrowser: URL в stdout всегда

def test_propose_prints_url_even_when_webbrowser_raises(tmp_path, capsys, monkeypatch):
    """URL должен появиться в stdout НЕЗАВИСИМО от webbrowser.open() — даже если тот падает."""
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
        httpx.post(base + "/save", json={
            "display": {"x": 685, "y": 140, "w": 478, "h": 850},
            "display_size": [1920, 1080], "frame_size": [3840, 2160],
        }, timeout=5)
    finally:
        th.join(timeout=5)

    captured = capsys.readouterr()
    assert "127.0.0.1" in captured.out


def test_propose_prints_url_before_webbrowser_call(tmp_path, capsys, monkeypatch):
    """URL должен быть напечатан явно — не только через webbrowser.open()."""
    import autoreels.local.calibrate as _cal_mod

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
        httpx.post(base + "/save", json={
            "display": {"x": 685, "y": 140, "w": 478, "h": 850},
            "display_size": [1920, 1080], "frame_size": [3840, 2160],
        }, timeout=5)
    finally:
        th.join(timeout=5)

    captured = capsys.readouterr()
    assert "http://127.0.0.1" in captured.out


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
