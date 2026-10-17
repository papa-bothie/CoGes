"""Contrôles croisés des chiffres d'une entreprise (lot C, C5 ; ADR 0086).

Appelés en fin des tests d'intégration critiques (échec au COMMIT, concurrence) et sur
le jeu de démonstration :

  uv run --directory backend python -m tests.helpers.invariants demo

Chaque contrôle rend la liste de ses violations (vide = cohérent) :

* stock projeté = somme des mouvements, jamais négatif ;
* total d'une vente = somme de ses lignes (sous-total, remises, taxes, total) ;
* vente confirmée : payé + reste de sa dette vivante = total ; payé ≤ total ;
* dette : 0 ≤ payé ≤ principal, « payée » ⇔ solde nul, « ouverte » ⇔ solde positif ;
* aucun paiement plus lettré que son montant.

Lu par le propriétaire **sous le contexte** de l'entreprise : la RLS (FORCE) s'applique,
une seule entreprise est lue, toutes ses tables sont visibles.
"""

from __future__ import annotations

import os
import sys
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

CHECKS: dict[str, str] = {
    "stock = somme des mouvements": """
        SELECT s.product_id::text FROM product_stock s
        LEFT JOIN (SELECT product_id, sum(qty_delta) AS total FROM inventory_movements
                   GROUP BY product_id) m ON m.product_id = s.product_id
        WHERE s.qty_on_hand <> coalesce(m.total, 0)
    """,
    "stock jamais négatif": "SELECT product_id::text FROM product_stock WHERE qty_on_hand < 0",
    "total de la vente = ses lignes": """
        SELECT s.sale_no FROM sales s
        LEFT JOIN (SELECT sale_id, sum(round(qty * unit_price, 2)) AS sub,
                          sum(discount) AS disc, sum(tax_amount) AS tax, sum(line_total) AS lt
                   FROM sale_items GROUP BY sale_id) l ON l.sale_id = s.id
        WHERE s.status <> 'draft'
          AND (s.subtotal <> coalesce(l.sub, 0) OR s.discount_total <> coalesce(l.disc, 0)
               OR s.tax_total <> coalesce(l.tax, 0) OR s.total <> coalesce(l.lt, 0))
    """,
    "payé + reste dû = total": """
        SELECT s.sale_no FROM sales s
        LEFT JOIN debts d ON d.sale_id = s.id
        WHERE s.status = 'confirmed'
          AND (d.id IS NULL OR d.status IN ('open', 'partially_paid', 'paid'))
          AND NOT EXISTS (SELECT 1 FROM sale_returns r WHERE r.sale_id = s.id)
          AND s.paid_total + coalesce(d.balance, 0) <> s.total
    """,
    "payé ≤ total": "SELECT sale_no FROM sales WHERE status = 'confirmed' AND paid_total > total",
    "dettes cohérentes": """
        SELECT id::text FROM debts
        WHERE amount_paid < 0 OR amount_paid > principal
           OR (status = 'paid' AND balance <> 0)
           OR (status IN ('open', 'partially_paid') AND balance <= 0)
    """,
    "lettrage ≤ paiement": """
        SELECT p.id::text FROM payments p
        JOIN (SELECT payment_id, sum(amount) AS lettered FROM payment_allocations
              GROUP BY payment_id) a ON a.payment_id = p.id
        WHERE a.lettered > p.amount
    """,
}


def violations(owner_engine: Engine, company_id: UUID) -> dict[str, list[str]]:
    """Violations par contrôle, pour une entreprise ; un dictionnaire vide = tout tient."""
    found: dict[str, list[str]] = {}
    with owner_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(company_id)}
        )
        for name, sql in CHECKS.items():
            rows = [str(value) for value in connection.execute(text(sql)).scalars()]
            if rows:
                found[name] = rows[:10]
    return found


def assert_consistent(owner_engine: Engine, company_id: UUID) -> None:
    found = violations(owner_engine, company_id)
    assert found == {}, f"Chiffres incohérents : {found}"


def main(argv: list[str]) -> int:
    """Contrôle une entreprise de la base locale (`make seed-demo` puis `make invariants`).

    `companies` est protégée contre l'énumération (T37) : l'entreprise se retrouve comme à
    la connexion, par son slug et l'e-mail de son gérant (`auth_lookup`).
    """
    if len(argv) not in (1, 2):
        print(
            "usage : python -m tests.helpers.invariants <slug> [e-mail du gérant]", file=sys.stderr
        )
        return 2
    slug = argv[0]
    email = argv[1] if len(argv) == 2 else f"gerant@{slug}.example.com"
    engine = create_engine(os.environ["COGES_DATABASE_URL_OWNER"])
    # `auth_lookup` n'est ouverte qu'au rôle applicatif (ADR 0005).
    with create_engine(os.environ["COGES_DATABASE_URL_APP"]).connect() as connection:
        row = connection.execute(
            text("SELECT company_id FROM auth_lookup(CAST(:s AS citext), CAST(:e AS citext))"),
            {"s": slug, "e": email},
        ).first()
    if row is None:
        print(f"entreprise « {slug} » ou gérant « {email} » introuvable", file=sys.stderr)
        return 2
    found = violations(engine, UUID(str(row[0])))
    for name in CHECKS:
        print(f"  {'ÉCHEC' if name in found else 'OK   '} {name} {found.get(name, '')}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
