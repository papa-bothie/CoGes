"""Référentiels : tiers, catégories, produits, prix historisés.

Bande B du Diagramme 3. Reprend le § 8.3 du Modèle de données V1.1 (noms de
contraintes compris), les index du § 8.10 et la RLS du § 8.11.

Deux points à retenir :

* **`product_stock` n'est pas créée ici.** C'est une projection du journal
  `inventory_movements`, qui n'existe pas encore : elle appartient à la phase 04,
  avec le trigger qui l'alimente. Créer la table sans son trigger laisserait croire
  qu'elle peut être écrite à la main, ce qu'aucun code n'a le droit de faire.
* **Aucun prix sur `products`.** Le prix de vente et le coût vivent uniquement dans
  `product_prices`, par intervalles. La contrainte `product_prices_no_overlap`
  (EXCLUDE gist) rend l'ambiguïté tarifaire impossible **en base** : deux intervalles
  qui se chevauchent pour un même produit sont rejetés, y compris en concurrence.

Privilèges : rien à accorder. Les `ALTER DEFAULT PRIVILEGES` posés par la révision
0001 couvrent automatiquement ces tables (SELECT, INSERT, UPDATE pour `coges_app`),
et le DELETE n'est jamais accordé — T36 échouerait si l'une d'elles le recevait.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables tenant-scoped créées par cette révision (§ 8.11).
TENANT_TABLES = ("customers", "suppliers", "categories", "products", "product_prices")

# `product_prices` est immuable par construction (un intervalle se ferme, il ne se
# corrige pas) : elle ne porte pas d'`updated_at`, donc pas de trigger.
TABLES_WITH_UPDATED_AT = ("customers", "suppliers", "categories", "products")


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
    op.execute(
        """
        CREATE TABLE customers (
           id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id   uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           code         text,
           name         text NOT NULL CHECK (length(btrim(name)) > 0),
           phone        text,
           email        citext,
           credit_limit numeric(14,2) CHECK (credit_limit >= 0),
           created_at   timestamptz NOT NULL DEFAULT now(),
           updated_at   timestamptz NOT NULL DEFAULT now(),
           deleted_at   timestamptz,
           CONSTRAINT customers_tenant_uq UNIQUE (company_id, id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE suppliers (
           id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id         uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           code               text,
           name               text NOT NULL CHECK (length(btrim(name)) > 0),
           phone              text,
           payment_terms_days smallint CHECK (payment_terms_days BETWEEN 0 AND 365),
           created_at         timestamptz NOT NULL DEFAULT now(),
           updated_at         timestamptz NOT NULL DEFAULT now(),
           deleted_at         timestamptz,
           CONSTRAINT suppliers_tenant_uq UNIQUE (company_id, id)
        )
        """
    )

    # `categories_self_fk` est composite : une sous-catégorie ne peut pas avoir pour
    # parent la catégorie d'une autre entreprise, quelle que soit la RLS (barrière 1).
    op.execute(
        """
        CREATE TABLE categories (
           id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           parent_id  uuid,
           name       text NOT NULL CHECK (length(btrim(name)) > 0),
           created_at timestamptz NOT NULL DEFAULT now(),
           updated_at timestamptz NOT NULL DEFAULT now(),
           deleted_at timestamptz,
           CONSTRAINT categories_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT categories_self_fk FOREIGN KEY (company_id, parent_id)
             REFERENCES categories (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT categories_not_self CHECK (parent_id IS DISTINCT FROM id)
        )
        """
    )
    # Unicité du nom **par parent** : le COALESCE donne une clé aux racines, dont
    # le `parent_id` est NULL (NULL ne s'égale jamais à lui-même dans un index).
    # Restreinte aux lignes vivantes : un nom supprimé redevient disponible.
    op.execute(
        """
        CREATE UNIQUE INDEX categories_name_uq
          ON categories (company_id,
                         COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid),
                         name)
          WHERE deleted_at IS NULL
        """
    )

    # Aucune colonne de prix, de coût ni de stock : ce sont des faits datés, ils
    # vivent dans product_prices et inventory_movements (§ 2.1 et § 2.4).
    # Aucune notion de variante non plus — point d'extension documenté, non implémenté.
    op.execute(
        """
        CREATE TABLE products (
           id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id       uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           category_id      uuid,
           sku              text NOT NULL,
           barcode          text,
           name             text NOT NULL CHECK (length(btrim(name)) > 0),
           unit             text NOT NULL DEFAULT 'piece'
                            CHECK (unit IN ('piece','kg','litre','carton','metre','paquet')),
           is_stock_tracked boolean NOT NULL DEFAULT true,
           -- V1.1 : paramètre de saisie, jamais source de recalcul d'une vente passée.
           default_tax_rate numeric(6,4) NOT NULL DEFAULT 0
                            CHECK (default_tax_rate >= 0 AND default_tax_rate < 1),
           reorder_point    numeric(14,3) CHECK (reorder_point >= 0),
           is_active        boolean NOT NULL DEFAULT true,
           created_at       timestamptz NOT NULL DEFAULT now(),
           updated_at       timestamptz NOT NULL DEFAULT now(),
           deleted_at       timestamptz,
           CONSTRAINT products_tenant_uq   UNIQUE (company_id, id),
           CONSTRAINT products_sku_uq      UNIQUE (company_id, sku),
           CONSTRAINT products_category_fk FOREIGN KEY (company_id, category_id)
             REFERENCES categories (company_id, id) ON DELETE RESTRICT
        )
        """
    )

    # EXCLUDE sur `product_id` seul, sans `company_id` : c'est le § 8.3 tel quel.
    # `product_id` est globalement unique (PK de products), la contrainte couvre donc
    # déjà tous les tenants — l'ajout de company_id ne changerait rien (ADR 0011).
    op.execute(
        """
        CREATE TABLE product_prices (
           id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           product_id uuid NOT NULL,
           unit_price numeric(14,2) NOT NULL CHECK (unit_price > 0),
           cost_price numeric(14,4) CHECK (cost_price >= 0),
           valid_from timestamptz NOT NULL DEFAULT now(),
           valid_to   timestamptz,
           created_by uuid,
           created_at timestamptz NOT NULL DEFAULT now(),
           CONSTRAINT product_prices_tenant_uq UNIQUE (company_id, id),
           CONSTRAINT product_prices_product_fk FOREIGN KEY (company_id, product_id)
             REFERENCES products (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT product_prices_creator_fk FOREIGN KEY (company_id, created_by)
             REFERENCES users (company_id, id) ON DELETE RESTRICT,
           CONSTRAINT product_prices_range CHECK (valid_to IS NULL OR valid_to > valid_from),
           -- un seul prix valide à la fois : l'ambiguïté tarifaire est impossible
           CONSTRAINT product_prices_no_overlap EXCLUDE USING gist (
             product_id WITH =, tstzrange(valid_from, valid_to) WITH &&)
        )
        """
    )

    # ----------------------------------------------------------------- 8.10
    # `company_id` est toujours la première colonne : la clause RLS est dans 100 %
    # des requêtes, un index qui ne commence pas par company_id est inutilisable.
    op.execute(
        "CREATE UNIQUE INDEX customers_code_uq ON customers (company_id, code) "
        "WHERE code IS NOT NULL AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX suppliers_code_uq ON suppliers (company_id, code) "
        "WHERE code IS NOT NULL AND deleted_at IS NULL"
    )
    op.execute("CREATE INDEX customers_name ON customers (company_id, name)")
    # GIN trigram : recherche tolérante aux fautes de frappe (ADR 0013).
    op.execute("CREATE INDEX customers_name_trgm ON customers USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX suppliers_name_trgm ON suppliers USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX categories_parent ON categories (company_id, parent_id)")

    op.execute(
        "CREATE UNIQUE INDEX products_barcode_uq ON products (company_id, barcode) "
        "WHERE barcode IS NOT NULL AND deleted_at IS NULL"
    )
    op.execute("CREATE INDEX products_category ON products (company_id, category_id)")
    op.execute(
        "CREATE INDEX products_sellable ON products (company_id) "
        "WHERE is_active AND deleted_at IS NULL"
    )
    op.execute("CREATE INDEX products_name_trgm ON products USING gin (name gin_trgm_ops)")

    op.execute(
        "CREATE INDEX prices_history ON product_prices (company_id, product_id, valid_from DESC)"
    )
    op.execute(
        "CREATE INDEX prices_current ON product_prices (company_id, product_id) "
        "WHERE valid_to IS NULL"
    )

    # -------------------------------------- garde de suppression d'une catégorie
    # L'architecture donne à `Categories` **aucune dépendance** : le module ne peut
    # donc pas interroger `products` pour refuser la suppression d'une catégorie
    # encore utilisée. L'invariant descend en base, où il tient aussi contre une
    # écriture directe — c'est l'exigence du § 10 (un test qui ne passe que parce
    # que l'API a filtré ne compte pas). Voir ADR 0014.
    #
    # Deux SQLSTATE distincts, que le service traduit en codes d'erreur métier :
    #   CG001 -> category_has_children   CG002 -> category_not_empty
    op.execute(
        """
        CREATE FUNCTION categories_guard_soft_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
           IF EXISTS (SELECT 1 FROM categories c
                      WHERE c.company_id = OLD.company_id
                        AND c.parent_id  = OLD.id
                        AND c.deleted_at IS NULL) THEN
              RAISE EXCEPTION USING ERRCODE = 'CG001', MESSAGE = 'Cette catégorie contient des sous-catégories.';
           END IF;

           IF EXISTS (SELECT 1 FROM products p
                      WHERE p.company_id = OLD.company_id
                        AND p.category_id = OLD.id
                        AND p.deleted_at IS NULL
                        AND p.is_active) THEN
              RAISE EXCEPTION USING ERRCODE = 'CG002', MESSAGE = 'Cette catégorie contient des produits actifs.';
           END IF;

           RETURN NEW;
        END $$
        """
    )
    # `WHEN` limite le trigger au **passage** à l'état supprimé : une modification
    # ordinaire, ou une suppression rejouée, ne paie pas les deux EXISTS.
    op.execute(
        """
        CREATE TRIGGER categories_guard_soft_delete BEFORE UPDATE ON categories
          FOR EACH ROW
          WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)
          EXECUTE FUNCTION categories_guard_soft_delete()
        """
    )

    # -------------------------------------------------------- triggers updated_at
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    # ----------------------------------------------------------------- 8.11
    for table in TENANT_TABLES:
        _rls(table)


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")

    for table in TABLES_WITH_UPDATED_AT:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_set_updated_at ON {table}")

    op.execute("DROP TRIGGER IF EXISTS categories_guard_soft_delete ON categories")
    op.execute("DROP FUNCTION IF EXISTS categories_guard_soft_delete()")

    # Ordre inverse des dépendances : les prix référencent les produits, les
    # produits référencent les catégories.
    op.execute("DROP TABLE IF EXISTS product_prices")
    op.execute("DROP TABLE IF EXISTS products")
    op.execute("DROP TABLE IF EXISTS categories")
    op.execute("DROP TABLE IF EXISTS suppliers")
    op.execute("DROP TABLE IF EXISTS customers")
