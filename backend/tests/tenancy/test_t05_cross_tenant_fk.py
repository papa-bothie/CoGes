"""T5 — FK **composites** : une référence croisée est refusée par PostgreSQL.

La RLS empêche d'écrire une ligne portant le `company_id` d'un autre tenant. Elle
n'empêche pas, à elle seule, d'écrire une ligne de A qui **pointe** une donnée de B :
c'est le rôle des clés étrangères composites `(company_id, autre_id)`, la barrière 1
du Diagramme 8.

Ces tests attaquent la base directement, en `coges_app`, sans passer par l'API :
un test qui ne passerait que parce que le service a vérifié quelque chose ne vaut
rien (§ 10 du Modèle de données).

Le § 10 illustre T5 avec `sale_items`, table de la phase 05 : c'est le cas nommé par
le modèle, et il est couvert plus bas. Les mêmes chemins sont fermés sur le
référentiel (phase 03) et sur le stock (phase 04).
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


def _draft_sale(session_factory: sessionmaker[Any], tenant: Tenant) -> Any:
    """Un brouillon neuf chez ce tenant.

    La vente semée par le harnais est confirmée : `sale_items_no_change` la
    protégerait et masquerait la clé étrangère qu'on cherche à mesurer ici.
    """
    sale_id = uuid4()
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO sales (id, company_id, sale_no, created_by) "
                "VALUES (:id, :company_id, :sale_no, :created_by)"
            ),
            {
                "id": sale_id,
                "company_id": tenant.company_id,
                "sale_no": f"V-{sale_id.hex[:6].upper()}",
                "created_by": tenant.user_id,
            },
        )
    return sale_id


def test_t05_sale_item_cannot_reference_a_foreign_product(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Le cas nommé par le § 10 : une ligne de A sur un produit de B.

    Ce chemin-ci est le plus coûteux de tous s'il s'ouvre : il ferait sortir du
    stock chez le concurrent, au prix du concurrent, sur une vente qu'il ne verra
    jamais. `sale_items_product_fk` le referme.
    """
    sale_id = _draft_sale(session_factory, tenant_a)

    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO sale_items (company_id, sale_id, product_id, qty, unit_price) "
                "VALUES (:company_id, :sale_id, :product_id, 1, 1000.00)"
            ),
            {
                "company_id": tenant_a.company_id,
                "sale_id": sale_id,
                # Le produit existe, mais chez l'autre entreprise.
                "product_id": tenant_b.product_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "sale_items_product_fk")


def test_t05_sale_item_cannot_be_attached_to_a_foreign_sale(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Une ligne de A greffée sur une vente de B viole `sale_items_sale_fk`.

    `sale_items_frozen` ne peut rien ici : il cherche la vente **dans le tenant
    courant**, ne la trouve pas, et laisse passer. C'est la clé étrangère
    composite qui refuse — la barrière 1, celle qui ne dépend d'aucun trigger.
    """
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO sale_items (company_id, sale_id, product_id, qty, unit_price) "
                "VALUES (:company_id, :sale_id, :product_id, 1, 1000.00)"
            ),
            {
                "company_id": tenant_a.company_id,
                "sale_id": tenant_b.sale_id,
                "product_id": tenant_a.product_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "sale_items_sale_fk")


def test_t05_a_sale_cannot_be_billed_to_a_foreign_customer(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Une vente de A au nom d'un client de B viole `sales_customer_fk`."""
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO sales (company_id, customer_id, sale_no, created_by) "
                "VALUES (:company_id, :customer_id, 'V-INTRUS', :created_by)"
            ),
            {
                "company_id": tenant_a.company_id,
                "customer_id": tenant_b.customer_id,
                "created_by": tenant_a.user_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "sales_customer_fk")


