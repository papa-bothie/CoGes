# Phase 01 — Socle multi-tenant, RLS et noyau partagé

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 01 : socle
multi-tenant**. Le Modèle de données le dit clairement : ce socle et ses tests passent **avant
toute autre ligne de code**. C'est la phase la plus critique du projet : une erreur ici peut
provoquer une fuite de données entre entreprises.

## 0. Protocole

1. Lis `CLAUDE.md`. Vérifie que la phase 00 est ✅, sinon arrête-toi et préviens-moi.
2. Lis, avec `docs/architecture/README.md` comme index :
   - Architecture : Diagramme 8 (RLS, pool, 3 barrières, ligne ≈585) et les tests de fuite (≈671) ;
     Diagramme 3 (bande A Plateforme, ≈224) ; décisions 01, 03, 06, 07, 15, 17 (≈1137).
   - Modèle : § 2.2 (1 compte = 1 entreprise), § 4.1 (recensement des tables et colonne RLS),
     § 7 (isolation) ; SQL § 8.1 et § 8.2 ; § 8.11 (RLS) ; § 10 tests T1–T5, T36, T37 ;
     § 12.1 point 1 (SET LOCAL et pool).
3. Pose-moi les questions du § 2 avec `AskUserQuestion` **avant d'écrire du code**.
4. Plan → mon feu vert → exécution → vérification → clôture.

## 1. Objectif

Livrer le noyau `backend/app/core/` et la première migration, de sorte qu'il soit
**structurellement impossible** d'exécuter une requête métier sans contexte tenant, et prouvé par
des tests qui attaquent la base directement qu'aucune fuite n'est possible.

## 2. Questions à me poser (AskUserQuestion)

1. **Stratégie de migration (point P1)** : le § 9 décrit une migration V1 → V1.1, or le projet
   part de zéro. Options : schéma V1.1 **directement**, découpé en une révision Alembic par phase
   (0001 plateforme, 0002 référentiels…) (Recommandé) / une seule révision qui crée tout le schéma
   V1.1 maintenant / suivre littéralement V1 puis V1.1.
2. **Types ENUM** : tous créés dès 0001 (Recommandé : une seule source, § 8.1) / chacun créé
   dans la phase qui l'utilise.
3. **Base de test** : base PostgreSQL dédiée recréée par session pytest via Alembic (Recommandé :
   teste les vraies migrations) / testcontainers / `create_all` SQLAlchemy (déconseillé : ne teste
   ni les triggers ni la RLS des migrations).
4. **Pose du contexte** : `SELECT set_config('app.company_id', :id, true)` (Recommandé :
   équivalent exact de `SET LOCAL`, mais paramétrable, donc sans injection) / `SET LOCAL`
   construit par chaîne.
5. Tout écart ou trou que tu découvres dans le SQL du § 8 (ligne coupée, contrainte
   incohérente) : **pose la question au moment où tu le trouves**, ne corrige pas en silence.

## 3. Périmètre

**Migration `0001_platform`** (exécutée par le rôle propriétaire, jamais par `coges_app`)
- Extensions `pgcrypto`, `citext`, `btree_gist`, `pg_trgm` ; types (selon la réponse 2) ;
  fonctions `set_updated_at()` et `cmp_next_avg()` (§ 8.1).
- Tables `companies`, `users`, `roles`, `permissions`, `user_roles`, `role_permissions`,
  **identiques au § 8.2** : `UNIQUE (company_id, id)`, FK composites, `UNIQUE (company_id, email)`.
- Triggers `updated_at`.
- RLS `ENABLE` + `FORCE` avec la politique type du § 7 (`USING` **et** `WITH CHECK`) sur toutes
  les tables tenant-scoped ; politique anti-énumération sur `companies` (`id = current_setting…`) ;
  `permissions` sans RLS, en lecture seule.
- Rôle `coges_app` : `LOGIN NOBYPASSRLS NOSUPERUSER`, `SELECT/INSERT/UPDATE` et **pas de DELETE**,
  plus les privilèges par défaut pour les tables futures.
- `downgrade()` complet et testé.

