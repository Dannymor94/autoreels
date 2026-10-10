"""Review sheet (`arl review-sheet`): one HTML page per source to watch the rendered clips and decide.

Every clip is shown with its video, title plate, caption, subtitle text, warnings and the review
line it came from. The owner marks each clip «оставить / убрать / переделать» (+ a note) and
downloads a decisions file; `arl review-apply` writes it into the draft (cloud/label.py). The page
is static: it is opened from disk next to the clips (reels-out/<stem>/), no server, nothing sent
anywhere; the choices survive a reload in the browser's local storage.

Pure: build_sheet() turns prepared cards into HTML; the CLI collects the cards.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field


@dataclass
class Card:
    rid: str
    video: str | None             # file name next to the page, None = not rendered
    duration: float               # played seconds (speed applied)
    title: str = ""
    caption: str = ""
    text: str = ""                # subtitle words
    warnings: list[str] = field(default_factory=list)
    seq: int | None = None        # review line number; None = no line found (draft changed)
    line: str = ""
    preview: str = ""
    marks: list[str] = field(default_factory=list)   # the owner's marks of earlier rounds


_CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1b;--mute:#6b6a66;--line:#e2e0da;--ok:#1f7a3e;--drop:#b3261e;
--fix:#9a5b00;--accent:#2f5bd3;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--card:#1f1f1d;--ink:#ecebe7;
--mute:#a09f9a;--line:#33322f;--ok:#5cc282;--drop:#ff8a80;--fix:#f0b252;--accent:#8aa8ff}}
:root[data-theme="dark"]{--bg:#151514;--card:#1f1f1d;--ink:#ecebe7;--mute:#a09f9a;--line:#33322f;--ok:#5cc282;
--drop:#ff8a80;--fix:#f0b252;--accent:#8aa8ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);
padding:12px 16px;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
header h1{font-size:17px;margin:0;flex:1 1 auto}
#count{color:var(--mute)}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;
padding:7px 12px;cursor:pointer}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
main{max-width:1100px;margin:0 auto;padding:16px}
.note-top{color:var(--mute);margin:0 0 12px}
.warn-top{border:1px solid var(--drop);color:var(--drop);border-radius:8px;padding:8px 12px;margin:0 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:0 0 16px;
display:grid;grid-template-columns:minmax(0,300px) minmax(0,1fr);gap:16px}
.card[data-v="ok"]{border-color:var(--ok)}.card[data-v="drop"]{border-color:var(--drop);opacity:.75}
.card[data-v="fix"]{border-color:var(--fix)}.card.missing-note{box-shadow:0 0 0 2px var(--fix)}
video{width:100%;aspect-ratio:9/16;background:#000;border-radius:8px;display:block}
.novideo{aspect-ratio:9/16;border:1px dashed var(--line);border-radius:8px;display:flex;align-items:center;
justify-content:center;color:var(--mute);text-align:center;padding:12px}
.rid{font-weight:600}.dur{color:var(--mute);margin-left:8px}
.title{font-size:18px;font-weight:600;margin:4px 0}
.caption{white-space:pre-wrap;margin:4px 0 8px}
details{margin:6px 0}summary{cursor:pointer;color:var(--mute)}
.subs{white-space:pre-wrap;color:var(--ink)}
.line{font-family:var(--mono);font-size:12.5px;background:var(--bg);border-radius:6px;padding:6px 8px;
overflow-wrap:anywhere}
.marks{font-size:13px;color:var(--mute);margin:4px 0}
.warns{color:var(--drop);font-size:13px;margin:6px 0;padding-left:18px}
.choice{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 6px}
.choice label{border:1px solid var(--line);border-radius:999px;padding:5px 12px;cursor:pointer;user-select:none}
.choice input{position:absolute;opacity:0;pointer-events:none}
.choice input:focus-visible+span{outline:2px solid var(--accent);outline-offset:3px}
.choice label:has(input[value="ok"]:checked){background:var(--ok);border-color:var(--ok);color:#fff}
.choice label:has(input[value="drop"]:checked){background:var(--drop);border-color:var(--drop);color:#fff}
.choice label:has(input[value="fix"]:checked){background:var(--fix);border-color:var(--fix);color:#fff}
textarea{width:100%;min-height:54px;font:inherit;border:1px solid var(--line);border-radius:8px;padding:6px 8px;
background:var(--bg);color:var(--ink)}
.noline{color:var(--drop)}
@media (max-width:700px){.card{grid-template-columns:1fr}video,.novideo{max-height:70vh;width:auto;margin:0 auto}}
"""

