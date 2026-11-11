"""Notifications sur le téléphone (Web Push, prompt 36, bloc N, ADR 0120).

Abonnement pour soi seul, adresses de services connus seulement, plafond d'appareils,
isolation entre entreprises ; envoi après le COMMIT par le worker, chiffré pour
l'appareil (relu ici avec sa clé), sans montant, 404/410 qui arrêtent l'abonnement,
rafale regroupée, personne qui agit non dérangée, plafond horaire.

Aucun appel réseau : le client HTTP du worker est remplacé par un transport simulé.
"""

from __future__ import annotations

import itertools
import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import http_ece  # type: ignore[import-untyped]
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core import cache, webpush
from app.core import queue as queue_module
from app.core.config import get_settings
from app.core.events.inbox import Event
from app.core.events.types import EventType
from app.modules.inventory.events import stock_updated_payload
from app.modules.notifications import service as notifications_service
from app.workers.tasks import notifications as notification_tasks
from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    lift_user_cap,
    login_token,
    read_scalar_in_tenant,
)
from tests.integration.test_sales_api import _token_for_role

pytestmark = pytest.mark.integration

PUSH = "/api/v1/notifications/push"
PUBLIC_KEY, PRIVATE_KEY = webpush.generate_vapid_keys()
_ids = itertools.count(950_000_000)


@pytest.fixture(scope="module")
def shop(app_bound_to_test_database: None, owner_engine: Engine) -> DemoCompany:
    company = _create_demo_company(f"push-{uuid4().hex[:6]}")
    lift_user_cap(owner_engine, company.company_id)
    return company


@pytest.fixture
def token(api_client: TestClient, shop: DemoCompany) -> str:
    return login_token(api_client, shop)


def _settings(monkeypatch: pytest.MonkeyPatch, **update: Any) -> None:
    patched = get_settings().model_copy(
        update={
            "vapid_public_key": PUBLIC_KEY,
            "vapid_private_key": SecretStr(PRIVATE_KEY),
            "vapid_subject": "mailto:equipe@coges.example",
            **update,
        }
    )
    for module in (notifications_service, notification_tasks):
        monkeypatch.setattr(module, "get_settings", lambda: patched)


@pytest.fixture
def push_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Ce que `notify()` enfile après le COMMIT, au lieu de Redis."""
    calls: list[dict[str, Any]] = []

    def fake(task_name: str, **kwargs: Any) -> bool:
        calls.append({"task": task_name, **kwargs})
        return True

    monkeypatch.setattr(queue_module, "enqueue", fake)
    return calls


@pytest.fixture(autouse=True)
def clean_push_counters() -> Iterator[None]:
    client = cache.get_client()
    if client is not None:
        for key in client.scan_iter("coges:*:push:*"):
            client.delete(key)
    yield


class Device:
    """Un navigateur : sa clé privée lit ce que le serveur chiffre pour lui."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = f"https://fcm.googleapis.com/fcm/send/{uuid4().hex}"
        public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self.body = {
            "endpoint": self.endpoint,
            "keys": {
                "p256dh": webpush.b64url_encode(public),
                "auth": webpush.b64url_encode(self.auth),
            },
            "device_label": "Téléphone Android",
        }

    def read(self, content: bytes) -> dict[str, Any]:
        clear = http_ece.decrypt(
            content, private_key=self.key, auth_secret=self.auth, version="aes128gcm"
        )
        return dict(json.loads(clear))


def _subscribe(client: TestClient, token: str, device: Device) -> Any:
    return client.post(f"{PUSH}/subscriptions", headers=auth_headers(token), json=device.body)


def _live(session_factory: sessionmaker[Any], company: DemoCompany, endpoint: str) -> Any:
    return read_scalar_in_tenant(
        session_factory,
        company.company_id,
        "SELECT coalesce(disabled_reason, 'live') FROM push_subscriptions WHERE endpoint = :e "
        "ORDER BY created_at DESC LIMIT 1",
        {"e": endpoint},
    )


