"""Plafond d'utilisateurs de l'offre, tenu par la base (ADR 0091, révision 0028).

Les premiers tests attaquent la base directement, sous `coges_app` : un refus qui ne
viendrait que de l'API ne compterait pas. Les derniers vérifient que l'API le dit en
mots (409 `plan_user_limit_reached`), à la création comme à la réactivation.
"""

from __future__ import annotations

import threading
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import sqlstate
from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import _create_demo_company, auth_headers, login_token
from tests.integration.billing_harness import set_subscription, unlimited_plan

pytestmark = pytest.mark.usefixtures("app_bound_to_test_database")


@pytest.fixture
def company(platform_session_factory: sessionmaker[Any]) -> Any:
    """Une entreprise neuve (un gérant actif) sur Starter : trois comptes au plus."""
    shop = _create_demo_company(f"plafond-{uuid4().hex[:8]}")
    set_subscription(platform_session_factory, shop.company_id, plan="starter")
    return shop


def _insert_user(session: Session, company_id: UUID, *, active: bool = True) -> UUID:
    return session.execute(
        text(
            """
            INSERT INTO users (company_id, email, password_hash, full_name, is_active,
                               deactivated_at)
            VALUES (:company_id, :email, 'x', 'Compte de test', :active,
                    CASE WHEN :active THEN NULL ELSE now() END)
            RETURNING id
            """
        ),
        {"company_id": company_id, "email": f"{uuid4().hex[:10]}@test.example", "active": active},
    ).scalar_one()


def _add(session_factory: sessionmaker[Any], company_id: UUID, *, active: bool = True) -> UUID:
    with tenant_transaction(
        TenantContext.bootstrap(company_id), session_factory=session_factory
    ) as session:
        return _insert_user(session, company_id, active=active)


def _set_active(
    session_factory: sessionmaker[Any], company_id: UUID, user_id: UUID, active: bool
) -> None:
    with tenant_transaction(
        TenantContext.bootstrap(company_id), session_factory=session_factory
    ) as session:
        session.execute(
            text(
                "UPDATE users SET is_active = :active, "
                "deactivated_at = CASE WHEN :active THEN NULL ELSE now() END WHERE id = :id"
            ),
            {"active": active, "id": user_id},
        )


def _refused(call: Any) -> None:
    with pytest.raises(DBAPIError) as caught:
        call()
    assert sqlstate(caught.value) == "CG007"
    assert caught.value.orig.diag.message_detail == "3"  # type: ignore[union-attr]


def test_one_below_the_cap_is_accepted_and_the_cap_itself_refused(
    session_factory: sessionmaker[Any], company: Any
) -> None:
    _add(session_factory, company.company_id)
    _add(session_factory, company.company_id)  # 3 comptes actifs : le plafond
    _refused(lambda: _add(session_factory, company.company_id))


def test_an_inactive_account_does_not_count(
    session_factory: sessionmaker[Any], company: Any
) -> None:
    for _ in range(4):
        _add(session_factory, company.company_id, active=False)
    _add(session_factory, company.company_id)
    _add(session_factory, company.company_id)


def test_deactivating_frees_a_seat_and_reactivating_takes_it_back(
    session_factory: sessionmaker[Any], company: Any
) -> None:
    first = _add(session_factory, company.company_id)
    _add(session_factory, company.company_id)
    _set_active(session_factory, company.company_id, first, False)
    newcomer = _add(session_factory, company.company_id)  # repasse sous le plafond
    _refused(lambda: _set_active(session_factory, company.company_id, first, True))
    _set_active(session_factory, company.company_id, newcomer, False)
    _set_active(session_factory, company.company_id, first, True)


def test_a_plan_without_cap_accepts_everyone(
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    owner_engine: Engine,
    company: Any,
) -> None:
    with unlimited_plan(owner_engine) as code:
        set_subscription(platform_session_factory, company.company_id, plan=code)
        for _ in range(12):
            _add(session_factory, company.company_id)


def test_two_creations_racing_for_the_last_seat_let_only_one_through(
    concurrent_session_factory: sessionmaker[Any], company: Any
) -> None:
    """L'abonnement est verrouillé : la seconde attend la première, puis compte juste."""
    _add(concurrent_session_factory, company.company_id)  # 2 actifs, une place
    first = concurrent_session_factory()
    first.execute(
        text("SELECT set_config('app.company_id', :id, true)"), {"id": str(company.company_id)}
    )
    _insert_user(first, company.company_id)  # tient le verrou, sans valider
    outcome: dict[str, BaseException | None] = {}

    def second() -> None:
        try:
            _add(concurrent_session_factory, company.company_id)
            outcome["error"] = None
        except BaseException as exc:  # noqa: BLE001 - rapporté au fil principal
            outcome["error"] = exc

    racer = threading.Thread(target=second)
    racer.start()
    racer.join(timeout=1)
    assert racer.is_alive(), "la seconde création aurait dû attendre le verrou"
    first.commit()
    first.close()
    racer.join(timeout=10)
    error = outcome["error"]
    assert error is not None and sqlstate(error) == "CG007"


# ------------------------------------------------------------------------- API


def test_the_api_names_the_cap_on_creation_and_reactivation(
    api_client: TestClient, session_factory: sessionmaker[Any], company: Any
) -> None:
    headers = auth_headers(login_token(api_client, company))
    created = [
        api_client.post(
            "/api/v1/users",
            headers=headers,
            json={"full_name": f"Vendeur {n}", "email": f"v{n}-{uuid4().hex[:6]}@test.example"},
        )
        for n in range(2)
    ]
    assert [response.status_code for response in created] == [201, 201]

    refused = api_client.post(
        "/api/v1/users",
        headers=headers,
        json={"full_name": "De trop", "email": f"trop-{uuid4().hex[:6]}@test.example"},
    )
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert error["code"] == "plan_user_limit_reached"
    assert error["message"] == (
        "Ce plan autorise 3 utilisateurs maximum. Passez à un palier supérieur pour en ajouter."
    )
    assert error["details"] == {"max_users": 3}

    seller = created[0].json()["id"]
    assert (
        api_client.patch(
            f"/api/v1/users/{seller}", headers=headers, json={"is_active": False}
        ).status_code
        == 200
    )
    _add(session_factory, company.company_id)  # la place libérée est reprise
    again = api_client.patch(f"/api/v1/users/{seller}", headers=headers, json={"is_active": True})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "plan_user_limit_reached"
