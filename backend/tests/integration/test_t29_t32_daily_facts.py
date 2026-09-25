"""T29 à T32 — reconstruction de `daily_sales_facts`.

Les quatre tests portent sur la requête du § 6.1, exécutée par
`DailySalesFactRepository.rebuild_days`. Aucun ne passe par l'API : ce qui est
éprouvé, c'est le SQL qui construit les agrégats.

**T29** est le test qui échouait en V1. La cause était structurelle : joindre
`sale_items` à `sale_return_items` directement produit autant de lignes que la ligne
de vente a reçu de retours, donc autant de fois la quantité vendue, le chiffre
d'affaires, la remise et le coût — et autant de fois le même `sale_id` dans le
comptage des tickets. La correction est la CTE `retours`, pré-agrégée par
`sale_item_id` **avant** toute jointure.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import tenant_transaction
from app.modules.analytics import service as analytics_service
from app.modules.analytics.repository import DailySalesFactRepository
from app.modules.sales import service as sales_service
from tests.integration import facts_harness as facts
from tests.integration import sales_harness as sales
from tests.tenancy.harness import Tenant

pytestmark = pytest.mark.integration

#: Mesures que les retours ne doivent **pas** changer. C'est l'énoncé de T29.
UNAFFECTED_BY_RETURNS = ("qty_sold", "gross_revenue", "discount_total", "cogs_gross", "sale_count")

TOLERANCE = Decimal("0.01")


def _rebuild(analytics_factory: sessionmaker[Any], tenant: Tenant, days: list[dt.date]) -> None:
    """Reconstruit dans une transaction à part, **en `coges_analytics`**.

    Le rôle importe : la purge des faits devenus vides est un `DELETE`, que
    `coges_app` n'a le droit de faire nulle part (T36). Lancer la reconstruction sous
    le rôle applicatif ferait échouer T31 pour une raison qui n'existe pas en
    production.
    """
    with tenant_transaction(tenant.ctx, session_factory=analytics_factory) as session:
        DailySalesFactRepository(session, tenant.ctx).rebuild_days(days)


def _today(session_factory: sessionmaker[Any], tenant: Tenant) -> dt.date:
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        return analytics_service.today_in_company(session, tenant.ctx)


def test_t29_three_partial_returns_do_not_inflate_the_fact(
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """T29 — une ligne retournée trois fois pèse autant qu'une ligne jamais retournée.

    Deux produits, deux ventes identiques. L'une reçoit trois retours partiels de 3,
    4 puis 2 unités sur dix vendues ; l'autre n'en reçoit aucun. Les cinq mesures qui
    décrivent la **vente** doivent être rigoureusement égales.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        with_returns = facts.extra_product(session, tenant_a, "T29-AVEC")
        without_returns = facts.extra_product(session, tenant_a, "T29-SANS")

        sale_id, item_id = facts.sold_line(
            session, tenant_a, with_returns, qty="10", discount="250"
        )
        for qty in ("3", "4", "2"):
            facts.returned(session, tenant_a, sale_id, item_id, qty=qty)

        facts.sold_line(session, tenant_a, without_returns, qty="10", discount="250")

    day = _today(session_factory, tenant_a)
    _rebuild(analytics_session_factory, tenant_a, [day])

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        affected = facts.read_fact(session, tenant_a, day, with_returns)
        untouched = facts.read_fact(session, tenant_a, day, without_returns)

    assert affected is not None and untouched is not None
    for measure in UNAFFECTED_BY_RETURNS:
        assert getattr(affected, measure) == getattr(untouched, measure), (
            f"{measure} gonflé par les retours : {getattr(affected, measure)} "
            f"au lieu de {getattr(untouched, measure)}"
        )

    # Et le test n'est pas vide : les retours ont bien été comptés, ailleurs.
    assert affected.returned_qty == Decimal("9.000")
    assert untouched.returned_qty == Decimal("0.000")
    assert affected.net_qty_sold == Decimal("1.000")
    assert affected.refund_net_amount == Decimal("9000.00")
    # `sale_count` compte des **tickets** : une vente, quels que soient ses retours.
    assert affected.sale_count == 1


