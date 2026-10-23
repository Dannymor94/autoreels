# TASK M135 (ПАРАЛЛЕЛЬНЫЙ агент, Mac): фиксы и уборка по ревью m133

Файлы — ветка `handoff`, папка `handoff/m135/`: `TASK-M135.md`, `m135-code.patch`, `cleanup.sh`.
Параллельно работает MAIN (m134: коммиты, рендер). Поэтому код правится **в отдельной рабочей копии**, а в основной папке трогаются только неотслеживаемые файлы по `cleanup.sh`.

## Что в патче (ассистент проверил: 2461 тест прошёл, падают только известные песочные; ложится и до, и после m134)
- `.gitignore`: правило `transcripts/   # комментарий` ничего не игнорировало (git не понимает комментарий в конце строки) → комментарий отдельной строкой; добавлены `data/models/`, `manifests/_archive/`.
- Удалены настройки, которые код не читал: `chunk_overlap_sec`, `prompt_language` (r0.yaml), `intrusion_guard_sec` и вся секция `subtitles:` в `render.yaml`. Это мёртвая копия стиля; действует `config/subtitles.yaml`, правка `render.yaml subtitles.font` ничего не меняла.
- Молчаливые `except`: битый `r0.yaml` при рендере → предупреждение; нечитаемый манифест в учёте сирот → предупреждение (его файлы и раньше не удалялись); проверка шва синтетического хвоста, которая не смогла измерить, → ошибка клипа, а не тихое «ок».
- Удалены `FallbackLLM` (нигде не создавалась) с её 4 тестами и 4 неиспользуемых импорта.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк.
2. В основной папке `/Users/danny/Documents/autoreels` не делать `git add/commit/checkout/pull/stash`. Там можно только запускать `cleanup.sh` и `git status`.
3. Не трогать: `reviews/*_answer.txt`, `manifests/`, гейт `m134` (его пишет MAIN), замки моложе суток.
4. Удалять насовсем можно только то, что удаляет `cleanup.sh` (пустые замки старше суток и `.DS_Store`). Остальное уходит в Корзину.

## Шаг 1. Отдельная рабочая копия, патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/take.sh m135
grep -nE "^subtitles:|intrusion_guard_sec|margin_v|font_dir" config/render.local.yaml 2>/dev/null || echo "render.local.yaml: удаляемых ключей нет"
W=/Users/danny/Documents/autoreels-m135
git fetch -q origin main && git worktree add -f --detach "$W" origin/main && cd "$W"
cp /Users/danny/Documents/autoreels/config/render.local.yaml config/ 2>/dev/null || true
git apply --check /Users/danny/Documents/autoreels/handoff/m135/m135-code.patch && git apply /Users/danny/Documents/autoreels/handoff/m135/m135-code.patch && echo applied
/Users/danny/Documents/autoreels/.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3
git add -A .gitignore src tests config && git status --short
git commit -m "Cleanup (M135): dead config knobs removed (render.yaml subtitles copy, intrusion_guard_sec, chunk_overlap_sec, prompt_language), silent excepts speak, FallbackLLM gone, .gitignore transcripts rule fixed (m133 review)"
git log --oneline -1
```
Ожидается: «удаляемых ключей нет» (если ключи есть в `render.local.yaml` — СТОП, назвать их); `applied`; pytest — все прошли (если упал только `test_menu_bash.py::test_menu_settings_profile_picker_and_cancel`, перезапустить его один раз); коммит есть. `git status` не показывает `config/render.local.yaml`, он в `.gitignore`.

## Шаг 2. Отправка — только когда MAIN закончил m134
```bash
cd /Users/danny/Documents/autoreels-m135
git fetch -q origin main; git log --oneline origin/main -5 | grep -c "Montage (M134)"; pgrep -fl "autoreels" || echo "autoreels не запущен"
```
- В `origin/main` есть коммит `Montage (M134)` **и** `autoreels` не запущен: выполнить `git rebase origin/main`. Если rebase что-то менял, снова прогнать pytest как в шаге 1. Затем `git push origin HEAD:main`.
- Иначе: `git push origin HEAD:refs/heads/m135` (ветка, не main) и в отчёте написать «ждёт m134 — влить: `git -C /Users/danny/Documents/autoreels-m135 rebase origin/main && git push origin HEAD:main`».

Ожидается: push прошёл (в main или в ветку `m135`), хэш в отчёт.

## Шаг 3. Уборка папки (основная копия)
```bash
cd /Users/danny/Documents/autoreels
df -h . | tail -1
bash handoff/m135/cleanup.sh | tee handoff/m135/cleanup-dry.txt | grep -E "^==|всего|ВНИМАНИЕ|пропуск"
bash handoff/m135/cleanup.sh --do | tee handoff/m135/cleanup.txt | tail -3
df -h . | tail -1; git status --short | head -20
```
Ожидается: в списке гейтов нет `m18_final m88 m94 m101 m102 m105 m112 m115 m126 m131 m134` (их держим: свежие и ещё не просмотренные владельцем); после `--do` — «СДЕЛАНО», Корзина `~/.Trash/autoreels-m135`. `git status` основной копии: изменений от уборки нет, кроме того, что уже было (`data/token_scale.json`, неотслеживаемые).

## Шаг 4. Отчёт
`handoff/m135/REPORT.md`: коммит и куда ушёл (main или ветка), строка pytest, итоги `cleanup.txt` (сколько замков, `.DS_Store`, `.bak`, гейтов и ГБ в Корзине), `df` до и после.
```bash
cd /Users/danny/Documents/autoreels
TMPDIR=$(mktemp -d) bash handoff/bin/report.sh m135 cleanup.txt
```
Владельцу — две строки: куда ушёл коммит; «в Корзине ~N ГБ старых гейтов — очисти Корзину, чтобы освободить место (или верни нужное из ~/.Trash/autoreels-m135)».

Рабочую копию `autoreels-m135` не удалять до вливания коммита в main.
