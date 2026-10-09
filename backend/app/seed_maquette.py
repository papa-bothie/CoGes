"""Données de la maquette v2 : Alimentation Keur Fatou, le mardi 6 octobre 2026 à 10 h 45.

    make seed-maquette                    # crée l'entreprise `maquette` dans la base locale
    COGES_FROZEN_NOW=2026-10-06T10:45:00+00:00 make api   # pour la voir « ce jour-là »

Sert à comparer le front aux captures de `docs/design/maquette-v2/` (phase 15, ADR 0065).
Les captures ne se tiennent pas entre elles (les cinq dernières ventes de l'accueil font
90 000 F quand la tuile annonce 87 500 F pour 14 ventes, etc.) : ce jeu est **cohérent et
au plus près** (choix du propriétaire du produit, 2026-10-07). Sont exacts : la boutique,
les personnes, les articles (nom, rayon, prix, stock, seuil), les clients et fournisseurs
(nom, téléphone, ce qu'ils doivent), les tuiles et le graphique de l'accueil, les dépenses
du mois. Chaque chiffre qui diffère d'une capture est listé dans
`docs/design/maquette-v2/ecarts.md`.

Comme `app.seed`, tout passe par les **façades de service**. Ce que le serveur date
lui-même (sorties de stock, encaissements faits à la confirmation, livraisons, création
des dettes, journal d'audit, outbox…) porte d'abord l'heure du remplissage (ADR 0060) ;
`restamp` le recale ensuite, en propriétaire et pour cette seule entreprise, sur l'heure
de son opération d'origine, jamais après `FROZEN_NOW` (ADR 0065).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.cli import create_company
from app.core.config import get_settings
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.analytics import service as analytics_service
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
from app.modules.sales.schemas import SaleCancel, SaleConfirm, SaleCreate, SaleItemCreate
from app.modules.suppliers import service as suppliers_service
from app.modules.suppliers.schemas import SupplierCreate
from app.modules.users import service as users_service
from app.modules.users.schemas import UserCreate, UserUpdate

#: Le moment des captures, et la valeur de `COGES_FROZEN_NOW` qui va avec.
FROZEN_NOW = datetime(2026, 10, 6, 10, 45, tzinfo=UTC)
TIMEZONE = "Africa/Dakar"
SLUG = "maquette"
COMPANY_NAME = "Alimentation Keur Fatou"
MANAGER_NAME = "Fatou Diop"
PASSWORD = "demo-coges-2026"
SEED = 20261006

#: Premier jour d'activité, et le nombre de ventes avant aujourd'hui : la dernière vente
#: du jour porte le n° 1046, comme dans la maquette (« Vente n° 1046 · Awa Diop »).
FIRST_DAY = date(2026, 9, 1)
LAST_SALE_NUMBER = 1046

#: Ventes des six jours passés du graphique de l'accueil (« Vos ventes des 7 derniers jours »).
CHART = {
    date(2026, 9, 30): 62000,
    date(2026, 10, 1): 71500,
    date(2026, 10, 2): 98000,
    date(2026, 10, 3): 124000,
    date(2026, 10, 4): 45000,
    date(2026, 10, 5): 80500,
}
TODAY = FROZEN_NOW.date()
TODAY_TOTAL = 87500
TODAY_COUNT = 14

ZERO = Decimal("0")

#: Ce qui précède la première vente : l'entreprise, les comptes, les rayons, les articles
#: et leurs prix, les clients et les fournisseurs (heure du recalage, voir `restamp`).
OPENING = datetime(2026, 9, 1, 6, 30, tzinfo=UTC)
#: Livraison du Grossiste Sandaga (maquettes 11 et 16), payée en partie à 11 h 30.
DELIVERY_AT = datetime(2026, 10, 3, 11, 0, tzinfo=UTC)
#: Dette de Sénégal Distribution : due le 18 octobre, à 30 jours (maquette 13).
SENDIS_DEBT_AT = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
#: Une vente annulée l'est quelques minutes après avoir été encaissée.
CANCEL_DELAY = timedelta(minutes=3)


@dataclass(frozen=True)
class Article:
    key: str
    name: str
    category: str
    unit: str
    price: int
    cost: int
    stock: int  # stock final, au 6 octobre à 10 h 45 (maquette 07)
    reorder: int  # seuil « Bientôt épuisé » (maquette 07)
    weight: int = 10  # fréquence dans les paniers de passage


#: Les articles des maquettes 02 et 07. Prix, stocks et seuils de la maquette ; coûts de
#: la livraison (maquette 11) quand elle les donne, sinon une marge d'épicerie (~20 %).
ARTICLES: tuple[Article, ...] = (
    Article("riz", "Riz brisé 25 kg", "Céréales", "sac", 15500, 14000, 2, 3, 3),
    Article("huile", "Huile Dinor 1 L", "Huiles", "bouteille", 1400, 1150, 4, 5, 9),
    Article("sucre", "Sucre en morceaux 1 kg", "Épicerie", "paquet", 900, 700, 3, 5, 8),
    Article("laitp", "Lait en poudre 500 g", "Épicerie", "piece", 3200, 2600, 0, 4, 1),
    Article("lait", "Lait Vitalait 400 g", "Épicerie", "piece", 2600, 2000, 18, 6, 6),
    Article("cafe", "Café Touba 250 g", "Boissons", "paquet", 1000, 800, 25, 8, 10),
    Article("savon", "Savon Madar", "Hygiène", "piece", 300, 230, 60, 10, 14),
    Article("oignon", "Oignons 1 kg", "Épicerie", "kg", 600, 450, 40, 8, 10),
    Article("the", "Thé Lipton 25 sachets", "Boissons", "piece", 1250, 1000, 14, 5, 5),
    Article("pates", "Pâtes 500 g", "Céréales", "paquet", 650, 500, 32, 8, 8),
    Article("tomate", "Tomate concentrée 400 g", "Épicerie", "piece", 1100, 850, 22, 6, 6),
    Article("eau", "Eau Kirène 1,5 L", "Boissons", "piece", 400, 300, 48, 12, 12),
    Article("bougie", "Bougies (paquet)", "Épicerie", "paquet", 500, 380, 12, 4, 2),
)
BY_KEY = {article.key: article for article in ARTICLES}
#: L'écran « Rayons » (12) montre aussi un rayon vide.
CATEGORIES = ("Céréales", "Huiles", "Boissons", "Hygiène", "Épicerie", "Produits frais")

#: Clients de la maquette 13 : nom, téléphone.
CUSTOMERS: tuple[tuple[str, str, str], ...] = (
    ("moussa", "Moussa Fall", "76 220 15 90"),
    ("aminata", "Aminata Sow", "77 655 90 21"),
    ("mariama", "Mariama Diallo", "77 903 27 58"),
    ("ibrahima", "Ibrahima Ba", "70 118 62 47"),
    ("awa", "Awa Diop", "77 412 08 33"),
    ("ndiaye", "Boutique Ndiaye", "78 301 44 12"),
    ("ousmane", "Ousmane Sarr", "76 584 11 06"),
    ("fatou", "Fatou Gaye", "77 220 87 14"),
    ("cheikh", "Cheikh Mbaye", "78 645 02 39"),
    ("ndeye", "Ndeye Faye", "77 318 55 70"),
)

#: Fournisseurs de la maquette 13 : nom, téléphone, délai de paiement.
SUPPLIERS: tuple[tuple[str, str, str, int | None], ...] = (
    ("sandaga", "Grossiste Sandaga", "33 821 45 10", 7),
    ("sendis", "Sénégal Distribution", "33 864 22 07", 30),
    ("boulangerie", "Boulangerie Mame Diarra", "77 540 19 82", None),
    ("laiterie", "Laiterie du Berger", "33 957 30 44", None),
    ("diouf", "Ets Diouf et Frères", "77 609 73 21", None),
)

#: Catégories de dépense de la maquette 20, dans son ordre.
EXPENSE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Loyer", "fixed"),
    ("Électricité", "variable"),
    ("Eau", "variable"),
    ("Transport", "variable"),
    ("Salaires", "fixed"),
    ("Téléphone et internet", "fixed"),
    ("Réparations", "variable"),
    ("Taxes et impôts", "fixed"),
    ("Autre", "variable"),
)

#: Dépenses du mois (maquette 20) : 237 500 F, comme « Ce mois » de L'argent (17).
EXPENSES: tuple[tuple[str, str, int, datetime, str], ...] = (
    ("Loyer", "Loyer d'octobre", 120000, datetime(2026, 10, 1, 9, 0, tzinfo=UTC), "wave"),
    ("Eau", "Facture d'eau", 12500, datetime(2026, 10, 1, 9, 30, tzinfo=UTC), "wave"),
    ("Salaires", "Salaire de Modou", 50000, datetime(2026, 10, 2, 18, 0, tzinfo=UTC), "cash"),
    (
        "Téléphone et internet",
        "Crédit internet",
        5000,
        datetime(2026, 10, 2, 12, 0, tzinfo=UTC),
        "orange_money",
    ),
    ("Transport", "Transport", 15000, datetime(2026, 10, 3, 11, 0, tzinfo=UTC), "cash"),
    (
        "Électricité",
        "Facture d'électricité",
        35000,
        datetime(2026, 10, 6, 8, 30, tzinfo=UTC),
        "cash",
    ),
)


@dataclass(frozen=True)
class NamedSale:
    """Une vente que la maquette nomme : client, moment, panier, ce qui est payé."""

    customer: str | None
    sold_at: datetime
    lines: dict[str, int]
    paid: int
    method: str = "cash"
    #: Règlements ultérieurs de sa dette : (instant, montant, moyen).
    settlements: tuple[tuple[datetime, int, str], ...] = ()
    #: Encaissée puis annulée (paiement annulé, puis vente) : hors des totaux du jour.
    cancelled: bool = False

    @property
    def total(self) -> int:
        return sum(BY_KEY[key].price * qty for key, qty in self.lines.items())


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=UTC)


#: Dettes clients de la maquette 18 (« Encaisser une dette ») et 14 (fiche de Moussa
#: Fall), et ventes du jour de l'accueil (01). Total dû : 54 500 F par 5 clients. Les
#: paniers suivent les libellés de la maquette (« Riz, huile, sucre ») au franc près.
NAMED_SALES: tuple[NamedSale, ...] = (
    NamedSale("moussa", _at(date(2026, 9, 1), 17, 20), {"riz": 1, "huile": 2, "savon": 4}, 19500),
    # Le riz et le lait en poudre ne se vendent qu'ici : leur stock final (2 sacs, épuisé)
    # se règle au sac près.
    NamedSale(None, _at(date(2026, 9, 8), 10, 5), {"laitp": 1}, 3200),
    NamedSale(None, _at(date(2026, 9, 10), 9, 30), {"riz": 1}, 15500),
    NamedSale(None, _at(date(2026, 9, 17), 17, 45), {"riz": 1}, 15500),
    NamedSale(None, _at(date(2026, 9, 27), 11, 20), {"laitp": 2}, 6400),
    NamedSale(
        "moussa",
        _at(date(2026, 9, 14), 18, 5),
        {"lait": 3, "cafe": 4, "savon": 1, "eau": 1},
        0,
        settlements=((_at(date(2026, 9, 19), 11, 0), 12500, "cash"),),
    ),
    NamedSale(
        "cheikh",
        _at(date(2026, 9, 22), 16, 40),
        {"pates": 2, "tomate": 2, "oignon": 3, "sucre": 1},
        6200,
    ),
    NamedSale(
        "moussa",
        _at(date(2026, 9, 24), 10, 15),
        {"riz": 1, "huile": 5, "sucre": 5, "savon": 10},
        15000,
        method="wave",
    ),
    NamedSale(
        "aminata",
        _at(date(2026, 9, 28), 17, 50),
        {"riz": 1, "huile": 1, "savon": 2, "the": 2},
        1200,
        settlements=((_at(TODAY, 8, 55), 6800, "cash"),),
    ),
    NamedSale("ibrahima", _at(date(2026, 9, 30), 12, 12), {"riz": 1}, 9500),
    NamedSale("ndeye", _at(date(2026, 10, 1), 16, 30), {"eau": 1, "the": 2, "savon": 4}, 4100),
    NamedSale("mariama", _at(date(2026, 10, 3), 8, 3), {"savon": 5, "bougie": 7, "the": 2}, 0),
    NamedSale(
        "ousmane",
        _at(date(2026, 10, 3), 15, 10),
        {"cafe": 2, "sucre": 1, "pates": 2, "tomate": 1},
        5300,
    ),
    NamedSale("awa", _at(date(2026, 10, 5), 11, 40), {"huile": 3, "tomate": 4, "eau": 1}, 5000),
    NamedSale("fatou", _at(date(2026, 10, 5), 18, 25), {"oignon": 1, "pates": 4, "savon": 2}, 3800),
    # « Vente annulée par Modou · enregistrée deux fois » (alertes 23, historique 24d).
    NamedSale(None, _at(date(2026, 10, 5), 17, 12), {"oignon": 3}, 1800, cancelled=True),
    # Aujourd'hui, de la plus ancienne à la plus récente (accueil 01, caisse 21).
    NamedSale(None, _at(TODAY, 8, 47), {"oignon": 3}, 1800),
    NamedSale(
        "ndiaye",
        _at(TODAY, 9, 20),
        {"riz": 2, "savon": 10, "bougie": 2},
        35000,
        method="orange_money",
    ),
    # Détaillée par les maquettes 04 et 05 : 1 riz, 5 huiles, 5 bougies.
    NamedSale("moussa", _at(TODAY, 9, 58), {"riz": 1, "huile": 5, "bougie": 5}, 15000),
    NamedSale(None, _at(TODAY, 10, 15), {"cafe": 2, "eau": 3}, 3200),
    NamedSale(
        "awa",
        _at(TODAY, 10, 42),
        {"lait": 2, "cafe": 3, "huile": 2, "savon": 5},
        12500,
        method="wave",
    ),
)

#: Les montants que la maquette affiche, vérifiés au chargement du module.
_EXPECTED_TOTALS = (
    19500,
    3200,
    15500,
    15500,
    6400,
    12500,
    6200,
    30000,
    20000,
    15500,
    4100,
    7500,
    5300,
    9000,
    3800,
    1800,
    1800,
    35000,
    25000,
    3200,
    12500,
)
assert tuple(sale.total for sale in NAMED_SALES) == _EXPECTED_TOTALS


#: Une vente prévue : client (clé), instant, panier (clé → quantité), vente nommée.
type PlannedSale = tuple[str | None, datetime, dict[str, int], NamedSale | None]


# --- Paniers ------------------------------------------------------------------------


def solve_basket(target: int, keys: Sequence[str], rng: random.Random) -> dict[str, int]:
    """Quantités des articles `keys` (chacun au moins une fois) dont le total vaut `target`.

    Petit sac à dos sur les prix (tous multiples de 50) : on retire d'abord un exemplaire
    de chaque article, puis on cherche une somme exacte pour le reste. Les articles sont
    essayés dans un ordre tiré au sort, pour que deux paniers ne se ressemblent pas.
    """
    base = sum(BY_KEY[key].price for key in keys)
    rest = target - base
    if rest < 0:
        raise ValueError(f"{target} F ne suffit pas pour {keys}")
    order = list(keys)
    rng.shuffle(order)
    step = 50
    size = rest // step
    best: list[str | None] = [None] * (size + 1)
    reach = [False] * (size + 1)
    reach[0] = True
    for amount in range(1, size + 1):
        for key in order:
            price = BY_KEY[key].price // step
            if price <= amount and reach[amount - price]:
                reach[amount] = True
                best[amount] = key
                break
    if rest % step or not reach[size]:
        raise ValueError(f"Aucun panier de {target} F avec {keys}")
    quantities = Counter(keys)
    amount = size
    while amount:
        picked = best[amount]
        assert picked is not None
        quantities[picked] += 1
        amount -= BY_KEY[picked].price // step
    return dict(quantities)


def walk_in_baskets(
    count: int, total: int, rng: random.Random, *, cheap: bool = False
) -> list[dict[str, int]]:
    """`count` paniers de passage dont la somme vaut exactement `total`.

    Chaque panier vise le montant moyen du jour, à ±60 % ; le dernier est résolu au franc
    près (`solve_basket`). On recommence tant que le reste n'est pas un panier plausible.
    """
    pool = [a for a in ARTICLES if a.key not in ("riz", "laitp")]
    if cheap:
        pool = [a for a in pool if a.price <= 1400]
    average = total / count
    for _ in range(2000):
        baskets: list[dict[str, int]] = []
        spent = 0
        for _ in range(count - 1):
            aim = average * rng.uniform(0.4, 1.6)
            basket: dict[str, int] = defaultdict(int)
            amount = 0
            while True:
                choices = [a for a in pool if amount + a.price <= aim]
                if not choices:
                    break
                article = rng.choices(choices, [a.weight for a in choices])[0]
                basket[article.key] += 1
                amount += article.price
            if not basket:
                cheapest = min(pool, key=lambda a: a.price)
                basket[cheapest.key] = 1
                amount = cheapest.price
            baskets.append(dict(basket))
            spent += amount
        rest = total - spent
        if rest < 300 or rest > max(average * 2.5, 3000):
            continue
        keys = [a.key for a in pool if a.price <= rest]
        for size in (1, 2, 3):
            for _ in range(15):
                chosen = tuple(rng.sample(keys, k=min(size, len(keys))))
                try:
                    baskets.append(solve_basket(rest, chosen, rng))
                    rng.shuffle(baskets)
                    return baskets
                except ValueError:
                    continue
    raise RuntimeError(f"Impossible de composer {count} paniers pour {total} F")


# --- Remplissage --------------------------------------------------------------------


@dataclass
class Shop:
    manager: TenantContext
    seller: TenantContext
    products: dict[str, UUID] = field(default_factory=dict)
    customers: dict[str, UUID] = field(default_factory=dict)
    suppliers: dict[str, UUID] = field(default_factory=dict)
    sold: Counter[str] = field(default_factory=Counter)
    received: Counter[str] = field(default_factory=Counter)
    sales: int = 0
    #: Moments d'origine des lignes que `restamp` ne peut pas déduire d'une autre :
    #: mouvements de la livraison et dettes fournisseurs, par identifiant.
    moments: dict[UUID, datetime] = field(default_factory=dict)


def seed(*, slug: str = SLUG, password: str = PASSWORD, owner_engine: Engine | None = None) -> UUID:
    """Crée l'entreprise de la maquette, la remplit, recale ses horodatages et renvoie son
    identifiant.

    Le plan des ventes se calcule **avant** toute écriture : un plan impossible ne laisse
    pas d'entreprise à moitié remplie. Le recalage se fait sous le rôle propriétaire
    (`owner_engine`, sinon `COGES_DATABASE_URL_OWNER`).
    """
    plan = _plan(random.Random(SEED))
    try:
        company_id, manager_id = create_company(
            name=COMPANY_NAME,
            slug=slug,
            manager_email=f"gerant@{slug}.example.com",
            manager_name=MANAGER_NAME,
            password=password,
            currency="XOF",
            timezone=TIMEZONE,
        )
    except IntegrityError as exc:
        raise SystemExit(f"Une entreprise porte déjà le slug « {slug} ».") from exc
    manager = TenantContext(user_id=UUID(manager_id), company_id=UUID(company_id))
    shop = _fill(manager, plan, slug=slug, password=password)
    engine = owner_engine or create_engine(get_settings().require_owner_url(), future=True)
    try:
        restamp(engine, manager.company_id, shop.moments)
    finally:
        if owner_engine is None:
            engine.dispose()
    return manager.company_id


def _with_permissions(ctx: TenantContext, user_id: UUID) -> TenantContext:
    with tenant_transaction(ctx) as session:
        codes = rbac_service.permission_codes_for_user(session, ctx, user_id)
    return TenantContext(user_id=user_id, company_id=ctx.company_id, permissions=frozenset(codes))


#: Coordonnées de la boutique, comme sur le reçu et la facture de la maquette (05, 05b).
SHOP_DETAILS = CompanyUpdate(
    address="Marché HLM 5, Dakar",
    phone="77 123 45 67",
    wave_number="77 123 45 67",
    ninea="0012345678",
    rc="SN-DKR-2024-A-1234",
    receipt_footer=(
        "Merci de votre visite ! Les articles ne sont ni repris ni échangés après 7 jours."
    ),
)


def _fill(manager: TenantContext, plan: list[PlannedSale], *, slug: str, password: str) -> Shop:
    manager = _with_permissions(manager, manager.user_id)
    with tenant_transaction(manager) as session:
        companies_service.update_current_company(session, manager, SHOP_DETAILS)
        role_id = rbac_service.system_role_id(session, manager, SALESPERSON)
        roles = [] if role_id is None else [role_id]
        modou = users_service.create_user(
            session,
            manager,
            UserCreate(
                email=f"vendeur@{slug}.example.com",
                full_name="Modou Sène",
                password=password,
                role_ids=roles,
            ),
        )
        awa = users_service.create_user(
            session,
            manager,
            UserCreate(
                email=f"vendeuse@{slug}.example.com",
                full_name="Awa Ndiaye",
                password=password,
                role_ids=roles,
            ),
        )
        users_service.update_user(session, manager, awa.id, UserUpdate(is_active=False))
    shop = Shop(manager=manager, seller=_with_permissions(manager, modou.id))

    with tenant_transaction(manager) as session:
        for key, name, phone in CUSTOMERS:
            shop.customers[key] = customers_service.create_customer(
                session, manager, CustomerCreate(name=name, phone=phone)
            ).id
        for key, name, phone, terms in SUPPLIERS:
            shop.suppliers[key] = suppliers_service.create_supplier(
                session, manager, SupplierCreate(name=name, phone=phone, payment_terms_days=terms)
            ).id

    _catalogue(shop, plan)
    # Les mouvements de stock portent la date du remplissage jusqu'au recalage : la
    # livraison du 3 octobre passe avant les ventes, pour qu'aucune ne manque de riz.
    _delivery(shop)
    _history(shop, plan)
    _suppliers(shop)
    _expenses(shop)
    _rebuild_facts(manager)
    print(f"  ventes         {shop.sales}")
    return shop


def _plan(
    rng: random.Random,
) -> list[PlannedSale]:
    """Toutes les ventes, dans l'ordre chronologique, avec leurs paniers."""
    named_by_day: dict[date, list[NamedSale]] = defaultdict(list)
    for sale in NAMED_SALES:
        named_by_day[sale.sold_at.date()].append(sale)

    days = [FIRST_DAY + timedelta(days=offset) for offset in range((TODAY - FIRST_DAY).days)]
    history_count = LAST_SALE_NUMBER - TODAY_COUNT
    named_before = sum(len(named_by_day[day]) for day in days)
    walk_ins = history_count - named_before
    # Plus de monde le samedi, moins le dimanche ; le reste réparti au hasard.
    shares = [(1.4 if day.weekday() == 5 else 0.6 if day.weekday() == 6 else 1.0) for day in days]
    counts = [int(walk_ins * share / sum(shares)) for share in shares]
    for index in rng.sample(range(len(days)), walk_ins - sum(counts)):
        counts[index] += 1

    plan: list[PlannedSale] = []
    for day, count in [
        *zip(days, counts, strict=True),
        (TODAY, TODAY_COUNT - len(named_by_day[TODAY])),
    ]:
        named = named_by_day[day]
        named_total = sum(sale.total for sale in named if not sale.cancelled)
        if day == TODAY:
            total = TODAY_TOTAL - named_total
        elif day in CHART:
            total = CHART[day] - named_total
        else:
            total = rng.randrange(52000, 96000, 500) - named_total
        cheap = day == TODAY
        baskets = walk_in_baskets(count, total, rng, cheap=cheap)
        # Aujourd'hui, les ventes de passage précèdent la première vente nommée (8 h 47).
        opening, closing = (7, 8) if day == TODAY else (7, 20)
        times = sorted(_at(day, rng.randint(opening, closing), rng.randint(0, 59)) for _ in baskets)
        if day == TODAY:
            times = [min(moment, _at(day, 8, 40)) for moment in times]
        rows: list[PlannedSale] = [
            (None, moment, basket, None) for moment, basket in zip(times, baskets, strict=True)
        ]
        for sale in named:
            rows.append((sale.customer, sale.sold_at, dict(sale.lines), sale))
        plan.extend(sorted(rows, key=lambda row: row[1]))
    return plan


