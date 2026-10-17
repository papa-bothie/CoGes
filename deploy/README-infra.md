# Infrastructure — CoGes

Répartition des composants : Diagramme 2 de
`docs/architecture/pdf/architecture-technique-v1.1.pdf`. Hébergement : **ADR 0083**
(tout sur un VPS sauf la base ; remplace l'ADR 0040). Sécurité et observabilité :
ADR 0042. Guides : `docs/runbooks/vps.md`, `docs/runbooks/deploiement.md`,
`docs/runbooks/workers.md`.

| Composant | Production (VPS) | Préproduction | Fichier |
|---|---|---|---|
| HTTPS, routage `/api/v1` | **Caddy 2.10**, certificats Let's Encrypt | même Caddy, `preprod.<domaine>` | `deploy/vps/Caddyfile` |
| Front Next.js | conteneur `front` (standalone) | projet `coges-preprod`, arrêté par défaut | `frontend/Dockerfile` |
| API FastAPI | conteneur `api` (uvicorn, 2 processus) | idem | `backend/Dockerfile.api` |
| Worker, beat, relais, ML | conteneurs `worker`, `beat`, `relay` | idem | `backend/Dockerfile.worker` |
| Redis 7 | conteneur `redis`, réseau interne, `noeviction` | son propre Redis | `deploy/vps/docker-compose.yml` |
| PostgreSQL 16 | **Neon** offre payante (Francfort), `sslmode=require` | branche Neon de préprod | `deploy/postgres/init/01-roles.sql` |
| Images | `ghcr.io/papa-bothie/coges/{front,api,worker,bundle}` (privé) | mêmes images | `.github/workflows/deploy.yml` |
| Migrations Alembic | job « Déployer » de GitHub Actions (`coges_owner`) | idem | `.github/workflows/deploy.yml` |
| Système du VPS | Ubuntu 24.04, ufw, fail2ban, Docker | même machine | `deploy/vps/bootstrap.sh` |
| Erreurs | Sentry (offre Developer) | idem | `app/core/observability.py` |

Transition : la préproduction historique (API et front sur Vercel, workers sur le poste,
`deploy/docker-compose.worker.yml`) reste en place jusqu'à l'ouverture du VPS ; plus aucun
workflow ne déploie sur Vercel. Le propriétaire supprime les projets Vercel une fois la
production stable.

Aucun service payant n'est ouvert sans accord explicite.

## Développement local

```bash
cp .env.example .env     # puis remplacer les valeurs
make up                  # PostgreSQL 16 + Redis 7, avec healthchecks
make migrate             # migrations, rôle propriétaire
make api                 # http://localhost:8000/api/v1/health
```

Si un PostgreSQL ou un Redis tourne déjà sur la machine, `make up` échoue sur
`address already in use` : changer `POSTGRES_PORT` / `REDIS_PORT` dans `.env` et
reporter le nouveau port dans les DSN.

`deploy/postgres/init/01-roles.sql` ne s'exécute qu'à la **création du volume**. Après un
changement de ce fichier : `docker compose down -v && make up`.

## Rôles PostgreSQL

| Rôle | Connexion | Usage | Privilèges |
|---|---|---|---|
| `coges_owner` | oui | **migrations uniquement** (job de déploiement) | propriétaire du schéma ; membre `WITH INHERIT FALSE` de `coges_auth` et `coges_bus` |
| `coges_app` | oui | API et workers | SELECT/INSERT/UPDATE ; DELETE sur quatre tables seulement ; ni superuser ni BYPASSRLS |
| `coges_relay` | oui | relais de l'outbox | aucun privilège de table ; EXECUTE sur les fonctions du bus |
| `coges_analytics` | oui | agrégats et ML (worker) | seul DELETE : projections reconstruisibles |
| `coges_auth` | **non** | propriétaire d'`auth_lookup` | BYPASSRLS |
| `coges_bus` | **non** | propriétaire des fonctions du relais | BYPASSRLS |
| `coges_ops` | **non** | propriétaire des fonctions de surveillance (ADR 0077) | BYPASSRLS ; n'atteint que `job_runs` |

### `coges_owner` et son risque résiduel

`coges_owner` est membre de `coges_auth` et de `coges_bus`, deux rôles `BYPASSRLS`, pour
que les migrations 0002 et 0010 puissent leur transférer la propriété de fonctions. Un
changement de rôle explicite (`SET ROLE`) lui ouvrirait donc toutes les entreprises.
L'appartenance est **conservée** (décision de la phase 10) ; trois garde-fous la bornent :

1. **Refus au démarrage** (`app/core/role_guard.py`) : tout engine applicatif vérifie à sa
   première connexion que l'utilisateur n'est ni `coges_owner` ni `BYPASSRLS`. Le worker,
   beat et le relais le vérifient avant de consommer quoi que ce soit ; l'API refuse sa
   première requête. Testé par `tests/integration/test_runtime_role_guard.py`.
2. **DSN confiné** : `NEON_OWNER_DSN` n'existe que dans l'environnement GitHub du job de
   migration. `deploy/scripts/check_runtime_env.py` échoue s'il trouve une variable
   `COGES_DATABASE_URL_OWNER`, ou un DSN `coges_owner`, dans les variables Vercel ou dans
   `docker-compose.worker.yml` ; il tourne en CI et avant chaque déploiement.
3. **Surface nommée** : T36 vérifie qu'aucun rôle **connectable** n'a `BYPASSRLS`, que
   `coges_app` n'est pas membre de `coges_auth`, et quelles tables `coges_bus` atteint.

Risque résiduel accepté : quiconque détient le mot de passe de `coges_owner` peut lire
toutes les entreprises. Ce mot de passe se traite donc comme celui d'un administrateur :
secret GitHub d'environnement, jamais sur un poste, rotation à chaque départ d'une personne
qui y a eu accès (`ALTER ROLE coges_owner PASSWORD …` en `neondb_owner`, puis mise à jour
du secret).

## Neon (PostgreSQL)

- **Deux DSN par rôle** : l'hôte `…-pooler…` (PgBouncer en **mode transaction**) pour
  l'API et les workers, avec `COGES_DB_POOLER=transaction` : pool local désactivé
  (`NullPool`) et requêtes préparées côté serveur coupées (`prepare_threshold=None`),
  sans quoi psycopg 3 réutiliserait une requête préparée sur une autre connexion
  physique. L'hôte **direct** (sans `-pooler`) sert seulement aux migrations.
- **Projet de préproduction** : `CoGes-preprod` (`divine-forest-38221389`), PostgreSQL 16,
  `aws-eu-central-1`, branche par défaut `production`. Lien local et politique `neon.ts`
  dans `deploy/neon/` : les commandes `neon` se lancent depuis ce dossier, **toujours avec
  `--no-env-pull`** (sinon la CLI écrit le DSN de `neondb_owner`, BYPASSRLS, dans un `.env`).
- **Amorçage** (fait le 2026-09-26, une fois par projet) : `01-roles.sql` joué en
  `neondb_owner` crée les six rôles ; Neon accepte `NOLOGIN BYPASSRLS`. En PostgreSQL 16,
  `neondb_owner` ne peut pas créer une base appartenant à `coges_owner` sans en être
  membre : la base `coges` se crée donc sous une appartenance **temporaire**
  (`GRANT coges_owner TO neondb_owner WITH INHERIT FALSE, SET TRUE`, `CREATE DATABASE coges
  OWNER coges_owner`, droits du schéma `public` sous `SET ROLE coges_owner`, puis
  `REVOKE coges_owner FROM neondb_owner`). Il ne reste que la délégation d'administration
  automatique, sans `SET` ni `INHERIT`. Pas de `coges_test` sur Neon : les tests tournent
  en local et en CI.
- **Mots de passe** : générés par `openssl rand -hex 24`, jamais affichés. Les trois DSN
  d'exécution sont dans `deploy/.env.preprod` (mode 600, ignoré), **entre guillemets** —
  ils contiennent `&`, et un fichier non protégé chargé par `source` lance chaque ligne en
  tâche de fond et affiche le DSN. Le DSN propriétaire (hôte direct) attend dans
  `deploy/neon/owner-dsn.secret` d'être déposé dans le secret GitHub `NEON_OWNER_DSN`,
  puis détruit (`shred -u`).
- **Préproduction, offre gratuite** : la base s'endort après 5 min d'inactivité ; le
  quota est de 100 CU-heures par mois. Pour laisser la base dormir, le relais espace ses
  passages quand l'outbox est vide, jusqu'à **10 min**
  (`COGES_OUTBOX_IDLE_MAX_SECONDS=600`), puis revient à 1 s dès qu'un événement passe.
  Beat ne planifie que des tâches nocturnes. Conséquence acceptée : après une période
  calme, le premier événement peut attendre jusqu'à 10 min avant d'atteindre les
  agrégats et les alertes.
- **Production, offre Launch** : mise en veille **désactivée**, `COGES_OUTBOX_IDLE_MAX_SECONDS=1`.
- **Sauvegardes** : Neon conserve l'historique pour le PITR, avec une fenêtre qui dépend
  de l'offre (courte en gratuit, 7 jours en Launch). Pas de sauvegarde logique séparée en
  préproduction.

## Redis Cloud

Une base par environnement, à Francfort comme Neon. **Production : TLS obligatoire**
(`rediss://default:<mot-de-passe>@<hôte>:<port>/0`), donc une offre qui le propose.
**Préproduction : sans TLS**, écart accepté le 2026-09-26 (ADR 0040) — l'offre gratuite ne le
propose pas ; mot de passe, messages Celery et cache y passent en clair, ce qui n'est
tolérable qu'avec des données de démonstration. Valeur à coller **seule** et entre
guillemets (`COGES_REDIS_URL="redis://…/0"`), pas la commande `redis-cli -u …` de la console.
Elle porte la file Celery, le cache court du tableau de bord et les compteurs de
limitation de débit. Une panne de Redis ne bloque ni une vente ni un paiement : l'outbox
retient les événements, le cache recalcule, la limitation de débit se désactive.

## Zone B en préproduction : le poste local

```bash
cp deploy/.env.preprod.example deploy/.env.preprod   # puis remplir (fichier ignoré par git)
docker compose --env-file deploy/.env.preprod -f deploy/docker-compose.worker.yml up -d --build
docker compose --env-file deploy/.env.preprod -f deploy/docker-compose.worker.yml logs -f relay
```

**Le relais et le worker de cette zone doivent tourner.** Sans eux, le CA du jour reste
juste (calculé en direct, ADR 0061), mais les jours passés du tableau de bord, la courbe,
les analyses, les alertes et les conseils prennent du retard ; au-delà de deux minutes
d'attente dans l'outbox, le tableau de bord du gérant affiche « Certains chiffres se
mettent à jour, patientez une minute. »

Machine éteinte : les événements s'accumulent dans `business_events` et partent au
redémarrage (au moins une fois, T40) ; les exports restent `pending`, et le balayage
nocturne les renfile. L'API sur Vercel continue de servir.

## Surveillance des workers (ADR 0077)

Objectif : savoir en moins de 10 minutes qu'un worker, beat ou le relais est tombé ou
bloqué, ou qu'une tâche de nuit n'a pas tourné. Quoi faire de chaque alerte :
**`docs/runbooks/workers.md`**.

| Signal | Où | Délai de détection |
|---|---|---|
| Battement Redis `coges:heartbeat:<composant>:<hôte>`, toutes les 30 s | healthcheck Docker → `autoheal` relance le conteneur | ≈ 4 min (3 × 60 s) |
| Passage du relais de plus de 5 min | le relais s'arrête (exit 1), `restart` le relance | 5 min |
| `GET /api/v1/system/workers` (jeton `COGES_OPS_TOKEN`), `make ops-status` | 503 + liste `problems` | à la demande |
| Pings « homme mort » (`COGES_JOB_PING_URLS`) | Healthchecks.io ou Sentry Crons | délai de grâce du check |
| Tâche en échec | Sentry, étiquettes `component`, `job`, `company_id` | immédiat |
| `GET /api/v1/health/ready` (public) : PostgreSQL et Redis | sonde externe, 503 si l'un ne répond pas (ADR 0081) ; sur Neon gratuit, chaque appel réveille la base | intervalle de la sonde |

**Aucun service payant n'est ouvert sans accord** : les comptes se créent à la main, puis
leurs URL passent par les variables ci-dessous.

### Rôle `coges_ops` (révision 0021)

Rôle de cluster : il ne naît pas d'une migration. **Avant** la migration 0021 sur un
cluster existant (Neon préprod, puis prod), en `neondb_owner` :

```sql
CREATE ROLE coges_ops NOLOGIN NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT coges_ops TO coges_owner WITH INHERIT FALSE;
```

**Préproduction : fait le 2026-10-15** (projet `CoGes-preprod`, base alors en 0020).
Production : à faire à son ouverture.

En local, sans recréer le volume : même commande par
`docker compose exec -T postgres psql -U postgres`. Un cluster neuf l'a déjà par
`01-roles.sql`.

### Pings « homme mort » (Healthchecks.io, offre gratuite)

Un check par tâche ; l'URL `https://hc-ping.com/<uuid>` reçoit `GET` au succès et
`GET …/fail` à l'échec. Le service alerte quand un ping attendu n'arrive pas.

| Tâche (clé du JSON) | Période | Délai de grâce |
|---|---|---|
| `system.beat_tick` | 5 min | 10 min |
| `reconcile.ensure_audit_partitions`, `system.purge_job_runs`, `reconcile.purge_idempotency_keys`, `exports.sweep_all`, `reconcile.rebuild_stock_all`, `reconcile.rebuild_recent_facts_all`, `ml_features.compute_all`, `ml_infer.infer_all`, `notifications.scan_due_debts_all` | 1 jour (cron `beat.py`, UTC) | 2 h |
| `ml_train.train_all`, `reconcile.check_revenue_all` | 7 jours | 6 h |

Un échec d'entreprise pingue `/fail` au nom de l'éventail. Le succès part à la fin de
l'éventail. **Sentry Crons** (inclus dans l'offre Sentry) : mettre `{status}` dans l'URL de
check-in (`…/cron/<slug>/<clé>/?status={status}`), remplacé par `ok` ou `error`.

