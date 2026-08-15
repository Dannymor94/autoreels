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

# Реальный _run_git, захваченный ДО autouse-мока (_no_real_git) — для теста самого _run_git.
_REAL_RUN_GIT = cli._run_git


@pytest.fixture(autouse=True)
def _encoder_available(monkeypatch):
    """По умолчанию энкодер «доступен» — тесты не гоняют реальный ffmpeg-пробник (нет AMF
    на Mac). Тесты префлайта/меню переопределяют cli.probe_encoder явно."""
    monkeypatch.setattr(cli, "probe_encoder", lambda codec, **k: True)


@pytest.fixture(autouse=True)
def _no_real_git(monkeypatch):
    """КРИТИЧНО: тесты используют root=REPO_ROOT (реальный репозиторий). cmd_run/cmd_render
    теперь дёргают git pull, а calibrate — commit/push. Без этого мока реальный git выполнялся
    бы в рабочем репо во время тестов (наблюдалось: тест закоммитил и запушил калибровки).
    По умолчанию git — no-op; тесты git (_FakeGit) переопределяют _run_git явно."""
    monkeypatch.setattr(cli, "_git_pull", lambda *a, **k: None)

    def _fake_git(args, *, root, timeout=None):
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()
    monkeypatch.setattr(cli, "_run_git", _fake_git)


@pytest.fixture(autouse=True)
def _frame_size_probe(monkeypatch):
    """По умолчанию реальный размер кадра = 3840×2160 (совпадает с frame в _setup()) — cmd_run
    кросс-проверяет кроп против ffprobe при сборке манифеста, а тестовые mp4 фейковые. Тесты,
    которым нужен другой размер (авто-кроп, out-of-bounds), переопределяют явно."""
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))


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


def _manifest_with_crop(stem, sha, crop: Crop, setup_id) -> Manifest:
    return Manifest(
        source=f"{stem}.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
        duration_preset="shorts",
        setup=SetupProfile(setup_id=setup_id, crop=crop, scale=[1080, 1920], frame=[3840, 2160]),
        run_key="rk", reels=[],
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
    monkeypatch.setattr(cli, "_stage_padding", rec("padding", [_reel()]))
    monkeypatch.setattr(cli, "_stage_trim", rec("trim", [_reel()]))
    monkeypatch.setattr(cli, "_stage_subtitles", rec("subtitles", [_reel()]))
    monkeypatch.setattr(cli, "_assemble_manifest", rec("assemble", _manifest()))
    monkeypatch.setattr(cli, "_write_manifest", rec("write", tmp_path / "v.json"))
    # Попутное сохранение транскрипта не входит в цепочку этапов — мокаем (транскрипт-стаб=str).
    monkeypatch.setattr(cli, "_write_transcript_file", lambda *a, **k: tmp_path / "v.txt")

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path, transcripts_dir=tmp_path)

    assert order == ["extract", "transcribe", "compress", "select", "snap", "padding", "trim",
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

    cli.cmd_run(video, root=REPO_ROOT, calibrations_dir=calib, manifests_dir=manifests,
                transcripts_dir=tmp_path / "transcripts")

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

    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=manifests,
                transcripts_dir=tmp_path / "transcripts")

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

    cli.cmd_run(video, root=REPO_ROOT, calibrations_dir=calib, manifests_dir=manifests,
                transcripts_dir=tmp_path / "transcripts")

    # Манифест → lecture.json (stem от lecture.mp4)
    m = Manifest.model_validate_json((manifests / "lecture.json").read_text(encoding="utf-8"))
    assert m.setup.setup_id == "my_room"
    assert m.setup.crop.model_dump() == {"x": 100, "y": 50, "w": 900, "h": 1600}
    assert m.source == "lecture.mp4"
    assert len(m.source_sha256) == 64
    assert len(m.reels) == 1


def test_run_rejects_crop_out_of_real_frame(monkeypatch, tmp_path):
    """Калибровка записана в перепутанном пространстве (кроп h=2347 в кадре 2688×1512): при
    сборке манифеста кроп кросс-проверяется против РЕАЛЬНЫХ ffprobe-размеров → падаем с числами,
    а не рендерим 30 битых клипов."""
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: Transcript(language="ru", words=[]))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [_reel("r01")])
    # Реальный кадр — горизонтальный 2688×1512, а кроп из калибровки — в повёрнутом (h=2347).
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (2688, 1512))

    video = tmp_path / "PXL.mp4"
    video.write_bytes(b"hello-bytes")
    calib = tmp_path / "calibrations"
    save_calibration(
        calib, source_name="PXL.mp4", source_sha256=state.file_sha256_partial(video),
        crop=Crop(x=278, y=224, w=718, h=2347), frame=[1512, 2688], setup_label="pxl",
    )

    with pytest.raises(cli.CalibrationError) as e:
        cli.cmd_run(video, root=REPO_ROOT, calibrations_dir=calib,
                    manifests_dir=tmp_path / "manifests", transcripts_dir=tmp_path / "transcripts")
    msg = str(e.value)
    assert "2688×1512" in msg                          # отображаемые размеры в сообщении
    assert "перекалибруй" in msg.lower()               # явная инструкция, не молчаливый откат
    assert "Автокроп НЕ подставляю" in msg             # инвариант: не подменяем автокропом
    assert not (tmp_path / "manifests" / "PXL.json").exists()   # битый манифест не записан


def test_run_snaps_segment_bounds_using_transcript(monkeypatch, tmp_path):
    # Пауза после «стоп» 1.9с (> min_pause 1.5) → «стоп» = реальная граница мысли.
    words = [Word(word="a", t0=30.0, t1=30.4), Word(word="b", t0=30.5, t1=31.0),
             Word(word="стоп", t0=31.1, t1=31.6), Word(word="далее", t0=33.5, t1=34.0)]
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

    cli.cmd_run(video, root=REPO_ROOT, calibrations_dir=calib, manifests_dir=manifests,
                transcripts_dir=tmp_path / "transcripts")

    m = Manifest.model_validate_json((manifests / "v.json").read_text(encoding="utf-8"))
    # После snap: end = 31.6 (граница слова «стоп») + tail_sec 0.3 = 31.9
    # После apply_padding: last_word.t1 + tail_pad_sec = 31.6 + 0.7 = 32.3
    #                       first_word.t0 - lead_pad_sec = 30.0 - 0.3 = 29.7
    assert abs(m.reels[0].end - 32.3) < 1e-6
    assert abs(m.reels[0].start - 29.7) < 1e-6


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
                archive_dir=archive, transcripts_dir=tmp_path / "transcripts")

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
        archive_dir=tmp_path / "inputs-archive", transcripts_dir=tmp_path / "transcripts",
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
        archive_dir=tmp_path / "inputs-archive", transcripts_dir=tmp_path / "transcripts",
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


# ------------------------------------------------- авто-коммит манифеста per-video (git push)

class _FakeGit:
    """Записывает git-вызовы; можно назначить сбой/таймаут конкретной подкоманде."""
    def __init__(self, fail_on=None, timeout_on=None):
        self.calls = []           # список списков-аргументов git
        self._fail_on = fail_on
        self._timeout_on = timeout_on

    def __call__(self, args, *, root, timeout=None):
        import subprocess
        self.calls.append(list(args))
        sub = args[0]
        if self._timeout_on and sub == self._timeout_on:
            raise subprocess.TimeoutExpired(cmd="git", timeout=timeout or 1)
        rc = 1 if (self._fail_on and sub == self._fail_on) else 0
        stderr = "fatal: could not read Username (no network)" if rc else ""
        class _R:
            returncode = rc
            stdout = ""
            stderr = ""
        _R.stderr = stderr
        return _R()

    def subcommands(self):
        return [c[0] for c in self.calls]


def test_commit_push_manifest_runs_add_commit_push(monkeypatch, tmp_path, capsys):
    """_commit_push_manifest: add → commit (с сообщением) → push, всё успешно."""
    git = _FakeGit()
    monkeypatch.setattr(cli, "_run_git", git)
    mf = tmp_path / "manifests" / "lecture.json"
    mf.parent.mkdir(parents=True)
    mf.write_text("{}", encoding="utf-8")

    cli._commit_push_manifest(mf, 7, root=tmp_path)

    assert git.subcommands() == ["add", "commit", "push"]
    commit_args = next(c for c in git.calls if c[0] == "commit")
    assert "manifest: lecture (7 reels)" in commit_args      # формат сообщения
    assert "запушен" in capsys.readouterr().out


def test_commit_push_manifest_includes_calibration(monkeypatch, tmp_path):
    """Калибровка кропа коммитится ВМЕСТЕ с манифестом (уезжает на системник)."""
    git = _FakeGit()
    monkeypatch.setattr(cli, "_run_git", git)
    mf = tmp_path / "manifests" / "lecture.json"
    mf.parent.mkdir(parents=True)
    mf.write_text("{}", encoding="utf-8")
    cal = tmp_path / "calibrations" / ("a" * 64 + ".json")
    cal.parent.mkdir(parents=True)
    cal.write_text("{}", encoding="utf-8")

    cli._commit_push_manifest(mf, 3, root=tmp_path, calibration_path=cal)

    add_args = next(c for c in git.calls if c[0] == "add")
    assert str(mf) in add_args and str(cal) in add_args      # оба файла в коммите


def test_commit_push_calibrations_syncs_dir(monkeypatch, tmp_path, capsys):
    """_commit_push_calibrations: add calibrations/ → commit → push (для системника)."""
    git = _FakeGit()
    monkeypatch.setattr(cli, "_run_git", git)
    (tmp_path / "calibrations").mkdir()

    cli._commit_push_calibrations(root=tmp_path)

    assert git.subcommands() == ["add", "commit", "push"]
    add_args = next(c for c in git.calls if c[0] == "add")
    assert "calibrations" in add_args
    out = capsys.readouterr().out
    assert "отправлена" in out and "arl run" in out         # следующий шаг — run на Mac


def test_commit_push_calibrations_noop_when_dir_absent(monkeypatch, tmp_path):
    """Нет calibrations/ → git не дёргаем."""
    git = _FakeGit()
    monkeypatch.setattr(cli, "_run_git", git)
    cli._commit_push_calibrations(root=tmp_path)
    assert git.calls == []


def test_commit_push_calibrations_git_error_does_not_raise(monkeypatch, tmp_path, capsys):
    """Ошибка git (нет сети) → предупреждение, не исключение (калибровки уже на диске)."""
    monkeypatch.setattr(cli, "_run_git", _FakeGit(fail_on="push"))
    (tmp_path / "calibrations").mkdir()
    cli._commit_push_calibrations(root=tmp_path)          # не должно бросить
    assert "локально" in capsys.readouterr().err


def test_run_commits_calibration_with_manifest(monkeypatch, tmp_path):
    """cmd_run(push=True) передаёт путь калибровки в коммит (кроп уезжает на системник)."""
    _mock_pipeline(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(cli, "_commit_push_manifest",
                        lambda path, n, *, root, calibration_path=None:
                        captured.update(calib=calibration_path))

    video = tmp_path / "inputs" / "lecture.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "m",
                transcripts_dir=tmp_path / "t", cache_dir=tmp_path / "c",
                calibrations_dir=tmp_path / "calibrations", archive_dir=tmp_path / "arch",
                push=True)

    assert captured["calib"] is not None
    assert "calibrations" in str(captured["calib"])       # путь к calibrations/<sha>.json
    assert str(captured["calib"]).endswith(".json")


def test_git_sync_enabled_on_all_platforms_by_default(monkeypatch):
    """Оба тира — участники git (системник калибрует и пушит калибровки, Mac пушит манифесты).
    По умолчанию синхронизация включена ВЕЗДЕ (workflow изменился — Windows больше не только потребитель)."""
    monkeypatch.delenv("AUTOREELS_GIT_SYNC", raising=False)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    assert cli._should_git_sync() is True                 # системник тоже пушит калибровки
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    assert cli._should_git_sync() is True


def test_git_sync_env_override(monkeypatch):
    """AUTOREELS_GIT_SYNC=0 выключает (одиночная машина без remote), =1 форсит."""
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setenv("AUTOREELS_GIT_SYNC", "0")
    assert cli._should_git_sync() is False                # выкл явно
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setenv("AUTOREELS_GIT_SYNC", "1")
    assert cli._should_git_sync() is True                 # вкл явно


def test_commit_push_calibrations_works_on_windows(monkeypatch, tmp_path):
    """На системнике (Windows) калибровки ПУШАТСЯ — он теперь источник калибровок (item 1)."""
    monkeypatch.delenv("AUTOREELS_GIT_SYNC", raising=False)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    git = _FakeGit()
    monkeypatch.setattr(cli, "_run_git", git)
    (tmp_path / "calibrations").mkdir()

    cli._commit_push_calibrations(root=tmp_path)

    assert git.subcommands() == ["add", "commit", "push"]  # пушит, а не молчит


def test_git_sync_disabled_by_env_skips_push(monkeypatch, tmp_path):
    """AUTOREELS_GIT_SYNC=0 → _commit_push_* не трогает git (одиночная машина без remote)."""
    monkeypatch.setenv("AUTOREELS_GIT_SYNC", "0")
    git = _FakeGit()
    monkeypatch.setattr(cli, "_run_git", git)
    (tmp_path / "calibrations").mkdir()
    mf = tmp_path / "m" / "v.json"
    mf.parent.mkdir(parents=True)
    mf.write_text("{}", encoding="utf-8")

    cli._commit_push_calibrations(root=tmp_path)
    cli._commit_push_manifest(mf, 3, root=tmp_path)

    assert git.calls == []                                 # git не дёргался (выкл env)


def test_commit_push_manifest_git_failure_warns_not_raises(monkeypatch, tmp_path, capsys):
    """Сбой push (нет сети/конфликт) → предупреждение, НЕ исключение (прогон продолжается)."""
    monkeypatch.setattr(cli, "_run_git", _FakeGit(fail_on="push"))
    mf = tmp_path / "m" / "v.json"
    mf.parent.mkdir(parents=True)
    mf.write_text("{}", encoding="utf-8")

    cli._commit_push_manifest(mf, 3, root=tmp_path)   # не должно бросить

    err = capsys.readouterr().err
    assert "сохранён локально" in err and "вручную" in err


def test_commit_push_manifest_timeout_warns_not_hangs(monkeypatch, tmp_path, capsys):
    """Push завис (passphrase/сеть) → TimeoutExpired ловится, предупреждение, без зависания."""
    monkeypatch.setattr(cli, "_run_git", _FakeGit(timeout_on="push"))
    mf = tmp_path / "m" / "v.json"
    mf.parent.mkdir(parents=True)
    mf.write_text("{}", encoding="utf-8")

    cli._commit_push_manifest(mf, 1, root=tmp_path)

    assert "локально" in capsys.readouterr().err


def test_run_git_uses_noninteractive_env(monkeypatch, tmp_path):
    """_run_git выставляет неинтерактивный режим: не зависать на пароле/SSH-passphrase."""
    seen = {}
    def fake_subprocess_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["env"] = kw.get("env", {})
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()
    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(cli, "_run_git", _REAL_RUN_GIT)   # снять autouse-мок: тестируем сам _run_git

    cli._run_git(["push"], root=tmp_path)

    assert seen["env"].get("GIT_TERMINAL_PROMPT") == "0"
    assert "BatchMode=yes" in seen["env"].get("GIT_SSH_COMMAND", "")


def test_run_commits_manifest_when_push_true(monkeypatch, tmp_path):
    """cmd_run(push=True) → _commit_push_manifest вызван после записи манифеста."""
    _mock_pipeline(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(cli, "_commit_push_manifest",
                        lambda path, n, *, root, **k: calls.append((Path(path).stem, n)))

    video = tmp_path / "inputs" / "lecture.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "m",
                transcripts_dir=tmp_path / "t", cache_dir=tmp_path / "c",
                archive_dir=tmp_path / "arch", push=True)

    assert calls == [("lecture", 1)]     # 1 reel из _mock_pipeline


def test_run_no_commit_when_push_false(monkeypatch, tmp_path):
    """По умолчанию (push=False) git не трогается — текущее поведение single-run."""
    _mock_pipeline(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(cli, "_commit_push_manifest",
                        lambda *a, **k: calls.append(1))

    video = tmp_path / "inputs" / "v.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "m",
                transcripts_dir=tmp_path / "t", cache_dir=tmp_path / "c",
                archive_dir=tmp_path / "arch")   # push по умолчанию False

    assert calls == []


