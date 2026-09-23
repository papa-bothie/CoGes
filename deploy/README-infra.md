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

Si un PostgreSQL ou un Redis tourne déjà sur la machine, `make up` échoue sur
`address already in use` : changer `POSTGRES_PORT` / `REDIS_PORT` dans `.env` et
reporter le nouveau port dans les trois DSN.

`deploy/postgres/init/01-roles.sql` ne s'exécute qu'à la **création du volume**. Après un
changement de ce fichier : `docker compose down -v && make up`.

## Rôles PostgreSQL

| Rôle | Usage | Privilèges |
|---|---|---|
| `postgres` | superutilisateur du conteneur, amorçage uniquement | tous |
| `coges_owner` | propriétaire du schéma, **migrations Alembic uniquement** | ni superuser, ni BYPASSRLS, mais membre de `coges_auth` |
| `coges_app` | API et workers | SELECT/INSERT/UPDATE, DELETE sur trois tables seulement, ni superuser, ni BYPASSRLS |
| `coges_auth` | propriétaire de la seule fonction `auth_lookup` | **NOLOGIN**, BYPASSRLS |

### `coges_owner` ne doit jamais servir à l'exécution

`COGES_DATABASE_URL_OWNER` est réservé à `alembic upgrade`. Ni l'API, ni les workers, ni un
script d'exploitation ne doivent s'en servir, pour trois raisons cumulatives :

1. il est **propriétaire des tables**, donc il peut modifier les politiques RLS et les
   contraintes qui constituent la barrière 3 ;
2. il est **membre de `coges_auth`** (`WITH INHERIT FALSE`, uniquement pour transférer la
   propriété de `auth_lookup` lors de la migration). Un `SET ROLE coges_auth` explicite lui
   donnerait donc **BYPASSRLS**, c'est-à-dire l'accès à toutes les entreprises ;
3. il échappe aux garde-fous de `coges_app` : les `REVOKE DELETE`, l'interdiction d'écrire dans
   `permissions` et le caractère append-only d'`audit_logs` ne s'appliquent pas à lui.

En production, le DSN propriétaire n'est donc exposé qu'à l'étape de déploiement qui joue les
migrations, jamais à l'environnement d'exécution de l'API ni à celui des workers. Le test
**T36** vérifie de son côté qu'aucun rôle **connectable** n'a `BYPASSRLS` et que `coges_app`
n'est pas membre de `coges_auth`.

Les `GRANT`/`REVOKE` et les politiques RLS sont posés par les migrations `0001` et `0002`,
pas par le script d'amorçage. Attention : `FORCE ROW LEVEL SECURITY` s'applique **aussi** aux
migrations — une migration qui touche des données tenant-scoped doit en tenir compte
explicitement (voir ADR 0008).

## État

Phase 00 : seuls PostgreSQL et Redis sont réellement configurés.
`docker-compose.worker.yml`, `Dockerfile.worker` et `vercel.json` sont des squelettes
provisoires ; ils sont complétés et testés en phases 08 (async) et 10 (déploiement).
