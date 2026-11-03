# TASK M214B (окно MAIN, Mac + ssh gamebox): VPN для autoreels на gamebox, пакеты, модель выравнивания, ключи моделей

Файлы — ветка `handoff`, папка `handoff/m214b/`: `TASK-M214B.md`, `m214b-gamebox-vpn.patch` (ложится на `main` после M214a, `ef5da33`), `xray.service` (служба пользователя).
Около 30 минут: установка на gamebox, **без рендера**. Отчёт — только на русском.

## Зачем
M214a: для полного прогона на gamebox не хватает `torch`, `torchaudio`, `pymorphy3`, модели выравнивания и ключей. Кроме того, на gamebox нет VPN, а Groq, OpenRouter и Hugging Face без него недоступны.
Владелец, 2026-11-03: ключ VLESS положен в `~/.config/xray/vless.txt` на gamebox.

## Что вносит патч (Mac)
- `tools/vless2xray.py` — строка `vless://…` → конфиг Xray:
  - локальный прокси http `127.0.0.1:10809`, socks `127.0.0.1:10808`;
  - маршруты как у клиента владельца: `domain:ru / su / xn--p1ai`, `geosite:category-ru`, `geoip:ru`, `geoip:private` — напрямую;
  - ключ не печатается, конфиг — chmod 600.

  Ассистент проверил конфиг из этого ключа самим Xray 26.10.31: `Configuration OK`.
- `tests/test_m214b_vless2xray.py` — 3 теста (на выдуманном ключе).
- `docs/GAMEBOX.md` — раздел «VPN для autoreels на gamebox»; `PLAN.md`, `PROJECT_STRUCTURE.md`.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. **Ключ VLESS, конфиг Xray и `.env` не печатать** и не копировать в `handoff/` — только «есть / нет», коды ответа и версии.
3. Системный VPN на gamebox не включать: прокси — только для autoreels (`.env`). `sudo` не нужен; если шаг его просит — **СТОП**.
4. **Без рендера.** `data/token_scale.json` не коммитить.
5. Итог — «IMPLEMENTED, VERIFIED».

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m214b
ssh gamebox 'test -s ~/.config/xray/vless.txt && grep -c "^vless://" ~/.config/xray/vless.txt'
grep -cE '^(GROQ_API_KEY|OPENROUTER_API_KEY|HF_TOKEN)=.' .env
```
Ожидается:
- последний коммит — M214a (`ef5da33`);
- на gamebox ключ есть: `1`;
- на Mac ключей моделей ≥ 1. Если ключа VLESS нет — **СТОП**: «владельцу — положить ключ».

## Часть 1. Патч, тесты, коммит, код на gamebox
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m214b/m214b-gamebox-vpn.patch && git apply handoff/m214b/m214b-gamebox-vpn.patch && echo applied
.venv/bin/python -m pytest tests/test_m214b_vless2xray.py -q 2>&1 | tail -1
git add PLAN.md PROJECT_STRUCTURE.md docs/GAMEBOX.md tools/vless2xray.py tests/test_m214b_vless2xray.py
git commit -m "Gamebox VPN (M214b): tools/vless2xray.py — a vless:// line into an Xray config: a local proxy for autoreels on gamebox (http 10809, socks 10808), Russia and the LAN direct as the owner's client routes them; GAMEBOX.md: the proxy only for autoreels through .env"
git push; git log --oneline -1
git ls-files -z | rsync -a --from0 --files-from=- ./ gamebox:/mnt/data/autoreels/ && echo "код на gamebox"
```
Ожидается: `applied`; `3 passed`; коммит запушен; «код на gamebox».

## Часть 2. Xray на gamebox: установка, конфиг, служба, проверка
```bash
cd /Users/danny/Documents/autoreels
ssh gamebox 'set -e; mkdir -p ~/.local/xray && cd ~/.local/xray
  curl -fsSL -o x.zip https://github.com/XTLS/Xray-core/releases/download/v26.10.31/Xray-linux-64.zip \
    || curl -fsSL -o x.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip
  python3 -c "import zipfile; zipfile.ZipFile(\"x.zip\").extractall(\".\")"; chmod +x xray; ./xray version | head -1
  cd /mnt/data/autoreels && .venv/bin/python tools/vless2xray.py ~/.config/xray/vless.txt --out ~/.config/xray/config.json
  ~/.local/xray/xray run -test -c ~/.config/xray/config.json 2>&1 | tail -1' 2>&1 | tee handoff/m214b/xray.txt
scp handoff/m214b/xray.service gamebox:.config/systemd/user/xray.service 2>/dev/null || { ssh gamebox 'mkdir -p ~/.config/systemd/user'; scp handoff/m214b/xray.service gamebox:.config/systemd/user/xray.service; }
ssh gamebox 'systemctl --user daemon-reload && systemctl --user enable --now xray && sleep 2 && systemctl --user is-active xray;
  loginctl show-user "$USER" -p Linger; loginctl enable-linger "$USER" 2>&1 | tail -1; loginctl show-user "$USER" -p Linger;
  printf "через прокси: "; curl -s -o /dev/null -w "%{http_code}\n" --max-time 20 -x http://127.0.0.1:10809 https://api.groq.com/openai/v1/models;
  printf "напрямую:    "; curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 https://api.groq.com/openai/v1/models || true;
  printf "Я.Диск напрямую: "; curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 "https://cloud-api.yandex.net/v1/disk/public/resources?public_key=x"' 2>&1 | tee -a handoff/m214b/xray.txt
```
Ожидается:
- версия Xray (26.10.31); «конфиг: … xhttp/reality …»; `Configuration OK`;
- `active`; `Linger=yes` (если `enable-linger` просит пароль и Linger остался `no` — не СТОП: служба работает, пока есть вход; записать в отчёт);
- **через прокси — `401`** (Groq ответил, ключа в запросе нет); напрямую — `000` или `403`; Я.Диск напрямую — `4xx` (ответил).