def test_batch_commits_each_video(monkeypatch, tmp_path):
    """batch push=True → коммит+пуш ПОСЛЕ КАЖДОГО видео (не в конце пачки)."""
    _mock_pipeline(monkeypatch, tmp_path)
    pushed = []
    monkeypatch.setattr(cli, "_commit_push_manifest",
                        lambda path, n, *, root, **k: pushed.append(Path(path).stem))

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.mp4").write_bytes(b"x")
    (inputs / "b.mp4").write_bytes(b"x")

    cli.cmd_run_batch(root=REPO_ROOT, inputs_dir=inputs, manifests_dir=tmp_path / "m",
                      archive_dir=tmp_path / "arch", transcripts_dir=tmp_path / "t",
                      cache_dir=tmp_path / "c", push=True)

    assert sorted(pushed) == ["a", "b"]


def test_batch_failed_video_keeps_previous_pushes(monkeypatch, tmp_path):
    """Упавшее видео НЕ откатывает уже запушенные — b падает, a и c запушены."""
    _mock_pipeline(monkeypatch, tmp_path)
    def selective_extract(video, **k):
        if Path(video).name == "b.mp4":
            raise Exception("forced failure on b")
        return tmp_path / "a.wav"
    monkeypatch.setattr(cli, "_stage_extract_audio", selective_extract)
    pushed = []
    monkeypatch.setattr(cli, "_commit_push_manifest",
                        lambda path, n, *, root, **k: pushed.append(Path(path).stem))

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        (inputs / name).write_bytes(b"x")

    ok, failed = cli.cmd_run_batch(
        root=REPO_ROOT, inputs_dir=inputs, manifests_dir=tmp_path / "m",
        archive_dir=tmp_path / "arch", transcripts_dir=tmp_path / "t",
        cache_dir=tmp_path / "c", push=True,
    )

    assert pushed == ["a", "c"]           # b пропущено (упало ДО записи манифеста)
    assert [n for n, _ in failed] == ["b.mp4"]


def test_batch_no_push_when_disabled(monkeypatch, tmp_path):
    """push=False (флаг --no-push) → ни одного git-вызова."""
    _mock_pipeline(monkeypatch, tmp_path)
    pushed = []
    monkeypatch.setattr(cli, "_commit_push_manifest",
                        lambda *a, **k: pushed.append(1))

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.mp4").write_bytes(b"x")

    cli.cmd_run_batch(root=REPO_ROOT, inputs_dir=inputs, manifests_dir=tmp_path / "m",
                      archive_dir=tmp_path / "arch", transcripts_dir=tmp_path / "t",
                      cache_dir=tmp_path / "c", push=False)

    assert pushed == []


# ------------------------------------- рассинхронизация калибровка ↔ манифест (кроп устарел)

def test_desync_detects_auto_manifest_with_manual_calibration(tmp_path):
    """Манифест с автокропом + появилась ручная калибровка (другой кроп) → рассинхрон."""
    sha = "a" * 64
    m = _manifest_with_crop("lecture", sha, Crop(x=100, y=0, w=900, h=1600), "auto")
    cal = tmp_path / "calibrations"
    save_calibration(cal, source_name="lecture.mp4", source_sha256=sha,
                     crop=Crop(x=300, y=50, w=800, h=1400), frame=[3840, 2160],
                     setup_label="lecture")

    msg = cli._manifest_calibration_desync(m, cal)
    assert msg is not None
    assert "lecture" in msg
    assert "recrop" in msg.lower()       # советует быстрый recrop (без пересчёта R0)
    assert "автокроп" in msg


def test_no_desync_when_manifest_crop_matches_calibration(tmp_path):
    """Кроп манифеста == калибровка → синхронно, предупреждения нет."""
    sha = "b" * 64
    crop = Crop(x=300, y=50, w=800, h=1400)
    m = _manifest_with_crop("v", sha, crop, "v")
    cal = tmp_path / "calibrations"
    save_calibration(cal, source_name="v.mp4", source_sha256=sha, crop=crop,
                     frame=[3840, 2160], setup_label="v")

    assert cli._manifest_calibration_desync(m, cal) is None


def test_no_desync_when_no_calibration_file(tmp_path):
    """Нет файла калибровки (локален/удалён) → сравнить не с чем, предупреждения нет."""
    m = _manifest_with_crop("v", "c" * 64, Crop(x=0, y=0, w=900, h=1600), "auto")
    assert cli._manifest_calibration_desync(m, tmp_path / "calibrations") is None


def test_status_reports_calibration_desync(tmp_path, capsys):
    """status показывает рассинхронизацию: манифест с автокропом при ручной калибровке."""
    root = tmp_path
    (root / "inputs").mkdir()
    manifests = root / "manifests"
    manifests.mkdir()
    cal = root / "calibrations"
    sha = "a" * 64
    m = _manifest_with_crop("lecture", sha, Crop(x=100, y=0, w=900, h=1600), "auto")
    (manifests / "lecture.json").write_text(m.model_dump_json(), encoding="utf-8")
    save_calibration(cal, source_name="lecture.mp4", source_sha256=sha,
                     crop=Crop(x=300, y=50, w=800, h=1400), frame=[3840, 2160],
                     setup_label="lecture")

    cli.cmd_status(root=root)

    out = capsys.readouterr().out
    assert "recrop" in out
    assert "lecture" in out


def test_warn_if_manifest_stale_returns_and_prints(tmp_path, capsys):
    """_warn_if_manifest_stale (вызывается после calibrate): устаревший манифест → предупреждение."""
    root = tmp_path
    (root / "manifests").mkdir()
    cal = root / "calibrations"
    sha = "a" * 64
    m = _manifest_with_crop("lecture", sha, Crop(x=100, y=0, w=900, h=1600), "auto")
    (root / "manifests" / "lecture.json").write_text(m.model_dump_json(), encoding="utf-8")
    save_calibration(cal, source_name="lecture.mp4", source_sha256=sha,
                     crop=Crop(x=300, y=50, w=800, h=1400), frame=[3840, 2160],
                     setup_label="lecture")

    msg = cli._warn_if_manifest_stale(root / "inputs" / "lecture.mp4", root=root)

    assert msg is not None
    assert "recrop" in capsys.readouterr().err


def test_warn_if_manifest_stale_silent_when_no_manifest(tmp_path, capsys):
    """Манифеста ещё нет (калибровка ДО первого run — норма) → тихо, без предупреждения."""
    root = tmp_path
    (root / "calibrations").mkdir()
    save_calibration(root / "calibrations", source_name="v.mp4", source_sha256="a" * 64,
                     crop=Crop(x=1, y=2, w=3, h=4), frame=[3840, 2160], setup_label="v")

    msg = cli._warn_if_manifest_stale(root / "inputs" / "v.mp4", root=root)

    assert msg is None
    assert capsys.readouterr().err == ""


# --------------------------------- авто-синхронизация: run тянет pull, render блокирует устаревшее

def test_run_pulls_before_start(monkeypatch, tmp_path):
    """cmd_run делает git pull ПЕРЕД стартом (подтянуть свежие калибровки с системника)."""
    _mock_pipeline(monkeypatch, tmp_path)
    pulls = []
    monkeypatch.setattr(cli, "_git_pull", lambda root, **k: pulls.append(k.get("what")))
    video = tmp_path / "inputs" / "v.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")

    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "m",
                transcripts_dir=tmp_path / "t", cache_dir=tmp_path / "c",
                calibrations_dir=tmp_path / "calibrations", archive_dir=tmp_path / "arch")

    assert pulls == ["калибровки"]                     # pull вызван ровно раз перед работой


def test_run_batch_pulls_once_not_per_video(monkeypatch, tmp_path):
    """Batch тянет pull ОДИН раз, а не на каждое видео (cmd_run зовётся с pull_first=False)."""
    _mock_pipeline(monkeypatch, tmp_path)
    pulls = []
    monkeypatch.setattr(cli, "_git_pull", lambda root, **k: pulls.append(1))
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.mp4").write_bytes(b"x")
    (inputs / "b.mp4").write_bytes(b"x")

    cli.cmd_run_batch(root=REPO_ROOT, inputs_dir=inputs, manifests_dir=tmp_path / "m",
                      archive_dir=tmp_path / "arch", transcripts_dir=tmp_path / "t",
                      cache_dir=tmp_path / "c", calibrations_dir=tmp_path / "calibrations")

    assert pulls == [1]                                # один pull на всю пачку


