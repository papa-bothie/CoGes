"""Outils partagés par les étapes du pipeline."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.companies import service as companies_service

FORECAST_EXPONENT = Decimal("0.0001")


def week_version(as_of: date) -> str:
    """Version d'un modèle hebdomadaire : semaine ISO de sa production (`2026-W39`).

    Le pipeline tourne au matin de `as_of + 1` : c'est cette semaine-là qui nomme la
    version. L'entraînement du lundi (sur `as_of` = dimanche) et les inférences des
    six jours suivants partagent donc la même version.
    """
    year, week, _ = (as_of + timedelta(days=1)).isocalendar()
    return f"{year}-W{week:02d}"


def valid_until(as_of: date) -> datetime:
    """Fin de la semaine qui suit `as_of` : un insight non réémis sort de l'affichage."""
    next_next_monday = as_of + timedelta(days=14 - as_of.weekday())
    return datetime.combine(next_next_monday, time.min, tzinfo=UTC)


def to_decimal(value: float) -> Decimal:
    """Retour d'un estimateur en décimal, précision de `forecasts.yhat`."""
    return Decimal(repr(value)).quantize(FORECAST_EXPONENT, rounding=ROUND_HALF_UP)


def uncertainty_level(yhat: float, lower: float, upper: float) -> str:
    """Qualificatif lisible, figé dans les résultats (règles d'affichage du Diagramme 7)."""
    relative = (upper - lower) / max(yhat, 1e-3)
    if relative <= 0.5:
        return "faible"
    if relative <= 1.0:
        return "moyenne"
    return "élevée"


def yesterday(session: Session, ctx: TenantContext, now: datetime | None = None) -> date:
    """Veille dans le fuseau de l'entreprise : le dernier jour **terminé**."""
    timezone = companies_service.get_timezone(session, ctx)
    moment = now or datetime.now(UTC)
    return moment.astimezone(ZoneInfo(timezone)).date() - timedelta(days=1)
