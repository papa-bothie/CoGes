"""La démo montre chaque état de l'interface (phase 15, « Démo »).

`make seed-demo` doit faire apparaître, sur 90 jours : un jour en perte, un client soldé,
trois articles sous le seuil et deux dettes fournisseurs à échéance proche. Ce test sème
une démo neuve (une bonne minute), reconstruit ses agrégats comme le worker, puis lit
chaque état dans le seul contexte de l'entreprise.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import TenantContext, tenant_transaction
from app.seed import DAYS, seed
from tests.conftest import TEST_PASSWORD
from tests.helpers.invariants import assert_consistent
from tests.integration import facts_harness as facts

pytestmark = pytest.mark.integration

#: Jour par jour : gagné sur les ventes moins les dépenses du jour.
_LOSS_DAYS = text(
    """
    WITH gained AS (
        SELECT day, sum(net_revenue - cogs_net) AS amount FROM daily_sales_facts
        WHERE company_id = :co GROUP BY day
    ), spent AS (
        SELECT spent_at AS day, sum(amount) AS amount FROM expenses
        WHERE company_id = :co AND deleted_at IS NULL GROUP BY spent_at
    )
    SELECT count(*) FROM gained g LEFT JOIN spent s USING (day)
    WHERE g.amount - coalesce(s.amount, 0) < 0
    """
)
#: Clients qui ont eu des dettes et n'en ont plus aucune ouverte.
_SETTLED_CUSTOMERS = text(
    """
    SELECT count(DISTINCT d.customer_id) FROM debts d
    WHERE d.company_id = :co AND d.party_type = 'customer' AND d.status = 'paid'
      AND NOT EXISTS (
        SELECT 1 FROM debts o WHERE o.company_id = :co
          AND o.customer_id = d.customer_id AND o.status = 'open')
    """
)
#: Articles en stock, mais pas plus que leur seuil.
_UNDER_THRESHOLD = text(
    """
    SELECT count(*) FROM product_stock s
    JOIN products p ON p.company_id = s.company_id AND p.id = s.product_id
    WHERE s.company_id = :co AND p.reorder_point IS NOT NULL
      AND s.qty_on_hand > 0 AND s.qty_on_hand <= p.reorder_point
    """
)
#: Dettes fournisseurs ouvertes, dues dans les sept jours.
_SUPPLIER_DUE_SOON = text(
    """
    SELECT count(*) FROM debts
    WHERE company_id = :co AND party_type = 'supplier' AND status = 'open'
      AND due_date BETWEEN :today AND :today + 7
    """
)


def test_the_demo_shows_every_state(
    app_bound_to_test_database: None,
    session_factory: sessionmaker[Any],
    analytics_session_factory: sessionmaker[Any],
    owner_engine: Engine,
) -> None:
    company_id: UUID = seed(f"demo-{uuid4().hex[:8]}", password=TEST_PASSWORD)
    today = facts.today_in_company(session_factory, company_id)
    facts.rebuild(
        analytics_session_factory,
        company_id,
        [today - timedelta(days=offset) for offset in range(DAYS + 1)],
    )

    ctx = TenantContext.bootstrap(company_id)
    params = {"co": company_id, "today": today}
    with tenant_transaction(ctx, session_factory=session_factory) as session:
        counts = {
            name: int(session.execute(query, params).scalar_one())
            for name, query in (
                ("jours en perte", _LOSS_DAYS),
                ("clients soldés", _SETTLED_CUSTOMERS),
                ("articles sous le seuil", _UNDER_THRESHOLD),
                ("dettes fournisseurs dues sous 7 jours", _SUPPLIER_DUE_SOON),
            )
        }

    assert counts["jours en perte"] >= 1, counts
    assert counts["clients soldés"] >= 1, counts
    assert counts["articles sous le seuil"] >= 3, counts
    assert counts["dettes fournisseurs dues sous 7 jours"] >= 2, counts
    # Trois mois d'activité semée : stock, ventes, dettes et lettrages se recoupent (C5).
    assert_consistent(owner_engine, company_id)
