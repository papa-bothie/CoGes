# Prompt 17 — Surveillance et fiabilité des workers (zone B)

Branche `feat/workers-surveillance`, depuis `main` à jour, après le prompt 16 (lot A) et avant le prompt 18 (VPS).

```
Objectif : savoir en moins de 10 minutes qu'un worker, le relais ou beat est tombé, bloqué
ou qu'une tâche de nuit n'a pas tourné, et pouvoir réparer avec un guide écrit. ADR au
prochain numéro libre.
Aucun service payant n'est ouvert sans mon accord explicite : tu prépares le code et la
documentation, je crée moi-même les comptes et je te donne les URL par variables d'env.

1. Battements de cœur (heartbeat)
   - worker, beat et relais écrivent toutes les 30 s une clé Redis
     `coges:heartbeat:<composant>:<hôte>` = horodatage, TTL 120 s.
     Worker : signal `heartbeat_sent` ou thread dédié ; beat : `beat_init` + tâche
     `system.beat_tick` toutes les minutes ; relais : à chaque tour de boucle.
   - `python -m app.workers.health <worker|beat|relay>` : sort en 0 si le battement a
     moins de 90 s, sinon 1. Pour le worker, ajoute `celery inspect ping` sur son nœud.
   - Relais : s'il ne finit pas un tour en 5 min, il s'arrête lui-même (exit 1) pour
     être relancé par Docker.

2. docker-compose.worker.yml
   - `healthcheck` sur les trois services avec la commande ci-dessus (interval 60 s,
     retries 3, start_period 60 s).
   - Docker ne relance pas un conteneur « unhealthy » : ajoute le service `autoheal`
     (willfarrell/autoheal, version figée) limité aux conteneurs étiquetés
     `autoheal=true`.
   - `restart: unless-stopped` déjà présent : garde-le. Logs : garde la rotation.

3. Journal des tâches planifiées
   - Table `job_runs` (migration au prochain numéro libre, après celle du lot A) : job,
     company_id (nullable), started_at, finished_at, status (running|ok|failed), error
     (texte court, sans donnée personnelle). Écrite par un décorateur commun sur chaque
     tâche de beat.py et sur chaque tâche par entreprise de l'éventail. Purge à 90 jours.
   - RLS : lisible seulement par le rôle plateforme, jamais par un tenant.

4. Alertes « homme mort » (dead man's switch)
   - Variable `COGES_JOB_PING_URLS` (JSON : nom de tâche -> URL). En fin de tâche :
     GET <url> si succès, GET <url>/fail si échec ; délai 5 s, jamais bloquant, aucune
     donnée envoyée. Compatible Healthchecks.io et Sentry Crons. Absente = inactif.
   - Un ping « vivant » toutes les 5 min depuis `system.beat_tick` (prouve que beat,
     Redis et le worker tournent ensemble).

5. Point de contrôle global
   - `GET /api/v1/system/workers` réservé au rôle plateforme (jeton
     `COGES_OPS_TOKEN`, comparé en temps constant) : battements par composant, nombre
     d'événements en attente dans l'outbox et âge du plus ancien (fonction SECURITY
     DEFINER de coges_bus, comme outbox_claim), longueur de la file Celery, dernière
     exécution et statut de chaque tâche de beat.py. Répond 503 si un battement manque,
     si l'outbox a un événement de plus de 10 min, ou si une tâche de nuit n'a pas
     réussi depuis 26 h. Réponse sans nom d'entreprise ni donnée personnelle.
   - `make ops-status` : affiche ce bilan en lisible depuis le terminal.
   - `/api/v1/health` : ajoute une variante qui vérifie aussi PostgreSQL et Redis
     (`/api/v1/health/ready`), pour la sonde externe.

6. Sentry
   - Vérifie que l'intégration Celery est active (tag component=worker/beat/relay) et
     qu'une tâche qui épuise ses retries remonte une erreur avec job et company_id.
   - Documente dans README-infra.md les règles d'alerte à créer (e-mail sur nouveau
     problème `component:worker`, `component:relay`).

7. Robustesse
   - ensure_audit_partitions crée 3 mois d'avance (pas 1) : une nuit ratée ne doit
     jamais bloquer les ventes. Test.
   - Au démarrage du worker : refuse de démarrer si Redis a une `maxmemory-policy`
     autre que `noeviction` en production (la file Celery ne doit jamais être
     évincée) ; avertissement seulement en local et préprod.
   - Chaque tâche de beat.py peut être relancée à la main sans effet de bord
     (idempotence) : test par tâche.

8. Guide d'intervention : docs/runbooks/workers.md
   Pour chaque alerte : ce qu'elle veut dire, l'impact pour les gérants, les commandes
   (docker compose ps / logs / restart, make ops-status, relancer une tâche de nuit à
   la main avec `celery -A app.workers.celery_app call <tâche>`), et quand c'est grave.

9. Tests : battement absent -> health en 1 ; tâche en échec -> job_runs failed + ping
   /fail ; /system/workers en 503 dans chacun des 3 cas ; sans jeton -> 401 ; aucune
   fuite inter-tenant (tests/tenancy). Suite complète, ruff, mypy, puis commit.
```

## Décisions prises par le propriétaire

- Zone B en production sur un VPS Infomaniak VPS Lite (prompt 18), Redis sur ce VPS.
- Service d'alerte (Healthchecks.io ou Sentry Crons) et canal de réception : à créer par le propriétaire, qui donne les URL à l'agent.