def _catalogue(shop: Shop, plan: list[PlannedSale]) -> None:
    """Rayons, articles et stock d'ouverture : ce qu'il faut pour finir au stock de la
    maquette, livraison du 3 octobre comprise (enregistrée juste après)."""
    sold: Counter[str] = Counter()
    for _, _, lines, _ in plan:
        sold.update(lines)
    delivery = {"riz": 10, "huile": 24}
    ctx = shop.manager
    with tenant_transaction(ctx) as session:
        categories = {
            name: categories_service.create_category(session, ctx, CategoryCreate(name=name)).id
            for name in CATEGORIES
        }
        for index, article in enumerate(ARTICLES, start=1):
            product, _ = products_service.create_product(
                session,
                ctx,
                ProductCreate(
                    sku=f"KF-{index:03d}",
                    name=article.name,
                    unit=article.unit,
                    category_id=categories[article.category],
                    reorder_point=Decimal(article.reorder),
                    unit_price=Decimal(article.price),
                    cost_price=Decimal(article.cost),
                ),
            )
            shop.products[article.key] = product.id
            opening = article.stock + sold[article.key] - delivery.get(article.key, 0)
            if opening <= 0:
                raise RuntimeError(f"Stock d'ouverture impossible pour {article.name} : {opening}")
            inventory_service.record_movement(
                session,
                ctx,
                MovementCreate(
                    product_id=product.id,
                    type="initial",
                    qty_delta=Decimal(opening),
                    unit_cost=Decimal(article.cost),
                    note="Stock à l'ouverture du logiciel",
                    occurred_at=_at(FIRST_DAY, 7, 0),
                ),
                idempotency_key=uuid4(),
            )
    shop.received.update(delivery)