def _stale_render_setup(tmp_path):
    """Манифест + калибровка с ДРУГИМ (свежим) кропом → рассинхрон. Возвращает (manifests, cal)."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    m = _manifest()                                    # sha 'a'*64, crop 1370,280,956,1700
    (manifests / "v.json").write_text(m.model_dump_json(), encoding="utf-8")
    cal = tmp_path / "calibrations"
    save_calibration(cal, source_name="v.mp4", source_sha256=m.source_sha256,
                     crop=Crop(x=96, y=170, w=1320, h=2347), frame=[1512, 2688], setup_label="v")
    return manifests, cal


def test_render_blocks_stale_crop(monkeypatch, tmp_path, capsys):
    """Калибровка новее манифеста → рендер ПРОПУСКАЕТ видео (не жжёт старый кроп), советует recrop."""
    manifests, cal = _stale_render_setup(tmp_path)
    called = []
    monkeypatch.setattr(cli, "render_crop", lambda m, **k: called.append(m) or [])

    out = cli.cmd_render(manifests_dir=manifests, calibrations_dir=cal, root=REPO_ROOT)

    assert called == []                                # render_crop НЕ вызван (пропущено)
    assert out == []
    err = capsys.readouterr().err
    assert "ПРОПУСК" in err and "recrop" in err


def test_render_allow_stale_renders_anyway(monkeypatch, tmp_path):
    """--allow-stale: рендерим устаревший кроп сознательно (форс)."""
    manifests, cal = _stale_render_setup(tmp_path)
    called = []
    monkeypatch.setattr(cli, "render_crop", lambda m, **k: called.append(m) or [Path("r.mp4")])

    cli.cmd_render(manifests_dir=manifests, calibrations_dir=cal, root=REPO_ROOT, allow_stale=True)

    assert len(called) == 1                            # отрендерён несмотря на рассинхрон


def test_status_shows_manifest_sync_marks(monkeypatch, tmp_path, capsys):
    """status по каждому видео показывает состояние манифеста: ✓ / кроп устарел → recrop / нет."""
    root = tmp_path
    inputs = root / "inputs"; inputs.mkdir()
    manifests = root / "manifests"; manifests.mkdir()
    cal = root / "calibrations"
    sha = "d" * 64
    monkeypatch.setattr(cli.state, "file_sha256_cached_fast", lambda v, c: sha)
    monkeypatch.setattr(cli, "_calibration_kind", lambda d, s: "manual")
    (inputs / "v.mp4").write_bytes(b"x")
    # манифест с УСТАРЕВШИМ кропом + свежая калибровка (другой кроп) → «кроп устарел → recrop»
    (manifests / "v.json").write_text(
        _manifest_with_crop("v", sha, Crop(x=0, y=0, w=900, h=1600), "auto").model_dump_json(),
        encoding="utf-8")
    save_calibration(cal, source_name="v.mp4", source_sha256=sha,
                     crop=Crop(x=96, y=170, w=1320, h=2347), frame=[1512, 2688], setup_label="v")

    cli.cmd_status(root=root)

    out = capsys.readouterr().out
    assert "кроп устарел → recrop" in out              # per-video метка синхронизации


# ------------------------------------------------------------ recrop: обновить кроп без R0

def _recrop_manifest_and_cal(tmp_path, *, manifest_crop, cal_crop, cal_frame=(1512, 2688)):
    sha = "d" * 64
    manifests = tmp_path / "manifests"; manifests.mkdir()
    reels = [Reel(id="r01", start=10.0, end=40.0, score=80, hook="h", title="Т", description="о",
                  reason="r", topic="x", subtitles=[Word(word="слово", t0=11.0, t1=11.5)])]
    m = Manifest(source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
                 duration_preset="shorts",
                 setup=SetupProfile(setup_id="old", crop=manifest_crop, scale=[1080, 1920],
                                    frame=[2688, 1512]),
                 run_key="rk", reels=reels)
    (manifests / "v.json").write_text(m.model_dump_json(indent=2), encoding="utf-8")
    cal = tmp_path / "calibrations"
    save_calibration(cal, source_name="v.mp4", source_sha256=sha, crop=cal_crop,
                     frame=list(cal_frame), setup_label="room")
    return manifests, cal


def test_recrop_updates_only_crop_rest_byte_identical(tmp_path):
    """recrop меняет ТОЛЬКО setup; reels/тексты/субтитры/прочее — байт-в-байт те же."""
    manifests, cal = _recrop_manifest_and_cal(
        tmp_path, manifest_crop=Crop(x=133, y=75, w=808, h=1437),
        cal_crop=Crop(x=96, y=170, w=1320, h=2347))
    before = json.loads((manifests / "v.json").read_text(encoding="utf-8"))

    rc = cli.cmd_recrop("v.mp4", root=REPO_ROOT, manifests_dir=manifests,
                        calibrations_dir=cal, push=False)

    assert rc == 0
    after = json.loads((manifests / "v.json").read_text(encoding="utf-8"))
    assert after["setup"]["crop"] == {"x": 96, "y": 170, "w": 1320, "h": 2347}   # кроп обновлён
    assert after["setup"]["frame"] == [1512, 2688]
    # всё, кроме setup — идентично (границы клипов, тексты, субтитры не тронуты)
    before.pop("setup"); after.pop("setup")
    assert before == after


def test_recrop_validates_crop_bounds(tmp_path, capsys):
    """Кроп калибровки вне отображаемого кадра → recrop ПРОПУСКАЕТ (манифест не портится)."""
    manifests, cal = _recrop_manifest_and_cal(
        tmp_path, manifest_crop=Crop(x=133, y=75, w=808, h=1437),
        cal_crop=Crop(x=0, y=0, w=1512, h=2800), cal_frame=(1512, 2688))   # h=2800 > 2688
    before = (manifests / "v.json").read_text(encoding="utf-8")

    cli.cmd_recrop("v.mp4", root=REPO_ROOT, manifests_dir=manifests,
                   calibrations_dir=cal, push=False)

    assert (manifests / "v.json").read_text(encoding="utf-8") == before   # не изменён
    assert "пропуск" in capsys.readouterr().err.lower()


def test_recrop_batch_updates_only_stale(tmp_path):
    """Batch recrop: обновляет манифест с устаревшим кропом, синхронный не трогает."""
    sha_stale, sha_ok = "d" * 64, "e" * 64
    manifests = tmp_path / "manifests"; manifests.mkdir()
    cal = tmp_path / "calibrations"
    good_crop = Crop(x=96, y=170, w=1320, h=2347)
    # устаревший: манифест-кроп ≠ калибровка
    m1 = _manifest_with_crop("stale", sha_stale, Crop(x=1, y=2, w=900, h=1600), "auto")
    (manifests / "stale.json").write_text(m1.model_dump_json(indent=2), encoding="utf-8")
    save_calibration(cal, source_name="stale.mp4", source_sha256=sha_stale,
                     crop=good_crop, frame=[1512, 2688], setup_label="s")
    # синхронный: манифест-кроп == калибровка
    m2 = _manifest_with_crop("ok", sha_ok, good_crop, "ok")
    m2_frame = m2.model_copy(update={"setup": SetupProfile(setup_id="ok", crop=good_crop,
                                     scale=[1080, 1920], frame=[1512, 2688])})
    (manifests / "ok.json").write_text(m2_frame.model_dump_json(indent=2), encoding="utf-8")
    save_calibration(cal, source_name="ok.mp4", source_sha256=sha_ok,
                     crop=good_crop, frame=[1512, 2688], setup_label="ok")
    ok_before = (manifests / "ok.json").read_text(encoding="utf-8")

    cli.cmd_recrop(None, root=REPO_ROOT, manifests_dir=manifests, calibrations_dir=cal, push=False)

    stale_after = json.loads((manifests / "stale.json").read_text(encoding="utf-8"))
    assert stale_after["setup"]["crop"] == good_crop.model_dump()          # обновлён
    assert (manifests / "ok.json").read_text(encoding="utf-8") == ok_before  # синхронный не тронут


def test_recrop_batch_updates_on_frame_space_change_and_reports_synced(tmp_path, capsys):
    """Кадр в манифесте перевёрнут vs калибровки (кодированное [2688,1512] ↔ отображаемое
    [1512,2688]) → однозначно устарел, обновляется; синхронный явно помечается «уже синхронно»
    (иначе «0 обновлено» в batch выглядит как баг)."""
    manifests = tmp_path / "manifests"; manifests.mkdir()
    cal = tmp_path / "calibrations"
    disp = Crop(x=170, y=457, w=1255, h=2231)
    # coded манифест (frame [2688,1512]) + display калибровка (frame [1512,2688]) → устарел
    m1 = Manifest(source="coded.mp4", source_sha256="a" * 64, source_hash_scheme="partial-p1",
                  duration_preset="shorts",
                  setup=SetupProfile(setup_id="auto", crop=Crop(x=133, y=75, w=808, h=1437),
                                     scale=[1080, 1920], frame=[2688, 1512]),
                  run_key="rk", reels=[_reel_win("r01", 10, 40)])
    (manifests / "coded.json").write_text(m1.model_dump_json(indent=2), encoding="utf-8")
    save_calibration(cal, source_name="coded.mp4", source_sha256="a" * 64,
                     crop=disp, frame=[1512, 2688], setup_label="c")
    # синхронный
    m2 = Manifest(source="ok.mp4", source_sha256="b" * 64, source_hash_scheme="partial-p1",
                  duration_preset="shorts",
                  setup=SetupProfile(setup_id="c", crop=disp, scale=[1080, 1920], frame=[1512, 2688]),
                  run_key="rk", reels=[_reel_win("r01", 10, 40)])
    (manifests / "ok.json").write_text(m2.model_dump_json(indent=2), encoding="utf-8")
    save_calibration(cal, source_name="ok.mp4", source_sha256="b" * 64,
                     crop=disp, frame=[1512, 2688], setup_label="c")

    cli.cmd_recrop(None, root=REPO_ROOT, manifests_dir=manifests, calibrations_dir=cal, push=False)

    out = capsys.readouterr().out
    coded_after = json.loads((manifests / "coded.json").read_text(encoding="utf-8"))
    assert coded_after["setup"]["frame"] == [1512, 2688]        # пространство обновлено
    assert "кодированное→отображаемое" in out                   # явная пометка смены пространства
    assert "уже синхронно" in out                              # синхронный виден в batch
    assert "1 обновлено" in out and "1 уже синхронно" in out


def test_recrop_auto_pushes_updated_manifest(tmp_path):
    """recrop с push=True коммитит+пушит обновлённый манифест (уезжает на системник)."""
    manifests, cal = _recrop_manifest_and_cal(
        tmp_path, manifest_crop=Crop(x=133, y=75, w=808, h=1437),
        cal_crop=Crop(x=96, y=170, w=1320, h=2347))
    pushed = []
    import autoreels.__main__ as _cli
    orig = _cli._commit_push_manifest
    _cli._commit_push_manifest = lambda path, n, *, root, calibration_path=None: pushed.append(Path(path).name)
    try:
        cli.cmd_recrop("v.mp4", root=REPO_ROOT, manifests_dir=manifests,
                       calibrations_dir=cal, push=True)
    finally:
        _cli._commit_push_manifest = orig

    assert pushed == ["v.json"]                        # обновлённый манифест запушен


# ------------------------------------------------------------ diagnose-cuts (обрывы фраз)

def _setup_diag(tmp_path, *, reels, sha="d" * 64):
    """Манифест + кэш-транскрипт по реальной цепочке source_sha → mp3 → audio_hash → transcript."""
    manifests = tmp_path / "manifests"; manifests.mkdir()
    cache = tmp_path / "cache"; cache.mkdir()
    words = [{"word": "всё", "t0": 0.0, "t1": 0.5}, {"word": "понятно.", "t0": 0.5, "t1": 1.0},
             {"word": "это", "t0": 1.2, "t1": 1.6}, {"word": "дальше", "t0": 3.5, "t1": 4.0}]
    audio = cache / f"{sha}.mp3"; audio.write_bytes(b"FAKE-MP3-BYTES")
    ah = state.audio_hash(audio)
    (cache / f"{ah}.transcript.json").write_text(
        json.dumps({"language": "ru", "words": words}), encoding="utf-8")
    m = Manifest(source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
                 duration_preset="shorts", setup=_setup(), run_key="rk", reels=reels)
    (manifests / "v.json").write_text(m.model_dump_json(), encoding="utf-8")
    return manifests, cache


def _reel_win(rid, start, end):
    return Reel(id=rid, start=start, end=end, score=80, hook="h", title="t",
                description="d", reason="r", topic="x")


def test_diagnose_cuts_classifies_manifest_ends(tmp_path, capsys):
    """Дефолт (без LLM): r01 кончается на «понятно.» → CLEAN, r02 на «это» → HARD висячее."""
    manifests, cache = _setup_diag(tmp_path, reels=[
        _reel_win("r01", 0.0, 1.0),     # «понятно.» — CLEAN
        _reel_win("r02", 0.0, 1.6),     # «это» — HARD висячее
    ])
    rc = cli.cmd_diagnose_cuts(root=REPO_ROOT, manifests_dir=manifests, cache_dir=cache)
    out = capsys.readouterr().out
    assert rc == 0
    assert "CLEAN" in out and "HARD" in out and "висячее" in out
    assert "1 clean" in out and "1 HARD" in out          # сводка


def test_diagnose_cuts_warns_when_transcript_missing(tmp_path, capsys):
    """Нет кэш-транскрипта (видео не прогонялось здесь) → предупреждение, не падение."""
    manifests = tmp_path / "manifests"; manifests.mkdir()
    m = Manifest(source="v.mp4", source_sha256="e" * 64, source_hash_scheme="partial-p1",
                 duration_preset="shorts", setup=_setup(), run_key="rk", reels=[_reel_win("r01", 0, 1)])
    (manifests / "v.json").write_text(m.model_dump_json(), encoding="utf-8")
    rc = cli.cmd_diagnose_cuts(root=REPO_ROOT, manifests_dir=manifests, cache_dir=tmp_path / "cache")
    assert rc == 0
    assert "транскрипт не найден" in capsys.readouterr().err


def test_diagnose_cuts_rerun_uses_cached_transcript_and_warns(tmp_path, monkeypatch, capsys):
    """--rerun: пере-прогон от КЭШ-транскрипта (mock select — без реального LLM) + предупреждение."""
    manifests, cache = _setup_diag(tmp_path, reels=[_reel_win("r01", 0.0, 1.0)])
    seen = {}
    monkeypatch.setattr(cli, "build_pool", lambda cfg: type("P", (), {"preflight": lambda s: None})())
    def fake_select(compressed, **k):
        seen["compressed"] = compressed
        return [_reel_win("r01", 0.0, 1.0)]
    monkeypatch.setattr(cli, "select", fake_select)

    rc = cli.cmd_diagnose_cuts(root=REPO_ROOT, manifests_dir=manifests, cache_dir=cache, rerun=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "--rerun" in out and "сравнивать" in out.lower()   # предупреждение о different space
    assert "compressed" in seen                               # select вызван на кэш-транскрипте
    assert "понятно" in seen["compressed"]                    # именно текст кэш-транскрипта


def test_calibrate_batch_warns_when_manifest_already_exists(tmp_path, monkeypatch, capsys):
    """calibrate --all: ручная калибровка видео с уже созданным (авто)манифестом → предупреждение."""
    root = tmp_path
    inputs = root / "inputs"
    inputs.mkdir()
    (inputs / "lecture.mp4").write_bytes(b"x")
    (root / "manifests").mkdir()
    cal = root / "calibrations"
    cal.mkdir()
    sha = "d" * 64

    monkeypatch.setattr(cli.state, "file_sha256_cached_fast", lambda v, c: sha)
    monkeypatch.setattr(cli, "_calibration_kind", lambda d, s: "none")
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: "к")

    m = _manifest_with_crop("lecture", sha, Crop(x=100, y=0, w=900, h=1600), "auto")
    (root / "manifests" / "lecture.json").write_text(m.model_dump_json(), encoding="utf-8")

    def fake_calibrate(video, **k):
        save_calibration(cal, source_name=Path(video).name, source_sha256=sha,
                         crop=Crop(x=300, y=50, w=800, h=1400), frame=[3840, 2160],
                         setup_label="lecture")
    monkeypatch.setattr(cli, "cmd_calibrate", fake_calibrate)

    cli.cmd_calibrate_batch(root=root, inputs_dir=inputs, calibrations_dir=cal,
                            cache_dir=root / "c")

    assert "recrop" in capsys.readouterr().err


# ------------------------------------------------- разрешение пути к ffmpeg (машинные дефолты)

def _rcfg(ffmpeg="ffmpeg"):
    from types import SimpleNamespace
    return SimpleNamespace(ffmpeg=ffmpeg)


def test_resolve_ffmpeg_flag_beats_env_beats_config(monkeypatch):
    """Приоритет: флаг > env RENDER_FFMPEG > render.local.yaml/render.yaml (config)."""
    monkeypatch.setenv("RENDER_FFMPEG", "/env/ffmpeg")
    # флаг выигрывает
    assert cli.resolve_ffmpeg("/flag/ffmpeg", render_cfg=_rcfg("/cfg/ffmpeg")) == "/flag/ffmpeg"
    # без флага — env
    assert cli.resolve_ffmpeg(None, render_cfg=_rcfg("/cfg/ffmpeg")) == "/env/ffmpeg"


def test_resolve_ffmpeg_config_used_when_no_flag_no_env(monkeypatch):
    """render.local.yaml (config.ffmpeg ≠ дефолт) применяется без флага/env — машинный дефолт."""
    monkeypatch.delenv("RENDER_FFMPEG", raising=False)
    assert cli.resolve_ffmpeg(None, render_cfg=_rcfg(r"D:\ffmpeg\bin\ffmpeg.exe")) == \
        r"D:\ffmpeg\bin\ffmpeg.exe"


def test_resolve_ffmpeg_uses_path_when_nothing_set(monkeypatch):
    """Ничего не задано, ffmpeg в PATH → возвращаем «ffmpeg» (команда), не абсолютный путь."""
    monkeypatch.delenv("RENDER_FFMPEG", raising=False)
    got = cli.resolve_ffmpeg(None, render_cfg=_rcfg("ffmpeg"),
                             which=lambda b: "/usr/bin/ffmpeg" if b == "ffmpeg" else None)
    assert got == "ffmpeg"


def test_resolve_ffmpeg_autodiscovers_typical_path(monkeypatch):
    """Нет флага/env/config и НЕ в PATH → автопоиск типичных мест (работает без настройки)."""
    monkeypatch.delenv("RENDER_FFMPEG", raising=False)
    cands = [r"D:\ffmpeg\bin\ffmpeg.exe", "/usr/local/bin/ffmpeg"]
    got = cli.resolve_ffmpeg(
        None, render_cfg=_rcfg("ffmpeg"),
        which=lambda b: None,                              # не в PATH
        candidates=cands,
        is_file=lambda p: str(p) == r"D:\ffmpeg\bin\ffmpeg.exe",
    )
    assert got == r"D:\ffmpeg\bin\ffmpeg.exe"


def test_resolve_ffmpeg_not_found_clear_error(monkeypatch):
    """Не найден нигде → FFmpegNotFoundError: где искал + как задать (флаг/env/render.local.yaml)."""
    monkeypatch.delenv("RENDER_FFMPEG", raising=False)
    with pytest.raises(cli.FFmpegNotFoundError) as e:
        cli.resolve_ffmpeg(None, render_cfg=_rcfg("ffmpeg"),
                           which=lambda b: None,
                           candidates=[r"D:\ffmpeg\bin\ffmpeg.exe"],
                           is_file=lambda p: False)
    msg = str(e.value)
    assert "Искал" in msg and r"D:\ffmpeg\bin\ffmpeg.exe" in msg    # где искал
    assert "RENDER_FFMPEG" in msg and "render.local.yaml" in msg    # как задать
    assert "--ffmpeg" in msg


def test_cli_resolve_ffmpeg_reads_local_yaml_from_project_root_not_cwd(tmp_path, monkeypatch):
    """_cli_resolve_ffmpeg берёт render.local.yaml из КОРНЯ ПРОЕКТА, а не из cwd — иначе после
    autoload (`arl` из любой папки) машинный путь ffmpeg не находился → падало в 'ffmpeg'."""
    proj = tmp_path / "proj"
    (proj / "config").mkdir(parents=True)
    (proj / "config" / "render.yaml").write_text(
        (REPO_ROOT / "config" / "render.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (proj / "config" / "render.local.yaml").write_text(
        "ffmpeg: D:/ffmpeg/bin/ffmpeg.exe\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_project_root", lambda: proj)
    monkeypatch.delenv("RENDER_FFMPEG", raising=False)
    monkeypatch.chdir(tmp_path)                          # cwd НЕ корень проекта

    got = cli._cli_resolve_ffmpeg(None)                  # без root → корень проекта

    assert got == "D:/ffmpeg/bin/ffmpeg.exe"            # взят из render.local.yaml проекта


def test_cli_resolve_ffmpeg_falls_back_to_project_root_when_cwd_config_missing(tmp_path, monkeypatch):
    """Даже если явный root без config — деградируем к корню проекта (там render.local.yaml)."""
    proj = tmp_path / "proj"
    (proj / "config").mkdir(parents=True)
    (proj / "config" / "render.yaml").write_text(
        (REPO_ROOT / "config" / "render.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (proj / "config" / "render.local.yaml").write_text(
        "ffmpeg: /opt/ff/ffmpeg\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_project_root", lambda: proj)
    monkeypatch.delenv("RENDER_FFMPEG", raising=False)

    got = cli._cli_resolve_ffmpeg(None, root=tmp_path / "empty")   # root без config/

    assert got == "/opt/ff/ffmpeg"


def test_resolve_ffprobe_flag_and_env(monkeypatch):
    monkeypatch.delenv("RENDER_FFPROBE", raising=False)
    assert cli.resolve_ffprobe("/flag/ffprobe", which=lambda b: None) == "/flag/ffprobe"
    monkeypatch.setenv("RENDER_FFPROBE", "/env/ffprobe")
    assert cli.resolve_ffprobe(None, which=lambda b: None) == "/env/ffprobe"


def test_resolve_ffprobe_derives_sibling_of_ffmpeg(monkeypatch):
    """ffprobe не в PATH → берём соседний бинарь по каталогу резолвнутого ffmpeg.

    Путь нативный для ОС теста (на Windows Path сам разберёт D:\\...\\ffmpeg.exe)."""
    monkeypatch.delenv("RENDER_FFPROBE", raising=False)
    got = cli.resolve_ffprobe(
        None, ffmpeg="/opt/ffmpeg/bin/ffmpeg",
        which=lambda b: None,
        is_file=lambda p: str(p) == "/opt/ffmpeg/bin/ffprobe",
    )
    assert got == "/opt/ffmpeg/bin/ffprobe"               # рядом с ffmpeg


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


# ---------------------------------------------- префлайт энкодера: доступность + фоллбэк

def _tmp_manifests_with_one(tmp_path):
    m = tmp_path / "manifests"
    m.mkdir()
    (m / "v.json").write_text(_manifest().model_dump_json(), encoding="utf-8")
    return m


def test_render_unavailable_encoder_no_fallback_errors_before_render(monkeypatch, tmp_path):
    """Недоступный энкодер + --no-fallback → внятная ошибка ДО рендера (render_crop не зовётся)."""
    manifests = _tmp_manifests_with_one(tmp_path)
    monkeypatch.setattr(cli, "probe_encoder", lambda codec, **k: False)   # ничего не доступно
    called = []
    monkeypatch.setattr(cli, "render_crop", lambda manifest, **k: called.append(1) or [])

    with pytest.raises(cli.RenderError) as e:
        cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, profile="av1", fallback=False)

    assert "av1" in str(e.value).lower() and "не поддерживается" in str(e.value)
    assert called == []                                    # рендер не начался


def test_render_fallback_switches_to_available_profile(monkeypatch, tmp_path, capsys):
    """av1 недоступен, hevc доступен → фоллбэк на hevc с уведомлением, рендер идёт на hevc."""
    manifests = _tmp_manifests_with_one(tmp_path)
    # av1_amf недоступен, остальное доступно
    monkeypatch.setattr(cli, "probe_encoder", lambda codec, **k: "av1" not in codec)
    seen = {}
    monkeypatch.setattr(cli, "render_crop", lambda manifest, **k: seen.update(k) or [])

    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, profile="av1", fallback=True)

    assert seen["profile"] == "hevc"                       # переключились на доступный
    out = capsys.readouterr().out
    assert "фоллбэк" in out and "hevc" in out


def test_render_fallback_none_available_errors(monkeypatch, tmp_path):
    """Ни один энкодер не доступен → ошибка (пробовал всю цепочку)."""
    manifests = _tmp_manifests_with_one(tmp_path)
    monkeypatch.setattr(cli, "probe_encoder", lambda codec, **k: False)

    with pytest.raises(cli.RenderError):
        cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, profile="av1", fallback=True)


def test_render_no_fallback_flag_parsed():
    p = cli._build_parser()
    assert p.parse_args(["render", "--no-fallback"]).no_fallback is True
    assert p.parse_args(["render"]).no_fallback is False


def test_menu_profiles_marks_unavailable(monkeypatch, capsys):
    """menu --profiles помечает недоступные на этой машине энкодеры."""
    # av1 недоступен на этом GPU, hevc/h264 доступны
    monkeypatch.setattr(cli, "probe_encoder", lambda codec, **k: "av1" not in codec)
    monkeypatch.setattr(cli, "_cli_resolve_ffmpeg", lambda flag, **k: "ffmpeg")

    cli.main(["menu", "--profiles", "--root", str(REPO_ROOT)])

    out = capsys.readouterr().out
    # строка av1 помечена недоступной, hevc/h264 — нет
    av1_line = next(ln for ln in out.splitlines() if ln.startswith("av1"))
    hevc_line = next(ln for ln in out.splitlines() if ln.startswith("hevc"))
    assert "НЕДОСТУПНО" in av1_line
    assert "НЕДОСТУПНО" not in hevc_line


def test_render_ffmpeg_from_env(monkeypatch, tmp_path):
    """RENDER_FFMPEG задаёт путь к ffmpeg без флага (симметрично RENDER_ENCODER)."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest().model_dump_json(), encoding="utf-8")
    monkeypatch.setenv("RENDER_FFMPEG", "/opt/ffmpeg/bin/ffmpeg")

    seen = {}
    monkeypatch.setattr(cli, "render_crop", lambda manifest, **k: seen.update(k) or [])
    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT)
    assert seen["ffmpeg"] == "/opt/ffmpeg/bin/ffmpeg"


