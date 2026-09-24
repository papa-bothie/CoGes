"""Charges et familles de charges vues par l'API.

Ce que ces tests tiennent :

* la nature `fixed` / `variable` vit sur la **catégorie** (§ 8.6), et ne change
  plus dès que des charges y sont rangées — sinon la ventilation de tous les mois
  déjà présentés changerait rétroactivement ;
* une dépense est numérotée sans trou (`D-000001`, ADR 0021) ;
* elle se supprime **logiquement**, sous audit, et son numéro reste consommé ;
* `expense.created` est émis, et lui seul.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant, write_headers

pytestmark = pytest.mark.integration

CATEGORIES = "/api/v1/expense-categories"
EXPENSES = "/api/v1/expenses"


def _category(client: TestClient, token: str, *, kind: str = "fixed") -> str:
    created = client.post(
        CATEGORIES,
        headers=auth_headers(token),
        json={"name": f"Charge {uuid4().hex[:8]}", "kind": kind},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _expense(
    client: TestClient, token: str, category_id: str, *, amount: str = "50000.00", **extra: Any
) -> dict[str, Any]:
    created = client.post(
        EXPENSES,
        headers=write_headers(token),
        json={
            "category_id": category_id,
            "label": f"Charge {uuid4().hex[:6]}",
            "amount": amount,
            "spent_at": date.today().isoformat(),
            **extra,
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def test_a_category_carries_the_nature_of_its_charges(
    api_client: TestClient, alpha_token: str
) -> None:
    """Un loyer est fixe parce que c'est un loyer, pas parce qu'on l'a coché."""
    category_id = _category(api_client, alpha_token, kind="fixed")
    expense = _expense(api_client, alpha_token, category_id)
    assert expense["kind"] == "fixed"
    assert expense["category_id"] == category_id