def _history(shop: Shop, plan: list[PlannedSale]) -> None:
    for customer, sold_at, lines, named in plan:
        seller = shop.seller if shop.sales % 3 else shop.manager
        with tenant_transaction(seller) as session:
            sale = sales_service.create_sale(
                session,
                seller,
                SaleCreate(
                    customer_id=None if customer is None else shop.customers[customer],
                    sold_at=sold_at,
                ),
            )
            for key, qty in lines.items():
                sales_service.add_item(
                    session,
                    seller,
                    sale.id,
                    SaleItemCreate(product_id=shop.products[key], qty=Decimal(qty)),
                )
            session.flush()
            session.refresh(sale)
            paid = sale.total if named is None else Decimal(named.paid)
            sales_service.confirm_sale(
                session,
                seller,
                sale.id,
                SaleConfirm(
                    paid_amount=paid,
                    method="cash" if named is None else named.method,
                    due_date=None if paid == sale.total else sold_at.date() + timedelta(days=10),
                ),
            )
        shop.sales += 1
        shop.sold.update(lines)
        if named is not None:
            for paid_at, amount, method in named.settlements:
                _settle(shop, sale.id, paid_at, amount, method)
            if named.cancelled:
                _cancel(shop, sale.id)


def _settle(shop: Shop, sale_id: UUID, paid_at: datetime, amount: int, method: str) -> None:
    with tenant_transaction(shop.manager) as session:
        debt = finance_service.debt_for_sale(session, shop.manager, sale_id)
        assert debt is not None
        finance_service.record_payment(
            session,
            shop.manager,
            PaymentCreate(
                direction="inflow",
                method=method,
                amount=Decimal(amount),
                paid_at=paid_at,
                allocations=[AllocationInput(debt_id=debt.id, amount=Decimal(amount))],
            ),
        )


