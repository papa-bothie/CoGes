"""Idempotence des écritures financières — point ouvert P4, tranché par l'ADR 0027.

Quatre promesses, et chacune a son test :

1. **même clé, même corps** ⇒ la réponse initiale est rejouée, et il n'y a qu'un
   seul paiement en base ;
2. **même clé, corps différent** ⇒ 422. Rendre la première réponse à une seconde
   demande serait pire qu'un doublon : ce serait un mensonge ;
3. **clé absente** ⇒ 422 sur toute écriture financière ;
4. **deux requêtes simultanées avec la même clé** ⇒ un seul paiement. La seconde
   bloque sur `idempotency_keys_key_uq` jusqu'au COMMIT de la première, puis lit la
   réponse déjà enregistrée.

La quatrième est mesurée **sous la couche HTTP**, directement sur
`app.core.idempotency` : c'est là que vit le mécanisme, et deux clients de test
concurrents mesureraient surtout l'ordonnanceur de threads.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core import idempotency
from app.core.idempotency import IDEMPOTENCY_HEADER, REPLAY_HEADER
from app.core.tenancy import tenant_transaction
from app.main import app
from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant, write_headers
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

ENDPOINT = "/api/v1/payments"


def _customer(client: TestClient, token: str) -> str:
    marker = uuid4().hex[:8]
    response = client.post(
        "/api/v1/customers", headers=auth_headers(token), json={"name": f"Client {marker}"}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _debt(client: TestClient, token: str, customer_id: str, principal: str) -> str:
    response = client.post(
        "/api/v1/debts",
        headers=write_headers(token),
        json={"party_type": "customer", "customer_id": customer_id, "principal": principal},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _payment_count(session_factory: sessionmaker[Any], company_id: UUID) -> int:
    return int(
        read_scalar_in_tenant(
            session_factory,
            company_id,
            "SELECT count(*) FROM payments WHERE sale_id IS NULL AND sale_return_id IS NULL",
        )
    )


def test_replaying_the_same_request_returns_the_first_response(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Même clé, même corps : même réponse, et un seul paiement en base."""
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(api_client, alpha_token, customer_id, "1000.00")
    before = _payment_count(session_factory, company_alpha.company_id)

    key = uuid4().hex
    body = {
        "direction": "inflow",
        "method": "cash",
        "amount": "400.00",
        "allocations": [{"debt_id": debt_id, "amount": "400.00"}],
    }

    first = api_client.post(ENDPOINT, headers=write_headers(alpha_token, key), json=body)
    assert first.status_code == 201, first.text

    second = api_client.post(ENDPOINT, headers=write_headers(alpha_token, key), json=body)
    assert second.status_code == 201, second.text
    assert second.json() == first.json(), "le rejeu doit rendre la réponse initiale"
    assert second.headers.get(REPLAY_HEADER) == "true"
    assert first.headers.get(REPLAY_HEADER) is None, "la première réponse n'est pas un rejeu"

    assert _payment_count(session_factory, company_alpha.company_id) == before + 1

    # Et la dette n'a été réduite qu'une fois : le rejeu n'a rien lettré.
    balance = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT balance FROM debts WHERE id = :id",
        {"id": UUID(debt_id)},
    )
    assert balance == Decimal("600.00")


