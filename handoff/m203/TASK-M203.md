# TASK M203 (окно MAIN, Mac): ключевые слова `k:` без модели — правило, замер с голосом, пробный прогон

Файлы — ветка `handoff`, папка `handoff/m203/`: `TASK-M203.md`, `m203-keywords-rule.patch` (написан и прогнан ассистентом, ложится на `main` после M202).
Около 30 минут: замер и один прогон `arl auto` без рендера. Отчёт — только на русском.

## Зачем
Платного API нет (Claude: HTTP 403 с 30.10). В m202 все 65 запросов `k:` упали, и у клипов нет ключевых слов. Владелец, 2026-11-02: детерминированные механики вместо модели.

**Замер ассистента** на разметке владельца (`manifests/<источник>.json`, слова с `emph`: 68 клипов, 56 с `k:`, 135 слов):
- `k:` стоит в последней фразе клипа в 82 % клипов, в первой — в 48 %, в фразе из середины — в 13 %, в вопросе — в 7 %;
- внутри отмеченной фразы слово владельца — последнее содержательное в 47 %. Редкость, часть речи и повтор ничего к этому не добавили (перебор весов);
- правило по тексту при 2 словах на клип: 35 из 112 точно в слово владельца (31 %); случайное содержательное слово — 6 %.

Голос (растяжка слова, M99: 65 % против ~50 %) можно замерить только здесь: `transcripts/*.prosody.json` есть только на Mac.

## Что вносит патч
- `cloud/autocut.py` — `keywords_rule(rows, n, voiced)`. Порядок фраз: последняя → первая → середина по порядку; вопросы пропускаются. Слово — последнее содержательное: ≥ 3 букв, не стоп-слово, с pymorphy3 — значимая часть речи; одна лемма один раз. С `voiced` — слово, которое протягивает голос, если оно среди кандидатов.
- `config/r0.yaml`, autocut:
  - `keywords_source: model | rule | fallback` — по умолчанию `model`, как раньше. `rule` — без модели; `fallback` — модель, а правило, если модель ничего не дала;
  - `keywords_rule_voice: false`.

  Правило работает и при `--llm none`. В черновике заметка «k: по правилу (без модели)».
- `tools/kw_rule_check.py` — замер правила против `k:` владельца: rule, rule+voice (если есть prosody), случайный выбор. Только чтение.
- `tests/test_m203_keywords_rule.py` — 9 тестов; без кода патча не собираются.

Значение по умолчанию (`model`) выход не меняет. Ассистент прогнал весь набор поверх M202: 2650 прошли (было 2641 + 9). Упали прежние 8, включая флейк `test_menu_bash::…profile_picker…`.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел — не СТОП.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:**
   - ничего, кроме того, что вносит патч;
   - `keywords_source` в `config/r0.yaml` после части 3 вернуть в `model` (`git checkout config/r0.yaml`) — включает владелец по замеру;
   - `.env` не трогать;
   - гейты `m183`, `m196`, `m200`, `rp1`, `rp2` и их `reviews/*` не трогать.

   Без рендера, без `--install`. `arl export`, `arl crosspost` и сетку не запускать.