def _cancel(shop: Shop, sale_id: UUID) -> None:
    """Annulation d'une vente encaissée : son paiement d'abord, par contre-écriture
    (ADR 0038), puis la vente. Le gérant annule (le vendeur n'en a pas le droit)."""
    reason = "Vente enregistrée deux fois"
    with tenant_transaction(shop.manager) as session:
        for payment in finance_service.payment_reads_for_sale(session, shop.manager, sale_id):
            finance_service.cancel_payment(session, shop.manager, payment.id, reason=reason)
    with tenant_transaction(shop.manager) as session:
        sales_service.cancel_sale(session, shop.manager, sale_id, SaleCancel(reason=reason))


def _delivery(shop: Shop) -> None:
    """Livraison du Grossiste Sandaga du 3 octobre (maquettes 11 et 16) : 10 sacs de riz,
    24 huiles, 167 600 F ; 47 600 F payés en espèces, 120 000 F à payer avant le 10."""
    ctx = shop.manager
    with tenant_transaction(ctx) as session:
        for key, qty, cost in (("riz", 10, 14000), ("huile", 24, 1150)):
            movement = inventory_service.record_movement(
                session,
                ctx,
                MovementCreate(
                    product_id=shop.products[key],
                    type="purchase_in",
                    qty_delta=Decimal(qty),
                    unit_cost=Decimal(cost),
                    supplier_id=shop.suppliers["sandaga"],
                    note="Livraison du 03/10/2026",
                ),
                idempotency_key=uuid4(),
            )
            shop.moments[movement.id] = DELIVERY_AT
        debt = finance_service.create_debt(
            session,
            ctx,
            DebtCreate(
                party_type="supplier",
                supplier_id=shop.suppliers["sandaga"],
                principal=Decimal(167600),
                due_date=date(2026, 10, 10),
            ),
        )
        shop.moments[debt.id] = DELIVERY_AT
        finance_service.record_payment(
            session,
            ctx,
            PaymentCreate(
                direction="outflow",
                method="cash",
                amount=Decimal(47600),
                paid_at=_at(date(2026, 10, 3), 11, 30),
                allocations=[AllocationInput(debt_id=debt.id, amount=Decimal(47600))],
            ),
        )


