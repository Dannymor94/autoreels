# Отчёт M118

Статус: IMPLEMENTED (патч); MEASURED (замеры).

## Шаг 1. Коммит и тесты

Коммит: 3bf7b9e «Keywords (M118): voice hints off by default (m116: they led the model to hedges); hedges and fillers are never k: words»

pytest: 2444 passed, 9 deselected, 1 error (pre-existing: test_verify_gate::test_main_all_pass — гвард-артефакт полного прогона, проходит в одиночку)

## Шаг 2. tx.txt

```
IMG_6848: точки Groq → groq-noprompt: добавлено 174; концы предложения на 100 слов: groq-noprompt 3.6 → groq-noprompt-gp 7.5 (Groq 10.3)
Pxl 20260621 112938952: точки Groq → groq-noprompt: добавлено 397; концы предложения на 100 слов: groq-noprompt 5.2 → groq-noprompt-gp 12.0 (Groq 14.2)
=== IMG_6848
   расшифровка                      слов концов/100 известных на речи повторов звук без слов слов whisper.cpp в ней
   Groq с подсказкой (сейчас)       3372       10.3         9      10        1          385с                  66.0%
   groq-noprompt                    4434        3.6         0       0        0           45с                  89.5%
   groq-noprompt-gp                 4434        7.5         0       0        0           45с                  89.5%
   whisper.cpp local-m111-novad     4345        5.5         0       0        0           85с                 100.0%
=== Pxl 20260621 112938952
   расшифровка                      слов концов/100 известных на речи повторов звук без слов слов whisper.cpp в ней
   Groq с подсказкой (сейчас)       4964       14.2         7       8        1          285с                  78.2%
   groq-noprompt                    5865        5.2         0       2        2           25с                  93.0%
   groq-noprompt-gp                 5865       12.0         0       2        2           25с                  93.0%
   whisper.cpp local-m114-novad     5924        5.0         0       2        2            0с                 100.0%
```

## Шаг 3–4. owner.txt

```
=== First sentence
   owner_starts ответов 65/65, «да» 100%
   owner_cloud  ответов 65/65, «да» 37%, 2.9 с на запрос
   owner_haiku  ответов 65/65, «да» 35%, 3.5 с на запрос
   owner_sonnet ответов 65/65, «да» 22%, 1.9 с на запрос
   owner_local  ответов 65/65, «да» 46%, 21.1 с на запрос
   совпадение (на запросах, где ответили обе):
     owner_starts ↔ owner_cloud: 24/65 (37%)
     owner_starts ↔ owner_haiku: 23/65 (35%)
     owner_starts ↔ owner_sonnet: 14/65 (22%)
     owner_starts ↔ owner_local: 30/65 (46%)
     owner_cloud ↔ owner_haiku: 50/65 (77%)
     owner_cloud ↔ owner_sonnet: 51/65 (78%)
     owner_cloud ↔ owner_local: 59/65 (91%)
     owner_haiku ↔ owner_sonnet: 50/65 (77%)
     owner_haiku ↔ owner_local: 50/65 (77%)
     owner_sonnet ↔ owner_local: 47/65 (72%)
```

## Цены (из run_owner.txt)

- Haiku: запросов 65, вход 30036, ответ 28046 токенов ≈ $0.0170
- Sonnet: запросов 65, вход 30036, ответ 4669 токенов ≈ $0.1068
- Cloud (Groq): без цены (free tier)
- Local: без цены

## Шаг 4б. funnel.txt