def test_render_ffmpeg_flag_beats_env(monkeypatch, tmp_path):
    """Явный --ffmpeg приоритетнее RENDER_FFMPEG."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest().model_dump_json(), encoding="utf-8")
    monkeypatch.setenv("RENDER_FFMPEG", "/opt/ffmpeg/bin/ffmpeg")

    seen = {}
    monkeypatch.setattr(cli, "render_crop", lambda manifest, **k: seen.update(k) or [])
    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, ffmpeg="/custom/ffmpeg")
    assert seen["ffmpeg"] == "/custom/ffmpeg"


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
    monkeypatch.chdir(tmp_path)   # «inputs» приёма — под tmp, не засорять реальный inputs/ репо
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(cli, "_stage_extract_audio",
                        lambda *a, **k: pytest.fail("конвейер не должен добраться до extract"))

    rc = cli.main(["run", str(video), "--ffmpeg", "ffmpeg"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err


# ------------------------------------------------------------------ шпаргалка (без аргументов)

def test_no_args_prints_status_and_exits_0(capsys):
    """autoreels без аргументов показывает status (не cheatsheet) и выходит с 0."""
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    # Status-вывод содержит counts папок
    assert "inputs" in out.lower()
    assert "manifests" in out.lower()


def test_no_args_mentions_folders(capsys):
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "inputs/" in out
    assert "manifests/" in out
    assert "reels-out/" in out


def test_no_args_shows_next_step_hint(capsys):
    """autoreels без аргументов выводит подсказку следующего шага."""
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    # Либо hint (arl go / arl r) либо ссылка на help
    assert "arl" in out.lower() or "help" in out.lower() or "autoreels" in out


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

def test_no_args_includes_status_section(capsys):
    """autoreels без аргументов включает status-вывод (inputs, manifests)."""
    cli.main([])
    out = capsys.readouterr().out
    assert "status" in out.lower() or "inputs" in out.lower()


def test_no_args_help_command_still_works(capsys):
    """autoreels help по-прежнему выводит расширенную справку включая --all."""
    cli.main(["help"])
    out = capsys.readouterr().out
    assert "--all" in out


def test_help_command_has_workflow_steps(capsys):
    """autoreels help содержит пронумерованный цикл работы."""
    cli.main(["help"])
    out = capsys.readouterr().out
    assert "1." in out and "4." in out


def test_help_mentions_inputs_archive(capsys):
    cli.main(["help"])
    out = capsys.readouterr().out
    assert "inputs-archive/" in out


def test_help_mentions_mac_and_system(capsys):
    """autoreels help содержит пометки Mac / системник."""
    cli.main(["help"])
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


# ------------------------------------------------------------------ autoreels help: полное содержание

def _help_out(capsys):
    cli.main(["help"])
    return capsys.readouterr().out


def test_help_lists_all_six_commands(capsys):
    out = _help_out(capsys)
    for cmd in ("status", "calibrate", "run", "render", "help"):
        assert cmd in out, f"команда '{cmd}' не найдена в help"


def test_help_lists_key_flags(capsys):
    out = _help_out(capsys)
    assert "--all" in out
    assert "--encoder" in out
    assert "--setup" in out
    assert "--ffmpeg" in out


def test_help_has_4_workflow_stages(capsys):
    out = _help_out(capsys)
    assert "1." in out and "4." in out


def test_help_workflow_has_run_and_render_commands(capsys):
    out = _help_out(capsys)
    # help упоминает run и render (напрямую или через arl go / arl r)
    assert "run" in out
    assert "render" in out


def test_help_mentions_groq(capsys):
    out = _help_out(capsys)
    assert "Groq" in out or "groq" in out.lower()


def test_help_mentions_chunking(capsys):
    out = _help_out(capsys)
    assert "чанк" in out.lower() or "chunk" in out.lower()


def test_help_mentions_autocrop(capsys):
    out = _help_out(capsys)
    assert "автокроп" in out.lower() or "auto" in out.lower()


def test_help_mentions_too_long(capsys):
    out = _help_out(capsys)
    assert "59" in out or "too_long" in out or "обрезаются" in out.lower()


def test_help_lists_all_folders(capsys):
    out = _help_out(capsys)
    for folder in ("inputs/", "inputs-archive/", "manifests/", "reels-out/", "calibrations/"):
        assert folder in out, f"папка '{folder}' не найдена в help"


def test_help_mentions_alias(capsys):
    out = _help_out(capsys)
    assert "alias" in out or "ar=" in out or "ar " in out.lower()


def test_help_mentions_both_machines(capsys):
    out = _help_out(capsys)
    assert "Mac" in out or "mac" in out.lower()
    assert "системник" in out.lower() or "windows" in out.lower()


def test_help_mentions_groq_region_issue(capsys):
    out = _help_out(capsys)
    assert "регион" in out.lower() or "region" in out.lower() or "недоступен" in out.lower()


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


def test_calibrate_frame_at_flag_parsed():
    """--frame-at регистрируется и парсится ('50%' / секунда)."""
    p = cli._build_parser()
    assert p.parse_args(["calibrate", "v.mp4", "--frame-at", "50%"]).frame_at == "50%"
    assert p.parse_args(["calibrate", "v.mp4", "--frame-at", "120"]).frame_at == "120"
    assert p.parse_args(["calibrate", "v.mp4"]).frame_at is None      # дефолт


def test_calibrate_dispatch_passes_frame_at(monkeypatch, tmp_path):
    """Диспетчер прокидывает --frame-at в cmd_calibrate."""
    seen = {}
    monkeypatch.setattr(cli, "_cli_resolve_ffmpeg", lambda flag, **k: "ffmpeg")
    monkeypatch.setattr(cli, "resolve_ffprobe", lambda flag, **k: "ffprobe")
    monkeypatch.setattr(cli, "cmd_calibrate",
                        lambda video, **k: seen.update(k) or (tmp_path / "c.json"))
    monkeypatch.setattr(cli, "_warn_if_manifest_stale", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_commit_push_calibrations", lambda *, root: None)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    cli.main(["calibrate", str(video), "--frame-at", "50%"])

    assert seen.get("frame_at") == "50%"


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


def test_calibrate_all_offers_recalibration_for_manual(tmp_path, monkeypatch, capsys):
    """Видео с ручной калибровкой ТОЖЕ предлагается (браузер доступен из меню); Enter — оставить.

    Раньше manual пропускался молча → «Калибровать всё» при всех откалиброванных видео
    не делало ничего видимого. Теперь спрашивает (kind='manual'), по умолчанию оставляет."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    video = inputs / "manual.mp4"
    video.write_bytes(b"x")
    _save_manual_cal(tmp_path, video)

    asked = []
    recalibrated = []
    monkeypatch.setattr(cli, "_ask_batch_action",
                        lambda name, kind: asked.append((name, kind)) or "п")   # оставить
    monkeypatch.setattr(cli, "cmd_calibrate", lambda v, **k: recalibrated.append(v))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert asked == [("manual.mp4", "manual")]     # предложено (не пропущено молча)
    assert recalibrated == []                       # но по умолчанию (Enter/п) не перекалибровали
    out = capsys.readouterr().out
    assert "оставлено" in out                        # видна сводка-реакция


def test_calibrate_all_recalibrates_manual_when_chosen(tmp_path, monkeypatch):
    """Ручную калибровку можно ПЕРЕзапустить из --all (к → браузер) — фикс «ничего не происходит»."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    video = inputs / "manual.mp4"
    video.write_bytes(b"x")
    _save_manual_cal(tmp_path, video)

    recalibrated = []
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: "к")
    monkeypatch.setattr(cli, "cmd_calibrate", lambda v, **k: recalibrated.append(Path(v).name))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert recalibrated == ["manual.mp4"]           # браузер-калибратор запущен


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
    """Пачка: спрашивает про КАЖДОЕ видео (ручное/некалиброванное/автокроп) — с нужным kind."""
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

    asked = {}
    monkeypatch.setattr(cli, "_ask_batch_action",
                        lambda name, kind: asked.update({name: kind}) or "п")
    monkeypatch.setattr(cli, "_probe_frame_size_for_auto", lambda v, **k: (3840, 2160))

    cli.cmd_calibrate_batch(root=tmp_path, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert asked == {"manual.mp4": "manual", "raw.mp4": "none", "autocrop.mp4": "auto"}


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


def test_ask_batch_action_manual_offers_recalibrate_enter_keeps(monkeypatch):
    """Для kind='manual' промпт предлагает калибровать заново; Enter (пусто) → оставить (п)."""
    inputs_given = []
    monkeypatch.setattr("builtins.input", lambda prompt: inputs_given.append(prompt) or "")
    result = cli._ask_batch_action("video.mp4", "manual")
    assert "уже есть" in inputs_given[0] and "заново" in inputs_given[0]
    assert result == "п"                             # пустой ввод (Enter) = оставить


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
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path, transcripts_dir=tmp_path)


# -------------------------------------------------- install-aliases

def test_install_aliases_registered_as_subcommand():
    p = cli._build_parser()
    args = p.parse_args(["install-aliases", "--dry-run"])
    assert args.cmd == "install-aliases"


def test_install_aliases_dry_run_prints_source_line(tmp_path, capsys):
    profile = tmp_path / ".zshrc"
    profile.write_text("", encoding="utf-8")
    aliases = tmp_path / "aliases.sh"
    aliases.write_text("# autoreels aliases\n", encoding="utf-8")

    rc = cli.cmd_install_aliases(profile_path=profile, aliases_path=aliases, dry_run=True)

    out = capsys.readouterr().out
    assert rc == 0
    assert "source" in out
    assert str(aliases) in out


def test_install_aliases_appends_source_line(tmp_path):
    profile = tmp_path / ".zshrc"
    profile.write_text("export PATH=$PATH\n", encoding="utf-8")
    aliases = tmp_path / "aliases.sh"
    aliases.write_text("# autoreels aliases\n", encoding="utf-8")

    cli.cmd_install_aliases(profile_path=profile, aliases_path=aliases, dry_run=False, confirm=False)

    content = profile.read_text(encoding="utf-8")
    assert f"source {aliases}" in content


def test_install_aliases_idempotent(tmp_path):
    profile = tmp_path / ".zshrc"
    aliases = tmp_path / "aliases.sh"
    aliases.write_text("# autoreels aliases\n", encoding="utf-8")
    source_line = f"source {aliases}"
    profile.write_text(f"export PATH=$PATH\n{source_line}\n", encoding="utf-8")

    cli.cmd_install_aliases(profile_path=profile, aliases_path=aliases, dry_run=False, confirm=False)

    content = profile.read_text(encoding="utf-8")
    assert content.count(source_line) == 1, "source-строка добавлена дважды"


def test_install_aliases_missing_aliases_file_errors(tmp_path, capsys):
    profile = tmp_path / ".zshrc"
    profile.write_text("", encoding="utf-8")
    aliases = tmp_path / "aliases.sh"  # не создаём

    rc = cli.cmd_install_aliases(profile_path=profile, aliases_path=aliases, dry_run=False, confirm=False)

    assert rc != 0
    err = capsys.readouterr().err
    assert "aliases.sh" in err or "не найден" in err.lower()


def test_install_aliases_main_dispatch_dry_run(tmp_path, capsys, monkeypatch):
    profile = tmp_path / ".zshrc"
    profile.write_text("", encoding="utf-8")
    aliases = tmp_path / "aliases.sh"
    aliases.write_text("# autoreels aliases\n", encoding="utf-8")

    monkeypatch.setattr(cli, "_detect_shell_profile", lambda: profile)
    monkeypatch.setattr(cli, "_find_aliases_sh", lambda: aliases)

    rc = cli.main(["install-aliases", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "source" in out


# ---------------------- install-aliases: POSIX-путь на Windows + починка битой записи

def test_posix_path_converts_windows_path():
    """Windows-путь → POSIX (Git Bash/MSYS): D:\\autoreels\\aliases.sh → /d/autoreels/aliases.sh."""
    assert cli._posix_path_for_shell("D:\\autoreels\\aliases.sh") == "/d/autoreels/aliases.sh"
    assert cli._posix_path_for_shell("C:/proj/aliases.sh") == "/c/proj/aliases.sh"


def test_posix_path_leaves_unix_path_untouched():
    """Mac/Linux путь (POSIX) не трогаем."""
    assert cli._posix_path_for_shell("/Users/d/autoreels/aliases.sh") == "/Users/d/autoreels/aliases.sh"


def test_install_aliases_source_line_is_posix_for_windows_path(tmp_path, capsys):
    """Записываемая source-строка — POSIX, даже если resolve() вернул Windows-путь."""
    profile = tmp_path / ".bashrc"; profile.write_text("", encoding="utf-8")
    aliases = tmp_path / "aliases.sh"; aliases.write_text("#\n", encoding="utf-8")

    class _WinPath:
        def resolve(self): return "D:\\autoreels\\aliases.sh"
        def is_file(self): return True

    cli.cmd_install_aliases(profile_path=profile, aliases_path=_WinPath(), confirm=False)

    content = profile.read_text(encoding="utf-8")
    assert "source /d/autoreels/aliases.sh" in content    # POSIX, без backslashes
    assert "\\" not in content


def test_install_aliases_fixes_broken_windows_entry(tmp_path, capsys):
    """Битая запись (Windows-путь с backslashes) обнаруживается и ЗАМЕНЯЕТСЯ корректной."""
    profile = tmp_path / ".bashrc"
    profile.write_text("export PATH=$PATH\nsource D:\\autoreels\\aliases.sh\n", encoding="utf-8")
    aliases = tmp_path / "aliases.sh"; aliases.write_text("#\n", encoding="utf-8")
    source_line = f"source {aliases}"

    rc = cli.cmd_install_aliases(profile_path=profile, aliases_path=aliases, confirm=False)

    assert rc == 0
    content = profile.read_text(encoding="utf-8")
    assert source_line in content                          # корректная строка есть
    assert "D:\\autoreels" not in content                  # битая убрана
    assert content.count("aliases.sh") == 1                # ровно одна запись
    assert "исправлена" in capsys.readouterr().out


def test_install_aliases_detects_backslash_eaten_entry_not_already_installed(tmp_path, capsys):
    """Реальный случай пользователя: backslashes уже съедены (source D:autoreelsaliases.sh).
    Это НЕ «уже установлено» — обнаружить как битую и починить."""
    profile = tmp_path / ".bashrc"
    profile.write_text("source D:autoreelsaliases.sh\n", encoding="utf-8")
    aliases = tmp_path / "aliases.sh"; aliases.write_text("#\n", encoding="utf-8")

    cli.cmd_install_aliases(profile_path=profile, aliases_path=aliases, confirm=False)

    out = capsys.readouterr().out
    assert "уже установлено" not in out
    assert "исправлена" in out
    content = profile.read_text(encoding="utf-8")
    assert f"source {aliases}" in content
    assert "D:autoreelsaliases.sh" not in content          # битая строка убрана


# -------------------------------------------------- render: ffmpeg из конфига

def test_render_config_accepts_ffmpeg_field():
    """RenderConfig принимает поле ffmpeg."""
    from autoreels.core.config import load_render_config
    cfg = load_render_config(REPO_ROOT / "config" / "render.yaml")
    assert hasattr(cfg, "ffmpeg")


def test_render_config_ffmpeg_default_is_ffmpeg():
    """По умолчанию RenderConfig.ffmpeg == 'ffmpeg'."""
    from autoreels.core.config import load_render_config
    cfg = load_render_config(REPO_ROOT / "config" / "render.yaml")
    assert cfg.ffmpeg == "ffmpeg"


def test_cmd_render_uses_config_ffmpeg_when_no_flag(monkeypatch, tmp_path):
    """cmd_render без явного --ffmpeg берёт путь из render_cfg.ffmpeg."""
    from autoreels.core.config import RenderConfig, load_render_config
    from autoreels.core.models import Manifest

    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest(source="v.mp4").model_dump_json(), encoding="utf-8")
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "v.mp4").write_bytes(b"x")

    ffmpeg_used = []

    def _fake_render(manifest, *, inputs_dir, out_dir, render_cfg, ffmpeg, encoder, profile, subtitles_cfg):
        ffmpeg_used.append(ffmpeg)
        return []

    monkeypatch.setattr(cli, "render_crop", _fake_render)

    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, ffmpeg=None)

    assert ffmpeg_used, "render_crop не был вызван"
    # Должен использоваться путь из конфига (дефолт "ffmpeg"), а не None
    assert ffmpeg_used[0] is not None
    assert ffmpeg_used[0] == "ffmpeg"


def test_cmd_render_explicit_ffmpeg_overrides_config(monkeypatch, tmp_path):
    """Явный ffmpeg аргумент перекрывает значение из конфига."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest(source="v.mp4").model_dump_json(), encoding="utf-8")
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "v.mp4").write_bytes(b"x")

    ffmpeg_used = []

    def _fake_render(manifest, *, inputs_dir, out_dir, render_cfg, ffmpeg, encoder, profile, subtitles_cfg):
        ffmpeg_used.append(ffmpeg)
        return []

    monkeypatch.setattr(cli, "render_crop", _fake_render)

    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, ffmpeg="/custom/ffmpeg")

    assert ffmpeg_used[0] == "/custom/ffmpeg"


