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

import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, case, false, func, or_
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


#: Assez de chiffres pour désigner un téléphone (« 77 655 » : 5 chiffres).
MIN_PHONE_DIGITS = 4


def phone_matches(column: InstrumentedAttribute[str | None], term: str) -> ColumnElement[bool]:
    """Les chiffres tapés apparaissent dans le téléphone, espaces et signes ignorés.

    « 77655 », « 655 90 » et « +221 77 655 90 21 » trouvent « 77 655 90 21 ». Un terme
    sans assez de chiffres ne cherche pas de téléphone. Les listes de personnes d'une
    boutique comptent quelques centaines de lignes : aucun index n'est nécessaire.
    """
    digits = re.sub(r"\D", "", term)
    if len(digits) < MIN_PHONE_DIGITS:
        return false()
    if digits.startswith("221") and len(digits) > 9:
        digits = digits[3:]
    return func.regexp_replace(column, r"\D", "", "g").contains(digits)


def code_matches(
    columns: Sequence[InstrumentedAttribute[str] | InstrumentedAttribute[str | None]], term: str
) -> ColumnElement[bool]:
    """Égalité stricte sur un ou plusieurs codes. Aucune approximation."""
    return or_(*(column == term for column in columns))


def relevance_order(
    name: InstrumentedAttribute[str],
    codes: Sequence[InstrumentedAttribute[str] | InstrumentedAttribute[str | None]],
    term: str | None,
) -> list[ColumnElement[Any]]:
    """Ordre d'une liste filtrée : le plus pertinent d'abord, le nom ensuite.

    Sans recherche, l'ordre alphabétique. Avec une recherche, un code exact, puis le
    nom identique, puis le nom qui commence par le terme, puis la sous-chaîne, puis
    la seule similarité trigramme — sinon « Article 12 » peut disparaître derrière
    vingt « Article 1x » approchants, triés par nom, au-delà de la page affichée.
    """
    if term is None:
        return [name.asc()]
    escaped = _escape_like(term)
    rank = case(
        (or_(*(column == term for column in codes)), 0),
        (func.lower(name) == term.lower(), 1),
        (name.ilike(f"{escaped}%", escape=_LIKE_ESCAPE), 2),
        (name.ilike(f"%{escaped}%", escape=_LIKE_ESCAPE), 3),
        else_=4,
    )
    return [rank.asc(), func.similarity(name, term).desc(), name.asc()]