4. Итог — «IMPLEMENTED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m203
ls transcripts/*.prosody.json | grep -cE "disko_beach_p[123]|day_yoga_p[12]|prew_isaev_(anna|danny)"
.venv/bin/python -c "import pymorphy3; print('pymorphy3 есть')"
```
Ожидается:
- ветка `main`, чисто (кроме `handoff/`), последний коммит — M202 (`9ecda35`);
- prosody — `7`;
- «pymorphy3 есть». Если нет — **СТОП**: `.venv/bin/pip install -e ".[nlp]"` — решение владельца.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m203/m203-keywords-rule.patch && git apply handoff/m203/m203-keywords-rule.patch && echo applied
.venv/bin/python -m pytest tests/test_m203_keywords_rule.py tests/test_m202_replay_accounting.py tests/test_autocut.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml src/autoreels/__main__.py src/autoreels/cloud/autocut.py src/autoreels/core/config.py tests/test_m203_keywords_rule.py tools/kw_rule_check.py
git commit -m "Keywords (M203): k: without a model — autocut.keywords_source model|rule|fallback (default model): the last sentence, then the first, then the middle, no questions, the last content word or the one the voice draws out (owner's 68 clips: 31 % exact words vs 6 % random); tools/kw_rule_check.py measures it"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- первая строка pytest — все прошли;
- весь набор — прежнее число плюс 9. Если упал только `test_menu_bash::…profile_picker…` — перезапустить отдельно; прошёл → не СТОП;
- коммит запушен.

## Часть 2. Замер против `k:` владельца — по тексту и с голосом
```bash
cd /Users/danny/Documents/autoreels
for n in 2 owner config; do .venv/bin/python tools/kw_rule_check.py --n $n; done 2>&1 | tee handoff/m203/kw_check.txt
```
Ожидается:
- «клипов с k: 56, слов владельца 135»;
- `rule` при n=2 — 35 из 112 (31 %), как у ассистента;
- `rule+voice` — числа есть по всем 7 источникам (строки «голос замерен только для» нет);
- `random` — около 6 %.

Любое соотношение rule и rule+voice — не СТОП, это и есть замер.

## Часть 3. Пробный прогон: `k:` по правилу в настоящем `arl auto`
Голос — только если в части 2 при n=2 `rule+voice` дал больше попаданий, чем `rule`.
```bash
cd /Users/danny/Documents/autoreels
V=$(.venv/bin/python - <<'EOF'
import re
t = open("handoff/m203/kw_check.txt", encoding="utf-8").read().split("n = owner")[0]
def g(k):
    m = re.search(rf"{re.escape(k)}\s+выбрано \d+, попало в слово владельца (\d+)", t)
    return int(m.group(1)) if m else -1
print("true" if g("rule+voice") > g("rule ") else "false")
EOF
); echo "голос в правиле: $V"
.venv/bin/python - "$V" <<'EOF'
import sys
from pathlib import Path
p = Path("config/r0.yaml"); t = p.read_text(encoding="utf-8")
assert t.count("  keywords_source: model") == 1 and t.count("  keywords_rule_voice: false") == 1
t = t.replace("  keywords_source: model", "  keywords_source: rule", 1)
t = t.replace("  keywords_rule_voice: false", f"  keywords_rule_voice: {sys.argv[1]}", 1)
p.write_text(t, encoding="utf-8"); print("на прогон: keywords_source rule, rule_voice", sys.argv[1])
EOF
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
.venv/bin/python -m autoreels auto "${S7[@]}" --llm cloud --gate k203 --tag k203 --no-render > handoff/m203/auto.txt 2>&1; echo "код $?"
git checkout config/r0.yaml; grep -n "keywords_source:\|keywords_rule_voice:" config/r0.yaml
sed -n '/=== auto: итог/,$p' handoff/m203/auto.txt
{ for s in "${S7[@]}"; do f=reviews/${s}_auto_all_k203.txt
    printf "%-18s сборок %2s, с k: %2s, заметок правила %2s\n" "$s" "$(grep -c '^M' "$f")" "$(grep '^M' "$f" | grep -c ' | k:')" "$(grep -c 'k: по правилу' "$f")"
  done; } | tee handoff/m203/k_count.txt
grep -h "k: по правилу" reviews/*_auto_all_k203.txt | head -20 | tee handoff/m203/k_sample.txt
grep -c "ключевые слова: модель не ответила" handoff/m203/auto.txt
git status -sb | head -5
```
Ожидается:
- после прогона `keywords_source: model`, `keywords_rule_voice: false` (файл вернулся);
- у всех 7 `✓`;
- в `k_count.txt` у каждого источника «с k:» = «сборок» или почти (сборка без единой фразы со словом — без `k:`);
- «ключевые слова: модель не ответила» — `0`: модель для `k:` не вызывается;
- `git status` чистый вне `handoff/`.

## Отчёт
`handoff/m203/REPORT.md`:
```
M203 — IMPLEMENTED, MEASURED
Коммит: <хэш>; pytest: N passed (было M); флейк menu: <да/нет>
Замер (kw_check.txt), n=2: rule <h/t, %>; rule+voice <h/t, %>; random <%>. n=owner: rule <%>, rule+voice <%>. n=config: rule <%>, rule+voice <%>
Прогон (голос в правиле: <true/false>): сборок <всего>, с k: <всего>; «модель не ответила» по k: <0>
Примеры (k_sample.txt): <3–5 строк>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m203 kw_check.txt auto.txt k_count.txt k_sample.txt
```
Владельцу в чат — 3 строки:
1. статус и коммит;
2. «k: без модели: правило <x %>, с голосом <y %>, случайно <z %> (слово в слово с владельцем)»;
3. «прогон: k: у <a> из <b> сборок; включить — keywords_source: rule (решение владельца)».
