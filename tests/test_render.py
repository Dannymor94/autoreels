"""R1a — нарезка без кропа (local/render.py). ffmpeg МОКАЕТСЯ (проверяем сборку команды),
реальный прогон h264_amf — ручной шаг на Windows.

Инварианты, которые тесты защищают:
- исходник ищется в локальной inputs/ по sha256, НЕ по Mac-пути из манифеста;
- команда ffmpeg корректна: окно start→end, выход <id>_raw.mp4, энкодер из конфига/env;
- энкодер — рантайм-параметр (env RENDER_ENCODER переопределяет конфиг), не хардкод;
- все пути через pathlib, кроссплатформенно (basename Mac/Windows-строки извлекается верно);
- несколько reel → несколько вызовов ffmpeg.
"""
import subprocess
from pathlib import Path, PureWindowsPath

import pytest

from autoreels.core.models import (
    Crop,
    Manifest,
    Reel,
    SetupProfile,
    Word,
)
from autoreels.core.config import load_render_config, load_subtitles_config
from autoreels.local import render
from autoreels.local.render import (
    RenderError,
    build_cut_cmd,
    load_manifest,
    resolve_source,
    render_crop,
    render_cut,
)

ROOT = Path(__file__).resolve().parents[1]
RENDER_YAML = ROOT / "config" / "render.yaml"


@pytest.fixture
def render_cfg():
    return load_render_config(RENDER_YAML)


def _setup() -> SetupProfile:
    return SetupProfile(
        setup_id="tearoom_main",
        crop=Crop(x=980, y=220, w=1010, h=1795),
        scale=[1080, 1920],
        frame=[3840, 2160],
    )


def _reel(rid: str, start: float, end: float, title: str = "t", description: str = "d") -> Reel:
    return Reel(
        id=rid, start=start, end=end, score=80,
        hook="h", title=title, description=description, reason="r", topic="x",
    )


def _make_source(inputs_dir: Path, name: str, content: bytes) -> str:
    """Создаёт фейковый видеофайл в inputs/, возвращает его sha256."""
    from autoreels.core import state
    inputs_dir.mkdir(parents=True, exist_ok=True)
    p = inputs_dir / name
    p.write_bytes(content)
    return state.file_sha256(p)


def _manifest(source: str, sha: str, reels: list[Reel], setup: SetupProfile | None = None) -> Manifest:
    return Manifest(
        source=source, source_sha256=sha, duration_preset="shorts",
        setup=setup or _setup(), run_key="rk1", reels=reels,
    )


def _val_after(cmd: list[str], flag: str) -> str:
    """Значение аргумента, идущего сразу за `flag` в команде."""
    i = cmd.index(flag)
    return cmd[i + 1]


# ------------------------------------------------ чтение manifest.json из manifests/

