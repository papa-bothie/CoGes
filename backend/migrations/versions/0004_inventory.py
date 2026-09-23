"""Stock : projection `product_stock`, journal `inventory_movements`, CMP.

Bande C du Diagramme 3. Reprend le § 8.3 (`product_stock`) et le § 8.5 **en entier**
du Modèle de données V1.1, les index du § 8.10 et la RLS du § 8.11.

Le principe du § 5.6 tient en une phrase : **un seul point d'entrée, l'insertion dans
`inventory_movements` ; aucun code applicatif n'écrit `product_stock`**. La quantité,
le CMP et la valeur de stock sont maintenus par le trigger `t20_inv_apply`, qui pose
un verrou de ligne sur la projection — c'est ce verrou qui sérialise deux caisses sur
le même article (T38).

Ordre des triggers `BEFORE INSERT` : PostgreSQL les déclenche dans l'**ordre
alphabétique** de leur nom. Les préfixes `t05_` / `t10_` / `t20_` sont donc
significatifs — valider avant d'appliquer :

1. `t05_inv_check_backdating` — fenêtre d'antidatage (ADR 0015) ;
2. `t10_inv_check_reversal`   — cohérence du mouvement inverse (§ 8.5) ;
3. `t20_inv_apply`            — stock, CMP, non-négativité (§ 8.5).

Écarts assumés au § 8.5, consignés dans l'ADR 0018 : seuls les `ERRCODE` de
`inv_apply_movement()` changent (`CG020` au lieu de `check_violation`, `CG021` au lieu
de `restrict_violation`). Le document réutilise des codes standard que le service ne
peut pas distinguer : `restrict_violation` désigne aussi l'immuabilité du journal
(T13) et `check_violation` aussi `inv_sign_coherent`. Messages et logique inchangés ;
l'immuabilité, elle, garde bien `restrict_violation`, exigé mot pour mot par T13.

Déjà en place, non recréé ici : l'ENUM `movement_type` et la fonction `cmp_next_avg`
(révision 0001), les permissions `inventory:*` (révision 0002).

Privilèges : rien à révoquer, contrairement à `audit_logs` (révision 0002). Le
réflexe serait de retirer UPDATE à `coges_app` sur un journal append-only, mais
`SELECT … FOR SHARE` exige précisément ce privilège : `inv_check_reversal()` ne
pourrait plus verrouiller le mouvement qu'il annule, et aucune annulation ne
passerait. L'immuabilité est de toute façon portée par `inv_no_update` et
`inv_no_delete`, qui tiennent contre **tous** les rôles — y compris le
propriétaire, qui détient les droits (T13). Le DELETE, lui, n'a jamais été accordé
(révision 0001). Voir l'ADR 0018.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables tenant-scoped créées par cette révision (§ 8.11).
TENANT_TABLES = ("product_stock", "inventory_movements")

# Fenêtre d'antidatage (ADR 0015, § 12.1 point 2 du Modèle).
BACKDATING_WINDOW = "48 hours"


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
    # ------------------------------------------------------------------ 8.3
    # PROJECTION : aucune vérité propre. `stock_value` est une colonne générée,
    # donc impossible à désynchroniser de la quantité et du CMP.
    op.execute(
        """
        CREATE TABLE product_stock (
           product_id       uuid PRIMARY KEY,
           company_id       uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           qty_on_hand      numeric(14,3) NOT NULL DEFAULT 0
                              CHECK (qty_on_hand >= 0),
           avg_cost         numeric(14,4) NOT NULL DEFAULT 0
                              CHECK (avg_cost >= 0),
           stock_value      numeric(14,2) NOT NULL
                              GENERATED ALWAYS AS (round(qty_on_hand * avg_cost, 2)) STORED,
           last_movement_at timestamptz,
           recomputed_at    timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT product_stock_tenant_uq UNIQUE (company_id, product_id),
           CONSTRAINT product_stock_product_fk FOREIGN KEY (company_id, product_id)
             REFERENCES products (company_id, id) ON DELETE RESTRICT
        )
        """
    )

    # ------------------------------------------------------------------ 8.5
    # APPEND-ONLY : source de vérité. Tout le reste s'en déduit.
    op.execute(
        """
        CREATE TABLE inventory_movements (
           id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id              uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           product_id              uuid NOT NULL,
           type                    movement_type NOT NULL,
           qty_delta               numeric(14,3) NOT NULL CHECK (qty_delta <> 0),
           unit_cost               numeric(14,4) NOT NULL CHECK (unit_cost >= 0),
           ref_type                text CHECK (ref_type IN ('sale_item','sale_return_item',
                                                            'manual','import','initial')),
           ref_id                  uuid,
           reversal_of_movement_id uuid,
           supplier_id             uuid,
           note                    text,
           occurred_at             timestamptz NOT NULL DEFAULT now(),
           created_by              uuid,
           created_at              timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT inv_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT inv_product_fk FOREIGN KEY (company_id, product_id)
             REFERENCES products (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT inv_supplier_fk FOREIGN KEY (company_id, supplier_id)
             REFERENCES suppliers (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT inv_creator_fk FOREIGN KEY (company_id, created_by)
             REFERENCES users (company_id, id) ON DELETE RESTRICT,
           -- FK auto-référente TENANT-AWARE vers le mouvement annulé (V1.1).
           CONSTRAINT inv_reversal_fk FOREIGN KEY (company_id, reversal_of_movement_id)
             REFERENCES inventory_movements (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT inv_reversal_not_self CHECK (reversal_of_movement_id IS DISTINCT FROM id),
           -- Un mouvement ne peut être annulé QU'UNE SEULE FOIS (V1.1).
           CONSTRAINT inv_reversal_uq UNIQUE (company_id, reversal_of_movement_id),
           CONSTRAINT inv_sign_coherent CHECK (
                (type IN ('initial','purchase_in','customer_return_in') AND qty_delta > 0)
             OR (type IN ('sale_out','supplier_return_out','loss')      AND qty_delta < 0)
             OR (type = 'adjustment')),
           CONSTRAINT inv_ref_pair CHECK (num_nonnulls(ref_type, ref_id) <> 1)
        )
        """
    )

    # Idempotence des mouvements DIRECTS uniquement : sans la clause partielle, le
    # mouvement inverse serait rejeté comme doublon de son origine, qui porte les
    # mêmes `ref_type` / `ref_id` (§ 4.8).
    op.execute(
        """
        CREATE UNIQUE INDEX inv_ref_idempotence
           ON inventory_movements (company_id, ref_type, ref_id)
         WHERE ref_id IS NOT NULL AND reversal_of_movement_id IS NULL
        """
    )

    # ----------------------------------------------------------------- 8.10
    op.execute("CREATE INDEX stock_threshold ON product_stock (company_id, qty_on_hand)")
    op.execute("CREATE INDEX stock_out ON product_stock (company_id) WHERE qty_on_hand = 0")
    op.execute(
        "CREATE INDEX inv_stock_calc ON inventory_movements "
        "(company_id, product_id, occurred_at DESC)"
    )
    op.execute("CREATE INDEX inv_ref_lookup ON inventory_movements (company_id, ref_type, ref_id)")
    op.execute("CREATE INDEX inv_occurred_brin ON inventory_movements USING brin (occurred_at)")

    # ------------------------------------------- immuabilité du journal (8.5)
    # Exception explicite plutôt qu'une RULE « DO INSTEAD NOTHING », qui masquait
    # un bug applicatif derrière un « 0 ligne modifiée ».
    op.execute(
        """
        CREATE FUNCTION inv_immutable() RETURNS trigger AS $$
        BEGIN
           RAISE EXCEPTION 'inventory_movements est append-only : % interdit. '
                           'Corriger par un mouvement inverse ou un ajustement.', TG_OP
             USING ERRCODE = 'restrict_violation';
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER inv_no_update BEFORE UPDATE ON inventory_movements "
        "FOR EACH ROW EXECUTE FUNCTION inv_immutable()"
    )
    op.execute(
        "CREATE TRIGGER inv_no_delete BEFORE DELETE ON inventory_movements "
        "FOR EACH ROW EXECUTE FUNCTION inv_immutable()"
    )

    # -------------------------------------------- antidatage (ADR 0015, P5)
    # Le CMP dépend de l'ordre des mouvements (§ 5.7) : un mouvement inséré avec un
    # `occurred_at` très antérieur rendrait le CMP courant différent du CMP
    # recalculé. On refuse au-delà de la fenêtre plutôt que de corriger la nuit :
    # c'est la recommandation du § 12.1, et c'est explicable au gérant.
    op.execute(
        f"""
        CREATE FUNCTION inv_check_backdating() RETURNS trigger AS $$
        DECLARE v_last timestamptz;
        BEGIN
           SELECT max(occurred_at) INTO v_last FROM inventory_movements
            WHERE company_id = NEW.company_id AND product_id = NEW.product_id;
           IF v_last IS NOT NULL
              AND NEW.occurred_at < v_last - interval '{BACKDATING_WINDOW}' THEN
              RAISE EXCEPTION USING ERRCODE = 'CG010',
                 MESSAGE = format(
                    'Antidatage refusé : produit %s, dernier mouvement le %s, '
                    'date demandée %s (fenêtre de {BACKDATING_WINDOW}).',
                    NEW.product_id, v_last, NEW.occurred_at);
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER t05_inv_check_backdating BEFORE INSERT ON inventory_movements "
        "FOR EACH ROW EXECUTE FUNCTION inv_check_backdating()"
    )

    # ------------------------------------- validation du mouvement inverse (8.5)
    op.execute(
        """
        CREATE FUNCTION inv_check_reversal() RETURNS trigger AS $$
        DECLARE o inventory_movements;
        BEGIN
           IF NEW.reversal_of_movement_id IS NULL THEN RETURN NEW; END IF;
           SELECT * INTO o FROM inventory_movements
            WHERE company_id = NEW.company_id AND id = NEW.reversal_of_movement_id
            FOR SHARE;
           IF NOT FOUND THEN
              RAISE EXCEPTION 'Mouvement à annuler introuvable dans ce tenant';
           END IF;
           IF o.reversal_of_movement_id IS NOT NULL THEN
              RAISE EXCEPTION 'On ne peut pas annuler une annulation (mouvement %)', o.id;
           END IF;
           IF o.product_id <> NEW.product_id THEN
              RAISE EXCEPTION 'Le mouvement inverse doit porter sur le même produit';
           END IF;
           IF NEW.qty_delta <> -o.qty_delta THEN
              RAISE EXCEPTION 'Quantité inverse attendue % , reçue %',
                 -o.qty_delta, NEW.qty_delta;
           END IF;
           NEW.unit_cost := o.unit_cost;   -- on rend la marchandise à son coût de sortie
           NEW.ref_type  := o.ref_type;    -- traçabilité conservée vers l'objet métier
           NEW.ref_id    := o.ref_id;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER t10_inv_check_reversal BEFORE INSERT ON inventory_movements "
        "FOR EACH ROW EXECUTE FUNCTION inv_check_reversal()"
    )

    # ------------------------------------------- application : stock + CMP (8.5)
    op.execute(
        """
        CREATE FUNCTION inv_apply_movement() RETURNS trigger AS $$
        DECLARE
           v_tracked boolean;
           v_qty numeric(14,3); v_avg numeric(14,4);
           v_new_qty numeric(14,3); v_new_avg numeric(14,4);
        BEGIN
           SELECT is_stock_tracked INTO v_tracked FROM products
            WHERE company_id = NEW.company_id AND id = NEW.product_id;
           IF NOT FOUND THEN
              RAISE EXCEPTION 'Produit % inconnu dans ce tenant', NEW.product_id;
           END IF;
           IF NOT v_tracked THEN
              RAISE EXCEPTION 'Produit % non suivi en stock : aucun mouvement autorisé',
                 NEW.product_id USING ERRCODE = 'CG021';
           END IF;

           INSERT INTO product_stock (product_id, company_id, qty_on_hand, avg_cost)
           VALUES (NEW.product_id, NEW.company_id, 0, 0)
           ON CONFLICT (product_id) DO NOTHING;

           -- verrou de ligne : sérialise deux caisses sur le même article (T38)
           SELECT qty_on_hand, avg_cost INTO v_qty, v_avg FROM product_stock
            WHERE product_id = NEW.product_id FOR UPDATE;

           IF NEW.qty_delta < 0 AND NEW.reversal_of_movement_id IS NULL THEN
              -- SORTIE : le coût de sortie est le CMP applicable à cet instant
              NEW.unit_cost := v_avg;
           END IF;

           v_new_qty := v_qty + NEW.qty_delta;
           IF v_new_qty < 0 THEN
              RAISE EXCEPTION
                 'Stock négatif interdit : produit %, disponible %, sortie demandée %',
                 NEW.product_id, v_qty, abs(NEW.qty_delta)
                 USING ERRCODE = 'CG020';
           END IF;
           -- Garde-fou inatteignable en l'état (`unit_cost` est NOT NULL) : conservé
           -- du § 8.5, il protège un futur assouplissement de la colonne.
           IF NEW.qty_delta > 0 AND NEW.unit_cost IS NULL THEN
              RAISE EXCEPTION 'Entrée de stock sans coût unitaire : CMP indéfinissable';
           END IF;

           v_new_avg := cmp_next_avg(v_qty, v_avg, NEW.qty_delta, NEW.unit_cost);

           UPDATE product_stock
              SET qty_on_hand      = v_new_qty,
                  avg_cost         = v_new_avg,
                  last_movement_at = GREATEST(COALESCE(last_movement_at, NEW.occurred_at),
                                              NEW.occurred_at)
            WHERE product_id = NEW.product_id;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER t20_inv_apply BEFORE INSERT ON inventory_movements "
        "FOR EACH ROW EXECUTE FUNCTION inv_apply_movement()"
    )

    # ---------------------------------------- reconstruction (§ 5.7, job nocturne)
    # Rejoue le journal dans l'ordre canonique et applique la MÊME formule CMP que
    # le trigger : aucune divergence possible entre temps réel et recalcul (T12).
    # `_rebuilt` est `ON COMMIT DROP` : un seul appel par transaction.
    op.execute(
        """
        CREATE FUNCTION rebuild_product_stock(p_company uuid)
        RETURNS TABLE (product_id uuid, qty_ecart numeric, avg_ecart numeric)
        LANGUAGE plpgsql AS $$
        DECLARE m record; v_qty numeric(14,3); v_avg numeric(14,4); v_prod uuid;
        BEGIN
           CREATE TEMP TABLE _rebuilt (product_id uuid PRIMARY KEY,
              qty numeric(14,3), avg numeric(14,4)) ON COMMIT DROP;
           v_prod := NULL;
           FOR m IN
              SELECT * FROM inventory_movements
                 WHERE company_id = p_company
                 ORDER BY product_id, occurred_at, id         -- ordre canonique
           LOOP
              IF v_prod IS DISTINCT FROM m.product_id THEN
                 IF v_prod IS NOT NULL THEN
                    INSERT INTO _rebuilt VALUES (v_prod, v_qty, v_avg);
                 END IF;
                 v_prod := m.product_id; v_qty := 0; v_avg := 0;
              END IF;
              v_avg := cmp_next_avg(v_qty, v_avg, m.qty_delta, m.unit_cost);
              v_qty := v_qty + m.qty_delta;
              IF v_qty < 0 THEN
                 RAISE WARNING 'État intermédiaire négatif : produit %, mouvement % '
                               '(antidatage probable)', m.product_id, m.id;
              END IF;
           END LOOP;
           IF v_prod IS NOT NULL THEN
              INSERT INTO _rebuilt VALUES (v_prod, v_qty, v_avg);
           END IF;

           RETURN QUERY
              SELECT r.product_id, r.qty - s.qty_on_hand, r.avg - s.avg_cost
                  FROM _rebuilt r JOIN product_stock s USING (product_id)
                 WHERE r.qty <> s.qty_on_hand OR r.avg <> s.avg_cost;

           UPDATE product_stock s
                 SET qty_on_hand = r.qty, avg_cost = r.avg, recomputed_at = now()
              FROM _rebuilt r
            WHERE s.product_id = r.product_id AND s.company_id = p_company;
        END $$
        """
    )

    # ----------------------------------------------------------------- 8.11
    for table in TENANT_TABLES:
        _rls(table)


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")

    op.execute("DROP TRIGGER IF EXISTS t20_inv_apply ON inventory_movements")
    op.execute("DROP TRIGGER IF EXISTS t10_inv_check_reversal ON inventory_movements")
    op.execute("DROP TRIGGER IF EXISTS t05_inv_check_backdating ON inventory_movements")
    op.execute("DROP TRIGGER IF EXISTS inv_no_delete ON inventory_movements")
    op.execute("DROP TRIGGER IF EXISTS inv_no_update ON inventory_movements")

    op.execute("DROP FUNCTION IF EXISTS rebuild_product_stock(uuid)")
    op.execute("DROP FUNCTION IF EXISTS inv_apply_movement()")
    op.execute("DROP FUNCTION IF EXISTS inv_check_reversal()")
    op.execute("DROP FUNCTION IF EXISTS inv_check_backdating()")
    op.execute("DROP FUNCTION IF EXISTS inv_immutable()")

    # Ordre inverse des dépendances : le journal référence la projection par produit.
    op.execute("DROP TABLE IF EXISTS inventory_movements")
    op.execute("DROP TABLE IF EXISTS product_stock")
