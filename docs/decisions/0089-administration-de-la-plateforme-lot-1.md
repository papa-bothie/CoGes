# 0089 — Administration de la plateforme, lot 1 : rôle PostgreSQL dédié, application séparée

- **Date** : 2026-10-20
- **Phase** : lot admin 1 (prompt 22)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion) pour les quatre choix structurants ; le reste découle du code existant

## Contexte

L'équipe CoGes doit pouvoir voir les entreprises clientes (nom, statut, comptes, dernière
activité) et suspendre ou réactiver l'une d'elles. Rien dans le Modèle de données V1.1 ni
dans l'Architecture V1.1 ne prévoit de rôle au-dessus des entreprises : l'isolation
multi-tenant (3 barrières, RLS FORCE) est justement faite pour qu'aucun compte ne voie
deux entreprises. Le principe du prompt : l'administration ne doit **jamais, par
construction**, pouvoir lire les ventes, le stock, la finance ou les référentiels d'une
entreprise — une impossibilité au niveau du rôle PostgreSQL, pas une règle applicative.

Ce lot pose le socle des lots 23 à 26 (surveillance, abonnements, support, statistiques).

## Options envisagées

**Lecture à travers la RLS**
1. **Rôle `coges_app_platform` (retenue)** : LOGIN, NOBYPASSRLS, GRANT colonne par colonne
   sur les seules métadonnées, politiques RLS qui ne nomment que lui. Une erreur de code
   ne peut physiquement pas lire une vente : la base répond `permission denied`.
2. Indicateur `app.platform_mode` ajouté à chaque politique de `coges_app` : moins de
   travail, mais l'impossibilité repose sur un indicateur qu'un bug pourrait poser, et
   `coges_app` garde tous ses droits sur les tables commerciales.

**Profils des comptes**
1. **Colonne `platform_users.role` (retenue)**, ENUM `administrator` | `support`, à étendre
   par migration. Seul `administrator` suspend ou réactive.
2. Tables `platform_roles` + `platform_user_roles` calquées sur le RBAC tenant : prématuré
   pour deux profils.

**Interface**
1. **Application séparée `frontend-admin/` (retenue)** : son image, son service Docker,
   servie par Caddy sur `admin.<domaine>` derrière une liste d'adresses IP. Aucune route
   ni aucun JavaScript d'administration n'est livré au navigateur d'un commerçant.
2. Groupe de routes dans `frontend/` : moins de duplication, mais le code d'administration
   voyagerait dans l'application des commerçants.

**E-mails**
1. **SMTP par variables d'environnement (retenue)**, `smtplib` de la bibliothèque standard,
   dans une tâche Celery après COMMIT. Sans `COGES_SMTP_HOST`, rien ne part et rien
   n'échoue. Aucun service payant imposé.
2. Journal seulement, envoi réel reporté.

## Décision

### Base (révision 0026)
- `coges_app_platform` est un rôle de cluster (`01-roles.sql` en local et en CI,
  `deploy/sql/create_platform_role.sql` sur Neon, **avant** la migration).
- Ses seuls droits : SELECT sur `companies(id, name, slug, status, created_at,
  deleted_at)`, UPDATE sur `companies(status)` ; SELECT sur `users(id, company_id,
  full_name, email, phone, is_active, last_login_at, deleted_at)`, `roles(id, company_id,
  name, description)`, `user_roles(user_id, role_id, company_id)` et `audit_logs(company_id,
  occurred_at)` — jamais `diff` ; SELECT/INSERT/UPDATE sur `platform_users` et
  `platform_auth_sessions`, SELECT/INSERT sur `platform_audit_logs` (append-only). Aucune
  fonction `SECURITY DEFINER`, aucune séquence, aucun DELETE.
- Politiques `<table>_platform_read` (FOR SELECT) et `companies_platform_status` (FOR
  UPDATE), `TO coges_app_platform` seulement. Elles n'ouvrent rien sans GRANT : la
  barrière est le GRANT. T37 est amendé en conséquence (une politique pour tous sur
  `companies`, les autres nommant ce seul rôle).
- `companies.status` (`trial`, `active`, `suspended`), `active` par défaut jusqu'au lot 24.
  Le trigger `companies_status_guard` (SQLSTATE `CG006`) refuse tout changement de statut
  qui ne vient ni de `coges_app_platform` ni de `coges_owner` : `coges_app` a UPDATE sur
  toute la table (réglages de la boutique), un gérant ne peut pas se réactiver.
- Trois tables de plateforme **sans `company_id`**, donc hors RLS et déclarées dans
  `TABLES_WITHOUT_RLS` ; `coges_app` et `coges_analytics` n'y ont aucun droit. Le journal
  nomme l'entreprise visée `target_company_id` : il parle d'une entreprise, il ne lui
  appartient pas.

### Module `platform/`, un axe à part
- `backend/app/modules/platform/` (gabarit 0010, sans `events.py`) n'importe aucun module
  métier et aucun module métier ne l'importe (test d'architecture). Ce n'est pas une
  sixième bande sous la Restitution : il ne compose aucune façade, il lit des métadonnées
  sous son propre rôle. Ses lectures d'entreprise sont en SQL et ne nomment que les
  colonnes accordées.
