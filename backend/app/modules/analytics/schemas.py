"""Schémas du module Analytics.

Tous les montants sont **hors taxe** et sérialisés en chaînes : une marge n'est pas
un flottant. `tax_total` reste isolé — une taxe collectée n'a jamais été un revenu
(§ 4.10).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.core.money import Amount

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
