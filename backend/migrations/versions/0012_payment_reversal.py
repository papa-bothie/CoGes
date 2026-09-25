"""Annuler un paiement erroné sans rien effacer : la contre-écriture.

Un caissier qui saisit 50 000 au lieu de 5 000 n'avait aucun recours : `payments` n'a
ni statut ni suppression logique (§ 8.6), `coges_app` n'a pas `DELETE`, et l'ADR 0031
(décision 4) avait repoussé le sujet. Cette révision le tranche selon le principe du
mouvement de stock inverse (ADR 0017) : **on n'efface jamais, on contre-passe**. Le
paiement d'origine reste intact ; une ligne d'annulation le neutralise. ADR 0038.

**1. Deux colonnes, quatre contraintes.** `reversal_of_payment_id` désigne le paiement
annulé, `cancel_reason` en porte le motif. La clé étrangère composite interdit de
viser le paiement d'une autre entreprise, `payments_reversal_uq` interdit d'annuler
deux fois — c'est elle, et non le service, qui arbitre deux annulations simultanées.

**2. « Même montant, sens opposé » n'est pas un `CHECK`.** Le prompt de phase le
demandait ainsi, mais un `CHECK` ne lit qu'une ligne. `payment_reversal_check()` fait
ce que fait `inv_check_reversal()` au § 8.5 : il **réécrit** `amount`, `method` et
`direction` depuis l'origine. Une annulation incohérente n'est pas refusée, elle est
impossible à écrire.

**3. Les lettrages d'origine ne bougent pas ; ce sont les sommes qui changent.** Une
allocation négative est interdite (`amount > 0`), et modifier ou supprimer une ligne
de lettrage effacerait l'histoire. Les trois rollups — `debt_rollup`,
`refund_rollup`, `sale_paid_rollup` — ne somment donc plus que les lignes **vivantes**,
celles dont le paiement n'a pas d'annulation. Leurs corps sont ceux de la 0006, à ce
seul filtre près ; le calcul est déplacé dans trois fonctions `*_recompute` pour que
le trigger d'annulation appelle **la même** arithmétique.

**4. Verrouiller avant de sommer.** Insérer une annulation ne touche aucune ligne de
lettrage : aucun rollup ne se déclenche. `payment_reversal_rollup()` recalcule donc
les dettes, retours et vente du paiement d'origine — après les avoir verrouillés
`FOR UPDATE`, dans l'ordre des identifiants, **dans une instruction distincte**. Un
`UPDATE … FROM (SELECT SUM …)` qui attendrait le verrou garderait l'instantané pris
avant l'attente et manquerait l'allocation d'un paiement concurrent ; une nouvelle
instruction, en READ COMMITTED, prend un instantané neuf.

**5. Trois SQLSTATE applicatifs.**

| SQLSTATE | Fonction                               | Erreur métier              |
|----------|----------------------------------------|----------------------------|
| `CG051`  | `payment_reversal_check`               | `cannot_cancel_a_reversal` |
| `CG052`  | `allocation_check`, `refund_check`     | `payment_cancelled`        |
| `CG053`  | `payment_reversal_check`               | `payment_debt_written_off` |

`CG052` ferme une porte que rien n'ouvre aujourd'hui (un paiement n'est imputé qu'à
sa création), mais qu'une imputation différée ouvrirait : imputer un paiement annulé
ferait baisser une dette avec de l'argent qui n'existe pas. `allocation_check` et
`refund_check` sont repris de la 0008 mot pour mot, plus ce seul contrôle.

**6. Un dixième événement.** `payment.cancelled` entre dans le `CHECK` de
`business_events`, validé avant codage : sans lui, le tableau de bord resterait faux
jusqu'à l'expiration de son cache.

Privilèges : rien à accorder. L'annulation est un `INSERT` ; les `FOR UPDATE` sur
`payments`, `debts`, `sale_returns` et `sales` reposent sur l'UPDATE que les
privilèges par défaut de la 0001 accordent déjà (leçon de l'ADR 0018). Aucun DELETE :
T36 est inchangé.

Le `downgrade` rend les cinq fonctions de la 0006 et de la 0008 mot pour mot. Il ne
peut pas faire disparaître les annulations déjà écrites — `payments` est en FORCE ROW
LEVEL SECURITY et le propriétaire n'y voit rien (ADR 0024) — ni refuser de s'exécuter,
puisque la base de test repasse par `downgrade base` à chaque session. Ces lignes
redeviennent des paiements de sens opposé sans lien : le net de trésorerie reste
exact, les soldes stockés restent ceux de l'annulation.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Liste fermée des événements, identique à `app.core.events.types.EventType`.
#: Recopiée plutôt qu'importée : une migration livrée ne doit pas changer quand le
#: code applicatif change.
EVENT_TYPES_BEFORE = (
    "sale.confirmed",
    "sale.cancelled",
    "sale.returned",
    "sale_return.refunded",
    "stock.updated",
    "payment.received",
    "debt.created",
    "debt.settled",
    "expense.created",
)
EVENT_TYPES_AFTER = (*EVENT_TYPES_BEFORE, "payment.cancelled")

#: Nom attribué par PostgreSQL au `CHECK` en ligne de la révision 0002.
EVENT_CHECK = "business_events_event_type_check"

#: Borne du motif, reprise par `PaymentCancel` côté API.
REASON_MAX_LENGTH = 500

#: Filtre des lignes vivantes : le paiement `alias` n'a pas été annulé.
_LIVE = (
    "NOT EXISTS (SELECT 1 FROM payments r "
    "WHERE r.company_id = {alias}.company_id AND r.reversal_of_payment_id = {alias}.{column})"
)


def upgrade() -> None:
    _columns()
    _recompute_functions()
    _rollups(live_only=True)
    _checks(refuse_cancelled=True)
    _reversal_triggers()
    _event_check(EVENT_TYPES_AFTER)


def downgrade() -> None:
    _event_check(EVENT_TYPES_BEFORE, validate=False)
    _drop_reversal_triggers()
    _checks(refuse_cancelled=False)
    _rollups(live_only=False)
    _drop_recompute_functions()
    _drop_columns()


# ------------------------------------------------------------------ colonnes


def _columns() -> None:
    op.execute(
        f"""
        ALTER TABLE payments
          ADD COLUMN reversal_of_payment_id uuid,
          ADD COLUMN cancel_reason text,
          ADD CONSTRAINT payments_reversal_fk FOREIGN KEY (company_id, reversal_of_payment_id)
            REFERENCES payments (company_id, id) ON DELETE RESTRICT,
          ADD CONSTRAINT payments_reversal_uq UNIQUE (company_id, reversal_of_payment_id),
          -- Une annulation n'a ni contexte ni référence propre : elle se lit par le
          -- paiement qu'elle annule. Un paiement ordinaire n'a pas de motif d'annulation.
          ADD CONSTRAINT payments_reversal_shape CHECK (
            (reversal_of_payment_id IS NULL AND cancel_reason IS NULL)
            OR (reversal_of_payment_id IS NOT NULL
                AND num_nonnulls(sale_id, expense_id, sale_return_id, reference) = 0
                AND length(btrim(cancel_reason)) BETWEEN 1 AND {REASON_MAX_LENGTH})),
          ADD CONSTRAINT payments_reversal_not_self CHECK (reversal_of_payment_id <> id)
        """
    )


def _drop_columns() -> None:
    op.execute(
        """
        ALTER TABLE payments
          DROP CONSTRAINT IF EXISTS payments_reversal_not_self,
          DROP CONSTRAINT IF EXISTS payments_reversal_shape,
          DROP CONSTRAINT IF EXISTS payments_reversal_uq,
          DROP CONSTRAINT IF EXISTS payments_reversal_fk,
          DROP COLUMN IF EXISTS cancel_reason,
          DROP COLUMN IF EXISTS reversal_of_payment_id
        """
    )


# ------------------------------------------------- arithmétique des soldes


def _recompute_functions() -> None:
    """Les trois calculs de solde, appelés par les rollups **et** par l'annulation."""
    live_allocation = _LIVE.format(alias="a", column="payment_id")
    live_refund = _LIVE.format(alias="f", column="payment_id")
    live_payment = _LIVE.format(alias="p", column="id")

    # Corps de `debt_rollup` (0006), au filtre des lettrages vivants près.
    op.execute(
        f"""
        CREATE FUNCTION debt_recompute(p_co uuid, p_debt uuid) RETURNS void AS $$
        BEGIN
           UPDATE debts d SET
              amount_paid = COALESCE(t.s, 0),
              status = CASE WHEN COALESCE(t.s, 0) = 0          THEN 'open'
                            WHEN COALESCE(t.s, 0) < d.principal THEN 'partially_paid'
                            ELSE 'paid' END::debt_status,
              closed_at = CASE WHEN COALESCE(t.s, 0) >= d.principal THEN now() END,
              updated_at = now()
           FROM (SELECT SUM(a.amount) s FROM payment_allocations a
                  WHERE a.company_id = p_co AND a.debt_id = p_debt
                    AND {live_allocation}) t
           WHERE d.company_id = p_co AND d.id = p_debt AND d.status <> 'written_off';
        END $$ LANGUAGE plpgsql
        """
    )
    # Corps de `refund_rollup` (0006). `sr_status` recalcule `refund_status`.
    op.execute(
        f"""
        CREATE FUNCTION refund_recompute(p_co uuid, p_ret uuid) RETURNS void AS $$
        BEGIN
           UPDATE sale_returns r SET refunded_total = COALESCE(t.s, 0), updated_at = now()
             FROM (SELECT SUM(f.amount) s FROM sale_return_refunds f
                    WHERE f.company_id = p_co AND f.sale_return_id = p_ret
                      AND {live_refund}) t
            WHERE r.company_id = p_co AND r.id = p_ret;
        END $$ LANGUAGE plpgsql
        """
    )
    # Corps de `sale_paid_rollup` (0006). Une annulation ne porte jamais `sale_id`
    # (`payments_reversal_shape`) : seul le filtre des paiements annulés est utile.
    op.execute(
        f"""
        CREATE FUNCTION sale_paid_recompute(p_co uuid, p_sale uuid) RETURNS void AS $$
        BEGIN
           UPDATE sales s SET paid_total = COALESCE(t.s, 0), updated_at = now()
             FROM (SELECT SUM(p.amount) s FROM payments p
                    WHERE p.company_id = p_co AND p.sale_id = p_sale
                      AND p.direction = 'inflow' AND {live_payment}) t
            WHERE s.company_id = p_co AND s.id = p_sale;
        END $$ LANGUAGE plpgsql
        """
    )


