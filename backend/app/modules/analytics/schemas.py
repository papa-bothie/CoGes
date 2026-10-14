"""Schémas du module Analytics.

Tous les montants sont **hors taxe** et sérialisés en chaînes : une marge n'est pas
un flottant. `tax_total` reste isolé — une taxe collectée n'a jamais été un revenu
(§ 4.10).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.money import Amount, Quantity
from app.modules.inventory.schemas import MovementType, StockReason

#: Longueur maximale d'une plage d'analyse, en jours. Aucun texte ne la fixe ;
#: la borne existe pour qu'une plage saisie de travers ne balaye pas dix ans de
#: lignes de vente dans la transaction d'une requête HTTP.
MAX_PERIOD_DAYS = 366

#: Longueur de la série journalière rendue, en jours (fin de période comprise).
DAILY_SERIES_DAYS = 30


class DailyCashPoint(BaseModel):
    """Un jour de caisse, dans le fuseau de l'entreprise."""

    model_config = ConfigDict(extra="forbid")

    day: date
    cash_in: Amount
    cash_out: Amount
    net_cash: Amount


class FinanceOverview(BaseModel):
    """« Où en est mon argent ? » — la réponse de la V1, en un écran.

    Trois familles de chiffres, qui ne se confondent pas :

    * la **trésorerie** — ce qui est entré et sorti, compensations exclues ;
    * le **résultat** — ce qui a été vendu et ce que cela a coûté, qu'il soit
      encaissé ou non ;
    * les **encours** — ce qui reste dû, dans les deux sens, à l'instant présent.
    """

    model_config = ConfigDict(extra="forbid")

    period_from: date
    period_to: date

    # Trésorerie de la période (méthode `offset` exclue).
    cash_in: Amount
    cash_out: Amount
    net_cash: Amount

    # Résultat de la période, hors taxe.
    net_revenue: Amount
    cogs_net: Amount
    gross_margin: Amount
    expenses_total: Amount
    fixed_expenses: Amount
    variable_expenses: Amount
    estimated_result: Amount

    # Détail du revenu, pour qui veut vérifier la soustraction.
    gross_revenue: Amount
    discount_total: Amount
    refund_net_amount: Amount
    tax_total: Amount
    cogs_gross: Amount
    cogs_returned: Amount
    sale_count: int

    # Encours à l'instant présent, sans bornes de période.
    receivables_open: Amount
    payables_open: Amount

    daily: list[DailyCashPoint]


# --------------------------------------------------------- classements par métrique


class ProductMetric(StrEnum):
    """Les huit métriques du Diagramme 7, **jamais équivalentes**.

    Un « produit à forte valeur » n'existe pas comme mesure unique. Chaque classement
    porte donc le nom de sa métrique, et aucune n'est fusionnée avec une autre dans un
    score opaque (décision 12).
    """

    REVENUE = "revenue"
    MARGIN = "margin"
    QUANTITY = "quantity"
    FREQUENCY = "frequency"
    ROTATION = "rotation"
    VELOCITY = "velocity"
    DEMAND_TREND = "demand_trend"
    FUTURE_POTENTIAL = "future_potential"


#: Libellé affiché et unité de chaque métrique. Le libellé est la phrase que le § 7
#: de l'Architecture attend à l'écran ; l'unité empêche de lire des unités par jour
#: comme des francs.
METRIC_LABELS: dict[ProductMetric, tuple[str, str]] = {
    ProductMetric.REVENUE: ("Ventes générées", "XOF"),
    ProductMetric.MARGIN: ("Gagné sur les ventes", "XOF"),
    ProductMetric.QUANTITY: ("Quantité vendue", "unité"),
    ProductMetric.FREQUENCY: ("Fréquence de vente", "vente"),
    ProductMetric.ROTATION: ("Rotation du stock", "fois"),
    ProductMetric.VELOCITY: ("Vélocité des ventes", "unité/jour"),
    ProductMetric.DEMAND_TREND: ("Évolution de la demande", "%"),
    ProductMetric.FUTURE_POTENTIAL: ("Potentiel futur estimé", "unité"),
}