### Règles d'alerte Sentry à créer

L'intégration Celery est active sur le worker et beat ; chaque événement porte `component`
(`api`, `worker`, `beat`, `relay`), et pour une tâche `job` et, s'il y a lieu, `company_id`
(un identifiant, jamais un nom). Une tâche relancée par `self.retry` ne remonte qu'une
fois ses tentatives épuisées.

1. **Nouvelle erreur en zone B** : *Issue alert*, « A new issue is created », filtre
   `component` dans `worker, beat, relay` → e-mail (ou Slack) immédiat.
2. **Tâches qui échouent en série** : *Issue alert*, « The issue is seen more than 3 times
   in 1 hour », filtre `component:worker` → e-mail.
3. **Relais arrêté par son chien de garde** : *Issue alert* sur le message
   « Passage du relais bloqué », filtre `component:relay` → e-mail immédiat.
4. Si Sentry Crons est choisi à la place de Healthchecks.io : un moniteur par tâche avec
   les périodes et délais de grâce du tableau ci-dessus.

### Ce qui ne doit pas réveiller Neon

Les battements, le tic de beat et les pings passent par Redis ou HTTP, jamais par la base.
`/system/workers` lit la base (outbox, `job_runs`) : en préproduction, ne pas le faire
sonder plus d'une fois par heure par un service externe, sans quoi la base ne s'endort
plus (100 CU-heures par mois). Les pings couvrent le reste.

