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
