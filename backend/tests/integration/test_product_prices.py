"""Prix historisés : un seul intervalle ouvert, aucun trou, aucun recouvrement.

C'est l'invariant le plus important du référentiel : de lui dépend le prix qu'une
vente figera. Il est vérifié par l'API **et** attaqué directement en base, parce
que `product_prices_no_overlap` doit tenir sans l'aide du service.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.errors import sqlstate
from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant
from tests.integration.test_products import create_product

pytestmark = pytest.mark.integration

#: `exclusion_violation` — la contrainte gist a refusé un recouvrement.
EXCLUSION_VIOLATION = "23P01"


def _change_price(
    client: TestClient, token: str, product_id: str, **payload: Any
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/products/{product_id}/prices", headers=auth_headers(token), json=payload
    )
    assert response.status_code == 201, response.text
    price: dict[str, Any] = response.json()
    return price


def _history(client: TestClient, token: str, product_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/v1/products/{product_id}/prices", headers=auth_headers(token))
    assert response.status_code == 200
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def test_changing_the_price_closes_the_previous_interval(
    api_client: TestClient, alpha_token: str
) -> None:
    """L'ancien prix est fermé **exactement** à l'instant d'ouverture du nouveau."""
    product = create_product(api_client, alpha_token, unit_price="1000.00")
    _change_price(api_client, alpha_token, product["id"], unit_price="1200.00")

    history = _history(api_client, alpha_token, product["id"])
    assert len(history) == 2

    current, previous = history  # tri : valid_from décroissant
    assert current["unit_price"] == "1200.00"
    assert current["valid_to"] is None
    assert previous["unit_price"] == "1000.00"
    # Pas de trou : la fermeture de l'un est l'ouverture de l'autre.
    assert previous["valid_to"] == current["valid_from"]


def test_only_one_interval_stays_open(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Après trois changements, un seul `valid_to IS NULL` subsiste."""
    product = create_product(api_client, alpha_token, unit_price="500.00")
    for price in ("600.00", "700.00", "800.00"):
        _change_price(api_client, alpha_token, product["id"], unit_price=price)

    open_intervals = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM product_prices WHERE product_id = :id AND valid_to IS NULL",
        {"id": product["id"]},
    )
    assert open_intervals == 1

    current = api_client.get(
        f"/api/v1/products/{product['id']}", headers=auth_headers(alpha_token)
    ).json()
    assert current["unit_price"] == "800.00"


def test_the_price_change_is_audited(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Le prix est une donnée financière : chaque changement laisse une trace nominative."""
    product = create_product(api_client, alpha_token, unit_price="900.00")
    price = _change_price(api_client, alpha_token, product["id"], unit_price="950.00")

    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT diff FROM audit_logs "
        "WHERE entity_table = 'product_prices' AND entity_id = :id AND action = 'update'",
        {"id": price["id"]},
    )
    assert audited["before"]["unit_price"] == "900.00"
    assert audited["after"]["unit_price"] == "950.00"


def test_the_author_of_a_price_is_recorded(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """`created_by` porte l'utilisateur du contexte, jamais NULL via l'API (ADR 0011)."""
    product = create_product(api_client, alpha_token, unit_price="100.00")
    price = _change_price(api_client, alpha_token, product["id"], unit_price="110.00")

    assert price["created_by"] == str(company_alpha.manager_id)


def test_the_cost_price_is_optional_and_kept_apart(
    api_client: TestClient, alpha_token: str
) -> None:
    """Un prix de vente sans coût connu reste un prix valide."""
    product = create_product(api_client, alpha_token, unit_price="400.00")
    price = _change_price(api_client, alpha_token, product["id"], unit_price="450.00")

    assert price["cost_price"] is None


def test_a_zero_price_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """`CHECK (unit_price > 0)` : un produit à zéro serait une erreur de saisie."""
    product = create_product(api_client, alpha_token)

    response = api_client.post(
        f"/api/v1/products/{product['id']}/prices",
        headers=auth_headers(alpha_token),
        json={"unit_price": "0"},
    )
    assert response.status_code == 422


def test_overlapping_intervals_are_refused_by_the_database(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Attaque directe : deux intervalles ouverts pour un même produit sont impossibles.

    C'est `product_prices_no_overlap` qui refuse, pas le service : deux changements
    de prix concurrents tombent sur cette contrainte, et l'un des deux perd.
    """
    product = create_product(api_client, alpha_token, unit_price="1000.00")
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO product_prices (company_id, product_id, unit_price, created_by) "
                "VALUES (:company_id, :product_id, 999.00, :created_by)"
            ),
            {
                "company_id": company_alpha.company_id,
                "product_id": product["id"],
                "created_by": company_alpha.manager_id,
            },
        )

    assert sqlstate(excinfo.value) == EXCLUSION_VIOLATION
    assert "product_prices_no_overlap" in str(excinfo.value)


def test_a_past_interval_cannot_be_reopened(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Un intervalle qui recouvre l'intervalle courant est refusé, même daté du passé."""
    product = create_product(api_client, alpha_token, unit_price="1000.00")
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with (
        pytest.raises(IntegrityError),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO product_prices "
                "(company_id, product_id, unit_price, valid_from, valid_to, created_by) "
                "VALUES (:company_id, :product_id, 500.00, "
                "now() - interval '1 day', now() + interval '1 day', :created_by)"
            ),
            {
                "company_id": company_alpha.company_id,
                "product_id": product["id"],
                "created_by": company_alpha.manager_id,
            },
        )


def test_an_inverted_interval_is_refused(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """`CHECK (valid_to > valid_from)` : un intervalle ne finit pas avant de commencer."""
    product = create_product(api_client, alpha_token, unit_price="1000.00")
    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)

    with (
        pytest.raises(IntegrityError),
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO product_prices "
                "(company_id, product_id, unit_price, valid_from, valid_to, created_by) "
                "VALUES (:company_id, :product_id, 500.00, "
                "now() - interval '1 day', now() - interval '2 days', :created_by)"
            ),
            {
                "company_id": company_alpha.company_id,
                "product_id": product["id"],
                "created_by": company_alpha.manager_id,
            },
        )


def test_the_history_of_another_company_is_not_found(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """Lire le tarif d'un concurrent renvoie 404, jamais 403."""
    foreign = create_product(api_client, beta_token)

    response = api_client.get(
        f"/api/v1/products/{foreign['id']}/prices", headers=auth_headers(alpha_token)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_product_keeps_its_prices_after_a_soft_delete(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """La suppression logique n'efface pas l'historique : les ventes passées s'y réfèrent."""
    product = create_product(api_client, alpha_token, unit_price="777.00")
    _change_price(api_client, alpha_token, product["id"], unit_price="888.00")
    api_client.delete(f"/api/v1/products/{product['id']}", headers=auth_headers(alpha_token))

    kept = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM product_prices WHERE product_id = :id",
        {"id": product["id"]},
    )
    assert kept == 2


def test_prices_are_isolated_between_companies(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """Deux produits homonymes chez deux entreprises ont des tarifs indépendants."""
    marker = uuid4().hex[:8]
    mine = create_product(api_client, alpha_token, sku=f"SKU-{marker}", unit_price="100.00")
    theirs = create_product(api_client, beta_token, sku=f"SKU-{marker}", unit_price="200.00")

    _change_price(api_client, alpha_token, mine["id"], unit_price="150.00")

    unchanged = api_client.get(
        f"/api/v1/products/{theirs['id']}", headers=auth_headers(beta_token)
    ).json()
    assert unchanged["unit_price"] == "200.00"
