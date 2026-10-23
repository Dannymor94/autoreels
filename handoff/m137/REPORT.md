# M137 — Замер: что отличает выбор владельца

## Шаг 1. taste.py — признаки и вкус

7 источников с картами, 799 мыслей, 66 клипов владельца:

```
2026-08-08 09h 33m 14s: units 121, owner clips 15, taken 37, starts 15
2026-08-08 10h 59m 38s: units 140, owner clips 8, taken 22, starts 8
2026-08-08 11h 42m 49s: units 47, owner clips 4, taken 11, starts 4
IMG_6848: units 107, owner clips 8, taken 23, starts 8
PXL_20260729_085910095_34f06abf: units 156, owner clips 10, taken 24, starts 10
Pxl 20260621 112938952: units 189, owner clips 19, taken 50, starts 18
Pxl 20260621 122006193: units 39, owner clips 2, taken 5, starts 2
```

Источников без карты (skip): нет — все 7 имеют `.map.json`.

### Таблица признаков (сортировка по |AUC start − 0.5|)

```
feature             AUC taken  AUC start   mean in start / others
dur                      0.54       0.71   17.95 / 13.76
punch                    0.65       0.67   3.58 / 3.03
h_words_to_stop          0.56       0.61   11.09 / 8.57
h_name                   0.46       0.42   0.52 / 0.69
pos                      0.40       0.42   0.42 / 0.50
level_db                 0.58       0.57   -37.12 / -41.52
role_explanation         0.51       0.45   0.26 / 0.37
role_thesis              0.52       0.55   0.20 / 0.10
standalone               0.47       0.55   0.38 / 0.29
refers                   0.53       0.45   0.62 / 0.71
energy                   0.55       0.54   44.08 / 39.90
role_example             0.50       0.53   0.22 / 0.15
filtered                 0.46       0.47   0.03 / 0.10
rate                     0.51       0.53   2.05 / 2.01
h_backref_first          0.51       0.48   0.22 / 0.26
role_aside               0.47       0.48   0.02 / 0.06
h_you                    0.47       0.52   0.34 / 0.30
h_filler_first           0.49       0.48   0.02 / 0.05
h_negate                 0.50       0.48   0.02 / 0.05
h_hedge                  0.50       0.51   0.11 / 0.08
role_question            0.46       0.49   0.06 / 0.09
similar_n                0.50       0.51   0.18 / 0.17
role_metaphor            0.52       0.51   0.06 / 0.05
role_conclusion          0.53       0.49   0.08 / 0.09
h_number                 0.50       0.50   0.08 / 0.07
h_contrast               0.52       0.50   0.48 / 0.47
range_st                 0.52       0.50   8.83 / 8.56
role_address             0.48       0.50   0.11 / 0.11
h_question               0.51       0.50   0.26 / 0.26
```

### Leave-one-source-out логистическая регрессия

```
leave-one-source-out logistic, label taken: AUC 0.59
  strongest weights (all data): punch +0.49, pos -0.30, role_question -0.26, filtered -0.25, level_db +0.23, role_aside -0.18, h_you -0.15, role_conclusion +0.12

leave-one-source-out logistic, label start: AUC 0.65
  strongest weights (all data): dur +0.54, punch +0.44, filtered -0.18, level_db +0.17, role_explanation -0.16, pos -0.16, role_thesis +0.16, h_name -0.14
```

### Интерпретация (taste)

Сигнал **есть** и на «взята» (AUC 0.59), и на «начало клипа» (AUC 0.65).
Сильнейшие предикторы начала:
- **dur** (0.71) — владелец начинает клип с длинной мысли (+4 с выше среднего);
- **punch** (0.67) — более высокая сила карты;
- **h_words_to_stop** (0.61) — мысль длинная до первой точки;
- **level_db** (0.57) — чуть громче.

«Вирусные» признаки (число, вопрос, «вы») — около 0.5, сигнала нет. Имя в начале — скорее минус (AUC 0.42).

---

## Шаги 2–3. laugh.py — смех и аплодисменты

Время шага 2 (установка + скачивание модели 312 МБ): ~14:10–14:11 (около 1 мин).  
Время шага 3 (PANNs на 7 источниках, ~13880 с аудио, CPU): ~14:11–14:15 (около 4 мин).

```
2026-08-08 09h 33m 14s: 1968 s, laughter seconds ≥0.4: 0, applause ≥0.4: 0
  thr 0.2: owner clips with laughter/applause 0/15, random 0.0/15
  thr 0.4: owner clips with laughter/applause 0/15, random 0.0/15
2026-08-08 10h 59m 38s: 2590 s, laughter seconds ≥0.4: 0, applause ≥0.4: 0
  thr 0.2: owner clips with laughter/applause 0/8, random 0.0/8
  thr 0.4: owner clips with laughter/applause 0/8, random 0.0/8
2026-08-08 11h 42m 49s: 830 s, laughter seconds ≥0.4: 0, applause ≥0.4: 0
  thr 0.2: owner clips with laughter/applause 0/4, random 0.0/4
  thr 0.4: owner clips with laughter/applause 0/4, random 0.0/4
IMG_6848: 2124 s, laughter seconds ≥0.4: 0, applause ≥0.4: 0
  thr 0.2: owner clips with laughter/applause 0/8, random 0.0/8
  thr 0.4: owner clips with laughter/applause 0/8, random 0.0/8
PXL_20260729_085910095_34f06abf: 2862 s, laughter seconds ≥0.4: 0, applause ≥0.4: 0
  thr 0.2: owner clips with laughter/applause 0/10, random 0.0/10
  thr 0.4: owner clips with laughter/applause 0/10, random 0.0/10
Pxl 20260621 112938952: 2806 s, laughter seconds ≥0.4: 0, applause ≥0.4: 0
  thr 0.2: owner clips with laughter/applause 0/19, random 0.2/19
  thr 0.4: owner clips with laughter/applause 0/19, random 0.0/19
Pxl 20260621 122006193: 706 s, laughter seconds ≥0.4: 0, applause ≥0.4: 0
  thr 0.2: owner clips with laughter/applause 0/2, random 0.1/2
  thr 0.4: owner clips with laughter/applause 0/2, random 0.0/2

=== ALL
thr 0.2: owner clips 0/66 (0%), random 0.3/66 (0%)
thr 0.4: owner clips 0/66 (0%), random 0.0/66 (0%)
map units 799: AUC laughter→taken 0.50, →start 0.50
```

Источников без исходника (skip): нет — все 7 найдены в `inputs*/`.  
Временных `.f32` не осталось, только 7 кешей `data/cache/m137/*.laugh.json`.

### Интерпретация (laugh)

**Смеха и аплодисментов нет нигде** — 0 секунд ≥0.4 по всем 7 источникам (13880 с суммарно). Это ожидаемо для формата talking-head без зала. AUC 0.50 — сигнала нет.

---

## Итог

| Метрика | AUC |
|---|---|
| Признаки → взята (логрег, LOSO) | 0.59 |
| Признаки → начало клипа (логрег, LOSO) | 0.65 |
| Смех/аплодисменты → взята | 0.50 (нет сигнала) |
| Смех/аплодисменты → начало | 0.50 (нет сигнала) |

Учиться на вкусе **имеет смысл** (dur + punch — главные сигналы). Смех — нерабочий признак для данного формата.