- Transactions par `platform_transaction` (`core/deps.py`) : `tenant_transaction` sur
  l'entreprise nulle avec la fabrique `get_platform_app_session_factory` — jamais
  `get_tenant_session`. Dépendance `CurrentPlatformAdmin` en portée `function` (ADR 0079),
  compte relu en base à chaque requête, `require_platform_role("administrator")`.
- Routes sous `/api/v1/platform/*` : `auth/login|refresh|logout|me`, `companies`
  (paginée, recherche nom/slug), `companies/{id}` (comptes, rôles, dernière connexion),
  `PATCH companies/{id}/status` (`active` ↔ `suspended`, `trial` refusé en 422, raison
  obligatoire, audit critique dans `platform_audit_logs`, e-mail au gérant après COMMIT ;
  redemander le statut en place ne change rien et ne prévient personne).

### Jetons
- Même clé de signature, deux familles qui ne s'acceptent jamais : `typ="access"` +
  `aud="coges-tenant"` pour les commerçants, `typ="platform_access"` + `aud="coges-platform"`
  + `platform_role` (pas de `company_id`) pour l'administration. Les jetons commerçants
  émis avant le déploiement n'ont pas d'audience : refusés, ils sont renouvelés par le
  rafraîchissement (opaque, inchangé) — au pire une reconnexion.
- Refresh opaque dans `platform_auth_sessions`, rotation, famille révoquée à la
  réutilisation, 30 s de grâce (ADR 0051), sessions révoquées par trigger si le mot de
  passe change ou si le compte est désactivé. Cookie `coges_platform_refresh`, chemin
  `/api/v1/platform/auth`, `SameSite=Strict`.
- Freinage : le même compteur par compte (ADR 0078, 0088) avec la portée `platform:` —
  un slug ne contient jamais « : », aucune collision possible avec un commerçant. Au 10ᵉ
  échec, une alerte par e-mail à `COGES_PLATFORM_ALERT_EMAIL` (pas de gérant à ce niveau).
  Plafond par IP de la connexion étendu à `/platform/auth/login`.
- `COGES_OPS_TOKEN` reste la voie machine à machine (`make ops-status`) ; les comptes
  `platform_users` sont la voie humaine. Aucun compte ne naît d'une route : CLI
  `create-platform-user`.

### Suspension côté commerçant
- `company_suspended` (403, message en français) : à la connexion **après** le mot de
  passe vérifié (comme `temporary_password_expired`, aucune énumération), au
  rafraîchissement, et à **chaque** requête (`_LOAD_IDENTITY` lit `companies.status`) — un
  jeton émis avant la suspension cesse de servir à la requête suivante. Les sessions ne
  sont pas révoquées : la réactivation rend l'accès.
- Essai expiré : `TODO(lot 24)` au même endroit, aucune logique simulée.
- Les tâches de nuit continuent pour une entreprise suspendue : la suspension coupe
  l'accès, pas les données.
- Front commerçant : message dédié sur l'écran de connexion, et retour à la connexion
  avec ce message si l'API répond `company_suspended` en cours de session.

### Déploiement
- Service `admin` (image `ghcr.io/…/admin`, 192 Mo), servi par Caddy sur
  `admin.{$COGES_DOMAIN}` pour la pile de production : `@admin_allowed remote_ip
  {$COGES_ADMIN_ALLOWED_IPS}`, sinon 403 ; `/api/v1/platform/*` vers l'API, le reste de
  `/api/v1` en 404. Sur le domaine commerçant et la préprod, `/api/v1/platform/*` répond 404.
- `check_runtime_env.py` exige `COGES_DATABASE_URL_PLATFORM` (rôle `coges_app_platform`) et,
  hors préprod, une liste d'IP lisible qui n'ouvre pas `0.0.0.0/0`.

## Conséquences
- Tests : `test_platform_role_grants` énumère toutes les colonnes de toutes les tables et
  exige exactement la liste blanche ; la base elle-même refuse `SELECT … FROM sales` sous
  ce rôle. `test_platform_token_separation` passe chaque route de l'OpenAPI avec le
  mauvais jeton (et sans jeton). `test_platform_sees_companies` : A et B visibles, rien de
  B dans le détail de A, clés de réponse en liste blanche. Registres de la CI complétés
  (`READ_ROUTES` genre `PLATFORM`, `CROSS_TENANT_ROUTES` hors `/platform/`, écritures
  classées, nouvelle dépendance transactionnelle).
- Duplication assumée entre `frontend/` et `frontend-admin/` (client API, session) ; même
  version de Playwright (1.63.0) pour partager les navigateurs.
- Le propriétaire doit, avant la migration 0026 sur Neon, créer le rôle ; puis renseigner
  `COGES_DATABASE_URL_PLATFORM`, `COGES_ADMIN_ALLOWED_IPS`, le DNS d'`admin.<domaine>` et, s'il
  veut des e-mails, `COGES_SMTP_*`.
- Repoussé : `job_runs` pour l'administration (lot 23, par une fonction de `coges_ops`),
  essais et abonnements (lot 24), toute donnée commerciale même agrégée (lots 24 et 26).
