"""T18 à T22 — retours et remboursements, prouvés sur la base.

Ces tests n'appellent ni l'API ni le service : ils ouvrent une transaction en
`coges_app`, posent le contexte et attaquent PostgreSQL. Ce qui est mesuré, ce sont
les garanties **structurelles** du § 8.7 — `return_item_check`, `refund_check`,
`refund_rollup`, `return_refund_status_set` — et le CHECK `payments_return_outflow`
du § 8.6. Elles tiennent quel que soit l'appelant, y compris celui qui
contournerait l'API (§ 10 du Modèle de données).

Les SQLSTATE `CG040` et `CG041` viennent de la révision 0008 (ADR 0026) : le § 8.7
levait ces refus en `check_violation`, code déjà porté par `sale_returns_refund_cap`
et par les bornes de remise, et un service ne pouvait donc pas les distinguer.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.errors import constraint_name, sqlstate
from app.core.tenancy import tenant_transaction
from tests.integration.sales_harness import (
    add_line,
    confirm,
    letter_refund,
    make_return,
    make_sale,
    read_return,
    refund_payment,
    return_in,
    return_line,
    sale_out,
)
from tests.integration.stock_harness import insert_movement, make_product, read_stock
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: Écarts assumés au § 8.7, posés par la révision 0008 (ADR 0026).
_RETURN_QTY_CAP = "CG040"
_REFUND_EXCEEDS_DUE = "CG041"
_CHECK_VIOLATION = "23514"


def test_t18_cumulative_returns_are_capped_by_the_sold_quantity(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Ligne de 10 retournée 3, puis 4, puis 4 : le troisième retour lève.

    Le plafond porte sur le **cumul**, pas sur chaque retour pris isolément : 3 et 4
    passent, mais 3 + 4 + 4 = 11 dépasse les 10 vendus. C'est `return_item_check` qui
    le refuse, sous le verrou qu'il pose sur la ligne de vente.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        sale_id = make_sale(session, tenant_a, customer_id=tenant_a.customer_id)
        item_id = add_line(session, tenant_a, sale_id, product_id, qty="10", unit_price="1500")
        confirm(session, tenant_a, sale_id)

    # Les deux premiers retours passent : 3 + 4 = 7 <= 10.
    for qty in ("3", "4"):
        with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
            return_id = make_return(session, tenant_a, sale_id)
            return_line(session, tenant_a, return_id, item_id, qty=qty)

    # Le troisième porterait le cumul à 11.
    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        return_id = make_return(session, tenant_a, sale_id)
        return_line(session, tenant_a, return_id, item_id, qty="4")

    assert sqlstate(excinfo.value) == _RETURN_QTY_CAP, str(excinfo.value)

    # Rien de ce troisième retour ne subsiste : ni son en-tête, ni sa ligne.
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        returned = session.execute(
            text(
                "SELECT COALESCE(SUM(qty), 0) FROM sale_return_items WHERE sale_item_id = :item_id"
            ),
            {"item_id": item_id},
        ).scalar_one()
    assert returned == Decimal("7.000")


def test_t19_returned_goods_re_enter_at_their_exit_cost(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Vente au CMP 15, CMP porté à 20, puis retour : la rentrée est à **15**.

    C'est la règle explicite du § 5.3. Le COGS historique de la vente reste
    exactement compensé, et une variation du CMP entre la vente et le retour ne
    fabrique ni profit ni perte. Conséquence assumée, vérifiée ici aussi : cette
    entrée pèse ensuite sur le CMP courant comme n'importe quelle autre.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        # 100 à 10 puis 100 à 20 → CMP 15 (T9).
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        insert_movement(session, tenant_a, product_id, "purchase_in", "100", unit_cost="20")

        sale_id = make_sale(session, tenant_a, customer_id=tenant_a.customer_id)
        item_id = add_line(session, tenant_a, sale_id, product_id, qty="10", unit_price="1500")
        confirm(session, tenant_a, sale_id)
        # La sortie est estampillée au CMP par `t20_inv_apply` : 15.
        sale_out(session, tenant_a, product_id, item_id, qty="10")
        sold_cost = session.execute(
            text("SELECT unit_cost FROM inventory_movements WHERE ref_id = :item_id"),
            {"item_id": item_id},
        ).scalar_one()

    assert sold_cost == Decimal("15.0000")

    # Le CMP monte à 20 : tout le stock restant est racheté plus cher.
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        insert_movement(session, tenant_a, product_id, "purchase_in", "1000", unit_cost="20.5")
        before = read_stock(session, product_id)

    assert before.avg_cost > Decimal("15.0000")

    # Le retour rentre au coût de **sortie**, pas au CMP du jour.
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        return_id = make_return(session, tenant_a, sale_id)
        return_item_id = return_line(
            session, tenant_a, return_id, item_id, qty="4", unit_cost=str(sold_cost)
        )
        movement_id = return_in(
            session,
            tenant_a,
            product_id,
            return_item_id,
            qty="4",
            unit_cost=str(sold_cost),
        )
        entered = session.execute(
            text(
                "SELECT qty_delta, unit_cost, reversal_of_movement_id, ref_type "
                "  FROM inventory_movements WHERE id = :id"
            ),
            {"id": movement_id},
        ).one()
        after = read_stock(session, product_id)

    assert entered.unit_cost == Decimal("15.0000"), (
        "la marchandise doit rentrer à son coût de sortie"
    )
    assert entered.qty_delta == Decimal("4.000")
    # Un retour est un fait métier autonome, pas l'annulation d'un mouvement (§ 5.3).
    assert entered.reversal_of_movement_id is None
    assert entered.ref_type == "sale_return_item"
    assert after.qty_on_hand == before.qty_on_hand + Decimal("4.000")
    # Le CMP baisse : quatre unités reviennent à 15 dans un stock valorisé plus haut.
    assert after.avg_cost < before.avg_cost


def test_t20_refunds_are_capped_by_the_refundable_amount(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Retour de 1 000 remboursé 600 puis 500 : le second lève, statut `partial`.

    Les deux montants pris isolément tiennent dans les 1 000 ; c'est leur somme qui
    ne passe pas. Le double remboursement est structurellement impossible :
    `refund_check` refuse le lettrage, et `sale_returns_refund_cap` le refuserait
    encore si le trigger disparaissait.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        sale_id = make_sale(session, tenant_a, customer_id=tenant_a.customer_id)
        item_id = add_line(session, tenant_a, sale_id, product_id, qty="10", unit_price="1000")
        confirm(session, tenant_a, sale_id)

        return_id = make_return(session, tenant_a, sale_id)
        return_line(session, tenant_a, return_id, item_id, qty="1", refund_amount="1000.00")
        state = read_return(session, return_id)

    assert state.total_refund == Decimal("1000.00")
    assert state.refund_status == "pending"

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        payment_id = refund_payment(session, tenant_a, return_id, amount="600.00")
        letter_refund(session, tenant_a, return_id, payment_id, amount="600.00")
        state = read_return(session, return_id)

    assert state.refunded_total == Decimal("600.00")
    assert state.refund_status == "partial"

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        second = refund_payment(session, tenant_a, return_id, amount="500.00")
        letter_refund(session, tenant_a, return_id, second, amount="500.00")

    assert sqlstate(excinfo.value) == _REFUND_EXCEEDS_DUE, str(excinfo.value)

    # Le refus n'a rien changé : le retour reste partiellement remboursé.
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        state = read_return(session, return_id)

    assert state.refunded_total == Decimal("600.00")
    assert state.refund_status == "partial"


def test_t20_settling_the_remainder_closes_the_return(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Le solde exact, lui, passe — et le statut devient `settled`.

    Sans ce test, T20 prouverait seulement qu'on ne peut pas trop rembourser, pas
    qu'on peut rembourser en plusieurs fois.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        sale_id = make_sale(session, tenant_a, customer_id=tenant_a.customer_id)
        item_id = add_line(session, tenant_a, sale_id, product_id, qty="10", unit_price="1000")
        confirm(session, tenant_a, sale_id)
        return_id = make_return(session, tenant_a, sale_id)
        return_line(session, tenant_a, return_id, item_id, qty="1", refund_amount="1000.00")

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        first = refund_payment(session, tenant_a, return_id, amount="600.00")
        letter_refund(session, tenant_a, return_id, first, amount="600.00")
        second = refund_payment(session, tenant_a, return_id, amount="400.00")
        letter_refund(session, tenant_a, return_id, second, amount="400.00")
        state = read_return(session, return_id)

    assert state.refunded_total == Decimal("1000.00")
    assert state.refund_status == "settled"


def test_t21_a_refund_cannot_be_an_inflow(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Un `inflow` portant `sale_return_id` viole `payments_return_outflow`.

    Le sens n'est jamais porté par un montant négatif (§ 4.9) : c'est `direction`
    qui le dit, et un remboursement de retour ne peut pas être un encaissement.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        sale_id = make_sale(session, tenant_a, customer_id=tenant_a.customer_id)
        item_id = add_line(session, tenant_a, sale_id, product_id, qty="10", unit_price="1000")
        confirm(session, tenant_a, sale_id)
        return_id = make_return(session, tenant_a, sale_id)
        return_line(session, tenant_a, return_id, item_id, qty="1", refund_amount="1000.00")

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        refund_payment(session, tenant_a, return_id, amount="1000.00", direction="inflow")

    assert sqlstate(excinfo.value) == _CHECK_VIOLATION, str(excinfo.value)
    assert constraint_name(excinfo.value) == "payments_return_outflow"


def test_t22_the_refund_link_answers_in_both_directions(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Retour → paiement et paiement → retour : une réponse unique de chaque côté.

    Et pas seulement : un **même** versement couvre ici deux retours, ce qu'une
    simple `payments.sale_return_id` ne saurait pas représenter (§ 4.7). C'est ce
    qui justifie la table de lettrage, et ce que ce test vérifie.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        insert_movement(session, tenant_a, product_id, "initial", "100", unit_cost="10")
        sale_id = make_sale(session, tenant_a, customer_id=tenant_a.customer_id)
        item_id = add_line(session, tenant_a, sale_id, product_id, qty="10", unit_price="1000")
        confirm(session, tenant_a, sale_id)

        first_return = make_return(session, tenant_a, sale_id)
        return_line(session, tenant_a, first_return, item_id, qty="1", refund_amount="1000.00")
        second_return = make_return(session, tenant_a, sale_id)
        return_line(session, tenant_a, second_return, item_id, qty="2", refund_amount="2000.00")

        # Un seul versement, lettré sur les deux retours. Il ne porte le
        # `sale_return_id` que de l'un d'eux : le contexte direct est un raccourci
        # de lecture, la relation N:N vit dans le lettrage.
        payment_id = refund_payment(session, tenant_a, first_return, amount="3000.00")
        letter_refund(session, tenant_a, first_return, payment_id, amount="1000.00")
        letter_refund(session, tenant_a, second_return, payment_id, amount="2000.00")

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        # Sens 1 : « quel remboursement pour ce retour » (index `srr_by_return`).
        by_return = session.execute(
            text(
                "SELECT payment_id, amount FROM sale_return_refunds "
                " WHERE sale_return_id = :return_id"
            ),
            {"return_id": second_return},
        ).all()
        # Sens 2 : « quels retours a soldés cette sortie » (index `srr_by_payment`).
        by_payment = session.execute(
            text(
                "SELECT sale_return_id, amount FROM sale_return_refunds "
                " WHERE payment_id = :payment_id ORDER BY amount"
            ),
            {"payment_id": payment_id},
        ).all()

    assert len(by_return) == 1, "un retour ne doit pas remonter deux fois le même lettrage"
    assert by_return[0].payment_id == payment_id
    assert by_return[0].amount == Decimal("2000.00")

    assert [row.sale_return_id for row in by_payment] == [first_return, second_return]
    assert sum(row.amount for row in by_payment) == Decimal("3000.00")
