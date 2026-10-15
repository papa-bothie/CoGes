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
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.idempotency import IDEMPOTENCY_HEADER
from app.core.tenancy import TenantContext, tenant_transaction
from app.main import app
from app.modules.notifications.repository import NotificationRepository
from tests.conftest import DemoCompany, auth_headers


def _write_headers(token: str) -> dict[str, str]:
    """Jeton **et** clé d'idempotence, neuve à chaque appel.

    Depuis la phase 07, toute écriture financière exige `Idempotency-Key`. Le
    poser partout ne change rien aux routes qui l'ignorent, et évite qu'un test
    d'isolation ne prouve en réalité l'absence d'un en-tête (422 au lieu de 404).
    """
    return {**auth_headers(token), IDEMPOTENCY_HEADER: uuid4().hex}


pytestmark = pytest.mark.tenancy

#: Routes publiques : aucune donnée de tenant n'y transite.
#: Routes d'exploitation : protégées par `COGES_OPS_TOKEN`, pas par un compte. Sans
#: jeton configuré, elles répondent 404 ; leur 401 est vérifié dans
#: `tests/integration/test_system_workers.py` (ADR 0077).
OPS_PATHS = frozenset({"/api/v1/system/workers"})

PUBLIC_PATHS = frozenset(
    {"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout"}
)


#: Routes dont le paramètre de chemin n'est **pas** une ressource d'entreprise : un
#: type d'import ou d'export (`products`, `customers`…). Il n'y a rien à « croiser » ;
#: leur isolation — un import de A invisible de B, un export de A sans donnée de B —
#: est prouvée par `tests/tenancy/test_importexport_isolation.py`.
NON_RESOURCE_PATHS = frozenset(
    {
        "/api/v1/imports/{kind}",
        "/api/v1/imports/{kind}/template",
        "/api/v1/exports/referentials/{kind}",
    }
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
    "/api/v1/roles/{role_id}/abilities": CrossTenantCase(
        parameters={"role_id": "role"}, body={"abilities": ["sell"]}
    ),
    "/api/v1/categories/{category_id}": CrossTenantCase(parameters={"category_id": "category"}),
    "/api/v1/products/{product_id}": CrossTenantCase(parameters={"product_id": "product"}),
    "/api/v1/analytics/products/{product_id}/history": CrossTenantCase(
        parameters={"product_id": "product"}
    ),
    "/api/v1/products/{product_id}/prices": CrossTenantCase(
        parameters={"product_id": "product"}, body={"unit_price": "1500.00"}
    ),
    "/api/v1/customers/{customer_id}": CrossTenantCase(parameters={"customer_id": "customer"}),
    "/api/v1/suppliers/{supplier_id}": CrossTenantCase(parameters={"supplier_id": "supplier"}),
    "/api/v1/analytics/customers/{customer_id}": CrossTenantCase(
        parameters={"customer_id": "customer"}
    ),
    "/api/v1/analytics/customers/{customer_id}/sales": CrossTenantCase(
        parameters={"customer_id": "customer"}
    ),
    "/api/v1/analytics/customers/{customer_id}/payments": CrossTenantCase(
        parameters={"customer_id": "customer"}
    ),
    "/api/v1/analytics/suppliers/{supplier_id}": CrossTenantCase(
        parameters={"supplier_id": "supplier"}
    ),
    "/api/v1/analytics/suppliers/{supplier_id}/deliveries": CrossTenantCase(
        parameters={"supplier_id": "supplier"}
    ),
    "/api/v1/analytics/suppliers/{supplier_id}/payments": CrossTenantCase(
        parameters={"supplier_id": "supplier"}
    ),
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
    "/api/v1/sales/{sale_id}/returns": CrossTenantCase(
        parameters={"sale_id": "sale"},
        body={"lines": [{"sale_item_id": "sale_item", "qty": "1"}]},
    ),
    "/api/v1/sale-returns/{return_id}": CrossTenantCase(parameters={"return_id": "sale_return"}),
    "/api/v1/sale-returns/{return_id}/refunds": CrossTenantCase(
        parameters={"return_id": "sale_return"}, body={"amount": "100.00", "method": "cash"}
    ),
    "/api/v1/payments/{payment_id}/refunded-returns": CrossTenantCase(
        parameters={"payment_id": "payment"}
    ),
    "/api/v1/payments/{payment_id}": CrossTenantCase(parameters={"payment_id": "payment"}),
    "/api/v1/payments/{payment_id}/cancel": CrossTenantCase(
        parameters={"payment_id": "payment"},
        body={"reason": "Test de fuite inter-tenant, motif assez long"},
    ),
    "/api/v1/debts/{debt_id}": CrossTenantCase(parameters={"debt_id": "debt"}),
    "/api/v1/debts/{debt_id}/write-off": CrossTenantCase(
        parameters={"debt_id": "debt"},
        body={"reason": "Test de fuite inter-tenant, motif assez long"},
    ),
    "/api/v1/expense-categories/{category_id}": CrossTenantCase(
        parameters={"category_id": "expense_category"}
    ),
    "/api/v1/expenses/{expense_id}": CrossTenantCase(parameters={"expense_id": "expense"}),
    "/api/v1/insights/{insight_id}": CrossTenantCase(
        parameters={"insight_id": "insight"}, body={"status": "read"}
    ),
    "/api/v1/notifications/{notification_id}": CrossTenantCase(
        parameters={"notification_id": "notification"}, body={"read": True}
    ),
    "/api/v1/exports/{export_id}": CrossTenantCase(parameters={"export_id": "export"}),
    "/api/v1/exports/{export_id}/file": CrossTenantCase(parameters={"export_id": "export"}),
}


