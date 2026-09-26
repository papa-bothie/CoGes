# CLAUDE.md — Tour de contrôle du projet CoGes

> Ce fichier est lu au début de chaque session Claude Code. Il donne les règles du projet, la
> façon de travailler et l'état d'avancement. **Il prime sur tes habitudes par défaut.**
> Mets-le à jour à la fin de chaque phase (section « Avancement » et « Décisions »), sans le
> faire grossir inutilement : les détails vont dans `docs/`.

---

## 1. Le projet en 10 lignes

CoGes est un **logiciel de gestion pour PME ouest-africaines** (pas un ERP), centré sur le cycle
**vente → stock → argent → décision**. Tout ce qui n'est pas nécessaire à ce cycle est hors V1.

- **Backend** : monolithe modulaire **FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16**.
- **Asynchrone** : outbox transactionnelle `business_events` → relais → **Redis** → **Celery** (Docker).
- **Frontend** : **Next.js (App Router) + TypeScript**, qui n'appelle **que** l'API REST `/api/v1`.
- **Déploiement** : Next.js et API sur **Vercel** ; PostgreSQL et Redis managés ; workers, ML et batchs en **Docker**.
- **Multi-tenant** : isolation par `company_id` avec **3 barrières** (FK composites, repository, RLS FORCE).
- **Langue** : interface en **français**, code et schéma en **anglais**, devise par défaut **XOF (FCFA)**.

## 2. Sources de vérité (dans cet ordre)

1. `docs/architecture/pdf/modele-donnees-v1.1.pdf` — **Modèle de données V1.1** (fait autorité)
2. `docs/architecture/pdf/architecture-technique-v1.1.pdf` — **Architecture technique V1.1**
3. Ce fichier `CLAUDE.md`
4. `docs/decisions/` — décisions prises en cours de projet (ADR)
5. Le code existant

Les PDF ont des extraits texte découpés dans `docs/architecture/*.txt`.
**Commence toujours par `docs/architecture/README.md`** : il donne les numéros de ligne de chaque
section. Lis seulement les sections utiles (avec offset/limit), pas les fichiers entiers.
Si le code contredit l'architecture, c'est le code qui a tort, sauf si une décision de
`docs/decisions/` dit le contraire.

## 3. Protocole de travail — OBLIGATOIRE

1. **Une phase à la fois.** Les prompts de phase sont dans `docs/prompts/`. Ne commence jamais
   une phase dont les prérequis (section 8) ne sont pas terminés.
2. **Décider avec l'utilisateur, pas à sa place.** À chaque moment de décision (choix de
   bibliothèque, ambiguïté ou trou dans l'architecture, compromis, écart par rapport aux documents,
   nommage structurant, suppression de code), **arrête-toi et pose la question avec l'outil
   `AskUserQuestion`** avant de continuer :
   - 1 à 4 questions par appel, 2 à 4 options chacune ;
   - l'option recommandée en premier, suffixée « (Recommandé) » ;
   - pour chaque option, une phrase qui explique la conséquence ;
   - regroupe les questions d'une même phase dans un seul appel au début, puis pose les
     questions imprévues au moment où elles surgissent.
   Ne pose **pas** de question sur ce que l'architecture tranche déjà : applique-la.
3. **Planifier avant de coder.** Après les réponses, présente un plan court (fichiers, migrations,
   endpoints, tests) et attends le feu vert.
4. **Tester d'abord ce qui protège.** Les tests d'intégrité T1-T40 (§10 du modèle) attaquent la
   **base directement**. Un test qui ne passe que parce que l'API a filtré ne compte pas.
5. **Consigner.** Chaque décision prise → un fichier `docs/decisions/NNNN-titre.md` (modèle dans
   `docs/decisions/0000-template.md`) + une ligne dans la section 9 ci-dessous.
6. **Clore la phase.** Tests verts, lint propre, `CLAUDE.md` mis à jour (section 8), résumé à
   l'utilisateur : ce qui est fait, ce qui reste, les décisions prises, les risques.
7. **Git** : une branche par phase (`phase/NN-nom`), commits au format Conventional Commits en
   anglais (`feat(sales): confirm draft sale in single transaction`). Pas de push ni de merge sans
   accord explicite.

## 4. Règles non négociables (issues des 18 décisions V1)

