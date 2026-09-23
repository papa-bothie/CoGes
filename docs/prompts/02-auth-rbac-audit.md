# Phase 02 — Entreprises, authentification, utilisateurs, RBAC, audit critique, outbox

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 02 : bande A
Plateforme**. Elle branche l'authentification sur le socle tenant de la phase 01 et pose les deux
mécanismes transverses que toutes les phases suivantes utiliseront : **l'audit critique** et
**l'écriture dans l'outbox**.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 01 ✅ exigée) et les ADR de `docs/decisions/`.
2. Lis :
   - Architecture : Diagramme 3, modules Companies, Authentication, Users, Roles & Perms, Audit Log
     (≈272) ; section Audit critique / secondaire et liste des opérations critiques (≈412-460) ;
     Diagramme 8, étape 1 (détermination du tenant) ; décisions 04, 05, 16.
   - Modèle : § 2.2 (connexion par slug + e-mail) ; SQL § 8.2 et § 8.8 (`audit_logs`
     partitionné, `business_events`) ; § 8.11.
   - `docs/architecture/README.md` : points ouverts **P2** et **P3**.
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder (plusieurs appels si besoin).
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Un utilisateur se connecte avec (slug d'entreprise, e-mail, mot de passe), reçoit un JWT court et
un refresh token rotatif. Chaque requête authentifiée construit un `TenantContext` **côté
serveur**. Les permissions sont vérifiées côté serveur. Toute opération sensible écrit une ligne
d'audit dans sa propre transaction, et tout événement métier est écrit dans l'outbox dans la même
transaction.

## 2. Questions à me poser (AskUserQuestion)

1. **Connexion malgré la RLS (P2)** : pour trouver l'utilisateur, il faut lire `companies` et
   `users` avant d'avoir un contexte tenant. Options :
   (a) une fonction SQL `SECURITY DEFINER` minimale `auth_lookup(slug, email)` qui renvoie
   seulement `company_id`, `user_id`, `password_hash` et `is_active`, avec `search_path` figé et
   `EXECUTE` accordé à `coges_app` (Recommandé : la surface contournant la RLS est minuscule et
   testable) ;
   (b) un rôle PostgreSQL `coges_auth` dédié, avec une politique spécifique ;
   (c) résoudre d'abord le slug, puis poser le contexte avant de lire `users` (il faut quand même
   lire `companies` sans contexte).
2. **Refresh tokens (P3)** : nouvelle table `auth_sessions` tenant-scoped (`id`, `company_id`,
   `user_id`, `token_hash`, `family_id`, `expires_at`, `revoked_at`, `replaced_by`, `user_agent`,
   `ip`) avec RLS et détection de réutilisation (Recommandé) / refresh token JWT sans état et liste
   de révocation dans Redis.
3. **Transport des jetons vers le frontend** : access token en mémoire + refresh token en cookie
   `httpOnly; Secure; SameSite=Lax` (Recommandé) / les deux en cookies / en-tête Bearer uniquement,
   stockage côté client. Cela détermine la configuration CORS et CSRF.
4. **Durées** : access token 15 min et refresh 7 jours (Recommandé) / autre.
5. **Création d'une entreprise (onboarding)** : commande CLI d'administration
   `python -m app.cli create-company` qui crée l'entreprise, ses rôles système et un gérant
   (Recommandé pour la V1) / inscription publique en libre-service / les deux.
6. **Rôles système et matrice de permissions** : je te propose de rédiger la matrice
   `gérant / vendeur / comptable` × ressources × actions (`read, create, update, delete, confirm,
   cancel, export`) dans un ADR, que je valide **avant** que tu la codes. D'accord ?
7. **Partitions de `audit_logs`** : fonction SQL `ensure_audit_partition(date)` appelée par la
   migration (mois courant + mois suivant), puis par une tâche planifiée en phase 08 (Recommandé).

## 3. Périmètre

**Migration `0002_auth_audit_outbox`**
- `audit_logs` (partitionnée par mois, RLS sur la table parente) et `business_events`, conformes
  au § 8.8 ; `auth_sessions` selon la réponse 2 ; fonction de connexion selon la réponse 1 ;
  données de référence du catalogue `permissions`.

**Modules**
- `companies/` : lecture et mise à jour des paramètres (`name`, `currency`, `timezone`,
  `settings` : TVA activée, seuils par défaut). Toute modification de paramètre sensible passe par
  un **audit critique** avec la valeur avant et après.
- `auth/` : `POST /api/v1/auth/login`, `/refresh` (rotation + détection de réutilisation →
  révocation de toute la famille), `/logout` ; Argon2id ; `users.last_login_at` ; la connexion
  réussie va dans l'**audit secondaire** (asynchrone), elle n'est pas critique.
- `users/` : CRUD dans l'entreprise, désactivation (suppression logique), changement de mot de passe.
- `rbac/` : rôles, attribution, matrice ; dépendance `require_permission("sales:confirm")`. Tout
  changement de rôle ou de permission passe par un **audit critique**.
- `core/deps.py` : JWT vérifié → utilisateur chargé **en base** → `company_id` lu en base (jamais
  depuis un claim seul sans vérification) → `TenantContext` → transaction.
- `core/audit.py` : `audit_critical(session, action, entity_table, entity_id, before, after)`,
  qui écrit dans la **même session et la même transaction** que l'opération, avec l'acteur, l'IP et
  l'origine.
- `core/events/` : `types.py` (liste fermée des 9 types d'événements, notation pointée, avec un
  test qui refuse tout autre nom), `outbox.py` (`emit(session, event_type, aggregate_type,
  aggregate_id, payload)` dans la transaction courante), `bus.py` (interface du futur relais,
  **sans implémentation Redis** : phase 08).
- `app/cli.py` : création d'une entreprise (réponse 5).

**Tests**
- Connexion : bon ou mauvais mot de passe, utilisateur inactif, slug inconnu (message identique,
  pas d'énumération), même e-mail dans deux entreprises ⇒ deux comptes distincts.
- Refresh : rotation ; la réutilisation d'un ancien jeton révoque toute la famille.
- RBAC : un vendeur n'a pas accès à la gestion des rôles (403 dans son propre tenant) ; un appel
  sur la ressource d'un autre tenant ⇒ 404.
- Audit : un changement de rôle annulé par rollback ⇒ aucune ligne d'audit ; un changement validé
  ⇒ exactement une ligne avec la valeur avant et après.
- **Test générique de fuite sur la table des routes** : il parcourt `app.routes` et, pour chaque
  endpoint authentifié qui prend un identifiant, appelle en croisé A → B et exige 404. Tout nouvel
  endpoint y sera soumis automatiquement (Architecture, tests de fuite).
- T37 reste vert (la couverture RLS inclut `audit_logs`, `business_events` et `auth_sessions`).

**Hors périmètre** : relais outbox → Redis, notifications, e-mail, inscription publique (sauf si
tu l'as choisie à la question 5).

## 4. Règles à respecter

- Le `company_id` du contexte vient toujours de la base, jamais d'un en-tête ou d'un paramètre.
- Aucun secret en dur ; clé JWT lue dans la configuration.
- L'audit critique n'appelle jamais Redis ni un worker.

## 5. Vérification

`make test` vert. Démonstration via `httpx` ou `curl` : login → appel protégé → refresh →
logout. Montre une ligne `audit_logs` produite par un changement de rôle.

## 6. Clôture

ADR (connexion, sessions, transport des jetons, matrice RBAC, onboarding) ; `CLAUDE.md` mis à
jour (phase 02 ✅, décisions au § 9) ; résumé avec les risques restants.
