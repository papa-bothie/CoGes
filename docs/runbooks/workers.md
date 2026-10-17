# Guide de dépannage — workers, beat, relais (ADR 0077)

Ce guide répond à une alerte : un problème de `make ops-status`, un 503 de
`GET /api/v1/system/workers`, un check Healthchecks.io en retard, ou une erreur Sentry de
`component` `worker`, `beat` ou `relay`. Chaque fiche dit ce que l'alerte veut dire, ce
que vivent les gérants, comment réparer, et dans quel délai.

## Avant tout

```bash
# Préproduction (poste local) ; en production, même chose sur l'hôte des workers.
alias dc='docker compose --env-file deploy/.env.preprod -f deploy/docker-compose.worker.yml'

make ops-status                                   # bilan local (API :8000)
COGES_OPS_URL=https://coges-api.vercel.app make ops-status   # bilan de la préproduction
dc ps                                             # état et santé des conteneurs
dc logs --since 30m worker                        # journaux d'un service (worker, beat, relay)
dc restart relay                                  # relancer un service
dc up -d --build                                  # reconstruire après une mise à jour
dc exec worker celery -A app.workers.celery_app call <tâche>   # relancer une tâche à la main
```

**Toute tâche planifiée se relance à la main sans effet de bord** (testé par
`tests/integration/test_beat_tasks_rerun.py`) : en cas de doute, la relancer est sûr.
Les noms à passer à `call` sont ceux du bilan (`reconcile.rebuild_stock_all`…).

Niveaux d'urgence :

- **Immédiat** : les gérants voient déjà un effet, ou le verront dans l'heure.
- **Dans la journée** : rien de visible avant la nuit prochaine.
- **Peut attendre** : aucun effet avant plusieurs jours.

`autoheal` relance tout seul un conteneur « unhealthy » (3 échecs de sonde, ≈ 4 min). Une
alerte qui revient après une relance automatique est le signe d'une cause qui persiste :
lire les journaux avant de relancer encore.

---

## `heartbeat_missing:worker`

**Ce que ça veut dire.** Aucun worker n'a battu depuis 90 s : arrêté, bloqué, ou Redis
injoignable depuis le worker.

**Impact pour les gérants.** Les ventes, paiements et dépenses passent (l'API ne dépend
pas du worker). Mais les jours passés du tableau de bord, les alertes de stock et les
exports ne bougent plus ; au-delà de 2 min, le tableau de bord affiche « Certains chiffres
se mettent à jour, patientez une minute ».

**Réparer.**

