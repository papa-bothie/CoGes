"""Inscription libre-service : demandes et jetons de vérification (lot 30, ADR 0118).

Une **demande** n'est pas une boutique : rien n'est créé chez les commerçants avant
l'activation (lien e-mail ou équipe).

* `signup_requests` et `signup_email_tokens` : tables de la plateforme, sans `company_id`,
  hors RLS (déclarées dans `TABLES_WITHOUT_RLS`). `coges_app` et `coges_analytics` n'y ont
  **aucun** droit ;
* `coges_signup` (NOLOGIN, NOBYPASSRLS, `deploy/sql/create_signup_role.sql`, à lancer
  **avant** cette révision) possède neuf fonctions `SECURITY DEFINER` appelées sous
  `coges_app`. Chacune fige `search_path`, est retirée à `PUBLIC` et accordée à
  `coges_app` seul (`test_t36_*`). `signup_known` ne rend qu'un booléen ;
* `coges_signup` lit trois colonnes de `users` (e-mail, téléphone, suppression), par une
  politique qui ne nomme que lui, pour qu'un e-mail ou un numéro déjà inscrits n'ouvrent
  jamais une seconde boutique ; il écrit le journal de l'administration (activation) ;
* `coges_app_platform` lit les demandes (jamais le mot de passe haché ni l'empreinte de
  l'IP) et les décide (refus, note), bascule et efface par les tâches de fond ;
* les jetons ne sont stockés qu'en empreinte sha256 ; l'IP en HMAC (clé
  `COGES_SIGNUP_IP_HASH_KEY`), jamais en clair.

Ajouts seuls (ADR 0083) : l'image précédente les ignore.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "coges_app"
ANALYTICS_ROLE = "coges_analytics"
PLATFORM_ROLE = "coges_app_platform"
SIGNUP_ROLE = "coges_signup"
BACKUP_ROLE = "coges_backup"

TABLES = ("signup_requests", "signup_email_tokens")

#: Les neuf fonctions de `coges_signup`, avec leur signature exacte.
FUNCTIONS = (
    "signup_create(text, text, text, citext, text, text, text, text)",
    "signup_token_issue(uuid, text, interval)",
    "signup_token_consume(text)",
    "signup_reserve(uuid)",
    "signup_mark_activated(uuid, uuid, uuid, text, inet)",
    "signup_known(citext, text)",
    "signup_login_lookup(citext, text)",
    "signup_resend_target(citext)",
    "signup_switch_to_team(citext)",
)

#: Ce que l'équipe lit d'une demande : tout, sauf le mot de passe haché et l'empreinte IP.
PLATFORM_READ = (
    "id, shop_name, full_name, phone, email, legal_version, legal_accepted_at, path, "
    "path_changed_at, status, email_verified_at, reject_reason, team_note, created_at, "
    "decided_at, decided_by, decided_via, activated_company_id, purged_at"
)
#: Ce qu'elle écrit : ses décisions, la bascule et l'effacement des tâches de fond.
PLATFORM_WRITE = (
    "path, path_changed_at, status, reject_reason, team_note, decided_at, decided_by, "
    "decided_via, shop_name, full_name, phone, email, password_hash, ip_hash, purged_at"
)

_REQUIRE_ROLE = f"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SIGNUP_ROLE}') THEN
    RAISE EXCEPTION 'rôle {SIGNUP_ROLE} absent : lancer deploy/sql/create_signup_role.sql '
                    'sur ce cluster (en neondb_owner) avant la révision 0039';
  END IF;
END
$$
"""

