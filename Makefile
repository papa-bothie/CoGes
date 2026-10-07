# CoGes — commandes de développement.
# Le backend est un projet uv situé dans backend/ ; tout passe par `uv run --directory backend`.

# Le .env local (non versionné) fournit les DSN et les mots de passe de développement.
# Une valeur contenant $ ou # doit être évitée : make l'interpréterait.
ifneq (,$(wildcard .env))
include .env
export
endif

UV := uv run --directory backend
PNPM := pnpm --dir frontend

# Port de l'API locale ; le front réécrit /api/v1 vers cette origine (ADR 0047).
API_PORT ?= 8000
COGES_API_URL ?= http://localhost:$(API_PORT)

.PHONY: help install up down logs psql migrate test test-tenancy test-perf lint format dev api worker relay seed-demo seed-maquette maquette-check openapi requirements check-generated front-install front-dev front-api front-check front-e2e e2e-reset e2e-api e2e-front

help: ## Liste les cibles disponibles
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Installe les dépendances Python et les hooks de pré-commit
	uv sync --directory backend
	$(UV) pre-commit install

up: ## Démarre PostgreSQL 16 et Redis 7 et attend leur bonne santé
	docker compose up -d --wait

down: ## Arrête les services (les volumes sont conservés)
	docker compose down

logs: ## Suit les journaux des services
	docker compose logs -f

psql: ## Ouvre un psql sur la base coges en tant que coges_app
	docker compose exec -e PGPASSWORD=$(COGES_APP_PASSWORD) postgres psql -U coges_app -d coges

migrate: ## Applique les migrations Alembic (rôle propriétaire, jamais au démarrage de l'API)
	$(UV) alembic upgrade head

test: ## Lance toutes les suites de tests
	$(UV) pytest

test-tenancy: ## Lance uniquement les tests de fuite inter-tenant (bloquants en CI)
	$(UV) pytest tests/tenancy

test-perf: ## Mesure GET /dashboard sur le jeu de démonstration (cible < 200 ms)
	$(UV) pytest -m perf tests/perf

lint: ## ruff (lint + format) puis mypy --strict sur app/
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) mypy

format: ## Applique ruff format et les corrections automatiques
	$(UV) ruff format .
	$(UV) ruff check --fix .

dev: ## API, worker, relais et front ensemble (honcho, Procfile.dev) ; Ctrl+C arrête tout
	uv run --project backend honcho --procfile Procfile.dev --env /dev/null start

api: ## Lance l'API en local sur http://localhost:8000 (API_PORT=… pour changer)
	$(UV) uvicorn app.main:app --reload --port $(API_PORT)

worker: ## Lance un worker Celery avec le scheduler beat
	$(UV) celery -A app.workers.celery_app worker --beat --loglevel=info

relay: ## Lance le relais de l'outbox (rôle coges_relay, processus séparé)
	$(UV) python -m app.workers.relay

seed-demo: ## Épicerie de démonstration `demo` : 46 articles, 15 clients, 90 jours (≈ 1 200 ventes)
	$(UV) python -m app.seed

seed-maquette: ## Données de la maquette v2 `maquette` (Keur Fatou, 6 octobre 2026 à 10 h 45)
	$(UV) python -m app.seed_maquette

openapi: ## Régénère backend/openapi.json (source des types du frontend)
	$(UV) python -m app.cli export-openapi

requirements: ## Régénère backend/requirements.txt pour Vercel (sans dev ni ml)
	cd backend && uv export --no-dev --no-group ml --no-hashes --no-emit-project --no-header --format requirements-txt -o requirements.txt --quiet

check-generated: ## Échoue si openapi.json ou requirements.txt ne sont pas à jour
	cd backend && uv export --no-dev --no-group ml --no-hashes --no-emit-project --no-header --format requirements-txt --quiet | diff -u requirements.txt -
	$(UV) pytest -q tests/architecture/test_openapi_is_current.py

front-install: ## Installe les dépendances du frontend (pnpm via corepack) et Chromium
	corepack enable pnpm
	$(PNPM) install --frozen-lockfile
	$(PNPM) exec playwright install chromium

front-dev: ## Lance le frontend sur http://localhost:3000, branché sur l'API locale
	COGES_API_URL=$(COGES_API_URL) $(PNPM) dev

front-api: ## Régénère frontend/types/api.ts depuis backend/openapi.json
	$(PNPM) gen:api

front-check: ## Types à jour, lint, typecheck, tests unitaires, build
	$(PNPM) check:api
	$(PNPM) lint
	$(PNPM) typecheck
	$(PNPM) test
	COGES_API_URL=$(COGES_API_URL) $(PNPM) build

front-e2e: e2e-reset ## Parcours Playwright sur la base dédiée coges_e2e (recréée avant la suite)
	$(PNPM) e2e

maquette-check: ## Compare le front à la maquette v2 (seuil 2 %) ; MAQUETTE_ALL=1 : tous les écrans
	$(PNPM) exec playwright test --config playwright.maquette.config.ts

e2e-reset: ## Recrée coges_e2e : migrations, démo `demo` et entreprise `e2e` vide (jamais coges ni Neon)
	deploy/scripts/e2e.sh reset

e2e-api: ## API des parcours e2e sur :8100, base coges_e2e, limites de débit désactivées
	deploy/scripts/e2e.sh api

e2e-front: ## Front des parcours e2e sur :3100, branché sur l'API e2e (build .next-e2e)
	deploy/scripts/e2e.sh front
