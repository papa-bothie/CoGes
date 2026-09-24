"""Ventes, retours et finance : tables, triggers de cohérence, plafond de crédit.

Bande D du Diagramme 3. Reprend le § 8.4 (ventes et retours), le § 8.6 (charges,
dettes, paiements, remboursements), le § 8.7 **en entier**, les index du § 8.10 et
la RLS du § 8.11 du Modèle de données V1.1.

Pourquoi les tables du § 8.6 arrivent dès maintenant, alors que le § 12 place les
dettes et les paiements après les ventes : la confirmation d'une vente écrit dans
`payments` et `debts` **dans sa propre transaction** (§ 5.1 étape 7, Diagramme 4
étapes 07-08). Sans ces tables, la confirmation ne pourrait pas être atomique — la
promesse centrale de l'architecture. La révision crée donc la structure complète ;
les services de retour (phase 06) et de finance (phase 07) viendront s'y brancher
sans nouvelle migration. C'est le point ouvert P6, tranché par l'ADR 0019.

`expense_categories` et `expenses` sont créées pour la même raison mécanique :
`debts.expense_id` et `payments.expense_id` les référencent. Aucun modèle Python ne
les couvre avant la phase 07.

Écarts assumés, hors du § 8 :

1. **`document_counters`** — le § 8 ne dit pas comment `sales.sale_no` est numéroté.
   Une table compteur verrouillée dans la transaction donne une séquence **sans
   trou par entreprise**, ce qu'une séquence PostgreSQL ne garantit pas. Générique
   dès maintenant : `return_no` (phase 06) et les dépenses (phase 07) l'utiliseront
   sans nouvelle migration. ADR 0021.
2. **`sale_items_no_change` couvre aussi l'INSERT.** Le § 8.7 ne le pose que sur
   UPDATE et DELETE : rien n'empêcherait d'ajouter une ligne à une vente déjà
   confirmée, ce que `sale_recompute_totals` répercuterait aussitôt sur ses totaux.
   Le Diagramme 4 promet l'inverse — « brouillon verrouillé à la confirmation, plus
   aucune ligne modifiable ». Le trigger est donc étendu, et un test l'attaque en
   SQL direct. ADR 0023.
3. **`debt_credit_limit()` lève `CG030`** au lieu de `check_violation`. Même motif
   que l'ADR 0018 : 23514 désigne déjà `sales_discount_bounds`, `debts_paid_bounds`
   et `sale_items_discount_bounds`, que le service ne pourrait pas distinguer du
   plafond de crédit. Message et logique inchangés. Les autres triggers du § 8.7
   gardent leurs codes : aucun ne remonte en erreur métier nommée avant la phase 06.

Privilèges : une seule exception au « pas de DELETE » (ADR 0020). Retirer une ligne
d'un brouillon est un DELETE sur `sale_items`, et le § 8.4 ne donne à cette table ni
`deleted_at`, ni place dans les totaux pour une ligne neutralisée. `sale_items_frozen`
borne le droit à la seule vie utile de la ligne — le brouillon. T36 passe de trois à
quatre tables, et vérifie toujours une égalité stricte.

Déjà en place, non recréé ici : les ENUM `sale_status`, `expense_kind`, `party_type`,
`debt_status`, `cash_direction`, `pay_method`, `return_refund_status` et la fonction
`set_updated_at` (révision 0001), les permissions `sales:*`, `payments:*`, `debts:*`
et le `CHECK` des neuf types d'événements (révision 0002).

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables tenant-scoped créées par cette révision (§ 8.11).
TENANT_TABLES = (
    "sales",
    "sale_items",
    "sale_returns",
    "sale_return_items",
    "expense_categories",
    "expenses",
    "debts",
    "payments",
    "payment_allocations",
    "sale_return_refunds",
    "document_counters",
)

# Tables portant `updated_at` : le trigger est nommé `<table>_set_updated_at`.
TABLES_WITH_UPDATED_AT = ("sales", "sale_returns", "expenses", "debts")

APP_ROLE = "coges_app"

# Types de documents numérotés. La liste s'allonge avec les phases 06 et 07 ;
# le `CHECK` est là pour qu'une faute de frappe ne crée pas un compteur fantôme.
DOCUMENT_TYPES = ("sale", "sale_return", "expense")


def _rls(table: str) -> None:
    """Applique le gabarit de politique du projet (ADR 0003) à une table."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE  ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant ON {table}
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )


def upgrade() -> None:
    # ------------------------------------------------------------------ 8.4
    op.execute(
        """
        CREATE TABLE sales (
           id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id      uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           customer_id     uuid,
           sale_no         text NOT NULL,
           status          sale_status NOT NULL DEFAULT 'draft',
           sold_at         timestamptz NOT NULL DEFAULT now(),
           subtotal        numeric(14,2) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
           discount_total  numeric(14,2) NOT NULL DEFAULT 0,
           tax_total       numeric(14,2) NOT NULL DEFAULT 0 CHECK (tax_total >= 0),
           -- V1.1 : l'égalité comptable est PRODUITE par la base, pas vérifiée par le code
           total           numeric(14,2) NOT NULL
                             GENERATED ALWAYS AS (subtotal - discount_total + tax_total) STORED,
           paid_total      numeric(14,2) NOT NULL DEFAULT 0 CHECK (paid_total >= 0),
           cancel_reason   text,
           confirmed_at    timestamptz,
           cancelled_at    timestamptz,
           created_by      uuid NOT NULL,
           created_at      timestamptz NOT NULL DEFAULT now(),
           updated_at      timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT sales_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT sales_no_uq     UNIQUE (company_id, sale_no),
           CONSTRAINT sales_customer_fk FOREIGN KEY (company_id, customer_id)
             REFERENCES customers (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT sales_creator_fk FOREIGN KEY (company_id, created_by)
             REFERENCES users (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT sales_discount_bounds CHECK (discount_total >= 0
                                                  AND discount_total <= subtotal),
           CONSTRAINT sales_cancel_coherent CHECK (
            (status = 'cancelled') = (cancelled_at IS NOT NULL)
            AND (status <> 'cancelled' OR length(btrim(coalesce(cancel_reason,''))) > 0)),
           CONSTRAINT sales_confirm_coherent CHECK (
            status = 'draft' OR confirmed_at IS NOT NULL)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sale_items (
           id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           sale_id       uuid NOT NULL,
           product_id    uuid NOT NULL,
           price_id      uuid,
           qty           numeric(14,3) NOT NULL CHECK (qty > 0),
           unit_price    numeric(14,2) NOT NULL CHECK (unit_price >= 0),          -- snapshot HT
           unit_cost     numeric(14,4) NOT NULL DEFAULT 0 CHECK (unit_cost >= 0), -- CMP figé
           discount      numeric(14,2) NOT NULL DEFAULT 0 CHECK (discount >= 0),
           tax_rate      numeric(6,4)  NOT NULL DEFAULT 0                         -- V1.1 snapshot
                           CHECK (tax_rate >= 0 AND tax_rate < 1),
           net_amount    numeric(14,2) NOT NULL
                           GENERATED ALWAYS AS (round(qty * unit_price - discount, 2)) STORED,
           tax_amount    numeric(14,2) NOT NULL
                           GENERATED ALWAYS AS
                             (round((qty * unit_price - discount) * tax_rate, 2)) STORED,
           line_total    numeric(14,2) NOT NULL
                           GENERATED ALWAYS AS (round(qty * unit_price - discount, 2)
                            + round((qty * unit_price - discount) * tax_rate, 2)) STORED,
           created_at    timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT sale_items_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT sale_items_sale_fk FOREIGN KEY (company_id, sale_id)
             REFERENCES sales (company_id, id) ON DELETE CASCADE,
           CONSTRAINT sale_items_product_fk FOREIGN KEY (company_id, product_id)
             REFERENCES products (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT sale_items_price_fk FOREIGN KEY (company_id, price_id)
             REFERENCES product_prices (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT sale_items_discount_bounds CHECK (discount <= qty * unit_price)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sale_returns (
           id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id     uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           sale_id        uuid NOT NULL,
           return_no      text NOT NULL,
           reason         text,
           returned_at    timestamptz NOT NULL DEFAULT now(),
           total_refund   numeric(14,2) NOT NULL DEFAULT 0 CHECK (total_refund >= 0),
           refunded_total numeric(14,2) NOT NULL DEFAULT 0                        -- V1.1
                            CHECK (refunded_total >= 0),
           refund_status  return_refund_status NOT NULL DEFAULT 'pending',        -- V1.1
           created_by     uuid NOT NULL,
           created_at     timestamptz NOT NULL DEFAULT now(),
           updated_at     timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT sale_returns_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT sale_returns_no_uq     UNIQUE (company_id, return_no),
           CONSTRAINT sale_returns_sale_fk FOREIGN KEY (company_id, sale_id)
             REFERENCES sales (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT sale_returns_creator_fk FOREIGN KEY (company_id, created_by)
             REFERENCES users (company_id, id) ON DELETE RESTRICT,
           -- V1.1 : le double remboursement est structurellement impossible
           CONSTRAINT sale_returns_refund_cap CHECK (refunded_total <= total_refund)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sale_return_items (
           id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           return_id     uuid NOT NULL,
           sale_item_id  uuid NOT NULL,
           qty           numeric(14,3) NOT NULL CHECK (qty > 0),
           refund_amount numeric(14,2) NOT NULL CHECK (refund_amount >= 0),     -- TTC
           tax_refund    numeric(14,2) NOT NULL DEFAULT 0                       -- V1.1
                           CHECK (tax_refund >= 0),
           unit_cost     numeric(14,4) NOT NULL CHECK (unit_cost >= 0),         -- V1.1
           created_at    timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT sale_return_items_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT sale_return_items_return_fk FOREIGN KEY (company_id, return_id)
             REFERENCES sale_returns (company_id, id) ON DELETE CASCADE,
           CONSTRAINT sale_return_items_item_fk FOREIGN KEY (company_id, sale_item_id)
             REFERENCES sale_items (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT sale_return_items_tax_bounds CHECK (tax_refund <= refund_amount)
        )
        """
    )

    # ------------------------------------------------------------------ 8.6
    op.execute(
        """
        CREATE TABLE expense_categories (
           id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           name       text NOT NULL CHECK (length(btrim(name)) > 0),
           kind       expense_kind NOT NULL,
           created_at timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT expense_categories_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT expense_categories_name_uq   UNIQUE (company_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE expenses (
           id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           category_id uuid NOT NULL,
           supplier_id uuid,
           label       text NOT NULL CHECK (length(btrim(label)) > 0),
           amount      numeric(14,2) NOT NULL CHECK (amount > 0),
           spent_at    date NOT NULL CHECK (spent_at <= current_date + 1),
           created_by  uuid NOT NULL,
           created_at  timestamptz NOT NULL DEFAULT now(),
           updated_at  timestamptz NOT NULL DEFAULT now(),
           deleted_at  timestamptz,
           CONSTRAINT expenses_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT expenses_category_fk FOREIGN KEY (company_id, category_id)
             REFERENCES expense_categories (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT expenses_supplier_fk FOREIGN KEY (company_id, supplier_id)
             REFERENCES suppliers (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT expenses_creator_fk FOREIGN KEY (company_id, created_by)
             REFERENCES users (company_id, id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE debts (
           id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           party_type  party_type NOT NULL,
           customer_id uuid,
           supplier_id uuid,
           sale_id     uuid,
           expense_id  uuid,
           principal   numeric(14,2) NOT NULL CHECK (principal > 0),
           amount_paid numeric(14,2) NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
           balance     numeric(14,2) NOT NULL
                         GENERATED ALWAYS AS (principal - amount_paid) STORED,
           due_date    date,
           status      debt_status NOT NULL DEFAULT 'open',
           closed_at   timestamptz,
           created_at  timestamptz NOT NULL DEFAULT now(),
           updated_at  timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT debts_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT debts_customer_fk FOREIGN KEY (company_id, customer_id)
             REFERENCES customers (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT debts_supplier_fk FOREIGN KEY (company_id, supplier_id)
             REFERENCES suppliers (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT debts_sale_fk FOREIGN KEY (company_id, sale_id)
             REFERENCES sales (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT debts_expense_fk FOREIGN KEY (company_id, expense_id)
             REFERENCES expenses (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT debts_party_xor CHECK (
            (party_type = 'customer' AND customer_id IS NOT NULL AND supplier_id IS NULL)
         OR (party_type = 'supplier' AND supplier_id IS NOT NULL AND customer_id IS NULL)),
           CONSTRAINT debts_origin_one CHECK (num_nonnulls(sale_id, expense_id) <= 1),
           CONSTRAINT debts_paid_bounds CHECK (amount_paid <= principal),
           CONSTRAINT debts_closed_coherent CHECK (
            (status IN ('paid','written_off')) = (closed_at IS NOT NULL))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE payments (
           id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id     uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           direction      cash_direction NOT NULL,
           method         pay_method NOT NULL,
           amount         numeric(14,2) NOT NULL CHECK (amount > 0),
           paid_at        timestamptz NOT NULL DEFAULT now(),
           sale_id        uuid,
           expense_id     uuid,
           sale_return_id uuid,                                              -- V1.1
           reference      text,
           note           text,
           created_by     uuid NOT NULL,
           created_at     timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT payments_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT payments_sale_fk FOREIGN KEY (company_id, sale_id)
             REFERENCES sales (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT payments_expense_fk FOREIGN KEY (company_id, expense_id)
             REFERENCES expenses (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT payments_return_fk FOREIGN KEY (company_id, sale_return_id)
             REFERENCES sale_returns (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT payments_creator_fk FOREIGN KEY (company_id, created_by)
             REFERENCES users (company_id, id) ON DELETE RESTRICT,
           -- V1.1 : au plus un contexte direct, et sens financier cohérent
           CONSTRAINT payments_context_one CHECK (
            num_nonnulls(sale_id, expense_id, sale_return_id) <= 1),
           CONSTRAINT payments_return_outflow CHECK (
            sale_return_id IS NULL OR direction = 'outflow')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE payment_allocations (
           id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           payment_id uuid NOT NULL,
           debt_id    uuid NOT NULL,
           amount     numeric(14,2) NOT NULL CHECK (amount > 0),
           created_at timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT pa_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT pa_pair_uq   UNIQUE (company_id, payment_id, debt_id),
           CONSTRAINT pa_payment_fk FOREIGN KEY (company_id, payment_id)
             REFERENCES payments (company_id, id) ON DELETE CASCADE,
           CONSTRAINT pa_debt_fk FOREIGN KEY (company_id, debt_id)
             REFERENCES debts (company_id, id) ON DELETE RESTRICT
        )
        """
    )
    # V1.1 : lettrage retour <-> paiement, symétrique de payment_allocations.
    # Permet un remboursement échelonné, et un versement couvrant deux retours.
    op.execute(
        """
        CREATE TABLE sale_return_refunds (
           id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id     uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           sale_return_id uuid NOT NULL,
           payment_id     uuid NOT NULL,
           amount         numeric(14,2) NOT NULL CHECK (amount > 0),
           created_at     timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT srr_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT srr_pair_uq   UNIQUE (company_id, payment_id, sale_return_id),
           CONSTRAINT srr_return_fk FOREIGN KEY (company_id, sale_return_id)
             REFERENCES sale_returns (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT srr_payment_fk FOREIGN KEY (company_id, payment_id)
             REFERENCES payments (company_id, id) ON DELETE CASCADE
        )
        """
    )

    # ------------------------------------------------ numérotation (hors § 8)
    # Une ligne par entreprise et par type de document, verrouillée le temps de
    # la transaction : la séquence est continue, sans trou (ADR 0021).
    types = ",".join(f"'{document_type}'" for document_type in DOCUMENT_TYPES)
    op.execute(
        f"""
        CREATE TABLE document_counters (
           id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           document_type text NOT NULL CHECK (document_type IN ({types})),
           next_value    bigint NOT NULL DEFAULT 1 CHECK (next_value >= 1),
           CONSTRAINT document_counters_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT document_counters_type_uq   UNIQUE (company_id, document_type)
        )
        """
    )

    # ------------------------------------------------------------------ 8.7
    _sales_triggers()
    _return_triggers()
    _finance_triggers()

    for table in TABLES_WITH_UPDATED_AT:
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    # ----------------------------------------------------------------- 8.10
    # `company_id` est toujours la première colonne : la clause RLS est dans
    # 100 % des requêtes, un index qui ne commence pas par company_id est
    # inutilisable.
    for statement in (
        "CREATE INDEX sales_recent ON sales (company_id, sold_at DESC)",
        "CREATE INDEX sales_customer ON sales (company_id, customer_id, sold_at DESC)",
        "CREATE INDEX sales_confirmed ON sales (company_id, sold_at) WHERE status = 'confirmed'",
        "CREATE INDEX sales_sold_brin ON sales USING brin (sold_at)",
        "CREATE INDEX sale_items_sale ON sale_items (company_id, sale_id)",
        "CREATE INDEX sale_items_product ON sale_items (company_id, product_id)",
        "CREATE INDEX returns_sale ON sale_returns (company_id, sale_id)",
        "CREATE INDEX returns_recent ON sale_returns (company_id, returned_at DESC)",
        "CREATE INDEX returns_unpaid ON sale_returns (company_id, refund_status) "
        "WHERE refund_status IN ('pending','partial')",
        "CREATE INDEX sri_item ON sale_return_items (company_id, sale_item_id)",
        "CREATE INDEX srr_by_return ON sale_return_refunds (company_id, sale_return_id)",
        "CREATE INDEX srr_by_payment ON sale_return_refunds (company_id, payment_id)",
        "CREATE INDEX expenses_recent ON expenses (company_id, spent_at DESC)",
        "CREATE INDEX debts_party ON debts (company_id, party_type, status)",
        "CREATE INDEX debts_client ON debts (company_id, customer_id) WHERE status <> 'paid'",
        "CREATE INDEX debts_due ON debts (company_id, due_date) "
        "WHERE status IN ('open','partially_paid')",
        "CREATE INDEX payments_recent ON payments (company_id, paid_at DESC)",
        "CREATE INDEX payments_dir ON payments (company_id, direction, paid_at)",
        "CREATE INDEX payments_brin ON payments USING brin (paid_at)",
        "CREATE UNIQUE INDEX payments_ref_uq ON payments (company_id, reference) "
        "WHERE reference IS NOT NULL",
        "CREATE INDEX payments_sale ON payments (company_id, sale_id) WHERE sale_id IS NOT NULL",
        "CREATE INDEX pa_debt ON payment_allocations (company_id, debt_id)",
        "CREATE INDEX pa_payment ON payment_allocations (company_id, payment_id)",
        "CREATE INDEX debts_sale ON debts (company_id, sale_id) WHERE sale_id IS NOT NULL",
    ):
        op.execute(statement)

    # ------------------------------------------------------------ privilèges
    # Unique exception au « pas de DELETE » (ADR 0020) : retirer une ligne d'un
    # brouillon. `sale_items_no_change` borne ce droit à la vie du brouillon.
    op.execute(f"GRANT DELETE ON sale_items TO {APP_ROLE}")

    # ----------------------------------------------------------------- 8.11
    for table in TENANT_TABLES:
        _rls(table)


