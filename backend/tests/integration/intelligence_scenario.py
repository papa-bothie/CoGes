"""Boutique type des tests d'Intelligence : trois produits, trois destins.

* **Régulier** — une vente par jour depuis 60 jours, 20 unités en stock : assez
  d'historique pour une prévision, trop peu de stock pour tenir une semaine.
* **Rare** — deux ventes : sous le seuil d'historique, « données insuffisantes ».
* **Dormant** — six ventes à l'unité étalées sur 60 jours et 400 unités en stock :
  suffisant pour une prévision, classe C du chiffre d'affaires, couverture énorme.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from tests.integration import intelligence_harness as ih

DORMANT_OFFSETS = (2, 12, 23, 34, 45, 56)


@dataclass(frozen=True)
class Boutique:
    shop: ih.Shop
    as_of: dt.date
    steady: UUID
    rare: UUID
    dormant: UUID


def build(app_factory: sessionmaker[Any], prefix: str) -> Boutique:
    shop = ih.new_shop(prefix)
    as_of = ih.today()
    with ih.write(app_factory, shop) as session:
        steady = ih.add_product(session, shop, "Riz parfumé 5 kg")
        rare = ih.add_product(session, shop, "Théière émaillée")
        dormant = ih.add_product(session, shop, "Parapluie")
        ih.sell_daily(session, shop, steady, until=as_of, days=60)
        ih.sell(session, shop, rare, day=as_of - dt.timedelta(days=3), qty="1")
        ih.sell(session, shop, rare, day=as_of - dt.timedelta(days=9), qty="1")
        for offset in DORMANT_OFFSETS:
            ih.sell(session, shop, dormant, day=as_of - dt.timedelta(days=offset), qty="1")
        ih.stock_in(session, shop, steady, "20")
        ih.stock_in(session, shop, rare, "5")
        ih.stock_in(session, shop, dormant, "400")
    return Boutique(shop=shop, as_of=as_of, steady=steady, rare=rare, dormant=dormant)
