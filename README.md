# CoGes

Logiciel de gestion pour PME ouest-africaines, centré sur le cycle **vente → stock →
argent → décision**. Interface en français, montants en FCFA.

- **Backend** : FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 (Neon), multi-entreprise
  isolé par RLS ; asynchrone par outbox → Redis → Celery.
- **Frontend** : Next.js (App Router), TypeScript, qui n'appelle que `/api/v1`.
- **Hébergement** : un VPS en Docker derrière Caddy (front, API, Redis, worker, beat,
  relais), la base chez Neon (ADR 0083).

## Démarrer en local

```bash
cp .env.example .env      # puis remplacer les valeurs
make install              # dépendances et hooks
make up                   # PostgreSQL et Redis locaux
make migrate              # schéma
make seed-demo            # épicerie de démonstration
make dev                  # API, worker, relais et front ensemble
```

`make help` liste toutes les cibles (tests, lint, e2e, analyses de sécurité…).

## Où lire quoi

| Sujet | Fichier |
|---|---|
| Règles du projet, avancement, décisions | `CLAUDE.md` |
| Architecture et modèle de données (font autorité) | `docs/architecture/` |
| Décisions prises en cours de route | `docs/decisions/` |
| Infrastructure, secrets, hébergeurs | `deploy/README-infra.md` |
| Déployer une version | `docs/runbooks/deploiement.md` |
| Intervenir sur le VPS | `docs/runbooks/vps.md` |
| Workers, beat, relais | `docs/runbooks/workers.md` |
| Système visuel | `docs/design/DESIGN.md` |
