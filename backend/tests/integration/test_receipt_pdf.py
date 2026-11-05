"""Ticket, facture et bon de retour en PDF (prompt 35, bloc T, ADR 0113)."""

from __future__ import annotations

import io
import re
import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader
from sqlalchemy.orm import sessionmaker

from tests.conftest import (
    TEST_PASSWORD,
    DemoCompany,
    _create_demo_company,
    auth_headers,
    create_user_with_role,
    login_token,
    write_headers,
)

pytestmark = pytest.mark.integration

MM = 72 / 25.4


def _post(client: TestClient, token: str, path: str, body: Any) -> dict[str, Any]:
    response = client.post(path, headers=write_headers(token), json=body)
    assert response.status_code in (200, 201), f"{path} : {response.text}"
    return dict(response.json())


@pytest.fixture
def shop(app_bound_to_test_database: None) -> DemoCompany:
    return _create_demo_company(f"pdf-{uuid4().hex[:8]}")


@pytest.fixture
def manager(api_client: TestClient, shop: DemoCompany) -> str:
    token = login_token(api_client, shop)
    response = api_client.patch(
        "/api/v1/companies/me",
        headers=auth_headers(token),
        json={
            "name": "Boutique Keur Fatou",
            "address": "Rue 10, Médina, Dakar",
            "ninea": "0012345",
        },
    )
    assert response.status_code == 200, response.text
    return token


def _product(client: TestClient, token: str, **extra: Any) -> str:
    body = {"name": f"Riz {uuid4().hex[:6]}", "unit_price": "1500", **extra}
    product_id = _post(client, token, "/api/v1/products", body)["id"]
    _post(
        client,
        token,
        "/api/v1/inventory/movements",
        {"product_id": product_id, "type": "initial", "qty_delta": "500", "unit_cost": "900"},
    )
    return product_id


def _sale(client: TestClient, token: str, lines: int = 1, **product: Any) -> tuple[str, str]:
    """Vente confirmée, payée comptant ; rend (id, total)."""
    sale_id = _post(client, token, "/api/v1/sales", {})["id"]
    for _ in range(lines):
        _post(
            client,
            token,
            f"/api/v1/sales/{sale_id}/items",
            {"product_id": _product(client, token, **product), "qty": "2"},
        )
    total = client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token)).json()["total"]
    _post(
        client, token, f"/api/v1/sales/{sale_id}/confirm", {"paid_amount": total, "method": "cash"}
    )
    return sale_id, total


def _pdf(client: TestClient, token: str, path: str, **params: str) -> Any:
    return client.get(path, headers=auth_headers(token), params=params)


def _read(content: bytes) -> tuple[PdfReader, str]:
    assert content.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    return reader, text.replace(" ", " ").replace(" ", " ")


def _images(reader: PdfReader) -> int:
    return sum(len(page.images) for page in reader.pages)


@pytest.fixture
def with_logo(api_client: TestClient, manager: str) -> Iterator[None]:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 60), (10, 120, 60)).save(buffer, format="PNG")
    put = api_client.put(
        "/api/v1/companies/me/logo",
        headers=auth_headers(manager),
        files={"file": ("logo.png", buffer.getvalue(), "image/png")},
    )
    assert put.status_code == 200, put.text
    yield


def test_the_invoice_pdf_holds_the_shop_the_lines_and_the_total(
    api_client: TestClient, manager: str
) -> None:
    sale_id, _ = _sale(api_client, manager, description="Sac cousu, 25 kg")
    response = _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="a4")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="Facture-0001-Boutique-Keur-Fatou.pdf"' in disposition
    assert "filename*=UTF-8''Facture-0001-Boutique-Keur-Fatou.pdf" in disposition

    reader, text = _read(response.content)
    assert "Boutique Keur Fatou" in text
    assert "Rue 10, Médina, Dakar" in text
    assert "NINEA 0012345" in text
    assert "FACTURE" in text
    assert "Sac cousu, 25 kg" in text
    assert "3 000 F" in text, text
    assert "Page 1/1" in text
    assert _images(reader) == 0, "sans logo, aucune image"


