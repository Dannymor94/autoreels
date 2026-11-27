import json
import os
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture()
def tmp_root(tmp_path):
    reels = tmp_path / "reels-out" / "DEMO"
    reels.mkdir(parents=True)
    gate = reels / "_gate" / "variant_b"
    gate.mkdir(parents=True)

    fake_mp4 = b"\x00" * 200

    for name in ("r01", "r02"):
        (reels / f"{name}.mp4").write_bytes(fake_mp4)
        (reels / f"{name}.render.json").write_text(json.dumps({"fingerprint": f"fp_{name}"}))
    (gate / "r01.mp4").write_bytes(fake_mp4)

    return tmp_path


@pytest.fixture()
def client(tmp_root):
    import autoreels.orchestr.settings as _s
    from autoreels.orchestr.settings import Settings
    _s.settings = Settings.from_env(root_override=str(tmp_root))

    from autoreels.orchestr.app import app
    return TestClient(app, base_url="http://127.0.0.1:8765", raise_server_exceptions=True)


def test_health(client, tmp_root):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["schema_version"] == 1
    assert data["root"] == str(tmp_root.resolve())


def test_sources(client):
    r = client.get("/api/sources")
    assert r.status_code == 200
    stems = [s["stem"] for s in r.json()]
    assert "DEMO" in stems
    demo = next(s for s in r.json() if s["stem"] == "DEMO")
    assert demo["clip_count"] > 0


def test_clips(client):
    r = client.get("/api/sources/DEMO/clips")
    assert r.status_code == 200
    clips = [c["clip"] for c in r.json() if c["variant"] == ""]
    assert "r01" in clips


def test_clips_gate_variant(client):
    r = client.get("/api/sources/DEMO/clips")
    assert r.status_code == 200
    variants = [c["variant"] for c in r.json()]
    assert "_gate/variant_b" in variants


def test_clips_fingerprint(client):
    r = client.get("/api/sources/DEMO/clips")
    clips = {(c["clip"], c["variant"]): c for c in r.json()}
    assert clips[("r01", "")]["fingerprint"] == "fp_r01"


