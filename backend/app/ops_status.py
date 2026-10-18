"""Bilan des workers dans le terminal (ADR 0077).

    make ops-status
    COGES_OPS_URL=https://coges-api.vercel.app make ops-status

Interroge `GET /api/v1/system/workers` avec `COGES_OPS_TOKEN` (lu dans `.env`) et
affiche le résultat. Sort en 0 si tout va bien, en 1 si l'API signale un problème,
en 2 si elle n'a pas pu répondre. Ce qu'il faut faire de chaque problème est écrit
dans `docs/runbooks/workers.md`.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from app.core.config import get_settings

DEFAULT_URL = "http://localhost:8000"
TIMEOUT_SECONDS = 15.0


def fetch(base_url: str, token: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(  # noqa: S310
        f"{base_url.rstrip('/')}/api/v1/system/workers",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return int(response.status), json.loads(response.read())
    except urllib.error.HTTPError as error:
        return int(error.code), json.loads(error.read() or b"{}")


def _age(seconds: float | None) -> str:
    if seconds is None:
        return "jamais"
    if seconds < 120:
        return f"{seconds:.0f} s"
    if seconds < 7200:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def render(body: dict[str, Any]) -> str:
    mark = {True: "ok ", False: "KO "}
    lines = [f"Bilan du {body['checked_at']} : {'tout va bien' if body['healthy'] else 'PROBLÈME'}"]
    lines.append("")
    lines.append("Battements")
    for component in body["components"]:
        hosts = ", ".join(
            f"{host['host']} ({_age(host['age_seconds'])})" for host in component["hosts"]
        )
        lines.append(f"  {mark[component['healthy']]} {component['component']:<7} {hosts or '—'}")
    lines.append(f"  tic de beat : {_age(body['beat_tick_age_seconds'])}")
    outbox = body["outbox"]
    if outbox:
        lines.append("")
        lines.append(
            f"Outbox  {mark[outbox['healthy'] and not outbox['dead_lettered']]} "
            f"{outbox['pending']} en attente, "
            f"retard {_age(outbox['lag_seconds'])} (seuil {_age(outbox['max_lag_seconds'])}), "
            f"{outbox['dead_lettered']} au rebut"
        )
    queue = body["queue"]["length"]
    lines.append(f"File Celery : {'?' if queue is None else queue} tâche(s) en attente")
    lines.append("")
    lines.append("Tâches planifiées")
    for job in body["jobs"]:
        companies = (
            f", entreprises {job['companies_ok']} ok / {job['companies_failed']} en échec"
            if job["companies_ok"] or job["companies_failed"]
            else ""
        )
        lines.append(
            f"  {mark[job['healthy']]} {job['job']:<38} {job['state']:<17}"
            f" dernière réussite : {job['last_ok_at'] or 'jamais'}{companies}"
        )
    if body["problems"]:
        lines.append("")
        lines.append("Problèmes (voir docs/runbooks/workers.md) :")
        lines.extend(f"  - {problem}" for problem in body["problems"])
    return "\n".join(lines)


def main() -> int:
    token = get_settings().ops_token
    if token is None or not token.get_secret_value():
        print("COGES_OPS_TOKEN est absent : rien à interroger.", file=sys.stderr)
        return 2
    base_url = os.environ.get("COGES_OPS_URL", DEFAULT_URL)
    try:
        status, body = fetch(base_url, token.get_secret_value())
    except (OSError, ValueError) as exc:
        print(f"{base_url} injoignable : {exc}", file=sys.stderr)
        return 2
    if status not in (200, 503):
        print(f"Réponse inattendue {status} : {json.dumps(body, ensure_ascii=False)}")
        return 2
    print(render(body))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