def test_the_ticket_is_one_80_mm_band_with_the_logo(
    api_client: TestClient, manager: str, with_logo: None
) -> None:
    sale_id, _ = _sale(api_client, manager, lines=3, description="Jamais sur le ticket")
    response = _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="ticket")
    assert response.status_code == 200, response.text
    assert (
        'filename="Ticket-0001-Boutique-Keur-Fatou.pdf"' in response.headers["content-disposition"]
    )
    reader, text = _read(response.content)
    assert len(reader.pages) == 1
    width = float(reader.pages[0].mediabox.width)
    assert abs(width - 80 * MM) < 0.5, width
    assert "Boutique Keur Fatou".upper() in text.upper()
    assert "9 000 F" in text, text
    assert "Jamais sur le ticket" not in text
    assert _images(reader) == 1, "le logo, en tête"


def test_the_invoice_carries_the_logo(
    api_client: TestClient, manager: str, with_logo: None
) -> None:
    sale_id, _ = _sale(api_client, manager)
    reader, _ = _read(
        _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="a4").content
    )
    assert _images(reader) == 1


def test_a_long_invoice_is_paginated(api_client: TestClient, manager: str) -> None:
    sale_id, _ = _sale(api_client, manager, lines=60)
    reader, text = _read(
        _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="a4").content
    )
    pages = len(reader.pages)
    assert pages >= 2
    assert f"Page 1/{pages}" in text and f"Page {pages}/{pages}" in text
    assert "DÉSIGNATION" in reader.pages[1].extract_text(), "l'en-tête du tableau se répète"


def test_a_changed_price_is_never_printed(api_client: TestClient, manager: str) -> None:
    sale_id = _post(api_client, manager, "/api/v1/sales", {})["id"]
    item = _post(
        api_client,
        manager,
        f"/api/v1/sales/{sale_id}/items",
        {"product_id": _product(api_client, manager, unit_price="1777"), "qty": "1"},
    )
    changed = api_client.patch(
        f"/api/v1/sales/{sale_id}/items/{item['id']}",
        headers=auth_headers(manager),
        json={"unit_price": "1200.00", "price_reason": "Client fidèle"},
    )
    assert changed.status_code == 200, changed.text
    _post(
        api_client,
        manager,
        f"/api/v1/sales/{sale_id}/confirm",
        {"paid_amount": "1200", "method": "cash"},
    )
    for fmt in ("a4", "ticket"):
        _, text = _read(
            _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format=fmt).content
        )
        assert "1 200" in text
        assert "1 777" not in text and "fidèle" not in text


def test_a_draft_has_no_pdf(api_client: TestClient, manager: str) -> None:
    sale_id = _post(api_client, manager, "/api/v1/sales", {})["id"]
    refused = _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "sale_not_confirmed"


def test_another_company_gets_a_404(api_client: TestClient, manager: str, beta_token: str) -> None:
    sale_id, _ = _sale(api_client, manager)
    other = _pdf(api_client, beta_token, f"/api/v1/sales/{sale_id}/receipt/pdf")
    assert other.status_code == 404


def test_a_missing_right_is_refused(
    api_client: TestClient, manager: str, shop: DemoCompany
) -> None:
    """Un rôle sans `sales:read` ne télécharge pas le reçu."""
    sale_id, _ = _sale(api_client, manager)
    role = api_client.post(
        "/api/v1/roles",
        headers=auth_headers(manager),
        json={"name": f"Sans ventes {uuid4().hex[:6]}", "permissions": ["company:read"]},
    )
    assert role.status_code == 201, role.text
    email = f"nv-{uuid4().hex[:8]}@test.sn"
    created = api_client.post(
        "/api/v1/users",
        headers=auth_headers(manager),
        json={
            "email": email,
            "full_name": "Sans droit",
            "password": TEST_PASSWORD,
            "role_ids": [role.json()["id"]],
        },
    )
    assert created.status_code == 201, created.text
    login = api_client.post(
        "/api/v1/auth/login",
        json={"company_slug": shop.slug, "email": email, "password": TEST_PASSWORD},
    )
    token = login.json()["access_token"]
    assert _pdf(api_client, token, f"/api/v1/sales/{sale_id}/receipt/pdf").status_code == 403