def test_load_manifest_reads_and_validates_json(tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    m = _manifest("/Users/danny/inputs/lecture.mp4", "a" * 64, [_reel("r01", 1.0, 5.0)])
    (manifests / "manifest.json").write_text(m.model_dump_json(), encoding="utf-8")

    loaded = load_manifest(manifests)
    assert loaded == m
    assert loaded.source_sha256 == "a" * 64
    assert loaded.reels[0].id == "r01"


def test_load_manifest_missing_file_raises(tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    with pytest.raises(RenderError) as e:
        load_manifest(manifests)
    assert "манифест" in str(e.value).lower() or "manifest" in str(e.value).lower()


def test_load_manifest_invalid_json_raises(tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "manifest.json").write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(RenderError):
        load_manifest(manifests)


def test_load_manifest_schema_violation_raises(tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    # валидный JSON, но не схема манифеста (нет обязательных полей)
    (manifests / "manifest.json").write_text('{"source": "x.mp4"}', encoding="utf-8")
    with pytest.raises(RenderError):
        load_manifest(manifests)


# --------------------------------------------------------------- сборка команды

def test_cut_cmd_has_window_output_and_encoder():
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/lecture.mp4"), 284.5, 341.5,
        Path("/out/r01_raw.mp4"),
        codec="libx264", preset="medium", cq=23,
        audio_codec="aac", audio_bitrate="160k",
    )
    assert cmd[0] == "ffmpeg"
    assert _val_after(cmd, "-i") == str(Path("/inputs/lecture.mp4"))   # вход — исходник
    assert _val_after(cmd, "-ss") == "284.500"                         # начало окна
    assert _val_after(cmd, "-t") == "57.000"                           # длительность = end-start
    assert _val_after(cmd, "-c:v") == "libx264"                        # энкодер из аргумента
    assert _val_after(cmd, "-c:a") == "aac"
    assert _val_after(cmd, "-b:a") == "160k"
    assert cmd[-1] == str(Path("/out/r01_raw.mp4"))                    # выход — последний аргумент


def test_cut_cmd_passes_through_configured_encoder():
    # Энкодер не хардкодится: что передали (на Windows — h264_amf), то и в команде.
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 10.0, Path("/out/r01_raw.mp4"),
        codec="h264_amf", preset="balanced", cq=23,
        audio_codec="aac", audio_bitrate="160k",
    )
    assert _val_after(cmd, "-c:v") == "h264_amf"
    # libx264-специфичный -crf не должен лезть в аппаратный энкодер (rate-control — шаг 6).
    assert "-crf" not in cmd


def test_cut_cmd_no_crop_filter():
    # R1a изолирует рез от кропа: фильтра кропа/скейла в команде быть не должно.
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 10.0, Path("/out/r01_raw.mp4"),
        codec="libx264", preset="medium", cq=23,
        audio_codec="aac", audio_bitrate="160k",
    )
    joined = " ".join(cmd)
    assert "crop=" not in joined
    assert "scale=" not in joined
    assert "-vf" not in cmd


# ----------------------------------------------------- поиск исходника по хэшу

def test_resolve_source_found_by_hash(tmp_path):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "lecture.mp4", b"video-bytes-A")
    m = _manifest("lecture.mp4", sha, [])
    assert resolve_source(m, inputs) == inputs / "lecture.mp4"


def test_resolve_source_not_found_raises(tmp_path):
    inputs = tmp_path / "inputs"
    _make_source(inputs, "other.mp4", b"some-other-video")
    # Хэш, которого в inputs/ нет → внятная ошибка.
    m = _manifest("lecture.mp4", "f" * 64, [])
    with pytest.raises(RenderError) as e:
        resolve_source(m, inputs)
    assert "sha256" in str(e.value).lower()


def test_resolve_source_ignores_mac_path_uses_local_inputs(tmp_path):
    # Манифест несёт несуществующий на этой машине Mac-путь, а файл в inputs/ лежит
    # под ДРУГИМ именем. Идентичность по хэшу → находим, Mac-путь игнорируется.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "renamed_on_windows.mp4", b"the-real-video")
    mac_path = "/Users/danny/Documents/autoreels/inputs/lecture.mp4"
    assert not Path(mac_path).exists()           # Mac-путь на этой машине невалиден
    m = _manifest(mac_path, sha, [])
    assert resolve_source(m, inputs) == inputs / "renamed_on_windows.mp4"


def test_resolve_source_basename_hint_handles_windows_path(tmp_path):
    # source может прийти как Windows-строка; basename-подсказку извлекаем кроссплатформенно.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "clip.mp4", b"win-sourced-video")
    win_source = r"D:\autoreels\inputs\clip.mp4"
    assert PureWindowsPath(win_source).name == "clip.mp4"
    m = _manifest(win_source, sha, [])
    assert resolve_source(m, inputs) == inputs / "clip.mp4"


# ----------------------------------------------------------- render_cut (моки)

