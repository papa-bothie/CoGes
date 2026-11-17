# Sur site, lot 1 — L'assemblage : CoGes démarre sur http://localhost

> **STATUT : PRÊT À LANCER** (16 novembre 2026). Premier des six lots de l'installation sur site. Seul prérequis : `main` à jour (PR #91 fusionnée).

Branche `feat/sur-site-assemblage`, depuis `main` à jour. Une seule PR.

## Le plan d'ensemble (six lots)

| Lot | Contenu | Résultat attendu |
|---|---|---|
| **1 (ce prompt)** | Assemblage sur site : compose, Caddyfile, réglages, contrôle, migrations locales | CoGes démarre sur `http://localhost` |
| 2 | Commande `activate-license` et premier démarrage | Une société créée, licence activée |
| 3 | Script d'installation Windows | Installation en une commande |
| 4 | Sauvegarde et restauration locales | Une panne simulée, données retrouvées |
| 5 | Mises à jour à distance et retour arrière | Passage d'une version à la suivante sans se déplacer |
| 6 | Support à distance et journaux | Intervention sans se déplacer |

## Décisions déjà prises

- **Cas visé** : un client, une société, un seul PC fixe sous Windows 11 64 bits, 8 Go de RAM. Pas de téléphone, pas d'accès depuis le réseau du magasin : le navigateur du PC ouvre `http://localhost`.
- **Règle d'or : ajouter, ne rien modifier.** Tout va dans un nouveau dossier `deploy/onprem/`. Les fichiers du VPS, le code de l'application et les migrations ne changent pas : les utilisateurs actuels ne voient aucune différence. Un contrôle automatique de la CI le vérifie (bloc F).
- **Licence** (lot 2) : un abonnement `active` posé à l'installation, sans date de fin. Dans ce lot 1, l'essai de 30 jours démarre comme d'habitude ; c'est attendu.
- **Images** : téléchargées depuis le registre GitHub (`ghcr.io/papa-bothie/coges`), les mêmes que la production. Elles sont **publiques** : aucun compte ni jeton sur le PC du client.
- **Mises à jour à distance** (lot 5) : elles devront être possibles sans se déplacer. Le lot 1 prépare le terrain (bloc E) : une seule variable de version, réglages et données séparés des fichiers remplaçables, et uniquement des connexions sortantes (aucun port ouvert vers l'extérieur sur le PC ou la box du client).
- **Services facultatifs** (photos, e-mails, notifications, Sentry, pings) : tous éteints pour ce lot.
- **Mot de passe « propriétaire » de la base** : il vit sur le PC du client, car les migrations se lancent sur place. Exception assumée à la règle de production, limitée au mode sur site, et jamais donnée aux services qui tournent en continu.
- **Administration de la plateforme** : absente chez le client (ni application admin, ni Cloudflare).
- **Fusionner ne déploie rien** : la production ne se déploie que sur une étiquette `vX.Y.Z` ou à la main. Ce lot n'ajoute rien aux images : le prochain déploiement de production sera identique à ce qu'il aurait été sans lui.

## Prompt à donner à l'agent

```
Lot « Sur site 1 : assemblage » (branche feat/sur-site-assemblage, depuis main à jour).
Règles habituelles : ADR au prochain numéro libre, tests d'abord (rouge puis vert), aucun
service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod, backend/.vercel/ ni
/etc/coges/*. Résumé en français à la fin, questions ouvertes par AskUserQuestion.

But : qu'un PC Windows 11 (8 Go de RAM, Docker Desktop avec WSL2) fasse tourner CoGes en
entier, base comprise, sur http://localhost, sans Neon, sans nom de domaine, sans aucun
service externe. Un client, une société, un seul poste : le navigateur du PC lui-même.

Lis d'abord : docs/prompt-sur-site/01-assemblage.md (ce lot), deploy/vps/docker-compose.yml,
deploy/vps/Caddyfile, deploy/vps/coges.env.example, deploy/scripts/check_runtime_env.py et
ses tests, deploy/postgres/init/01-roles.sql, docker-compose.yml (racine),
backend/Dockerfile.worker, backend/Dockerfile.api, frontend/Dockerfile,
frontend/next.config.ts, backend/app/core/config.py, backend/app/modules/auth/router.py
(cookie), backend/app/cli.py (create-company), backend/app/workers/beat.py,
.github/workflows/ci.yml (job `vps`), .github/workflows/deploy.yml (lecture seule),
docs/runbooks/vps.md, les ADR 0040, 0042, 0083, 0088, 0091, 0122.

Principes non négociables
- AJOUTER, NE RIEN MODIFIER. Tout le lot vit dans deploy/onprem/ (plus un job de CI, des
  tests et de la documentation). Chemins protégés, à ne modifier sous aucun prétexte :
  deploy/vps/**, deploy/scripts/**, deploy/postgres/**, deploy/sql/**, docker-compose.yml
  (racine), backend/app/**, backend/migrations/**, backend/Dockerfile.*, backend/pyproject.toml,
  backend/uv.lock, frontend/**, frontend-admin/**, .github/workflows/deploy.yml,
  .github/workflows/backup*.yml. Si un changement d'un de ces chemins te semble nécessaire,
  ARRÊTE-TOI et demande-le-moi avec la raison : c'est ce qui protège les utilisateurs actuels.
- Aucune migration nouvelle. Aucune dépendance ajoutée aux images.
- Les mêmes images que la production (front, api, worker), au même registre public
  (COGES_IMAGE_REGISTRY, COGES_IMAGE_TAG obligatoire). Pas d'image admin, pas de bundle,
  aucune connexion au registre (docker login) dans la procédure.
- Le DSN de coges_owner n'est donné qu'au service ponctuel de migration, jamais à api, worker,
  beat ni relay.
- Hors lot (ne pas faire) : commande activate-license, script d'installation Windows,
  sauvegarde, automatisation des mises à jour, accès à distance. L'essai de 30 jours démarre
  donc normalement.

BLOC A — deploy/onprem/docker-compose.yml
- Services : postgres, redis, api, worker, beat, relay, front, caddy, autoheal. Ni admin ni
  cloudflared. Reprends du compose du VPS les réglages éprouvés (journaux bornés,
  no-new-privileges, healthchecks, stop_grace_period, commandes Redis renommées, noeviction,
  restart: unless-stopped) ; ne recopie pas ce qui ne sert qu'au VPS (profils edge et tunnel,
  réseau externe coges_edge partagé avec la préproduction, alias de pile).
- postgres : image postgres:18 figée sur la même version majeure que la production (ADR 0095),
  volume nommé, AUCUN port publié (réseau interne seulement), healthcheck pg_isready sur la
  base coges. Rôles créés au premier démarrage par un script d'amorçage propre au sur site
  (deploy/onprem/postgres-init/) : les mêmes rôles et les mêmes GRANT que 01-roles.sql, mais
  la seule base `coges` (ni coges_test ni coges_e2e). Mots de passe lus dans l'environnement,
  aucun défaut du type change-me. Un test compare la liste des rôles et de leurs attributs
  avec 01-roles.sql : si l'un change sans l'autre, la CI échoue.
- Caddy publie UN port, sur la boucle locale seulement : 127.0.0.1:${COGES_HTTP_PORT:-80}:80.
  Rien n'est joignable depuis le réseau du magasin. Aucun autre service ne publie de port.
- Réseau : un sous-réseau fixe distinct de ceux du VPS ; l'API ne croit X-Forwarded-For que
  venu de ce sous-réseau (COGES_FORWARDED_ALLOW_IPS, COGES_TRUST_PROXY_HEADERS=true).
- Réglages de l'application : COGES_ENV=production (cookies Secure, secrets réels exigés,
  documentation de l'API fermée), COGES_DB_POOLER=none, DSN vers l'hôte `postgres` sans
  sslmode, COGES_CORS_ORIGINS et COGES_MERCHANT_URL = http://localhost (avec le port s'il
  n'est pas 80), COGES_API_URL=http://api:8000 pour le front (ADR 0122),
  COGES_SIGNUP_ENABLED=false. SMTP, VAPID, Cloudinary, Sentry, pings, Cloudflare Access :
  vides. COGES_DATABASE_URL_PLATFORM et COGES_MFA_ENCRYPTION_KEY restent fournis (la tâche de
  nuit des abonnements et le lot 2 en ont besoin).
- Mémoire : Docker Desktop ne donne par défaut que la moitié de la RAM du PC (4 Go sur 8).
  Le total des plafonds (mem_limit), PostgreSQL compris, doit tenir sous 3 Go. Pistes :
  COGES_API_WORKERS=1, worker en --concurrency=1, Redis à 128 Mo de maxmemory, PostgreSQL
  avec shared_buffers modestes. Donne dans le résumé le tableau plafond / consommation
  mesurée (docker stats) au repos et pendant une vente.
- Service ponctuel `migrate` (profil `tools`, jamais lancé par `up`) : image worker, commande
  `alembic upgrade head`, seul service à recevoir COGES_DATABASE_URL_OWNER, dépend de postgres
  en bonne santé. Vérifie qu'alembic est bien dans l'image worker ; sinon ARRÊTE-TOI.
- Service ponctuel `cli` (profil `tools`) : image worker, `python -m app.cli`, pour
  create-company. Il ne reçoit pas le DSN propriétaire.

BLOC B — deploy/onprem/Caddyfile
- Un seul site : http://localhost, HTTPS automatique coupé (aucun certificat, aucun appel à
  Let's Encrypt, rien qui sorte du PC). /api/v1/platform/* répond 404 ; /api/v1/* va à l'API ;
  le reste au front. Mêmes en-têtes de sécurité que le VPS sauf HSTS, même filtre des
  journaux (ni chaîne de requête, ni cookie, ni jeton), même page de maintenance sur 502,
  503 et 504, même plafond de corps de requête.

BLOC C — Réglages et contrôle
- deploy/onprem/coges.env.example : le modèle, commenté en français simple, valeurs vides.
  Une section « à remplir », une section « ne pas toucher ». Mots de passe en hexadécimal
  seulement (ni $ ni #). Le runbook donne la commande PowerShell qui en tire un.
- deploy/onprem/check_onprem_env.py (bibliothèque standard seulement, comme
  check_runtime_env.py, dont il peut importer des fonctions SANS le modifier). Il refuse, avec
  un message en français qui dit quoi corriger : un secret de moins de 32 caractères ou resté
  à sa valeur de modèle ; un DSN d'exécution qui ne désigne pas son rôle attendu (liste
  blanche de l'ADR 0088) ; le DSN propriétaire présent dans l'environnement d'un service
  continu ; une URL Redis hors du réseau interne ; COGES_ENV autre que production ; une
  étiquette d'image vide ou `latest` ; des réglages facultatifs à moitié posés (VAPID,
  Cloudinary). Il n'exige ni Neon, ni sslmode, ni domaine public.
- Garde-fou « jamais la production » : le contrôle refuse tout DSN dont l'hôte n'est pas
  `postgres`, et toute valeur qui contient `neon.tech`, le domaine de production ou une
  adresse Redis externe. Une installation sur site ne peut donc pas, même par erreur de
  copier-coller, se brancher sur la base ou les services des utilisateurs actuels.
- Fins de ligne : un fichier deploy/onprem/.gitattributes (dans CE dossier, pas à la racine,
  pour ne renormaliser aucun autre fichier du dépôt) impose LF. Un script ou un fichier
  d'environnement en CRLF, extrait sous Windows, casse le conteneur. Un test le vérifie.

BLOC D — Vérifications dans la CI (nouveau job `onprem`, sans toucher au job `vps`)
- Compose valide (`docker compose config --quiet`) et Caddyfile valide (`caddy validate`).
- Démarrage réel sur le runner avec les images construites par la CI : `up`, puis `migrate`,
  puis `create-company` par le service `cli`. Ensuite :
  * tous les conteneurs sont « healthy » ;
  * http://localhost répond, /api/v1/health répond, /api/v1/platform/ répond 404 ;
  * aucun port autre que celui de Caddy n'est publié, et il l'est sur 127.0.0.1 ;
  * un parcours Playwright sous Chromium se connecte sur http://localhost avec le gérant
    créé, recharge la page et reste connecté (preuve que le cookie Secure est accepté sur
    localhost), puis enregistre une vente simple ;
  * le service worker de l'application s'enregistre sur http://localhost ;
  * aucune requête réseau ne sort vers l'extérieur pendant le parcours (ni depuis le
    navigateur, ni depuis les conteneurs : réseau du compose sans sortie pour ce test, ou
    contrôle équivalent que tu justifies) ;
  * après un déclenchement manuel des tâches de beat, les journaux de worker, beat et relay
    ne contiennent aucune erreur due aux réglages vides.
- Redémarrage : `down` puis `up` (sans -v) retrouve la société et la vente ; un `docker
  kill` de postgres en pleine marche est suivi d'un retour à l'état sain sans intervention.
- Garde le job raisonnable (vise moins de dix minutes) ; il ne tourne pas sur `schedule`.

BLOC E — Prêt pour la mise à jour à distance (le lot 5 l'automatisera ; ici, on ne ferme
aucune porte)
- Trois endroits bien séparés, et documentés comme tels :
  1. les fichiers remplaçables (tout deploy/onprem/ : compose, Caddyfile, scripts) ;
  2. les réglages du client (coges.env), rangés HORS de ce dossier, jamais écrasés ;
  3. les données (volumes nommés de PostgreSQL, Redis, artefacts ML, fichiers statiques).
  Remplacer (1) par une version plus récente ne touche jamais (2) ni (3). Le compose lit les
  réglages par --env-file, à un chemin passé en argument.
- Une seule variable décide de la version : COGES_IMAGE_TAG. Mettre à jour à la main, c'est :
  changer l'étiquette, `pull`, arrêter api/worker/beat/relay/front, `migrate`, `up`. Écris
  cette procédure dans le runbook (« Mettre à jour à la main ») et son retour arrière
  (remettre l'ancienne étiquette ; préciser qu'une migration déjà jouée ne se défait pas
  sans sauvegarde, sujet du lot 4).
- Test dans la CI : rejouer `migrate` une seconde fois ne change rien ; relancer `up` après
  un `pull` recrée les conteneurs et retrouve les données.
- Dossier autonome : deploy/onprem/ ne référence aucun fichier hors de lui-même (la page de
  maintenance y est copiée ; un test vérifie qu'elle reste identique à celle du VPS). Le
  lot 5 pourra ainsi le publier tel quel comme archive versionnée.
- Sorties seulement : la procédure n'ouvre aucun port entrant sur le PC ni sur la box du
  client. Tout ce dont une mise à jour a besoin passe par des connexions SORTANTES vers le
  registre public. Note dans l'ADR que la mise à jour à distance du lot 5 (à la demande par
  une session de support, ou vérification automatique d'une nouvelle version) reposera sur
  ce principe.
- Version installée lisible : le runbook donne la commande qui l'affiche (étiquette des
  images en cours d'exécution).

BLOC F — Garde-fous pour les utilisateurs actuels
- Contrôle automatique des chemins protégés : deploy/onprem/check_protected_paths.py
  (bibliothèque standard), lancé par le job `onprem` sur les pull requests dont la branche
  commence par `feat/sur-site-`. Il compare la PR à sa branche de base et ÉCHOUE si un chemin
  protégé (liste des principes ci-dessus) est modifié, en nommant le fichier. Les autres
  branches ne sont pas concernées : le développement habituel n'est pas gêné. Tests : une
  modification de deploy/vps/Caddyfile est refusée ; un ajout dans deploy/onprem/ passe.
- Le job `vps` et les tests existants de check_runtime_env.py restent verts SANS aucune
  modification : c'est la preuve que la production n'est pas touchée.
- Vérifie et écris dans le résumé : (a) deploy/vps/Dockerfile.bundle n'embarque aucun
  fichier de deploy/onprem/ ; (b) les contextes de construction des images (backend/,
  frontend/, frontend-admin/) sont inchangés, donc les images de production sont identiques ;
  (c) deploy.yml ne se déclenche que sur une étiquette vX.Y.Z ou à la main, donc la fusion
  ne déploie rien.
- Le nouveau job `onprem` est indépendant : son échec bloque la fusion d'une PR sur site,
  jamais un déploiement de production.
- Règle pour les lots suivants (à écrire dans l'ADR) : tout changement du code de
  l'application passera par un interrupteur éteint par défaut, avec un test qui prouve que,
  sans lui, le comportement est identique à aujourd'hui.

Tests (rouge d'abord)
- check_onprem_env.py : un cas par refus listé au bloc C (dont neon.tech et un hôte autre
  que `postgres`), plus le modèle rempli correctement qui passe.
- check_protected_paths.py : les deux cas du bloc F.
- Architecture : aucun service continu du compose sur site ne reçoit COGES_DATABASE_URL_OWNER ;
  parité des rôles avec 01-roles.sql ; mêmes noms d'images que le compose du VPS ; aucun port
  publié hors 127.0.0.1 ; fins de ligne LF ; dossier autonome.

Documentation
- docs/runbooks/sur-site.md, écrit pour quelqu'un qui débute, commandes PowerShell :
  prérequis (Windows 11 64 bits, 8 Go, virtualisation activée, Docker Desktop avec WSL2),
  où ranger les trois endroits du bloc E, remplir le fichier de réglages, lancer le contrôle,
  télécharger les images, démarrer, migrer, créer la société, ouvrir http://localhost,
  arrêter, redémarrer, lire les journaux, afficher la version, mettre à jour à la main,
  que faire si le port 80 est déjà pris. Une section « Ce qui n'existe pas encore » renvoie
  aux lots 2 à 6.
- ADR : pourquoi un assemblage à part plutôt qu'un profil du compose du VPS ; l'exception du
  DSN propriétaire sur le poste et ses garde-fous ; COGES_ENV=production sur http://localhost
  et le cookie Secure ; la boucle locale seule ; le budget mémoire ; ce qui est éteint ; les
  trois endroits et le principe « sorties seulement » ; les garde-fous du bloc F.
- docs/prompt-sur-site/README.md : la table des six lots et leur état. deploy/README-infra.md
  et la table des ADR à jour.

Tu ne peux pas tester sous Windows : termine le résumé par la liste précise de ce qui reste à
vérifier sur la machine Windows (Docker Desktop, WSL2, montage des fichiers, autoheal et le
socket Docker, port 80, navigateur Edge ou Chrome, redémarrage du PC).

Fin de lot : suite complète verte, jobs `vps` et `onprem` verts, PR ouverte.
```

## Ce que le propriétaire fait ensuite

1. **Préparer la machine Windows** : activer la virtualisation si besoin, installer Docker Desktop avec WSL2. Docker Desktop est gratuit pour les petites entreprises ; vérifier les conditions sur le site de Docker avant de l'installer chez un client.
2. **Suivre le runbook** `docs/runbooks/sur-site.md` produit par le lot : remplir les réglages, démarrer, migrer, créer une société de test, ouvrir `http://localhost`.
3. **Vérifier sur Windows** la liste que l'agent donne en fin de résumé, puis rapporter : ce qui marche, les messages d'erreur, et la mémoire utilisée (onglet de Docker Desktop).
4. **Essayer une mise à jour à la main** avec la procédure du runbook, pour valider le principe avant le lot 5.
5. Ne rien déployer en production pour ce lot : il n'y a rien à déployer, le lot n'ajoute que des fichiers à côté.
