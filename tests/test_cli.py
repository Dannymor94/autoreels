"""CLI-склейка (autoreels run / render) — M0 шаг 8. Внешнее (ffmpeg, Groq) мокается.

Инварианты, которые тесты защищают:
- `run` гонит этапы конвейера в правильном порядке (extract→transcribe→compress→select→
  assemble→write) — этапы как блоки, чтобы R3 потом вставился одним блоком;
- манифест собирается с setup_id И кропом ИЗ профиля (чинит расхождение pxl_sasha vs
  tearoom_main), не из хардкода и не из старого манифеста;
- `render` читает manifest.json и дёргает render_crop;
- .env подхватывается автоматически (dotenv) — больше не нужен ручной `source .env`;
- дефолтные пути (inputs/ reels-out/ manifests/) применяются без аргументов;
- ошибка этапа → внятное сообщение, не голый traceback.
"""
import json
import os
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile
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


def _manifest(reels=None) -> Manifest:
    return Manifest(
        source="v.mp4", source_sha256="a" * 64, duration_preset="shorts",
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

    monkeypatch.setattr(cli, "_stage_extract_audio", rec("extract", tmp_path / "a.wav"))
    monkeypatch.setattr(cli, "_stage_transcribe", rec("transcribe", "TRANSCRIPT"))
    monkeypatch.setattr(cli, "_stage_compress", rec("compress", "COMPRESSED"))
    monkeypatch.setattr(cli, "_stage_select", rec("select", [_reel()]))
    monkeypatch.setattr(cli, "_assemble_manifest", rec("assemble", _manifest()))
    monkeypatch.setattr(cli, "_write_manifest", rec("write", tmp_path / "manifest.json"))

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    cli.cmd_run(video, setup="tearoom_main", root=REPO_ROOT, manifests_dir=tmp_path)

    assert order == ["extract", "transcribe", "compress", "select", "assemble", "write"]


# ------------------------------------------------- run: манифест собран ИЗ профиля

def test_run_assembles_manifest_with_setup_and_crop_from_profile(monkeypatch, tmp_path):
    # облачные этапы замокать, assemble+write — настоящие
    monkeypatch.setattr(cli, "_stage_extract_audio", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(cli, "_stage_transcribe", lambda *a, **k: "T")
    monkeypatch.setattr(cli, "_stage_compress", lambda *a, **k: "C")
    monkeypatch.setattr(cli, "_stage_select", lambda *a, **k: [_reel("r01")])

    profile = tmp_path / "myroom.json"
    profile.write_text(json.dumps({
        "setup_id": "my_room",
        "crop": {"x": 100, "y": 50, "w": 900, "h": 1600},
        "scale": [1080, 1920],
        "frame": [3840, 2160],
    }), encoding="utf-8")
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"hello-bytes")
    manifests = tmp_path / "manifests"

    cli.cmd_run(video, profile=profile, root=REPO_ROOT, manifests_dir=manifests)

    m = Manifest.model_validate_json((manifests / "manifest.json").read_text(encoding="utf-8"))
    # setup_id и кроп — из профиля, НЕ хардкод
    assert m.setup.setup_id == "my_room"
    assert m.setup.crop.model_dump() == {"x": 100, "y": 50, "w": 900, "h": 1600}
    # source = имя реального файла; sha256 — от его содержимого
    assert m.source == "lecture.mp4"
    assert len(m.source_sha256) == 64
    assert len(m.reels) == 1


# --------------------------------------------------------------- render: читает манифест

def test_render_reads_manifest_and_calls_render_crop(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "manifest.json").write_text(_manifest().model_dump_json(), encoding="utf-8")

    called = {}

    def fake_crop(manifest, **k):
        called["manifest"] = manifest
        called["kwargs"] = k
        return [Path("reels-out/r01.mp4")]

    monkeypatch.setattr(cli, "render_crop", fake_crop)

    out = cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT)

    assert called["manifest"].source == "v.mp4"        # пришёл из manifest.json
    assert out == [Path("reels-out/r01.mp4")]


def test_render_passes_encoder_through(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "manifest.json").write_text(_manifest().model_dump_json(), encoding="utf-8")

    seen = {}
    monkeypatch.setattr(cli, "render_crop",
                        lambda manifest, **k: seen.update(k) or [])
    cli.cmd_render(manifests_dir=manifests, root=REPO_ROOT, encoder="h264_amf")
    assert seen["encoder"] == "h264_amf"


# ------------------------------------------------------------------ дефолтные пути

def test_render_uses_default_paths_without_args(monkeypatch):
    seen = {}

    def fake_load_manifest(d):
        seen["manifests"] = Path(d)
        return _manifest()

    monkeypatch.setattr(cli, "load_manifest", fake_load_manifest)

    def fake_crop(manifest, *, inputs_dir, out_dir, **k):
        seen["inputs"] = Path(inputs_dir)
        seen["out"] = Path(out_dir)
        return []

    monkeypatch.setattr(cli, "render_crop", fake_crop)
    cli.cmd_render()  # без аргументов

    assert seen["manifests"].name == "manifests"
    assert seen["inputs"].name == "inputs"
    assert seen["out"].name == "reels-out"


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

    assert rc == 1                                   # ненулевой код возврата
    err = capsys.readouterr().err
    assert "ffmpeg не найден в PATH" in err          # внятное сообщение
    assert "Traceback" not in err                    # не голый traceback
