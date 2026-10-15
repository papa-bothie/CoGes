"""Sonde de santé d'un conteneur de la zone B (ADR 0077).

    python -m app.workers.health worker|beat|relay

Sort en 0 si le battement de ce composant, **sur cet hôte**, a moins de 90 s ; en 1
sinon. Pour le worker, il faut en plus qu'il réponde à `celery inspect ping` : un
processus principal qui bat mais ne répond plus ne consomme plus rien.

C'est le `healthcheck` de `deploy/docker-compose.worker.yml` ; `autoheal` relance le
conteneur après trois échecs.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import redis

from app.core import heartbeat

#: Délai laissé au worker pour répondre au ping de contrôle.
PING_TIMEOUT_SECONDS = 5.0


def _celery_ping(host: str) -> bool:
    from app.workers.celery_app import celery_app  # noqa: PLC0415

    replies = celery_app.control.inspect(
        destination=[f"celery@{host}"], timeout=PING_TIMEOUT_SECONDS
    ).ping()
    return bool(replies)


def check(
    component: str,
    *,
    host: str | None = None,
    client_factory: Callable[[], redis.Redis] | None = None,
    celery_ping: Callable[[str], bool] = _celery_ping,
) -> tuple[bool, str]:
    """Rend (sain, raison). Ne lève jamais : une sonde qui plante est une sonde en échec."""
    if component not in heartbeat.COMPONENTS:
        return False, f"composant inconnu : {component}"
    where = host or heartbeat.hostname()
    try:
        client = (client_factory or heartbeat.redis_client)()
        age = heartbeat.age_seconds(client, component, where)
    except Exception as exc:
        return False, f"Redis injoignable ({type(exc).__name__})"
    if age is None:
        return False, "aucun battement"
    if age >= heartbeat.FRESH_SECONDS:
        return False, f"battement vieux de {age:.0f} s"
    if component == "worker":
        try:
            if not celery_ping(where):
                return False, "le worker ne répond pas au ping"
        except Exception as exc:
            return False, f"ping impossible ({type(exc).__name__})"
    return True, f"battement il y a {age:.0f} s"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage : python -m app.workers.health worker|beat|relay", file=sys.stderr)
        return 2
    healthy, reason = check(args[0])
    print(f"{args[0]} : {'ok' if healthy else 'KO'} — {reason}")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
