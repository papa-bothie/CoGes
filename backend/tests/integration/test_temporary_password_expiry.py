"""Échéance du mot de passe provisoire (ADR 0078, lot A1).

Le provisoire est connu de qui l'a donné : il ne doit pas rester une porte ouverte.
48 h après avoir été posé, il ne connecte plus ; la personne en demande un nouveau.

L'échéance est reculée **en base** (`coges_app`, à travers la RLS) plutôt que l'horloge
de l'application : la règle se lit à l'heure réelle, comme les jetons.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    read_scalar_in_tenant,
)

pytestmark = pytest.mark.integration

EXPIRED_MESSAGE = "Ce mot de passe provisoire a expiré. Demandez-en un nouveau au gérant."


def _fresh(client: TestClient) -> tuple[DemoCompany, str]:
    company = _create_demo_company(f"lot-a1-{uuid4().hex[:8]}")
    return company, login_token(client, company)


def _seller_role(client: TestClient, token: str) -> str:
    roles = client.get("/api/v1/roles?page_size=50", headers=auth_headers(token)).json()
    return str(next(role["id"] for role in roles["items"] if role["name"] == "vendeur"))


def _add(client: TestClient, token: str, phone: str) -> dict[str, Any]:
    created = client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={"full_name": "Awa Ndiaye", "phone": phone, "role_ids": [_seller_role(client, token)]},
    )
    assert created.status_code == 201, created.text
    result: dict[str, Any] = created.json()
    return result


def _login(client: TestClient, company: DemoCompany, identifier: str, password: str) -> Any:
    return client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "identifier": identifier, "password": password},
    )


def _set_deadline(
    session_factory: sessionmaker[Any], company: DemoCompany, user_id: str, deadline: datetime
) -> None:
    ctx = TenantContext.bootstrap(company.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        session.execute(
            text("UPDATE users SET must_change_password_until = :deadline WHERE id = :id"),
            {"deadline": deadline, "id": UUID(user_id)},
        )


def _deadline(
    session_factory: sessionmaker[Any], company: DemoCompany, user_id: str
) -> datetime | None:
    value: datetime | None = read_scalar_in_tenant(
        session_factory,
        company.company_id,
        "SELECT must_change_password_until FROM users WHERE id = :id",
        {"id": UUID(user_id)},
    )
    return value


def test_a_temporary_password_is_given_for_48_hours(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    company, token = _fresh(api_client)
    before = datetime.now(UTC)
    awa = _add(api_client, token, "770001122")
    deadline = _deadline(session_factory, company, awa["id"])
    assert deadline is not None
    assert before + timedelta(hours=48) <= deadline <= datetime.now(UTC) + timedelta(hours=48)
    assert awa["must_change_password_until"] is not None


def test_refused_48_hours_and_1_minute_after(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    """Posé il y a 48 h 01 : échéance passée d'une minute."""
    company, token = _fresh(api_client)
    awa = _add(api_client, token, "770001123")
    _set_deadline(session_factory, company, awa["id"], datetime.now(UTC) - timedelta(minutes=1))

    refused = _login(api_client, company, "770001123", awa["temporary_password"])
    assert refused.status_code == 401
    error = refused.json()["error"]
    assert error["code"] == "temporary_password_expired"
    assert error["message"] == EXPIRED_MESSAGE

    audited = read_scalar_in_tenant(
        session_factory,
        company.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_id = :id AND action = 'login' "
        "AND diff -> 'after' ->> 'refused' = 'temporary_password_expired'",
        {"id": UUID(awa["id"])},
    )
    assert audited == 1

    history = api_client.get("/api/v1/analytics/history", headers=auth_headers(token)).json()
    sentences = [item["sentence"] for item in history["items"]]
    assert "Awa n’a pas pu se connecter : mot de passe provisoire expiré" in sentences


