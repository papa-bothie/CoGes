"""Codes lisibles : tiers (`CLI-0001`) et documents numérotés (`V-000123`).

Deux mécaniques, pour deux exigences différentes.

Numérotation **par entreprise**, ce qu'une séquence PostgreSQL ne sait pas faire :
une séquence est un objet global, elle donnerait `CLI-0001` au premier client de la
première entreprise et `CLI-0002` au premier client de la deuxième. Le numéro suivant
est donc calculé à partir des codes existants du tenant, et l'unicité réelle reste
garantie par les index `customers_code_uq` / `suppliers_code_uq` : en cas de
collision, PostgreSQL refuse et l'appelant recommence (ADR 0013).

Le code reste **modifiable** : ces fonctions ne servent qu'à proposer une valeur de
départ à qui n'en fournit pas.

Un **document** — une vente, un retour, une dépense — se numérote autrement. Son
numéro engage : un gérant qui présente ses ventes doit pouvoir montrer une suite
continue, et un trou est une question à laquelle il devra répondre. Il vient donc
d'un compteur dédié, `document_counters`, verrouillé le temps de la transaction.
Un `ROLLBACK` rend le numéro, ce qu'une séquence PostgreSQL ne fait pas (ADR 0021).

`core/` ne dépend jamais de `modules/` : ces fonctions ne connaissent que la session
et le contexte tenant.
"""

from __future__ import annotations

from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext

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


#: Largeur du compteur d'un document. `V-000123` reste lisible et trié
#: alphabétiquement jusqu'à 999 999 ventes, bien au-delà d'une PME.
DOCUMENT_WIDTH = 6

#: Préfixes d'affichage, par type de document.
DOCUMENT_PREFIXES: dict[str, str] = {
    "sale": "V",
    "sale_return": "R",
    "expense": "D",
}

_ENSURE_COUNTER = sql(
    """
    INSERT INTO document_counters (company_id, document_type, next_value)
    VALUES (:company_id, :document_type, 1)
    ON CONFLICT (company_id, document_type) DO NOTHING
    """
)

_TAKE_NUMBER = sql(
    """
    UPDATE document_counters SET next_value = next_value + 1
     WHERE company_id = :company_id AND document_type = :document_type
    RETURNING next_value - 1
    """
)


def next_document_number(session: Session, ctx: TenantContext, document_type: str) -> str:
    """Numéro suivant du type demandé, réservé pour cette transaction.

    L'`UPDATE … RETURNING` pose de lui-même un verrou exclusif sur la ligne du
    compteur : deux caisses qui numérotent en même temps sont sérialisées, et la
    seconde lit la valeur déjà incrémentée par la première. Il n'y a donc ni
    doublon, ni trou — sauf `ROLLBACK`, qui rend le numéro comme il rend la vente.

    La ligne du compteur est créée à la volée : une entreprise existante n'a pas
    besoin d'être reprise pour vendre.
    """
    prefix = DOCUMENT_PREFIXES.get(document_type)
    if prefix is None:  # pragma: no cover - garde-fou de programmation
        raise ValueError(f"Type de document inconnu : {document_type!r}")

    parameters = {"company_id": ctx.company_id, "document_type": document_type}
    session.execute(_ENSURE_COUNTER, parameters)
    number = session.execute(_TAKE_NUMBER, parameters).scalar_one()
    return f"{prefix}-{number:0{DOCUMENT_WIDTH}d}"
