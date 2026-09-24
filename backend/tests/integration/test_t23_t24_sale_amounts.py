"""T23 et T24 — taxes figées et égalité comptable, prouvées sur la base.

Deux garanties de nature différente. T23 est une garantie de **non-relecture** : un
montant émis ne change plus, quoi qu'il advienne du référentiel. T24 est une
garantie **structurelle** : l'égalité comptable n'est pas vérifiée par le code, elle
est produite par une colonne générée — aucune écriture ne peut créer une vente
déséquilibrée, pas même un UPDATE direct en base.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.integration.sales_harness import add_line, confirm, make_sale, read_items, read_sale
from tests.integration.stock_harness import make_product
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: `generated_always` : PostgreSQL refuse d'écrire une colonne générée.
_GENERATED_ALWAYS = "428C9"


def test_t23_a_tax_rate_change_does_not_touch_a_confirmed_sale(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """T23 — vente à 18 %, puis `default_tax_rate` passé à 5 % : rien ne bouge.

    Le taux est copié sur la ligne à la confirmation et n'est **jamais relu**
    (§ 4.5). Sans ce figement, changer un taux réécrirait silencieusement le
    montant de toutes les ventes passées.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        session.execute(
            text(
                "UPDATE products SET default_tax_rate = 0.1800 "
                " WHERE company_id = :company_id AND id = :id"
            ),
            {"company_id": tenant_a.company_id, "id": product_id},
        )
        sale_id = make_sale(session, tenant_a)
        add_line(
            session, tenant_a, sale_id, product_id, qty="2", unit_price="1000", tax_rate="0.1800"
        )
        confirm(session, tenant_a, sale_id)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        before_sale = read_sale(session, sale_id)
        before_items = read_items(session, sale_id)

    assert before_items[0].tax_amount == Decimal("360.00"), "18 % de 2 000"
    assert before_sale.tax_total == Decimal("360.00")
    assert before_sale.total == Decimal("2360.00")

    # Le référentiel change. La vente, elle, est déjà émise.
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "UPDATE products SET default_tax_rate = 0.0500 "
                " WHERE company_id = :company_id AND id = :id"
            ),
            {"company_id": tenant_a.company_id, "id": product_id},
        )

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        after_sale = read_sale(session, sale_id)
        after_items = read_items(session, sale_id)

    assert after_items[0].tax_rate == Decimal("0.1800"), "le taux figé ne suit pas le référentiel"
    assert after_items[0].tax_amount == before_items[0].tax_amount
    assert after_items[0].line_total == before_items[0].line_total
    assert after_sale.tax_total == before_sale.tax_total
    assert after_sale.total == before_sale.total


def test_t23_a_confirmed_line_cannot_be_rewritten(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """T23 — même en SQL direct, une ligne confirmée refuse d'être réécrite."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        sale_id = make_sale(session, tenant_a)
        item_id = add_line(session, tenant_a, sale_id, product_id, qty="2", unit_price="1000")
        confirm(session, tenant_a, sale_id)

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text("UPDATE sale_items SET tax_rate = 0.0500 WHERE id = :id"), {"id": item_id}
        )

    assert "figees apres confirmation" in str(excinfo.value)


def test_t24_accounting_equality_holds_on_every_sale(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """T24 — balayage : `subtotal − discount_total + tax_total = total` partout.

    Le balayage porte sur **toutes** les ventes visibles du tenant, pas seulement
    sur celles que ce test fabrique : les ventes laissées par les autres tests et
    par le harnais entrent dans le contrôle.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = make_product(session, tenant_a)
        # Trois formes de vente : sèche, remisée, taxée et remisée.
        plain = make_sale(session, tenant_a)
        add_line(session, tenant_a, plain, product_id, qty="3", unit_price="1250")

        discounted = make_sale(session, tenant_a)
        add_line(
            session, tenant_a, discounted, product_id, qty="2", unit_price="1000", discount="350"
        )

        mixed = make_sale(session, tenant_a)
        add_line(
            session,
            tenant_a,
            mixed,
            product_id,
            qty="7",
            unit_price="333",
            discount="31",
            tax_rate="0.1800",
        )
        for sale_id in (plain, discounted, mixed):
            confirm(session, tenant_a, sale_id)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        unbalanced = session.execute(
            text(
                "SELECT id, subtotal, discount_total, tax_total, total FROM sales "
                " WHERE subtotal - discount_total + tax_total <> total"
            )
        ).all()
        swept = session.execute(text("SELECT count(*) FROM sales")).scalar_one()
        lines_off = session.execute(
            text(
                "SELECT id FROM sale_items "
                " WHERE line_total <> net_amount + tax_amount "
                "    OR net_amount <> round(qty * unit_price - discount, 2)"
            )
        ).all()

    assert unbalanced == [], f"ventes déséquilibrées : {unbalanced}"
    assert lines_off == [], f"lignes déséquilibrées : {lines_off}"
    assert swept >= 4, "le balayage doit porter sur des ventes réelles, pas sur une table vide"


def test_t24_the_total_cannot_be_written_by_hand(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """T24 — `total` est une colonne générée : personne ne peut la forcer.

    C'est ce qui rend l'égalité comptable indéformable. Un `CHECK` se contourne en
    écrivant les trois termes de façon cohérente mais fausse ; une colonne générée,
    non : elle n'est pas une donnée, c'est un calcul.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        sale_id = make_sale(session, tenant_a)

    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(text("UPDATE sales SET total = 999999.99 WHERE id = :id"), {"id": sale_id})

    assert sqlstate(excinfo.value) == _GENERATED_ALWAYS
