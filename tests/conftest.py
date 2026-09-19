"""Общие фикстуры pytest. Реальные ответы LLM и короткие транскрипты — в tests/fixtures/."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Тесты гоняются от корня репо; пакет лежит в src/ (layout из PROJECT_STRUCTURE).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

FFMPEG = shutil.which("ffmpeg")
# Длительность синтетического клипа (сек). Фикстура генерится ffmpeg-ом, не хранится в git.
SYNTH_DURATION = 5


@pytest.fixture(autouse=True)
def _isolate_history(tmp_path, monkeypatch):
    """Каждый тест пишет историю прогонов в свой tmp, а не в реальный data/history.jsonl.

    cmd_run/cmd_status зовут root=REPO_ROOT (там конфиги) → без изоляции история копилась бы
    в рабочем репо на каждом прогоне тестов (та же ловушка, что с manifests/). Тесты истории
    могут переопределить env своим путём."""
    monkeypatch.setenv("AUTOREELS_HISTORY_PATH", str(tmp_path / "history.jsonl"))


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory) -> Path:
    """Синтетический клип (sine 440 Гц + testsrc) под тесты извлечения аудио.

    Бинарник в git не хранится — генерируется ffmpeg-ом в session-tmp (чистится pytest).
    Если ffmpeg не установлен — тест пропускается, а не падает.
    """
    if FFMPEG is None:
        pytest.skip("ffmpeg не установлен — пропуск тестов, требующих реального извлечения")
    out = tmp_path_factory.mktemp("media") / "fixture.mp4"
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={SYNTH_DURATION}",
        "-f", "lavfi", "-i", f"testsrc=duration={SYNTH_DURATION}:size=320x240",
        "-shortest", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out
