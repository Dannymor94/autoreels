"""CLI-склейка (autoreels run / render) — M0 шаг 8. Внешнее (ffmpeg, Groq) мокается.

Инварианты, которые тесты защищают:
- `run` гонит этапы конвейера в правильном порядке (extract→transcribe→compress→select→
  assemble→write) — этапы как блоки, чтобы R3 потом вставился одним блоком;
- манифест называется <stem>.json (не manifest.json) — batch-совместимость;
- `render` глобит manifests/*.json и обрабатывает все по очереди;
- run/render архивируют исходник в inputs-archive/ после успеха (идемпотентно);
- batch: один файл упал → остальные продолжают, summary в конце;
- .env подхватывается автоматически (dotenv);
- ошибка этапа → внятное сообщение, не голый traceback.
"""
import json
import os
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.core import state
from autoreels.core.calibration import save_calibration
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Transcript, Word
from autoreels.local.render import RenderError

REPO_ROOT = Path(__file__).resolve().parents[1]


def _setup() -> SetupProfile:
    return SetupProfile(
        setup_id="tearoom_main",
        crop=Crop(x=1370, y=280, w=956, h=1700),
        scale=[1080, 1920],
        frame=[3840, 2160],
    )


def _reel(rid="r01") -> Reel:
    return Reel(id=rid, start=10.0, end=40.0, score=80,
                hook="h", title="t", description="d", reason="r", topic="x")


def _manifest(reels=None, source="v.mp4") -> Manifest:
    return Manifest(
        source=source, source_sha256="a" * 64, duration_preset="shorts",
        setup=_setup(), run_key="rk1", reels=reels if reels is not None else [_reel()],
    )


# ------------------------------------------------------------------ run: порядок этапов

def test_run_calls_stages_in_order(monkeypatch, tmp_path):
    order = []

    def rec(name, ret):
        def f(*a, **k):
            order.append(name)
            return ret
        return f

    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda d, s, n, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio", rec("extract", tmp_path / "a.wav"))
    monkeypatch.setattr(cli, "_stage_transcribe", rec("transcribe", "TRANSCRIPT"))
    monkeypatch.setattr(cli, "_stage_compress", rec("compress", "COMPRESSED"))
    monkeypatch.setattr(cli, "_stage_select", rec("select", [_reel()]))
    monkeypatch.setattr(cli, "_stage_snap", rec("snap", [_reel()]))
    monkeypatch.setattr(cli, "_stage_subtitles", rec("subtitles", [_reel()]))
    monkeypatch.setattr(cli, "_assemble_manifest", rec("assemble", _manifest()))
    monkeypatch.setattr(cli, "_write_manifest", rec("write", tmp_path / "v.json"))

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path)

    assert order == ["extract", "transcribe", "compress", "select", "snap",
                     "subtitles", "assemble", "write"]


def test_run_falls_back_to_auto_crop_when_uncalibrated(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: Transcript(language="ru", words=[]))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [_reel("r01")])

    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **kw: (3840, 2160))

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    calib = tmp_path / "calibrations"
    manifests = tmp_path / "manifests"

    cli.cmd_run(video, root=REPO_ROOT, calibrations_dir=calib, manifests_dir=manifests)

    # Манифест теперь <stem>.json
    m = Manifest.model_validate_json((manifests / "v.json").read_text(encoding="utf-8"))
    assert abs(m.setup.crop.w / m.setup.crop.h - 9 / 16) < 0.002
    assert m.setup.crop.x == (3840 - m.setup.crop.w) // 2
    assert m.setup.crop.y == 0


# ------------------------------------------------- run: манифест называется <stem>.json

def test_run_writes_manifest_named_by_stem(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda d, s, n, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: Transcript(language="ru", words=[]))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [_reel()])

    video = tmp_path / "PXL_20260621.mp4"
    video.write_bytes(b"x")
    manifests = tmp_path / "manifests"

    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=manifests)

    assert (manifests / "PXL_20260621.json").is_file()
    assert not (manifests / "manifest.json").exists()


# ------------------------------------------------- run: манифест собран ИЗ профиля

