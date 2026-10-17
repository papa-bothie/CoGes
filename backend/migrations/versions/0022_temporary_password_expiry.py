"""Échéance du mot de passe provisoire et alerte d'échecs de connexion (ADR 0078, lot A).

* `users.must_change_password_until` : posée à `now() + COGES_TEMP_PASSWORD_TTL_HOURS`
  par l'application chaque fois qu'un mot de passe provisoire est donné, effacée quand
  la personne choisit le sien. Les comptes déjà provisoires au moment de la migration
  gardent `NULL` : sans échéance (décision du lot A) ;
* `users_temp_password_coherent` : une échéance n'existe que pour un compte qui doit
  changer son mot de passe ;
* `auth_lookup` rend aussi `must_change_password` et `must_change_password_until` : la
  connexion refuse un provisoire expiré **après** avoir vérifié le mot de passe. Le type
  de retour change, donc la fonction est supprimée puis recréée sous son propriétaire
  `coges_auth`, avec exactement les mêmes droits (révision 0002) ;
* `notifications.type` admet `login_failures` (écart assumé au § 8.8, ADR 0078).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOOKUP_WITH_EXPIRY = """
    CREATE FUNCTION auth_lookup(p_slug citext, p_email citext)
    RETURNS TABLE (company_id uuid, user_id uuid, password_hash text, is_active boolean,
                   must_change_password boolean, must_change_password_until timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public AS $fn$
       SELECT c.id, u.id, u.password_hash, u.is_active,
              u.must_change_password, u.must_change_password_until
       FROM public.companies c
       JOIN public.users u ON u.company_id = c.id
       WHERE c.slug = p_slug
         AND CASE WHEN strpos(p_email::text, '@') > 0
                  THEN u.email = p_email
                  ELSE u.phone = p_email::text
             END
         AND c.deleted_at IS NULL
         AND u.deleted_at IS NULL
    $fn$
"""

_LOOKUP_WITHOUT_EXPIRY = """
    CREATE FUNCTION auth_lookup(p_slug citext, p_email citext)
    RETURNS TABLE (company_id uuid, user_id uuid, password_hash text, is_active boolean)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public AS $fn$
       SELECT c.id, u.id, u.password_hash, u.is_active
       FROM public.companies c
       JOIN public.users u ON u.company_id = c.id
       WHERE c.slug = p_slug
         AND CASE WHEN strpos(p_email::text, '@') > 0
                  THEN u.email = p_email
                  ELSE u.phone = p_email::text
             END
         AND c.deleted_at IS NULL
         AND u.deleted_at IS NULL
    $fn$
"""

_TYPES_BEFORE = (
    "'stock_low','stock_out','debt_due','sale_cancelled','forecast_alert','insight_critical'"
)
_TYPES_AFTER = f"{_TYPES_BEFORE},'login_failures'"


def _recreate_lookup(definition: str) -> None:
    """Recrée `auth_lookup` sous `coges_auth`, avec les droits de la révision 0002.

    `CREATE OR REPLACE` ne peut pas changer un `RETURNS TABLE` : il faut supprimer, ce
    que seul le propriétaire peut faire. CREATE sur le schéma est accordé puis retiré
    aussitôt, comme en révisions 0002 et 0019 : `coges_auth` ne doit pouvoir créer aucun
    objet en dehors de cette instruction.
    """
    op.execute("GRANT CREATE ON SCHEMA public TO coges_auth")
    op.execute("SET LOCAL ROLE coges_auth")
    op.execute("DROP FUNCTION auth_lookup(citext, citext)")
    op.execute(definition)
    op.execute("REVOKE ALL ON FUNCTION auth_lookup(citext, citext) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_lookup(citext, citext) TO coges_app")
    op.execute("RESET ROLE")
    op.execute("REVOKE CREATE ON SCHEMA public FROM coges_auth")


def _notification_types(types: str) -> None:
    op.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_type_check")
    op.execute(
        f"ALTER TABLE notifications ADD CONSTRAINT notifications_type_check "
        f"CHECK (type IN ({types}))"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN must_change_password_until timestamptz")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_temp_password_coherent "
        "CHECK (must_change_password_until IS NULL OR must_change_password)"
    )
    _recreate_lookup(_LOOKUP_WITH_EXPIRY)
    _notification_types(_TYPES_AFTER)


def downgrade() -> None:
    # Une alerte de ce type ne survivrait pas au CHECK d'origine. `notifications` est
    # sous RLS FORCE : FORCE est levé le temps de cette seule suppression de données.
    op.execute("ALTER TABLE notifications NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM notifications WHERE type = 'login_failures'")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    _notification_types(_TYPES_BEFORE)
    _recreate_lookup(_LOOKUP_WITHOUT_EXPIRY)
    op.execute("ALTER TABLE users DROP CONSTRAINT users_temp_password_coherent")
    op.execute("ALTER TABLE users DROP COLUMN must_change_password_until")
