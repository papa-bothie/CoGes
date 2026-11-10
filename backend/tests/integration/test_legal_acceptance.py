"""Acceptation des textes légaux (prompt 36, ADR 0117).

* un compte qui n'a pas accepté la version courante ne joint que `/auth/me` et
  `/auth/legal-acceptance`, comme un mot de passe provisoire (ADR 0074) ;
* le mot de passe provisoire passe d'abord, l'acceptation ensuite ;
* la version enregistrée est celle du serveur, pour la personne connectée seulement ;
* l'acceptation est un audit critique, écrit une fois ;
* changer `LEGAL_VERSION` redemande l'acceptation à la requête suivante ;
* l'acceptation d'une entreprise ne se lit ni ne s'écrit depuis une autre.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import text

from app.core import legal
from app.core.legal import LEGAL_VERSION
from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    _create_demo_company,
    accept_legal,
    auth_headers,
    login_token,
    role_id,
)

pytestmark = pytest.mark.integration

ACCEPT = "/api/v1/auth/legal-acceptance"
ME = "/api/v1/auth/me"


def _company() -> DemoCompany:
    return _create_demo_company(f"legal-{uuid4().hex[:8]}")


def _raw_login(client: TestClient, company: DemoCompany, email: str | None = None) -> str:
    """Connexion **sans** acceptation : ce que voit une personne au premier login."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "company_slug": company.slug,
            "email": email or company.email,
            "password": TEST_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def _acceptance(company_id: UUID, user_id: UUID) -> tuple[str | None, Any]:
    with tenant_transaction(TenantContext.bootstrap(company_id)) as session:
        row = session.execute(
            text("SELECT legal_accepted_version, legal_accepted_at FROM users WHERE id = :id"),
            {"id": user_id},
        ).one()
    return row.legal_accepted_version, row.legal_accepted_at


def _audits(company_id: UUID, user_id: UUID) -> list[dict[str, Any]]:
    with tenant_transaction(TenantContext.bootstrap(company_id)) as session:
        rows = session.execute(
            text(
                "SELECT actor_user_id, diff FROM audit_logs "
                "WHERE entity_table = 'users' AND entity_id = :id "
                "AND diff -> 'after' ? 'legal_accepted_version' ORDER BY id"
            ),
            {"id": user_id},
        ).all()
    return [{"actor": row.actor_user_id, "diff": row.diff} for row in rows]


def test_until_accepted_only_me_and_acceptance_answer(api_client: TestClient) -> None:
    company = _company()
    token = _raw_login(api_client, company)

    blocked = api_client.get("/api/v1/products", headers=auth_headers(token))
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "legal_acceptance_required"
    # Une écriture aussi : rien ne passe.
    write = api_client.post("/api/v1/categories", headers=auth_headers(token), json={"name": "X"})
    assert write.json()["error"]["code"] == "legal_acceptance_required"
    # Changer son mot de passe ne fait pas partie des routes ouvertes.
    password = api_client.post(
        "/api/v1/auth/password",
        headers=auth_headers(token),
        json={"current_password": TEST_PASSWORD, "new_password": "un-autre-mot-2026"},
    )
    assert password.json()["error"]["code"] == "legal_acceptance_required"

    me = api_client.get(ME, headers=auth_headers(token))
    assert me.status_code == 200, me.text
    assert me.json()["legal_version"] == LEGAL_VERSION
    assert me.json()["user"]["must_accept_legal"] is True
    assert me.json()["user"]["legal_accepted_version"] is None

    accepted = api_client.post(ACCEPT, headers=auth_headers(token), json={})
    assert accepted.status_code == 204, accepted.text

    assert api_client.get("/api/v1/products", headers=auth_headers(token)).status_code == 200
    me = api_client.get(ME, headers=auth_headers(token)).json()
    assert me["user"]["must_accept_legal"] is False
    assert me["user"]["legal_accepted_version"] == LEGAL_VERSION


def test_the_version_recorded_is_the_servers_and_audited_once(api_client: TestClient) -> None:
    company = _company()
    token = _raw_login(api_client, company)

    # Ni version ni personne venues du client : le corps est vide, tout ajout est refusé.
    for body in ({"version": "2000-01-01"}, {"user_id": str(uuid4())}, {"legal_version": "x"}):
        refused = api_client.post(ACCEPT, headers=auth_headers(token), json=body)
        assert refused.status_code == 422, (body, refused.text)
    assert _acceptance(company.company_id, company.manager_id) == (None, None)

    assert api_client.post(ACCEPT, headers=auth_headers(token), json={}).status_code == 204
    version, at = _acceptance(company.company_id, company.manager_id)
    assert version == LEGAL_VERSION
    assert at is not None

    audits = _audits(company.company_id, company.manager_id)
    assert len(audits) == 1
    assert audits[0]["actor"] == company.manager_id
    assert audits[0]["diff"]["before"] == {"legal_accepted_version": None}
    assert audits[0]["diff"]["after"]["legal_accepted_version"] == LEGAL_VERSION

    # Une seconde fois : rien n'est réécrit, rien n'est audité.
    assert api_client.post(ACCEPT, headers=auth_headers(token), json={}).status_code == 204
    assert _acceptance(company.company_id, company.manager_id) == (version, at)
    assert len(_audits(company.company_id, company.manager_id)) == 1

    history = api_client.get(
        "/api/v1/analytics/history?page_size=50", headers=auth_headers(token)
    ).json()
    assert any("a accepté les conditions" in str(item) for item in history["items"]), history


