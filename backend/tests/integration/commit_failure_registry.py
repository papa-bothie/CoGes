"""Registre des écritures face à un COMMIT refusé (lot C, C1 ; ADR 0086).

Chaque route POST/PUT/PATCH/DELETE de l'API y est classée :

* `Critical` — écriture testée par `test_commit_failure_all_writes.py` : son scénario
  prépare l'état nécessaire (par l'API, transactions validées) puis décrit l'appel ;
* `Exempt` — avec la raison écrite.

Une route ajoutée plus tard et absente d'ici fait échouer la CI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.notifications.repository import NotificationRepository
from tests.conftest import DemoCompany, auth_headers, role_id, write_headers

#: Écritures qui exigent `Idempotency-Key` (ADR 0027) : la clé y est enregistrée avec
#: la réponse, donc un rejeu identique doit rendre la même réponse sans réécrire.
KEYED = frozenset(
    {
        "/api/v1/payments",
        "/api/v1/payments/{payment_id}/cancel",
        "/api/v1/debts",
        "/api/v1/expenses",
        "/api/v1/sales/{sale_id}/confirm",
        "/api/v1/sales/{sale_id}/returns",
        "/api/v1/sale-returns/{return_id}/refunds",
        "/api/v1/imports/{kind}",
        "/api/v1/inventory/deliveries",
    }
)


@dataclass(frozen=True, slots=True)
class Call:
    method: str
    path: str
    json: Any = None
    files: dict[str, Any] | None = None
    params: dict[str, str] | None = None


@dataclass
class World:
    """Fabrique les objets dont un scénario a besoin, par l'API, comme un client."""

    client: TestClient
    token: str
    company: DemoCompany
    session_factory: sessionmaker[Any]
    analytics_factory: sessionmaker[Any]
    cache: dict[str, str] = field(default_factory=dict)

    # -- appels ------------------------------------------------------------------
    def post(self, path: str, json: Any = None) -> dict[str, Any]:
        response = self.client.post(path, headers=write_headers(self.token), json=json)
        assert response.status_code in (200, 201), f"{path} : {response.text}"
        return dict(response.json())

    def get(self, path: str) -> dict[str, Any]:
        response = self.client.get(path, headers=auth_headers(self.token))
        assert response.status_code == 200, f"{path} : {response.text}"
        return dict(response.json())

    @staticmethod
    def marker() -> str:
        return uuid4().hex[:8]

    # -- référentiels --------------------------------------------------------------
    def product(self, stock: str = "20") -> str:
        m = self.marker()
        product = self.post(
            "/api/v1/products",
            {"sku": f"C1-{m}", "name": f"Article C1 {m}", "unit_price": "1000.00"},
        )
        self.post(
            "/api/v1/inventory/movements",
            {
                "product_id": product["id"],
                "type": "initial",
                "qty_delta": stock,
                "unit_cost": "600",
            },
        )
        return str(product["id"])

    def customer(self) -> str:
        return str(self.post("/api/v1/customers", {"name": f"Client C1 {self.marker()}"})["id"])

    def supplier(self) -> str:
        return str(
            self.post("/api/v1/suppliers", {"name": f"Fournisseur C1 {self.marker()}"})["id"]
        )

    def category(self) -> str:
        return str(self.post("/api/v1/categories", {"name": f"Rayon C1 {self.marker()}"})["id"])

    def expense_category(self) -> str:
        return str(
            self.post(
                "/api/v1/expense-categories",
                {"name": f"Charge C1 {self.marker()}", "kind": "variable"},
            )["id"]
        )

    def expense(self) -> str:
        return str(
            self.post(
                "/api/v1/expenses",
                {
                    "category_id": self.expense_category(),
                    "label": "Dépense C1",
                    "amount": "2500",
                    "spent_at": date.today().isoformat(),
                },
            )["id"]
        )

    def role(self) -> str:
        return str(self.post("/api/v1/roles", {"name": f"Rôle C1 {self.marker()}"})["id"])

    def user(self) -> str:
        m = self.marker()
        return str(
            self.post(
                "/api/v1/users",
                {
                    "email": f"c1-{m}@example.com",
                    "full_name": f"Personne C1 {m}",
                    "password": "mot-de-passe-de-test-01",
                    "role_ids": [role_id(self.client, self.token, "vendeur")],
                },
            )["id"]
        )

    # -- ventes et argent ------------------------------------------------------------
    def draft_sale(self, *, customer: str | None = None) -> tuple[str, str]:
        sale = self.post("/api/v1/sales", {"customer_id": customer} if customer else {})
        item = self.post(
            f"/api/v1/sales/{sale['id']}/items", {"product_id": self.product(), "qty": "2"}
        )
        return str(sale["id"]), str(item["id"])

    def confirmed_sale(self) -> tuple[str, str, dict[str, Any]]:
        sale_id, item_id = self.draft_sale()
        total = self.get(f"/api/v1/sales/{sale_id}")["total"]
        confirmed = self.post(
            f"/api/v1/sales/{sale_id}/confirm", {"paid_amount": total, "method": "cash"}
        )
        return sale_id, item_id, confirmed

    def credit_sale(self) -> str:
        """Vente confirmée à crédit, sans encaissement : la seule qui s'annule."""
        sale_id, _ = self.draft_sale(customer=self.customer())
        self.post(f"/api/v1/sales/{sale_id}/confirm", {"paid_amount": "0", "method": "cash"})
        return sale_id

    def customer_debt(self) -> tuple[str, str]:
        customer = self.customer()
        sale_id, _ = self.draft_sale(customer=customer)
        self.post(f"/api/v1/sales/{sale_id}/confirm", {"paid_amount": "0", "method": "cash"})
        debts = self.get(f"/api/v1/debts?customer_id={customer}")["items"]
        return customer, str(debts[0]["id"])

    def payment(self) -> str:
        _, debt = self.customer_debt()
        return str(
            self.post(
                "/api/v1/payments",
                {
                    "direction": "inflow",
                    "method": "cash",
                    "amount": "500",
                    "allocations": [{"debt_id": debt, "amount": "500"}],
                },
            )["id"]
        )

    def sale_return(self) -> str:
        sale_id, item_id, _ = self.confirmed_sale()
        return str(
            self.post(
                f"/api/v1/sales/{sale_id}/returns",
                {"lines": [{"sale_item_id": item_id, "qty": "1"}]},
            )["id"]
        )

    def movement(self) -> str:
        product = self.product()
        return str(
            self.post(
                "/api/v1/inventory/movements",
                {"product_id": product, "qty_delta": "-1", "reason_code": "damaged"},
            )["id"]
        )

    # -- semés hors API (aucune route ne les crée) ---------------------------------------
    def notification(self) -> str:
        ctx = TenantContext(user_id=self.company.manager_id, company_id=self.company.company_id)
        with tenant_transaction(ctx, session_factory=self.session_factory) as session:
            row = NotificationRepository(ctx=ctx, session=session).add_for_user(
                user_id=self.company.manager_id,
                notification_type="stock_low",
                title="Stock bas — C1",
                body=None,
                data={},
            )
            session.flush()
            return str(row.id)

    def insight(self) -> str:
        ctx = TenantContext.bootstrap(self.company.company_id)
        with tenant_transaction(ctx, session_factory=self.analytics_factory) as session:
            return str(
                session.execute(
                    text(
                        "INSERT INTO insights (company_id, insight_type, severity, title, "
                        "dedupe_key) VALUES (:c, 'slow_mover', 'info', 'Écoulement lent — C1', "
                        ":k) RETURNING id"
                    ),
                    {"c": self.company.company_id, "k": f"c1-{self.marker()}"},
                ).scalar_one()
            )