### Redis : `maxmemory-policy noeviction`

Une politique d'éviction effacerait des tâches en attente quand Redis est plein. Le
worker **refuse de démarrer en production** sans `noeviction` (lu par `INFO memory`) et
avertit seulement en local et en préproduction. Redis Cloud : *Database* → *Configuration*
→ *Data eviction policy* → `noeviction`.

## Connexion : freinage et mode dégradé (ADR 0078)

Le freinage par compte (`rl:acct:{sha256(slug|identifiant)}`) et le plafond de connexion
par IP vivent dans Redis. **Si Redis manque**, `/auth/login` (et lui seul) passe sur un
compteur **en mémoire du processus** (10 000 clés au plus, les plus anciennes évincées) ;
les autres routes perdent leur limite, comme avant. L'incident est journalisé et envoyé à
Sentry (« limitation de connexion en mode dégradé », une fois par minute au plus).

Sur Vercel, chaque instance de la fonction a sa propre mémoire, et une instance froide
repart de zéro : c'est un **frein dégradé, pas une garantie**. Une panne de Redis en
production se répare, elle ne s'attend pas. L'alerte « Plusieurs tentatives de connexion
échouées » passe par une tâche du worker : sans Redis, elle se perd (le freinage tient).

## Secrets par environnement

> Tableau de la préproduction **Vercel** actuelle, valable jusqu'à l'ouverture du VPS.
> Sur le VPS, voir « Secrets et variables du VPS » ci-dessous (ADR 0083).

