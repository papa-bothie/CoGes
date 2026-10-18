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


def downgrade() -> None:
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
            f"CREATE UNIQUE INDEX {name} ON users (company_id, {column}) "
            "WHERE deleted_at IS NULL"
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
