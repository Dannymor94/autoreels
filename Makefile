.PHONY: setup test

VENV ?= .venv
PY := $(VENV)/bin/python
# Проекту нужен Python 3.11+. Системный python3 на Mac бывает 3.9 — берём первый подходящий.
PYTHON ?= $(shell for p in python3.13 python3.12 python3.11; do command -v $$p >/dev/null 2>&1 && { echo $$p; break; }; done)

# Окружение для юнит-слоя. Его сам вызывает исполнитель петли перед агентом; повторный запуск безопасен.
# numpy нужен тестам карты речи/просодии, но не объявлен в pyproject — временно ставим явно
# (задача петли: объявить зависимость).
setup:
	@test -n "$(PYTHON)" || { echo "Нужен Python 3.11+ (python3.13, python3.12 или python3.11 в PATH)"; exit 1; }
	@test -x $(PY) || $(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -q -e ".[dev]" numpy

# Падают на чистой машине без локальных данных и ключей (см. .loop/PROJECT.md, «Известное состояние»).
# Временно исключены, чтобы CI и агенты видели зелёный юнит-слой. Убирает их отсюда задача этапа 1,
# которая их чинит (Makefile защищён — понадобится одобрение владельца, это и есть проверка).
KNOWN_FAILING := \
	tests/test_cli.py::test_run_dispatch_bad_path_returns_error \
	tests/test_cli.py::test_run_dispatch_url_calls_download \
	tests/test_cli.py::test_run_dispatch_url_download_error_returns_1 \
	tests/test_cli.py::test_run_dispatch_yandex_calls_yandex_downloader \
	tests/test_map.py::test_voice_profile_measures_level_pitch_and_range \
	tests/test_montage.py::test_voice_level_and_pitch_of_a_stretch \
	tests/test_providers.py::test_r0_output_parsing_survives_lower_max_tokens

# Весь юнит-слой (integration по умолчанию отключены в pyproject).
test:
	$(PY) -m pytest -q -p no:cacheprovider $(addprefix --deselect ,$(KNOWN_FAILING))
