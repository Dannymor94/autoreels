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
from autoreels.local.render import RenderError, SourceNotFoundError

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
    monkeypatch.setattr(cli, "_stage_trim", rec("trim", [_reel()]))
    monkeypatch.setattr(cli, "_stage_subtitles", rec("subtitles", [_reel()]))
    monkeypatch.setattr(cli, "_assemble_manifest", rec("assemble", _manifest()))
    monkeypatch.setattr(cli, "_write_manifest", rec("write", tmp_path / "v.json"))

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path)

    assert order == ["extract", "transcribe", "compress", "select", "snap", "trim",
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


# --------------------------------------------------- render: пропуск отсутствующих исходников

def test_render_skips_manifest_when_source_missing(monkeypatch, tmp_path, capsys):
    """Манифест есть, видео нет → ⊘-предупреждение, пропуск, не ошибка."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "gone.json").write_text(_manifest(source="gone.mp4").model_dump_json(), encoding="utf-8")
    (manifests / "ok.json").write_text(_manifest(source="ok.mp4").model_dump_json(), encoding="utf-8")

    def selective_crop(manifest, **k):
        if manifest.source == "gone.mp4":
            raise SourceNotFoundError("gone.mp4 не найден")
        return [Path("out/ok.mp4")]

    monkeypatch.setattr(cli, "render_crop", selective_crop)

    out = cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT)

    captured = capsys.readouterr()
    assert "⊘" in captured.out or "пропущен" in captured.out
    assert "gone" in captured.out
    assert out == [Path("out/ok.mp4")]   # ok отрендерен, gone пропущен без упоминания в failed


def test_render_missing_source_not_counted_as_failure(monkeypatch, tmp_path):
    """SourceNotFoundError → пропуск (skipped), не failed → нет отметки об ошибке."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "missing.json").write_text(_manifest(source="missing.mp4").model_dump_json(),
                                            encoding="utf-8")

    monkeypatch.setattr(cli, "render_crop",
                        lambda m, **k: (_ for _ in ()).throw(SourceNotFoundError("нет")))

    # Не должно кидать исключение, возвращаем пустой список (отрендерено 0)
    out = cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT)
    assert out == []


# --------------------------------------------------- render: идемпотентность по выходным файлам

def test_render_skips_when_all_reels_done(monkeypatch, tmp_path, capsys):
    """Все mp4 уже есть в reels-out/<stem>/ → пропуск с ✓-сообщением, render_crop не вызывается."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    m = _manifest(reels=[_reel("r01"), _reel("r02")])
    (manifests / "v.json").write_text(m.model_dump_json(), encoding="utf-8")

    out_dir = tmp_path / "reels-out" / "v"
    out_dir.mkdir(parents=True)
    (out_dir / "r01.mp4").write_bytes(b"x")
    (out_dir / "r02.mp4").write_bytes(b"x")

    called = []
    monkeypatch.setattr(cli, "render_crop", lambda m, **k: called.append(1) or [])

    result = cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, out_dir=tmp_path / "reels-out")

    assert called == [], "render_crop не должен вызываться если всё готово"
    captured = capsys.readouterr()
    assert "✓" in captured.out or "уже" in captured.out
    assert "v" in captured.out
    assert result == []


def test_render_rerenders_partial_completion(monkeypatch, tmp_path):
    """Один mp4 из двух есть → render вызывается с одним недостающим reel."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    m = _manifest(reels=[_reel("r01"), _reel("r02")])
    (manifests / "v.json").write_text(m.model_dump_json(), encoding="utf-8")

    out_dir = tmp_path / "reels-out" / "v"
    out_dir.mkdir(parents=True)
    (out_dir / "r01.mp4").write_bytes(b"x")   # r01 готов, r02 нет

    seen_reels = []
    def fake_crop(manifest, **k):
        seen_reels.extend(r.id for r in manifest.reels)
        return [out_dir / "r02.mp4"]

    monkeypatch.setattr(cli, "render_crop", fake_crop)

    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, out_dir=tmp_path / "reels-out")

    assert seen_reels == ["r02"], f"ожидали только r02, получили {seen_reels}"


