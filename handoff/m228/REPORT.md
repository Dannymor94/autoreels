# M228 — Финальный отчёт синтеза (R2 — исправлено после Sol R1)

**Дата:** 2026-11-19  
**Исполнитель:** Claude Code Sonnet 4.6  
**PRODUCTION_DIFF=NONE**  
**BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682**  
**EVIDENCE_BASE_SHA (R1 delivery)=44086710a04af83ccbef41b8c491096349003e5a**  
**M229_CODE_GO=NO**

---

## 1. Источники и закреплённые SHA

| Задача | Sol review path | Evidence SHA (handoff branch) |
|--------|-----------------|-------------------------------|
| M223 | `handoff/m223/SOL-REVIEW-R5.md` | `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| M224 | `handoff/m224/SOL-REVIEW-R2-ACCEPTANCE.md` | `d18627fb0fff56c4735b3c0462b1796337989715` |
| M224 erratum | (в составе M224 Sol R2) | `78511b42887b5be7070b8241d30e6d7556e20568` |
| M225 | `handoff/m225/SOL-REVIEW-STAGE-A.md` | `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| M226 | `handoff/m226/SOL-REVIEW-STAGE-A.md` | `e1be1b74cb033a8575d3967eceb8b06c3800f790` |
| M227 | `handoff/m227/SOL-REVIEW-STAGE-A.md` | `929646319dc55b5d6dc62f6321582bf20622cc09` |
| Sol M228 R1 | `handoff/m228/SOL-REVIEW-R1.md` | (в handoff branch; `717556c15ac8f56ec5057d56b8a062de0d30e367`) |
| Coordinator Ledger | `handoff/m228/COORDINATOR-LEDGER-DRAFT.md` | (в handoff branch) |
| QA Stop Rules | `handoff/m222/QA-STOP-RULES.md` | (в handoff branch) |
| Plan V2 | `handoff/m222/PLAN-M222-V2.md` | (в handoff branch) |

**Production source:** `src/autoreels/` из `main@3c011e94263e16e5780936b4769d3490cd03b682`  
**Config SHA256:** `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`  
(подтверждён в M224–M227 Sol reviews)

---

## 2. Изменённые пути в этой задаче (R2)

```
handoff/m228/FINDINGS.md        — реестр 12 находок (R2)
handoff/m228/ARCHITECTURE.md   — архитектурное решение (R2)
handoff/m228/GATES.md          — план вех и GO/NO-GO (R2)
handoff/m228/REPORT.md         — этот документ (R2)
```

Никаких изменений в `src/`, `tests/`, `config/`, `manifests/`, `transcripts/`, `reels-out/`, `reviews/`, `CLAUDE.md`, или `main`.

---

## 3. Область доказательств (неизменна, заморожена после M223–M227)

| Задача | Находки | Уровень | Принято Sol |
|--------|---------|---------|-------------|
| M223 | #1, #2, #3 | CLI_CONFIRMED (bounded) + STATIC | PASS_SCOPED R5 |
| M224 | #5, #6 | CLI_HELPER_BOUNDARY | PASS_SCOPED R2 + erratum |
| M225 | #7, #8a, #8b | HELPER_CONFIRMED | PASS_SCOPED Stage-A |
| M226 | #4, #9a, #9b, #12 | HELPER_CONFIRMED + CLI_CONFIRMED preflight | PASS_SCOPED Stage-A |
| M227 | #11 | CLI_OUTPUT_GAP + HELPER (teaser) + STATIC (weak-seed) | PASS_SCOPED Stage-A |

**#7, #8, #9 — HELPER_CONFIRMED, не CLI_HELPER_BOUNDARY.** Не расширять заявленный уровень.  
Ни одна находка не имеет RENDER-уровня доказательства. Принятые Sol-области заморожены.

---

## 4. Расчёт диспозиций (R2 — исправлено)

| Действие | Родительские находки | Подслучаев | Веха |
|----------|---------------------|-----------|------|
| FIX_NOW | #1, #2, #3, #5, #7, #8, #9 | 9 (#1,#2,#3,#5,#7,#8a,#8b,#9a,#9b) | M230→impl |
| INSTRUMENT_FIRST | #4, #6, #11 | 3 | M231 |
| NO_FIX_INTENTIONAL | #10 | 1 | — |
| DEFER | #12 | 1 | — до runtime proof |

**Итого:** 12 родительских, 14 подслучаев.  
**FIX_NOW:** 7 родительских / 9 подслучаев · **INSTRUMENT_FIRST:** 3 · **NO_FIX_INTENTIONAL:** 1 · **DEFER:** 1

