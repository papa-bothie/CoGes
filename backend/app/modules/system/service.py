"""Façade de services du module System. Lecture seule, sans effet de bord."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import redis
from sqlalchemy.orm import Session

from app.core import heartbeat
from app.core.config import get_settings
from app.core.errors import ValidationFailedError
from app.core.tenancy import TenantContext
from app.modules.system.repository import OutboxHealthRepository, PlatformHealthRepository
from app.modules.system.schemas import (
    ComponentHealth,
    DeadLetter,
    DeadLetterPage,
    HostPulse,
    JobHealth,
    JobRun,
    JobRunPage,
    OutboxHealth,
    OutboxLag,
    PlatformOutbox,
    QueueDepth,
    WorkersHealth,
)
from app.workers.beat import (
    BEAT_TICK_MAX_AGE,
    JOB_FRESHNESS,
    TASK_TIME_LIMIT_SECONDS,
    Freshness,
)

logger = logging.getLogger(__name__)

#: File Celery par défaut, sur le broker Redis.
CELERY_QUEUE = "celery"


def outbox_health(session: Session, ctx: TenantContext) -> OutboxHealth:
    """État de l'outbox de l'entreprise du contexte.

    `dead_lettered` compte les événements qui ont épuisé leurs tentatives. Le seuil
    vient de la configuration, mais il est aussi porté par un `CHECK` en base
    (`attempts <= 10`) : l'un peut être plus prudent que l'autre, jamais plus laxiste.
    """
    health = OutboxHealthRepository(session, ctx).health(
        max_attempts=get_settings().outbox_max_attempts
    )
    return OutboxHealth.model_validate(health)


def workers_health(
    session: Session,
    *,
    redis_factory: Callable[[], redis.Redis] | None = None,
    now: datetime | None = None,
) -> WorkersHealth:
    """Bilan de la zone B : battements, outbox, file Celery, tâches de nuit (ADR 0077).

    Malsain dès que l'un de ces cas se présente :

    * un composant n'a battu sur aucun hôte depuis 90 s ;
    * le plus vieil événement en attente dépasse `COGES_OPS_OUTBOX_MAX_LAG_SECONDS` ;
    * une tâche planifiée n'a pas réussi dans sa fenêtre (26 h ou 8 jours), sa
      dernière exécution a échoué, ou une entreprise a vu échouer sa sous-tâche ;
    * `system.beat_tick` n'a pas tourné depuis 15 min ;
    * un événement de l'outbox est au rebut (`outbox_dead_lettered:<nombre>`, ADR 0087).

    Le calcul se fait sur l'horloge réelle, jamais sur l'heure figée des lectures
    métier (`COGES_FROZEN_NOW`) : une panne n'attend pas la maquette.
    """
    current = now or datetime.now(UTC)
    problems: list[str] = []

    pulses: list[heartbeat.Pulse] = []
    tick_age: float | None = None
    queue_length: int | None = None
    try:
        client = (redis_factory or heartbeat.redis_client)()
        stamp = current.timestamp()
        pulses = heartbeat.read_pulses(client, now=stamp)
        tick_age = heartbeat.beat_tick_age(client, now=stamp)
        queue_length = int(cast(int, client.llen(CELERY_QUEUE)))
    except Exception:
        logger.warning("Redis injoignable pour le bilan des workers", exc_info=True)
        problems.append("redis_unreachable")

    components: list[ComponentHealth] = []
    for component in heartbeat.COMPONENTS:
        hosts = [pulse for pulse in pulses if pulse.component == component]
        healthy = any(pulse.fresh for pulse in hosts)
        if not healthy:
            problems.append(f"heartbeat_missing:{component}")
        components.append(
            ComponentHealth(
                component=component,
                healthy=healthy,
                hosts=[
                    HostPulse(host=pulse.host, age_seconds=round(pulse.age_seconds, 1))
                    for pulse in hosts
                ],
            )
        )
    if tick_age is None or tick_age > BEAT_TICK_MAX_AGE.total_seconds():
        problems.append("beat_tick_missing")

    repository = PlatformHealthRepository(session)
    outbox = _outbox_lag(repository, current)
    if not outbox.healthy:
        problems.append("outbox_lagging")
    # Le rebut ne repart jamais seul : il attend qu'on le rejoue à la main
    # (docs/runbooks/workers.md). Le taire, c'est perdre l'effet de l'événement.
    if outbox.dead_lettered:
        problems.append(f"outbox_dead_lettered:{outbox.dead_lettered}")

    runs = {
        cast(str, row["job"]): row
        for row in repository.job_runs_latest(stale_seconds=TASK_TIME_LIMIT_SECONDS)
    }
    jobs = [_job_health(job, freshness, runs, current) for job, freshness in JOB_FRESHNESS.items()]
    problems.extend(f"job_{job.state}:{job.job}" for job in jobs if not job.healthy)

    return WorkersHealth(
        healthy=not problems,
        checked_at=current,
        problems=problems,
        components=components,
        beat_tick_age_seconds=round(tick_age, 1) if tick_age is not None else None,
        outbox=outbox,
        queue=QueueDepth(name=CELERY_QUEUE, length=queue_length),
        jobs=jobs,
    )


def _outbox_lag(repository: PlatformHealthRepository, now: datetime) -> OutboxLag:
    """Retard du relais, toutes entreprises confondues : un seul calcul, pour le bilan
    et pour l'écran de l'administration."""
    max_lag = get_settings().ops_outbox_max_lag_seconds
    lag = repository.outbox_lag()
    oldest = cast(datetime | None, lag["oldest_pending_at"])
    lag_seconds = max(0.0, (now - oldest).total_seconds()) if oldest else 0.0
    return OutboxLag(
        healthy=lag_seconds <= max_lag,
        pending=cast(int, lag["pending"]),
        dead_lettered=cast(int, lag["dead_lettered"]),
        oldest_pending_at=oldest,
        lag_seconds=round(lag_seconds, 1),
        max_lag_seconds=max_lag,
    )


# ------------------------------------------- administration de la plateforme (ADR 0090)

#: Tâches dont l'historique se filtre : celles de beat et leurs sous-tâches par
#: entreprise. `system.beat_tick` n'y est pas : il vit dans Redis seulement.
KNOWN_JOBS: frozenset[str] = frozenset(JOB_FRESHNESS) | frozenset(
    freshness.per_company for freshness in JOB_FRESHNESS.values() if freshness.per_company
)


def job_runs_page(
    session: Session, *, job: str | None, status: str | None, page: int, page_size: int
) -> JobRunPage:
    """Historique des tâches sur 90 jours, le plus récent d'abord."""
    if job is not None and job not in KNOWN_JOBS:
        raise ValidationFailedError(
            "Tâche inconnue.", details={"job": job, "known": sorted(KNOWN_JOBS)}
        )
    items, total = PlatformHealthRepository(session).job_runs_history(
        job=job,
        status=status,
        stale_seconds=TASK_TIME_LIMIT_SECONDS,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return JobRunPage(
        items=[JobRun.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


def platform_outbox(
    session: Session, *, page: int, page_size: int, now: datetime | None = None
) -> PlatformOutbox:
    """Retard du relais et rebut à rejouer, sans contenu d'événement."""
    repository = PlatformHealthRepository(session)
    items, total = repository.dead_letters(limit=page_size, offset=(page - 1) * page_size)
    return PlatformOutbox(
        lag=_outbox_lag(repository, now or datetime.now(UTC)),
        dead_letters=DeadLetterPage(
            items=[DeadLetter.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        ),
    )


def _job_health(
    job: str,
    freshness: Freshness,
    runs: dict[str, dict[str, object]],
    now: datetime,
) -> JobHealth:
    row = runs.get(job)
    subtask = runs.get(freshness.per_company) if freshness.per_company else None
    last_ok_at = cast(datetime | None, row["last_ok_at"]) if row else None
    last_status = cast(str | None, row["last_status"]) if row else None
    companies_ok = cast(int, subtask["companies_ok"]) if subtask else 0
    companies_failed = cast(int, subtask["companies_failed"]) if subtask else 0

    if row is None:
        state = "never_ran"
    elif last_status == "failed":
        state = "failed"
    elif last_ok_at is None or now - last_ok_at > freshness.window:
        state = "stale"
    elif companies_failed:
        state = "companies_failed"
    else:
        state = "ok"
    return JobHealth(
        job=job,
        healthy=state == "ok",
        state=state,
        window_hours=freshness.window.total_seconds() / 3600,
        last_status=last_status,
        last_started_at=cast(datetime | None, row["last_started_at"]) if row else None,
        last_finished_at=cast(datetime | None, row["last_finished_at"]) if row else None,
        last_ok_at=last_ok_at,
        companies_ok=companies_ok,
        companies_failed=companies_failed,
    )