def test_render_does_not_touch_manifests(monkeypatch, tmp_path):
    """render не трогает файлы манифестов — ни после успеха, ни при пропуске."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    mf = manifests / "v.json"
    content = _manifest().model_dump_json()
    mf.write_text(content, encoding="utf-8")

    monkeypatch.setattr(cli, "render_crop", lambda m, **k: [])

    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT)

    assert mf.exists(), "манифест должен остаться в manifests/"
    assert mf.read_text(encoding="utf-8") == content, "содержимое манифеста не должно меняться"


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


# ------------------------------------------------------------------ шпаргалка (без аргументов)

def test_no_args_prints_cheatsheet_and_exits_0(capsys):
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "calibrate" in out
    assert "run" in out
    assert "render" in out
    assert "цикл" in out.lower() or "рабочий" in out.lower()


def test_no_args_cheatsheet_mentions_folders(capsys):
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "inputs/" in out
    assert "manifests/" in out
    assert "reels-out/" in out


def test_no_args_cheatsheet_hints_subcommand_help(capsys):
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "--help" in out


# ------------------------------------------------------------------ autoreels help

def test_help_command_exits_0(capsys):
    rc = cli.main(["help"])
    assert rc == 0


def test_help_command_shows_extended_info(capsys):
    rc = cli.main(["help"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "calibrate" in out
    assert "run" in out
    assert "render" in out
    assert "inputs/" in out


# ------------------------------------------------------------------ описания флагов в --help

def test_render_help_mentions_encoder_flag(capsys):
    import argparse
    p = cli._build_parser()
    try:
        p.parse_args(["render", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "--encoder" in out


def test_calibrate_help_mentions_setup_flag(capsys):
    import argparse
    p = cli._build_parser()
    try:
        p.parse_args(["calibrate", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "--setup" in out


# ------------------------------------------------------------------ шпаргалка: новые команды

def test_cheatsheet_includes_status_command(capsys):
    cli.main([])
    out = capsys.readouterr().out
    assert "status" in out


def test_cheatsheet_includes_calibrate_all(capsys):
    cli.main([])
    out = capsys.readouterr().out
    assert "--all" in out


def test_cheatsheet_has_4_step_cycle(capsys):
    cli.main([])
    out = capsys.readouterr().out
    # Рабочий цикл должен содержать 4 шага (status + calibrate + run + render)
    assert "1." in out and "4." in out


def test_cheatsheet_mentions_inputs_archive(capsys):
    cli.main([])
    out = capsys.readouterr().out
    assert "inputs-archive/" in out


def test_cheatsheet_mentions_mac_and_system(capsys):
    """Шпаргалка содержит пометки Mac / системник."""
    cli.main([])
    out = capsys.readouterr().out
    assert "Mac" in out or "mac" in out.lower()
    assert "системник" in out.lower() or "amf" in out.lower()


# ------------------------------------------------------------------ --help каждой команды

def test_calibrate_help_mentions_all_flag(capsys):
    p = cli._build_parser()
    try:
        p.parse_args(["calibrate", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "--all" in out


def test_run_help_mentions_groq(capsys):
    p = cli._build_parser()
    try:
        p.parse_args(["run", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "Groq" in out or "groq" in out.lower()


def test_render_help_mentions_windows_or_encoder_hint(capsys):
    p = cli._build_parser()
    try:
        p.parse_args(["render", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "h264_amf" in out or "Windows" in out or "системник" in out.lower()


def test_help_command_includes_status_and_calibrate_all(capsys):
    cli.main(["help"])
    out = capsys.readouterr().out
    assert "status" in out
    assert "--all" in out


# ------------------------------------------------------------------ autoreels status

def _write_manifest_file(path: Path, manifest: Manifest) -> None:
    path.write_text(manifest.model_dump_json(), encoding="utf-8")


def test_status_counts_inputs(tmp_path, capsys):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.mp4").write_bytes(b"x")
    (inputs / "b.mp4").write_bytes(b"x")

    rc = cli.cmd_status(root=tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "2" in out
    assert "input" in out.lower() or "ждут" in out.lower() or "inputs" in out.lower()


def test_status_counts_manifests(tmp_path, capsys):
    (tmp_path / "manifests").mkdir()
    _write_manifest_file(tmp_path / "manifests" / "a.json", _manifest(source="a.mp4"))
    _write_manifest_file(tmp_path / "manifests" / "b.json", _manifest(source="b.mp4"))

    rc = cli.cmd_status(root=tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "2" in out
    assert "manifest" in out.lower() or "рендер" in out.lower() or "manifests" in out.lower()


def test_status_counts_reels_out_folders(tmp_path, capsys):
    reels_out = tmp_path / "reels-out"
    (reels_out / "video1").mkdir(parents=True)
    (reels_out / "video1" / "r01.mp4").write_bytes(b"x")
    (reels_out / "video2").mkdir(parents=True)
    (reels_out / "video2" / "r01.mp4").write_bytes(b"x")

    rc = cli.cmd_status(root=tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "2" in out


def test_status_counts_archive(tmp_path, capsys):
    archive = tmp_path / "inputs-archive"
    archive.mkdir()
    (archive / "old.mp4").write_bytes(b"x")

    rc = cli.cmd_status(root=tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "1" in out
    assert "archi" in out.lower() or "архив" in out.lower()


def test_status_warns_manifest_without_video(tmp_path, capsys):
    (tmp_path / "manifests").mkdir()
    _write_manifest_file(tmp_path / "manifests" / "gone.json", _manifest(source="gone.mp4"))
    # inputs/ пуст — видео нет

    rc = cli.cmd_status(root=tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "gone" in out


def test_status_warns_video_without_calibration(tmp_path, capsys):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "uncal.mp4").write_bytes(b"x")
    # calibrations/ пуст — нет профиля

    rc = cli.cmd_status(root=tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    assert "uncal" in out or "калибр" in out.lower()


def test_status_no_warnings_when_calibrated(tmp_path, capsys):
    """Если для видео есть калибровка — не предупреждать об отсутствии калибровки."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    video = inputs / "cal.mp4"
    video.write_bytes(b"x")

    # сохранить калибровку через реальный sha
    from autoreels.core import state
    from autoreels.core.calibration import save_calibration as _save_cal
    sha = state.file_sha256_cached_fast(video, tmp_path / "cache")
    setup = _setup()
    _save_cal(
        tmp_path / "calibrations",
        source_name="cal.mp4",
        source_sha256=sha,
        crop=setup.crop,
        frame=setup.frame,
    )

    rc = cli.cmd_status(root=tmp_path)

    assert rc == 0
    out = capsys.readouterr().out
    # предупреждение о некалиброванном видео не должно появляться
    assert "без калибр" not in out.lower() and "uncalibrated" not in out.lower()


