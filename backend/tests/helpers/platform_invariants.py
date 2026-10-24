"""Contrôles croisés des statistiques de la plateforme (lot admin 5 ; ADR 0093).

Sur le modèle de `invariants.py` (lot C) : chaque contrôle rend la liste de ses violations
(vide = cohérent).

* entreprises par statut : la somme égale le total ;
* répartition par offre : chaque ligne égale ses trois colonnes, et la somme des lignes
  plus les entreprises sans abonnement égale le total ;
* le total égale celui que la base compte elle-même, entreprises supprimées exclues : le
  propriétaire passe par `coges_auth` (BYPASSRLS, `SELECT` sur `id`, `status`,
  `deleted_at`), hors des politiques qui servent l'administration.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.sql import text


def overview_violations(overview: dict[str, Any]) -> list[str]:
    """Cohérence interne d'une réponse de `GET /platform/stats/overview`."""
    violations: list[str] = []
    companies = overview["companies"]
    by_status = companies["trial"] + companies["active"] + companies["suspended"]
    if by_status != companies["total"]:
        violations.append(f"statuts {by_status} ≠ total {companies['total']}")
    plans_total = 0
    for plan in overview["plans"]:
        parts = plan["trial"] + plan["paying"] + plan["suspended"]
        if parts != plan["total"]:
            violations.append(f"offre {plan['code']} : {parts} ≠ {plan['total']}")
        plans_total += plan["total"]
    if plans_total + overview["without_subscription"] != companies["total"]:
        violations.append(
            f"offres {plans_total} + sans abonnement {overview['without_subscription']} "
            f"≠ total {companies['total']}"
        )
    return violations


def database_violations(owner_engine: Engine, overview: dict[str, Any]) -> list[str]:
    """Le total et les statuts de la réponse face au décompte de la base elle-même."""
    with owner_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE coges_auth"))
        rows = dict(
            connection.execute(
                text(
                    "SELECT status::text, count(*) FROM companies "
                    "WHERE deleted_at IS NULL GROUP BY status"
                )
            ).all()
        )
    companies = overview["companies"]
    violations = [
        f"{status} : API {companies[status]} ≠ base {rows.get(status, 0)}"
        for status in ("trial", "active", "suspended")
        if companies[status] != rows.get(status, 0)
    ]
    if companies["total"] != sum(rows.values()):
        violations.append(f"total : API {companies['total']} ≠ base {sum(rows.values())}")
    return violations
