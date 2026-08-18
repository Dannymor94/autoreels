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
    probe_encoder,
    resolve_source,
    render_crop,
    render_cut,
)

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------ probe_encoder: доступность энкодера на GPU

class _RC:
    def __init__(self, code):
        self.returncode = code


def test_probe_encoder_true_on_success():
    """rc 0 пробного encode → энкодер доступен."""
    seen = {}
    ok = probe_encoder("av1_amf", ffmpeg="ffmpeg",
                       run=lambda cmd: seen.update(cmd=cmd) or _RC(0))
    assert ok is True
    assert "av1_amf" in seen["cmd"] and "-frames:v" in seen["cmd"]   # тестовый encode 1 кадра
    assert "null" in seen["cmd"]                                      # вывод в никуда


def test_probe_encoder_false_on_nonzero():
    """rc != 0 (AMF CreateComponent failed) → недоступен."""
    assert probe_encoder("av1_amf", run=lambda cmd: _RC(1)) is False


def test_probe_encoder_false_on_exception():
    """ffmpeg не найден / таймаут → недоступен (не падаем)."""
    def boom(cmd):
        raise OSError("no ffmpeg")
    assert probe_encoder("av1_amf", run=boom) is False
RENDER_YAML = ROOT / "config" / "render.yaml"


# Изолируем тесты от машинного config/render.local.yaml (напр. profile: av1, выставленный
# через меню) — тестируем ВЕРСИОНИРУЕМЫЙ render.yaml, а не локальные переопределения машины.
_NO_LOCAL = Path("/nonexistent/render.local.yaml")


@pytest.fixture
def render_cfg():
    return load_render_config(RENDER_YAML, local_path=_NO_LOCAL)


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


def _make_source(inputs_dir: Path, name: str, content: bytes, *,
                 scheme: str = "partial-p1") -> str:
    """Создаёт фейковый видеофайл в inputs/, возвращает его хэш по указанной схеме."""
    from autoreels.core import state
    inputs_dir.mkdir(parents=True, exist_ok=True)
    p = inputs_dir / name
    p.write_bytes(content)
    return state.file_sha256_partial(p) if scheme == "partial-p1" else state.file_sha256(p)


def _manifest(source: str, sha: str, reels: list[Reel], setup: SetupProfile | None = None,
              scheme: str = "partial-p1") -> Manifest:
    return Manifest(
        source=source, source_sha256=sha, source_hash_scheme=scheme,
        duration_preset="shorts", setup=setup or _setup(), run_key="rk1", reels=reels,
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


# ------------------------------------ соцсеть-оптимальный размер (bitrate/faststart/format)

def test_cut_cmd_has_target_bitrate_and_vbv_cap():
    """Целевой битрейт (-b:v) + VBV-потолок (-maxrate/-bufsize) → предсказуемый размер файла,
    один проход, без HandBrake. bufsize = 2× битрейта."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 30.0, Path("/out/r01.mp4"),
        codec="libx264", preset="medium", video_bitrate="7M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
    )
    assert _val_after(cmd, "-b:v") == "7M"
    assert _val_after(cmd, "-maxrate") == "7M"
    assert _val_after(cmd, "-bufsize") == "14M"      # 2× для VBV


def test_cut_cmd_amf_quality_flag():
    """AMF-кодек + quality='quality' → -quality quality в команде (режим кодера против мыла)."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/v.mp4"), 0.0, 30.0, Path("/r.mp4"),
        codec="hevc_amf", preset="medium", video_bitrate="5M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k", quality="quality",
    )
    assert _val_after(cmd, "-quality") == "quality"
    assert _val_after(cmd, "-b:v") == "5M"               # без cqp — целевой битрейт остаётся


def test_cut_cmd_amf_cqp_replaces_bitrate():
    """AMF + rate_control='cqp' + qp=18 → -rc cqp -qp_i 18 -qp_p 20 ВМЕСТО -b:v (качество)."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/v.mp4"), 0.0, 30.0, Path("/r.mp4"),
        codec="hevc_amf", preset="medium", video_bitrate="12M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
        quality="quality", rate_control="cqp", qp=18,
    )
    assert _val_after(cmd, "-rc") == "cqp"
    assert _val_after(cmd, "-qp_i") == "18" and _val_after(cmd, "-qp_p") == "20"
    assert "-b:v" not in cmd                              # cqp вместо целевого битрейта


def test_cut_cmd_software_codec_ignores_amf_quality():
    """Софтверный libx265 игнорирует AMF-флаги quality/cqp — остаётся целевой битрейт."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/v.mp4"), 0.0, 30.0, Path("/r.mp4"),
        codec="libx265", preset="medium", video_bitrate="5M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
        quality="quality", rate_control="cqp", qp=18,
    )
    assert "-quality" not in cmd and "-rc" not in cmd     # AMF-флаги не для софта
    assert _val_after(cmd, "-b:v") == "5M"                # битрейт-режим
    assert _val_after(cmd, "-preset") == "medium"         # у софта свой preset


def test_cut_cmd_has_pix_fmt_yuv420p():
    """yuv420p — универсальная цветовая субдискретизация: соцсети/плееры не примут yuv444."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 30.0, Path("/out/r01.mp4"),
        codec="libx264", preset="medium", video_bitrate="7M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
    )
    assert _val_after(cmd, "-pix_fmt") == "yuv420p"


def test_cut_cmd_has_faststart_before_output():
    """-movflags +faststart (moov atom в начало): часть соцсетей не примет файл без него.
    Флаг — опция мукса, идёт ДО имени выходного файла."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 30.0, Path("/out/r01.mp4"),
        codec="libx264", preset="medium", video_bitrate="7M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
    )
    assert _val_after(cmd, "-movflags") == "+faststart"
    assert cmd.index("-movflags") < cmd.index(str(Path("/out/r01.mp4")))
    assert cmd[-1] == str(Path("/out/r01.mp4"))