def test_t30_rebuilding_the_same_range_twice_is_idempotent(
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """T30 — rejouer la même plage donne exactement le même résultat."""
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = facts.extra_product(session, tenant_a, "T30")
        sale_id, item_id = facts.sold_line(session, tenant_a, product_id, qty="6")
        facts.returned(session, tenant_a, sale_id, item_id, qty="2")
        facts.sold_line(session, tenant_a, product_id, qty="4")

    day = _today(session_factory, tenant_a)
    _rebuild(analytics_session_factory, tenant_a, [day])
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        first = facts.read_day(session, tenant_a, day)

    _rebuild(analytics_session_factory, tenant_a, [day])
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        second = facts.read_day(session, tenant_a, day)

    assert first == second, "la reconstruction n'est pas idempotente"
    assert len(second) == len({row.product_id for row in second}), "lignes dupliquées"


def test_t31_cancelling_a_sale_purges_its_fact(
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """T31 — une vente annulée après construction ne laisse aucun fait fantôme.

    C'est le `DELETE` de purge du § 6.1 qui s'en charge. Sans lui, la ligne resterait
    avec ses anciens chiffres : un chiffre d'affaires que plus aucune vente ne porte.
    """
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = facts.extra_product(session, tenant_a, "T31")
        sale_id, _ = facts.sold_line(session, tenant_a, product_id, qty="5")

    day = _today(session_factory, tenant_a)
    _rebuild(analytics_session_factory, tenant_a, [day])
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        built = facts.read_fact(session, tenant_a, day, product_id)
    assert built is not None, "le fait n'a pas été construit : le test ne prouve rien"

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        sales.cancel(session, tenant_a, sale_id)

    _rebuild(analytics_session_factory, tenant_a, [day])
    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        purged = facts.read_fact(session, tenant_a, day, product_id)

    assert purged is None, "fait fantôme : la vente annulée pèse encore sur la journée"


def test_t32_aggregates_match_the_direct_computation_over_ninety_days(
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    tenant_a: Tenant,
) -> None:
    """T32 — égalité à 0,01 près entre les agrégats et le calcul transactionnel.

    Le § 12.1 point 3 le dit sans détour : un événement manquant produit un agrégat
    silencieusement faux, et aucune contrainte SQL ne peut le détecter. Ce test est la
    seule chose qui puisse — et il est rejoué chaque semaine par
    `reconcile.check_revenue`.

    Les deux sources somment les mêmes valeurs arrondies **à la ligne** (ADR 0034) :
    l'écart attendu est donc nul, et la tolérance ne sert qu'à ne pas échouer sur un
    arrondi.
    """
    today = _today(session_factory, tenant_a)
    window = [today - dt.timedelta(days=offset) for offset in range(90)]

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        product_id = facts.extra_product(session, tenant_a, "T32")
        # Une vente tous les trois jours, et un retour tardif sur la plus ancienne :
        # c'est le cas qui fait diverger un agrégat seulement incrémental.
        oldest: tuple[Any, Any] | None = None
        for offset in range(0, 90, 3):
            sold_at = dt.datetime.combine(
                today - dt.timedelta(days=offset), dt.time(12, 0), tzinfo=dt.UTC
            )
            sale_id, item_id = facts.sold_line(
                session,
                tenant_a,
                product_id,
                qty=str(2 + offset % 5),
                unit_price="1250",
                unit_cost="812.5",
                discount="75",
                sold_at=sold_at,
            )
            oldest = (sale_id, item_id)
        assert oldest is not None
        facts.returned(session, tenant_a, oldest[0], oldest[1], qty="1", unit_price="1250")

    _rebuild(analytics_session_factory, tenant_a, window)

    with tenant_transaction(tenant_a.ctx, session_factory=session_factory) as session:
        aggregated = DailySalesFactRepository(session, tenant_a.ctx).period_totals(
            period_from=window[-1], period_to=today
        )
        start, end = analytics_service.period_bounds(
            session, tenant_a.ctx, period_from=window[-1], period_to=today
        )
        direct = sales_service.revenue_totals(
            session, tenant_a.ctx, period_from=start, period_to=end
        )

    assert aggregated["net_revenue"] > 0, "aucune vente agrégée : le test ne prouve rien"
    for measure in (
        "gross_revenue",
        "discount_total",
        "tax_total",
        "refund_net_amount",
        "net_revenue",
        "cogs_gross",
        "cogs_returned",
        "cogs_net",
    ):
        gap = abs(aggregated[measure] - direct[measure])
        assert gap <= TOLERANCE, (
            f"{measure} : agrégats {aggregated[measure]} contre direct "
            f"{direct[measure]} (écart {gap})"
        )
