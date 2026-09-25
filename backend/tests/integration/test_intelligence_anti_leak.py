"""Anti-fuite temporelle (§ 6.2) : une feature à `as_of = D` ignore tout ce qui suit D.

Le piège exact que décrit le Modèle : `daily_sales_facts` est **réécrite** quand un
retour arrive plus tard. Une feature reconstruite depuis elle utiliserait un chiffre
inconnu à D. Ici, un retour et une annulation sont enregistrés **après** D : la
photographie de D doit être identique à celle d'un jumeau qui ne les a jamais vus.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

from tests.integration import intelligence_harness as ih

pytestmark = pytest.mark.integration

SNAPSHOT = "SELECT features FROM ml_feature_snapshots WHERE product_id = :p AND as_of = :d"


def _history(app_factory: sessionmaker[Any], prefix: str) -> tuple[ih.Shop, Any, list[Any]]:
    """Même historique dans chaque boutique : une vente par jour sur 40 jours."""
    shop = ih.new_shop(prefix)
    as_of = ih.today()
    sold: list[Any] = []
    with ih.write(app_factory, shop) as session:
        product = ih.add_product(session, shop, "Savon")
        for offset in range(40):
            day = as_of - dt.timedelta(days=offset)
            sold.append(ih.sell(session, shop, product, day=day, qty="4"))
    return shop, product, sold


def test_a_return_and_a_cancellation_recorded_after_d_do_not_leak_into_d(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    d = ih.today() - dt.timedelta(days=10)
    witness, witness_product, _ = _history(session_factory, "leak-witness")
    shop, product, sold = _history(session_factory, "leak")

    # Vente du jour D-3 : retournée et vente de D-2 : annulée — mais **aujourd'hui**,
    # c'est-à-dire dix jours après D. À D, ni l'une ni l'autre n'était connue.
    returned_sale, returned_item = sold[13]
    cancelled_sale, _ = sold[12]
    with ih.write(session_factory, shop) as session:
        ih.give_back(session, shop, returned_sale, returned_item, "3")
        ih.cancel(session, shop, cancelled_sale)

    ih.features(analytics_session_factory, witness, as_of=d)
    ih.features(analytics_session_factory, shop, as_of=d)

    seen = ih.rows(analytics_session_factory, shop, SNAPSHOT, p=product, d=d)[0].features
    expected = ih.rows(analytics_session_factory, witness, SNAPSHOT, p=witness_product, d=d)[
        0
    ].features
    assert seen["qty_7d"] == expected["qty_7d"] == "28.000"
    assert seen["qty_28d"] == expected["qty_28d"]
    assert seen["revenue_28d"] == expected["revenue_28d"]
    assert seen["margin_28d"] == expected["margin_28d"]

    # Et ce qui est connu **aujourd'hui** en tient bien compte : le test n'est pas
    # vert parce que le retour et l'annulation n'ont rien fait.
    ih.features(analytics_session_factory, shop, as_of=ih.today())
    now = ih.rows(analytics_session_factory, shop, SNAPSHOT, p=product, d=ih.today())[0].features
    assert now["qty_28d"] == "105.000"  # 28 × 4 − 3 rendus − 4 annulés


def test_a_snapshot_is_never_rewritten_with_later_knowledge(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
) -> None:
    """La photographie de D est prise une fois ; un retour ultérieur ne la corrige pas."""
    d = ih.today() - dt.timedelta(days=1)
    shop, product, sold = _history(session_factory, "leak-once")
    ih.features(analytics_session_factory, shop, as_of=d)
    before = ih.rows(analytics_session_factory, shop, SNAPSHOT, p=product, d=d)[0].features

    sale_id, item_id = sold[1]
    with ih.write(session_factory, shop) as session:
        ih.give_back(session, shop, sale_id, item_id, "4")
    run = ih.features(analytics_session_factory, shop, as_of=d)

    after = ih.rows(analytics_session_factory, shop, SNAPSHOT, p=product, d=d)[0].features
    assert run is not None and run.written == 0
    assert after == before
