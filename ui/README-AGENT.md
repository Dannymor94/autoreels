# README-AGENT — рецепты для агента ветки UI

## Добавить эндпоинт и обновить типы

1. Добавить эндпоинт в `src/autoreels/orchestr/app.py` (Pydantic response model обязателен).
2. Обновить snapshot: `python -m autoreels.orchestr.export_openapi > ui/openapi.json`
3. Пересгенерировать типы: `cd ui && npm run gen:api`
4. Обновить `src/api/client.ts` — добавить обёртку.
5. Запустить: `pytest tests/ui/ && npm run typecheck && npm run build`

## Добавить экран

1. Создать `ui/src/screens/MyScreen.tsx` (≤200 строк, один компонент, данные через `api.*`).
2. Добавить кейс в `App.tsx` — стейт-машина в `Router`.
3. Добавить кнопку/ссылку для перехода в `Sources.tsx` или другом экране.
4. Запустить: `npm run typecheck && npm run build`

## Добавить метку (label)

1. Добавить строку в `ui/src/labels.ts` в объект `L`.
2. Использовать как `L.myLabel` в компоненте.
3. Запустить: `npm run typecheck`
