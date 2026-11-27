"""Single-owner HTTP boundary. HTTPS is terminated by an explicitly private proxy.

The supported launcher always binds loopback and disables forwarded-header trust.
No identity from the proxy, forwarded headers, query strings or browser storage.
Local files and local OS users are trusted; this is not a multi-tenant sandbox.
"""
import base64
import binascii
import hashlib
import hmac
import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from . import settings as cfg

MAX_BODY = 16 * 1024
MAX_QUERY = 4096
MAX_HEADER = 8192
_RANGE = re.compile(rb"bytes=(?:[0-9]{1,20}-[0-9]{0,20}|-[0-9]{1,20})")
PRIVATE_HEADERS = {
    b"cache-control": b"no-store, private",
    b"pragma": b"no-cache",
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"content-security-policy": (
        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        b"img-src 'self' data:; media-src 'self'; connect-src 'self'; "
        b"frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    ),
}


def _one(headers, key):
    values = [value for name, value in headers if name.lower() == key]
    if len(values) > 1:
        raise ValueError("duplicate header")
    return values[0] if values else b""


def _owner(authorization, digest):
    if not authorization.startswith(b"Basic ") or len(authorization) > 512:
        return False
    try:
        user, password = base64.b64decode(authorization[6:], validate=True).split(b":", 1)
    except (ValueError, binascii.Error):
        return False
    # Provision a random high-entropy password, not a human-memorable password.
    actual = hashlib.sha256(password).hexdigest()
    return hmac.compare_digest(actual, digest) and hmac.compare_digest(user, b"owner")


class AccessBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        s = cfg.settings
        private = s.private_origin is not None
        headers = scope.get("headers", [])
        started = False

        async def secured_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                if private:
                    message = dict(message)
                    message["headers"] = [(k, v) for k, v in message.get("headers", [])
                                          if k.lower() not in PRIVATE_HEADERS]
                    message["headers"].extend(PRIVATE_HEADERS.items())
            await send(message)

        async def deny(status, detail, extra=None):
            await JSONResponse({"detail": detail}, status_code=status, headers=extra)(
                scope, receive, secured_send)

        try:
            if len(scope.get("query_string", b"")) > MAX_QUERY or any(
                len(k) + len(v) > MAX_HEADER for k, v in headers
            ):
                await deny(400, "request too large")
                return
            host = _one(headers, b"host").decode("ascii")
            origin = _one(headers, b"origin").decode("ascii")
            fetch_site = _one(headers, b"sec-fetch-site")
            method = scope.get("method", "")
            if private:
                allowed_host = urlsplit(s.private_origin).netloc
                # Actual socket peer (launcher disables proxy_headers); never X-Forwarded-For.
                if (scope.get("client") or ("", 0))[0] not in ("127.0.0.1", "::1"):
                    await deny(403, "private proxy required")
                    return
                if host != allowed_host:
                    await deny(403, "host denied")
                    return
                if not _owner(_one(headers, b"authorization"), s.owner_digest.get_secret_value()):
                    await deny(401, "owner authentication required",
                               {"WWW-Authenticate": 'Basic realm="Autoreels", charset="UTF-8"'})
                    return
                if (origin and origin != s.private_origin) or fetch_site in (b"cross-site", b"same-site"):
                    await deny(403, "origin denied")
                    return
                if method not in ("GET", "HEAD") and origin != s.private_origin:
                    await deny(403, "origin required")
                    return
            else:
                # Preserve loopback + Vite development workflow, reject DNS rebinding.
                allowed = {f"{h}:{port}" for h in ("localhost", "127.0.0.1")
                           for port in (s.port, 5173)}
                if host not in allowed:
                    await deny(403, "host denied")
                    return
                if (origin and origin not in {"http://" + h for h in allowed}) or fetch_site == b"cross-site":
                    await deny(403, "origin denied")
                    return
            if method not in ("GET", "HEAD", "PUT"):
                await deny(405, "method denied")
                return
            # Private playback supports only single byte ranges, including suffix ranges.
            if private:
                range_header = _one(headers, b"range")
                if range_header and not _RANGE.fullmatch(range_header):
                    await deny(416, "unsupported byte range")
                    return
            if method == "PUT":
                if _one(headers, b"content-type").split(b";", 1)[0].strip().lower() != b"application/json":
                    await deny(415, "JSON required")
                    return
                length = _one(headers, b"content-length")
                if length and (not length.isdigit() or len(length) > 8 or int(length) > MAX_BODY):
                    await deny(413, "body too large")
                    return
                # Bound actual bytes, including chunked requests. Replay only to downstream.
                body = bytearray()
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    body.extend(event.get("body", b""))
                    if len(body) > MAX_BODY:
                        await deny(413, "body too large")
                        return
                    if not event.get("more_body", False):
                        break
                original_receive = receive
                sent = False

                async def replay():
                    nonlocal sent
                    if not sent:
                        sent = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await original_receive()
                receive = replay
        except (ValueError, UnicodeError):
            await deny(400, "invalid request")
            return

        try:
            await self.app(scope, receive, secured_send)
        except Exception:
            if not private:
                raise
            # Avoid leaking paths or request data via error bodies/logs. If a
            # stream has started, terminate it (never pretend truncated data is complete).
            if started:
                raise RuntimeError("private response interrupted") from None
            await deny(500, "private request failed")