def _suppliers(shop: Shop) -> None:
    """Sénégal Distribution : 65 000 F avant le 18 octobre (maquette 13). Les livraisons
    payées de septembre (fiche 16) sont des décaissements."""
    ctx = shop.manager
    with tenant_transaction(ctx) as session:
        debt = finance_service.create_debt(
            session,
            ctx,
            DebtCreate(
                party_type="supplier",
                supplier_id=shop.suppliers["sendis"],
                principal=Decimal(65000),
                due_date=date(2026, 10, 18),
            ),
        )
        shop.moments[debt.id] = SENDIS_DEBT_AT
        for paid_at, amount, method, note in (
            (_at(date(2026, 9, 7), 10, 0), 60000, "cash", "Livraison du 07/09 : 5 sacs de riz"),
            (_at(date(2026, 9, 25), 10, 0), 85000, "wave", "Livraison du 22/09"),
        ):
            finance_service.record_payment(
                session,
                ctx,
                PaymentCreate(
                    direction="outflow",
                    method=method,
                    amount=Decimal(amount),
                    paid_at=paid_at,
                    note=note,
                ),
            )


def _expenses(shop: Shop) -> None:
    ctx = shop.manager
    with tenant_transaction(ctx) as session:
        categories = {
            name: expenses_service.create_category(
                session,
                ctx,
                ExpenseCategoryCreate(name=name, kind=kind),
            ).id
            for name, kind in EXPENSE_CATEGORIES
        }
    for category, label, amount, spent_at, method in EXPENSES:
        with tenant_transaction(ctx) as session:
            expenses_service.create_expense(
                session,
                ctx,
                ExpenseCreate(
                    category_id=categories[category],
                    label=label,
                    amount=Decimal(amount),
                    spent_at=spent_at.date(),
                    payment=ExpensePaymentInput(method=method, paid_at=spent_at),
                ),
            )