def test_one_accepts_for_oneself_only(api_client: TestClient) -> None:
    company = _company()
    manager = _raw_login(api_client, company)
    accept_legal(api_client, manager)
    email = f"vendeur-{uuid4().hex[:6]}@{company.slug}.example.com"
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(manager),
        json={
            "email": email,
            "full_name": "Vendeur",
            "password": TEST_PASSWORD,
            "role_ids": [role_id(api_client, manager, "vendeur")],
        },
    )
    assert created.status_code == 201, created.text
    seller_id = UUID(created.json()["id"])

    # Le gérant a accepté : son compte vendeur reste à accepter.
    assert _acceptance(company.company_id, seller_id) == (None, None)
    seller = _raw_login(api_client, company, email)
    blocked = api_client.get("/api/v1/products", headers=auth_headers(seller))
    assert blocked.json()["error"]["code"] == "legal_acceptance_required"

    # Le gérant rejoue l'acceptation : la sienne, déjà faite, rien pour le vendeur.
    assert api_client.post(ACCEPT, headers=auth_headers(manager), json={}).status_code == 204
    assert _acceptance(company.company_id, seller_id) == (None, None)

    assert api_client.post(ACCEPT, headers=auth_headers(seller), json={}).status_code == 204
    assert _acceptance(company.company_id, seller_id)[0] == LEGAL_VERSION
    assert _audits(company.company_id, seller_id)[0]["actor"] == seller_id


def test_temporary_password_first_then_acceptance(api_client: TestClient) -> None:
    company = _company()
    manager = login_token(api_client, company)
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(manager),
        json={
            "phone": "77 444 55 66",
            "full_name": "Awa",
            "role_ids": [role_id(api_client, manager, "vendeur")],
        },
    ).json()
    temporary = created["temporary_password"]
    token = api_client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "identifier": "774445566", "password": temporary},
    ).json()["access_token"]

    me = api_client.get(ME, headers=auth_headers(token)).json()
    assert me["user"]["must_change_password"] is True
    assert me["user"]["must_accept_legal"] is True
    # Le mot de passe d'abord : l'acceptation elle-même attend.
    early = api_client.post(ACCEPT, headers=auth_headers(token), json={})
    assert early.json()["error"]["code"] == "password_change_required"

    changed = api_client.post(
        "/api/v1/auth/password",
        headers=auth_headers(token),
        json={"current_password": temporary, "new_password": "mon-propre-mot-2026"},
    )
    assert changed.status_code == 204, changed.text
    blocked = api_client.get("/api/v1/products", headers=auth_headers(token))
    assert blocked.json()["error"]["code"] == "legal_acceptance_required"
    assert api_client.post(ACCEPT, headers=auth_headers(token), json={}).status_code == 204
    assert api_client.get("/api/v1/products", headers=auth_headers(token)).status_code == 200


def test_a_new_version_asks_everyone_again(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = _company()
    token = login_token(api_client, company)
    assert api_client.get("/api/v1/products", headers=auth_headers(token)).status_code == 200

    monkeypatch.setattr(legal, "LEGAL_VERSION", "2099-01-01")
    # Dès la requête suivante, sans attendre une nouvelle connexion.
    blocked = api_client.get("/api/v1/products", headers=auth_headers(token))
    assert blocked.json()["error"]["code"] == "legal_acceptance_required"
    me = api_client.get(ME, headers=auth_headers(token)).json()
    assert me["legal_version"] == "2099-01-01"
    assert me["user"]["must_accept_legal"] is True
    assert me["user"]["legal_accepted_version"] == LEGAL_VERSION

    assert api_client.post(ACCEPT, headers=auth_headers(token), json={}).status_code == 204
    assert _acceptance(company.company_id, company.manager_id)[0] == "2099-01-01"
    assert api_client.get("/api/v1/products", headers=auth_headers(token)).status_code == 200


def test_acceptance_stays_inside_its_company(api_client: TestClient) -> None:
    alpha, beta = _company(), _company()
    alpha_token = _raw_login(api_client, alpha)
    _raw_login(api_client, beta)
    assert api_client.post(ACCEPT, headers=auth_headers(alpha_token), json={}).status_code == 204

    # Le jeton d'alpha n'a écrit que chez alpha.
    assert _acceptance(alpha.company_id, alpha.manager_id)[0] == LEGAL_VERSION
    assert _acceptance(beta.company_id, beta.manager_id) == (None, None)
    # Depuis le contexte d'alpha, la ligne de beta n'existe pas (RLS).
    with tenant_transaction(TenantContext.bootstrap(alpha.company_id)) as session:
        seen = session.execute(
            text("SELECT count(*) FROM users WHERE id = :id"), {"id": beta.manager_id}
        ).scalar_one()
    assert seen == 0
    # Et l'audit de l'acceptation d'alpha n'est pas lisible chez beta.
    assert _audits(beta.company_id, alpha.manager_id) == []


@pytest.mark.usefixtures("app_bound_to_test_database")
def test_the_constraint_keeps_version_and_date_together() -> None:
    company = _company()
    with (
        pytest.raises(Exception, match="users_legal_acceptance_coherent"),
        tenant_transaction(TenantContext.bootstrap(company.company_id)) as session,
    ):
        session.execute(
            text("UPDATE users SET legal_accepted_version = 'x' WHERE id = :id"),
            {"id": company.manager_id},
        )
