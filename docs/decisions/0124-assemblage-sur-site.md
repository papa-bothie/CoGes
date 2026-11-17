# 0124 — CoGes « sur site » : un assemblage à part, sur http://localhost

- **Date** : 2026-11-16
- **Phase** : installation sur site, lot 1 (`docs/prompt-sur-site/01-assemblage.md`)
- **Statut** : acceptée (exception nommée au garde-fou 2 de l'ADR 0042 ; complète 0083 et 0095)
- **Décideur** : utilisateur (prompt du lot, et quatre choix par AskUserQuestion)

## Contexte

Un client veut CoGes sur **son** PC : une société, un poste fixe sous Windows 11 (8 Go de
mémoire, Docker Desktop avec WSL 2), sans téléphone ni accès depuis le réseau du magasin.
Le navigateur du PC ouvre `http://localhost`. L'architecture V1 ne prévoit que la
production en ligne (VPS et Neon, ADR 0083) : il faut faire tourner la base sur place, sans
nom de domaine ni service externe, **sans rien changer pour les utilisateurs actuels**.

Six lots : assemblage (celui-ci), licence, installation Windows, sauvegarde, mises à jour à
distance, support à distance.

## Options envisagées

1. **Un assemblage à part, `deploy/onprem/` (retenue)** : nouveau compose, nouveau
   Caddyfile, nouveau contrôle. Aucun fichier du VPS ne change.
2. Un profil de plus dans `deploy/vps/docker-compose.yml` : un seul fichier à maintenir,
   mais chaque retouche pour le sur site modifierait le fichier qui porte la production,
   et le bundle de déploiement embarquerait des services qu'elle ne lance jamais. Le
   compose du VPS suppose en outre Neon, un domaine, Let's Encrypt et le réseau partagé
   `coges_edge` : presque rien n'est commun.

## Décision

**Ajouter, ne rien modifier.** Tout vit dans `deploy/onprem/` (livré au client) et
`deploy/onprem-ci/` (vérification), avec un workflow, des tests et de la documentation.

### Ce qui tourne

Neuf services continus : `caddy`, `autoheal`, `postgres`, `redis`, `front`, `api`,
`worker`, `beat`, `relay` ; deux services ponctuels (profil `tools`) : `migrate` et `cli`.
Ni administration de la plateforme (`/api/v1/platform/*` répond 404), ni `cloudflared`.
Les images `front`, `api` et `worker` sont **celles de la production**, au même registre
public (`COGES_IMAGE_REGISTRY`, `COGES_IMAGE_TAG` obligatoire) : aucun `docker login`,
aucune image propre au sur site, aucune dépendance ajoutée.

Réglages repris du VPS : journaux bornés, `no-new-privileges`, sondes, `stop_grace_period`,
Redis en `noeviction` aux commandes renommées, `restart: unless-stopped`, `autoheal` figé
par condensat.

### PostgreSQL sur place (choix du propriétaire)

`postgres:18.7-alpine` : la version majeure de la production (ADR 0095), version mineure
figée, volume nommé, aucun port publié. Tri **intégré** `C.UTF-8`
(`--locale-provider=builtin`) : il ne dépend pas du système de l'image, donc aucun index à
reconstruire quand l'image change. Il est fixé à la création de la base, pour toujours.

`postgres-init/01-roles.sql` crée les mêmes rôles, attributs et GRANT que
`deploy/postgres/init/01-roles.sql`, pour la seule base `coges`, sans aucun mot de passe
par défaut. Un test compare les deux scripts : si l'un change sans l'autre, la CI échoue.
`coges_backup` existe (la révision 0023 lui donne ses droits) avec un mot de passe vide :
personne ne s'y connecte avant le lot 4.

### L'exception du DSN propriétaire

Le garde-fou 2 de l'ADR 0042 veut que le DSN de `coges_owner` n'existe que dans le job de
migration de GitHub Actions. Sur site, les migrations se jouent sur le PC : le mot de
passe de `coges_owner` vit donc dans `coges.env`. Exception **limitée au sur site**, avec
ses garde-fous :

- le compose compose lui-même les DSN ; celui du propriétaire n'est écrit qu'une fois,
  dans le service ponctuel `migrate`, jamais lancé par `up` ;
- aucun service continu, ni `cli`, ne le reçoit (test sur le fichier, et contrôle du
  compose rendu) ;
- les garde-fous 1 de l'ADR 0042 restent actifs : worker et relais refusent de démarrer
  sous `coges_owner` ;
- `deploy/scripts/check_runtime_env.py` et ses tests ne changent pas : le compose du VPS
  reste sans aucune mention de ce DSN.

### Réglages : des mots de passe, pas d'adresses (choix du propriétaire)

`coges.env` porte l'étiquette de version, huit mots de passe hexadécimaux, la clé
`COGES_MFA_ENCRYPTION_KEY` (exigée par l'API hors `local` et `ci`, ADR 0105), le port et
l'adresse locale. Aucun DSN : rôle, hôte `postgres` et base sont figés dans le compose.

`check_onprem_env.py` (bibliothèque standard, lancé dans l'image worker : le PC n'a pas
Python) refuse, en français et en disant quoi corriger : un secret vide, court, de modèle,
non hexadécimal ou en double ; une étiquette vide ou `latest` ; un port et une adresse qui
ne concordent pas ; un service facultatif posé ou à moitié posé ; tout DSN ou URL Redis
écrits à la main ; `COGES_ENV` autre que `production`. Avec `--rendered` (le rendu JSON du
compose, joué en CI), il vérifie ce que chaque conteneur reçoit vraiment : rôle de chaque
DSN (liste blanche de l'ADR 0088, tenue identique à celle du VPS par un test), hôte
`postgres`, DSN propriétaire dans `migrate` seulement, Redis interne, étiquettes, ports.

**Garde-fou « jamais la production »** : toute valeur contenant `neon.tech`, `coges.app`,
`vercel.app` ou un Redis hébergé est refusée. Une installation sur site ne peut pas, même
par copier-coller, se brancher sur la base ou les services des utilisateurs actuels.

Un fichier de réglages enregistré en CRLF par le Bloc-notes est accepté : `docker compose
--env-file` le lit de la même façon (vérifié). Les fichiers du **programme**, eux, restent
en LF (`deploy/onprem/.gitattributes`, dans ce dossier seulement, et un test).

### `COGES_ENV=production` sur `http://localhost`

L'application tourne en `production` : secrets réels exigés, documentation de l'API
fermée, cookies `Secure`. Les navigateurs traitent `http://localhost` comme un contexte
sûr : le cookie de rafraîchissement `Secure` y est accepté et le service worker s'y
enregistre (prouvé sous Chromium dans la CI ; Edge et Chrome partagent ce moteur).

En `production`, l'API ajoute un en-tête HSTS à ses réponses. Servi en HTTP, un navigateur
l'ignore ; Caddy le retire quand même, pour ne laisser aucune ambiguïté. Caddy sert un seul
site, `http://localhost`, HTTPS automatique coupé : ni certificat, ni Let's Encrypt.

### La boucle locale seule, et aucune sortie (choix du propriétaire)

Caddy publie un port, `127.0.0.1:${COGES_HTTP_PORT:-80}` : rien n'est joignable depuis le
réseau du magasin. Tous les services sont sur un réseau Docker **interne**
(`172.31.80.0/24`, distinct de ceux du VPS) : aucun conteneur ne joint Internet. Caddy
touche en plus un second réseau, le seul moyen pour Docker de publier son port. L'API ne
croit `X-Forwarded-For` que venu du sous-réseau interne.

Ce qui est testé en CI est donc exactement ce qui est livré. Un lot futur qui voudrait
des e-mails ou des photos devra ouvrir une sortie explicitement.

### Ce qui est éteint

SMTP, Web Push (VAPID), Cloudinary, Sentry, pings, Cloudflare Access, inscription
libre-service. Le contrôle refuse qu'on les pose. Les seize tâches planifiées, déclenchées
à la main en CI, ne laissent ni erreur ni avertissement dans les journaux.

### Budget mémoire

Docker Desktop ne donne par défaut que la moitié de la mémoire (4 Go sur 8). Plafonds des
services continus : 2 736 Mo (test : moins de 3 Go).

| Service | Plafond | Mesuré au repos | Mesuré pendant une vente |
|---|---|---|---|
| postgres (`shared_buffers` 128 Mo) | 512 Mo | 74 Mo | 67 Mo |
| worker (`--concurrency=1`) | 700 Mo | 277 Mo | 239 Mo |
| api (1 processus) | 500 Mo | 147 Mo | 124 Mo |
| front | 320 Mo | 67 Mo | 76 Mo |
| redis (`maxmemory` 128 Mo) | 224 Mo | 6 Mo | 4 Mo |
| beat | 224 Mo | 111 Mo | 142 Mo |
| relay | 160 Mo | 74 Mo | 70 Mo |
| caddy | 64 Mo | 20 Mo | 26 Mo |
| autoheal | 32 Mo | 1 Mo | 1 Mo |
| **Total** | **2 736 Mo** | **≈ 780 Mo** | **≈ 750 Mo** |

Mesures `docker stats` sur un poste Linux, base presque vide ; à refaire sous Docker
Desktop, et avec un historique de ventes (le worker monte pendant les calculs de nuit).

### Trois endroits, et « sorties seulement »

1. **Le programme** : tout `deploy/onprem/`, remplaçable par une version plus récente. Le
   dossier ne référence aucun fichier hors de lui-même (la page de maintenance y est
   copiée ; un test la tient identique à celle du VPS) : le lot 5 pourra le publier tel
   quel comme archive versionnée.
2. **Les réglages** du client (`coges.env`), rangés hors de ce dossier, passés par
   `--env-file`, jamais écrasés.
3. **Les données** : volumes nommés (PostgreSQL, Redis, artefacts ML, état de beat,
   fichiers statiques du front, Caddy).

Une seule variable décide de la version : `COGES_IMAGE_TAG`. Mettre à jour à la main :
changer l'étiquette, `pull`, arrêter `api worker beat relay front`, `migrate`, `up`
(guide, et rejoué en CI). `migrate` rejoué ne change rien.

La procédure n'ouvre **aucun port entrant** sur le PC ni sur la box du client : tout passe
par des connexions sortantes vers le registre public, lancées par Docker sur l'hôte (les
conteneurs, eux, n'ont aucune sortie). La mise à jour à distance du lot 5 (à la demande
par une session de support, ou vérification automatique d'une nouvelle version) reposera
sur ce principe.

### Garde-fous pour les utilisateurs actuels

- `deploy/onprem/check_protected_paths.py` : sur une pull request dont la branche commence
  par `feat/sur-site-`, le workflow échoue si un chemin protégé change (`deploy/vps/**`,
  `deploy/scripts/**`, `deploy/postgres/**`, `deploy/sql/**`, `docker-compose.yml`,
  `backend/app/**`, `backend/migrations/**`, `backend/Dockerfile.*`,
  `backend/pyproject.toml`, `backend/uv.lock`, `frontend/**`, `frontend-admin/**`,
  `.github/workflows/deploy.yml`, `.github/workflows/backup*.yml`), en nommant le fichier.
  Les autres branches ne sont pas concernées.
- **Workflow à part** (choix du propriétaire) : `.github/workflows/onprem.yml`.
  « Déployer » rappelle `ci.yml` en entier avant de livrer ; un job `onprem` dans `ci.yml`
  aurait pu bloquer un déploiement de production. `ci.yml` n'est pas modifié du tout.
- Le job `vps` et les tests de `check_runtime_env.py` restent verts sans modification.
- `deploy/vps/Dockerfile.bundle` n'embarque rien de `deploy/onprem/` (test) ; les
  contextes de construction (`backend/`, `frontend/`, `frontend-admin/`) sont inchangés :
  les images de production sont identiques. `deploy.yml` ne part que sur une étiquette
  `vX.Y.Z` ou à la main : fusionner ne déploie rien.
- **Règle pour les lots suivants** : tout changement du code de l'application passera par
  un interrupteur éteint par défaut, avec un test qui prouve que, sans lui, le comportement
  est identique à aujourd'hui.

## Conséquences

- Aucune migration, aucune dépendance, aucun changement du code de l'application.
- Écart au prompt, constaté : `docker kill` (comme `docker stop`) est pour Docker un arrêt
  **à la main**, jamais suivi d'un redémarrage, quelle que soit la politique. La CI prouve
  donc le retour seul après une **panne** (arrêt immédiat du postmaster, sans point de
  contrôle : Docker relance, PostgreSQL rejoue son journal), et montre que `up -d` ramène
  un conteneur tué à la main. Le guide le dit.
- Ordre du guide : `migrate` avant `up`. Démarrer d'abord laisserait le relais et le worker
  échouer sur une base vide.
- Aucune sauvegarde tant que le lot 4 n'existe pas : ne pas mettre de données réelles chez
  un client sans copie. Une migration jouée ne se défait pas sans elle.
- Le lot 2 (`activate-license`) touchera `backend/app/` : le contrôle des chemins protégés
  le refusera tant que son prompt ne prévoit pas la dérogation, à demander au propriétaire.
- Windows n'est pas testé par la CI : liste des vérifications à faire sur la machine dans
  `docs/prompt-sur-site/README.md`.

## Complément (lot 2, ADR 0125) : dérogation étroite au contrôle des chemins protégés

`check_protected_paths.py` accepte désormais les fichiers de sa table `DEROGATIONS`, et
seulement si le diff n'y retire **aucune** ligne (`git diff --numstat`). Pour le lot 2 :
`backend/app/cli.py` et `backend/app/modules/platform/service.py`, rien d'autre ; un
test épingle la table. Tout autre chemin protégé reste refusé, comme ci-dessus.
