"""Connexion par téléphone et mot de passe provisoire (ADR 0074, lot 3e de la phase 15).

La maquette v2 (écran 24b) ajoute une personne avec « téléphone ou e-mail » et lui donne
un mot de passe provisoire lisible, qu'elle change à sa première connexion (écran 25).

* `users.phone` : facultatif, chiffres seuls (« 770000000 »), unique **par entreprise**
  comme l'e-mail (§ 2.2) ;
* `users.email` devient facultatif ; un compte a un e-mail, un téléphone, ou les deux
  (`users_contact_present`) ;
* `users.must_change_password` : vrai tant qu'un mot de passe donné par quelqu'un d'autre
  n'a pas été remplacé ;
* `auth_lookup(slug, identifiant)` garde sa signature, donc son propriétaire
  `coges_auth` et ses droits (ADR 0005, T36) : un identifiant avec « @ » se compare à
  l'e-mail, sinon au téléphone, déjà ramené à ses chiffres par l'application.

Les privilèges de `coges_app` sur `users` sont des privilèges de table : les nouvelles
colonnes en héritent.

`downgrade` remet l'e-mail obligatoire : un compte qui n'a qu'un téléphone reçoit
l'adresse `<numéro>@telephone.invalid` (domaine réservé, jamais distribuable), pour
qu'aucun compte ne disparaisse ni ne bloque le retour en arrière.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOOKUP_BY_IDENTIFIER = """
    CREATE OR REPLACE FUNCTION auth_lookup(p_slug citext, p_email citext)
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

_LOOKUP_BY_EMAIL = """
    CREATE OR REPLACE FUNCTION auth_lookup(p_slug citext, p_email citext)
    RETURNS TABLE (company_id uuid, user_id uuid, password_hash text, is_active boolean)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public AS $fn$
       SELECT c.id, u.id, u.password_hash, u.is_active
       FROM public.companies c
       JOIN public.users u ON u.company_id = c.id
       WHERE c.slug = p_slug
         AND u.email = p_email
         AND c.deleted_at IS NULL
         AND u.deleted_at IS NULL
    $fn$
"""


def _replace_lookup(definition: str) -> None:
    """Remplace le corps d'`auth_lookup` sans changer ni propriétaire ni droits.

    Le propriétaire est `coges_auth` : on prend son rôle le temps de l'instruction
    (révision 0010). Remplacer une fonction exige CREATE sur le schéma, accordé puis
    retiré aussitôt, comme à sa création (révision 0002) : `coges_auth` ne doit pouvoir
    créer aucun objet.
    """
    op.execute("GRANT CREATE ON SCHEMA public TO coges_auth")
    op.execute("SET LOCAL ROLE coges_auth")
    op.execute(definition)
    op.execute("RESET ROLE")
    op.execute("REVOKE CREATE ON SCHEMA public FROM coges_auth")


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN phone text")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_phone_digits "
        "CHECK (phone IS NULL OR phone ~ '^[0-9]{6,15}$')"
    )
    op.execute("ALTER TABLE users ADD CONSTRAINT users_phone_uq UNIQUE (company_id, phone)")
    op.execute("ALTER TABLE users ALTER COLUMN email DROP NOT NULL")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_contact_present "
        "CHECK (email IS NOT NULL OR phone IS NOT NULL)"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN must_change_password boolean NOT NULL DEFAULT false"
    )
    _replace_lookup(_LOOKUP_BY_IDENTIFIER)


def downgrade() -> None:
    _replace_lookup(_LOOKUP_BY_EMAIL)
    op.execute("ALTER TABLE users DROP COLUMN must_change_password")
    op.execute("ALTER TABLE users DROP CONSTRAINT users_contact_present")
    # `users` est sous RLS FORCE : sans contexte tenant, le propriétaire ne verrait
    # aucune ligne. FORCE est levé le temps de cette seule mise à jour de données.
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE users
           SET email = phone || '@telephone.invalid'
         WHERE email IS NULL;
        """
    )
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users ALTER COLUMN email SET NOT NULL")
    op.execute("ALTER TABLE users DROP CONSTRAINT users_phone_uq")
    op.execute("ALTER TABLE users DROP CONSTRAINT users_phone_digits")
    op.execute("ALTER TABLE users DROP COLUMN phone")