def test_status_empty_project(tmp_path, capsys):
    """Все папки пусты/отсутствуют → нули, не ошибка."""
    rc = cli.cmd_status(root=tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "0" in out


def test_status_registered_as_subcommand(capsys):
    p = cli._build_parser()
    args = p.parse_args(["status"])
    assert args.cmd == "status"


def test_main_status_exits_0(tmp_path, capsys):
    rc = cli.main(["status", "--root", str(tmp_path)])
    assert rc == 0


# --------------------------------------------------------- status: per-file crop table

def _save_manual_cal(tmp_path, video):
    """Сохранить ручную калибровку для видео (setup_label != 'auto')."""
    from autoreels.core import state
    from autoreels.core.calibration import save_calibration as _save_cal
    sha = state.file_sha256_cached_fast(video, tmp_path / "cache")
    setup = _setup()
    _save_cal(
        tmp_path / "calibrations",
        source_name=video.name,
        source_sha256=sha,
        crop=setup.crop,
        frame=setup.frame,
        setup_label="tearoom_main",
    )
    return sha


def test_status_shows_calibrated_mark_for_each_video(tmp_path, capsys):
    """Видео с ручной калибровкой → ✓ в таблице."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    video = inputs / "cal.mp4"
    video.write_bytes(b"x")
    _save_manual_cal(tmp_path, video)

    cli.cmd_status(root=tmp_path)
    out = capsys.readouterr().out
    assert "cal.mp4" in out
    assert "✓" in out


def test_status_shows_auto_mark_for_uncalibrated(tmp_path, capsys):
    """Видео без калибровки → ⚙ автокроп в таблице."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "raw.mp4").write_bytes(b"x")

    cli.cmd_status(root=tmp_path)
    out = capsys.readouterr().out
    assert "raw.mp4" in out
    assert "⚙" in out


def test_status_shows_both_marks_for_mixed_inputs(tmp_path, capsys):
    """Часть откалиброванных, часть нет — оба маркера в таблице."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    cal = inputs / "cal.mp4"
    cal.write_bytes(b"calibrated-content")
    _save_manual_cal(tmp_path, cal)
    (inputs / "raw.mp4").write_bytes(b"raw-content")

    cli.cmd_status(root=tmp_path)
    out = capsys.readouterr().out
    assert "✓" in out
    assert "⚙" in out
    assert "cal.mp4" in out
    assert "raw.mp4" in out


def test_status_no_per_file_table_when_inputs_empty(tmp_path, capsys):
    """inputs/ пуст → таблицы нет, не ошибка."""
    (tmp_path / "inputs").mkdir()
    cli.cmd_status(root=tmp_path)
    out = capsys.readouterr().out
    assert "✓" not in out
    assert "⚙" not in out


# ------------------------------------------ calibrate --all: базовый флаг и регистрация

def test_calibrate_all_flag_registered_in_parser():
    p = cli._build_parser()
    args = p.parse_args(["calibrate", "--all", "dummy.mp4"])
    assert args.all is True


def test_calibrate_all_without_video_arg_is_valid():
    """calibrate --all без позиционного аргумента — допустимо (batch по inputs/)."""
    p = cli._build_parser()
    args = p.parse_args(["calibrate", "--all"])
    assert args.all is True
    assert args.video is None


# ------------------------------------------ calibrate --all: логика пачки

def _write_auto_cal(tmp_path, video):
    """Записать автокалибровку (setup_label='auto', auto=True)."""
    from autoreels.core import state
    from autoreels.core.calibration import calibration_path, auto_crop
    import json
    sha = state.file_sha256_cached_fast(video, tmp_path / "cache")
    cal_dir = tmp_path / "calibrations"
    cal_dir.mkdir(parents=True, exist_ok=True)
    crop = auto_crop((3840, 2160))
    rec = {
        "source_name": video.name,
        "source_sha256": sha,
        "setup_label": "auto",
        "crop": crop.model_dump(),
        "scale": [1080, 1920],
        "frame": [3840, 2160],
        "auto": True,
    }
    calibration_path(cal_dir, sha).write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8"
    )
    return sha


def test_calibrate_all_skips_manually_calibrated(tmp_path, monkeypatch, capsys):
    """Видео с ручной калибровкой пропускается молча — _ask_batch_action не вызывается."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    video = inputs / "manual.mp4"
    video.write_bytes(b"x")
    _save_manual_cal(tmp_path, video)

    asked = []
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: asked.append(name) or "п")
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert asked == [], "ручная калибровка не должна переспрашиваться"


