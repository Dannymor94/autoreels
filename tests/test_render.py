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
)
from autoreels.core.config import load_render_config
from autoreels.local import render
from autoreels.local.render import (
    RenderError,
    build_cut_cmd,
    resolve_source,
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


def _reel(rid: str, start: float, end: float) -> Reel:
    return Reel(
        id=rid, start=start, end=end, score=80,
        hook="h", title="t", description="d", reason="r", topic="x",
    )


def _make_source(inputs_dir: Path, name: str, content: bytes) -> str:
    """Создаёт фейковый видеофайл в inputs/, возвращает его sha256."""
    from autoreels.core import state
    inputs_dir.mkdir(parents=True, exist_ok=True)
    p = inputs_dir / name
    p.write_bytes(content)
    return state.file_sha256(p)


def _manifest(source: str, sha: str, reels: list[Reel]) -> Manifest:
    return Manifest(
        source=source, source_sha256=sha, duration_preset="shorts",
        setup=_setup(), run_key="rk1", reels=reels,
    )


def _val_after(cmd: list[str], flag: str) -> str:
    """Значение аргумента, идущего сразу за `flag` в команде."""
    i = cmd.index(flag)
    return cmd[i + 1]


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
    """Мокает ffmpeg: shutil.which находит бинарь, subprocess.run пишет вызовы и 'успешен'."""
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(render.shutil, "which", lambda b: "/fake/bin/ffmpeg")
    monkeypatch.setattr(render.subprocess, "run", fake_run)
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
    monkeypatch.setattr(
        render.subprocess, "run",
        lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"),
    )
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
