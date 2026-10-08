"""Wave et Orange Money, deux moyens de paiement (ADR 0068).

`mobile_money` reste accepté (paiements d'avant, imports) ; les deux opérateurs se
saisissent et se relisent tels quels, et comptent dans la trésorerie comme l'espèce.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, write_headers

pytestmark = pytest.mark.integration

PAYMENTS = "/api/v1/payments"


@pytest.mark.parametrize("method", ["wave", "orange_money", "mobile_money"])
def test_an_operator_is_recorded_and_read_back(
    api_client: TestClient, alpha_token: str, method: str
) -> None:
    created = api_client.post(
        PAYMENTS,
        headers=write_headers(alpha_token),
        json={"direction": "inflow", "method": method, "amount": "2500"},
    )
    assert created.status_code == 201, created.text
    read = api_client.get(f"{PAYMENTS}/{created.json()['id']}", headers=auth_headers(alpha_token))
    assert read.json()["method"] == method


def test_an_unknown_operator_is_refused(api_client: TestClient, alpha_token: str) -> None:
    response = api_client.post(
        PAYMENTS,
        headers=write_headers(alpha_token),
        json={"direction": "inflow", "method": "free_money", "amount": "2500"},
    )
    assert response.status_code == 422