def test_calibrate_all_prompts_for_uncalibrated(tmp_path, monkeypatch):
    """Видео без калибровки → _ask_batch_action вызывается с именем файла."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "raw.mp4").write_bytes(b"x")

    asked = []
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: asked.append(name) or "п")
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert asked == ["raw.mp4"]


def test_calibrate_all_prompts_for_auto_calibrated(tmp_path, monkeypatch):
    """Видео с авто-калибровкой (setup_label='auto') тоже переспрашивается."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    video = inputs / "auto.mp4"
    video.write_bytes(b"x")
    _write_auto_cal(tmp_path, video)

    asked = []
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: asked.append(name) or "п")
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert asked == ["auto.mp4"]


def test_calibrate_all_action_a_saves_auto_crop(tmp_path, monkeypatch):
    """Выбор 'а' → сохраняет автокроп, файл калибровки создаётся."""
    from autoreels.core.calibration import calibration_path
    from autoreels.core import state

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    video = inputs / "raw.mp4"
    video.write_bytes(b"x")
    sha = state.file_sha256_cached_fast(video, tmp_path / "cache")

    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: "а")
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    cal_path = calibration_path(tmp_path / "calibrations", sha)
    assert cal_path.is_file(), "автокроп должен быть сохранён"


def test_calibrate_all_action_p_skips_without_saving(tmp_path, monkeypatch):
    """Выбор 'п' → файл калибровки НЕ создаётся."""
    from autoreels.core.calibration import calibration_path
    from autoreels.core import state

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    video = inputs / "raw.mp4"
    video.write_bytes(b"x")
    sha = state.file_sha256_cached_fast(video, tmp_path / "cache")

    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: "п")
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    cal_path = calibration_path(tmp_path / "calibrations", sha)
    assert not cal_path.exists(), "пропуск не должен создавать калибровку"


