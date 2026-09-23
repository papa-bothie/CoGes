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


def _beta_category_id(client: TestClient, beta_token: str) -> str:
    """Catégorie appartenant à Beta, créée par Beta elle-même."""
    response = client.post(
        "/api/v1/categories",
        headers=auth_headers(beta_token),
        json={"name": f"Catégorie {uuid4()}"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


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
        "category": _beta_category_id(api_client, beta_token),
    }

    concrete_path = path
    for parameter, source in case.parameters.items():
        concrete_path = concrete_path.replace(f"{{{parameter}}}", sources[source])

    body = dict(case.body) if case.body else None
    if body and body.get("role_id") == "role":
        body["role_id"] = sources["role"]

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
