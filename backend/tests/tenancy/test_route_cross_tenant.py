"""Fuite inter-tenant sur **toutes** les routes paramétrées.

Le test ne connaît pas les routes à l'avance : il les découvre dans l'application.
Deux garanties en découlent :

1. tout endpoint authentifié prenant un identifiant est appelé en croisé A → B et
   doit répondre **404** — jamais 403, qui révélerait l'existence de la ressource ;
2. un endpoint ajouté par une phase future et **non déclaré** dans le registre
   ci-dessous fait échouer le test. Personne ne peut livrer une route paramétrée
   sans avoir décidé comment elle se comporte face à un autre tenant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import DemoCompany, auth_headers

pytestmark = pytest.mark.tenancy

#: Routes publiques : aucune donnée de tenant n'y transite.
PUBLIC_PATHS = frozenset(
    {"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout"}
)


@dataclass(frozen=True, slots=True)
class CrossTenantCase:
    """Comment fabriquer un appel croisé pour une route paramétrée."""

    #: Nom du paramètre de chemin → source de la valeur chez l'autre tenant.
    parameters: dict[str, str]
    #: Corps minimal pour les méthodes qui en exigent un.
    body: dict[str, Any] | None = None


#: Registre des routes paramétrées. À compléter à chaque nouvelle route.
CROSS_TENANT_ROUTES: dict[str, CrossTenantCase] = {
    "/api/v1/users/{user_id}": CrossTenantCase(parameters={"user_id": "manager"}),
    "/api/v1/users/{user_id}/password": CrossTenantCase(
        parameters={"user_id": "manager"}, body={"new_password": "mot-de-passe-de-test-01"}
    ),
    "/api/v1/users/{user_id}/roles": CrossTenantCase(
        parameters={"user_id": "manager"}, body={"role_id": "role"}
    ),
    "/api/v1/users/{user_id}/roles/{role_id}": CrossTenantCase(
        parameters={"user_id": "manager", "role_id": "role"}
    ),
    "/api/v1/roles/{role_id}": CrossTenantCase(parameters={"role_id": "role"}),
    "/api/v1/categories/{category_id}": CrossTenantCase(parameters={"category_id": "category"}),
    "/api/v1/products/{product_id}": CrossTenantCase(parameters={"product_id": "product"}),
    "/api/v1/products/{product_id}/prices": CrossTenantCase(
        parameters={"product_id": "product"}, body={"unit_price": "1500.00"}
    ),
    "/api/v1/customers/{customer_id}": CrossTenantCase(parameters={"customer_id": "customer"}),
    "/api/v1/suppliers/{supplier_id}": CrossTenantCase(parameters={"supplier_id": "supplier"}),
    "/api/v1/inventory/movements/{movement_id}/reverse": CrossTenantCase(
        parameters={"movement_id": "movement"}
    ),
    "/api/v1/sales/{sale_id}": CrossTenantCase(parameters={"sale_id": "sale"}),
    "/api/v1/sales/{sale_id}/receipt": CrossTenantCase(parameters={"sale_id": "sale"}),
    "/api/v1/sales/{sale_id}/items": CrossTenantCase(
        parameters={"sale_id": "sale"}, body={"product_id": "product", "qty": "1"}
    ),
    "/api/v1/sales/{sale_id}/items/{item_id}": CrossTenantCase(
        parameters={"sale_id": "sale", "item_id": "sale_item"}
    ),
    "/api/v1/sales/{sale_id}/confirm": CrossTenantCase(parameters={"sale_id": "sale"}),
    "/api/v1/sales/{sale_id}/cancel": CrossTenantCase(
        parameters={"sale_id": "sale"}, body={"reason": "Test de fuite inter-tenant"}
    ),
}


def _parameterised_paths() -> list[str]:
    """Routes de l'API qui prennent au moins un paramètre de chemin."""
    return sorted(
        path
        for path in app.openapi()["paths"]
        if path.startswith("/api/v1/") and "{" in path and path not in PUBLIC_PATHS
    )


def test_every_parameterised_route_is_registered() -> None:
    """Une route paramétrée non enregistrée casse la CI : c'est voulu."""
    missing = [path for path in _parameterised_paths() if path not in CROSS_TENANT_ROUTES]

    assert missing == [], (
        "Routes paramétrées sans test de fuite croisée. Ajoutez-les à "
        f"CROSS_TENANT_ROUTES : {missing}"
    )


def _beta_role_id(client: TestClient, beta_token: str) -> str:
    response = client.get("/api/v1/roles?page_size=50", headers=auth_headers(beta_token))
    assert response.status_code == 200
    return str(response.json()["items"][0]["id"])


