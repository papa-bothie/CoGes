"""Recherche texte des listes du référentiel.

Toutes les listes du référentiel exposent un `?search=`. Deux mécanismes, tous
deux **servis par l'index GIN trigramme** du § 8.10 (`products_name_trgm`,
`customers_name_trgm`, `suppliers_name_trgm`) :

* `name % 'terme'` — opérateur de similarité de `pg_trgm` : tolère les fautes de
  frappe (« yaourt » trouve « yaourth »), au-delà du seuil
  `pg_trgm.similarity_threshold` (0,3 par défaut) ;
* `name ILIKE '%terme%'` — sous-chaîne. `pg_trgm` indexe aussi ce motif, il n'y a
  donc pas de balayage complet de la table.

Les codes — `sku`, `barcode`, `code` client ou fournisseur — ne sont **jamais**
cherchés par approximation : une correspondance exacte, ou rien. Un code-barres
scanné qui ramènerait « le produit le plus ressemblant » serait une erreur de
caisse.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, or_
from sqlalchemy.orm import InstrumentedAttribute

#: Un terme plus court ne discrimine rien et ne franchit pas le seuil de
#: similarité : la recherche est alors ignorée plutôt que de renvoyer la table.
MIN_SEARCH_LENGTH = 2

#: `LIKE` interprète `%`, `_` et `\` : ils sont neutralisés avant l'interpolation.
_LIKE_ESCAPE = "\\"


def normalise_term(raw: str | None) -> str | None:
    """Terme exploitable, ou `None` si la recherche doit être ignorée."""
    if raw is None:
        return None
    term = raw.strip()
    return term if len(term) >= MIN_SEARCH_LENGTH else None


def _escape_like(term: str) -> str:
    escaped = term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
    for wildcard in ("%", "_"):
        escaped = escaped.replace(wildcard, f"{_LIKE_ESCAPE}{wildcard}")
    return escaped


def name_matches(column: InstrumentedAttribute[str], term: str) -> ColumnElement[bool]:
    """Similarité trigramme **ou** sous-chaîne, sur le nom."""
    return or_(
        column.op("%", is_comparison=True)(term),
        column.ilike(f"%{_escape_like(term)}%", escape=_LIKE_ESCAPE),
    )


def code_matches(
    columns: Sequence[InstrumentedAttribute[str] | InstrumentedAttribute[str | None]], term: str
) -> ColumnElement[bool]:
    """Égalité stricte sur un ou plusieurs codes. Aucune approximation."""
    return or_(*(column == term for column in columns))
