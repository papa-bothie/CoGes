# Infrastructure — CoGes

Répartition des composants : Diagramme 2 de
`docs/architecture/pdf/architecture-technique-v1.1.pdf`. Règle unique : un composant
persistant, long, planifié ou gourmand en mémoire vit **hors Vercel**. Choix des
hébergeurs : ADR 0040. Sécurité et observabilité : ADR 0042.

| Composant | Préproduction | Production (à ouvrir) | Fichier |
|---|---|---|---|
| API FastAPI | Vercel **Hobby** (fonction Python) | Vercel **Pro** | `backend/vercel.json`, `backend/api/index.py` |
| PostgreSQL 16 | **Neon**, offre gratuite (mise en veille) | Neon **Launch**, veille désactivée | `deploy/postgres/init/01-roles.sql` |
| Redis 7 | **Redis Cloud**, offre gratuite (30 Mo) | Redis Cloud | — |
| Worker, beat, relais, ML | **Poste local**, docker compose | hôte à choisir (ADR 0040) | `backend/Dockerfile.worker`, `deploy/docker-compose.worker.yml` |
| Migrations Alembic | job `Déploiement` de GitHub Actions | idem | `.github/workflows/deploy.yml` |
| Erreurs | Sentry (offre Developer) | idem | `app/core/observability.py` |

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

Machine éteinte : les événements s'accumulent dans `business_events` et partent au
redémarrage (au moins une fois, T40) ; les exports restent `pending`, et le balayage
nocturne les renfile. L'API sur Vercel continue de servir.

## Secrets par environnement

| Où | Variable | Préproduction | Production |
|---|---|---|---|
| Vercel (API) | `COGES_ENV` | `staging` | `production` |
| | `COGES_DATABASE_URL_APP` | DSN `coges_app`, hôte **pooler** | idem, projet Launch |
| | `COGES_DB_POOLER` | `transaction` | `transaction` |
| | `COGES_REDIS_URL`, `COGES_JWT_SECRET`, `COGES_SENTRY_DSN` | propres à la préprod | propres à la prod |
| | `COGES_CORS_ORIGINS` | domaine du frontend de préprod | domaine de prod |
| | `COGES_TRUST_PROXY_HEADERS` | `true` | `true` |
| Poste / hôte workers | `COGES_DATABASE_URL_APP`, `…_RELAY`, `…_ANALYTICS` | hôte pooler | idem |
| | `COGES_OUTBOX_IDLE_MAX_SECONDS` | `600` | `1` |
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

`.github/workflows/deploy.yml`, à chaque push sur `main` (préprod) ou à la demande :

1. **CI complète** (`ci.yml`, appelé) : lint, fichiers générés, T1–T40 avec leur tableau
   récapitulatif, tests de fuite, reste de la suite, migrations réversibles, latence. Un
   seul échec, dont une fuite inter-tenant, arrête tout ;
2. contrôle des environnements d'exécution (garde-fou 2) ;
3. `alembic upgrade head` sous `coges_owner`, hôte direct — jamais au démarrage de l'API ;
4. `vercel build` puis `vercel deploy --prebuilt` : les déploiements automatiques depuis
   Git sont **désactivés** (`git.deploymentEnabled: false`), pour qu'aucun code ne parte
   sans la CI ;
5. test de fumée : `deploy/scripts/smoke.py` (santé, connexion, tableau de bord), sur le
   domaine public `COGES_PUBLIC_URL` ; les URL propres à chaque déploiement restent derrière
   la protection Vercel (seule la préversion passe par le jeton de contournement) ;
6. **front** (`coges-web`, ADR 0058) : même `vercel build` puis `vercel deploy --prebuilt`
   depuis `frontend/` (projet `VERCEL_WEB_PROJECT_ID`), **après** le test de fumée de l'API ;
7. test de fumée du front sur `COGES_WEB_PUBLIC_URL` : page `/login` servie, puis
   `smoke.py` **à travers la réécriture** `/api/v1` du front (le chemin d'un utilisateur).

Une migration destructive se déploie en deux temps (décision 17) : d'abord la version
compatible avec l'ancien et le nouveau code, puis le nettoyage.

Les images workers se reconstruisent sur leur hôte (`up -d --build`) après chaque
déploiement qui touche `backend/`.

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
