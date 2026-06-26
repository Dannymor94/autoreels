"""Загрузка конфига (core/config.py).

Инварианты: типизированный объект (не сырой dict), fail-fast на загрузке (никаких
молчаливых дефолтов), пресет длины резолвится в числа в единственном месте, профиль
сетапа валидируется (crop в границах кадра, scale = [1080,1920]). Опечатка в ключе
обязана падать на загрузке (extra='forbid').
"""
import json
from pathlib import Path

import pytest

from autoreels.core.config import (
    ConfigError,
    R0Config,
    RenderConfig,
    load_r0_config,
    load_render_config,
    load_profile,
)
from autoreels.core.models import SetupProfile

ROOT = Path(__file__).resolve().parents[1]
R0_YAML = ROOT / "config" / "r0.yaml"
RENDER_YAML = ROOT / "config" / "render.yaml"
PROFILE_JSON = ROOT / "profiles" / "tearoom_main.json"


# ---- happy path: реальные файлы репозитория ----

def test_load_r0_config_returns_typed_object():
    cfg = load_r0_config(R0_YAML)
    assert isinstance(cfg, R0Config)
    assert cfg.min_score == 65
    assert cfg.max_reels is None
    assert "shorts" in cfg.presets


def test_preset_resolves_shorts_to_15_59():
    # Единственное место, где пресет превращается в числа. Сверка с config/r0.yaml.
    cfg = load_r0_config(R0_YAML)
    assert cfg.duration_preset == "shorts"
    assert cfg.min_duration == 15
    assert cfg.max_duration == 59


def test_load_render_config_returns_typed_object():
    cfg = load_render_config(RENDER_YAML)
    assert isinstance(cfg, RenderConfig)
    assert cfg.scale == [1080, 1920]
    assert cfg.subtitles.font == "Montserrat"


def test_load_profile_returns_setup_profile():
    prof = load_profile(PROFILE_JSON)
    assert isinstance(prof, SetupProfile)
    assert prof.setup_id == "tearoom_main"
    assert prof.scale == [1080, 1920]


# ---- fail-fast ----

def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_unknown_duration_preset_raises(tmp_path):
    text = R0_YAML.read_text(encoding="utf-8").replace(
        "duration_preset: shorts", "duration_preset: bogus"
    )
    p = _write(tmp_path, "r0.yaml", text)
    with pytest.raises(ConfigError) as e:
        load_r0_config(p)
    assert "bogus" in str(e.value)  # внятно: какой пресет неизвестен


def test_broken_yaml_raises(tmp_path):
    p = _write(tmp_path, "r0.yaml", "duration_preset: : : [unbalanced\n  - ]")
    with pytest.raises(ConfigError):
        load_r0_config(p)


def test_incomplete_config_raises(tmp_path):
    # Неполный конфиг (нет min_score) → ошибка на загрузке, не молчаливый дефолт.
    p = _write(tmp_path, "r0.yaml", "duration_preset: shorts\n")
    with pytest.raises(ConfigError):
        load_r0_config(p)


def test_typo_in_key_raises(tmp_path):
    # Опечатка в ключе (min_scor вместо min_score) обязана упасть, а не утечь в R0.
    text = R0_YAML.read_text(encoding="utf-8").replace("min_score:", "min_scor:")
    p = _write(tmp_path, "r0.yaml", text)
    with pytest.raises(ConfigError):
        load_r0_config(p)


def test_profile_crop_out_of_frame_raises(tmp_path):
    data = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
    data["frame"] = [1920, 1080]  # кроп 980+1010=1990 > 1920 → вне кадра
    p = _write(tmp_path, "bad.json", json.dumps(data))
    with pytest.raises(ConfigError) as e:
        load_profile(p)
    assert "кадр" in str(e.value).lower() or "frame" in str(e.value).lower()


def test_profile_wrong_scale_raises(tmp_path):
    data = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
    data["scale"] = [720, 1280]
    p = _write(tmp_path, "bad.json", json.dumps(data))
    with pytest.raises(ConfigError):
        load_profile(p)
