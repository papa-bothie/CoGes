"""Les alertes : qui les reçoit, et pourquoi elles ne se répètent pas.

Trois propriétés, et ce sont les trois seules qui comptent.

**Le destinataire se déduit d'un droit**, jamais d'un nom de rôle : c'est celui qui
peut agir qu'on dérange. Le gérant ajuste le stock, donc il entend parler d'une
rupture ; le vendeur encaisse, donc il n'en entend pas parler.

**Une alerte décrit une situation, pas un flux.** Un article sous son seuil le reste
tant qu'on ne l'a pas réapprovisionné : sans fenêtre de déduplication, chaque vente
rouvrirait la même alerte et le fil cesserait d'avertir de quoi que ce soit.

**Le fil est personnel.** Aucune route ne permet de désigner quelqu'un d'autre, ni
d'émettre : une alerte naît d'un worker, après COMMIT, jamais d'un appel client.

Les tâches sont appelées **directement**, sans Celery ni Redis : ce qui est éprouvé
ici, c'est le consommateur, pas le transport. Le transport, c'est T40.
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.events.inbox import Event
from app.core.events.types import EventType
from app.modules.inventory.events import stock_updated_payload
from app.workers.tasks.notifications import on_sale_cancelled, on_stock_updated, scan_due_debts
from tests.conftest import (
    DemoCompany,
    auth_headers,
    create_user_with_role,
    write_headers,
)

pytestmark = pytest.mark.integration

NOTIFICATIONS = "/api/v1/notifications"

#: Identifiants d'événements fabriqués. `processed_events` ne porte **aucune** clé
#: étrangère vers `business_events` (révision 0010), donc un identifiant synthétique
#: suffit — et il évite de dépendre de l'ordre d'exécution de la suite.
_ids = itertools.count(900_000_000)


def _stock_event(company_id: UUID, product_id: UUID, *, qty: str, below: bool) -> Event:
    """Un `stock.updated` tel que l'Inventory l'émet, corps compris."""
    return Event(
        id=next(_ids),
        company_id=company_id,
        event_type=EventType.STOCK_UPDATED,
        aggregate_type="product",
        aggregate_id=product_id,
        payload=stock_updated_payload(
            product_id=product_id,
            qty_on_hand=Decimal(qty),
            avg_cost=Decimal("600.0000"),
            movement_id=uuid4(),
            below_reorder_point=below,
        ),
        occurred_at=datetime.now(UTC),
    )


def _product(client: TestClient, token: str) -> UUID:
    """Un produit suivi en stock, seuil d'alerte à 5."""
    response = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={
            "sku": f"ALERT-{uuid4().hex[:8]}",
            "name": f"Article {uuid4().hex[:6]}",
            "unit": "piece",
            "is_stock_tracked": True,
            "reorder_point": "5.000",
            "unit_price": "1000.00",
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def _feed(client: TestClient, token: str, **params: Any) -> list[dict[str, Any]]:
    """Le fil de l'utilisateur du jeton, page complète."""
    query = "&".join(f"{key}={value}" for key, value in {"page_size": 100, **params}.items())
    response = client.get(f"{NOTIFICATIONS}?{query}", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def _about(feed: list[dict[str, Any]], entity_id: UUID) -> list[dict[str, Any]]:
    """Les alertes du fil qui concernent cette entité, et elles seules."""
    return [item for item in feed if item["data"].get("entity_id") == str(entity_id)]


def _unread(client: TestClient, token: str) -> int:
    response = client.get(f"{NOTIFICATIONS}/unread-count", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    count: int = response.json()["unread"]
    return count


# ------------------------------------------------------------------ stock


def test_a_stock_below_its_threshold_alerts_those_who_can_act(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """`stock_low` nomme le produit, et porte de quoi y donner suite."""
    product_id = _product(api_client, alpha_token)

    result = on_stock_updated(
        **_stock_event(company_alpha.company_id, product_id, qty="3.000", below=True).as_message()
    )

    assert result == "handled"
    alerts = _about(_feed(api_client, alpha_token), product_id)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "stock_low"
    assert alerts[0]["data"]["qty_on_hand"] == "3.000"
    assert alerts[0]["read_at"] is None


def test_an_empty_stock_is_named_a_stock_out(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Zéro n'est pas « bas » : c'est une rupture, et l'alerte le dit.

    Les deux situations appellent deux décisions différentes — réapprovisionner
    bientôt, ou cesser de vendre tout de suite. Les confondre coûterait une vente.
    """
    product_id = _product(api_client, alpha_token)

    on_stock_updated(
        **_stock_event(company_alpha.company_id, product_id, qty="0.000", below=True).as_message()
    )

    alerts = _about(_feed(api_client, alpha_token), product_id)
    assert [alert["type"] for alert in alerts] == ["stock_out"]


def test_a_healthy_stock_alerts_nobody_but_is_still_processed(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """« Rien à faire » est un traitement : la marque est posée, le fil reste vide.

    Sans cela, chaque mouvement normal — l'immense majorité — serait rejoué à chaque
    reprise du worker, pour ne toujours rien produire.
    """
    product_id = _product(api_client, alpha_token)

    result = on_stock_updated(
        **_stock_event(company_alpha.company_id, product_id, qty="40.000", below=False).as_message()
    )

    assert result == "handled"
    assert _about(_feed(api_client, alpha_token), product_id) == []


def test_the_same_situation_is_not_reported_twice_in_the_window(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Deux événements **différents** sur le même produit ⇒ une seule alerte.

    C'est la déduplication, et non l'idempotence : les deux événements sont bien
    traités tous les deux — deux marques dans `processed_events` — mais le second
    n'écrit pas d'alerte, parce que la première décrit déjà la situation.
    """
    product_id = _product(api_client, alpha_token)
    company = company_alpha.company_id

    first = on_stock_updated(
        **_stock_event(company, product_id, qty="3.000", below=True).as_message()
    )
    second = on_stock_updated(
        **_stock_event(company, product_id, qty="2.000", below=True).as_message()
    )

    assert (first, second) == ("handled", "handled")
    assert len(_about(_feed(api_client, alpha_token), product_id)) == 1


def test_two_products_in_trouble_do_not_silence_each_other(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """La fenêtre porte sur (type, **entité**, destinataire), pas sur le type seul.

    Sans l'entité, le gérant n'entendrait parler que du premier produit en rupture de
    la journée — et ignorerait les dix suivants.
    """
    first_id = _product(api_client, alpha_token)
    second_id = _product(api_client, alpha_token)
    company = company_alpha.company_id

    on_stock_updated(**_stock_event(company, first_id, qty="0.000", below=True).as_message())
    on_stock_updated(**_stock_event(company, second_id, qty="0.000", below=True).as_message())

    feed = _feed(api_client, alpha_token)
    assert len(_about(feed, first_id)) == 1
    assert len(_about(feed, second_id)) == 1


def test_only_those_who_may_adjust_the_stock_are_alerted(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Le vendeur n'a pas `inventory:update` : la rupture ne l'atteint pas.

    Le destinataire vient du **droit**, pas du nom du rôle : un rôle personnalisé qui
    porterait `inventory:update` recevrait l'alerte sans qu'une ligne change ici.
    """
    seller_token = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"vendeur-alerte-{uuid4().hex[:8]}@alpha.example.com",
    )
    product_id = _product(api_client, alpha_token)

    on_stock_updated(
        **_stock_event(company_alpha.company_id, product_id, qty="0.000", below=True).as_message()
    )

    assert len(_about(_feed(api_client, alpha_token), product_id)) == 1
    assert _about(_feed(api_client, seller_token), product_id) == []


# ------------------------------------------------------------------ dettes


def test_a_due_debt_is_reported_to_those_who_follow_debts(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Une échéance ne produit aucun événement : c'est le calendrier qui la trouve.

    Une dette arrive à terme précisément quand **rien ne bouge**. Le balayage
    quotidien est donc la seule façon de la voir, et `today` est paramétrable pour
    que le test n'ait pas à geler l'horloge du processus.
    """
    supplier = api_client.post(
        "/api/v1/suppliers",
        headers=auth_headers(alpha_token),
        json={"name": f"F {uuid4().hex[:6]}"},
    )
    assert supplier.status_code == 201, supplier.text
    due_on = date.today() - timedelta(days=3)
    debt = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={
            "party_type": "supplier",
            "supplier_id": supplier.json()["id"],
            "principal": "750.00",
            "due_date": due_on.isoformat(),
        },
    )
    assert debt.status_code == 201, debt.text
    debt_id = UUID(debt.json()["id"])

    sent = scan_due_debts(str(company_alpha.company_id), date.today().isoformat())

    assert sent >= 1
    alerts = _about(_feed(api_client, alpha_token), debt_id)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "debt_due"
    assert alerts[0]["data"]["balance"] == "750.00"

    # Deuxième passage le même jour : la fenêtre de 24 h tient, le fil ne grossit pas.
    scan_due_debts(str(company_alpha.company_id), date.today().isoformat())
    assert len(_about(_feed(api_client, alpha_token), debt_id)) == 1


def test_a_debt_not_yet_due_is_left_alone(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Prévenir d'une échéance qui n'est pas atteinte, c'est apprendre à ignorer le fil."""
    supplier = api_client.post(
        "/api/v1/suppliers",
        headers=auth_headers(alpha_token),
        json={"name": f"F {uuid4().hex[:6]}"},
    )
    assert supplier.status_code == 201, supplier.text
    debt = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={
            "party_type": "supplier",
            "supplier_id": supplier.json()["id"],
            "principal": "400.00",
            "due_date": (date.today() + timedelta(days=10)).isoformat(),
        },
    )
    assert debt.status_code == 201, debt.text

    scan_due_debts(str(company_alpha.company_id), date.today().isoformat())

    assert _about(_feed(api_client, alpha_token), UUID(debt.json()["id"])) == []


# ------------------------------------------------------------ vente annulée


def test_a_cancelled_sale_reaches_those_who_may_cancel(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """L'alerte accompagne l'audit critique, elle ne le remplace pas (§ 6)."""
    sale_id = uuid4()
    event = Event(
        id=next(_ids),
        company_id=company_alpha.company_id,
        event_type=EventType.SALE_CANCELLED,
        aggregate_type="sale",
        aggregate_id=sale_id,
        payload={"sale_no": "V-000777", "total": "5000.00", "reason": "Erreur de caisse"},
        occurred_at=datetime.now(UTC),
    )

    assert on_sale_cancelled(**event.as_message()) == "handled"

    alerts = _about(_feed(api_client, alpha_token), sale_id)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "sale_cancelled"
    assert "V-000777" in alerts[0]["title"]
    assert "Erreur de caisse" in (alerts[0]["body"] or "")


# ----------------------------------------------------- textes à la française


def test_alert_texts_read_like_the_screen(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Montants en FCFA sans décimales, milliers séparés, dates jj/mm/aaaa (ADR 0057).

    Le texte est lu tel quel par l'écran : « 21830.00 » ou « 2026-09-17 » y seraient
    des valeurs brutes. Les champs `data`, eux, gardent leur forme machine.
    """
    nnbsp, nbsp = "\u202f", "\u00a0"

    product_id = _product(api_client, alpha_token)
    on_stock_updated(
        **_stock_event(
            company_alpha.company_id, product_id, qty="1500.500", below=True
        ).as_message()
    )
    stock = _about(_feed(api_client, alpha_token), product_id)[0]
    assert f"Il reste 1{nnbsp}500,5 de " in stock["body"]
    assert stock["data"]["qty_on_hand"] == "1500.500"

    sale_id = uuid4()
    on_sale_cancelled(
        **Event(
            id=next(_ids),
            company_id=company_alpha.company_id,
            event_type=EventType.SALE_CANCELLED,
            aggregate_type="sale",
            aggregate_id=sale_id,
            payload={"sale_no": "V-000888", "total": "12000.00", "reason": ""},
            occurred_at=datetime.now(UTC),
        ).as_message()
    )
    cancelled = _about(_feed(api_client, alpha_token), sale_id)[0]
    assert cancelled["body"] == f"La vente V-000888 (12{nnbsp}000{nbsp}FCFA) a été annulée."
    assert cancelled["data"]["total"] == "12000.00"

    supplier = api_client.post(
        "/api/v1/suppliers",
        headers=auth_headers(alpha_token),
        json={"name": f"F {uuid4().hex[:6]}"},
    )
    assert supplier.status_code == 201, supplier.text
    due_on = date.today() - timedelta(days=5)
    debt = api_client.post(
        "/api/v1/debts",
        headers=write_headers(alpha_token),
        json={
            "party_type": "supplier",
            "supplier_id": supplier.json()["id"],
            "principal": "21830.40",
            "due_date": due_on.isoformat(),
        },
    )
    assert debt.status_code == 201, debt.text
    scan_due_debts(str(company_alpha.company_id), date.today().isoformat())
    due = _about(_feed(api_client, alpha_token), UUID(debt.json()["id"]))[0]
    assert due["body"] == (
        f"Une dette de 21{nnbsp}830{nbsp}FCFA est échue depuis le {due_on:%d/%m/%Y}."
    )
    assert due["data"]["due_date"] == due_on.isoformat()


# ------------------------------------------------------------------- le fil


def test_the_feed_is_personal(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Chacun lit le sien. Aucune route ne permet de désigner quelqu'un d'autre."""
    accountant_token = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="comptable",
        email=f"comptable-fil-{uuid4().hex[:8]}@alpha.example.com",
    )
    product_id = _product(api_client, alpha_token)

    on_stock_updated(
        **_stock_event(company_alpha.company_id, product_id, qty="0.000", below=True).as_message()
    )

    assert _about(_feed(api_client, accountant_token), product_id) == []


def test_marking_an_alert_as_read_moves_the_counter(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Lue, puis rendue à l'état non lu : le compteur suit dans les deux sens.

    Revenir en arrière est un besoin réel — on ouvre par erreur, on veut y revenir —
    d'où un booléen explicite plutôt qu'une action à sens unique.
    """
    product_id = _product(api_client, alpha_token)
    on_stock_updated(
        **_stock_event(company_alpha.company_id, product_id, qty="0.000", below=True).as_message()
    )
    alert_id = _about(_feed(api_client, alpha_token), product_id)[0]["id"]
    before = _unread(api_client, alpha_token)

    read = api_client.patch(
        f"{NOTIFICATIONS}/{alert_id}", headers=auth_headers(alpha_token), json={"read": True}
    )
    assert read.status_code == 200, read.text
    assert read.json()["read_at"] is not None
    assert _unread(api_client, alpha_token) == before - 1
    assert _about(_feed(api_client, alpha_token, unread="true"), product_id) == []

    unread = api_client.patch(
        f"{NOTIFICATIONS}/{alert_id}", headers=auth_headers(alpha_token), json={"read": False}
    )
    assert unread.status_code == 200, unread.text
    assert unread.json()["read_at"] is None
    assert _unread(api_client, alpha_token) == before


def test_another_persons_alert_is_not_found(
    api_client: TestClient, alpha_token: str, company_alpha: DemoCompany
) -> None:
    """Marquer l'alerte d'autrui ⇒ 404, pas 403 : elle n'existe pas pour lui.

    Le fil est filtré par `user_id` avant tout : la question « existe-t-elle ? » ne
    se pose donc jamais, et rien n'est révélé.
    """
    seller_token = create_user_with_role(
        api_client,
        alpha_token,
        company_alpha,
        role="vendeur",
        email=f"vendeur-404-{uuid4().hex[:8]}@alpha.example.com",
    )
    product_id = _product(api_client, alpha_token)
    on_stock_updated(
        **_stock_event(company_alpha.company_id, product_id, qty="0.000", below=True).as_message()
    )
    alert_id = _about(_feed(api_client, alpha_token), product_id)[0]["id"]

    response = api_client.patch(
        f"{NOTIFICATIONS}/{alert_id}", headers=auth_headers(seller_token), json={"read": True}
    )

    assert response.status_code == 404


def test_a_foreign_companys_alert_is_not_found(
    api_client: TestClient, alpha_token: str, beta_token: str, company_beta: DemoCompany
) -> None:
    """Même réponse d'un tenant à l'autre, pour la même raison."""
    product_id = _product(api_client, beta_token)
    on_stock_updated(
        **_stock_event(company_beta.company_id, product_id, qty="0.000", below=True).as_message()
    )
    alert_id = _about(_feed(api_client, beta_token), product_id)[0]["id"]

    response = api_client.patch(
        f"{NOTIFICATIONS}/{alert_id}", headers=auth_headers(alpha_token), json={"read": True}
    )

    assert response.status_code == 404