_FUNCTIONS_SQL = r"""
CREATE FUNCTION signup_create(
    p_shop_name text, p_full_name text, p_phone text, p_email citext,
    p_password_hash text, p_legal_version text, p_ip_hash text, p_path text)
RETURNS TABLE (request_id uuid, created boolean, path text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $fn$
DECLARE
  existing record;
BEGIN
  -- Une demande en attente par numéro et par e-mail : la seconde rend la première, pour
  -- une réponse identique et sans doublon dans la file de l'équipe.
  SELECT r.id, r.path INTO existing
    FROM public.signup_requests r
   WHERE r.status = 'pending'
     AND (r.phone = p_phone OR (p_email IS NOT NULL AND r.email = p_email))
   ORDER BY r.created_at
   LIMIT 1
   FOR UPDATE;
  IF FOUND THEN
    RETURN QUERY SELECT existing.id, false, existing.path;
    RETURN;
  END IF;
  RETURN QUERY
    INSERT INTO public.signup_requests AS r
      (shop_name, full_name, phone, email, password_hash, legal_version,
       legal_accepted_at, path, path_changed_at, ip_hash)
    VALUES (p_shop_name, p_full_name, p_phone, p_email, p_password_hash, p_legal_version,
            now(), p_path, CASE WHEN p_path = 'team' THEN now() END, p_ip_hash)
    RETURNING r.id, true, r.path;
END
$fn$;

CREATE FUNCTION signup_token_issue(p_request_id uuid, p_token_hash text, p_ttl interval)
RETURNS TABLE (email citext, shop_name text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $fn$
BEGIN
  PERFORM 1 FROM public.signup_requests r
   WHERE r.id = p_request_id AND r.status = 'pending'
     AND r.email IS NOT NULL AND r.email_verified_at IS NULL
   FOR UPDATE;
  IF NOT FOUND THEN
    RETURN;
  END IF;
  -- Un nouveau jeton rend l'ancien inutilisable.
  UPDATE public.signup_email_tokens t SET revoked_at = now()
   WHERE t.request_id = p_request_id AND t.used_at IS NULL AND t.revoked_at IS NULL;
  INSERT INTO public.signup_email_tokens (request_id, token_hash, expires_at)
  VALUES (p_request_id, p_token_hash, now() + p_ttl);
  RETURN QUERY SELECT r.email, r.shop_name FROM public.signup_requests r
                WHERE r.id = p_request_id;
END
$fn$;

CREATE FUNCTION signup_token_consume(p_token_hash text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $fn$
DECLARE
  token record;
BEGIN
  SELECT t.id, t.request_id INTO token
    FROM public.signup_email_tokens t
    JOIN public.signup_requests r ON r.id = t.request_id
   WHERE t.token_hash = p_token_hash
     AND t.used_at IS NULL AND t.revoked_at IS NULL
     AND t.expires_at > now()
     AND r.status = 'pending' AND r.email IS NOT NULL
   FOR UPDATE OF t, r;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  UPDATE public.signup_email_tokens SET used_at = now() WHERE id = token.id;
  -- La bascule vers l'équipe (48 h) ne fait rien perdre : le lien reste valable.
  UPDATE public.signup_requests SET email_verified_at = now() WHERE id = token.request_id;
  RETURN token.request_id;
END
$fn$;

CREATE FUNCTION signup_reserve(p_request_id uuid)
RETURNS TABLE (shop_name text, full_name text, phone text, email citext,
               email_verified boolean, password_hash text, legal_version text,
               legal_accepted_at timestamptz)
LANGUAGE sql SECURITY DEFINER
SET search_path = pg_catalog, public AS $fn$
  -- Verrou jusqu'au COMMIT : un second appel (lien cliqué deux fois, lien pendant que
  -- l'équipe active) attend, puis ne trouve plus de demande en attente.
  SELECT r.shop_name, r.full_name, r.phone, r.email, r.email_verified_at IS NOT NULL,
         r.password_hash, r.legal_version, r.legal_accepted_at
    FROM public.signup_requests r
   WHERE r.id = p_request_id AND r.status = 'pending'
   FOR UPDATE
$fn$;

CREATE FUNCTION signup_mark_activated(
    p_request_id uuid, p_company_id uuid, p_actor uuid, p_via text, p_ip inet)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $fn$
BEGIN
  UPDATE public.signup_requests
     SET status = 'activated', activated_company_id = p_company_id, decided_at = now(),
         decided_by = p_actor, decided_via = p_via
   WHERE id = p_request_id AND status = 'pending';
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  -- Audit critique dans la transaction de l'activation (ADR 0118), lien e-mail compris.
  INSERT INTO public.platform_audit_logs
    (actor_id, action, entity_table, entity_id, target_company_id, diff, ip_address)
  VALUES (p_actor, 'update', 'signup_requests', p_request_id, p_company_id,
          jsonb_build_object('before', jsonb_build_object('status', 'pending'),
                             'after', jsonb_build_object('status', 'activated',
                                                         'via', p_via)),
          p_ip);
  RETURN true;
END
$fn$;

CREATE FUNCTION signup_known(p_email citext, p_phone text)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public AS $fn$
  -- Vrai ou faux, jamais une ligne : l'appelant n'apprend pas QUI ni OÙ.
  SELECT EXISTS (
    SELECT 1 FROM public.users u
     WHERE u.deleted_at IS NULL
       AND ((p_email IS NOT NULL AND u.email = p_email)
            OR (p_phone IS NOT NULL AND u.phone = p_phone)))
$fn$;

CREATE FUNCTION signup_login_lookup(p_email citext, p_phone text)
RETURNS TABLE (password_hash text, path text, email_pending boolean)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public AS $fn$
  -- La connexion vérifie le mot de passe avant d'en dire quoi que ce soit (ADR 0118).
  SELECT r.password_hash, r.path, r.email IS NOT NULL AND r.email_verified_at IS NULL
    FROM public.signup_requests r
   WHERE r.status = 'pending'
     AND ((p_email IS NOT NULL AND r.email = p_email)
          OR (p_phone IS NOT NULL AND r.phone = p_phone))
$fn$;

CREATE FUNCTION signup_resend_target(p_email citext)
RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public AS $fn$
  SELECT r.id FROM public.signup_requests r
   WHERE r.status = 'pending' AND r.email = p_email AND r.email_verified_at IS NULL
   ORDER BY r.created_at DESC
   LIMIT 1
$fn$;

CREATE FUNCTION signup_switch_to_team(p_email citext)
RETURNS uuid
LANGUAGE sql SECURITY DEFINER
SET search_path = pg_catalog, public AS $fn$
  UPDATE public.signup_requests SET path = 'team', path_changed_at = now()
   WHERE status = 'pending' AND email = p_email AND path = 'email'
  RETURNING id
$fn$;
"""