def _sales_triggers() -> None:
    """Totaux de vente et immuabilité des lignes (§ 8.7)."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sale_recompute_totals() RETURNS trigger AS $$
        DECLARE v_sale uuid; v_co uuid;
        BEGIN
           v_sale := COALESCE(NEW.sale_id, OLD.sale_id);
           v_co   := COALESCE(NEW.company_id, OLD.company_id);
           UPDATE sales s SET
              subtotal       = COALESCE(t.sub, 0),
              discount_total = COALESCE(t.dis, 0),
              tax_total      = COALESCE(t.tax, 0),
              updated_at     = now()
           FROM (SELECT SUM(qty * unit_price) sub, SUM(discount) dis, SUM(tax_amount) tax
                   FROM sale_items
                  WHERE company_id = v_co AND sale_id = v_sale) t
           WHERE s.company_id = v_co AND s.id = v_sale;
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER sale_items_totals AFTER INSERT OR UPDATE OR DELETE ON sale_items "
        "FOR EACH ROW EXECUTE FUNCTION sale_recompute_totals()"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION sale_items_frozen() RETURNS trigger AS $$
        DECLARE v_status sale_status;
        BEGIN
           SELECT status INTO v_status FROM sales
            WHERE company_id = COALESCE(NEW.company_id, OLD.company_id)
              AND id = COALESCE(NEW.sale_id, OLD.sale_id);
           IF v_status <> 'draft' THEN
              RAISE EXCEPTION 'Vente % : les lignes sont figees apres confirmation',
                 COALESCE(NEW.sale_id, OLD.sale_id) USING ERRCODE = 'restrict_violation';
           END IF;
           RETURN COALESCE(NEW, OLD);
        END $$ LANGUAGE plpgsql
        """
    )
    # Écart assumé au § 8.7 : l'INSERT est couvert lui aussi. Le § 8.7 laissait
    # la porte ouverte à l'ajout d'une ligne sur une vente confirmée, que
    # `sale_recompute_totals` aurait aussitôt répercuté sur ses totaux — alors
    # que le Diagramme 4 promet « plus aucune ligne modifiable » (ADR 0023).
    op.execute(
        "CREATE TRIGGER sale_items_no_change "
        "BEFORE INSERT OR UPDATE OR DELETE ON sale_items "
        "FOR EACH ROW EXECUTE FUNCTION sale_items_frozen()"
    )


