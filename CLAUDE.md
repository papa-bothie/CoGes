# CLAUDE.md — Tour de contrôle du projet CoGes

> Ce fichier est lu au début de chaque session Claude Code. Il donne les règles du projet, la
> façon de travailler et l'état d'avancement. **Il prime sur tes habitudes par défaut.**
> Mets-le à jour à la fin de chaque phase (section « Avancement » et « Décisions »), sans le
> faire grossir inutilement : les détails vont dans `docs/`.

---

## 1. Le projet en 10 lignes

CoGes est un **logiciel de gestion pour PME ouest-africaines** (pas un ERP), centré sur le cycle
**vente → stock → argent → décision**. Tout ce qui n'est pas nécessaire à ce cycle est hors V1.

- **Backend** : monolithe modulaire **FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 18** (version majeure de la production Neon, suivie par la CI, le poste et la sauvegarde, ADR 0095).
- **Asynchrone** : outbox transactionnelle `business_events` → relais → **Redis** → **Celery** (Docker).
- **Frontend** : **Next.js (App Router) + TypeScript**, qui n'appelle **que** l'API REST `/api/v1`.
  L'administration de la plateforme est une application à part, `frontend-admin/` (ADR 0089).
- **Déploiement** : tout sur un **VPS** Infomaniak en Docker (Caddy, front, API, Redis, worker, beat, relais) ; PostgreSQL chez **Neon** (ADR 0083, remplace l'ADR 0040).
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
- **Hors des cinq bandes** : `modules/platform/` (administration de la plateforme, ADR 0089)
  n'importe aucun module métier et n'est importé par aucun ; il ne parle qu'au rôle
  `coges_app_platform` (métadonnées colonne par colonne, **aucune** table commerciale), sous
  `/api/v1/platform/*`, avec son propre jeton (audience `coges-platform`). Seule exception
  (ADR 0092) : l'accès support écrit l'ouverture et la fermeture dans le journal **de
  l'entreprise**, en `coges_app` dans son contexte ; le jeton de support lit par le chemin
  de tout utilisateur (RLS, transaction `READ ONLY`), jamais par un rôle privilégié.
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
- Toute recommandation **nomme sa métrique** (9 métriques distinctes, jamais fusionnées ; la 9ᵉ « jours sans vente », ADR 0074) et affiche
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
- Tests : `backend/tests/{unit,integration,tenancy,architecture}`.
- **Registres imposés par la CI** (ADR 0086) : toute nouvelle route d'écriture se classe dans
  `tests/integration/commit_failure_registry.py`, toute lecture sans paramètre dans `READ_ROUTES`
  (`tests/tenancy/test_list_routes_cross_tenant.py`), toute route paramétrée dans
  `CROSS_TENANT_ROUTES`, toute tâche planifiée dans `test_beat_tasks_tenant_isolation.py`,
  toute table sans RLS dans `TABLES_WITHOUT_RLS` ; une clé Redis nouvelle doit suivre
  `test_redis_keys_isolation.py`. Les tests d'intégrité portent
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
make dev                     # API + worker + relais + front ensemble (honcho, Procfile.dev)
make up / make down          # PostgreSQL 18 + Redis 7 en local (docker compose, --wait)
make db-upgrade-18           # poste d'avant l'ADR 0095 : après ce lot, lancer make db-upgrade-18 ou make up && make migrate && make seed-demo
make logs / make psql        # journaux des services / psql en coges_app sur coges
make migrate                 # alembic upgrade head (rôle propriétaire, jamais au boot de l'API)
make test                    # pytest (toutes suites, sauf le marqueur perf)
make test-tenancy            # tests de fuite inter-tenant (bloquants en CI)
make test-perf               # latence de GET /dashboard sur le jeu de démo (< 200 ms)
make openapi / make requirements   # régénère backend/openapi.json / requirements.txt (Vercel, jusqu'à son arrêt)
make check-generated         # échoue si l'un des deux n'est pas à jour (CI)
deploy/scripts/restore-check.sh    # sauvegarde → restauration → contrôles, en local
make shellcheck              # shellcheck des scripts du VPS et de deploy/scripts
make invariants SLUG=demo    # recoupe stock, ventes, dettes et lettrages d'une entreprise locale (ADR 0086)
deploy/scripts/backup_chain_check.sh   # preuve sauvegarde → restauration → contrôles (ADR 0084, docs/runbooks/sauvegarde.md)
sudo -u deploy /opt/coges/deploy.sh production vX.Y.Z   # sur le VPS : déployer (rollback, status ; preprod stop)
/opt/coges/check.sh          # sur le VPS : bilan disque, mémoire, conteneurs, certificat, Neon
make lint                    # ruff check + ruff format --check + mypy --strict
make format                  # ruff format + ruff check --fix
make security-scan           # gitleaks (tout l'historique), pip-audit, pnpm audit --prod ; exceptions dans security/
make api                     # uvicorn → http://localhost:8000/api/v1/health (et /health/ready : base + Redis)
make worker                  # celery worker + beat
make relay                   # relais de l'outbox (rôle coges_relay, processus séparé)
make ops-status              # bilan workers/beat/relais/tâches de nuit (COGES_OPS_TOKEN ; COGES_OPS_URL) — docs/runbooks/workers.md
make seed-demo               # épicerie de démo `demo` : 46 articles, 15 clients, 90 jours (≈ 1 200 ventes)
make seed-maquette           # entreprise `maquette` de la maquette v2 (Keur Fatou, 6 octobre 2026 à 10 h 45)
make maquette-check          # compare le front à la maquette v2 (pixelmatch, 2 %) ; MAQUETTE_ALL=1 : tous les écrans
make lighthouse              # accessibilité Lighthouse des 26 écrans (≥ 95), rapport docs/design/captures/phase-15/lighthouse.md
uv run --directory backend python -m app.seed --existing-slug <slug> --password …   # remplit une entreprise existante sans vente
uv run --directory backend python -m app.cli create-company --help   # créer une entreprise
uv run --directory backend python -m app.cli create-company … --manager-phone "77 123 45 67"   # gérant sans e-mail (--manager-email ou --manager-phone, l'un au moins)
uv run --directory backend python -m app.cli rebuild-stock --company-id <uuid>   # recalcul stock/CMP
uv run --directory backend python -m app.cli run-intelligence --company-id <uuid> [--as-of AAAA-MM-JJ] [--train]
make front-install           # pnpm (corepack) + dépendances + Chromium pour Playwright
make front-dev               # Next sur :3000, /api/v1 réécrit vers COGES_API_URL (défaut http://localhost:8000)
make front-api               # régénère frontend/types/api.ts après `make openapi`
make front-check             # types à jour, lint, typecheck, Vitest, build (ce que joue la CI)
make admin-check / admin-e2e # administration (frontend-admin/, :3200) : mêmes contrôles, parcours sur coges_e2e
make create-platform-user EMAIL=… NAME="…" ROLE=administrator|support   # compte de l'équipe (jamais de route publique)
make front-e2e               # e2e-reset puis Playwright sur coges_e2e (API :8100 et front :3100 lancés seuls), axe AA bloquant
make e2e-reset / e2e-api / e2e-front   # base e2e recréée (migrations + seed) / API e2e sans limite de débit / front e2e
CAPTURES_STAGE=apres make front-e2e   # + captures clair/sombre de la phase 14 (docs/design/captures/phase-14/<étape>/)
COGES_FROZEN_NOW=2026-10-06T10:45:00+00:00 make api   # « aujourd'hui » figé pour les lectures (local et CI seulement)
make api API_PORT=8001       # si le port 8000 est déjà pris ; front : COGES_API_URL=http://localhost:8001
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
│   ├── prompts/               ← prompts de phase 00 → 20
│   └── runbooks/              ← guides d'intervention (vps, déploiement, workers, sauvegarde)
├── backend/                   ← FastAPI, modules, workers, migrations, tests (dont tests/perf)
├── frontend/                  ← Next.js App Router (commerçants)
├── frontend-admin/            ← administration de la plateforme (ADR 0089), sur admin.<domaine>
└── deploy/                    ← vps/ (compose, Caddyfile, bootstrap, deploy.sh), scripts, README-infra
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
| 10 Import/export, durcissement, déploiement | `10-durcissement-deploiement.md` | 09 | T1–T40 en CI | ✅ préprod en ligne (`https://coges-api.vercel.app`, zone B sur le poste) ; prod à ouvrir |
| 11 Front : fondations et design system | `11-front-fondations.md` | 10 (ou 07 + OpenAPI stable) | e2e login | ✅ 61 Vitest, 6 e2e locaux ; préversion `coges-web` en ligne, connexion vérifiée contre la préprod |
| 12 Front : opérations | `12-front-operations.md` | 11 | e2e vente | ✅ 81 Vitest, 16 e2e locaux (vente, survente, retour, ajustement, produits, clients, fournisseurs) ; captures `docs/design/captures/phase-12/` |
| 13 Front : finance, pilotage, paramètres | `13-front-pilotage.md` | 12 | e2e | ✅ 92 Vitest, 26 e2e locaux (dont paiement réparti, métrique, insight écarté, vendeur sans paramètres) ; 674 tests backend ; captures `docs/design/captures/phase-13/` |
| 14 Finition visuelle (Impeccable) | `14-polish-impeccable.md` | 13 | audit Impeccable | ✅ audit 13/20 → 18/20, axe 241 → 0 violation (clair + sombre), 96 Vitest, 30 e2e ; `docs/design/DESIGN.md` ; captures `docs/design/captures/phase-14/` |
| 15 Simplicité d'abord | `15-refonte-simplicite.md` | 14 | bugs B1–B3, test du commerçant, axe, captures | ✅ lots 0, F, 1, 2, 3a à 3e-2 fusionnés (PR n° 8 à 17) : maquette v2 sur les 26 écrans (41 écrans et états comparés, `make maquette-check`), bugs B1–B3, test du commerçant en e2e, axe 0 en clair et en sombre, Lighthouse accessibilité 100 (`make lighthouse`), audit Impeccable 18/20 conservé (`docs/design/audit-phase-15.md`), démo garantie par test ; révisions 0015 à 0020 ; ADR 0063 à 0076 |
| Lot A Sécurité avant la production | `16-securite-lot-a.md` | 15 | expiration du provisoire, freinage A2/A3, échec au COMMIT, analyses de sécurité | ✅ PR n° 21 : ADR 0078 à 0080, révision 0022, 977 tests backend, CI verte (gitleaks, pip-audit, pnpm audit) ; préprod migrée |
| Surveillance des workers (zone B) | `17-surveillance-workers.md` | 15 | battement absent, `job_runs` en échec, `/system/workers` en 503, fuite inter-tenant | ✅ PR n° 20 (ADR 0077, révision 0021) puis n° 22 (`/health/ready`, ADR 0081) ; `/health/ready` en 200 sur la préprod |
| Tout CoGes sur le VPS (sauf la base) | `18-vps-zone-b.md` | 17 | shellcheck, 4 images, pile locale + e2e, `deploy.sh`, `check_runtime_env --require-vps` | ✅ PR n° 25 : ADR 0083, images front/api/worker/bundle, pile locale derrière Caddy + 67 e2e ; VPS à installer par le propriétaire (`docs/runbooks/vps.md`) |
| Sauvegarde chiffrée et page d'erreur | `19-sauvegarde-et-page-erreur.md` | 18 | chaîne de sauvegarde en CI, refus de restauration, 500 stable, e2e coupure et rejeu | ✅ PR n° 26 : ADR 0084 et 0085, révision 0023 (`create_backup_role.sql` sur Neon avant), chaîne de sauvegarde prouvée en CI, Lighthouse 100 |
| Lot C Intégrité et isolation prouvées | `20-integrite-lot-c.md` | 16 | C1 à C5, registres découverts, invariants | ✅ PR n° 27 : ADR 0086, 1263 tests backend, 51 écritures critiques, registres découverts ; entreprise supprimée ⇒ sessions fermées (`core/deps.py`) |
| Correctifs de la revue, partie 1 | `21-correctifs-de-la-revue.md` | 20 | chaque constat reproduit (test rouge) puis corrigé | ✅ PR n° 29 : ADR 0087, révision 0024, 8/8 reproduits et corrigés |
| Correctifs de la revue, partie 2 | `21-correctifs-de-la-revue.md` | partie 1 fusionnée | idem, tableau reproduit / non reproduit / reporté | ✅ PR n° 30 : ADR 0088, révision 0025, 25 points (2 non reproduits, 2 reportés) |
| Lot admin 1 : rôle plateforme, statut, métadonnées | `22-admin-role-plateforme.md` | 21 | jetons séparés dans les deux sens, GRANT du rôle énumérés, suspension à la requête suivante, A et B visibles sans donnée commerciale, e2e admin | ✅ PR n° 32 : ADR 0089, révision 0026, `frontend-admin/` (Next 16.4.2), 1734 tests backend, 259 + 8 Vitest, 69 + 4 e2e ; `create_platform_role.sql` sur Neon avant 0026 |
| Lot admin 2 : surveillance système en version web | `23-admin-surveillance-web.md` | admin 1 | deux portes à l'octet près, job-runs et outbox sans donnée commerciale, bandeau de panne sur tout écran (e2e) | ✅ PR n° 33 : ADR 0090, révision 0027, 1763 tests backend, 22 Vitest et 6 e2e admin |
| Lot admin 3 : abonnements, offres, essai | `24-admin-abonnements.md` | admin 1 | plafond d'utilisateurs en base (exact, un de moins, sans plafond, réactivation, concurrence), essai J-8/J-7/J-3/J-1/J+0 et relance, descente refusée, paiement idempotent, cloisonnement | ✅ PR n° 34 : ADR 0091, révision 0028, 1814 tests backend, 259 + 27 Vitest, 69 + 7 e2e ; `create_billing_role.sql` sur Neon avant 0028 |
| Lot admin 4 : accès support encadré | `25-admin-support-encadre.md` | admin 1 | jeton expiré ou fermé refusé à la requête suivante, aucune écriture acceptée, bandeau et journal, isolation, e2e bris de glace complet | ✅ PR n° 35 : ADR 0092, révision 0029, 1949 tests backend, 267 + 32 Vitest, 69 + 8 e2e |
| Lot admin 5 : statistiques | `26-admin-statistiques.md` | admin 1 et 3 | revenu bougé par un paiement seulement, invariant statuts = total, routes classées, e2e de l'écran | ✅ PR n° 36 : ADR 0093, sans révision, 1977 tests backend, 267 + 39 Vitest, 69 + 9 e2e ; l'administration couvre les cinq volets (entreprises, abonnements, système, support, statistiques) |
| Lot admin 6 : interface et accès de l'équipe | `27-admin-interface-et-acces.md` | admin 1 à 5 | invitation (jeton haché, usage unique, renvoi), dernier administrateur, soi-même, support sans écriture, journal sans secret, registre des profils ; partie B : parcours D1 chronométrés, axe clair et sombre, 360 px, Lighthouse | 🟨 partie A ✅ PR n° 37 (ADR 0094, révision 0030, 2046 tests backend) ; partie B (interface) PR n° 38 : thème CoGes et repère ardoise, 6 tâches chronométrées (2, 2, 3, 2, 1, 0 action), 65 Vitest et 20 e2e admin, axe clair et sombre, 360 px, Lighthouse 100 |
| Sauvegarde sur PostgreSQL 18 | prompt 20 du suivi de production | `main` | pg_dump 16 + serveur 18 refusé avec ping /fail, manifeste à deux versions, pg_restore trop ancien refusé, CI et poste en 18, chaîne complète verte sur 18 | ✅ PR n° 39 : ADR 0095, sans révision, CI verte sur 18 (client PGDG 18.6 sur le runner) ; `make db-upgrade-18` sur le poste après fusion |
| Corrections du terrain, C2 : mots de passe | `28-corrections-du-terrain.md` | `main` | bascule afficher / cacher (valeur gardée, remasqué à l'envoi), vendeur et comptable changent leur mot de passe et se reconnectent, axe | ✅ ADR 0098, sans révision ; sessions : règle de l'ADR 0088 inchangée |

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
| 0024 | 2026-09-24 | Compensation d'une dette par un retour : `offset` entre dans `pay_method`, deux paiements sans flux de caisse (un `outflow` lettré au retour, un `inflow` alloué à la dette) ; **la trésorerie exclut `method = 'offset'`**. *Amendé par 0062* : la compensation compte dans `paid_total` (« réglé ») | `docs/decisions/0024-compensation-d-une-dette-par-un-retour.md` |
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
| 0043 | 2026-09-26 | **P8 tranché** : aucun palier commercial dans le code V1 — *remplacée par 0091* | `docs/decisions/0043-pas-de-palier-commercial-en-v1.md` |
| 0044 | 2026-09-27 | Mise en ligne : variables Vercel **chiffrées relisibles** (pas *sensitive*, pour le garde-fou 2), fumée sur le domaine public `COGES_PUBLIC_URL`, `database_url_app` facultatif pour le relais | `docs/decisions/0044-mise-en-ligne-de-la-preproduction.md` |
| 0045 | 2026-09-27 | **Aucune formule dans un export** : `'` devant `= + - @ \t \r` en CSV, tout texte en type chaîne (+ *quotePrefix*) en .xlsx, nombres intacts ; `'` retiré à l'import (aller-retour fidèle) | `docs/decisions/0045-aucune-formule-dans-un-export.md` |
| 0046 | 2026-09-29 | **Pile front** : Next 16 (`proxy.ts`), TS strict, Tailwind 4, shadcn/ui (Radix), TanStack Query, react-hook-form + zod, Recharts, Inter, Vitest + Playwright (e2e en local), mode sombre ; tokens du prototype à l'identique | `docs/decisions/0046-pile-frontend.md` |
| 0047 | 2026-09-29 | **Même origine** : Next réécrit `/api/v1/*` vers `COGES_API_URL` (deux `*.vercel.app` = deux sites, le cookie `Lax` ne passerait pas) ; `openapi-typescript` + `openapi-fetch`, `pnpm check:api` en CI ; `ApiError` | `docs/decisions/0047-client-api-type-et-reecriture.md` |
| 0048 | 2026-09-29 | **`GET /auth/me`** sans permission ; jeton en mémoire rafraîchi à la demande, mutualisé et verrouillé entre onglets ; indicateur `coges_session=1` pour `proxy.ts` ; déconnexion propagée (`BroadcastChannel`, une instance par onglet) | `docs/decisions/0048-jetons-cote-front.md` |
| 0049 | 2026-09-29 | **Redirection ouverte corrigée** : `safeNext(next, origine)` refuse `\` et les caractères de contrôle, résout par `new URL`, exige la même origine et un chemin qui ne commence pas par `//`, refuse `/login` ; appliquée au formulaire, à `loginUrl` et à `proxy.ts` | `docs/decisions/0049-destination-apres-connexion-sans-redirection-ouverte.md` |
| 0050 | 2026-09-29 | **Lectures pour le front** : `product_name`, `sku`, `returned_qty` sur les lignes de vente, `customer_name` sur les ventes, `product_id` répété sur `/inventory/stock` (≤ 100), `customer_id`/`supplier_id` sur `/debts` ; recherche des référentiels **triée par pertinence** | `docs/decisions/0050-enrichissements-de-lecture-pour-le-front.md` |
| 0051 | 2026-09-30 | **Délai de grâce de 30 s** sur la rotation du refresh : jeton tourné < 30 s dont le successeur n'a jamais servi ⇒ nouvelle session, une seule fois, auditée ; sinon réutilisation ⇒ famille révoquée (complète 0005) | `docs/decisions/0051-delai-de-grace-de-la-rotation.md` |
| 0052 | 2026-09-30 | **Écrans opérationnels** : brouillon serveur synchronisé, totaux du serveur, reçu 80 mm/A4, confirmation bloquée si stock affiché insuffisant + erreur serveur sur la ligne, retour en deux temps, clé d'idempotence gardée jusqu'au succès ; écarts au prototype listés. Complément à 0017 : **seuls les mouvements manuels** s'inversent depuis le stock | `docs/decisions/0052-ecrans-operationnels-cote-front.md` |
| 0053 | 2026-09-30 | **Journal d'activité** `GET /audit-logs` (gérant + comptable) ; `roles` sur les utilisateurs, `party_name` sur les dettes, `amount_paid` sur les dépenses ; **dépense payée atomique** (bloc `payment` sous la même `Idempotency-Key`) | `docs/decisions/0053-journal-d-activite-et-lectures-de-pilotage.md` |
| 0054 | 2026-09-30 | `settings.default_reorder_point` appliqué **par le serveur** aux produits suivis sans seuil ; réglages connus vérifiés ; devise en lecture seule à l'écran ; **garde du dernier gérant actif** (409 `last_manager`), routes de rôles d'un utilisateur servies par Users | `docs/decisions/0054-parametres-seuil-par-defaut-et-dernier-gerant.md` |
| 0055 | 2026-09-30 | **Écrans de pilotage** : cartes d'Intelligence compactes + panneau, métrique en liste déroulante nommée sur chaque ligne, période commune dans l'URL, règlement réparti prérempli, journal en lecture ; écarts au prototype listés | `docs/decisions/0055-ecrans-de-pilotage-cote-front.md` |
| 0056 | 2026-10-01 | **Finition visuelle** : identité raffinée, `docs/design/DESIGN.md` fait foi (liens à la racine pour Impeccable) ; Inter + axe optique, échelle par rôle en tokens (déclarée dans `cn`) ; fil d'Ariane, barre latérale repliée sous 1024 px, barre d'actions de vente sous 1280 px ; densité compacte/confortable **dans le navigateur** ; **encres d'état** pour tout texte d'état ; animations discrètes et `prefers-reduced-motion` ; `SegmentedControl` ; axe AA bloquant ; textes de notifications du worker reportés | `docs/decisions/0056-finition-visuelle.md` |
| 0057 | 2026-10-01 | **Recommandations triées par sévérité** (critique, attention, information) puis date, `CASE` explicite ; **textes de notification à la française** par `app/core/display.py` (FCFA fixe, `jj/mm/aaaa`, quantités du front), `data` inchangé | `docs/decisions/0057-tri-des-recommandations-et-textes-de-notification.md` |
| 0058 | 2026-10-01 | **Front déployé avec l'API** à chaque push sur `main` (production Vercel de `coges-web`, adresse stable publique `https://coges-app.vercel.app`), après le test de fumée de l'API ; fumée du front à travers sa réécriture ; garde-fou 2 étendu à `coges-web` | `docs/decisions/0058-deploiement-automatique-du-front.md` |
| 0059 | 2026-10-01 | **Cibles tactiles 44 px** sur `pointer: coarse` (composants partagés, ordinateur inchangé) ; **e2e sur `coges_e2e`** (`make e2e-reset`, API :8100 sans limite de débit, front :3100, hôtes non locaux refusés) ; **gravité des alertes** dérivée par le serveur (`severity`), bandeaux orange ou rouge, jamais neutres | `docs/decisions/0059-cibles-tactiles-base-e2e-et-gravite-des-alertes.md` |
| 0060 | 2026-10-02 | **Démo réaliste** : `seed-demo` remplacé par une épicerie de Dakar (46 articles, 15 clients, 90 jours, crédit, règlements, retours, réassorts), `--existing-slug` remplit une entreprise existante par connexion du gérant (`demo-front` en préprod) ; **entreprise `e2e` à part** pour les parcours qui écrivent ; dates serveur (encaissements de confirmation, sorties de stock) concentrées sur le jour du remplissage, assumé | `docs/decisions/0060-demo-realiste-et-entreprise-e2e.md` |
| 0061 | 2026-10-07 | **Le jour en cours est calculé en direct** (amende 0034) : CA, marge et ventes du jour lus sur `sales`, le passé sur les faits ; `tenancy.on_commit` vide le tableau de bord après COMMIT (depuis `outbox.emit`) ; bandeau si l'outbox attend > 2 min ; `make dev` (honcho) | `docs/decisions/0061-le-jour-en-cours-est-calcule-en-direct.md` |
| 0062 | 2026-10-07 | **Le reste dû d'une vente suit sa dette** (révision 0014, amende 0024) : `paid_total` = encaissé direct + lettrages vivants sur la dette, compensation comprise ; trigger `pa_sale_rollup` ; verrou dette puis vente ; `debt_status` sur les ventes, badge « Payé » / « Reste X » / « Dette abandonnée » | `docs/decisions/0062-ce-qui-reste-du-sur-une-vente-suit-sa-dette.md` |
| 0063 | 2026-10-07 | **Liste de clients pour la vente** : `GET /sales/customer-choices` (récents puis alphabétique, téléphone, dette ouverte, pages de 50) ; Popover en portail, « Nouveau client » ; les ADR du prompt de phase 15 décalés d'un rang | `docs/decisions/0063-liste-de-clients-pour-la-vente.md` |
| 0064 | 2026-10-07 | **Thème de la maquette v2** : jetons `--coges-*` puis rôles dans `globals.css`, classes de rubrique, `text-sm` à 15 px, Figtree et JetBrains Mono hébergées, logo officiel, kit `components/kit/` et vitrine `/dev/composants` (404 en production), « 87 500 F », aucune couleur en dur (test), sombre dérivé ; couleur d'article tirée du nom | `docs/decisions/0064-theme-de-la-maquette-v2.md` |
| 0065 | 2026-10-07 | **Heure figée et seed de la maquette** : `COGES_FROZEN_NOW` pour les lectures métier (`core/clock.py`, accepté en `local` et `ci` seulement), seed recalé sur l'heure figée (`restamp`, rôle propriétaire), `make seed-maquette` cohérent au plus près (accueil exact), `make maquette-check` (pixelmatch, 2 %, serveurs :8101/:3101 à part) | `docs/decisions/0065-heure-figee-et-seed-de-la-maquette.md` |
| 0066 | 2026-10-08 | **Références et codes-barres générés** : `sku` facultatif (`ART-0001` par entreprise), EAN-13 interne préfixe 2 si rien n'est scanné, nouvel essai sous savepoint en concurrence ; unités `sac` et `bouteille` (révision 0015) ; `POST /inventory/products` crée l'article et son stock d'ouverture en une transaction (prix d'achat exigé) ; TVA omise = `settings.default_tax_rate` ; pas de photo en V1 | `docs/decisions/0066-references-et-codes-barres-generes.md` |
| 0067 | 2026-10-08 | **Raisons de correction en liste fermée** : `reason_code` (7 raisons) obligatoire sur `adjustment` et `loss`, le type s'en déduit, note facultative, `inv_reason_coherent` en base | `docs/decisions/0067-raisons-de-correction-en-liste-fermee.md` |
| 0068 | 2026-10-08 | **Wave et Orange Money** : deux valeurs de `pay_method` (révision 0015), `mobile_money` gardé pour l'existant ; refonte visuelle décalée en 0069 | `docs/decisions/0068-wave-et-orange-money.md` |
| 0069 | 2026-10-08 | **Mots simples** (lot 2) : lexique appliqué au front et au serveur (métriques, séries, insights, notifications), « Gagné »/« Perdu », sous-titres de calcul supprimés, tests qui interdisent les anciens termes ; **en-têtes d'import et d'export en mots** (« Référence », « Prix de vente », « Vente n° »), anciens noms acceptés en alias, `Référence` facultative ; refonte visuelle décalée en 0070 | `docs/decisions/0069-mots-simples-et-import-tolerant.md` |
| 0070 | 2026-10-09 | **Refonte visuelle, lot 3a** : coquille de la maquette v2 (cinq onglets, Conseils, cloche à badge grave, engrenage avec personne, thème et déconnexion, barre basse, écran 26 pour le téléphone, 48 px, densité supprimée) ; coordonnées de la boutique sur `companies` (révision 0016) ; « Dans la caisse » = entré − sorti depuis le début ; liste sans brouillons, « Nouvelle vente » reprend le brouillon du jour ; reçu sans PDF, facture F-1044 ; `GET /sales/day-totals`, filtres `state`, `mine`, recherche par nom | `docs/decisions/0070-refonte-visuelle-de-la-vente.md` |
| 0071 | 2026-10-10 | **Refonte visuelle du stock, lot 3b** : `POST /inventory/deliveries` (stock, dette fournisseur et paiement en une transaction, révision 0017), « Commander » ouvre la livraison préremplie, niveau rapporté au plus haut stock des 90 jours, journal derrière « Tous les mouvements », `categories.color` (1 à 8), rayon supprimé seulement vide | `docs/decisions/0071-refonte-visuelle-du-stock.md` |
| 0072 | 2026-10-10 | **Clients et fournisseurs, lot 3c** : `suppliers.address` (révision 0018), « Ajouter une personne » en page pour créer et modifier (fenêtre seulement dans la vente et la livraison), huit lectures `GET /analytics/customers|suppliers…` (qui doit d'abord, fiches, achats, livraisons, paiements), aucun montant dû sans `debts:read`, recherche par téléphone, mots neutres, encaisser et payer provisoires jusqu'au lot 3d, plafond de crédit jamais affiché | `docs/decisions/0072-clients-et-fournisseurs.md` |
| 0073 | 2026-10-14 | **L'argent, lot 3d** : `GET /analytics/money` (gagné ou perdu, caisse en moments, jours ou semaines du mois, plus grosse dépense, ce qui est dû), `/analytics/cash` (lignes du jour en mots, net par moyen, annulé et ligne inverse listés sans compter), `/analytics/expenses-summary` ; « Annuler » une ligne de caisse = contre-écriture avec la raison en boutons ; « Toutes les dettes » et « Toutes les dépenses » en liens secondaires, anciens `?tab=` redirigés ; icônes de dépense tirées du nom | `docs/decisions/0073-l-argent.md` |
| 0074 | 2026-10-14 | **Conseils, alertes, connexion, lot 3e-1** : connexion par téléphone ou e-mail (révision 0019 : `users.phone`, e-mail facultatif, `must_change_password` ; `auth_lookup` garde sa signature), mot de passe provisoire lisible rendu une fois et à changer avant tout (409 `password_change_required`, `POST /auth/password`) ; Conseils en trois vues (`/analytics` y renvoie), « Vos meilleurs articles » gardé comme titre d'onglet, 9ᵉ métrique `days_since_last_sale`, `GET /analytics/next-week` ; `POST /notifications/read-all` ; textes d'alertes et de conseils en mots simples ; seed `maquette` avec alertes et nuit de l'Intelligence | `docs/decisions/0074-conseils-alertes-connexion.md` |
| 0075 | 2026-10-15 | **Réglages, lot 3e-2** : une page par rubrique (`/settings`, `people`, `rights`, `history`, `files`), anciens `?tab=` redirigés ; grille de 8 gestes `GET /roles/abilities` et `PUT /roles/{id}/abilities` (gérant et « Gérer les personnes » verrouillés, droits hors grille gardés, Vendeur et Comptable modifiables par la grille seule) ; `GET /analytics/history` raconte le journal en phrases, sans le geste courant ; `users.deactivated_at` (révision 0020) ; `settings.receipt_format` lu par `/auth/me` ; `ExportRead.params` ; pas de logo | `docs/decisions/0075-reglages.md` |
| 0076 | 2026-10-15 | **Clôture de la phase 15** : `lighthouse@13.5.0` en dépendance de dev et `make lighthouse` (26 écrans, page d'arrivée vérifiée, 100 partout) ; audit Impeccable 18/20 conservé, constats P2/P3 reportés ; états de la démo garantis par `test_seed_demo_states` | `docs/decisions/0076-cloture-de-la-phase-15.md` |
| 0077 | 2026-10-15 | **Surveillance des workers** : battements Redis (30 s, TTL 120 s) et sonde Docker + `autoheal`, chien de garde du relais (5 min), `job_runs` (révision 0021) par les fonctions du rôle `coges_ops` (NOLOGIN BYPASSRLS, aucune lecture directe), `outbox_lag()` de `coges_bus`, `GET /system/workers` sous `COGES_OPS_TOKEN` (200/503, 404 sans jeton configuré), fenêtres 26 h / 8 jours, pings `COGES_JOB_PING_URLS`, `beat_tick` dans Redis seulement, partitions d'audit 3 mois d'avance, Redis `noeviction` exigé en production ; guide `docs/runbooks/workers.md` | `docs/decisions/0077-surveillance-des-workers.md` |
| 0078 | 2026-10-17 | **Lot A, connexion** : provisoire à 48 h (`users.must_change_password_until`, révision 0022, `NULL` pour les anciens), `temporary_password_expired` après le mot de passe vérifié, « Donner un nouveau mot de passe » (corps vide ⇒ provisoire tiré) ; freinage par compte `rl:acct:{sha256}` (5 échecs / 15 min ⇒ 1, 2, 4… 30 min, sans verrou, sans Argon2 pendant l'attente), alerte `login_failures` au 10ᵉ échec par tâche worker ; compteur en mémoire pour `/auth/login` sans Redis (frein dégradé) | `docs/decisions/0078-mot-de-passe-provisoire-et-freinage-de-la-connexion.md` |
| 0079 | 2026-10-17 | **COMMIT avant la réponse** : dépendances transactionnelles en `scope="function"` (FastAPI fermait la transaction après l'envoi : 2xx sur COMMIT refusé, démontré), test d'architecture | `docs/decisions/0079-commit-avant-la-reponse.md` |
| 0080 | 2026-10-17 | **Analyses de sécurité en CI** : gitleaks 8.30.1 (binaire + SHA-256, tout l'historique), pip-audit (toute faille), `pnpm audit --prod` (haute/critique), exceptions datées dans `security/audit-exceptions.toml`, chaque lundi ; PyJWT 2.15.1, Next 16.3.8, `shadcn` en dev, override `source-map-js` | `docs/decisions/0080-analyses-de-securite-en-ci.md` |
| 0081 | 2026-10-17 | **`GET /api/v1/health/ready`** (complète le prompt 17) : `SELECT 1` sous `coges_app` et `PING` Redis sur un client neuf, 200/503, même corps sans détail ; Redis sans `COGES_REDIS_URL` = `not_configured`, pas une panne ; sur Neon gratuit la sonde réveille la base | `docs/decisions/0081-sonde-de-disponibilite-complete.md` |
| 0082 | 2026-10-17 | **Liens de retour des écrans d'action** (caisse, encaisser, payer, dépenses, corriger, recevoir, modifier un article) : `BackLink` au-dessus du titre, `?from=` posé par le lien d'entrée et vérifié par `safePath` (ADR 0049), libellé = la fiche ou la rubrique d'origine, sinon l'écran parent ; écart à la maquette noté | `docs/decisions/0082-liens-de-retour-des-ecrans-d-action.md` |
| 0083 | 2026-10-17 | **CoGes sur un VPS, sauf la base** (remplace 0040 et la partie Vercel de 0047) : Caddy seul exposé, `/api/v1/*` → API, le reste → front ; images front/api/worker/bundle sur ghcr.io ; « Déployer » à la main ou par tag (préprod), migrations depuis le job, `deploy.sh` par clé SSH bridée avec vérification et retour automatique ; préprod `coges-preprod` arrêtée par défaut ; X-Forwarded-For lu à droite ; redémarrage auto à 05 h 15 UTC | `docs/decisions/0083-coges-sur-un-vps.md` |
| 0084 | 2026-10-17 | **Sauvegarde externe chiffrée** : workflow GitHub de nuit (pas le VPS), rôle `coges_backup` LOGIN BYPASSRLS en lecture seule (révision 0023, exception nommée de T36, vérifié sur Neon), `pg_dump` → `age` (clé publique) → S3 hors Neon par rclone, relecture et seuil de 50 %, rétention 7/4/12 par un compte distinct, `restore_backup.sh` + `verify_restore.py`, chaîne prouvée en CI | `docs/decisions/0084-sauvegarde-externe-chiffree.md` |
| 0085 | 2026-10-17 | **Erreurs et coupures** : toute 500 imprévue au format stable avec `request_id` (corps, en-tête, journal, Sentry), référence d'incident « AB12 CD34 », `error.tsx`/`global-error.tsx`, bandeau « Connexion difficile » et lectures réessayées à 2/4/8 s, écritures jamais rejouées en silence (même clé), page de maintenance de Caddy en 502/503/504 | `docs/decisions/0085-page-d-erreur-et-coupures.md` |
| 0086 | 2026-10-17 | **Lot C, intégrité et isolation prouvées** : échec au COMMIT réel (triggers différés sur toutes les tables d'entreprise) sur 51 écritures critiques, lectures sans paramètre croisées A/B (JSON et exports), clés Redis inventoriées, tâches de beat par entreprise, concurrence par HTTP, invariants réutilisables ; registres découverts qui font échouer la CI ; **une entreprise supprimée ferme ses sessions** (`core/deps.py`) | `docs/decisions/0086-integrite-et-isolation-prouvees.md` |
| 0087 | 2026-10-18 | **Correctifs de la revue, partie 1** (révision 0024, 8 constats reproduits puis corrigés) : panne de Redis ⇒ tentative rendue (`outbox_release`), rebut signalé par `/system/workers` ; registre : `production`/`production-previous` jamais supprimées, `vX.Y.Z` construite depuis son étiquette, réutilisée ou refusée ; `sale_id` retiré de `POST /payments` ; brouillon verrouillé avant d'écrire ses lignes ; secret JWT `change-me` refusé hors local/CI ; e-mail et téléphone uniques sur les comptes vivants seulement ; tableau de bord : cache commun, alertes et chiffres d'argent par personne ; annuler une entrée rend le CMP, refusé (`CG022`) si elle a été suivie | `docs/decisions/0087-correctifs-de-la-revue-partie-1.md` |
| 0088 | 2026-10-18 | **Correctifs de la revue, partie 2** (révision 0025, 25 points, tableau reproduit / non reproduit / reporté) : sessions révoquées en base quand l'accès change ; délégation de droits bornée ; freinage de connexion à mémoire de 45 min, réservé avant Argon2, par compte ; ordre des verrous unifié et 409 `concurrent_update` ; dates à fuseau, vente datée à la confirmation ; dépense payée figée ; gardes du Référentiel (`CG003`–`CG005`) ; sous-total arrondi par ligne ; Celery plafonné ; sauvegarde à manifeste ; déploiement et CI durcis ; imports bornés ; exports plafonnés et idempotents | `docs/decisions/0088-correctifs-de-la-revue-partie-2.md` |
| 0089 | 2026-10-20 | **Administration de la plateforme, lot 1** (révision 0026) : rôle `coges_app_platform` (NOBYPASSRLS, GRANT colonne par colonne, politiques qui ne nomment que lui, aucune table commerciale), `platform_users` à colonne `role` (`administrator`/`support`), jetons à audience distincte dans les deux sens, `companies.status` (`company_suspended` en 403 à la connexion après mot de passe, au refresh et à chaque requête ; garde `CG006`), `platform_audit_logs`, e-mail SMTP après COMMIT, application séparée `frontend-admin/` sur `admin.<domaine>` filtré par IP ; module `platform/` hors des cinq bandes | `docs/decisions/0089-administration-de-la-plateforme-lot-1.md` |
| 0090 | 2026-10-23 | **Surveillance dans l'administration, lot 2** (révision 0027) : `coges_app_platform` exécute exactement 4 fonctions `SECURITY DEFINER` (`outbox_lag`, `job_runs_latest`, `job_runs_history`, `outbox_dead_letters`), sans entreprise ni contenu ; `GET /platform/system/workers` (même réponse que `/system/workers`, qui garde le seul jeton d'exploitation), `job-runs` (90 j), `outbox` (rebut) dans `system/`, administrateur et support ; écrans Système et Tâches, bandeau de panne sur toute page, interrogation 30 s | `docs/decisions/0090-surveillance-web-de-la-plateforme.md` |
| 0091 | 2026-10-24 | **Abonnements, lot admin 3** (révision 0028, remplace 0043, referme P8) : `plans` (Starter 4 900 / 3, Business 9 900 / 7, Premium 14 900 / 10 ; `max_users` NULL = sur devis), `subscriptions` (une par entreprise, statut commercial synchronisé avec `companies.status`), `subscription_payments` déclaratifs et idempotents ; rôle `coges_billing` (NOLOGIN) : essai Premium de 30 j créé avec l'entreprise, plafond d'utilisateurs en trigger (`CG007` ⇒ 409 `plan_user_limit_reached`) ; tâche de nuit : avertissements J-7/J-3/J-1 (e-mail + cloche `trial_ending`), suspension à l'échéance ; paiement ⇒ actif, +1 mois, réactivation ; worker avec `COGES_DATABASE_URL_PLATFORM` | `docs/decisions/0091-abonnements-offres-et-essai.md` |
| 0092 | 2026-10-24 | **Accès support encadré, lot admin 4** (révision 0029) : bris de glace (motif obligatoire, 2 h par défaut, 4 h au plus, une session par entreprise), jeton tenant `via_support_session` relu à chaque requête (fermé ou échu ⇒ 401 `support_session_ended`), lecture seule par trois verrous (GET/HEAD seuls, transaction `READ ONLY`, rôle `support_readonly` en code, jamais en base) ; `coges_app` lit 5 colonnes de `support_sessions` ; journal plateforme **et** journal de l'entreprise, gérant prévenu (e-mail + cloche `support_access`), bandeau pour tous ; « Voir l'entreprise » ouvre le front commerçant (jeton dans le fragment, `COGES_MERCHANT_URL`) ; consentement du gérant reporté | `docs/decisions/0092-acces-support-encadre.md` |
| 0093 | 2026-10-24 | **Statistiques, lot admin 5** (sans révision ni droit nouveau) : `GET /platform/stats/overview` (statuts, comptes actifs, offres avec les essais à part, une seule requête), `revenue` (paiements **déclarés** seulement, mois en cours, précédent ou 366 jours au plus, heure de Dakar), `signups` (12 mois ou 52 semaines, vides à 0) ; administrateur et support ; écran « Statistiques » daté, barres CSS + tableau | `docs/decisions/0093-statistiques-de-la-plateforme.md` |
| 0094 | 2026-10-24 | **Équipe et accès, lot admin 6** (révision 0030) : `platform_invitations` (empreinte seule, `issue` par renvoi, 72 h, une en attente par adresse), jeton **tiré par le worker** après COMMIT (sans SMTP : lien montré une fois), acceptation publique freinée, même réponse pour tout lien invalide ; `PATCH /team/{id}` jamais sur soi, toujours un administrateur actif (verrou), suspension = sessions révoquées ; `/users` commerçants en lecture seule, `/audit` (administrateur, `diff` en liste blanche), `/roles` déduit des dépendances (registre), `/attention` ; `COGES_ADMIN_URL` ; partie B : thème CoGes (amende 0089), repère « Administration » en **encre ardoise** (`#1e2320`), menu latéral et recherche « / », tableau de bord « À traiter », confirmation unique, tâches chronométrées en e2e | `docs/decisions/0094-equipe-et-acces-de-l-administration.md` |
| 0095 | 2026-10-25 | **La sauvegarde suit la version majeure de la production** (Neon en 18 ; pg_dump refuse un serveur plus récent) : client PGDG figé (`PG_CLIENT_MAJOR`, `install_pg_client.sh`), garde-fou de version dans `backup.sh` (ping `/fail`) et `restore_backup.sh`, manifeste à `server_version`/`pg_dump_version` ; CI (`matrix.postgres`) et poste (`postgres:18-alpine`, volume `coges_pgdata18`, `make db-upgrade-18`) en 18, concordance testée ; complément : restauration sur Neon sans les droits de `cloud_admin`/`neon_*`, base vide au sens large, `USAGE, CREATE` sur `public` vérifiés | `docs/decisions/0095-la-sauvegarde-suit-la-version-majeure-de-la-production.md` |
| 0098 | 2026-10-28 | **Mots de passe** (prompt 28, C2) : `PasswordField` unique (afficher / cacher, `aria-pressed`, remasqué à l'envoi et onglet caché) à la connexion, à la première connexion et dans « Changer mon mot de passe » (`/account/password`, menu du compte, tous les rôles) ; copie dans l'administration ; les autres sessions restent révoquées au changement (ADR 0088) | `docs/decisions/0098-afficher-le-mot-de-passe-et-le-changer.md` |

Points ouverts connus, à trancher dans leur phase : voir `docs/architecture/README.md` (P1-P8).
P1 à P6 et P8 sont tranchés (ADR 0002, 0005, 0005, 0027, 0015, 0019, 0043 puis 0091) ; reste **P7**
(signalé, hors V1 technique).

> **Backend V1 terminé (code)** — 23 groupes, 100 opérations sous `/api/v1` (`auth/me` en phase 11 ; lectures ajoutées en phase 12, ADR 0050 ; `audit-logs` et lectures de pilotage en phase 13, ADR 0053). Contrat :
> `backend/openapi.json` (versionné, vérifié en CI, `make openapi`) ; servi hors production sur
> `/api/v1/openapi.json`, documentation interactive `/api/v1/docs`.
> Plateforme `health` · `auth` (login, refresh, logout, me) · `companies/me` · `users` · `roles`,
> `permissions` · Référentiel `categories` · `products` (+ `prices`) · `customers` · `suppliers` ·
> Opérations `inventory` (stock, movements, reverse) · `sales` (brouillon, items, confirm, cancel,
> receipt, returns) · `sale-returns` (refunds) · Finance `payments` (+ cancel) · `debts`
> (+ write-off) · `expense-categories` · `expenses` · Restitution `analytics` (overview,
> products, timeseries) · `dashboard` · `notifications` · `insights`, `forecasts`,
> `intelligence/summary` · `imports/{kind}` (+ template) · `exports` (referentials, sales, file) ·
> `system/outbox` · `audit-logs`. Préproduction en ligne depuis le 2026-09-27 : `https://coges-api.vercel.app`
> (`deploy/README-infra.md`). Front : projet Vercel `coges-web`, déployé avec l'API à chaque push sur `main` (ADR 0058, `https://coges-app.vercel.app` ; `frontend/README.md`,
> `deploy/README-infra.md`). Phases 12 et 13 terminées (ADR 0052, 0055) : **le produit V1 est
> fonctionnellement complet**. Phase 14 terminée (ADR 0056) : interface finie, système documenté dans
> `docs/design/DESIGN.md`. Améliorations reportées : `docs/design/audit-phase-14-apres.md` (« Ce qui reste »).

## 10. Ce que tu ne fais jamais

- Contourner une contrainte, un trigger ou la RLS pour qu'un test passe.
- Écrire du SQL dans un router, un appel HTTP dans un service, une règle métier dans un repository.
- Ajouter une fonctionnalité hors V1 « parce que c'est facile ».
- Utiliser `float` pour un montant, `SET` sans `LOCAL`, ou lire un `company_id` venant du client.
- Modifier un fichier de `docs/architecture/` : si tu y trouves une erreur, signale-la et propose
  une décision.
- Continuer après un choix structurant sans l'avoir fait valider avec `AskUserQuestion`.