---

## 5. Закрытие P1 блокеров (Sol R1 → R2)

| Блокер | Путь и секция | Статус |
|--------|---------------|--------|
| P1-A: неверная классификация доказательств (#7/#8/#9 как CLI) | GATES.md §1; FINDINGS.md таблица | CLOSED — #7/#8/#9 помечены HELPER_CONFIRMED; GO_SCOPED rationale скорректирован |
| P1-B: противоречие M229/M230 ворот | GATES.md §2; ARCHITECTURE.md §8 | CLOSED — M229_CODE_GO=NO; все FIX_NOW требуют M230 arch review; единственная последовательность задокументирована |
| P1-C: #1 механизм не адресует подавление | ARCHITECTURE.md §2; FINDINGS.md #1 | CLOSED — bounded enumeration vs selection различены; stable IDs, dedup at selection, stopping condition, overlap preservation описаны; test contract NOT breach overlap |
| P1-D: M231 смешивает наблюдение и мутацию | ARCHITECTURE.md §5; GATES.md M231 | CLOSED — M231 ограничен additive counters + delta-log; teaser_misses/weak-seed/no_start/rhythm_out мутации явно перенесены в post-M230 |
| P1-E: запрет question-first; unconditional answer extension; build_passage tuple как API | ARCHITECTURE.md §1,§2 | CLOSED — принцип 8 защищает question-led loop; answer extension → гипотеза за arch gate; (clip,reason) tuple → гипотеза; #8b fail-closed |
| P1-F: M231 требует owner-видео | GATES.md M231 §success | CLOSED — success criterion = synthetic fixtures only; owner-данные требуют отдельного explicit authorization |

---

## 6. Нерешённые вопросы и пробелы доказательств

### Доказательные пробелы (не требуют новых reprо — стоп-правило)

- #1, #4: late rejection в реальных медиа — NOT_REPRODUCED
- #3: production impact на реальных hook-кандидатах — NOT_REPRODUCED
- #5, #6: Proposal.seconds / rendered playback — NOT_VERIFIED / NOT_REPRODUCED
- #7: несвязный клип у пользователя — NOT_REPRODUCED
- #8b: ремонтируемый сосед — NOT_VERIFIED
- #9a-b: CLI-финальный результат — NOT_REPRODUCED
- #11: per-seed CLI spy, реальный пользовательский эффект teaser — NOT_REPRODUCED
- M227 evidence.json: `repro.exit` отсутствует в published tree (отмечено Sol M227)

### Продуктовые/архитектурные решения (для owner)

- Semantic clauses rescue (#3): спасать ли hook через clause?
- Repair neighbor contract (#8b): какой сосед легален?
- Answer-after-question semantics (#9b): всегда ли?
- #1 bounded N попыток: стоп-условие?
- #10 budget: нужно ли измерять % без hook?
- Real data plan (#6, M237): когда, с чьими данными, privacy?

---

## READY_FOR_SOL_QA

```
TASK=M228-R2
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
EVIDENCE_BASE_SHA=44086710a04af83ccbef41b8c491096349003e5a
PRODUCTION_DIFF=NONE
M229_CODE_GO=NO
P1_A=CLOSED (GATES.md §1 + FINDINGS.md доказательные уровни скорректированы)
P1_B=CLOSED (M229_CODE_GO=NO; единственная последовательность M229→M230 arch→M231 impl)
P1_C=CLOSED (ARCHITECTURE.md §2: bounded enumeration vs selection, overlap preserved)
P1_D=CLOSED (ARCHITECTURE.md §5 + GATES.md M231: observability-only, мутации отложены)
P1_E=CLOSED (question-first защищён; answer extension за arch gate; build_passage tuple гипотеза; #8b fail-closed)
P1_F=CLOSED (GATES.md M231: synthetic only; owner-данные требуют explicit auth)
CHANGED_PATHS=handoff/m228/FINDINGS.md, handoff/m228/ARCHITECTURE.md,
              handoff/m228/GATES.md, handoff/m228/REPORT.md
DISPOSITION_COUNTS=FIX_NOW:7parents/9subcases, INSTRUMENT_FIRST:3, NO_FIX_INTENTIONAL:1, DEFER:1
RECOMMENDED_GATE=GO_SCOPED (M229 preparation docs+tests, NO_CODE; M230 arch before any impl)
READY_FOR_SOL_QA=YES
```
