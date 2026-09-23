"""T5 — FK **composites** : une référence croisée est refusée par PostgreSQL.

La RLS empêche d'écrire une ligne portant le `company_id` d'un autre tenant. Elle
n'empêche pas, à elle seule, d'écrire une ligne de A qui **pointe** une donnée de B :
c'est le rôle des clés étrangères composites `(company_id, autre_id)`, la barrière 1
du Diagramme 8.

Ces tests attaquent la base directement, en `coges_app`, sans passer par l'API :
un test qui ne passerait que parce que le service a vérifié quelque chose ne vaut
rien (§ 10 du Modèle de données).

Le § 10 illustre T5 avec `sale_items` et `sale_return_refunds`, tables de la phase
05 ; la phase 03 couvre les mêmes chemins sur le référentiel.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.tenancy import tenant_transaction
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.tenancy


def _assert_foreign_key_violation(excinfo: pytest.ExceptionInfo[IntegrityError], name: str) -> None:
    """La contrainte nommée doit être celle qui a refusé l'écriture."""
    message = str(excinfo.value)
    assert "foreign key" in message.lower(), message
    assert name in message, f"contrainte attendue : {name}\n{message}"


def test_t05_product_cannot_reference_a_foreign_category(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Un produit de A rangé dans une catégorie de B viole `products_category_fk`."""
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO products (id, company_id, category_id, sku, name) "
                "VALUES (:id, :company_id, :category_id, 'SKU-VOLE', 'Produit intrus')"
            ),
            {
                "id": uuid4(),
                "company_id": tenant_a.company_id,
                # La catégorie existe, mais chez l'autre entreprise.
                "category_id": tenant_b.category_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "products_category_fk")


def test_t05_category_cannot_be_nested_under_a_foreign_parent(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Une sous-catégorie de A sous un parent de B viole `categories_self_fk`."""
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO categories (id, company_id, parent_id, name) "
                "VALUES (:id, :company_id, :parent_id, 'Sous-catégorie intruse')"
            ),
            {"id": uuid4(), "company_id": tenant_a.company_id, "parent_id": tenant_b.category_id},
        )

    _assert_foreign_key_violation(excinfo, "categories_self_fk")


def test_t05_price_cannot_reference_a_foreign_product(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Un prix de A posé sur un produit de B viole `product_prices_product_fk`.

    C'est le chemin le plus dangereux du référentiel : il permettrait de lire ou de
    modifier le tarif d'un concurrent.
    """
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO product_prices "
                "(company_id, product_id, unit_price, valid_from, valid_to, created_by) "
                "VALUES (:company_id, :product_id, 100.00, "
                "now() - interval '2 days', now() - interval '1 day', :created_by)"
            ),
            {
                "company_id": tenant_a.company_id,
                "product_id": tenant_b.product_id,
                "created_by": tenant_a.user_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "product_prices_product_fk")


def test_t05_price_cannot_credit_a_foreign_user(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """L'auteur d'un changement de prix appartient forcément à la même entreprise."""
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO product_prices "
                "(company_id, product_id, unit_price, valid_from, valid_to, created_by) "
                "VALUES (:company_id, :product_id, 100.00, "
                "now() - interval '2 days', now() - interval '1 day', :created_by)"
            ),
            {
                "company_id": tenant_a.company_id,
                "product_id": tenant_a.product_id,
                "created_by": tenant_b.user_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "product_prices_creator_fk")


def test_t05_movement_cannot_reference_a_foreign_product(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Un mouvement de A sur un produit de B est refusé — par le trigger, pas la FK.

    C'est le chemin qui permettrait de vider le stock d'un concurrent. Deux
    barrières le ferment, et l'ordre compte : `t20_inv_apply` est un trigger
    `BEFORE INSERT`, il s'exécute **avant** la vérification de `inv_product_fk` et
    cherche le produit dans le tenant courant. Le refus vient donc de lui.
    `inv_product_fk` reste la garantie structurelle, celle qui tiendrait si le
    trigger disparaissait.
    """
    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO inventory_movements "
                "(company_id, product_id, type, qty_delta, unit_cost) "
                "VALUES (:company_id, :product_id, 'purchase_in', 1, 10.0000)"
            ),
            {"company_id": tenant_a.company_id, "product_id": tenant_b.product_id},
        )

    assert "inconnu dans ce tenant" in str(excinfo.value)


def test_t05_movement_cannot_reference_a_product_of_no_tenant(
    session_factory: sessionmaker[Any], tenant_a: Tenant
) -> None:
    """Même refus pour un produit qui n'existe nulle part : rien n'est deviné."""
    with (
        pytest.raises(DBAPIError),
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO inventory_movements "
                "(company_id, product_id, type, qty_delta, unit_cost) "
                "VALUES (:company_id, :product_id, 'purchase_in', 1, 10.0000)"
            ),
            {"company_id": tenant_a.company_id, "product_id": uuid4()},
        )


def test_t05_movement_cannot_reference_a_foreign_supplier(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Une réception de A attribuée à un fournisseur de B viole `inv_supplier_fk`."""
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO inventory_movements "
                "(company_id, product_id, type, qty_delta, unit_cost, supplier_id) "
                "VALUES (:company_id, :product_id, 'purchase_in', 1, 10.0000, :supplier_id)"
            ),
            {
                "company_id": tenant_a.company_id,
                "product_id": tenant_a.product_id,
                "supplier_id": tenant_b.supplier_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "inv_supplier_fk")
