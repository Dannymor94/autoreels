# REPORT M147

## Шаг 1: патч, тесты, коммит

- `git apply` → applied
- pytest: 2500 passed, 9 deselected (4m36s)
- Коммит: `37a52d4` «Render (M147): pre-roll on; loudnorm_mode source…»
- Запуш: OK

## Шаг 2: рендер m147 (source)

Строка громкости источника:
```
громкость источника: -28.5 LUFS → усиление +14.5 dB (пик -0.6 dBTP, ограничитель -1.5)
```

`git diff --stat config/` — пуст (конфиг возвращён).

### ramp.txt

```
m146b (dynamic): медиана по клипам: 0–0.3 с -1.7 dB, 0.3–1 с +1.4, 1–2 с +1.4; клипов с провалом начала ≥ 3 dB: 2 из 9
m147 (source):  медиана по клипам: 0–0.3 с -0.6 dB, 0.3–1 с +0.7, 1–2 с +0.6; клипов с провалом начала ≥ 3 dB: 1 из 9
```

Провал начала: dynamic −1.7 dB → source −0.6 dB (+1.1 dB). Клипов с провалом ≥ 3 dB: 2 → 1.

- Гейт m146b (dynamic, пред-ролл): `reels-out/IMG_6848/_gate/m146b/` (12 клипов)
- Гейт m147 (source, пред-ролл): `reels-out/IMG_6848/_gate/m147/` (12 клипов)
- Лист ревью: `reels-out/IMG_6848/_gate/m147/_review.html`

## Статус

IMPLEMENTED, GATE PENDING — жду решения владельца по слуховому сравнению.
