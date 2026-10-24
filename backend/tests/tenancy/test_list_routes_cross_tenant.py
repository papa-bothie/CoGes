"""Isolation de TOUTES les lectures, y compris sans identifiant dans l'URL (lot C, C2).

`test_route_cross_tenant.py` croise les routes paramétrées. Ici, les autres : listes,
tableau de bord, argent, analyses, conseils, alertes, journal, exports, recherches,
compteurs. Deux entreprises A et B reçoivent des données reconnaissables ; chaque route
de lecture est appelée avec le jeton de A, et la réponse — JSON parcouru récursivement,
fichier d'export lu en clair — ne doit contenir **aucune** trace de B : identifiants,
noms marqueurs, montant marqueur.

Les routes sont découvertes dans l'application : une lecture ajoutée plus tard et non
classée dans `READ_ROUTES` fait échouer `test_every_read_route_is_classified`.
"""

from __future__ import annotations

import io
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.config import get_settings
from app.core.idempotency import IDEMPOTENCY_HEADER
from app.core.tenancy import TenantContext, tenant_transaction
from app.main import app
from app.modules.notifications.repository import NotificationRepository
from tests.conftest import (
    TEST_BASE_URL,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    create_user_with_role,
    login_token,
    role_id,
    write_headers,
)
from tests.integration.platform_harness import create_platform_account
from tests.integration.support_harness import open_support_session

pytestmark = pytest.mark.tenancy

TODAY = date.today()
PERIOD = {"from": (TODAY - timedelta(days=30)).isoformat(), "to": TODAY.isoformat()}

#: Lectures sans paramètre de chemin : paramètres obligatoires à fournir, ou classe.
TENANT = "tenant"
PUBLIC = "public"
OPS = "ops"
#: Administration de la plateforme (ADR 0089) : jeton à part, prouvé par
#: `test_platform_token_separation.py` et `test_platform_sees_companies.py`.
PLATFORM = "platform"
READ_ROUTES: dict[str, tuple[str, dict[str, str]]] = {
    "/api/v1/platform/auth/me": (PLATFORM, {}),
    "/api/v1/platform/companies": (PLATFORM, {}),
    # Catalogue des offres (ADR 0091), le même pour tous ; aucune donnée d'entreprise.
    "/api/v1/platform/plans": (PLATFORM, {}),
    # Surveillance (ADR 0090) : ni entreprise ni contenu, `test_platform_monitoring.py`.
    "/api/v1/platform/system/workers": (PLATFORM, {}),
    "/api/v1/platform/system/job-runs": (PLATFORM, {}),
    "/api/v1/platform/system/outbox": (PLATFORM, {}),
    "/api/v1/health": (PUBLIC, {}),
    "/api/v1/health/ready": (PUBLIC, {}),
    # Jeton d'exploitation, pas un compte : aucune donnée d'entreprise (ADR 0077).
    "/api/v1/system/workers": (OPS, {}),
    # Catalogue global des permissions, identique pour toutes les entreprises.
    "/api/v1/permissions": (TENANT, {}),
    "/api/v1/analytics/cash": (TENANT, {}),
    "/api/v1/analytics/customers": (TENANT, {}),
    "/api/v1/analytics/expenses-summary": (TENANT, {}),
    "/api/v1/analytics/history": (TENANT, {}),
    "/api/v1/analytics/money": (TENANT, {"period": "month"}),
    "/api/v1/analytics/next-week": (TENANT, {}),
    "/api/v1/analytics/overview": (TENANT, PERIOD),
    "/api/v1/analytics/products": (TENANT, {"metric": "revenue", **PERIOD}),
    "/api/v1/analytics/suppliers": (TENANT, {}),
    "/api/v1/analytics/timeseries": (TENANT, {"measure": "revenue", **PERIOD}),
    "/api/v1/audit-logs": (TENANT, {}),
    "/api/v1/auth/me": (TENANT, {}),
    "/api/v1/categories": (TENANT, {}),
    "/api/v1/companies/me": (TENANT, {}),
    # Le bandeau d'accès support (ADR 0092) : début et fin, de sa seule entreprise.
    "/api/v1/companies/me/support-access": (TENANT, {}),
    "/api/v1/customers": (TENANT, {}),
    "/api/v1/dashboard": (TENANT, {}),
    "/api/v1/debts": (TENANT, {}),
    "/api/v1/expense-categories": (TENANT, {}),
    "/api/v1/expenses": (TENANT, {}),
    "/api/v1/exports": (TENANT, {}),
    "/api/v1/forecasts": (TENANT, {}),
    "/api/v1/insights": (TENANT, {}),
    "/api/v1/intelligence/summary": (TENANT, {}),
    "/api/v1/inventory/movements": (TENANT, {}),
    "/api/v1/inventory/stock": (TENANT, {}),
    "/api/v1/inventory/stock/summary": (TENANT, {}),
    "/api/v1/notifications": (TENANT, {}),
    "/api/v1/notifications/unread-count": (TENANT, {}),
    "/api/v1/payments": (TENANT, {}),
    "/api/v1/products": (TENANT, {}),
    "/api/v1/products/category-counts": (TENANT, {}),
    "/api/v1/roles": (TENANT, {}),
    "/api/v1/roles/abilities": (TENANT, {}),
    "/api/v1/sales": (TENANT, {"include_drafts": "true"}),
    "/api/v1/sales/customer-choices": (TENANT, {}),
    "/api/v1/sales/day-totals": (
        TENANT,
        {"date_from": PERIOD["from"], "date_to": PERIOD["to"]},
    ),
    "/api/v1/suppliers": (TENANT, {}),
    "/api/v1/system/outbox": (TENANT, {}),
    "/api/v1/users": (TENANT, {}),
}

