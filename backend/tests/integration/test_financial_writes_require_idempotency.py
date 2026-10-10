"""Toutes les écritures financières exigent `Idempotency-Key` (ADR 0027, 0039, 0042).

La liste est **fermée** et vérifiée des deux côtés : chaque route qu'elle nomme
refuse une requête sans clé (422 `idempotency_key_required`), et une écriture qui
déplace de l'argent sans y figurer se verrait à la revue de ce fichier.

Trois écritures en sont volontairement absentes (ADR 0042) : l'annulation de vente et
l'abandon de créance, protégés par leur état (409 au second appel, sans effet), et la
modification d'une dépense, un PATCH en valeurs absolues.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import auth_headers

FINANCIAL_WRITES = (
    "/api/v1/payments",
    "/api/v1/payments/{payment_id}/cancel",
    "/api/v1/debts",
    "/api/v1/expenses",
    "/api/v1/sales/{sale_id}/confirm",
    "/api/v1/sales/{sale_id}/returns",
    "/api/v1/sale-returns/{return_id}/refunds",
    "/api/v1/imports/{kind}",
    "/api/v1/inventory/deliveries",
)


def test_every_listed_route_exists() -> None:
    paths = app.openapi()["paths"]
    missing = [path for path in FINANCIAL_WRITES if "post" not in paths.get(path, {})]
    assert missing == []


@pytest.mark.parametrize("path", FINANCIAL_WRITES)
def test_financial_write_without_key_is_refused(
    path: str, app_bound_to_test_database: None, alpha_token: str
) -> None:
    concrete = path.format(payment_id=uuid4(), sale_id=uuid4(), return_id=uuid4(), kind="products")
    # Client nu : `api_client` pose une clé d'office, ce qui masquerait l'absence.
    with TestClient(app) as bare_client:
        response = bare_client.post(concrete, headers=auth_headers(alpha_token), json={})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "idempotency_key_required"
