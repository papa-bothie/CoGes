"""Cloudinary : déposer, supprimer et lister des images, par httpx (ADR 0121).

Trois appels de l'API publique, sans SDK :

- **déposer** (`POST /v1_1/<cloud>/image/upload`) et **supprimer**
  (`POST /v1_1/<cloud>/image/destroy`) : requêtes signées, SHA-256 des paramètres triés
  suivis du secret (« Authentication signatures » de la documentation Cloudinary) ;
- **lister** un dossier (`GET /v1_1/<cloud>/resources/image/upload?prefix=`, API Admin) :
  authentification de base, clé et secret.

Le secret ne sort jamais du serveur : ni dans une réponse de l'API CoGes, ni vers le
navigateur, qui ne parle jamais à l'API Cloudinary (il lit seulement les images
publiques de `res.cloudinary.com`).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

#: Hôte des images servies au navigateur, seul ajouté à `img-src` (CSP).
DELIVERY_HOST = "https://res.cloudinary.com"


class CloudinaryError(Exception):
    """Cloudinary injoignable ou en refus. Le message ne porte aucun secret."""


@dataclass(frozen=True, slots=True)
class CloudinaryAccount:
    cloud_name: str
    api_key: str
    api_secret: str
    api_base: str = "https://api.cloudinary.com"

    def url(self, path: str) -> str:
        return f"{self.api_base.rstrip('/')}/v1_1/{self.cloud_name}/{path}"


@dataclass(frozen=True, slots=True)
class UploadedImage:
    public_id: str
    version: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class StoredImage:
    public_id: str
    created_at: datetime


def signature(params: Mapping[str, str], secret: str) -> str:
    """Signature Cloudinary : `k=v` triés, joints par `&`, suivis du secret, en SHA-256."""
    payload = "&".join(f"{key}={params[key]}" for key in sorted(params) if params[key] != "")
    return hashlib.sha256((payload + secret).encode()).hexdigest()


def _signed(account: CloudinaryAccount, params: dict[str, str]) -> dict[str, str]:
    params = {**params, "timestamp": str(int(time.time()))}
    return {
        **params,
        "api_key": account.api_key,
        "signature": signature(params, account.api_secret),
        "signature_algorithm": "sha256",
    }


def _json(response: httpx.Response, action: str) -> dict[str, Any]:
    if response.status_code >= 400:
        raise CloudinaryError(f"Cloudinary a refusé {action} (HTTP {response.status_code}).")
    try:
        body = response.json()
    except ValueError as exc:
        raise CloudinaryError(f"Réponse illisible de Cloudinary ({action}).") from exc
    if not isinstance(body, dict):
        raise CloudinaryError(f"Réponse inattendue de Cloudinary ({action}).")
    return body


def upload(
    account: CloudinaryAccount, content: bytes, *, public_id: str, client: httpx.Client
) -> UploadedImage:
    """Dépose une image sous `public_id` (jamais écrasée : l'identifiant est neuf)."""
    data = _signed(account, {"public_id": public_id, "overwrite": "false"})
    try:
        response = client.post(
            account.url("image/upload"),
            data=data,
            files={"file": ("photo.jpg", content, "image/jpeg")},
        )
    except httpx.HTTPError as exc:
        raise CloudinaryError("Cloudinary injoignable (dépôt).") from exc
    body = _json(response, "le dépôt")
    try:
        return UploadedImage(
            public_id=str(body["public_id"]),
            version=int(body["version"]),
            width=int(body["width"]),
            height=int(body["height"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CloudinaryError("Réponse incomplète de Cloudinary (dépôt).") from exc


def destroy(account: CloudinaryAccount, public_id: str, *, client: httpx.Client) -> None:
    """Supprime une image. Une image déjà absente compte comme supprimée."""
    data = _signed(account, {"public_id": public_id, "invalidate": "true"})
    try:
        response = client.post(account.url("image/destroy"), data=data)
    except httpx.HTTPError as exc:
        raise CloudinaryError("Cloudinary injoignable (suppression).") from exc
    result = _json(response, "la suppression").get("result")
    if result not in ("ok", "not found"):
        raise CloudinaryError(f"Suppression refusée par Cloudinary ({result}).")


def list_folder(
    account: CloudinaryAccount, prefix: str, *, client: httpx.Client
) -> list[StoredImage]:
    """Toutes les images dont l'identifiant commence par `prefix` (pages de 500)."""
    found: list[StoredImage] = []
    cursor: str | None = None
    while True:
        params = {"prefix": prefix, "max_results": "500", "type": "upload"}
        if cursor:
            params["next_cursor"] = cursor
        try:
            response = client.get(
                account.url("resources/image/upload"),
                params=params,
                auth=(account.api_key, account.api_secret),
            )
        except httpx.HTTPError as exc:
            raise CloudinaryError("Cloudinary injoignable (liste).") from exc
        body = _json(response, "la liste")
        for item in body.get("resources", []):
            try:
                created = datetime.fromisoformat(str(item["created_at"]).replace("Z", "+00:00"))
                found.append(StoredImage(public_id=str(item["public_id"]), created_at=created))
            except (KeyError, ValueError):
                continue
        cursor = body.get("next_cursor") or None
        if cursor is None:
            return found
