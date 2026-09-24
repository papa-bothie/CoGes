"""La formule du remboursable — proration de la remise et arrondi (§ 4.7).

Ces tests ne touchent pas la base : ils fixent le seul calcul que la phase 06
effectue en Python. Tout le reste — plafonds, totaux, statuts — est calculé par
PostgreSQL et vérifié par les tests d'intégrité T18 à T22.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from app.modules.sales.models import SaleItem
from app.modules.sales.service import _refund_amounts


def _line(
    *,
    qty: str,
    unit_price: str,
    discount: str = "0",
    tax_rate: str = "0",
) -> SaleItem:
    """Une ligne de vente réduite à ce que le calcul lit.

    Un objet nu plutôt qu'une instance de `SaleItem` : le calcul ne doit dépendre
    que de ces quatre champs, et un test qui en fournirait davantage laisserait
    passer une dépendance cachée.
    """
    return cast(
        "SaleItem",
        cast(
            "Any",
            SimpleNamespace(
                qty=Decimal(qty),
                unit_price=Decimal(unit_price),
                discount=Decimal(discount),
                tax_rate=Decimal(tax_rate),
            ),
        ),
    )


def test_a_full_return_refunds_exactly_the_line_total() -> None:
    """Rendre tout ce qu'on a acheté rend exactement ce qu'on a payé.

    C'est la propriété qui commande la forme de l'arrondi : le net et la taxe sont
    arrondis **séparément**, comme les colonnes générées `net_amount` et
    `tax_amount` de `sale_items`, puis additionnés. Un arrondi unique sur le TTC
    rendrait ici un centime de moins.
    """
    item = _line(qty="10", unit_price="1500", discount="333.33", tax_rate="0.1800")

    refund_amount, tax_refund = _refund_amounts(item, Decimal("10"))

    net_amount = Decimal("14666.67")  # round(10 × 1500 − 333.33, 2)
    tax_amount = Decimal("2640.00")  # round(14666.67 × 0.18, 2)
    assert tax_refund == tax_amount
    assert refund_amount == net_amount + tax_amount


def test_the_discount_is_prorated_across_the_returned_quantity() -> None:
    """Rendre 3 articles sur 10 rend trois dixièmes de la remise, pas la remise."""
    item = _line(qty="10", unit_price="1000", discount="1000", tax_rate="0")

    refund_amount, tax_refund = _refund_amounts(item, Decimal("3"))

    # 3 × 1000 − 1000 × 3/10 = 3000 − 300.
    assert refund_amount == Decimal("2700.00")
    assert tax_refund == Decimal("0.00")


def test_tax_is_computed_on_the_historic_rate_of_the_line() -> None:
    """Le taux vient de la ligne, figé à la confirmation, jamais du produit du jour."""
    item = _line(qty="10", unit_price="1000", tax_rate="0.1800")

    refund_amount, tax_refund = _refund_amounts(item, Decimal("3"))

    assert tax_refund == Decimal("540.00")
    assert refund_amount == Decimal("3540.00")


def test_a_fully_discounted_line_refunds_nothing() -> None:
    """Une ligne offerte se rend sans rien rembourser : `refund_amount` vaut 0.

    Le cas n'est pas théorique : c'est le seul par lequel `refund_status` peut
    valoir `none_due`, puisque le § 8.7 le dérive du seul montant nul et qu'aucun
    renoncement n'est représentable en V1 (ADR 0025).
    """
    item = _line(qty="4", unit_price="2500", discount="10000", tax_rate="0.1800")

    refund_amount, tax_refund = _refund_amounts(item, Decimal("4"))

    assert refund_amount == Decimal("0.00")
    assert tax_refund == Decimal("0.00")


def test_the_tax_share_never_exceeds_the_refunded_amount() -> None:
    """`sale_return_items_tax_bounds` exige `tax_refund <= refund_amount`.

    La contrainte est en base ; ce test vérifie que le calcul ne la frôle jamais,
    y compris sur une quantité fractionnaire dont la remise proratisée ne tombe pas
    juste.
    """
    item = _line(qty="3", unit_price="99.99", discount="0.07", tax_rate="0.1800")

    refund_amount, tax_refund = _refund_amounts(item, Decimal("1"))

    assert Decimal("0") <= tax_refund <= refund_amount
