"""Annuler une entrée de stock rend le CMP d'avant (prompt 21, P1.8 ; ADR 0087).

Le constat : stock 10 à 50, achat de 10 à 100 → CMP 75 ; l'achat annulé, la quantité
revient à 10 mais le CMP restait à 75. `cmp_next_avg` laisse la moyenne inchangée sur
une sortie, et l'inverse d'une entrée **est** une sortie ; `rebuild_product_stock`
rejouait la même formule et ne corrigeait rien.

La règle retenue : l'inverse d'une entrée la **retire au coût où elle est entrée**, ce
qui rend exactement le CMP d'avant — à condition qu'aucun autre mouvement du produit ne
l'ait suivie. Sinon, l'annulation est refusée (`CG022`) : le geste juste est une
correction de stock datée.

Tout passe ici par du SQL direct sous `coges_app` : c'est le trigger qui tient la règle.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.errors import sqlstate
from app.core.tenancy import tenant_transaction
from tests.conftest import auth_headers
from tests.integration.stock_harness import insert_movement, make_product, read_stock
from tests.tenancy.harness import Tenant, create_tenant

pytestmark = pytest.mark.integration

ENTRY_REVERSAL_SUPERSEDED = "CG022"

_REVERSE = text(
    """
    INSERT INTO inventory_movements
        (id, company_id, product_id, type, qty_delta, unit_cost,
         reversal_of_movement_id, created_by)
    SELECT :id, company_id, product_id, 'adjustment', -qty_delta, unit_cost, id, :created_by
      FROM inventory_movements WHERE id = :origin_id
    """
)


@pytest.fixture
def shop(session_factory: sessionmaker[Any], owner_engine: Engine) -> Iterator[Tenant]:
    """Une entreprise par test : `rebuild_product_stock` porte sur toute l'entreprise."""
    yield create_tenant(session_factory, owner_engine, f"cmp-{uuid4().hex[:6]}")


def _move(
    factory: sessionmaker[Any],
    tenant: Tenant,
    product_id: UUID,
    kind: str,
    qty: str,
    cost: str = "0",
) -> UUID:
    """Un mouvement par transaction : chacun a sa propre date, l'ordre est sans ambiguïté."""
    with tenant_transaction(tenant.ctx, session_factory=factory) as session:
        return insert_movement(session, tenant, product_id, kind, qty, unit_cost=cost)


def _reverse(factory: sessionmaker[Any], tenant: Tenant, origin_id: UUID) -> None:
    with tenant_transaction(tenant.ctx, session_factory=factory) as session:
        session.execute(
            _REVERSE, {"id": uuid4(), "origin_id": origin_id, "created_by": tenant.user_id}
        )


def _stock(factory: sessionmaker[Any], tenant: Tenant, product_id: UUID) -> tuple[Decimal, Decimal]:
    with tenant_transaction(tenant.ctx, session_factory=factory) as session:
        row = read_stock(session, product_id)
    return Decimal(row.qty_on_hand), Decimal(row.avg_cost)


def _product(factory: sessionmaker[Any], tenant: Tenant) -> UUID:
    with tenant_transaction(tenant.ctx, session_factory=factory) as session:
        return make_product(session, tenant)


def _rebuild_gaps(factory: sessionmaker[Any], tenant: Tenant) -> list[Any]:
    with tenant_transaction(tenant.ctx, session_factory=factory) as session:
        return list(
            session.execute(
                text("SELECT * FROM rebuild_product_stock(:company_id)"),
                {"company_id": tenant.company_id},
            ).all()
        )


def test_cancelling_the_last_purchase_gives_back_the_previous_cmp(
    session_factory: sessionmaker[Any], shop: Tenant
) -> None:
    product = _product(session_factory, shop)
    _move(session_factory, shop, product, "initial", "10", "50")
    purchase = _move(session_factory, shop, product, "purchase_in", "10", "100")
    assert _stock(session_factory, shop, product) == (Decimal("20"), Decimal("75"))

    _reverse(session_factory, shop, purchase)

    assert _stock(session_factory, shop, product) == (Decimal("10"), Decimal("50"))
    assert _rebuild_gaps(session_factory, shop) == [], "le recalcul de nuit diverge du trigger"


def _assert_refused(factory: sessionmaker[Any], tenant: Tenant, origin: UUID) -> None:
    with pytest.raises(DBAPIError) as raised:
        _reverse(factory, tenant, origin)
    assert sqlstate(raised.value) == ENTRY_REVERSAL_SUPERSEDED, raised.value


def test_an_entry_followed_by_a_sale_cannot_be_cancelled(
    session_factory: sessionmaker[Any], shop: Tenant
) -> None:
    """Entrée, vente, annulation de l'entrée : le coût de la vente reposait sur elle."""
    product = _product(session_factory, shop)
    _move(session_factory, shop, product, "initial", "10", "50")
    purchase = _move(session_factory, shop, product, "purchase_in", "10", "100")
    _move(session_factory, shop, product, "sale_out", "-5")
    before = _stock(session_factory, shop, product)

    _assert_refused(session_factory, shop, purchase)

    assert _stock(session_factory, shop, product) == before


def test_the_first_of_two_purchases_cannot_be_cancelled(
    session_factory: sessionmaker[Any], shop: Tenant
) -> None:
    product = _product(session_factory, shop)
    first = _move(session_factory, shop, product, "purchase_in", "10", "50")
    _move(session_factory, shop, product, "purchase_in", "10", "100")

    _assert_refused(session_factory, shop, first)

    assert _stock(session_factory, shop, product) == (Decimal("20"), Decimal("75"))


def test_cancelling_a_loss_still_works_after_other_movements(
    session_factory: sessionmaker[Any], shop: Tenant
) -> None:
    """La règle ne vise que l'inverse d'une **entrée** : rendre une perte reste libre."""
    product = _product(session_factory, shop)
    _move(session_factory, shop, product, "initial", "10", "50")
    loss = _move(session_factory, shop, product, "loss", "-2")
    _move(session_factory, shop, product, "purchase_in", "10", "100")

    _reverse(session_factory, shop, loss)

    qty, _ = _stock(session_factory, shop, product)
    assert qty == Decimal("20")
    assert _rebuild_gaps(session_factory, shop) == []


def test_the_api_explains_the_refusal(api_client: TestClient, alpha_token: str) -> None:
    headers = auth_headers(alpha_token)
    created = api_client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": f"Riz {uuid4().hex[:6]}", "unit_price": "1000.00", "default_tax_rate": "0"},
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["id"]

    def move(kind: str, qty: str, cost: str = "0") -> str:
        response = api_client.post(
            "/api/v1/inventory/movements",
            headers=headers,
            json={"product_id": product_id, "type": kind, "qty_delta": qty, "unit_cost": cost},
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    move("initial", "10", "50")
    purchase = move("purchase_in", "10", "100")
    move("purchase_in", "5", "80")

    refused = api_client.post(f"/api/v1/inventory/movements/{purchase}/reverse", headers=headers)

    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "entry_reversal_superseded"
