"""Une entreprise dont le gérant n'a qu'un téléphone (`create-company --manager-phone`).

Le gérant naît par la même façade que l'écran Personnes (`users_service.create_user`) :
numéro ramené à ses chiffres par `normalise_phone` (ADR 0074), même unicité par
entreprise, mêmes messages. Rien n'est écrit si l'identité est refusée.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.cli import create_company, main
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.rbac.matrix import MANAGER
from tests.conftest import TEST_PASSWORD, auth_headers

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/auth/login"


def _slug() -> str:
    return f"tel-{uuid4().hex[:10]}"


def _national() -> str:
    """Numéro national à neuf chiffres, propre à chaque test (la base de test persiste)."""
    return "77" + str(uuid4().int)[:7]


def _spaced(national: str) -> str:
    return f"{national[:2]} {national[2:5]} {national[5:7]} {national[7:]}"


def _create(slug: str, **identity: str | None) -> tuple[UUID, UUID]:
    company_id, manager_id = create_company(
        name="Boutique par téléphone",
        slug=slug,
        manager_name="Fatou Sarr",
        password=TEST_PASSWORD,
        currency="XOF",
        timezone="Africa/Dakar",
        **identity,
    )
    return UUID(company_id), UUID(manager_id)


def _login(client: TestClient, slug: str, identifier: str) -> Any:
    return client.post(
        LOGIN, json={"company_slug": slug, "identifier": identifier, "password": TEST_PASSWORD}
    )


def _company_exists(platform_session_factory: sessionmaker[Any], slug: str) -> bool:
    """Par le rôle de l'administration : la RLS FORCE cache tout au propriétaire, et
    aucun contexte tenant ne voit une entreprise dont on ignore l'identifiant."""
    with platform_session_factory() as session:
        return bool(
            session.execute(
                text("SELECT count(*) FROM companies WHERE slug = :slug"), {"slug": slug}
            ).scalar_one()
        )


def _rows_in_tenant(
    session_factory: sessionmaker[Any], company_id: UUID, sql: str, **params: Any
) -> list[Any]:
    """Lecture **à travers la RLS**, dans le contexte de l'entreprise."""
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        return list(session.execute(text(sql), params).all())


def test_a_manager_with_only_a_phone_logs_in_with_any_spelling(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    slug, national = _slug(), _national()

    company_id, manager_id = _create(slug, manager_phone=f"+221 {_spaced(national)}")

    [row] = _rows_in_tenant(
        session_factory,
        company_id,
        "SELECT email, phone, must_change_password FROM users WHERE id = :id",
        id=manager_id,
    )
    assert row.email is None
    assert row.phone == national
    assert row.must_change_password is False

    for spelling in (_spaced(national), f"+221 {_spaced(national)}", f"221{national}"):
        response = _login(api_client, slug, spelling)
        assert response.status_code == 200, (spelling, response.text)
        me = api_client.get(
            "/api/v1/auth/me", headers=auth_headers(response.json()["access_token"])
        ).json()
        assert me["user"]["id"] == str(manager_id), spelling
        assert me["company"]["id"] == str(company_id), spelling
        assert MANAGER in {role["name"] for role in me["roles"]}


def test_the_manager_role_is_audited_with_the_manager_as_author(
    session_factory: sessionmaker[Any],
) -> None:
    """L'auteur de l'audit est le gérant, créé dans la même transaction (FK satisfaite)."""
    company_id, manager_id = _create(_slug(), manager_phone=_national())

    rows = _rows_in_tenant(
        session_factory,
        company_id,
        "SELECT actor_user_id, entity_id FROM audit_logs WHERE entity_table = 'user_roles'",
    )
    assert [(row.actor_user_id, row.entity_id) for row in rows] == [(manager_id, manager_id)]


@pytest.mark.parametrize(
    ("identity", "message"),
    [
        ({}, "Donnez un e-mail ou un numéro de téléphone."),
        ({"manager_email": " ", "manager_phone": " "}, "Donnez un e-mail ou un numéro"),
        ({"manager_phone": "12"}, "Ce numéro de téléphone n'est pas valide."),
        ({"manager_email": "pas-un-email"}, "Adresse e-mail invalide"),
    ],
)
def test_a_refused_identity_creates_nothing(
    platform_session_factory: sessionmaker[Any], identity: dict[str, str], message: str
) -> None:
    slug = _slug()

    with pytest.raises(SystemExit) as refused:
        _create(slug, **identity)

    assert message in str(refused.value.code)
    assert not _company_exists(platform_session_factory, slug)


def test_the_command_line_requires_an_email_or_a_phone(
    platform_session_factory: sessionmaker[Any],
) -> None:
    slug = _slug()
    argv = ["create-company", "--name", "Sans contact", "--slug", slug, "--manager-name", "Awa"]

    with pytest.raises(SystemExit) as refused:
        main([*argv, "--password", TEST_PASSWORD])

    assert "Donnez un e-mail ou un numéro de téléphone." in str(refused.value.code)
    assert not _company_exists(platform_session_factory, slug)


def test_the_command_line_prints_the_phone_to_log_in_with(
    platform_session_factory: sessionmaker[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    slug, national = _slug(), _national()
    argv = ["create-company", "--name", "Par téléphone", "--slug", slug, "--manager-name", "Awa"]

    assert main([*argv, "--manager-phone", f"00221{national}", "--password", TEST_PASSWORD]) == 0

    assert f"slug={slug} téléphone={national}" in capsys.readouterr().out
    assert _company_exists(platform_session_factory, slug)


def test_the_manager_phone_is_taken_for_the_people_screen(api_client: TestClient) -> None:
    """Le numéro posé par la commande compte dans l'unicité de l'écran Personnes."""
    slug, national = _slug(), _national()
    _create(slug, manager_phone=national)
    token = _login(api_client, slug, national).json()["access_token"]

    twice = api_client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={"full_name": "Homonyme", "phone": f"+221 {_spaced(national)}"},
    )

    assert twice.status_code == 422, twice.text
    assert (
        twice.json()["error"]["message"]
        == "Un compte utilise déjà ce numéro dans cette entreprise."
    )


def test_the_same_phone_in_two_companies_gives_two_separate_managers(
    api_client: TestClient,
) -> None:
    national = _national()
    slug_a, slug_b = _slug(), _slug()
    company_a, manager_a = _create(slug_a, manager_phone=national)
    company_b, manager_b = _create(slug_b, manager_phone=_spaced(national))
    assert manager_a != manager_b

    token_a = _login(api_client, slug_a, national).json()["access_token"]
    token_b = _login(api_client, slug_b, national).json()["access_token"]
    me_a = api_client.get("/api/v1/auth/me", headers=auth_headers(token_a)).json()
    me_b = api_client.get("/api/v1/auth/me", headers=auth_headers(token_b)).json()
    assert (me_a["user"]["id"], me_a["company"]["id"]) == (str(manager_a), str(company_a))
    assert (me_b["user"]["id"], me_b["company"]["id"]) == (str(manager_b), str(company_b))

    seen_by_a = api_client.get("/api/v1/users", headers=auth_headers(token_a)).json()["items"]
    assert [user["id"] for user in seen_by_a] == [str(manager_a)]
    other = api_client.get(f"/api/v1/users/{manager_b}", headers=auth_headers(token_a))
    assert other.status_code == 404
