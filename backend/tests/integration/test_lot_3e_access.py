"""Accès du lot 3e de la phase 15 (ADR 0074) : écrans 24b et 25, conseils 22b et 22c.

* une personne s'ajoute avec un téléphone ou un e-mail ; sans mot de passe, le serveur
  en tire un provisoire lisible, rendu une seule fois ;
* elle se connecte avec son numéro, tapé n'importe comment, ou son e-mail ;
* tant qu'elle n'a pas choisi son mot de passe, seules son identité et le changement de
  mot de passe répondent ;
* « Vente rare » classe les articles en stock par jours sans vente ;
* « la semaine prochaine » répond sans inventer quand rien n'est prévu.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.integration

READABLE = re.compile(r"^[A-Z]+-\d{4}-[A-Z]+$")


def _fresh(client: TestClient) -> tuple[DemoCompany, str]:
    company = _create_demo_company(f"lot-3e-{uuid4().hex[:8]}")
    return company, login_token(client, company)


def _seller_role(client: TestClient, token: str) -> str:
    roles = client.get("/api/v1/roles?page_size=50", headers=auth_headers(token)).json()
    return str(next(role["id"] for role in roles["items"] if role["name"] == "vendeur"))


def _add(client: TestClient, token: str, **body: Any) -> dict[str, Any]:
    created = client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={"full_name": "Modou Sène", "role_ids": [_seller_role(client, token)], **body},
    )
    assert created.status_code == 201, created.text
    result: dict[str, Any] = created.json()
    return result


def _login(client: TestClient, company: DemoCompany, identifier: str, password: str) -> Any:
    return client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "identifier": identifier, "password": password},
    )


def test_a_person_added_by_phone_gets_a_readable_temporary_password(
    api_client: TestClient,
) -> None:
    company, token = _fresh(api_client)
    modou = _add(api_client, token, phone="+221 77 123 45 67")
    assert modou["phone"] == "771234567"
    assert modou["email"] is None
    assert modou["must_change_password"] is True
    temporary = modou["temporary_password"]
    assert READABLE.match(temporary) and len(temporary) >= 12

    # Rendu une seule fois : la relecture ne le donne plus.
    again = api_client.get(f"/api/v1/users/{modou['id']}", headers=auth_headers(token)).json()
    assert "temporary_password" not in again

    for typed in ("77 123 45 67", "771234567", "00221771234567", "+221 77-123-45-67"):
        logged = _login(api_client, company, typed, temporary)
        assert logged.status_code == 200, (typed, logged.text)


def test_until_the_password_is_changed_only_me_and_password_answer(
    api_client: TestClient,
) -> None:
    company, token = _fresh(api_client)
    modou = _add(api_client, token, phone="77 222 33 44")
    seller = _login(api_client, company, "772223344", modou["temporary_password"]).json()[
        "access_token"
    ]

    blocked = api_client.get("/api/v1/products", headers=auth_headers(seller))
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "password_change_required"
    me = api_client.get("/api/v1/auth/me", headers=auth_headers(seller))
    assert me.status_code == 200, me.text
    assert me.json()["user"]["must_change_password"] is True

    def change(current: str, new: str) -> Any:
        return api_client.post(
            "/api/v1/auth/password",
            headers=auth_headers(seller),
            json={"current_password": current, "new_password": new},
        )

    wrong = change("pas-le-bon-mot", "un-tout-nouveau-mot")
    assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "current_password_mismatch"
    same = change(modou["temporary_password"], modou["temporary_password"])
    assert same.status_code == 409 and same.json()["error"]["code"] == "same_password"
    short = change(modou["temporary_password"], "court")
    assert short.status_code == 422, short.text

    done = change(modou["temporary_password"], "mon-mot-de-passe-a-moi")
    assert done.status_code == 204, done.text
    assert api_client.get("/api/v1/products", headers=auth_headers(seller)).status_code == 200
    assert (
        api_client.get("/api/v1/auth/me", headers=auth_headers(seller)).json()["user"][
            "must_change_password"
        ]
        is False
    )
    assert _login(api_client, company, "77 222 33 44", "mon-mot-de-passe-a-moi").status_code == 200


def test_contact_rules(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    _add(api_client, token, phone="77 555 66 77")

    def attempt(**body: Any) -> Any:
        return api_client.post(
            "/api/v1/users",
            headers=auth_headers(token),
            json={"full_name": "Awa Ndiaye", **body},
        )

    assert attempt().status_code == 422
    assert attempt(phone="12").status_code == 422
    duplicate = attempt(phone="+221775556677")
    assert duplicate.status_code == 422, duplicate.text

    # Un mot de passe choisi reste tel quel : rien à changer à la connexion.
    chosen = _add(
        api_client,
        token,
        email=f"awa-{uuid4().hex[:6]}@lot3e.example.com",
        password="un-mot-de-passe-choisi",
    )
    assert chosen["must_change_password"] is False
    assert chosen["temporary_password"] is None


def test_the_email_still_logs_in_and_the_old_field_is_accepted(api_client: TestClient) -> None:
    company, _ = _fresh(api_client)
    assert _login(api_client, company, company.email.upper(), TEST_PASSWORD).status_code == 200
    old = api_client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "email": company.email, "password": TEST_PASSWORD},
    )
    assert old.status_code == 200, old.text
    unknown = _login(api_client, company, "70 000 00 00", TEST_PASSWORD)
    assert unknown.status_code == 401
    unreadable = _login(api_client, company, "abc", TEST_PASSWORD)
    assert unreadable.status_code == 401
    assert unknown.json()["error"]["message"] == unreadable.json()["error"]["message"]


def test_a_password_reset_by_the_manager_must_be_changed(api_client: TestClient) -> None:
    company, token = _fresh(api_client)
    modou = _add(api_client, token, phone="77 888 99 00", password="un-mot-de-passe-choisi")
    reset = api_client.post(
        f"/api/v1/users/{modou['id']}/password",
        headers=auth_headers(token),
        json={"new_password": "donne-par-la-gerante"},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["must_change_password"] is True


# ------------------------------------------------------------------ conseils


def _stocked(client: TestClient, token: str, name: str) -> str:
    created = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={"name": name, "unit_price": "1000", "default_tax_rate": "0"},
    )
    assert created.status_code == 201, created.text
    product_id = str(created.json()["id"])
    stocked = client.post(
        "/api/v1/inventory/movements",
        headers=auth_headers(token),
        json={"product_id": product_id, "type": "initial", "qty_delta": "20", "unit_cost": "600"},
    )
    assert stocked.status_code == 201, stocked.text
    return product_id


def test_rare_sales_rank_articles_in_stock_by_days_without_sale(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    sold = _stocked(api_client, token, "Riz")
    _stocked(api_client, token, "Bougies")
    sale = api_client.post("/api/v1/sales", headers=auth_headers(token), json={}).json()
    api_client.post(
        f"/api/v1/sales/{sale['id']}/items",
        headers=auth_headers(token),
        json={"product_id": sold, "qty": "1"},
    )
    confirmed = api_client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers=write_headers(token),
        json={"paid_amount": "1000", "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    ranking = api_client.get(
        "/api/v1/analytics/products",
        headers=auth_headers(token),
        params={"metric": "days_since_last_sale", "from": "2026-01-01", "to": "2026-01-31"},
    )
    assert ranking.status_code == 200, ranking.text
    body = ranking.json()
    assert body["metric_label"] == "Jours sans vente"
    assert body["unit"] == "jour"
    assert {row["product_name"]: row["value"] for row in body["items"]} == {
        "Riz": "0",
        "Bougies": "0",
    }


def test_next_week_says_nothing_rather_than_inventing(api_client: TestClient) -> None:
    _, token = _fresh(api_client)
    forecast = api_client.get("/api/v1/analytics/next-week", headers=auth_headers(token))
    assert forecast.status_code == 200, forecast.text
    body = forecast.json()
    assert body["enabled"] is True
    assert body["items"] == []
    assert body["as_of"] is None