_JS = r"""
(function(){
  const meta = JSON.parse(document.getElementById('meta').textContent);
  const key = 'arl-review:' + meta.stem + ':' + meta.key;
  const cards = Array.from(document.querySelectorAll('.card[data-seq]'));
  function load(){ try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch(e){ return {}; } }
  function save(st){ try { localStorage.setItem(key, JSON.stringify(st)); } catch(e){} }
  function state(){
    const st = {};
    cards.forEach(c => {
      const v = (c.querySelector('input[type=radio]:checked') || {}).value || '';
      const n = c.querySelector('textarea').value.trim();
      if (v || n) st[c.dataset.rid] = {v: v, n: n};
    });
    return st;
  }
  function refresh(){
    let done = 0;
    cards.forEach(c => {
      const v = (c.querySelector('input[type=radio]:checked') || {}).value || '';
      c.dataset.v = v;
      c.classList.toggle('missing-note', v === 'fix' && !c.querySelector('textarea').value.trim());
      if (v) done++;
    });
    document.getElementById('count').textContent = 'решено ' + done + ' из ' + cards.length;
    save(state());
  }
  const st = load();
  cards.forEach(c => {
    const s = st[c.dataset.rid];
    if (s) {
      const r = c.querySelector('input[value="' + s.v + '"]'); if (r) r.checked = true;
      c.querySelector('textarea').value = s.n || '';
    }
    c.addEventListener('change', refresh);
    c.querySelector('textarea').addEventListener('input', refresh);
  });
  function text(){
    const out = ['# stem: ' + meta.stem, '# review: ' + meta.review, '# manifest: ' + meta.manifest,
                 '# decided: ' + new Date().toISOString().slice(0, 10)];
    cards.forEach(c => {
      const v = (c.querySelector('input[type=radio]:checked') || {}).value || '';
      const n = c.querySelector('textarea').value.trim().replace(/\s*\n\s*/g, ' ');
      const head = c.dataset.rid + ' | line ' + c.dataset.seq;
      if (!v) out.push('# ' + head + ' | не решено' + (n ? ' | ' + n : ''));
      else out.push(head + ' | ' + v + (n ? ' | ' + n : ''));
    });
    return out.join('\n') + '\n';
  }
  function problems(){
    return cards.filter(c => c.classList.contains('missing-note')).map(c => c.dataset.rid);
  }
  document.getElementById('save').addEventListener('click', () => {
    const p = problems();
    if (p.length && !confirm('Нет замечания у «переделать»: ' + p.join(', ') + '. Эти клипы не попадут в решения. Скачать всё равно?')) return;
    const blob = new Blob([text()], {type: 'text/plain;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = meta.stem + '_decisions.txt';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  document.getElementById('copy').addEventListener('click', () => {
    const t = text();
    const ok = () => { document.getElementById('copy').textContent = 'Скопировано'; };
    if (navigator.clipboard) navigator.clipboard.writeText(t).then(ok, () => prompt('Скопируйте:', t));
    else prompt('Скопируйте:', t);
  });
  refresh();
})();
"""


def _e(s: str) -> str:
    return html.escape(s or "", quote=True)


def _card_html(c: Card) -> str:
    vid = (f'<video src="{_e(c.video)}" controls preload="metadata" playsinline></video>' if c.video
           else '<div class="novideo">клип не отрендерен</div>')
    warns = "".join(f"<li>{_e(w)}</li>" for w in c.warnings)
    parts = [f'<div class="media">{vid}</div><div class="info">',
             f'<div><span class="rid">{_e(c.rid)}</span><span class="dur">{c.duration:.0f} с</span></div>']
    if c.title:
        parts.append(f'<div class="title">{_e(c.title)}</div>')
    if c.caption:
        parts.append(f'<div class="caption">{_e(c.caption)}</div>')
    if c.text:
        parts.append(f'<details><summary>текст клипа</summary><div class="subs">{_e(c.text)}</div></details>')
    if warns:
        parts.append(f'<ul class="warns">{warns}</ul>')
    if c.seq is None:
        parts.append('<p class="noline">Строка черновика для этого клипа не найдена: черновик менялся '
                     'после рендера. Решение по нему здесь не принимается.</p></div>')
        return f'<section class="card" data-rid="{_e(c.rid)}">' + "".join(parts) + "</section>"
    parts.append(f'<details><summary>строка {c.seq} черновика</summary><div class="line">{_e(c.line)}</div>'
                 + (f'<div class="marks">{_e(c.preview)}</div>' if c.preview else "") + "</details>")
    if c.marks:
        parts.append('<div class="marks">' + "<br>".join(_e(m) for m in c.marks) + "</div>")
    name = f"v-{_e(c.rid)}"
    radios = "".join(
        f'<label><input type="radio" name="{name}" value="{v}"><span>{t}</span></label>'
        for v, t in (("ok", "Оставить"), ("drop", "Убрать"), ("fix", "Переделать")))
    parts.append(f'<div class="choice">{radios}</div>'
                 f'<textarea placeholder="Замечание (для «Переделать» обязательно): что не так, '
                 f'где начать или закончить…" aria-label="Замечание к {_e(c.rid)}"></textarea></div>')
    return (f'<section class="card" data-rid="{_e(c.rid)}" data-seq="{c.seq}">' + "".join(parts)
            + "</section>")


def build_sheet(stem: str, cards: list[Card], *, review_ref: str, manifest_ref: str, key: str,
                notes: list[str] = ()) -> str:
    """The whole page. key: a short hash of the draft — choices saved in the browser belong to it."""
    meta = json.dumps({"stem": stem, "review": review_ref, "manifest": manifest_ref, "key": key},
                      ensure_ascii=False).replace("</", "<\\/")
    unmatched = [c.rid for c in cards if c.seq is None]
    top = [f'<p class="note-top">Черновик: {_e(review_ref)} · манифест: {_e(manifest_ref)}. '
           f'Отметьте каждый клип, нажмите «Скачать решения», затем: '
           f'<code>arl review-apply ~/Downloads/{_e(stem)}_decisions.txt</code></p>']
    if unmatched:
        top.append(f'<p class="warn-top">Без строки черновика: {_e(", ".join(unmatched))}</p>')
    top += [f'<p class="warn-top">{_e(n)}</p>' for n in notes]
    return (
        "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>Ревью {_e(stem)}</title><style>{_CSS}</style></head><body>"
        f"<header><h1>Ревью: {_e(stem)}</h1><span id=\"count\"></span>"
        "<button id=\"copy\" type=\"button\">Копировать</button>"
        "<button id=\"save\" class=\"primary\" type=\"button\">Скачать решения</button></header>"
        "<main>" + "".join(top) + "".join(_card_html(c) for c in cards) + "</main>"
        f"<script id=\"meta\" type=\"application/json\">{meta}</script><script>{_JS}</script>"
        "</body></html>\n"
    )
