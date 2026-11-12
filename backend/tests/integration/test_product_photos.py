"""Photo d'un article chez Cloudinary (prompt 36, bloc I, ADR 0121).

Un faux Cloudinary (transport httpx simulé) : aucun appel réseau. Il vérifie la
signature de chaque requête comme le vrai, garde ce qu'on lui dépose, et répond.

Ce qui est prouvé : l'image est ré-encodée (JPEG, 1600 px, sans EXIF ni GPS) avant de
partir, SVG et bombe refusés, identifiant aléatoire dans le dossier de l'entreprise ; la
suppression (retrait, changement, article supprimé) part après le COMMIT seulement ; le
balayage retire les orphelines d'un jour et plus ; isolation, droits, secret jamais rendu.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.parser import BytesParser
from email.policy import default as email_policy
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core import queue as queue_module
from app.core.config import get_settings
from app.modules.products import schemas as products_schemas
from app.modules.products import service as products_service
from app.workers.tasks import products as product_tasks
from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    lift_user_cap,
    login_token,
    read_scalar_in_tenant,
)
from tests.integration.test_commit_failure_all_writes import failing_commit
from tests.integration.test_sales_api import _make_product, _token_for_role

pytestmark = pytest.mark.integration

SECRET = "secret-de-test-cloudinary-0123456789"
API_KEY = "123456789012345"
CLOUD = "coges-test"


@pytest.fixture(scope="module")
def shop(app_bound_to_test_database: None, owner_engine: Engine) -> DemoCompany:
    company = _create_demo_company(f"photo-{uuid4().hex[:6]}")
    lift_user_cap(owner_engine, company.company_id)
    return company


@pytest.fixture
def token(api_client: TestClient, shop: DemoCompany) -> str:
    return login_token(api_client, shop)


class FakeCloudinary:
    """Ce que Cloudinary garde, et ce qu'il a reçu. `down` : injoignable."""

    def __init__(self) -> None:
        self.images: dict[str, dict[str, Any]] = {}
        self.uploads: list[dict[str, Any]] = []
        self.destroyed: list[str] = []
        self.down = False

    @staticmethod
    def _check(params: dict[str, str]) -> None:
        signed = {
            key: value
            for key, value in params.items()
            if key not in {"api_key", "signature", "signature_algorithm", "file"}
        }
        payload = "&".join(f"{key}={signed[key]}" for key in sorted(signed))
        assert params["signature_algorithm"] == "sha256"
        assert params["api_key"] == API_KEY
        assert params["signature"] == hashlib.sha256((payload + SECRET).encode()).hexdigest()

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("Cloudinary injoignable")
        path = request.url.path
        assert path.startswith(f"/v1_1/{CLOUD}/"), path
        if path.endswith("/resources/image/upload"):
            assert request.headers["authorization"].startswith("Basic ")
            prefix = request.url.params["prefix"]
            return httpx.Response(
                200,
                json={
                    "resources": [
                        {"public_id": key, "created_at": value["created_at"].isoformat()}
                        for key, value in self.images.items()
                        if key.startswith(prefix)
                    ]
                },
            )
        if path.endswith("/image/upload"):
            message = BytesParser(policy=email_policy).parsebytes(
                b"Content-Type: "
                + request.headers["content-type"].encode()
                + b"\r\n\r\n"
                + request.content
            )
            params: dict[str, str] = {}
            content = b""
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if name == "file":
                    content = part.get_payload(decode=True)
                else:
                    params[str(name)] = part.get_content().strip()
            self._check(params)
            image = Image.open(io.BytesIO(content))
            self.uploads.append({"params": params, "content": content, "image": image})
            public_id = params["public_id"]
            self.images[public_id] = {"created_at": datetime.now(UTC)}
            return httpx.Response(
                200,
                json={
                    "public_id": public_id,
                    "version": 1_700_000_000 + len(self.uploads),
                    "width": image.width,
                    "height": image.height,
                },
            )
        if path.endswith("/image/destroy"):
            params = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            self._check(params)
            self.destroyed.append(params["public_id"])
            found = self.images.pop(params["public_id"], None)
            return httpx.Response(200, json={"result": "ok" if found else "not found"})
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))