def _substitute(value: Any, sources: dict[str, str]) -> Any:
    """Remplace récursivement les noms de source par les identifiants de Beta.

    Récursivement, parce qu'un retour porte ses lignes : la substitution doit
    descendre dans les listes et les objets, pas seulement dans les champs de tête.
    """
    if isinstance(value, str):
        return sources.get(value, value)
    if isinstance(value, list):
        return [_substitute(item, sources) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, sources) for key, item in value.items()}
    return value


def _parameterised_paths() -> list[str]:
    """Routes de l'API qui prennent au moins un paramètre de chemin."""
    return sorted(
        path
        for path in app.openapi()["paths"]
        if path.startswith("/api/v1/")
        and "{" in path
        and path not in PUBLIC_PATHS
        and path not in NON_RESOURCE_PATHS
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
    response = client.post(f"/api/v1/{resource}", headers=_write_headers(beta_token), json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _beta_sale(client: TestClient, beta_token: str, product_id: str) -> tuple[str, str]:
    """Un brouillon de vente **chez Beta**, garni d'une ligne. Reste en brouillon.

    Alpha doit se heurter à un 404 sur toutes les routes, y compris celles qui ne
    répondraient qu'à une vente modifiable : une vente déjà confirmée renverrait
    409 sur `confirm`, et le test ne prouverait plus rien sur l'isolation.
    """
    headers = _write_headers(beta_token)
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


def _beta_returned_sale(client: TestClient, beta_token: str, product_id: str) -> dict[str, str]:
    """Une vente **confirmée, payée et retournée** chez Beta.

    Distincte du brouillon ci-dessus, et pour la même raison : un retour n'existe
    que sur une vente confirmée, et un remboursement suppose un décaissement. Sans
    ces trois objets réels, les routes de la phase 06 seraient appelées sur du vide
    et le 404 ne prouverait rien.
    """
    headers = _write_headers(beta_token)
    sale = client.post("/api/v1/sales", headers=headers, json={})
    assert sale.status_code == 201, sale.text
    sale_id = str(sale.json()["id"])

    item = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=headers,
        json={"product_id": product_id, "qty": "1"},
    )
    assert item.status_code == 201, item.text
    sale_item_id = str(item.json()["id"])

    # Payée intégralement : sans client identifié, le solde ouvrirait une dette et
    # `customer_required_for_credit` refuserait la confirmation.
    total = client.get(f"/api/v1/sales/{sale_id}", headers=headers).json()["total"]
    confirmed = client.post(
        f"/api/v1/sales/{sale_id}/confirm",
        headers=_write_headers(beta_token),
        json={"paid_amount": total, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    sale_return = client.post(
        f"/api/v1/sales/{sale_id}/returns",
        # Clé neuve : celle de `headers` a déjà servi à la confirmation.
        headers=_write_headers(beta_token),
        json={"lines": [{"sale_item_id": sale_item_id, "qty": "1"}]},
    )
    assert sale_return.status_code == 201, sale_return.text

    return {
        "sale_return": str(sale_return.json()["id"]),
        "payment": str(confirmed.json()["payments"][0]["id"]),
    }


def _beta_notification(session_factory: sessionmaker[Any], company: DemoCompany) -> str:
    """Une alerte **chez Beta**, posée par la façade du module.

    Aucune route ne crée de notification — une alerte naît d'un worker, jamais d'un
    appel client (ADR 0032). Elle est donc semée par le service, dans une transaction
    tenant comme le ferait la tâche. Sans elle, le 404 croisé prouverait seulement
    qu'un identifiant au hasard n'existe pas.
    """
    ctx = TenantContext(user_id=company.manager_id, company_id=company.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        notification = NotificationRepository(ctx=ctx, session=session).add_for_user(
            user_id=company.manager_id,
            notification_type="stock_low",
            title="Stock bas — article de Beta",
            body=None,
            data={},
        )
        session.flush()
        return str(notification.id)


def _beta_insight(analytics_factory: sessionmaker[Any], company: DemoCompany) -> str:
    """Un insight **chez Beta**, écrit comme le pipeline l'écrit : sous `coges_analytics`.

    `coges_app` n'a pas le droit d'insérer un insight (révision 0011) ; aucune route
    n'en crée. Sans cette ligne réelle, le 404 croisé ne prouverait rien.
    """
    ctx = TenantContext.bootstrap(company.company_id)
    with tenant_transaction(ctx, session_factory=analytics_factory) as session:
        return str(
            session.execute(
                text(
                    "INSERT INTO insights (company_id, insight_type, severity, title, dedupe_key) "
                    "VALUES (:c, 'slow_mover', 'info', 'Écoulement lent — Beta', :k) RETURNING id"
                ),
                {"c": company.company_id, "k": f"cross-tenant:{uuid4()}"},
            ).scalar_one()
        )


def _beta_export(client: TestClient, beta_token: str) -> str:
    """Un export de ventes demandé par Beta (resté en attente : aucun worker ici)."""
    response = client.post(
        "/api/v1/exports/sales",
        headers=auth_headers(beta_token),
        json={"date_from": date.today().isoformat(), "date_to": date.today().isoformat()},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


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
    movement_id = _beta_owned(
        client,
        beta_token,
        "inventory/movements",
        {"product_id": product_id, "type": "initial", "qty_delta": "10", "unit_cost": "1000"},
    )
    supplier_id = _beta_owned(client, beta_token, "suppliers", {"name": f"Fournisseur {marker}"})
    expense_category_id = _beta_owned(
        client, beta_token, "expense-categories", {"name": f"Charge {marker}", "kind": "fixed"}
    )
    expense_id = _beta_owned(
        client,
        beta_token,
        "expenses",
        {
            "category_id": expense_category_id,
            "label": f"Loyer {marker}",
            "amount": "50000.00",
            "spent_at": date.today().isoformat(),
        },
    )
    # Une dette fournisseur, plutôt qu'une créance : elle reste ouverte et
    # abandonnable, donc `write-off` se heurte bien à l'isolation et non à un état.
    debt_id = _beta_owned(
        client,
        beta_token,
        "debts",
        {"party_type": "supplier", "supplier_id": supplier_id, "principal": "50000.00"},
    )
    return {
        "sale": sale_id,
        "sale_item": sale_item_id,
        "category": _beta_owned(client, beta_token, "categories", {"name": f"Cat-{marker}"}),
        "product": product_id,
        "customer": _beta_owned(client, beta_token, "customers", {"name": f"Client {marker}"}),
        "supplier": supplier_id,
        "movement": movement_id,
        "expense_category": expense_category_id,
        "expense": expense_id,
        "debt": debt_id,
        "export": _beta_export(client, beta_token),
        # Le stock existe désormais : une vente peut être confirmée puis retournée.
        **_beta_returned_sale(client, beta_token, product_id),
    }


@pytest.mark.parametrize("path", sorted(CROSS_TENANT_ROUTES))
def test_cross_tenant_access_is_not_found(
    api_client: TestClient,
    alpha_token: str,
    beta_token: str,
    company_beta: DemoCompany,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    path: str,
) -> None:
    """Alpha appelle les ressources de Beta : chaque méthode doit répondre 404."""
    case = CROSS_TENANT_ROUTES[path]
    sources = {
        "manager": str(company_beta.manager_id),
        "role": _beta_role_id(api_client, beta_token),
        "notification": _beta_notification(session_factory, company_beta),
        "insight": _beta_insight(analytics_session_factory, company_beta),
        **_beta_sources(api_client, beta_token),
    }

    concrete_path = path
    for parameter, source in case.parameters.items():
        concrete_path = concrete_path.replace(f"{{{parameter}}}", sources[source])

    # Toute valeur de corps qui nomme une source est remplacée par l'identifiant
    # correspondant chez Beta ; les autres (un montant, un mot de passe) passent
    # telles quelles, à tous les niveaux du corps.
    body = _substitute(case.body, sources) if case.body else None

    methods = sorted(method.upper() for method in app.openapi()["paths"][path])
    assert methods, f"aucune méthode déclarée pour {path}"

    for method in methods:
        # Un corps absent ferait échouer la validation (422) avant même d'atteindre
        # la route : on envoie au minimum un objet vide, valide pour les schémas
        # dont tous les champs sont optionnels.
        payload = (body or {}) if method in {"POST", "PATCH", "PUT"} else None
        response = api_client.request(
            method, concrete_path, headers=_write_headers(alpha_token), json=payload
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
        if path in PUBLIC_PATHS | OPS_PATHS or not path.startswith("/api/v1/"):
            continue
        # N'importe quel paramètre de chemin reçoit un UUID valide : le test reste
        # vrai pour les routes des phases suivantes, sans liste à tenir à jour.
        concrete_path = re.sub(r"\{[^}]+\}", str(company_beta.manager_id), path)
        for method in app.openapi()["paths"][path]:
            response = api_client.request(method.upper(), concrete_path)
            assert response.status_code == 401, f"{method.upper()} {path}"