**Architecture**
- Un module = un dossier `backend/app/modules/<module>/` avec `router.py · service.py ·
  repository.py · models.py · schemas.py · events.py`. **Aucune logique métier hors `modules/`.**
- Un module **n'importe jamais** le repository ni les modèles d'un autre : il passe par la
  **façade service** de l'autre module. Dépendances **vers le bas uniquement** (Plateforme →
  Référentiel → Opérations → Finance → Restitution). Un test d'architecture le vérifie.
- Routers : HTTP uniquement (pas de SQL). Services : invariants et transaction (pas de HTTP).
  Repositories : requêtes filtrées par tenant (pas de règle métier).

**Transactions et données**
- **Une transaction PostgreSQL par cas d'usage**, rollback complet si une étape critique échoue.
- **Contexte tenant** : `SET LOCAL app.company_id` au début de **chaque** transaction, posé par
  **une seule** dépendance FastAPI. `SET` sans `LOCAL` est **interdit**. `DISCARD ALL` au retour
  d'une connexion dans le pool. Le `company_id` vient **du serveur** (JWT → utilisateur en base),
  jamais d'un en-tête ni d'un paramètre client.
- Rôle applicatif `coges_app` : ni superuser, ni `BYPASSRLS`, **pas de DELETE** (suppression logique).
- **Montants** : `NUMERIC` en base, `Decimal` en Python, chaînes dans le JSON. **Jamais de float.**
  Montants `numeric(14,2)`, quantités `(14,3)`, coûts unitaires `(14,4)`, taux `(6,4)`.
- **Stock** = projection de `inventory_movements` (journal append-only). Aucun code n'écrit
  `product_stock`. Stock négatif **interdit** partout. Valorisation **CMP** uniquement.
- **Prix** historisés dans `product_prices` (jamais sur `products`). Taxes et coûts **figés** sur
  la ligne à la confirmation, jamais relus ensuite.
- **Vente** : `draft` (aucun effet de bord) → `POST /api/v1/sales/{id}/confirm` (stock, finance,
  dette, audit critique, outbox, dans une seule transaction).

**Événements et audit**
- Événements en **notation pointée** `namespace.action`, **uniquement** : `sale.confirmed`,
  `sale.cancelled`, `sale.returned`, `sale_return.refunded`, `stock.updated`,
  `payment.received`, `payment.cancelled` (ADR 0038), `debt.created`, `debt.settled`,
  `expense.created`. Un nouveau type d'événement = une décision à faire valider.
- Outbox écrite **dans la transaction** métier, publiée **après COMMIT** uniquement. Consommateurs
  idempotents.
- **Audit critique** (dans la transaction) pour : données financières, suppressions logiques
  importantes, rôles/permissions, paramètres sensibles, dettes, paiements, annulations/retours,
  ajustements manuels de stock. Le reste passe par l'audit secondaire (asynchrone).

**Intelligence**
- Lecture seule, hors transactionnel, **aucun calcul ML dans une requête HTTP**. L'API ne lit que
  `forecasts` et `insights`. Désactivable sans casser CoGes.
- Toute recommandation **nomme sa métrique** (8 métriques distinctes, jamais fusionnées) et affiche
  la date de calcul, le modèle et sa version, l'incertitude. « Données insuffisantes » plutôt
  qu'une valeur inventée. Jamais « meilleur produit ».

**Sécurité**
- JWT courts + refresh rotatif, Argon2, RBAC **côté serveur** (le front ne fait que masquer).
- Accès à la ressource d'un autre tenant ⇒ **404** (jamais 403).
- Pydantic strict, limitation de débit, clés d'idempotence sur les écritures financières, secrets
  hors dépôt (`.env` ignoré, `.env.example` versionné).

**Périmètre**
- **Hors V1** (ne rien préparer au-delà des frontières existantes) : devis, commandes, achats
  avancés, multi-entrepôts, variantes, avoirs, comptabilité générale, multi-devises, CRM, RH,
  paie, mobile, hors ligne, microservices, Kafka/RabbitMQ, agents conversationnels.

## 5. Conventions

- **Python 3.12**, typage strict (`mypy --strict` sur `app/`), `ruff` (lint + format).
- Endpoints : `/api/v1/<ressource>` au pluriel, pagination obligatoire sur les listes
  (`?page=&page_size=`, max 100), erreurs au format `{ "error": { "code", "message", "details" } }`.
