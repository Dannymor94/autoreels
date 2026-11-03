"""M214b: a `vless://…` line → an Xray config — a local proxy for gamebox (no VPN there; the models need one).

Owner, 2026-11-03: gamebox has no VPN; Groq / OpenRouter / Hugging Face need it, Yandex Disk and the LAN do not.
The config: inbounds socks 127.0.0.1:10808 and http 127.0.0.1:10809 (autoreels uses the http one through HTTPS_PROXY in
.env — the system itself is not routed); one VLESS outbound (security reality | tls | none; network xhttp | tcp | ws |
grpc); routing as the owner's client has it: .ru / .su / .рф / geosite:category-ru and geoip:ru / geoip:private go
direct. The key is read from a file and never printed; the config goes to stdout or --out (chmod 600).
Run: python tools/vless2xray.py ~/.config/xray/vless.txt --out ~/.config/xray/config.json"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

DIRECT_DOMAINS = ["domain:ru", "domain:su", "domain:xn--p1ai", "geosite:category-ru"]
DIRECT_IPS = ["geoip:ru", "geoip:private"]


def parse(uri: str) -> dict:
    """The parts of a vless:// line (id, host, port and the query) — ValueError when it is not one."""
    u = urlparse(uri.strip())
    if u.scheme != "vless" or not u.username or not u.hostname:
        raise ValueError("не строка vless://id@host:port?…")
    q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
    return {"id": unquote(u.username), "host": u.hostname, "port": int(u.port or 443), "q": q,
            "name": unquote(u.fragment or "")}


def config(uri: str, *, socks_port: int = 10808, http_port: int = 10809, direct_ru: bool = True) -> dict:
    p = parse(uri)
    q = p["q"]
    net = q.get("type", "tcp") or "tcp"
    sec = q.get("security", "none") or "none"
    user = {"id": p["id"], "encryption": q.get("encryption", "none") or "none"}
    if q.get("flow"):
        user["flow"] = q["flow"]
    stream: dict = {"network": net, "security": sec}
    if sec == "reality":
        stream["realitySettings"] = {"serverName": q.get("sni", ""), "fingerprint": q.get("fp", "chrome"),
                                     "publicKey": q.get("pbk", ""), "shortId": q.get("sid", ""),
                                     "spiderX": unquote(q.get("spx", "") or "")}
    elif sec == "tls":
        stream["tlsSettings"] = {"serverName": q.get("sni", p["host"]), "fingerprint": q.get("fp", "chrome"),
                                 **({"alpn": q["alpn"].split(",")} if q.get("alpn") else {})}
    if net == "xhttp":
        stream["xhttpSettings"] = {"path": unquote(q.get("path", "/") or "/"), "mode": q.get("mode", "auto") or "auto",
                                   **({"host": q["host"]} if q.get("host") else {})}
    elif net == "ws":
        stream["wsSettings"] = {"path": unquote(q.get("path", "/") or "/"),
                                **({"headers": {"Host": q["host"]}} if q.get("host") else {})}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": q.get("serviceName", "")}
    elif net != "tcp":
        raise ValueError(f"транспорт {net!r} не поддержан (xhttp, tcp, ws, grpc)")
    rules = []
    if direct_ru:
        rules = [{"type": "field", "outboundTag": "direct", "domain": DIRECT_DOMAINS},
                 {"type": "field", "outboundTag": "direct", "ip": DIRECT_IPS}]
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"tag": "socks", "listen": "127.0.0.1", "port": socks_port, "protocol": "socks",
                      "settings": {"udp": True}},
                     {"tag": "http", "listen": "127.0.0.1", "port": http_port, "protocol": "http"}],
        "outbounds": [{"tag": "proxy", "protocol": "vless",
                       "settings": {"vnext": [{"address": p["host"], "port": p["port"], "users": [user]}]},
                       "streamSettings": stream},
                      {"tag": "direct", "protocol": "freedom"},
                      {"tag": "block", "protocol": "blackhole"}],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": rules},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("key_file", help="файл со строкой vless://… (ключ не печатается)")
    ap.add_argument("--out", default=None, help="куда записать конфиг (иначе — в stdout)")
    ap.add_argument("--socks-port", type=int, default=10808)
    ap.add_argument("--http-port", type=int, default=10809)
    ap.add_argument("--no-direct-ru", action="store_true", help="без правил «РФ и локальная сеть — напрямую»")
    a = ap.parse_args(argv)
    line = next((ln.strip() for ln in Path(a.key_file).expanduser().read_text(encoding="utf-8").splitlines()
                 if ln.strip().startswith("vless://")), "")
    try:
        cfg = config(line, socks_port=a.socks_port, http_port=a.http_port, direct_ru=not a.no_direct_ru)
    except ValueError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(cfg, ensure_ascii=False, indent=2)
    if a.out:
        out = Path(a.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        os.chmod(out, 0o600)
        o = cfg["outbounds"][0]["streamSettings"]
        print(f"конфиг: {out} (vless → {cfg['outbounds'][0]['settings']['vnext'][0]['address']}, "
              f"{o['network']}/{o['security']}, http 127.0.0.1:{a.http_port}, socks 127.0.0.1:{a.socks_port})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
