"""M211: the voice measures of the owner's thoughts against the rest (AUC per measure, within each source)."""
from __future__ import annotations

import importlib.util
import json


def _tool():
    spec = importlib.util.spec_from_file_location("voice_owner_check", "tools/voice_owner_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_auc():
    t = _tool()
    assert t.auc([3, 4], [1, 2]) == 1.0 and t.auc([1], [2]) == 0.0 and t.auc([2], [2]) == 0.5
    assert t.auc([], [1]) is None


def test_the_owners_loud_thoughts_show_as_a_signal(tmp_path, monkeypatch, capsys):
    t = _tool()
    (tmp_path / "manifests").mkdir()
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "manifests" / "v.json").write_text(json.dumps({"selection_source": "human", "reels": [
        {"id": "r01", "start": 0.0, "end": 20.0, "segments": [{"start": 0.0, "end": 20.0}]}]}), encoding="utf-8")
    units = [{"id": i + 1, "t0": 10.0 * i, "t1": 10.0 * i + 9.0, "punch": 3,
              "voice": {"level_db": -20 + (10 if i < 2 else 0) + i * 0.1, "pitch_st": 0.0, "range_st": 5.0,
                        "rate": 3.0, "energy": 90 if i < 2 else 10}} for i in range(6)]
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps({"units": units}), encoding="utf-8")
    (tmp_path / "manifests" / "w.json").write_text(json.dumps({"selection_source": "auto", "reels": []}),
                                                   encoding="utf-8")
    (tmp_path / "transcripts" / "w.map.json").write_text(json.dumps({"units": units}), encoding="utf-8")
    monkeypatch.setattr(t, "ROOT", tmp_path)
    assert t.main(["v", "w", "x"]) == 0
    out = capsys.readouterr().out
    row = next(ln for ln in out.splitlines() if ln.startswith("v "))
    nums = row.split()
    assert nums[1] == "6" and nums[2] == "2"                       # 6 thoughts, the first two in the owner's clip
    assert float(nums[3]) == 1.0 and float(nums[7]) == 1.0          # level and energy: the owner's are the loudest
    assert "нет ручной разметки" in out and "нет карты или манифеста" in out
