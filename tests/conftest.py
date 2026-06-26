"""Общие фикстуры pytest. Реальные ответы LLM и короткие транскрипты — в tests/fixtures/."""
import sys
from pathlib import Path

# Тесты гоняются от корня репо; пакет лежит в src/ (layout из PROJECT_STRUCTURE).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
