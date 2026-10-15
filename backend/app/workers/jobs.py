"""Trace des tâches planifiées dans `job_runs` (ADR 0077).

`@tracked_job` se pose sous `@celery_app.task`, sur chaque tâche de `beat.py` et sur
chaque sous-tâche par entreprise. Il écrit :

1. une ligne `running`, **validée seule** avant la tâche : un worker tué en cours de
   route laisse cette ligne, que la lecture compte comme un échec passé le délai
   maximal d'une tâche ;
2. `ok` ou `failed` à la fin, dans une seconde transaction, indépendante de celle de
   la tâche : un ROLLBACK de la tâche n'efface pas la trace de son échec.

L'erreur gardée est le **nom de la classe** d'exception et le SQLSTATE, jamais le
message, qui peut citer un nom de client ou un montant.

Puis il envoie le ping « homme mort » (`pings.py`) : succès à la fin d'un éventail,
échec dès qu'une sous-tâche échoue (`ping_as` désigne l'éventail parent).

La trace ne fait jamais échouer la tâche : si la base refuse l'écriture, l'incident est
journalisé et la tâche s'exécute quand même.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable, Mapping
from typing import Any, ParamSpec, TypeVar
from uuid import UUID

from sqlalchemy import text

from app.core.errors import sqlstate
from app.core.tenancy import TenantContext, tenant_transaction
from app.workers import pings

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

#: Les fonctions `SECURITY DEFINER` de `coges_ops` : le rôle applicatif n'a aucun
#: privilège sur `job_runs` (révision 0021).
_START = text("SELECT job_run_start(:job, CAST(:company_id AS uuid))")
_FINISH = text("SELECT job_run_finish(:id, :status, :error)")

#: Contexte des écritures de plate-forme : aucune entreprise (comme les partitions).
_PLATFORM = TenantContext.bootstrap(UUID(int=0))


def company_id_of(
    signature: inspect.Signature, args: tuple[Any, ...], kwargs: Mapping[str, Any]
) -> UUID | None:
    """Le `company_id` d'un appel de tâche, s'il en porte un et s'il est valide."""
    value = kwargs.get("company_id")
    if value is None and "company_id" in signature.parameters:
        try:
            value = signature.bind_partial(*args, **kwargs).arguments.get("company_id")
        except TypeError:
            value = None
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        return None


def describe(exc: BaseException) -> str:
    """Résumé d'une erreur, sans aucune donnée : la classe, et le SQLSTATE s'il existe."""
    code = sqlstate(exc)
    name = type(exc).__name__
    return f"{name} (SQLSTATE {code})" if code else name


def _start(job: str, company_id: UUID | None) -> int | None:
    try:
        with tenant_transaction(_PLATFORM) as session:
            run_id = session.execute(
                _START, {"job": job, "company_id": str(company_id) if company_id else None}
            ).scalar_one()
        return int(run_id)
    except Exception:
        logger.warning("Trace de tâche impossible à ouvrir", extra={"job": job}, exc_info=True)
        return None


def _finish(run_id: int | None, job: str, status: str, error: str | None) -> None:
    if run_id is None:
        return
    try:
        with tenant_transaction(_PLATFORM) as session:
            session.execute(_FINISH, {"id": run_id, "status": status, "error": error})
    except Exception:
        logger.warning("Trace de tâche impossible à clore", extra={"job": job}, exc_info=True)


def tracked_job(
    name: str, *, ping_as: str | None = None
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Trace la tâche `name` dans `job_runs`, puis pingue.

    Sans `ping_as`, la tâche pingue son propre nom, en succès comme en échec. Avec
    `ping_as`, c'est une sous-tâche : elle ne pingue que son échec, au nom de son
    éventail — le succès d'une entreprise ne dit rien des autres.
    """

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            run_id = _start(name, company_id_of(signature, args, kwargs))
            try:
                result = function(*args, **kwargs)
            except Exception as exc:
                _finish(run_id, name, "failed", describe(exc))
                pings.ping(ping_as or name, ok=False)
                raise
            _finish(run_id, name, "ok", None)
            if ping_as is None:
                pings.ping(name, ok=True)
            return result

        return wrapper

    return decorate
