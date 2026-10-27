# TASK M165 (окно MAIN или второе; Mac + gamebox): голос ведущего — карта говорящих и переключатель

Владелец 2026-10-27: «нужно распознавать голос интервьюера — там бывают смешные моменты или контекст к ролику; нужна гибкость и переключатель: включать интервьюера или нет». Замер m141: правило «пауза + вы/ты» ловило 6 из 55 вопросов ведущего.

Патч:
- `arl speakers <ист>` — карта говорящих `transcripts/<ист>.speakers.json`. Её даёт pyannote через `tools/diarize.py` в своём окружении (`--python ~/.venvs/m141/bin/python`) или импорт готового разделения (`--from data/cache/m141/<ист>.diar.json`). Главный говорящий — у кого больше речи, все остальные — «ведущий».
- `autocut.interviewer` (в репо `on`):
  - `on` — реплики ведущего можно брать как контекст (вопрос, открывающий ролик) или живую реплику (шутка, смех). Спикер должен говорить больше половины ролика. Сценарист видит фразы ведущего с пометкой «[ведущий]»;
  - `off` — ролики без реплик ведущего;
  - `""` — карта не читается, как до M165.
- На один прогон: `arl auto … --interviewer on|off`.
- Без карты говорящих ничего не меняется.
- Тесты `tests/test_m165_speakers.py` (9), PLAN, R0_SPEC, README, PROJECT_STRUCTURE.

## Правила
1. Шаг упал → **СТОП**.
2. pytest — без рендера на Mac. Если на Mac идёт m163, pytest шага 1 не запускать до её конца (или делать патч в worktree, как в m156). Рендер шага 3 — на gamebox (`--remote`), Mac не занимает.
3. `--install` не запускать, `manifests/` и `reviews/*_answer*.txt` не трогать.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels (auto|render)" && echo "ИДЁТ РЕНДЕР — pytest позже" || echo "свободно"
bash handoff/bin/take.sh m165
git apply --check handoff/m165/m165-speakers.patch && git apply handoff/m165/m165-speakers.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests tools config PLAN.md R0_SPEC.md README.md PROJECT_STRUCTURE.md && git commit -m "Speakers (M165): the speaker map (arl speakers, pyannote or m141 import) and autocut.interviewer on|off — the host's lines as context/exchange or none" && git push && git log --oneline -1
```

## Шаг 2. Карты говорящих из готового замера m141
Время в разделении — время исходника, поэтому сжатая копия PXL берёт разделение оригинала (та же временная шкала).
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
for S in "2026-08-08 09h 33m 14s" "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s" IMG_6848 "Pxl 20260621 112938952" "Pxl 20260621 122006193"; do
  arl speakers "$S" --from "data/cache/m141/$S.diar.json" 2>&1 | tail -1; done | tee handoff/m165/speakers.txt
arl speakers PXL_20260729_copy --from data/cache/m141/PXL_20260729_085910095_34f06abf.diar.json 2>&1 | tail -1 | tee -a handoff/m165/speakers.txt
```
Ожидается семь строк «✓ … говорящих N … главный …».

## Шаг 3. Интервью заново, с ведущим (gamebox)
IMG_6848 и PXL_copy — источники с вопросами ведущего (26 и 28). Сценарист пишет заново: в запросе теперь есть пометки «[ведущий]», поэтому это новый запрос, не из кэша. Рендер — на gamebox.
```bash
nohup .venv/bin/python -m autoreels auto IMG_6848 PXL_20260729_copy --gate m165 --tag m165 --interviewer on --remote > handoff/m165/auto.txt 2>&1 &
echo "pid $!"
```
До `=== auto: итог` проверять `tail -5`. Затем:
```bash
sed -n '/=== auto: итог/,$p' handoff/m165/auto.txt | tee handoff/m165/itog.txt
grep -hE "ведущий:" handoff/m165/auto.txt | sort | uniq -c | head -20 | tee handoff/m165/host.txt
grep -c "ведущий: " reviews/IMG_6848_auto_m165.txt reviews/PXL_20260729_copy_auto_m165.txt 2>/dev/null | tee -a handoff/m165/host.txt
for S in IMG_6848 PXL_20260729_copy; do d="reels-out/$S/_gate/m165"; echo "$S: клипов $(ls $d/r*.mp4 2>/dev/null | grep -vc ERROR), постов $(ls $d/r*.post.txt 2>/dev/null | wc -l | tr -d ' '), с ошибкой $(ls $d/*ERROR* 2>/dev/null | wc -l | tr -d ' ')"; done | tee handoff/m165/clips.txt
```

## Шаг 4. Отчёт
`handoff/m165/REPORT.md`: коммит, pytest, `speakers.txt`, `itog.txt`, `host.txt` (сколько роликов взяли ведущего и какие строки — 3–5 примеров из черновиков с заметкой «ведущий: …»), `clips.txt`.
`bash handoff/bin/report.sh m165 speakers.txt itog.txt host.txt clips.txt`
Владельцу: «сравни листы reels-out/IMG_6848/_gate/m165 и …/PXL_20260729_copy/_gate/m165 (с ведущим) против _gate/m157 (без него): реплики ведущего к месту?».

Статус: IMPLEMENTED, GATE PENDING.