def _rebuild_facts(manager: TenantContext) -> None:
    """Ce que le worker ferait après chaque vente : les faits du graphique et des
    analyses, jour par jour, sous le rôle analytique (seul autorisé à purger)."""
    from app.core.database import get_analytics_session_factory

    ctx = TenantContext.bootstrap(manager.company_id)
    days = [FIRST_DAY + timedelta(days=offset) for offset in range((TODAY - FIRST_DAY).days + 1)]
    with tenant_transaction(ctx, session_factory=get_analytics_session_factory()) as session:
        analytics_service.rebuild_days(session, ctx, days=days)


# --- Recalage des horodatages ---------------------------------------------------------

#: Tables dont `restamp` réécrit une date. Leurs triggers utilisateur (journal
#: append-only, `updated_at` automatique, recalcul des soldes) sont coupés le temps de la
#: transaction : on ne change que des dates, jamais un montant ni une quantité.
RESTAMPED_TABLES = (
    "companies",
    "users",
    "roles",
    "user_roles",
    "categories",
    "products",
    "product_prices",
    "product_stock",
    "customers",
    "suppliers",
    "sales",
    "sale_items",
    "payments",
    "payment_allocations",
    "debts",
    "inventory_movements",
    "expense_categories",
    "expenses",
    "audit_logs",
    "business_events",
    "daily_sales_facts",
)

