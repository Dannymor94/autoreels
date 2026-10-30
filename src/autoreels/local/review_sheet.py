"""Review sheet (`arl review-sheet`): one HTML page per source to watch the rendered clips and decide.

Every clip is shown with its video, title plate, caption, subtitle text, warnings and the review
line it came from. The owner marks each clip «оставить / убрать / переделать» (+ reasons, a note) and
downloads a decisions file; `arl review-apply` writes it into the draft (cloud/label.py). The page
is static: it is opened from disk next to the clips (reels-out/<stem>/), no server, nothing sent
anywhere; the choices survive a reload in the browser's local storage.

Pure: build_sheet() turns prepared cards into HTML; the CLI collects the cards.

M52 — the clip as text (like text-based video editors): under the video, every sentence of the
clip's block group in the review numbering. A click turns a sentence on or off (or, in hook mode,
makes it the cold open); «▶ правка» plays the new version from a small preview file next to the
page (_preview/<rid>-<a>-<b>.m4a, or .mp4 with the picture — arl review-sheet --preview), jumping
over the sentences that are off. An edited clip gets the verdict «edit» with its new s:/e:/x:/h:;
arl review-apply writes them into the line. Data contract (for any other UI of the sheet): the
script #clips holds {rid: {seq, sentences: [{n, text, a, b, complete, open, played}], hook,
media, offset}}; a and b are source seconds, media time = source time − offset.
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
    score: int | None = None      # the draft's score (after ranking: the place, 95 best … 65)
    montage: str = ""             # M50: the montage line (M …) the clip was built from
    edit: dict | None = None      # M52: label.edit_model + "media", "offset" (None: not editable here)
    attention: list[dict] = field(default_factory=list)   # M53: attention_marks(reel) — clip time
    cover: str | None = None      # M95: <rid>.cover.jpg next to the page (M89)
    post: str = ""                # M95: the post text crosspost gets — <rid>.post.txt (M94) or <rid>.txt
    post_kind: str = ""           # «описание» (.post.txt) | «подпись рендера» (.txt)
    hook: str = ""                # M95: the cold open's words (what the viewer hears first)
    keywords: list[str] = field(default_factory=list)    # M95: the k: words highlighted in the subtitles


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
.cover{display:block;width:96px;margin:8px auto 0;border-radius:6px;border:1px solid var(--line)}
.covercap{text-align:center;color:var(--mute);font-size:12px}
.kv{margin:2px 0;color:var(--mute)}.kv b{color:var(--ink);font-weight:600}
.post{white-space:pre-wrap;margin:6px 0 8px;padding:8px 10px;border:1px solid var(--line);border-radius:8px}
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
.why{display:flex;flex-wrap:wrap;gap:4px;margin:0 0 6px}
.why label{border:1px dashed var(--line);border-radius:999px;padding:2px 9px;font-size:13px;cursor:pointer;user-select:none;
color:var(--mute)}
.why input{position:absolute;opacity:0;pointer-events:none}
.why input:focus-visible+span{outline:2px solid var(--accent);outline-offset:3px}
.why label:has(input:checked){border-style:solid;border-color:var(--fix);color:var(--ink);
background:color-mix(in srgb,var(--fix) 18%,transparent)}
textarea{width:100%;min-height:54px;font:inherit;border:1px solid var(--line);border-radius:8px;padding:6px 8px;
background:var(--bg);color:var(--ink)}
.noline{color:var(--drop)}
.card[data-v="edit"]{border-color:var(--accent)}
.choice label:has(input[value="edit"]:checked){background:var(--accent);border-color:var(--accent);color:#fff}
.ed{margin:8px 0;border-top:1px solid var(--line);padding-top:8px}
.ed .bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0 0 8px}
.ed .bar button{padding:5px 10px}.ed .bar button[aria-pressed="true"]{background:var(--ink);color:var(--card)}
.ed .txt{line-height:1.7}
.ed .s{cursor:pointer;border-radius:4px;padding:1px 2px;-webkit-tap-highlight-color:transparent}
.ed .s.off{color:var(--mute);text-decoration:line-through;opacity:.7}
.ed .s.hook{background:color-mix(in srgb,var(--accent) 22%,transparent)}
.ed .s.now{outline:2px solid var(--accent)}
.ed .n{font-family:var(--mono);font-size:11px;color:var(--mute);margin-right:2px}
.ed .flag{font-size:12px;color:var(--fix)}
.ed .out{font-family:var(--mono);font-size:12.5px;margin-top:8px}
.ed .warn{color:var(--fix);font-size:13px}
.ed video.pv{width:100%;max-width:300px;aspect-ratio:16/9;margin:6px 0}
.att{margin-top:8px}
.tl{position:relative;height:18px;background:var(--bg);border:1px solid var(--line);border-radius:4px}
.tl .tk{position:absolute;top:2px;bottom:2px;width:3px;margin-left:-1px;padding:0;border:0;border-radius:2px;
background:var(--mute);cursor:pointer}
.tl .tk.seam{background:var(--accent)}.tl .tk.cut{background:var(--line);width:2px}
.tl .tk.shot{background:var(--ok);opacity:.6;width:2px}.tl .tk.hook{background:var(--ink)}
.tl .tk{z-index:1}.tl .tk.static,.tl .tk.static.bad{z-index:0;background:color-mix(in srgb,var(--fix) 28%,transparent);
margin-left:0;border-radius:0}
.tl .tk.bad{background:var(--fix);width:4px}
.al{list-style:none;padding:0;margin:6px 0;font-size:13px}.al li{margin:4px 0}.al li.bad{color:var(--fix)}
.al ul{margin:2px 0 0 18px;padding:0}.al .tt{padding:1px 6px;font-family:var(--mono);font-size:12px}
@media (max-width:700px){.card{grid-template-columns:1fr}video,.novideo{max-height:70vh;width:auto;margin:0 auto}}
"""

