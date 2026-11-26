"""Offres Pro et Business, droits par offre, droits acquis (prompt 41, ADR 0132).

La base d'abord : catalogue posé par la révision 0043, recopie des boutiques existantes,
`current_plan()` cloisonnée, plafond acquis tenu par `users_plan_limit()` (y compris en
concurrence). Puis l'API : `require_feature("imports")` sur toutes les routes d'import
(403 `plan_feature_required`), exports ouverts, bloc `plan` de `/auth/me`,
`GET /subscription` réservé au gérant.
"""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core import plan_features
from app.core.errors import sqlstate
from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import (
    BACKEND_ROOT,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    create_user_with_role,
    login_token,
)
from tests.integration.billing_harness import set_subscription, subscription_row

pytestmark = pytest.mark.usefixtures("app_bound_to_test_database")

#: La source partagée du front (vitrine et « Mon abonnement ») : un seul endroit.
OFFERS_JSON = BACKEND_ROOT.parent / "frontend" / "content" / "offres.json"

IMPORT_ROUTES = (
    ("POST", "/api/v1/imports/customers?dry_run=true"),
    ("GET", "/api/v1/imports/products/template"),
)


@pytest.fixture
def shop() -> DemoCompany:
    """Une boutique neuve : essai Pro (révision 0043)."""
    return _create_demo_company(f"offre-{uuid4().hex[:8]}")


def _insert_user(session: Session, company_id: UUID) -> UUID:
    return session.execute(
        text(
            "INSERT INTO users (company_id, email, password_hash, full_name, is_active) "
            "VALUES (:company_id, :email, 'x', 'Compte de test', true) RETURNING id"
        ),
        {"company_id": company_id, "email": f"{uuid4().hex[:10]}@test.example"},
    ).scalar_one()


def _add_user(session_factory: sessionmaker[Any], company_id: UUID) -> UUID:
    with tenant_transaction(
        TenantContext.bootstrap(company_id), session_factory=session_factory
    ) as session:
        return _insert_user(session, company_id)


def _plan_of(session_factory: sessionmaker[Any], company_id: UUID | None) -> list[Any]:
    """`current_plan()` sous `coges_app`, dans le contexte de `company_id` (ou sans)."""
    session = session_factory()
    try:
        if company_id is not None:
            session.execute(
                text("SELECT set_config('app.company_id', :id, true)"), {"id": str(company_id)}
            )
        return list(session.execute(text("SELECT * FROM current_plan()")))
    finally:
        session.rollback()
        session.close()


def _call(client: TestClient, token: str, method: str, path: str) -> Any:
    headers = {**auth_headers(token), "Idempotency-Key": uuid4().hex}
    if method == "POST":
        return client.post(
            path, headers=headers, files={"file": ("c.csv", b"Nom\nAwa\n", "text/csv")}
        )
    return client.get(path, headers=headers)


# ------------------------------------------------------------------ catalogue


