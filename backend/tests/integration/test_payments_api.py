"""L'encaissement et le décaissement vus par l'API (Diagramme 5).

Ce que ces tests tiennent :

* un versement s'impute sur **plusieurs** dettes en une transaction ;
* le sur-paiement est refusé deux fois, pour deux raisons différentes — la demande
  qui se contredit (422) et l'état qui refuse (409) ;
* le sens financier et la nature de la dette doivent s'accorder ;
* `payment.received` n'est émis que pour un encaissement ; `debt.settled` l'est
  pour chaque dette éteinte.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant, write_headers

pytestmark = pytest.mark.integration

ENDPOINT = "/api/v1/payments"


def _customer(client: TestClient, token: str) -> str:
    created = client.post(
        "/api/v1/customers",
        headers=auth_headers(token),
        json={"name": f"Client {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _supplier(client: TestClient, token: str) -> str:
    created = client.post(
        "/api/v1/suppliers",
        headers=auth_headers(token),
        json={"name": f"Fournisseur {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _debt(client: TestClient, token: str, *, principal: str, **party: str) -> str:
    created = client.post(
        "/api/v1/debts",
        headers=write_headers(token),
        json={"principal": principal, **party},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _events(
    session_factory: sessionmaker[Any], company_id: UUID, event_type: str, aggregate_id: UUID
) -> int:
    return int(
        read_scalar_in_tenant(
            session_factory,
            company_id,
            "SELECT count(*) FROM business_events "
            " WHERE event_type = :event_type AND aggregate_id = :aggregate_id",
            {"event_type": event_type, "aggregate_id": aggregate_id},
        )
    )


def test_one_payment_settles_two_debts(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Un versement de 1 000 réparti 600 / 400 éteint les deux créances.

    C'est le cas que `payment_allocations` existe pour représenter : un client
    règle plusieurs factures d'un coup, et chaque dette sait ce qu'elle a reçu.
    """
    customer_id = _customer(api_client, alpha_token)
    first = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="600.00"
    )
    second = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="400.00"
    )

    created = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "1000.00",
            "allocations": [
                {"debt_id": first, "amount": "600.00"},
                {"debt_id": second, "amount": "400.00"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["amount"] == "1000.00"
    assert len(body["allocations"]) == 2

    for debt_id in (first, second):
        detail = api_client.get(f"/api/v1/debts/{debt_id}", headers=auth_headers(alpha_token))
        assert detail.json()["status"] == "paid"
        assert detail.json()["balance"] == "0.00"
        assert detail.json()["closed_at"] is not None
        assert (
            _events(session_factory, company_alpha.company_id, "debt.settled", UUID(debt_id)) == 1
        ), "chaque dette éteinte s'annonce"

    assert (
        _events(
            session_factory, company_alpha.company_id, "payment.received", UUID(str(body["id"]))
        )
        == 1
    )


def test_allocations_cannot_exceed_the_payment_itself(
    api_client: TestClient, alpha_token: str
) -> None:
    """422 : la demande se contredit, sans qu'il faille lire la moindre dette."""
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="5000.00"
    )

    refused = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "500.00",
            "allocations": [{"debt_id": debt_id, "amount": "900.00"}],
        },
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "allocations_exceed_payment"


def test_an_allocation_cannot_exceed_the_balance_of_its_debt(
    api_client: TestClient, alpha_token: str
) -> None:
    """409 : la demande est bien formée, c'est l'état de la dette qui refuse.

    Sur-paiement refusé par défaut (Diagramme 5) : il n'existe ni avoir, ni solde
    créditeur en V1. Le trop-perçu se règle en rendant l'argent.
    """
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="300.00"
    )

    refused = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "1000.00",
            "allocations": [{"debt_id": debt_id, "amount": "500.00"}],
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "allocation_exceeds_balance"
    assert refused.json()["error"]["details"]["balance"] == "300.00"


def test_the_same_debt_cannot_be_allocated_twice_in_one_payment(
    api_client: TestClient, alpha_token: str
) -> None:
    """`pa_pair_uq` l'interdit en base ; le schéma le dit avant, et plus clairement."""
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="1000.00"
    )

    refused = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "400.00",
            "allocations": [
                {"debt_id": debt_id, "amount": "200.00"},
                {"debt_id": debt_id, "amount": "200.00"},
            ],
        },
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "duplicate_allocation"


def test_a_customer_debt_is_not_settled_by_an_outflow(
    api_client: TestClient, alpha_token: str
) -> None:
    """Une créance s'éteint quand l'argent **entre**, pas quand il sort.

    Aucun trigger ne porte cette règle — `allocation_check` ignore `direction`,
    et il le doit : la compensation d'un retour en dépend (ADR 0024). Le refus est
    donc applicatif, et assumé comme tel.
    """
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="1000.00"
    )

    refused = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "outflow",
            "method": "cash",
            "amount": "400.00",
            "allocations": [{"debt_id": debt_id, "amount": "400.00"}],
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "allocation_direction_mismatch"


