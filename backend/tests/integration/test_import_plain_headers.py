"""En-têtes en mots simples (phase 15, lot 2, ADR 0069) — contre la vraie base.

* les modèles et les exports écrivent des mots (« Référence », « Prix de vente ») ;
* un fichier exporté se réimporte tel quel, dans une autre entreprise ;
* un fichier aux anciens en-têtes techniques (`sku`, `prix_vente`) s'importe toujours ;
* une erreur nomme la colonne par son mot, pas par sa clé.
"""

from __future__ import annotations

import csv
import io
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.modules.importexport.service import SALES_HEADERS
from tests.conftest import (
    DemoCompany,
    _create_demo_company,
    auth_headers,
    login_token,
    read_scalar_in_tenant,
    write_headers,
)


def _upload(
    client: TestClient, token: str, kind: str, content: bytes, *, dry_run: bool = False
) -> Any:
    return client.post(
        f"/api/v1/imports/{kind}",
        params={"dry_run": "true"} if dry_run else None,
        headers=write_headers(token, None),
        files={"file": ("import.csv", content, "application/octet-stream")},
    )


def _first_line(content: bytes) -> list[str]:
    return next(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))


def test_product_template_speaks_plain_words(api_client: TestClient, alpha_token: str) -> None:
    response = api_client.get(
        "/api/v1/imports/products/template", headers=auth_headers(alpha_token)
    )

    assert response.status_code == 200
    assert _first_line(response.content) == [
        "Référence",
        "Nom",
        "Prix de vente",
        "Catégorie",
        "Unité",
        "Code-barres",
        "TVA",
        "Prix d'achat",
        "Seuil d'alerte",
        "Suivi du stock",
        "Stock initial",
        "Coût unitaire",
    ]


def test_exported_customers_reimport_elsewhere(
    api_client: TestClient,
    alpha_token: str,
    session_factory: sessionmaker[Any],
) -> None:
    marker = uuid4().hex[:6]
    created = _upload(
        api_client,
        alpha_token,
        "customers",
        f"Nom;Téléphone\nAwa {marker};77 000 00 00\n".encode(),
    )
    assert created.status_code == 201, created.text

    exported = api_client.get(
        "/api/v1/exports/referentials/customers",
        params={"format": "csv"},
        headers=auth_headers(alpha_token),
    )
    assert exported.status_code == 200
    assert _first_line(exported.content) == [
        "Nom",
        "Code",
        "Téléphone",
        "E-mail",
        "Plafond de crédit",
    ]

    # Une entreprise neuve : aucun code déjà pris, le fichier passe tel quel.
    fresh = _create_demo_company(f"aller-retour-{marker}")
    reimported = _upload(api_client, login_token(api_client, fresh), "customers", exported.content)
    assert reimported.status_code == 201, reimported.text
    assert reimported.json()["errors"] == []
    assert (
        read_scalar_in_tenant(
            session_factory,
            fresh.company_id,
            "SELECT count(*) FROM customers WHERE name = :name",
            {"name": f"Awa {marker}"},
        )
        == 1
    )


def test_old_technical_headers_still_import(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    sku = f"OLD-{uuid4().hex[:6].upper()}"
    content = (
        "sku;nom;prix_vente;taux_taxe;prix_achat;seuil_reappro;suivi_stock;stock_initial\n"
        f"{sku};Ancien format;1500;0;1000;3;oui;4\n"
    ).encode()

    response = _upload(api_client, alpha_token, "products", content)

    assert response.status_code == 201, response.text
    assert (
        read_scalar_in_tenant(
            session_factory,
            company_alpha.company_id,
            "SELECT reorder_point FROM products WHERE sku = :sku",
            {"sku": sku},
        )
        == 3
    )


def test_errors_name_the_column_in_plain_words(api_client: TestClient, alpha_token: str) -> None:
    missing = _upload(api_client, alpha_token, "products", b"Nom\nArticle\n", dry_run=True)
    assert missing.status_code == 200
    assert [(e["column"], e["code"]) for e in missing.json()["errors"]] == [
        ("Prix de vente", "missing_column")
    ]

    wrong = _upload(
        api_client, alpha_token, "products", b"Nom;Prix de vente\nArticle;abc\n", dry_run=True
    )
    assert [(e["row"], e["column"]) for e in wrong.json()["errors"]] == [(2, "Prix de vente")]


def test_sales_export_headers_are_words() -> None:
    # Le contenu est couvert par test_exports ; ici, seulement la première ligne.
    assert list(SALES_HEADERS) == [
        "Vente n°",
        "Date",
        "Statut",
        "Client",
        "Sous-total",
        "Remise",
        "Taxes",
        "Total",
        "Payé",
        "Retourné",
    ]
