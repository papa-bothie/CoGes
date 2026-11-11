"""Web Push : chiffrer, signer et poster une notification (ADR 0120).

Le standard en trois morceaux, sans bibliothèque cliente de plus :

- **chiffrement** (RFC 8291, `aes128gcm`) par `http_ece`, pour l'appareil seul : le
  service de push du navigateur transporte un message qu'il ne sait pas lire ;
- **signature VAPID** (RFC 8292) par `py_vapid` : le service sait que le message vient
  de notre serveur, et notre clé privée ne quitte jamais le serveur ;
- **envoi** par `httpx`, déjà utilisé par l'API.

Une adresse d'abonnement vient du navigateur, donc du client : le worker ne poste
**que** chez les services de push connus (`push_host_allowed`), jamais vers une adresse
quelconque qu'un client aurait fournie (requête forgée côté serveur).
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import http_ece  # type: ignore[import-untyped]
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02  # type: ignore[import-untyped]

#: Services de push des navigateurs : Chrome et Android (FCM), Firefox, Safari et iPhone,
#: Edge. Un sous-domaine compte (`*.push.apple.com`, `*.notify.windows.com`).
PUSH_HOSTS: tuple[str, ...] = (
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
)

#: Durée de vie d'une notification chez le service de push : passé ce délai, un téléphone
#: resté éteint ne la reçoit plus (une alerte de stock vieille d'un jour ne sert à rien).
DEFAULT_TTL_SECONDS = 12 * 3600

#: Le jeton VAPID vaut 12 h : sous la limite de 24 h de la RFC 8292.
VAPID_TOKEN_SECONDS = 12 * 3600


def b64url_decode(value: str) -> bytes | None:
    """Base64url avec ou sans remplissage ; `None` si ce n'en est pas."""
    text = value.strip()
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        return None


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def public_key_of(private_raw: bytes) -> bytes:
    """Clé publique (point non compressé, 65 octets) d'une clé privée P-256 brute."""
    key = ec.derive_private_key(int.from_bytes(private_raw, "big"), ec.SECP256R1())
    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def vapid_problem(public_key: str, private_key: str, subject: str) -> str | None:
    """Ce qui ne va pas dans une paire VAPID posée, ou `None`. Message sans secret."""
    private_raw = b64url_decode(private_key)
    if private_raw is None or len(private_raw) != 32:
        return "COGES_VAPID_PRIVATE_KEY : 32 octets en base64url (clé privée P-256 brute)."
    public_raw = b64url_decode(public_key)
    if public_raw is None or len(public_raw) != 65 or public_raw[0] != 4:
        return "COGES_VAPID_PUBLIC_KEY : 65 octets en base64url (point P-256 non compressé)."
    try:
        derived = public_key_of(private_raw)
    except ValueError:
        return "COGES_VAPID_PRIVATE_KEY n'est pas une clé P-256 valable."
    if derived != public_raw:
        return "COGES_VAPID_PUBLIC_KEY ne correspond pas à COGES_VAPID_PRIVATE_KEY."
    if not (subject.startswith("mailto:") or subject.startswith("https://")):
        return "COGES_VAPID_SUBJECT : « mailto:adresse » ou une adresse https://."
    return None


def generate_vapid_keys() -> tuple[str, str]:
    """Une paire neuve (publique, privée), en base64url : ce que le runbook fait poser."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    return b64url_encode(public_key_of(private_raw)), b64url_encode(private_raw)


def push_host_allowed(endpoint: str) -> bool:
    """L'adresse est en HTTPS, chez un service de push connu, sans identifiants ni port."""
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in PUSH_HOSTS)


def subscription_keys_valid(p256dh: str, auth: str) -> bool:
    """Clé publique de l'appareil (65 octets, point non compressé) et secret de 16 octets."""
    public = b64url_decode(p256dh)
    secret = b64url_decode(auth)
    return (
        public is not None
        and len(public) == 65
        and public[0] == 4
        and secret is not None
        and len(secret) == 16
    )


@dataclass(frozen=True, slots=True)
class PushTarget:
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True, slots=True)
class PushResult:
    """`status` : code HTTP du service, ou `None` si le réseau a manqué."""

    status: int | None

    @property
    def delivered(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def gone(self) -> bool:
        """L'abonnement n'existe plus chez le service : on l'arrête (ADR 0120)."""
        return self.status in (404, 410)


def encrypt(payload: bytes, target: PushTarget) -> bytes:
    """Chiffre pour l'appareil (RFC 8291) : clé éphémère et sel neufs à chaque envoi."""
    receiver = b64url_decode(target.p256dh)
    secret = b64url_decode(target.auth)
    if receiver is None or secret is None:
        raise ValueError("Clés d'abonnement illisibles.")
    body: bytes = http_ece.encrypt(
        payload,
        salt=os.urandom(16),
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=receiver,
        auth_secret=secret,
        version="aes128gcm",
    )
    return body


def vapid_headers(endpoint: str, *, private_key: str, subject: str) -> dict[str, str]:
    """En-tête `Authorization: vapid t=…,k=…` pour l'origine du service de push."""
    parts = urlsplit(endpoint)
    signer = Vapid02.from_raw(private_key.strip().encode())
    claims: dict[str, Any] = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "sub": subject,
        "exp": int(time.time()) + VAPID_TOKEN_SECONDS,
    }
    signed: dict[str, str] = signer.sign(claims)
    return signed


def send(
    target: PushTarget,
    message: dict[str, Any],
    *,
    private_key: str,
    subject: str,
    client: httpx.Client,
    ttl: int = DEFAULT_TTL_SECONDS,
    urgency: str = "normal",
) -> PushResult:
    """Poste une notification chiffrée. Jamais d'exception réseau : `status=None`."""
    if not push_host_allowed(target.endpoint):
        # Contrôlé à l'abonnement ; revérifié ici, au seul endroit qui poste.
        return PushResult(status=None)
    body = encrypt(json.dumps(message, ensure_ascii=False).encode(), target)
    headers = {
        **vapid_headers(target.endpoint, private_key=private_key, subject=subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": urgency,
    }
    try:
        response = client.post(target.endpoint, content=body, headers=headers)
    except httpx.HTTPError:
        return PushResult(status=None)
    return PushResult(status=response.status_code)
