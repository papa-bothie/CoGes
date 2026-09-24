"""Le plafond de crédit se vérifie sous verrou, sinon il ne se vérifie pas.

`debt_credit_limit()`, tel que la révision 0006 le reprend du § 8.7, lit
`customers.credit_limit` puis somme les dettes ouvertes du client — **sans aucun
verrou**. C'est une vérification « lire puis décider » sur une agrégation, et elle ne
tient pas sous concurrence : deux transactions simultanées lisent toutes les deux un
encours de 0, concluent toutes les deux que le crédit passe, et le client ressort
engagé au double de son plafond.

Reproduit : plafond 1 000, deux dettes de 800 ouvertes en parallèle, encours final
1 600. Aucune contrainte déclarative ne peut rattraper cela — la règle du § 5.5 porte
sur une **somme de lignes**, pas sur une ligne.

Le correctif ajoute `FOR UPDATE` à la lecture du plafond. Il ne protège pas
`customers`, que ce trigger ne modifie jamais : il en fait un **point de rendez-vous**.
Deux ouvertures de dette pour le même client s'y sérialisent, et la seconde, qui
reprend la main après le COMMIT de la première, somme en `READ COMMITTED` un encours
qui contient déjà celle-ci. C'est la même mécanique que le `SELECT … FOR UPDATE` sur
`product_stock` dans `inv_apply_movement` (§ 8.5, T38) : verrouiller la ligne qui
désigne la ressource partagée, pas celles qu'on s'apprête à écrire.

Le verrou est pris **avant** la somme, et pour tout client — y compris ceux dont le
plafond est `NULL`. On ne peut pas savoir qu'il n'y a pas de plafond sans lire la
ligne, et la lire sans la verrouiller ramènerait le problème.

Privilèges : rien à accorder. `SELECT … FOR UPDATE` exige `UPDATE` en plus de
`SELECT`, et `coges_app` l'a sur `customers` par les `ALTER DEFAULT PRIVILEGES` de la
révision 0001 — c'est la leçon de l'ADR 0018, décision 3, qui avait failli être perdue
sur `inventory_movements`. Un `REVOKE UPDATE ON customers` casserait ce trigger.

Pourquoi une révision séparée plutôt qu'une retouche de la 0006 : la 0006 est déjà
livrable, et une migration livrée ne se réécrit pas.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION debt_credit_limit() RETURNS trigger AS $$
        DECLARE v_limit numeric(14,2); v_open numeric(14,2);
        BEGIN
           IF NEW.party_type <> 'customer' THEN RETURN NEW; END IF;
           -- Point de rendez-vous : deux ouvertures de crédit pour le même client
           -- se sérialisent ici. Sans ce verrou, toutes deux sommeraient le même
           -- encours périmé et passeraient (révision 0007).
           SELECT credit_limit INTO v_limit FROM customers
            WHERE company_id = NEW.company_id AND id = NEW.customer_id
            FOR UPDATE;
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


def downgrade() -> None:
    # Corps de la révision 0006, restitué mot pour mot : sans verrou, donc faux
    # sous concurrence. Un downgrade rétablit un état, il ne le corrige pas.
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
