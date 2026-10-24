"""État du système pour les parcours de l'administration (ADR 0090).

    deploy/scripts/e2e.sh system healthy            # tout va bien
    deploy/scripts/e2e.sh system missing-heartbeat  # le worker ne bat plus

L'API des parcours tourne sans worker, sans beat ni relais : laissée telle quelle, elle
est toujours en panne. `healthy` écrit ce que ces processus écriraient (battements, tic
de beat, une exécution réussie par tâche, plus un échec ancien pour l'historique) et
marque publiés les événements que le relais aurait publiés. `missing-heartbeat` retire
le battement du worker. Jamais ailleurs que sur `coges_e2e` et un Redis local :
`e2e.sh` l'a vérifié avant de lancer ce module, et on le revérifie ici.
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

from app.core import heartbeat
from app.core.config import get_settings
from app.workers.beat import JOB_FRESHNESS, REBUILD_STOCK

HOST = "parcours-e2e"
E2E_DB = "/coges_e2e"


def _engine_url() -> str:
    url = get_settings().database_url_owner or ""
    local = "@localhost" in url or "@127.0.0.1" in url
    if not (url.endswith(E2E_DB) and local):
        sys.exit("system_state : seulement sur coges_e2e, en local")
    return url


def healthy() -> None:
    client = heartbeat.redis_client()
    for component in heartbeat.COMPONENTS:
        heartbeat.beat(client, component, HOST)
    heartbeat.record_beat_tick(client)
    engine = create_engine(_engine_url())
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE coges_ops"))
            connection.execute(text("DELETE FROM job_runs"))
            # Un échec il y a trois heures, rattrapé depuis : l'historique en montre un.
            connection.execute(
                text(
                    "INSERT INTO job_runs (job, status, started_at, finished_at, error) "
                    "VALUES (:job, 'failed', now() - interval '3 hours', "
                    "now() - interval '3 hours', 'OperationalError (08006)')"
                ),
                {"job": REBUILD_STOCK},
            )
            for job in JOB_FRESHNESS:
                connection.execute(
                    text(
                        "INSERT INTO job_runs (job, status, started_at, finished_at) "
                        "VALUES (:job, 'ok', now() - interval '1 hour', now() - interval '1 hour')"
                    ),
                    {"job": job},
                )
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE coges_bus"))
            connection.execute(
                text("UPDATE business_events SET published_at = now() WHERE published_at IS NULL")
            )
    finally:
        engine.dispose()


def missing_heartbeat() -> None:
    _engine_url()
    heartbeat.redis_client().delete(heartbeat.heartbeat_key("worker", HOST))


if __name__ == "__main__":
    actions = {"healthy": healthy, "missing-heartbeat": missing_heartbeat}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        sys.exit(f"usage : system_state {'|'.join(actions)}")
    actions[sys.argv[1]]()