def upgrade() -> None:
    # Avant toute modification : sans le rôle, rien n'est touché.
    op.execute(_REQUIRE_ROLE)
    op.execute(
        """
        CREATE TABLE signup_requests (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          -- Données personnelles : effacées (NULL) 30 jours après un refus ou un abandon.
          shop_name         text CHECK (length(shop_name) BETWEEN 2 AND 80),
          full_name         text CHECK (length(full_name) BETWEEN 2 AND 120),
          phone             text CHECK (phone ~ '^\\+[1-9][0-9]{6,14}$'),
          email             citext CHECK (length(email) <= 254),
          password_hash     text,
          legal_version     text NOT NULL CHECK (legal_version ~ '^\\d{4}-\\d{2}-\\d{2}$'),
          legal_accepted_at timestamptz NOT NULL,
          path              text NOT NULL CHECK (path IN ('email', 'team')),
          path_changed_at   timestamptz,
          status            text NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'activated', 'rejected', 'abandoned')),
          email_verified_at timestamptz,
          reject_reason     text CHECK (reject_reason IN
                              ('unreachable', 'duplicate', 'not_a_business', 'fraud', 'other')),
          team_note         text CHECK (length(team_note) <= 1000),
          created_at        timestamptz NOT NULL DEFAULT now(),
          decided_at        timestamptz,
          decided_by        uuid REFERENCES platform_users (id),
          decided_via       text CHECK (decided_via IN ('email_link', 'team', 'system')),
          -- Pas `company_id` : la demande n'appartient à aucune entreprise (T37) ; elle
          -- nomme celle qu'elle a fait naître, comme `target_company_id` au journal.
          activated_company_id uuid REFERENCES companies (id),
          ip_hash           text CHECK (ip_hash ~ '^[0-9a-f]{64}$'),
          purged_at         timestamptz,
          CONSTRAINT signup_requests_pending_is_complete CHECK (
            status <> 'pending' OR (shop_name IS NOT NULL AND full_name IS NOT NULL
                                    AND phone IS NOT NULL AND password_hash IS NOT NULL)),
          CONSTRAINT signup_requests_activated_has_company CHECK (
            (status = 'activated') = (activated_company_id IS NOT NULL)),
          CONSTRAINT signup_requests_rejected_has_reason CHECK (
            (status = 'rejected') = (reject_reason IS NOT NULL)),
          CONSTRAINT signup_requests_decided_is_dated CHECK (
            (status = 'pending') = (decided_at IS NULL)),
          CONSTRAINT signup_requests_purge_after_decision CHECK (
            purged_at IS NULL OR status IN ('rejected', 'abandoned'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX signup_requests_pending_phone ON signup_requests (phone) "
        "WHERE status = 'pending'"
    )
    op.execute(
        "CREATE UNIQUE INDEX signup_requests_pending_email ON signup_requests (email) "
        "WHERE status = 'pending' AND email IS NOT NULL"
    )
    op.execute("CREATE INDEX signup_requests_queue ON signup_requests (status, path, created_at)")
    op.execute(
        """
        CREATE TABLE signup_email_tokens (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          request_id  uuid NOT NULL REFERENCES signup_requests (id),
          -- Empreinte sha256 : le jeton lui-même n'est jamais stocké ni journalisé.
          token_hash  text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
          expires_at  timestamptz NOT NULL,
          used_at     timestamptz,
          revoked_at  timestamptz,
          created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX signup_email_tokens_request ON signup_email_tokens (request_id)")

    # Les privilèges par défaut (révisions 0001 et 0010) ouvrent toute table neuve à
    # `coges_app` et `coges_analytics` : on les reprend tous.
    for table in TABLES:
        for role in (APP_ROLE, ANALYTICS_ROLE):
            op.execute(f"REVOKE ALL ON {table} FROM {role}")
        op.execute(f"GRANT SELECT ON {table} TO {BACKUP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(TABLES)} TO {SIGNUP_ROLE}")
    op.execute(f"GRANT INSERT ON platform_audit_logs TO {SIGNUP_ROLE}")
    # E-mail ou numéro déjà inscrits (aucune seconde boutique) : trois colonnes, rien d'autre.
    op.execute(f"GRANT SELECT (email, phone, deleted_at) ON users TO {SIGNUP_ROLE}")
    op.execute(f"CREATE POLICY users_signup_read ON users FOR SELECT TO {SIGNUP_ROLE} USING (true)")
    op.execute(f"GRANT SELECT ({PLATFORM_READ}) ON signup_requests TO {PLATFORM_ROLE}")
    op.execute(f"GRANT UPDATE ({PLATFORM_WRITE}) ON signup_requests TO {PLATFORM_ROLE}")

    # Une instruction à la fois : chaque CREATE FUNCTION est un bloc à part.
    for statement in _FUNCTIONS_SQL.split("\n\nCREATE FUNCTION "):
        body = statement.strip()
        if body:
            op.execute(body if body.startswith("CREATE") else f"CREATE FUNCTION {body}")
    # Retirer à PUBLIC et accorder à `coges_app` AVANT le transfert de propriété : après,
    # un REVOKE de l'ancien propriétaire serait sans effet (test_t36_*).
    for signature in FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")
    op.execute(f"GRANT CREATE ON SCHEMA public TO {SIGNUP_ROLE}")
    for signature in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {SIGNUP_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {SIGNUP_ROLE}")


def downgrade() -> None:
    for signature in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {signature}")
    op.execute(f"REVOKE UPDATE ({PLATFORM_WRITE}) ON signup_requests FROM {PLATFORM_ROLE}")
    op.execute(f"REVOKE SELECT ({PLATFORM_READ}) ON signup_requests FROM {PLATFORM_ROLE}")
    op.execute("DROP POLICY users_signup_read ON users")
    op.execute(f"REVOKE SELECT (email, phone, deleted_at) ON users FROM {SIGNUP_ROLE}")
    op.execute(f"REVOKE INSERT ON platform_audit_logs FROM {SIGNUP_ROLE}")
    op.execute("DROP TABLE signup_email_tokens")
    op.execute("DROP TABLE signup_requests")