class PushServer:
    """Le service de push simulé : note chaque envoi, répond le code voulu."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status: Callable[[httpx.Request], int] = lambda _: 201

    def client(self, **_: Any) -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status(request))

        return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture
def push_server(monkeypatch: pytest.MonkeyPatch) -> PushServer:
    server = PushServer()
    monkeypatch.setattr(notification_tasks, "httpx", SimpleNamespace(Client=server.client))
    return server


def _stock_out(client: TestClient, token: str, company: DemoCompany) -> UUID:
    """Un article épuisé : l'alerte `stock_out` est créée par le vrai consommateur."""
    product = client.post(
        "/api/v1/products",
        headers=auth_headers(token),
        json={
            "name": f"Riz 25 kg {uuid4().hex[:4]}",
            "unit": "sac",
            "is_stock_tracked": True,
            "reorder_point": "5.000",
            "unit_price": "16500.00",
        },
    )
    assert product.status_code == 201, product.text
    product_id = UUID(product.json()["id"])
    notification_tasks.on_stock_updated(
        **Event(
            id=next(_ids),
            company_id=company.company_id,
            event_type=EventType.STOCK_UPDATED,
            aggregate_type="product",
            aggregate_id=product_id,
            payload=stock_updated_payload(
                product_id=product_id,
                qty_on_hand=Decimal("0"),
                avg_cost=Decimal("15000.0000"),
                movement_id=uuid4(),
                below_reorder_point=True,
            ),
            occurred_at=datetime.now(UTC),
        ).as_message()
    )
    return product_id


def _deliver(company: DemoCompany, enqueued: list[dict[str, Any]]) -> int:
    """Joue ce que `notify()` a enfilé, comme le worker."""
    sent = 0
    for call in enqueued:
        assert call["task"] == "notifications.push_deliver"
        assert call["company_id"] == str(company.company_id)
        sent += notification_tasks.push_deliver(call["company_id"], call["ids"])
    enqueued.clear()
    return sent


# ------------------------------------------------------------------- abonnement


def test_without_keys_there_is_no_button_and_no_subscription(
    api_client: TestClient, token: str
) -> None:
    config = api_client.get(f"{PUSH}/config", headers=auth_headers(token))
    assert config.status_code == 200, config.text
    assert config.json() == {"public_key": None}
    refused = _subscribe(api_client, token, Device())
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "push_unavailable"


def test_a_device_subscribes_for_its_person_only(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    push_on: None,
    session_factory: sessionmaker[Any],
) -> None:
    assert api_client.get(f"{PUSH}/config", headers=auth_headers(token)).json() == {
        "public_key": PUBLIC_KEY
    }
    device = Device()
    created = _subscribe(api_client, token, device)
    assert created.status_code == 201, created.text
    assert set(created.json()) == {"id", "device_label", "created_at"}, "jamais les clés"
    mine = api_client.get(f"{PUSH}/subscriptions", headers=auth_headers(token)).json()["items"]
    assert created.json()["id"] in [item["id"] for item in mine]

    # Le même navigateur qui s'abonne à nouveau ne double rien.
    again = _subscribe(api_client, token, device)
    assert again.json()["id"] == created.json()["id"]

    removed = api_client.post(
        f"{PUSH}/subscriptions/remove",
        headers=auth_headers(token),
        json={"endpoint": device.endpoint},
    )
    assert removed.status_code == 204, removed.text
    assert _live(session_factory, shop, device.endpoint) == "unsubscribed"