def test_cut_cmd_faststart_off_omits_flag():
    """faststart=False → флага нет (управляемо из конфига)."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 30.0, Path("/out/r01.mp4"),
        codec="libx264", preset="medium", video_bitrate="7M", pix_fmt="yuv420p",
        faststart=False, audio_codec="aac", audio_bitrate="128k",
    )
    assert "-movflags" not in cmd


def test_cut_cmd_hevc_gets_hvc1_tag():
    """HEVC в mp4 → тег hvc1 (иначе Apple/Safari/часть соцсетей не проигрывают)."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 30.0, Path("/out/r01.mp4"),
        codec="hevc_amf", preset="balanced", video_bitrate="5M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
    )
    assert _val_after(cmd, "-tag:v") == "hvc1"


def test_cut_cmd_libx265_also_gets_hvc1_tag():
    """Тег hvc1 навешивается на HEVC любого бэкенда (софтверный libx265 тоже)."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 30.0, Path("/out/r01.mp4"),
        codec="libx265", preset="medium", video_bitrate="5M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
    )
    assert _val_after(cmd, "-tag:v") == "hvc1"


def test_cut_cmd_h264_has_no_hvc1_tag():
    """H.264 не нуждается в hvc1 — тег только у HEVC."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 30.0, Path("/out/r01.mp4"),
        codec="h264_amf", preset="balanced", video_bitrate="7M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
    )
    assert "-tag:v" not in cmd


def test_cut_cmd_amf_gets_bitrate_not_crf():
    """Аппаратный AMF: целевой битрейт применяется (это и есть фикс огромных файлов —
    AMF по умолчанию без rate-control раздувает размер), а libx264-specific -crf/-preset — нет."""
    cmd = build_cut_cmd(
        "ffmpeg", Path("/inputs/v.mp4"), 0.0, 30.0, Path("/out/r01.mp4"),
        codec="h264_amf", preset="balanced", video_bitrate="7M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
    )
    assert _val_after(cmd, "-b:v") == "7M"           # rate-control есть и на AMF
    assert _val_after(cmd, "-maxrate") == "7M"
    assert "-crf" not in cmd                          # софтверный флаг не лезет в AMF
    assert "-preset" not in cmd


# ------------------------------------ профили битрейта (config Encoder)

def _enc(**kw):
    """Encoder с профилями по умолчанию (h264/hevc/av1), переопределяемыми через kw."""
    from autoreels.core.config import Encoder
    return Encoder(preset="medium", cq=23, **kw)


def test_encoder_active_profile_resolves_codec_and_bitrate():
    enc = _enc(profile="h264")
    assert enc.codec == "h264_amf"
    assert enc.video_bitrate == "7M"


def test_encoder_profile_switch_changes_codec_and_bitrate():
    # hevc-профиль → другой кодек И другой (меньший) битрейт: компактнее при том же качестве.
    enc = _enc(profile="hevc")
    assert enc.codec == "hevc_amf"
    assert enc.video_bitrate == "5M"


def test_encoder_av1_profile():
    enc = _enc(profile="av1")
    assert enc.codec == "av1_amf"
    assert enc.video_bitrate == "4M"


def test_load_render_config_unknown_profile_raises(tmp_path):
    """Опечатка в profile → ConfigError на загрузке (fail-fast), не молча."""
    from autoreels.core.config import ConfigError, load_render_config
    import yaml
    base = yaml.safe_load(RENDER_YAML.read_text(encoding="utf-8"))
    base["encoder"]["profile"] = "no_such_profile"
    p = tmp_path / "render.yaml"
    p.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(ConfigError, match="профиль"):
        load_render_config(p)


def test_real_render_config_defaults_are_social_optimal():
    """Дефолтный config/render.yaml даёт соцсеть-оптимальные значения из коробки."""
    cfg = load_render_config(RENDER_YAML, local_path=_NO_LOCAL)   # без машинного override
    assert cfg.encoder.pix_fmt == "yuv420p"
    assert cfg.encoder.faststart is True
    assert cfg.audio.bitrate == "128k"               # aac 128k — достаточно для соцсетей
    assert cfg.encoder.profile == "hevc"             # дефолт — компактный hevc
    # активный профиль резолвится в разумный битрейт 4–8 Мбит/с
    bv = cfg.encoder.video_bitrate
    assert bv.endswith("M") and 4 <= int(bv[:-1]) <= 8
    # базовые + hq + софтверный профили присутствуют
    assert {"h264", "hevc", "av1", "hevc_hq", "h264_hq", "hevc_sw"} <= set(cfg.encoder.profiles)
    # дефолтный hevc несёт AMF quality-режим (против мыла на равном битрейте)
    assert cfg.encoder.profiles["hevc"].quality == "quality"
    # обработка звука: нормализация -14 LUFS включена, шумоподавление и фейд — выключены
    ap = cfg.audio_processing
    assert ap.loudnorm_enabled is True and ap.target_lufs == -14.0
    assert ap.denoise_enabled is False and ap.fade_enabled is False
    # зум выключен по умолчанию; схема hook, наезд 8%
    assert cfg.zoom.enabled is False and cfg.zoom.scheme == "hook" and cfg.zoom.percent == 8.0


