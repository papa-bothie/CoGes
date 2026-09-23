# Phase 00 — Initialisation du dépôt et de l'outillage

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 00 :
initialisation du dépôt**. Aucune ligne de code métier dans cette phase.

## 0. Protocole (à suivre dans cet ordre)

1. Lis `CLAUDE.md` en entier, puis `docs/architecture/README.md`.
2. Lis dans `docs/architecture/01-architecture-technique-v1.1.txt` : le Diagramme 2
   (déploiement, ligne ≈158), le Diagramme 10 (arborescence, ligne ≈785) et les 18 décisions
   (ligne ≈1137).
3. **Avant d'écrire un seul fichier**, pose-moi les questions du § 2 avec l'outil
   `AskUserQuestion` (un seul appel, 4 questions au maximum par appel ; fais un second appel
   si besoin). L'option recommandée vient en premier.
4. Présente ensuite un plan (arborescence créée, fichiers de configuration, commandes `make`) et
   attends mon feu vert.
5. Exécute, vérifie (§ 5), puis clos la phase (§ 6).

## 1. Objectif

Obtenir un dépôt monorepo propre, conforme au Diagramme 10, où `make up && make test && make lint`
passe à vide en local comme en CI, avec PostgreSQL 16 et Redis disponibles en local.

## 2. Questions à me poser (AskUserQuestion)

1. **Gestionnaire Python** : `uv` (Recommandé : rapide, lockfile, gère Python 3.12) / Poetry / pip-tools.
2. **Gestionnaire JS** (pour préparer `frontend/`, sans rien y coder) : `pnpm` (Recommandé) / npm / yarn.
3. **CI** : GitHub Actions (Recommandé) / GitLab CI / aucune pour l'instant.
4. **Dépôt distant** : GitHub existant (me demander l'URL) / à créer plus tard (Recommandé :
   `git init` local seulement) / GitLab.
5. **Base locale** : docker compose avec PostgreSQL 16 + Redis 7 (Recommandé) / services
   installés sur la machine.
6. **Pré-commit** : hooks `pre-commit` avec ruff, mypy et un contrôle anti-secrets
   (Recommandé) / pas de hooks.
7. **SQLAlchemy synchrone ou asynchrone** : synchrone + psycopg 3 (Recommandé : transactions
   explicites plus simples, `SET LOCAL` et verrous `FOR UPDATE` faciles à raisonner, même code
   pour l'API et les workers Celery, qui sont synchrones) / asynchrone (asyncpg). C'est un choix
   structurant pour toutes les phases suivantes.

## 3. Périmètre

**À faire**
- `git init`, branche `main`, puis la branche `phase/00-initialisation`.
- Arborescence (fichiers vides ou `__init__.py`) :
  `backend/app/{core,core/events,modules,workers,workers/tasks}`, `backend/migrations/`,
  `backend/tests/{unit,integration,tenancy,architecture}`, `frontend/` (un `README.md` seulement),
  `deploy/`.
- `backend/pyproject.toml` : Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2 (mode choisi à la
  question 7), psycopg 3, Alembic, Pydantic v2,
  pydantic-settings, argon2-cffi, PyJWT, Celery, redis ; dev : pytest, pytest-cov, httpx, ruff,
  mypy, et testcontainers si tu le proposes.
- `backend/app/main.py` minimal : `GET /api/v1/health` → `{ "status": "ok" }`, rien d'autre.
- `docker-compose.yml` à la racine (développement) : `postgres:16` et `redis:7`, volumes nommés,
  healthchecks. Crée un utilisateur propriétaire des migrations **et** le rôle `coges_app` via un
  script d'initialisation (le rôle sera configuré en phase 01).
- `.env.example` (aucun secret réel), `.gitignore` (dont `.env`, `__pycache__`, `.venv`,
  `node_modules`, `*.~lock*`), `.editorconfig`.
- `Makefile` : `up`, `down`, `migrate`, `test`, `test-tenancy`, `lint`, `format`, `api`, `worker`.
- `backend/tests/unit/test_health.py`, et un test d'architecture **squelette** dans
  `tests/architecture/` (il sera rempli en phase 01).
- CI : lint + tests avec un service PostgreSQL 16, déclenchée sur push et PR.
- `docs/decisions/0001-outillage.md` : consigne les réponses du § 2.

**Hors périmètre** : aucune table, aucun module métier, aucun code frontend.

## 4. Règles à respecter

- L'arborescence suit **exactement** le Diagramme 10 ; si tu veux en dévier, demande-moi.
- Aucun secret dans le dépôt. Les valeurs par défaut de `.env.example` sont factices.
- Les migrations ne se lancent **jamais** au démarrage de l'API.

## 5. Vérification

- `make up` démarre PostgreSQL et Redis ; `make test` et `make lint` passent.
- `curl localhost:8000/api/v1/health` renvoie 200.
- Montre-moi l'arborescence finale (`tree -L 3`, sans `.venv` ni `node_modules`).

## 6. Clôture

- Complète la section « Commandes utiles » de `CLAUDE.md` avec les vraies commandes.
- Passe la phase 00 à ✅ dans `CLAUDE.md` § 8 et ajoute la décision 0001 au § 9.
- Commits en Conventional Commits. Ne pousse rien sans mon accord.
- Résumé final : ce qui est fait, les décisions, et ce que la phase 01 va nécessiter.