def test_logout_stops_the_subscription_of_this_device(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    push_on: None,
    session_factory: sessionmaker[Any],
) -> None:
    device = Device()
    assert _subscribe(api_client, token, device).status_code == 201
    removed = api_client.post(
        f"{PUSH}/subscriptions/remove?logout=true",
        headers=auth_headers(token),
        json={"endpoint": device.endpoint},
    )
    assert removed.status_code == 204
    assert _live(session_factory, shop, device.endpoint) == "logout"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.example.com/push",
        "http://fcm.googleapis.com/fcm/send/abc",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_an_unknown_push_service_is_refused(
    api_client: TestClient, token: str, push_on: None, endpoint: str
) -> None:
    device = Device()
    refused = api_client.post(
        f"{PUSH}/subscriptions",
        headers=auth_headers(token),
        json={**device.body, "endpoint": endpoint},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "push_endpoint_refused"


def test_a_sixth_device_replaces_the_oldest(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    push_on: None,
    session_factory: sessionmaker[Any],
) -> None:
    seller = _token_for_role(api_client, token, shop, "vendeur")
    devices = [Device() for _ in range(6)]
    for device in devices:
        assert _subscribe(api_client, seller, device).status_code == 201
    mine = api_client.get(f"{PUSH}/subscriptions", headers=auth_headers(seller)).json()["items"]
    assert len(mine) == 5
    assert _live(session_factory, shop, devices[0].endpoint) == "replaced"
    assert _live(session_factory, shop, devices[5].endpoint) == "live"


def test_a_shared_phone_follows_the_person_logged_in(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    push_on: None,
    session_factory: sessionmaker[Any],
) -> None:
    device = Device()
    assert _subscribe(api_client, token, device).status_code == 201
    seller = _token_for_role(api_client, token, shop, "vendeur")
    assert _subscribe(api_client, seller, device).status_code == 201
    owners = read_scalar_in_tenant(
        session_factory,
        shop.company_id,
        "SELECT count(*) FROM push_subscriptions WHERE endpoint = :e AND disabled_at IS NULL",
        {"e": device.endpoint},
    )
    assert owners == 1


def test_another_company_neither_sees_nor_stops_a_subscription(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    company_beta: DemoCompany,
    push_on: None,
    session_factory: sessionmaker[Any],
) -> None:
    device = Device()
    assert _subscribe(api_client, token, device).status_code == 201
    beta = login_token(api_client, company_beta)
    seen = api_client.get(f"{PUSH}/subscriptions", headers=auth_headers(beta)).json()["items"]
    assert seen == []
    api_client.post(
        f"{PUSH}/subscriptions/remove",
        headers=auth_headers(beta),
        json={"endpoint": device.endpoint},
    )
    assert _live(session_factory, shop, device.endpoint) == "live"


# ------------------------------------------------------------------------ envoi


def test_an_alert_reaches_the_phone_after_commit_without_any_amount(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    push_on: None,
    enqueued: list[dict[str, Any]],
    push_server: PushServer,
) -> None:
    device = Device()
    assert _subscribe(api_client, token, device).status_code == 201

    product_id = _stock_out(api_client, token, shop)
    assert len(enqueued) == 1, "enfilé une fois, après le COMMIT de l'alerte"
    assert push_server.requests == [], "rien ne part dans la transaction"

    assert _deliver(shop, enqueued) == 1
    [request] = [r for r in push_server.requests if str(r.url) == device.endpoint]
    assert request.headers["Content-Encoding"] == "aes128gcm"
    assert request.headers["Authorization"].startswith("vapid t=")
    message = device.read(request.content)
    assert message["title"].endswith("est épuisé")
    assert "16" not in message["title"] + message["body"], "pas le prix de l'article"
    assert message["url"] == f"/inventory/receive?product={product_id}"
    assert message["tag"] == "coges-alertes"


def test_a_gone_subscription_is_stopped(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    push_on: None,
    enqueued: list[dict[str, Any]],
    push_server: PushServer,
    session_factory: sessionmaker[Any],
) -> None:
    device = Device()
    assert _subscribe(api_client, token, device).status_code == 201
    push_server.status = lambda request: 410 if str(request.url) == device.endpoint else 201
    _stock_out(api_client, token, shop)
    _deliver(shop, enqueued)
    assert _live(session_factory, shop, device.endpoint) == "gone"


def test_no_push_to_the_person_who_cancelled(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    push_on: None,
    enqueued: list[dict[str, Any]],
    push_server: PushServer,
) -> None:
    """La gérante qui annule n'est pas dérangée ; l'alerte reste dans sa cloche."""
    device = Device()
    assert _subscribe(api_client, token, device).status_code == 201
    sale_id = uuid4()
    notification_tasks.on_sale_cancelled(
        **Event(
            id=next(_ids),
            company_id=shop.company_id,
            event_type=EventType.SALE_CANCELLED,
            aggregate_type="sale",
            aggregate_id=sale_id,
            payload={
                "sale_no": "V-000042",
                "total": "87500.00",
                "reason": "Erreur de saisie",
                "cancelled_by_user_id": str(shop.manager_id),
            },
            occurred_at=datetime.now(UTC),
        ).as_message()
    )
    assert _deliver(shop, enqueued) == 0
    assert [r for r in push_server.requests if str(r.url) == device.endpoint] == []
    feed = api_client.get(
        "/api/v1/notifications?page_size=100", headers=auth_headers(token)
    ).json()["items"]
    assert any(item["data"].get("sale_id") == str(sale_id) for item in feed)


def test_a_burst_becomes_a_single_message(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    push_on: None,
    enqueued: list[dict[str, Any]],
    push_server: PushServer,
) -> None:
    device = Device()
    assert _subscribe(api_client, token, device).status_code == 201
    for _ in range(5):
        _stock_out(api_client, token, shop)
    ids = [item for call in enqueued for item in call["ids"]]
    enqueued.clear()
    notification_tasks.push_deliver(str(shop.company_id), ids)

    mine = [device.read(r.content) for r in push_server.requests if str(r.url) == device.endpoint]
    assert len(mine) == 1
    assert mine[0]["title"].endswith("nouvelles alertes")
    assert mine[0]["url"] == "/notifications"


def test_the_hourly_cap_holds(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[dict[str, Any]],
    push_server: PushServer,
) -> None:
    _settings(monkeypatch, push_max_per_hour=1)
    device = Device()
    assert _subscribe(api_client, token, device).status_code == 201
    _stock_out(api_client, token, shop)
    _deliver(shop, enqueued)
    _stock_out(api_client, token, shop)
    _deliver(shop, enqueued)
    assert len([r for r in push_server.requests if str(r.url) == device.endpoint]) == 1
