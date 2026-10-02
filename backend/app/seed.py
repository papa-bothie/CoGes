"""Jeu de démonstration : une épicerie de quartier à Dakar, trois mois d'activité.

    make seed-demo                                   # crée l'entreprise `demo`
    python -m app.seed --existing-slug demo-front \\
        --manager-email gerant@demo-front.example.com  # remplit une entreprise existante

Sert à trois choses : montrer CoGes sur des données crédibles (captures, préproduction),
vérifier à la main le chemin asynchrone de bout en bout, et mesurer
`GET /api/v1/dashboard` sur un volume réaliste (cible < 200 ms). Ce n'est pas une
migration, ce n'est pas un jeu de test : les tests construisent leurs propres données,
ligne par ligne, pour pouvoir les affirmer.

Tout passe par les **façades de service**, jamais par des INSERT bruts. C'est la seule
façon d'obtenir un jeu vraisemblable : le CMP est réellement calculé, les numéros de
documents réellement attribués, les plafonds de crédit réellement vérifiés, et les
événements réellement écrits dans l'outbox.

Limite assumée (ADR 0060) : seules les dates **métier** saisissables sont étalées sur
quatre-vingt-dix jours — `sold_at`, `returned_at`, `spent_at`, `paid_at` des règlements
saisis après coup, et le stock d'ouverture (premier mouvement d'un article, libre de
date, ADR 0015). Ce que le serveur date lui-même reste daté du remplissage : sorties
de stock et encaissements faits à la confirmation, réceptions (bornées à 48 h après
le dernier mouvement), création des dettes. Chiffre d'affaires, marges, créances et
Intelligence sont réalistes ; la trésorerie jour par jour et l'historique de stock
sont concentrés sur le jour du remplissage.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cli import create_company
from app.core.errors import BusinessRuleError
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import LoginRequest
from app.modules.categories import service as categories_service
from app.modules.categories.schemas import CategoryCreate
from app.modules.companies import service as companies_service
from app.modules.companies.schemas import CompanyUpdate
from app.modules.customers import service as customers_service
from app.modules.customers.schemas import CustomerCreate
from app.modules.expenses import service as expenses_service
from app.modules.expenses.schemas import (
    ExpenseCategoryCreate,
    ExpenseCreate,
    ExpensePaymentInput,
)
from app.modules.finance import service as finance_service
from app.modules.finance.schemas import AllocationInput, DebtCreate, PaymentCreate
from app.modules.inventory import service as inventory_service
from app.modules.inventory.schemas import MovementCreate
from app.modules.products import service as products_service
from app.modules.products.schemas import ProductCreate
from app.modules.rbac import service as rbac_service
from app.modules.rbac.matrix import SALESPERSON
from app.modules.sales import service as sales_service
from app.modules.sales.schemas import (
    RefundCreate,
    SaleCancel,
    SaleConfirm,
    SaleCreate,
    SaleItemCreate,
    SaleReturnCreate,
    SaleReturnLineCreate,
)
from app.modules.suppliers import service as suppliers_service
from app.modules.suppliers.schemas import SupplierCreate
from app.modules.users import service as users_service
from app.modules.users.schemas import UserCreate

#: Graine fixe : deux exécutions produisent le même jeu (à la date près), donc la même
#: mesure de performance. Un jeu aléatoire rendrait toute comparaison illisible.
SEED = 20261002

DAYS = 90
COMPANY_NAME = "Alimentation Keur Fatou"
MANAGER_NAME = "Fatou Ndiaye"
SALESPERSON_NAME = "Moussa Diallo"
TIMEZONE = "Africa/Dakar"

ZERO = Decimal("0")
VAT = "0.18"
EXEMPT = "0"


@dataclass(frozen=True, slots=True)
class Article:
    sku: str
    name: str
    unit: str
    price: str
    cost: str
    tax: str
    reorder: str
    #: Fréquence relative dans les paniers : le riz et l'huile partent tous les jours.
    weight: int
    #: Quantités usuelles d'une ligne, au comptoir.
    qtys: tuple[str, ...]
    #: Indice du fournisseur habituel dans `SUPPLIERS`.
    supplier: int
    #: Stock à l'ouverture ; les réassorts suivent ensuite la demande observée.
    batch: str
    #: Fin de période voulue : `rupture`, `low` (sous le seuil) ou rien.
    ending: str | None = None


# fmt: off
CATALOGUE: tuple[tuple[str, tuple[Article, ...]], ...] = (
    (
        "Céréales et féculents",
        (
            Article("RIZ-25", "Riz brisé parfumé, sac 25 kg", "piece", "15500", "13600", EXEMPT, "4", 9, ("1",), 0, "15"),
            Article("RIZ-KG", "Riz brisé au détail", "kg", "650", "545", EXEMPT, "25", 40, ("1", "1", "2", "3", "5"), 0, "250"),
            Article("MIL-KG", "Mil souna", "kg", "500", "380", EXEMPT, "15", 14, ("1", "2", "3"), 2, "100"),
            Article("MAI-KG", "Maïs concassé", "kg", "450", "330", EXEMPT, "10", 8, ("1", "2"), 2, "75"),
            Article("FON-1", "Fonio précuit 1 kg", "piece", "2000", "1500", EXEMPT, "6", 4, ("1",), 2, "30"),
            Article("FAR-KG", "Farine de blé", "kg", "600", "470", EXEMPT, "10", 10, ("1", "2"), 0, "75"),
            Article("PAT-500", "Spaghetti 500 g", "piece", "450", "330", EXEMPT, "20", 16, ("1", "2", "3"), 0, "120", "low"),
            Article("COU-1", "Couscous de mil 1 kg", "piece", "1200", "850", EXEMPT, "8", 6, ("1",), 2, "40"),
        ),
    ),
    (
        "Huiles et condiments",
        (
            Article("HUI-L", "Huile végétale au détail", "litre", "1300", "1080", EXEMPT, "15", 30, ("0.5", "1", "1", "2"), 0, "120"),
            Article("HUI-5", "Huile d'arachide, bidon 5 L", "piece", "7500", "6300", EXEMPT, "4", 6, ("1",), 0, "18"),
            Article("BOU-100", "Bouillon en cubes, boîte de 100", "piece", "2500", "2000", VAT, "6", 7, ("1",), 0, "36"),
            Article("BOU-U", "Bouillon en cube, à l'unité", "piece", "25", "18", VAT, "200", 28, ("4", "6", "10"), 0, "1500"),
            Article("TOM-400", "Tomate concentrée 400 g", "piece", "750", "560", EXEMPT, "12", 12, ("1", "2"), 0, "72"),
            Article("TOM-70", "Tomate concentrée, sachet 70 g", "piece", "150", "100", EXEMPT, "40", 26, ("1", "2", "3"), 0, "300"),
            Article("SEL-1", "Sel iodé 1 kg", "piece", "250", "160", EXEMPT, "12", 10, ("1",), 0, "60"),
            Article("OIG-KG", "Oignons", "kg", "500", "380", EXEMPT, "20", 32, ("0.5", "1", "1", "2"), 2, "200", "rupture"),
            Article("POI-50", "Poivre noir moulu 50 g", "piece", "400", "260", VAT, "8", 6, ("1",), 0, "40"),
            Article("VIN-1", "Vinaigre blanc 1 L", "piece", "700", "500", VAT, "6", 5, ("1",), 0, "30"),
            Article("MOU-370", "Moutarde 370 g", "piece", "1200", "900", VAT, "5", 4, ("1",), 0, "24", "low"),
        ),
    ),
    (
        "Petit-déjeuner",
        (
            Article("LAI-400", "Lait en poudre 400 g", "piece", "2600", "2150", EXEMPT, "8", 9, ("1",), 0, "48"),
            Article("LAI-25", "Lait en poudre, sachet 25 g", "piece", "125", "85", EXEMPT, "60", 30, ("1", "2", "4"), 0, "500", "rupture"),
            Article("SUC-KG", "Sucre en poudre", "kg", "750", "620", EXEMPT, "25", 30, ("0.5", "1", "1", "2"), 0, "200"),
            Article("SUC-MOR", "Sucre en morceaux 1 kg", "piece", "900", "720", EXEMPT, "8", 8, ("1",), 0, "50"),
            Article("CAF-250", "Café Touba moulu 250 g", "piece", "1500", "1100", EXEMPT, "8", 11, ("1",), 2, "50"),
            Article("THE-250", "Thé vert de Chine 250 g", "piece", "1800", "1300", EXEMPT, "8", 10, ("1",), 0, "50"),
            Article("KIN-100", "Kinkéliba en feuilles 100 g", "piece", "500", "320", EXEMPT, "6", 5, ("1",), 2, "30", "rupture"),
            Article("CHO-400", "Chocolat en poudre 400 g", "piece", "2200", "1700", VAT, "5", 4, ("1",), 0, "24"),
            Article("MAR-250", "Margarine 250 g", "piece", "800", "600", VAT, "8", 8, ("1",), 0, "48", "low"),
        ),
    ),
    (
        "Boissons",
        (
            Article("EAU-15", "Eau minérale 1,5 L", "piece", "350", "230", VAT, "24", 18, ("1", "2", "6"), 3, "144"),
            Article("EAU-S30", "Eau en sachet, pack de 30", "paquet", "1500", "1100", VAT, "6", 6, ("1",), 3, "40"),
            Article("BIS-1", "Jus de bissap 1 L", "piece", "1000", "650", VAT, "8", 8, ("1", "2"), 3, "48"),
            Article("GIN-1", "Jus de gingembre 1 L", "piece", "1000", "650", VAT, "8", 7, ("1", "2"), 3, "48", "low"),
            Article("SOD-33", "Soda en canette 33 cl", "piece", "400", "270", VAT, "24", 14, ("1", "2", "4"), 3, "144"),
            Article("ENE-25", "Boisson énergisante 25 cl", "piece", "600", "420", VAT, "12", 6, ("1",), 3, "72"),
        ),
    ),
    (
        "Entretien et hygiène",
        (
            Article("SAV-400", "Savon de ménage 400 g", "piece", "350", "240", VAT, "20", 14, ("1", "2"), 4, "120"),
            Article("SAV-125", "Savon de toilette 125 g", "piece", "400", "270", VAT, "15", 9, ("1", "2"), 4, "96"),
            Article("JAV-1", "Eau de javel 1 L", "piece", "600", "420", VAT, "10", 8, ("1",), 4, "60"),
            Article("LES-1", "Lessive en poudre 1 kg", "piece", "1400", "1080", VAT, "8", 7, ("1",), 4, "48"),
            Article("LES-150", "Lessive en poudre, sachet 150 g", "piece", "250", "170", VAT, "30", 16, ("1", "2"), 4, "200"),
            Article("EPO-1", "Éponge à vaisselle", "piece", "200", "110", VAT, "15", 6, ("1", "2"), 4, "100"),
            Article("PAP-4", "Papier hygiénique, 4 rouleaux", "paquet", "1000", "720", VAT, "8", 5, ("1",), 4, "40"),
            Article("DEN-75", "Dentifrice 75 ml", "piece", "700", "480", VAT, "8", 5, ("1",), 4, "48"),
        ),
    ),
    (
        "Divers",
        (
            Article("BOG-6", "Bougies, paquet de 6", "paquet", "600", "420", VAT, "8", 5, ("1",), 1, "48"),
            Article("ALL-10", "Allumettes, lot de 10 boîtes", "paquet", "500", "340", VAT, "8", 6, ("1",), 1, "48"),
            Article("PIL-AA", "Piles AA, lot de 4", "paquet", "1200", "850", VAT, "6", 4, ("1",), 1, "30", "low"),
            Article("CHA-10", "Charbon de bois, sac 10 kg", "piece", "2500", "1900", EXEMPT, "6", 7, ("1",), 1, "30"),
        ),
    ),
)
# fmt: on

#: (nom, plafond de crédit, téléphone, poids, profil). Un plafond `None` laisse le
#: crédit libre, `"0"` l'interdit. Le profil règle la taille des paniers et la façon
#: de payer : `pro` (restaurants, cantines), `regular`, `late` (paie en retard),
#: `bad` (une créance finira abandonnée).
CUSTOMERS: tuple[tuple[str, str | None, str, int, str], ...] = (
    ("Restaurant Chez Tanti Awa", "400000", "+221 77 412 35 18", 9, "pro"),
    ("Dibiterie Chez Modou", "250000", "+221 76 588 20 41", 6, "pro"),
    ("Cantine de l'école Liberté 6", "500000", "+221 33 824 17 90", 5, "pro"),
    ("Tangana Pape Ndiaye", "120000", "+221 78 301 66 25", 6, "pro"),
    ("Boutique Serigne Mbaye", "300000", "+221 77 655 09 83", 4, "late"),
    ("Mme Ndèye Fall", "50000", "+221 77 230 44 71", 8, "regular"),
    ("Mme Aïssatou Diallo", "40000", "+221 70 118 52 06", 7, "regular"),
    ("M. Ibrahima Ndiaye", "40000", "+221 76 940 13 57", 6, "late"),
    ("Mme Khady Sarr", "30000", "+221 77 803 29 64", 6, "regular"),
    ("M. Mamadou Ba", "30000", "+221 78 562 71 30", 5, "regular"),
    ("Gargote Yaye Fatou", "150000", "+221 77 477 85 12", 5, "pro"),
    ("Mme Coumba Gaye", "25000", "+221 70 655 38 49", 4, "regular"),
    ("M. Cheikh Diop", "35000", "+221 76 207 94 16", 3, "bad"),
    ("Mme Mariama Cissé", "0", "+221 77 389 60 22", 4, "regular"),
    ("M. Abdoulaye Sy", None, "+221 78 714 05 93", 3, "regular"),
)

#: (nom, téléphone, délai de paiement en jours).
SUPPLIERS: tuple[tuple[str, str, int], ...] = (
    ("Sandaga Distribution", "+221 33 821 45 60", 15),
    ("Établissements Diop et Fils", "+221 33 842 19 77", 0),
    ("Comptoir alimentaire de Thiaroye", "+221 77 640 28 15", 7),
    ("Dakar Boissons Distribution", "+221 33 869 52 04", 30),
    ("Hygiène Plus", "+221 33 855 71 38", 15),
)

#: (libellé, nature, montant, jours du mois, aléa en %). Une dépense par jour listé.
EXPENSES: tuple[tuple[str, str, str, tuple[int, ...], int], ...] = (
    ("Loyer de la boutique", "fixed", "125000", (5,), 0),
    ("Électricité", "variable", "32000", (12,), 20),
    ("Eau", "variable", "7500", (14,), 25),
    ("Salaire du vendeur", "fixed", "90000", (28,), 0),
    ("Transport des marchandises", "variable", "4000", (3, 10, 17, 24), 40),
    ("Crédit téléphonique et internet", "fixed", "10000", (1,), 0),
    ("Sacs et emballages", "variable", "6000", (8, 22), 30),
)

RETURN_REASONS = (
    "Emballage abîmé",
    "Produit périmé à la livraison",
    "Erreur de quantité",
    "Article échangé",
)
CANCEL_REASONS = ("Erreur de saisie en caisse", "Client parti sans la marchandise")

#: Jours de la semaine (lundi = 0) : le samedi est le jour du marché, le dimanche est
#: calme, le vendredi après la prière remplit la boutique.
WEEKDAY_FACTOR = (1.0, 0.95, 1.0, 1.05, 1.2, 1.35, 0.55)
#: Heures d'ouverture et affluence relative : matin, retour du travail le soir.
HOURS = tuple(range(7, 22))
HOUR_WEIGHTS = (3, 6, 6, 5, 4, 5, 4, 3, 3, 4, 6, 8, 8, 6, 3)


@dataclass(slots=True)
class Shop:
    """Ce que le remplissage sait de l'entreprise, et le miroir de son état."""

    company_id: UUID
    manager: TenantContext
    salesperson: TenantContext
    tz: ZoneInfo
    articles: dict[UUID, Article] = field(default_factory=dict)
    stock: dict[UUID, Decimal] = field(default_factory=dict)
    sold: dict[UUID, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    supplier_ids: list[UUID] = field(default_factory=list)
    #: (identifiant, plafond, profil, poids)
    customers: list[tuple[UUID, Decimal | None, str, int]] = field(default_factory=list)
    outstanding: dict[UUID, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    #: Règlements de créances à venir : jour → (vente, client, montant, moyen).
    settlements: dict[date, list[tuple[UUID, UUID, Decimal, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    #: Règlements fournisseurs à venir : jour → dette.
    supplier_payments: dict[date, list[UUID]] = field(default_factory=lambda: defaultdict(list))
    cash_sales: list[tuple[UUID, datetime]] = field(default_factory=list)
    old_debts_of_bad_payer: list[UUID] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def seed(slug: str, *, password: str, days: int = DAYS, scale: float = 1.0) -> UUID:
    """Crée l'entreprise de démonstration, la remplit et renvoie son identifiant."""
    try:
        company_id_str, manager_id_str = create_company(
            name=COMPANY_NAME,
            slug=slug,
            manager_email=f"gerant@{slug}.example.com",
            manager_name=MANAGER_NAME,
            password=password,
            currency="XOF",
            timezone=TIMEZONE,
        )
    except IntegrityError as exc:
        # Le jeu n'est pas rejouable : il écrirait deux fois les mêmes ventes.
        raise SystemExit(
            f"Une entreprise porte déjà le slug « {slug} ». "
            f"Relancer avec --slug autrement, ou --existing-slug pour la remplir."
        ) from exc
    manager = TenantContext(user_id=UUID(manager_id_str), company_id=UUID(company_id_str))
    fill(manager, slug=slug, password=password, days=days, scale=scale)
    return manager.company_id


def seed_existing(
    slug: str,
    *,
    manager_email: str,
    password: str,
    rename: str | None,
    days: int = DAYS,
    scale: float = 1.0,
) -> UUID:
    """Remplit une entreprise existante, vide de ventes, au nom de son gérant.

    L'entreprise et le gérant sont trouvés par une **connexion** (`auth_service.login`) :
    il faut le mot de passe du gérant, et aucune lecture ne contourne la RLS.
    """
    tokens = auth_service.login(
        LoginRequest(company_slug=slug, email=manager_email, password=password)
    )
    manager = TenantContext(user_id=tokens.user_id, company_id=tokens.company_id)
    with tenant_transaction(manager) as session:
        _, sale_count, _ = sales_service.list_sales(session, manager, page=1, page_size=1)
        if sale_count:
            raise SystemExit(
                f"« {slug} » a déjà {sale_count} vente(s) : le jeu ne s'écrit que sur une "
                "entreprise sans vente."
            )
        archived = 0
        products, _ = products_service.list_products(
            session, manager, page=1, page_size=100, is_active=True
        )
        catalogue_skus = {article.sku for _, articles in CATALOGUE for article in articles}
        for product, _ in products:
            if product.sku not in catalogue_skus:
                products_service.delete_product(session, manager, product.id)
                archived += 1
        if rename:
            companies_service.update_current_company(
                session, manager, CompanyUpdate(name=rename, timezone=TIMEZONE)
            )
    if archived:
        print(f"{archived} produit(s) hors catalogue archivé(s).")
    fill(manager, slug=slug, password=password, days=days, scale=scale)
    return manager.company_id


def fill(manager: TenantContext, *, slug: str, password: str, days: int, scale: float) -> None:
    rng = random.Random(SEED)
    with tenant_transaction(manager) as session:
        tz = ZoneInfo(companies_service.get_timezone(session, manager))
        salesperson_id = _salesperson(session, manager, slug=slug, password=password)
        # Les permissions réelles de chacun, comme la dépendance d'authentification les
        # pose : un service qui vérifie un droit le vérifie aussi ici.
        manager = _with_permissions(session, manager, manager.user_id)
        shop = Shop(
            company_id=manager.company_id,
            manager=manager,
            salesperson=_with_permissions(session, manager, salesperson_id),
            tz=tz,
        )
        shop.supplier_ids = _suppliers(session, manager)
        shop.customers = _customers(session, manager)

    today = datetime.now(tz).date()
    start = today - timedelta(days=days - 1)
    with tenant_transaction(manager) as session:
        _catalogue(session, shop, opened_at=_at(shop, start, time(7, 0)))

    expense_categories = _expense_categories(shop)

    for offset in range(days):
        day = start + timedelta(days=offset)
        _settle_customer_debts(shop, rng, day)
        _pay_suppliers(shop, day)
        _restock(shop, rng, day, elapsed=offset, days_left=days - 1 - offset)
        _day_of_sales(shop, rng, day, progress=offset / days, scale=scale)
        _day_of_expenses(shop, rng, day, expense_categories)

    _returns(shop, rng, today)
    _write_off(shop)
    for label, count in sorted(shop.counts.items()):
        print(f"  {label:<14} {count}")


# --- Référentiels -------------------------------------------------------------------


def _with_permissions(session: Session, ctx: TenantContext, user_id: UUID) -> TenantContext:
    codes = rbac_service.permission_codes_for_user(session, ctx, user_id)
    return TenantContext(user_id=user_id, company_id=ctx.company_id, permissions=frozenset(codes))


def _salesperson(session: Session, ctx: TenantContext, *, slug: str, password: str) -> UUID:
    email = f"vendeur@{slug}.example.com"
    users, _ = users_service.list_users(session, ctx, page=1, page_size=100)
    for user in users:
        if user.email == email:
            return user.id
    role_id = rbac_service.system_role_id(session, ctx, SALESPERSON)
    user = users_service.create_user(
        session,
        ctx,
        UserCreate(
            email=email,
            full_name=SALESPERSON_NAME,
            password=password,
            role_ids=[] if role_id is None else [role_id],
        ),
    )
    return user.id


def _suppliers(session: Session, ctx: TenantContext) -> list[UUID]:
    return [
        suppliers_service.create_supplier(
            session, ctx, SupplierCreate(name=name, phone=phone, payment_terms_days=terms)
        ).id
        for name, phone, terms in SUPPLIERS
    ]


def _customers(session: Session, ctx: TenantContext) -> list[tuple[UUID, Decimal | None, str, int]]:
    rows = []
    for name, limit, phone, weight, profile in CUSTOMERS:
        credit_limit = None if limit is None else Decimal(limit)
        customer = customers_service.create_customer(
            session, ctx, CustomerCreate(name=name, phone=phone, credit_limit=credit_limit)
        )
        rows.append((customer.id, credit_limit, profile, weight))
    return rows


def _catalogue(session: Session, shop: Shop, *, opened_at: datetime) -> None:
    """Catalogue et stock d'ouverture, daté du premier jour.

    Le premier mouvement d'un article échappe à la fenêtre d'antidatage (ADR 0015) :
    c'est la reprise d'un stock existant, et elle porte sa vraie date.
    """
    ctx = shop.manager
    existing = categories_service.ids_by_name(session, ctx)
    for category_name, articles in CATALOGUE:
        ids = existing.get(category_name)
        category_id = (
            ids[0]
            if ids
            else categories_service.create_category(
                session, ctx, CategoryCreate(name=category_name)
            ).id
        )
        for article in articles:
            product, _ = products_service.create_product(
                session,
                ctx,
                ProductCreate(
                    sku=article.sku,
                    name=article.name,
                    unit=article.unit,
                    category_id=category_id,
                    default_tax_rate=Decimal(article.tax),
                    reorder_point=Decimal(article.reorder),
                    unit_price=Decimal(article.price),
                    cost_price=Decimal(article.cost),
                ),
            )
            opening = Decimal(article.batch)
            inventory_service.record_movement(
                session,
                ctx,
                MovementCreate(
                    product_id=product.id,
                    type="initial",
                    qty_delta=opening,
                    unit_cost=Decimal(article.cost),
                    supplier_id=shop.supplier_ids[article.supplier],
                    note="Stock à l'ouverture du logiciel",
                    occurred_at=opened_at,
                ),
                idempotency_key=uuid4(),
            )
            shop.articles[product.id] = article
            shop.stock[product.id] = opening


def _expense_categories(shop: Shop) -> dict[str, UUID]:
    with tenant_transaction(shop.manager) as session:
        return {
            label: expenses_service.create_category(
                session,
                shop.manager,
                ExpenseCategoryCreate(name=label, kind=kind),
            ).id
            for label, kind, *_ in EXPENSES
        }


# --- Une journée --------------------------------------------------------------------


def _restock(shop: Shop, rng: random.Random, day: date, *, elapsed: int, days_left: int) -> None:
    """Commande chez le fournisseur habituel ce qui passe sous le seuil de commande.

    Le seuil et la quantité suivent la demande observée (trois semaines de ventes). Sur
    le dernier mois, les articles marqués `rupture` ou `low` ne sont plus commandés
    que pour finir à zéro ou sous leur seuil : les alertes de la démo sont vraies.

    Une facture par fournisseur et par jour ; à crédit quand le fournisseur accorde un
    délai, réglée à l'échéance (ou laissée ouverte si l'échéance n'est pas atteinte).
    """
    by_supplier: dict[int, list[tuple[UUID, Article, Decimal, Decimal]]] = defaultdict(list)
    for product_id, article in shop.articles.items():
        qty = _order_qty(shop, product_id, article, elapsed=elapsed, days_left=days_left)
        if qty <= ZERO:
            continue
        # Les prix d'achat montent un peu sur la période : le CMP bouge vraiment.
        drift = Decimal(1 + rng.uniform(0, 0.05)).quantize(Decimal("0.0001"))
        unit_cost = (Decimal(article.cost) * drift).quantize(Decimal("1"))
        by_supplier[article.supplier].append((product_id, article, qty, unit_cost))
    if not by_supplier:
        return

    with tenant_transaction(shop.manager) as session:
        for supplier, lines in by_supplier.items():
            supplier_id = shop.supplier_ids[supplier]
            invoice = ZERO
            for product_id, _, qty, unit_cost in lines:
                inventory_service.record_movement(
                    session,
                    shop.manager,
                    MovementCreate(
                        product_id=product_id,
                        type="purchase_in",
                        qty_delta=qty,
                        unit_cost=unit_cost,
                        supplier_id=supplier_id,
                        note=f"Livraison du {day:%d/%m/%Y}",
                    ),
                    idempotency_key=uuid4(),
                )
                invoice += qty * unit_cost
            terms = SUPPLIERS[supplier][2]
            if terms:
                due = day + timedelta(days=terms)
                debt = finance_service.create_debt(
                    session,
                    shop.manager,
                    DebtCreate(
                        party_type="supplier",
                        supplier_id=supplier_id,
                        principal=invoice,
                        due_date=due,
                    ),
                )
                shop.supplier_payments[due].append(debt.id)
            else:
                # Payé comptant à la livraison, à la date de la livraison.
                finance_service.record_payment(
                    session,
                    shop.manager,
                    PaymentCreate(
                        direction="outflow",
                        method="cash",
                        amount=invoice,
                        paid_at=_at(shop, day, time(8, 30)),
                        note=f"Livraison {SUPPLIERS[supplier][0]}",
                    ),
                )
    for _, lines in by_supplier.items():
        for product_id, _, qty, _ in lines:
            shop.stock[product_id] += qty
    shop.counts["receptions"] += sum(len(lines) for lines in by_supplier.values())


def _order_qty(
    shop: Shop, product_id: UUID, article: Article, *, elapsed: int, days_left: int
) -> Decimal:
    stock = shop.stock[product_id]
    reorder = Decimal(article.reorder)
    rate = shop.sold[product_id] / elapsed if elapsed >= 7 else Decimal(article.batch) / 30
    if stock >= max(reorder * Decimal("1.5"), rate * 4):
        return ZERO
    if article.ending == "rupture" and days_left <= 30:
        # Le fournisseur n'a plus livré : le rayon se vide avant la fin.
        return ZERO
    if article.ending == "low" and days_left <= 30:
        # Juste de quoi tenir, et finir sous le seuil.
        return max(ZERO, rate * days_left + reorder / 2 - stock).quantize(Decimal("1"))
    return max(rate * 21, reorder * 2).quantize(Decimal("1"))


def _pay_suppliers(shop: Shop, day: date) -> None:
    due = shop.supplier_payments.pop(day, [])
    if not due:
        return
    with tenant_transaction(shop.manager) as session:
        for debt_id in due:
            debt = finance_service.get_debt(session, shop.manager, debt_id)
            finance_service.record_payment(
                session,
                shop.manager,
                PaymentCreate(
                    direction="outflow",
                    method="bank_transfer",
                    amount=debt.balance,
                    paid_at=_at(shop, day, time(10, 0)),
                    allocations=[AllocationInput(debt_id=debt_id, amount=debt.balance)],
                ),
            )


def _settle_customer_debts(shop: Shop, rng: random.Random, day: date) -> None:
    due = shop.settlements.pop(day, [])
    for sale_id, customer_id, amount, method in due:
        with tenant_transaction(shop.manager) as session:
            debt = finance_service.debt_for_sale(session, shop.manager, sale_id)
            if debt is None or debt.status not in ("open", "partially_paid"):
                continue
            paid = min(amount, debt.balance)
            finance_service.record_payment(
                session,
                shop.manager,
                PaymentCreate(
                    direction="inflow",
                    method=method,
                    amount=paid,
                    paid_at=_at(shop, day, time(rng.randint(9, 19), rng.randint(0, 59))),
                    allocations=[AllocationInput(debt_id=debt.id, amount=paid)],
                ),
            )
        shop.outstanding[customer_id] -= paid
        shop.counts["settlements"] += 1


def _day_of_sales(
    shop: Shop, rng: random.Random, day: date, *, progress: float, scale: float
) -> None:
    factor = WEEKDAY_FACTOR[day.weekday()] * (1.2 if day.day <= 5 else 1.0) * (1 + 0.15 * progress)
    count = max(1, round(rng.randint(9, 15) * factor * scale))
    now = datetime.now(shop.tz)
    times = sorted(
        datetime.combine(
            day, time(rng.choices(HOURS, HOUR_WEIGHTS)[0], rng.randint(0, 59)), tzinfo=shop.tz
        )
        for _ in range(count)
    )
    for sold_at in times:
        # Aujourd'hui, seules les ventes déjà passées ont eu lieu.
        if sold_at > now:
            continue
        _one_sale(shop, rng, sold_at.astimezone(UTC))


def _one_sale(shop: Shop, rng: random.Random, sold_at: datetime) -> None:
    customer = None
    if rng.random() < 0.3:
        customer = rng.choices(shop.customers, [row[3] for row in shop.customers])[0]
    profile = customer[2] if customer else "walk-in"

    lines = _basket(shop, rng, profile)
    if not lines:
        return
    seller = shop.salesperson if rng.random() < 0.6 else shop.manager
    cancel = customer is not None and profile != "bad" and rng.random() < 0.02

    try:
        with tenant_transaction(seller) as session:
            sale = sales_service.create_sale(
                session,
                seller,
                SaleCreate(customer_id=None if customer is None else customer[0], sold_at=sold_at),
            )
            for product_id, qty in lines:
                sales_service.add_item(
                    session, seller, sale.id, SaleItemCreate(product_id=product_id, qty=qty)
                )
            session.flush()
            session.refresh(sale)
            total = sale.total

            paid, due_days = _payment_terms(shop, rng, customer, total, force_credit=cancel)
            method = _method(rng, profile)
            sales_service.confirm_sale(
                session,
                seller,
                sale.id,
                SaleConfirm(
                    paid_amount=paid,
                    method=method,
                    due_date=None if due_days is None else sold_at + timedelta(days=due_days),
                ),
            )
            if cancel:
                sales_service.cancel_sale(
                    session, shop.manager, sale.id, SaleCancel(reason=rng.choice(CANCEL_REASONS))
                )
    except BusinessRuleError as exc:
        # Rare (plafond atteint entre-temps, stock juste) : la vente n'a pas eu lieu, et
        # c'est aussi ce que vivrait la caisse.
        shop.counts[f"refusée : {exc.code}"] += 1
        return

    if cancel:
        shop.counts["cancelled"] += 1
        return
    for product_id, qty in lines:
        shop.stock[product_id] -= qty
        shop.sold[product_id] += qty
    shop.counts["sales"] += 1
    if customer is None or paid == total:
        if paid == total:
            shop.cash_sales.append((sale.id, sold_at))
        return
    _schedule_settlement(shop, rng, sale.id, customer, total - paid, sold_at, due_days or 15)


def _basket(shop: Shop, rng: random.Random, profile: str) -> list[tuple[UUID, Decimal]]:
    size = rng.choices((1, 2, 3, 4, 5), (34, 30, 20, 10, 6))[0]
    if profile == "pro":
        size += 1
    ids = list(shop.articles)
    weights = [shop.articles[product_id].weight for product_id in ids]
    chosen: dict[UUID, Decimal] = {}
    for product_id in rng.choices(ids, weights, k=size * 2):
        if product_id in chosen or len(chosen) == size:
            continue
        qty = Decimal(rng.choice(shop.articles[product_id].qtys))
        if profile == "pro":
            qty *= rng.choice((2, 3, 5))
        # Le client prend ce qui reste : c'est ainsi qu'un rayon se vide vraiment.
        qty = min(qty, shop.stock[product_id])
        if qty > ZERO:
            chosen[product_id] = qty
    return list(chosen.items())


def _payment_terms(
    shop: Shop,
    rng: random.Random,
    customer: tuple[UUID, Decimal | None, str, int] | None,
    total: Decimal,
    *,
    force_credit: bool,
) -> tuple[Decimal, int | None]:
    """Part payée à la confirmation, et délai accordé sur le reste."""
    if customer is None:
        return total, None
    customer_id, limit, profile, _ = customer
    if limit == ZERO:
        return total, None
    odds = {"pro": 0.55, "bad": 0.9}.get(profile, 0.4)
    wants_credit = force_credit or rng.random() < odds
    if not wants_credit:
        return total, None
    deposit = ZERO
    if not force_credit and rng.random() < 0.5:
        share = Decimal(rng.choice(("0.3", "0.5")))
        deposit = (total * share / 500).quantize(Decimal("1"), rounding=ROUND_DOWN) * 500
    remaining = total - deposit
    if limit is not None and shop.outstanding[customer_id] + remaining > limit:
        return total, None
    return deposit, rng.choice((7, 15, 15, 30))


def _method(rng: random.Random, profile: str) -> str:
    if profile == "pro":
        return rng.choices(("cash", "mobile_money", "bank_transfer"), (50, 40, 10))[0]
    return rng.choices(("cash", "mobile_money"), (75, 25))[0]


def _schedule_settlement(
    shop: Shop,
    rng: random.Random,
    sale_id: UUID,
    customer: tuple[UUID, Decimal | None, str, int],
    remaining: Decimal,
    sold_at: datetime,
    due_days: int,
) -> None:
    customer_id, _, profile, _ = customer
    shop.outstanding[customer_id] += remaining
    sold_on = sold_at.date()
    if profile == "bad":
        shop.old_debts_of_bad_payer.append(sale_id)
        return
    if profile == "late":
        delay = due_days + rng.randint(5, 25)
    else:
        delay = rng.randint(max(1, due_days - 5), due_days + 3)
    method = _method(rng, profile)
    if rng.random() < 0.35:
        # Deux versements : une moitié vers l'échéance, le reste un peu plus tard.
        half = (remaining / 2).quantize(Decimal("1"), rounding=ROUND_DOWN)
        shop.settlements[sold_on + timedelta(days=delay)].append(
            (sale_id, customer_id, half, method)
        )
        shop.settlements[sold_on + timedelta(days=delay + rng.randint(4, 12))].append(
            (sale_id, customer_id, remaining - half, method)
        )
    else:
        shop.settlements[sold_on + timedelta(days=delay)].append(
            (sale_id, customer_id, remaining, method)
        )


def _day_of_expenses(
    shop: Shop, rng: random.Random, day: date, categories: dict[str, UUID]
) -> None:
    due = [row for row in EXPENSES if day.day in row[3]]
    if not due:
        return
    with tenant_transaction(shop.manager) as session:
        for label, _, amount, _, jitter in due:
            value = Decimal(amount) * Decimal(1 + rng.uniform(-jitter, jitter) / 100)
            value = (value / 100).quantize(Decimal("1")) * 100
            expenses_service.create_expense(
                session,
                shop.manager,
                ExpenseCreate(
                    category_id=categories[label],
                    label=label,
                    amount=value,
                    spent_at=day,
                    payment=ExpensePaymentInput(
                        method="cash" if value < 50000 else "mobile_money",
                        paid_at=_at(shop, day, time(11, 0)),
                    ),
                ),
            )
            shop.counts["expenses"] += 1


# --- Après coup ---------------------------------------------------------------------


def _returns(shop: Shop, rng: random.Random, today: date) -> None:
    """Six retours sur des ventes comptant récentes ; les quatre premiers remboursés."""
    recent = [row for row in shop.cash_sales if (today - row[1].date()).days < 60]
    for index, (sale_id, sold_at) in enumerate(rng.sample(recent, k=min(6, len(recent)))):
        returned_at = min(
            sold_at + timedelta(days=rng.randint(1, 3), hours=rng.randint(0, 4)),
            datetime.now(shop.tz),
        )
        try:
            with tenant_transaction(shop.manager) as session:
                items = sales_service.get_items(session, shop.manager, sale_id)
                item = items[0]
                qty = Decimal("1") if item.qty >= 1 else item.qty
                sale_return = sales_service.create_return(
                    session,
                    shop.manager,
                    sale_id,
                    SaleReturnCreate(
                        lines=[SaleReturnLineCreate(sale_item_id=item.id, qty=qty)],
                        reason=rng.choice(RETURN_REASONS),
                        returned_at=returned_at,
                    ),
                )
                if index < 4 and sale_return.total_refund > ZERO:
                    sales_service.refund_return(
                        session,
                        shop.manager,
                        sale_return.id,
                        RefundCreate(amount=sale_return.total_refund, method="cash"),
                    )
        except BusinessRuleError as exc:
            shop.counts[f"retour refusé : {exc.code}"] += 1
            continue
        shop.counts["returns"] += 1


def _write_off(shop: Shop) -> None:
    """La plus ancienne créance du mauvais payeur est abandonnée ; les autres restent."""
    if not shop.old_debts_of_bad_payer:
        return
    with tenant_transaction(shop.manager) as session:
        debt = finance_service.debt_for_sale(session, shop.manager, shop.old_debts_of_bad_payer[0])
        if debt is None:
            return
        finance_service.write_off_debt(
            session,
            shop.manager,
            debt.id,
            reason="Client injoignable depuis deux mois, créance jugée irrécouvrable",
        )
    shop.counts["write-off"] += 1


def _at(shop: Shop, day: date, moment: time) -> datetime:
    """Instant d'une journée de l'entreprise, jamais après maintenant (le jour même)."""
    return min(datetime.combine(day, moment, tzinfo=shop.tz), datetime.now(shop.tz)).astimezone(UTC)


# --- Ligne de commande --------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed",
        description="Épicerie de démonstration : catalogue, clients, trois mois d'activité.",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--slug", default="demo", help="Crée cette entreprise (défaut : demo)")
    target.add_argument(
        "--existing-slug",
        default=None,
        help="Remplit cette entreprise existante, sans vente, au nom de son gérant",
    )
    parser.add_argument("--manager-email", default=None, help="Gérant de --existing-slug")
    parser.add_argument(
        "--rename",
        default=COMPANY_NAME,
        help=f"Nouveau nom de --existing-slug (défaut : {COMPANY_NAME} ; vide = inchangé)",
    )
    parser.add_argument(
        "--password",
        default="demo-coges-2026",
        help="Mot de passe du gérant (et du vendeur créé), 12 caractères minimum",
    )
    parser.add_argument("--days", type=int, default=DAYS, help=f"Jours d'activité ({DAYS})")
    parser.add_argument(
        "--scale", type=float, default=1.0, help="Multiplie le nombre de ventes par jour"
    )
    args = parser.parse_args(argv)

    if args.existing_slug:
        slug = args.existing_slug
        email = args.manager_email or f"gerant@{slug}.example.com"
        company_id = seed_existing(
            slug,
            manager_email=email,
            password=args.password,
            rename=args.rename or None,
            days=args.days,
            scale=args.scale,
        )
        print(f"Entreprise de démonstration remplie : {company_id}")
    else:
        slug = args.slug
        email = f"gerant@{slug}.example.com"
        company_id = seed(slug, password=args.password, days=args.days, scale=args.scale)
        print(f"Entreprise de démonstration créée : {company_id}")
    print(f"  slug     : {slug}")
    print(f"  gérant   : {email}")
    print(f"  vendeur  : vendeur@{slug}.example.com (même mot de passe)")
    print(f"  {args.days} jours d'activité")
    print("\nLancer `make relay` et `make worker` pour voir les agrégats se construire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