def _settings(monkeypatch: pytest.MonkeyPatch, **update: Any) -> None:
    patched = get_settings().model_copy(
        update={
            "cloudinary_cloud_name": CLOUD,
            "cloudinary_api_key": API_KEY,
            "cloudinary_api_secret": SecretStr(SECRET),
            **update,
        }
    )
    for module in (products_service, products_schemas):
        monkeypatch.setattr(module, "get_settings", lambda: patched)


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch) -> FakeCloudinary:
    fake = FakeCloudinary()
    _settings(monkeypatch)
    monkeypatch.setattr(products_service, "http_client", fake.client)
    return fake


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(task_name: str, **kwargs: Any) -> bool:
        calls.append({"task": task_name, **kwargs})
        return True

    monkeypatch.setattr(queue_module, "enqueue", fake)
    return calls


def _image(fmt: str = "JPEG", size: tuple[int, int] = (3000, 2000), **save: Any) -> bytes:
    image = Image.new("RGBA" if fmt == "PNG" else "RGB", size, (200, 120, 40, 128))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save)
    return buffer.getvalue()


def _gps_jpeg() -> bytes:
    """Une photo de téléphone : 3000 × 2000, avec la position GPS et l'appareil."""
    image = Image.new("RGB", (3000, 2000), (10, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "Fabricant du téléphone"  # Make
    exif[0x8825] = {1: "N", 2: (14.0, 41.0, 30.0), 3: "W", 4: (17.0, 26.0, 50.0)}  # GPS
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _put(
    client: TestClient, token: str, product_id: str, content: bytes, name: str = "a.jpg"
) -> Any:
    return client.put(
        f"/api/v1/products/{product_id}/photo",
        headers=auth_headers(token),
        files={"file": (name, content, "image/jpeg")},
    )


def _deliver_deletes(enqueued: list[dict[str, Any]]) -> None:
    for call in enqueued:
        assert call["task"] == "products.delete_photo"
        assert product_tasks.delete_photo(call["company_id"], call["public_id"]) is True
    enqueued.clear()


# ------------------------------------------------------------------ disponibilité


def test_without_an_account_the_photo_is_simply_unavailable(
    api_client: TestClient, token: str
) -> None:
    config = api_client.get("/api/v1/products/photos/config", headers=auth_headers(token))
    assert config.json() == {"enabled": False}
    product_id = _make_product(api_client, token)
    refused = _put(api_client, token, product_id, _image())
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "photo_unavailable"
    product = api_client.get(f"/api/v1/products/{product_id}", headers=auth_headers(token))
    assert product.json()["photo"] is None


# ---------------------------------------------------------------------- envoi


def test_a_phone_photo_is_cleaned_resized_and_stored_under_a_random_id(
    api_client: TestClient, token: str, shop: DemoCompany, cloud: FakeCloudinary
) -> None:
    assert api_client.get("/api/v1/products/photos/config", headers=auth_headers(token)).json() == {
        "enabled": True
    }
    product_id = _make_product(api_client, token, name="Riz parfumé 25 kg")

    response = _put(api_client, token, product_id, _gps_jpeg())
    assert response.status_code == 200, response.text
    photo = response.json()["photo"]
    assert photo["cloud_name"] == CLOUD
    assert (photo["width"], photo["height"]) == (1600, 1067)

    [upload] = cloud.uploads
    stored: Image.Image = upload["image"]
    assert stored.format == "JPEG"
    assert max(stored.size) == 1600
    assert dict(stored.getexif()) == {}, "ni GPS ni appareil"
    public_id = upload["params"]["public_id"]
    assert public_id == photo["public_id"]
    assert public_id.startswith(f"coges-{get_settings().env}/{shop.company_id}/")
    assert "riz" not in public_id.lower(), "jamais le nom de l'article"
    assert len(public_id.rsplit("/", 1)[1]) >= 22, "128 bits aléatoires"
    assert SECRET not in response.text


def test_a_transparent_png_and_a_webp_are_accepted(
    api_client: TestClient, token: str, cloud: FakeCloudinary
) -> None:
    product_id = _make_product(api_client, token)
    assert (
        _put(api_client, token, product_id, _image("PNG", (400, 300)), "a.png").status_code == 200
    )
    assert (
        _put(api_client, token, product_id, _image("WEBP", (400, 300)), "a.webp").status_code == 200
    )
    assert all(upload["image"].format == "JPEG" for upload in cloud.uploads)


@pytest.mark.parametrize(
    ("content", "status", "code"),
    [
        (
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            422,
            "photo_unsupported_format",
        ),
        (b"%PDF-1.4 pas une image", 422, "photo_unsupported_format"),
        (b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024), 413, "photo_too_large"),
    ],
    ids=["svg", "pdf", "trop-lourde"],
)
def test_what_is_not_a_photo_is_refused(
    api_client: TestClient,
    token: str,
    cloud: FakeCloudinary,
    content: bytes,
    status: int,
    code: str,
) -> None:
    product_id = _make_product(api_client, token)
    refused = _put(api_client, token, product_id, content, "a.jpg")
    assert refused.status_code == status, refused.text
    assert refused.json()["error"]["code"] == code
    assert cloud.uploads == [], "rien ne part chez Cloudinary"


def test_a_decompression_bomb_is_refused_without_being_decoded(
    api_client: TestClient, token: str, cloud: FakeCloudinary
) -> None:
    bomb = io.BytesIO()
    Image.new("1", (7000, 7000)).save(bomb, format="PNG", optimize=True)  # 49 Mpx, quelques Ko
    product_id = _make_product(api_client, token)
    refused = _put(api_client, token, product_id, bomb.getvalue(), "bombe.png")
    assert refused.status_code == 422, refused.text
    assert cloud.uploads == []


def test_cloudinary_down_changes_nothing(
    api_client: TestClient, token: str, cloud: FakeCloudinary
) -> None:
    product_id = _make_product(api_client, token)
    cloud.down = True
    refused = _put(api_client, token, product_id, _image())
    assert refused.status_code == 503, refused.text
    assert refused.json()["error"]["code"] == "photo_storage_unavailable"
    product = api_client.get(f"/api/v1/products/{product_id}", headers=auth_headers(token))
    assert product.json()["photo"] is None


# ---------------------------------------------------------------- suppression


def test_changing_removing_and_deleting_drop_the_old_image_after_commit(
    api_client: TestClient,
    token: str,
    cloud: FakeCloudinary,
    enqueued: list[dict[str, Any]],
) -> None:
    product_id = _make_product(api_client, token, stock=None)
    first = _put(api_client, token, product_id, _image()).json()["photo"]["public_id"]
    assert enqueued == []

    second = _put(api_client, token, product_id, _image()).json()["photo"]["public_id"]
    assert [call["public_id"] for call in enqueued] == [first]
    _deliver_deletes(enqueued)
    assert first not in cloud.images and second in cloud.images

    removed = api_client.delete(f"/api/v1/products/{product_id}/photo", headers=auth_headers(token))
    assert removed.status_code == 200, removed.text
    assert removed.json()["photo"] is None
    _deliver_deletes(enqueued)
    assert second not in cloud.images

    third = _put(api_client, token, product_id, _image()).json()["photo"]["public_id"]
    deleted = api_client.delete(f"/api/v1/products/{product_id}", headers=auth_headers(token))
    assert deleted.status_code == 200, deleted.text
    assert [call["public_id"] for call in enqueued] == [third]
    _deliver_deletes(enqueued)
    assert cloud.images == {}

    again = api_client.delete(
        f"/api/v1/products/{_make_product(api_client, token)}/photo", headers=auth_headers(token)
    )
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "photo_not_found"


def test_a_refused_commit_neither_changes_the_article_nor_deletes_the_image(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    cloud: FakeCloudinary,
    enqueued: list[dict[str, Any]],
    owner_engine: Engine,
) -> None:
    product_id = _make_product(api_client, token)
    first = _put(api_client, token, product_id, _image()).json()["photo"]["public_id"]
    with failing_commit(owner_engine, shop.company_id):
        refused = _put(api_client, token, product_id, _image())
    assert refused.status_code >= 500
    assert enqueued == [], "rien n'est supprimé sans COMMIT"
    product = api_client.get(f"/api/v1/products/{product_id}", headers=auth_headers(token))
    assert product.json()["photo"]["public_id"] == first
    # L'image déposée avant le COMMIT refusé est orpheline : le balayage la retrouvera.
    assert len(cloud.images) == 2


def test_the_nightly_sweep_removes_orphans_older_than_a_day(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    cloud: FakeCloudinary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(product_tasks.products_service, "http_client", cloud.client)
    product_id = _make_product(api_client, token)
    kept = _put(api_client, token, product_id, _image()).json()["photo"]["public_id"]
    folder = f"coges-{get_settings().env}/{shop.company_id}"
    old_orphan, new_orphan = f"{folder}/orpheline-ancienne", f"{folder}/orpheline-recente"
    other = f"coges-{get_settings().env}/{uuid4()}/autre-entreprise"
    cloud.images[old_orphan] = {"created_at": datetime.now(UTC) - timedelta(days=2)}
    cloud.images[new_orphan] = {"created_at": datetime.now(UTC) - timedelta(hours=2)}
    cloud.images[other] = {"created_at": datetime.now(UTC) - timedelta(days=9)}
    cloud.images[kept]["created_at"] = datetime.now(UTC) - timedelta(days=9)

    assert product_tasks.sweep_photos(str(shop.company_id)) == 1
    assert cloud.destroyed == [old_orphan]
    assert {kept, new_orphan, other} <= set(cloud.images)


# ---------------------------------------------------------- isolation et droits


def test_another_company_never_touches_a_photo(
    api_client: TestClient,
    token: str,
    shop: DemoCompany,
    company_beta: DemoCompany,
    cloud: FakeCloudinary,
) -> None:
    product_id = _make_product(api_client, token)
    _put(api_client, token, product_id, _image())
    beta = login_token(api_client, company_beta)
    assert _put(api_client, beta, product_id, _image()).status_code == 404
    gone = api_client.delete(f"/api/v1/products/{product_id}/photo", headers=auth_headers(beta))
    assert gone.status_code == 404
    # Un message de suppression qui viserait l'image d'une autre entreprise est ignoré.
    alpha_image = next(iter(cloud.images))
    assert product_tasks.delete_photo(str(company_beta.company_id), alpha_image) is False
    assert alpha_image in cloud.images


def test_rights(
    api_client: TestClient, token: str, shop: DemoCompany, cloud: FakeCloudinary
) -> None:
    product_id = _make_product(api_client, token)
    for role in ("vendeur", "comptable"):
        other = _token_for_role(api_client, token, shop, role)
        refused = _put(api_client, other, product_id, _image())
        assert refused.status_code == 403, (role, refused.text)


def test_the_photo_reaches_the_lists(
    api_client: TestClient,
    token: str,
    session_factory: sessionmaker[Any],
    shop: DemoCompany,
    cloud: FakeCloudinary,
) -> None:
    product_id = _make_product(api_client, token)
    photo = _put(api_client, token, product_id, _image()).json()["photo"]
    stock = api_client.get(
        "/api/v1/inventory/stock", params={"product_id": product_id}, headers=auth_headers(token)
    ).json()["items"]
    assert stock[0]["photo"] == photo
    listed = api_client.get(
        "/api/v1/products", params={"page_size": 100}, headers=auth_headers(token)
    ).json()["items"]
    assert next(item for item in listed if item["id"] == product_id)["photo"] == photo
    audited = read_scalar_in_tenant(
        session_factory,
        shop.company_id,
        "SELECT diff -> 'after' ->> 'photo' FROM audit_logs "
        "WHERE entity_table = 'products' AND entity_id = :id ORDER BY occurred_at DESC LIMIT 1",
        {"id": product_id},
    )
    assert audited == "added"
    assert SECRET not in json.dumps(stock)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Aucun test de ce fichier ne sort : le vrai client échouerait bruyamment."""

    def refuse(*_: Any, **__: Any) -> httpx.Client:
        raise AssertionError("Appel réseau réel vers Cloudinary")

    monkeypatch.setattr(products_service, "http_client", refuse)
    yield
