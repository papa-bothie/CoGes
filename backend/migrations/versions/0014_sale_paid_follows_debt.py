"""Ce qui reste dû sur une vente suit sa dette (ADR 0062, bug B2 de la phase 15).

`sales.paid_total` ne sommait que les paiements portant `sale_id`. Un règlement de dette
passe par `payment_allocations` sur la dette (`debts.sale_id`), **sans** `sale_id` sur le
paiement : la dette se soldait, et la vente restait « Reste dû ».

**1. `paid_total` = encaissé directement + lettré sur la dette de la vente.** Les deux
termes ne gardent que les lignes **vivantes** (filtre `_LIVE` de la 0012). La compensation
par un retour (`offset`, ADR 0024) est un lettrage comme un autre : elle compte, si bien
que `paid_total` veut dire « réglé », pas « encaissé ». La trésorerie ne change pas : elle
exclut déjà `method = 'offset'`.

Il n'y a pas de double comptage : l'acompte encaissé à la confirmation porte `sale_id` et
n'est jamais lettré, et la dette ne porte que le solde (`principal = total − acompte`).

**2. Un trigger sur `payment_allocations`** recalcule la vente de la dette touchée.
Ordre des verrous : la dette (déjà prise par `pa_check`), puis la vente. Le même ordre est
tenu par l'annulation d'une vente, qui verrouille sa dette avant elle (ADR 0062).

**3. L'annulation d'un paiement** (`payment_reversal_rollup`) recalcule aussi les ventes
des dettes qu'il avait lettrées, après les avoir verrouillées dans l'ordre des
identifiants (ADR 0039).

**4. Rattrapage puis contrôle.** Toutes les ventes qui portent une dette sont recalculées.
Ensuite, la migration échoue si une seule vente garde `total − paid_total ≠ debts.balance`.
Une dette abandonnée est exclue du contrôle : son solde est gelé, il ne se règle plus.
Comme pour la 0009, les tables sont en `FORCE ROW LEVEL SECURITY` et `coges_owner` ne
verrait aucune ligne : `NO FORCE` le temps du rattrapage, dans la transaction de la
migration.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Filtre des lignes vivantes, identique à la révision 0012.
_LIVE = (
    "NOT EXISTS (SELECT 1 FROM payments r "
    "WHERE r.company_id = {alias}.company_id AND r.reversal_of_payment_id = {alias}.{column})"
)

#: Tables lues par le rattrapage, toutes en FORCE ROW LEVEL SECURITY.
_BACKFILL_TABLES = ("sales", "debts", "payments", "payment_allocations")


def upgrade() -> None:
    live_payment = _LIVE.format(alias="p", column="id")
    live_allocation = _LIVE.format(alias="a", column="payment_id")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION sale_paid_recompute(p_co uuid, p_sale uuid)
        RETURNS void AS $$
        BEGIN
           UPDATE sales s
              SET paid_total = COALESCE(direct.s, 0) + COALESCE(lettered.s, 0),
                  updated_at = now()
             FROM (SELECT SUM(p.amount) s FROM payments p
                    WHERE p.company_id = p_co AND p.sale_id = p_sale
                      AND p.direction = 'inflow' AND {live_payment}) direct,
                  (SELECT SUM(a.amount) s FROM payment_allocations a
                     JOIN debts d ON d.company_id = a.company_id AND d.id = a.debt_id
                    WHERE a.company_id = p_co AND d.sale_id = p_sale
                      AND {live_allocation}) lettered
            WHERE s.company_id = p_co AND s.id = p_sale;
        END $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        """
        CREATE FUNCTION allocation_sale_rollup() RETURNS trigger AS $$
        DECLARE v_co uuid; v_sale uuid;
        BEGIN
           v_co := COALESCE(NEW.company_id, OLD.company_id);
           IF TG_OP <> 'INSERT' THEN
              SELECT sale_id INTO v_sale FROM debts
               WHERE company_id = v_co AND id = OLD.debt_id;
              IF v_sale IS NOT NULL THEN PERFORM sale_paid_recompute(v_co, v_sale); END IF;
           END IF;
           IF TG_OP <> 'DELETE' THEN
              SELECT sale_id INTO v_sale FROM debts
               WHERE company_id = v_co AND id = NEW.debt_id;
              IF v_sale IS NOT NULL THEN PERFORM sale_paid_recompute(v_co, v_sale); END IF;
           END IF;
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    # Nommé après `pa_rollup` : les triggers AFTER d'une table se jouent dans l'ordre
    # alphabétique, la dette est donc à jour quand la vente se recalcule.
    op.execute(
        "CREATE TRIGGER pa_sale_rollup AFTER INSERT OR UPDATE OR DELETE ON payment_allocations "
        "FOR EACH ROW EXECUTE FUNCTION allocation_sale_rollup()"
    )

    op.execute(_REVERSAL_ROLLUP_0014)
    _backfill_and_check()


