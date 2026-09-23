# 0001 — Outillage du dépôt et mode d'accès à PostgreSQL

- **Date** : 2026-09-23
- **Phase** : 00
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

L'architecture V1.1 fixe la pile (FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis,
Celery, Next.js) mais ne tranche pas l'outillage du dépôt : gestionnaire de paquets,
intégration continue, infrastructure locale, hooks. Elle ne tranche pas non plus le point
le plus structurant de la phase 00 : **SQLAlchemy en mode synchrone ou asynchrone**.
Ce choix engage toutes les phases suivantes, puisque le contexte tenant (`SET LOCAL`),
les verrous `FOR UPDATE` et les transactions par cas d'usage en dépendent.

## Options envisagées

### 1. Accès base : synchrone + psycopg 3 (**retenue**) ou asynchrone (asyncpg)

1. **Synchrone + psycopg 3 (retenue)** : une seule pile de repositories, partagée par l'API
   et par les workers Celery — qui sont synchrones. Transactions explicites,
   `SET LOCAL` / `set_config(..., true)` et `SELECT ... FOR UPDATE` faciles à raisonner et à
   prouver dans les tests de fuite. FastAPI exécute les routes `def` dans un threadpool ;
   les endpoints CoGes sont courts (cible < 300 ms, Diagramme 2).
2. Asynchrone (asyncpg) : meilleure concurrence d'E/S par process, mais double pile
   (sync pour Celery, async pour l'API) ou wrappers, et un contexte tenant plus délicat à
   démontrer sur pool.

### 2 à 7. Outillage

| Sujet | Retenu | Écarté |
|---|---|---|
| Paquets Python | **uv** (`uv.lock` versionné, Python 3.12 épinglé par `.python-version`) | Poetry, pip-tools |
| Paquets JS | **pnpm** via `corepack enable pnpm` | npm, yarn |
| CI | **GitHub Actions** (`.github/workflows/ci.yml`, services PostgreSQL 16 + Redis 7) | GitLab CI, aucune |
| Dépôt distant | **aucun** : `git init` local, branche `main` + `phase/00-initialisation` | GitHub, GitLab |
| Infra locale | **docker compose** : `postgres:16-alpine`, `redis:7-alpine`, volumes nommés, healthchecks | services installés sur la machine |
| Pré-commit | **pre-commit** : ruff, ruff-format, mypy `--strict`, gitleaks, garde-fous | aucun hook |

## Décision

SQLAlchemy 2 en **mode synchrone avec psycopg 3**, projet géré par **uv**, CI **GitHub
Actions**, infrastructure locale en **docker compose**, hooks **pre-commit**, **pnpm** pour
le futur frontend, **aucun dépôt distant** pour l'instant.

## Conséquences

- Les repositories, le point d'entrée transactionnel `tenant_transaction()` (phase 01) et les
  tâches Celery partagent **le même code d'accès base** : une seule implémentation du contexte
  tenant à auditer, donc une seule surface de fuite possible.
- `Session` SQLAlchemy classique, `engine` avec `pool_pre_ping` et écouteur `checkin`
  (`DISCARD ALL`) : phase 01.
- Les routes FastAPI seront déclarées en `def` (et non `async def`) dès qu'elles touchent la
  base, pour ne pas bloquer la boucle d'événements.
- `uv.lock` est versionné ; la CI installe avec `--frozen`, donc local et CI sont identiques.
- `testcontainers` n'est **pas** ajouté : la stratégie de base de test est une question de la
  phase 01 (§ 2.3 de `docs/prompts/01-socle-tenant-rls.md`).
- Écart mineur assumé : `celery.*` est exempté de `ignore_missing_imports` dans mypy, Celery
  ne publiant ni stubs ni marqueur `py.typed`. Le reste de `app/` reste en `--strict`.
- Ce que ça repousse : passer l'API en asynchrone plus tard obligerait à réécrire les
  repositories et à re-prouver l'isolation multi-tenant. Le choix est donc durable.