def test_a_seller_downloads_the_receipt(
    api_client: TestClient, manager: str, shop: DemoCompany
) -> None:
    sale_id, _ = _sale(api_client, manager)
    seller = create_user_with_role(
        api_client, manager, shop, role="vendeur", email=f"v-{uuid4().hex[:8]}@test.sn"
    )
    assert _pdf(api_client, seller, f"/api/v1/sales/{sale_id}/receipt/pdf").status_code == 200


def test_the_ticket_is_rendered_in_under_a_second(api_client: TestClient, manager: str) -> None:
    sale_id, _ = _sale(api_client, manager, lines=5)
    path = f"/api/v1/sales/{sale_id}/receipt/pdf"
    _pdf(api_client, manager, path, format="ticket")  # polices chargées une fois
    started = time.perf_counter()
    response = _pdf(api_client, manager, path, format="ticket")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    print(f"\nticket PDF : {elapsed * 1000:.0f} ms")
    assert elapsed < 1.0, elapsed


def _return(client: TestClient, token: str, sale_id: str) -> dict[str, Any]:
    item_id = client.get(f"/api/v1/sales/{sale_id}", headers=auth_headers(token)).json()["items"][
        0
    ]["id"]
    return _post(
        client,
        token,
        f"/api/v1/sales/{sale_id}/returns",
        {"lines": [{"sale_item_id": item_id, "qty": "1"}], "reason": "Abîmé"},
    )


def test_the_return_slip_pdf(api_client: TestClient, manager: str, with_logo: None) -> None:
    sale_id, _ = _sale(api_client, manager)
    created = _return(api_client, manager, sale_id)
    response = _pdf(api_client, manager, f"/api/v1/sale-returns/{created['id']}/slip/pdf")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert (
        'filename="Retour-0001-Boutique-Keur-Fatou.pdf"' in response.headers["content-disposition"]
    )
    reader, text = _read(response.content)
    assert "BON DE RETOUR" in text
    assert "Rue 10, Médina, Dakar" in text
    assert "Abîmé" in text
    assert "1 500 F" in text, text
    assert _images(reader) == 1


def test_the_return_slip_of_another_company_is_a_404(
    api_client: TestClient, manager: str, beta_token: str
) -> None:
    sale_id, _ = _sale(api_client, manager)
    created = _return(api_client, manager, sale_id)
    other = _pdf(api_client, beta_token, f"/api/v1/sale-returns/{created['id']}/slip/pdf")
    assert other.status_code == 404


@pytest.fixture
def support_client(platform_bound_to_test_database: None) -> Iterator[TestClient]:
    from app.main import app
    from tests.conftest import TEST_BASE_URL

    with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as test_client:
        yield test_client