def downgrade() -> None:
    op.execute(_REVERSAL_ROLLUP_0012)
    op.execute("DROP TRIGGER IF EXISTS pa_sale_rollup ON payment_allocations")
    op.execute("DROP FUNCTION IF EXISTS allocation_sale_rollup()")
    live_payment = _LIVE.format(alias="p", column="id")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION sale_paid_recompute(p_co uuid, p_sale uuid)
        RETURNS void AS $$
        BEGIN
           UPDATE sales s SET paid_total = COALESCE(t.s, 0), updated_at = now()
             FROM (SELECT SUM(p.amount) s FROM payments p
                    WHERE p.company_id = p_co AND p.sale_id = p_sale
                      AND p.direction = 'inflow' AND {live_payment}) t
            WHERE s.company_id = p_co AND s.id = p_sale;
        END $$ LANGUAGE plpgsql
        """
    )
    _backfill_and_check(check=False)


def _backfill_and_check(*, check: bool = True) -> None:
    """Recalcule chaque vente à dette, puis vérifie l'invariant de l'ADR 0062."""
    for table in _BACKFILL_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "SELECT sale_paid_recompute(s.company_id, s.id) FROM sales s "
        "WHERE EXISTS (SELECT 1 FROM debts d "
        "              WHERE d.company_id = s.company_id AND d.sale_id = s.id)"
    )
    if check:
        op.execute(
            """
            DO $$
            DECLARE v_count bigint;
            BEGIN
               SELECT count(*) INTO v_count
                 FROM sales s
                 JOIN debts d ON d.company_id = s.company_id AND d.sale_id = s.id
                WHERE d.status <> 'written_off' AND s.total - s.paid_total <> d.balance;
               IF v_count > 0 THEN
                  RAISE EXCEPTION 'ADR 0062 : % vente(s) dont le reste dû diffère de la dette',
                     v_count;
               END IF;
            END $$
            """
        )
    for table in reversed(_BACKFILL_TABLES):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


# ------------------------------------------------ annulation d'un paiement

#: Corps de la 0012, à deux ajouts près : les ventes des dettes lettrées sont
#: verrouillées puis recalculées, au même titre que la vente d'un paiement direct.
_REVERSAL_ROLLUP_0014 = """
CREATE OR REPLACE FUNCTION payment_reversal_rollup() RETURNS trigger AS $$
DECLARE v_co uuid := NEW.company_id; v_id uuid;
BEGIN
   -- 1. Verrous : dettes, retours, puis ventes, chaque fois dans l'ordre des ids.
   PERFORM 1 FROM debts d
     WHERE d.company_id = v_co
       AND d.id IN (SELECT a.debt_id FROM payment_allocations a
                     WHERE a.company_id = v_co
                       AND a.payment_id = NEW.reversal_of_payment_id)
     ORDER BY d.id FOR UPDATE;
   PERFORM 1 FROM sale_returns r
     WHERE r.company_id = v_co
       AND r.id IN (SELECT f.sale_return_id FROM sale_return_refunds f
                     WHERE f.company_id = v_co
                       AND f.payment_id = NEW.reversal_of_payment_id)
     ORDER BY r.id FOR UPDATE;
   PERFORM 1 FROM sales s
     WHERE s.company_id = v_co
       AND s.id IN (SELECT p.sale_id FROM payments p
                     WHERE p.company_id = v_co AND p.id = NEW.reversal_of_payment_id
                    UNION
                    SELECT d.sale_id FROM payment_allocations a
                      JOIN debts d ON d.company_id = a.company_id AND d.id = a.debt_id
                     WHERE a.company_id = v_co
                       AND a.payment_id = NEW.reversal_of_payment_id)
     ORDER BY s.id FOR UPDATE;

   -- 2. Recalculs, chacun dans sa propre instruction : instantané neuf, qui voit ce
   --    qu'un concurrent a commité pendant l'attente du verrou.
   FOR v_id IN SELECT a.debt_id FROM payment_allocations a
                WHERE a.company_id = v_co
                  AND a.payment_id = NEW.reversal_of_payment_id
                ORDER BY a.debt_id LOOP
      PERFORM debt_recompute(v_co, v_id);
   END LOOP;
   FOR v_id IN SELECT f.sale_return_id FROM sale_return_refunds f
                WHERE f.company_id = v_co
                  AND f.payment_id = NEW.reversal_of_payment_id
                ORDER BY f.sale_return_id LOOP
      PERFORM refund_recompute(v_co, v_id);
   END LOOP;
   FOR v_id IN SELECT p.sale_id FROM payments p
                WHERE p.company_id = v_co AND p.id = NEW.reversal_of_payment_id
                  AND p.sale_id IS NOT NULL
               UNION
               SELECT d.sale_id FROM payment_allocations a
                 JOIN debts d ON d.company_id = a.company_id AND d.id = a.debt_id
                WHERE a.company_id = v_co
                  AND a.payment_id = NEW.reversal_of_payment_id
                  AND d.sale_id IS NOT NULL
               ORDER BY 1 LOOP
      PERFORM sale_paid_recompute(v_co, v_id);
   END LOOP;
   RETURN NULL;