| Où | Variable | Préproduction | Production |
|---|---|---|---|
| Vercel (API) | `COGES_ENV` | `staging` | `production` |
| | `COGES_DATABASE_URL_APP` | DSN `coges_app`, hôte **pooler** | idem, projet Launch |
| | `COGES_DB_POOLER` | `transaction` | `transaction` |
| | `COGES_REDIS_URL`, `COGES_JWT_SECRET`, `COGES_SENTRY_DSN` | propres à la préprod | propres à la prod |
| | `COGES_CORS_ORIGINS` | domaine du frontend de préprod | domaine de prod |
| | `COGES_TRUST_PROXY_HEADERS` | `true` | `true` |
| | `COGES_OPS_TOKEN` | `openssl rand -hex 32` | idem, distinct |
| | `COGES_OPS_OUTBOX_MAX_LAG_SECONDS` | `900` | `600` |
| | `COGES_TEMP_PASSWORD_TTL_HOURS` (ADR 0078) | `48` (défaut, à ne poser que pour changer) | `48` |
| | `COGES_LOGIN_THROTTLE_*` (ADR 0078) | défauts : 5 échecs / 15 min, 30 min au plus, alerte au 10e | idem |
| Poste / hôte workers | `COGES_DATABASE_URL_APP`, `…_RELAY`, `…_ANALYTICS` | hôte pooler | idem |
| | `COGES_OUTBOX_IDLE_MAX_SECONDS` | `600` | `1` |
| | `COGES_JOB_PING_URLS` | JSON des URL de Healthchecks.io (facultatif) | idem |
| GitHub, environnement `preprod` / `production` | `NEON_OWNER_DSN` | DSN `coges_owner`, hôte **direct** | idem |
| | `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` (`VERCEL_TEAM_ID`) | projet Hobby | projet Pro |
| | `SMOKE_SLUG`, `SMOKE_EMAIL`, `SMOKE_PASSWORD` | entreprise de fumée | idem |
| | `VERCEL_AUTOMATION_BYPASS_SECRET` | pour les préversions protégées | — |
| GitHub, variable d'environnement | `COGES_PUBLIC_URL` | `https://coges-api.vercel.app` (cible du test de fumée) | domaine de prod |