**Noyau `backend/app/core/`**
- `config.py` (pydantic-settings) : deux DSN distincts, un pour les migrations (propriétaire) et
  un pour l'application (`coges_app`).
- `database.py` : engine, pool borné, écouteur `checkin` qui exécute `DISCARD ALL` (ou
  `RESET app.company_id`) avant la réutilisation d'une connexion.
- `tenancy.py` :
  - `TenantContext` immuable (`user_id`, `company_id`, `permissions`) ;
  - un **unique** point d'entrée transactionnel, par exemple
    `with tenant_transaction(ctx) as session:`, qui ouvre la transaction, pose le contexte en
    portée transaction, puis commit ou rollback ;
  - une assertion en début de transaction : `current_setting('app.company_id')` doit égaler
    `ctx.company_id`, sinon erreur immédiate.
- Repository de base (`core/repository.py` ou équivalent) : injecte le filtre `company_id` et
  refuse d'écrire une ligne dont le `company_id` diffère du contexte. Les repositories métier en
  héritent et ne peuvent pas construire de requête sans ce filtre.
- `errors.py` : erreurs métier → format `{ "error": { "code", "message", "details" } }` ;
  « ressource d'un autre tenant » ⇒ **404**.
- `logging.py` : logs JSON structurés avec `request_id` et `company_id` (jamais de secrets).
- Noyau partagé : type monétaire `Decimal` avec quantification (2 décimales pour les montants,
  3 pour les quantités, 4 pour les coûts, 4 pour les taux), sérialisé en **chaîne** dans le JSON.
- `deps.py` : squelette de la dépendance FastAPI qui construira le contexte (branchée sur l'auth
  en phase 02). En attendant, **aucun** mode où le `company_id` viendrait d'un en-tête.

**Tests (base réelle, connexion en `coges_app`)**
- `tests/tenancy/` : **T1** (lecture croisée, pour l'instant sur `users` et `roles`), **T2**
  (écriture croisée rejetée par `WITH CHECK`), **T3** (sans contexte ⇒ 0 ligne, sans erreur),
  **T4** (la même connexion physique enchaîne A puis B sans nouveau contexte ⇒ 0 ligne), **T5**
  (FK croisée `user_roles` A → rôle B), **T36** (`coges_app` sans BYPASSRLS, sans superuser, sans
  DELETE), **T37** (couverture RLS).
- **T37 doit être générique** : toute table du schéma `public` qui possède une colonne
  `company_id` doit avoir `relrowsecurity` **et** `relforcerowsecurity`. Il échouera tout seul si
  une phase future oublie la RLS.
- Un **harnais de fuite réutilisable** (fixture paramétrée : deux entreprises A et B + fabriques
  de données), que chaque phase suivante étendra à ses tables.
- `tests/architecture/` : un module de `app/modules/*` ne peut importer ni le `repository` ni les
  `models` d'un autre module (analyse AST ou `import-linter`, à me proposer) ; aucun `SET ` sans
  `LOCAL` dans le code (recherche statique, hors tests).
- Tests unitaires du type monétaire (arrondis, sérialisation, refus des `float`).

**Hors périmètre** : authentification réelle, endpoints métier, autres tables.

## 4. Règles à respecter

- Le contexte tenant n'est posé **qu'à un seul endroit** du code.
- Aucune requête métier hors transaction.
- Ne désactive **jamais** la RLS, même dans les tests : les tests se connectent en `coges_app`.
- Copie le SQL du § 8 **à l'identique** (noms de contraintes compris), sauf décision validée.

## 5. Vérification

- `alembic upgrade head`, puis `downgrade base`, puis `upgrade head` : sans erreur.
- `make test-tenancy` est vert ; montre-moi la sortie.
- Démonstration : sabote volontairement un test (par exemple `SET` au lieu de `SET LOCAL` dans une
  branche jetable) et montre que T4 échoue. Puis annule le sabotage.

## 6. Clôture

- `docs/decisions/0002-strategie-migrations.md` (et d'autres ADR si besoin).
- `CLAUDE.md` : phase 01 ✅, décisions ajoutées au § 9.
- Résumé : les garanties obtenues, les limites connues, ce que la phase 02 doit brancher.
