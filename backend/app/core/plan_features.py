"""Droits par offre (prompt 41, ADR 0132).

`plans.features` est la **source** des droits ; ce module en tient le catalogue fermé
(un code inconnu ne s'écrit nulle part, test) et la lecture par la fonction
`current_plan()` de `coges_billing` : `coges_app` ne lit toujours aucune table de la
plateforme (ADR 0091), la fonction lui rend l'offre de **son** entreprise seulement.

Le contrôle est fait par le serveur (`app.core.deps.require_feature`) ; l'écran ne fait
que refléter le bloc `plan` de `/auth/me`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

FeatureCode = Literal[
    "sales",
    "purchases",
    "inventory",
    "dashboard",
    "reports_exports",
    "product_photos",
    "documents",
    "stock_alerts",
    "imports",
    "physical_inventory",
    "invoice_branding",
    "stock_locations",
    "priority_support",
]

#: Pro et Business (et Premium).
COMMON_FEATURES: Final[tuple[FeatureCode, ...]] = (
    "sales",
    "purchases",
    "inventory",
    "dashboard",
    "reports_exports",
    "product_photos",
    "documents",
    "stock_alerts",
)
#: Business seulement (et Premium). `physical_inventory`, `invoice_branding` (lot E) et
#: `stock_locations` (lot F) existent dès maintenant mais ne protègent encore rien.
BUSINESS_FEATURES: Final[tuple[FeatureCode, ...]] = (
    "imports",
    "physical_inventory",
    "invoice_branding",
    "stock_locations",
    "priority_support",
)
CATALOGUE: Final[tuple[FeatureCode, ...]] = COMMON_FEATURES + BUSINESS_FEATURES

#: Ce que chaque offre contient, par code interne (les codes ne changent pas, ADR 0125).
PLAN_FEATURES: Final[dict[str, tuple[FeatureCode, ...]]] = {
    "starter": COMMON_FEATURES,
    "business": CATALOGUE,
    "premium": CATALOGUE,
}

#: L'offre vendable la plus petite qui donne un droit réservé (rendue dans l'erreur).
REQUIRED_PLAN: Final[dict[FeatureCode, str]] = {code: "business" for code in BUSINESS_FEATURES}

#: Droits qu'un administrateur peut accorder en droit acquis : ceux qu'une offre réserve.
GRANTABLE: Final[frozenset[str]] = frozenset(BUSINESS_FEATURES)


@dataclass(frozen=True, slots=True)
class CurrentPlan:
    plan_code: str
    plan_name: str
    status: Literal["trial", "active", "past_due", "suspended"]
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    is_license: bool
    max_users: int | None
    active_users: int
    features: tuple[str, ...]
    extra_features: tuple[str, ...]

    def has(self, feature: FeatureCode) -> bool:
        return feature in self.features


_READ = text(
    "SELECT plan_code, plan_name, status, trial_ends_at, current_period_end, is_license, "
    "max_users, active_users, features, extra_features FROM current_plan()"
)


def read_current_plan(session: Session) -> CurrentPlan | None:
    """L'offre de l'entreprise du contexte (`app.company_id`), ou `None` sans abonnement."""
    row = session.execute(_READ).one_or_none()
    if row is None:
        return None
    return CurrentPlan(
        plan_code=row.plan_code,
        plan_name=row.plan_name,
        status=row.status,
        trial_ends_at=row.trial_ends_at,
        current_period_end=row.current_period_end,
        is_license=row.is_license,
        max_users=row.max_users,
        active_users=row.active_users,
        features=tuple(row.features),
        extra_features=tuple(row.extra_features),
    )
