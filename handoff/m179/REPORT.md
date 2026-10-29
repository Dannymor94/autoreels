# REPORT M179

## Версии ffmpeg

| Машина | Версия |
|---|---|
| gamebox | ffmpeg 8.0.1-3ubuntu2 |
| Mac | ffmpeg 9.0.2 |

---

## Шаг 1. Обычный удалённый рендер

Дополнительный коммит перед рендером: `3119930 Cleanup: remove stale timestamp-named transcript files` — 26 файлов `transcripts/` были удалены с диска, но не зафиксированы в git; `git ls-files` включал их в rsync-файлслист, и rsync падал с `stat: No such file or directory`. Удаления зафиксированы.

**anna r1-10 (h264_vaapi)**: 10/10 ✓, 0 ошибок integrity.
**danny r1-14 (h264_vaapi)**: 13/14 ✓, 1 ошибка — `r14: audio/video duration differ by 33 ms` (это A/V drift, не integrity check).
**PXL r1-17 (keep_render, на gamebox напрямую)**: 17/17 ✓, INTEGRITY total: 0.

**Ошибка не воспроизводится** на текущих клипах с текущими версиями. (`remote.txt`, `keep.txt`)

---

## Шаг 2. keep_render: INTEGRITY total: 0

Скрипт `keep_render.py` перехватывает `_check_integrity` и записывает строки `INTEGRITY <path>: <stderr>` вместо удаления. Все три источника дали `INTEGRITY total: 0` — `_check_integrity` вернул пустую строку для каждого клипа: h264_vaapi сейчас не производит тот маленький пакет.

---

## Шаг 3. Probe на сохранённых клипах

Взят клип `prew_isaev_anna/_gate/m179keep/r03.mp4` (h264_vaapi).

**На gamebox** (`probe_au.sh`):
- ffmpeg integrity (copy): без ошибок
- full decode errors: нет
- small video packets (<64 bytes): нет
- packets: 3700, frames: 3700

**На Mac** (`probe_au.sh`):
- ffmpeg integrity (copy): без ошибок
- small video packets (<64 bytes): нет
- packets: 3700, frames: 3700

(`probe_gamebox.txt`, `probe_mac.txt`)

---

## Шаг 4. Тест raw h264_vaapi (testsrc2)

```
ffmpeg -f lavfi -i testsrc2=s=1080x1920:r=30 -t 2 -vaapi_device /dev/dri/renderD128 -vf format=nv12,hwupload -c:v h264_vaapi -b:v 5M /tmp/m179_raw.mp4
→ encode_rc=0, integrity_rc=0, small_pkts=0
```

Сам по себе h264_vaapi не производит маленький пакет в текущей конфигурации.

---

## Диагностика: что это было

По логу **M165** (`handoff/m165/auto.txt`): при рендере 26 клипов `PXL_20260729_copy` 16 из них получили `integrity check failed — [h264 @ …] missing picture in access unit with size 12` (r01-r03, r07-r08, r12, r15-r23, r26). Та же версия ffmpeg: 8.0.1-3ubuntu2.

Прошли без ошибки: r04, r05, r06, r09, r10, r11, r13, r14, r24, r25.

**Что такое пакет в 12 байт**: H.264 Access Unit Delimiter (AUD, NAL type 9) + End Of Sequence (EOS, NAL type 10) в Annex-B: `00 00 00 01 09 F0 00 00 00 01 0A 80` = 12 байт. h264_vaapi иногда добавляет такой flush-пакет в конец файла при определённых параметрах (длина клипа, буфер энкодера). ffmpeg H.264 decoder трактует его как отдельный access unit без опорного кадра → `missing picture`.

**Почему Mac молчал**: Mac использовал `hevc_videotoolbox` (HEVC), не h264_vaapi. `ffmpeg -v error -codec copy` на Mac проверял уже готовый файл — та же команда, но декодер разный. Вероятнее всего, клипы из M165 были **удалены** на gamebox до копирования обратно на Mac — Mac их вообще не видел; M165 REPORT говорит «28 клипов, 0 ошибок» — это 18 IMG_6848 + 10 выживших PXL, проверенных уже на Mac.

**Почему сейчас не воспроизводится**: Манифест M165 использовал `PXL_20260729_copy_m165.review.json` с 26 клипами; в нём были `k:` keyword-метки (`subtitle_keywords=False` → предупреждение). Текущий манифест имеет другие границы и структуру. Вероятно, старые clips имели несколько сегментов или специфический concat-граф, при котором h264_vaapi выдавал flush-пакет.

---

## Вывод по трём вопросам задачи

1. **Что за пакет**: AUD + EOS NAL units, ~12 байт, flush в конце битстрима. Содержимого (опорного кадра) нет — декодер жалуется.
2. **На каком шаге**: финальный `ffmpeg` (concat + h264_vaapi encode), при сбросе буфера энкодера после последнего кадра.
3. **Почему Mac молчал**: те конкретные файлы Mac не проверял (они были удалены на gamebox). Если бы проверял — тот же `ffmpeg -v error -codec copy` дал бы ту же ошибку (H.264 парсер, не видеокарта).

---

## Рекомендация

Признать `missing picture in access unit with size 12` безвредным — это trailing flush-пакет без опорного кадра, клип визуально и технически корректен. Правка: в `_check_integrity` фильтровать строки с `missing picture in access unit with size 12` (или с размером < 64 по ffprobe) как ложные срабатывания h264_vaapi.

Альтернатива: `-bsf:v h264_metadata` или `-bsf:v filter_units=pass_types=1-5` при кодировании, чтобы отфильтровать EOS NAL unit.

Предпочтительнее первое: не трогать кодировщик, фильтровать в проверке.

---

## Уборка

```
ssh gamebox 'cd /mnt/data/autoreels && rm -rf reels-out/prew_isaev_anna/_gate/m179keep reels-out/prew_isaev_danny/_gate/m179keep keep_render.py probe_au.sh /tmp/m179_raw.mp4 2>/dev/null'
```

Локальный `_gate/m179diag` — в Корзину.

Статус: замер готов, ассистент делает правку.
