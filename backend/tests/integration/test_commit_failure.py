"""Un COMMIT qui échoue ne renvoie jamais un succès (ADR 0079).

Le COMMIT du cas d'usage se fait à la sortie de la dépendance `get_tenant_session`.
Si cette sortie avait lieu **après** l'envoi de la réponse, le client recevrait un
2xx pour une écriture que la base a refusée : vente « confirmée » restée en
brouillon, paiement « reçu » jamais enregistré.

L'échec est **réel** : un trigger de contrainte `DEFERRABLE INITIALLY DEFERRED` posé
sur `business_events` ne se déclenche qu'au COMMIT. Chaque écriture testée émet un
événement d'outbox dans sa transaction, donc chacune tombe au moment exact du COMMIT,
après que le service a tout écrit et que le routeur a construit sa réponse. Le trigger
est retiré avant le rejeu, qui doit alors réussir avec la **même** clé d'idempotence :
la clé n'a pas été enregistrée comme un succès.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.idempotency import IDEMPOTENCY_HEADER
from app.main import app
from tests.conftest import TEST_BASE_URL, DemoCompany, auth_headers, read_scalar_in_tenant

pytestmark = pytest.mark.integration

_FAIL_FUNCTION = """
CREATE OR REPLACE FUNCTION test_fail_at_commit() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'échec de COMMIT provoqué par le test';
END
$fn$
"""


@contextmanager
def failing_commit(owner_engine: Engine, company_id: UUID) -> Iterator[None]:
    """Fait échouer au COMMIT toute transaction qui écrit un événement de `company_id`."""
    with owner_engine.begin() as connection:
        connection.execute(text(_FAIL_FUNCTION))
        connection.execute(
            text(
                f"""
                CREATE CONSTRAINT TRIGGER test_fail_at_commit
                AFTER INSERT ON business_events
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW
                WHEN (NEW.company_id = '{company_id}'::uuid)
                EXECUTE FUNCTION test_fail_at_commit()
                """
            )
        )
    try:
        yield
    finally:
        with owner_engine.begin() as connection:
            connection.execute(text("DROP TRIGGER test_fail_at_commit ON business_events"))
            connection.execute(text("DROP FUNCTION test_fail_at_commit()"))


@pytest.fixture
def raw_client(app_bound_to_test_database: None) -> Iterator[TestClient]:
    """Client qui rend la réponse HTTP au lieu de relever l'exception du serveur.

    C'est la seule façon de voir ce que le client aurait reçu : un 500, ou un 2xx déjà
    parti avant le COMMIT.
    """
    with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as client:
        yield client


def _headers(token: str, key: str) -> dict[str, str]:
    return {**auth_headers(token), IDEMPOTENCY_HEADER: key}


def _scalar(session_factory: sessionmaker[Any], company_id: UUID, sql: str, **params: Any) -> Any:
    return read_scalar_in_tenant(session_factory, company_id, sql, params)


def _events(session_factory: sessionmaker[Any], company_id: UUID) -> int:
    return int(_scalar(session_factory, company_id, "SELECT count(*) FROM business_events"))


def _key_count(session_factory: sessionmaker[Any], company_id: UUID, key: str) -> int:
    return int(
        _scalar(
            session_factory,
            company_id,
            "SELECT count(*) FROM idempotency_keys WHERE key = :key",
            key=key,
        )
    )


def _stock(session_factory: sessionmaker[Any], company_id: UUID, product_id: str) -> Any:
    with_row = _scalar(
        session_factory,
        company_id,
        "SELECT row(qty_on_hand, avg_cost)::text FROM product_stock WHERE product_id = :id",
        id=UUID(product_id),
    )
    return with_row


def _product_with_stock(client: TestClient, token: str) -> str:
    marker = uuid4().hex[:8]
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"sku": f"SKU-{marker}", "name": f"Article {marker}", "unit_price": "1500.00"},
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=_headers(token, uuid4().hex),
        json={"product_id": product_id, "type": "initial", "qty_delta": "50", "unit_cost": "1000"},
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def test_sale_confirmation_whose_commit_fails_is_not_reported_as_done(
    raw_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    owner_engine: Engine,
    session_factory: sessionmaker[Any],
) -> None:
    company_id = company_alpha.company_id
    product_id = _product_with_stock(raw_client, alpha_token)
    draft = raw_client.post("/api/v1/sales", headers=auth_headers(alpha_token), json={})
    assert draft.status_code == 201, draft.text
    sale_id = str(draft.json()["id"])
    line = raw_client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=auth_headers(alpha_token),
        json={"product_id": product_id, "qty": "3"},
    )
    assert line.status_code == 201, line.text

    stock_before = _stock(session_factory, company_id, product_id)
    events_before = _events(session_factory, company_id)
    key = uuid4().hex
    body = {"paid_amount": "4500.00"}

    with failing_commit(owner_engine, company_id):
        failed = raw_client.post(
            f"/api/v1/sales/{sale_id}/confirm", headers=_headers(alpha_token, key), json=body
        )

    assert failed.status_code >= 500, f"COMMIT refusé mais réponse {failed.status_code}"
    status = _scalar(
        session_factory,
        company_id,
        "SELECT status::text FROM sales WHERE id = :id",
        id=UUID(sale_id),
    )
    assert status == "draft"
    assert _stock(session_factory, company_id, product_id) == stock_before
    assert _events(session_factory, company_id) == events_before
    assert _key_count(session_factory, company_id, key) == 0

    replay = raw_client.post(
        f"/api/v1/sales/{sale_id}/confirm", headers=_headers(alpha_token, key), json=body
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "confirmed"


def test_payment_whose_commit_fails_is_not_reported_as_received(
    raw_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    owner_engine: Engine,
    session_factory: sessionmaker[Any],
) -> None:
    company_id = company_alpha.company_id
    customer = raw_client.post(
        "/api/v1/customers",
        headers=auth_headers(alpha_token),
        json={"name": f"Client {uuid4().hex[:8]}"},
    )
    assert customer.status_code == 201, customer.text
    debt = raw_client.post(
        "/api/v1/debts",
        headers=_headers(alpha_token, uuid4().hex),
        json={
            "party_type": "customer",
            "customer_id": customer.json()["id"],
            "principal": "1000.00",
        },
    )
    assert debt.status_code == 201, debt.text
    debt_id = UUID(debt.json()["id"])

    payments_before = int(_scalar(session_factory, company_id, "SELECT count(*) FROM payments"))
    events_before = _events(session_factory, company_id)
    key = uuid4().hex
    body = {
        "direction": "inflow",
        "method": "cash",
        "amount": "400.00",
        "allocations": [{"debt_id": str(debt_id), "amount": "400.00"}],
    }

    with failing_commit(owner_engine, company_id):
        failed = raw_client.post("/api/v1/payments", headers=_headers(alpha_token, key), json=body)

    assert failed.status_code >= 500, f"COMMIT refusé mais réponse {failed.status_code}"
    assert (
        int(_scalar(session_factory, company_id, "SELECT count(*) FROM payments"))
        == payments_before
    )
    balance = _scalar(
        session_factory, company_id, "SELECT balance FROM debts WHERE id = :id", id=debt_id
    )
    assert balance == Decimal("1000.00")
    assert _events(session_factory, company_id) == events_before
    assert _key_count(session_factory, company_id, key) == 0

    replay = raw_client.post("/api/v1/payments", headers=_headers(alpha_token, key), json=body)
    assert replay.status_code == 201, replay.text
    balance = _scalar(
        session_factory, company_id, "SELECT balance FROM debts WHERE id = :id", id=debt_id
    )
    assert balance == Decimal("600.00")


def test_stock_correction_whose_commit_fails_is_not_reported_as_done(
    raw_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    owner_engine: Engine,
    session_factory: sessionmaker[Any],
) -> None:
    company_id = company_alpha.company_id
    product_id = _product_with_stock(raw_client, alpha_token)
    stock_before = _stock(session_factory, company_id, product_id)
    events_before = _events(session_factory, company_id)
    key = uuid4().hex
    body = {"product_id": product_id, "qty_delta": "-4", "reason_code": "damaged"}

    with failing_commit(owner_engine, company_id):
        failed = raw_client.post(
            "/api/v1/inventory/movements", headers=_headers(alpha_token, key), json=body
        )

    assert failed.status_code >= 500, f"COMMIT refusé mais réponse {failed.status_code}"
    assert _stock(session_factory, company_id, product_id) == stock_before
    assert _events(session_factory, company_id) == events_before
    assert _key_count(session_factory, company_id, key) == 0

    replay = raw_client.post(
        "/api/v1/inventory/movements", headers=_headers(alpha_token, key), json=body
    )
    assert replay.status_code == 201, replay.text
    assert _stock(session_factory, company_id, product_id) != stock_before
