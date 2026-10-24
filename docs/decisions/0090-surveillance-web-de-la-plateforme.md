# 0090 — Surveillance système dans l'administration (lot admin 2)

- **Date** : 2026-10-23
- **Phase** : lot admin 2 (`docs/prompts/23-admin-surveillance-web.md`)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
Le bilan des workers (`GET /system/workers`, `job_runs`, `make ops-status`, ADR 0077) ne
servait qu'à un terminal muni de `COGES_OPS_TOKEN`. Le prompt 23 l'ouvre aux comptes de
l'équipe (ADR 0089) dans `frontend-admin/`, avec l'historique des tâches, le rebut de
l'outbox et un bandeau de panne sur tout l'écran d'administration.

Trois contraintes héritées se croisent :

1. `job_runs` et `business_events` ne se lisent que par des fonctions `SECURITY DEFINER`
   (`coges_ops`, `coges_bus`) ; `business_events` est une table commerciale, fermée à
   `coges_app_platform`, et l'ADR 0089 lui interdisait **toute** fonction `SECURITY DEFINER`.
2. `modules/platform/` n'importe aucun autre module (test d'architecture).
3. L'administration ne joint que `/api/v1/platform/*` : réécriture Next, et Caddy sur
   `admin.<domaine>`, filtré par adresse IP. `/api/v1/system/workers` est servi sur le
   domaine commerçant, sans filtre.

## Options envisagées
**Rôle qui lit.**
1. **Liste blanche pour `coges_app_platform` (retenue)** : EXECUTE sur quatre fonctions
   nommées ; le test de 0089 passe de « aucune » à « exactement ces quatre ».
2. Lire sous `coges_app` à contexte nul : le rôle plateforme reste nu, mais le rôle
   commerçant pourrait lister le rebut de toutes les entreprises.

**Module.**
1. **Second router dans `system/` (retenue)** : même service, même dépôt que le bilan.
2. Nouveau module `monitoring/` : duplique ou importe `system/`.

**Porte de l'équipe sur le bilan.**
1. **`GET /platform/system/workers` (retenue)** : la même fonction de réponse montée deux
   fois ; `/system/workers` garde le seul jeton d'exploitation. Écart d'URL au prompt
   (« `/system/workers` accepte deux jetons »), assumé.
2. `/system/workers` accepte les deux jetons et s'ouvre sur `admin.<domaine>` : un jeton de
   l'équipe servirait aussi sur le domaine commerçant, hors filtre IP.

**Profils.** Administrateur **et** support (lecture seule, aucune donnée d'entreprise).

## Décision
- **Révision 0027** : `job_runs_history(job, status, stale, limit, offset)` (`coges_ops`,
  90 jours = `purge_job_runs`, `running` périmé rendu `failed`, `per_company` au lieu du
  `company_id`) et `outbox_dead_letters(limit, offset)` (`coges_bus` : identifiant, type,
  date, tentatives, jamais `payload` ni `company_id`). EXECUTE à `coges_app_platform` seul
  sur ces deux-là et sur `outbox_lag()`, `job_runs_latest(interval)` — accordé **au nom du
  propriétaire** (`SET LOCAL ROLE`), `coges_owner` n'héritant pas de ses rôles.
- **Routes**, toutes sous `require_platform_role("administrator", "support")` :
  `GET /platform/system/workers` (même corps, même statut 200/503 que `/system/workers`),
  `GET /platform/system/job-runs?job=&status=&page=&page_size=` (tâche inconnue ⇒ 422),
  `GET /platform/system/outbox?page=&page_size=` (`lag` du bilan + page du rebut).
  L'horloge du bilan passe par `get_ops_now` (réelle ; surchargée par les tests).
- **Front** : `SystemHealthProvider` interroge le bilan toutes les 30 s (et au retour au
  premier plan) ; bandeau `role="alert"` en haut de toutes les pages si 503, motif en mots
  et code exact ; écrans **Système** et **Tâches** ; serveur injoignable ⇒ « État du
  système inconnu », pas une fausse panne.
- **e2e** : `deploy/scripts/e2e.sh system healthy|missing-heartbeat`
  (`backend/tests/e2e/system_state.py`, `coges_e2e` et Redis local seulement) écrit ce
  que worker, beat et relais écriraient, ou retire un battement.

## Conséquences
- Deux portes, une lecture : `_workers_response` → `service.workers_health`, prouvé
  octet pour octet (sain et en panne). Chaque porte refuse le jeton de l'autre.
- `tests/tenancy/test_platform_role_grants.py` nomme les quatre fonctions ;
  `business_events` reste sans aucun droit pour le rôle plateforme.
- Trois lectures de plus dans `READ_ROUTES` (`PLATFORM`). Aucune écriture, aucune tâche,
  aucune table, aucune clé Redis nouvelles. Aucun rôle à créer sur Neon avant 0027.
- L'écran lit, il ne répare pas : rejouer le rebut, relancer une tâche restent des gestes
  de terminal (`docs/runbooks/workers.md`, qui commence désormais par l'écran).