Через прокси не `401` — **СТОП**.

## Часть 3. `.env` gamebox: прокси и ключи моделей (ничего не печатая)
```bash
cd /Users/danny/Documents/autoreels
ssh gamebox 'cd /mnt/data/autoreels && touch .env && chmod 600 .env && grep -vE "^(HTTPS_PROXY|HTTP_PROXY|NO_PROXY)=" .env > .env.tmp || true;
  printf "%s\n" "HTTPS_PROXY=http://127.0.0.1:10809" "HTTP_PROXY=http://127.0.0.1:10809" \
    "NO_PROXY=localhost,127.0.0.1,yandex.ru,.yandex.ru,yandex.net,.yandex.net,yandex.com,.yandex.com,yadi.sk,.yadi.sk" >> .env.tmp;
  mv .env.tmp .env && chmod 600 .env && grep -cE "^(HTTPS_PROXY|HTTP_PROXY|NO_PROXY)=." .env'
grep -E '^(GROQ_API_KEY|OPENROUTER_API_KEY|HF_TOKEN)=' .env | ssh gamebox 'cd /mnt/data/autoreels && grep -vE "^(GROQ_API_KEY|OPENROUTER_API_KEY|HF_TOKEN)=" .env > .env.tmp || true; cat >> .env.tmp; mv .env.tmp .env && chmod 600 .env && grep -cE "^(GROQ_API_KEY|OPENROUTER_API_KEY|HF_TOKEN)=." .env'
```
Ожидается: `3` (строки прокси); число ключей — столько же, сколько на Mac в части 0.

## Часть 4. Пакеты, модель выравнивания, проверка autoreels
```bash
cd /Users/danny/Documents/autoreels
ssh gamebox 'cd /mnt/data/autoreels && export HTTPS_PROXY=http://127.0.0.1:10809 HTTP_PROXY=http://127.0.0.1:10809;
  .venv/bin/pip install -q "pymorphy3>=2.0" 2>&1 | tail -2;
  .venv/bin/pip install -q torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu 2>&1 | tail -2 \
    || { echo "torch 2.8.0 под этот Python нет — ставлю ближайшую с колесом"; .venv/bin/pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cpu 2>&1 | tail -2; };
  .venv/bin/python -c "import torch, torchaudio, pymorphy3, parselmouth; print(\"torch\", torch.__version__, \"torchaudio\", torchaudio.__version__, \"pymorphy3 ok\")";
  .venv/bin/python -c "import torchaudio; torchaudio.pipelines.MMS_FA.get_model(); print(\"MMS_FA: модель на месте\")" 2>&1 | tail -2;
  .venv/bin/python -c "from autoreels.__main__ import _load_env; _load_env(); import os, httpx; r = httpx.get(\"https://api.groq.com/openai/v1/models\", headers={\"Authorization\": \"Bearer \" + os.environ.get(\"GROQ_API_KEY\", \"\")}, timeout=30); print(\"Groq из autoreels:\", r.status_code)";
  .venv/bin/python -m autoreels doctor 2>&1 | tail -25' 2>&1 | tee handoff/m214b/setup.txt
```
Ожидается:
- версии `torch` / `torchaudio`; если не 2.8.0 — записать: под Python 3.14 закреплённой нет;
- «MMS_FA: модель на месте» (первый раз — скачивание ~1,2 ГБ через прокси);
- «Groq из autoreels: 200»;
- `arl doctor` без красных строк по ключам и пакетам.

`MMS_FA` упал (новая `torchaudio` убрала конвейер) — не СТОП: записать текст ошибки, решение — ассистенту.

## Отчёт
`handoff/m214b/REPORT.md`:
```
M214B — IMPLEMENTED, VERIFIED
Коммит: <хэш>
Xray: <версия>; служба <active>; Linger <yes/no>; через прокси <401>; напрямую <…>; Я.Диск напрямую <…>
.env gamebox: прокси 3, ключей <n>
Пакеты: torch <версия>, torchaudio <версия>, pymorphy3 <ok>; MMS_FA <на месте / ошибка …>
Groq из autoreels: <200/…>; doctor: <итог>
```
```bash
bash handoff/bin/report.sh m214b xray.txt setup.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «gamebox: VPN для autoreels <работает>, torch <версия>, модель выравнивания <на месте/нет>, Groq <200>».
