"""Jeu de démonstration : une entreprise, son catalogue, deux mois de ventes.

    make seed-demo

Sert à deux choses, et à rien d'autre : vérifier à la main que le chemin asynchrone
fonctionne de bout en bout, et mesurer `GET /api/v1/dashboard` sur un volume réaliste
(cible < 200 ms). Ce n'est pas une migration, ce n'est pas un jeu de test : les tests
construisent leurs propres données, ligne par ligne, pour pouvoir les affirmer.

Tout passe par les **façades de service**, jamais par des INSERT bruts. C'est la
seule façon d'obtenir un jeu vraisemblable : le CMP est réellement calculé, les
numéros de documents réellement attribués, et surtout les événements réellement
écrits dans l'outbox — sans quoi il n'y aurait rien à relayer, donc rien à voir.

Une limite assumée : les réceptions de stock sont datées de maintenant, parce que
l'antidatage d'un mouvement est borné à 48 h (ADR 0015), alors que les ventes
s'étalent sur soixante jours. L'historique de stock est donc plat — la métrique
« rotation » reste lisible, mais ne raconte pas une vraie saisonnalité.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cli import create_company
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.categories import service as categories_service
from app.modules.categories.schemas import CategoryCreate
from app.modules.customers import service as customers_service
from app.modules.customers.schemas import CustomerCreate
from app.modules.expenses import service as expenses_service
from app.modules.expenses.schemas import ExpenseCategoryCreate, ExpenseCreate
from app.modules.inventory import service as inventory_service
from app.modules.inventory.schemas import MovementCreate
from app.modules.products import service as products_service
from app.modules.products.schemas import ProductCreate
from app.modules.sales import service as sales_service
from app.modules.sales.schemas import (
    SaleCancel,
    SaleConfirm,
    SaleCreate,
    SaleItemCreate,
    SaleReturnCreate,
    SaleReturnLineCreate,
)

#: Graine fixe : deux exécutions produisent le même jeu, donc la même mesure de
#: performance. Un jeu aléatoire rendrait toute comparaison de temps illisible.
SEED = 20260924

DAYS = 60
SALES = 50
CANCELLED = 3
RETURNS = 4

CATALOGUE: tuple[tuple[str, tuple[tuple[str, str, str, str], ...]], ...] = (
    (
        "Boissons",
        (
            ("BOI-001", "Eau minérale 1,5 L", "350", "220"),
            ("BOI-002", "Jus de bissap 1 L", "900", "600"),
            ("BOI-003", "Soda cola 33 cl", "400", "260"),
            ("BOI-004", "Thé vert 250 g", "1800", "1150"),
            ("BOI-005", "Café moulu 500 g", "3500", "2400"),
        ),
    ),
    (
        "Épicerie",
        (
            ("EPI-001", "Riz brisé 25 kg", "14500", "12000"),
            ("EPI-002", "Huile d'arachide 5 L", "7200", "5900"),
            ("EPI-003", "Sucre en poudre 1 kg", "800", "620"),
            ("EPI-004", "Sel fin 1 kg", "300", "180"),
            ("EPI-005", "Pâte d'arachide 1 kg", "2200", "1600"),
            ("EPI-006", "Tomate concentrée 400 g", "750", "520"),
        ),
    ),
    (
        "Entretien",
        (
            ("ENT-001", "Savon de Marseille", "500", "320"),
            ("ENT-002", "Eau de javel 1 L", "650", "430"),
            ("ENT-003", "Détergent 2 kg", "3200", "2400"),
            ("ENT-004", "Éponge à récurer", "200", "110"),
        ),
    ),
    (
        "Papeterie",
        (
            ("PAP-001", "Cahier 200 pages", "900", "620"),
            ("PAP-002", "Stylo bille bleu", "150", "80"),
            ("PAP-003", "Ramette A4 500 f.", "4200", "3300"),
            ("PAP-004", "Chemise cartonnée", "250", "150"),
            ("PAP-005", "Marqueur permanent", "600", "380"),
        ),
    ),
)

CUSTOMERS: tuple[tuple[str, str | None], ...] = (
    ("Boutique Keur Massar", "400000"),
    ("Restaurant Le Baobab", "250000"),
    ("École Cheikh Anta Diop", "600000"),
    ("Cantine Médina", "150000"),
    ("Client de passage", None),
    ("Hôtel Téranga", "800000"),
)

EXPENSES: tuple[tuple[str, str, str], ...] = (
    ("Loyer du local", "fixed", "150000"),
    ("Électricité", "variable", "42000"),
    ("Carburant livraison", "variable", "35000"),
    ("Salaires", "fixed", "320000"),
    ("Connexion internet", "fixed", "25000"),
)


def _decimal(value: str) -> Decimal:
    return Decimal(value)


def seed(slug: str, *, password: str) -> UUID:
    """Construit l'entreprise de démonstration et renvoie son identifiant."""
    rng = random.Random(SEED)
    try:
        company_id_str, manager_id_str = create_company(
            name="Boutique Démo CoGes",
            slug=slug,
            manager_email=f"gerant@{slug}.example.com",
            manager_name="Awa Diop",
            password=password,
            currency="XOF",
            timezone="Africa/Dakar",
        )
    except IntegrityError as exc:
        # Le jeu de démonstration n'est pas rejouable : il écrirait deux fois les
        # mêmes ventes, et la mesure de performance perdrait son sens.
        raise SystemExit(
            f"Une entreprise porte déjà le slug « {slug} ». "
            f"Relancer avec --slug autrement, ou supprimer l'entreprise existante."
        ) from exc
    company_id = UUID(company_id_str)
    ctx = TenantContext(user_id=UUID(manager_id_str), company_id=company_id)

    with tenant_transaction(ctx) as session:
        product_ids, prices = _catalogue(session, ctx)
        customer_ids = _customers(session, ctx)
        _stock(session, ctx, product_ids)

    # Une transaction par vente, comme en production : chaque confirmation est un cas
    # d'usage, et c'est ce qui donne un événement par vente dans l'outbox.
    confirmed: list[tuple[UUID, list[UUID]]] = []
    now = datetime.now(UTC)
    for index in range(SALES):
        sold_at = now - timedelta(
            days=rng.randint(0, DAYS - 1), hours=rng.randint(7, 19), minutes=rng.randint(0, 59)
        )
        with tenant_transaction(ctx) as session:
            # Les ventes destinées à l'annulation partent à crédit : une vente
            # encaissée ne s'annule pas, elle se corrige par un retour (§ 5.2).
            sale_id, item_ids, total = _one_sale(
                session,
                ctx,
                rng,
                product_ids,
                prices,
                customer_ids,
                sold_at,
                force_credit=index < CANCELLED,
            )
            if index < CANCELLED:
                sales_service.cancel_sale(
                    session, ctx, sale_id, SaleCancel(reason="Erreur de saisie en caisse")
                )
            else:
                confirmed.append((sale_id, item_ids))
        del total

    for sale_id, item_ids in rng.sample(confirmed, k=min(RETURNS, len(confirmed))):
        with tenant_transaction(ctx) as session:
            _one_return(session, ctx, sale_id, item_ids)

    with tenant_transaction(ctx) as session:
        _expenses(session, ctx, rng)

    return company_id


