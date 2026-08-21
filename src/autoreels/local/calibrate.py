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

UI (_HTML_TEMPLATE) — страница-видоискатель: кадр-фон, 9:16-рамка (constrained при
drag/resize), поля x/y/w/h в РЕАЛЬНЫХ px исходника (двусторонние), Save → fetch POST /save.
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
from autoreels.core.calibration import (
    CalibrationError,
    RawSelection,
    _probe_frame_size_for_auto,
    crop_orientation_warnings,
    finalize_selection,
    frame_orientation,
    rotation_safety_warning,
    save_calibration,
    validate_crop_in_frame,
)
from autoreels.core.models import Crop


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
    # autorotate (ПО УМОЛЧАНИЮ, без -noautorotate): PNG выходит в ОТОБРАЖАЕМОЙ ориентации —
    # ровно как человек видит видео и как рендерит crop-фильтр (тоже autorotate). Единое
    # пространство координат калибратора и рендера. Кадр НЕ поворачиваем сами.
    return [
        ffmpeg, "-y", "-loglevel", "error",
        "-ss", f"{at_seconds:.3f}",
        "-i", str(video),
        "-frames:v", "1",
        str(out_png),
    ]


# Дефолт: НЕ первый кадр (штатив ещё правят, человек садится) — из 40% длительности,
# где кадр уже установился. Хороший дефолт без действий пользователя.
_DEFAULT_FRAME_FRACTION = 0.4
# Позиции превью-сетки (доли длительности) — пользователь видит варианты и кликает.
_PREVIEW_FRACTIONS = (0.1, 0.25, 0.5, 0.75)


def parse_frame_at(spec, duration: float) -> float:
    """Разобрать `--frame-at` в секунды: '50%'→50% длительности; '120'/'120s'→секунда.

    None → дефолт (_DEFAULT_FRAME_FRACTION середины, не первый кадр). Результат зажимается
    в [0, duration). Мусор/отрицательное → CalibrateError."""
    if spec is None:
        return duration * _DEFAULT_FRAME_FRACTION
    s = str(spec).strip().lower()
    try:
        if s.endswith("%"):
            frac = float(s[:-1]) / 100.0
            at = duration * frac
        else:
            at = float(s[:-1] if s.endswith("s") else s)
    except ValueError as e:
        raise CalibrateError(
            f"неверный --frame-at {spec!r}: ожидается '50%' или секунда ('120' / '120s')"
        ) from e
    if at < 0:
        raise CalibrateError(f"--frame-at не может быть отрицательным: {spec!r}")
    # Не выходить за конец видео (seek за пределы даёт пустой/последний кадр).
    return min(at, max(0.0, duration - 0.05))


