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
    proc = subprocess.run(build_probe_cmd(binary, video), capture_output=True, text=True, encoding="utf-8")
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
        build_frame_cmd(binary, video, out_png, at_seconds), capture_output=True, text=True, encoding="utf-8"
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

def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_calibration_html(frame_b64: str, frame_size: tuple[int, int], *, sha: str,
                           source_name: str) -> str:
    """Страница-видоискатель: кадр-фон + 9:16-рамка (constrained при drag/resize), поля
    x/y/w/h в РЕАЛЬНЫХ px исходника (двусторонние), Save → fetch POST /save.

    Кадр показывается уменьшенным; пересчёт показ↔реальные консистентен с to_real_pixels
    (s = display_w / frame_w; real = display / s). На сервер уходит display-рамка +
    display_size + frame_size — финал (9:16, реальные px, границы) считает ядро.
    """
    fw, fh = frame_size
    config = json.dumps({"fw": fw, "fh": fh, "sha": sha, "source": source_name})
    return (
        _HTML_TEMPLATE
        .replace("__CONFIG__", config)
        .replace("__FRAME_B64__", frame_b64)
        .replace("__SOURCE__", _html_escape(source_name))
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
  .frame img{display:block;max-width:100%;height:auto;user-select:none;-webkit-user-drag:none}

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

  .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .field{display:flex;flex-direction:column;gap:5px}
  .field label{font:600 10px/1 var(--mono);letter-spacing:.14em;color:var(--mut);
    text-transform:uppercase}
  .field .u{color:var(--accent-dim)}
  .field input{background:#0c0d10;border:1px solid var(--line);color:var(--ink);
    font:500 16px/1 var(--mono);padding:9px 10px;border-radius:5px;width:100%}
  .field input:focus{outline:none;border-color:var(--accent)}

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
  @media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<main>
  <section class="stage">
    <div class="frame" id="frame">
      <img id="img" src="data:image/png;base64,__FRAME_B64__" alt="опорный кадр середины видео">
      <div class="crop" id="crop" tabindex="0" aria-label="рамка кропа 9:16, стрелки двигают">
        <div class="thirds"></div>
        <div class="badge" id="badge">9:16 · 1080×1920</div>
        <div class="handle nw" data-corner="nw"></div>
        <div class="handle ne" data-corner="ne"></div>
        <div class="handle sw" data-corner="sw"></div>
        <div class="handle se" data-corner="se"></div>
      </div>
    </div>
  </section>

  <aside class="panel">
    <div>
      <div class="eyebrow">Кадр середины · 9:16</div>
      <h1>Калибровка кропа<span class="src">__SOURCE__</span></h1>
    </div>
    <p class="hint">Тяни рамку — двигает. Тяни углы — меняет размер, держа 9:16.
      Координаты — в реальных пикселях исходника. Стрелки двигают на 1 px (Shift — 10).</p>

    <div class="grid">
      <div class="field"><label>X <span class="u">px</span></label><input id="fx" type="number" inputmode="numeric"></div>
      <div class="field"><label>Y <span class="u">px</span></label><input id="fy" type="number" inputmode="numeric"></div>
      <div class="field"><label>Ширина <span class="u">px</span></label><input id="fw" type="number" inputmode="numeric"></div>
      <div class="field"><label>Высота <span class="u">px</span></label><input id="fh" type="number" inputmode="numeric"></div>
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
const FW = CFG.fw, FH = CFG.fh;
const RATIO = 1080/1920;              // ширина/высота = 0.5625 (жёстко держим)
const MIN_REAL_H = 160;              // не дать рамке схлопнуться

const img=document.getElementById('img'), frame=document.getElementById('frame'),
      crop=document.getElementById('crop'), statusEl=document.getElementById('status'),
      saveBtn=document.getElementById('save');
const fld={x:document.getElementById('fx'),y:document.getElementById('fy'),
           w:document.getElementById('fw'),h:document.getElementById('fh')};

let DW=0, DH=0, s=1;                  // размер показа + масштаб (показ на реальный)
let box={x:0,y:0,w:0,h:0};            // рамка в ПИКСЕЛЯХ ПОКАЗА

function measure(){ DW=img.clientWidth; DH=img.clientHeight; s=DW/FW;
  frame.style.width=DW+'px'; frame.style.height=DH+'px'; }

function clamp(){                     // 9:16 + в границах кадра (показ-px)
  const minH=MIN_REAL_H*s, maxH=Math.min(DH, DW/RATIO);
  box.h=Math.max(minH, Math.min(box.h, maxH));
  box.w=box.h*RATIO;
  box.x=Math.max(0, Math.min(box.x, DW-box.w));
  box.y=Math.max(0, Math.min(box.y, DH-box.h));
}
function syncFields(){                // показ → РЕАЛЬНЫЕ px исходника
  fld.x.value=Math.round(box.x/s); fld.y.value=Math.round(box.y/s);
  fld.w.value=Math.round(box.w/s); fld.h.value=Math.round(box.h/s);
}
function render(){
  crop.style.left=box.x+'px'; crop.style.top=box.y+'px';
  crop.style.width=box.w+'px'; crop.style.height=box.h+'px';
  syncFields();
}

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
      frame_size:[FW,FH]
    })})
   .then(r=>r.json())
   .then(d=>{ if(d.ok){ const c=d.crop;
       saved=true;
       saveBtn.classList.add('saved');               // зелёная, под цвет статуса
       saveBtn.textContent='✓ Сохранено — закройте вкладку';
       statusEl.className='status ok';
       statusEl.textContent='Кроп '+c.x+','+c.y+' '+c.w+'×'+c.h+' сохранён. Сервер калибровки остановлен.';
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
if(img.complete && img.naturalWidth) init(); else img.addEventListener('load',init);
</script>
</body>
</html>
"""
