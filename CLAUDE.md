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
  `payment.received`, `debt.created`, `debt.settled`, `expense.created`. Un nouveau type
  d'événement = une décision à faire valider.
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
make test                    # pytest (toutes suites)
make test-tenancy            # tests de fuite inter-tenant (bloquants en CI)
make lint                    # ruff check + ruff format --check + mypy --strict
make format                  # ruff format + ruff check --fix
make api                     # uvicorn → http://localhost:8000/api/v1/health
make worker                  # celery worker + beat
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
│   └── prompts/               ← prompts de phase 00 → 14
├── backend/                   ← FastAPI, modules, workers, migrations, tests
├── frontend/                  ← Next.js App Router
└── deploy/                    ← docker-compose worker, README-infra
```

## 8. Avancement

Légende : ⬜ à faire · 🟨 en cours · ✅ terminé (tests verts) · ⛔ bloqué

| Phase | Prompt | Prérequis | Tests exigés | Statut |
|---|---|---|---|---|
| 00 Initialisation du dépôt | `docs/prompts/00-initialisation.md` | — | CI verte à vide | ✅ |
| 01 Socle tenant + RLS | `01-socle-tenant-rls.md` | 00 | T1–T5, T36–T37, architecture | ⬜ |
| 02 Auth, utilisateurs, RBAC, audit, outbox | `02-auth-rbac-audit.md` | 01 | fuite générique, RBAC | ⬜ |
| 03 Référentiels et prix | `03-referentiels.md` | 02 | fuite, FK croisées (T5) | ⬜ |
| 04 Stock et CMP | `04-stock-cmp.md` | 03 | T6–T13, T38 | ⬜ |
| 05 Ventes (draft → confirm → cancel, reçu) | `05-ventes.md` | 04 | T14–T17, T23–T24, T39 | ⬜ |
| 06 Retours et remboursements | `06-retours.md` | 05 | T18–T22 | ⬜ |
| 07 Finance de gestion | `07-finance.md` | 06 | T25–T28 | ⬜ |
| 08 Async, analytics, dashboard, notifications | `08-async-analytics.md` | 07 | T29–T32, T40 | ⬜ |
| 09 CoGes Intelligence | `09-intelligence.md` | 08 | T33–T35 | ⬜ |
| 10 Import/export, durcissement, déploiement | `10-durcissement-deploiement.md` | 09 | T1–T40 en CI | ⬜ |
| 11 Front : fondations et design system | `11-front-fondations.md` | 10 (ou 07 + OpenAPI stable) | e2e login | ⬜ |
| 12 Front : opérations | `12-front-operations.md` | 11 | e2e vente | ⬜ |
| 13 Front : finance, pilotage, paramètres | `13-front-pilotage.md` | 12 | e2e | ⬜ |
| 14 Finition visuelle (Impeccable) | `14-polish-impeccable.md` | 13 | audit Impeccable | ⬜ |

## 9. Journal des décisions

| # | Date | Décision | Fichier |
|---|---|---|---|
| 0001 | 2026-09-23 | Outillage (uv, GitHub Actions, docker compose, pre-commit, pnpm) et **SQLAlchemy synchrone + psycopg 3** | `docs/decisions/0001-outillage.md` |

Points ouverts connus, à trancher dans leur phase : voir `docs/architecture/README.md` (P1-P8).

## 10. Ce que tu ne fais jamais

- Contourner une contrainte, un trigger ou la RLS pour qu'un test passe.
- Écrire du SQL dans un router, un appel HTTP dans un service, une règle métier dans un repository.
- Ajouter une fonctionnalité hors V1 « parce que c'est facile ».
- Utiliser `float` pour un montant, `SET` sans `LOCAL`, ou lire un `company_id` venant du client.
- Modifier un fichier de `docs/architecture/` : si tu y trouves une erreur, signale-la et propose
  une décision.
- Continuer après un choix structurant sans l'avoir fait valider avec `AskUserQuestion`.