Scenario = Callable[[World], Call]


@dataclass(frozen=True, slots=True)
class Critical:
    scenario: Scenario


@dataclass(frozen=True, slots=True)
class Exempt:
    reason: str


def _delivery(w: World) -> Call:
    return Call(
        "POST",
        "/api/v1/inventory/deliveries",
        {
            "supplier_id": w.supplier(),
            "lines": [{"product_id": w.product(), "qty": "5", "unit_cost": "650"}],
            "payment_mode": "now",
            "method": "cash",
        },
    )


def _new_product_with_stock(w: World) -> Call:
    m = w.marker()
    return Call(
        "POST",
        "/api/v1/inventory/products",
        {
            "name": f"Nouvel article C1 {m}",
            "unit_price": "1200",
            "opening_qty": "4",
            "cost_price": "700",
        },
    )


def _import_customers(w: World) -> Call:
    content = f"Nom;Téléphone\nImporté C1 {w.marker()};77 000 00 01\n".encode()
    return Call(
        "POST",
        "/api/v1/imports/customers",
        files={"file": ("import.csv", content, "application/octet-stream")},
    )


def _payment(w: World) -> Call:
    _, debt = w.customer_debt()
    return Call(
        "POST",
        "/api/v1/payments",
        {
            "direction": "inflow",
            "method": "wave",
            "amount": "700",
            "allocations": [{"debt_id": debt, "amount": "700"}],
        },
    )


