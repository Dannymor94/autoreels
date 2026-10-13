"""M54: the map of a source as one HTML page (reels-out/<stem>/_map.html, `arl map`).

Topics on the timeline, then every thought with its time, review numbering (B.k — ready for a
montage line), role, strength, voice energy, what it leans on and the similar thoughts elsewhere.
Filters by topic and role; nothing is sent anywhere. Pure: build_map_page(map dict) → HTML.
"""
from __future__ import annotations

import html
import json

from autoreels.cloud.thoughtmap import ROLE_RU

_PALETTE = ["#2f5bd3", "#1f7a3e", "#9a5b00", "#b3261e", "#6b4bc4", "#0f7c8c", "#a14f8a", "#5b6b1f",
            "#c2571a", "#3d6e9e", "#7a4f2a", "#2c8a6a", "#8c3b3b", "#4a4ac4", "#6b6a66"]

_CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1b;--mute:#6b6a66;--line:#e2e0da;--accent:#2f5bd3;--warn:#9a5b00;
--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--card:#1f1f1d;--ink:#ecebe7;
--mute:#a09f9a;--line:#33322f;--accent:#8aa8ff;--warn:#f0b252}}
:root[data-theme="dark"]{--bg:#151514;--card:#1f1f1d;--ink:#ecebe7;--mute:#a09f9a;--line:#33322f;--accent:#8aa8ff;--warn:#f0b252}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px}
h1{font-size:17px;margin:0 0 8px}.sub{color:var(--mute);font-size:13px}
main{max-width:1100px;margin:0 auto;padding:16px}
.tl{position:relative;height:28px;border-radius:6px;overflow:hidden;background:var(--line);margin:10px 0 4px}
.tl a{position:absolute;top:0;bottom:0;display:block;border-right:1px solid var(--bg)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:3px 10px;
font:inherit;font-size:13px;cursor:pointer}.chip[aria-pressed="true"]{outline:2px solid var(--accent)}
.chip i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.u{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--line);border-radius:10px;
padding:10px 12px;margin:0 0 10px}
.u.hidden{display:none}.u.weak{opacity:.55}
.meta{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;font-size:13px;color:var(--mute)}
.id{font-family:var(--mono);color:var(--ink);font-weight:600}.refs{font-family:var(--mono);color:var(--accent)}
.role{border-radius:4px;padding:0 6px;background:var(--bg);color:var(--ink)}
.stars{color:var(--warn);letter-spacing:1px}
.en{display:inline-block;width:60px;height:6px;background:var(--line);border-radius:3px;vertical-align:middle}
.en b{display:block;height:6px;border-radius:3px;background:var(--accent)}
.sum{font-weight:600;margin:4px 0 2px}.txt{margin:2px 0}
.links{font-size:13px;color:var(--mute);margin-top:4px}.links a{color:var(--accent)}
.flag{color:var(--warn)}
@media (max-width:600px){main{padding:10px}.u{padding:8px}}
"""

_JS = r"""
(function(){
  const units = Array.from(document.querySelectorAll('.u'));
  const st = {topic: null, role: null};
  function apply(){
    units.forEach(u => {
      const ok = (st.topic === null || u.dataset.topic === st.topic) && (st.role === null || u.dataset.role === st.role);
      u.classList.toggle('hidden', !ok);
    });
    document.querySelectorAll('.chip[data-topic]').forEach(c => c.setAttribute('aria-pressed', c.dataset.topic === st.topic));
    document.querySelectorAll('.chip[data-role]').forEach(c => c.setAttribute('aria-pressed', c.dataset.role === st.role));
  }
  document.querySelectorAll('.chip[data-topic]').forEach(c => c.addEventListener('click', () => {
    st.topic = st.topic === c.dataset.topic ? null : c.dataset.topic; apply(); }));
  document.querySelectorAll('.chip[data-role]').forEach(c => c.addEventListener('click', () => {
    st.role = st.role === c.dataset.role ? null : c.dataset.role; apply(); }));
})();
"""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _t(x: float) -> str:
    return f"{int(x // 60)}:{int(x % 60):02d}"


def build_map_page(m: dict) -> str:
    units = m.get("units") or []
    topics = {t["id"]: t for t in (m.get("topics") or [])}
    color = {tid: _PALETTE[i % len(_PALETTE)] for i, tid in enumerate(sorted(topics, key=lambda x: (x == 0, x)))}
    total = max((u["t1"] for u in units), default=1.0) or 1.0
    tl = "".join(
        f'<a href="#u{u["id"]}" title="#{u["id"]} {_e(_t(u["t0"]))} {_e(topics.get(u.get("topic"), {}).get("name", ""))}" '
        f'style="left:{100 * u["t0"] / total:.3f}%;width:{max(0.2, 100 * (u["t1"] - u["t0"]) / total):.3f}%;'
        f'background:{color.get(u.get("topic"), "#999")};opacity:{0.35 + 0.13 * (u.get("punch") or 1):.2f}"></a>'
        for u in units)
    tchips = "".join(
        f'<button type="button" class="chip" data-topic="{tid}" aria-pressed="false"><i style="background:{color[tid]}"></i>'
        f'{_e(t["name"])} · {len(t["units"])}</button>' for tid, t in sorted(topics.items(), key=lambda x: (x[0] == 0, x[0])))
    roles_present = sorted({u.get("role") for u in units if u.get("role")}, key=lambda r: list(ROLE_RU).index(r))
    rchips = "".join(f'<button type="button" class="chip" data-role="{r}" aria-pressed="false">{ROLE_RU[r]}</button>'
                     for r in roles_present)
    cards = []
    for u in units:
        v = u.get("voice") or {}
        en = v.get("energy")
        punch = u.get("punch")
        bits = [f'<span class="id">#{u["id"]}</span>', f'<span>{_t(u["t0"])}–{_t(u["t1"])}</span>']
        bits.append(f'<span class="refs">{_e(u["refs"])}</span>' if u.get("refs")
                    else f'<span class="flag">вне разметки{(" (" + _e(u.get("filtered")) + ")") if u.get("filtered") else ""}</span>')
        if u.get("role"):
            bits.append(f'<span class="role">{ROLE_RU.get(u["role"], u["role"])}</span>')
        if punch:
            bits.append(f'<span class="stars" title="сила {punch} из 5">{"★" * punch}{"☆" * (5 - punch)}</span>')
        if en is not None:
            bits.append(f'<span title="энергия голоса {en} из 100">голос <span class="en"><b style="width:{en}%"></b></span></span>')
        if u.get("missing"):
            bits.append('<span class="flag">модель не описала</span>')
        links = []
        if u.get("standalone") is False:
            links.append("опирается на " + (f'<a href="#u{u["refers"]}">#{u["refers"]}</a>' if u.get("refers") else "предыдущее"))
        if u.get("similar"):
            links.append("похоже: " + ", ".join(f'<a href="#u{i}">#{i}</a> ({s:.2f})' for i, s in u["similar"]))
        tname = topics.get(u.get("topic"), {}).get("name", "")
        cards.append(
            f'<section class="u{" weak" if (punch or 3) <= 1 or u.get("role") == "aside" else ""}" id="u{u["id"]}" '
            f'data-topic="{_e(u.get("topic"))}" data-role="{_e(u.get("role") or "")}" '
            f'style="border-left-color:{color.get(u.get("topic"), "var(--line)")}">'
            f'<div class="meta">{"".join(bits)}<span>{_e(tname)}</span></div>'
            + (f'<div class="sum">{_e(u.get("summary"))}</div>' if u.get("summary") else "")
            + f'<div class="txt">{_e(u["text"])}</div>'
            + (f'<div class="links">{" · ".join(links)}</div>' if links else "") + "</section>")
    n_strong = sum(1 for u in units if (u.get("punch") or 0) >= 4)
    return ("<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Карта {_e(m.get('stem'))}</title><style>{_CSS}</style></head><body>"
            f"<header><h1>Карта: {_e(m.get('stem'))}</h1>"
            f"<div class=\"sub\">{len(units)} мыслей · тем {sum(1 for t in topics if t)} · сильных (★4–5) {n_strong}"
            f"{' · модель ' + _e(m.get('model')) if m.get('model') else ''}</div>"
            f"<div class=\"tl\" aria-label=\"темы на шкале времени\">{tl}</div>"
            f"<div class=\"chips\">{tchips}</div><div class=\"chips\">{rchips}</div></header>"
            f"<main>{''.join(cards)}</main><script>{_JS}</script></body></html>\n")


def write_map_json(m: dict) -> str:
    return json.dumps(m, ensure_ascii=False, indent=1)
