"""Correctifs de la revue de code, partie 1 (prompt 21, ADR 0087).

* **P1.1** — `outbox_release(bigint[])` rend la tentative que `outbox_claim` a consommée
  quand la publication a échoué faute de transport (Redis injoignable). Sans elle, une
  panne de quelques minutes mettait au rebut des événements sains. Propriétaire
  `coges_bus`, exécutable par le seul `coges_relay`, sur le patron
  d'`outbox_mark_published` (révision 0010).
* **P1.6** — `users_email_uq` et `users_phone_uq` deviennent des index uniques
  **partiels** (`WHERE deleted_at IS NULL`) : l'e-mail ou le téléphone d'un compte
  supprimé se réutilise. Les noms sont gardés, le service traduit leur violation en 422.
  Le retour arrière recrée les contraintes pleines ; un compte **supprimé** dont
  l'identifiant est repris ailleurs perd d'abord le sien (téléphone effacé, e-mail
  réécrit en `supprime-<id>@compte.invalid`), comme la révision 0019 réécrivait les
  e-mails manquants. Aucun compte vivant n'est touché.
* **P1.8** — l'inverse d'une **entrée** la retire au coût où elle est entrée :
  `cmp_next_avg(…, p_reversal)` rend (Q·A − q·c)/(Q − q), soit exactement le CMP
  d'avant l'entrée. `inv_apply_movement` et `rebuild_product_stock` appellent tous deux
  cette forme : une seule formule, en direct comme à la reconstruction (T12). Sous le
  verrou de `product_stock`, le trigger refuse (`CG022`) l'inverse d'une entrée qu'un
  autre mouvement du même produit a suivie : le coût des ventes suivantes reposait sur
  elle. Le premier recalcul de nuit corrige le CMP des articles dont une entrée avait
  déjà été annulée (écart signalé, attendu).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUS_ROLE = "coges_bus"
RELAY_ROLE = "coges_relay"

RELEASE = "outbox_release(bigint[])"


#: Unicité des identifiants de connexion, par entreprise, sur les comptes vivants.
USER_IDENTIFIERS = (("users_email_uq", "email"), ("users_phone_uq", "phone"))


def upgrade() -> None:
    _outbox_release()
    _live_user_identifiers()
    _entry_reversal_restores_the_cmp()


def downgrade() -> None:
    op.execute(
        _APPLY.format(cmp="cmp_next_avg(v_qty, v_avg, NEW.qty_delta, NEW.unit_cost)", guard="")
    )
    op.execute(_REBUILD.format(cmp="cmp_next_avg(v_qty, v_avg, m.qty_delta, m.unit_cost)"))
    op.execute("DROP FUNCTION IF EXISTS cmp_next_avg(numeric, numeric, numeric, numeric, boolean)")
    _free_identifiers_of_deleted_accounts()
    for name, column in USER_IDENTIFIERS:
        op.execute(f"DROP INDEX {name}")
        op.execute(f"ALTER TABLE users ADD CONSTRAINT {name} UNIQUE (company_id, {column})")
    op.execute(f"DROP FUNCTION IF EXISTS {RELEASE}")


def _live_user_identifiers() -> None:
    # `auth_lookup` filtre déjà `deleted_at IS NULL` : il ne rend qu'un compte vivant,
    # et l'index garantit qu'il n'y en a qu'un par identifiant.
    for name, column in USER_IDENTIFIERS:
        op.execute(f"ALTER TABLE users DROP CONSTRAINT {name}")
        op.execute(
            f"CREATE UNIQUE INDEX {name} ON users (company_id, {column}) WHERE deleted_at IS NULL"
        )


def _free_identifiers_of_deleted_accounts() -> None:
    # `users` est sous RLS FORCE : levé le temps de ces seules mises à jour (révision 0019).
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    placeholder = "'supprime-' || replace(u.id::text, '-', '') || '@compte.invalid'"
    op.execute(
        f"""
        UPDATE users u
           SET phone = NULL,
               email = coalesce(u.email, {placeholder})
         WHERE u.deleted_at IS NOT NULL AND u.phone IS NOT NULL
           AND EXISTS (SELECT 1 FROM users o
                        WHERE o.company_id = u.company_id AND o.phone = u.phone
                          AND o.id <> u.id)
        """
    )
    op.execute(
        f"""
        UPDATE users u
           SET email = {placeholder}
         WHERE u.deleted_at IS NOT NULL
           AND EXISTS (SELECT 1 FROM users o
                        WHERE o.company_id = u.company_id AND o.email = u.email
                          AND o.id <> u.id)
        """
    )
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")


def _outbox_release() -> None:
    # Ne touche qu'aux événements encore en attente et jamais sous zéro : un appel
    # rejoué ou tardif ne peut rien abîmer.
    op.execute(
        """
        CREATE FUNCTION outbox_release(p_ids bigint[])
        RETURNS integer
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $fn$
           WITH released AS (
              UPDATE public.business_events
                 SET attempts = attempts - 1
               WHERE id = ANY(p_ids)
                 AND published_at IS NULL
                 AND attempts > 0
              RETURNING 1)
           SELECT count(*)::integer FROM released
        $fn$
        """
    )
    # Droits **avant** le transfert de propriété (révision 0010).
    op.execute(f"REVOKE ALL ON FUNCTION {RELEASE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {RELEASE} TO {RELAY_ROLE}")
    op.execute(f"GRANT CREATE ON SCHEMA public TO {BUS_ROLE}")
    op.execute(f"ALTER FUNCTION {RELEASE} OWNER TO {BUS_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {BUS_ROLE}")


# --------------------------------------------------------------------------- P1.8
# Les deux fonctions de la révision 0004, en gabarit : `downgrade` les rend telles
# quelles, `upgrade` y place la nouvelle formule et le refus `CG022`.

_SUPERSEDED_GUARD = """
           -- Inverse d'une entrée : refusé si un autre mouvement du produit l'a
           -- suivie (ADR 0087). Lu sous le verrou de `product_stock` : aucun
           -- mouvement du produit ne peut s'intercaler entre ce contrôle et l'écriture.
           IF NEW.qty_delta < 0 AND NEW.reversal_of_movement_id IS NOT NULL THEN
              SELECT created_at, occurred_at INTO v_origin_created, v_origin_occurred
                FROM inventory_movements
               WHERE company_id = NEW.company_id AND id = NEW.reversal_of_movement_id;
              IF EXISTS (
                 SELECT 1 FROM inventory_movements m
                  WHERE m.company_id = NEW.company_id
                    AND m.product_id = NEW.product_id
                    AND m.id <> NEW.reversal_of_movement_id
                    AND (m.created_at > v_origin_created OR m.occurred_at > v_origin_occurred))
              THEN
                 RAISE EXCEPTION
                    'Entrée % suivie d''autres mouvements : corriger par un ajustement daté',
                    NEW.reversal_of_movement_id USING ERRCODE = 'CG022';
              END IF;
           END IF;
