"""Le « maintenant » métier (ADR 0065).

Toute lecture qui dépend du jour en cours — tableau de bord, périodes par défaut, retards
des dettes, fraîcheur des recommandations — demande l'heure ici. En temps normal, c'est
l'heure réelle. Avec `COGES_FROZEN_NOW` (développement, e2e de la maquette v2), c'est ce
moment figé, pour que les écrans et ceux de la maquette montrent la même journée.

Ce qui **n'y passe pas**, et garde l'heure réelle : jetons et sessions, limites de débit,
clés d'idempotence, expirations, horodatages écrits par la base (`now()`), et les gardes
d'antidatage des écritures (ADR 0015) — une heure figée de plus de 48 h ferait refuser
chaque mouvement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def now() -> datetime:
    """Maintenant, en UTC : l'heure figée si elle est configurée, sinon l'heure réelle."""
    frozen = get_settings().frozen_now
    return frozen.astimezone(UTC) if frozen is not None else datetime.now(UTC)


def now_in(timezone: str) -> datetime:
    """Maintenant dans le fuseau donné (celui de l'entreprise)."""
    return now().astimezone(ZoneInfo(timezone))


def today_in(timezone: str) -> date:
    """La date du jour dans le fuseau donné."""
    return now_in(timezone).date()


def today_utc() -> date:
    """La date du jour en UTC (bornes historiquement prises en UTC, ex. retards)."""
    return now().date()