#: Dans l'ordre : chaque requête s'appuie sur les dates déjà recalées par les précédentes.
#: Une requête par chaîne, `UPDATE` en tête de ligne (test d'architecture des `SET`).
_RESTAMP_SQL = (
    # Ce qui précède la première vente.
    """
    UPDATE companies SET created_at = :opening, updated_at = :opening WHERE id = :co;
    """,
    """
    UPDATE users SET created_at = :opening, updated_at = :opening WHERE company_id = :co;
    """,
    """
    UPDATE roles SET created_at = :opening, updated_at = :opening WHERE company_id = :co;
    """,
    """
    UPDATE user_roles SET granted_at = :opening WHERE company_id = :co;
    """,
    """
    UPDATE categories SET created_at = :opening, updated_at = :opening WHERE company_id = :co;
    """,
    """
    UPDATE products SET created_at = :opening, updated_at = :opening WHERE company_id = :co;
    """,
    """
    UPDATE product_prices SET valid_from = :opening, created_at = :opening
    WHERE company_id = :co;
    """,
    """
    UPDATE customers SET created_at = :opening, updated_at = :opening WHERE company_id = :co;
    """,
    """
    UPDATE suppliers SET created_at = :opening, updated_at = :opening WHERE company_id = :co;
    """,
    """
    UPDATE expense_categories SET created_at = :opening WHERE company_id = :co;
    """,
    # Ventes : saisies, confirmées et (pour l'une) annulées à l'heure de la vente.
    """
    UPDATE sales SET created_at = sold_at, confirmed_at = sold_at,
        cancelled_at = CASE WHEN cancelled_at IS NULL THEN NULL ELSE sold_at + :delay END
    WHERE company_id = :co;
    """,
    """
    UPDATE sale_items si SET created_at = s.sold_at
    FROM sales s
    WHERE si.company_id = :co AND s.company_id = :co AND s.id = si.sale_id;
    """,
    # Paiements : l'encaissement de la confirmation à l'heure de la vente, la
    # contre-écriture à l'heure de l'annulation, le reste à son `paid_at`.
    """
    UPDATE payments p SET paid_at = s.sold_at
    FROM sales s
    WHERE p.company_id = :co AND s.company_id = :co AND s.id = p.sale_id
        AND p.reversal_of_payment_id IS NULL;
    """,
    """
    UPDATE payments r SET paid_at = s.cancelled_at
    FROM payments o, sales s
    WHERE r.company_id = :co AND o.company_id = :co AND s.company_id = :co
        AND o.id = r.reversal_of_payment_id AND s.id = o.sale_id;
    """,
    """
    UPDATE payments SET created_at = paid_at WHERE company_id = :co;
    """,
    """
    UPDATE payment_allocations a SET created_at = p.paid_at
    FROM payments p
    WHERE a.company_id = :co AND p.company_id = :co AND p.id = a.payment_id;
    """,
    # Dettes : ouvertes avec leur vente (ou à leur moment noté), soldées au dernier
    # règlement lettré.
    """
    UPDATE debts d SET created_at = s.sold_at
    FROM sales s
    WHERE d.company_id = :co AND s.company_id = :co AND s.id = d.sale_id;
    """,
    """
    UPDATE debts SET created_at = CAST(m.value AS timestamptz)
    FROM jsonb_each_text(CAST(:moments AS jsonb)) m
    WHERE company_id = :co AND id = CAST(m.key AS uuid);
    """,
    """
    UPDATE debts d SET
        closed_at = CASE
            WHEN d.closed_at IS NULL THEN NULL
            ELSE COALESCE(last.paid_at, d.created_at)
        END,
        updated_at = GREATEST(d.created_at, last.paid_at)
    FROM debts d2
    LEFT JOIN LATERAL (
        SELECT max(p.paid_at) AS paid_at
        FROM payment_allocations a
        JOIN payments p ON p.id = a.payment_id AND p.company_id = :co
        WHERE a.company_id = :co AND a.debt_id = d2.id
    ) last ON true
    WHERE d.company_id = :co AND d2.company_id = :co AND d2.id = d.id;
    """,
    """
    UPDATE sales s SET updated_at = GREATEST(s.sold_at, s.cancelled_at, d.updated_at)
    FROM sales s2
    LEFT JOIN debts d ON d.sale_id = s2.id AND d.company_id = :co
    WHERE s.company_id = :co AND s2.company_id = :co AND s2.id = s.id;
    """,
    # Stock : sortie à l'heure de la vente, retour d'une annulation à l'heure de
    # l'annulation, livraison à son heure notée, stock d'ouverture inchangé.
    """
    UPDATE inventory_movements m SET occurred_at = CASE
            WHEN m.type = 'customer_return_in' THEN COALESCE(s.cancelled_at, s.sold_at)
            ELSE s.sold_at
        END
    FROM sale_items si, sales s
    WHERE m.company_id = :co AND si.company_id = :co AND s.company_id = :co
        AND m.ref_type = 'sale_item' AND si.id = m.ref_id AND s.id = si.sale_id;
    """,
    """
    UPDATE inventory_movements SET occurred_at = CAST(m.value AS timestamptz)
    FROM jsonb_each_text(CAST(:moments AS jsonb)) m
    WHERE company_id = :co AND id = CAST(m.key AS uuid);
    """,
    """
    UPDATE inventory_movements SET created_at = occurred_at WHERE company_id = :co;
    """,
    """
    UPDATE product_stock ps SET recomputed_at = :opening, last_movement_at = (
        SELECT max(m.occurred_at) FROM inventory_movements m
        WHERE m.company_id = :co AND m.product_id = ps.product_id
    )
    WHERE ps.company_id = :co;
    """,
    # Dépenses : enregistrées à l'heure de leur paiement, sinon le jour de la dépense.
    """
    UPDATE expenses e SET created_at = COALESCE(
        (
            SELECT min(p.paid_at) FROM payments p
            WHERE p.company_id = :co AND p.expense_id = e.id
        ),
        CAST(e.spent_at AS timestamp) AT TIME ZONE 'UTC' + interval '9 hours'
    )
    WHERE e.company_id = :co;
    """,
    """
    UPDATE expenses SET updated_at = created_at WHERE company_id = :co;
    """,
    # Journal d'audit : l'heure de l'opération qu'il trace.
    """
    UPDATE audit_logs l SET occurred_at = s.sold_at
    FROM sales s
    WHERE l.company_id = :co AND s.company_id = :co
        AND l.entity_table = 'sales' AND l.action = 'confirm' AND s.id = l.entity_id;
    """,
    """
    UPDATE audit_logs l SET occurred_at = s.cancelled_at
    FROM sales s
    WHERE l.company_id = :co AND s.company_id = :co
        AND l.entity_table = 'sales' AND l.action = 'cancel' AND s.id = l.entity_id;
    """,
    """
    UPDATE audit_logs l SET occurred_at = p.paid_at
    FROM payments p
    WHERE l.company_id = :co AND p.company_id = :co
        AND l.entity_table = 'payments' AND l.action = 'insert' AND p.id = l.entity_id;
    """,
    """
    UPDATE audit_logs l SET occurred_at = r.paid_at
    FROM payments r
    WHERE l.company_id = :co AND r.company_id = :co
        AND l.entity_table = 'payments' AND l.action = 'cancel'
        AND r.reversal_of_payment_id IS NOT NULL
        AND l.entity_id IN (r.id, r.reversal_of_payment_id);
    """,
    """
    UPDATE audit_logs l SET occurred_at = d.created_at
    FROM debts d
    WHERE l.company_id = :co AND d.company_id = :co
        AND l.entity_table = 'debts' AND d.id = l.entity_id;
    """,
    """
    UPDATE audit_logs l SET occurred_at = e.created_at
    FROM expenses e
    WHERE l.company_id = :co AND e.company_id = :co
        AND l.entity_table = 'expenses' AND e.id = l.entity_id;
    """,
    """
    UPDATE audit_logs SET occurred_at = :opening
    WHERE company_id = :co
        AND entity_table IN ('product_prices', 'users', 'user_roles', 'roles', 'companies');
    """,
    # Outbox : l'heure de l'événement qu'elle porte.
    """
    UPDATE business_events b SET occurred_at = s.sold_at
    FROM sales s
    WHERE b.company_id = :co AND s.company_id = :co
        AND b.event_type = 'sale.confirmed' AND s.id = b.aggregate_id;
    """,
    """
    UPDATE business_events b SET occurred_at = s.cancelled_at
    FROM sales s
    WHERE b.company_id = :co AND s.company_id = :co
        AND b.event_type = 'sale.cancelled' AND s.id = b.aggregate_id;
    """,
    """
    UPDATE business_events b SET occurred_at = p.paid_at
    FROM payments p
    WHERE b.company_id = :co AND p.company_id = :co
        AND b.event_type = 'payment.received' AND p.id = b.aggregate_id;
    """,
    """
    UPDATE business_events b SET occurred_at = r.paid_at
    FROM payments r
    WHERE b.company_id = :co AND r.company_id = :co
        AND b.event_type = 'payment.cancelled'
        AND r.id = CAST(b.payload ->> 'cancellation_id' AS uuid);
    """,
    """
    UPDATE business_events b SET occurred_at = d.created_at
    FROM debts d
    WHERE b.company_id = :co AND d.company_id = :co
        AND b.event_type = 'debt.created' AND d.id = b.aggregate_id;
    """,
    """
    UPDATE business_events b SET occurred_at = d.closed_at,
        payload = jsonb_set(b.payload, '{closed_at}', to_jsonb(d.closed_at))
    FROM debts d
    WHERE b.company_id = :co AND d.company_id = :co
        AND b.event_type = 'debt.settled' AND d.id = b.aggregate_id;
    """,
    """
    UPDATE business_events b SET occurred_at = e.created_at
    FROM expenses e
    WHERE b.company_id = :co AND e.company_id = :co
        AND b.event_type = 'expense.created' AND e.id = b.aggregate_id;
    """,
    """
    UPDATE business_events b SET occurred_at = m.occurred_at
    FROM inventory_movements m
    WHERE b.company_id = :co AND m.company_id = :co
        AND b.event_type = 'stock.updated'
        AND m.id = CAST(b.payload ->> 'movement_id' AS uuid);
    """,
    # Le seed construit lui-même les faits (`_rebuild_facts`) et la comparaison tourne sans
    # relais : sans ceci, l'outbox attendrait depuis des jours et l'accueil afficherait le
    # bandeau de retard (ADR 0061), absent de la maquette. Publié à l'heure de l'événement.
    """
    UPDATE business_events SET published_at = occurred_at
    WHERE company_id = :co AND published_at IS NULL;
    """,
    # Faits analytiques : construits au moment de la capture.
    """
    UPDATE daily_sales_facts SET built_at = :frozen WHERE company_id = :co;
    """,
)


