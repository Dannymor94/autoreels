M192B — EXPORTED

```
$ ls -1 reviews/*_ab192.review.json | wc -l
       6

$ .venv/bin/python handoff/m192/export_texts.py
клипов: 20 (с видео 19) → handoff/m192/blind_texts.json, blind_map.csv

$ .venv/bin/python -c "import json;d=json.load(open('handoff/m192/blind_texts.json'));print(len(d), sum(1 for x in d if x['text']))"
20 20
```