#: Exports en fichier (paramètre de chemin = type d'export, pas une ressource).
EXPORTS = ("products", "customers", "suppliers")
#: Montant qui n'existe que chez B.
B_AMOUNT = "97531"


@dataclass
class Shop:
    company: DemoCompany
    token: str
    ids: dict[str, str] = field(default_factory=dict)
    names: list[str] = field(default_factory=list)


def _post(client: TestClient, token: str, path: str, body: Any) -> dict[str, Any]:
    response = client.post(path, headers=write_headers(token), json=body)
    assert response.status_code in (200, 201), f"{path} : {response.text}"
    return dict(response.json())


def _fill(
    client: TestClient, shop: Shop, tag: str, session_factory: sessionmaker[Any], amount: str
) -> None:
    """Une boutique complète, aux noms marqués `tag`, plus un client au nom PARTAGÉ."""
    t = shop.token
    names = {
        "customer": f"Client {tag}",
        "supplier": f"Fournisseur {tag}",
        "product": f"Article {tag}",
        "category": f"Rayon {tag}",
        "expense_category": f"Charge {tag}",
    }
    shop.names += list(names.values())
    ids = shop.ids
    ids["company"] = str(shop.company.company_id)
    ids["manager"] = str(shop.company.manager_id)
    ids["category"] = _post(client, t, "/api/v1/categories", {"name": names["category"]})["id"]
    ids["product"] = _post(
        client,
        t,
        "/api/v1/products",
        {"name": names["product"], "unit_price": amount, "category_id": ids["category"]},
    )["id"]
    _post(
        client,
        t,
        "/api/v1/inventory/movements",
        {"product_id": ids["product"], "type": "initial", "qty_delta": "40", "unit_cost": "600"},
    )
    ids["customer"] = _post(
        client, t, "/api/v1/customers", {"name": names["customer"], "phone": "77 111 22 33"}
    )["id"]
    # Même nom chez A et chez B : seule la ligne de sa propre entreprise doit sortir.
    ids["twin"] = _post(client, t, "/api/v1/customers", {"name": "Moussa Fall"})["id"]
    ids["supplier"] = _post(client, t, "/api/v1/suppliers", {"name": names["supplier"]})["id"]
    sale = _post(client, t, "/api/v1/sales", {"customer_id": ids["customer"]})
    ids["sale"] = sale["id"]
    item = _post(
        client, t, f"/api/v1/sales/{sale['id']}/items", {"product_id": ids["product"], "qty": "1"}
    )
    ids["sale_item"] = item["id"]
    confirmed = _post(
        client, t, f"/api/v1/sales/{sale['id']}/confirm", {"paid_amount": "0", "method": "cash"}
    )
    debts = client.get(
        f"/api/v1/debts?customer_id={ids['customer']}", headers=auth_headers(t)
    ).json()["items"]
    ids["debt"] = debts[0]["id"]
    ids["payment"] = _post(
        client,
        t,
        "/api/v1/payments",
        {
            "direction": "inflow",
            "method": "cash",
            "amount": "1000",
            "allocations": [{"debt_id": ids["debt"], "amount": "1000"}],
        },
    )["id"]
    ids["expense_category"] = _post(
        client,
        t,
        "/api/v1/expense-categories",
        {"name": names["expense_category"], "kind": "variable"},
    )["id"]
    ids["expense"] = _post(
        client,
        t,
        "/api/v1/expenses",
        {
            "category_id": ids["expense_category"],
            "label": f"Dépense {tag}",
            "amount": amount,
            "spent_at": TODAY.isoformat(),
        },
    )["id"]
    shop.names.append(f"Dépense {tag}")
    ids["role"] = _post(client, t, "/api/v1/roles", {"name": f"Rôle {tag}"})["id"]
    shop.names.append(f"Rôle {tag}")
    ids["user"] = _post(
        client,
        t,
        "/api/v1/users",
        {
            "email": f"{tag.lower()}@example.com",
            "full_name": f"Personne {tag}",
            "password": "mot-de-passe-de-test-01",
            "role_ids": [role_id(client, t, "vendeur")],
        },
    )["id"]
    shop.names.append(f"Personne {tag}")
    ids["sale_no"] = confirmed["sale_no"]
    ctx = TenantContext(user_id=shop.company.manager_id, company_id=shop.company.company_id)
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        notification = NotificationRepository(ctx=ctx, session=session).add_for_user(
            user_id=shop.company.manager_id,
            notification_type="stock_low",
            title=f"Stock bas — {names['product']}",
            body=None,
            data={"product_id": ids["product"]},
        )
        session.flush()
        ids["notification"] = str(notification.id)


