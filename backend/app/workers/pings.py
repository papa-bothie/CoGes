"""Pings « homme mort » vers un service de surveillance externe (ADR 0077).

`COGES_JOB_PING_URLS` associe un nom de tâche à une URL. À la fin de la tâche :

* succès : `GET <url>` ;
* échec  : `GET <url>/fail`.

C'est le protocole de Healthchecks.io. Pour Sentry Crons, dont l'URL de check-in
porte le statut en paramètre (`…?status=ok`), écrire `{status}` dans l'URL : il est
remplacé par `ok` ou `error`, et rien n'est ajouté au chemin.

Le service externe alerte de lui-même quand un ping attendu **n'arrive pas** : c'est
ce qui couvre la panne qu'aucun code ne peut signaler, celle où rien ne tourne.

Aucune donnée ne part : pas de corps, pas de paramètre ajouté. L'URL est un secret
(elle suffit à pinguer) : elle n'est jamais journalisée. Un ping ne fait jamais
échouer une tâche, et son délai est borné à 5 s.
"""

from __future__ import annotations

import logging
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0
STATUS_PLACEHOLDER = "{status}"


def ping_target(url: str, *, ok: bool) -> str:
    """URL réellement appelée pour ce résultat."""
    if STATUS_PLACEHOLDER in url:
        return url.replace(STATUS_PLACEHOLDER, "ok" if ok else "error")
    return url if ok else url.rstrip("/") + "/fail"


def _open(url: str) -> None:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "coges-worker"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):  # noqa: S310
        pass


def ping(
    job: str,
    *,
    ok: bool,
    urls: Mapping[str, str] | None = None,
    opener: Callable[[str], Any] | None = None,
) -> bool:
    """Pingue l'URL de `job`, si elle existe. Rend `True` si le ping est parti."""
    url = (get_settings().job_ping_urls if urls is None else urls).get(job)
    if not url:
        return False
    try:
        (opener or _open)(ping_target(url, ok=ok))
    except Exception as exc:
        logger.warning(
            "Ping de surveillance impossible",
            extra={"job": job, "ok": ok, "error": type(exc).__name__},
        )
        return False
    return True