def test_the_support_access_downloads(
    support_client: TestClient,
    shop: DemoCompany,
    platform_session_factory: sessionmaker[Any],
) -> None:
    from tests.integration.platform_harness import create_platform_account
    from tests.integration.support_harness import open_support_session

    token = login_token(support_client, shop)
    sale_id, _ = _sale(support_client, token)
    account = create_platform_account("support")
    _, support = open_support_session(platform_session_factory, shop.company_id, account.id)
    response = support_client.get(
        f"/api/v1/sales/{sale_id}/receipt/pdf", headers=auth_headers(support)
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------- corrections avant fusion (ADR 0113)


def _credit_sale(client: TestClient, token: str) -> str:
    """Vente confirmée à crédit (rien payé) : le reste dû serait le total."""
    sale_id = _post(client, token, "/api/v1/sales", {})["id"]
    _post(
        client,
        token,
        f"/api/v1/sales/{sale_id}/items",
        {"product_id": _product(client, token), "qty": "2"},
    )
    customer = _post(client, token, "/api/v1/customers", {"name": "Awa Ndiaye"})["id"]
    patched = client.patch(
        f"/api/v1/sales/{sale_id}", headers=auth_headers(token), json={"customer_id": customer}
    )
    assert patched.status_code == 200, patched.text
    _post(client, token, f"/api/v1/sales/{sale_id}/confirm", {"paid_amount": "0", "method": "cash"})
    return sale_id


def test_a_cancelled_sale_neither_asks_for_the_rest_nor_states_the_sum(
    api_client: TestClient, manager: str
) -> None:
    """Une vente annulée ne réclame rien : ni « Reste à payer », ni « Arrêtée la présente
    facture à la somme de… », sur la facture comme sur le ticket."""
    sale_id = _credit_sale(api_client, manager)
    _post(api_client, manager, f"/api/v1/sales/{sale_id}/cancel", {"reason": "Erreur de saisie"})
    for fmt in ("a4", "ticket"):
        response = _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format=fmt)
        assert response.status_code == 200, response.text
        _, text = _read(response.content)
        assert "VENTE ANNULÉE" in text, fmt
        assert "reste à payer" not in text.casefold(), (fmt, text)
        assert "Arrêtée la présente facture" not in text, (fmt, text)


def test_a_shop_name_with_markup_and_no_logo_is_printed_as_typed(
    api_client: TestClient, manager: str
) -> None:
    """Les initiales qui remplacent le logo sont échappées : « <Keur> » n'est pas une
    balise pour ReportLab (500 avant la correction)."""
    patched = api_client.patch(
        "/api/v1/companies/me",
        headers=auth_headers(manager),
        json={"name": "Diop & Fils <Keur>"},
    )
    assert patched.status_code == 200, patched.text
    sale_id, _ = _sale(api_client, manager)
    for fmt in ("a4", "ticket"):
        response = _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format=fmt)
        assert response.status_code == 200, (fmt, response.text)
        reader, text = _read(response.content)
        assert ("Diop & Fils <Keur>" if fmt == "a4" else "DIOP & FILS <KEUR>") in text
        assert _images(reader) == 0
    _, invoice = _read(
        _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="a4").content
    )
    assert "FK" in invoice, "initiales : premières lettres des deux derniers mots"
    disposition = _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf").headers[
        "content-disposition"
    ]
    assert 'filename="Facture-0001-Diop-Fils-Keur.pdf"' in disposition


@pytest.mark.parametrize("name", ["", "   ", None])
def test_a_blank_seller_name_prints_no_seller(
    api_client: TestClient, manager: str, name: str | None
) -> None:
    """Un nom de vendeur vide ou fait d'espaces : ni 500, ni « Servi par : » orphelin.

    La base refuse un tel nom (`users_full_name_check`) ; le rendu ne s'y fie pas pour
    autant, il reçoit un reçu et ne doit jamais tomber dessus.
    """
    from app.modules.sales.documents import render_invoice, render_ticket
    from app.modules.sales.schemas import ReceiptRead

    sale_id, _ = _sale(api_client, manager)
    body = api_client.get(f"/api/v1/sales/{sale_id}/receipt", headers=auth_headers(manager))
    receipt = ReceiptRead.model_validate(body.json()).model_copy(update={"seller_name": name})
    for render in (render_invoice, render_ticket):
        _, content = _read(render(receipt, logo_png=None, tz="Africa/Dakar"))
        assert "Servi par" not in content, (render.__name__, content)


# ------------------------------------------- facture au vert CoGes (ADR 0112 amendé)


def _fills(reader: PdfReader) -> list[tuple[float, float, float]]:
    """Couleurs de remplissage (`r g b rg`) des pages : le vert des bandeaux s'y lit."""
    found: list[tuple[float, float, float]] = []
    for page in reader.pages:
        data = page.get_contents().get_data().decode("latin-1")  # type: ignore[union-attr]
        for r, g, b in re.findall(r"([\d.]+) ([\d.]+) ([\d.]+) rg", data):
            found.append((float(r), float(g), float(b)))
    return found