def restamp(engine: Engine, company_id: UUID, moments: dict[UUID, datetime]) -> None:
    """Recale sur l'heure de leur opération les dates que le serveur a posées pendant le
    remplissage, pour la seule entreprise `company_id` (ADR 0065).

    Le serveur date lui-même l'encaissement d'une confirmation, une sortie de stock, une
    dette, une ligne d'audit… à l'heure du remplissage, le 7 octobre ou plus tard : la
    caisse du 6 octobre en serait vide. Chaque ligne reprend ici l'heure de sa vente, de
    sa livraison, de son annulation, sans jamais dépasser `FROZEN_NOW`.

    Ce n'est pas un chemin de l'application : il s'exécute sous le **rôle propriétaire**,
    dans une seule transaction ouverte par `tenant_transaction` (la RLS FORCE s'applique au
    propriétaire aussi), chaque requête filtrée sur `company_id`. Les triggers
    utilisateur des tables touchées sont coupés puis rétablis dans cette transaction.
    """
    params = {
        "co": company_id,
        "opening": OPENING,
        "frozen": FROZEN_NOW,
        "delay": CANCEL_DELAY,
        "moments": json.dumps({str(key): value.isoformat() for key, value in moments.items()}),
    }
    owner = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx, session_factory=owner) as session:
        for table in RESTAMPED_TABLES:
            session.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        for statement in _RESTAMP_SQL:
            session.execute(text(statement), params)
        for table in RESTAMPED_TABLES:
            session.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed_maquette",
        description="Données de la maquette v2 (Alimentation Keur Fatou, 6 octobre 2026).",
    )
    parser.add_argument("--slug", default=SLUG, help=f"Slug de l'entreprise (défaut : {SLUG})")
    parser.add_argument("--password", default=PASSWORD, help="Mot de passe des comptes")
    args = parser.parse_args(argv)
    company_id = seed(slug=args.slug, password=args.password)
    print(f"Entreprise de la maquette créée : {company_id}")
    print(f"  slug     : {args.slug}")
    print(f"  gérante  : gerant@{args.slug}.example.com")
    print(f"  heure    : COGES_FROZEN_NOW={FROZEN_NOW.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
