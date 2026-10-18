"""Ordre des verrous et interblocages (P2.8, ADR 0088).

La confirmation d'une vente verrouille le stock **par `product_id` croissant** : c'est ce
qui empêche deux caisses de s'interbloquer (§ 5). L'annulation d'une vente et la
réception d'une livraison prenaient les mêmes verrous dans un autre ordre — l'identifiant
aléatoire du mouvement, l'ordre de saisie des lignes — et pouvaient donc s'interbloquer
avec une confirmation. Un interblocage ou un échec de sérialisation, s'il survient
malgré tout, doit dire « Réessayez » (409), pas 500.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.modules.inventory import service as inventory_service
from tests.conftest import auth_headers, write_headers
from tests.integration.test_lot_3b_stock import _deliver, _fresh, _product, _supplier

pytestmark = pytest.mark.integration

PRODUCTS = 6


def _spy_stock_writes(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Produits dans l'ordre où leur ligne de stock est écrite (donc verrouillée)."""
    seen: list[UUID] = []
    for name in ("reverse_sale_out", "record_movement"):
        original = getattr(inventory_service, name)

        def spy(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
            target = args[2]
            product = getattr(target, "product_id", None)
            seen.append(UUID(str(product)))
            return _original(*args, **kwargs)

        monkeypatch.setattr(inventory_service, name, spy)
    return seen


def test_cancelling_a_sale_locks_stock_in_product_order(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = _fresh(api_client)
    products = [_product(api_client, token, f"Article {index}") for index in range(PRODUCTS)]
    sale = api_client.post("/api/v1/sales", headers=auth_headers(token), json={}).json()
    for product in products:
        added = api_client.post(
            f"/api/v1/sales/{sale['id']}/items",
            headers=auth_headers(token),
            json={"product_id": product, "qty": "1"},
        )
        assert added.status_code == 201, added.text
    total = api_client.get(f"/api/v1/sales/{sale['id']}", headers=auth_headers(token)).json()
    confirmed = api_client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "0"},
    )
    if confirmed.status_code != 200:  # vente à crédit sans client : comptant
        confirmed = api_client.post(
            f"/api/v1/sales/{sale['id']}/confirm",
            headers=write_headers(token),
            json={"paid_amount": total["total"], "method": "cash"},
        )
    assert confirmed.status_code == 200, confirmed.text

    seen = _spy_stock_writes(monkeypatch)
    # Une vente encaissée ne s'annule pas : on vise le seul ordre des verrous, donc on
    # neutralise ce refus-là.
    monkeypatch.setattr(
        "app.modules.finance.service.has_settled_payment", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "app.modules.finance.service.write_off_sale_debt", lambda *args, **kwargs: None
    )
    cancelled = api_client.post(
        f"/api/v1/sales/{sale['id']}/cancel",
        headers=write_headers(token),
        json={"reason": "Erreur de caisse"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert seen == sorted(seen), "l'annulation verrouille le stock dans le désordre"


def test_receiving_a_delivery_locks_stock_in_product_order(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = _fresh(api_client)
    products = [_product(api_client, token, f"Livré {index}") for index in range(PRODUCTS)]
    supplier = _supplier(api_client, token)
    seen = _spy_stock_writes(monkeypatch)

    received = _deliver(
        api_client,
        token,
        {
            "supplier_id": supplier,
            "lines": [
                {"product_id": product, "qty": "2", "unit_cost": "500"}
                for product in sorted(products, reverse=True)
            ],
            "payment_mode": "now",
        },
    )

    assert received.status_code in (200, 201), received.text
    assert seen == sorted(seen), "la livraison verrouille le stock dans l'ordre de saisie"


@pytest.mark.parametrize(
    "error", [psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure]
)
def test_a_deadlock_says_try_again_not_500(
    api_client: TestClient, alpha_token: str, monkeypatch: pytest.MonkeyPatch, error: type
) -> None:
    def deadlocked(*args: Any, **kwargs: Any) -> Any:
        raise OperationalError("UPDATE product_stock …", {}, error("interblocage simulé"))

    monkeypatch.setattr("app.modules.customers.service.create_customer", deadlocked)

    response = api_client.post(
        "/api/v1/customers", headers=auth_headers(alpha_token), json={"name": "Course"}
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "concurrent_update"


def test_a_refund_locks_the_debt_before_the_return(
    api_client: TestClient, alpha_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dette, puis retour : l'ordre de l'annulation d'un paiement (`refund_rollup`)."""
    from app.modules.finance import service as finance_service  # noqa: PLC0415
    from app.modules.sales.repository import SaleReturnRepository  # noqa: PLC0415
    from tests.integration.test_returns_api import (  # noqa: PLC0415
        _confirmed_sale,
        _create_return,
    )
    from tests.integration.test_returns_api import _product as _return_product  # noqa: PLC0415

    product_id = _return_product(api_client, alpha_token)
    sale_id, item_id, _ = _confirmed_sale(api_client, alpha_token, product_id, qty="2")
    created = _create_return(api_client, alpha_token, sale_id, item_id, "1")
    assert created.status_code == 201, created.text

    order: list[str] = []
    original_lock = finance_service.lock_sale_debt
    original_return = SaleReturnRepository.get_for_update

    def lock_debt(*args: Any, **kwargs: Any) -> Any:
        order.append("dette")
        return original_lock(*args, **kwargs)

    def lock_return(self: Any, *args: Any, **kwargs: Any) -> Any:
        order.append("retour")
        return original_return(self, *args, **kwargs)

    monkeypatch.setattr(finance_service, "lock_sale_debt", lock_debt)
    monkeypatch.setattr(SaleReturnRepository, "get_for_update", lock_return)

    refunded = api_client.post(
        f"/api/v1/sale-returns/{created.json()['id']}/refunds",
        headers=write_headers(alpha_token),
        json={"amount": "100.00", "method": "cash"},
    )

    assert refunded.status_code in (200, 201), refunded.text
    assert order[:2] == ["dette", "retour"], f"ordre des verrous : {order}"
