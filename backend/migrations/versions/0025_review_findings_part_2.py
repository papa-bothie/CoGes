"""Correctifs de la revue de code, partie 2 (prompt 21, ADR 0088).

* **P2.1** — `users_revoke_sessions` : un mot de passe changé, un compte désactivé ou
  supprimé révoque **en base** toutes les sessions de la personne. Le module Users ne
  peut pas appeler Auth (Auth dépend de lui) : la règle descend en base, sur le
  précédent de l'ADR 0014. Une connexion réussie, qui ne touche que `last_login_at`,
  ne déclenche rien.
* **P2.11** — trois refus que le Référentiel ne peut pas tenir seul (il est sous
  Inventory et Finance), en base comme `categories_guard_soft_delete` (ADR 0014) :
  `CG003` changer `is_stock_tracked` d'un article qui a des mouvements, `CG004`
  supprimer un article qui a du stock, `CG005` supprimer un client qui a une dette
  ouverte.
* **P2.13** — `sale_recompute_totals` arrondit le sous-total **ligne par ligne**, comme
  `net_amount` et `line_total` : total de la vente = somme de ses lignes, même au kilo.
  Les brouillons sont recalculés (aucun effet de bord) ; les ventes confirmées restent
  telles quelles, leurs dettes et paiements ayant été calculés sur leur total (choix du
  propriétaire). Leur nombre d'écarts est écrit dans le journal de migration.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _revoke_sessions_on_access_change()
    _referential_guards()
    op.execute(_RECOMPUTE.format(subtotal="SUM(round(qty * unit_price, 2))"))
    _recompute_drafts_and_count_confirmed_gaps()


def downgrade() -> None:
    op.execute(_RECOMPUTE.format(subtotal="SUM(qty * unit_price)"))
    op.execute("DROP TRIGGER IF EXISTS customers_guard_soft_delete ON customers")
    op.execute("DROP FUNCTION IF EXISTS customers_guard_soft_delete()")
    op.execute("DROP TRIGGER IF EXISTS products_guard_stock ON products")
    op.execute("DROP FUNCTION IF EXISTS products_guard_stock()")
    op.execute("DROP TRIGGER IF EXISTS users_revoke_sessions ON users")
    op.execute("DROP FUNCTION IF EXISTS users_revoke_sessions()")


def _revoke_sessions_on_access_change() -> None:
    # SECURITY INVOKER : `coges_app` révoque déjà des sessions (rotation, déconnexion),
    # sous la RLS de l'entreprise du contexte.
    op.execute(
        """
        CREATE FUNCTION users_revoke_sessions() RETURNS trigger AS $$
        BEGIN
           UPDATE auth_sessions
              SET revoked_at = now()
            WHERE company_id = NEW.company_id
              AND user_id = NEW.id
              AND revoked_at IS NULL;
           RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER users_revoke_sessions
        AFTER UPDATE OF password_hash, is_active, deleted_at ON users
        FOR EACH ROW
        WHEN (OLD.password_hash IS DISTINCT FROM NEW.password_hash
              OR (OLD.is_active AND NOT NEW.is_active)
              OR (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL))
        EXECUTE FUNCTION users_revoke_sessions()
        """
    )


def _referential_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION products_guard_stock() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
           IF OLD.is_stock_tracked IS DISTINCT FROM NEW.is_stock_tracked
              AND EXISTS (SELECT 1 FROM inventory_movements m
                           WHERE m.company_id = OLD.company_id AND m.product_id = OLD.id) THEN
              RAISE EXCEPTION USING ERRCODE = 'CG003',
                 MESSAGE = 'Cet article a déjà des mouvements de stock.';
           END IF;
           IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL
              AND EXISTS (SELECT 1 FROM product_stock s
                           WHERE s.company_id = OLD.company_id AND s.product_id = OLD.id
                             AND s.qty_on_hand <> 0) THEN
              RAISE EXCEPTION USING ERRCODE = 'CG004',
                 MESSAGE = 'Cet article a encore du stock.';
           END IF;
           RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER products_guard_stock BEFORE UPDATE ON products
          FOR EACH ROW
          WHEN (OLD.is_stock_tracked IS DISTINCT FROM NEW.is_stock_tracked
                OR (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL))
          EXECUTE FUNCTION products_guard_stock()
        """
    )
    op.execute(
        """
        CREATE FUNCTION customers_guard_soft_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
           IF EXISTS (SELECT 1 FROM debts d
                       WHERE d.company_id = OLD.company_id AND d.customer_id = OLD.id
                         AND d.status IN ('open', 'partially_paid')) THEN
              RAISE EXCEPTION USING ERRCODE = 'CG005',
                 MESSAGE = 'Ce client a encore une dette ouverte.';
           END IF;
           RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER customers_guard_soft_delete BEFORE UPDATE ON customers
          FOR EACH ROW
          WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)
          EXECUTE FUNCTION customers_guard_soft_delete()
        """
    )


_RECOMPUTE = """
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
           FROM (SELECT {subtotal} sub, SUM(discount) dis, SUM(tax_amount) tax
                   FROM sale_items
                  WHERE company_id = v_co AND sale_id = v_sale) t
           WHERE s.company_id = v_co AND s.id = v_sale;
           RETURN NULL;
        END $$ LANGUAGE plpgsql
"""


def _recompute_drafts_and_count_confirmed_gaps() -> None:
    # `sales` est sous RLS FORCE : levé le temps de ces seules lectures et écritures
    # de données (révision 0019).
    op.execute("ALTER TABLE sales NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE sales s
           SET subtotal = t.sub, updated_at = now()
          FROM (SELECT sale_id, SUM(round(qty * unit_price, 2)) AS sub
                  FROM sale_items GROUP BY sale_id) t
         WHERE t.sale_id = s.id AND s.status = 'draft' AND s.subtotal <> t.sub
        """
    )
    op.execute(
        """
        DO $$
        DECLARE gaps integer;
        BEGIN
           SELECT count(*) INTO gaps
             FROM sales s
             JOIN (SELECT sale_id, SUM(round(qty * unit_price, 2)) AS sub
                     FROM sale_items GROUP BY sale_id) t ON t.sale_id = s.id
            WHERE s.status <> 'draft' AND s.subtotal <> t.sub;
           RAISE NOTICE 'Ventes confirmées dont le sous-total diffère de leurs lignes, laissées telles quelles : %', gaps;
        END $$
        """
    )
    op.execute("ALTER TABLE sales FORCE ROW LEVEL SECURITY")
