"""État du système pour les parcours de l'administration (ADR 0090).

    deploy/scripts/e2e.sh system healthy            # tout va bien
    deploy/scripts/e2e.sh system missing-heartbeat  # le worker ne bat plus
    deploy/scripts/e2e.sh system build-exports      # produit les exports en attente
    deploy/scripts/e2e.sh system legal-stale <e-mail>   # acceptation d'une ancienne version
    deploy/scripts/e2e.sh system signup-link <e-mail>   # le lien qu'aurait envoyé le worker

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


def build_exports() -> None:
    """Produit les exports en attente, comme le worker (ADR 0114) : les parcours tournent
    sans worker, et l'export PDF des ventes doit arriver dans Réglages → Fichiers."""
    from app.core.tenancy import TenantContext, tenant_transaction
    from app.modules.importexport import service as importexport_service
    from app.workers.tasks import exports as export_tasks
    from app.workers.tenants import each_company

    _engine_url()
    for company_id in each_company():
        ctx = TenantContext.bootstrap(company_id)
        with tenant_transaction(ctx) as session:
            pending = importexport_service.pending_export_ids(session, ctx)
            requested_by = importexport_service.requesters(session, ctx, pending)
        for export_id in pending:
            export_tasks.build_sales(
                company_id=str(company_id),
                user_id=str(requested_by[export_id]),
                export_id=str(export_id),
            )


def legal_stale(email: str) -> None:
    """Le compte `email` n'a accepté qu'une **ancienne** version des textes légaux (ADR
    0117) : ce que voit tout le monde le jour où `LEGAL_VERSION` change. La constante ne se
    change pas sous une API qui tourne ; la version acceptée, si."""
    engine = create_engine(_engine_url())
    try:
        with engine.begin() as connection:
            # Le propriétaire est soumis à la RLS FORCE : levée le temps de cette ligne.
            connection.execute(text("ALTER TABLE users NO FORCE ROW LEVEL SECURITY"))
            updated = connection.execute(
                text(
                    "UPDATE users SET legal_accepted_version = '2000-01-01', "
                    "legal_accepted_at = now() WHERE email = :email AND deleted_at IS NULL"
                ),
                {"email": email},
            ).rowcount
            connection.execute(text("ALTER TABLE users FORCE ROW LEVEL SECURITY"))
    finally:
        engine.dispose()
    if updated != 1:
        sys.exit(f"system_state : aucun compte unique pour {email}")


def signup_link(email: str) -> None:
    """Tire le jeton d'une demande en attente comme le worker (ADR 0118) et imprime le
    lien : les parcours tournent sans worker ni SMTP."""
    from uuid import UUID

    from app.core.tenancy import TenantContext, tenant_transaction
    from app.modules.signup import repository, service

    _engine_url()
    with tenant_transaction(TenantContext.bootstrap(UUID(int=0))) as session:
        request_id = repository.resend_target(session, email)
    if request_id is None:
        sys.exit(f"system_state : aucune demande en attente pour {email}")
    issued = service.issue_verification(request_id)
    if issued is None:
        sys.exit(f"system_state : aucun lien possible pour {email}")
    print(service.verification_link(issued[0]))


if __name__ == "__main__":
    actions = {
        "healthy": healthy,
        "missing-heartbeat": missing_heartbeat,
        "build-exports": build_exports,
    }
    if len(sys.argv) == 3 and sys.argv[1] == "legal-stale":
        legal_stale(sys.argv[2])
        sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "signup-link":
        signup_link(sys.argv[2])
        sys.exit(0)
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        sys.exit(f"usage : system_state {'|'.join(actions)}|legal-stale <e-mail>")
    actions[sys.argv[1]]()
