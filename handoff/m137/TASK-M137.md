# TASK M137 (можно ПАРАЛЛЕЛЬНЫМ агентом, Mac): замер — что отличает выбор владельца

Файлы — ветка `handoff`, папка `handoff/m137/`: `TASK-M137.md`, `taste.py`, `laugh.py`.
**Только замер:** код проекта, конфиг, `reviews/`, `manifests/` не меняются, коммитов нет. Пишется только `data/cache/m137/` (в .gitignore) и `handoff/m137/`. pytest и рендер не нужны, поэтому MAIN не мешает. Около 40–60 минут, почти всё — расчёт звука.

## Зачем
Владелец взял «учиться на его решениях» и «смех и аплодисменты зала». Сначала надо понять, есть ли сигнал.
- `taste.py`: единица — мысль карты. Метки берутся из 66 клипов владельца (манифесты `selection_source: human`): «взята» и «с неё начат клип». Признаки — паспорт карты (сила, роль, самостоятельность, голос), положение и признаки первых слов, посчитанные кодом (число, «вы», вопрос, оговорка, паразит или отсылка первым словом, контраст, имя). Для каждого признака AUC (0.5 = сигнала нет) и логистическая регрессия с проверкой на источнике, которого не было в обучении. Плюс сводка `reviews/verdicts.jsonl`.
  Ассистент прогнал на двух картах, что есть у него (09h33, IMG_6848): сила мысли AUC 0.69. Для «начала» сильнее длина первой мысли (0.73), отсылка или объяснение первым хуже. «Вирусные» признаки (число, вопрос, «вы») — около 0.5, то есть сигнала нет. Регрессия: «взята» 0.54, «начало» 0.68. Нужно на всех 7 источниках.
- `laugh.py`: модель звуков PANNs (AudioSet) посекундно ищет смех и аплодисменты. Затем сравнивает клипы владельца со случайными отрезками той же длины и считает AUC по мыслям карты.

## Правила
1. Упало или не совпало с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. Ничего в проекте не менять (см. выше). `torch` ставится в отдельное окружение `~/.venvs/m137`, не в `.venv` проекта.

## Шаг 1. Признаки и вкус
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/take.sh m137
.venv/bin/python handoff/m137/taste.py 2>&1 | tee handoff/m137/taste.txt | tail -45
git status --short | grep -v "^??" | head
```
Ожидается: строки по 7 источникам (`units …, owner clips …`; источник без карты — `skip`, его назвать); таблица признаков; две строки `leave-one-source-out … AUC`; `git status` без новых изменений.

## Шаг 2. Окружение для звука
```bash
python3.13 -m venv ~/.venvs/m137 && ~/.venvs/m137/bin/pip install -q torch panns-inference librosa torchlibrosa matplotlib numpy
mkdir -p ~/panns_data
[ -s ~/panns_data/class_labels_indices.csv ] || curl -sL -o ~/panns_data/class_labels_indices.csv http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv
[ -s ~/panns_data/Cnn14_DecisionLevelMax.pth ] || curl -L -o ~/panns_data/Cnn14_DecisionLevelMax.pth "https://zenodo.org/record/3987831/files/Cnn14_DecisionLevelMax_mAP%3D0.385.pth?download=1"
ls -l ~/panns_data; ~/.venvs/m137/bin/python -c "from panns_inference import labels; print(len(labels), [l for l in labels if 'augh' in l])"
```
Ожидается: файл модели больше 300 МБ, `527` и список классов со смехом. (`panns_inference` сам качает через `wget`, которого на Маке нет, поэтому качаем `curl`.)

## Шаг 3. Смех и аплодисменты
```bash
cd /Users/danny/Documents/autoreels
~/.venvs/m137/bin/python handoff/m137/laugh.py 2>&1 | grep -v "s$" | tee handoff/m137/laugh.txt | tail -40
ls -la data/cache/m137/; git status --short | grep -v "^??" | head
```
Ожидается: по каждому источнику секунды смеха и аплодисментов, «owner clips with … N/M, random …», enrichment; итог `=== ALL` и AUC по мыслям; временных `.f32` в `data/cache/m137/` не осталось, только `.laugh.json`. Источник, не найденный в `inputs*/`, — `skip`, назвать.
Если смеха почти нет нигде (единицы секунд), это тоже результат: так и написать.

## Шаг 4. Отчёт
`handoff/m137/REPORT.md`: `taste.txt` (таблица и две регрессии целиком), `laugh.txt` целиком, время шагов 2–3.
```bash
TMPDIR=$(mktemp -d) bash handoff/bin/report.sh m137 taste.txt laugh.txt
```
Владельцу — одна строка: «замер m137 готов, ассистент разберёт».