def test_calibrate_all_action_k_calls_cmd_calibrate(tmp_path, monkeypatch):
    """Выбор 'к' → вызывается cmd_calibrate для этого видео."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "raw.mp4").write_bytes(b"x")

    called = []
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: "к")
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))
    monkeypatch.setattr(cli, "cmd_calibrate",
                        lambda video, **k: called.append(Path(video).name))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert called == ["raw.mp4"]


def test_calibrate_all_mixed_batch(tmp_path, monkeypatch):
    """Пачка: ручная (пропуск) + некалиброванная (спросить) + автокроп (спросить)."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()

    manual = inputs / "manual.mp4"
    manual.write_bytes(b"manual-content")
    _save_manual_cal(tmp_path, manual)

    raw = inputs / "raw.mp4"
    raw.write_bytes(b"raw-content")

    auto_v = inputs / "autocrop.mp4"
    auto_v.write_bytes(b"auto-content")
    _write_auto_cal(tmp_path, auto_v)

    asked = []
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: asked.append(name) or "п")
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert "manual.mp4" not in asked
    assert "raw.mp4" in asked
    assert "autocrop.mp4" in asked


# ------------------------------------------ новые тесты: исправления багов

def test_calibration_kind_returns_corrupt_for_broken_json(tmp_path):
    """Повреждённый JSON → 'corrupt', не 'none'."""
    cal_dir = tmp_path / "calibrations"
    cal_dir.mkdir()
    sha = "a" * 64
    cli.calibration_path(cal_dir, sha).write_text("{ broken json", encoding="utf-8")
    assert cli._calibration_kind(cal_dir, sha) == "corrupt"


def test_calibrate_all_skips_corrupt_without_overwriting(tmp_path, monkeypatch, capsys):
    """Повреждённый файл калибровки → предупреждение и пропуск без перезаписи."""
    inputs_dir = tmp_path / "inputs"
    cal_dir    = tmp_path / "calibrations"
    inputs_dir.mkdir()
    cal_dir.mkdir()

    video = inputs_dir / "bad.mp4"
    video.write_bytes(b"x")
    sha = "b" * 64
    monkeypatch.setattr(cli.state, "file_sha256_cached_fast", lambda v, c: sha)
    cli.calibration_path(cal_dir, sha).write_text("{ broken", encoding="utf-8")

    asked = []
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: asked.append(name) or "а")

    cli.cmd_calibrate_batch(root=tmp_path, inputs_dir=inputs_dir, calibrations_dir=cal_dir,
                            cache_dir=tmp_path / "cache")

    assert not asked, "corrupt-файл не должен вызывать промпт"
    out = capsys.readouterr().out
    assert "повреждённый" in out


