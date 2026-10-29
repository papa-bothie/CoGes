"""Droits après la relecture des lots 28 et 29 (prompt 32, bloc D, ADR 0103).

* D1 — « Vendre » ne donne plus `payments:create` : la caisse encaisse par la confirmation
  (`sales:confirm`), jamais par `POST /payments`. « Encaisser une dette » ne permet que cela :
  un encaissement lettré sur des dettes client. Toute autre écriture d'argent (sortie,
  fournisseur, paiement sans dette) exige « Gérer les dettes, les dépenses et les paiements ».
* D2 — décocher une ligne retire ses droits, même ceux qu'une ligne « en partie » partage.
* D4 — deux enregistrements simultanés de la grille se suivent : le rôle est verrouillé.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.rbac import service as rbac_service
from tests.conftest import (
    BACKEND_ROOT,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    read_scalar_in_tenant,
    write_headers,
)
from tests.integration.test_debts_api import _customer, _supplier, _token_for_role
from tests.integration.test_sales_api import _add_line, _draft, _make_product

pytestmark = pytest.mark.integration


def _fresh(client: TestClient) -> tuple[DemoCompany, str]:
    company = _create_demo_company(f"review32-{uuid4().hex[:8]}")
    return company, login_token(client, company)


def _role_id(client: TestClient, token: str, name: str) -> str:
    grid = client.get("/api/v1/roles/abilities", headers=auth_headers(token)).json()
    return str(next(role["role_id"] for role in grid["roles"] if role["name"] == name))


def _set(client: TestClient, token: str, role_id: str, abilities: list[str]) -> Any:
    response = client.put(
        f"/api/v1/roles/{role_id}/abilities",
        headers=auth_headers(token),
        json={"abilities": abilities},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _permissions(client: TestClient, token: str, role_id: str) -> set[str]:
    detail = client.get(f"/api/v1/roles/{role_id}", headers=auth_headers(token)).json()
    return set(detail["permissions"])


def _debt(client: TestClient, token: str, party: str, party_id: str, principal: str) -> str:
    created = client.post(
        "/api/v1/debts",
        headers=write_headers(token),
        json={"party_type": party, f"{party}_id": party_id, "principal": principal},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _pay(client: TestClient, token: str, body: dict[str, Any]) -> Any:
    return client.post("/api/v1/payments", headers=write_headers(token), json=body)


# ---------------------------------------------------------------------------- D1


def test_d1_a_default_seller_still_takes_the_money_when_selling(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    company, boss = _fresh(api_client)
    seller = _token_for_role(api_client, boss, company, "vendeur")
    me = api_client.get("/api/v1/auth/me", headers=auth_headers(seller)).json()
    assert "payments:create" not in me["permissions"]

    product = _make_product(api_client, boss)
    customer = _customer(api_client, boss, credit_limit="100000")
    for paid, owed in (("3000.00", Decimal("0")), ("1000.00", Decimal("2000"))):
        sale = _draft(api_client, seller, customer_id=customer)
        assert _add_line(api_client, seller, sale, product).status_code == 201
        confirmed = api_client.post(
            f"/api/v1/sales/{sale}/confirm",
            headers=write_headers(seller),
            json={"paid_amount": paid, "method": "cash"},
        )
        assert confirmed.status_code == 200, confirmed.text
        cashed = read_scalar_in_tenant(
            session_factory,
            company.company_id,
            "SELECT COALESCE(SUM(amount), 0) FROM payments "
            "WHERE sale_id = :id AND direction = 'inflow'",
            {"id": UUID(sale)},
        )
        assert Decimal(cashed) == Decimal(paid)
        assert Decimal(confirmed.json()["balance"]) == owed


def test_d1_a_default_seller_writes_no_payment_by_hand(api_client: TestClient) -> None:
    company, boss = _fresh(api_client)
    seller = _token_for_role(api_client, boss, company, "vendeur")
    debt = _debt(api_client, boss, "customer", _customer(api_client, boss), "1000.00")
    for body in (
        {"direction": "inflow", "method": "cash", "amount": "400.00"},
        {"direction": "outflow", "method": "cash", "amount": "20000.00"},
        {
            "direction": "inflow",
            "method": "cash",
            "amount": "400.00",
            "allocations": [{"debt_id": debt, "amount": "400.00"}],
        },
    ):
        refused = _pay(api_client, seller, body)
        assert refused.status_code == 403, (body, refused.text)


def test_d1_collect_debt_only_collects_a_customer_debt(api_client: TestClient) -> None:
    company, boss = _fresh(api_client)
    seller = _token_for_role(api_client, boss, company, "vendeur")
    _set(
        api_client,
        boss,
        _role_id(api_client, boss, "vendeur"),
        ["base", "see", "sell", "collect_debt"],
    )
    customer_debt = _debt(api_client, boss, "customer", _customer(api_client, boss), "1000.00")
    supplier_debt = _debt(api_client, boss, "supplier", _supplier(api_client, boss), "5000.00")

    collected = _pay(
        api_client,
        seller,
        {
            "direction": "inflow",
            "method": "wave",
            "amount": "400.00",
            "allocations": [{"debt_id": customer_debt, "amount": "400.00"}],
        },
    )
    assert collected.status_code == 201, collected.text

    for body in (
        # Payer un fournisseur.
        {
            "direction": "outflow",
            "method": "cash",
            "amount": "3000.00",
            "allocations": [{"debt_id": supplier_debt, "amount": "3000.00"}],
        },
        # Sortir de l'argent sans motif.
        {"direction": "outflow", "method": "cash", "amount": "20000.00"},
        # Une entrée d'argent qui ne règle aucune dette.
        {"direction": "inflow", "method": "cash", "amount": "100.00"},
    ):
        refused = _pay(api_client, seller, body)
        assert refused.status_code == 403, (body, refused.text)
        assert refused.json()["error"]["code"] == "permission_denied"


def test_d1_managing_money_keeps_every_payment(api_client: TestClient) -> None:
    company, boss = _fresh(api_client)
    accountant = _token_for_role(api_client, boss, company, "comptable")
    supplier_debt = _debt(api_client, boss, "supplier", _supplier(api_client, boss), "5000.00")
    for body in (
        {"direction": "outflow", "method": "cash", "amount": "2000.00"},
        {
            "direction": "outflow",
            "method": "cash",
            "amount": "3000.00",
            "allocations": [{"debt_id": supplier_debt, "amount": "3000.00"}],
        },
    ):
        assert _pay(api_client, accountant, body).status_code == 201


# ---------------------------------------------------------------------------- D2


def test_d2_a_second_press_removes_a_line_shared_with_a_partial_one(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    """Ancienne grille : `inventory:create` + `debts:create`, deux lignes « en partie »."""
    company, boss = _fresh(api_client)
    seller = _role_id(api_client, boss, "vendeur")
    ctx = TenantContext(user_id=company.manager_id, company_id=company.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO role_permissions (company_id, role_id, permission_id) "
                "SELECT :company, :role, id FROM permissions "
                "WHERE code IN ('inventory:create', 'debts:create')"
            ),
            {"company": str(company.company_id), "role": seller},
        )
    grid = api_client.get("/api/v1/roles/abilities", headers=auth_headers(boss)).json()
    partial = next(role for role in grid["roles"] if role["name"] == "vendeur")["partial"]
    assert set(partial) == {"stock", "manage_money"}

    ticked = _set(api_client, boss, seller, ["base", "see", "sell", "manage_money"])
    assert "manage_money" in ticked["abilities"]
    unticked = _set(api_client, boss, seller, ["base", "see", "sell"])
    permissions = _permissions(api_client, boss, seller)
    assert "debts:create" not in permissions
    assert "manage_money" not in unticked["partial"]
    # Rien n'est ajouté en silence : la ligne stock garde seulement ce qu'elle avait à elle.
    assert "inventory:create" in permissions and "inventory:update" not in permissions
    assert unticked["partial"] == ["stock"]


# ---------------------------------------------------------------------------- D4


def test_d4_saving_the_grid_locks_the_role(
    api_client: TestClient, session_factory: sessionmaker[Any]
) -> None:
    company, boss = _fresh(api_client)
    seller = UUID(_role_id(api_client, boss, "vendeur"))
    ctx = TenantContext(user_id=company.manager_id, company_id=company.company_id)
    bind = session_factory.kw["bind"]
    # Une connexion à part : le pool des tests n'en prête qu'une à la fois.
    other = create_engine(bind.url.render_as_string(hide_password=False), poolclass=NullPool)
    with tenant_transaction(ctx, session_factory=session_factory) as first:
        rbac_service.set_role_abilities(first, ctx, seller, ["base", "see", "sell", "stock"])
        # Un second enregistrement, en même temps, attend le premier au lieu de le croiser.
        with other.connect() as connection, pytest.raises(OperationalError, match="lock"):
            connection.execute(
                text("SELECT set_config('app.company_id', :id, true)"),
                {"id": str(company.company_id)},
            )
            connection.execute(
                text("SELECT 1 FROM roles WHERE id = :id FOR SHARE NOWAIT"), {"id": seller}
            )
    other.dispose()


# ------------------------------------------------------------------ révision 0031


def _alembic(owner_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", owner_url)
    return config


def _codes(session_factory: sessionmaker[Any], company: DemoCompany, role_id: str) -> set[str]:
    ctx = TenantContext(user_id=company.manager_id, company_id=company.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        rows = session.execute(
            text(
                "SELECT p.code FROM role_permissions rp JOIN permissions p "
                "ON p.id = rp.permission_id WHERE rp.role_id = :role"
            ),
            {"role": role_id},
        )
        return {row[0] for row in rows}


def test_d1_d3_revision_0031_takes_back_the_rights_with_an_audit_line(
    api_client: TestClient,
    session_factory: sessionmaker[Any],
    migrated_database: str,
) -> None:
    """Une entreprise réglée avant : vendeur avec `payments:create`, comptable avec
    `company:update` et `system:read` ; un vendeur à qui « Encaisser une dette » a été donné."""
    company, boss = _fresh(api_client)
    seller = _role_id(api_client, boss, "vendeur")
    accountant = _role_id(api_client, boss, "comptable")
    collector, _ = _fresh(api_client)
    collector_boss = login_token(api_client, collector)
    collector_seller = _role_id(api_client, collector_boss, "vendeur")
    _set(api_client, collector_boss, collector_seller, ["base", "see", "sell", "collect_debt"])

    def grant(target: DemoCompany, role: str, codes: tuple[str, ...]) -> None:
        ctx = TenantContext(user_id=target.manager_id, company_id=target.company_id)
        with tenant_transaction(ctx, session_factory=session_factory) as session:
            session.execute(
                text(
                    "INSERT INTO role_permissions (company_id, role_id, permission_id) "
                    "SELECT :company, :role, id FROM permissions WHERE code = ANY(:codes) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"company": str(target.company_id), "role": role, "codes": list(codes)},
            )

    grant(company, seller, ("payments:create",))
    grant(company, accountant, ("company:update", "system:read"))
    before_accountant = _codes(session_factory, company, accountant)

    config = _alembic(migrated_database)
    command.downgrade(config, "0030")
    command.upgrade(config, "head")

    assert "payments:create" not in _codes(session_factory, company, seller)
    after_accountant = _codes(session_factory, company, accountant)
    assert after_accountant == before_accountant - {"company:update", "system:read"}
    # « Encaisser une dette » cochée : rien ne bouge.
    assert "payments:create" in _codes(session_factory, collector, collector_seller)
    lines = read_scalar_in_tenant(
        session_factory,
        company.company_id,
        "SELECT count(*) FROM audit_logs WHERE entity_table = 'roles' "
        "AND diff->>'source' = '0031' AND actor_user_id IS NULL",
        {},
    )
    assert lines == 2

    # Réversible : le retour remet exactement ce qui avait été retiré.
    command.downgrade(config, "0030")
    assert "payments:create" in _codes(session_factory, company, seller)
    assert {"company:update", "system:read"} <= _codes(session_factory, company, accountant)
    command.upgrade(config, "head")