def _drop_recompute_functions() -> None:
    for signature in (
        "sale_paid_recompute(uuid, uuid)",
        "refund_recompute(uuid, uuid)",
        "debt_recompute(uuid, uuid)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")


def _rollups(*, live_only: bool) -> None:
    """Les trois rollups du § 8.7.

    `live_only=True` délègue aux fonctions `*_recompute` ; `False` restitue mot pour
    mot les corps de la révision 0006 — un downgrade rétablit un état.
    """
    if live_only:
        debt_body = "PERFORM debt_recompute(v_co, v_debt);"
        refund_body = "PERFORM refund_recompute(v_co, v_ret);"
        sale_body = "PERFORM sale_paid_recompute(v_co, v_sale);"
    else:
        debt_body = """
           UPDATE debts d SET
              amount_paid = COALESCE(t.s, 0),
              status = CASE WHEN COALESCE(t.s, 0) = 0          THEN 'open'
                            WHEN COALESCE(t.s, 0) < d.principal THEN 'partially_paid'
                            ELSE 'paid' END::debt_status,
              closed_at = CASE WHEN COALESCE(t.s, 0) >= d.principal THEN now() END,
              updated_at = now()
           FROM (SELECT SUM(amount) s FROM payment_allocations
                  WHERE company_id = v_co AND debt_id = v_debt) t
           WHERE d.company_id = v_co AND d.id = v_debt AND d.status <> 'written_off';"""
        refund_body = """
           UPDATE sale_returns r SET refunded_total = COALESCE(t.s, 0), updated_at = now()
             FROM (SELECT SUM(amount) s FROM sale_return_refunds
                    WHERE company_id = v_co AND sale_return_id = v_ret) t
            WHERE r.company_id = v_co AND r.id = v_ret;"""
        sale_body = """
           UPDATE sales s SET paid_total = COALESCE(t.s, 0), updated_at = now()
             FROM (SELECT SUM(amount) s FROM payments
                    WHERE company_id = v_co AND sale_id = v_sale AND direction = 'inflow') t
            WHERE s.company_id = v_co AND s.id = v_sale;"""

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION debt_rollup() RETURNS trigger AS $$
        DECLARE v_debt uuid; v_co uuid;
        BEGIN
           v_debt := COALESCE(NEW.debt_id, OLD.debt_id);
           v_co   := COALESCE(NEW.company_id, OLD.company_id);
           {debt_body}
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION refund_rollup() RETURNS trigger AS $$
        DECLARE v_ret uuid; v_co uuid;
        BEGIN
           v_ret := COALESCE(NEW.sale_return_id, OLD.sale_return_id);
           v_co  := COALESCE(NEW.company_id, OLD.company_id);
           {refund_body}
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION sale_paid_rollup() RETURNS trigger AS $$
        DECLARE v_sale uuid; v_co uuid;
        BEGIN
           v_sale := COALESCE(NEW.sale_id, OLD.sale_id);
           IF v_sale IS NULL THEN RETURN NULL; END IF;
           v_co := COALESCE(NEW.company_id, OLD.company_id);
           {sale_body}
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )


# ---------------------------------------------------- imputations refusées


def _checks(*, refuse_cancelled: bool) -> None:
    """`allocation_check` et `refund_check`, corps de la 0008 plus un contrôle.

    `refuse_cancelled=False` restitue exactement les corps de la révision 0008.
    Le contrôle ajouté vient **après** les verrous existants : il lit une ligne de
    paiement déjà verrouillée, et ne change pas l'ordre des verrous.
    """
    cancelled_guard = (
        """
           IF EXISTS (SELECT 1 FROM payments p
                       WHERE p.company_id = NEW.company_id AND p.id = NEW.payment_id
                         AND (p.reversal_of_payment_id IS NOT NULL
                              OR EXISTS (SELECT 1 FROM payments r
                                          WHERE r.company_id = p.company_id
                                            AND r.reversal_of_payment_id = p.id))) THEN
              RAISE EXCEPTION 'Paiement % annule ou d''annulation : il ne s''impute plus',
                 NEW.payment_id USING ERRCODE = 'CG052';
           END IF;"""
        if refuse_cancelled
        else ""
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION allocation_check() RETURNS trigger AS $$
        DECLARE v_bal numeric(14,2); v_free numeric(14,2);
        BEGIN
           SELECT balance INTO v_bal FROM debts
            WHERE company_id = NEW.company_id AND id = NEW.debt_id FOR UPDATE;
           IF NEW.amount > v_bal THEN
              RAISE EXCEPTION 'Affectation % superieure au solde restant %',
                 NEW.amount, v_bal USING ERRCODE = 'CG044';
           END IF;
           SELECT p.amount - COALESCE((SELECT SUM(a.amount) FROM payment_allocations a
                                        WHERE a.payment_id = p.id AND a.id <> NEW.id), 0)
             INTO v_free FROM payments p
            WHERE p.company_id = NEW.company_id AND p.id = NEW.payment_id FOR UPDATE;
           IF NEW.amount > v_free THEN
              RAISE EXCEPTION 'Paiement sur-affecte : reste % disponible', v_free USING ERRCODE = 'CG045';
           END IF;{cancelled_guard}
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION refund_check() RETURNS trigger AS $$
        DECLARE v_due numeric(14,2); v_free numeric(14,2); v_dir cash_direction;
        BEGIN
           SELECT total_refund - refunded_total INTO v_due FROM sale_returns
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
           END IF;{cancelled_guard}
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )


# ------------------------------------------------------- la contre-écriture


def _reversal_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION payment_reversal_check() RETURNS trigger AS $$
        DECLARE o payments;
        BEGIN
           -- Verrou sur l'origine : deux annulations simultanées s'y sérialisent, et
           -- la seconde bute ensuite sur `payments_reversal_uq`.
           SELECT * INTO o FROM payments
            WHERE company_id = NEW.company_id AND id = NEW.reversal_of_payment_id
            FOR UPDATE;
           IF NOT FOUND THEN
              -- `payments_reversal_fk` le dira, avec son nom.
              RETURN NEW;
           END IF;
           IF o.reversal_of_payment_id IS NOT NULL THEN
              RAISE EXCEPTION 'Le paiement % est une annulation : il ne s''annule pas', o.id
                 USING ERRCODE = 'CG051';
           END IF;
           IF EXISTS (SELECT 1 FROM payment_allocations a
                        JOIN debts d ON d.company_id = a.company_id AND d.id = a.debt_id
                       WHERE a.company_id = o.company_id AND a.payment_id = o.id
                         AND d.status = 'written_off') THEN
              RAISE EXCEPTION 'Le paiement % est impute sur une dette abandonnee', o.id
                 USING ERRCODE = 'CG053';
           END IF;
           -- Même montant, même moyen, sens opposé : réécrits, jamais crus.
           NEW.amount    := o.amount;
           NEW.method    := o.method;
           NEW.direction := CASE o.direction WHEN 'inflow' THEN 'outflow'
                                             ELSE 'inflow' END::cash_direction;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER payments_reversal_check BEFORE INSERT ON payments "
        "FOR EACH ROW WHEN (NEW.reversal_of_payment_id IS NOT NULL) "
        "EXECUTE FUNCTION payment_reversal_check()"
    )

    op.execute(
        """
        CREATE FUNCTION payment_reversal_rollup() RETURNS trigger AS $$
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
    )
    op.execute(
        "CREATE TRIGGER payments_reversal_rollup AFTER INSERT ON payments "
        "FOR EACH ROW WHEN (NEW.reversal_of_payment_id IS NOT NULL) "
        "EXECUTE FUNCTION payment_reversal_rollup()"
    )


def _drop_reversal_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS payments_reversal_rollup ON payments")
    op.execute("DROP TRIGGER IF EXISTS payments_reversal_check ON payments")
    op.execute("DROP FUNCTION IF EXISTS payment_reversal_rollup()")
    op.execute("DROP FUNCTION IF EXISTS payment_reversal_check()")


# ------------------------------------------------------------- événements


def _event_check(event_types: Sequence[str], *, validate: bool = True) -> None:
    """Réécrit le `CHECK` de la liste fermée.

    Au downgrade, `NOT VALID` : l'outbox peut déjà porter des `payment.cancelled`,
    et un `CHECK` validé ferait échouer le retour en arrière sur des lignes qu'une
    migration ne peut ni voir ni supprimer (FORCE RLS). Les écritures nouvelles, elles,
    sont bien contrôlées.
    """
    values = ", ".join(f"'{event}'" for event in event_types)
    suffix = "" if validate else " NOT VALID"
    op.execute(f"ALTER TABLE business_events DROP CONSTRAINT IF EXISTS {EVENT_CHECK}")
    op.execute(
        f"ALTER TABLE business_events ADD CONSTRAINT {EVENT_CHECK} "
        f"CHECK (event_type IN ({values})){suffix}"
    )
