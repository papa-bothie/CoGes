"""Test de fumée post-déploiement : santé, connexion, tableau de bord.

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
    bypass = os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET")
    if bypass:
        headers["x-vercel-protection-bypass"] = bypass
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


def main() -> int:
    base = os.environ["COGES_SMOKE_URL"].rstrip("/") + "/api/v1"
    status, payload = _call("GET", f"{base}/health")
    if status != 200 or payload != {"status": "ok"}:
        print(f"ÉCHEC santé : {payload}", file=sys.stderr)
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
