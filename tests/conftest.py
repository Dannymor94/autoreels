"""Общие фикстуры pytest. Реальные ответы LLM и короткие транскрипты — в tests/fixtures/."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Тесты гоняются от корня репо; пакет лежит в src/ (layout из PROJECT_STRUCTURE).
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

FFMPEG = shutil.which("ffmpeg")
# Длительность синтетического клипа (сек). Фикстура генерится ffmpeg-ом, не хранится в git.
SYNTH_DURATION = 5


@pytest.fixture(autouse=True)
def _isolate_machine_local_state(tmp_path, monkeypatch):
    """Перенаправить машинно-локальные записи (история прогонов, калибровка токенов) в tmp.

    cmd_run/cmd_status зовутся с root=REPO_ROOT (там конфиги), а часть путей записи не берётся
    из root вовсе (token_scale.json прибит к пакету). Без изоляции они копились бы в рабочем
    репо на каждом прогоне тестов. Тесты могут переопределить env своим путём."""
    monkeypatch.setenv("AUTOREELS_HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("AUTOREELS_TOKEN_SCALE_FILE", str(tmp_path / "token_scale.json"))


# --------------------------------------------------------------------------- repo write guard
# Каталоги под корнем репо, где живёт РЕАЛЬНОЕ состояние, которое тест не должен трогать:
# reviews/ вообще не в git — запись туда стёрла бы ручную разметку безвозвратно.
_GUARD_STAT_DIRS = (          # снимок по (mtime, size) — небольшие, ловим и правки на месте
    "manifests", "transcripts", "reviews", "reels-out", "inputs", "inputs-archive",
    "calibrations", "config", "data/runs", "data/outputs", "data/blocks_dataset",
)
_GUARD_SET_DIRS = ("data/cache",)   # тысячи файлов, контент-адресные → следим за появлением/удалением
# Тесту, которому НУЖЕН реальный корень, добавь маркер @pytest.mark.uses_real_repo и обоснуй —
# молча исключать нельзя (см. docs). Пока таких нет.


def _guard_snapshot(root: Path) -> tuple[dict, set]:
    """(stat_snap, name_set) реального репо: файлы под корнем и watched-каталогами."""
    stat_snap: dict[str, tuple[int, int]] = {}
    # Файлы верхнего уровня корня и data/ (ловит data/token_scale.json, изменения PLAN.md и т.п.).
    for base in (root, root / "data"):
        if base.is_dir():
            for e in os.scandir(base):
                if e.is_file():
                    st = e.stat()
                    stat_snap[e.path] = (st.st_mtime_ns, st.st_size)
    for d in _GUARD_STAT_DIRS:
        p = root / d
        if not p.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(p):
            for f in files:
                fp = os.path.join(dirpath, f)
                try:
                    st = os.stat(fp)
                    stat_snap[fp] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    pass
    name_set: set[str] = set()
    for d in _GUARD_SET_DIRS:
        p = root / d
        if not p.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(p):
            for f in files:
                name_set.add(os.path.join(dirpath, f))
    return stat_snap, name_set


@pytest.fixture(autouse=True)
def _guard_repo_writes(_isolate_machine_local_state, request):
    """Провалить тест, который создал / изменил / удалил файл под корнем репозитория.

    Ставит границу под баг «тесты пишут в реальный репо» (manifests/, transcripts/,
    data/token_scale.json уже затирались и восстанавливались вручную). Зависит от изоляции —
    та отрабатывает раньше, так что перенаправленные записи снимок не видит."""
    if request.node.get_closest_marker("uses_real_repo"):
        yield
        return
    before_stat, before_set = _guard_snapshot(_REPO)
    yield
    after_stat, after_set = _guard_snapshot(_REPO)
    added = (set(after_stat) - set(before_stat)) | (after_set - before_set)
    removed = (set(before_stat) - set(after_stat)) | (before_set - after_set)
    changed = {p for p in before_stat if p in after_stat and before_stat[p] != after_stat[p]}
    problems = sorted(added | removed | changed)
    if problems:
        rel = "\n  ".join(sorted(
            f"{'+' if p in added else '-' if p in removed else '~'} {os.path.relpath(p, _REPO)}"
            for p in problems
        ))
        pytest.fail(
            f"test touched {len(problems)} file(s) under the repository root "
            f"(must write only under tmp_path):\n  {rel}"
        )


@pytest.fixture(autouse=True)
def _sandbox_repo_root(request, tmp_path, monkeypatch):
    """Модулям с USE_SANDBOX_ROOT=True подменить REPO_ROOT на tmp-песочницу с КОПИЕЙ config/.

    Тесты передают root=REPO_ROOT ради конфигов, но тот же root служит корнем ЗАПИСИ (cache_dir,
    inputs-archive, manifests, reviews…). Песочница даёт рабочие конфиги, а записи остаются в tmp —
    корень «не может быть репозиторием». config КОПИРУЕТСЯ, а не симлинкается: иначе Path.resolve()
    увёл бы пути назад в реальный репо и обошёл фикстуру _no_local_render_cfg (она сверяет префикс
    пути с REPO_ROOT). Прочее (prompts, aliases.sh) читается не из root, песочнице не нужно."""
    mod = request.module
    if mod is None or not getattr(mod, "USE_SANDBOX_ROOT", False):
        return
    sandbox = tmp_path / "_repo"
    sandbox.mkdir()
    real_config = _REPO / "config"
    if real_config.is_dir():
        shutil.copytree(real_config, sandbox / "config")   # copy: resolve() must stay in tmp
    real_prompts = _REPO / "prompts"
    if real_prompts.is_dir():
        (sandbox / "prompts").symlink_to(real_prompts)      # read-only (root/prompts/... in select.py)
    for env_name in (".env", ".env.txt"):                   # _load_env reads root/.env → require_key
        src = _REPO / env_name
        if src.is_file():
            shutil.copy2(src, sandbox / env_name)
    monkeypatch.setattr(mod, "REPO_ROOT", sandbox, raising=False)
    # main-based tests resolve the root via _project_root() (not REPO_ROOT) → point it at the
    # sandbox too, so their default cache_dir/manifests/… also land in tmp. Tests that set
    # _project_root themselves just override this (later setattr wins).
    monkeypatch.setattr("autoreels.__main__._project_root", lambda: sandbox)


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
