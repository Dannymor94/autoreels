# M228 — Финальный отчёт синтеза (аудит-готов)

**Дата:** 2026-11-19  
**Исполнитель:** Claude Code Sonnet 4.6  
**PRODUCTION_DIFF=NONE**  
**BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682**

---

## 1. Источники и закреплённые SHA

| Задача | Sol review path | Evidence SHA (handoff branch) |
|--------|-----------------|-------------------------------|
| M223 | `handoff/m223/SOL-REVIEW-R5.md` | `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| M224 | `handoff/m224/SOL-REVIEW-R2-ACCEPTANCE.md` | `d18627fb0fff56c4735b3c0462b1796337989715` |
| M224 erratum | `handoff/m224/SOL-REVIEW-R2-ACCEPTANCE.md` erratum SHA | `78511b42887b5be7070b8241d30e6d7556e20568` |
| M225 | `handoff/m225/SOL-REVIEW-STAGE-A.md` | `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| M226 | `handoff/m226/SOL-REVIEW-STAGE-A.md` | `e1be1b74cb033a8575d3967eceb8b06c3800f790` |
| M227 | `handoff/m227/SOL-REVIEW-STAGE-A.md` | `929646319dc55b5d6dc62f6321582bf20622cc09` |
| Coordinator Ledger | `handoff/m228/COORDINATOR-LEDGER-DRAFT.md` | (в handoff branch) |
| QA Stop Rules | `handoff/m222/QA-STOP-RULES.md` | (в handoff branch) |
| Plan V2 | `handoff/m222/PLAN-M222-V2.md` | (в handoff branch) |

**Production source:** `src/autoreels/` из `main@3c011e94263e16e5780936b4769d3490cd03b682`  
**Config SHA256:** `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba` (подтверждён в M224–M227 Sol reviews)

---

## 2. Изменённые пути в этой задаче

```
handoff/m228/FINDINGS.md        — реестр 12 находок
handoff/m228/ARCHITECTURE.md   — архитектурное решение
handoff/m228/GATES.md          — план вех и GO/NO-GO
handoff/m228/REPORT.md         — этот документ
```

Никаких изменений в `src/`, `tests/`, `config/`, `manifests/`, `transcripts/`, `reels-out/`, `reviews/`, `CLAUDE.md`, или `main`.

---

## 3. Область доказательств (по задачам)

| Задача | Находки | Уровень | Принято Sol |
|--------|---------|---------|-------------|
| M223 | #1, #2, #3 | CLI_CONFIRMED (bounded) + STATIC | PASS_SCOPED R5 |
| M224 | #5, #6 | CLI_HELPER_BOUNDARY | PASS_SCOPED R2 + erratum |
| M225 | #7, #8a, #8b | HELPER_CONFIRMED | PASS_SCOPED Stage-A |
| M226 | #4, #9a, #9b, #12 | HELPER_CONFIRMED + CLI_CONFIRMED preflight | PASS_SCOPED Stage-A |
| M227 | #11 | CLI_OUTPUT_GAP + HELPER (teaser) + STATIC (weak-seed) | PASS_SCOPED Stage-A |

Ни одна находка не имеет RENDER-уровня доказательства.

---

## 4. Расчёт диспозиций

| Действие | Количество | Находки |
|----------|-----------|---------|
| FIX_NOW (M229, нет arch) | 5 | #1, #2, #5, #8a, #9a |
| FIX_NOW (M230, arch required) | 4 | #3, #7, #8b, #9b |
| INSTRUMENT_FIRST | 3 | #4, #6, #11 |
| NO_FIX_INTENTIONAL | 2 | #10, #12 |
| **Итого** | **14 диспозиций** | **12 находок** (#8 и #9 — по 2 подслучая) |

---

## 5. Нерешённые вопросы и пробелы доказательств

### Доказательные пробелы (не требуют новых reprо — зафиксированы стоп-правилом)

- **#1:** late rejection в реальных медиа — NOT_REPRODUCED
- **#3:** production impact на реальных hook-кандидатах — NOT_REPRODUCED
- **#4:** поздний финальный drop после select_global — NOT_REPRODUCED
- **#5, #6:** Proposal.seconds / rendered playback — NOT_VERIFIED / NOT_REPRODUCED
- **#7:** несвязный клип у пользователя — NOT_REPRODUCED
- **#8b:** ремонтируемый сосед — NOT_VERIFIED
- **#9a-b:** CLI-финальный результат — NOT_REPRODUCED
- **#11:** per-seed CLI spy, реальный пользовательский эффект teaser — NOT_REPRODUCED
- **M227 evidence.json:** `repro.exit` отсутствует в published tree (отмечено Sol)

### Продуктовые/архитектурные решения (для owner)

- Semantic clauses rescue (#3): спасать ли hook через clause?
- Repair neighbor contract (#8b): какой сосед легален?
- Answer-after-question semantics (#9b): всегда ли?
- #10 budget: нужно ли измерять % без hook?
- A/B рендер (#4, #6): когда и с чьими данными?

---

## 6. Рекомендованные ворота

**GO_SCOPED** — переход к M229 planning авторизован при условии:
1. Независимый Sol 6.1 PASS M228 получен и опубликован.
2. M229 ограничен находками #1, #2, #5, #8a, #9a (нет propose signature).
3. M230 arch review проведён перед любым изменением `propose`.
4. Никаких production changes, рендеров, платных API до соответствующих гейтов.

**НЕ авторизует:**
- Изменение `propose()` / `select_global()` / `fill_pool()` до M230.
- Мержить production main до Sol QA каждой следующей вехи.
- M237 A/B без отдельного owner approval.

---

## READY_FOR_SOL_QA

```
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
PRODUCTION_DIFF=NONE
CHANGED_PATHS=handoff/m228/FINDINGS.md, handoff/m228/ARCHITECTURE.md,
              handoff/m228/GATES.md, handoff/m228/REPORT.md
DISPOSITION_COUNTS=FIX_NOW:9, INSTRUMENT_FIRST:3, NO_FIX_INTENTIONAL:2
RECOMMENDED_GATE=GO_SCOPED (M229 FIX_NOW isolated; M230 arch required for propose)
PROOF_GAPS=late_rejection(#1,#4), playback(#5,#6), depends_fix(#7,#8b,#9b),
           per_seed_cli(#11), render(all)
```