"""

_APPLY = """
        CREATE OR REPLACE FUNCTION inv_apply_movement() RETURNS trigger AS $$
        DECLARE
           v_tracked boolean;
           v_qty numeric(14,3); v_avg numeric(14,4);
           v_new_qty numeric(14,3); v_new_avg numeric(14,4);
           v_origin_created timestamptz; v_origin_occurred timestamptz;
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
{guard}
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

           v_new_avg := {cmp};

           UPDATE product_stock
              SET qty_on_hand      = v_new_qty,
                  avg_cost         = v_new_avg,
                  last_movement_at = GREATEST(COALESCE(last_movement_at, NEW.occurred_at),
                                              NEW.occurred_at)
            WHERE product_id = NEW.product_id;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
"""

_REBUILD = """
        CREATE OR REPLACE FUNCTION rebuild_product_stock(p_company uuid)
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
              v_avg := {cmp};
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


def _entry_reversal_restores_the_cmp() -> None:
    # Surcharge à cinq arguments : la forme à quatre reste, inchangée, pour ce qui
    # l'appelle déjà. Une sortie ordinaire garde le CMP ; l'inverse d'une entrée la
    # retire à son coût. Stock ramené à zéro : CMP gardé, comme T11. Jamais négatif,
    # même sur un historique antérieur à la règle.
    op.execute(
        """
        CREATE FUNCTION cmp_next_avg(
           p_qty numeric, p_avg numeric, p_delta numeric, p_cost numeric,
           p_reversal boolean)
        RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
           SELECT CASE
              WHEN p_reversal AND p_delta < 0 AND p_qty + p_delta > 0
                 THEN GREATEST(round((p_qty * p_avg + p_delta * p_cost) / (p_qty + p_delta), 4), 0)
              ELSE cmp_next_avg(p_qty, p_avg, p_delta, p_cost)
           END;
        $$
        """
    )
    op.execute(
        _APPLY.format(
            cmp="cmp_next_avg(v_qty, v_avg, NEW.qty_delta, NEW.unit_cost,\n"
            "                                    NEW.reversal_of_movement_id IS NOT NULL)",
            guard=_SUPERSEDED_GUARD,
        )
    )
    op.execute(
        _REBUILD.format(
            cmp="cmp_next_avg(v_qty, v_avg, m.qty_delta, m.unit_cost,\n"
            "                                   m.reversal_of_movement_id IS NOT NULL)"
        )
    )