def test_the_catalogue_is_written_in_the_database(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        rows = {
            row.code: row
            for row in connection.execute(
                text(
                    "SELECT code, name, price_fcfa, annual_price_fcfa, max_users, features, "
                    "is_orderable FROM plans WHERE code IN ('starter', 'business', 'premium')"
                )
            )
        }
    assert {code: (row.name, row.max_users, row.is_orderable) for code, row in rows.items()} == {
        "starter": ("Pro", 3, True),
        "business": ("Business", 7, True),
        "premium": ("Premium", 10, False),
    }
    assert rows["premium"].price_fcfa is None and rows["premium"].annual_price_fcfa is None
    for code in ("starter", "business"):
        price, annual = rows[code].price_fcfa, rows[code].annual_price_fcfa
        assert annual == price * 12 * Decimal("0.9"), code
    assert (rows["starter"].price_fcfa, rows["starter"].annual_price_fcfa) == (4900, 52920)
    assert (rows["business"].price_fcfa, rows["business"].annual_price_fcfa) == (9900, 106920)
    for code, row in rows.items():
        assert sorted(row.features) == sorted(plan_features.PLAN_FEATURES[code]), code


def test_the_catalogue_of_codes_is_closed() -> None:
    assert len(set(plan_features.CATALOGUE)) == 13
    assert set(plan_features.COMMON_FEATURES).isdisjoint(plan_features.BUSINESS_FEATURES)
    assert set(plan_features.BUSINESS_FEATURES) == plan_features.GRANTABLE
    assert set(plan_features.PLAN_FEATURES["premium"]) >= set(
        plan_features.PLAN_FEATURES["business"]
    )
    assert "imports" not in plan_features.PLAN_FEATURES["starter"]


def test_the_front_source_matches_the_database(owner_engine: Engine) -> None:
    """Les prix de la vitrine et de « Mon abonnement » sont ceux de la révision 0043."""
    offers = json.loads(Path(OFFERS_JSON).read_text(encoding="utf-8"))
    with owner_engine.connect() as connection:
        rows = {
            row.code: row
            for row in connection.execute(
                text("SELECT code, name, price_fcfa, annual_price_fcfa, max_users FROM plans")
            )
        }
    by_code = {offer["code"]: offer for offer in offers["plans"]}
    assert set(by_code) == {"starter", "business", "premium"}
    for code, offer in by_code.items():
        row = rows[code]
        assert offer["name"] == row.name
        assert offer["maxUsers"] == row.max_users
        assert offer["monthly"] == (None if row.price_fcfa is None else int(row.price_fcfa))
        assert offer["annual"] == (
            None if row.annual_price_fcfa is None else int(row.annual_price_fcfa)
        )
        assert sorted(offer["features"]) == sorted(plan_features.PLAN_FEATURES[code])
    assert offers["trialDays"] == 30
    assert offers["trialPlan"] == "starter"
    assert offers["trialPrice"] == 0


# -------------------------------------------------------------- current_plan()


def test_a_new_company_starts_a_pro_trial_without_imports(
    session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    [row] = _plan_of(session_factory, shop.company_id)
    assert (row.plan_code, row.plan_name, row.status, row.max_users, row.active_users) == (
        "starter",
        "Pro",
        "trial",
        3,
        1,
    )
    assert row.is_license is False
    assert row.extra_features == []
    assert sorted(row.features) == sorted(plan_features.COMMON_FEATURES)


def test_current_plan_never_reads_another_company(
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    other = _create_demo_company(f"offre-autre-{uuid4().hex[:8]}")
    set_subscription(platform_session_factory, other.company_id, plan="business")
    assert _plan_of(session_factory, None) == []
    [mine] = _plan_of(session_factory, shop.company_id)
    [theirs] = _plan_of(session_factory, other.company_id)
    assert (mine.plan_code, theirs.plan_code) == ("starter", "business")


def test_current_plan_belongs_to_the_billing_role(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT pg_get_userbyid(proowner) AS owner, prosecdef FROM pg_proc "
                "WHERE proname = 'current_plan'"
            )
        ).one()
    assert (row.owner, row.prosecdef) == ("coges_billing", True)


def test_acquired_features_are_added_to_the_plan(
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    set_subscription(
        platform_session_factory, shop.company_id, extra_features=json.dumps(["imports"])
    )
    [row] = _plan_of(session_factory, shop.company_id)
    assert "imports" in row.features and row.extra_features == ["imports"]
    assert len(row.features) == len(set(row.features))


# ------------------------------------------------------------- plafond acquis


def test_an_override_raises_the_cap_in_the_database(
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    set_subscription(platform_session_factory, shop.company_id, max_users_override=5)
    for _ in range(4):
        _add_user(session_factory, shop.company_id)  # 5 actifs : le plafond acquis
    with pytest.raises(DBAPIError) as caught:
        _add_user(session_factory, shop.company_id)
    assert sqlstate(caught.value) == "CG007"
    assert caught.value.orig.diag.message_detail == "5"  # type: ignore[union-attr]

    set_subscription(platform_session_factory, shop.company_id, max_users_override=None)
    [row] = _plan_of(session_factory, shop.company_id)
    assert (row.max_users, row.active_users) == (3, 5)


def test_two_creations_racing_for_the_last_acquired_seat_let_only_one_through(
    concurrent_session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    set_subscription(platform_session_factory, shop.company_id, max_users_override=4)
    _add_user(concurrent_session_factory, shop.company_id)
    _add_user(concurrent_session_factory, shop.company_id)  # 3 actifs, une place acquise
    first = concurrent_session_factory()
    first.execute(
        text("SELECT set_config('app.company_id', :id, true)"), {"id": str(shop.company_id)}
    )
    _insert_user(first, shop.company_id)
    outcome: dict[str, BaseException | None] = {}

    def second() -> None:
        try:
            _add_user(concurrent_session_factory, shop.company_id)
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


# ------------------------------------------------------- droits, côté API


def _business(platform_session_factory: sessionmaker[Any], company_id: UUID) -> None:
    set_subscription(platform_session_factory, company_id, plan="business")


def _premium(platform_session_factory: sessionmaker[Any], company_id: UUID) -> None:
    set_subscription(platform_session_factory, company_id, plan="premium")


def _pro_with_imports(platform_session_factory: sessionmaker[Any], company_id: UUID) -> None:
    set_subscription(platform_session_factory, company_id, extra_features='["imports"]')


def _license(platform_session_factory: sessionmaker[Any], company_id: UUID) -> None:
    set_subscription(
        platform_session_factory,
        company_id,
        status="active",
        current_period_end=None,
        is_license=True,
    )


def _pro(platform_session_factory: sessionmaker[Any], company_id: UUID) -> None:
    return None


MATRIX = [
    ("pro", _pro, False),
    ("pro_avec_droits_acquis", _pro_with_imports, True),
    ("business", _business, True),
    ("premium", _premium, True),
    ("licence_sur_site_pro", _license, False),
]


@pytest.mark.parametrize(("label", "setup", "allowed"), MATRIX, ids=[m[0] for m in MATRIX])
@pytest.mark.parametrize(("method", "path"), IMPORT_ROUTES)
def test_t_plan_matrix_on_every_import_route(
    api_client: TestClient,
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
    label: str,
    setup: Any,
    allowed: bool,
    method: str,
    path: str,
) -> None:
    setup(platform_session_factory, shop.company_id)
    response = _call(api_client, login_token(api_client, shop), method, path)
    if allowed:
        assert response.status_code == 200, (label, response.text)
        return
    assert response.status_code == 403, (label, response.text)
    error = response.json()["error"]
    assert error["code"] == "plan_feature_required"
    assert error["details"] == {"feature": "imports", "required_plan": "business"}
    assert error["message"] == "Cette fonction est disponible avec l'offre Business."


def test_a_refused_import_writes_nothing(
    api_client: TestClient, session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    response = api_client.post(
        "/api/v1/imports/customers",
        headers={**auth_headers(login_token(api_client, shop)), "Idempotency-Key": uuid4().hex},
        files={"file": ("c.csv", b"Nom\nAwa Pro\n", "text/csv")},
    )
    assert response.status_code == 403
    with tenant_transaction(
        TenantContext.bootstrap(shop.company_id), session_factory=session_factory
    ) as session:
        assert session.execute(text("SELECT count(*) FROM customers")).scalar_one() == 0


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/exports/referentials/customers?format=csv",
        "/api/v1/exports/referentials/products?format=xlsx",
    ],
)
def test_exports_stay_open_on_pro(api_client: TestClient, shop: DemoCompany, path: str) -> None:
    response = api_client.get(path, headers=auth_headers(login_token(api_client, shop)))
    assert response.status_code == 200, response.text


def test_a_seller_without_the_right_still_gets_a_permission_error(
    api_client: TestClient,
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    """Business, mais pas `importexport:create` : la permission reste refusée."""
    _business(platform_session_factory, shop.company_id)
    manager = login_token(api_client, shop)
    seller = create_user_with_role(
        api_client, manager, shop, role="vendeur", email=f"v-{uuid4().hex[:6]}@test.example"
    )
    response = _call(api_client, seller, "GET", "/api/v1/imports/products/template")
    assert response.status_code == 403
    assert response.json()["error"]["code"] in ("permission_denied", "plan_feature_required")
    assert response.json()["error"]["code"] == "permission_denied"


# --------------------------------------------------- /auth/me, /subscription


def test_me_carries_the_plan_block(api_client: TestClient, shop: DemoCompany) -> None:
    me = api_client.get("/api/v1/auth/me", headers=auth_headers(login_token(api_client, shop)))
    assert me.status_code == 200
    plan = me.json()["plan"]
    assert set(plan) == {"code", "name", "status", "is_license", "features"}
    assert (plan["code"], plan["name"], plan["status"], plan["is_license"]) == (
        "starter",
        "Pro",
        "trial",
        False,
    )
    assert "imports" not in plan["features"]


def test_the_manager_reads_the_subscription(
    api_client: TestClient,
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    set_subscription(
        platform_session_factory,
        shop.company_id,
        extra_features='["imports"]',
        max_users_override=5,
    )
    response = api_client.get(
        "/api/v1/subscription", headers=auth_headers(login_token(api_client, shop))
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "code",
        "name",
        "status",
        "is_license",
        "features",
        "trial_ends_at",
        "current_period_end",
        "max_users",
        "active_users",
        "extra_features",
    }
    assert (body["code"], body["max_users"], body["active_users"]) == ("starter", 5, 1)
    assert body["extra_features"] == ["imports"]
    row = subscription_row(platform_session_factory, shop.company_id)
    assert body["trial_ends_at"] is not None and row.trial_ends_at is not None


@pytest.mark.parametrize("role", ["vendeur", "comptable"])
def test_only_the_manager_reads_the_subscription(
    api_client: TestClient, shop: DemoCompany, role: str
) -> None:
    manager = login_token(api_client, shop)
    token = create_user_with_role(
        api_client, manager, shop, role=role, email=f"{role}-{uuid4().hex[:6]}@test.example"
    )
    response = api_client.get("/api/v1/subscription", headers=auth_headers(token))
    assert response.status_code == 403
    # Le nom de l'offre reste lisible par tous, pour verrouiller les écrans.
    me = api_client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert me.json()["plan"]["code"] == "starter"


# ------------------------------------------------------------- la migration


@pytest.fixture
def alembic_config(migrated_database: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", migrated_database)
    return config


def test_existing_shops_move_to_pro_with_acquired_rights(
    alembic_config: Config,
    subscriptions_kept: None,
    owner_engine: Engine,
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
) -> None:
    command.downgrade(alembic_config, "0042")
    try:
        trial = _create_demo_company(f"avant-essai-{uuid4().hex[:6]}")
        paid = _create_demo_company(f"avant-payee-{uuid4().hex[:6]}")
        suspended = _create_demo_company(f"avant-suspendue-{uuid4().hex[:6]}")
        licensed = _create_demo_company(f"avant-licence-{uuid4().hex[:6]}")
        set_subscription(platform_session_factory, paid.company_id, plan="business")
        for _ in range(4):
            _add_user(session_factory, paid.company_id)  # 5 comptes actifs
        set_subscription(
            platform_session_factory,
            paid.company_id,
            status="active",
            current_period_end="2027-01-15T00:00:00+00:00",
        )
        set_subscription(platform_session_factory, suspended.company_id, status="suspended")
        set_subscription(
            platform_session_factory,
            licensed.company_id,
            status="active",
            current_period_end=None,
        )
        with owner_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO platform_audit_logs (action, entity_table, target_company_id, "
                    "diff) VALUES ('update', 'subscriptions', :id, "
                    '\'{"reason": "licence sur site"}\'::jsonb)'
                ),
                {"id": licensed.company_id},
            )
        before = {
            shop.slug: subscription_row(platform_session_factory, shop.company_id)
            for shop in (trial, paid, suspended, licensed)
        }
    finally:
        command.upgrade(alembic_config, "head")

    for shop in (trial, paid, suspended, licensed):
        row = subscription_row(platform_session_factory, shop.company_id)
        old = before[shop.slug]
        assert row.plan_code == "starter", shop.slug
        assert row.extra_features == ["imports"], shop.slug
        assert (row.status, row.trial_ends_at, row.current_period_end, row.started_at) == (
            old.status,
            old.trial_ends_at,
            old.current_period_end,
            old.started_at,
        ), shop.slug
    assert subscription_row(platform_session_factory, paid.company_id).max_users_override == 5
    assert subscription_row(platform_session_factory, trial.company_id).max_users_override is None
    assert subscription_row(platform_session_factory, licensed.company_id).is_license is True
    assert subscription_row(platform_session_factory, paid.company_id).is_license is False
    # L'import, acquis, reste ouvert ; le plafond acquis tient en base.
    [row] = _plan_of(session_factory, paid.company_id)
    assert "imports" in row.features and (row.max_users, row.active_users) == (5, 5)
    with pytest.raises(DBAPIError):
        _add_user(session_factory, paid.company_id)
    # Une boutique née après la migration : essai Pro, sans droit acquis.
    fresh = _create_demo_company(f"apres-{uuid4().hex[:6]}")
    [row] = _plan_of(session_factory, fresh.company_id)
    assert (row.plan_code, row.status, row.extra_features) == ("starter", "trial", [])