def test_the_same_key_on_another_body_is_refused(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Même clé, corps différent : 422, et aucune seconde écriture."""
    before = _payment_count(session_factory, company_alpha.company_id)
    key = uuid4().hex

    first = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token, key),
        json={"direction": "inflow", "method": "cash", "amount": "400.00"},
    )
    assert first.status_code == 201, first.text

    second = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token, key),
        json={"direction": "inflow", "method": "cash", "amount": "900.00"},
    )
    assert second.status_code == 422, second.text
    assert second.json()["error"]["code"] == "idempotency_key_reused"
    assert _payment_count(session_factory, company_alpha.company_id) == before + 1


def test_a_financial_write_without_a_key_is_refused(
    app_bound_to_test_database: None, alpha_token: str
) -> None:
    """L'en-tête est obligatoire, et son absence se nomme.

    Client brut, et non `api_client` : ce dernier pose une clé de lui-même, comme
    le ferait une vraie bibliothèque cliente. Pour mesurer l'absence d'en-tête, il
    faut un client qui n'en pose pas.
    """
    with TestClient(app) as client:
        response = client.post(
            ENDPOINT,
            headers=auth_headers(alpha_token),
            json={"direction": "inflow", "method": "cash", "amount": "100.00"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "idempotency_key_required"


def test_a_key_too_short_to_identify_anything_is_refused(
    api_client: TestClient, alpha_token: str
) -> None:
    """Une clé d'un caractère ne distingue rien : le schéma la refuse avant la base.

    Les bornes reprennent le `CHECK` de `idempotency_keys` — le client reçoit un
    422 qui nomme l'en-tête, et non un 500 sur violation de contrainte.
    """
    response = api_client.post(
        ENDPOINT,
        headers={**auth_headers(alpha_token), IDEMPOTENCY_HEADER: "x"},
        json={"direction": "inflow", "method": "cash", "amount": "100.00"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "idempotency_key_malformed"


def test_an_unauthenticated_write_is_refused_before_the_key_is_looked_at(
    api_client: TestClient,
) -> None:
    """Sans jeton, la réponse est 401 — jamais 422 sur un en-tête manquant.

    L'ordre des dépendances dans la signature de la route en dépend : une API qui
    répondrait 422 apprendrait à un inconnu que l'endpoint existe et ce qu'il attend.
    """
    response = api_client.post(
        ENDPOINT, json={"direction": "inflow", "method": "cash", "amount": "100.00"}
    )
    assert response.status_code == 401, response.text


def test_a_rolled_back_request_does_not_burn_its_key(
    api_client: TestClient, alpha_token: str
) -> None:
    """Une écriture refusée rend sa clé : elle a été annulée avec la transaction.

    Sans cette propriété, un caissier qui se trompe de montant devrait changer de
    clé pour réessayer — et la clé cesserait d'identifier *sa demande* pour
    n'identifier que *sa tentative*.
    """
    key = uuid4().hex
    refused = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token, key),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "100.00",
            "allocations": [{"debt_id": str(uuid4()), "amount": "100.00"}],
        },
    )
    assert refused.status_code == 404, refused.text

    accepted = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token, key),
        json={"direction": "inflow", "method": "cash", "amount": "100.00"},
    )
    assert accepted.status_code == 201, accepted.text


def test_two_concurrent_requests_with_the_same_key_write_once(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """La seconde attend la première, puis rejoue sa réponse. Un seul paiement.

    Le test **provoque** la fenêtre au lieu de courir après : la première
    transaction réserve la clé puis attend un signal avant de valider, ce qui
    garantit que la seconde se présente pendant qu'elle est encore ouverte.

    Aucun verrou applicatif n'intervient : c'est `idempotency_keys_key_uq` qui
    sérialise, et PostgreSQL qui fait patienter la seconde insertion jusqu'au
    dénouement de la première.
    """
    key = uuid4().hex
    endpoint = "POST /api/v1/payments"
    reserved = threading.Event()
    may_commit = threading.Event()

    def first() -> str:
        with tenant_transaction(
            tenant_a.ctx, session_factory=concurrent_session_factory
        ) as session:
            assert idempotency.reserve(session, tenant_a.ctx, key=key, endpoint=endpoint) is None
            session.execute(
                text(
                    "INSERT INTO payments "
                    "(id, company_id, direction, method, amount, reference, created_by) "
                    "VALUES (:id, :company_id, 'inflow', 'cash', 500.00, :reference, "
                    "        :created_by)"
                ),
                {
                    "id": uuid4(),
                    "company_id": tenant_a.company_id,
                    "reference": key,
                    "created_by": tenant_a.user_id,
                },
            )
            idempotency.record(
                session, tenant_a.ctx, key=key, status_code=201, body={"origin": "première"}
            )
            reserved.set()
            may_commit.wait(timeout=10)
        return "écrit"

    def second() -> str:
        reserved.wait(timeout=10)
        with tenant_transaction(
            tenant_a.ctx, session_factory=concurrent_session_factory
        ) as session:
            # L'INSERT ci-dessous bloque : la clé est prise par une transaction
            # encore ouverte. Le signal est donné juste avant, sans quoi la
            # première attendrait indéfiniment le COMMIT de personne.
            may_commit.set()
            replay = idempotency.reserve(session, tenant_a.ctx, key=key, endpoint=endpoint)
        assert replay is not None, "la seconde requête aurait dû trouver la clé prise"
        assert replay.body == {"origin": "première"}
        return "rejoué"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(future.result() for future in (pool.submit(first), pool.submit(second)))

    assert outcomes == ["rejoué", "écrit"] or outcomes == ["écrit", "rejoué"]

    with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session:
        written = session.execute(
            text("SELECT count(*) FROM payments WHERE reference = :reference"),
            {"reference": key},
        ).scalar_one()
    assert written == 1, "deux requêtes de même clé ne produisent qu'un paiement"