# ------------------------------------ оценка размера выходного файла

def test_estimate_size_mb_30s_clip_in_social_range():
    """30-сек клип на 7 Мбит/с видео + 128k аудио ≈ 26–28 МБ — компактно, не сотни МБ."""
    from autoreels.local.render import estimate_size_mb
    mb = estimate_size_mb(video_bitrate="7M", audio_bitrate="128k", duration_sec=30.0)
    assert 20 <= mb <= 35, f"ожидалось 20–35 МБ, получено {mb:.1f}"


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


def test_resolve_source_uses_partial_hash_when_scheme_is_partial(tmp_path):
    """hash_scheme='partial-p1' → resolve_source хэширует файл через file_sha256_partial."""
    from autoreels.core import state as st
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    p = inputs / "v.mp4"
    p.write_bytes(b"video-content-partial")
    partial_sha = st.file_sha256_partial(p)

    m = Manifest(
        source="v.mp4", source_sha256=partial_sha, source_hash_scheme="partial-p1",
        duration_preset="shorts", setup=_setup(), run_key="rk", reels=[],
    )
    assert resolve_source(m, inputs) == p


def test_resolve_source_uses_full_hash_when_scheme_is_full(tmp_path):
    """hash_scheme='full' (или отсутствует) → обратная совместимость: полный sha256."""
    from autoreels.core import state as st
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    p = inputs / "v.mp4"
    p.write_bytes(b"video-content-full")
    full_sha = st.file_sha256(p)

    m = Manifest(
        source="v.mp4", source_sha256=full_sha, source_hash_scheme="full",
        duration_preset="shorts", setup=_setup(), run_key="rk", reels=[],
    )
    assert resolve_source(m, inputs) == p


def test_manifest_model_default_scheme_is_full_for_compat():
    """Дефолт модели 'full' — чтобы старые JSON без поля читались корректно."""
    m = Manifest(
        source="v.mp4", source_sha256="a" * 64, duration_preset="shorts",
        setup=_setup(), run_key="rk", reels=[],
    )
    assert m.source_hash_scheme == "full"


def test_new_manifests_from_assemble_use_partial_scheme():
    """_assemble_manifest явно ставит partial-p1 — новые манифесты не зависят от дефолта модели."""
    import autoreels.__main__ as cli
    from pathlib import Path
    m = cli._assemble_manifest(
        "v.mp4", [], sha="x" * 64, setup=_setup(), duration_preset="shorts"
    )
    assert m.source_hash_scheme == "partial-p1"


def test_manifest_hash_scheme_survives_json_roundtrip(tmp_path):
    m = Manifest(
        source="v.mp4", source_sha256="b" * 64, source_hash_scheme="partial-p1",
        duration_preset="shorts", setup=_setup(), run_key="rk", reels=[],
    )
    loaded = Manifest.model_validate_json(m.model_dump_json())
    assert loaded.source_hash_scheme == "partial-p1"


def test_old_manifest_without_hash_scheme_treated_as_full(tmp_path):
    """Старые манифесты не имеют hash_scheme → трактуем как 'full' (обратная совместимость)."""
    # Симулируем старый JSON без поля source_hash_scheme
    old_json = """{
        "source": "v.mp4",
        "source_sha256": "aabbcc0000000000000000000000000000000000000000000000000000000000",
        "duration_preset": "shorts",
        "setup": {"setup_id": "s", "crop": {"x":0,"y":0,"w":1080,"h":1920},
                  "scale":[1080,1920],"frame":[3840,2160]},
        "run_key": "rk",
        "status": "pending",
        "reels": []
    }"""
    m = Manifest.model_validate_json(old_json)
    assert m.source_hash_scheme == "full"


# ----------------------------------------------------------- render_cut (моки)