#: Longueur maximale d'un classement. Dix lignes suffisent à décider ; cent lignes
#: sont un export, et un export est une autre route.
MAX_RANKING_LIMIT = 50


class ProductRankRow(BaseModel):
    """Un produit et **sa** valeur pour la métrique demandée."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    product_name: str
    #: Chaîne, comme tout nombre décimal du projet. La précision dépend de la
    #: métrique : deux décimales pour un montant, trois pour une quantité.
    value: str
    #: Métrique 8 seulement : intervalle et modèle qui ont produit la valeur
    #: (décision 13). Absents des sept métriques observées, qui n'estiment rien.
    lower: str | None = None
    upper: str | None = None
    model_name: str | None = None
    model_version: str | None = None


class ProductRanking(BaseModel):
    """Classement pour **une seule** métrique, qui se nomme dans la réponse."""

    model_config = ConfigDict(extra="forbid")

    metric: ProductMetric
    metric_label: str
    unit: str
    period_from: date
    period_to: date
    #: Renseigné quand la métrique n'est pas encore calculable ; `items` est alors
    #: vide. « Données insuffisantes » plutôt qu'une valeur inventée (décision 13).
    unavailable_reason: str | None = None
    #: Métrique 8 seulement : date de production de la prévision — jamais « en
    #: direct » — et horizon couvert à partir de `forecast_as_of`.
    computed_at: datetime | None = None
    forecast_as_of: date | None = None
    horizon_days: int | None = None
    items: list[ProductRankRow]


class TimeseriesMeasure(StrEnum):
    """Les deux séries que la V1 sait tracer."""

    REVENUE = "revenue"
    MARGIN = "margin"


#: Libellé affiché de chaque série (mots simples, phase 15).
SERIES_LABELS: dict[TimeseriesMeasure, str] = {
    TimeseriesMeasure.REVENUE: "Vendu",
    TimeseriesMeasure.MARGIN: "Gagné sur les ventes",
}


class TimeseriesPoint(BaseModel):
    """Un jour de la série, dans le fuseau de l'entreprise."""

    model_config = ConfigDict(extra="forbid")

    day: date
    value: Amount


class Timeseries(BaseModel):
    """Série journalière d'une mesure nommée, jours creux à zéro.

    Les jours sans vente valent zéro et ne sont jamais omis : une courbe trouée se lit
    comme une absence de données, pas comme une caisse immobile.
    """

    model_config = ConfigDict(extra="forbid")

    measure: TimeseriesMeasure
    measure_label: str
    period_from: date
    period_to: date
    points: list[TimeseriesPoint]


class ProductHistoryItem(BaseModel):
    """Un mouvement de l'article, avec de quoi l'écrire en phrase (écran 08, ADR 0071)."""

    model_config = ConfigDict(extra="forbid")

    movement_id: UUID
    occurred_at: datetime
    type: MovementType
    reason_code: StockReason | None
    qty_delta: Quantity
    #: Client de la vente ou du retour, fournisseur de la livraison ; `None` sinon.
    counterparty: str | None
    #: Annulation d'un autre mouvement (ADR 0017).
    is_reversal: bool


class ProductHistory(BaseModel):
    """« Ce qui s'est passé » et « Vendu ce mois » d'un article."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    #: Vendu depuis le 1er du mois, retours et annulations déduits.
    month_sold_qty: Quantity
    #: Jours écoulés du mois, aujourd'hui compris (« Environ 1 sac par jour »).
    month_days: int
    items: list[ProductHistoryItem]


# ------------------------------------------- clients et fournisseurs (écrans 13 à 16)

#: Taille par défaut des listes de personnes et de leurs historiques (ADR 0072).
PEOPLE_PAGE_SIZE = 50
#: Articles nommés sur une ligne d'achat ou de livraison, et sur la fiche fournisseur.
NAMED_ITEMS = 3
SUPPLIER_NAMED_PRODUCTS = 4


class PersonRow(BaseModel):
    """Un client ou un fournisseur dans la liste de l'écran 13.

    `owed` est `null` pour qui n'a pas le droit de lire les dettes (un vendeur) : il voit
    les personnes, jamais l'argent qu'elles doivent.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    phone: str | None
    #: Client : ce qu'il vous doit ; fournisseur : ce que vous lui devez.
    owed: Amount | None
    #: La plus ancienne dette encore ouverte (« Depuis 12 jours »).
    owed_since: datetime | None
    #: L'échéance ouverte la plus proche (« Avant le 10 octobre »).
    due_date: date | None
    #: Client : sa dernière vente confirmée ; fournisseur : sa dernière livraison.
    last_seen_at: datetime | None


class PeoplePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PersonRow]
    page: int
    page_size: int
    total: int
    #: Combien doivent (ou à combien on doit), et combien en tout ; `null` sans le droit.
    owing_count: int | None
    owed_total: Amount | None
    #: Les deux compteurs du sélecteur « Clients (15) · Fournisseurs (5) ».
    customer_count: int
    supplier_count: int


class CustomerSheet(BaseModel):
    """Les tuiles de la fiche client (écran 14)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    phone: str | None
    created_at: datetime
    owed: Amount | None
    owed_since: datetime | None
    #: Ventes confirmées depuis le 1er du mois, dans le fuseau de l'entreprise.
    month_total: Amount
    month_visits: int
    last_visit_at: datetime | None


class CustomerSaleRow(BaseModel):
    """Un achat du client : la vente, ses premiers articles et ce qu'il en reste dû."""

    model_config = ConfigDict(extra="forbid")

    sale_id: UUID
    sale_no: str
    sold_at: datetime
    status: Literal["confirmed", "cancelled"]
    total: Amount
    balance: Amount
    debt_status: Literal["open", "partially_paid", "paid", "written_off"] | None
    has_returns: bool
    returned_total: Amount
    #: Les trois premiers articles, dans l'ordre de saisie, et le nombre de lignes.
    item_names: list[str]
    item_count: int


class CustomerSalePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CustomerSaleRow]
    page: int
    page_size: int
    total: int


class PersonPaymentRow(BaseModel):
    """Un versement d'un client, ou à un fournisseur, et ce qu'il paie."""

    model_config = ConfigDict(extra="forbid")

    payment_id: UUID
    paid_at: datetime
    amount: Amount
    method: str
    #: Client : vrai si le versement règle une dette, faux s'il est payé à la vente.
    on_debt: bool
    #: La vente payée (client), directement ou par sa dette.
    sale_id: UUID | None
    sale_no: str | None
    #: La dette réglée et sa date (fournisseur : « Livraison du 3 oct. »).
    debt_id: UUID | None
    debt_created_at: datetime | None


class PersonPaymentPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PersonPaymentRow]
    page: int
    page_size: int
    total: int


class SupplierSheet(BaseModel):
    """Les tuiles de la fiche fournisseur (écran 16)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    phone: str | None
    address: str | None
    created_at: datetime
    owed: Amount | None
    due_date: date | None
    #: Livré depuis le 1er du mois (montant `null` sans le droit de lire les dettes).
    month_total: Amount | None
    month_deliveries: int
    #: Ce qu'il livre : quatre articles nommés, et combien en tout.
    product_names: list[str]
    product_count: int


class DeliveryLineRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    name: str
    qty: Quantity
    unit: str


class SupplierDeliveryRow(BaseModel):
    """Une livraison (une dette fournisseur) et ses principaux articles."""

    model_config = ConfigDict(extra="forbid")

    debt_id: UUID
    created_at: datetime
    total: Amount
    balance: Amount
    status: Literal["open", "partially_paid", "paid", "written_off"]
    due_date: date | None
    #: Les trois plus grosses lignes ; une dette saisie à la main n'en a aucune.
    lines: list[DeliveryLineRow]
    line_count: int


class SupplierDeliveryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SupplierDeliveryRow]
    page: int
    page_size: int
    total: int