- Codes d'erreur métier stables en anglais `snake_case` (`insufficient_stock`,
  `sale_not_draft`…), messages affichés en français.
- Migrations Alembic **réversibles** (`upgrade` + `downgrade` testés), jamais lancées au démarrage
  de l'API.
- Tests : `backend/tests/{unit,integration,tenancy,architecture}`. Les tests d'intégrité portent
  le numéro du modèle dans leur nom : `test_t06_negative_stock_on_sale`.
- Frontend : types générés depuis l'OpenAPI dans `frontend/types/`, jamais écrits à la main.
- Formats d'affichage : `1 234 567 FCFA` (espace fine insécable, pas de décimales pour XOF),
  dates `jj/mm/aaaa`, heures 24 h, fuseau de l'entreprise.

## 6. Commandes utiles

Toutes les cibles s'exécutent depuis la **racine** du dépôt et délèguent au projet uv
`backend/` (`uv run --directory backend`). `make help` liste les cibles.

```bash
cp .env.example .env         # une fois, puis remplacer les valeurs
make install                 # uv sync + installation des hooks pre-commit
make up / make down          # PostgreSQL 16 + Redis 7 en local (docker compose, --wait)
make logs / make psql        # journaux des services / psql en coges_app sur coges
make migrate                 # alembic upgrade head (rôle propriétaire, jamais au boot de l'API)
make test                    # pytest (toutes suites, sauf le marqueur perf)
make test-tenancy            # tests de fuite inter-tenant (bloquants en CI)
make test-perf               # latence de GET /dashboard sur le jeu de démo (< 200 ms)
make openapi / make requirements   # régénère backend/openapi.json / requirements.txt (Vercel)
make check-generated         # échoue si l'un des deux n'est pas à jour (CI)
deploy/scripts/restore-check.sh    # sauvegarde → restauration → contrôles, en local
make lint                    # ruff check + ruff format --check + mypy --strict
make format                  # ruff format + ruff check --fix
make api                     # uvicorn → http://localhost:8000/api/v1/health
make worker                  # celery worker + beat
make relay                   # relais de l'outbox (rôle coges_relay, processus séparé)
make seed-demo               # entreprise de démo : 20 produits, 50 ventes sur 60 jours
uv run --directory backend python -m app.cli create-company --help   # créer une entreprise
uv run --directory backend python -m app.cli rebuild-stock --company-id <uuid>   # recalcul stock/CMP
uv run --directory backend python -m app.cli run-intelligence --company-id <uuid> [--as-of AAAA-MM-JJ] [--train]
cd frontend && pnpm dev      # à partir de la phase 11 (corepack enable pnpm)
```

## 7. Carte du dépôt

```
coges/
├── CLAUDE.md                  ← ce fichier
├── docs/
│   ├── architecture/          ← PDF sources + extraits texte + README (index par ligne)
│   ├── design/                ← référence visuelle du prototype, puis DESIGN.md (Impeccable)
│   ├── decisions/             ← ADR (une décision = un fichier)
│   ├── guides/                ← guides d'usage (formats d'import…)
│   └── prompts/               ← prompts de phase 00 → 14
├── backend/                   ← FastAPI, modules, workers, migrations, tests (dont tests/perf)
├── frontend/                  ← Next.js App Router
└── deploy/                    ← docker-compose worker, README-infra
```

## 8. Avancement

Légende : ⬜ à faire · 🟨 en cours · ✅ terminé (tests verts) · ⛔ bloqué

