# 0081 — Sonde de disponibilité complète `/api/v1/health/ready`

- **Date** : 2026-10-17
- **Phase** : hors phase (complément du prompt 17, surveillance des workers)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

Le prompt 17 (point 5) demandait, à côté de `GET /api/v1/health`, une variante qui vérifie
aussi PostgreSQL et Redis, pour une sonde externe. La PR n° 20 (ADR 0077) a livré le reste
du prompt mais pas cette route. `/health` ne dit que « le processus répond » : une base
endormie ou un Redis tombé ne s'y voient pas.

Deux trous : la valeur par défaut de `redis_url` (`redis://localhost:6379/0`) ne permet pas
de savoir si Redis est attendu, et le client mémorisé de `app.core.cache` garde `None`
après un premier échec, donc ne peut pas servir de sonde.

## Options envisagées

1. **Redis sans adresse = `not_configured`, la sonde reste à 200 (retenue)** : seul un
   Redis dont `COGES_REDIS_URL` est posée et qui ne répond pas donne 503 ; la sonde ne
   sonne pas à tort là où Redis n'est pas prévu.
2. 503 dès que Redis manque : plus strict, mais faux positif en local.

## Décision

- `GET /api/v1/health/ready`, publique comme `/health` : `SELECT 1` sous `coges_app`
  (sans contexte d'entreprise, `statement_timeout` de 2 s) et `PING` sur un client Redis
  neuf (`heartbeat.redis_client`, 2 s).
- Corps identique en 200 et en 503 : `{"status": "ok"|"unavailable", "checks":
  {"database": "ok"|"down", "redis": "ok"|"down"|"not_configured"}}`. Aucun message
  d'erreur, aucun hôte ; le détail part dans les journaux.
- « Configuré » veut dire `COGES_REDIS_URL` donnée par l'environnement (`model_fields_set`).
- Code dans `app/core/readiness.py` : c'est de la plate-forme, pas une règle métier.

## Conséquences

- Contrat : une opération de plus (`openapi.json`, `frontend/types/api.ts`).
- La route rejoint les routes publiques du test de fuite inter-tenant.
- Chaque appel ouvre une connexion PostgreSQL : sur Neon, une sonde toutes les quelques
  minutes **empêche la base de s'endormir** (heures de calcul). En préproduction, espacer
  la sonde externe ou viser `/health` ; en production (Launch, sans veille), sans effet.
- Le service de sonde externe (UptimeRobot, Healthchecks.io…) reste à créer par le
  propriétaire.
