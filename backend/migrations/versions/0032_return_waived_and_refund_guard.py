"""Retours après la relecture des lots 28 et 29 (prompt 32, bloc C, ADR 0103).

- **C1, `sale_returns.waived_total`** : la part d'un retour qui correspond à une dette
  abandonnée (ADR 0029) est soldée **sans argent**. Le client n'a jamais versé cet argent,
  on ne le lui rend pas ; sans cette colonne, le retour restait « à régler » pour toujours
  (argent plafonné à ce qui a été versé, ADR 0097, plus de dette à compenser). Le reste dû
  devient `total_refund - refunded_total - waived_total` partout : plafond
  `sale_returns_refund_cap`, statut (`return_refund_status_set`), contrôle d'un remboursement
  (`refund_check`, corps de la 0012 à ce seul calcul près). Un retour dont tout est soldé
  ainsi est `none_due`.
- **C2, `payments_reversal_refund_guard`** : annuler un encaissement d'une vente est refusé
  (`CG054` ⇒ 409 `refund_exceeds_paid`) si l'argent qui resterait versé sur la vente devient
  inférieur à ce qui a déjà été rendu en argent sur ses retours. Règle à cheval entre
  Finance et Sales, descendue en base comme celle de l'ADR 0014 : Finance ne lit pas les
  retours. Le trigger passe après `payments_reversal_check` (ordre alphabétique), qui a
  déjà verrouillé le paiement d'origine.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CANCELLED_GUARD = """
           IF EXISTS (SELECT 1 FROM payments p
                       WHERE p.company_id = NEW.company_id AND p.id = NEW.payment_id
                         AND (p.reversal_of_payment_id IS NOT NULL
                              OR EXISTS (SELECT 1 FROM payments r
                                          WHERE r.company_id = p.company_id
                                            AND r.reversal_of_payment_id = p.id))) THEN
              RAISE EXCEPTION 'Paiement % annule ou d''annulation : il ne s''impute plus',
                 NEW.payment_id USING ERRCODE = 'CG052';
           END IF;"""


def _refund_check(due: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION refund_check() RETURNS trigger AS $$
        DECLARE v_due numeric(14,2); v_free numeric(14,2); v_dir cash_direction;
        BEGIN
           SELECT {due} INTO v_due FROM sale_returns
            WHERE company_id = NEW.company_id AND id = NEW.sale_return_id FOR UPDATE;
           IF NOT FOUND THEN RAISE EXCEPTION 'Retour introuvable'; END IF;
           IF NEW.amount > v_due THEN
              RAISE EXCEPTION 'Remboursement % superieur au reste du %', NEW.amount, v_due
                 USING ERRCODE = 'CG041';
           END IF;
           SELECT direction, amount - COALESCE(
                     (SELECT SUM(r.amount) FROM sale_return_refunds r
                       WHERE r.payment_id = p.id AND r.id <> NEW.id), 0)
             INTO v_dir, v_free
             FROM payments p
            WHERE p.company_id = NEW.company_id AND p.id = NEW.payment_id FOR UPDATE;
           IF v_dir <> 'outflow' THEN
              RAISE EXCEPTION 'Un remboursement de retour exige direction = outflow' USING ERRCODE = 'CG042';
           END IF;
           IF NEW.amount > v_free THEN
              RAISE EXCEPTION 'Paiement sur-affecte : reste % disponible', v_free USING ERRCODE = 'CG043';
           END IF;{_CANCELLED_GUARD}
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )


def _status(owed: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION return_refund_status_set() RETURNS trigger AS $$
        BEGIN
           NEW.refund_status := CASE
              WHEN {owed} = 0                  THEN 'none_due'
              WHEN NEW.refunded_total = 0                THEN 'pending'
              WHEN NEW.refunded_total < {owed} THEN 'partial'
              ELSE 'settled' END::return_refund_status;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )


#: Vrai mouvement de caisse, comme `_counts_as_cash` (finance/repository.py).
_LIVE_CASH = """
    {p}.method <> 'offset' AND {p}.reversal_of_payment_id IS NULL
    AND NOT EXISTS (SELECT 1 FROM payments x
                     WHERE x.company_id = {p}.company_id AND x.reversal_of_payment_id = {p}.id)
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sale_returns ADD COLUMN waived_total numeric(14,2) NOT NULL DEFAULT 0 "
        "CONSTRAINT sale_returns_waived_nonneg CHECK (waived_total >= 0)"
    )
    op.execute("ALTER TABLE sale_returns DROP CONSTRAINT sale_returns_refund_cap")
    op.execute(
        "ALTER TABLE sale_returns ADD CONSTRAINT sale_returns_refund_cap "
        "CHECK (refunded_total + waived_total <= total_refund)"
    )
    _status("(NEW.total_refund - NEW.waived_total)")
    op.execute("DROP TRIGGER sr_status ON sale_returns")
    op.execute(
        "CREATE TRIGGER sr_status BEFORE INSERT OR UPDATE OF total_refund, refunded_total, "
        "waived_total ON sale_returns FOR EACH ROW EXECUTE FUNCTION return_refund_status_set()"
    )
    _refund_check("total_refund - refunded_total - waived_total")

    received = _LIVE_CASH.format(p="p")
    refunded = _LIVE_CASH.format(p="q")
    op.execute(
        f"""
        CREATE FUNCTION payment_reversal_refund_guard() RETURNS trigger AS $$
        DECLARE o payments; v_sale uuid; v_received numeric(14,2); v_refunded numeric(14,2);
        BEGIN
           SELECT * INTO o FROM payments
            WHERE company_id = NEW.company_id AND id = NEW.reversal_of_payment_id;
           IF NOT FOUND OR o.direction <> 'inflow' OR o.method = 'offset' THEN
              RETURN NEW;
           END IF;
           FOR v_sale IN
              SELECT o.sale_id WHERE o.sale_id IS NOT NULL
              UNION
              SELECT d.sale_id FROM payment_allocations a
                JOIN debts d ON d.company_id = a.company_id AND d.id = a.debt_id
               WHERE a.company_id = o.company_id AND a.payment_id = o.id
                 AND d.sale_id IS NOT NULL
           LOOP
              SELECT COALESCE(SUM(p.amount), 0) INTO v_received FROM payments p
               WHERE p.company_id = o.company_id AND p.sale_id = v_sale
                 AND p.direction = 'inflow' AND p.id <> o.id AND {received};
              SELECT v_received + COALESCE(SUM(a.amount), 0) INTO v_received
                FROM payment_allocations a
                JOIN payments p ON p.company_id = a.company_id AND p.id = a.payment_id
                JOIN debts d ON d.company_id = a.company_id AND d.id = a.debt_id
               WHERE a.company_id = o.company_id AND d.sale_id = v_sale
                 AND p.direction = 'inflow' AND p.id <> o.id AND {received};
              SELECT COALESCE(SUM(q.amount), 0) INTO v_refunded FROM payments q
                JOIN sale_returns r ON r.company_id = q.company_id AND r.id = q.sale_return_id
               WHERE q.company_id = o.company_id AND r.sale_id = v_sale
                 AND q.direction = 'outflow' AND {refunded};
              IF v_refunded > v_received THEN
                 RAISE EXCEPTION 'Vente % : % rendus, il ne resterait que % verses',
                    v_sale, v_refunded, v_received USING ERRCODE = 'CG054';
              END IF;
           END LOOP;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER payments_reversal_refund_guard BEFORE INSERT ON payments "
        "FOR EACH ROW WHEN (NEW.reversal_of_payment_id IS NOT NULL) "
        "EXECUTE FUNCTION payment_reversal_refund_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER payments_reversal_refund_guard ON payments")
    op.execute("DROP FUNCTION payment_reversal_refund_guard()")
    _refund_check("total_refund - refunded_total")
    op.execute("DROP TRIGGER sr_status ON sale_returns")
    op.execute(
        "CREATE TRIGGER sr_status BEFORE INSERT OR UPDATE OF total_refund, refunded_total "
        "ON sale_returns FOR EACH ROW EXECUTE FUNCTION return_refund_status_set()"
    )
    _status("NEW.total_refund")
    op.execute("ALTER TABLE sale_returns DROP CONSTRAINT sale_returns_refund_cap")
    op.execute(
        "ALTER TABLE sale_returns ADD CONSTRAINT sale_returns_refund_cap "
        "CHECK (refunded_total <= total_refund)"
    )
    op.execute("ALTER TABLE sale_returns DROP COLUMN waived_total")
