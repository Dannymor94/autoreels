"""M214b: a vless:// line → an Xray config (a local proxy for gamebox); the key is read from a file, never printed."""
from __future__ import annotations

import importlib.util
import json

import pytest

URI = ("vless://11111111-2222-3333-4444-555555555555@example.org:443?encryption=none&security=reality"
       "&sni=example.org&fp=chrome&pbk=PUBLICKEY&sid=abcd1234&type=xhttp&path=%2Fsecret&mode=auto#TEST")


def _tool():
    spec = importlib.util.spec_from_file_location("vless2xray", "tools/vless2xray.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reality_xhttp_with_the_owners_direct_rules():
    t = _tool()
    c = t.config(URI)
    out = c["outbounds"][0]
    assert out["protocol"] == "vless" and out["settings"]["vnext"][0]["address"] == "example.org"
    assert out["settings"]["vnext"][0]["users"][0] == {"id": "11111111-2222-3333-4444-555555555555", "encryption": "none"}
    s = out["streamSettings"]
    assert s["network"] == "xhttp" and s["security"] == "reality"
    assert s["realitySettings"] == {"serverName": "example.org", "fingerprint": "chrome", "publicKey": "PUBLICKEY",
                                    "shortId": "abcd1234", "spiderX": ""}
    assert s["xhttpSettings"] == {"path": "/secret", "mode": "auto"}
    assert [i["port"] for i in c["inbounds"]] == [10808, 10809] and all(i["listen"] == "127.0.0.1" for i in c["inbounds"])
    rules = c["routing"]["rules"]
    assert rules[0]["domain"] == ["domain:ru", "domain:su", "domain:xn--p1ai", "geosite:category-ru"]
    assert rules[1]["ip"] == ["geoip:ru", "geoip:private"] and all(r["outboundTag"] == "direct" for r in rules)


def test_other_transports_and_errors():
    t = _tool()
    ws = t.config("vless://id@h:8443?security=tls&sni=s&type=ws&path=%2Fw&host=hh")
    assert ws["outbounds"][0]["streamSettings"]["wsSettings"] == {"path": "/w", "headers": {"Host": "hh"}}
    assert ws["outbounds"][0]["settings"]["vnext"][0]["port"] == 8443
    assert t.config("vless://id@h?type=tcp")["outbounds"][0]["streamSettings"]["network"] == "tcp"
    with pytest.raises(ValueError):
        t.parse("vmess://x")
    with pytest.raises(ValueError):
        t.config("vless://id@h?type=quic")
    assert t.config(URI, direct_ru=False)["routing"]["rules"] == []


def test_the_key_file_to_a_private_config_without_printing_the_key(tmp_path, capsys):
    t = _tool()
    key = tmp_path / "vless.txt"
    key.write_text("# мой ключ\n" + URI + "\n", encoding="utf-8")
    out = tmp_path / "x" / "config.json"
    assert t.main([str(key), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "11111111" not in printed and "PUBLICKEY" not in printed and "конфиг:" in printed
    assert json.loads(out.read_text(encoding="utf-8"))["outbounds"][0]["streamSettings"]["network"] == "xhttp"
    assert (out.stat().st_mode & 0o777) == 0o600
    bad = tmp_path / "bad.txt"
    bad.write_text("nothing\n", encoding="utf-8")
    assert t.main([str(bad)]) == 1