@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Мокает ffmpeg: shutil.which находит бинарь, subprocess.Popen пишет вызовы и 'успешен'."""
    calls = []

    class _FakeProc:
        def __init__(self, cmd, **kwargs):
            if "ffprobe" not in str(cmd[0]):   # диагностический ffprobe (crop-space) не считаем
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


def test_render_cut_default_profile_applies_hevc_codec_and_bitrate(tmp_path, render_cfg, fake_ffmpeg):
    # Дефолтный профиль конфига (hevc) → hevc_amf + 5M битрейт + hvc1 в команде.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"default-hevc-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 0.0, 30.0)])

    render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    cmd = fake_ffmpeg[0]
    assert _val_after(cmd, "-c:v") == "hevc_amf"
    assert _val_after(cmd, "-b:v") == "5M"
    assert _val_after(cmd, "-tag:v") == "hvc1"


def test_render_cut_profile_arg_switches_codec_and_bitrate(tmp_path, render_cfg, fake_ffmpeg):
    # --profile h264 → h264_amf + 7M, без hvc1.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"profile-switch-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 0.0, 30.0)])

    render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg, profile="h264")

    cmd = fake_ffmpeg[0]
    assert _val_after(cmd, "-c:v") == "h264_amf"
    assert _val_after(cmd, "-b:v") == "7M"
    assert "-tag:v" not in cmd


def test_render_cut_profile_from_env(tmp_path, render_cfg, fake_ffmpeg, monkeypatch):
    # RENDER_PROFILE=av1 → av1_amf + 4M.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"env-profile-video")
    monkeypatch.setenv("RENDER_PROFILE", "av1")
    m = _manifest("v.mp4", sha, [_reel("r01", 0.0, 30.0)])

    render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    cmd = fake_ffmpeg[0]
    assert _val_after(cmd, "-c:v") == "av1_amf"
    assert _val_after(cmd, "-b:v") == "4M"


def test_render_cut_encoder_overrides_codec_keeps_profile_bitrate(tmp_path, render_cfg, fake_ffmpeg):
    # Mac-дев: --encoder libx265 подменяет кодек, но битрейт активного профиля (hevc→5M) остаётся.
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"encoder-override-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 0.0, 30.0)])

    render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out",
               render_cfg=render_cfg, encoder="libx265")

    cmd = fake_ffmpeg[0]
    assert _val_after(cmd, "-c:v") == "libx265"
    assert _val_after(cmd, "-b:v") == "5M"       # битрейт из профиля hevc, не сброшен
    assert _val_after(cmd, "-tag:v") == "hvc1"   # libx265 — HEVC → тег есть


def test_render_cut_unknown_profile_raises(tmp_path, render_cfg, fake_ffmpeg):
    from autoreels.core.config import ConfigError
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"bad-profile-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 0.0, 30.0)])
    with pytest.raises(ConfigError, match="профиль"):
        render_cut(m, inputs_dir=inputs, out_dir=tmp_path / "out",
                   render_cfg=render_cfg, profile="nope")


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


# ------------------------------------------------------------ эффект зума (hook, качество из источника)

from autoreels.core.config import Zoom
from autoreels.local.render import _crop_vf, _zoom_vf


def test_zoom_disabled_gives_plain_scale():
    # выкл (дефолт) → обычный scale, без zoompan
    assert _zoom_vf([1080, 1920], Zoom()) == ""
    vf = _crop_vf(_crop_setup(), Zoom())
    assert vf == "crop=1215:2160:1240:0,scale=1080:1920"
    assert "zoompan" not in vf


def test_zoom_scheme_none_gives_plain_scale():
    assert _zoom_vf([1080, 1920], Zoom(enabled=True, scheme="none")) == ""


def test_zoom_enabled_replaces_scale_with_zoompan():
    # зум ВМЕСТО scale (не поверх): выход 1080×1920, вход zoompan — полноразмерный регион
    vf = _crop_vf(_crop_setup(), Zoom(enabled=True))
    assert "zoompan=" in vf and "scale=1080:1920" not in vf
    assert "s=1080x1920" in vf                                # zoompan сам даёт целевой размер
    assert vf.startswith("crop=1215:2160:1240:0,zoompan=")    # crop полноразмерного региона ДО zoompan


def test_zoom_is_dynamic_crop_not_upscale_of_finished_frame():
    # качество: zoompan идёт СРАЗУ после crop полноразмерного региона (нет промежуточного
    # scale в 1080, который бы потом апскейлился) — зум сэмплит исходное разрешение
    vf = _crop_vf(_crop_setup(), Zoom(enabled=True, percent=8))
    assert vf.index("crop=") < vf.index("zoompan=")
    assert "scale=" not in vf                                 # единственный ресемплинг — внутри zoompan


def test_zoom_params_from_config_in_expression():
    # параметры (percent/duration/hook/fps) попадают в выражение zoompan
    vf = _zoom_vf([1080, 1920], Zoom(enabled=True, percent=12, duration=0.5,
                                     hook_seconds=3.0, fps=25))
    assert "1+0.12*" in vf                                    # percent 12 → 0.12
    assert "ot/0.5" in vf                                     # duration 0.5
    assert "(3-ot)/0.5" in vf                                 # hook_seconds 3.0
    assert "fps=25" in vf


def test_zoom_zooms_into_center():
    vf = _zoom_vf([1080, 1920], Zoom(enabled=True))
    assert "x='iw/2-(iw/zoom/2)'" in vf and "y='ih/2-(ih/zoom/2)'" in vf


def test_render_zoom_flag_adds_zoompan_to_command(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"zoom-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg, zoom=True)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    assert "zoompan=" in vf


def test_render_zoom_off_by_default(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"no-zoom-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    assert "zoompan" not in vf and "scale=1080:1920" in vf


# ------------------------------------------------------------ обработка звука (loudnorm/denoise/fade)

from autoreels.core.config import AudioProcessing
from autoreels.local.render import _audio_filter_chain, _video_fade_filter


def test_audio_chain_default_is_loudnorm_only():
    # дефолт: только нормализация громкости к -14 LUFS
    af = _audio_filter_chain(AudioProcessing(), 30.0)
    assert af == "loudnorm=I=-14:TP=-1.5:LRA=11"


def test_audio_chain_empty_when_all_disabled():
    ap = AudioProcessing(loudnorm_enabled=False, denoise_enabled=False, fade_enabled=False)
    assert _audio_filter_chain(ap, 30.0) == ""


def test_audio_chain_denoise_before_loudnorm():
    ap = AudioProcessing(denoise_enabled=True, denoise_strength=10)
    af = _audio_filter_chain(ap, 30.0)
    assert af == "afftdn=nr=10,loudnorm=I=-14:TP=-1.5:LRA=11"
    assert af.index("afftdn") < af.index("loudnorm")


def test_audio_chain_fade_last_and_out_start_from_duration():
    ap = AudioProcessing(fade_enabled=True, fade_duration=0.25)
    af = _audio_filter_chain(ap, 30.0)
    # порядок: loudnorm → afade in → afade out; out стартует в конце минус длительность фейда
    assert af == "loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.25,afade=t=out:st=29.75:d=0.25"


def test_video_fade_off_by_default():
    assert _video_fade_filter(AudioProcessing(), 30.0) == ""


def test_video_fade_matches_audio_fade_timing():
    ap = AudioProcessing(fade_enabled=True, fade_duration=0.3)
    assert _video_fade_filter(ap, 20.0) == "fade=t=in:st=0:d=0.3,fade=t=out:st=19.7:d=0.3"


def test_render_default_adds_loudnorm_to_command(tmp_path, render_cfg, fake_ffmpeg):
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"loudnorm-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    af = _val_after(fake_ffmpeg[0], "-af")
    assert "loudnorm=I=-14" in af


def test_render_loudnorm_disabled_by_config_omits_af(tmp_path, render_cfg, fake_ffmpeg):
    render_cfg.audio_processing.loudnorm_enabled = False
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"no-loudnorm-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    assert "-af" not in fake_ffmpeg[0]


def test_render_denoise_flag_adds_afftdn(tmp_path, render_cfg, fake_ffmpeg):
    render_cfg.audio_processing.denoise_enabled = True
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"denoise-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    af = _val_after(fake_ffmpeg[0], "-af")
    assert "afftdn" in af and af.index("afftdn") < af.index("loudnorm")


def test_render_fade_video_appended_after_subtitles(tmp_path, render_cfg, fake_ffmpeg):
    # фейд-видео последним в vf (после ass) — фейдит готовый кадр; таймкод из длительности клипа
    subs_cfg = load_subtitles_config(ROOT / "config" / "subtitles.yaml")
    render_cfg.audio_processing.fade_enabled = True
    render_cfg.audio_processing.fade_duration = 0.25
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"fade-video")
    reel = _reel("r01", 10.0, 40.0)         # длительность 30с
    reel.subtitles = [Word(word="привет", t0=11.0, t1=11.4)]
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg,
                subtitles_cfg=subs_cfg)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    af = _val_after(fake_ffmpeg[0], "-af")
    assert vf.index("ass=") < vf.index("fade=t=in")           # фейд после субтитров
    assert "fade=t=out:st=29.75" in vf                        # 30 - 0.25 (не конфликтует с padding)
    assert "afade=t=out:st=29.75" in af                       # аудиофейд синхронен видео


# ------------------------------------------------------------ выравнивание горизонта (rotate)

def _crop_setup_rot(deg: float) -> SetupProfile:
    return SetupProfile(
        setup_id="tilt", crop=Crop(x=1240, y=0, w=1215, h=2160),
        scale=[1080, 1920], frame=[3840, 2160], rotation_deg=deg,
    )


def test_crop_rotation_zero_adds_no_rotate_filter(tmp_path, render_cfg, fake_ffmpeg):
    # дефолт 0° → фильтр rotate НЕ добавляется (команда прежняя)
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"rot-zero-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup_rot(0.0))

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    assert "rotate=" not in vf
    assert vf == "crop=1215:2160:1240:0,scale=1080:1920"


def test_crop_rotation_prepends_rotate_before_crop(tmp_path, render_cfg, fake_ffmpeg):
    # угол → rotate ПЕРЕД crop (иначе кроп берёт пустые углы); значение в радианах
    import math
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"rot-set-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup_rot(3.0))

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    rad = math.radians(3.0)
    assert vf == f"rotate={rad:.6f},crop=1215:2160:1240:0,scale=1080:1920"
    assert vf.index("rotate=") < vf.index("crop=") < vf.index("scale=")


def test_crop_rotation_then_palette_then_subtitles_order(tmp_path, render_cfg, fake_ffmpeg):
    # полная цепочка: rotate → crop → scale → eq (палитра) → ass (субтитры)
    subs_cfg = load_subtitles_config(ROOT / "config" / "subtitles.yaml")
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"rot-palette-subs-video")
    reel = _reel("r01", 10.0, 40.0)
    reel.subtitles = [Word(word="привет", t0=11.0, t1=11.4)]
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup_rot(2.5))

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg,
                palette="vivid", subtitles_cfg=subs_cfg)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    assert vf.index("rotate=") < vf.index("crop=") < vf.index("scale=") \
        < vf.index("eq=") < vf.index("ass=")


# ------------------------------------------------------------ палитра / цветокоррекция

from autoreels.core.config import Palette, PaletteEq, PaletteUnsharp
from autoreels.local.render import palette_filter


def test_palette_neutral_produces_empty_filter():
    # neutral = все дефолты → пустая строка (команда рендера не меняется)
    assert palette_filter(Palette()) == ""


def test_palette_eq_only_non_neutral_terms():
    # eq выдаёт только НЕ-нейтральные термы, порядок фиксирован contrast→brightness→sat→gamma
    pal = Palette(eq=PaletteEq(saturation=1.15, contrast=1.10))
    assert palette_filter(pal) == "eq=contrast=1.1:saturation=1.15"


def test_palette_unsharp_off_by_default_on_when_enabled():
    off = Palette(unsharp=PaletteUnsharp(enabled=False, luma_amount=0.6))
    assert "unsharp" not in palette_filter(off)
    on = Palette(unsharp=PaletteUnsharp(enabled=True, luma_amount=0.6))
    assert palette_filter(on) == "unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=0.6"


def test_palette_colortemperature_appended_last():
    pal = Palette(eq=PaletteEq(contrast=0.95), colortemperature=5400)
    assert palette_filter(pal) == "eq=contrast=0.95,colortemperature=temperature=5400"


def test_palette_filter_part_order_eq_unsharp_temp():
    # порядок частей: eq → unsharp → colortemperature
    pal = Palette(
        eq=PaletteEq(contrast=1.05),
        unsharp=PaletteUnsharp(enabled=True, luma_amount=0.6),
        colortemperature=5400,
    )
    f = palette_filter(pal)
    assert f.index("eq=") < f.index("unsharp=") < f.index("colortemperature=")


def test_render_config_default_palette_is_neutral():
    cfg = load_render_config(RENDER_YAML, local_path=_NO_LOCAL)
    assert cfg.palette == "neutral"
    assert set(cfg.palettes) >= {"neutral", "vivid", "soft", "sharp"}
    assert palette_filter(cfg.palettes["neutral"]) == ""
    assert cfg.active_palette is cfg.palettes["neutral"]


def test_render_config_vivid_preset_values():
    cfg = load_render_config(RENDER_YAML, local_path=_NO_LOCAL)
    assert palette_filter(cfg.palettes["vivid"]) == "eq=contrast=1.1:saturation=1.15"


def test_crop_default_neutral_palette_leaves_vf_unchanged(tmp_path, render_cfg, fake_ffmpeg):
    # дефолт neutral → vf ровно crop,scale, без eq/unsharp/colortemperature
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"neutral-palette-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    assert vf == "crop=1215:2160:1240:0,scale=1080:1920"
    assert "eq=" not in vf and "unsharp=" not in vf


def test_crop_palette_arg_inserts_eq_between_scale_and_end(tmp_path, render_cfg, fake_ffmpeg):
    # --palette vivid → eq после scale; порядок crop→scale→eq
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"vivid-palette-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg,
                palette="vivid")

    vf = _val_after(fake_ffmpeg[0], "-vf")
    assert vf == "crop=1215:2160:1240:0,scale=1080:1920,eq=contrast=1.1:saturation=1.15"
    assert vf.index("eq=") > vf.index("scale=")


def test_crop_palette_from_config_when_no_arg(tmp_path, render_cfg, fake_ffmpeg):
    # палитра из конфига (render_cfg.palette), без явного arg
    render_cfg.palette = "vivid"
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"config-palette-video")
    m = _manifest("v.mp4", sha, [_reel("r01", 10.0, 40.0)], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg)

    assert "eq=contrast=1.1:saturation=1.15" in _val_after(fake_ffmpeg[0], "-vf")


def test_crop_palette_before_subtitles_ass(tmp_path, render_cfg, fake_ffmpeg):
    # порядок цепочки: crop → scale → eq (палитра) → ass (субтитры чистые, поверх цветокора)
    subs_cfg = load_subtitles_config(ROOT / "config" / "subtitles.yaml")
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"palette-then-subs-video")
    reel = _reel("r01", 10.0, 40.0)
    reel.subtitles = [Word(word="привет", t0=11.0, t1=11.4)]
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out", render_cfg=render_cfg,
                palette="vivid", subtitles_cfg=subs_cfg)

    vf = _val_after(fake_ffmpeg[0], "-vf")
    assert vf.index("scale=") < vf.index("eq=") < vf.index("ass=")


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


# ---------------------------------------- Windows: ass фильтр без абсолютного пути (cwd-fix)

def test_ass_filter_contains_only_filename_no_path(tmp_path, render_cfg, monkeypatch):
    """ass= фильтр содержит только имя файла (r01.ass), без полного пути.

    Абсолютный путь с C:\\ или бэкслэшами ломает ffmpeg filtergraph на Windows —
    двоеточие и бэкслэши трактуются как синтаксис разделителей опций.
    Решение: ffmpeg запускается с cwd=tmp_ass_dir и видит файл по имени.
    """
    subs_cfg = load_subtitles_config(ROOT / "config" / "subtitles.yaml")
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"win-subs-video")
    reel = _reel("r01", 10.0, 40.0)
    reel.subtitles = [Word(word="тест", t0=11.0, t1=11.5)]
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())

    vf_seen = []

    class _FakeProc:
        def __init__(self, cmd, **kwargs):
            if "ffprobe" not in str(cmd[0]):   # диагностический ffprobe (crop-space) не считаем
                vf_seen.append(cmd)
            self.returncode = 0
            self.stdout = iter([])
            self.stderr = iter([])

        def wait(self):
            return 0

    monkeypatch.setattr(render.shutil, "which", lambda b: "/fake/ffmpeg")
    monkeypatch.setattr(render.subprocess, "Popen", _FakeProc)

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out",
                render_cfg=render_cfg, subtitles_cfg=subs_cfg)

    assert vf_seen, "ffmpeg не вызван"
    cmd = vf_seen[0]
    vf = _val_after(cmd, "-vf")
    assert "ass=" in vf
    # Фильтр должен содержать ТОЛЬКО имя файла, без пути (нет разделителей)
    ass_arg = vf.split("ass=", 1)[1].split(",")[0]  # часть после ass= до следующей запятой
    assert "/" not in ass_arg, f"ass-фильтр содержит прямой слэш (путь): {ass_arg!r}"
    assert "\\" not in ass_arg, f"ass-фильтр содержит обратный слэш: {ass_arg!r}"
    assert ":" not in ass_arg, f"ass-фильтр содержит двоеточие (Windows-диск?): {ass_arg!r}"
    assert ass_arg.endswith("r01.ass"), f"ожидали 'r01.ass', получили {ass_arg!r}"


def test_source_path_is_absolute_when_cwd_is_set(tmp_path, render_cfg, monkeypatch):
    """ffmpeg получает АБСОЛЮТНЫЙ путь к исходнику даже когда cwd=tmp_ass_dir.

    Когда Popen запускается с cwd, относительный путь к исходнику (inputs/1.mp4)
    резолвится относительно tmp_ass_dir, а не рабочей директории autoreels → файл не найден.
    Симулируем Windows-сценарий: inputs_dir передаётся относительным путём.
    """
    subs_cfg = load_subtitles_config(ROOT / "config" / "subtitles.yaml")
    inputs_abs = tmp_path / "inputs"
    sha = _make_source(inputs_abs, "v.mp4", b"abs-path-video")
    reel = _reel("r01", 10.0, 40.0)
    reel.subtitles = [Word(word="тест", t0=11.0, t1=11.5)]
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())

    cmds_seen: list[list[str]] = []

    class _FakeProc:
        def __init__(self, cmd, **kwargs):
            if "ffprobe" not in str(cmd[0]):   # диагностический ffprobe (crop-space) не считаем
                cmds_seen.append(cmd)
            self.returncode = 0
            self.stdout = iter([])
            self.stderr = iter([])

        def wait(self):
            return 0

    monkeypatch.setattr(render.shutil, "which", lambda b: "/fake/ffmpeg")
    monkeypatch.setattr(render.subprocess, "Popen", _FakeProc)
    # Передаём inputs_dir как ОТНОСИТЕЛЬНЫЙ путь — именно так на Windows при root="."
    monkeypatch.chdir(tmp_path)
    inputs_rel = Path("inputs")   # относительный, как "inputs" в рабочей директории

    render_crop(m, inputs_dir=inputs_rel, out_dir=Path("out"),
                render_cfg=render_cfg, subtitles_cfg=subs_cfg)

    assert cmds_seen, "ffmpeg не вызван"
    cmd = cmds_seen[0]
    source_arg = _val_after(cmd, "-i")
    assert Path(source_arg).is_absolute(), (
        f"путь к исходнику не абсолютный: {source_arg!r} — "
        f"при cwd=tmp_ass_dir относительный путь ведёт не туда"
    )


def test_ffmpeg_popen_receives_cwd_pointing_to_ass_dir(tmp_path, render_cfg, monkeypatch):
    """subprocess.Popen вызывается с cwd= указывающим на директорию с .ass файлом.

    Это позволяет ffmpeg найти r01.ass по имени без абсолютного пути в фильтре.
    """
    subs_cfg = load_subtitles_config(ROOT / "config" / "subtitles.yaml")
    inputs = tmp_path / "inputs"
    sha = _make_source(inputs, "v.mp4", b"cwd-test-video")
    reel = _reel("r01", 10.0, 40.0)
    reel.subtitles = [Word(word="слово", t0=11.0, t1=11.5)]
    m = _manifest("v.mp4", sha, [reel], setup=_crop_setup())

    popen_kwargs: list[dict] = []

    class _FakeProc:
        def __init__(self, cmd, **kwargs):
            if "ffprobe" not in str(cmd[0]):   # диагностический ffprobe (crop-space) не считаем
                popen_kwargs.append(kwargs)
            self.returncode = 0
            self.stdout = iter([])
            self.stderr = iter([])

        def wait(self):
            return 0

    monkeypatch.setattr(render.shutil, "which", lambda b: "/fake/ffmpeg")
    monkeypatch.setattr(render.subprocess, "Popen", _FakeProc)

    render_crop(m, inputs_dir=inputs, out_dir=tmp_path / "out",
                render_cfg=render_cfg, subtitles_cfg=subs_cfg)

    assert popen_kwargs, "Popen не вызван"
    cwd = popen_kwargs[0].get("cwd")
    assert cwd is not None, "Popen вызван без cwd"
    # cwd должен быть временной директорией, содержащей .ass файл
    cwd_path = Path(cwd)
    assert cwd_path.is_dir() or not cwd_path.exists(), f"cwd не является директорией: {cwd}"


# ------------------------------------ integration: реальный рендер (размер+формат)

@pytest.mark.integration
def test_real_render_social_size_and_format(tmp_path):
    """СКВОЗНОЙ: реальный ffmpeg-рендер 30-сек клипа целевым битрейтом →
    файл в соцсеть-диапазоне размера, h264/yuv420p/aac, moov в начале (faststart).

    Гоняется только там, где есть ffmpeg (pytest -m integration). Прямо проверяет цель
    задачи: клип из рендера сразу готов к загрузке, второй проход HandBrake не нужен.
    """
    import shutil, json as _json
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe не установлены")

    # Источник: 30с 1080×1920, намеренно тяжёлый (шум) — без rate-control раздулся бы.
    src = tmp_path / "src.mp4"
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "nullsrc=s=1080x1920:d=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
        "-vf", "geq=random(1)*255:128:128",     # шум: несжимаемый → проверка потолка битрейта
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
        "-shortest", str(src),
    ], check=True, capture_output=True)

    out = tmp_path / "clip.mp4"
    cmd = build_cut_cmd(
        ffmpeg, src, 0.0, 30.0, out,
        codec="libx264", preset="medium", video_bitrate="7M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
    )
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"ffmpeg упал: {r.stderr}"

    # Размер в соцсеть-диапазоне (30с @7Мбит/с ≈ 26 МБ; допускаем 18–40 с запасом на VBV)
    size_mb = out.stat().st_size / (1024 * 1024)
    assert 15 <= size_mb <= 45, f"размер {size_mb:.1f} МБ вне соцсеть-диапазона"

    # Формат через ffprobe: h264 + yuv420p + aac
    probe = subprocess.run([
        ffprobe, "-v", "error", "-show_streams", "-of", "json", str(out),
    ], capture_output=True, text=True)
    streams = _json.loads(probe.stdout)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert v["codec_name"] == "h264"
    assert v["pix_fmt"] == "yuv420p"
    assert a["codec_name"] == "aac"

    # faststart: moov-atom раньше mdat в файле (соцсети требуют для стрим-старта)
    head = out.read_bytes()
    assert head.index(b"moov") < head.index(b"mdat"), "moov после mdat — faststart не сработал"


@pytest.mark.integration
def test_real_render_hevc_is_compact_and_tagged_hvc1(tmp_path):
    """HEVC-профиль (дефолт): реальный рендер того же клипа компактнее h264 и с тегом hvc1.

    Проверяет цель дефолтного профиля hevc — вдвое меньший файл при совместимом контейнере
    (hvc1, не hev1). libx265 как софтверный стенд-ин для hevc_amf (AMF только на Windows AMD).
    """
    import shutil, json as _json
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe не установлены")
    if "libx265" not in subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                                        capture_output=True, text=True).stdout:
        pytest.skip("libx265 недоступен в этой сборке ffmpeg")

    src = tmp_path / "src.mp4"
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
        "-shortest", str(src),
    ], check=True, capture_output=True)

    out = tmp_path / "clip_hevc.mp4"
    cmd = build_cut_cmd(
        ffmpeg, src, 0.0, 30.0, out,
        codec="libx265", preset="medium", video_bitrate="5M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
    )
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"ffmpeg упал: {r.stderr}"

    # 30с @5Мбит/с ≈ 18–19 МБ — компактнее h264-диапазона (25+)
    size_mb = out.stat().st_size / (1024 * 1024)
    assert 10 <= size_mb <= 30, f"размер {size_mb:.1f} МБ вне hevc-диапазона"

    probe = subprocess.run([
        ffprobe, "-v", "error", "-show_streams", "-of", "json", str(out),
    ], capture_output=True, text=True)
    streams = _json.loads(probe.stdout)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    assert v["codec_name"] == "hevc"
    assert v["pix_fmt"] == "yuv420p"
    # тег hvc1 (не hev1) — иначе Apple/соцсети не проигрывают
    assert v.get("codec_tag_string") == "hvc1", f"тег {v.get('codec_tag_string')} — не hvc1"

    head = out.read_bytes()
    assert head.index(b"moov") < head.index(b"mdat"), "moov после mdat — faststart не сработал"


@pytest.mark.integration
def test_real_rotated_video_calibration_and_render_same_space(tmp_path):
    """СКВОЗНОЙ (повёрнутое видео = телефон PXL): кадр калибровки и crop-фильтр рендера в ОДНОМ
    отображаемом пространстве. Синтезируем coded 2688×1512 + display-matrix rotation 90 (→ показ
    1512×2688), затем проверяем:

    1. _probe_frame_size_for_auto (rotation-aware) → отображаемые 1512×2688;
    2. кадр калибровки (build_frame_cmd, autorotate по умолчанию) → PNG 1512×2688 = как видит человек;
    3. crop-фильтр рендера в этих же координатах (1320×2347@96,170) РЕНДЕРИТСЯ без клампа —
       значит autorotate применяется ДО crop (иначе кроп в 2688×1512 и h=2347>1512 → ошибка).
    """
    import shutil, struct, json as _json
    from autoreels.core.calibration import _probe_frame_size_for_auto
    from autoreels.local.calibrate import build_frame_cmd
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe не установлены")

    horiz = tmp_path / "h.mp4"
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=2688x1512:rate=5:duration=2",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(horiz),
    ], check=True, capture_output=True)
    # Запекаем display-matrix rotation 90 (как у телефонного вертикального видео): coded остаётся
    # 2688×1512, но метаданные говорят показывать вертикально 1512×2688.
    rot = tmp_path / "rot.mp4"
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error",
        "-display_rotation:v:0", "90", "-i", str(horiz), "-c", "copy", str(rot),
    ], check=True, capture_output=True)

    # 1. отображаемые размеры (rotation-aware) = вертикальные
    assert _probe_frame_size_for_auto(rot, ffprobe=ffprobe) == (1512, 2688)

    # 2. кадр калибровки (autorotate по умолчанию) — вертикальный PNG
    frame_png = tmp_path / "frame.png"
    r = subprocess.run(build_frame_cmd(ffmpeg, rot, frame_png, at_seconds=1.0),
                       capture_output=True, text=True)
    assert r.returncode == 0, f"извлечение кадра упало: {r.stderr}"
    png = frame_png.read_bytes()
    assert struct.unpack(">II", png[16:24]) == (1512, 2688), "PNG калибровки не в отображаемом пространстве"

    # 3. рендер: crop в отображаемых координатах 1512×2688 → без клампа (autorotate до crop)
    out = tmp_path / "clip.mp4"
    cmd = build_cut_cmd(
        ffmpeg, rot, 0.0, 2.0, out,
        codec="libx264", preset="ultrafast", video_bitrate="4M", pix_fmt="yuv420p",
        faststart=True, audio_codec="aac", audio_bitrate="128k",
        vf="crop=1320:2347:96:170,scale=1080:1920",
    )
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"рендер crop в отображаемом пространстве упал: {r.stderr}"
    probe = subprocess.run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(out),
    ], capture_output=True, text=True)
    v = _json.loads(probe.stdout)["streams"][0]
    assert (v["width"], v["height"]) == (1080, 1920), "выход не 1080×1920"