@pytest.fixture(scope="module")
def shops(
    app_bound_to_test_database: None, session_factory: sessionmaker[Any]
) -> Iterator[tuple[Shop, Shop]]:
    marker = uuid4().hex[:6]
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        a = _create_demo_company(f"lecture-a-{marker}")
        b = _create_demo_company(f"lecture-b-{marker}")
        shop_a = Shop(a, login_token(client, a))
        shop_b = Shop(b, login_token(client, b))
        _fill(client, shop_a, f"Amark{marker}", session_factory, "1000")
        _fill(client, shop_b, f"Bmark{marker}", session_factory, B_AMOUNT)
        yield shop_a, shop_b


def _b_markers(b: Shop) -> list[str]:
    return [*(v for k, v in b.ids.items() if k != "sale_no"), *b.names, B_AMOUNT, b.company.slug]


def _leaks(value: Any, markers: list[str], path: str = "$") -> list[str]:
    """Chemins du JSON où apparaît une trace de B."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            found += _leaks(key, markers, f"{path}.<clé>")
            found += _leaks(item, markers, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += _leaks(item, markers, f"{path}[{index}]")
    elif value is not None:
        rendered = str(value)
        found += [f"{path} = {rendered[:80]}" for m in markers if m in rendered]
    return found


@pytest.fixture
def client(app_bound_to_test_database: None) -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as test_client:
        yield test_client


def _read_paths() -> list[str]:
    return sorted(
        path
        for path, operations in app.openapi()["paths"].items()
        if "get" in operations and "{" not in path
    )


def test_every_read_route_is_classified() -> None:
    missing = [path for path in _read_paths() if path not in READ_ROUTES]
    stale = [path for path in READ_ROUTES if path not in _read_paths()]
    assert missing == [], f"Lectures à classer dans READ_ROUTES : {missing}"
    assert stale == [], f"Entrées sans route : {stale}"


TENANT_READS = sorted(path for path, (kind, _) in READ_ROUTES.items() if kind == TENANT)


@pytest.mark.parametrize("path", TENANT_READS)
def test_a_read_shows_nothing_of_the_other_company(
    path: str, client: TestClient, shops: tuple[Shop, Shop]
) -> None:
    a, b = shops
    response = client.get(path, headers=auth_headers(a.token), params=READ_ROUTES[path][1])
    assert response.status_code == 200, f"{path} : {response.status_code} {response.text}"
    assert _leaks(response.json(), _b_markers(b)) == []


@pytest.fixture(scope="module")
def support_of_a(
    shops: tuple[Shop, Shop],
    platform_bound_to_test_database: None,
    platform_session_factory: sessionmaker[Any],
) -> str:
    """Jeton d'accès support sur A (ADR 0092) : même périmètre que tout jeton tenant."""
    account = create_platform_account("support")
    _, token = open_support_session(
        platform_session_factory, shops[0].company.company_id, account.id
    )
    return token