def test_run_assembles_manifest_with_crop_from_calibration(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: Transcript(language="ru", words=[]))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [_reel("r01")])

    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"hello-bytes")
    calib = tmp_path / "calibrations"
    save_calibration(
        calib, source_name="lecture.mp4", source_sha256=state.file_sha256_partial(video),
        crop=Crop(x=100, y=50, w=900, h=1600), frame=[3840, 2160], setup_label="my_room",
    )
    manifests = tmp_path / "manifests"

    cli.cmd_run(video, root=REPO_ROOT, calibrations_dir=calib, manifests_dir=manifests)

    # Манифест → lecture.json (stem от lecture.mp4)
    m = Manifest.model_validate_json((manifests / "lecture.json").read_text(encoding="utf-8"))
    assert m.setup.setup_id == "my_room"
    assert m.setup.crop.model_dump() == {"x": 100, "y": 50, "w": 900, "h": 1600}
    assert m.source == "lecture.mp4"
    assert len(m.source_sha256) == 64
    assert len(m.reels) == 1


def test_run_snaps_segment_bounds_using_transcript(monkeypatch, tmp_path):
    words = [Word(word="a", t0=30.0, t1=30.4), Word(word="b", t0=30.5, t1=31.0),
             Word(word="стоп", t0=31.1, t1=31.6), Word(word="далее", t0=33.0, t1=33.5)]
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: Transcript(language="ru", words=words))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    midword = Reel(id="r01", start=30.0, end=31.3, score=80, hook="h", title="t",
                   description="d", reason="r", topic="x")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [midword])

    video = tmp_path / "v.mp4"
    video.write_bytes(b"vid")
    calib = tmp_path / "calibrations"
    save_calibration(calib, source_name="v.mp4", source_sha256=state.file_sha256_partial(video),
                     crop=Crop(x=1370, y=280, w=956, h=1700), frame=[3840, 2160], setup_label="t")
    manifests = tmp_path / "manifests"

    cli.cmd_run(video, root=REPO_ROOT, calibrations_dir=calib, manifests_dir=manifests)

    m = Manifest.model_validate_json((manifests / "v.json").read_text(encoding="utf-8"))
    assert abs(m.reels[0].end - 31.9) < 1e-6


# ------------------------------------------------------------------ run: архив

def test_run_archives_video_after_success(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda d, s, n, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: Transcript(language="ru", words=[]))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [_reel()])

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    archive = tmp_path / "inputs-archive"

    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "manifests",
                archive_dir=archive)

    assert not video.exists()                    # перемещён из inputs/
    assert (archive / "v.mp4").exists()          # находится в архиве


def test_run_does_not_archive_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda d, s, n, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio",
                        lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    archive = tmp_path / "inputs-archive"

    with pytest.raises(Exception, match="boom"):
        cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "manifests",
                    archive_dir=archive)

    assert video.exists()                        # не архивирован — ошибка на этапе


# ------------------------------------------------------------------ _archive_video

def test_archive_video_moves_to_archive_dir(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    archive = tmp_path / "inputs-archive"

    cli._archive_video(video, archive)

    assert not video.exists()
    assert (archive / "v.mp4").read_bytes() == b"data"


def test_archive_video_idempotent_when_dest_exists(tmp_path):
    archive = tmp_path / "inputs-archive"
    archive.mkdir()
    (archive / "v.mp4").write_bytes(b"old")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"new")

    cli._archive_video(video, archive)

    assert (archive / "v.mp4").read_bytes() == b"old"   # не перезаписан
    assert video.exists()                                # источник не тронут


def test_archive_video_noop_when_source_missing(tmp_path):
    archive = tmp_path / "inputs-archive"
    cli._archive_video(tmp_path / "ghost.mp4", archive)   # не должен падать
    assert not archive.exists()                            # dir не создан зря


# ------------------------------------------------------------------ run: batch

def _mock_pipeline(monkeypatch, tmp_path):
    """Общие моки конвейера для batch-тестов."""
    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda d, s, n, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: Transcript(language="ru", words=[]))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [_reel()])