def test_status_no_warning_for_archived_video(tmp_path, capsys):
    """Манифест чьё видео в inputs-archive/ → НЕ выдаёт предупреждение."""
    (tmp_path / "inputs").mkdir()
    archive_dir = tmp_path / "inputs-archive"
    archive_dir.mkdir()
    (archive_dir / "done.mp4").write_bytes(b"x")

    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    m = _manifest(source="done.mp4")
    (manifests_dir / "done.json").write_text(m.model_dump_json(), encoding="utf-8")

    cli.cmd_status(root=tmp_path)
    out = capsys.readouterr().out
    assert "⚠" not in out, "архивное видео не должно давать предупреждение"


def test_calibrate_all_root_flag_registered():
    """calibrate --all должен принимать флаг --root."""
    p = cli._build_parser()
    args = p.parse_args(["calibrate", "--all", "--root", "/some/path"])
    assert args.root == "/some/path"


def test_ask_batch_action_auto_prompt_differs_from_none(monkeypatch):
    """Для kind='auto' промпт содержит 'автокроп уже зафиксирован', не 'кропа нет'."""
    inputs_given = []
    monkeypatch.setattr("builtins.input", lambda prompt: inputs_given.append(prompt) or "п")
    cli._ask_batch_action("video.mp4", "auto")
    assert "автокроп уже зафиксирован" in inputs_given[0]
    assert "кропа нет" not in inputs_given[0]


def test_ask_batch_action_none_prompt_says_no_crop(monkeypatch):
    """Для kind='none' промпт содержит 'кропа нет'."""
    inputs_given = []
    monkeypatch.setattr("builtins.input", lambda prompt: inputs_given.append(prompt) or "п")
    cli._ask_batch_action("video.mp4", "none")
    assert "кропа нет" in inputs_given[0]


def test_calibrate_batch_action_a_uses_save_calibration(tmp_path, monkeypatch):
    """Ветка 'а' вызывает save_calibration вместо ручной сборки JSON."""
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    (inputs_dir / "v.mp4").write_bytes(b"x")
    sha = "c" * 64
    monkeypatch.setattr(cli.state, "file_sha256_cached_fast", lambda v, c: sha)
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, ffprobe="ffprobe": (1920, 1080))
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: "а")
    saved = []
    real_save = cli.save_calibration
    def mock_save(cal_dir, *, source_name, source_sha256, crop, frame, setup_label=None):
        saved.append({"source_name": source_name, "setup_label": setup_label})
        return real_save(cal_dir, source_name=source_name, source_sha256=source_sha256,
                         crop=crop, frame=frame, setup_label=setup_label)
    monkeypatch.setattr(cli, "save_calibration", mock_save)

    cli.cmd_calibrate_batch(root=tmp_path, inputs_dir=inputs_dir,
                            calibrations_dir=tmp_path / "calibrations",
                            cache_dir=tmp_path / "cache")
    assert saved, "save_calibration должна была быть вызвана"
    assert saved[0]["setup_label"] == "auto"


# ------------------------------------------ run: не интерактивен

def test_run_does_not_call_ask_batch_action(monkeypatch, tmp_path):
    """cmd_run не должен вызывать интерактивный промпт ни при каких условиях."""
    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda d, s, n, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(cli, "_stage_transcribe",
                        lambda *a, **k: __import__("autoreels.core.models", fromlist=["Transcript"])
                        .Transcript(language="ru", words=[]))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [_reel()])

    if hasattr(cli, "_ask_batch_action"):
        called = []
        monkeypatch.setattr(cli, "_ask_batch_action",
                            lambda name, kind: called.append(name) or (_ for _ in ()).throw(
                                AssertionError(f"run вызвал интерактив для {name}")))

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    # Не должно кинуть AssertionError — run не интерактивен
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path)