| Phase | Prompt | Prérequis | Tests exigés | Statut |
|---|---|---|---|---|
| 00 Initialisation du dépôt | `docs/prompts/00-initialisation.md` | — | CI verte à vide | ✅ |
| 01 Socle tenant + RLS | `01-socle-tenant-rls.md` | 00 | T1–T5, T36–T37, architecture | ✅ |
| 02 Auth, utilisateurs, RBAC, audit, outbox | `02-auth-rbac-audit.md` | 01 | fuite générique, RBAC | ✅ |
| 03 Référentiels et prix | `03-referentiels.md` | 02 | fuite, FK croisées (T5) | ✅ |
| 04 Stock et CMP | `04-stock-cmp.md` | 03 | T6–T13, T38 | ✅ |
| 05 Ventes (draft → confirm → cancel, reçu) | `05-ventes.md` | 04 | T14–T17, T23–T24, T39 | ✅ |
| 06 Retours et remboursements | `06-retours.md` | 05 | T18–T22 | ✅ |
| 07 Finance de gestion | `07-finance.md` | 06 | T25–T28 | ✅ |
| 08 Async, analytics, dashboard, notifications | `08-async-analytics.md` | 07 | T29–T32, T40 | ✅ |
| 09 CoGes Intelligence | `09-intelligence.md` | 08 | T33–T35 | ✅ |
| 10 Import/export, durcissement, déploiement | `10-durcissement-deploiement.md` | 09 | T1–T40 en CI | 🟨 temps A ✅ ; temps B livré (code, CI, docs, 620 tests verts) — **préprod en ligne en attente du provisionnement** (`deploy/README-infra.md`) |
| 11 Front : fondations et design system | `11-front-fondations.md` | 10 (ou 07 + OpenAPI stable) | e2e login | ⬜ |
| 12 Front : opérations | `12-front-operations.md` | 11 | e2e vente | ⬜ |
| 13 Front : finance, pilotage, paramètres | `13-front-pilotage.md` | 12 | e2e | ⬜ |
| 14 Finition visuelle (Impeccable) | `14-polish-impeccable.md` | 13 | audit Impeccable | ⬜ |

## 9. Journal des décisions