_JS = r"""
(function(){
  const meta = JSON.parse(document.getElementById('meta').textContent);
  const CLIPS = JSON.parse(document.getElementById('clips').textContent || '{}');
  const key = 'arl-review:' + meta.stem + ':' + meta.key;
  const cards = Array.from(document.querySelectorAll('.card[data-seq], .card[data-montage]'));
  const ED = {};                       // rid → {played:Set, hook, orig:{played, hook}}
  function load(){ try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch(e){ return {}; } }
  function save(st){ try { localStorage.setItem(key, JSON.stringify(st)); } catch(e){} }
  function verdict(c){ return (c.querySelector('input[type=radio]:checked') || {}).value || ''; }
  function reasons(c){ return Array.from(c.querySelectorAll('.why input:checked')).map(i => i.value); }

  // ── M52: the clip as text ──────────────────────────────────────────────────────────────
  function ranges(ns){
    const out = []; let a = null, b = null;
    ns.forEach(n => { if (a === null) { a = b = n; } else if (n === b + 1) { b = n; } else { out.push([a, b]); a = b = n; } });
    if (a !== null) out.push([a, b]);
    return out;
  }
  function fields(rid){
    const e = ED[rid]; const p = Array.from(e.played).sort((x, y) => x - y);
    if (!p.length) return '';
    const s = p[0], en = p[p.length - 1], x = [];
    for (let k = s; k <= en; k++) if (!e.played.has(k)) x.push(k);
    let f = 's:' + s + ' e:' + en;
    if (x.length) f += ' x:' + ranges(x).map(r => r[0] === r[1] ? '' + r[0] : r[0] + '-' + r[1]).join(',');
    if (e.hook) f += ' h:' + e.hook;
    return f;
  }
  function changed(rid){
    const e = ED[rid];
    if ((e.hook || null) !== (e.orig.hook || null)) return true;
    if (e.played.size !== e.orig.played.size) return true;
    for (const n of e.played) if (!e.orig.played.has(n)) return true;
    return false;
  }
  function segments(rid, version){
    const d = CLIPS[rid], e = ED[rid];
    const played = version === 'orig' ? e.orig.played : e.played;
    const hook = version === 'orig' ? e.orig.hook : e.hook;
    const by = {}; d.sentences.forEach(x => by[x.n] = x);
    const segs = [];
    if (hook && by[hook]) segs.push([by[hook].a - 0.1, by[hook].b + 0.25, [hook]]);
    ranges(Array.from(played).sort((x, y) => x - y)).forEach(r => {
      const ns = []; for (let k = r[0]; k <= r[1]; k++) ns.push(k);
      segs.push([by[r[0]].a - 0.12, by[r[1]].b + 0.25, ns]);
    });
    return segs.map(sg => [Math.max(0, sg[0] - d.offset), sg[1] - d.offset, sg[2]]);
  }
  let playing = null;
  function stop(){
    if (!playing) return;
    playing.el.pause(); playing.card.querySelectorAll('.s.now').forEach(x => x.classList.remove('now'));
    playing = null;
  }
  function play(card, rid, version){
    stop();
    const el = card.querySelector('.pv'); if (!el) return;
    const segs = segments(rid, version); if (!segs.length) return;
    playing = {el: el, card: card, segs: segs, i: 0};
    const mark = () => {
      card.querySelectorAll('.s.now').forEach(x => x.classList.remove('now'));
      const t = el.currentTime + CLIPS[rid].offset;
      const ns = playing.segs[playing.i][2];
      CLIPS[rid].sentences.forEach(x => { if (ns.indexOf(x.n) >= 0 && t >= x.a && t < x.b) {
        const sp = card.querySelector('.s[data-n="' + x.n + '"]'); if (sp) sp.classList.add('now'); } });
    };
    const go = () => { el.currentTime = playing.segs[playing.i][0]; el.play(); };
    const tick = () => {
      if (!playing || playing.el !== el) return;
      if (el.currentTime >= playing.segs[playing.i][1]) {
        playing.i++;
        if (playing.i >= playing.segs.length) { stop(); return; }
        el.currentTime = playing.segs[playing.i][0];
      }
      mark(); requestAnimationFrame(tick);
    };
    go(); requestAnimationFrame(tick);
  }
  function drawEditor(card){
    const rid = card.dataset.rid, d = CLIPS[rid], e = ED[rid];
    const box = card.querySelector('.ed'); if (!box) return;
    const txt = box.querySelector('.txt');
    txt.innerHTML = '';
    d.sentences.forEach(x => {
      const sp = document.createElement('span');
      sp.className = 's' + (e.played.has(x.n) ? '' : ' off') + (e.hook === x.n ? ' hook' : '');
      sp.dataset.n = x.n;
      sp.innerHTML = '<span class="n">[' + x.n + ']</span>';
      sp.appendChild(document.createTextNode(x.text));
      if (!x.complete) sp.insertAdjacentHTML('beforeend', ' <span class="flag">…→</span>');
      if (x.open) sp.insertAdjacentHTML('beforeend', ' <span class="flag">↗</span>');
      txt.appendChild(sp); txt.appendChild(document.createTextNode(' '));
    });
    const p = Array.from(e.played).sort((a, b) => a - b);
    const segs = segments(rid, 'new');
    const sec = segs.reduce((t, sg) => t + (sg[1] - sg[0]), 0);
    box.querySelector('.out').textContent = changed(rid)
      ? 'правка: ' + (fields(rid) || '—') + ' · ≈' + Math.round(sec) + ' с'
      : 'как в черновике · ≈' + Math.round(sec) + ' с';
    const w = [];
    if (!p.length) w.push('ни одной фразы — клип пустой');
    else {
      const last = d.sentences.find(x => x.n === p[p.length - 1]), first = d.sentences.find(x => x.n === p[0]);
      if (!last.complete) w.push('конец на незаконченной фразе (…→)');
      if (last.open) w.push('конец с голосом вверх (↗) — звучит как «продолжение следует»');
      if (first.text && first.text[0] === first.text[0].toLowerCase()) w.push('начало посреди фразы');
      if (sec < 15) w.push('короче 15 с');
    }
    box.querySelector('.warn').textContent = w.join(' · ');
  }
  function setVerdictFromEdit(card){
    const rid = card.dataset.rid;
    const r = card.querySelector('input[value="edit"]'); if (!r) return;
    if (changed(rid)) r.checked = true;
    else if (r.checked) r.checked = false;
  }
  cards.forEach(card => {
    const rid = card.dataset.rid, d = CLIPS[rid];
    if (!d) return;
    const orig = {played: new Set(d.sentences.filter(x => x.played).map(x => x.n)), hook: d.hook || null};
    ED[rid] = {played: new Set(orig.played), hook: orig.hook, orig: orig, mode: 'cut'};
    const box = card.querySelector('.ed'); if (!box) return;
    box.querySelectorAll('[data-mode]').forEach(b => b.addEventListener('click', () => {
      ED[rid].mode = b.dataset.mode;
      box.querySelectorAll('[data-mode]').forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
    }));
    box.querySelector('.txt').addEventListener('click', ev => {
      const sp = ev.target.closest('.s'); if (!sp) return;
      const n = +sp.dataset.n, e = ED[rid];
      if (e.mode === 'hook') e.hook = (e.hook === n ? null : n);
      else if (e.played.has(n)) e.played.delete(n); else e.played.add(n);
      drawEditor(card); setVerdictFromEdit(card); refresh();
    });
    box.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => {
      const a = b.dataset.act, e = ED[rid];
      if (a === 'play') play(card, rid, 'new');
      else if (a === 'orig') play(card, rid, 'orig');
      else if (a === 'stop') stop();
      else if (a === 'reset') { e.played = new Set(e.orig.played); e.hook = e.orig.hook; drawEditor(card);
                                setVerdictFromEdit(card); refresh(); }
    }));
  });

  // ── M53: marks — click jumps the clip to that moment ───────────────────────────────────
  document.querySelectorAll('.card').forEach(card => {
    const v = card.querySelector('.media video'); if (!v) return;
    card.querySelectorAll('.att [data-t]').forEach(b => b.addEventListener('click', () => {
      v.currentTime = Math.max(0, +b.dataset.t - 1.5); v.play();
    }));
  });

  // ── verdicts ───────────────────────────────────────────────────────────────────────────
  function state(){
    const st = {};
    cards.forEach(c => {
      const v = verdict(c), rid = c.dataset.rid;
      const n = c.querySelector('textarea').value.trim();
      const ed = ED[rid] && changed(rid) ? {p: Array.from(ED[rid].played), h: ED[rid].hook} : null;
      const r = reasons(c);
      if (v || n || ed || r.length) st[rid] = {v: v, n: n, ed: ed, r: r};
    });
    return st;
  }
  function refresh(){
    let done = 0;
    cards.forEach(c => {
      const v = verdict(c);
      c.dataset.v = v;
      c.classList.toggle('missing-note', v === 'fix' && !c.querySelector('textarea').value.trim() && !reasons(c).length);
      if (v) done++;
    });
    document.getElementById('count').textContent = 'решено ' + done + ' из ' + cards.length;
    save(state());
  }
  const st = load();
  cards.forEach(c => {
    const s = st[c.dataset.rid], rid = c.dataset.rid;
    if (s) {
      if (s.ed && ED[rid]) { ED[rid].played = new Set(s.ed.p); ED[rid].hook = s.ed.h || null; }
      const r = c.querySelector('input[type=radio][value="' + s.v + '"]'); if (r) r.checked = true;
      (s.r || []).forEach(x => { const b = c.querySelector('.why input[value="' + x + '"]'); if (b) b.checked = true; });
      c.querySelector('textarea').value = s.n || '';
    }
    if (ED[rid]) drawEditor(c);
    c.addEventListener('change', refresh);
    c.querySelector('textarea').addEventListener('input', refresh);
  });
  function text(){
    const out = ['# stem: ' + meta.stem, '# review: ' + meta.review, '# manifest: ' + meta.manifest,
                 '# decided: ' + new Date().toISOString().slice(0, 10)];
    if (meta.gate) out.push('# gate: ' + meta.gate);
    cards.forEach(c => {
      const v = verdict(c), rid = c.dataset.rid;
      const r = reasons(c);
      const n0 = c.querySelector('textarea').value.trim().replace(/\s*\n\s*/g, ' ');
      const n = (r.length ? 'причины: ' + r.join(', ') + (n0 ? ' | ' : '') : '') + n0;
      const head = rid + (c.dataset.montage ? ' | montage ' + c.dataset.montage : ' | line ' + c.dataset.seq);
      if (!v) out.push('# ' + head + ' | не решено' + (n ? ' | ' + n : ''));
      else if (v === 'edit' && !c.dataset.montage) {
        const f = ED[rid] ? fields(rid) : '';
        if (f && changed(rid)) out.push(head + ' | edit | ' + f + (n ? ' | ' + n : ''));
        else out.push('# ' + head + ' | правка без изменений' + (n ? ' | ' + n : ''));
      }
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


# M82: why a clip is dropped or must be redone — one tap each; the verdicts with their reasons are what the
# formulas will later learn from (arl review-apply → reviews/verdicts.jsonl).
REASONS = ("начало", "крючок", "плашка", "конец", "темп", "стык", "кадр", "звук", "скучно")


def _choice_html(c: "Card", *, edit: bool = False) -> str:
    name = f"v-{_e(c.rid)}"
    choices = (("ok", "Оставить"), ("drop", "Убрать"), ("fix", "Переделать")) + ((("edit", "Правка"),) if edit else ())
    radios = "".join(f'<label><input type="radio" name="{name}" value="{v}"><span>{t}</span></label>'
                     for v, t in choices)
    why = "".join(f'<label><input type="checkbox" value="{r}"><span>{r}</span></label>' for r in REASONS)
    return (f'<div class="choice">{radios}</div>'
            f'<div class="why" aria-label="Что не так у {_e(c.rid)}">{why}</div>'
            f'<textarea placeholder="Замечание (для «Переделать» — замечание или причина): что не так, '
            f'где начать или закончить…" aria-label="Замечание к {_e(c.rid)}"></textarea>')


def _e(s: str) -> str:
    return html.escape(s or "", quote=True)


def _card_html(c: Card) -> str:
    vid = (f'<video src="{_e(c.video)}" controls preload="metadata" playsinline></video>' if c.video
           else '<div class="novideo">клип не отрендерен</div>')
    warns = "".join(f"<li>{_e(w)}</li>" for w in c.warnings)
    cover = (f'<img class="cover" src="{_e(c.cover)}" alt="обложка {_e(c.rid)}" loading="lazy">'
             f'<div class="covercap">обложка</div>' if c.cover else "")
    parts = [f'<div class="media">{vid}{_attention_html(c)}{cover}</div><div class="info">',
             f'<div><span class="rid">{_e(c.rid)}</span><span class="dur">{c.duration:.0f} с</span>'
             + (f'<span class="dur">· оценка {c.score}</span>' if c.score is not None else "") + '</div>']
    if c.title:
        parts.append(f'<div class="title">{_e(c.title)}</div>')
    if c.caption:
        parts.append(f'<div class="caption">{_e(c.caption)}</div>')
    if c.hook:
        parts.append(f'<div class="kv">крючок: <b>«{_e(c.hook)}»</b></div>')
    if c.keywords:
        parts.append(f'<div class="kv">ключевые слова: <b>{_e(", ".join(c.keywords))}</b></div>')
    if c.post:
        parts.append(f'<details open><summary>текст поста ({_e(c.post_kind or "crosspost")})</summary>'
                     f'<div class="post">{_e(c.post)}</div></details>')
    if c.text:
        parts.append(f'<details><summary>текст клипа</summary><div class="subs">{_e(c.text)}</div></details>')
    if warns:
        parts.append(f'<ul class="warns">{warns}</ul>')
    if c.montage:
        # M82: a montage clip is decided like any other (the verdict and its reasons go to the decisions file —
        # into reviews/verdicts.jsonl at arl review-apply; the draft line itself is not rewritten)
        label = (c.montage.split() or ["M"])[0]
        parts.append(f'<details open><summary>сборка из кусков разных блоков</summary>'
                     f'<div class="line">{_e(c.montage)}</div></details>')
        parts.append(_choice_html(c) + "</div>")
        return (f'<section class="card" data-rid="{_e(c.rid)}" data-montage="{_e(label)}">' + "".join(parts)
                + "</section>")
    if c.seq is None:
        parts.append('<p class="noline">Строка черновика для этого клипа не найдена: черновик менялся '
                     'после рендера. Решение по нему здесь не принимается.</p></div>')
        return f'<section class="card" data-rid="{_e(c.rid)}">' + "".join(parts) + "</section>"
    parts.append(f'<details><summary>строка {c.seq} черновика</summary><div class="line">{_e(c.line)}</div>'
                 + (f'<div class="marks">{_e(c.preview)}</div>' if c.preview else "") + "</details>")
    if c.marks:
        parts.append('<div class="marks">' + "<br>".join(_e(m) for m in c.marks) + "</div>")
    if c.edit:
        parts.append(_editor_html(c))
    parts.append(_choice_html(c, edit=bool(c.edit)) + "</div>")
    return (f'<section class="card" data-rid="{_e(c.rid)}" data-seq="{c.seq}">' + "".join(parts)
            + "</section>")


STATIC_SEC = 8.0      # longer than this with no change of picture: the viewer's attention drops

_KIND_RU = {"seam": "стык", "cut": "вырезана пауза", "shot": "смена плана", "hook": "конец крючка",
            "static": "без смены картинки"}


def attention_marks(reel, static_sec: float = STATIC_SEC) -> list[dict]:
    """M53: where in the rendered clip to look, in the clip's own seconds (speed applied):
    seams between windows, filler/pause cuts, shot changes, the end of the cold open, stretches
    longer than static_sec with none of these (attention drops), and the montage seam notes the
    plan wrote into reel.marks (pause, loudness, pitch, picture jump, warnings). Approximate by the
    xfade (a few frames) — for pointing, not for measuring."""
    speed = float(getattr(reel, "speed", 1.0) or 1.0)
    wins = reel.playback_windows()
    has_co = getattr(reel, "cold_open", None) is not None
    events: list[dict] = []
    starts: list[float] = []
    acc = 0.0
    for i, w in enumerate(wins):
        starts.append(acc)
        dur = (w.end - w.start) / speed
        if i > 0:
            kind = "hook" if (has_co and i == 1) else ("cut" if getattr(w, "window_cut", False) else "seam")
            events.append({"t": round(acc, 2), "kind": kind})
        for c0, c1 in (getattr(w, "close_intervals", None) or []):
            for x in (c0, c1):
                if 0.05 < x / speed < dur - 0.05:
                    events.append({"t": round(acc + x / speed, 2), "kind": "shot"})
        acc += dur
    total = acc
    body0 = 1 if has_co else 0
    for m in getattr(reel, "marks", None) or []:
        t_src = float(m.get("t", 0.0))
        k = next((i for i in range(body0, len(wins)) if abs(wins[i].start - t_src) < 0.02), None)
        if k is None:
            k = next((i for i in range(body0, len(wins)) if wins[i].start <= t_src < wins[i].end), None)
        if k is None:
            continue
        t = round(starts[k] + (t_src - wins[k].start) / speed, 2)
        ev = next((e for e in events if abs(e["t"] - t) < 0.05 and e["kind"] in ("seam", "cut")), None)
        if ev is None:
            ev = {"t": t, "kind": m.get("kind", "seam")}
            events.append(ev)
        ev["kind"] = m.get("kind", ev["kind"])
        ev["text"] = m.get("text", "")
        ev["warn"] = list(m.get("warn", []))
    changes = sorted({0.0, total, *[e["t"] for e in events if e["kind"] != "static"]})
    for a, b in zip(changes, changes[1:]):
        if b - a > static_sec:
            events.append({"t": round(a, 2), "kind": "static", "len": round(b - a, 1),
                           "warn": [f"{b - a:.0f} с без смены картинки — внимание падает"]})
    events.sort(key=lambda e: (e["t"], e["kind"]))
    return events


def _fmt_t(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _attention_html(c: Card) -> str:
    if not c.attention or not c.duration:
        return ""
    total = max(c.duration, 0.1)
    ticks = "".join(
        f'<button type="button" class="tk {e["kind"]}{" bad" if e.get("warn") else ""}" data-t="{e["t"]}" '
        f'style="left:{min(100.0, 100.0 * e["t"] / total):.2f}%'
        + (f';width:{100.0 * e.get("len", 0) / total:.2f}%' if e["kind"] == "static" else "")
        + f'" title="{_e(_fmt_t(e["t"]) + " " + _KIND_RU.get(e["kind"], e["kind"]))}"></button>'
        for e in c.attention)
    items = []
    for e in c.attention:
        if not (e.get("warn") or e.get("text")):
            continue
        what = e.get("text") or _KIND_RU.get(e["kind"], e["kind"])
        warn = "".join(f"<li>{_e(w)}</li>" for w in e.get("warn", []))
        items.append(f'<li class="{"bad" if e.get("warn") else ""}"><button type="button" class="tt" data-t="{e["t"]}">'
                     f'{_fmt_t(e["t"])}</button> {_e(what)}' + (f"<ul>{warn}</ul>" if warn else "") + "</li>")
    n_bad = sum(1 for e in c.attention if e.get("warn"))
    head = f"на что смотреть: {n_bad}" if n_bad else "на что смотреть"
    return (f'<div class="att"><div class="tl" aria-label="метки клипа">{ticks}</div>'
            + (f'<details {"open" if n_bad else ""}><summary>{head}</summary><ul class="al">{"".join(items)}</ul></details>'
               if items else "") + "</div>")


def _editor_html(c: Card) -> str:
    """The clip as text (M52). The sentences are filled in by the script from #clips."""
    media = c.edit.get("media") or ""
    player = ""
    if media.endswith(".mp4"):
        player = f'<video class="pv" src="{_e(media)}" preload="metadata" playsinline></video>'
    elif media:
        player = f'<audio class="pv" src="{_e(media)}" preload="metadata"></audio>'
    play = ('<button type="button" data-act="play">▶ правка</button>'
            '<button type="button" data-act="orig">▶ было</button>'
            '<button type="button" data-act="stop">■</button>') if media else \
        '<span class="warn">нет файла предпросмотра (arl review-sheet … --preview audio)</span>'
    return (f'<details class="ed" open><summary>правка по тексту</summary>{player}'
            '<div class="bar"><button type="button" data-mode="cut" aria-pressed="true">вкл/выкл фразу</button>'
            '<button type="button" data-mode="hook" aria-pressed="false">★ крючок</button>'
            f'{play}<button type="button" data-act="reset">↺ как было</button></div>'
            '<div class="txt"></div><div class="out"></div><div class="warn"></div></details>')


