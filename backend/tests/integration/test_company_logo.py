"""Logo de l'entreprise par l'API (prompt 35, bloc L, ADR 0111)."""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    create_user_with_role,
    login_token,
    read_scalar_in_tenant,
)

pytestmark = pytest.mark.integration

LOGO = "/api/v1/companies/me/logo"


def _png(size: tuple[int, int] = (120, 60), color: tuple[int, int, int] = (10, 120, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _put(client: TestClient, token: str, content: bytes, name: str = "logo.png") -> Any:
    return client.put(
        LOGO, headers=auth_headers(token), files={"file": (name, content, "image/png")}
    )


@pytest.fixture
def shop(app_bound_to_test_database: None) -> DemoCompany:
    """Une boutique neuve par test : le logo est une ligne unique par entreprise."""
    return _create_demo_company(f"logo-{uuid4().hex[:8]}")


@pytest.fixture
def manager(api_client: TestClient, shop: DemoCompany) -> str:
    return login_token(api_client, shop)


def _audits(session_factory: sessionmaker[Any], shop: DemoCompany) -> list[dict[str, Any]]:
    ctx = TenantContext.bootstrap(shop.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        rows = session.execute(
            text(
                "SELECT action::text AS action, diff FROM audit_logs "
                "WHERE entity_table = 'company_logos' ORDER BY id"
            )
        ).all()
    return [{"action": row.action, "diff": row.diff} for row in rows]


def test_no_logo_at_first(api_client: TestClient, manager: str) -> None:
    missing = api_client.get(LOGO, headers=auth_headers(manager))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "logo_not_found"
    company = api_client.get("/api/v1/companies/me", headers=auth_headers(manager)).json()
    assert company["logo_updated_at"] is None


def test_add_change_then_remove_the_logo(
    api_client: TestClient,
    manager: str,
    shop: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    added = _put(api_client, manager, _png((1024, 512)))
    assert added.status_code == 200, added.text
    body = added.json()
    assert (body["width"], body["height"]) == (512, 256)
    assert body["updated_at"]

    read = api_client.get(LOGO, headers=auth_headers(manager))
    assert read.status_code == 200
    assert read.headers["content-type"] == "image/png"
    assert read.headers["cache-control"] == "no-store"
    assert read.headers["x-content-type-options"] == "nosniff"
    with Image.open(io.BytesIO(read.content)) as image:
        assert image.size == (512, 256)
    company = api_client.get("/api/v1/companies/me", headers=auth_headers(manager)).json()
    assert company["logo_updated_at"] == body["updated_at"]

    changed = _put(api_client, manager, _png((64, 64), (200, 0, 0)), name="autre.jpg")
    assert changed.status_code == 200, changed.text
    assert (changed.json()["width"], changed.json()["height"]) == (64, 64)
    assert api_client.get(LOGO, headers=auth_headers(manager)).content != read.content

    removed = api_client.delete(LOGO, headers=auth_headers(manager))
    assert removed.status_code == 204, removed.text
    assert api_client.get(LOGO, headers=auth_headers(manager)).status_code == 404
    company = api_client.get("/api/v1/companies/me", headers=auth_headers(manager)).json()
    assert company["logo_updated_at"] is None
    stored = read_scalar_in_tenant(
        session_factory,
        shop.company_id,
        "SELECT png IS NULL FROM company_logos WHERE company_id = :id",
        {"id": shop.company_id},
    )
    assert stored is True, "l'image retirée n'est plus en base"

    again = api_client.delete(LOGO, headers=auth_headers(manager))
    assert again.status_code == 404, "rien à retirer"

    audits = _audits(session_factory, shop)
    assert [row["action"] for row in audits] == ["insert", "update", "delete"]
    assert audits[1]["diff"]["before"]["width"] == 512
    assert audits[1]["diff"]["after"]["width"] == 64
    assert audits[2]["diff"]["after"] is None or audits[2]["diff"]["after"].get("sha256") is None
    for row in audits:
        assert "png" not in str(row["diff"]), "jamais les octets dans le journal"


def test_refusals_are_clear(api_client: TestClient, manager: str) -> None:
    svg = _put(api_client, manager, b'<svg xmlns="http://www.w3.org/2000/svg"/>', "logo.svg")
    assert svg.status_code == 422
    assert svg.json()["error"]["code"] == "logo_unsupported_format"
    assert svg.json()["error"]["message"] == "Format non pris en charge : PNG, JPEG ou WebP."

    heavy = _put(api_client, manager, b"\x89PNG" + b"\x00" * (2 * 1024 * 1024 + 1))
    assert heavy.status_code == 413
    assert heavy.json()["error"]["code"] == "logo_too_large"
    assert heavy.json()["error"]["message"] == "Image trop lourde (2 Mo au plus)."

    assert api_client.get(LOGO, headers=auth_headers(manager)).status_code == 404


def test_a_body_well_beyond_the_limit_is_cut_by_the_middleware(
    api_client: TestClient, manager: str
) -> None:
    huge = _put(api_client, manager, b"\x00" * (3 * 1024 * 1024))
    assert huge.status_code == 413


def test_a_seller_reads_the_logo_but_never_changes_it(
    api_client: TestClient, manager: str, shop: DemoCompany
) -> None:
    assert _put(api_client, manager, _png()).status_code == 200
    seller = create_user_with_role(
        api_client, manager, shop, role="vendeur", email=f"v-{uuid4().hex[:8]}@test.sn"
    )
    assert api_client.get(LOGO, headers=auth_headers(seller)).status_code == 200
    assert _put(api_client, seller, _png()).status_code == 403
    assert api_client.delete(LOGO, headers=auth_headers(seller)).status_code == 403


def test_another_company_never_sees_the_logo(
    api_client: TestClient,
    manager: str,
    shop: DemoCompany,
    company_beta: DemoCompany,
    beta_token: str,
    session_factory: sessionmaker[Any],
) -> None:
    assert _put(api_client, manager, _png()).status_code == 200
    other = api_client.get(LOGO, headers=auth_headers(beta_token))
    assert other.status_code == 404, "B n'a pas de logo et ne lit jamais celui de A"

    # En base, sous RLS, B ne voit pas la ligne de A.
    seen = read_scalar_in_tenant(
        session_factory,
        company_beta.company_id,
        "SELECT count(*) FROM company_logos WHERE company_id = :id",
        {"id": shop.company_id},
    )
    assert seen == 0


def test_rls_refuses_a_logo_written_for_another_company(
    session_factory: sessionmaker[Any], shop: DemoCompany, company_beta: DemoCompany
) -> None:
    """T5/T37 : sous le contexte de B, écrire la ligne de A est refusé par la base."""
    ctx = TenantContext.bootstrap(company_beta.company_id)
    with (
        pytest.raises(DBAPIError),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text("INSERT INTO company_logos (company_id, updated_by) VALUES (:company, :user)"),
            {"company": shop.company_id, "user": shop.manager_id},
        )


@pytest.fixture
def support_client(platform_bound_to_test_database: None) -> Iterator[TestClient]:
    from app.main import app
    from tests.conftest import TEST_BASE_URL

    with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as test_client:
        yield test_client


def test_the_support_access_reads_the_logo_and_writes_nothing(
    support_client: TestClient,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    from tests.integration.platform_harness import create_platform_account
    from tests.integration.support_harness import open_support_session

    manager = login_token(support_client, shop)
    assert _put(support_client, manager, _png()).status_code == 200
    account = create_platform_account("support")
    _, token = open_support_session(platform_session_factory, shop.company_id, account.id)

    assert support_client.get(LOGO, headers=auth_headers(token)).status_code == 200
    refused = _put(support_client, token, _png())
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "support_read_only"


def test_the_history_tells_the_logo_in_words(api_client: TestClient, manager: str) -> None:
    assert _put(api_client, manager, _png()).status_code == 200
    assert _put(api_client, manager, _png(color=(1, 2, 3))).status_code == 200
    assert api_client.delete(LOGO, headers=auth_headers(manager)).status_code == 204
    history = api_client.get("/api/v1/analytics/history", headers=auth_headers(manager)).json()
    sentences = [line["sentence"] for line in history["items"]]
    told = [s for s in sentences if "logo" in s]
    assert len(told) == 3, sentences
    assert any("a ajouté le logo" in s for s in told)
    assert any("a changé le logo" in s for s in told)
    assert any("a retiré le logo" in s for s in told)