def probe_frame(video, *, ffprobe: str = "ffprobe") -> tuple[int, int, float]:
    binary = shutil.which(ffprobe)
    if binary is None:
        raise CalibrateError(f"ffprobe не найден (искали '{ffprobe}')")
    proc = subprocess.run(build_probe_cmd(binary, video), capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise CalibrateError(f"ffprobe не смог прочитать {video}: {proc.stderr.strip()}")
    return parse_probe(proc.stdout)


# --------------------------------------------------------------- валидация входного файла

class InputInvalid(Exception):
    """Входной файл битый/пустой/не видео — обрабатывать нельзя. Это SKIPPED, не FAILED:
    пользователь чинит файл, конвейер не тратит на него хэш/калибровку/аудио."""


# Порог «пустой/недокачан»: реальное talking-head видео на минуты — это десятки-сотни МБ.
# Меньше 1 МБ — почти наверняка обрезок/пустышка/недокачка (0 байт — тем более).
_MIN_INPUT_BYTES = 1 << 20


def _humanize_ffprobe_error(stderr: str) -> str:
    """Типичные ошибки ffprobe → человеческое объяснение (что случилось и что делать)."""
    s = (stderr or "").lower()
    if "moov atom not found" in s:
        return ("файл недокачан или обрезан при копировании — перекачай/пересними "
                "(moov atom not found)")
    if "invalid data found" in s:
        return "не видеофайл или повреждён (Invalid data found)"
    if "end of file" in s or "truncat" in s:
        return "файл обрезан/недокачан (unexpected end of file)"
    tail = stderr.strip() or "(без вывода)"
    return f"ffprobe не смог прочитать файл: {tail}"


def validate_input(video, *, ffprobe: str = "ffprobe",
                   min_bytes: int = _MIN_INPUT_BYTES) -> tuple[int, int, float]:
    """Быстрая проверка входного файла ПЕРВЫМ шагом — ДО хэша/калибровки/аудио.

    Ловит битые/пустые/недокачанные файлы сразу: размер ≥ `min_bytes`; ffprobe читает файл; есть
    видеопоток с ненулевыми размером кадра и длительностью. Ничего тяжёлого не считает (никакого
    sha по гигабайтам). Возвращает (w, h, duration) при успехе; иначе `InputInvalid` с понятной
    причиной (типичные ошибки ffprobe распознаются и объясняются)."""
    video = Path(video)
    if not video.is_file():
        raise InputInvalid(f"файл не найден: {video}")
    size = video.stat().st_size
    if size < min_bytes:
        what = "файл пустой (0 байт)" if size == 0 else f"файл слишком мал ({size} Б < {min_bytes} Б)"
        raise InputInvalid(f"{what} — вероятно недокачан или обрезан при копировании")
    binary = shutil.which(ffprobe)
    if binary is None:
        raise InputInvalid(f"ffprobe не найден (искали '{ffprobe}') — не могу проверить файл")
    proc = subprocess.run(build_probe_cmd(binary, video), capture_output=True, text=True,
                          encoding="utf-8")
    if proc.returncode != 0:
        raise InputInvalid(_humanize_ffprobe_error(proc.stderr))
    try:
        w, h, duration = parse_probe(proc.stdout)
    except CalibrateError as e:
        raise InputInvalid("нет видеопотока или файл повреждён — не определяются "
                           "размер кадра и длительность") from e
    if w <= 0 or h <= 0 or duration <= 0:
        raise InputInvalid(f"невалидные параметры видео: кадр {w}×{h}, длительность {duration}с")
    return w, h, duration


def extract_reference_frame(video, out_png, *, at_seconds: float, ffmpeg: str = "ffmpeg") -> Path:
    binary = shutil.which(ffmpeg)
    if binary is None:
        raise CalibrateError(f"ffmpeg не найден (искали '{ffmpeg}')")
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        build_frame_cmd(binary, video, out_png, at_seconds), capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        raise CalibrateError(f"ffmpeg не извлёк кадр из {video}: {proc.stderr.strip()}")
    return out_png


def extract_preview_frames(video, work_dir, sha: str, duration: float, *, main_at: float,
                           ffmpeg: str = "ffmpeg") -> list[dict]:
    """Извлечь кадры для превью-сетки: главный (main_at) + опорные точки (10/25/50/75%).

    Возвращает список {label, path, at, is_main}, отсортированный по времени. Best-effort:
    неудавшийся кадр пропускается (сетка не роняет калибровку). Первый успешный — фолбэк-главный,
    если main_at не извлёкся. ffmpeg -ss — быстрый seek без полного декодирования."""
    work_dir = Path(work_dir)
    positions = {round(duration * f, 3) for f in _PREVIEW_FRACTIONS if 0 <= duration * f < duration}
    positions.add(round(main_at, 3))
    frames: list[dict] = []
    for at in sorted(positions):
        pct = int(round(at / duration * 100)) if duration > 0 else 0
        png = work_dir / f"{sha}_{pct:02d}.png"
        try:
            extract_reference_frame(video, png, at_seconds=at, ffmpeg=ffmpeg)
        except CalibrateError:
            continue
        frames.append({"label": f"{pct}%", "path": png, "at": at,
                       "is_main": abs(at - main_at) < 1e-3})
    if frames and not any(f["is_main"] for f in frames):
        frames[0]["is_main"] = True   # главный не извлёкся → показываем первый успешный
    return frames


# ----------------------------------------------------- payload браузера → RawSelection

_NARROW_CROP_FRACTION = 0.30   # ширина < 30% кадра — подозрительно узко (возможно масштаб не тот)


def narrow_crop_warning(crop, frame) -> str | None:
    """Санити-проверка: кроп подозрительно узкий (ширина < 30% кадра) → текст предупреждения.

    Полновысотный 9:16 из 16:9-кадра ≈ 31.6% ширины — норма. Уже → вероятно координаты не в
    масштабе оригинала (превью-пиксели без пересчёта). None если кроп нормальный."""
    fw = frame[0] if frame else 0
    w = getattr(crop, "w", None)
    if fw and w is not None and w < _NARROW_CROP_FRACTION * fw:
        return (f"очень узкий кроп: ширина {w}px = {w / fw * 100:.0f}% кадра ({fw}px) — "
                f"проверь рамку (возможно координаты не в масштабе оригинала)")
    return None


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

def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_calibration_html(frame_b64: str, frame_size: tuple[int, int], *, sha: str,
                           source_name: str, preview_frames: list | None = None) -> str:
    """Страница-видоискатель: кадр-фон + 9:16-рамка (constrained при drag/resize), поля
    x/y/w/h в РЕАЛЬНЫХ px исходника (двусторонние), Save → fetch POST /save.

    Кадр показывается уменьшенным; пересчёт показ↔реальные консистентен с to_real_pixels
    (s = display_w / frame_w; real = display / s). На сервер уходит display-рамка +
    display_size + frame_size — финал (9:16, реальные px, границы) считает ядро.

    `preview_frames` (≥2) → превью-сетка: клик по кадру меняет фон (кроп-координаты
    frame-независимы). Пусто/один → одиночный кадр как раньше.
    """
    fw, fh = frame_size
    orient = frame_orientation(fw, fh)
    orient_hint = {
        "vertical": f"Видео вертикальное {fw}×{fh} — кроп приближает кадр (рамка внутри вертикали).",
        "horizontal": f"Видео горизонтальное {fw}×{fh} — кроп вырезает вертикальную полосу 9:16.",
        "square": f"Видео квадратное {fw}×{fh} — кроп вырезает вертикальную полосу 9:16.",
    }[orient]
    config = json.dumps({"fw": fw, "fh": fh, "sha": sha, "source": source_name})
    frames_json = json.dumps(preview_frames if preview_frames and len(preview_frames) >= 2 else [])
    return (
        _HTML_TEMPLATE
        .replace("__CONFIG__", config)
        .replace("__FRAMES_JSON__", frames_json)
        .replace("__FRAME_B64__", frame_b64)
        .replace("__SOURCE__", _html_escape(source_name))
        .replace("__ORIENT_HINT__", _html_escape(orient_hint))
        .replace("__FW__", str(fw))
        .replace("__FH__", str(fh))
        .replace("__SHA12__", _html_escape(sha[:12]))
    )


# ------------------------------------------------------- HTTP-хендлер (один на калибровку)

def _make_handler(html_bytes: bytes, on_save, done: threading.Event):
    class _Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, ctype: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()                      # ответ полностью ушёл до гашения сервера

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
    preview_frames: list | None = None   # [{label, path, is_main}] для превью-сетки в браузере
    saved_path: Path | None = field(default=None)
    _sel: RawSelection | None = field(default=None)

    def _handle_save(self, body: bytes) -> dict:
        """POST /save: payload → finalize_selection → save_calibration. Возвращает ответ OK."""
        payload = json.loads(body)
        sel = raw_selection_from_drop(payload, self.frame_size)
        crop = finalize_selection(sel)              # реальные px + точный 9:16 + границы (ядро)
        rotation_deg = float(payload.get("rotation_deg", 0.0) or 0.0)
        palette = payload.get("palette") or None    # выбранная в калибраторе палитра (или дефолт)
        if palette == "neutral":
            palette = None                          # neutral = «палитра по умолчанию», не пишем
        # frame = размер, в котором браузер считал координаты (натуральный размер кадра из PNG),
        # чтобы кроп и кадр были в ОДНОМ пространстве (важно при SAR/повороте телефона).
        frame = list(sel.frame_size) if sel.frame_size and sel.frame_size[0] else list(self.frame_size)
        self.saved_path = save_calibration(
            self.calib_dir, source_name=self.source_name, source_sha256=self.sha,
            crop=crop, frame=frame, setup_label=self.setup_label, rotation_deg=rotation_deg,
            palette=palette,
        )
        self._sel = sel
        resp = {"ok": True, "crop": crop.model_dump(), "saved": str(self.saved_path),
                "rotation_deg": rotation_deg, "palette": palette}
        warn = narrow_crop_warning(crop, frame)
        # Валидация выравнивания: кроп при этом угле должен помещаться в заполненную область.
        rot_warn = rotation_safety_warning(crop, frame[0], frame[1], rotation_deg) if frame and frame[0] else None
        combined = "; ".join(w for w in (warn, rot_warn) if w)
        if warn:
            print(f"  ⚠ {warn}", flush=True)
        if rot_warn:
            print(f"  ⚠ {rot_warn}", flush=True)
        if combined:
            resp["warning"] = combined
        return resp

    def propose(self, frame_png, frame_size: tuple[int, int]) -> RawSelection:
        self.frame_size = tuple(frame_size)
        b64 = base64.b64encode(Path(frame_png).read_bytes()).decode("ascii")
        # Превью-сетка: base64 каждого кадра для клика-выбора (крон-координаты не зависят
        # от того, какой кадр показан — все одного разрешения; сетка лишь помогает увидеть,
        # где кадр установился). Только с ≥2 кадрами — иначе одиночный кадр как раньше.
        preview = []
        for fr in (self.preview_frames or []):
            try:
                fb64 = base64.b64encode(Path(fr["path"]).read_bytes()).decode("ascii")
            except OSError:
                continue
            preview.append({"label": fr.get("label", ""), "b64": fb64,
                            "main": bool(fr.get("is_main"))})
        html = build_calibration_html(
            b64, self.frame_size, sha=self.sha, source_name=self.source_name,
            preview_frames=preview,
        ).encode("utf-8")

        done = threading.Event()
        server = _bind_server(self.host, self.port, _make_handler(html, self._handle_save, done))
        self.port = server.server_address[1]
        url = f"http://{self.host}:{self.port}/"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # Печатаем URL СРАЗУ после старта треда, до ожидания POST.
        # Формат заметный: >>> на отдельной строке + flush — Windows буферизует stdout.
        print(f"\n>>> Открой в браузере: {url}\n", flush=True)
        try:
            if self.open_browser:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass          # Git Bash / headless — браузер не открылся, URL уже напечатан
            print("(Save в браузере сохранит кроп; Ctrl-C — отмена)", flush=True)
            if not done.wait(self.timeout_sec):
                raise CalibrateError(
                    f"калибровка не завершена за {self.timeout_sec:.0f}с (не было Save)"
                )
            # Гасим сервер ТОЛЬКО после паузы — чтобы 200 успел долететь до браузера и
            # fetch разрешился в ok (а не свалился в catch с попыткой повтора).
            time.sleep(0.4)
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
    cache_dir=None,
    frame_at=None,
) -> Path:
    """Откалибровать кроп для `video` → calibrations/<sha>.json. Отдельно ПЕРЕД run.

    Кадр для калибровки: по умолчанию из середины (~40%), НЕ первый (первый часто нерелевантен —
    штатив правят, человек садится). `frame_at` ('50%' / '120' сек) задаёт конкретную позицию.
    В браузере — превью-сетка кадров (10/25/50/75%), можно кликнуть репрезентативный."""
    root = Path(root)
    video = Path(video)
    if not video.is_file():
        raise CalibrateError(f"видео не найдено: {video}")

    w, h, duration = probe_frame(video, ffprobe=ffprobe)
    # Отображаемые (после rotation-метаданных) размеры — единое пространство калибратора и
    # рендера. Кадр извлекается с autorotate, поэтому калибруем и валидируем именно в них.
    dw, dh = _probe_frame_size_for_auto(video, ffprobe=ffprobe)
    orient = frame_orientation(dw, dh)
    _hint = {"vertical": f"видео вертикальное {dw}×{dh} — кроп приближает кадр",
             "horizontal": f"видео горизонтальное {dw}×{dh} — кроп вырезает вертикальную полосу",
             "square": f"видео квадратное {dw}×{dh} — кроп вырезает вертикальную полосу"}[orient]
    print(_hint, flush=True)
    main_at = parse_frame_at(frame_at, duration)

    _cache_dir = Path(cache_dir) if cache_dir else root / "data" / "cache"
    size_gb = video.stat().st_size / (1 << 30)
    print(f"считаю хэш видео ({size_gb:.1f} ГБ, может занять ~{max(1, int(size_gb * 2))} с)…", flush=True)
    # ВАЖНО: тот же хэш, что использует run/status/автокроп (partial-p1, file_sha256_cached_fast).
    # Раньше был полный file_sha256_cached → ключ калибровки не совпадал с ключом поиска в run,
    # и ручной кроп молча игнорировался (run падал в автокроп). См. регресс-тест.
    sha = state.file_sha256_cached_fast(video, _cache_dir)
    print("хэш готов.", flush=True)
    calib_dir = root / "calibrations"
    work = calib_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)

    print(f"извлекаю кадры для калибровки (главный ~{main_at:.0f}с + превью-сетка)…", flush=True)
    frames = extract_preview_frames(video, work, sha, duration, main_at=main_at, ffmpeg=ffmpeg)
    if not frames:
        # Ни один кадр не извлёкся → фолбэк к одиночному извлечению (внятная ошибка при провале).
        frame_png = work / f"{sha}.png"
        extract_reference_frame(video, frame_png, at_seconds=main_at, ffmpeg=ffmpeg)
        frames = [{"label": f"{int(round(main_at/duration*100)) if duration else 0}%",
                   "path": frame_png, "at": main_at, "is_main": True}]
    main_frame = next(f for f in frames if f["is_main"])

    if calibrator is None:
        calibrator = ManualCalibrator(
            sha=sha, source_name=video.name, calib_dir=calib_dir, setup_label=setup_label,
            host=host, port=port, timeout_sec=timeout_sec, preview_frames=frames,
        )

    sel = calibrator.propose(main_frame["path"], (dw, dh))
    # POST-хендлер ManualCalibrator уже сохранил (saved_path); иначе (напр. авто-детект,
    # возвращающий только рамку) — сохраняем здесь. Единый финал через ядро.
    path = getattr(calibrator, "saved_path", None)
    if path is None:
        crop = finalize_selection(sel)
        path = save_calibration(
            calib_dir, source_name=video.name, source_sha256=sha,
            crop=crop, frame=[dw, dh], setup_label=setup_label,
        )
    # Жёсткая кросс-проверка сохранённого кропа против ОТОБРАЖАЕМЫХ (display, rotation-aware)
    # размеров — ровно то пространство, в котором рендер применит crop-фильтр. Ловит рассинхрон
    # ДО того как рендер молча склампит и выдаст 30 битых клипов. Битую калибровку удаляем.
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    sc = saved["crop"]
    crop_obj = Crop.model_validate(sc)
    try:
        validate_crop_in_frame(crop_obj, dw, dh)
    except CalibrationError as e:
        Path(path).unlink(missing_ok=True)
        raise CalibrateError(
            f"калибровка отклонена: {e} (отображаемый кадр {dw}×{dh}). Перекалибруй — "
            f"координаты не в масштабе оригинала."
        ) from e
    for warn in crop_orientation_warnings(crop_obj, dw, dh):
        print(f"  ⚠ {warn}", flush=True)
    print(f"калибровка сохранена: {path}  "
          f"(кроп {sc['w']}×{sc['h']} @ {sc['x']},{sc['y']} в кадре {dw}×{dh})", flush=True)
    return path


