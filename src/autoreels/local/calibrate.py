"""Команда `autoreels calibrate <video>` — ручная визуальная калибровка кропа (local-тир).

Транспорт — ЭФЕМЕРНЫЙ localhost-сервер (stdlib http.server, без Flask):
1. probe размера/длительности → извлечь опорный кадр середины (ffmpeg -ss);
2. поднять сервер на 127.0.0.1:<port> → открыть его в браузере;
3. GET / отдаёт HTML (кадр base64-фоном, 9:16-рамка); человек тянет рамку, жмёт Save;
4. браузер шлёт fetch POST /save {display, display_size, frame_size} → сервер
   finalize_selection → save_calibration → ответ OK → сервер гасится.

Сервер живёт ОДНУ калибровку, не висит фоном; таймаут (10 мин) и Ctrl-C гасят корректно.
Determinism-first: браузер ПРЕДЛАГАЕТ display-рамку; реальные px + точный 9:16 + границы
считает ядро (core.calibration). Интерфейс `propose(frame)→RawSelection` сохранён —
авто-детект потом встанет за него, не трогая `run`/`cmd_calibrate`.

Ядро (finalize_selection/save_calibration/геометрия) НЕ меняется — только транспорт. Был
download+watch (drop-файл в Downloads); заменён на localhost-сервер, как и решили.

NB: HTML ниже — СТАБ (кадр + fetch POST на /save). Полноценный интерактив 9:16-рамки +
двусторонние поля в реальных px — отдельный шаг frontend-design.
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from autoreels.core import state
from autoreels.core.calibration import RawSelection, finalize_selection, save_calibration


class CalibrateError(Exception):
    """Калибровка не удалась (нет ffmpeg/кадра, не подняли сервер, нет Save в срок)."""


# ----------------------------------------------------- probe + извлечение опорного кадра

def build_probe_cmd(ffprobe: str, video) -> list[str]:
    return [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video),
    ]


def parse_probe(output: str) -> tuple[int, int, float]:
    """ffprobe nokey-вывод (width, height, duration) → числа."""
    vals = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if len(vals) < 3:
        raise CalibrateError(f"не удалось разобрать ffprobe: {output!r}")
    return int(vals[0]), int(vals[1]), float(vals[2])


def build_frame_cmd(ffmpeg: str, video, out_png, at_seconds: float) -> list[str]:
    return [
        ffmpeg, "-y", "-loglevel", "error",
        "-ss", f"{at_seconds:.3f}",
        "-i", str(video),
        "-frames:v", "1",
        str(out_png),
    ]


def probe_frame(video, *, ffprobe: str = "ffprobe") -> tuple[int, int, float]:
    binary = shutil.which(ffprobe)
    if binary is None:
        raise CalibrateError(f"ffprobe не найден (искали '{ffprobe}')")
    proc = subprocess.run(build_probe_cmd(binary, video), capture_output=True, text=True)
    if proc.returncode != 0:
        raise CalibrateError(f"ffprobe не смог прочитать {video}: {proc.stderr.strip()}")
    return parse_probe(proc.stdout)


def extract_reference_frame(video, out_png, *, at_seconds: float, ffmpeg: str = "ffmpeg") -> Path:
    binary = shutil.which(ffmpeg)
    if binary is None:
        raise CalibrateError(f"ffmpeg не найден (искали '{ffmpeg}')")
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        build_frame_cmd(binary, video, out_png, at_seconds), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise CalibrateError(f"ffmpeg не извлёк кадр из {video}: {proc.stderr.strip()}")
    return out_png


# ----------------------------------------------------- payload браузера → RawSelection

def raw_selection_from_drop(drop: dict, frame_size: tuple[int, int]) -> RawSelection:
    """POST-тело из браузера → RawSelection (display-рамка + размеры показа/кадра)."""
    d = drop["display"]
    ds = drop.get("display_size")
    fs = drop.get("frame_size") or frame_size
    return RawSelection(
        x=d["x"], y=d["y"], w=d["w"], h=d["h"],
        display_size=tuple(ds), frame_size=tuple(fs),
    )


# --------------------------------------------------------------- HTML-страница (СТАБ)

def build_calibration_html(frame_b64: str, frame_size: tuple[int, int], *, sha: str,
                           source_name: str) -> str:
    """СТАБ страницы: кадр + fetch POST на /save. Интерактив 9:16 — шаг frontend-design.

    Реальный UI: фон-кадр, перетаскиваемая/ресайзимая 9:16-рамка, двусторонние поля x/y/w/h
    в реальных px, кнопка Save → fetch('/save', {display, display_size, frame_size}).
    """
    fw, fh = frame_size
    return (
        "<!doctype html><html lang=ru><head><meta charset=utf-8>"
        f"<title>calibrate {source_name}</title></head><body "
        f'data-sha="{sha}" data-frame-w="{fw}" data-frame-h="{fh}">'
        f"<h1>Калибровка кропа: {source_name}</h1>"
        f"<p>Кадр {fw}×{fh}. UI 9:16-рамки — TODO (frontend-design). Сохранение: POST /save.</p>"
        f'<img alt="reference frame" style="max-width:100%" src="data:image/png;base64,{frame_b64}">'
        "</body></html>"
    )


# ------------------------------------------------------- HTTP-хендлер (один на калибровку)

def _make_handler(html_bytes: bytes, on_save, done: threading.Event):
    class _Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, ctype: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", html_bytes)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/save":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                resp = on_save(body)
            except Exception as e:  # битый payload / невалидная рамка → 400, сервер живёт
                msg = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8")
                self._send(400, "application/json; charset=utf-8", msg)
                return
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(resp, ensure_ascii=False).encode("utf-8"))
            done.set()                              # успешный Save → гасим сервер

        def log_message(self, *args):               # тихо (не сорить в stdout)
            pass

    return _Handler


def _bind_server(host: str, port: int, handler) -> HTTPServer:
    """Поднять сервер: пробуем port..port+9, иначе любой свободный (0)."""
    ports = [port + i for i in range(10)] + [0] if port else [0]
    last = None
    for p in ports:
        try:
            return HTTPServer((host, p), handler)
        except OSError as e:
            last = e
    raise CalibrateError(f"не удалось поднять сервер калибровки: {last}")


# ----------------------------------------------------- ручной калибратор (localhost-сервер)

@dataclass
class ManualCalibrator:
    """Ручной калибратор: поднимает localhost-сервер, ждёт POST /save → RawSelection.

    POST-хендлер сам финализирует и сохраняет (save до ответа OK), `saved_path` фиксирует
    путь — cmd_calibrate его и возвращает, не пересохраняя.
    """

    sha: str
    source_name: str
    calib_dir: Path
    setup_label: str | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    timeout_sec: float = 600.0
    open_browser: bool = True
    frame_size: tuple[int, int] = (0, 0)
    saved_path: Path | None = field(default=None)
    _sel: RawSelection | None = field(default=None)

    def _handle_save(self, body: bytes) -> dict:
        """POST /save: payload → finalize_selection → save_calibration. Возвращает ответ OK."""
        payload = json.loads(body)
        sel = raw_selection_from_drop(payload, self.frame_size)
        crop = finalize_selection(sel)              # реальные px + точный 9:16 + границы (ядро)
        self.saved_path = save_calibration(
            self.calib_dir, source_name=self.source_name, source_sha256=self.sha,
            crop=crop, frame=list(self.frame_size), setup_label=self.setup_label,
        )
        self._sel = sel
        return {"ok": True, "crop": crop.model_dump(), "saved": str(self.saved_path)}

    def propose(self, frame_png, frame_size: tuple[int, int]) -> RawSelection:
        self.frame_size = tuple(frame_size)
        b64 = base64.b64encode(Path(frame_png).read_bytes()).decode("ascii")
        html = build_calibration_html(
            b64, self.frame_size, sha=self.sha, source_name=self.source_name
        ).encode("utf-8")

        done = threading.Event()
        server = _bind_server(self.host, self.port, _make_handler(html, self._handle_save, done))
        self.port = server.server_address[1]
        url = f"http://{self.host}:{self.port}/"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            if self.open_browser:
                webbrowser.open(url)
            print(f"калибровка открыта: {url}  (Save в браузере сохранит кроп; Ctrl-C — отмена)",
                  flush=True)
            if not done.wait(self.timeout_sec):
                raise CalibrateError(
                    f"калибровка не завершена за {self.timeout_sec:.0f}с (не было Save)"
                )
            return self._sel
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


# ------------------------------------------------------------------- команда

def cmd_calibrate(
    video,
    *,
    setup_label: str | None = None,
    root=".",
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    host: str = "127.0.0.1",
    port: int = 8765,
    calibrator=None,
    timeout_sec: float = 600.0,
) -> Path:
    """Откалибровать кроп для `video` → calibrations/<sha>.json. Отдельно ПЕРЕД run."""
    root = Path(root)
    video = Path(video)
    if not video.is_file():
        raise CalibrateError(f"видео не найдено: {video}")

    w, h, duration = probe_frame(video, ffprobe=ffprobe)
    sha = state.file_sha256(video)
    calib_dir = root / "calibrations"
    work = calib_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)
    frame_png = work / f"{sha}.png"

    print("извлекаю опорный кадр (середина видео)…", flush=True)
    extract_reference_frame(video, frame_png, at_seconds=duration / 2, ffmpeg=ffmpeg)

    if calibrator is None:
        calibrator = ManualCalibrator(
            sha=sha, source_name=video.name, calib_dir=calib_dir, setup_label=setup_label,
            host=host, port=port, timeout_sec=timeout_sec,
        )

    sel = calibrator.propose(frame_png, (w, h))
    # POST-хендлер ManualCalibrator уже сохранил (saved_path); иначе (напр. авто-детект,
    # возвращающий только рамку) — сохраняем здесь. Единый финал через ядро.
    path = getattr(calibrator, "saved_path", None)
    if path is None:
        crop = finalize_selection(sel)
        path = save_calibration(
            calib_dir, source_name=video.name, source_sha256=sha,
            crop=crop, frame=[w, h], setup_label=setup_label,
        )
    print(f"калибровка сохранена: {path}", flush=True)
    return path