def _return_triggers() -> None:
    """Retours : quantité bornée, total remboursable, statut, remboursements (§ 8.7)."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION return_item_check() RETURNS trigger AS $$
        DECLARE v_sold numeric(14,3); v_already numeric(14,3);
        BEGIN
           SELECT qty INTO v_sold FROM sale_items
            WHERE company_id = NEW.company_id AND id = NEW.sale_item_id FOR UPDATE;
           IF NOT FOUND THEN RAISE EXCEPTION 'Ligne de vente introuvable'; END IF;
           SELECT COALESCE(SUM(qty), 0) INTO v_already FROM sale_return_items
            WHERE company_id = NEW.company_id AND sale_item_id = NEW.sale_item_id
              AND id <> NEW.id;
           IF v_already + NEW.qty > v_sold THEN
              RAISE EXCEPTION 'Retour cumule % superieur a la quantite vendue %',
                 v_already + NEW.qty, v_sold USING ERRCODE = 'check_violation';
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER sri_check BEFORE INSERT OR UPDATE ON sale_return_items "
        "FOR EACH ROW EXECUTE FUNCTION return_item_check()"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION return_recompute() RETURNS trigger AS $$
        DECLARE v_ret uuid; v_co uuid;
        BEGIN
           v_ret := COALESCE(NEW.return_id, OLD.return_id);
           v_co  := COALESCE(NEW.company_id, OLD.company_id);
           UPDATE sale_returns r SET total_refund = COALESCE(t.s, 0), updated_at = now()
             FROM (SELECT SUM(refund_amount) s FROM sale_return_items
                    WHERE company_id = v_co AND return_id = v_ret) t
            WHERE r.company_id = v_co AND r.id = v_ret;
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER sri_totals AFTER INSERT OR UPDATE OR DELETE ON sale_return_items "
        "FOR EACH ROW EXECUTE FUNCTION return_recompute()"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION return_refund_status_set() RETURNS trigger AS $$
        BEGIN
           NEW.refund_status := CASE
              WHEN NEW.total_refund = 0                  THEN 'none_due'
              WHEN NEW.refunded_total = 0                THEN 'pending'
              WHEN NEW.refunded_total < NEW.total_refund THEN 'partial'
              ELSE 'settled' END::return_refund_status;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER sr_status BEFORE INSERT OR UPDATE OF total_refund, refunded_total "
        "ON sale_returns FOR EACH ROW EXECUTE FUNCTION return_refund_status_set()"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION refund_check() RETURNS trigger AS $$
        DECLARE v_due numeric(14,2); v_free numeric(14,2); v_dir cash_direction;
        BEGIN
           SELECT total_refund - refunded_total INTO v_due FROM sale_returns
            WHERE company_id = NEW.company_id AND id = NEW.sale_return_id FOR UPDATE;
           IF NOT FOUND THEN RAISE EXCEPTION 'Retour introuvable'; END IF;
           IF NEW.amount > v_due THEN
              RAISE EXCEPTION 'Remboursement % superieur au reste du %', NEW.amount, v_due
                 USING ERRCODE = 'check_violation';
           END IF;
           SELECT direction, amount - COALESCE(
                     (SELECT SUM(r.amount) FROM sale_return_refunds r
                       WHERE r.payment_id = p.id AND r.id <> NEW.id), 0)
             INTO v_dir, v_free
             FROM payments p
            WHERE p.company_id = NEW.company_id AND p.id = NEW.payment_id FOR UPDATE;
           IF v_dir <> 'outflow' THEN
              RAISE EXCEPTION 'Un remboursement de retour exige direction = outflow';
           END IF;
           IF NEW.amount > v_free THEN
              RAISE EXCEPTION 'Paiement sur-affecte : reste % disponible', v_free;
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER srr_check BEFORE INSERT OR UPDATE ON sale_return_refunds "
        "FOR EACH ROW EXECUTE FUNCTION refund_check()"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION refund_rollup() RETURNS trigger AS $$
        DECLARE v_ret uuid; v_co uuid;
        BEGIN
           v_ret := COALESCE(NEW.sale_return_id, OLD.sale_return_id);
           v_co  := COALESCE(NEW.company_id, OLD.company_id);
           UPDATE sale_returns r SET refunded_total = COALESCE(t.s, 0), updated_at = now()
             FROM (SELECT SUM(amount) s FROM sale_return_refunds
                    WHERE company_id = v_co AND sale_return_id = v_ret) t
            WHERE r.company_id = v_co AND r.id = v_ret;
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER srr_rollup AFTER INSERT OR UPDATE OR DELETE ON sale_return_refunds "
        "FOR EACH ROW EXECUTE FUNCTION refund_rollup()"
    )


def _finance_triggers() -> None:
    """Lettrage, solde de dette, plafond de crédit, `paid_total` de la vente (§ 8.7)."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION allocation_check() RETURNS trigger AS $$
        DECLARE v_bal numeric(14,2); v_free numeric(14,2);
        BEGIN
           SELECT balance INTO v_bal FROM debts
            WHERE company_id = NEW.company_id AND id = NEW.debt_id FOR UPDATE;
           IF NEW.amount > v_bal THEN
              RAISE EXCEPTION 'Affectation % superieure au solde restant %',
                 NEW.amount, v_bal USING ERRCODE = 'check_violation';
           END IF;
           SELECT p.amount - COALESCE((SELECT SUM(a.amount) FROM payment_allocations a
                                        WHERE a.payment_id = p.id AND a.id <> NEW.id), 0)
             INTO v_free FROM payments p
            WHERE p.company_id = NEW.company_id AND p.id = NEW.payment_id FOR UPDATE;
           IF NEW.amount > v_free THEN
              RAISE EXCEPTION 'Paiement sur-affecte : reste % disponible', v_free;
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER pa_check BEFORE INSERT OR UPDATE ON payment_allocations "
        "FOR EACH ROW EXECUTE FUNCTION allocation_check()"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION debt_rollup() RETURNS trigger AS $$
        DECLARE v_debt uuid; v_co uuid;
        BEGIN
           v_debt := COALESCE(NEW.debt_id, OLD.debt_id);
           v_co   := COALESCE(NEW.company_id, OLD.company_id);
           UPDATE debts d SET
              amount_paid = COALESCE(t.s, 0),
              status = CASE WHEN COALESCE(t.s, 0) = 0          THEN 'open'
                            WHEN COALESCE(t.s, 0) < d.principal THEN 'partially_paid'
                            ELSE 'paid' END::debt_status,
              closed_at = CASE WHEN COALESCE(t.s, 0) >= d.principal THEN now() END,
              updated_at = now()
           FROM (SELECT SUM(amount) s FROM payment_allocations
                  WHERE company_id = v_co AND debt_id = v_debt) t
           WHERE d.company_id = v_co AND d.id = v_debt AND d.status <> 'written_off';
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER pa_rollup AFTER INSERT OR UPDATE OR DELETE ON payment_allocations "
        "FOR EACH ROW EXECUTE FUNCTION debt_rollup()"
    )

    # Écart assumé au § 8.7 : `CG030` au lieu de `check_violation`, qui désigne
    # déjà `debts_paid_bounds` et `sales_discount_bounds` (même motif qu'ADR 0018).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION debt_credit_limit() RETURNS trigger AS $$
        DECLARE v_limit numeric(14,2); v_open numeric(14,2);
        BEGIN
           IF NEW.party_type <> 'customer' THEN RETURN NEW; END IF;
           SELECT credit_limit INTO v_limit FROM customers
            WHERE company_id = NEW.company_id AND id = NEW.customer_id;
           IF v_limit IS NULL THEN RETURN NEW; END IF;
           SELECT COALESCE(SUM(balance), 0) INTO v_open FROM debts
            WHERE company_id = NEW.company_id AND customer_id = NEW.customer_id
              AND status IN ('open','partially_paid') AND id <> NEW.id;
           IF v_open + NEW.principal > v_limit THEN
              RAISE EXCEPTION 'Plafond de credit depasse : % + % > %',
                 v_open, NEW.principal, v_limit USING ERRCODE = 'CG030';
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER debts_credit_limit BEFORE INSERT ON debts "
        "FOR EACH ROW EXECUTE FUNCTION debt_credit_limit()"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION sale_paid_rollup() RETURNS trigger AS $$
        DECLARE v_sale uuid; v_co uuid;
        BEGIN
           v_sale := COALESCE(NEW.sale_id, OLD.sale_id);
           IF v_sale IS NULL THEN RETURN NULL; END IF;
           v_co := COALESCE(NEW.company_id, OLD.company_id);
           UPDATE sales s SET paid_total = COALESCE(t.s, 0), updated_at = now()
             FROM (SELECT SUM(amount) s FROM payments
                    WHERE company_id = v_co AND sale_id = v_sale AND direction = 'inflow') t
            WHERE s.company_id = v_co AND s.id = v_sale;
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER payments_sale_rollup AFTER INSERT OR UPDATE OR DELETE ON payments "
        "FOR EACH ROW EXECUTE FUNCTION sale_paid_rollup()"
    )


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")

    op.execute(f"REVOKE DELETE ON sale_items FROM {APP_ROLE}")

    for table in TABLES_WITH_UPDATED_AT:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_set_updated_at ON {table}")

    for trigger, table in (
        ("payments_sale_rollup", "payments"),
        ("debts_credit_limit", "debts"),
        ("pa_rollup", "payment_allocations"),
        ("pa_check", "payment_allocations"),
        ("srr_rollup", "sale_return_refunds"),
        ("srr_check", "sale_return_refunds"),
        ("sr_status", "sale_returns"),
        ("sri_totals", "sale_return_items"),
        ("sri_check", "sale_return_items"),
        ("sale_items_no_change", "sale_items"),
        ("sale_items_totals", "sale_items"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")

    for function in (
        "sale_paid_rollup",
        "debt_credit_limit",
        "debt_rollup",
        "allocation_check",
        "refund_rollup",
        "refund_check",
        "return_refund_status_set",
        "return_recompute",
        "return_item_check",
        "sale_items_frozen",
        "sale_recompute_totals",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")

    # Ordre inverse des dépendances : les lettrages référencent les paiements,
    # qui référencent les ventes, les retours et les dépenses.
    for table in (
        "document_counters",
        "sale_return_refunds",
        "payment_allocations",
        "payments",
        "debts",
        "expenses",
        "expense_categories",
        "sale_return_items",
        "sale_returns",
        "sale_items",
        "sales",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