```
=== 2026-08-08 09h 33m 14s: клипов владельца 15, мыслей в карте 121, кандидатов «только правила» 4
   r01:  29.3 с, мысли conclusion★5 explanation★4; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✗ haiku:✗ sonnet:✗
   r02:  59.9 с, мысли explanation★3 metaphor★4 example★4 explanation★3 metaphor★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r03:  24.9 с, мысли example★3; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r04:  35.6 с, мысли aside★1 explanation★4; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r05:  35.6 с, мысли metaphor★5 metaphor★4 metaphor★4; зерно; кандидат ✓ (3 общ.); судьи начала: cloud:✓ haiku:✓ sonnet:✓
   r06:  26.2 с, мысли conclusion★5 metaphor★4; зерно; кандидата нет; судьи начала: cloud:✓ haiku:✓ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r07:  24.5 с, мысли address★3 conclusion★4; зерно; кандидат ✓ (2 общ.); судьи начала: cloud:✓ haiku:✓ sonnet:✓
   r08:  26.4 с, мысли thesis★4 address★3; зерно; кандидата нет; судьи начала: cloud:✓ haiku:✗ sonnet:✓  ← зерно есть, но кандидата с его мыслями нет
   r09:  41.3 с, мысли example★3 example★3 thesis★3 conclusion★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r10:  35.7 с, мысли thesis★3 explanation★3 explanation★2 conclusion★5; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✗ haiku:✗ sonnet:✗
   r11:  22.0 с, мысли thesis★4 explanation★3; зерно; кандидат ✓ (2 общ.); судьи начала: cloud:✗ haiku:✗ sonnet:✗
   r12:  56.7 с, мысли explanation★3 explanation★4 explanation★3 explanation★3; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r13:  39.7 с, мысли explanation★4 explanation★3; без зерна; кандидата нет; судьи начала: cloud:✓ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r14:  63.2 с, мысли explanation★3 example★4 conclusion★5 metaphor★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r15:  43.2 с, мысли explanation★3 explanation★4; без зерна; кандидат ✓ (1 общ.); судьи начала: cloud:✓ haiku:✓ sonnet:✓

=== 2026-08-08 10h 59m 38s: клипов владельца 8, мыслей в карте 140, кандидатов «только правила» 6
   r01:  72.9 с, мысли thesis★3 explanation★3 question★3 explanation★3 explanation★3; без зерна; кандидат ✓ (1 общ.); судьи начала: cloud:✗ haiku:✓ sonnet:✓
   r02:  58.8 с, мысли explanation★3 metaphor★4 example★3; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✓ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r03:  43.2 с, мысли explanation★3 conclusion★4 thesis★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r04:  45.4 с, мысли thesis★4 explanation★4 address★3 explanation★3; зерно; кандидат ✓ (2 общ.); судьи начала: cloud:✓ haiku:✗ sonnet:✓
   r05:  20.1 с, мысли thesis★4 explanation★3; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✓ haiku:✓ sonnet:✓
   r06:  27.7 с, мысли conclusion★4; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✓ haiku:✓ sonnet:✗
   r07:  23.3 с, мысли address★3 thesis★3; без зерна; кандидата нет; судьи начала: cloud:✓ haiku:✗ sonnet:✓  ← нет зерна (сильной мысли из STORY)
   r08:  19.2 с, мысли address★3 address★2; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)

=== 2026-08-08 11h 42m 49s: клипов владельца 4, мыслей в карте 47, кандидатов «только правила» 3
   r01:  36.0 с, мысли explanation★3 conclusion★4; зерно; кандидата нет; судьи начала: cloud:✓ haiku:✓ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r02:  40.9 с, мысли address★3 address★2 metaphor★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r03:  26.2 с, мысли explanation★4; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r04:  60.3 с, мысли explanation★3 explanation★3 explanation★3 thesis★4 metaphor★5; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✗ haiku:✗ sonnet:✗

=== IMG_6848: клипов владельца 8, мыслей в карте 107, кандидатов «только правила» 6
   r01:  72.4 с, мысли example★4 example★3 example★3 conclusion★4 explanation★3; зерно; кандидата нет; судьи начала: cloud:✓ haiku:✓ sonnet:✓  ← зерно есть, но кандидата с его мыслями нет
   r02:  30.1 с, мысли thesis★4; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✓ haiku:✗ sonnet:✗
   r03:  41.5 с, мысли explanation★4 conclusion★4; зерно; кандидат ✓ (2 общ.); судьи начала: cloud:✓ haiku:✗ sonnet:✗
   r04:  44.8 с, мысли example★2 example★3 conclusion★4 thesis★4; зерно; кандидат ✓ (2 общ.); судьи начала: cloud:✗ haiku:✓ sonnet:✗
   r05:  21.9 с, мысли thesis★4; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✓ haiku:✓ sonnet:✓
   r06:  35.0 с, мысли example★3 conclusion★3; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r07:  49.8 с, мысли explanation★3 example★4 example★3 example★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r08:  41.8 с, мысли conclusion★3 conclusion★3 thesis★4; зерно; кандидат ✓ (2 общ.); судьи начала: cloud:✗ haiku:✗ sonnet:✗

=== PXL_20260729_085910095_34f06abf: клипов владельца 10, мыслей в карте 156, кандидатов «только правила» 14
   r01:  59.8 с, мысли thesis★4 example★3 explanation★3 thesis★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r02:  44.6 с, мысли question★4 explanation★4; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✓ haiku:✓ sonnet:✗
   r03:  38.7 с, мысли explanation★4 explanation★3 conclusion★3; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r04:  19.2 с, мысли example★4; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✗ haiku:✗ sonnet:✗
   r05:  42.4 с, мысли conclusion★4 example★3 conclusion★4; зерно; кандидат ✓ (3 общ.); судьи начала: cloud:✓ haiku:✗ sonnet:✗
   r06:  29.6 с, мысли example★4 explanation★3; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r07:  53.9 с, мысли thesis★3 explanation★3 explanation★4; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r08:  39.0 с, мысли explanation★4 explanation★3; без зерна; кандидат ✓ (1 общ.); судьи начала: cloud:✗ haiku:✗ sonnet:✗
   r09:  28.8 с, мысли metaphor★4 explanation★3; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✗ haiku:✓ sonnet:✗
   r10:  40.8 с, мысли thesis★4 explanation★3; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✗ haiku:✓ sonnet:✗

=== Pxl 20260621 112938952: клипов владельца 19, мыслей в карте 189, кандидатов «только правила» 4
   r01:  57.0 с, мысли explanation★3 explanation★3 explanation★4 explanation★3 conclusion★4; зерно; кандидат ✓ (3 общ.); судьи начала: cloud:✓ haiku:✓ sonnet:✗
   r02:  47.6 с, мысли thesis★5 explanation★4 address★3 metaphor★3; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r03:  48.0 с, мысли thesis★4 example★3 explanation★3; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r04:  38.4 с, мысли thesis★3 explanation★3; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r05:  25.8 с, мысли explanation★3 explanation★2; без зерна; кандидата нет; судьи начала: cloud:✓ haiku:✓ sonnet:✓  ← нет зерна (сильной мысли из STORY)
   r06:  24.7 с, мысли example★4 conclusion★3 explanation★2; зерно; кандидат ✓ (2 общ.); судьи начала: cloud:✓ haiku:✓ sonnet:✗
   r07:  18.0 с, мысли question★3 example★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← короче min_sec (25 с)
   r08:  19.6 с, мысли example★3 example★3; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r09:  28.8 с, мысли conclusion★4 example★3 explanation★3; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r10:  23.8 с, мысли example★4 thesis★3; зерно; кандидата нет; судьи начала: cloud:✓ haiku:✓ sonnet:✗  ← короче min_sec (25 с)
   r11:  58.3 с, мысли explanation★4 address★3 conclusion★4 explanation★3; зерно; кандидат ✓ (1 общ.); судьи начала: cloud:✗ haiku:✗ sonnet:✗
   r12:  32.2 с, мысли explanation★3 example★3 explanation★3; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✓ sonnet:✓  ← нет зерна (сильной мысли из STORY)
   r13:  24.7 с, мысли address★4; без зерна; кандидата нет; судьи начала: cloud:✓ haiku:✓ sonnet:✓  ← нет зерна (сильной мысли из STORY)
   r14:  31.2 с, мысли question★3 explanation★4; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✓ sonnet:✗  ← нет зерна (сильной мысли из STORY)
   r15:  59.8 с, мысли conclusion★4 explanation★3 explanation★4 example★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r16:  22.7 с, мысли thesis★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← короче min_sec (25 с)
   r17:  56.5 с, мысли metaphor★4 explanation★3 question★3 explanation★4 metaphor★4; зерно; кандидата нет; судьи начала: cloud:✓ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r18:  27.5 с, мысли conclusion★4; зерно; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← зерно есть, но кандидата с его мыслями нет
   r19:  37.6 с, мысли explanation★3 thesis★5 example★3; зерно; кандидата нет  ← зерно есть, но кандидата с его мыслями нет

=== Pxl 20260621 122006193: клипов владельца 2, мыслей в карте 39, кандидатов «только правила» 1
   r01:  34.0 с, мысли thesis★4 address★4 explanation★3; без зерна; кандидата нет; судьи начала: cloud:✓ haiku:✓ sonnet:✓  ← нет зерна (сильной мысли из STORY)
   r02:  34.0 с, мысли explanation★4 explanation★3; без зерна; кандидата нет; судьи начала: cloud:✗ haiku:✗ sonnet:✗  ← нет зерна (сильной мысли из STORY)

=== ВОРОНКА (все источники)
   клипов                 66
   с мыслями карты        66
   с зерном               45
   не короче min_sec      52
   есть кандидат          25
   причины, по которым кандидата нет:
      20 — зерно есть, но кандидата с его мыслями нет
      18 — нет зерна (сильной мысли из STORY)
       3 — короче min_sec (25 с)
   судья cloud: принял начал владельца 24 из 65 (37%)
   судья haiku: принял начал владельца 23 из 65 (35%)
   судья sonnet: принял начал владельца 14 из 65 (22%)
```
