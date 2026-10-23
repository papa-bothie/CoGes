"""Schémas du module System."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OutboxHealth(BaseModel):
    """État de l'outbox pour l'entreprise du contexte.

    Les trois compteurs se lisent ensemble : `pending` qui monte sans que `published`
    bouge signale un relais arrêté ; `dead_lettered` non nul signale des événements
    qu'aucune reprise ne rattrapera plus.
    """

    model_config = ConfigDict(extra="forbid")

    #: Événements écrits, pas encore publiés, et encore réclamables.
    pending: int
    #: Événements ayant épuisé leurs dix tentatives : plus aucune reprise automatique.
    dead_lettered: int
    #: Événements publiés depuis toujours — repère, pas une alerte.
    published: int
    #: Date du plus ancien événement en attente : c'est elle qui dit si le retard
    #: se compte en secondes ou en jours.
    oldest_pending_at: datetime | None
    #: Dernière publication observée.
    last_published_at: datetime | None


class HostPulse(BaseModel):
    """Un battement de cœur : l'hôte (identifiant de conteneur) et son âge."""

    model_config = ConfigDict(extra="forbid")

    host: str
    age_seconds: float


class ComponentHealth(BaseModel):
    """Worker, beat ou relais : sain si au moins un hôte a battu depuis moins de 90 s."""

    model_config = ConfigDict(extra="forbid")

    component: str
    healthy: bool
    hosts: list[HostPulse]


class OutboxLag(BaseModel):
    """Retard du relais, toutes entreprises confondues. Aucune donnée d'événement."""

    model_config = ConfigDict(extra="forbid")

    healthy: bool
    pending: int
    dead_lettered: int
    oldest_pending_at: datetime | None
    lag_seconds: float
    max_lag_seconds: int


class QueueDepth(BaseModel):
    """Tâches en attente dans la file Celery ; `None` si Redis n'a pas répondu."""

    model_config = ConfigDict(extra="forbid")

    name: str
    length: int | None


class JobHealth(BaseModel):
    """Dernière exécution d'une tâche planifiée, et ce qu'il faut en penser.

    `companies_failed` compte les entreprises dont la **dernière** exécution de la
    sous-tâche a échoué. Jamais de nom ni d'identifiant d'entreprise.
    """

    model_config = ConfigDict(extra="forbid")

    job: str
    healthy: bool
    #: `ok`, `never_ran`, `stale`, `failed` ou `companies_failed`.
    state: str
    window_hours: float
    last_status: str | None
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_ok_at: datetime | None
    companies_ok: int
    companies_failed: int


class WorkersHealth(BaseModel):
    """Bilan de la zone B (ADR 0077). Rendu en 200 si tout va bien, en 503 sinon.

    `problems` liste les causes en codes stables (`heartbeat_missing:beat`,
    `outbox_lagging`, `job_stale:reconcile.rebuild_stock_all`…) : c'est ce que lit
    le guide `docs/runbooks/workers.md`.
    """

    model_config = ConfigDict(extra="forbid")

    healthy: bool
    checked_at: datetime
    problems: list[str]
    components: list[ComponentHealth]
    beat_tick_age_seconds: float | None
    outbox: OutboxLag | None
    queue: QueueDepth
    jobs: list[JobHealth]


# ------------------------------------------- administration de la plateforme (ADR 0090)


class JobRun(BaseModel):
    """Une exécution de tâche planifiée. `per_company` dit si c'est la sous-tâche d'une
    entreprise, **jamais** laquelle. `error` : nom de classe et SQLSTATE, 200 caractères
    au plus (ADR 0077), jamais le message."""

    model_config = ConfigDict(extra="forbid")

    id: int
    job: str
    #: `ok`, `failed` ou `running` ; un `running` plus vieux que le délai d'une tâche
    #: est rendu `failed`, comme dans le bilan.
    status: str
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    per_company: bool


class JobRunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[JobRun]
    page: int
    page_size: int
    total: int


class DeadLetter(BaseModel):
    """Un événement au rebut : de quoi le rejouer à la main, rien de son contenu."""

    model_config = ConfigDict(extra="forbid")

    id: int
    event_type: str
    occurred_at: datetime
    attempts: int


class DeadLetterPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DeadLetter]
    page: int
    page_size: int
    total: int


class PlatformOutbox(BaseModel):
    """Retard du relais (le même calcul que le bilan) et liste du rebut."""

    model_config = ConfigDict(extra="forbid")

    lag: OutboxLag
    dead_letters: DeadLetterPage
