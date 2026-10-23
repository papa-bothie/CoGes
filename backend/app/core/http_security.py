"""Garde-fous HTTP de l'API (ADR 0042), en middlewares ASGI purs.

* `BodySizeLimitMiddleware` — 413 au-delà du plafond, que la taille soit annoncée par
  `Content-Length` ou découverte en lisant le flux ;
* `IpRateLimitMiddleware`   — compteur par IP, et un compteur plus strict sur la
  connexion (le compteur par entreprise est posé après authentification, dans
  `app.core.deps`) ;
* `SecurityHeadersMiddleware` — en-têtes de sécurité sur toutes les réponses.

Écrits en ASGI pur plutôt qu'avec `BaseHTTPMiddleware` : il faut pouvoir couper un
corps de requête pendant sa lecture, ce que ce dernier ne permet pas proprement.
"""

from __future__ import annotations

import json
from typing import Any

from anyio import to_thread
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import rate_limit
from app.core.config import get_settings
from app.core.deps import raw_client_ip
from app.core.errors import CogesError, PayloadTooLargeError

API_PREFIX = "/api/v1"
IMPORTS_PREFIX = f"{API_PREFIX}/imports"
LOGIN_PATH = f"{API_PREFIX}/auth/login"
#: Les deux connexions, commerçante et administration (ADR 0089), partagent le plafond
#: bas par adresse IP.
LOGIN_PATHS = frozenset({LOGIN_PATH, f"{API_PREFIX}/platform/auth/login"})
DOCS_PATHS = (f"{API_PREFIX}/docs", f"{API_PREFIX}/openapi.json")


async def _send_error(send: Send, error: CogesError) -> None:
    body = json.dumps(error.to_payload()).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    headers.extend((name.lower().encode(), value.encode()) for name, value in error.headers.items())
    await send({"type": "http.response.start", "status": error.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    """Refuse un corps de requête plus grand que le plafond de sa route."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        path: str = scope["path"]
        limit = (
            settings.max_import_bytes
            if path.startswith(IMPORTS_PREFIX)
            else settings.max_body_bytes
        )
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _send_error(send, _too_large(limit))
            return

        if declared is not None:
            # Taille annoncée et sous le plafond : le serveur HTTP garantit qu'on ne
            # recevra pas davantage que `Content-Length`.
            await self.app(scope, receive, send)
            return

        # Corps sans taille annoncée (envoi par morceaux) : on le lit d'abord, en
        # s'arrêtant au premier octet de trop, puis on le rejoue à l'application. Le
        # plafond borne la mémoire ; couper pendant la lecture de FastAPI, lui, se
        # transformerait en 400 « corps illisible ».
        chunks: list[bytes] = []
        received = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            body = message.get("body", b"")
            received += len(body)
            if received > limit:
                await _send_error(send, _too_large(limit))
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def _too_large(limit: int) -> PayloadTooLargeError:
    return PayloadTooLargeError(
        f"La requête dépasse la taille maximale autorisée ({limit // 1024} Ko).",
        details={"max_bytes": limit},
    )


class IpRateLimitMiddleware:
    """Compteur par IP sur toute l'API, et compteur de connexion plus strict."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        ip = raw_client_ip(
            Headers(scope=scope).get("x-forwarded-for"),
            _Peer(client[0]) if client else None,
        )
        if ip:
            is_login = scope["path"] in LOGIN_PATHS and scope["method"] == "POST"
            try:
                # Redis est appelé en synchrone : hors de la boucle d'événements.
                await to_thread.run_sync(_hit_ip, ip, is_login)
            except CogesError as error:
                await _send_error(send, error)
                return
        await self.app(scope, receive, send)


def _hit_ip(ip: str, is_login: bool) -> None:
    rate_limit.hit_ip(ip)
    if is_login:
        rate_limit.hit_login(ip)


class _Peer:
    """Adaptateur minimal : `raw_client_ip` lit un attribut `host`."""

    def __init__(self, host: str) -> None:
        self.host = host


#: Une API JSON n'a rien à charger : CSP fermée. La documentation interactive, elle,
#: charge Swagger UI depuis un CDN — elle n'est servie que hors production.
_API_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware:
    """Ajoute les en-têtes de sécurité à chaque réponse HTTP."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        is_docs = scope["path"].startswith(DOCS_PATHS)
        extra: list[tuple[bytes, bytes]] = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"cross-origin-opener-policy", b"same-origin"),
        ]
        if not is_docs:
            extra.append((b"content-security-policy", _API_CSP.encode()))
        if settings.env in ("staging", "production"):
            extra.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[Any] = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers.extend(item for item in extra if item[0] not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
