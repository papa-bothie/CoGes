"""Sentry pour les erreurs, en plus des logs JSON (ADR 0042).

Inactif tant que `COGES_SENTRY_DSN` est absent : développement, CI et tests ne
contactent aucun service. Même module pour l'API (Vercel), le worker, beat et le
relais — seul le composant change dans les étiquettes.

Ce qui ne part **jamais** vers Sentry : en-têtes `Authorization` et `Cookie`, corps de
requête, adresse IP, e-mail (`send_default_pii=False`, puis `scrub_event`). Ce qui
part : l'identifiant de requête et le `company_id`, pour relier une erreur à la ligne
de log et à l'entreprise touchée sans rien exposer de ses données.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import sentry_sdk

from app.core.config import get_settings
from app.core.logging import request_id_var, scrub_text

logger = logging.getLogger(__name__)

#: En-têtes retirés de tout événement, quelle que soit leur casse.
SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "idempotency-key"})


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Retire secrets et données personnelles d'un événement avant l'envoi."""
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                name: value
                for name, value in headers.items()
                if name.lower() not in SENSITIVE_HEADERS
            }
        request.pop("cookies", None)
        request.pop("data", None)
        env = request.get("env")
        if isinstance(env, dict):
            env.pop("REMOTE_ADDR", None)
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {key: value for key, value in user.items() if key == "id"}
    # Messages d'exception : le détail SQL cite des valeurs (ADR 0088).
    if isinstance(event.get("message"), str):
        event["message"] = scrub_text(event["message"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict) and isinstance(logentry.get("message"), str):
        logentry["message"] = scrub_text(logentry["message"])
    exception = event.get("exception")
    if isinstance(exception, dict):
        for value in exception.get("values") or []:
            if isinstance(value, dict) and isinstance(value.get("value"), str):
                value["value"] = scrub_text(value["value"])
    request_id = request_id_var.get()
    if request_id:
        event.setdefault("tags", {})["request_id"] = request_id
    return event


def init_sentry(component: str, *, celery: bool = False) -> bool:
    """Initialise Sentry pour ce processus ; renvoie `False` sans DSN.

    `celery=True` pour le worker et beat : l'intégration Celery rapporte toute tâche qui
    échoue pour de bon — une tâche relancée par `self.retry` ne remonte qu'une fois ses
    tentatives épuisées (ADR 0077). Les moniteurs Crons de Sentry ne sont pas activés
    d'office : les pings sont configurés tâche par tâche (`COGES_JOB_PING_URLS`).
    """
    settings = get_settings()
    # Absent ou vide (`COGES_SENTRY_DSN=` dans un .env) : inactif.
    dsn = settings.sentry_dsn.get_secret_value() if settings.sentry_dsn else ""
    if not dsn:
        return False
    integrations: list[Any] = []
    if celery:
        from sentry_sdk.integrations.celery import CeleryIntegration  # noqa: PLC0415

        integrations.append(CeleryIntegration(monitor_beat_tasks=False))
    sentry_sdk.init(
        dsn=dsn,
        integrations=integrations,
        environment=settings.env,
        send_default_pii=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=scrub_event,  # type: ignore[arg-type]
    )
    # Portée globale : chaque tâche Celery ouvre sa propre portée, qui en hérite.
    sentry_sdk.get_global_scope().set_tag("component", component)
    logger.info("Sentry actif", extra={"component": component})
    return True


def tag_job(job: str, company_id: UUID | None) -> None:
    """Rattache les erreurs de la tâche courante à son nom et à son entreprise."""
    sentry_sdk.set_tag("job", job)
    if company_id is not None:
        tag_tenant(company_id)


def tag_tenant(company_id: UUID) -> None:
    """Rattache les erreurs de la requête courante à son entreprise (aucun effet sans DSN)."""
    sentry_sdk.set_tag("company_id", str(company_id))