def test_run_batch_processes_all_mp4_in_inputs(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.mp4").write_bytes(b"x")
    (inputs / "b.mp4").write_bytes(b"x")
    manifests = tmp_path / "manifests"

    ok, failed = cli.cmd_run_batch(
        root=REPO_ROOT, inputs_dir=inputs, manifests_dir=manifests,
        archive_dir=tmp_path / "inputs-archive",
    )

    assert sorted(ok) == ["a.mp4", "b.mp4"]
    assert failed == []
    assert (manifests / "a.json").is_file()
    assert (manifests / "b.json").is_file()


def test_run_batch_continues_after_failure(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)

    # Первый файл в алфавитном порядке упадёт на extract_audio
    original_extract = cli._stage_extract_audio
    calls = []
    def selective_extract(video, **k):
        calls.append(Path(video).name)
        if Path(video).name == "bad.mp4":
            raise Exception("forced failure")
        return tmp_path / "a.wav"
    monkeypatch.setattr(cli, "_stage_extract_audio", selective_extract)

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "bad.mp4").write_bytes(b"x")
    (inputs / "good.mp4").write_bytes(b"x")

    ok, failed = cli.cmd_run_batch(
        root=REPO_ROOT, inputs_dir=inputs, manifests_dir=tmp_path / "manifests",
        archive_dir=tmp_path / "inputs-archive",
    )

    assert ok == ["good.mp4"]
    assert len(failed) == 1
    assert failed[0][0] == "bad.mp4"
    assert (inputs / "bad.mp4").exists()     # не архивирован (упал)
    assert not (inputs / "good.mp4").exists() # архивирован (успех)


def test_run_batch_empty_inputs_returns_empty(monkeypatch, tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()

    ok, failed = cli.cmd_run_batch(root=REPO_ROOT, inputs_dir=inputs,
                                   manifests_dir=tmp_path / "m", archive_dir=tmp_path / "a")

    assert ok == [] and failed == []


# --------------------------------------------------------------- render: глобит manifests/

def test_render_reads_manifest_and_calls_render_crop(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest().model_dump_json(), encoding="utf-8")

    called = {}
    def fake_crop(manifest, **k):
        called["manifest"] = manifest
        called["kwargs"] = k
        return [Path("reels-out/r01.mp4")]

    monkeypatch.setattr(cli, "render_crop", fake_crop)

    out = cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT)

    assert called["manifest"].source == "v.mp4"
    assert out == [Path("reels-out/r01.mp4")]
    assert called["kwargs"]["out_dir"].name == "v"


def test_render_batch_processes_multiple_manifests(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "a.json").write_text(_manifest(source="a.mp4").model_dump_json(), encoding="utf-8")
    (manifests / "b.json").write_text(_manifest(source="b.mp4").model_dump_json(), encoding="utf-8")

    processed = []
    monkeypatch.setattr(cli, "render_crop",
                        lambda m, **k: processed.append(m.source) or [Path(f"out/{m.source}")])

    out = cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT)

    assert sorted(processed) == ["a.mp4", "b.mp4"]
    assert len(out) == 2   # оба mp4 в плоском списке


def test_render_batch_continues_after_failure(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "bad.json").write_text(_manifest(source="bad.mp4").model_dump_json(), encoding="utf-8")
    (manifests / "good.json").write_text(_manifest(source="good.mp4").model_dump_json(), encoding="utf-8")

    def selective_crop(manifest, **k):
        if manifest.source == "bad.mp4":
            raise RenderError("ffmpeg упал")
        return [Path("out/good.mp4")]

    monkeypatch.setattr(cli, "render_crop", selective_crop)

    out = cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT)

    assert out == [Path("out/good.mp4")]   # только успешные попали в результат


def test_render_out_dir_uses_stem_from_manifest_source(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    m = Manifest(
        source="PXL_20260621_122006193.mp4", source_sha256="b" * 64,
        duration_preset="shorts", setup=_setup(), run_key="rk2", reels=[_reel()],
    )
    (manifests / "PXL_20260621_122006193.json").write_text(m.model_dump_json(), encoding="utf-8")

    seen_out: list[Path] = []
    monkeypatch.setattr(cli, "render_crop", lambda manifest, *, out_dir, **k: seen_out.append(Path(out_dir)) or [])
    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, out_dir=tmp_path / "reels-out")

    assert len(seen_out) == 1
    assert seen_out[0].name == "PXL_20260621_122006193"
    assert seen_out[0].parent.name == "reels-out"