def test_t05_a_payment_cannot_be_posted_on_a_foreign_sale(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Un encaissement de A imputé à une vente de B viole `payments_sale_fk`.

    C'est le pendant financier du cas précédent : sans cette barrière, on
    solderait la vente d'un concurrent avec son propre argent.
    """
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO payments "
                "(company_id, direction, method, amount, sale_id, created_by) "
                "VALUES (:company_id, 'inflow', 'cash', 100.00, :sale_id, :created_by)"
            ),
            {
                "company_id": tenant_a.company_id,
                "sale_id": tenant_b.sale_id,
                "created_by": tenant_a.user_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "payments_sale_fk")


def test_t05_a_debt_cannot_be_charged_to_a_foreign_customer(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Une dette de A au nom d'un client de B viole `debts_customer_fk`."""
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO debts (company_id, party_type, customer_id, principal) "
                "VALUES (:company_id, 'customer', :customer_id, 500.00)"
            ),
            {"company_id": tenant_a.company_id, "customer_id": tenant_b.customer_id},
        )

    _assert_foreign_key_violation(excinfo, "debts_customer_fk")


def test_t05_a_return_cannot_be_attached_to_a_foreign_sale(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Un retour de A sur une vente de B viole `sale_returns_sale_fk`."""
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO sale_returns (company_id, sale_id, return_no, created_by) "
                "VALUES (:company_id, :sale_id, 'R-INTRUS', :created_by)"
            ),
            {
                "company_id": tenant_a.company_id,
                "sale_id": tenant_b.sale_id,
                "created_by": tenant_a.user_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "sale_returns_sale_fk")


def test_t05_a_return_item_cannot_reference_a_foreign_sale_item(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Une ligne de retour de A pointant une ligne de vente de B est refusée.

    `return_item_check` ne peut rien ici, et pour la même raison que
    `sale_items_frozen` au cas précédent : il cherche la ligne de vente **dans le
    tenant courant**, ne la trouve pas, et lève « Ligne de vente introuvable » —
    un refus, mais qui ne dit pas ce qui s'est réellement passé. Le test mesure la
    clé étrangère, la barrière qui tiendrait si le trigger disparaissait, et
    accepte donc l'un ou l'autre des deux refus.
    """
    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO sale_return_items "
                "(company_id, return_id, sale_item_id, qty, refund_amount, unit_cost) "
                "VALUES (:company_id, :return_id, :sale_item_id, 1, 100.00, 10.0000)"
            ),
            {
                "company_id": tenant_a.company_id,
                "return_id": tenant_a.sale_return_id,
                "sale_item_id": tenant_b.sale_item_id,
            },
        )

    message = str(excinfo.value)
    assert "sale_return_items_item_fk" in message or "Ligne de vente introuvable" in message, (
        message
    )


def test_t05_a_refund_cannot_be_lettered_on_a_foreign_payment(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Le second cas nommé par le § 10 : `sale_return_refunds` → paiement de B.

    Sans cette barrière, une entreprise imputerait le remboursement de son propre
    retour sur la trésorerie d'une autre : l'argent sortirait chez le voisin.

    `refund_check` verrouille et lit le paiement **dans le tenant courant** ; ne le
    trouvant pas, il laisse `v_dir` à NULL, et `NULL <> 'outflow'` ne vaut pas
    `true` — le trigger ne refuse donc rien. C'est `srr_payment_fk` qui refuse.
    """
    with (
        pytest.raises(IntegrityError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO sale_return_refunds "
                "(company_id, sale_return_id, payment_id, amount) "
                "VALUES (:company_id, :sale_return_id, :payment_id, 100.00)"
            ),
            {
                "company_id": tenant_a.company_id,
                "sale_return_id": tenant_a.sale_return_id,
                "payment_id": tenant_b.refund_payment_id,
            },
        )

    _assert_foreign_key_violation(excinfo, "srr_payment_fk")


def test_t05_a_refund_cannot_be_lettered_on_a_foreign_return(
    session_factory: sessionmaker[Any], tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Le sens inverse : un décaissement de A lettré sur un retour de B.

    `refund_check` cherche le retour chez A, ne le trouve pas et lève « Retour
    introuvable » avant que `srr_return_fk` n'ait son mot à dire. Les deux refus
    sont acceptés : ce qui compte est qu'aucune écriture ne passe.
    """
    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text(
                "INSERT INTO sale_return_refunds "
                "(company_id, sale_return_id, payment_id, amount) "
                "VALUES (:company_id, :sale_return_id, :payment_id, 100.00)"
            ),
            {
                "company_id": tenant_a.company_id,
                "sale_return_id": tenant_b.sale_return_id,
                "payment_id": tenant_a.refund_payment_id,
            },
        )

    message = str(excinfo.value)
    assert "srr_return_fk" in message or "Retour introuvable" in message, message