def _catalogue(session: Session, ctx: TenantContext) -> tuple[list[UUID], dict[UUID, Decimal]]:
    product_ids: list[UUID] = []
    prices: dict[UUID, Decimal] = {}
    for category_name, items in CATALOGUE:
        category = categories_service.create_category(
            session, ctx, CategoryCreate(name=category_name)
        )
        for sku, name, unit_price, cost_price in items:
            product, _ = products_service.create_product(
                session,
                ctx,
                ProductCreate(
                    sku=sku,
                    name=name,
                    category_id=category.id,
                    default_tax_rate=Decimal("0.18"),
                    reorder_point=Decimal("12"),
                    unit_price=_decimal(unit_price),
                    cost_price=_decimal(cost_price),
                ),
            )
            product_ids.append(product.id)
            prices[product.id] = _decimal(unit_price)
    return product_ids, prices


def _customers(session: Session, ctx: TenantContext) -> list[UUID | None]:
    ids: list[UUID | None] = []
    for name, credit_limit in CUSTOMERS:
        customer = customers_service.create_customer(
            session,
            ctx,
            CustomerCreate(
                name=name,
                credit_limit=None if credit_limit is None else _decimal(credit_limit),
            ),
        )
        ids.append(customer.id)
    # Une vente sur sept n'a pas de client : c'est le comptant de comptoir, et il ne
    # doit pas disparaître des jeux de démonstration.
    ids.append(None)
    return ids


