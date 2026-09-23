"""Codes lisibles des tiers : `CLI-0001`, `FRN-0001`.

Numérotation **par entreprise**, ce qu'une séquence PostgreSQL ne sait pas faire :
une séquence est un objet global, elle donnerait `CLI-0001` au premier client de la
première entreprise et `CLI-0002` au premier client de la deuxième. Le numéro suivant
est donc calculé à partir des codes existants du tenant, et l'unicité réelle reste
garantie par les index `customers_code_uq` / `suppliers_code_uq` : en cas de
collision, PostgreSQL refuse et l'appelant recommence (ADR 0013).

Le code reste **modifiable** : ces fonctions ne servent qu'à proposer une valeur de
départ à qui n'en fournit pas.
"""

from __future__ import annotations

#: Nombre de tentatives avant d'abandonner. Chaque collision suppose une création
#: concurrente dans la même entreprise à la même seconde ; deux de suite est déjà
#: improbable, cinq relève de la panne.
CODE_ATTEMPTS = 5

#: Largeur du compteur. `CLI-0001` reste lisible jusqu'à 9 999, puis s'allonge
#: naturellement sans rien casser (`CLI-10000`).
CODE_WIDTH = 4


def format_code(prefix: str, number: int) -> str:
    """`('CLI', 7)` → `CLI-0007`."""
    return f"{prefix}-{number:0{CODE_WIDTH}d}"


def number_pattern(prefix: str) -> str:
    """Expression régulière POSIX qui extrait le compteur d'un code du tenant.

    Les codes saisis à la main qui ne suivent pas la convention ne matchent pas :
    ils n'entrent donc pas dans le calcul du numéro suivant.
    """
    return f"^{prefix}-([0-9]+)$"