def _has_fill(reader: PdfReader, token: str) -> bool:
    from app.core.pdf import PALETTE

    value = PALETTE[token]
    want = tuple(int(value[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return any(
        all(abs(a - b) < 0.003 for a, b in zip(fill, want, strict=True)) for fill in _fills(reader)
    )


def test_the_green_invoice_follows_the_model(api_client: TestClient, manager: str) -> None:
    api_client.patch(
        "/api/v1/companies/me", headers=auth_headers(manager), json={"phone": "77 123 45 67"}
    )
    sale_id, _ = _sale(api_client, manager, lines=2, description="Sac cousu, 25 kg")
    reader, text = _read(
        _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="a4").content
    )
    # En-tête et blocs : coordonnées, « De », titre, numéro, date, « Facturé à ».
    for expected in (
        "77 123 45 67",
        "Rue 10, Médina, Dakar",
        "DE",
        "FACTURE",
        "Facture n°",
        "F-1",
        "Date",
        "FACTURÉ À",
        "Client de passage",
        "NINEA 0012345",
    ):
        assert expected in text, (expected, text)
    # Tableau à bandeau : colonnes du modèle, numéro de ligne, description en petit.
    flat = " ".join(text.split())
    assert "N° DÉSIGNATION PRIX UNITAIRE QTÉ TOTAL" in flat, flat
    assert "01" in text and "Sac cousu, 25 kg" in text
    # Totaux puis bas de page.
    for expected in ("Total", "Déjà payé", "Merci pour votre confiance", "MOYENS DE PAIEMENT"):
        assert expected in text, (expected, text)
    assert "Espèces : 6 000 F" in text, text
    assert "Signature et cachet" in text
    # Les verts de la marque et la teinte claire, jamais une couleur hors palette.
    assert _has_fill(reader, "coges-vert-marque"), "bandeaux et titre"
    assert _has_fill(reader, "coges-vert-action"), "pastilles"
    assert _has_fill(reader, "coges-ventes-teinte"), "cadre « Facturé à »"
    assert _has_fill(reader, "coges-recu-entete"), "lignes alternées"


def test_the_invoice_names_its_customer(api_client: TestClient, manager: str) -> None:
    sale_id = _credit_sale(api_client, manager)
    _, text = _read(
        _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="a4").content
    )
    assert "Awa Ndiaye" in text and "Client de passage" not in text
    assert "Reste à payer" in text


def test_40_lines_make_two_pages_with_the_band_repeated(
    api_client: TestClient, manager: str
) -> None:
    sale_id, _ = _sale(api_client, manager, lines=40)
    reader, text = _read(
        _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="a4").content
    )
    assert len(reader.pages) == 2, len(reader.pages)
    assert "Page 1/2" in text and "Page 2/2" in text
    for page in reader.pages:
        assert "DÉSIGNATION" in page.extract_text(), "bandeau répété"
    assert "40" in text


def test_a_cancelled_invoice_shows_neither_paid_nor_due(
    api_client: TestClient, manager: str
) -> None:
    sale_id = _credit_sale(api_client, manager)
    _post(api_client, manager, f"/api/v1/sales/{sale_id}/cancel", {"reason": "Erreur de saisie"})
    _, text = _read(
        _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="a4").content
    )
    assert "VENTE ANNULÉE" in text
    assert "Déjà payé" not in text and "Reste à payer" not in text


def test_the_ticket_stays_black_and_white(
    api_client: TestClient, manager: str, with_logo: None
) -> None:
    sale_id, _ = _sale(api_client, manager)
    reader, _ = _read(
        _pdf(api_client, manager, f"/api/v1/sales/{sale_id}/receipt/pdf", format="ticket").content
    )
    for r, g, b in _fills(reader):
        assert r == g == b, ("couleur sur le ticket", r, g, b)
