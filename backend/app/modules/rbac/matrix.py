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

from app.core import support_access

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

#: Quatrième rôle, celui de l'accès support encadré (ADR 0092). Défini dans le noyau,
#: qui le pose sur le contexte d'un jeton de support (`core/deps.py`, et le noyau ne
#: dépend d'aucun module), et repris ici pour que la matrice reste le registre complet.
#: Il n'existe **pas** en base : aucune entreprise ne le voit, personne ne le reçoit.
SUPPORT_READONLY: Final = support_access.ROLE
SUPPORT_READONLY_PERMISSIONS: Final[frozenset[str]] = support_access.PERMISSIONS

#: `None` signifie « toutes les permissions du catalogue ».
SYSTEM_ROLES: Final[dict[str, frozenset[str] | None]] = {
    MANAGER: None,
    SALESPERSON: SALESPERSON_PERMISSIONS,
    ACCOUNTANT: ACCOUNTANT_PERMISSIONS,
}


#: Grille « Qui peut faire quoi » (écran 24c, ADR 0075) : une ligne = un geste du
#: commerçant, cochée pour un rôle quand il porte **toutes** ses permissions. Les
#: lignes partagent parfois un droit (`inventory:create`) : décocher l'une le garde tant
#: qu'une autre cochée le demande.
ABILITIES: Final[dict[str, tuple[str, frozenset[str]]]] = {
    "sell": ("Vendre", frozenset({"sales:create", "sales:update", "sales:confirm"})),
    "cancel_sale": ("Annuler une vente", frozenset({"sales:cancel", "sale_returns:confirm"})),
    "fix_stock": ("Corriger le stock", frozenset({"inventory:create", "inventory:update"})),
    "receive": ("Recevoir une livraison", frozenset({"inventory:create", "debts:create"})),
    "see_money": ("Voir l’argent et les bénéfices", frozenset({"analytics:read", "expenses:read"})),
    "collect_debt": ("Encaisser une dette", frozenset({"debts:read", "payments:create"})),
    "change_prices": ("Changer les prix", frozenset({"prices:create", "products:update"})),
    "manage_people": (
        "Gérer les personnes",
        frozenset({"users:create", "users:read", "users:update", "users:delete"}),
    ),
}

#: Lignes que la grille montre sans permettre de les changer : gérer les personnes
#: reste au gérant (et le gérant, lui, garde tout).
LOCKED_ABILITIES: Final[frozenset[str]] = frozenset({"manage_people"})

#: Ordre des colonnes de la grille ; pas de rôle sur mesure à l'écran.
GRID_ROLES: Final[tuple[str, ...]] = (MANAGER, SALESPERSON, ACCOUNTANT)