1. `dc ps worker` : `unhealthy` ou `restarting` ? `dc logs --since 15m worker`.
2. `Démarrage du worker refusé` → voir [Redis en éviction](#redis-en-éviction).
3. `ForbiddenRuntimeRoleError` → le DSN du worker vise `coges_owner` : corriger
   `deploy/.env.preprod` (garde-fou de l'ADR 0042).
4. Sinon `dc restart worker`, puis `make ops-status` après 1 min.

**Urgence : immédiat.**

## `heartbeat_missing:beat` ou `beat_tick_missing`

**Ce que ça veut dire.** Beat ne bat plus, ou `system.beat_tick` n'a pas tourné depuis
15 min. Le second seul, avec un worker et un beat qui battent tous deux, veut dire que
beat ne planifie plus ou qu'aucun worker ne consomme la file (voir
[file Celery](#file-celery-qui-grossit)).

**Impact.** Aucun dans la journée. La nuit suivante, plus rien ne tourne : stock non
réaligné, agrégats non rejoués, pas d'alerte de dette échue, pas de conseil au réveil.

**Réparer.** `dc logs --since 30m beat`, puis `dc restart beat`. Si l'état du
planificateur est corrompu (`celerybeat-schedule` illisible dans les journaux), le
supprimer : `dc run --rm beat rm /var/lib/coges/beat/celerybeat-schedule`, puis
`dc up -d beat`. **Un seul beat** à la fois : deux beat déclencheraient chaque batch
deux fois.

**Urgence : dans la journée** (avant 01 h UTC).

## `heartbeat_missing:relay`, ou « Passage du relais bloqué » dans Sentry

**Ce que ça veut dire.** Le relais ne bat plus, ou il s'est arrêté de lui-même parce qu'un
passage a duré plus de 5 min (base qui ne répond plus, verrou, Redis suspendu). Dans le
second cas, `restart` le relance aussitôt : une seule occurrence n'est pas grave, une
répétition l'est.

**Impact.** Les événements s'accumulent dans `business_events` sans être perdus (ils
partiront au redémarrage, T40). En attendant, mêmes effets qu'un worker arrêté.

**Réparer.**

1. `dc logs --since 30m relay` : `Passage du relais en échec` répété → base ou Redis
   injoignable. Vérifier Neon (console : *Compute* actif ? quota de CU-heures épuisé ?) et
   Redis Cloud.
2. `dc restart relay`.
3. Suivre `make ops-status` : `outbox.pending` doit redescendre en quelques minutes.

**Urgence : immédiat.**

## `outbox_lagging`

**Ce que ça veut dire.** Le plus vieil événement en attente a dépassé le seuil
(`COGES_OPS_OUTBOX_MAX_LAG_SECONDS` : 600 s en production, 900 s en préproduction, où le
relais attend jusqu'à 10 min quand la file est vide).

**Impact.** Tableau de bord, alertes et analyses en retard d'autant.

**Réparer.**

1. Le relais bat-il ? Sinon, voir la fiche du relais.
2. S'il bat : `dc logs relay | grep -E "Publication impossible|en échec"`. Publication
   impossible → Redis : vérifier `COGES_REDIS_URL`, la mémoire de la base Redis Cloud.
3. `outbox.dead_lettered` > 0 : des événements ont épuisé leurs 10 tentatives et ne
   repartiront plus seuls. Ils restent en base. Corriger la cause, puis les rejouer
   délibérément (remettre `attempts` à 0 sous `coges_bus`, avec l'accord du responsable
   technique) ; le rebut n'entre pas dans le calcul du retard.

**Urgence : immédiat.**

## File Celery qui grossit

**Ce que ça veut dire.** `queue.length` dans le bilan reste élevé ou monte. Les workers ne
suivent pas, ou aucun ne consomme.

**Impact.** Retard croissant de tout ce qui est asynchrone.

**Réparer.** Un worker bat-il ? `dc logs worker` montre-t-il des tâches qui se terminent ?
Si une tâche bloque (délai de 300 s puis 360 s dépassé), le nom de la tâche est dans
Sentry. Augmenter temporairement `--concurrency` dans le compose si le volume est
simplement trop grand.

**Urgence : dans l'heure** si la file dépasse quelques centaines de tâches.

## `job_failed:<tâche>`, `job_companies_failed:<tâche>`

**Ce que ça veut dire.** La dernière exécution de la tâche a échoué, ou la dernière
exécution de sa sous-tâche a échoué pour au moins une entreprise (`companies_failed`).
Une trace `running` de plus de 6 min compte comme un échec : worker tué en pleine tâche.

**Impact.** Selon la tâche :

| Tâche | Ce que les gérants voient |
|---|---|
| `reconcile.ensure_audit_partitions` | rien tant que trois mois d'avance tiennent ; ensuite l'audit va dans la partition par défaut |
| `reconcile.purge_idempotency_keys`, `system.purge_job_runs`, `exports.sweep_all` | rien ; la base grossit un peu, les exports périmés restent |
| `reconcile.rebuild_stock_all` | rien en général ; une projection de stock peut rester décalée d'un mouvement antidaté |
| `reconcile.rebuild_recent_facts_all` | jours passés du tableau de bord éventuellement faux |
| `ml_*` | pas de conseil frais au réveil |
| `notifications.scan_due_debts_all` | pas d'alerte de dette échue ce jour-là |
| `reconcile.check_revenue_all` | aucun ; c'est le contrôle T32 qui n'a pas tourné |

**Réparer.**

1. Sentry, filtre `job:<sous-tâche>` : classe d'erreur, et `company_id` de l'entreprise
   touchée. La table `job_runs` ne garde que la classe et le SQLSTATE, jamais le message.
2. Corriger la cause, puis relancer l'éventail entier (sûr) :
   `dc exec worker celery -A app.workers.celery_app call reconcile.rebuild_stock_all`,
   ou la sous-tâche d'une seule entreprise :
   `dc exec worker celery -A app.workers.celery_app call reconcile.rebuild_stock --args='["<company_id>"]'`.
3. `make ops-status` : la tâche repasse `ok` dès que la relance réussit.

**Urgence : dans la journée** ; **immédiat** pour `rebuild_recent_facts` et
`scan_due_debts` si un gérant s'en plaint.

## `job_stale:<tâche>` ou `job_never_ran:<tâche>`

**Ce que ça veut dire.** La tâche n'a pas réussi dans sa fenêtre (26 h pour une tâche
quotidienne, 8 jours pour `ml_train.train_all` et `reconcile.check_revenue_all`), ou
n'a jamais tourné depuis 9 jours. Presque toujours beat (voir sa fiche), ou la machine
de la zone B éteinte cette nuit-là.

**Réparer.** Vérifier beat, puis relancer la tâche à la main (commande ci-dessus).
Après un premier déploiement, `job_never_ran` est normal jusqu'à la première nuit.

**Urgence : dans la journée.**

## `redis_unreachable`

**Ce que ça veut dire.** L'API n'a pas pu lire Redis : battements, tic et file inconnus.

**Impact.** Rien de bloquant pour la vente (cache et limitation de débit se désactivent),
mais la file Celery est dans Redis : plus rien d'asynchrone ne part.

**Réparer.** Console Redis Cloud : base active, mémoire, mot de passe inchangé ?
`COGES_REDIS_URL` identique dans Vercel et `deploy/.env.preprod` ?

**Urgence : immédiat.**

## `/api/v1/health/ready` en 503 (sonde externe)

**Ce que ça veut dire.** Le corps dit quelle dépendance manque : `database: down`
(PostgreSQL injoignable par `coges_app`) ou `redis: down` (Redis configuré mais muet).
`redis: not_configured` n'est pas une panne (ADR 0081).

**Impact.** `database: down` : plus aucune vente ni lecture, tout l'écran est en erreur.
`redis: down` : voir `redis_unreachable` ci-dessus.

**Réparer.** Base : console Neon (projet suspendu, quota de calcul, mot de passe de
`coges_app` changé ?), `COGES_DATABASE_URL_APP` dans Vercel. Le détail de l'erreur est dans
les journaux de la fonction Vercel (« Sonde de disponibilité : … »).

**Urgence : immédiat.**

## Redis en éviction

**Ce que ça veut dire.** Au démarrage, le worker a lu une `maxmemory-policy` autre que
`noeviction`. En production, il refuse de démarrer (`Démarrage du worker refusé`) ;
ailleurs, il avertit seulement.

**Impact.** Redis plein effacerait des tâches en attente, sans erreur.

**Réparer.** Redis Cloud → *Database* → *Configuration* → *Data eviction policy* →
`noeviction`, puis `dc restart worker`.

**Urgence : immédiat** en production (le worker ne démarre pas).

## Partitions d'audit

**Ce que ça veut dire.** `reconcile.ensure_audit_partitions` garantit le mois courant et
les trois suivants. Si elle échoue trois mois de suite, l'audit tombe dans
`audit_logs_default` : rien ne casse (ADR 0008), mais la partition par défaut grossit.

**Réparer.** Relancer la tâche ; vérifier en `coges_owner` :
`SELECT relname FROM pg_class WHERE relname LIKE 'audit_logs_2%' ORDER BY 1;`.

**Urgence : peut attendre** (trois mois d'avance).