def test_two_categories_cannot_share_a_name(api_client: TestClient, alpha_token: str) -> None:
    """`expense_categories_name_uq`, nommé avant que la base ne s'en charge."""
    name = f"Charge {uuid4().hex[:8]}"
    first = api_client.post(
        CATEGORIES, headers=auth_headers(alpha_token), json={"name": name, "kind": "fixed"}
    )
    assert first.status_code == 201, first.text

    second = api_client.post(
        CATEGORIES, headers=auth_headers(alpha_token), json={"name": name, "kind": "variable"}
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "expense_category_name_taken"


def test_the_nature_of_a_used_category_no_longer_changes(
    api_client: TestClient, alpha_token: str
) -> None:
    """Changer `kind` après coup réécrirait la ventilation des mois déjà clos."""
    category_id = _category(api_client, alpha_token, kind="fixed")

    renamed = api_client.patch(
        f"{CATEGORIES}/{category_id}",
        headers=auth_headers(alpha_token),
        json={"name": f"Loyer {uuid4().hex[:6]}"},
    )
    assert renamed.status_code == 200, renamed.text

    _expense(api_client, alpha_token, category_id)
    refused = api_client.patch(
        f"{CATEGORIES}/{category_id}",
        headers=auth_headers(alpha_token),
        json={"kind": "variable"},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "expense_category_in_use"


def test_expenses_are_numbered_without_a_gap(api_client: TestClient, alpha_token: str) -> None:
    """`D-000001`, `D-000002`… : la suite des pièces émises (ADR 0021)."""
    category_id = _category(api_client, alpha_token)
    numbers = [_expense(api_client, alpha_token, category_id)["expense_no"] for _ in range(3)]

    assert all(number.startswith("D-") for number in numbers), numbers
    values = [int(number.split("-")[1]) for number in numbers]
    assert values == list(range(values[0], values[0] + 3)), values


def test_creating_an_expense_is_audited_and_announced(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Écriture financière : audit critique dans la transaction, et outbox."""
    category_id = _category(api_client, alpha_token, kind="variable")
    expense = _expense(api_client, alpha_token, category_id, amount="12345.00")
    expense_id = UUID(str(expense["id"]))

    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT diff -> 'after' ->> 'amount' FROM audit_logs "
        " WHERE entity_table = 'expenses' AND entity_id = :id AND action = 'insert'",
        {"id": expense_id},
    )
    assert audited == "12345.00"

    kind = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT payload ->> 'kind' FROM business_events "
        " WHERE event_type = 'expense.created' AND aggregate_id = :id",
        {"id": expense_id},
    )
    assert kind == "variable", "l'analytique ventile sans relire les catégories"


def test_an_expense_is_deleted_logically_and_leaves_a_trace(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """La ligne reste, le numéro aussi : une charge effacée sans trace serait une
    trésorerie qu'on ne peut plus expliquer."""
    category_id = _category(api_client, alpha_token)
    expense = _expense(api_client, alpha_token, category_id)
    expense_id = UUID(str(expense["id"]))

    removed = api_client.delete(f"{EXPENSES}/{expense_id}", headers=auth_headers(alpha_token))
    assert removed.status_code == 204, removed.text

    gone = api_client.get(f"{EXPENSES}/{expense_id}", headers=auth_headers(alpha_token))
    assert gone.status_code == 404

    still_there = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM expenses WHERE id = :id AND deleted_at IS NOT NULL",
        {"id": expense_id},
    )
    assert still_there == 1, "suppression logique, jamais physique"

    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs "
        " WHERE entity_table = 'expenses' AND entity_id = :id AND action = 'delete'",
        {"id": expense_id},
    )
    assert audited == 1


def test_correcting_an_expense_keeps_the_previous_value(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """L'audit garde l'avant et l'après : c'est ce qui rend une enquête possible."""
    category_id = _category(api_client, alpha_token)
    expense = _expense(api_client, alpha_token, category_id, amount="1000.00")
    expense_id = UUID(str(expense["id"]))

    corrected = api_client.patch(
        f"{EXPENSES}/{expense_id}", headers=auth_headers(alpha_token), json={"amount": "1200.00"}
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["amount"] == "1200.00"

    before = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT diff -> 'before' ->> 'amount' FROM audit_logs "
        " WHERE entity_table = 'expenses' AND entity_id = :id AND action = 'update'",
        {"id": expense_id},
    )
    assert before == "1000.00"


def test_expenses_are_filtered_by_period_and_category(
    api_client: TestClient, alpha_token: str
) -> None:
    """Les deux questions d'un gérant : quand, et pour quoi."""
    category_id = _category(api_client, alpha_token)
    today = _expense(api_client, alpha_token, category_id)
    old_day = (date.today() - timedelta(days=60)).isoformat()
    older = api_client.post(
        EXPENSES,
        headers=write_headers(alpha_token),
        json={
            "category_id": category_id,
            "label": "Charge ancienne",
            "amount": "999.00",
            "spent_at": old_day,
        },
    )
    assert older.status_code == 201, older.text

    recent = api_client.get(
        f"{EXPENSES}?from={date.today().isoformat()}&to={date.today().isoformat()}&page_size=100",
        headers=auth_headers(alpha_token),
    )
    assert recent.status_code == 200, recent.text
    identifiers = [item["id"] for item in recent.json()["items"]]
    assert today["id"] in identifiers
    assert str(older.json()["id"]) not in identifiers

    by_category = api_client.get(
        f"{EXPENSES}?category_id={category_id}&page_size=100", headers=auth_headers(alpha_token)
    )
    assert by_category.status_code == 200
    assert {item["category_id"] for item in by_category.json()["items"]} == {category_id}


def test_an_expense_cannot_be_dated_far_in_the_future(
    api_client: TestClient, alpha_token: str
) -> None:
    """`CHECK (spent_at <= current_date + 1)` : une charge à venir n'est pas une charge."""
    category_id = _category(api_client, alpha_token)
    refused = api_client.post(
        EXPENSES,
        headers=write_headers(alpha_token),
        json={
            "category_id": category_id,
            "label": "Charge anticipée",
            "amount": "100.00",
            "spent_at": (date.today() + timedelta(days=30)).isoformat(),
        },
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "validation_failed"


def test_an_expense_can_name_its_supplier(api_client: TestClient, alpha_token: str) -> None:
    """Le fournisseur est facultatif, mais vérifié quand il est donné."""
    category_id = _category(api_client, alpha_token)
    supplier = api_client.post(
        "/api/v1/suppliers",
        headers=auth_headers(alpha_token),
        json={"name": f"Bailleur {uuid4().hex[:8]}"},
    )
    assert supplier.status_code == 201, supplier.text
    supplier_id = str(supplier.json()["id"])

    expense = _expense(api_client, alpha_token, category_id, supplier_id=supplier_id)
    assert expense["supplier_id"] == supplier_id

    refused = api_client.post(
        EXPENSES,
        headers=write_headers(alpha_token),
        json={
            "category_id": category_id,
            "label": "Charge sans fournisseur connu",
            "amount": "100.00",
            "spent_at": date.today().isoformat(),
            "supplier_id": str(uuid4()),
        },
    )
    assert refused.status_code == 404, refused.text


def test_paying_an_expense_is_an_outflow_bound_to_it(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le règlement d'une charge n'appartient pas à Expenses mais à Finance.

    `payments.expense_id` rattache le décaissement à sa pièce d'origine : c'est
    ce qui rend un export comptable ultérieur possible sans reprise de données.
    """
    category_id = _category(api_client, alpha_token)
    expense = _expense(api_client, alpha_token, category_id, amount="7500.00")

    paid = api_client.post(
        "/api/v1/payments",
        headers=write_headers(alpha_token),
        json={
            "direction": "outflow",
            "method": "cash",
            "amount": "7500.00",
            "expense_id": expense["id"],
        },
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["expense_id"] == expense["id"]