Jamais de `COGES_DATABASE_URL_OWNER` dans Vercel ni chez les workers (garde-fou 2).
L'approbation obligatoire sur l'environnement GitHub `production` n'existe pas pour un dépôt
privé en offre gratuite (refusée par GitHub le 2026-09-26). Garde-fou en attendant : un
déploiement de production ne part que d'un lancement manuel du workflow (cible
`production`), et cet environnement n'a aucun secret tant que la production n'est pas
ouverte. À activer avec une offre GitHub qui le permet.

### Rotation de la clé JWT

`COGES_JWT_SECRET` signe les jetons d'accès (15 min) ; les jetons de rafraîchissement sont
des valeurs aléatoires hachées en base (`auth_sessions`), indépendantes de la clé.

1. Générer une clé : `openssl rand -hex 32`.
2. La remplacer dans Vercel (et chez les workers, qui la lisent pour la configuration),
   puis redéployer.
3. Effet : chaque jeton d'accès en cours est refusé (401). Le frontend rafraîchit alors
   sa session avec le cookie de rafraîchissement, que la rotation n'invalide pas : aucune
   reconnexion n'est demandée. Pour **forcer** la reconnexion de tous (fuite supposée),
   révoquer aussi les sessions : `UPDATE auth_sessions SET revoked_at = now() WHERE revoked_at IS NULL`,
   entreprise par entreprise, sous le contexte tenant.

## Déploiement

Tout est décrit dans `docs/runbooks/deploiement.md`. En bref (ADR 0083) :

1. la **CI** tourne sur chaque push et chaque PR (lint, tests, T1–T40, fuites, analyses de
   sécurité, et le job `vps` : shellcheck, Caddyfile, compose, quatre images sans push) ;