def build_sheet(stem: str, cards: list[Card], *, review_ref: str, manifest_ref: str, key: str,
                notes: list[str] = (), gate: str = "") -> str:
    """The whole page. key: a short hash of the draft — choices saved in the browser belong to it."""
    meta = json.dumps({"stem": stem, "review": review_ref, "manifest": manifest_ref, "key": key, "gate": gate or ""},
                      ensure_ascii=False).replace("</", "<\\/")
    clips = json.dumps({c.rid: c.edit for c in cards if c.edit and c.seq is not None},
                       ensure_ascii=False).replace("</", "<\\/")
    unmatched = [c.rid for c in cards if c.seq is None and not c.montage]
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
        f"<script id=\"meta\" type=\"application/json\">{meta}</script>"
        f"<script id=\"clips\" type=\"application/json\">{clips}</script><script>{_JS}</script>"
        "</body></html>\n"
    )


PREVIEW_PAD = 1.0     # seconds of source kept before the first and after the last sentence


def preview_span(model: dict) -> tuple[float, float]:
    ss = model["sentences"]
    return max(0.0, round(ss[0]["a"] - PREVIEW_PAD, 2)), round(ss[-1]["b"] + PREVIEW_PAD, 2)


def preview_name(rid: str, span: tuple[float, float], kind: str) -> str:
    """_preview/<rid>-<a>-<b>.m4a|.mp4 — the span in the name: a changed clip gets a new file."""
    return f"_preview/{rid}-{span[0]:.2f}-{span[1]:.2f}." + ("mp4" if kind == "video" else "m4a")


def preview_cmd(ffmpeg: str, source, span: tuple[float, float], out, kind: str,
                vcodec: str = "libx264") -> list[str]:
    """Small preview of a stretch of the source for the text editor: mono AAC (audio) or, with the
    picture, the whole frame scaled to 480 px wide at 15 fps (video). Not the reel crop: the
    preview is for hearing the seams and seeing the speaker, not for judging the frame."""
    a, b = span
    cmd = [ffmpeg, "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(source)]
    if kind == "video":
        vq = ["-crf", "32", "-preset", "veryfast"] if vcodec == "libx264" else ["-b:v", "500k"]
        cmd += ["-vf", "scale=480:-2", "-r", "15", "-c:v", vcodec, *vq, "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-vn"]
    cmd += ["-ac", "1", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)]
    return cmd
