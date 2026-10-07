"""Module Inventory par l'API : endpoints, permissions, idempotence, annulation.

Les invariants de stock sont prouvés en base par T6 à T13 et T38. Ce fichier
vérifie ce qui relève du module : ce que le schéma refuse d'emblée, ce que la
matrice RBAC autorise, ce que le service écrit en plus du mouvement (audit critique
et outbox), et la forme des erreurs métier.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.idempotency import IDEMPOTENCY_HEADER
from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    auth_headers,
    read_scalar_in_tenant,
)

pytestmark = pytest.mark.integration


def _role_id(client: TestClient, token: str, name: str) -> str:
    response = client.get("/api/v1/roles?page_size=50", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return next(role["id"] for role in response.json()["items"] if role["name"] == name)


def _token_for_role(client: TestClient, token: str, company: DemoCompany, role: str) -> str:
    """Compte porteur d'un rôle système, et son jeton d'accès."""
    email = f"{role}-{uuid4().hex[:8]}@{company.slug}.example.com"
    created = client.post(
        "/api/v1/users",
        headers=auth_headers(token),
        json={
            "email": email,
            "full_name": f"Compte {role}",
            "password": TEST_PASSWORD,
            "role_ids": [_role_id(client, token, role)],
        },
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        json={"company_slug": company.slug, "email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    access_token: str = login.json()["access_token"]
    return access_token


def _make_product(client: TestClient, token: str, **overrides: Any) -> str:
    marker = uuid4().hex[:8]
    payload: dict[str, Any] = {
        "sku": f"SKU-{marker}",
        "name": f"Article {marker}",
        "unit_price": "1500.00",
    }
    payload.update(overrides)
    response = client.post("/api/v1/products", headers=auth_headers(token), json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _record(client: TestClient, token: str, product_id: str, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "product_id": product_id,
        "type": "initial",
        "qty_delta": "100",
        "unit_cost": "10",
    }
    payload.update(overrides)
    headers = auth_headers(token)
    idempotency_key = payload.pop("idempotency_key", None)
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return client.post("/api/v1/inventory/movements", headers=headers, json=payload)


# ------------------------------------------------------- ce que le schéma refuse


@pytest.mark.parametrize("movement_type", ["sale_out", "customer_return_in"])
def test_sale_flow_types_are_not_reachable_from_the_api(
    api_client: TestClient, alpha_token: str, movement_type: str
) -> None:
    """Les types réservés aux ventes n'existent pas dans le schéma d'entrée.

    Le refus est structurel, pas conditionnel : ces deux types arriveront par le
    service, appelé depuis Sales, jamais par une saisie humaine.
    """
    product_id = _make_product(api_client, alpha_token)
    response = _record(
        api_client, alpha_token, product_id, type=movement_type, qty_delta="-1", unit_cost=None
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


@pytest.mark.parametrize("movement_type", ["adjustment", "loss"])
def test_adjustment_and_loss_require_a_reason(
    api_client: TestClient, alpha_token: str, movement_type: str
) -> None:
    """Sans motif écrit, pas d'écriture de stock hors flux métier."""
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id).status_code == 201

    response = _record(
        api_client, alpha_token, product_id, type=movement_type, qty_delta="-5", unit_cost=None
    )
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert any("motif" in field["message"] for field in fields), fields


def test_an_outflow_cannot_carry_a_cost(api_client: TestClient, alpha_token: str) -> None:
    """Le coût d'une sortie est le CMP : il se constate, il ne se saisit pas."""
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id).status_code == 201

    response = _record(
        api_client,
        alpha_token,
        product_id,
        type="loss",
        qty_delta="-5",
        unit_cost="999",
        note="tentative",
    )
    assert response.status_code == 422


# -------------------------------------------------------------- règles métier