2. le workflow **« Déployer »** part d'un tag `vX.Y.Z` (préprod) ou à la main (préprod ou
   production) : CI, images poussées sur ghcr.io, `alembic upgrade head` sous
   `coges_owner` depuis le job, puis `deploy.sh` sur le VPS par une clé SSH bridée, test de
   fumée (`deploy/scripts/smoke.py` : `/health/ready`, `/login`, connexion, tableau de
   bord) et retour automatique à la version précédente en cas d'échec ;
3. sans clé de déploiement, le workflow s'arrête après les migrations et affiche la
   commande à lancer sur le VPS.

Une migration reste compatible avec la version précédente du code (on ajoute d'abord, on
supprime à la version suivante) : un retour arrière ne touche jamais la base.

### Secrets et variables du VPS (ADR 0083)

| Où | Nom | Contenu |
|---|---|---|
| VPS, `/etc/coges/coges.env` (root:deploy, 0640) | modèle `deploy/vps/coges.env.example` | `COGES_DOMAIN`, `COGES_ACME_EMAIL`, DSN Neon d'exécution (`sslmode=require`), `COGES_REDIS_PASSWORD`, `COGES_JWT_SECRET`, `COGES_OPS_TOKEN`, `COGES_SENTRY_DSN`, `COGES_JOB_PING_URLS` |
| VPS, `/etc/coges/preprod.env` | même modèle | valeurs de la préprod (branche Neon de préprod) |
| VPS, `/etc/coges/ghcr-user`, `ghcr-token` | jeton GitHub **`read:packages` seulement** | lecture des images |
| GitHub, environnements `preprod` / `production` | secrets `NEON_OWNER_DSN`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`, `SMOKE_SLUG`, `SMOKE_EMAIL`, `SMOKE_PASSWORD` | voir `docs/runbooks/deploiement.md` |
| GitHub, variables d'environnement | `DEPLOY_HOST`, `DEPLOY_PORT`, `COGES_PUBLIC_URL` | adresse SSH du VPS, `https://<domaine>` |

`check_runtime_env.py --require-vps` refuse un fichier de secrets qui contient un DSN
propriétaire, un DSN sans `sslmode=require`, un Redis externe, un domaine avec schéma ou
des secrets de moins de 32 caractères ; `deploy.sh` le lance avant chaque démarrage.

Registre : une version pèse ≈ 460 Mo compressés (worker ≈ 295 Mo), cinq versions ≈ 0,7 Go.
Le quota gratuit d'un dépôt privé (500 Mo) ne suffit pas : GitHub Pro (2 Go) ou moins de
versions gardées (ADR 0083).

## Restauration

**Testée en local** par `deploy/scripts/restore-check.sh` (après `make up`) : sauvegarde
`pg_dump` de `coges`, restauration dans une base neuve, puis contrôles — révision Alembic,
nombre de lignes des tables clés, RLS FORCE sur toutes les tables, propriétaire
d'`auth_lookup`, et `coges_app` sans contexte qui ne voit rien.

**Sur Neon (PITR)** :