def test_a_supplier_debt_is_settled_by_an_outflow(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Le sens inverse, et l'absence d'événement qui va avec.

    Aucun `payment.sent` dans la liste fermée des neuf types (ADR 0008 et 0026) :
    un décaissement n'émet rien plutôt que d'emprunter le nom d'une recette.
    """
    supplier_id = _supplier(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="supplier", supplier_id=supplier_id, principal="800.00"
    )

    paid = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "outflow",
            "method": "bank_transfer",
            "amount": "800.00",
            "allocations": [{"debt_id": debt_id, "amount": "800.00"}],
        },
    )
    assert paid.status_code == 201, paid.text
    payment_id = UUID(str(paid.json()["id"]))

    assert _events(session_factory, company_alpha.company_id, "payment.received", payment_id) == 0
    assert _events(session_factory, company_alpha.company_id, "debt.settled", UUID(debt_id)) == 1


def test_a_payment_cannot_be_recorded_as_a_compensation(
    api_client: TestClient, alpha_token: str
) -> None:
    """`offset` n'est pas un moyen de payer : il ne se saisit pas (ADR 0024)."""
    refused = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={"direction": "inflow", "method": "offset", "amount": "100.00"},
    )
    assert refused.status_code == 422, refused.text


def test_a_payment_dated_in_the_future_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """Un encaissement de demain n'est pas un encaissement, c'est une prévision."""
    refused = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "100.00",
            "paid_at": "2099-01-01T10:00:00Z",
        },
    )
    assert refused.status_code == 422, refused.text


def test_a_payment_on_an_unknown_debt_is_not_found(
    api_client: TestClient, alpha_token: str
) -> None:
    """Une dette inexistante donne 404, comme celle d'un autre tenant."""
    refused = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "100.00",
            "allocations": [{"debt_id": str(uuid4()), "amount": "100.00"}],
        },
    )
    assert refused.status_code == 404, refused.text


def test_a_payment_on_an_unknown_expense_is_not_found(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le contexte `expense_id` est validé par la clé étrangère composite.

    Finance ne peut pas interroger Expenses — ce module est **au-dessus** d'elle
    dans l'ordre des dépendances. C'est `payments_expense_fk` qui refuse, et le
    service traduit sa violation en 404.
    """
    refused = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "outflow",
            "method": "cash",
            "amount": "100.00",
            "expense_id": str(uuid4()),
        },
    )
    assert refused.status_code == 404, refused.text


def test_two_payments_cannot_share_a_reference(api_client: TestClient, alpha_token: str) -> None:
    """`payments_ref_uq` : un numéro de bordereau ne désigne qu'un versement."""
    reference = f"BORD-{uuid4().hex[:10]}"
    body = {
        "direction": "inflow",
        "method": "cheque",
        "amount": "100.00",
        "reference": reference,
    }
    first = api_client.post(ENDPOINT, headers=write_headers(alpha_token), json=body)
    assert first.status_code == 201, first.text

    second = api_client.post(ENDPOINT, headers=write_headers(alpha_token), json=body)
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "payment_reference_taken"


def test_payments_are_listed_and_filtered_by_direction(
    api_client: TestClient, alpha_token: str
) -> None:
    """La liste sépare ce qui est entré de ce qui est sorti."""
    marker = f"REF-{uuid4().hex[:10]}"
    created = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "outflow",
            "method": "cash",
            "amount": "250.00",
            "reference": marker,
        },
    )
    assert created.status_code == 201, created.text
    payment_id = str(created.json()["id"])

    outflows = api_client.get(
        "/api/v1/payments?direction=outflow&page_size=100", headers=auth_headers(alpha_token)
    )
    assert outflows.status_code == 200, outflows.text
    assert payment_id in [item["id"] for item in outflows.json()["items"]]

    inflows = api_client.get(
        "/api/v1/payments?direction=inflow&page_size=100", headers=auth_headers(alpha_token)
    )
    assert payment_id not in [item["id"] for item in inflows.json()["items"]]

    detail = api_client.get(f"/api/v1/payments/{payment_id}", headers=auth_headers(alpha_token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["reference"] == marker


def test_recording_a_payment_is_audited(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Audit critique, avec les affectations : on sait *ce que* le versement a soldé."""
    customer_id = _customer(api_client, alpha_token)
    debt_id = _debt(
        api_client, alpha_token, party_type="customer", customer_id=customer_id, principal="500.00"
    )

    created = api_client.post(
        ENDPOINT,
        headers=write_headers(alpha_token),
        json={
            "direction": "inflow",
            "method": "cash",
            "amount": "500.00",
            "allocations": [{"debt_id": debt_id, "amount": "500.00"}],
        },
    )
    assert created.status_code == 201, created.text

    allocated = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT diff -> 'after' -> 'allocations' ->> 0 FROM audit_logs "
        " WHERE entity_table = 'payments' AND entity_id = :id",
        {"id": UUID(str(created.json()["id"]))},
    )
    assert debt_id in allocated
