"""La formule du CMP et les bornes de saisie d'un mouvement.

`cmp_next_avg` est lue **en base**, jamais réécrite en Python : le § 5.6 exige une
formule unique, partagée par le trigger et la reconstruction. Ce fichier ne fait
que l'interroger sur des cas remarquables, pour que son comportement soit lisible
ailleurs que dans une migration.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from app.modules.inventory.schemas import MovementCreate

#: Identifiant quelconque : les tests de bornes ne touchent jamais la base.
_ANY_ID = UUID("11111111-1111-1111-1111-111111111111")

pytestmark = pytest.mark.integration

_CMP = text("SELECT cmp_next_avg(:qty, :avg, :delta, :cost)")


@pytest.mark.parametrize(
    ("qty", "avg", "delta", "cost", "expected", "why"),
    [
        ("0", "0", "100", "10", "10.0000", "premier lot : le CMP est son coût"),
        ("100", "10", "100", "20", "15.0000", "deux lots égaux : la moyenne exacte"),
        ("100", "10", "-50", "10", "10.0000", "sortie : la moyenne ne bouge pas"),
        ("100", "10", "-100", "10", "10.0000", "stock vidé : dernier CMP conservé, pas de 0/0"),
        ("1", "10", "2", "40", "30.0000", "pondération par les quantités, pas par les lots"),
        ("3", "10", "1", "15", "11.2500", "arrondi à quatre décimales"),
    ],
)
def test_cmp_next_avg_is_computed_by_postgresql(
    owner_engine: Engine,
    qty: str,
    avg: str,
    delta: str,
    cost: str,
    expected: str,
    why: str,
) -> None:
    """La seule autorité est le SQL ; ce test le documente, il ne le double pas."""
    with owner_engine.begin() as connection:
        result = connection.execute(
            _CMP,
            {
                "qty": Decimal(qty),
                "avg": Decimal(avg),
                "delta": Decimal(delta),
                "cost": Decimal(cost),
            },
        ).scalar_one()

    assert result == Decimal(expected), why


def test_a_movement_refuses_a_float() -> None:
    """Aucun flottant sur une quantité : un CMP calculé dessus serait faux."""
    with pytest.raises(ValueError, match="flottants sont interdits"):
        MovementCreate(product_id=_ANY_ID, type="purchase_in", qty_delta=1.5, unit_cost="10")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"type": "purchase_in", "qty_delta": "-1", "unit_cost": "10"}, "est une entrée"),
        ({"type": "loss", "qty_delta": "1"}, "est une sortie"),
        ({"type": "adjustment", "qty_delta": "1", "unit_cost": "10"}, "exige un motif"),
        ({"type": "purchase_in", "qty_delta": "1"}, "exige un coût unitaire"),
        ({"type": "loss", "qty_delta": "-1", "note": "x", "unit_cost": "10"}, "valorisée au CMP"),
        ({"type": "adjustment", "qty_delta": "0", "note": "x"}, "aucun sens"),
    ],
)
def test_movement_bounds_name_the_faulty_field(payload: dict[str, str], expected: str) -> None:
    """Chaque `CHECK` du § 8.5 est doublé côté schéma, avec un message lisible."""
    with pytest.raises(ValueError, match=expected):
        MovementCreate(product_id=_ANY_ID, **payload)  # type: ignore[arg-type]


def test_a_valid_movement_is_accepted() -> None:
    """Le test précédent ne vaut que si la forme correcte passe."""
    movement = MovementCreate(
        product_id=_ANY_ID, type="purchase_in", qty_delta="10", unit_cost="12.5"
    )
    assert movement.qty_delta == Decimal("10.000")
    assert movement.unit_cost == Decimal("12.5000")
