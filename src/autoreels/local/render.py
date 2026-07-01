r"""R1a — нарезка без кропа: manifest → reels-out/<id>_raw.mp4 (горизонтальный, как есть).

Локальный тир. Исходник живёт ЛОКАЛЬНО (на машине рендера), в облако не уходит; манифест
приходит через Syncthing. Кроп (R1b) и субтитры (R3) — отдельные шаги, здесь изолирован рез.

Несущие решения:
- **Идентичность по содержимому, не по пути.** `manifest.source` — Mac-путь с машины облака,
  на машине рендера невалиден. Исходник ищется в локальной `inputs/` по `source_sha256`
  (имя из `source` — лишь подсказка для быстрого поиска). Нет файла с таким хэшем → ошибка.
- **Энкодер — рантайм-параметр, не хардкод.** Кодек берётся из env `RENDER_ENCODER`, иначе
  из `render.yaml` (дефолт libx264; на Windows — h264_amf). Тонкая настройка rate-control
  под аппаратные энкодеры (AMF/VAAPI) — шаг 6; здесь покрыт дефолтный libx264-путь.
- **Кроссплатформенность.** Все локальные пути — через `pathlib`, без строк с `/` или `\`.
  Путь к ffmpeg-бинарю конфигурируем (Windows: `D:\ffmpeg\bin\ffmpeg.exe` или из PATH).
- **fail-fast.** Нет inputs/ / нет исходника / нет ffmpeg / ffmpeg упал → RenderError с
  внятным сообщением, без голого traceback и без битого частичного выхода.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from pydantic import ValidationError

from autoreels.core import state
from autoreels.core.config import RenderConfig, SubtitlesConfig
from autoreels.core.models import Manifest, SetupProfile
from autoreels.local.subtitles import build_ass

# Имя файла манифеста в папке manifests/ (приходит по Syncthing с машины облака).
_MANIFEST_NAME = "manifest.json"

# Кодеки, для которых -preset/-crf — родной rate-control. Для аппаратных энкодеров
# (h264_amf/h264_vaapi/nvenc) эти флаги невалидны; их настройка — шаг 6.
_SOFTWARE_X26X = {"libx264", "libx265"}

# env-переопределение энкодера (рантайм-конфиг машины рендера поверх render.yaml).
_ENCODER_ENV = "RENDER_ENCODER"


def _fmt_time(sec: float) -> str:
    """Секунды → M:SS или H:MM:SS для прогресс-строки."""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _run_ffmpeg_with_progress(
    cmd: list[str],
    *,
    reel_id: str,
    idx: int,
    total: int,
    duration_sec: float,
) -> tuple[int, str]:
    """Запустить ffmpeg с отображением прогресса через -progress pipe:1.

    Печатает «клип N/M: id (D:DD)…» затем обновляемую строку «\\r  T/D (P%)».
    Возвращает (returncode, stderr_text).
    """
    prog_cmd = [cmd[0], "-progress", "pipe:1"] + cmd[1:]
    stderr_chunks: list[str] = []

    proc = subprocess.Popen(
        prog_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    def _drain_stderr() -> None:
        for line in proc.stderr:
            stderr_chunks.append(line)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    print(f"\nклип {idx}/{total}: {reel_id} ({_fmt_time(duration_sec)})…", flush=True)
    for line in proc.stdout:
        key, _, val = line.strip().partition("=")
        if key == "out_time_ms":
            try:
                elapsed = max(0.0, int(val) / 1_000_000)
                pct = min(100, int(elapsed / duration_sec * 100)) if duration_sec > 0 else 0
                print(
                    f"\r  {_fmt_time(elapsed)}/{_fmt_time(duration_sec)} ({pct}%)",
                    end="", flush=True,
                )
            except (ValueError, ZeroDivisionError):
                pass
        elif key == "progress" and val.strip() == "end":
            print(
                f"\r  {_fmt_time(duration_sec)}/{_fmt_time(duration_sec)} (100%)",
                end="", flush=True,
            )

    proc.wait()
    t.join(timeout=2)
    print(flush=True)
    return proc.returncode, "".join(stderr_chunks)


class RenderError(Exception):
    """Рендер не удался (нет исходника/inputs/, нет ffmpeg, ffmpeg вернул ошибку)."""


def load_manifest(manifests_dir: str | Path, *, name: str = _MANIFEST_NAME) -> Manifest:
    """Прочитать и провалидировать manifest.json из папки `manifests/`.

    Манифест — единственный контракт ОБЛАКО→ЛОКАЛЬ; приходит по Syncthing. Битый/неполный
    файл или нарушение схемы → RenderError на загрузке (fail-fast), без голого traceback.
    """
    path = Path(manifests_dir) / name
    if not path.is_file():
        raise RenderError(f"манифест не найден: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise RenderError(f"не удалось прочитать манифест {path}: {e}") from e
    try:
        return Manifest.model_validate_json(text)
    except ValidationError as e:
        raise RenderError(f"невалидный манифест {path}:\n{e}") from e


def _ts(seconds: float) -> str:
    """Таймкод для ffmpeg в секундах с миллисекундной точностью."""
    return f"{seconds:.3f}"


def _basename_hint(source: str) -> str:
    """Имя файла из `source` независимо от ОС-происхождения строки (POSIX или Windows).

    Это лишь подсказка для быстрого поиска в inputs/; идентичность исходника всё равно
    проверяется по sha256, не по имени.
    """
    win = PureWindowsPath(source).name      # режет и по '\', и по '/'
    posix = PurePosixPath(source).name
    # Берём более короткий результат: тот разделитель «сработал» и отрезал каталоги.
    return win if len(win) <= len(posix) else posix


def resolve_source(manifest: Manifest, inputs_dir: str | Path) -> Path:
    """Найти исходник в `inputs_dir` по `manifest.source_sha256`.

    Mac-путь из `manifest.source` игнорируется (на машине рендера невалиден) — используется
    как подсказка по имени для быстрого пути. Файл с нужным хэшем не найден → RenderError.
    """
    inputs_dir = Path(inputs_dir)
    if not inputs_dir.is_dir():
        raise RenderError(f"папка inputs/ не найдена: {inputs_dir}")

    want = manifest.source_sha256
    if not want:
        raise RenderError("в манифесте нет source_sha256 — нечем идентифицировать исходник")

    # Порядок проверки: сначала файл с тем же именем (подсказка), затем остальные файлы
    # папки — чтобы не хэшировать всю inputs/, когда имя уцелело.
    hint = _basename_hint(manifest.source)
    by_name = inputs_dir / hint
    ordered: list[Path] = []
    if by_name.is_file():
        ordered.append(by_name)
    for p in sorted(inputs_dir.iterdir()):
        if p.is_file() and p != by_name:
            ordered.append(p)

    scheme = getattr(manifest, "source_hash_scheme", "full")
    hash_fn = state.file_sha256_partial if scheme == "partial-p1" else state.file_sha256
    for p in ordered:
        if hash_fn(p) == want:
            return p

    raise RenderError(
        f"исходник не найден в {inputs_dir}: нет файла с sha256={want[:12]}… "
        f"(имя-подсказка из манифеста: {hint!r})"
    )


def _video_quality_args(codec: str, preset: str, cq: int) -> list[str]:
    """Аргументы качества/скорости видеоэнкодера.

    Покрыт дефолтный libx264(+x265) путь (-preset/-crf). Для аппаратных энкодеров
    rate-control задаётся на шаге 6 — здесь им отдаём только кодек (дефолтное качество),
    чтобы не подсовывать невалидные для AMF/VAAPI флаги.
    """
    if codec in _SOFTWARE_X26X:
        return ["-preset", preset, "-crf", str(cq)]
    return []


def build_cut_cmd(
    ffmpeg: str,
    source: str | Path,
    start: float,
    end: float,
    out: str | Path,
    *,
    codec: str,
    preset: str,
    cq: int,
    audio_codec: str,
    audio_bitrate: str,
    vf: str | None = None,
) -> list[str]:
    """Собрать команду ffmpeg: вырезать окно start→end из `source`.

    Без `vf` — рез КАК ЕСТЬ (R1a, горизонтальный <id>_raw.mp4). С `vf` — добавляется
    видеофильтр (R1b: `crop=…,scale=…` → вертикальный <id>.mp4). Чистая функция (без ФС) —
    единица, которую проверяют тесты сборки команды. Seek по входу (`-ss` до `-i`) +
    `-t` (длительность) — быстрый рез с перекодированием.
    """
    duration = round(end - start, 3)
    return [
        str(ffmpeg), "-y", "-loglevel", "error",
        "-ss", _ts(start),
        "-i", str(source),
        "-t", _ts(duration),
        *(["-vf", vf] if vf else []),
        "-c:v", codec,
        *_video_quality_args(codec, preset, cq),
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        str(out),
    ]


def _crop_vf(setup: SetupProfile) -> str:
    """Видеофильтр кропа+скейла из профиля сетапа: `crop=w:h:x:y,scale=SW:SH`.

    Числа — данные манифеста (`setup.crop` + `setup.scale`), НЕ хардкод в коде. Кроп один
    на все клипы (уровень манифеста, не reel — как в схеме models.py).
    """
    c = setup.crop
    sw, sh = setup.scale
    return f"crop={c.w}:{c.h}:{c.x}:{c.y},scale={sw}:{sh}"


def _escape_ass_path(path: Path) -> str:
    """Путь к .ass для фильтрграфа ffmpeg: экранируем ':' (Windows D:\\…), слэши — прямые."""
    return str(path).replace("\\", "/").replace(":", "\\:")


def _render_segments(
    manifest: Manifest,
    *,
    inputs_dir: str | Path,
    out_dir: str | Path,
    render_cfg: RenderConfig,
    ffmpeg: str,
    encoder: str | None,
    vf: str | None,
    suffix: str,
    progress: Callable[[str], None] | None = None,
    emit_text: bool = False,
    subtitles_cfg: SubtitlesConfig | None = None,
) -> list[Path]:
    """Общий цикл резки сегментов. `vf` — видеофильтр (None=рез как есть, R1a),
    `suffix` — хвост имени выхода (`_raw` для горизонтального, `` для вертикального).
    `progress` — колбэк, вызывается с id reel перед его рендером (видимый прогресс CLI).
    `emit_text` — класть рядом с клипом <id>.txt (title/description для публикации)."""
    source = resolve_source(manifest, inputs_dir)

    ffmpeg_bin = shutil.which(ffmpeg)
    if ffmpeg_bin is None:
        raise RenderError(
            f"ffmpeg не найден (искали '{ffmpeg}'); укажите путь к бинарю "
            f"(Windows: D:\\ffmpeg\\bin\\ffmpeg.exe) или добавьте его в PATH"
        )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    codec = encoder or os.environ.get(_ENCODER_ENV) or render_cfg.encoder.codec
    enc = render_cfg.encoder
    aud = render_cfg.audio

    # .ass живут в tempdir: после ffmpeg убираются автоматически, в out_dir не остаются.
    with tempfile.TemporaryDirectory(prefix="autoreels_ass_") as _tmp_ass:
        tmp_ass_dir = Path(_tmp_ass)
        outputs: list[Path] = []
        total = len(manifest.reels)
        for idx, reel in enumerate(manifest.reels, 1):
            if progress is not None:
                progress(reel.id)
            out = out_dir / f"{reel.id}{suffix}.mp4"
            # Субтитры (R3): на каждый reel свой .ass; ass-фильтр ПОСЛЕ crop/scale
            # (в координатах финального кадра 1080×1920). Слова берутся из reel.subtitles.
            reel_vf = vf
            if subtitles_cfg is not None and reel.subtitles:
                ass_path = tmp_ass_dir / f"{reel.id}.ass"
                ass_path.write_text(
                    build_ass(reel.subtitles, cfg=subtitles_cfg, clip_start=reel.start),
                    encoding="utf-8",
                )
                ass_filter = f"ass={_escape_ass_path(ass_path)}"
                reel_vf = f"{vf},{ass_filter}" if vf else ass_filter
            cmd = build_cut_cmd(
                ffmpeg_bin, source, reel.start, reel.end, out,
                codec=codec, preset=enc.preset, cq=enc.cq,
                audio_codec=aud.codec, audio_bitrate=aud.bitrate,
                vf=reel_vf,
            )
            returncode, stderr_text = _run_ffmpeg_with_progress(
                cmd, reel_id=reel.id, idx=idx, total=total,
                duration_sec=reel.end - reel.start,
            )
            if returncode != 0:
                out.unlink(missing_ok=True)         # не оставлять битый частичный выход
                stderr = stderr_text.strip() or "(пустой stderr)"
                raise RenderError(
                    f"ffmpeg не смог обработать reel {reel.id} "
                    f"({_ts(reel.start)}→{_ts(reel.end)}, код {returncode}): {stderr}"
                )
            outputs.append(out)
            if emit_text:
                _write_sidecar_text(out, reel)
        return outputs


def _write_sidecar_text(clip_path: Path, reel) -> None:
    """Текст публикации рядом с клипом: <id>.txt = title, пустая строка, description.

    Это НЕ субтитры (их вшивает R3) — это заголовок и описание поста (description уже
    несёт хэштеги по схеме R0). utf-8. Пусто и там, и там — файл не создаём.
    """
    if not (reel.title or reel.description):
        return
    txt_path = clip_path.with_suffix(".txt")
    txt_path.write_text(f"{reel.title}\n\n{reel.description}\n", encoding="utf-8")


def render_cut(
    manifest: Manifest,
    *,
    inputs_dir: str | Path,
    out_dir: str | Path,
    render_cfg: RenderConfig,
    ffmpeg: str = "ffmpeg",
    encoder: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    """R1a: для каждого reel вырезать окно из исходника КАК ЕСТЬ → `out_dir`/<id>_raw.mp4.

    Энкодер: явный `encoder` > env `RENDER_ENCODER` > `render_cfg.encoder.codec`. Возвращает
    пути готовых сырых клипов (горизонтальный исходник, без кропа и субтитров).
    """
    return _render_segments(
        manifest, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
        ffmpeg=ffmpeg, encoder=encoder, vf=None, suffix="_raw", progress=progress,
    )


def render_crop(
    manifest: Manifest,
    *,
    inputs_dir: str | Path,
    out_dir: str | Path,
    render_cfg: RenderConfig,
    ffmpeg: str = "ffmpeg",
    encoder: str | None = None,
    progress: Callable[[str], None] | None = None,
    subtitles_cfg: SubtitlesConfig | None = None,
) -> list[Path]:
    """R1b+R3: вырезать окно, применить кроп-профиль и (опц.) выжечь субтитры → <id>.mp4.

    Кроп+скейл (`setup.crop` + `setup.scale`) — данные манифеста, один на все клипы. Если
    передан `subtitles_cfg` и у reel есть слова — на клип накладывается ASS (после crop/scale).
    Выход — вертикальный 1080×1920, отдельно от <id>_raw.mp4 (R1a). Энкодер — тот же параметр.
    """
    return _render_segments(
        manifest, inputs_dir=inputs_dir, out_dir=out_dir, render_cfg=render_cfg,
        ffmpeg=ffmpeg, encoder=encoder, vf=_crop_vf(manifest.setup), suffix="",
        progress=progress, emit_text=True, subtitles_cfg=subtitles_cfg,
    )
