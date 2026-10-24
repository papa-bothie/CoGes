"""Accès support encadré : ce que porte un jeton de support (ADR 0092).

Un compte de l'équipe CoGes lit les données d'une entreprise par **le même chemin**
qu'un utilisateur de cette entreprise — `coges_app`, la RLS normale, `SET LOCAL
app.company_id` —, en lecture seule, pour une durée bornée, et jamais sans trace.

La lecture seule tient par trois verrous indépendants, posés par `core/deps.py` :

1. les permissions ci-dessous, toutes des lectures ;
2. toute méthode autre que GET ou HEAD est refusée avant le handler
   (`support_read_only`) ;
3. la transaction est déclarée `READ ONLY` : PostgreSQL refuse lui-même toute écriture.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

ROLE: Final = "support_readonly"
#: Nom montré à l'entreprise : jamais celui de la personne de l'équipe.
DISPLAY_NAME: Final = "Équipe CoGes (support)"
ROLE_LABEL: Final = "Support CoGes, lecture seule"

#: Des lectures, et rien d'autre. Sans `notifications:read` (le fil est personnel, le
#: support n'est personne) ni exports (un export écrit un fichier et une ligne d'audit).
PERMISSIONS: Final[frozenset[str]] = frozenset(
    {
        "analytics:read",
        "audit:read",
        "categories:read",
        "company:read",
        "customers:read",
        "dashboard:read",
        "debts:read",
        "expenses:read",
        "insights:read",
        "inventory:read",
        "payments:read",
        "prices:read",
        "products:read",
        "roles:read",
        "sale_returns:read",
        "sales:read",
        "suppliers:read",
        "system:read",
        "users:read",
    }
)

#: Méthodes admises sous un jeton de support.
READ_METHODS: Final = frozenset({"GET", "HEAD"})

#: Durées (ADR 0092) : 2 h par défaut, 4 h au plus (la base le vérifie aussi).
DEFAULT_DURATION: Final = timedelta(hours=2)
MIN_DURATION: Final = timedelta(minutes=30)
MAX_DURATION: Final = timedelta(hours=4)