def test_initial_stock_can_only_be_set_once(api_client: TestClient, alpha_token: str) -> None:
    """`ref_id = product_id` rend l'unicité du stock initial structurelle."""
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id).status_code == 201

    response = _record(api_client, alpha_token, product_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "initial_stock_already_set"


def test_an_idempotency_key_rejects_the_double_submit(
    api_client: TestClient, alpha_token: str
) -> None:
    """Deux fois la même clé : la seconde réception n'entre pas."""
    product_id = _make_product(api_client, alpha_token)
    key = str(uuid4())

    first = _record(
        api_client,
        alpha_token,
        product_id,
        type="purchase_in",
        qty_delta="10",
        unit_cost="10",
        idempotency_key=key,
    )
    assert first.status_code == 201, first.text

    second = _record(
        api_client,
        alpha_token,
        product_id,
        type="purchase_in",
        qty_delta="10",
        unit_cost="10",
        idempotency_key=key,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_movement"


def test_insufficient_stock_names_the_available_quantity(
    api_client: TestClient, alpha_token: str
) -> None:
    """L'erreur dit combien il reste : le gérant corrige sa saisie sans chercher."""
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id, qty_delta="5").status_code == 201

    response = _record(
        api_client, alpha_token, product_id, type="loss", qty_delta="-6", unit_cost=None, note="x"
    )
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "insufficient_stock"
    assert body["details"]["available"] == "5.000"


def test_an_untracked_product_refuses_every_movement(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le service rend la main avant la base, avec le même verdict."""
    product_id = _make_product(api_client, alpha_token, is_stock_tracked=False)
    response = _record(api_client, alpha_token, product_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_not_stock_tracked"


def test_backdating_beyond_the_window_is_a_named_business_error(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le SQLSTATE `CG010` ressort en erreur métier, pas en 500."""
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id).status_code == 201

    response = _record(
        api_client,
        alpha_token,
        product_id,
        type="purchase_in",
        qty_delta="10",
        unit_cost="10",
        occurred_at=(datetime.now(UTC) - timedelta(hours=72)).isoformat(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "movement_backdated_too_far"


def test_a_future_date_is_named_immediately_by_the_schema(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le message arrive avant la base, et nomme le champ fautif.

    Le contrôle existe aussi en base (`CG011`, révision 0005), pour les appels qui
    n'entrent pas par l'API et pour un décalage d'horloge défavorable.
    """
    product_id = _make_product(api_client, alpha_token)
    response = _record(
        api_client,
        alpha_token,
        product_id,
        occurred_at=(datetime.now(UTC) + timedelta(days=365)).isoformat(),
    )
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert any("dans le futur" in field["message"] for field in fields), fields


def test_a_positive_adjustment_defaults_to_the_current_average(
    api_client: TestClient, alpha_token: str
) -> None:
    """Retrouver de la marchandise ne déforme pas le CMP (ADR 0016)."""
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id, qty_delta="100").status_code == 201

    found = _record(
        api_client,
        alpha_token,
        product_id,
        type="adjustment",
        qty_delta="10",
        unit_cost=None,
        note="inventaire : 10 de plus",
    )
    assert found.status_code == 201, found.text
    assert found.json()["unit_cost"] == "10.0000"

    line = _stock_line(api_client, alpha_token, product_id)
    assert line["avg_cost"] == "10.0000"
    assert line["qty_on_hand"] == "110.000"


def test_a_positive_adjustment_without_any_average_demands_a_cost(
    api_client: TestClient, alpha_token: str
) -> None:
    """Sans CMP à reprendre, on ne devine pas : le coût devient obligatoire."""
    product_id = _make_product(api_client, alpha_token)
    response = _record(
        api_client,
        alpha_token,
        product_id,
        type="adjustment",
        qty_delta="10",
        unit_cost=None,
        note="trouvé sans historique",
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "unit_cost_required"


def test_the_response_shows_what_the_triggers_wrote(
    api_client: TestClient, alpha_token: str
) -> None:
    """Une sortie est renvoyée estampillée au CMP, pas au coût envoyé.

    Les triggers `BEFORE INSERT` réécrivent la ligne ; sans relecture, l'API
    répondrait `unit_cost = 0` alors que la base porte le CMP. Le gérant lirait un
    coût de perte nul dans son journal.
    """
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id, qty_delta="100").status_code == 201
    assert (
        _record(
            api_client,
            alpha_token,
            product_id,
            type="purchase_in",
            qty_delta="100",
            unit_cost="20",
        ).status_code
        == 201
    )

    loss = _record(
        api_client,
        alpha_token,
        product_id,
        type="loss",
        qty_delta="-10",
        unit_cost=None,
        note="casse",
    )
    assert loss.status_code == 201, loss.text
    assert loss.json()["unit_cost"] == "15.0000", "le CMP estampillé, pas le coût envoyé"

    journal = api_client.get(
        f"/api/v1/inventory/movements?product_id={product_id}&type=loss",
        headers=auth_headers(alpha_token),
    )
    assert journal.json()["items"][0]["unit_cost"] == "15.0000"


# ---------------------------------------------------------------- annulation


def test_reverse_restores_the_stock_and_refuses_the_second_call(
    api_client: TestClient, alpha_token: str
) -> None:
    """Un mouvement ne s'annule qu'une fois, et son inverse ne s'annule pas."""
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id, qty_delta="100").status_code == 201

    loss = _record(
        api_client,
        alpha_token,
        product_id,
        type="loss",
        qty_delta="-10",
        unit_cost=None,
        note="casse",
    )
    assert loss.status_code == 201, loss.text
    loss_id = loss.json()["id"]

    reversal = api_client.post(
        f"/api/v1/inventory/movements/{loss_id}/reverse", headers=auth_headers(alpha_token)
    )
    assert reversal.status_code == 201, reversal.text
    body = reversal.json()
    assert body["reversal_of_movement_id"] == loss_id
    assert body["qty_delta"] == "10.000"
    assert _stock_line(api_client, alpha_token, product_id)["qty_on_hand"] == "100.000"

    again = api_client.post(
        f"/api/v1/inventory/movements/{loss_id}/reverse", headers=auth_headers(alpha_token)
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_reversed"

    on_reversal = api_client.post(
        f"/api/v1/inventory/movements/{body['id']}/reverse", headers=auth_headers(alpha_token)
    )
    assert on_reversal.status_code == 409
    assert on_reversal.json()["error"]["code"] == "movement_not_reversible"


def test_a_sale_movement_is_not_reversed_from_the_stock(
    api_client: TestClient, alpha_token: str
) -> None:
    """Inverser une sortie de vente la remettrait en stock sous une vente confirmée.

    Un flux se corrige par son propre cas d'usage — annulation ou retour —, jamais
    depuis le journal (ADR 0017, complément de la phase 12).
    """
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id, qty_delta="10").status_code == 201
    headers = auth_headers(alpha_token)
    sale = api_client.post("/api/v1/sales", headers=headers, json={}).json()
    api_client.post(
        f"/api/v1/sales/{sale['id']}/items",
        headers=headers,
        json={"product_id": product_id, "qty": "2", "discount": "0"},
    )
    total = api_client.get(f"/api/v1/sales/{sale['id']}", headers=headers).json()["total"]
    confirmed = api_client.post(
        f"/api/v1/sales/{sale['id']}/confirm",
        headers={**headers, IDEMPOTENCY_HEADER: uuid4().hex},
        json={"paid_amount": total, "method": "cash"},
    )
    assert confirmed.status_code == 200, confirmed.text

    journal = api_client.get(
        f"/api/v1/inventory/movements?product_id={product_id}&type=sale_out", headers=headers
    ).json()
    sale_out = journal["items"][0]["id"]

    refused = api_client.post(f"/api/v1/inventory/movements/{sale_out}/reverse", headers=headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "movement_not_reversible"
    assert _stock_line(api_client, alpha_token, product_id)["qty_on_hand"] == "8.000"


# --------------------------------------------------------------------- lecture


def _stock_line(client: TestClient, token: str, product_id: str) -> Any:
    response = client.get(
        "/api/v1/inventory/stock", params={"product_id": product_id}, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["product_id"] == product_id)


def test_stock_view_joins_the_product_sheet_and_computes_the_status(
    api_client: TestClient, alpha_token: str
) -> None:
    """SKU, catégorie, seuil et statut : la vue de l'ADR 0012, côté Inventory."""
    category = api_client.post(
        "/api/v1/categories",
        headers=auth_headers(alpha_token),
        json={"name": f"Boissons {uuid4().hex[:6]}"},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]

    product_id = _make_product(api_client, alpha_token, category_id=category_id, reorder_point="20")
    assert _record(api_client, alpha_token, product_id, qty_delta="100").status_code == 201

    line = _stock_line(api_client, alpha_token, product_id)
    assert line["category_id"] == category_id
    assert line["category_name"] == category.json()["name"]
    assert line["reorder_point"] == "20.000"
    assert line["stock_value"] == "1000.00"
    assert line["status"] == "ok"

    assert (
        _record(
            api_client,
            alpha_token,
            product_id,
            type="loss",
            qty_delta="-85",
            unit_cost=None,
            note="sinistre",
        ).status_code
        == 201
    )
    assert _stock_line(api_client, alpha_token, product_id)["status"] == "low"

    assert (
        _record(
            api_client,
            alpha_token,
            product_id,
            type="loss",
            qty_delta="-15",
            unit_cost=None,
            note="sinistre",
        ).status_code
        == 201
    )
    assert _stock_line(api_client, alpha_token, product_id)["status"] == "out"


def test_the_journal_is_filterable_by_product_and_type(
    api_client: TestClient, alpha_token: str
) -> None:
    """Le journal se lit par produit, par type et par période."""
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id, qty_delta="100").status_code == 201
    assert (
        _record(
            api_client,
            alpha_token,
            product_id,
            type="loss",
            qty_delta="-1",
            unit_cost=None,
            note="casse",
        ).status_code
        == 201
    )

    everything = api_client.get(
        f"/api/v1/inventory/movements?product_id={product_id}",
        headers=auth_headers(alpha_token),
    )
    assert everything.status_code == 200
    assert everything.json()["total"] == 2
    # Le plus récent d'abord.
    assert everything.json()["items"][0]["type"] == "loss"

    losses = api_client.get(
        f"/api/v1/inventory/movements?product_id={product_id}&type=loss",
        headers=auth_headers(alpha_token),
    )
    assert losses.json()["total"] == 1


# ------------------------------------------------------ audit, outbox, RBAC


def test_an_adjustment_writes_a_critical_audit_entry_and_an_event(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Audit critique et outbox sont écrits **dans** la transaction du mouvement."""
    product_id = _make_product(api_client, alpha_token)
    assert _record(api_client, alpha_token, product_id, qty_delta="100").status_code == 201
    adjustment = _record(
        api_client,
        alpha_token,
        product_id,
        type="adjustment",
        qty_delta="-4",
        unit_cost=None,
        note="inventaire annuel",
    )
    assert adjustment.status_code == 201, adjustment.text
    movement_id = adjustment.json()["id"]

    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs "
        "WHERE entity_table = 'inventory_movements' AND entity_id = :id",
        {"id": movement_id},
    )
    assert audited == 1

    unpublished = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM business_events "
        "WHERE event_type = 'stock.updated' AND aggregate_id = :product_id "
        "  AND published_at IS NULL AND payload->>'movement_id' = :movement_id",
        {"product_id": product_id, "movement_id": movement_id},
    )
    assert unpublished == 1, "l'événement reste à publier : le relais est phase 08"


def test_a_plain_reception_relies_on_the_journal_rather_than_on_audit(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Seules les écritures hors flux métier passent en audit critique.

    Une réception est déjà tracée, et de façon inaltérable : par le journal
    lui-même, append-only et signé par `created_by`.
    """
    product_id = _make_product(api_client, alpha_token)
    reception = _record(api_client, alpha_token, product_id, qty_delta="100")
    assert reception.status_code == 201

    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs "
        "WHERE entity_table = 'inventory_movements' AND entity_id = :id",
        {"id": reception.json()["id"]},
    )
    assert audited == 0


@pytest.mark.parametrize("role", ["vendeur", "comptable"])
def test_only_the_manager_writes_stock(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany, role: str
) -> None:
    """Vendeur et comptable lisent le stock ; aucun des deux ne l'écrit (ADR 0007)."""
    token = _token_for_role(api_client, alpha_token, company_alpha, role)
    product_id = _make_product(api_client, alpha_token)

    assert api_client.get("/api/v1/inventory/stock", headers=auth_headers(token)).status_code == 200

    refused = _record(api_client, token, product_id)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["required_permission"] == "inventory:create"

    movement = _record(api_client, alpha_token, product_id)
    assert movement.status_code == 201
    reversal = api_client.post(
        f"/api/v1/inventory/movements/{movement.json()['id']}/reverse",
        headers=auth_headers(token),
    )
    assert reversal.status_code == 403
    assert reversal.json()["error"]["details"]["required_permission"] == "inventory:update"