# -------------------------------------------------- ar без аргументов: status + hint

def test_no_args_shows_status_output(capsys):
    """autoreels без аргументов выводит status (inputs/, manifests/ и т.п.)."""
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "inputs/" in out and "manifests/" in out


def test_no_args_main_exits_0(capsys):
    rc = cli.main([])
    assert rc == 0


def test_no_args_includes_status_info(capsys):
    """autoreels без аргументов выводит информацию о состоянии проекта."""
    cli.main([])
    out = capsys.readouterr().out
    # Должно быть что-то из status (inputs/ или manifests/)
    assert "inputs" in out.lower() or "status" in out.lower() or "autoreels" in out


def test_next_hint_with_videos(tmp_path):
    """_next_hint возвращает 'arl go' когда есть видео в inputs/."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.mp4").write_bytes(b"x")

    hint = cli._next_hint(root=tmp_path)
    assert hint is not None
    assert "arl go" in hint


def test_next_hint_with_manifests(tmp_path):
    """_next_hint возвращает 'arl r' когда есть манифесты в manifests/."""
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "a.json").write_bytes(b"{}")

    hint = cli._next_hint(root=tmp_path)
    assert hint is not None
    assert "arl r" in hint


def test_next_hint_empty_project(tmp_path):
    """_next_hint возвращает None или пустую подсказку когда ничего нет."""
    hint = cli._next_hint(root=tmp_path)
    # Пустой проект — нет срочного следующего шага
    assert hint is None or isinstance(hint, str)


def test_next_hint_videos_take_priority_over_manifests(tmp_path):
    """Если есть и видео и манифесты — подсказка про arl go (run первым)."""
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "a.mp4").write_bytes(b"x")
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "b.json").write_bytes(b"{}")

    hint = cli._next_hint(root=tmp_path)
    assert hint is not None
    assert "go" in hint


def test_no_args_shows_hint_with_videos(capsys, tmp_path, monkeypatch):
    """autoreels без аргументов показывает 'arl go' когда есть видео."""
    monkeypatch.chdir(tmp_path)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.mp4").write_bytes(b"x")

    # Нужен config dir чтобы cmd_status не упал на манифестах
    cli.main([])
    out = capsys.readouterr().out
    assert "arl go" in out


def test_no_args_shows_hint_with_manifests(capsys, tmp_path, monkeypatch):
    """autoreels без аргументов показывает 'arl r' когда есть манифесты без видео."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "a.json").write_bytes(
        _manifest(source="a.mp4").model_dump_json().encode()
    )

    cli.main([])
    out = capsys.readouterr().out
    assert "arl r" in out


# -------------------------------------------------- приём исходника: путь вне inputs/

def test_ingest_copies_external_path_into_inputs(tmp_path):
    """Путь вне inputs/ копируется в inputs/<имя>, оригинал не трогается."""
    ext = tmp_path / "Downloads"
    ext.mkdir()
    src = ext / "lecture.mp4"
    src.write_bytes(b"video-bytes")
    inputs = tmp_path / "inputs"

    result = cli._ingest_source(src, inputs)

    assert result == inputs / "lecture.mp4"
    assert result.read_bytes() == b"video-bytes"     # скопировано
    assert src.exists()                               # оригинал на месте


def test_ingest_path_already_inside_inputs_is_noop(tmp_path):
    """Файл уже в inputs/ — возвращается как есть, без копии-дубля."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    src = inputs / "v.mp4"
    src.write_bytes(b"x")

    result = cli._ingest_source(src, inputs)

    assert result.resolve() == src.resolve()
    assert sorted(p.name for p in inputs.iterdir()) == ["v.mp4"]   # нет дубля


def test_ingest_nonexistent_path_raises_clear_error(tmp_path):
    """Несуществующий путь → внятная ошибка (не краш)."""
    with pytest.raises(FileNotFoundError) as exc:
        cli._ingest_source(tmp_path / "ghost.mp4", tmp_path / "inputs")
    assert "ghost.mp4" in str(exc.value)


def test_ingest_non_video_extension_raises(tmp_path):
    """Не видео (по расширению) → внятная ошибка."""
    doc = tmp_path / "notes.txt"
    doc.write_text("hello", encoding="utf-8")
    with pytest.raises(cli.RunError) as exc:
        cli._ingest_source(doc, tmp_path / "inputs")
    assert "notes.txt" in str(exc.value)


def test_ingest_name_collision_different_content_raises(tmp_path):
    """В inputs/ уже другой файл с тем же именем → ошибка коллизии, не тихая перезапись."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "v.mp4").write_bytes(b"OTHER-content")
    ext = tmp_path / "elsewhere"
    ext.mkdir()
    src = ext / "v.mp4"
    src.write_bytes(b"NEW-content")

    with pytest.raises(cli.RunError) as exc:
        cli._ingest_source(src, inputs)
    assert "v.mp4" in str(exc.value)
    assert (inputs / "v.mp4").read_bytes() == b"OTHER-content"   # не перезаписан