def _beta_owned(client: TestClient, beta_token: str, resource: str, payload: dict[str, Any]) -> str:
    """Crée une ressource **chez Beta**, que Alpha tentera ensuite d'atteindre."""
    response = client.post(f"/api/v1/{resource}", headers=auth_headers(beta_token), json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _beta_sale(client: TestClient, beta_token: str, product_id: str) -> tuple[str, str]:
    """Un brouillon de vente **chez Beta**, garni d'une ligne. Reste en brouillon.

    Alpha doit se heurter à un 404 sur toutes les routes, y compris celles qui ne
    répondraient qu'à une vente modifiable : une vente déjà confirmée renverrait
    409 sur `confirm`, et le test ne prouverait plus rien sur l'isolation.
    """
    headers = auth_headers(beta_token)
    sale = client.post("/api/v1/sales", headers=headers, json={})
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])

    item = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=headers,
        json={"product_id": product_id, "qty": "1"},
    )
    assert item.status_code == 201, item.text
    return sale_id, str(item.json()["id"])


def _beta_sources(client: TestClient, beta_token: str) -> dict[str, str]:
    """Une ressource de Beta par type d'identifiant manipulé par les routes."""
    marker = uuid4().hex[:8]
    product_id = _beta_owned(
        client,
        beta_token,
        "products",
        {"sku": f"SKU-{marker}", "name": f"Produit {marker}", "unit_price": "1500.00"},
    )
    sale_id, sale_item_id = _beta_sale(client, beta_token, product_id)
    return {
        "sale": sale_id,
        "sale_item": sale_item_id,
        "category": _beta_owned(client, beta_token, "categories", {"name": f"Cat-{marker}"}),
        "product": product_id,
        "customer": _beta_owned(client, beta_token, "customers", {"name": f"Client {marker}"}),
        "supplier": _beta_owned(client, beta_token, "suppliers", {"name": f"Fournisseur {marker}"}),
        "movement": _beta_owned(
            client,
            beta_token,
            "inventory/movements",
            {
                "product_id": product_id,
                "type": "initial",
                "qty_delta": "10",
                "unit_cost": "1000",
            },
        ),
    }


@pytest.mark.parametrize("path", sorted(CROSS_TENANT_ROUTES))
def test_cross_tenant_access_is_not_found(
    api_client: TestClient,
    alpha_token: str,
    beta_token: str,
    company_beta: DemoCompany,
    path: str,
) -> None:
    """Alpha appelle les ressources de Beta : chaque méthode doit répondre 404."""
    case = CROSS_TENANT_ROUTES[path]
    sources = {
        "manager": str(company_beta.manager_id),
        "role": _beta_role_id(api_client, beta_token),
        **_beta_sources(api_client, beta_token),
    }

    concrete_path = path
    for parameter, source in case.parameters.items():
        concrete_path = concrete_path.replace(f"{{{parameter}}}", sources[source])

    # Toute valeur de corps qui nomme une source est remplacée par l'identifiant
    # correspondant chez Beta ; les autres (un montant, un mot de passe) passent
    # telles quelles.
    body = (
        {key: sources.get(value, value) for key, value in case.body.items()} if case.body else None
    )

    methods = sorted(method.upper() for method in app.openapi()["paths"][path])
    assert methods, f"aucune méthode déclarée pour {path}"

    for method in methods:
        # Un corps absent ferait échouer la validation (422) avant même d'atteindre
        # la route : on envoie au minimum un objet vide, valide pour les schémas
        # dont tous les champs sont optionnels.
        payload = (body or {}) if method in {"POST", "PATCH", "PUT"} else None
        response = api_client.request(
            method, concrete_path, headers=auth_headers(alpha_token), json=payload
        )
        assert response.status_code == 404, (
            f"{method} {path} a répondu {response.status_code} sur la donnée d'un autre "
            "tenant ; seul 404 est acceptable."
        )
        assert response.json()["error"]["code"] == "not_found", f"{method} {path}"


def test_unauthenticated_access_is_refused_on_every_protected_route(
    api_client: TestClient, company_beta: DemoCompany
) -> None:
    """Sans jeton, aucune route protégée ne répond autre chose que 401."""
    for path in sorted(app.openapi()["paths"]):
        if path in PUBLIC_PATHS or not path.startswith("/api/v1/"):
            continue
        # N'importe quel paramètre de chemin reçoit un UUID valide : le test reste
        # vrai pour les routes des phases suivantes, sans liste à tenir à jour.
        concrete_path = re.sub(r"\{[^}]+\}", str(company_beta.manager_id), path)
        for method in app.openapi()["paths"][path]:
            response = api_client.request(method.upper(), concrete_path)
            assert response.status_code == 401, f"{method.upper()} {path}"
