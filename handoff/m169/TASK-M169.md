# TASK M169 (окно MAIN, Mac): продакшн — только наборы без ведущего, всё в crosspost, лишние гейты прочь

Владелец 2026-10-27: «оставить только нужные гейты; все ролики без ведущих используем — они уходят в продакшн». Это его одобрение всех клипов выбранных наборов. Наборы:
- три лекции 2026-08-08 и оба Pxl 20260621 — `_gate/m163`;
- IMG_6848 и PXL_20260729_copy — `_gate/m157` (без ведущего).

Ничего не публикуется: `arl crosspost` складывает клипы, обложки и тексты постов в `export/crosspost/` для импорта в crosspost, публикует владелец руками.

## Правила
1. Шаг упал → **СТОП**.
2. `--install` не запускать, `manifests/` и `reviews/*_answer*.txt` не трогать. Рендер один, pytest во время рендера не запускать.

## Шаг 1. Ведущий выключен по умолчанию; m163 — без реплик ведущего
С m165 в репо `autocut.interviewer: on`. 10h59 и 11h42 пересобирались в m167/m168 уже с картой говорящих, поэтому реплики ведущего могли попасть в их клипы.
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels (auto|render)" || echo "свободно"
bash handoff/bin/take.sh m169; mkdir -p handoff/m169
sed -i '' 's/^  interviewer: "on"$/  interviewer: "off"/' config/r0.yaml && grep -n '^  interviewer:' config/r0.yaml
sed -i '' 's/assert load_r0_config(REPO_ROOT \/ "config" \/ "r0.yaml").autocut.interviewer == "on"/assert load_r0_config(REPO_ROOT \/ "config" \/ "r0.yaml").autocut.interviewer == "off"/' tests/test_m165_speakers.py
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml tests/test_m165_speakers.py && git commit -m "Config (M169): autocut.interviewer off by default — owner: production clips without the interviewer (on stays a switch: arl auto --interviewer on)" && git push
for S in "2026-08-08 09h 33m 14s" "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s" "Pxl 20260621 122006193" "Pxl 20260621 112938952"; do
  echo "$S: строк с ведущим $(grep -c 'ведущий: ' "reviews/${S}_auto_m163.txt" 2>/dev/null || echo 0)"; done | tee handoff/m169/host.txt
```
Ожидается: `interviewer: "off"`, pytest — все прошли, коммит запушен. В `host.txt` по строке на источник.

Если где-то «строк с ведущим» больше 0 — пересобрать этот источник в тот же гейт без ведущего. Ответ сценариста из кэша, платно только проверки и посты:
```bash
S="<источник>"; mkdir -p "$HOME/.Trash/autoreels-m169/$S"; mv "reels-out/$S/_gate/m163" "$HOME/.Trash/autoreels-m169/$S/"
.venv/bin/python -m autoreels auto "$S" --gate m163 --tag m163 --interviewer off --encoder hevc_videotoolbox 2>&1 | tail -4
grep -c 'ведущий: ' "reviews/${S}_auto_m163.txt"   # 0
```

## Шаг 2. Лишние гейты — в Корзину
```bash
bash handoff/m169/gates.sh | tee handoff/m169/gates.txt | tail -12
bash handoff/m169/gates.sh --do | tail -2
ls -d reels-out/*/_gate/*/
ssh gamebox 'rm -rf /mnt/data/autoreels/reels-out/*/_gate/*' 2>/dev/null && echo "gamebox: гейты удалены" || echo "gamebox недоступен — пропуск"
```
Ожидается: ровно 7 папок — пять `m163` и две `m157`.

## Шаг 3. Всё в crosspost (одобрено владельцем)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
for SG in "2026-08-08 09h 33m 14s|m163" "2026-08-08 10h 59m 38s|m163" "2026-08-08 11h 42m 49s|m163" "Pxl 20260621 122006193|m163" "Pxl 20260621 112938952|m163" "IMG_6848|m157" "PXL_20260729_copy|m157"; do
  S="${SG%|*}"; G="${SG#*|}"; d="reels-out/$S/_gate/$G"
  R=$(ls "$d"/r[0-9]*.mp4 2>/dev/null | grep -v ERROR | xargs -n1 basename | sed 's/\.mp4$//' | paste -sd, -)
  for f in "$d"/r[0-9]*.mp4; do case "$f" in *ERROR*) ;; *) [ -f "${f%.mp4}.post.txt" ] || .venv/bin/python -m autoreels describe "$S" --gate "$G" --llm sonnet >/dev/null 2>&1;; esac; done
  arl crosspost "$S" --gate "$G" --reels "$R" 2>&1 | tail -2
done | tee handoff/m169/export.txt
ls export/crosspost/*.csv | while read c; do echo "$c: постов $(($(wc -l < "$c") - 1))"; done | tee -a handoff/m169/export.txt
```
Ожидается: по CSV на источник, число постов равно числу клипов набора без ERROR. Клипы, которые crosspost пропустил («нет подписи»), — в отчёт.

## Шаг 4. Отчёт
`handoff/m169/REPORT.md`: коммит, `host.txt`, `gates.txt` (сколько ушло в Корзину), `export.txt`, итог «в crosspost N клипов из 7 источников».
`bash handoff/bin/report.sh m169 host.txt gates.txt export.txt`
Владельцу: «в export/crosspost/ N клипов с постами — импортируй в crosspost (вкладка «Импорт плана»); в reels-out осталось 7 наборов».
