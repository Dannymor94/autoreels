# TASK M142 (окно MAIN, Mac): первая буква слова в начале клипа + тон сценариста

Файлы — ветка `handoff`, папка `handoff/m142/`: `TASK-M142.md`, `m142-start.patch`, `onset.py`. Около 30 минут, без платных моделей.

## Зачем
Владелец о IMG_6848 (m126): «часто не слышно первой буквы слова», «r01 — первая фраза плохо слышна», «r04 — начало можно чуть расширить», «в 9 недоговорил»; «можно задавать тон сценаристу — строгий или фановый». Pxl 112938952 (m136) — «норм».
- Перед первым словом клипа сейчас остаётся `seam_pad_sec` = 0.04 с воздуха, как на внутреннем стыке. Выровненное начало слова бывает позже первой согласной, и она срезается.
- Патч: `start_pad_sec` в `r0.yaml` (0 = как раньше) — воздух перед первым звуком клипа (начало тела и холодный старт). Он никогда не заходит в речь перед этим словом: рез посередине тишины.
- `autocut.scenario_tone` (`""` = нет) — одна строка тона в промпте сценариста; проверки строк те же.
- Тесты `tests/test_m142_start.py` (5), записи в REEL_SPEC и R0_SPEC.

## Правила
Как в m136: СТОП при несовпадении; `reviews/IMG_6848.review.json` сохранить и вернуть; `config/r0.yaml` правится только командами и правилом задачи; `--install`, `arl auto` не запускать; pytest только в шаге 1.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m142
git apply --check handoff/m142/m142-start.patch && git apply handoff/m142/m142-start.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config docs R0_SPEC.md && git commit -m "Plan (M142): air before a clip's first sound (start_pad_sec, off) — the owner: «не слышно первой буквы слова»; the scenarist's tone (scenario_tone)" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли; коммит запушен.

## Шаг 2. Замер: начала врезаны? (тот же черновик, 0.04 против 0.15)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m142
R=reviews/IMG_6848.review.json; B=handoff/m142/IMG_6848.review.json.before; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
sed -i '' 's/^start_pad_sec: .*/start_pad_sec: 0.15/' config/r0.yaml
arl blocks --apply reviews/IMG_6848_auto_m126-scen.txt --labeler auto > handoff/m142/apply.txt 2>&1; echo "rc=$?"
cp "$R" reviews/IMG_6848_m142.review.json
if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm -f "$R" && echo "review.json не было — убран"; fi
git checkout config/r0.yaml; git diff --stat config/r0.yaml
.venv/bin/python handoff/m142/onset.py reviews/IMG_6848_m126.review.json reviews/IMG_6848_m142.review.json 2>&1 | tee handoff/m142/onset.txt
arl blocks-text IMG_6848 > handoff/m142/blocks-text.txt 2>&1; wc -l handoff/m142/blocks-text.txt
grep -nE "^M[0-9]+ " reviews/IMG_6848_auto_m126-scen.txt > handoff/m142/draft-lines.txt; wc -l handoff/m142/draft-lines.txt
```
Ожидается: `rc=0`; `review.json возвращён`; `git diff --stat config/r0.yaml` пуст; в `onset.txt` две секции по клипам — «первый звук ок/ВРЕЗАН (+N dB до реза)», громкость первых 2 с, итог «врезанных начал: N»; `blocks-text.txt` и `draft-lines.txt` не пустые (по ним ассистент разберёт r01, r04, r09).

## Шаг 3. Решение и гейт (агент применяет сам)
- Если в секции `m142` «врезанных начал» **меньше**, чем в `m126`, а в `apply.txt` нет `[ERROR]`: в `config/r0.yaml` поставить `start_pad_sec: 0.15`, коммит `Plan (M142): start_pad_sec 0.15 on (m142 IMG_6848: cut-in starts <old> → <new>)`, push. Затем рендер для глаз и ушей:
  ```bash
  arl render --manifest reviews/IMG_6848_m142.review.json --reels 1,4,9 --gate m142 --encoder hevc_videotoolbox 2>&1 | tail -6
  ls reels-out/IMG_6848/_gate/m142/r*.mp4
  ```
  Если `--reels` не принимает список — `1-9`, и так и написать.
- Иначе флаг не трогать, рендер не делать, написать в отчёт.

## Шаг 4. Отчёт
`handoff/m142/REPORT.md`: коммиты, pytest, `onset.txt` целиком, решение, пути клипов.
`bash handoff/bin/report.sh m142 onset.txt blocks-text.txt draft-lines.txt`
Владельцу — две строки: «врезанных начал было N, стало M»; «слушать: reels-out/IMG_6848/_gate/m142/ r01, r04, r09 — первая буква слышна?».

Тон сценариста в этой задаче не запускается (платная модель). Владелец пробует сам: `arl autocut IMG_6848 --scenario --llm sonnet --ac scenario_tone=фановый`.

Статус: IMPLEMENTED, GATE PENDING.