| # | Date | Décision | Fichier |
|---|---|---|---|
| 0001 | 2026-09-23 | Outillage (uv, GitHub Actions, docker compose, pre-commit, pnpm) et **SQLAlchemy synchrone + psycopg 3** | `docs/decisions/0001-outillage.md` |
| 0002 | 2026-09-23 | Schéma V1.1 direct, une révision Alembic par phase ; ENUM dès 0001 ; base de test `coges_test` migrée | `docs/decisions/0002-strategie-migrations.md` |
| 0003 | 2026-09-23 | RLS : `NULLIF(current_setting(…), '')::uuid` et `RESET ALL` au retour au pool (écart démontré au § 8.11) | `docs/decisions/0003-politique-rls-nullif.md` |
| 0004 | 2026-09-23 | Contexte via `set_config(…, true)` dans `core/tenancy.py` seul ; tenant amorcé par UUID pré-généré ; privilèges par défaut, `permissions` en lecture seule | `docs/decisions/0004-contexte-tenant-et-privileges.md` |
| 0005 | 2026-09-23 | Connexion : `auth_lookup` SECURITY DEFINER appartenant à `coges_auth` (NOLOGIN BYPASSRLS) ; table `auth_sessions`, refresh rotatif avec détection de réutilisation | `docs/decisions/0005-connexion-et-sessions.md` |
| 0006 | 2026-09-23 | Access token en mémoire (15 min), refresh en cookie `httpOnly` (7 j), clé JWT ≥ 32 caractères | `docs/decisions/0006-transport-des-jetons.md` |
| 0007 | 2026-09-23 | Matrice RBAC gérant/vendeur/comptable ; DELETE accordé sur exactement `user_roles`, `role_permissions`, `roles` | `docs/decisions/0007-matrice-rbac.md` |
| 0008 | 2026-09-23 | `ensure_audit_partition` + partition DEFAULT, RLS par partition, audit append-only, `CHECK` sur les 9 événements | `docs/decisions/0008-audit-partitionne-et-outbox.md` |
| 0009 | 2026-09-23 | Onboarding par `python -m app.cli create-company`, pas d'inscription publique en V1 | `docs/decisions/0009-onboarding-par-cli.md` |
| 0010 | 2026-09-23 | **Gabarit d'un module métier** : 6 fichiers (pas d'`events.py` sans événement), erreurs métier nommées en 409, bornes de saisie dans le schéma | `docs/decisions/0010-gabarit-de-module.md` |
| 0011 | 2026-09-23 | Prix : premier intervalle obligatoire à la création, changement = fermeture + ouverture à `now()` sous audit critique, `created_by` toujours renseigné | `docs/decisions/0011-prix-historises.md` |
| 0012 | 2026-09-23 | La vue « produits + stock » sera un endpoint d'Inventory (phase 04) ; `product_stock` non créée en 0003 | `docs/decisions/0012-produits-et-stock.md` |
| 0013 | 2026-09-23 | Codes tiers `CLI-0001`/`FRN-0001` générés par entreprise et modifiables ; recherche trigramme sur le nom, égalité stricte sur les codes | `docs/decisions/0013-codes-tiers-et-recherche.md` |
| 0014 | 2026-09-23 | Une règle inter-modules interdite par le sens des dépendances descend en base : trigger `categories_guard_soft_delete` + SQLSTATE traduits | `docs/decisions/0014-garde-de-suppression-en-base.md` |
| 0015 | 2026-09-23 | `occurred_at` borné des deux côtés : 48 h d'antidatage au plus (`CG010`), jamais dans le futur (`CG011`, révision 0005) | `docs/decisions/0015-antidatage-des-mouvements.md` |
| 0016 | 2026-09-23 | Ajustement positif : `unit_cost` par défaut = CMP courant, surchargeable ; refus si aucun CMP à reprendre | `docs/decisions/0016-cout-d-un-ajustement-positif.md` |
| 0017 | 2026-09-23 | Correction d'un mouvement par `POST /inventory/movements/{id}/reverse`, gérant seul, audit critique | `docs/decisions/0017-correction-par-mouvement-inverse.md` |
| 0018 | 2026-09-23 | Écarts assumés au § 8.5 : SQLSTATE `CG020`/`CG021`, `insufficient_stock` en 409, aucun `REVOKE` (le `FOR SHARE` exige UPDATE), `refresh` après `flush` | `docs/decisions/0018-ecarts-assumes-au-paragraphe-8-5.md` |
| 0019 | 2026-09-24 | **P6 tranché** : la révision 0006 crée toutes les tables des § 8.4 et § 8.6 ; un seul module `finance/` (sans router), services complétés en 06 et 07 | `docs/decisions/0019-ordre-des-phases-ventes-et-finance.md` |
| 0020 | 2026-09-24 | DELETE accordé sur `sale_items` — quatrième et dernière exception, bornée par `sale_items_no_change` ; T36 passe à 4 tables | `docs/decisions/0020-delete-sur-les-lignes-de-brouillon.md` |
| 0021 | 2026-09-24 | `document_counters` : suite sans trou par entreprise (`V-000123`), numéro attribué dès le brouillon, générique pour les retours et les dépenses | `docs/decisions/0021-numerotation-des-documents.md` |
| 0022 | 2026-09-24 | `tax_enabled` absent ⇒ taxes actives ; reçu en JSON refusé sur brouillon ; second `confirm` ⇒ 409 `sale_not_draft` | `docs/decisions/0022-ce-que-la-vente-promet-au-client.md` |
| 0023 | 2026-09-24 | Écarts assumés au § 8.7 : `sale_items_frozen` étendu à l'INSERT, SQLSTATE `CG030` ; annulation du § 5.2 appliquée telle quelle. **Corrigé par la révision 0007** : le plafond de crédit se lit `FOR UPDATE`, sans quoi il ne tient pas sous concurrence | `docs/decisions/0023-ecarts-assumes-au-paragraphe-8-7.md` |
| 0024 | 2026-09-24 | Compensation d'une dette par un retour : `offset` entre dans `pay_method`, deux paiements sans flux de caisse (un `outflow` lettré au retour, un `inflow` alloué à la dette) ; **la trésorerie exclut `method = 'offset'`** | `docs/decisions/0024-compensation-d-une-dette-par-un-retour.md` |
| 0025 | 2026-09-24 | Retours : numéro `R-000123` par `document_counters`, règlement en une ou plusieurs fois après coup, `sale_returns:confirm` (gérant) garde l'argent, aucun délai maximal, aucun renoncement (`none_due` reste dérivé du montant nul) | `docs/decisions/0025-ce-que-le-retour-promet-et-ce-qu-il-ne-promet-pas.md` |
| 0026 | 2026-09-24 | Écarts assumés au § 8.7 (suite) : SQLSTATE `CG040`–`CG045`, remboursable arrondi net et taxe séparément (retour total = `line_total`), aucun événement pour le paiement d'un remboursement | `docs/decisions/0026-ecarts-assumes-au-paragraphe-8-7-suite.md` |
| 0027 | 2026-09-24 | **P4 tranché** : table `idempotency_keys` sous RLS, `Idempotency-Key` obligatoire sur **toutes** les écritures financières (y compris `confirm` et les remboursements) ; réservation sous `SAVEPOINT`, concurrence réglée par l'index unique | `docs/decisions/0027-cles-d-idempotence.md` |
| 0028 | 2026-09-24 | Module `expenses/` à part ; `kind` reste sur la catégorie et se fige dès qu'elle porte des charges ; colonne `expenses.expense_no` (`D-000001`), écart assumé au § 8.6 | `docs/decisions/0028-module-depenses.md` |
| 0029 | 2026-09-24 | Dette fournisseur saisie à la main ; abandon de créance réservé au gérant (`debts:write_off`, motif obligatoire, audit critique, aucun événement), autorisé sur une dette partiellement payée | `docs/decisions/0029-dettes-manuelles-et-abandon.md` |
| 0030 | 2026-09-24 | **Module `analytics/` de bande E** : `GET /api/v1/analytics/overview`, composition des façades (Finance ne peut pas appeler Sales) ; marge aux définitions du § 4.10, calcul direct puis agrégats en phase 08 | `docs/decisions/0030-marge-estimee-et-module-analytics.md` |
| 0031 | 2026-09-24 | Écarts assumés de la phase 07 : 409 pour l'état / 422 pour la demande, sens de l'allocation en applicatif, `paid_at` jamais futur, **correction d'un paiement repoussée** (aucune colonne au § 8.6) | `docs/decisions/0031-ecarts-assumes-de-la-phase-07.md` |
| 0032 | 2026-09-25 | **Chemin asynchrone** : relais en processus dédié sous `coges_relay` (aucune table, deux fonctions `SECURITY DEFINER` de `coges_bus`), `coges_analytics` seul rôle avec DELETE ; `processed_events` écrite dans la transaction de l'effet ; rebut **en base** après 10 tentatives, exposé par `GET /system/outbox` ; alertes adressées par **droit**, dédoublonnées 24 h, canal in-app derrière un `Protocol` ; cache Redis par tenant, TTL 60 s + invalidation par événement | `docs/decisions/0032-chemin-asynchrone.md` |
| 0033 | 2026-09-25 | **Huit métriques produit** : 1 à 7 calculées à la lecture, `future_potential` renvoyée à la phase 09 ; stock moyen reconstitué fin de journée par fin de journée (pas `(début+fin)/2`) ; un stock moyen nul **écarte** le produit ; chaque réponse nomme sa métrique, son libellé et son unité | `docs/decisions/0033-metriques-produit-et-rotation.md` |
| 0034 | 2026-09-25 | Écarts assumés de la phase 08 : l'overview devient **éventuellement cohérent**, `sale_count` reste compté sur `sales`, produits arrondis **à la ligne** dans les deux sources de T32, bornes de période dans le fuseau de l'entreprise, `SET LOCAL ROLE` dans la révision 0010 | `docs/decisions/0034-ecarts-assumes-de-la-phase-08.md` |
| 0035 | 2026-09-25 | **Intelligence** : numpy + pandas + statsmodels (groupe `ml`, worker seul, test d'architecture), seuil 28 j + 5 jours vendus/60, artefacts JSON sur le volume du worker, **point-in-time strict** sur les horodatages métier | `docs/decisions/0035-intelligence-bibliotheques-seuils-artefacts.md` |
| 0036 | 2026-09-25 | `settings.intelligence_enabled` par entreprise (absent = activée), aucun palier ; **privilèges en GRANT** : `coges_app` sans accès aux snapshots, SELECT seul sur `forecasts`, UPDATE (`status`, dates) sur `insights` ; aucun DELETE | `docs/decisions/0036-desactivation-et-privileges-intelligence.md` |
| 0037 | 2026-09-25 | Écarts de la phase 09 : ENUM `insufficient_history`, dossier `estimators/`, révision 0011, horizons J+14 / rupture sous 28 j, champs additifs de la métrique 8 | `docs/decisions/0037-ecarts-assumes-de-la-phase-09.md` |
| 0038 | 2026-09-25 | **Annulation d'un paiement par contre-écriture** (révision 0012) : `reversal_of_payment_id` unique, rollups sur les lettrages vivants, paiement annulé et annulation hors trésorerie, `offset` par paire, 10ᵉ événement `payment.cancelled`, gérant + comptable, refus sur dette abandonnée ; correction = annuler puis ressaisir | `docs/decisions/0038-annulation-d-un-paiement-par-contre-ecriture.md` |
| 0039 | 2026-09-26 | Annulation : paiements **puis** dettes verrouillés (ordre des ids) avant l'audit « before » ; **idempotence par ressource** : `confirm` et `refunds` enregistrent l'id dans l'endpoint de la clé | `docs/decisions/0039-verrous-de-l-annulation-et-idempotence-par-ressource.md` |
| 0040 | 2026-09-26 | **Hébergeurs** : Neon (gratuit en préprod, Launch sans veille en prod), Redis Cloud, API en fonction Vercel (Hobby puis Pro), zone B sur le poste en préprod ; relais espacé jusqu'à 10 min quand l'outbox est vide ; pooler en mode transaction ⇒ `NullPool` + `prepare_threshold=None`, migrations sur l'hôte direct | `docs/decisions/0040-hebergeurs-et-pooler.md` |
| 0041 | 2026-09-26 | **Import/Export** : CSV + .xlsx, `dry_run` puis même fichier, tout ou rien avec un savepoint par ligne pour un rapport complet ; pas de ventes historiques ; exports de ventes par le worker dans `export_files` (révision 0013, 10 Mo, 24 h, purge sans DELETE) ; enfilement par nom depuis l'API (`core/queue.py`) | `docs/decisions/0041-import-et-export.md` |
| 0042 | 2026-09-26 | **Sécurité** : débit par IP, connexion et entreprise (Redis, levé si panne), 413, en-têtes, CORS ; `Idempotency-Key` aussi sur la création d'un retour ; garde-fous `coges_owner` (refus au démarrage, DSN confiné vérifié en CI, appartenance conservée) ; Sentry sans PII ; `openapi.json` versionné | `docs/decisions/0042-securite-et-observabilite.md` |
| 0043 | 2026-09-26 | **P8 tranché** : aucun palier commercial dans le code V1 | `docs/decisions/0043-pas-de-palier-commercial-en-v1.md` |

Points ouverts connus, à trancher dans leur phase : voir `docs/architecture/README.md` (P1-P8).
P1 à P6 et P8 sont tranchés (ADR 0002, 0005, 0005, 0027, 0015, 0019, 0043) ; reste **P7**
(signalé, hors V1 technique).

> **Backend V1 terminé (code)** — 22 groupes, 97 opérations sous `/api/v1`. Contrat :
> `backend/openapi.json` (versionné, vérifié en CI, `make openapi`) ; servi hors production sur
> `/api/v1/openapi.json`, documentation interactive `/api/v1/docs`.
> Plateforme `health` · `auth` (login, refresh, logout) · `companies/me` · `users` · `roles`,
> `permissions` · Référentiel `categories` · `products` (+ `prices`) · `customers` · `suppliers` ·
> Opérations `inventory` (stock, movements, reverse) · `sales` (brouillon, items, confirm, cancel,
> receipt, returns) · `sale-returns` (refunds) · Finance `payments` (+ cancel) · `debts`
> (+ write-off) · `expense-categories` · `expenses` · Restitution `analytics` (overview,
> products, timeseries) · `dashboard` · `notifications` · `insights`, `forecasts`,
> `intelligence/summary` · `imports/{kind}` (+ template) · `exports` (referentials, sales, file) ·
> `system/outbox`. Reste : la mise en ligne de la préproduction (provisionnement,
> `deploy/README-infra.md`).

## 10. Ce que tu ne fais jamais

- Contourner une contrainte, un trigger ou la RLS pour qu'un test passe.
- Écrire du SQL dans un router, un appel HTTP dans un service, une règle métier dans un repository.
- Ajouter une fonctionnalité hors V1 « parce que c'est facile ».
- Utiliser `float` pour un montant, `SET` sans `LOCAL`, ou lire un `company_id` venant du client.
- Modifier un fichier de `docs/architecture/` : si tu y trouves une erreur, signale-la et propose
  une décision.
- Continuer après un choix structurant sans l'avoir fait valider avec `AskUserQuestion`.