END $$ LANGUAGE plpgsql
"""

#: Corps de la 0012, mot pour mot, pour le downgrade.
_REVERSAL_ROLLUP_0012 = """
CREATE OR REPLACE FUNCTION payment_reversal_rollup() RETURNS trigger AS $$
DECLARE v_co uuid := NEW.company_id; v_id uuid; v_sale uuid;
BEGIN
   -- 1. Verrous, dans l'ordre des identifiants : un paiement concurrent sur la
   --    même dette attend ici, ou nous attendons son COMMIT.
   PERFORM 1 FROM debts d
     WHERE d.company_id = v_co
       AND d.id IN (SELECT a.debt_id FROM payment_allocations a
                     WHERE a.company_id = v_co
                       AND a.payment_id = NEW.reversal_of_payment_id)
     ORDER BY d.id FOR UPDATE;
   PERFORM 1 FROM sale_returns r
     WHERE r.company_id = v_co
       AND r.id IN (SELECT f.sale_return_id FROM sale_return_refunds f
                     WHERE f.company_id = v_co
                       AND f.payment_id = NEW.reversal_of_payment_id)
     ORDER BY r.id FOR UPDATE;
   SELECT sale_id INTO v_sale FROM payments
    WHERE company_id = v_co AND id = NEW.reversal_of_payment_id;
   IF v_sale IS NOT NULL THEN
      PERFORM 1 FROM sales WHERE company_id = v_co AND id = v_sale FOR UPDATE;
   END IF;

   -- 2. Recalculs, chacun dans sa propre instruction : instantané neuf, qui
   --    voit ce qu'un concurrent a commité pendant l'attente du verrou.
   FOR v_id IN SELECT a.debt_id FROM payment_allocations a
                WHERE a.company_id = v_co
                  AND a.payment_id = NEW.reversal_of_payment_id
                ORDER BY a.debt_id LOOP
      PERFORM debt_recompute(v_co, v_id);
   END LOOP;
   FOR v_id IN SELECT f.sale_return_id FROM sale_return_refunds f
                WHERE f.company_id = v_co
                  AND f.payment_id = NEW.reversal_of_payment_id
                ORDER BY f.sale_return_id LOOP
      PERFORM refund_recompute(v_co, v_id);
   END LOOP;
   IF v_sale IS NOT NULL THEN
      PERFORM sale_paid_recompute(v_co, v_sale);
   END IF;
   RETURN NULL;
END $$ LANGUAGE plpgsql
"""