def test_range_206(client):
    r = client.get("/api/media/DEMO/r01", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100


def test_traversal_stem(client):
    r = client.get("/api/media/../x/r01")
    assert r.status_code == 404


def test_traversal_clip(client):
    r = client.get("/api/media/DEMO/../../etc/passwd")
    assert r.status_code == 404


def test_traversal_variant(client):
    r = client.get("/api/media/DEMO/r01?variant=_gate/../../x")
    assert r.status_code == 404


def test_symlink_outside(client, tmp_root):
    evil = tmp_path_factory = tmp_root.parent / "evil.mp4"
    evil.write_bytes(b"\x00" * 50)
    link = tmp_root / "reels-out" / "DEMO" / "r99.mp4"
    link.symlink_to(evil)
    r = client.get("/api/media/DEMO/r99")
    assert r.status_code == 404


def test_default_bind():
    from autoreels.orchestr.settings import Settings
    s = Settings.from_env()
    assert s.root.is_absolute()
    assert s.port == 8765


# --- added in U1-fix ---------------------------------------------------------

def test_each_test_gets_its_own_root(tmp_path):
    """Guard: the app must read settings at call time, not at import time."""
    import autoreels.orchestr.settings as _s
    from autoreels.orchestr.settings import Settings
    from autoreels.orchestr.app import app

    roots = [tmp_path / "a", tmp_path / "b"]
    for r in roots:
        (r / "reels-out").mkdir(parents=True)
        _s.settings = Settings.from_env(root_override=str(r))
        assert TestClient(app, base_url="http://127.0.0.1:8765").get("/api/health").json()["root"] == str(r.resolve())


def test_clips_listing_traversal_rejected(client, tmp_root):
    (tmp_root / "r09.mp4").write_bytes(b"secret")   # one level above reels-out
    for stem in ("%2E%2E", "..", "%2E%2E%2F%2E%2E"):
        assert client.get(f"/api/sources/{stem}/clips").status_code == 404


def test_error_files_not_listed(client, tmp_root):
    (tmp_root / "reels-out" / "DEMO" / "r01.ERROR.mp4").write_bytes(b"x")
    clips = [c["clip"] for c in client.get("/api/sources/DEMO/clips").json()]
    assert "r01.ERROR" not in clips
    src = client.get("/api/sources").json()[0]
    assert src["clip_count"] == 2


def test_symlink_outside_not_listed(client, tmp_root):
    evil = tmp_root.parent / "evil2.mp4"
    evil.write_bytes(b"\x00" * 50)
    (tmp_root / "reels-out" / "DEMO" / "r98.mp4").symlink_to(evil)
    clips = [c["clip"] for c in client.get("/api/sources/DEMO/clips").json()]
    assert "r98" not in clips


def test_render_inventory_is_read_only_and_has_no_assumed_worker(client, tmp_root, monkeypatch):
    from autoreels.orchestr import render_targets

    # Even environment values which look like a hostname or executor
    # configuration cannot invent a registered, authorized worker.
    monkeypatch.setenv("AUTOREELS_RENDER_TARGET", "gamebox")
    before = sorted(str(p.relative_to(tmp_root)) for p in tmp_root.rglob("*"))
    result = client.get("/api/render-targets")
    assert result.status_code == 200
    data = result.json()
    assert data == {
        "schema_version": 1,
        "modes": [
            {"kind": "desktop", "integration": "cli_adapter_pending"},
            {"kind": "remote", "integration": "cli_adapter_pending"},
            {"kind": "mobile", "integration": "device_spike_pending"},
        ],
        "targets": [],
        "execution_enabled": False,
    }
    assert render_targets.RenderInventory.model_validate(data) == render_targets.inventory()
    assert client.get("/api/render-targets").json() == data
    assert client.get("/api/capabilities").json()["source"] == "fallback"
    assert client.put("/api/render-targets", json={"target_id": "gamebox"}).status_code == 405
    assert sorted(str(p.relative_to(tmp_root)) for p in tmp_root.rglob("*")) == before



def test_pipeline_settings_use_validated_cli_config_without_writes(client, tmp_root, monkeypatch):
    import shutil
    import yaml
    from autoreels.core.config import load_r0_config, load_render_config

    config = tmp_root / "config"
    config.mkdir()
    repo = Path(__file__).resolve().parents[2] / "config"
    for name in ("r0.yaml", "render.yaml"):
        shutil.copyfile(repo / name, config / name)
    # Machine-local overlay is part of the CLI contract, but its paths aren't public.
    local = config / "render.local.yaml"
    local.write_text(yaml.safe_dump({"ffmpeg": "/secret/sentinel-ffmpeg", "role": "analyze",
                                    "audio_processing": {"denoise_enabled": True}}))
    r0 = load_r0_config(config / "r0.yaml")
    render = load_render_config(config / "render.yaml")
    before = {p.name: p.read_bytes() for p in config.iterdir()}
    monkeypatch.setenv("GROQ_API_KEY", "secret-sentinel-key")
    response = client.get("/api/pipeline-settings")
    assert response.status_code == 200
    data = response.json()
    assert data["analysis_status"] == data["render_status"] == "configured"
    assert data["analysis"]["base_clips"] == r0.autocut.clips
    assert data["analysis"]["clips_every_min"] == r0.autocut.clips_every_min
    assert data["analysis"]["target_sec"] == r0.autocut.target_sec
    assert data["analysis"]["label_min_sec"] == r0.min_duration
    assert data["render"]["width"] == render.scale[0]
    assert data["render"]["profile"] == render.encoder.profile
    assert data["render"]["role"] == "analyze"
    assert data["render"]["denoise_enabled"] is True
    assert "secret" not in response.text
    assert data["preview_status"] == "not_requested" and not data["execution_enabled"]
    preview = client.get("/api/pipeline-settings", params={"clips": 7, "profile": "h264"}).json()
    assert preview["preview_status"] == "valid"
    assert preview["draft_clips"] == 7 and preview["draft_profile"] == "h264"
    assert preview["analysis"] == data["analysis"] and preview["render"] == data["render"]
    assert client.get("/api/pipeline-settings?clips=0").status_code == 422
    assert client.get("/api/pipeline-settings?clips=1.5").status_code == 422
    assert client.get("/api/pipeline-settings?profile=arbitrary").status_code == 422
    assert {p.name: p.read_bytes() for p in config.iterdir()} == before
    assert not (tmp_root / "reviews").exists()


def test_pipeline_settings_fail_closed_when_missing_invalid_or_symlink(client, tmp_root):
    empty = client.get("/api/pipeline-settings?clips=5&profile=h264").json()
    assert empty["analysis_status"] == empty["render_status"] == "missing"
    assert empty["analysis"] is None and empty["render"] is None
    assert empty["preview_status"] == "blocked"
    assert empty["draft_clips"] is None and empty["draft_profile"] is None
    config = tmp_root / "config"
    config.mkdir()
    (config / "r0.yaml").write_text("bad: config")
    assert client.get("/api/pipeline-settings").json()["analysis_status"] == "invalid"
    (config / "render.local.yaml").symlink_to(tmp_root / "missing-secret")
    assert client.get("/api/pipeline-settings").json()["render_status"] == "blocked"
    (config / "r0.yaml").unlink()
    (config / "r0.yaml").symlink_to(tmp_root / "missing-secret")
    assert client.get("/api/pipeline-settings").json()["analysis_status"] == "blocked"



def test_module_settings_preview_is_read_only(client, tmp_root, monkeypatch):
    import shutil
    import yaml
    from autoreels.core.config import load_r0_config, load_render_config

    config = tmp_root / "config"
    config.mkdir()
    repo = Path(__file__).resolve().parents[2] / "config"
    for name in ("r0.yaml", "render.yaml"):
        shutil.copyfile(repo / name, config / name)
    (config / "render.local.yaml").write_text(yaml.safe_dump({
        "ffmpeg": "/private/sentinel", "music": {"enabled": False},
    }))
    before = {p.name: p.read_bytes() for p in config.iterdir()}
    monkeypatch.setenv("GROQ_API_KEY", "secret-sentinel-key")
    response = client.get("/api/module-settings")
    assert response.status_code == 200
    base = response.json()
    assert base["schema_version"] == 1 and base["status"] == "configured"
    assert not base["apply_enabled"] and base["invalidates"] == []
    rows = {r["module"]: r for r in base["modules"]}
    assert len(rows) == 6 and all(not r["available"] for r in rows.values())
    r0 = load_r0_config(config / "r0.yaml")
    render = load_render_config(config / "render.yaml")
    assert rows["hook_rescue"]["configured"] == r0.autocut.hook_clauses_autocut
    assert rows["filler_cut"]["configured"] == r0.montage.filler_cut
    assert rows["music"]["configured"] == render.music.enabled is False
    assert "sentinel" not in response.text
    result = client.get("/api/module-settings", params={
        "hook_rescue": "off" if rows["hook_rescue"]["configured"] else "on",
        "filler_cut": "off" if rows["filler_cut"]["configured"] else "on",
        "music": "on",
    }).json()
    assert result["invalidates"] == ["proposals", "plan", "render"]
    assert result["base_sha256"] == base["base_sha256"]
    assert not result["apply_enabled"]
    changed = {r["module"]: r for r in result["modules"]}
    assert changed["music"]["proposed"] is True
    assert changed["music"]["configured"] is False
    assert client.get("/api/module-settings").json() == base
    assert client.get("/api/module-settings?music=true").status_code == 422
    assert client.put("/api/module-settings", json={"music":"on"}).status_code == 405
    assert {p.name: p.read_bytes() for p in config.iterdir()} == before


def test_module_settings_fail_closed(client, tmp_root):
    empty = client.get("/api/module-settings?music=on").json()
    assert empty == {"schema_version":1,"status":"missing","modules":[],
                     "invalidates":[],"base_sha256":None,"apply_enabled":False}
    config = tmp_root / "config"
    config.mkdir()
    (config / "r0.yaml").write_text("bad: config")
    (config / "render.yaml").write_text("bad: config")
    assert client.get("/api/module-settings").json()["status"] == "invalid"
    (config / "render.local.yaml").symlink_to(tmp_root / "missing-secret")
    assert client.get("/api/module-settings").json()["status"] == "blocked"


def test_clip_plan_exact_revision_and_repeated_occurrences(client, tmp_root):
    import hashlib
    from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Word, make_segment, make_cold_open_segment
    directory = tmp_root / "manifests"
    directory.mkdir()
    path = directory / "DEMO.json"
    reel = Reel(id="r01", start=4, end=2, reordered=True, speed=2,
                segments=[make_segment(4, 6), make_segment(0, 2)],
                cold_open=make_cold_open_segment(4, 6), score=80, hook="h",
                title="test", description="test",
                subtitles=[Word(word="Первое", t0=0.5, t1=1.0),
                           Word(word="Хук", t0=4.5, t1=5.0),
                           Word(word="Вырезано", t0=3.0, t1=3.5)])
    manifest = Manifest(source="DEMO.mp4", source_path="/private/never-return",
        source_sha256="a"*64, source_hash_scheme="partial-p1",
        duration_preset="shorts", run_key="test",
        setup=SetupProfile(setup_id="s", crop=Crop(x=0,y=0,w=360,h=640),
                           frame=[360,640], scale=[360,640]), reels=[reel])
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    before = path.read_bytes()
    response = client.get("/api/clip-plan/DEMO/r01")
    assert response.status_code == 200
    view = response.json()
    assert view["revision_sha256"] == hashlib.sha256(before).hexdigest()
    assert view["recorded_source_id"] == "partial-p1:" + "a"*64
    assert view["planned_duration_s"] == 3
    assert [w["word"] for w in view["words"]] == ["Хук", "Хук", "Первое"]
    assert [w["plan_start"] for w in view["words"]] == [0.25, 1.25, 2.25]
    assert len({w["occurrence_id"] for w in view["words"]}) == 3
    assert "private" not in response.text and path.read_bytes() == before
    assert client.get("/api/clip-plan/DEMO/r01").json() == view
    path.write_text(manifest.model_copy(update={"reels":[reel.model_copy(update={"speed":1.0})]}).model_dump_json())
    changed = client.get("/api/clip-plan/DEMO/r01").json()
    assert changed["revision_sha256"] != view["revision_sha256"] and changed["clip_ref"] != view["clip_ref"]
    path.write_text(manifest.model_copy(update={"reels":[reel,reel]}).model_dump_json())
    assert client.get("/api/clip-plan/DEMO/r01").status_code == 409
    path.unlink()
    path.symlink_to(tmp_root / "missing.json")
    assert client.get("/api/clip-plan/DEMO/r01").status_code == 404
    assert client.get("/api/clip-plan/DEMO/%2E%2E").status_code == 404


def test_synthetic_editor_disabled_read_only_and_durable_history(client, tmp_root):
    import autoreels.orchestr.settings as settings
    from autoreels.orchestr.settings import Settings
    path = tmp_root / ".ui-synthetic-editor.sqlite3"
    baseline = client.get("/api/synthetic-editor").json()
    assert baseline["enabled"] is False
    body = dict(action="edit", op_id="first", base_revision=0, base_plan_sha256="a"*64,
                clip_uid="b"*64, word_index=0, expected_text="Превет", replacement="Привет")
    assert client.put("/api/synthetic-editor", json=body).status_code == 409
    assert not path.exists()
    settings.settings = Settings.from_env(root_override=str(tmp_root), synthetic_editor=True)
    initial = client.get("/api/synthetic-editor").json()
    assert initial["enabled"] and initial["revision"] == 0
    assert not path.exists()
    body.update(base_plan_sha256=initial["plan_sha256"], clip_uid=initial["clip_uid"])
    result = client.put("/api/synthetic-editor", json=body)
    assert result.status_code == 200
    changed = result.json()
    assert changed["revision"] == 1 and changed["words"][0]["word"] == "Привет"
    assert changed["words"][0]["start"] == initial["words"][0]["start"]
    assert changed["words"][0]["end"] == initial["words"][0]["end"]
    assert client.put("/api/synthetic-editor", json=body).json() == changed
    assert client.get("/api/synthetic-editor").json() == changed
    assert client.put("/api/synthetic-editor", json={**body,"op_id":"stale"}).status_code == 409
    inverse = {**body,"action":"undo","op_id":"undo","base_revision":1,
               "base_plan_sha256":changed["plan_sha256"],"expected_text":"Привет","replacement":"Превет"}
    restored = client.put("/api/synthetic-editor", json=inverse).json()
    assert restored["revision"] == 2 and restored["words"] == initial["words"]
    assert restored["redo"] is not None and restored["undo"] is None
    redo = {**body,"action":"redo","op_id":"redo","base_revision":2,
            "base_plan_sha256":restored["plan_sha256"]}
    redone = client.put("/api/synthetic-editor", json=redo).json()
    assert redone["revision"] == 3 and redone["words"] == changed["words"]
    assert len(redone["history"]) == 3 and redone["clip_uid"] == initial["clip_uid"]
    assert client.get("/api/synthetic-editor").json() == redone
    assert client.put("/api/synthetic-editor", json=body).json() == redone
    assert path.is_file()


def test_synthetic_editor_symlink_storage_blocked(client, tmp_root):
    import autoreels.orchestr.settings as settings
    from autoreels.orchestr.settings import Settings
    settings.settings = Settings.from_env(root_override=str(tmp_root), synthetic_editor=True)
    target = tmp_root.parent / "sentinel-editor"
    target.write_bytes(b"untouched")
    (tmp_root / ".ui-synthetic-editor.sqlite3").symlink_to(target)
    assert client.get("/api/synthetic-editor").status_code == 409
    assert target.read_bytes() == b"untouched"


def test_synthetic_cut_preview_read_only(client,tmp_root):
    import autoreels.orchestr.settings as settings
    from autoreels.orchestr.settings import Settings
    before = sorted(str(p.relative_to(tmp_root)) for p in tmp_root.rglob("*"))
    assert client.get("/api/synthetic-cut").json()["enabled"] is False
    settings.settings = Settings.from_env(root_override=str(tmp_root),synthetic_editor=True)
    response = client.get("/api/synthetic-cut")
    assert response.status_code == 200
    view = response.json()
    assert view["enabled"] and view["source_duration"] == 3
    assert len(view["sentences"]) == 3
    plans = {tuple(p["removed"]):p for p in view["plans"] if p["order"] == sorted(p["order"])}
    baseline, cut = plans[()], plans[(2,)]
    assert len(cut["windows"]) == 2 and 0 < cut["duration"] < baseline["duration"]
    for removed, plan in plans.items():
        assert len(removed) < 3 and plan["duration"] > 0
        offset = 0
        for window in plan["windows"]:
            assert 0 <= window["source_start"] < window["source_end"] <= 3
            assert window["output_start"] == pytest.approx(offset)
            offset += window["source_end"]-window["source_start"]
            assert window["output_end"] == pytest.approx(offset)
            for s in view["sentences"]:
                if s["number"] in removed:
                    assert min(s["end"],window["source_end"])-max(s["start"],window["source_start"]) <= 1e-6
        assert plan["duration"] == pytest.approx(offset)
    assert client.get("/api/synthetic-cut").json() == view
    assert sorted(str(p.relative_to(tmp_root)) for p in tmp_root.rglob("*")) == before


def test_synthetic_cut_persists_exact_selection_and_restores(client,tmp_root):
    import autoreels.orchestr.settings as settings
    from autoreels.orchestr.settings import Settings
    path = tmp_root / ".ui-synthetic-editor.sqlite3"
    body=dict(op_id="cut-first",base_revision=0,base_plan_sha256="a"*64,
              clip_uid="b"*64,candidate_plan_sha256="c"*64,removed=[2])
    assert client.put("/api/synthetic-cut",json=body).status_code == 409
    assert not path.exists()
    settings.settings=Settings.from_env(root_override=str(tmp_root),synthetic_editor=True)
    original=client.get("/api/synthetic-cut").json()
    assert original["revision"]==0 and original["current_removed"]==[] and not path.exists()
    spelling=client.get("/api/synthetic-editor").json()
    candidate=next(p for p in original["plans"] if p["removed"]==[2])
    body.update(base_plan_sha256=original["plan_sha256"],clip_uid=original["clip_uid"],
                candidate_plan_sha256=candidate["plan_sha256"])
    assert client.put("/api/synthetic-cut",json={**body,"removed":[1,3]}).status_code==409
    assert not path.exists()
    response=client.put("/api/synthetic-cut",json=body)
    assert response.status_code==200,response.text
    cut=response.json()
    assert cut["revision"]==1 and cut["current_removed"]==[2]
    assert cut["plan_sha256"]==candidate["plan_sha256"] and cut["history"]==[{"revision":1,"removed":[2],"order":None}]
    assert client.get("/api/synthetic-cut").json()==cut
    assert client.get("/api/synthetic-editor").json()==spelling
    assert client.put("/api/synthetic-cut",json=body).json()==cut
    assert client.put("/api/synthetic-cut",json={**body,"op_id":"stale-cut"}).status_code==409
    edit=dict(action="edit",op_id="spelling-separate",base_revision=spelling["revision"],
              base_plan_sha256=spelling["plan_sha256"],clip_uid=spelling["clip_uid"],word_index=0,
              expected_text="Превет",replacement="Привет")
    result=client.put("/api/synthetic-editor",json=edit)
    assert result.status_code==200
    assert client.get("/api/synthetic-cut").json()==cut
    restore={**body,"op_id":"cut-restore","base_revision":1,"base_plan_sha256":cut["plan_sha256"],
             "candidate_plan_sha256":original["plan_sha256"],"removed":[]}
    result=client.put("/api/synthetic-cut",json=restore)
    assert result.status_code==200,result.text
    restored=result.json()
    assert restored["revision"]==2 and restored["current_removed"]==[]
    assert restored["plan_sha256"]==original["plan_sha256"] and restored["clip_uid"]==original["clip_uid"]
    assert restored["history"]==[{"revision":2,"removed":[],"order":None},{"revision":1,"removed":[2],"order":None}]
    assert client.put("/api/synthetic-cut",json=body).json()==restored
    assert client.get("/api/synthetic-cut").json()==restored
    assert client.get("/api/synthetic-editor").json()["words"][0]["word"]=="Привет"


def test_synthetic_reorder_cas_preserves_cut_and_legacy_retry(client,tmp_root):
    import autoreels.orchestr.settings as settings
    from autoreels.orchestr.settings import Settings
    settings.settings=Settings.from_env(root_override=str(tmp_root),synthetic_editor=True)
    view=client.get("/api/synthetic-cut").json()
    natural=next(p for p in view["plans"] if p["removed"]==[2] and p["order"]==[1,3])
    reordered=next(p for p in view["plans"] if p["removed"]==[2] and p["order"]==[3,1])
    legacy=dict(op_id="old-cut",base_revision=0,base_plan_sha256=view["plan_sha256"],
                clip_uid=view["clip_uid"],candidate_plan_sha256=natural["plan_sha256"],removed=[2])
    response=client.put("/api/synthetic-cut",json=legacy)
    assert response.status_code==200,response.text
    cut=response.json()
    op=dict(op_id="reorder",base_revision=1,base_plan_sha256=cut["plan_sha256"],
            clip_uid=cut["clip_uid"],candidate_plan_sha256=reordered["plan_sha256"],
            removed=[2],order=[3,1])
    for bad in ({**op,"order":[1,3]}, {**op,"order":[3,3]},
                {**op,"order":None,"removed":[2,0,3,1]},
                {**op,"order":[3,2]}, {**op,"candidate_plan_sha256":natural["plan_sha256"]}):
        assert client.put("/api/synthetic-cut",json=bad).status_code==409
    response=client.put("/api/synthetic-cut",json=op)
    assert response.status_code==200,response.text
    moved=response.json()
    assert moved["revision"]==2 and moved["current_removed"]==[2]
    assert moved["plan_sha256"]==reordered["plan_sha256"]
    assert moved["history"][0]=={"revision":2,"removed":[2],"order":[3,1]}
    assert reordered["windows"][0]["source_start"]>reordered["windows"][-1]["source_start"]
    assert client.get("/api/synthetic-cut").json()==moved
    assert client.put("/api/synthetic-cut",json=op).json()==moved
    assert client.put("/api/synthetic-cut",json=legacy).json()==moved
    assert client.put("/api/synthetic-cut",json={**op,"op_id":"stale-reorder"}).status_code==409
    restore={**legacy,"op_id":"restore-reordered","base_revision":2,
             "base_plan_sha256":moved["plan_sha256"],"removed":[],
             "candidate_plan_sha256":view["plan_sha256"]}
    response=client.put("/api/synthetic-cut",json=restore)
    assert response.status_code==200,response.text
    assert response.json()["plan_sha256"]==view["plan_sha256"]