def test_ingest_same_content_already_in_inputs_reuses(tmp_path):
    """В inputs/ уже тот же файл (то же содержимое) → переиспользуем, без ошибки."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "v.mp4").write_bytes(b"same-content")
    ext = tmp_path / "elsewhere"
    ext.mkdir()
    src = ext / "v.mp4"
    src.write_bytes(b"same-content")

    result = cli._ingest_source(src, inputs)

    assert result == inputs / "v.mp4"
    assert result.read_bytes() == b"same-content"


def test_ingest_expands_user_and_resolves(tmp_path):
    """Путь-директория → внятная ошибка (не видео-файл)."""
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises((cli.RunError, FileNotFoundError)):
        cli._ingest_source(d, tmp_path / "inputs")


def test_run_dispatch_ingests_external_path(monkeypatch, tmp_path):
    """main('run <внешний путь>') прогоняет приём: копирует в inputs/ и зовёт cmd_run с ним."""
    monkeypatch.chdir(tmp_path)
    ext = tmp_path / "Downloads"
    ext.mkdir()
    src = ext / "clip.mp4"
    src.write_bytes(b"vid")

    seen = {}

    def _fake_cmd_run(video, **kwargs):
        seen["video"] = Path(video)
        return tmp_path / "manifests" / "clip.json"

    monkeypatch.setattr(cli, "cmd_run", _fake_cmd_run)

    rc = cli.main(["run", str(src)])

    assert rc == 0
    assert seen["video"] == (tmp_path / "inputs" / "clip.mp4")
    assert (tmp_path / "inputs" / "clip.mp4").exists()


def test_run_dispatch_bad_path_returns_error(monkeypatch, tmp_path, capsys):
    """main('run <несуществующий>') → код 1 + внятное сообщение, не traceback."""
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["run", str(tmp_path / "nope.mp4")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "nope.mp4" in err


# -------------------------------------------------- меню: парсинг выбора

def test_menu_action_maps_digits_to_actions():
    """Каждая цифра меню → свой action-токен (стабильная нумерация)."""
    assert cli._menu_action("1") == "go"
    assert cli._menu_action("2") == "render"
    assert cli._menu_action("3") == "status"
    assert cli._menu_action("4") == "calibrate"
    assert cli._menu_action("5") == "path"
    assert cli._menu_action("6") == "transcribe"
    assert cli._menu_action("7") == "resume"
    assert cli._menu_action("8") == "help"
    assert cli._menu_action("0") == "quit"


def test_menu_action_accepts_quit_aliases():
    """q / exit / quit / выход (в любом регистре) → quit."""
    for c in ("q", "Q", "exit", "quit", "выход", "ВЫХОД"):
        assert cli._menu_action(c) == "quit"


def test_menu_action_strips_whitespace():
    """Пробелы вокруг цифры игнорируются."""
    assert cli._menu_action("  1  ") == "go"


def test_menu_action_invalid_returns_none():
    """Пустой ввод / вне диапазона / мусор → None (меню повторит запрос)."""
    for c in ("", "99", "abc", "  ", "12"):
        assert cli._menu_action(c) is None


# -------------------------------------------------- меню: состояние и рекомендация

def test_menu_state_counts_filesystem(tmp_path):
    """_menu_state считает inputs/manifests/reels-out."""
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "a.mp4").write_bytes(b"x")
    (tmp_path / "inputs" / "b.mp4").write_bytes(b"x")
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "reels-out" / "a").mkdir(parents=True)

    st = cli._menu_state(root=tmp_path)
    assert st == {"inputs": 2, "manifests": 1, "rendered": 1}


def test_menu_state_empty_project(tmp_path):
    """Пустой проект → все нули, без падения."""
    assert cli._menu_state(root=tmp_path) == {"inputs": 0, "manifests": 0, "rendered": 0}


def test_recommended_action_prefers_inputs():
    """Есть видео → рекомендуем go (даже если есть манифесты)."""
    assert cli._recommended_action({"inputs": 2, "manifests": 3, "rendered": 0}) == "go"


def test_recommended_action_render_when_only_manifests():
    """Видео нет, манифесты есть → рекомендуем render."""
    assert cli._recommended_action({"inputs": 0, "manifests": 3, "rendered": 0}) == "render"


def test_recommended_action_none_when_empty():
    """Ни видео, ни манифестов → нет рекомендации."""
    assert cli._recommended_action({"inputs": 0, "manifests": 0, "rendered": 5}) is None


# -------------------------------------------------- меню: рендер

def test_menu_render_shows_state_header(tmp_path):
    """Шапка меню показывает счётчики состояния."""
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "a.mp4").write_bytes(b"x")
    (tmp_path / "inputs" / "b.mp4").write_bytes(b"x")

    out = cli._menu_render(root=tmp_path)
    assert "inputs: 2" in out
    assert "манифест" in out.lower()


def test_menu_render_lists_all_items(tmp_path):
    """Меню перечисляет все пункты с их цифрами."""
    out = cli._menu_render(root=tmp_path)
    for num in ("1", "2", "3", "4", "5", "6", "7", "8", "0"):
        assert f"{num})" in out
    assert "Выход" in out


def test_menu_render_has_resume_item(tmp_path):
    """В меню есть пункт «Продолжить прерванное»."""
    out = cli._menu_render(root=tmp_path)
    assert "родолж" in out


# ------------------------------------------------- профиль рендера (машинная настройка)

def _tmp_project_with_render_yaml(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "render.yaml").write_text(
        (REPO_ROOT / "config" / "render.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_set_render_profile_writes_local_yaml(tmp_path):
    """set_render_profile пишет encoder.profile в render.local.yaml (машинная настройка)."""
    import yaml
    root = _tmp_project_with_render_yaml(tmp_path)
    path = cli.set_render_profile("av1", root=root)
    assert path == root / "config" / "render.local.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["encoder"]["profile"] == "av1"


def test_set_render_profile_preserves_existing_keys(tmp_path):
    """Смена профиля не затирает уже заданный ffmpeg (deep-merge в encoder.profile)."""
    import yaml
    root = _tmp_project_with_render_yaml(tmp_path)
    local = root / "config" / "render.local.yaml"
    local.write_text("ffmpeg: D:/ffmpeg/bin/ffmpeg.exe\n", encoding="utf-8")
    cli.set_render_profile("h264", root=root)
    data = yaml.safe_load(local.read_text(encoding="utf-8"))
    assert data["ffmpeg"] == "D:/ffmpeg/bin/ffmpeg.exe"    # сохранён
    assert data["encoder"]["profile"] == "h264"


def test_set_render_profile_invalid_raises(tmp_path):
    from autoreels.core.config import ConfigError
    root = _tmp_project_with_render_yaml(tmp_path)
    with pytest.raises(ConfigError, match="профиль"):
        cli.set_render_profile("mpeg2", root=root)


def test_render_uses_saved_profile(tmp_path):
    """Сохранённый профиль подхватывается конфигом рендера (render.local.yaml deep-merge)."""
    from autoreels.core.config import load_render_config
    root = _tmp_project_with_render_yaml(tmp_path)
    cli.set_render_profile("av1", root=root)
    cfg = load_render_config(root / "config" / "render.yaml")
    assert cfg.encoder.profile == "av1"                   # рендер возьмёт этот профиль
    assert cli._current_render_profile(root=root) == "av1"


def test_menu_set_profile_cli_writes_and_confirms(tmp_path, capsys):
    """`autoreels menu --set-profile hevc` пишет профиль и подтверждает."""
    root = _tmp_project_with_render_yaml(tmp_path)
    rc = cli.main(["menu", "--set-profile", "h264", "--root", str(root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "h264" in out and "профиль" in out.lower()
    assert cli._current_render_profile(root=root) == "h264"


def test_menu_header_shows_profile_and_ffmpeg(tmp_path, monkeypatch):
    """Шапка меню показывает текущий профиль и ffmpeg (видно, чем рендерит)."""
    monkeypatch.setenv("RENDER_PROFILE", "av1")
    out = cli._menu_render(root=tmp_path)
    assert "профиль av1" in out
    assert "ffmpeg" in out.lower()


def test_menu_item_profile_shows_current(tmp_path, monkeypatch):
    """Пункт профиля в меню показывает текущий профиль в подписи."""
    monkeypatch.setenv("RENDER_PROFILE", "h264")
    out = cli._menu_render(root=tmp_path)
    assert "Профиль рендера: h264" in out


def test_menu_action_9_is_profile():
    """Цифра 9 → action-токен profile (стабильная карта)."""
    assert cli._menu_action("9") == "profile"


def test_status_header_shows_machine_settings(tmp_path, monkeypatch, capsys):
    """Шапка status показывает машинные настройки: профиль | ffmpeg."""
    monkeypatch.setenv("RENDER_PROFILE", "hevc")
    cli.cmd_status(root=tmp_path)
    out = capsys.readouterr().out
    assert "профиль hevc" in out
    assert "ffmpeg" in out.lower()


# -------------------------------------------------- resume: продолжить прерванное

def test_resume_reports_interrupted_downloads(tmp_path, capsys, monkeypatch):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "big.mp4.part").write_bytes(b"partial")
    monkeypatch.setattr(cli, "cmd_render", lambda **k: [])
    cli.cmd_resume(root=tmp_path)
    out = capsys.readouterr().out
    assert "big.mp4.part" in out
    assert "прерван" in out.lower() or "докач" in out.lower()


def test_resume_renders_pending_manifests(tmp_path, monkeypatch):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "v.json").write_text(_manifest(source="v.mp4").model_dump_json(), encoding="utf-8")
    called = {}
    monkeypatch.setattr(cli, "cmd_render", lambda **k: called.setdefault("rendered", True) or [])
    cli.cmd_resume(root=tmp_path)
    assert called.get("rendered")


def test_resume_nothing_to_do(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "cmd_render", lambda **k: pytest.fail("render не нужен — нечего"))
    cli.cmd_resume(root=tmp_path)
    assert "нечего продолжать" in capsys.readouterr().out.lower()


def test_resume_subcommand_registered():
    args = cli._build_parser().parse_args(["resume"])
    assert args.cmd == "resume"


def test_menu_render_has_transcribe_item(tmp_path):
    """В меню есть пункт транскрибации для контента."""
    out = cli._menu_render(root=tmp_path)
    assert "ранскриб" in out


def test_menu_item5_text_is_clearer(tmp_path):
    """Пункт 5 понятно объясняет, что принимает (ссылка/URL/Я.Диск/YouTube/файл)."""
    out = cli._menu_render(root=tmp_path)
    line = next(l for l in out.splitlines() if l.strip().startswith("5)") or ") 5)" in l or "5)" in l)
    assert "ссылк" in line.lower() or "пут" in line.lower()
    assert "Яндекс" in line or "YouTube" in line or "URL" in line


# -------------------------------------------------- меню: классификация источника

def test_classify_source_detects_yandex():
    assert cli._classify_source("https://disk.yandex.ru/i/x") == "yandex"
    assert cli._classify_source("https://yadi.sk/i/x") == "yandex"


def test_classify_source_detects_url():
    assert cli._classify_source("https://youtu.be/x") == "url"
    assert cli._classify_source("https://example.com/v.mp4") == "url"


def test_classify_source_detects_path():
    for p in ("/Users/danny/v.mp4", "inputs/v.mp4", "~/Downloads/v.mp4", "v.mp4"):
        assert cli._classify_source(p) == "path", p


def test_classify_label_yandex():
    assert "Яндекс" in cli._classify_label("https://disk.yandex.ru/i/x")


def test_classify_label_url_mentions_ytdlp():
    lbl = cli._classify_label("https://youtu.be/x")
    assert "URL" in lbl or "yt-dlp" in lbl


def test_classify_label_path():
    assert "файл" in cli._classify_label("inputs/v.mp4").lower()


def test_menu_classify_cli_prints_label(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.main(["menu", "--classify", "https://disk.yandex.ru/i/abc"])
    assert "Яндекс" in capsys.readouterr().out


def test_menu_render_highlights_recommended_with_videos(tmp_path):
    """Есть видео → пункт «Обработать видео» подсвечен маркером ▶."""
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "a.mp4").write_bytes(b"x")

    out = cli._menu_render(root=tmp_path, platform="darwin")
    line = next(l for l in out.splitlines() if "Обработать видео" in l)
    assert "▶" in line


def test_menu_render_highlights_render_when_manifests(tmp_path):
    """Видео нет, манифесты есть → подсвечен пункт рендера, не обработки."""
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "a.json").write_text("{}", encoding="utf-8")

    out = cli._menu_render(root=tmp_path, platform="darwin")
    render_line = next(l for l in out.splitlines() if "рендер" in l.lower() or "Отрендер" in l)
    go_line = next(l for l in out.splitlines() if "Обработать видео" in l)
    assert "▶" in render_line
    assert "▶" not in go_line


def test_menu_render_win32_uses_ascii_border(tmp_path):
    """На win32 рамки меню из ASCII — нет Unicode box-drawing chars (═, ─)."""
    out = cli._menu_render(root=tmp_path, platform="win32")
    assert "═" not in out
    assert "─" not in out


def test_menu_render_win32_uses_ascii_marker(tmp_path):
    """На win32 маркер рекомендуемого пункта ASCII '>' а не '▶'."""
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "a.mp4").write_bytes(b"x")
    out = cli._menu_render(root=tmp_path, platform="win32")
    assert "▶" not in out
    line = next(l for l in out.splitlines() if "Обработать видео" in l)
    assert ">" in line


def test_menu_render_win32_still_has_all_items(tmp_path):
    """На win32 все пункты меню присутствуют — только символы другие."""
    out = cli._menu_render(root=tmp_path, platform="win32")
    for num in ("1", "2", "3", "4", "5", "6", "7", "8", "0"):
        assert f"{num})" in out


# -------------------------------------------------- меню: CLI-субкоманда

def test_menu_subcommand_registered():
    """menu зарегистрирован как подкоманда."""
    parser = cli._build_parser()
    args = parser.parse_args(["menu"])
    assert args.cmd == "menu"


def test_menu_subcommand_prints_menu(capsys, tmp_path, monkeypatch):
    """autoreels menu печатает меню."""
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["menu"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Выход" in out
    assert "0)" in out


def test_menu_resolve_prints_action_token(capsys, tmp_path, monkeypatch):
    """autoreels menu --resolve 1 → печатает 'go' (для bash-диспетча)."""
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["menu", "--resolve", "1"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "go"


def test_menu_resolve_invalid_prints_invalid(capsys, tmp_path, monkeypatch):
    """autoreels menu --resolve <мусор> → печатает 'invalid' (bash попадёт в *)."""
    monkeypatch.chdir(tmp_path)
    cli.main(["menu", "--resolve", "99"])
    out = capsys.readouterr().out.strip()
    assert out == "invalid"


# -------------------------------------------------- URL-режим: определение url

def test_is_url_detects_http_and_https():
    assert cli._is_url("http://example.com/v.mp4") is True
    assert cli._is_url("https://youtu.be/abc123") is True


def test_is_url_rejects_local_paths():
    for p in ("/Users/danny/v.mp4", "~/Downloads/v.mp4", "inputs/v.mp4",
              "v.mp4", "C:\\video.mp4", "file:///x.mp4", "ftp://h/x"):
        assert cli._is_url(p) is False, p


# -------------------------------------------------- URL-режим: санитизация имени

def test_sanitize_filename_removes_emoji_and_special():
    """Эмодзи, слэши, спецсимволы → безопасное имя; пробелы → _."""
    out = cli._sanitize_filename("Как варить чай 🍵 / Часть 1!")
    assert "🍵" not in out
    assert "/" not in out
    assert "!" not in out
    assert " " not in out
    assert out == "Как_варить_чай_Часть_1"


def test_sanitize_filename_keeps_cyrillic_and_alnum():
    assert cli._sanitize_filename("Лекция_2024-раз") == "Лекция_2024-раз"


def test_sanitize_filename_collapses_and_trims():
    assert cli._sanitize_filename("  //  a   b  // ") == "a_b"


def test_sanitize_filename_all_emoji_is_empty():
    assert cli._sanitize_filename("😀😀😀") == ""


def test_sanitize_filename_truncates_to_maxlen():
    out = cli._sanitize_filename("a" * 200)
    assert len(out) <= 80


# -------------------------------------------------- URL-режим: команда yt-dlp

def _fake_which_yes(_name):
    return "/usr/bin/yt-dlp"


def test_download_url_builds_correct_command(tmp_path):
    """Команда yt-dlp: --no-playlist, лимит 1080p, вывод в inputs/."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        # эмулируем успешную загрузку: кладём <id>.mp4 и печатаем filepath+title
        id_path = tmp_path / "inputs" / "abc123.mp4"
        id_path.parent.mkdir(parents=True, exist_ok=True)
        id_path.write_bytes(b"video")

        class R:
            returncode = 0
            stdout = f"{id_path}\nТест ролик"
        return R()

    cli._download_url("https://youtu.be/abc123", tmp_path / "inputs",
                      which=_fake_which_yes, run=fake_run)

    cmd = captured["cmd"]
    assert "--no-playlist" in cmd
    assert any("height<=1080" in c for c in cmd)
    # -o шаблон указывает в inputs/
    o_idx = cmd.index("-o")
    assert str(tmp_path / "inputs") in cmd[o_idx + 1]
    assert "https://youtu.be/abc123" in cmd


def test_download_url_renames_with_sanitized_title(tmp_path):
    """После загрузки файл переименован в <sanitized>_<id>.mp4."""
    def fake_run(cmd, **kwargs):
        id_path = tmp_path / "inputs" / "abc123.mp4"
        id_path.parent.mkdir(parents=True, exist_ok=True)
        id_path.write_bytes(b"video")

        class R:
            returncode = 0
            stdout = f"{id_path}\nЧай 🍵 / Часть 1"
        return R()

    result = cli._download_url("https://youtu.be/abc123", tmp_path / "inputs",
                               which=_fake_which_yes, run=fake_run)

    assert result.parent == (tmp_path / "inputs")
    assert result.name == "Чай_Часть_1_abc123.mp4"
    assert result.exists()


def test_download_url_missing_ytdlp_raises(tmp_path):
    """yt-dlp не установлен → внятная ошибка с подсказкой про установку."""
    with pytest.raises(cli.RunError) as exc:
        cli._download_url("https://youtu.be/x", tmp_path / "inputs",
                          which=lambda _n: None, run=lambda *a, **k: None)
    assert "yt-dlp" in str(exc.value)


def test_download_url_failed_download_raises(tmp_path):
    """Битая ссылка / гео-блок → yt-dlp код ≠ 0 → RunError, не краш."""
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
            stdout = ""
        return R()

    with pytest.raises(cli.RunError) as exc:
        cli._download_url("https://youtu.be/broken", tmp_path / "inputs",
                          which=_fake_which_yes, run=fake_run)
    assert "broken" in str(exc.value) or "yt-dlp" in str(exc.value)


def test_download_url_all_emoji_title_falls_back_to_id(tmp_path):
    """Заголовок целиком из эмодзи → имя = <id>.mp4 (без ведущего _)."""
    def fake_run(cmd, **kwargs):
        id_path = tmp_path / "inputs" / "xyz789.mp4"
        id_path.parent.mkdir(parents=True, exist_ok=True)
        id_path.write_bytes(b"v")

        class R:
            returncode = 0
            stdout = f"{id_path}\n😀😀😀"
        return R()

    result = cli._download_url("https://youtu.be/xyz789", tmp_path / "inputs",
                               which=_fake_which_yes, run=fake_run)
    assert result.name == "xyz789.mp4"


# -------------------------------------------------- URL-режим: диспетч main()

def test_run_dispatch_url_calls_download(monkeypatch, tmp_path):
    """main('run <url>') идёт по ветке скачивания, не _ingest_source."""
    monkeypatch.chdir(tmp_path)
    calls = {}

    def fake_download(url, inputs_dir, **kwargs):
        calls["url"] = url
        p = tmp_path / "inputs" / "dl.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"v")
        return p

    def fake_cmd_run(video, **kwargs):
        calls["video"] = Path(video)
        return tmp_path / "manifests" / "dl.json"

    monkeypatch.setattr(cli, "_download_url", fake_download)
    monkeypatch.setattr(cli, "cmd_run", fake_cmd_run)
    monkeypatch.setattr(cli, "_ingest_source",
                        lambda *a, **k: pytest.fail("ingest не должен вызываться для url"))

    rc = cli.main(["run", "https://youtu.be/dl"])

    assert rc == 0
    assert calls["url"] == "https://youtu.be/dl"
    assert calls["video"] == (tmp_path / "inputs" / "dl.mp4")


def test_run_dispatch_url_download_error_returns_1(monkeypatch, tmp_path, capsys):
    """Ошибка скачивания → код 1 + внятное сообщение."""
    monkeypatch.chdir(tmp_path)

    def fake_download(url, inputs_dir, **kwargs):
        raise cli.RunError("yt-dlp не смог скачать https://youtu.be/bad")

    monkeypatch.setattr(cli, "_download_url", fake_download)
    rc = cli.main(["run", "https://youtu.be/bad"])
    assert rc == 1
    assert "bad" in capsys.readouterr().err


# -------------------------------------------------- Я.Диск: определение ссылки

def test_is_yandex_disk_detects():
    for u in ("https://disk.yandex.ru/i/abc", "https://disk.yandex.ru/d/x",
              "https://yadi.sk/i/x", "https://disk.yandex.com/i/x",
              "https://www.disk.yandex.ru/i/x"):
        assert cli._is_yandex_disk(u) is True, u


def test_is_yandex_disk_rejects_others():
    for u in ("https://youtu.be/x", "https://example.com/v.mp4",
              "/local/path", "yadi.sk", "inputs/v.mp4"):
        assert cli._is_yandex_disk(u) is False, u


# -------------------------------------------------- Я.Диск: имя файла

def test_yandex_filename_sanitizes_and_adds_hash():
    import hashlib
    url = "https://disk.yandex.ru/i/abc"
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    out = cli._yandex_filename("Лекция 5 🎬.mp4", url)
    assert out == f"Лекция_5_{h}.mp4"


def test_yandex_filename_empty_title_fallback():
    import hashlib
    url = "https://disk.yandex.ru/i/x"
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    assert cli._yandex_filename("😀.mp4", url) == f"yadisk_{h}.mp4"


# -------------------------------------------------- Я.Диск: download URL из API

def test_yandex_download_href_parses_href():
    def fake_get_json(suffix, public_key, *, token=None):
        assert suffix == "/download"
        return {"href": "https://downloader.disk.yandex.ru/x"}
    href = cli._yandex_download_href("https://disk.yandex.ru/i/a", get_json=fake_get_json)
    assert href == "https://downloader.disk.yandex.ru/x"


def test_yandex_api_get_404_raises(monkeypatch):
    import httpx

    class Resp:
        status_code = 404
        def json(self):
            return {}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Resp())
    with pytest.raises(cli.RunError) as exc:
        cli._yandex_api_get("", "https://disk.yandex.ru/i/gone")
    assert "gone" in str(exc.value) or "404" in str(exc.value)


# -------------------------------------------------- Я.Диск: тип файл / папка

def test_yandex_folder_link_raises(tmp_path):
    """type=='dir' (ссылка /d/ на папку) → внятная ошибка, batch пока не поддержан."""
    def fake_get_json(suffix, public_key, *, token=None):
        return {"type": "dir", "name": "folder"}
    with pytest.raises(cli.RunError) as exc:
        cli._download_yandex_disk("https://disk.yandex.ru/d/abc", tmp_path / "inputs",
                                  get_json=fake_get_json,
                                  download=lambda *a, **k: None)
    assert "папк" in str(exc.value).lower()


def test_yandex_non_video_raises(tmp_path):
    """Файл не видео (mime + расширение) → ошибка до скачивания."""
    def fake_get_json(suffix, public_key, *, token=None):
        return {"type": "file", "name": "archive.zip", "mime_type": "application/zip"}
    with pytest.raises(cli.RunError) as exc:
        cli._download_yandex_disk("https://disk.yandex.ru/i/abc", tmp_path / "inputs",
                                  get_json=fake_get_json,
                                  download=lambda *a, **k: None)
    assert "видео" in str(exc.value).lower()