1. Console Neon → *Branches* → *Create branch* → *Point in time*, à l'instant voulu
   (avant l'incident). La branche est une copie complète, rôles compris.
2. Vérifier la branche : `SOURCE_DB` / connexion vers la branche, puis
   `alembic current` et les contrôles de `restore-check.sh` à la main.
3. Basculer : soit *Restore* de la branche principale sur ce point (Neon garde une
   sauvegarde de l'état remplacé), soit pointer les DSN de Vercel et des workers vers
   la branche, puis redéployer.
4. Rejouer le test de fumée. Les événements de l'outbox postérieurs au point de
   restauration sont perdus avec leurs données : relancer les batchs nocturnes
   (`reconcile.*`) pour réaligner stock et agrégats.

À rejouer une fois ensemble sur la préproduction, puis une fois par trimestre.

## Provisionnement de la préproduction (fait le 2026-09-27)

En ligne : **`https://coges-api.vercel.app`** (Vercel, équipe CipherOne, projet `coges-api`,
Hobby). Premier déploiement vert par le workflow, test de fumée compris, et chaîne
asynchrone vérifiée (outbox → relais → Redis → worker en ~10 s). Écarts rencontrés : ADR 0044.

1. **Neon** : projet `CoGes-preprod`, rôles et base amorcés (section Neon) ; migrations
   jouées par le workflow.
2. **Redis Cloud** : base gratuite, sans TLS (écart préprod, ADR 0040).
3. **Sentry** : DSN dans Vercel et `deploy/.env.preprod`.
4. **Vercel** : `vercel link` depuis `backend/` (lien `.vercel/` ignoré). Variables posées
   **par l'API avec `type: "encrypted"`**, pas par `vercel env add`, qui les rend
   *sensitive* et aveugle le garde-fou 2 (ADR 0044).
5. **GitHub, environnement `preprod`** : secrets `NEON_OWNER_DSN`, `VERCEL_TOKEN`,
   `VERCEL_ORG_ID`, `VERCEL_TEAM_ID`, `VERCEL_PROJECT_ID`, `SMOKE_*` ; variable
   `COGES_PUBLIC_URL`.
6. **Entreprise de fumée** : slug `fumee`, gérant `fumee@example.com`, mot de passe
   aléatoire connu du seul secret `SMOKE_PASSWORD` (le réinitialiser par
   `users.service.change_password` en cas de perte).
7. **Zone B** : `up -d --build` sur le poste (section ci-dessus).

## Frontend de préproduction (fait le 2026-09-29)

Projet Vercel **`coges-web`** (équipe CipherOne, Hobby), lié depuis `frontend/` (lien
`.vercel/` ignoré), configuré par `frontend/vercel.json` (Next.js, `cdg1`, déploiements Git
désactivés). Variable `COGES_API_URL=https://coges-api.vercel.app` (preview et production),
lue **au build** par la réécriture `/api/v1/*` (ADR 0047).

**Depuis le 2026-10-01 (ADR 0058)**, le front se déploie avec l'API à chaque push sur `main`,
par le workflow « Déploiement », en production Vercel du projet : adresse stable et
**publique** **`https://coges-app.vercel.app`** (la connexion CoGes reste exigée). Ce domaine est
attribué au projet `coges-web` ; l'adresse générée `coges-web-cipher-one1.vercel.app` reste
derrière la protection Vercel (seuls les domaines attribués échappent à la protection standard).
Environnement GitHub `preprod` : secret `VERCEL_WEB_PROJECT_ID`, variable
`COGES_WEB_PUBLIC_URL`. Le garde-fou 2 contrôle aussi les variables de `coges-web`.

Piège rencontré au premier déploiement (2026-10-01) : `COGES_API_URL` avait été posée par
`vercel env add`, donc **sensible** ; `vercel pull` sur GitHub la récupère alors sous la forme
`[SENSITIVE]` et `next build` refuse la réécriture (« Invalid rewrite found »). Les préversions
manuelles passaient, car construites sur les serveurs de Vercel. Comme pour l'API (ADR 0044),
la variable est posée **par l'API Vercel avec `type: "encrypted"`** (production et preview).

Préversion manuelle d'une branche, toujours possible :

```bash
cd frontend && vercel deploy --scope cipher-one1
```

Les préversions sont derrière la protection Vercel : ouvrir l'URL dans un navigateur connecté
à un compte de l'équipe, ou `vercel curl <url>/api/v1/health --scope cipher-one1`. Une cible
`preview` du workflow a besoin du secret `VERCEL_WEB_AUTOMATION_BYPASS_SECRET` (jeton de
contournement du projet `coges-web`) pour son test de fumée.
Entreprise de test du front : slug `demo-front`, gérant `gerant@demo-front.example.com`
(créée par `create-company` ; mot de passe transmis hors dépôt).

Piège rencontré : le job de déploiement lit les secrets de l'**environnement** GitHub
`preprod`, qui priment sur ceux du dépôt. Un `VERCEL_TOKEN` se remplace donc par
`gh secret set VERCEL_TOKEN --env preprod`, avec un jeton Vercel de portée **CipherOne**
(un jeton de portée « Personal Account » reçoit `403 invalidToken`).

Reste ouvert : la production (Neon Launch, Vercel Pro, hôte de la zone B), l'environnement
`preview` (`VERCEL_AUTOMATION_BYPASS_SECRET`), et l'exercice de restauration PITR à rejouer
ensemble.