@pytest.mark.parametrize("path", TENANT_READS)
def test_a_support_read_shows_nothing_of_the_other_company(
    path: str, client: TestClient, shops: tuple[Shop, Shop], support_of_a: str
) -> None:
    """Le jeton de support lit A comme un utilisateur de A — en transaction `READ ONLY`,
    sans jamais tomber en 500 — et rien de B. Hors de ses permissions : 403."""
    _, b = shops
    response = client.get(path, headers=auth_headers(support_of_a), params=READ_ROUTES[path][1])
    assert response.status_code in (200, 403), f"{path} : {response.status_code} {response.text}"
    assert _leaks(response.json(), _b_markers(b)) == []


def _file_text(response: Any, fmt: str) -> str:
    """Texte d'un export : le CSV tel quel, le .xlsx par ses fichiers XML internes."""
    if fmt == "csv":
        return str(response.content.decode("utf-8-sig", errors="replace"))
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return "".join(
            archive.read(name).decode("utf-8", errors="replace")
            for name in archive.namelist()
            if name.endswith(".xml")
        )


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
@pytest.mark.parametrize("kind", EXPORTS)
def test_an_export_file_holds_nothing_of_the_other_company(
    kind: str, fmt: str, client: TestClient, shops: tuple[Shop, Shop]
) -> None:
    a, b = shops
    response = client.get(
        f"/api/v1/exports/referentials/{kind}",
        headers=auth_headers(a.token),
        params={"format": fmt},
    )
    assert response.status_code == 200, response.text
    content = _file_text(response, fmt)
    assert [m for m in _b_markers(b) if m in content] == []
    assert any(m in content for m in a.names), "l'export de A doit contenir A"


#: Filtres par identifiant : glisser l'identifiant d'une ressource de B.
HOSTILE_FILTERS: list[tuple[str, str, str]] = [
    ("/api/v1/debts", "customer_id", "customer"),
    ("/api/v1/debts", "supplier_id", "supplier"),
    ("/api/v1/sales", "customer_id", "customer"),
    ("/api/v1/inventory/movements", "product_id", "product"),
    ("/api/v1/inventory/stock", "product_id", "product"),
    ("/api/v1/inventory/stock", "category_id", "category"),
    ("/api/v1/products", "category_id", "category"),
    ("/api/v1/categories", "parent_id", "category"),
    ("/api/v1/expenses", "category_id", "expense_category"),
    ("/api/v1/expenses", "supplier_id", "supplier"),
    ("/api/v1/forecasts", "product_id", "product"),
    ("/api/v1/audit-logs", "actor_user_id", "manager"),
    ("/api/v1/audit-logs", "entity_id", "sale"),
    ("/api/v1/analytics/history", "actor_user_id", "manager"),
]


@pytest.mark.parametrize(("path", "param", "source"), HOSTILE_FILTERS)
def test_filtering_by_an_id_of_the_other_company_reveals_nothing(
    path: str, param: str, source: str, client: TestClient, shops: tuple[Shop, Shop]
) -> None:
    a, b = shops
    response = client.get(
        path, headers=auth_headers(a.token), params={param: b.ids[source], **READ_ROUTES[path][1]}
    )
    assert response.status_code in (200, 404), response.text
    assert _leaks(response.json(), _b_markers(b)) == []
    if response.status_code == 200 and "items" in response.json():
        assert response.json()["items"] == []


SEARCHES = ["%", "_", "'", '"', "%' OR '1'='1", "Bmark", "\\", "*", "Moussa Fall"]
SEARCHABLE = [
    "/api/v1/customers",
    "/api/v1/suppliers",
    "/api/v1/products",
    "/api/v1/categories",
    "/api/v1/sales",
    "/api/v1/sales/customer-choices",
    "/api/v1/inventory/stock",
    "/api/v1/analytics/customers",
    "/api/v1/analytics/suppliers",
]