# -------------------------------------------------- Я.Диск: скачивание (httpx-стрим мокается)

def _yandex_meta_video(size=4):
    def fake_get_json(suffix, public_key, *, token=None):
        if suffix == "":
            return {"type": "file", "name": "Лекция.mp4",
                    "mime_type": "video/mp4", "size": size}
        return {"href": "https://downloader.disk.yandex.ru/x"}
    return fake_get_json


def test_yandex_download_happy_path(tmp_path):
    def fake_download(href, part, *, resume_from, total):
        part.write_bytes(b"data")   # 4 байта == size

    out = cli._download_yandex_disk("https://disk.yandex.ru/i/abc", tmp_path / "inputs",
                                    get_json=_yandex_meta_video(size=4), download=fake_download)
    assert out.exists()
    assert out.parent == (tmp_path / "inputs")
    assert out.suffix == ".mp4" and "Лекция" in out.name


def test_yandex_download_passes_fresh_href_and_zero_resume(tmp_path):
    """Первая попытка: скачиваем со свежего API-href, resume_from=0."""
    captured = {}

    def fake_download(href, part, *, resume_from, total):
        captured["href"] = href
        captured["resume_from"] = resume_from
        captured["total"] = total
        part.write_bytes(b"data")

    cli._download_yandex_disk("https://disk.yandex.ru/i/abc", tmp_path / "inputs",
                              get_json=_yandex_meta_video(size=4), download=fake_download)
    assert captured["href"] == "https://downloader.disk.yandex.ru/x"
    assert captured["resume_from"] == 0
    assert captured["total"] == 4


def test_yandex_retry_fetches_fresh_url_and_resumes(tmp_path):
    """Обрыв (неполный размер) → повтор со СВЕЖИМ href и докачкой с текущего смещения."""
    href_calls = {"n": 0}

    def fake_get_json(suffix, public_key, *, token=None):
        if suffix == "":
            return {"type": "file", "name": "v.mp4", "mime_type": "video/mp4", "size": 5}
        href_calls["n"] += 1
        return {"href": f"https://downloader/{href_calls['n']}"}

    attempts = {"n": 0}
    resumes = []

    def fake_download(href, part, *, resume_from, total):
        attempts["n"] += 1
        resumes.append(resume_from)
        if attempts["n"] == 1:
            part.write_bytes(b"xx")        # неполный (2 < 5) → обрыв
        else:
            part.write_bytes(b"xxxxx")     # полный

    out = cli._download_yandex_disk("https://disk.yandex.ru/i/abc", tmp_path / "inputs",
                                    get_json=fake_get_json, download=fake_download,
                                    retry_pause_sec=0)
    assert out.exists()
    assert href_calls["n"] == 2            # свежий URL на каждую попытку
    assert resumes == [0, 2]               # вторая попытка докачивает с 2 байт


def test_yandex_retry_survives_httpx_connection_reset(tmp_path):
    """Обрыв соединения (httpx.HTTPError, как curl 56) ловится и докачивается, не крашит."""
    import httpx
    attempts = {"n": 0}

    def fake_download(href, part, *, resume_from, total):
        attempts["n"] += 1
        if attempts["n"] == 1:
            part.write_bytes(b"xx")                       # частично…
            raise httpx.RemoteProtocolError("Connection reset by peer")  # …и обрыв
        part.write_bytes(b"xxxxx")                        # докачали

    out = cli._download_yandex_disk("https://disk.yandex.ru/i/abc", tmp_path / "inputs",
                                    get_json=_yandex_meta_video(size=5), download=fake_download,
                                    retry_pause_sec=0)
    assert out.exists()
    assert attempts["n"] == 2


def test_yandex_download_gives_up_after_stalls_without_progress(tmp_path):
    """Нет прогресса N попыток подряд → RunError (не бесконечный цикл)."""
    def fake_download(href, part, *, resume_from, total):
        part.write_bytes(b"xx")            # всегда 2 из 5 — прогресса нет после первой

    with pytest.raises(cli.RunError) as exc:
        cli._download_yandex_disk("https://disk.yandex.ru/i/abc", tmp_path / "inputs",
                                  get_json=_yandex_meta_video(size=5), download=fake_download,
                                  max_stalls=3, retry_pause_sec=0)
    assert "прогресс" in str(exc.value).lower() or "не удалось" in str(exc.value).lower()


def test_yandex_idempotent_when_dest_exists(tmp_path):
    """Файл уже скачан (dest есть) → download не зовём, возвращаем существующий."""
    url = "https://disk.yandex.ru/i/abc"
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    dest = inputs / cli._yandex_filename("Лекция.mp4", url)
    dest.write_bytes(b"already")

    out = cli._download_yandex_disk(
        url, inputs, get_json=_yandex_meta_video(),
        download=lambda *a, **k: pytest.fail("download не должен зваться — файл уже есть"),
    )
    assert out == dest


# -------------------------------------------------- httpx-стрим: запись/докачка

class _FakeStreamResp:
    def __init__(self, chunks, status_code=206):
        self._chunks = chunks
        self.status_code = status_code
        self.headers = {}

    def iter_bytes(self, chunk_size=None):
        yield from self._chunks


class _FakeStreamCM:
    def __init__(self, resp, captured):
        self._resp = resp
        self._captured = captured

    def __enter__(self):
        return self._resp

    def __exit__(self, *a):
        return False


def _patch_stream(monkeypatch, resp):
    import httpx
    captured = {}

    def fake_stream(method, href, *, headers=None, **kwargs):
        captured["headers"] = headers or {}
        captured["href"] = href
        return _FakeStreamCM(resp, captured)

    monkeypatch.setattr(httpx, "stream", fake_stream)
    return captured


def test_httpx_stream_download_writes_bytes(monkeypatch, tmp_path):
    cap = _patch_stream(monkeypatch, _FakeStreamResp([b"ab", b"cd", b"ef"], status_code=200))
    part = tmp_path / "f.part"
    cli._httpx_stream_download("https://dl/x", part, resume_from=0, total=6)
    assert part.read_bytes() == b"abcdef"
    assert "Range" not in cap["headers"]           # с нуля — без Range


def test_httpx_stream_download_resumes_with_range(monkeypatch, tmp_path):
    cap = _patch_stream(monkeypatch, _FakeStreamResp([b"cd", b"ef"], status_code=206))
    part = tmp_path / "f.part"
    part.write_bytes(b"ab")                          # уже скачано 2 байта
    cli._httpx_stream_download("https://dl/x", part, resume_from=2, total=6)
    assert part.read_bytes() == b"abcdef"            # докачка дописала
    assert cap["headers"].get("Range") == "bytes=2-"


def test_httpx_stream_download_restarts_when_server_ignores_range(monkeypatch, tmp_path):
    """Сервер отдал 200 (не 206) на Range → не дублируем, качаем заново с нуля."""
    _patch_stream(monkeypatch, _FakeStreamResp([b"abcdef"], status_code=200))
    part = tmp_path / "f.part"
    part.write_bytes(b"XX")                          # старый огрызок
    cli._httpx_stream_download("https://dl/x", part, resume_from=2, total=6)
    assert part.read_bytes() == b"abcdef"            # перезаписан, не XXabcdef


def test_httpx_stream_download_http_error_raises(monkeypatch, tmp_path):
    _patch_stream(monkeypatch, _FakeStreamResp([], status_code=404))
    with pytest.raises(cli.RunError):
        cli._httpx_stream_download("https://dl/x", tmp_path / "f.part", resume_from=0, total=6)


# -------------------------------------------------- Я.Диск: диспетч main()

def test_run_dispatch_yandex_calls_yandex_downloader(monkeypatch, tmp_path):
    """main('run <я.диск-url>') → _download_yandex_disk, не yt-dlp и не _ingest_source."""
    monkeypatch.chdir(tmp_path)
    calls = {}

    def fake_yd(url, inputs_dir, **k):
        calls["url"] = url
        p = tmp_path / "inputs" / "y.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"v")
        return p

    monkeypatch.setattr(cli, "_download_yandex_disk", fake_yd)
    monkeypatch.setattr(cli, "cmd_run",
                        lambda video, **k: calls.setdefault("video", Path(video)))
    monkeypatch.setattr(cli, "_download_url",
                        lambda *a, **k: pytest.fail("yt-dlp не для Я.Диска"))

    rc = cli.main(["run", "https://disk.yandex.ru/i/abc"])
    assert rc == 0
    assert calls["url"] == "https://disk.yandex.ru/i/abc"
    assert calls["video"] == (tmp_path / "inputs" / "y.mp4")


# -------------------------------------------------- transcribe: приём медиа (аудио тоже)

def test_validate_media_accepts_audio(tmp_path):
    a = tmp_path / "x.mp3"
    a.write_bytes(b"a")
    assert cli._validate_media(a, exts=cli._MEDIA_EXTS) == a.resolve()


def test_ingest_source_still_rejects_audio(tmp_path):
    a = tmp_path / "x.mp3"
    a.write_bytes(b"a")
    with pytest.raises(cli.RunError):
        cli._ingest_source(a, tmp_path / "inputs")


# -------------------------------------------------- transcribe: команда

def _transcript_two_paragraphs():
    return Transcript(language="ru", words=[
        Word(word="Первая", t0=0.0, t1=0.4), Word(word="мысль.", t0=0.5, t1=0.9),
        Word(word="Вторая", t0=4.0, t1=4.4), Word(word="мысль.", t0=4.5, t1=4.9),
    ])


def test_transcribe_writes_clean_text_without_timecodes(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.mp3")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: _transcript_two_paragraphs())
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"x")

    out = cli.cmd_transcribe(video, fmt="text", root=REPO_ROOT,
                             out_dir=tmp_path / "transcripts", cache_dir=tmp_path / "c")

    assert out == tmp_path / "transcripts" / "lecture.txt"
    txt = out.read_text(encoding="utf-8")
    assert "Первая мысль." in txt
    assert "\n\n" in txt                       # абзацы по паузе
    assert "[" not in txt and "-->" not in txt  # без таймкодов


def test_transcribe_srt_format_has_timecodes(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.mp3")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: _transcript_two_paragraphs())
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    out = cli.cmd_transcribe(video, fmt="srt", root=REPO_ROOT,
                             out_dir=tmp_path / "t", cache_dir=tmp_path / "c")
    assert out.suffix == ".srt"
    assert "-->" in out.read_text(encoding="utf-8")


def test_transcribe_json_format_is_word_level(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.mp3")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: _transcript_two_paragraphs())
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    out = cli.cmd_transcribe(video, fmt="json", root=REPO_ROOT,
                             out_dir=tmp_path / "t", cache_dir=tmp_path / "c")
    assert out.suffix == ".json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0] == {"word": "Первая", "t0": 0.0, "t1": 0.4}


def test_transcribe_passes_chunking_cfg_to_stage(monkeypatch, tmp_path):
    """Длинное видео проходит через чанкинг: _stage_transcribe получает r0_cfg с chunking."""
    seen = {}
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.mp3")

    def fake_ts(audio, *, transcribe_cfg, cache_dir, r0_cfg=None, audio_cfg=None, ffmpeg="ffmpeg"):
        seen["r0_cfg"] = r0_cfg
        return _transcript_two_paragraphs()

    monkeypatch.setattr(cli, "_stage_transcribe", fake_ts)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    cli.cmd_transcribe(video, fmt="text", root=REPO_ROOT,
                       out_dir=tmp_path / "t", cache_dir=tmp_path / "c")
    assert seen["r0_cfg"] is not None
    assert seen["r0_cfg"].chunking is not None   # чанкинг-конфиг прокинут


def test_transcribe_subcommand_registered():
    parser = cli._build_parser()
    args = parser.parse_args(["transcribe", "v.mp4"])
    assert args.cmd == "transcribe"
    assert args.format == "text"                 # дефолт — text (под контент)


def test_transcribe_format_choices():
    parser = cli._build_parser()
    for f in ("text", "srt", "vtt", "json"):
        assert parser.parse_args(["transcribe", "v.mp4", "--format", f]).format == f


def test_transcribe_dispatch_local_processed_in_place(monkeypatch, tmp_path):
    """transcribe локального файла НЕ копирует его в inputs/ (нет рендера — не нужно)."""
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"v")
    seen = {}

    def fake_cmd(source, **kwargs):
        seen["source"] = Path(source)
        return tmp_path / "transcripts" / "clip.txt"

    monkeypatch.setattr(cli, "cmd_transcribe", fake_cmd)
    monkeypatch.setattr(cli, "_ingest_source",
                        lambda *a, **k: pytest.fail("transcribe не копирует в inputs/"))

    rc = cli.main(["transcribe", str(src)])
    assert rc == 0
    assert seen["source"] == src.resolve()


def test_transcribe_dispatch_accepts_audio(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "podcast.mp3"
    src.write_bytes(b"a")
    monkeypatch.setattr(cli, "cmd_transcribe", lambda source, **k: tmp_path / "t" / "p.txt")
    assert cli.main(["transcribe", str(src)]) == 0


def test_transcribe_dispatch_bad_source_errors(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["transcribe", str(tmp_path / "ghost.mp4")])
    assert rc == 1
    assert "ghost" in capsys.readouterr().err


def test_transcribe_dispatch_url_downloads(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake_dl(url, inputs_dir, **k):
        seen["url"] = url
        p = tmp_path / "inputs" / "d.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"v")
        return p

    monkeypatch.setattr(cli, "_download_url", fake_dl)
    monkeypatch.setattr(cli, "cmd_transcribe", lambda source, **k: tmp_path / "t" / "d.txt")

    rc = cli.main(["transcribe", "https://youtu.be/d"])
    assert rc == 0
    assert seen["url"] == "https://youtu.be/d"


# -------------------------------------------------- transcribe --from-cache

_FAKE_HASH = "a" * 64  # 64-char hex hash, имитирует реальный sha256 аудио


def _write_fake_transcript_cache(cache_dir: Path, audio_hash: str, transcript: Transcript) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"{audio_hash}.transcript.json"
    p.write_text(transcript.model_dump_json(), encoding="utf-8")
    return p


def test_from_cache_loads_transcript_without_whisper(monkeypatch, tmp_path):
    """--from-cache <hash> читает транскрипт из файла кэша, минуя Whisper и ffmpeg."""
    cache_dir = tmp_path / "cache"
    tx = _transcript_two_paragraphs()
    _write_fake_transcript_cache(cache_dir, _FAKE_HASH, tx)

    extract_called = []
    monkeypatch.setattr(cli, "_stage_extract_audio",
                        lambda *a, **k: extract_called.append(1) or (tmp_path / "a.mp3"))
    monkeypatch.setattr(cli, "_stage_transcribe",
                        lambda *a, **k: pytest.fail("_stage_transcribe не должна вызываться"))

    out = cli.cmd_transcribe(
        fmt="text", root=REPO_ROOT,
        out_dir=tmp_path / "transcripts", cache_dir=cache_dir,
        from_cache=_FAKE_HASH,
    )

    assert not extract_called, "_stage_extract_audio вызвана, хотя есть кэш"
    assert out.exists()
    assert "Первая" in out.read_text(encoding="utf-8")


def test_from_cache_uses_hash_stem_when_no_source(monkeypatch, tmp_path):
    """Без source выходной файл называется по первым 16 символам хэша."""
    cache_dir = tmp_path / "cache"
    _write_fake_transcript_cache(cache_dir, _FAKE_HASH, _transcript_two_paragraphs())

    out = cli.cmd_transcribe(
        fmt="text", root=REPO_ROOT,
        out_dir=tmp_path / "transcripts", cache_dir=cache_dir,
        from_cache=_FAKE_HASH,
    )

    assert out.stem == _FAKE_HASH[:16]


def test_from_cache_uses_source_stem_when_given(monkeypatch, tmp_path):
    """Если source задан — stem берётся из source, не из хэша."""
    cache_dir = tmp_path / "cache"
    _write_fake_transcript_cache(cache_dir, _FAKE_HASH, _transcript_two_paragraphs())

    out = cli.cmd_transcribe(
        source="PXL_20260729_085910095.mp4",
        fmt="text", root=REPO_ROOT,
        out_dir=tmp_path / "transcripts", cache_dir=cache_dir,
        from_cache=_FAKE_HASH,
    )

    assert out.stem == "PXL_20260729_085910095"


def test_from_cache_raises_if_not_in_cache(tmp_path):
    """Если файла кэша нет — RunError с понятным сообщением."""
    with pytest.raises(cli.RunError, match="не найден в кэше"):
        cli.cmd_transcribe(
            fmt="text", root=REPO_ROOT,
            out_dir=tmp_path / "transcripts", cache_dir=tmp_path / "empty_cache",
            from_cache=_FAKE_HASH,
        )


def test_transcribe_parser_accepts_from_cache_without_source():
    """argparse принимает --from-cache без обязательного source."""
    parser = cli._build_parser()
    args = parser.parse_args(["transcribe", "--from-cache", _FAKE_HASH])
    assert args.from_cache == _FAKE_HASH
    assert args.source is None


def test_transcribe_parser_from_cache_with_source():
    """argparse принимает --from-cache вместе с source (для именования)."""
    parser = cli._build_parser()
    args = parser.parse_args(["transcribe", "видео.mp4", "--from-cache", _FAKE_HASH])
    assert args.from_cache == _FAKE_HASH
    assert args.source == "видео.mp4"


def test_transcribe_dispatch_from_cache_skips_validate_media(monkeypatch, tmp_path):
    """CLI-dispatch при --from-cache НЕ вызывает _validate_media (файл не нужен)."""
    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake_cmd(source=None, **kwargs):
        seen["source"] = source
        seen["from_cache"] = kwargs.get("from_cache")
        return tmp_path / "transcripts" / "t.txt"

    monkeypatch.setattr(cli, "cmd_transcribe", fake_cmd)
    monkeypatch.setattr(cli, "_validate_media",
                        lambda *a, **k: pytest.fail("_validate_media вызвана при --from-cache"))

    rc = cli.main(["transcribe", "--from-cache", _FAKE_HASH])
    assert rc == 0
    assert seen["from_cache"] == _FAKE_HASH


# -------------------------------------------------- R0: модель из конфига

def test_stage_select_builds_provider_pool_from_config(monkeypatch):
    """_stage_select собирает провайдер-пул из r0_cfg (модели/стратегия — не хардкод)."""
    from autoreels.core.config import load_r0_config
    r0 = load_r0_config(REPO_ROOT / "config" / "r0.yaml")
    captured = {}

    def fake_build_pool(cfg, **k):
        captured["cfg"] = cfg
        return object()

    monkeypatch.setattr(cli, "build_pool", fake_build_pool)
    monkeypatch.setattr(cli, "select", lambda *a, **k: [])
    cli._stage_select("COMPRESSED", r0_cfg=r0, root=REPO_ROOT)
    assert captured["cfg"] is r0                       # пул строится из того же r0_cfg
    assert captured["cfg"].model == r0.model
    assert captured["cfg"].provider_strategy in ("adaptive", "round_robin")


def test_run_preflights_models_before_transcription(monkeypatch, tmp_path):
    """cmd_run валидирует модели (preflight) ДО транскрипции; тот же пул уходит в R0-select."""
    order = []

    class _FakePool:
        def preflight(self):
            order.append("preflight")

    fake_pool = _FakePool()
    captured = {}
    monkeypatch.setattr(cli, "build_pool", lambda cfg, **k: fake_pool)
    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda *a, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio",
                        lambda *a, **k: order.append("extract") or (tmp_path / "a.mp3"))
    monkeypatch.setattr(cli, "_stage_transcribe",
                        lambda *a, **k: order.append("transcribe") or Transcript(language="ru", words=[]))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select",
                        lambda *a, **k: captured.update(provider=k.get("provider")) or [])

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "m",
                transcripts_dir=tmp_path / "t", cache_dir=tmp_path / "c",
                archive_dir=tmp_path / "arch")

    # префлайт строго до извлечения аудио и транскрипции
    assert order.index("preflight") < order.index("extract") < order.index("transcribe")
    assert captured["provider"] is fake_pool           # тот же провалидированный пул → select


