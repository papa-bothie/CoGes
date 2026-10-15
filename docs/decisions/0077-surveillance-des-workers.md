# 0077 — Surveillance des workers, de beat et du relais

- **Date** : 2026-10-15
- **Phase** : hors phase (durcissement de la zone B, après la phase 15)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion), sur un cahier des charges fourni

## Contexte

La zone B (worker, beat, relais) tourne hors Vercel (Diagramme 2, ADR 0040). Rien ne
signalait qu'un de ces processus était tombé ou bloqué, ni qu'une tâche de nuit n'avait
pas tourné : les erreurs restaient dans les journaux du poste. L'objectif est de le savoir
en moins de 10 minutes et de réparer avec un guide écrit (`docs/runbooks/workers.md`),
sans ouvrir de service payant (les URL de surveillance arrivent par variables
d'environnement). Le cahier des charges citait « ADR 0066 » et « migration 0015 » :
numéros déjà pris, la décision est la 0077 et la révision la 0021.

## Options envisagées

1. **Propriétaire de `job_runs` : nouveau rôle `coges_ops` (retenue)** — NOLOGIN
   BYPASSRLS, sur le patron de `coges_bus`, portée limitée à `job_runs` (T36). À créer à
   la main sur chaque cluster (Neon), comme les rôles précédents.
2. Réutiliser `coges_bus` : rien à créer, mais le rôle qui franchit la RLS de l'outbox
   aurait vu sa portée s'étendre.
3. **Seuil de retard de l'outbox réglable (retenue)** — `COGES_OPS_OUTBOX_MAX_LAG_SECONDS`,
   600 s en production, 900 s en préproduction, où le relais attend jusqu'à 600 s
   (ADR 0040). Un seuil fixe de 10 min aurait sonné à tort.
4. **Fenêtre de fraîcheur par tâche (retenue)** — 26 h pour une tâche quotidienne,
   8 jours pour `ml_train.train_all` et `reconcile.check_revenue_all`, déclarées dans
   `beat.py` (`JOB_FRESHNESS`) ; un test exige que chaque tâche planifiée y figure.

## Décision

- **Battements** dans Redis, toutes les 30 s, TTL 120 s, jugés absents à 90 s ;
  `python -m app.workers.health` sert de sonde Docker, `autoheal` (1.2.0) relance.
- **Relais** : chien de garde qui arrête le processus si un passage dépasse 5 min.
- **`job_runs`** (révision 0021) : écrite et lue par quatre fonctions de `coges_ops` ;
  aucun privilège pour les rôles d'exécution ; erreur réduite à la classe et au SQLSTATE ;
  purge à 90 jours ; FK vers `companies` mais aucun `company_id` en lecture.
- **`outbox_lag()`**, fonction de `coges_bus` : nombre en attente, rebut, plus vieil
  événement, toutes entreprises confondues.
- **`GET /api/v1/system/workers`** protégé par `COGES_OPS_TOKEN` (temps constant ; 401
  sans jeton ou avec un mauvais jeton ; **404** quand la variable est absente), 200 ou 503
  avec le même corps et une liste `problems` en codes stables ; `make ops-status`.
- **Pings « homme mort »** (`COGES_JOB_PING_URLS`) : `GET <url>` / `<url>/fail`,
  `{status}` pour Sentry Crons, 5 s, jamais bloquants ; succès à la fin d'un éventail,
  échec dès qu'une entreprise échoue.
- **`system.beat_tick` n'écrit pas en base** : une écriture toutes les 5 min empêcherait la
  base de préproduction de s'endormir (100 CU-heures par mois). Son heure va dans Redis.
- **Sentry** : intégration Celery sur le worker et beat, étiquettes `job` et `company_id`
  posées par la classe de tâche commune ; Sentry initialisé dans les signaux Celery et non
  à l'import, pour que le relais reste étiqueté `relay`.
- **Robustesse** : partitions d'audit sur le mois courant et les trois suivants ; worker
  refusé en production si Redis n'est pas en `noeviction` (lu par `INFO memory`) ; chaque
  tâche planifiée testée en double exécution.

## Conséquences

- Schéma : révision 0021 (`job_runs`, `job_run_status`, cinq fonctions). T36 compte cinq
  fonctions privilégiées de plus et un rôle `coges_ops` dont la portée est `job_runs`.
- **Prérequis de déploiement** : `CREATE ROLE coges_ops …` sur Neon **avant** la
  migration 0021 (README-infra).
- `job_runs` est une table de plate-forme absente du § 8 : écart assumé ici.
- Les routes d'exploitation échappent au balayage « 401 sans jeton » des tests de fuite
  (elles répondent 404 tant que le jeton n'est pas configuré) ; leur 401 est testé à part.
- Écart constaté et **non corrigé** ici : Celery avale les exceptions levées dans un
  récepteur de signal ; le garde-fou de rôle de `worker_process_init` (ADR 0042) ne fait
  donc que journaliser. L'engine reste inutilisable par le garde-fou `first_connect`, qui
  protège réellement. Le refus Redis de cette ADR passe par `SystemExit`, que Celery laisse
  passer.
- Repoussé : alerte e-mail ou SMS intégrée à CoGes, tableau de bord d'exploitation dans le
  front.