# --------------------------------------------------------------- HTML-шаблон (видоискатель)
# Плейсхолдеры (__CONFIG__/__FRAME_B64__/…) подставляет build_calibration_html. Не f-string:
# фигурные скобки CSS/JS остаются литералами.
_HTML_TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">  <!-- пустой favicon: браузер не дёргает /favicon.ico (после Save сервер мёртв) -->
<title>Калибровка кропа — __SOURCE__</title>
<style>
  :root{
    --bg:#0c0d10; --stage:#08090b; --panel:#14161c; --line:#23262e;
    --ink:#e9e6df; --mut:#8b9099; --accent:#ffbf47; --accent-dim:#7a5a14;
    --ok:#7bd88f; --bad:#ff6b6b;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{background:var(--bg);color:var(--ink);font-family:var(--sans);
    -webkit-font-smoothing:antialiased}
  main{display:grid;grid-template-columns:1fr 340px;gap:0;min-height:100vh}
  @media(max-width:880px){main{grid-template-columns:1fr}}

  /* сцена с кадром */
  .stage{background:var(--stage);display:grid;place-items:center;padding:28px;overflow:auto}
  .frame{position:relative;line-height:0;box-shadow:0 24px 80px rgba(0,0,0,.6)}
  .frame img{display:block;max-width:100%;height:auto;user-select:none;-webkit-user-drag:none;
    transform-origin:center center}   /* поворот выравнивания горизонта — вокруг центра */

  /* сетка-помощник выравнивания: горизонтали/вертикали поверх кадра (НЕ поворачивается —
     эталон, к которому пользователь подгоняет наклонённый горизонт). Плотнее правила третей. */
  .level-grid{position:absolute;inset:0;pointer-events:none;z-index:1;display:none;
    background:
      repeating-linear-gradient(0deg,transparent 0,transparent calc(10% - 1px),rgba(110,168,254,.5) calc(10% - 1px),rgba(110,168,254,.5) 10%),
      repeating-linear-gradient(90deg,transparent 0,transparent calc(10% - 1px),rgba(110,168,254,.5) calc(10% - 1px),rgba(110,168,254,.5) 10%)}
  .level-grid.on{display:block}
  .level-grid::after{content:"";position:absolute;left:0;right:0;top:50%;height:2px;
    margin-top:-1px;background:rgba(123,216,143,.9)}   /* центральная горизонталь — «уровень» */

  /* 9:16 рамка-видоискатель: вырез в затемнении через большой box-shadow */
  .crop{position:absolute;left:0;top:0;cursor:grab;
    outline:1.5px solid var(--accent);
    box-shadow:0 0 0 100vmax rgba(7,8,10,.66);
    touch-action:none}
  .crop:active{cursor:grabbing}
  .crop:focus-visible{outline:2px solid #fff}
  /* правило третей */
  .thirds{position:absolute;inset:0;pointer-events:none;
    background:
      linear-gradient(var(--accent),var(--accent)) 33.33% 0/1px 100% no-repeat,
      linear-gradient(var(--accent),var(--accent)) 66.66% 0/1px 100% no-repeat,
      linear-gradient(var(--accent),var(--accent)) 0 33.33%/100% 1px no-repeat,
      linear-gradient(var(--accent),var(--accent)) 0 66.66%/100% 1px no-repeat;
    opacity:.28}
  .badge{position:absolute;left:50%;bottom:8px;transform:translateX(-50%);
    font:600 11px/1 var(--mono);letter-spacing:.08em;color:#0c0d10;
    background:var(--accent);padding:4px 8px;border-radius:2px;white-space:nowrap;
    pointer-events:none}
  .badge.warn{background:var(--bad);color:#fff}   /* очень узкий кроп (<30% ширины) */
  /* угловые ручки-метки */
  .handle{position:absolute;width:16px;height:16px;border:2px solid var(--accent);
    background:rgba(12,13,16,.5);touch-action:none}
  .handle.nw{left:-8px;top:-8px;border-right:0;border-bottom:0;cursor:nwse-resize}
  .handle.ne{right:-8px;top:-8px;border-left:0;border-bottom:0;cursor:nesw-resize}
  .handle.sw{left:-8px;bottom:-8px;border-right:0;border-top:0;cursor:nesw-resize}
  .handle.se{right:-8px;bottom:-8px;border-left:0;border-top:0;cursor:nwse-resize}

  /* панель */
  .panel{background:var(--panel);border-left:1px solid var(--line);
    padding:22px 22px 26px;display:flex;flex-direction:column;gap:18px}
  .eyebrow{font:600 11px/1 var(--mono);letter-spacing:.22em;text-transform:uppercase;
    color:var(--accent)}
  h1{margin:.35em 0 0;font-size:19px;font-weight:650;letter-spacing:-.01em}
  h1 .src{display:block;font:500 12px/1.4 var(--mono);color:var(--mut);margin-top:6px;
    word-break:break-all}
  .hint{margin:0;font-size:12.5px;line-height:1.5;color:var(--mut)}
  .orient{margin:0;font:600 12px/1.45 var(--sans);color:var(--accent);
    background:var(--accent-dim);opacity:.95;padding:9px 11px;border-radius:6px}

  .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .field{display:flex;flex-direction:column;gap:5px}
  .field label{font:600 10px/1 var(--mono);letter-spacing:.14em;color:var(--mut);
    text-transform:uppercase}
  .field .u{color:var(--accent-dim)}
  .field input{background:#0c0d10;border:1px solid var(--line);color:var(--ink);
    font:500 16px/1 var(--mono);padding:9px 10px;border-radius:5px;width:100%}
  .field input:focus{outline:none;border-color:var(--accent)}

  /* блок палитры цвета */
  .palbox{border:1px solid var(--line);border-radius:8px;padding:12px 13px;
    display:flex;flex-direction:column;gap:9px}
  .palhead{font:600 10px/1 var(--mono);letter-spacing:.14em;color:var(--mut);text-transform:uppercase}
  .palrow{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}
  .palbtn{appearance:none;border:1px solid var(--line);background:#0c0d10;color:var(--ink);
    font:600 12px/1 var(--sans);padding:9px 4px;border-radius:5px;cursor:pointer;text-align:center}
  .palbtn:hover{border-color:var(--accent)}
  .palbtn.active{border-color:var(--accent);background:var(--accent-dim);color:var(--accent)}
  .palhint{margin:0;font:500 11px/1.4 var(--sans);color:var(--mut)}

  /* блок выравнивания горизонта */
  .rotbox{border:1px solid var(--line);border-radius:8px;padding:12px 13px;
    display:flex;flex-direction:column;gap:9px}
  .rothead{display:flex;justify-content:space-between;align-items:baseline}
  .rothead label{font:600 10px/1 var(--mono);letter-spacing:.14em;color:var(--mut);
    text-transform:uppercase}
  .rothead output{font:650 15px/1 var(--mono);color:var(--accent)}
  .rotbox input[type=range]{width:100%;accent-color:var(--accent);cursor:pointer}
  .rotrow{display:flex;justify-content:space-between;align-items:center;gap:10px}
  .rotbox .mini{appearance:none;border:1px solid var(--line);background:#0c0d10;color:var(--ink);
    font:600 11px/1 var(--mono);padding:6px 9px;border-radius:5px;cursor:pointer}
  .rotbox .mini:hover{border-color:var(--accent)}
  .chk{display:flex;align-items:center;gap:6px;font:500 11.5px/1 var(--sans);color:var(--mut);
    cursor:pointer}
  .rothint{margin:0;font:500 11px/1.4 var(--sans);color:var(--mut)}
  .rothint.bad{color:var(--bad)}

  button#save{appearance:none;border:0;border-radius:6px;cursor:pointer;
    background:var(--accent);color:#0c0d10;font:650 14px/1 var(--sans);
    padding:13px 14px;letter-spacing:.01em}
  button#save:not(:disabled):hover{filter:brightness(1.06)}
  button#save:focus-visible{outline:2px solid #fff;outline-offset:2px}
  button#save:disabled{cursor:default;opacity:.6}           /* «Сохраняю…» — приглушённо */
  button#save.saved{background:var(--ok);color:#06140a;opacity:1}  /* терминальное «сохранено» */

  .status{margin:0;font:500 12.5px/1.5 var(--mono);min-height:1.4em;color:var(--mut)}
  .status.ok{color:var(--ok)} .status.bad{color:var(--bad)}
  body.done .stage{opacity:.5;transition:opacity .3s} 

  .meta{margin:0;border-top:1px solid var(--line);padding-top:14px;
    display:grid;grid-template-columns:auto 1fr;gap:6px 12px;
    font:500 11.5px/1.4 var(--mono);color:var(--mut)}
  .meta dt{color:#5f656e} .meta dd{margin:0;text-align:right;word-break:break-all}
  .thumbs{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;justify-content:center}
  .thumb{border:2px solid var(--line);border-radius:7px;overflow:hidden;cursor:pointer;
    width:104px;background:var(--stage);opacity:.65;transition:opacity .15s,border-color .15s}
  .thumb:hover{opacity:.9}
  .thumb.active{border-color:#6ea8fe;opacity:1}
  .thumb img{width:100%;display:block;height:58px;object-fit:cover}
  .thumb span{display:block;font:600 10px/1.6 var(--mono);text-align:center;color:var(--mut)}
  @media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<main>
  <section class="stage">
    <div class="frame" id="frame">
      <img id="img" src="data:image/png;base64,__FRAME_B64__" alt="опорный кадр середины видео">
      <div class="level-grid" id="levelGrid"></div>
      <div class="crop" id="crop" tabindex="0" aria-label="рамка кропа 9:16, стрелки двигают">
        <div class="thirds"></div>
        <div class="badge" id="badge">9:16 · 1080×1920</div>
        <div class="handle nw" data-corner="nw"></div>
        <div class="handle ne" data-corner="ne"></div>
        <div class="handle sw" data-corner="sw"></div>
        <div class="handle se" data-corner="se"></div>
      </div>
    </div>
    <div class="thumbs" id="thumbs" aria-label="выбор кадра для калибровки"></div>
  </section>

  <aside class="panel">
    <div>
      <div class="eyebrow">Кадр середины · 9:16</div>
      <h1>Калибровка кропа<span class="src">__SOURCE__</span></h1>
    </div>
    <p class="orient" id="orient">__ORIENT_HINT__</p>
    <p class="hint">Тяни рамку — двигает. Тяни углы — меняет размер, держа 9:16.
      Координаты — в реальных пикселях исходника. Стрелки двигают на 1 px (Shift — 10).</p>

    <div class="grid">
      <div class="field"><label>X <span class="u">px</span></label><input id="fx" type="number" inputmode="numeric"></div>
      <div class="field"><label>Y <span class="u">px</span></label><input id="fy" type="number" inputmode="numeric"></div>
      <div class="field"><label>Ширина <span class="u">px</span></label><input id="fw" type="number" inputmode="numeric"></div>
      <div class="field"><label>Высота <span class="u">px</span></label><input id="fh" type="number" inputmode="numeric"></div>
    </div>

    <div class="palbox">
      <div class="palhead">Палитра цвета</div>
      <div class="palrow" id="palrow">
        <button type="button" class="palbtn active" data-pal="neutral">без изм.</button>
        <button type="button" class="palbtn" data-pal="vivid">vivid</button>
        <button type="button" class="palbtn" data-pal="soft">soft</button>
        <button type="button" class="palbtn" data-pal="sharp">sharp</button>
      </div>
      <p class="palhint">Мгновенный предпросмотр на кадре. Палитра сохранится в манифест этого видео.</p>
    </div>

    <div class="rotbox">
      <div class="rothead">
        <label for="rot">Выравнивание горизонта</label>
        <output id="rotval">0.0°</output>
      </div>
      <input id="rot" type="range" min="-10" max="10" step="0.1" value="0"
             aria-label="угол поворота, градусы">
      <div class="rotrow">
        <button type="button" id="rotreset" class="mini">Сброс 0°</button>
        <label class="chk"><input type="checkbox" id="gridtog"> сетка-уровень</label>
      </div>
      <p class="rothint" id="rothint">Наклонён горизонт? Крути ползунок и ровняй по сетке.</p>
    </div>

    <button id="save">Сохранить кроп</button>
    <p class="status" id="status" role="status"></p>

    <dl class="meta">
      <dt>Исходник</dt><dd id="m-frame">__FW__×__FH__</dd>
      <dt>Выход</dt><dd>1080×1920</dd>
      <dt>sha</dt><dd>__SHA12__…</dd>
    </dl>
  </aside>
</main>

<script>
const CFG = __CONFIG__;
const FRAMES = __FRAMES_JSON__;
const FW = CFG.fw, FH = CFG.fh;

// Превью-сетка: клик по кадру меняет фон-кадр (кроп frame-независим — все одного разрешения).
(function renderThumbs(){
  const box = document.getElementById('thumbs');
  const img = document.getElementById('img');
  if (!box || !img || !Array.isArray(FRAMES) || FRAMES.length < 2) return;
  FRAMES.forEach(f => {
    const uri = 'data:image/png;base64,' + f.b64;
    const t = document.createElement('div');
    t.className = 'thumb' + (f.main ? ' active' : '');
    t.innerHTML = '<img src="' + uri + '" alt="кадр ' + f.label + '"><span>' + f.label + '</span>';
    t.addEventListener('click', function(){
      img.src = uri;
      box.querySelectorAll('.thumb').forEach(e => e.classList.remove('active'));
      t.classList.add('active');
    });
    box.appendChild(t);
  });
})();
const RATIO = 1080/1920;              // ширина/высота = 0.5625 (жёстко держим)
const MIN_REAL_H = 160;              // не дать рамке схлопнуться

const img=document.getElementById('img'), frame=document.getElementById('frame'),
      crop=document.getElementById('crop'), statusEl=document.getElementById('status'),
      saveBtn=document.getElementById('save');
const fld={x:document.getElementById('fx'),y:document.getElementById('fy'),
           w:document.getElementById('fw'),h:document.getElementById('fh')};

let DW=0, DH=0, s=1;                  // размер показа + масштаб (показ на реальный)
let NW=FW, NH=FH;                     // НАТУРАЛЬНЫЙ размер извлечённого кадра. Берём его из
                                     // самого PNG, а не из ffprobe: при SAR/повороте телефона
                                     // ffprobe width/height (кодированный) ≠ реальному кадру,
                                     // и масштаб врал → кроп сохранялся не в тех пикселях.
let box={x:0,y:0,w:0,h:0};            // рамка в ПИКСЕЛЯХ ПОКАЗА

function measure(){ NW=img.naturalWidth||FW; NH=img.naturalHeight||FH;
  DW=img.clientWidth; DH=img.clientHeight; s=DW/NW;   // показ→реальный по НАТУРАЛЬНОМУ размеру
  frame.style.width=DW+'px'; frame.style.height=DH+'px'; }

function clamp(){                     // 9:16 + в границах кадра (показ-px)
  const minH=MIN_REAL_H*s, maxH=Math.min(DH, DW/RATIO);
  box.h=Math.max(minH, Math.min(box.h, maxH));
  box.w=box.h*RATIO;
  box.x=Math.max(0, Math.min(box.x, DW-box.w));
  box.y=Math.max(0, Math.min(box.y, DH-box.h));
}
const badgeEl=document.getElementById('badge');
function syncFields(){                // показ → РЕАЛЬНЫЕ px исходника (в натуральном размере кадра)
  const rx=Math.round(box.x/s), ry=Math.round(box.y/s),
        rw=Math.round(box.w/s), rh=Math.round(box.h/s);
  fld.x.value=rx; fld.y.value=ry; fld.w.value=rw; fld.h.value=rh;
  // Живой показ реальных пикселей ОРИГИНАЛА рядом с рамкой + доля ширины кадра.
  if(badgeEl){ const pct=NW?Math.round(rw/NW*100):0;
    badgeEl.textContent=rw+'×'+rh+' @ '+rx+','+ry+'  ('+pct+'% ширины '+NW+'px)';
    badgeEl.classList.toggle('warn', pct>0 && pct<30); }   // <30% — подозрительно узко
}
function render(){
  crop.style.left=box.x+'px'; crop.style.top=box.y+'px';
  crop.style.width=box.w+'px'; crop.style.height=box.h+'px';
  syncFields();
  updateRotHint();                    // при сдвиге рамки — пересчёт безопасности угла
}

/* ---- выравнивание горизонта: поворот кадра (CSS-превью), сетка-уровень, live-проверка ---- */
let ROT=0;
const rotEl=document.getElementById('rot'), rotVal=document.getElementById('rotval'),
      rotHint=document.getElementById('rothint'), levelGrid=document.getElementById('levelGrid');
// Помещается ли кроп в заполненную область при повороте на deg (та же октагон-проверка, что в
// ядре: оба знака поворота, углы кропа в реальных px должны попасть в [0,NW]×[0,NH]).
function cropFitsRot(deg){
  if(!deg) return true;
  const th=Math.abs(deg)*Math.PI/180, cx=NW/2, cy=NH/2, ct=Math.cos(th), st=Math.sin(th), tol=1;
  const rx=box.x/s, ry=box.y/s, rw=box.w/s, rh=box.h/s;
  const corners=[[rx,ry],[rx+rw,ry],[rx,ry+rh],[rx+rw,ry+rh]];
  for(const c of corners){ const dx=c[0]-cx, dy=c[1]-cy;
    for(const sg of [1,-1]){ const qx=cx+dx*ct-sg*dy*st, qy=cy+sg*dx*st+dy*ct;
      if(qx<-tol||qy<-tol||qx>NW+tol||qy>NH+tol) return false; } }
  return true;
}
function updateRotHint(){
  if(!rotHint) return;
  const ok=cropFitsRot(ROT);
  rotHint.classList.toggle('bad', !ok);
  rotHint.textContent = ok
    ? 'Наклонён горизонт? Крути ползунок и ровняй по сетке.'
    : '⚠ кроп задевает пустые углы повёрнутого кадра — уменьши угол или сдвинь/сузь рамку';
}
function applyRot(){
  ROT=parseFloat(rotEl.value)||0;
  rotVal.textContent=ROT.toFixed(1)+'°';
  img.style.transform = ROT ? 'rotate('+ROT+'deg)' : '';
  updateRotHint();
}
rotEl.addEventListener('input',applyRot);
document.getElementById('rotreset').addEventListener('click',()=>{ rotEl.value=0; applyRot(); });
document.getElementById('gridtog').addEventListener('change',e=>{
  levelGrid.classList.toggle('on', e.target.checked); });

/* ---- палитра цвета: мгновенный предпросмотр CSS-фильтром на кадре ---- */
let PAL='neutral';
// CSS-приближение пресетов рендера (eq/unsharp). Предпросмотр ориентировочный: точный цветокор
// делает ffmpeg при рендере, здесь — чтобы прикинуть, какая палитра идёт видео.
const PAL_FILTER={neutral:'',vivid:'saturate(1.15) contrast(1.1)',
  soft:'contrast(0.95) saturate(1.05) sepia(0.12)',sharp:'contrast(1.08) saturate(1.02)'};
function applyPal(){ img.style.filter = PAL_FILTER[PAL] || 'none'; }
document.querySelectorAll('.palbtn').forEach(b=>b.addEventListener('click',()=>{
  PAL=b.dataset.pal;
  document.querySelectorAll('.palbtn').forEach(e=>e.classList.remove('active'));
  b.classList.add('active');
  applyPal();
}));

/* ---- перетаскивание тела рамки ---- */
crop.addEventListener('pointerdown',e=>{
  if(e.target.classList.contains('handle')) return;
  e.preventDefault(); crop.setPointerCapture(e.pointerId);
  const sx=e.clientX, sy=e.clientY, bx=box.x, by=box.y;
  function mv(ev){ box.x=bx+(ev.clientX-sx); box.y=by+(ev.clientY-sy); clamp(); render(); }
  function up(ev){ crop.releasePointerCapture(e.pointerId);
    crop.removeEventListener('pointermove',mv); crop.removeEventListener('pointerup',up); }
  crop.addEventListener('pointermove',mv); crop.addEventListener('pointerup',up);
});

/* ---- ресайз за угол, якорь — противоположный угол, всегда 9:16 ---- */
frame.querySelectorAll('.handle').forEach(h=>{
  h.addEventListener('pointerdown',e=>{
    e.preventDefault(); e.stopPropagation(); h.setPointerCapture(e.pointerId);
    const corner=h.dataset.corner;
    const ax=(corner==='nw'||corner==='sw')?box.x+box.w:box.x;   // фикс. X угла
    const ay=(corner==='nw'||corner==='ne')?box.y+box.h:box.y;   // фикс. Y угла
    const left=(corner==='nw'||corner==='sw');                   // тянем влево
    const up_=(corner==='nw'||corner==='ne');                    // тянем вверх
    const rect=img.getBoundingClientRect();
    function mv(ev){
      const px=ev.clientX-rect.left, py=ev.clientY-rect.top;
      let nh=Math.abs(py-ay);                                    // высота от якоря до курсора
      const roomH=up_?ay:DH-ay;                                  // вертикальный запас
      const roomW=left?ax:DW-ax;                                 // горизонтальный запас
      nh=Math.min(nh, roomH, roomW/RATIO);
      nh=Math.max(nh, MIN_REAL_H*s);
      const nw=nh*RATIO;
      box.h=nh; box.w=nw;
      box.x=left?ax-nw:ax;
      box.y=up_?ay-nh:ay;
      clamp(); render();
    }
    function up(ev){ h.releasePointerCapture(e.pointerId);
      h.removeEventListener('pointermove',mv); h.removeEventListener('pointerup',up); }
    h.addEventListener('pointermove',mv); h.addEventListener('pointerup',up);
  });
});

/* ---- поля (реальные px) → рамка; двусторонняя связь ---- */
function fromField(which){
  const v=parseFloat(fld[which].value); if(isNaN(v)) return;
  if(which==='h'){ box.h=v*s; box.w=box.h*RATIO; }
  else if(which==='w'){ box.w=v*s; box.h=box.w/RATIO; }
  else if(which==='x'){ box.x=v*s; }
  else if(which==='y'){ box.y=v*s; }
  clamp(); render();
}
for(const k of ['x','y','w','h']) fld[k].addEventListener('change',()=>fromField(k));

/* ---- стрелки для точной подвижки (1 реальный px, Shift — 10) ---- */
crop.addEventListener('keydown',e=>{
  const step=(e.shiftKey?10:1)*s; let used=true;
  if(e.key==='ArrowLeft') box.x-=step; else if(e.key==='ArrowRight') box.x+=step;
  else if(e.key==='ArrowUp') box.y-=step; else if(e.key==='ArrowDown') box.y+=step;
  else used=false;
  if(used){ e.preventDefault(); clamp(); render(); }
});

/* ---- сохранить: показ-рамка + размеры показа/кадра → сервер. Один успешный POST,
       после него сервер гаснет → кнопку запираем терминально, второй POST не шлём. ---- */
let saved=false;
saveBtn.addEventListener('click',()=>{
  if(saved) return;                                    // уже сохранено — сервер мёртв, не бьёмся
  saveBtn.disabled=true; statusEl.className='status'; statusEl.textContent='Сохраняю…';
  fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      display:{x:Math.round(box.x),y:Math.round(box.y),w:Math.round(box.w),h:Math.round(box.h)},
      display_size:[Math.round(DW),Math.round(DH)],
      frame_size:[NW,NH],                             // НАТУРАЛЬНЫЙ размер кадра, не ffprobe
      rotation_deg:ROT,                               // угол выравнивания горизонта (0 = без поворота)
      palette:PAL                                     // палитра цвета (neutral = дефолт рендера)
    })})
   .then(r=>r.json())
   .then(d=>{ if(d.ok){ const c=d.crop;
       saved=true;
       saveBtn.classList.add('saved');               // зелёная, под цвет статуса
       saveBtn.textContent='✓ Сохранено — закройте вкладку';
       statusEl.className=d.warning?'status bad':'status ok';
       statusEl.textContent='Кроп '+c.x+','+c.y+' '+c.w+'×'+c.h+' сохранён.'
         +(d.warning?('  ⚠ '+d.warning):'  Сервер остановлен.');
       document.body.classList.add('done');
       // Без авто-закрытия вкладки, reload и повторных запросов: сервер погас, страница
       // застывает в финальном состоянии. Вкладку пользователь закрывает сам.
     } else { statusEl.className='status bad'; statusEl.textContent='Ошибка: '+(d.error||'?');
       saveBtn.disabled=false; } })
   .catch(err=>{ statusEl.className='status bad'; statusEl.textContent='Сеть: '+err;
       saveBtn.disabled=false; });
});

/* ---- старт: рамка во всю высоту по центру; держим реальные коорд. при ресайзе окна ---- */
function init(){ measure(); box.h=DH; box.w=box.h*RATIO; box.x=(DW-box.w)/2; box.y=0;
  clamp(); render(); }
window.addEventListener('resize',()=>{ const r={x:box.x/s,y:box.y/s,w:box.w/s,h:box.h/s};
  measure(); box={x:r.x*s,y:r.y*s,w:r.w*s,h:r.h*s}; clamp(); render(); });
// Первый кадр → init (рамка по центру). Смена кадра превью-сеткой → пересчёт по реальным
// координатам (сохраняем рамку, не сбрасываем — иначе клик по превью терял настройку).
let _inited=false;
function onFrameLoad(){
  if(!_inited){ _inited=true; init(); }
  else { const r={x:box.x/s,y:box.y/s,w:box.w/s,h:box.h/s};
         measure(); box={x:r.x*s,y:r.y*s,w:r.w*s,h:r.h*s}; clamp(); render(); }
}
img.addEventListener('load',onFrameLoad);
if(img.complete && img.naturalWidth) onFrameLoad();
</script>
</body>
</html>
"""
