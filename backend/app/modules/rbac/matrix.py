"""Matrice des rôles système (ADR 0007).

Ces trois rôles sont créés dans chaque entreprise à sa création. Ils sont marqués
`is_system = true` : ni renommables, ni supprimables.

Le gérant reçoit **toutes** les permissions du catalogue. Les deux autres reçoivent
la liste ci-dessous, et rien d'autre.

Arbitrages consignés dans l'ADR :

* le vendeur **confirme** une vente et encaisse — c'est la caisse — mais n'annule
  jamais : une annulation touche à la fois le stock, la finance et la dette ;
* l'ajustement manuel de stock (`inventory:update`) est réservé au gérant : c'est la
  seule écriture de stock qui ne vient pas d'un flux métier ;
* le comptable ne confirme aucune vente et ne touche pas au stock ;
* utilisateurs, rôles et paramètres d'entreprise : gérant uniquement ;
* le fil d'alertes est **personnel** : chacun lit et marque le sien, donc les trois
  rôles portent `notifications:read` et `notifications:update`. En revanche
  `system:read` — la santé du chemin asynchrone — reste au gérant seul : ce n'est ni
  une information comptable, ni une information de caisse (ADR 0032).
"""

from __future__ import annotations

from typing import Final

MANAGER: Final = "gerant"
SALESPERSON: Final = "vendeur"
ACCOUNTANT: Final = "comptable"

#: Libellés affichés en français ; le nom technique reste stable.
SYSTEM_ROLE_LABELS: Final[dict[str, str]] = {
    MANAGER: "Gérant",
    SALESPERSON: "Vendeur",
    ACCOUNTANT: "Comptable",
}

SALESPERSON_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {
        "categories:read",
        "products:read",
        "prices:read",
        "suppliers:read",
        "customers:read",
        "customers:create",
        "customers:update",
        "sales:read",
        "sales:create",
        "sales:update",
        "sales:confirm",
        "sale_returns:read",
        "sale_returns:create",
        "inventory:read",
        "payments:read",
        "payments:create",
        "dashboard:read",
        "notifications:read",
        "notifications:update",
    }
)

ACCOUNTANT_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {
        "company:read",
        "categories:read",
        "products:read",
        "prices:read",
        "suppliers:read",
        "customers:read",
        "sales:read",
        "sales:export",
        "sale_returns:read",
        "inventory:read",
        "payments:read",
        "payments:create",
        "payments:update",
        "payments:cancel",
        "expenses:read",
        "expenses:create",
        "expenses:update",
        "expenses:delete",
        "debts:read",
        "debts:create",
        "debts:update",
        "dashboard:read",
        "analytics:read",
        "analytics:export",
        "insights:read",
        "insights:update",
        "audit:read",
        "audit:export",
        "importexport:export",
        "notifications:read",
        "notifications:update",
    }
)

#: `None` signifie « toutes les permissions du catalogue ».
SYSTEM_ROLES: Final[dict[str, frozenset[str] | None]] = {
    MANAGER: None,
    SALESPERSON: SALESPERSON_PERMISSIONS,
    ACCOUNTANT: ACCOUNTANT_PERMISSIONS,
}