def test_run_survives_provider_404_via_pool(monkeypatch, tmp_path):
    """Сквозной: 404 одного провайдера в R0 не роняет run — пул уводит на второй, манифест собран."""
    from autoreels.cloud.providers import ProviderPool, ProviderModelNotFound

    class _Prov:
        def __init__(self, name, script, model="m"):
            self.name = name
            self._model = model
            self._script = list(script)
        def complete(self, messages, *, temperature=0.0):
            a = self._script.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        def available_models(self):
            return None                                 # префлайт не проверяет (нет сети)

    bad = _Prov("OpenRouter", [ProviderModelNotFound("модель X 404", model="X", provider="OpenRouter")])
    good = _Prov("Groq", ['{"segments": []}'])
    # OpenRouter первым, чтобы 404 сработал до Groq и был реально исключён
    pool = ProviderPool([bad, good], strategy="round_robin")
    monkeypatch.setattr(cli, "build_pool", lambda cfg, **k: pool)
    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda *a, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.mp3")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: Transcript(language="ru", words=[]))
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "[0-5] короткий текст")

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    # не должно бросить — 404 OpenRouter исключается, R0 идёт на Groq
    path = cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "m",
                       transcripts_dir=tmp_path / "t", cache_dir=tmp_path / "c",
                       archive_dir=tmp_path / "arch")
    assert path.is_file()                               # манифест собран, прогон завершился


# -------------------------------------------------- calibrate --all: изоляция ошибок

def test_calibrate_all_skips_broken_video_and_continues(tmp_path, monkeypatch, capsys):
    """Битое видео (ffprobe/CalibrateError) не роняет весь batch — пропуск и продолжение."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "bad.mp4").write_bytes(b"x")
    (inputs / "good.mp4").write_bytes(b"y")

    monkeypatch.setattr(cli.state, "file_sha256_cached_fast",
                        lambda v, c: "sha_" + Path(v).name)
    monkeypatch.setattr(cli, "_calibration_kind", lambda d, s: "none")
    monkeypatch.setattr(cli, "_ask_batch_action", lambda name, kind: "к")

    attempted = []

    def fake_calibrate(video, **k):
        attempted.append(Path(video).name)
        if Path(video).name == "bad.mp4":
            from autoreels.local.calibrate import CalibrateError
            raise CalibrateError("ffprobe не смог прочитать bad.mp4: moov atom not found")

    monkeypatch.setattr(cli, "cmd_calibrate", fake_calibrate)

    # НЕ должно бросать — обе видео обработаны, битое пропущено
    cli.cmd_calibrate_batch(root=tmp_path, inputs_dir=inputs,
                            calibrations_dir=tmp_path / "calib", cache_dir=tmp_path / "c")

    assert attempted == ["bad.mp4", "good.mp4"]      # дошли до второго после падения первого
    err = capsys.readouterr().err
    assert "bad.mp4" in err


# -------------------------------------------------- run: попутно сохраняет транскрипт

def test_run_saves_transcript_text(monkeypatch, tmp_path):
    """run после Whisper сохраняет чистый текст в transcripts/<stem>.txt (тот же формат)."""
    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda *a, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.mp3")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: _transcript_two_paragraphs())
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [])

    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"x")
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "m",
                transcripts_dir=tmp_path / "t", cache_dir=tmp_path / "c")

    txt = (tmp_path / "t" / "lecture.txt").read_text(encoding="utf-8")
    assert "Первая мысль." in txt        # связный текст
    assert "\n\n" in txt                 # абзацы по паузе
    assert "[" not in txt                # без таймкодов


def test_run_batch_saves_transcript_for_each_video(monkeypatch, tmp_path):
    """batch: три видео → три transcripts/<stem>.txt (попутно, у каждого свой файл)."""
    _mock_pipeline(monkeypatch, tmp_path)
    # реальный транскрипт (не пустой) → _write_transcript_file пишет содержательный текст
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: _transcript_two_paragraphs())

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        (inputs / name).write_bytes(b"x")
    transcripts = tmp_path / "transcripts"

    ok, failed = cli.cmd_run_batch(
        root=REPO_ROOT, inputs_dir=inputs, manifests_dir=tmp_path / "m",
        archive_dir=tmp_path / "arch", transcripts_dir=transcripts, cache_dir=tmp_path / "c",
    )

    assert failed == []
    for stem in ("a", "b", "c"):
        txt = (transcripts / f"{stem}.txt").read_text(encoding="utf-8")
        assert "Первая мысль." in txt    # содержательный текст у каждого
        assert "[" not in txt            # без таймкодов


def test_run_transcript_byte_identical_to_transcribe(monkeypatch, tmp_path):
    """Попутный транскрипт run и вывод команды transcribe — байт-в-байт (общий рендер-путь)."""
    monkeypatch.setattr(cli, "load_or_auto_calibrate", lambda *a, **k: _setup())
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.mp3")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: _transcript_two_paragraphs())
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [])

    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"x")

    # эталон — отдельная команда transcribe (fmt=text по умолчанию)
    transcribe_out = cli.cmd_transcribe(video, fmt="text", root=REPO_ROOT,
                                        out_dir=tmp_path / "tr", cache_dir=tmp_path / "c")
    # run пишет попутный транскрипт в свою папку (тот же исходный транскрипт)
    cli.cmd_run(video, root=REPO_ROOT, manifests_dir=tmp_path / "m",
                transcripts_dir=tmp_path / "run", cache_dir=tmp_path / "c",
                archive_dir=tmp_path / "arch")

    run_txt = (tmp_path / "run" / "lecture.txt").read_text(encoding="utf-8")
    assert run_txt == transcribe_out.read_text(encoding="utf-8")


# -------------------------------------------------- транскрипт-кэш общий (Whisper 1 раз)

def test_transcript_cache_shared_whisper_called_once(monkeypatch, tmp_path):
    """Повторный _stage_transcribe (run ИЛИ transcribe) на том же аудио → кэш, не Whisper."""
    from autoreels.core.config import load_transcribe_config
    from autoreels.core.models import Transcript, Word

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"AUDIODATA" * 200)
    cache = tmp_path / "cache"
    calls = {"n": 0}

    class _Counter:
        def transcribe(self, path, *, language=None):
            calls["n"] += 1
            return Transcript(language="ru", words=[Word(word="привет", t0=0.0, t1=0.5)])

    monkeypatch.setattr(cli, "get_backend", lambda cfg: _Counter())
    tcfg = load_transcribe_config(REPO_ROOT / "config" / "transcribe.yaml")

    # 1-й вызов — Whisper; кэш по хэшу содержимого аудио
    cli._stage_transcribe(audio, transcribe_cfg=tcfg, cache_dir=cache, r0_cfg=None)
    # 2-й (эмулирует повторный run / команду transcribe на том же видео) — из кэша
    cli._stage_transcribe(audio, transcribe_cfg=tcfg, cache_dir=cache, r0_cfg=None)

    assert calls["n"] == 1               # Whisper вызван ровно один раз


def test_transcribe_passes_source_sha_for_shared_audio_cache(monkeypatch, tmp_path):
    """transcribe передаёт source_sha в extract_audio → общий с run аудио-кэш (то же имя)."""
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: _transcript_two_paragraphs())
    seen = {}

    def fake_extract(source, *, render_cfg, cache_dir, ffmpeg, source_sha=None):
        seen["source_sha"] = source_sha
        return tmp_path / "a.mp3"

    monkeypatch.setattr(cli, "_stage_extract_audio", fake_extract)
    src = tmp_path / "v.mp4"
    src.write_bytes(b"video-bytes-123")

    cli.cmd_transcribe(src, fmt="text", root=REPO_ROOT,
                       out_dir=tmp_path / "t", cache_dir=tmp_path / "c")

    assert seen["source_sha"] is not None
    # совпадает с ключом, который использует run (partial-хэш содержимого)
    assert seen["source_sha"] == cli.state.file_sha256_cached_fast(src, tmp_path / "c")


# -------------------------------------------------- migrate-calibrations (рекей ручных)

def test_migrate_calibrations_rekeys_manual_to_partial(tmp_path):
    """Ручная калибровка под старым (полным) ключом переносится на актуальный partial-p1."""
    from autoreels.core import state
    from autoreels.core.calibration import Crop, load_calibration, save_calibration

    archive = tmp_path / "inputs-archive"
    archive.mkdir()
    video = archive / "lecture.mp4"
    video.write_bytes(b"videobytes" * 2000)
    calib = tmp_path / "calibrations"

    full = state.file_sha256(video)
    partial = state.file_sha256_cached_fast(video, tmp_path / "c")
    assert full != partial
    save_calibration(calib, source_name="lecture.mp4", source_sha256=full,
                     crop=Crop(x=1194, y=0, w=1215, h=2160), frame=[3840, 2160],
                     setup_label="main")
    assert not (calib / f"{partial}.json").exists()   # run-ключ пуст → был бы автокроп

    cli.cmd_migrate_calibrations(root=tmp_path, archive_dir=archive,
                                 calibrations_dir=calib, cache_dir=tmp_path / "c")

    setup = load_calibration(calib, partial)          # теперь находится по run-ключу
    assert setup.crop.x == 1194
    assert setup.setup_id == "main"


def test_migrate_calibrations_overwrites_auto_with_manual(tmp_path):
    """Если под partial-ключом лежит автокроп, ручная (важнее) его перекрывает."""
    from autoreels.core import state
    from autoreels.core.calibration import Crop, load_calibration, save_calibration

    archive = tmp_path / "inputs-archive"
    archive.mkdir()
    video = archive / "v.mp4"
    video.write_bytes(b"content" * 3000)
    calib = tmp_path / "calibrations"

    full = state.file_sha256(video)
    partial = state.file_sha256_cached_fast(video, tmp_path / "c")
    # авто под правильным ключом (как поставил run), ручная под полным
    save_calibration(calib, source_name="v.mp4", source_sha256=partial,
                     crop=Crop(x=1312, y=0, w=1215, h=2160), frame=[3840, 2160], setup_label="auto")
    save_calibration(calib, source_name="v.mp4", source_sha256=full,
                     crop=Crop(x=1194, y=0, w=1215, h=2160), frame=[3840, 2160], setup_label="main")

    cli.cmd_migrate_calibrations(root=tmp_path, archive_dir=archive,
                                 calibrations_dir=calib, cache_dir=tmp_path / "c")

    setup = load_calibration(calib, partial)
    assert setup.crop.x == 1194 and setup.setup_id == "main"   # ручная победила


def test_migrate_calibrations_skips_auto_only(tmp_path):
    """Авто-калибровка под чужим ключом НЕ мигрируется (мигрируем только ручные)."""
    from autoreels.core import state
    from autoreels.core.calibration import Crop, save_calibration

    archive = tmp_path / "inputs-archive"
    archive.mkdir()
    video = archive / "v.mp4"
    video.write_bytes(b"xyz" * 4000)
    calib = tmp_path / "calibrations"

    full = state.file_sha256(video)
    partial = state.file_sha256_cached_fast(video, tmp_path / "c")
    save_calibration(calib, source_name="v.mp4", source_sha256=full,
                     crop=Crop(x=1, y=0, w=1215, h=2160), frame=[3840, 2160], setup_label="auto")

    cli.cmd_migrate_calibrations(root=tmp_path, archive_dir=archive,
                                 calibrations_dir=calib, cache_dir=tmp_path / "c")
    assert not (calib / f"{partial}.json").exists()   # авто не перенесена


def test_migrate_calibrations_idempotent(tmp_path, capsys):
    """Калибровка уже под актуальным ключом → миграция ничего не делает."""
    from autoreels.core import state
    from autoreels.core.calibration import Crop, save_calibration

    archive = tmp_path / "inputs-archive"
    archive.mkdir()
    video = archive / "v.mp4"
    video.write_bytes(b"abc" * 5000)
    calib = tmp_path / "calibrations"
    partial = state.file_sha256_cached_fast(video, tmp_path / "c")
    save_calibration(calib, source_name="v.mp4", source_sha256=partial,
                     crop=Crop(x=1194, y=0, w=1215, h=2160), frame=[3840, 2160], setup_label="main")

    cli.cmd_migrate_calibrations(root=tmp_path, archive_dir=archive,
                                 calibrations_dir=calib, cache_dir=tmp_path / "c")
    assert "уже на актуальных" in capsys.readouterr().out.lower()


def test_migrate_calibrations_subcommand_registered():
    args = cli._build_parser().parse_args(["migrate-calibrations"])
    assert args.cmd == "migrate-calibrations"
