# Infrastructure — CoGes

Répartition des composants : voir le Diagramme 2 de
`docs/architecture/pdf/architecture-technique-v1.1.pdf`. Règle unique : un composant
persistant, long, planifié ou gourmand en mémoire vit **hors Vercel**.

| Composant | Où | Fichier |
|---|---|---|
| Next.js, API FastAPI | Vercel | `backend/vercel.json` |
| PostgreSQL 16, Redis 7 | Managé (dev : docker compose) | `docker-compose.yml` (racine) |
| Workers Celery, ML, batchs | Docker | `backend/Dockerfile.worker`, `deploy/docker-compose.worker.yml` |
| Migrations Alembic | Étape de déploiement, image worker | `make migrate` |

## Développement local

```bash
cp .env.example .env     # puis remplacer les valeurs
make up                  # PostgreSQL 16 + Redis 7, avec healthchecks
make migrate             # migrations, rôle propriétaire
make api                 # http://localhost:8000/api/v1/health
```

`deploy/postgres/init/01-roles.sql` ne s'exécute qu'à la **création du volume**. Après un
changement de ce fichier : `docker compose down -v && make up`.

## Rôles PostgreSQL

| Rôle | Usage | Privilèges |
|---|---|---|
| `postgres` | superutilisateur du conteneur, amorçage uniquement | tous |
| `coges_owner` | propriétaire du schéma, migrations Alembic | ni superuser, ni BYPASSRLS |
| `coges_app` | API et workers | SELECT/INSERT/UPDATE, **pas de DELETE**, ni superuser, ni BYPASSRLS |

Les `GRANT`/`REVOKE` et les politiques RLS sont posés par la migration `0001` (phase 01),
pas par le script d'amorçage.

## État

Phase 00 : seuls PostgreSQL et Redis sont réellement configurés.
`docker-compose.worker.yml`, `Dockerfile.worker` et `vercel.json` sont des squelettes
provisoires ; ils sont complétés et testés en phases 08 (async) et 10 (déploiement).