def test_accepted_at_47_hours_59(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    """Posé il y a 47 h 59 : encore une minute de validité."""
    company, token = _fresh(api_client)
    awa = _add(api_client, token, "770001124")
    _set_deadline(session_factory, company, awa["id"], datetime.now(UTC) + timedelta(minutes=1))

    accepted = _login(api_client, company, "770001124", awa["temporary_password"])
    assert accepted.status_code == 200, accepted.text


def test_a_wrong_password_on_an_expired_account_reveals_nothing(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    """L'échéance ne se révèle qu'à qui connaît le mot de passe."""
    company, token = _fresh(api_client)
    awa = _add(api_client, token, "770001125")
    _set_deadline(session_factory, company, awa["id"], datetime.now(UTC) - timedelta(hours=1))

    wrong = _login(api_client, company, "770001125", "pas-le-bon-mot-de-passe")
    unknown = _login(api_client, company, "770009999", "pas-le-bon-mot-de-passe")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_the_deadline_is_cleared_when_the_person_chooses_a_password(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    company, token = _fresh(api_client)
    awa = _add(api_client, token, "770001126")
    access = _login(api_client, company, "770001126", awa["temporary_password"])
    assert access.status_code == 200, access.text

    changed = api_client.post(
        "/api/v1/auth/password",
        headers=auth_headers(access.json()["access_token"]),
        json={"current_password": awa["temporary_password"], "new_password": "le-mien-a-moi-1"},
    )
    assert changed.status_code == 204, changed.text
    assert _deadline(session_factory, company, awa["id"]) is None


def test_a_reset_by_the_manager_gives_a_new_48_hours(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    company, token = _fresh(api_client)
    awa = _add(api_client, token, "770001127")
    _set_deadline(session_factory, company, awa["id"], datetime.now(UTC) - timedelta(hours=1))

    reset = api_client.post(
        f"/api/v1/users/{awa['id']}/password",
        headers=auth_headers(token),
        json={"new_password": "donne-par-la-gerante"},
    )
    assert reset.status_code == 200, reset.text
    deadline = _deadline(session_factory, company, awa["id"])
    assert deadline is not None and deadline > datetime.now(UTC) + timedelta(hours=47)
    assert _login(api_client, company, "770001127", "donne-par-la-gerante").status_code == 200


def test_an_older_temporary_password_without_deadline_never_expires(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    """Provisoires antérieurs à la révision 0022 : `NULL`, sans échéance (décision du lot)."""
    company, token = _fresh(api_client)
    awa = _add(api_client, token, "770001128")
    ctx = TenantContext.bootstrap(company.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        session.execute(
            text("UPDATE users SET must_change_password_until = NULL WHERE id = :id"),
            {"id": UUID(awa["id"])},
        )
    assert _login(api_client, company, "770001128", awa["temporary_password"]).status_code == 200


def test_the_database_refuses_a_deadline_without_a_temporary_password(
    session_factory: sessionmaker[Any], company_alpha: DemoCompany
) -> None:
    """`users_temp_password_coherent` : une échéance sans obligation n'a pas de sens."""
    from sqlalchemy.exc import IntegrityError

    ctx = TenantContext.bootstrap(company_alpha.company_id)
    with (
        pytest.raises(IntegrityError),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "UPDATE users SET must_change_password_until = now() "
                "WHERE id = :id AND NOT must_change_password"
            ),
            {"id": company_alpha.manager_id},
        )


def test_the_manager_can_draw_a_new_temporary_password(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    """Écran 24b, « Donner un nouveau mot de passe » : corps vide, provisoire tiré."""
    company, token = _fresh(api_client)
    awa = _add(api_client, token, "770001129")
    _set_deadline(session_factory, company, awa["id"], datetime.now(UTC) - timedelta(hours=1))
    assert _login(api_client, company, "770001129", awa["temporary_password"]).status_code == 401

    drawn = api_client.post(
        f"/api/v1/users/{awa['id']}/password", headers=auth_headers(token), json={}
    )
    assert drawn.status_code == 200, drawn.text
    body = drawn.json()
    assert body["must_change_password"] is True
    assert body["must_change_password_until"] is not None
    fresh_password = body["temporary_password"]
    assert fresh_password and fresh_password != awa["temporary_password"]
    assert _login(api_client, company, "770001129", fresh_password).status_code == 200

    listed = api_client.get("/api/v1/users", headers=auth_headers(token)).json()["items"]
    assert all("temporary_password" not in user for user in listed), "rendu une seule fois"
