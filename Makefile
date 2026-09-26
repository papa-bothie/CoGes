# CoGes — commandes de développement.
# Le backend est un projet uv situé dans backend/ ; tout passe par `uv run --directory backend`.

# Le .env local (non versionné) fournit les DSN et les mots de passe de développement.
# Une valeur contenant $ ou # doit être évitée : make l'interpréterait.
ifneq (,$(wildcard .env))
include .env
export
endif

UV := uv run --directory backend

.PHONY: help install up down logs psql migrate test test-tenancy test-perf lint format api worker relay seed-demo openapi requirements check-generated

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

api: ## Lance l'API en local sur http://localhost:8000
	$(UV) uvicorn app.main:app --reload --port 8000

worker: ## Lance un worker Celery avec le scheduler beat
	$(UV) celery -A app.workers.celery_app worker --beat --loglevel=info

relay: ## Lance le relais de l'outbox (rôle coges_relay, processus séparé)
	$(UV) python -m app.workers.relay

seed-demo: ## Remplit une entreprise de démonstration (20 produits, 50 ventes sur 60 jours)
	$(UV) python -m app.seed

openapi: ## Régénère backend/openapi.json (source des types du frontend)
	$(UV) python -m app.cli export-openapi

requirements: ## Régénère backend/requirements.txt pour Vercel (sans dev ni ml)
	cd backend && uv export --no-dev --no-group ml --no-hashes --no-emit-project --no-header --format requirements-txt -o requirements.txt --quiet

check-generated: ## Échoue si openapi.json ou requirements.txt ne sont pas à jour
	cd backend && uv export --no-dev --no-group ml --no-hashes --no-emit-project --no-header --format requirements-txt --quiet | diff -u requirements.txt -
	$(UV) pytest -q tests/architecture/test_openapi_is_current.py
