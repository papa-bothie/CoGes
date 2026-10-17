"""Test de fumée post-déploiement : santé complète, page de connexion, connexion, tableau de bord.

Vise le domaine public, à travers Caddy (ADR 0083) : `/api/v1/health/ready` (API,
PostgreSQL et Redis), `/login` (le front), puis une connexion et le tableau de bord.

Usage :
  COGES_SMOKE_URL=https://… COGES_SMOKE_SLUG=… COGES_SMOKE_EMAIL=… \\
  COGES_SMOKE_PASSWORD=… python deploy/scripts/smoke.py

Le compte de fumée est un gérant d'une entreprise dédiée, créée une fois par
`python -m app.cli create-company` : il ne touche jamais aux données d'un client.
Bibliothèque standard seulement.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _call(method: str, url: str, *, body: Any = None, token: str | None = None) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            status, payload = response.status, json.load(response)
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read().decode(errors="replace")
    elapsed = (time.perf_counter() - started) * 1000
    print(f"{method} {url} → {status} ({elapsed:.0f} ms)")
    return status, payload


def _login_page(url: str) -> bool:
    """Le front répond, derrière le même domaine que l'API."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            page = response.read().decode(errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        status, page = error.code, ""
    print(f"GET {url} → {status}")
    if status != 200 or "Connexion" not in page:
        print("ÉCHEC : la page de connexion n'est pas servie", file=sys.stderr)
        return False
    return True


def main() -> int:
    site = os.environ["COGES_SMOKE_URL"].rstrip("/")
    base = f"{site}/api/v1"
    status, payload = _call("GET", f"{base}/health/ready")
    if status != 200 or not isinstance(payload, dict) or payload.get("status") != "ok":
        print(f"ÉCHEC santé : {payload}", file=sys.stderr)
        return 1

    if not _login_page(f"{site}/login"):
        return 1

    status, payload = _call(
        "POST",
        f"{base}/auth/login",
        body={
            "company_slug": os.environ["COGES_SMOKE_SLUG"],
            "email": os.environ["COGES_SMOKE_EMAIL"],
            "password": os.environ["COGES_SMOKE_PASSWORD"],
        },
    )
    if status != 200:
        print(f"ÉCHEC connexion : {payload}", file=sys.stderr)
        return 1
    token = payload["access_token"]

    status, payload = _call("GET", f"{base}/dashboard", token=token)
    if status != 200:
        print(f"ÉCHEC tableau de bord : {payload}", file=sys.stderr)
        return 1
    print("Test de fumée : OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