@pytest.mark.parametrize("path", SEARCHABLE)
@pytest.mark.parametrize("term", SEARCHES)
def test_searching_with_wildcards_leaks_nothing(
    path: str, term: str, client: TestClient, shops: tuple[Shop, Shop]
) -> None:
    a, b = shops
    response = client.get(path, headers=auth_headers(a.token), params={"search": term})
    assert response.status_code < 500, response.text
    if response.status_code == 200:
        assert _leaks(response.json(), _b_markers(b)) == []


@pytest.mark.parametrize(
    "params",
    [
        {"page": "999999"},
        {"page": "0"},
        {"page_size": "100000"},
        {"page_size": "-1"},
        {"sort": "company_id"},
        {"order_by": "password_hash"},
    ],
)
@pytest.mark.parametrize("path", ["/api/v1/customers", "/api/v1/sales", "/api/v1/payments"])
def test_odd_pagination_and_sorting_leak_nothing(
    path: str, params: dict[str, str], client: TestClient, shops: tuple[Shop, Shop]
) -> None:
    a, b = shops
    response = client.get(path, headers=auth_headers(a.token), params=params)
    assert response.status_code in (200, 422), response.text
    assert _leaks(response.json(), _b_markers(b)) == []


# ------------------------------------------------------------------ écritures croisées


def _cross_writes(b: Shop) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("POST", "/api/v1/sales", {"customer_id": b.ids["customer"]}),
        (
            "POST",
            "/api/v1/debts",
            {"party_type": "customer", "customer_id": b.ids["customer"], "principal": "500"},
        ),
        (
            "POST",
            "/api/v1/debts",
            {"party_type": "supplier", "supplier_id": b.ids["supplier"], "principal": "500"},
        ),
        (
            "POST",
            "/api/v1/payments",
            {
                "direction": "inflow",
                "method": "cash",
                "amount": "100",
                "allocations": [{"debt_id": b.ids["debt"], "amount": "100"}],
            },
        ),
        (
            "POST",
            "/api/v1/inventory/movements",
            {"product_id": b.ids["product"], "qty_delta": "-1", "reason_code": "damaged"},
        ),
        (
            "POST",
            "/api/v1/inventory/deliveries",
            {
                "supplier_id": b.ids["supplier"],
                "lines": [{"product_id": b.ids["product"], "qty": "1", "unit_cost": "100"}],
                "payment_mode": "later",
            },
        ),
        (
            "POST",
            "/api/v1/expenses",
            {
                "category_id": b.ids["expense_category"],
                "label": "Croisée",
                "amount": "100",
                "spent_at": TODAY.isoformat(),
            },
        ),
        (
            "POST",
            "/api/v1/products",
            {"name": "Croisé", "unit_price": "10", "category_id": b.ids["category"]},
        ),
        (
            "POST",
            "/api/v1/categories",
            {"name": "Sous-rayon croisé", "parent_id": b.ids["category"]},
        ),
        ("POST", "/api/v1/users", {"full_name": "Croisé", "role_ids": [b.ids["role"]]}),
    ]


def test_an_id_of_the_other_company_in_a_write_body_has_no_effect(
    client: TestClient,
    shops: tuple[Shop, Shop],
    owner_engine: Engine,
    session_factory: sessionmaker[Any],
) -> None:
    from tests.integration.test_commit_failure_all_writes import snapshot

    a, b = shops
    before = snapshot(owner_engine, session_factory, a.company.company_id)
    for method, path, body in _cross_writes(b):
        response = client.request(method, path, headers=write_headers(a.token), json=body)
        assert response.status_code in (404, 409, 422), f"{path} {body} → {response.status_code}"
        assert _leaks(response.json(), [n for n in b.names]) == []
    # Ventes : une ligne qui pointe un article de B, sur un brouillon de A.
    sale = client.post("/api/v1/sales", headers=write_headers(a.token), json={}).json()
    middle = snapshot(owner_engine, session_factory, a.company.company_id)
    line = client.post(
        f"/api/v1/sales/{sale['id']}/items",
        headers=write_headers(a.token),
        json={"product_id": b.ids["product"], "qty": "1"},
    )
    assert line.status_code in (404, 422), line.text
    returned = client.post(
        f"/api/v1/sales/{a.ids['sale']}/returns",
        headers=write_headers(a.token),
        json={"lines": [{"sale_item_id": b.ids["sale_item"], "qty": "1"}]},
    )
    assert returned.status_code in (404, 409, 422), returned.text
    after = snapshot(owner_engine, session_factory, a.company.company_id)
    assert {t for t in before if before[t] != middle[t]} <= {
        "sales",
        "document_counters",
        "audit_logs",
        "idempotency_keys",
    }, "seul le brouillon de test a pu être écrit"
    assert [t for t in middle if middle[t] != after[t]] == [], "écriture croisée acceptée"


