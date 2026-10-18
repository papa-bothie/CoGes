"""L'e-mail ou le téléphone d'un compte supprimé se réutilise (prompt 21, P1.6 ; ADR 0087).

`users_email_uq` et `users_phone_uq` étaient des UNIQUE (company_id, email|phone) sans
filtre sur `deleted_at`, alors que la vérification du service ignore les comptes
supprimés : elle passait, l'INSERT échouait, et l'`IntegrityError` non traduite
donnait une 500. Désormais l'unicité ne porte que sur les comptes vivants (index
partiels), et toute violation d'unicité restante — une course — rend 422.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.database import create_app_engine
from app.core.errors import ValidationFailedError
from app.core.tenancy import tenant_transaction
from app.modules.users import service as users_service
from app.modules.users.schemas import UserCreate
from tests.conftest import DemoCompany, auth_headers
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

USERS = "/api/v1/users"
FIRST_PASSWORD = "ancien-" + "x" * 12
SECOND_PASSWORD = "nouveau-" + "y" * 12


def _create(client: TestClient, token: str, **identity: str) -> Any:
    return client.post(
        USERS,
        headers=auth_headers(token),
        json={"full_name": "Awa Ndiaye", **identity},
    )


def _phone() -> str:
    return "77" + str(uuid4().int)[:7]


@pytest.mark.parametrize("identifier", ["email", "phone"])
def test_a_deleted_account_frees_its_identifier(
    api_client: TestClient, alpha_token: str, identifier: str
) -> None:
    value = f"awa-{uuid4().hex[:8]}@example.com" if identifier == "email" else _phone()
    first = _create(api_client, alpha_token, **{identifier: value})
    assert first.status_code == 201, first.text
    deleted = api_client.delete(f"{USERS}/{first.json()['id']}", headers=auth_headers(alpha_token))
    assert deleted.status_code == 200, deleted.text

    again = _create(api_client, alpha_token, **{identifier: value})

    assert again.status_code == 201, again.text
    assert again.json()["id"] != first.json()["id"]


@pytest.mark.parametrize("identifier", ["email", "phone"])
def test_a_live_account_still_holds_its_identifier(
    api_client: TestClient, alpha_token: str, identifier: str
) -> None:
    value = f"awa-{uuid4().hex[:8]}@example.com" if identifier == "email" else _phone()
    assert _create(api_client, alpha_token, **{identifier: value}).status_code == 201

    twice = _create(api_client, alpha_token, **{identifier: value})

    assert twice.status_code == 422, twice.text


def test_login_reaches_the_live_account_not_the_deleted_one(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """`auth_lookup` ignore le compte supprimé quand un homonyme vivant existe."""
    email = f"awa-{uuid4().hex[:8]}@example.com"
    old = _create(api_client, alpha_token, email=email, password=FIRST_PASSWORD)
    assert old.status_code == 201, old.text
    api_client.delete(f"{USERS}/{old.json()['id']}", headers=auth_headers(alpha_token))
    new = _create(api_client, alpha_token, email=email, password=SECOND_PASSWORD)
    assert new.status_code == 201, new.text

    def login(password: str) -> Any:
        return api_client.post(
            "/api/v1/auth/login",
            json={"company_slug": company_alpha.slug, "email": email, "password": password},
        )

    assert login(FIRST_PASSWORD).status_code == 401
    accepted = login(SECOND_PASSWORD)
    assert accepted.status_code == 200, accepted.text
    me = api_client.get("/api/v1/auth/me", headers=auth_headers(accepted.json()["access_token"]))
    assert me.json()["user"]["id"] == new.json()["id"]


@pytest.fixture
def concurrent_session_factory(
    migrated_database: str, database_urls: tuple[str, str]
) -> Iterator[sessionmaker[Any]]:
    _, app_url = database_urls
    engine: Engine = create_app_engine(app_url, pool_size=2, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()


def test_two_simultaneous_creations_give_422_not_500(
    concurrent_session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """La première tient la clé sans valider ; la seconde passe la vérification du
    service, bute sur l'index, puis reçoit l'erreur d'unicité au COMMIT de la première."""
    email = f"course-{uuid4().hex[:8]}@example.com"
    payload = UserCreate(full_name="Course", email=email, password=FIRST_PASSWORD)

    def second() -> None:
        with tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as s:
            users_service.create_user(s, tenant_a.ctx, payload)

    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        tenant_transaction(tenant_a.ctx, session_factory=concurrent_session_factory) as session,
    ):
        users_service.create_user(session, tenant_a.ctx, payload)
        racing: Future[None] = pool.submit(second)
        # La seconde a le temps d'atteindre l'index avant le COMMIT de la première.
        with pytest.raises(TimeoutError):
            racing.result(timeout=1)

    error = racing.exception(timeout=10)
    assert isinstance(error, ValidationFailedError), f"attendu 422, obtenu {error!r}"