def test_render_passes_encoder_through(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest().model_dump_json(), encoding="utf-8")

    seen = {}
    monkeypatch.setattr(cli, "render_crop",
                        lambda manifest, **k: seen.update(k) or [])
    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, encoder="h264_amf")
    assert seen["encoder"] == "h264_amf"


# ------------------------------------------------------------------ render: архив

def test_render_archives_source_after_success(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest().model_dump_json(), encoding="utf-8")

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "v.mp4").write_bytes(b"video")
    archive = tmp_path / "inputs-archive"

    monkeypatch.setattr(cli, "render_crop", lambda m, **k: [Path("out/r01.mp4")])

    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT,
                   inputs_dir=inputs, archive_dir=archive)

    assert not (inputs / "v.mp4").exists()
    assert (archive / "v.mp4").exists()


def test_render_archive_idempotent_when_already_in_archive(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest().model_dump_json(), encoding="utf-8")

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    archive = tmp_path / "inputs-archive"
    archive.mkdir()
    (archive / "v.mp4").write_bytes(b"original")  # уже заархивирован

    monkeypatch.setattr(cli, "render_crop", lambda m, **k: [])

    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT,
                   inputs_dir=inputs, archive_dir=archive)

    assert (archive / "v.mp4").read_bytes() == b"original"  # не перезаписан


def test_render_does_not_archive_on_failure(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest().model_dump_json(), encoding="utf-8")

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "v.mp4").write_bytes(b"video")
    archive = tmp_path / "inputs-archive"

    monkeypatch.setattr(cli, "render_crop", lambda m, **k: (_ for _ in ()).throw(RenderError("ffmpeg")))

    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT,
                   inputs_dir=inputs, archive_dir=archive)

    assert (inputs / "v.mp4").exists()   # не архивирован — рендер упал
    assert not archive.exists()


# ------------------------------------------------------------------ дефолтные пути

def test_render_uses_default_paths_without_args(monkeypatch, tmp_path):
    # Пишем реальный файл манифеста — render глобит manifests/*.json
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest().model_dump_json(), encoding="utf-8")

    seen = {}
    def fake_crop(manifest, *, inputs_dir, out_dir, **k):
        seen["inputs"] = Path(inputs_dir)
        seen["out"] = Path(out_dir)
        return []

    monkeypatch.setattr(cli, "render_crop", fake_crop)
    cli.cmd_render(manifests_dir=manifests)

    assert seen["inputs"].name == "inputs"
    assert seen["out"].parent.name == "reels-out"
    assert seen["out"].name == "v"


# ------------------------------------------------------------------ .env автоподхват

def test_cli_autoloads_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("AUTOREELS_DOTENV_PROBE=loaded123\n", encoding="utf-8")
    monkeypatch.delenv("AUTOREELS_DOTENV_PROBE", raising=False)
    try:
        cli._load_env(env)
        assert os.environ["AUTOREELS_DOTENV_PROBE"] == "loaded123"
    finally:
        os.environ.pop("AUTOREELS_DOTENV_PROBE", None)


# --------------------------------------------------------- ошибка этапа → чистое сообщение

def test_main_wraps_stage_error_as_clean_message(monkeypatch, capsys):
    def boom(*a, **k):
        raise RenderError("ffmpeg не найден в PATH")

    monkeypatch.setattr(cli, "cmd_render", boom)
    rc = cli.main(["render"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "ffmpeg не найден в PATH" in err
    assert "Traceback" not in err


def test_main_run_bad_video_returns_1_with_clean_message(tmp_path, capsys, monkeypatch):
    # run с фейковым видео (b"x") → ffprobe или extract_audio падает → код 1, нет traceback.
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(cli, "_stage_extract_audio",
                        lambda *a, **k: pytest.fail("конвейер не должен добраться до extract"))

    rc = cli.main(["run", str(video), "--ffmpeg", "ffmpeg"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err
