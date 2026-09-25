"""Harnais de fuite inter-tenant, réutilisable par toutes les phases.

Deux entreprises **A** et **B** sont créées avec leurs propres données, puis chaque
phase ajoute ses tables à `TENANT_TABLES` et ses fabriques ici. Les tests croisés
(A → A autorisé, A → B vide, B → A vide, écriture croisée refusée) s'appliquent
alors automatiquement aux nouvelles tables.

Amorçage d'un tenant : l'UUID de l'entreprise est **généré côté serveur avant**
l'INSERT, puis posé comme contexte. La politique `companies_self` accepte alors
l'écriture (`WITH CHECK id = current_setting(...)`), sans aucun contournement de la
RLS ni fonction `SECURITY DEFINER`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.security import hash_password
from app.core.tenancy import TenantContext, tenant_transaction

# Tables tenant-scoped couvertes par les tests croisés.
# Chaque phase ajoute les siennes ; T37 vérifie en plus, génériquement, qu'aucune
# table portant `company_id` n'échappe à la RLS.
TENANT_TABLES: tuple[str, ...] = (
    "users",
    "roles",
    "user_roles",
    "role_permissions",
    "auth_sessions",
    "business_events",
    # Phase 03 — référentiels.
    "customers",
    "suppliers",
    "categories",
    "products",
    "product_prices",
    # Phase 04 — stock.
    "product_stock",
    "inventory_movements",
    # Phase 05 — ventes et finance.
    "sales",
    "sale_items",
    "payments",
    "debts",
    "document_counters",
    # Phase 06 — retours et remboursements.
    "sale_returns",
    "sale_return_items",
    "sale_return_refunds",
    "payment_allocations",
    # Phase 07 — charges, et les clés d'idempotence des écritures financières.
    "expense_categories",
    "expenses",
    "idempotency_keys",
    # Phase 08 — restitution et chemin asynchrone.
    "daily_sales_facts",
    "notifications",
    "processed_events",
)

# Valeur factice : aucun mot de passe réel ne figure dans les tests.
PLACEHOLDER_PASSWORD_HASH = "argon2-placeholder-not-a-real-hash"  # noqa: S105


@dataclass(frozen=True, slots=True)
class Tenant:
    """Une entreprise de test et ses identifiants."""

    slug: str
    company_id: UUID
    user_id: UUID
    role_id: UUID
    permission_id: UUID
    email: str
    # Phase 03 — une ligne de référentiel par table, pour que les tests croisés
    # portent sur des données réelles et non sur des tables vides.
    customer_id: UUID
    supplier_id: UUID
    category_id: UUID
    product_id: UUID
    # Phase 04 — un mouvement, qui crée du même coup la ligne de `product_stock`.
    movement_id: UUID
    # Phase 05 — une vente confirmée, sa ligne, son encaissement et sa dette.
    sale_id: UUID
    sale_item_id: UUID
    payment_id: UUID
    debt_id: UUID
    # Phase 06 — un retour, sa ligne, son remboursement et le décaissement qui le
    # porte. Le paiement de la phase 05 est un `inflow` : `payments_return_outflow`
    # en exige un second, en sens inverse, pour pouvoir lettrer un remboursement.
    sale_return_id: UUID
    sale_return_item_id: UUID
    refund_payment_id: UUID
    refund_id: UUID
    allocation_id: UUID
    # Phase 07 — une famille de charges, une dépense, et une clé d'idempotence.
    expense_category_id: UUID
    expense_id: UUID
    idempotency_key: str
    # Phase 08 — un fait analytique, une alerte, une marque de consommation. Semés
    # comme le reste : le harnais attaque la base, et chaque tenant doit posséder
    # une ligne dans chaque table pour que T1 et T2 aient quelque chose à ne pas voir.
    fact_day: date
    notification_id: UUID

    @property
    def ctx(self) -> TenantContext:
        """Contexte applicatif de cette entreprise."""
        return TenantContext(user_id=self.user_id, company_id=self.company_id)


def catalogue_permission_id(owner_engine: Engine, code: str = "dashboard:read") -> UUID:
    """Identifiant d'une permission du catalogue global, livré par la migration 0002.

    Lu avec le rôle **propriétaire** : `coges_app` n'a que SELECT sur ce catalogue
    (ADR 0004), et le vocabulaire des droits n'est jamais écrit par un tenant.
    """
    with owner_engine.begin() as connection:
        return UUID(
            str(
                connection.execute(
                    text("SELECT id FROM permissions WHERE code = :code"), {"code": code}
                ).scalar_one()
            )
        )


def create_tenant(
    session_factory: sessionmaker[Any],
    owner_engine: Engine,
    slug: str,
    *,
    password: str | None = None,
) -> Tenant:
    """Crée une entreprise complète : société, utilisateur, rôle, rattachement."""
    company_id = uuid4()
    user_id = uuid4()
    role_id = uuid4()
    # `.test` est un domaine réservé que le validateur d'e-mail refuse : les comptes
    # de test utilisent donc un sous-domaine d'example.com.
    email = f"gerant@{slug}.example.com"
    password_hash = hash_password(password) if password else PLACEHOLDER_PASSWORD_HASH

    # Le contexte est posé sur l'UUID pré-généré : l'INSERT satisfait `WITH CHECK`.
    bootstrap = TenantContext(user_id=user_id, company_id=company_id)

    with tenant_transaction(bootstrap, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO companies (id, name, slug, currency, timezone) "
                "VALUES (:id, :name, :slug, 'XOF', 'Africa/Dakar')"
            ),
            {"id": company_id, "name": f"Entreprise {slug.upper()}", "slug": slug},
        )
        session.execute(
            text(
                "INSERT INTO users (id, company_id, email, password_hash, full_name) "
                "VALUES (:id, :company_id, :email, :password_hash, :full_name)"
            ),
            {
                "id": user_id,
                "company_id": company_id,
                "email": email,
                "password_hash": password_hash,
                "full_name": f"Gérant {slug.upper()}",
            },
        )
        session.execute(
            text("INSERT INTO roles (id, company_id, name) VALUES (:id, :company_id, :name)"),
            {"id": role_id, "company_id": company_id, "name": "gerant"},
        )
        session.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id, company_id) "
                "VALUES (:user_id, :role_id, :company_id)"
            ),
            {"user_id": user_id, "role_id": role_id, "company_id": company_id},
        )

    permission_id = catalogue_permission_id(owner_engine)
    tenant = Tenant(
        slug=slug,
        company_id=company_id,
        user_id=user_id,
        role_id=role_id,
        permission_id=permission_id,
        email=email,
        customer_id=uuid4(),
        supplier_id=uuid4(),
        category_id=uuid4(),
        product_id=uuid4(),
        movement_id=uuid4(),
        sale_id=uuid4(),
        sale_item_id=uuid4(),
        payment_id=uuid4(),
        debt_id=uuid4(),
        sale_return_id=uuid4(),
        sale_return_item_id=uuid4(),
        refund_payment_id=uuid4(),
        refund_id=uuid4(),
        allocation_id=uuid4(),
        expense_category_id=uuid4(),
        expense_id=uuid4(),
        idempotency_key=uuid4().hex,
        fact_day=date(2026, 9, 1),
        notification_id=uuid4(),
    )

    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id, company_id) "
                "VALUES (:role_id, :permission_id, :company_id)"
            ),
            {"role_id": role_id, "permission_id": permission_id, "company_id": company_id},
        )

    # Une ligne dans chaque table tenant-scoped de la phase 02, pour que les tests
    # croisés portent sur des données réelles et non sur des tables vides.
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO auth_sessions "
                "(company_id, user_id, token_hash, family_id, expires_at) "
                "VALUES (:company_id, :user_id, :token_hash, gen_random_uuid(), "
                "now() + interval '7 days')"
            ),
            {
                "company_id": company_id,
                "user_id": user_id,
                "token_hash": f"empreinte-de-test-{slug}",
            },
        )
        session.execute(
            text(
                "INSERT INTO business_events "
                "(company_id, event_type, aggregate_type, aggregate_id, payload) "
                "VALUES (:company_id, 'stock.updated', 'product', :aggregate_id, '{}'::jsonb)"
            ),
            {"company_id": company_id, "aggregate_id": uuid4()},
        )

    _seed_referential(session_factory, tenant)
    _seed_inventory(session_factory, tenant)
    _seed_sales(session_factory, tenant)
    _seed_returns(session_factory, tenant)
    _seed_expenses(session_factory, tenant)
    _seed_restitution(session_factory, tenant)
    return tenant


def _seed_referential(session_factory: sessionmaker[Any], tenant: Tenant) -> None:
    """Une ligne dans chaque table du référentiel (phase 03).

    Les identifiants sont pré-générés : les tests croisés désignent ensuite une
    ligne précise de l'autre entreprise, pas « la première venue ».
    """
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO customers (id, company_id, code, name, credit_limit) "
                "VALUES (:id, :company_id, 'CLI-0001', :name, 250000.00)"
            ),
            {
                "id": tenant.customer_id,
                "company_id": tenant.company_id,
                "name": f"Client {tenant.slug.upper()}",
            },
        )
        session.execute(
            text(
                "INSERT INTO suppliers (id, company_id, code, name, payment_terms_days) "
                "VALUES (:id, :company_id, 'FRN-0001', :name, 30)"
            ),
            {
                "id": tenant.supplier_id,
                "company_id": tenant.company_id,
                "name": f"Fournisseur {tenant.slug.upper()}",
            },
        )
        session.execute(
            text(
                "INSERT INTO categories (id, company_id, name) "
                "VALUES (:id, :company_id, 'Boissons')"
            ),
            {"id": tenant.category_id, "company_id": tenant.company_id},
        )
        session.execute(
            text(
                "INSERT INTO products (id, company_id, category_id, sku, name, unit) "
                "VALUES (:id, :company_id, :category_id, 'SKU-0001', :name, 'piece')"
            ),
            {
                "id": tenant.product_id,
                "company_id": tenant.company_id,
                "category_id": tenant.category_id,
                "name": f"Produit {tenant.slug.upper()}",
            },
        )
        session.execute(
            text(
                "INSERT INTO product_prices "
                "(company_id, product_id, unit_price, cost_price, created_by) "
                "VALUES (:company_id, :product_id, 1500.00, 1000.0000, :created_by)"
            ),
            {
                "company_id": tenant.company_id,
                "product_id": tenant.product_id,
                "created_by": tenant.user_id,
            },
        )


def _seed_inventory(session_factory: sessionmaker[Any], tenant: Tenant) -> None:
    """Un mouvement de stock par entreprise (phase 04).

    Un seul INSERT suffit à peupler les **deux** tables : `t20_inv_apply` crée la
    ligne de `product_stock` au passage. Écrire la projection à la main serait
    d'ailleurs interdit (§ 5.6).
    """
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO inventory_movements "
                "(id, company_id, product_id, type, qty_delta, unit_cost, "
                " ref_type, ref_id, created_by) "
                "VALUES (:id, :company_id, :product_id, 'initial', 100, 1000.0000, "
                "        'initial', :product_id, :created_by)"
            ),
            {
                "id": tenant.movement_id,
                "company_id": tenant.company_id,
                "product_id": tenant.product_id,
                "created_by": tenant.user_id,
            },
        )


def _seed_sales(session_factory: sessionmaker[Any], tenant: Tenant) -> None:
    """Une vente confirmée, sa ligne, son encaissement et sa dette (phase 05).

    L'ordre n'est pas libre : `sale_items_no_change` refuse d'écrire une ligne sur
    une vente qui n'est plus `draft` (ADR 0023). La vente est donc semée en
    brouillon, garnie, puis confirmée — exactement ce que fait le service.

    Les totaux ne sont jamais écrits ici : `sale_recompute_totals` les calcule
    depuis la ligne, `sale_paid_rollup` renseigne `paid_total` depuis le paiement.
    """
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO sales (id, company_id, customer_id, sale_no, created_by) "
                "VALUES (:id, :company_id, :customer_id, 'V-000001', :created_by)"
            ),
            {
                "id": tenant.sale_id,
                "company_id": tenant.company_id,
                "customer_id": tenant.customer_id,
                "created_by": tenant.user_id,
            },
        )
        session.execute(
            text(
                "INSERT INTO sale_items "
                "(id, company_id, sale_id, product_id, qty, unit_price, tax_rate) "
                "VALUES (:id, :company_id, :sale_id, :product_id, 2, 1500.00, 0.1800)"
            ),
            {
                "id": tenant.sale_item_id,
                "company_id": tenant.company_id,
                "sale_id": tenant.sale_id,
                "product_id": tenant.product_id,
            },
        )
        session.execute(
            text(
                "UPDATE sales SET status = 'confirmed', confirmed_at = now() "
                " WHERE company_id = :company_id AND id = :id"
            ),
            {"company_id": tenant.company_id, "id": tenant.sale_id},
        )
        session.execute(
            text(
                "INSERT INTO payments "
                "(id, company_id, direction, method, amount, sale_id, created_by) "
                "VALUES (:id, :company_id, 'inflow', 'cash', 1000.00, :sale_id, :created_by)"
            ),
            {
                "id": tenant.payment_id,
                "company_id": tenant.company_id,
                "sale_id": tenant.sale_id,
                "created_by": tenant.user_id,
            },
        )
        session.execute(
            text(
                "INSERT INTO debts "
                "(id, company_id, party_type, customer_id, sale_id, principal) "
                "VALUES (:id, :company_id, 'customer', :customer_id, :sale_id, 2540.00)"
            ),
            {
                "id": tenant.debt_id,
                "company_id": tenant.company_id,
                "customer_id": tenant.customer_id,
                "sale_id": tenant.sale_id,
            },
        )
        session.execute(
            text(
                "INSERT INTO document_counters (company_id, document_type, next_value) "
                "VALUES (:company_id, 'sale', 2)"
            ),
            {"company_id": tenant.company_id},
        )


def _seed_returns(session_factory: sessionmaker[Any], tenant: Tenant) -> None:
    """Un retour, sa ligne, son remboursement et une allocation (phase 06).

    L'ordre est imposé par les triggers : la ligne de retour renseigne
    `total_refund` par `sri_totals`, et `refund_check` refuserait un lettrage qui
    dépasserait ce total. Le décaissement doit exister avant d'être lettré, et il
    doit être un `outflow` — d'où un **second** paiement, celui de `_seed_sales`
    étant un encaissement.

    `total_refund` et `refunded_total` ne sont jamais écrits ici : les triggers les
    calculent, comme ils le feront pour le service.
    """
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO sale_returns "
                "(id, company_id, sale_id, return_no, reason, created_by) "
                "VALUES (:id, :company_id, :sale_id, 'R-000001', 'Article defectueux', "
                "        :created_by)"
            ),
            {
                "id": tenant.sale_return_id,
                "company_id": tenant.company_id,
                "sale_id": tenant.sale_id,
                "created_by": tenant.user_id,
            },
        )
        session.execute(
            text(
                "INSERT INTO sale_return_items "
                "(id, company_id, return_id, sale_item_id, qty, refund_amount, "
                " tax_refund, unit_cost) "
                "VALUES (:id, :company_id, :return_id, :sale_item_id, 1, 1770.00, "
                "        270.00, 1000.0000)"
            ),
            {
                "id": tenant.sale_return_item_id,
                "company_id": tenant.company_id,
                "return_id": tenant.sale_return_id,
                "sale_item_id": tenant.sale_item_id,
            },
        )
        session.execute(
            text(
                "INSERT INTO payments "
                "(id, company_id, direction, method, amount, sale_return_id, created_by) "
                "VALUES (:id, :company_id, 'outflow', 'cash', 1770.00, :sale_return_id, "
                "        :created_by)"
            ),
            {
                "id": tenant.refund_payment_id,
                "company_id": tenant.company_id,
                "sale_return_id": tenant.sale_return_id,
                "created_by": tenant.user_id,
            },
        )
        session.execute(
            text(
                # Partiel à dessein : le retour garde 770,00 de reste dû, sans quoi
                # `refund_check` refuserait tout lettrage supplémentaire avant même
                # que les clés étrangères de T5 n'aient leur mot à dire.
                "INSERT INTO sale_return_refunds "
                "(id, company_id, sale_return_id, payment_id, amount) "
                "VALUES (:id, :company_id, :sale_return_id, :payment_id, 1000.00)"
            ),
            {
                "id": tenant.refund_id,
                "company_id": tenant.company_id,
                "sale_return_id": tenant.sale_return_id,
                "payment_id": tenant.refund_payment_id,
            },
        )
        # Le lettrage paiement ↔ dette de la phase 05 : l'encaissement de 1 000
        # s'impute sur la dette de la vente, qui passe `partially_paid`.
        session.execute(
            text(
                "INSERT INTO payment_allocations "
                "(id, company_id, payment_id, debt_id, amount) "
                "VALUES (:id, :company_id, :payment_id, :debt_id, 1000.00)"
            ),
            {
                "id": tenant.allocation_id,
                "company_id": tenant.company_id,
                "payment_id": tenant.payment_id,
                "debt_id": tenant.debt_id,
            },
        )


def _seed_expenses(session_factory: sessionmaker[Any], tenant: Tenant) -> None:
    """Une famille de charges, une dépense et une clé d'idempotence (phase 07).

    La clé est semée directement plutôt qu'obtenue par un appel d'API : ce harnais
    attaque la base, et une ligne de `idempotency_keys` doit exister chez chaque
    tenant pour que T1 et T2 aient quelque chose à ne pas voir.
    """
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO expense_categories (id, company_id, name, kind) "
                "VALUES (:id, :company_id, 'Loyer', 'fixed')"
            ),
            {"id": tenant.expense_category_id, "company_id": tenant.company_id},
        )
        session.execute(
            text(
                "INSERT INTO expenses "
                "(id, company_id, expense_no, category_id, supplier_id, label, amount, "
                " spent_at, created_by) "
                "VALUES (:id, :company_id, 'D-000001', :category_id, :supplier_id, "
                "        'Loyer du mois', 50000.00, current_date, :created_by)"
            ),
            {
                "id": tenant.expense_id,
                "company_id": tenant.company_id,
                "category_id": tenant.expense_category_id,
                "supplier_id": tenant.supplier_id,
                "created_by": tenant.user_id,
            },
        )
        session.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(company_id, key, endpoint, request_hash, response_status, expires_at) "
                "VALUES (:company_id, :key, 'POST /api/v1/payments', 'seed', 201, "
                "        now() + interval '24 hours')"
            ),
            {"company_id": tenant.company_id, "key": tenant.idempotency_key},
        )


def _seed_restitution(session_factory: sessionmaker[Any], tenant: Tenant) -> None:
    """Un fait analytique, une alerte et une marque de consommation (phase 08).

    Le fait est écrit à la main plutôt que reconstruit : ce harnais mesure la RLS, pas
    l'exactitude des agrégats — celle-là, ce sont T29 à T32 qui la prouvent. Les
    valeurs respectent tout de même `net_qty_sold = qty_sold - returned_qty`, sans
    quoi le `CHECK` refuserait la ligne.

    `processed_events.event_id` réutilise l'identifiant de l'événement semé dans
    l'outbox : une marque doit désigner un événement réel pour être lisible.
    """
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO daily_sales_facts "
                "(company_id, day, product_id, category_id, qty_sold, returned_qty, "
                " net_qty_sold, gross_revenue, discount_total, tax_total, "
                " refund_net_amount, net_revenue, cogs_gross, cogs_returned, cogs_net, "
                " sale_count) "
                "VALUES (:company_id, :day, :product_id, :category_id, 4.000, 1.000, "
                "        3.000, 4000.00, 0.00, 720.00, 1000.00, 3000.00, 2400.00, "
                "        600.00, 1800.00, 2)"
            ),
            {
                "company_id": tenant.company_id,
                "day": tenant.fact_day,
                "product_id": tenant.product_id,
                "category_id": tenant.category_id,
            },
        )
        session.execute(
            text(
                "INSERT INTO notifications (id, company_id, user_id, type, title, body) "
                "VALUES (:id, :company_id, :user_id, 'stock_low', "
                "        'Stock bas — article de test', 'Semé par le harnais')"
            ),
            {
                "id": tenant.notification_id,
                "company_id": tenant.company_id,
                "user_id": tenant.user_id,
            },
        )
        event_id = session.execute(
            text(
                "SELECT id FROM business_events WHERE company_id = :company_id ORDER BY id LIMIT 1"
            ),
            {"company_id": tenant.company_id},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO processed_events (company_id, consumer, event_id) "
                "VALUES (:company_id, 'harness', :event_id)"
            ),
            {"company_id": tenant.company_id, "event_id": event_id},
        )


def own_row_ids(tenant: Tenant, table: str) -> dict[str, Any]:
    """Critère SQL qui désigne la ligne de `tenant` dans `table`."""
    criteria: dict[str, dict[str, Any]] = {
        "users": {"clause": "id = :value", "value": tenant.user_id},
        "roles": {"clause": "id = :value", "value": tenant.role_id},
        "user_roles": {"clause": "user_id = :value", "value": tenant.user_id},
        "role_permissions": {"clause": "role_id = :value", "value": tenant.role_id},
        # Ces deux tables sont alimentées par les tests qui les concernent ; le
        # critère porte sur le tenant, la RLS étant ce que l'on mesure.
        "customers": {"clause": "id = :value", "value": tenant.customer_id},
        "suppliers": {"clause": "id = :value", "value": tenant.supplier_id},
        "categories": {"clause": "id = :value", "value": tenant.category_id},
        "products": {"clause": "id = :value", "value": tenant.product_id},
        "product_prices": {"clause": "product_id = :value", "value": tenant.product_id},
        "product_stock": {"clause": "product_id = :value", "value": tenant.product_id},
        "inventory_movements": {"clause": "id = :value", "value": tenant.movement_id},
        "sales": {"clause": "id = :value", "value": tenant.sale_id},
        "sale_items": {"clause": "id = :value", "value": tenant.sale_item_id},
        "payments": {"clause": "id = :value", "value": tenant.payment_id},
        "debts": {"clause": "id = :value", "value": tenant.debt_id},
        "sale_returns": {"clause": "id = :value", "value": tenant.sale_return_id},
        "sale_return_items": {"clause": "id = :value", "value": tenant.sale_return_item_id},
        "sale_return_refunds": {"clause": "id = :value", "value": tenant.refund_id},
        "payment_allocations": {"clause": "id = :value", "value": tenant.allocation_id},
        "document_counters": {"clause": "company_id = :value", "value": tenant.company_id},
        "auth_sessions": {"clause": "company_id = :value", "value": tenant.company_id},
        "business_events": {"clause": "company_id = :value", "value": tenant.company_id},
        "expense_categories": {"clause": "id = :value", "value": tenant.expense_category_id},
        "expenses": {"clause": "id = :value", "value": tenant.expense_id},
        "idempotency_keys": {"clause": "key = :value", "value": tenant.idempotency_key},
        # Le critère doit désigner **une** entreprise, sinon le test croisé
        # retrouverait sa propre ligne et conclurait à une fuite. `day` et
        # `consumer` sont identiques chez A et B : on passe par le produit et par
        # l'entreprise, comme le font déjà `business_events` et `document_counters`.
        "daily_sales_facts": {"clause": "product_id = :value", "value": tenant.product_id},
        "notifications": {"clause": "id = :value", "value": tenant.notification_id},
        "processed_events": {"clause": "company_id = :value", "value": tenant.company_id},
    }
    return criteria[table]