# ------------------------------------------------------------------ rôles et jetons


MANAGER_ONLY = ["/api/v1/users", "/api/v1/audit-logs", "/api/v1/system/outbox", "/api/v1/roles"]


def test_a_salesperson_cannot_read_manager_screens(
    client: TestClient, shops: tuple[Shop, Shop]
) -> None:
    a, _ = shops
    token = create_user_with_role(
        client, a.token, a.company, role="vendeur", email=f"v-{uuid4().hex[:6]}@example.com"
    )
    for path in MANAGER_ONLY:
        response = client.get(path, headers=auth_headers(token))
        assert response.status_code == 403, f"{path} : {response.status_code}"


def test_a_token_stays_in_its_company_whatever_the_request_says(
    client: TestClient, shops: tuple[Shop, Shop]
) -> None:
    a, b = shops
    forged = {
        **auth_headers(a.token),
        "X-Company-Id": b.ids["company"],
        "X-Company-Slug": b.company.slug,
        "X-Tenant-Id": b.ids["company"],
    }
    for path in ["/api/v1/customers", "/api/v1/companies/me", "/api/v1/dashboard"]:
        response = client.get(
            path, headers=forged, params={"company_id": b.ids["company"], "company": b.company.slug}
        )
        assert response.status_code == 200, response.text
        assert _leaks(response.json(), _b_markers(b)) == []
    me = client.get("/api/v1/companies/me", headers=forged).json()
    assert me["id"] == a.ids["company"]


def test_an_expired_token_is_refused_without_data(
    client: TestClient, shops: tuple[Shop, Shop]
) -> None:
    a, _ = shops
    settings = get_settings()
    now = int(time.time())
    expired = jwt.encode(
        {
            "sub": a.ids["manager"],
            "company_id": a.ids["company"],
            "typ": "access",
            "aud": "coges-tenant",
            "jti": str(uuid4()),
            "iat": now - 3600,
            "exp": now - 60,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    response = client.get("/api/v1/customers", headers=auth_headers(expired))
    assert response.status_code == 401
    assert set(response.json()) == {"error"}


def test_a_token_of_a_deleted_company_is_refused(
    client: TestClient, owner_engine: Engine, app_bound_to_test_database: None
) -> None:
    gone = _create_demo_company(f"fermee-{uuid4().hex[:6]}")
    token = login_token(client, gone)
    assert client.get("/api/v1/customers", headers=auth_headers(token)).status_code == 200
    # `companies` est en RLS FORCE : même le propriétaire ne la voit qu'avec le contexte.
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :id, true)"), {"id": str(gone.company_id)}
        )
        updated = connection.execute(
            text("UPDATE companies SET deleted_at = now() WHERE id = :id"), {"id": gone.company_id}
        ).rowcount
    assert updated == 1
    response = client.get("/api/v1/customers", headers=auth_headers(token))
    assert response.status_code in (401, 403), response.text
    assert set(response.json()) == {"error"}


def test_the_idempotency_key_of_a_and_b_never_mix(
    client: TestClient, shops: tuple[Shop, Shop]
) -> None:
    """Même clé envoyée par A et par B : deux traitements indépendants (complète C3)."""
    a, b = shops
    key = uuid4().hex
    created = []
    for shop in (a, b):
        response = client.post(
            "/api/v1/debts",
            headers={**auth_headers(shop.token), IDEMPOTENCY_HEADER: key},
            json={
                "party_type": "supplier",
                "supplier_id": shop.ids["supplier"],
                "principal": "250",
            },
        )
        assert response.status_code == 201, response.text
        created.append(response.json()["id"])
    assert created[0] != created[1]