def _confirm(w: World) -> Call:
    sale_id, _ = w.draft_sale()
    total = w.get(f"/api/v1/sales/{sale_id}")["total"]
    return Call(
        "POST", f"/api/v1/sales/{sale_id}/confirm", {"paid_amount": total, "method": "cash"}
    )


def _sale_return(w: World) -> Call:
    sale_id, item_id, _ = w.confirmed_sale()
    return Call(
        "POST",
        f"/api/v1/sales/{sale_id}/returns",
        {"lines": [{"sale_item_id": item_id, "qty": "1"}]},
    )


def _refund(w: World) -> Call:
    return Call(
        "POST",
        f"/api/v1/sale-returns/{w.sale_return()}/refunds",
        {"amount": "500", "method": "cash"},
    )


def _item(w: World) -> tuple[str, str]:
    return w.draft_sale()


REGISTRY: dict[tuple[str, str], Critical | Exempt] = {
    # --- Authentification : pas de transaction d'entreprise ouverte par le client.
    ("POST", "/api/v1/auth/login"): Exempt(
        "transaction d'identité puis de session, testée par test_login_throttle et "
        "test_temporary_password_expiry (aucune écriture métier)"
    ),
    ("POST", "/api/v1/auth/refresh"): Exempt(
        "rotation de session, couverte par test_auth (réutilisation, délai de grâce)"
    ),
    ("POST", "/api/v1/auth/logout"): Exempt("révocation de session, idempotente par nature"),
    ("POST", "/api/v1/auth/password"): Exempt(
        "mot de passe de la personne connectée : sa propre session, couverte par "
        "test_temporary_password_expiry ; aucun argent, aucun stock"
    ),
    # --- Ventes
    ("POST", "/api/v1/sales"): Critical(lambda w: Call("POST", "/api/v1/sales", {})),
    ("PATCH", "/api/v1/sales/{sale_id}"): Critical(
        lambda w: Call("PATCH", f"/api/v1/sales/{w.draft_sale()[0]}", {"customer_id": w.customer()})
    ),
    ("POST", "/api/v1/sales/{sale_id}/items"): Critical(
        lambda w: Call(
            "POST",
            f"/api/v1/sales/{w.post('/api/v1/sales', {})['id']}/items",
            {"product_id": w.product(), "qty": "1"},
        )
    ),
    ("PATCH", "/api/v1/sales/{sale_id}/items/{item_id}"): Critical(
        lambda w: (lambda s, i: Call("PATCH", f"/api/v1/sales/{s}/items/{i}", {"qty": "3"}))(
            *_item(w)
        )
    ),
    ("DELETE", "/api/v1/sales/{sale_id}/items/{item_id}"): Critical(
        lambda w: (lambda s, i: Call("DELETE", f"/api/v1/sales/{s}/items/{i}"))(*_item(w))
    ),
    ("POST", "/api/v1/sales/{sale_id}/confirm"): Critical(_confirm),
    ("POST", "/api/v1/sales/{sale_id}/cancel"): Critical(
        lambda w: Call(
            "POST", f"/api/v1/sales/{w.credit_sale()}/cancel", {"reason": "Erreur de saisie"}
        )
    ),
    ("POST", "/api/v1/sales/{sale_id}/returns"): Critical(_sale_return),
    ("POST", "/api/v1/sale-returns/{return_id}/refunds"): Critical(_refund),
    # --- Argent
    ("POST", "/api/v1/payments"): Critical(_payment),
    ("POST", "/api/v1/payments/{payment_id}/cancel"): Critical(
        lambda w: Call(
            "POST", f"/api/v1/payments/{w.payment()}/cancel", {"reason": "Erreur de saisie"}
        )
    ),
    ("POST", "/api/v1/debts"): Critical(
        lambda w: Call(
            "POST",
            "/api/v1/debts",
            {"party_type": "supplier", "supplier_id": w.supplier(), "principal": "15000"},
        )
    ),
    ("POST", "/api/v1/debts/{debt_id}/write-off"): Critical(
        lambda w: Call(
            "POST",
            f"/api/v1/debts/{w.customer_debt()[1]}/write-off",
            {"reason": "Client parti, créance jugée irrécouvrable"},
        )
    ),
    ("POST", "/api/v1/expense-categories"): Critical(
        lambda w: Call(
            "POST", "/api/v1/expense-categories", {"name": f"Charge {w.marker()}", "kind": "fixed"}
        )
    ),
    ("PATCH", "/api/v1/expense-categories/{category_id}"): Critical(
        lambda w: Call(
            "PATCH",
            f"/api/v1/expense-categories/{w.expense_category()}",
            {"name": f"Renommée {w.marker()}"},
        )
    ),
    ("POST", "/api/v1/expenses"): Critical(
        lambda w: Call(
            "POST",
            "/api/v1/expenses",
            {
                "category_id": w.expense_category(),
                "label": "Loyer C1",
                "amount": "40000",
                "spent_at": date.today().isoformat(),
            },
        )
    ),
    ("PATCH", "/api/v1/expenses/{expense_id}"): Critical(
        lambda w: Call("PATCH", f"/api/v1/expenses/{w.expense()}", {"amount": "3000"})
    ),
    ("DELETE", "/api/v1/expenses/{expense_id}"): Critical(
        lambda w: Call("DELETE", f"/api/v1/expenses/{w.expense()}")
    ),
    # --- Stock
    ("POST", "/api/v1/inventory/movements"): Critical(
        lambda w: Call(
            "POST",
            "/api/v1/inventory/movements",
            {"product_id": w.product(), "qty_delta": "-2", "reason_code": "count_error"},
        )
    ),
    ("POST", "/api/v1/inventory/movements/{movement_id}/reverse"): Critical(
        lambda w: Call("POST", f"/api/v1/inventory/movements/{w.movement()}/reverse")
    ),
    ("POST", "/api/v1/inventory/deliveries"): Critical(_delivery),
    ("POST", "/api/v1/inventory/products"): Critical(_new_product_with_stock),
    # --- Référentiels
    ("POST", "/api/v1/products"): Critical(
        lambda w: Call(
            "POST", "/api/v1/products", {"name": f"Produit {w.marker()}", "unit_price": "900"}
        )
    ),
    ("PATCH", "/api/v1/products/{product_id}"): Critical(
        lambda w: Call(
            "PATCH", f"/api/v1/products/{w.product()}", {"name": f"Renommé {w.marker()}"}
        )
    ),
    ("DELETE", "/api/v1/products/{product_id}"): Critical(
        lambda w: Call("DELETE", f"/api/v1/products/{w.product(stock='1')}")
    ),
    ("POST", "/api/v1/products/{product_id}/prices"): Critical(
        lambda w: Call("POST", f"/api/v1/products/{w.product()}/prices", {"unit_price": "1100.00"})
    ),
    ("POST", "/api/v1/categories"): Critical(
        lambda w: Call("POST", "/api/v1/categories", {"name": f"Rayon {w.marker()}"})
    ),
    ("PATCH", "/api/v1/categories/{category_id}"): Critical(
        lambda w: Call(
            "PATCH", f"/api/v1/categories/{w.category()}", {"name": f"Rayon {w.marker()}"}
        )
    ),
    ("DELETE", "/api/v1/categories/{category_id}"): Critical(
        lambda w: Call("DELETE", f"/api/v1/categories/{w.category()}")
    ),
    ("POST", "/api/v1/customers"): Critical(
        lambda w: Call("POST", "/api/v1/customers", {"name": f"Client {w.marker()}"})
    ),
    ("PATCH", "/api/v1/customers/{customer_id}"): Critical(
        lambda w: Call("PATCH", f"/api/v1/customers/{w.customer()}", {"phone": "77 123 45 67"})
    ),
    ("DELETE", "/api/v1/customers/{customer_id}"): Critical(
        lambda w: Call("DELETE", f"/api/v1/customers/{w.customer()}")
    ),
    ("POST", "/api/v1/suppliers"): Critical(
        lambda w: Call("POST", "/api/v1/suppliers", {"name": f"Fournisseur {w.marker()}"})
    ),
    ("PATCH", "/api/v1/suppliers/{supplier_id}"): Critical(
        lambda w: Call("PATCH", f"/api/v1/suppliers/{w.supplier()}", {"phone": "33 800 00 00"})
    ),
    ("DELETE", "/api/v1/suppliers/{supplier_id}"): Critical(
        lambda w: Call("DELETE", f"/api/v1/suppliers/{w.supplier()}")
    ),
    ("POST", "/api/v1/imports/{kind}"): Critical(_import_customers),
    # --- Personnes, rôles, réglages
    ("POST", "/api/v1/users"): Critical(
        lambda w: Call(
            "POST",
            "/api/v1/users",
            {
                "email": f"c1-{w.marker()}@example.com",
                "full_name": "Personne C1",
                "role_ids": [role_id(w.client, w.token, "vendeur")],
            },
        )
    ),
    ("PATCH", "/api/v1/users/{user_id}"): Critical(
        lambda w: Call("PATCH", f"/api/v1/users/{w.user()}", {"full_name": "Nom changé"})
    ),
    ("DELETE", "/api/v1/users/{user_id}"): Critical(
        lambda w: Call("DELETE", f"/api/v1/users/{w.user()}")
    ),
    ("POST", "/api/v1/users/{user_id}/password"): Critical(
        lambda w: Call("POST", f"/api/v1/users/{w.user()}/password", {})
    ),
    ("POST", "/api/v1/users/{user_id}/roles"): Critical(
        lambda w: Call(
            "POST",
            f"/api/v1/users/{w.user()}/roles",
            {"role_id": role_id(w.client, w.token, "comptable")},
        )
    ),
    ("DELETE", "/api/v1/users/{user_id}/roles/{role_id}"): Critical(
        lambda w: Call(
            "DELETE", f"/api/v1/users/{w.user()}/roles/{role_id(w.client, w.token, 'vendeur')}"
        )
    ),
    ("POST", "/api/v1/roles"): Critical(
        lambda w: Call("POST", "/api/v1/roles", {"name": f"Rôle {w.marker()}"})
    ),
    ("PATCH", "/api/v1/roles/{role_id}"): Critical(
        lambda w: Call("PATCH", f"/api/v1/roles/{w.role()}", {"description": "Décrit"})
    ),
    ("DELETE", "/api/v1/roles/{role_id}"): Critical(
        lambda w: Call("DELETE", f"/api/v1/roles/{w.role()}")
    ),
    ("PUT", "/api/v1/roles/{role_id}/abilities"): Critical(
        lambda w: Call(
            "PUT",
            f"/api/v1/roles/{role_id(w.client, w.token, 'vendeur')}/abilities",
            {"abilities": ["sell"]},
        )
    ),
    ("PATCH", "/api/v1/companies/me"): Critical(
        lambda w: Call("PATCH", "/api/v1/companies/me", {"receipt_footer": f"Merci {w.marker()}"})
    ),
    # --- Restitution
    ("POST", "/api/v1/exports/sales"): Critical(
        lambda w: Call(
            "POST",
            "/api/v1/exports/sales",
            {"date_from": date.today().isoformat(), "date_to": date.today().isoformat()},
        )
    ),
    ("POST", "/api/v1/notifications/read-all"): Critical(
        lambda w: (w.notification(), Call("POST", "/api/v1/notifications/read-all"))[1]
    ),
    ("PATCH", "/api/v1/notifications/{notification_id}"): Critical(
        lambda w: Call("PATCH", f"/api/v1/notifications/{w.notification()}", {"read": True})
    ),
    ("PATCH", "/api/v1/insights/{insight_id}"): Critical(
        lambda w: Call("PATCH", f"/api/v1/insights/{w.insight()}", {"status": "acknowledged"})
    ),
}


def write_routes(openapi: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, operations in openapi["paths"].items()
        for method in operations
        if method in ("post", "put", "patch", "delete")
    }


def company_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(value)