def _stock(session: Session, ctx: TenantContext, product_ids: list[UUID]) -> None:
    """Une réception par produit, assez large pour couvrir soixante jours de ventes."""
    for product_id in product_ids:
        current = products_service.get_current_price(session, ctx, product_id)
        inventory_service.record_movement(
            session,
            ctx,
            MovementCreate(
                product_id=product_id,
                type="initial",
                qty_delta=Decimal("400"),
                unit_cost=current.cost_price or Decimal("100"),
                note="Stock initial de démonstration",
            ),
            idempotency_key=uuid4(),
        )


def _one_sale(
    session: Session,
    ctx: TenantContext,
    rng: random.Random,
    product_ids: list[UUID],
    prices: dict[UUID, Decimal],
    customer_ids: list[UUID | None],
    sold_at: datetime,
    force_credit: bool = False,
) -> tuple[UUID, list[UUID], Decimal]:
    known = [customer_id for customer_id in customer_ids if customer_id is not None]
    customer_id = rng.choice(known) if force_credit else rng.choice(customer_ids)
    sale = sales_service.create_sale(
        session, ctx, SaleCreate(customer_id=customer_id, sold_at=sold_at)
    )
    item_ids: list[UUID] = []
    for product_id in rng.sample(product_ids, k=rng.randint(1, 3)):
        item = sales_service.add_item(
            session,
            ctx,
            sale.id,
            SaleItemCreate(product_id=product_id, qty=Decimal(rng.randint(1, 6))),
        )
        item_ids.append(item.id)

    session.flush()
    session.refresh(sale)
    total = sale.total
    # Un tiers des ventes à client connu part à crédit : sans dette, ni les créances
    # ni les alertes d'échéance n'auraient de quoi s'afficher.
    on_credit = customer_id is not None and (force_credit or rng.random() < 0.34)
    paid = Decimal("0") if on_credit else total
    sales_service.confirm_sale(
        session,
        ctx,
        sale.id,
        SaleConfirm(
            paid_amount=paid,
            method="cash",
            due_date=sold_at + timedelta(days=rng.choice([7, 15, 30])) if on_credit else None,
        ),
    )
    return sale.id, item_ids, total


def _one_return(session: Session, ctx: TenantContext, sale_id: UUID, item_ids: list[UUID]) -> None:
    items = {item.id: item for item in sales_service.get_items(session, ctx, sale_id)}
    target = items.get(item_ids[0])
    if target is None or target.qty < 1:
        return
    sales_service.create_return(
        session,
        ctx,
        sale_id,
        SaleReturnCreate(
            lines=[SaleReturnLineCreate(sale_item_id=target.id, qty=Decimal("1"))],
            reason="Article non conforme",
        ),
    )


def _expenses(session: Session, ctx: TenantContext, rng: random.Random) -> None:
    today = datetime.now(UTC).date()
    for label, kind, amount in EXPENSES:
        category = expenses_service.create_category(
            session, ctx, ExpenseCategoryCreate(name=label, kind=kind)
        )
        # Deux occurrences par charge, réparties sur la période des ventes. Toujours
        # dans le passé : une dépense datée de demain est refusée, et avec raison.
        for offset in rng.sample(range(1, DAYS), k=2):
            spent_at = today - timedelta(days=offset)
            expenses_service.create_expense(
                session,
                ctx,
                ExpenseCreate(
                    category_id=category.id,
                    label=label,
                    amount=_decimal(amount),
                    spent_at=spent_at,
                ),
                ip_address=None,
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed",
        description="Crée une entreprise de démonstration avec deux mois d'activité.",
    )
    parser.add_argument("--slug", default="demo", help="Identifiant court de l'entreprise")
    parser.add_argument(
        "--password",
        default="demo-coges-2026",
        help="Mot de passe du gérant (12 caractères minimum)",
    )
    args = parser.parse_args(argv)

    company_id = seed(args.slug, password=args.password)
    print(f"Entreprise de démonstration créée : {company_id}")
    print(f"  slug     : {args.slug}")
    print(f"  gérant   : gerant@{args.slug}.example.com")
    print(f"  mot de passe : {args.password}")
    print(f"  {SALES} ventes sur {DAYS} jours, dont {CANCELLED} annulées et {RETURNS} retours")
    print("\nLancer `make relay` et `make worker` pour voir les agrégats se construire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