@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Мокает ffmpeg: shutil.which находит бинарь, subprocess.Popen пишет вызовы и 'успешен'."""
    calls = []

    class _FakeProc:
        def __init__(self, cmd, **kwargs):
            calls.append(cmd)
            self.returncode = 0
            self.stdout = iter([])   # нет progress-строк
            self.stderr = iter([])

        def wait(self):
            return 0

    monkeypatch.setattr(render.shutil, "which", lambda b: "/fake/bin/ffmpeg")
    monkeypatch.setattr(render.subprocess, "Popen", _FakeProc)
    return calls


def test_render_cut_one_command_per_reel(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "lecture.mp4", b"multi-reel-video")
    out_dir = tmp_path / "reels-out"
    m = _manifest("lecture.mp4", sha, [
        _reel("r01", 10.0, 40.0),
        _reel("r02", 100.0, 130.0),
        _reel("r03", 200.0, 250.0),
    ])

    outputs = render_cut(m, inputs_dir=inputs, out_dir=out_dir, render_cfg=render_cfg)

    assert len(fake_ffmpeg) == 3                       # один вызов ffmpeg на reel
    assert outputs == [
        out_dir / "r01_raw.mp4",
        out_dir / "r02_raw.mp4",
        out_dir / "r03_raw.mp4",
    ]
    # окно второго клипа попало в его команду
    cmd2 = fake_ffmpeg[1]
    assert _val_after(cmd2, "-ss") == "100.000"
    assert _val_after(cmd2, "-t") == "30.000"


def test_render_cut_output_paths_are_pathlib_under_out_dir(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "lecture.mp4", b"pathlib-video")
    out_dir = tmp_path / "reels-out"
    m = _manifest("lecture.mp4", sha, [_reel("r01", 1.0, 5.0)])

    outputs = render_cut(m, inputs_dir=inputs, out_dir=out_dir, render_cfg=render_cfg)

    out = outputs[0]
    assert isinstance(out, Path)                       # не строка с / или \
    assert out.parent == out_dir
    assert out.name == "r01_raw.mp4"
    assert out_dir.is_dir()                            # папка выдачи создана


def test_render_cut_encoder_from_env_overrides_config(tmp_path, render_cfg, fake_ffmpeg, monkeypatch):
    # На Windows энкодер задаётся рантайм-конфигом (env), а не дефолтом libx264 из yaml.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "lecture.mp4", b"env-encoder-video")
    monkeypatch.setenv("RENDER_ENCODER", "h264_amf")
    m = _manifest("lecture.mp4", sha, [_reel("r01", 0.0, 5.0)])

    render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    assert _val_after(fake_ffmpeg[0], "-c:v") == "h264_amf"


def test_render_cut_uses_resolved_local_source_not_manifest_path(tmp_path, render_cfg, fake_ffmpeg):
    # В команду должен попасть локальный путь inputs/, а не Mac-путь из манифеста.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "real.mp4", b"resolved-source-video")
    mac_path = "/Users/danny/Documents/autoreels/inputs/lecture.mp4"
    m = _manifest(mac_path, sha, [_reel("r01", 0.0, 5.0)])

    render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    src_in_cmd = _val_after(fake_ffmpeg[0], "-i")
    assert src_in_cmd == str(inputs / "real.mp4")
    assert mac_path not in fake_ffmpeg[0]


def test_render_cut_missing_source_raises(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    m = _manifest("lecture.mp4", "e" * 64, [_reel("r01", 0.0, 5.0)])
    with pytest.raises(RenderError):
        render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)


def test_render_cut_ffmpeg_failure_raises(tmp_path, render_cfg, monkeypatch):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "lecture.mp4", b"ffmpeg-fails-video")
    monkeypatch.setattr(render.shutil, "which", lambda b: "/fake/bin/ffmpeg")

    class _FailProc:
        def __init__(self, cmd, **kwargs):
            self.returncode = 1
            self.stdout = iter([])
            self.stderr = iter(["boom\n"])

        def wait(self):
            return 1

    monkeypatch.setattr(render.subprocess, "Popen", _FailProc)
    m = _manifest("lecture.mp4", sha, [_reel("r01", 0.0, 5.0)])
    with pytest.raises(RenderError) as e:
        render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)
    assert "ffmpeg" in str(e.value).lower()


def test_render_cut_ffmpeg_not_found_raises(tmp_path, render_cfg, monkeypatch):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "lecture.mp4", b"no-ffmpeg-video")
    monkeypatch.setattr(render.shutil, "which", lambda b: None)
    m = _manifest("lecture.mp4", sha, [_reel("r01", 0.0, 5.0)])
    with pytest.raises(RenderError) as e:
        render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)
    assert "ffmpeg" in str(e.value).lower()


# ------------------------------------------------------------ render_crop (R1b)

def _crop_setup() -> SetupProfile:
    # Профиль из R1b: вертикальный кроп 9:16 из 4K-кадра.
    return SetupProfile(
        setup_id="pxl_test",
        crop=Crop(x=1240, y=0, w=1215, h=2160),
        scale=[1080, 1920],
        frame=[3840, 2160],
    )


def test_crop_cmd_has_crop_and_scale_from_setup(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"crop-from-setup-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    # crop=w:h:x:y из setup.crop, затем scale=1080:1920 из setup.scale.
    assert vf == "crop=1215:2160:1240:0,scale=1080:1920"


def test_crop_numbers_come_from_setup_not_reel(tmp_path, render_cfg, fake_ffmpeg):
    # Разные reel'ы — один и тот же кроп (он на уровне setup манифеста, не reel).
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"setup-level-crop-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 0.0, 5.0), _reel("r02", 99.0, 130.0)],
                  setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    vf0 = _val_after(fake_ffmpeg[0], "-vf")
    vf1 = _val_after(fake_ffmpeg[1], "-vf")
    assert vf0 == vf1 == "crop=1215:2160:1240:0,scale=1080:1920"
    # окно реза по-прежнему разное у разных reel — кроп его не подменяет
    assert _val_after(fake_ffmpeg[1], "-ss") == "99.000"


def test_crop_output_is_vertical_id_mp4_not_raw(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"vertical-output-video")
    out_dir = tmp_path / "out"
    m = _manifest("v.mp4", sha, [_reel("r01", 0.0, 5.0), _reel("r02", 10.0, 15.0)],
                  setup=_crop_setup())

    outputs = render_crop(m, inputs_dir=inputs, out_dir=out_dir, render_cfg=render_cfg)

    # вертикальный выход <id>.mp4 — отдельно от <id>_raw.mp4 из R1a
    assert outputs == [out_dir / "r01.mp4", out_dir / "r02.mp4"]
    assert all(isinstance(p, Path) and "_raw" not in p.name for p in outputs)
    assert fake_ffmpeg[0][-1] == str(out_dir / "r01.mp4")


def test_crop_cuts_window_and_passes_encoder(tmp_path, render_cfg, fake_ffmpeg, monkeypatch):
    # Кроп-сегмент тоже режет окно start→end и слушает тот же рантайм-энкодер.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"crop-window-encoder-video")
    monkeypatch.setenv("RENDER_ENCODER", "h264_amf")
    m = _manifest("v.mp4", sha, [_reel("r01", 284.5, 341.5)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    cmd = fake_ffmpeg[0]
    assert _val_after(cmd, "-ss") == "284.500"
    assert _val_after(cmd, "-t") == "57.000"
    assert _val_after(cmd, "-c:v") == "h264_amf"


def test_crop_resolves_local_source_ignoring_mac_path(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "real.mp4", b"crop-resolve-video")
    mac_path = "/Users/danny/Загрузки/Саша/PXL_20260621_122006193.mp4"
    m = _manifest(mac_path, sha, [_reel("r01", 0.0, 5.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    assert _val_after(fake_ffmpeg[0], "-i") == str(inputs / "real.mp4")
    assert mac_path not in fake_ffmpeg[0]


def test_crop_burns_subtitles_ass_after_crop_scale(tmp_path, render_cfg, fake_ffmpeg):
    # R3: при subtitles_cfg + словах у reel — ass-фильтр ПОСЛЕ crop/scale
    subs_cfg = load_subtitles_config(ROOT / "config" / "subtitles.yaml")
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"subs-video")
    out_dir = tmp_path / "out"
    reel = _reel("r01", 10.0, 40.0)
    reel.subtitles = [Word(word="привет", t0=11.0, t1=11.4), Word(word="мир", t0=11.5, t1=12.0)]
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=out_dir, render_cfg=render_cfg, subtitles_cfg=subs_cfg)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    assert "ass=" in vf
    assert vf.index("ass=") > vf.index("scale=")      # субтитры в координатах финального кадра
    # .ass убирается из tempdir после рендера — в out_dir его быть не должно
    assert not (out_dir / "r01.ass").exists()


def test_crop_no_subtitles_when_cfg_absent(tmp_path, render_cfg, fake_ffmpeg):
    # без subtitles_cfg — vf только crop/scale (R1a/R1b не задеты)
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"no-subs-video")
    reel = _reel("r01", 10.0, 40.0)
    reel.subtitles = [Word(word="привет", t0=11.0, t1=11.4)]
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    assert "ass=" not in _val_after(fake_ffmpeg[0], "-vf")


def test_crop_emits_title_description_sidecar_txt(tmp_path, render_cfg, fake_ffmpeg):
    # Текст публикации (title/description) кладётся РЯДОМ с клипом, НЕ вшивается в видео.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"sidecar-text-video")
    out_dir = tmp_path / "out"
    reel = _reel("r01", 10.0, 40.0, title="ЗА ТРАВМОЙ скрыт ДАР 🫀…",
                 description="Контринтуитивный момент 🫀 #травма #психология")
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=out_dir, render_cfg=render_cfg)

    txt = out_dir / "r01.txt"
    assert txt.exists()
    content = txt.read_text(encoding="utf-8")
    assert "ЗА ТРАВМОЙ скрыт ДАР 🫀…" in content
    assert "#травма #психология" in content


def test_crop_sidecar_txt_format_is_title_blankline_description_utf8(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"sidecar-format-video")
    out_dir = tmp_path / "out"
    reel = _reel("r01", 0.0, 5.0, title="Заголовок", description="Описание #тег")
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=out_dir, render_cfg=render_cfg)

    # формат: заголовок, пустая строка, описание; utf-8 (декодируем явно из байтов)
    raw = (out_dir / "r01.txt").read_bytes()
    assert raw.decode("utf-8") == "Заголовок\n\nОписание #тег\n"


def test_crop_sidecar_txt_per_reel(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"sidecar-per-reel-video")
    out_dir = tmp_path / "out"
    m = _manifest("v.mp4", sha, [
        _reel("r01", 0.0, 5.0, title="Первый", description="Опис 1"),
        _reel("r02", 10.0, 15.0, title="Второй", description="Опис 2"),
    ], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=out_dir, render_cfg=render_cfg)

    assert (out_dir / "r01.txt").read_text(encoding="utf-8").startswith("Первый\n\nОпис 1")
    assert (out_dir / "r02.txt").read_text(encoding="utf-8").startswith("Второй\n\nОпис 2")


# ------------------------------------------------- Windows: subprocess encoding

def test_render_popen_uses_utf8_encoding(tmp_path, render_cfg, monkeypatch):
    """subprocess.Popen должен получать encoding='utf-8' — иначе Windows cp1251 ломает stderr."""
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"bytes")
    kwargs_seen = []

    class _FakeProc:
        def __init__(self, cmd, **kwargs):
            kwargs_seen.append(kwargs)
            self.returncode = 0
            self.stdout = iter([])
            self.stderr = iter([])

        def wait(self):
            return 0

    monkeypatch.setattr(render.shutil, "which", lambda b: "/fake/ffmpeg")
    monkeypatch.setattr(render.subprocess, "Popen", _FakeProc)
    m = _manifest("v.mp4", sha, [_reel("r01", 0.0, 30.0)])
    render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    assert kwargs_seen, "subprocess.Popen не вызван"
    assert kwargs_seen[0].get("encoding") == "utf-8", (
        f"subprocess.Popen вызван без encoding='utf-8': {kwargs_seen[0]}"
    )
