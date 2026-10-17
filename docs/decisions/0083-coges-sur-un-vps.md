# 0083 — CoGes sur un VPS, sauf la base

- **Date** : 2026-10-17
- **Phase** : prompt 18 (après les lots 16 et 17)
- **Statut** : acceptée — **remplace l'ADR 0040** (hébergeurs) et **la partie Vercel de
  l'ADR 0047** (le principe « même origine » est gardé) ; rend caduques les parties Vercel
  des ADR 0044 et 0058
- **Décideur** : propriétaire (choix d'hébergement), options recommandées appliquées pour
  le reste (consigne du 2026-10-17 : « choisis les options recommandées »)

## Contexte

L'offre gratuite Hobby de Vercel est réservée à un usage non commercial, et l'offre
payante n'est pas retenue. Le propriétaire a décidé de quitter Vercel (front **et** API)
pour un VPS Infomaniak VPS Lite non géré (Suisse, Ubuntu 24.04 LTS), qui porte aussi
Redis, le worker, beat et le relais. PostgreSQL reste chez Neon (Francfort, offre payante,
`sslmode=require`) : rien de la base n'est sur le VPS.

## Décision

**Pile** (`deploy/vps/docker-compose.yml`) : Caddy (seul service exposé, 80 et 443),
front Next.js (`output: "standalone"`), API FastAPI (uvicorn, 2 processus), worker, beat
(un seul), relais, Redis, autoheal. Un seul domaine public (`COGES_DOMAIN`) en HTTPS :
Caddy envoie `/api/v1/*` directement à l'API (un saut de moins) et le reste au front. La
réécriture de `next.config.ts` reste pour le développement et les e2e, et ne dépend plus
de la variable `VERCEL`.

**Réseaux** : `coges_edge` (externe, 172.30.0.0/24, créé par `deploy.sh`) pour Caddy, le
front et l'API des deux piles ; `data` (interne, sans sortie) pour Redis ; `jobs` pour la
sortie des workers vers Neon et Sentry. Redis n'a aucun port publié : pas de TLS, mot de
passe obligatoire, `FLUSHALL`, `FLUSHDB`, `CONFIG`, `DEBUG`, `SHUTDOWN`, `MODULE` désactivés,
`maxmemory 512mb`, `noeviction`, `appendonly yes`.

**Adresse du client** : Caddy n'a aucun `trusted_proxies`, donc ignore le
`X-Forwarded-For` du client et transmet l'adresse du pair TCP. L'API lit désormais
l'entrée **la plus à droite** de l'en-tête (`app/core/deps.py`), celle de notre proxy :
un client qui envoie son propre en-tête ne change pas son compteur (test
`test_a_forged_forwarded_for_does_not_escape_the_ip_limit`, et vérifié sur la pile
locale : 6ᵉ connexion refusée en 429 malgré une fausse adresse différente à chaque
requête). uvicorn `--proxy-headers --forwarded-allow-ips 172.30.0.0/24`.

**Images** : front, API, worker, plus un **bundle** (image `scratch` de 52 ko qui
transporte le compose, le Caddyfile et `check_runtime_env.py` de la version). Construites
dans GitHub Actions (jamais sur le VPS), étiquetées `vX.Y.Z` (ou SHA court) et SHA
complet, poussées sur `ghcr.io/papa-bothie/coges/*` (privé). Non root, versions figées
(`node:22.23.3-bookworm-slim`, `python:3.12.11-slim-bookworm`, `caddy:2.10.2-alpine`,
`redis:7.4.2-alpine`, `willfarrell/autoheal:1.2.0`). Revenir à une version ramène aussi
la configuration qui allait avec elle.

**Pipeline** :
- la CI tourne sur chaque push (`main` compris) et chaque PR, plus un job `vps`
  (shellcheck, Caddyfile validé par Caddy, compose validé, quatre images construites sans
  push) ;
- le déploiement (`deploy.yml`, « Déployer ») part **à la main** (préprod ou
  production, version) ou d'un tag `vX.Y.Z` (préprod seulement) : CI, images, migrations
  sous `coges_owner` depuis le job (le DSN propriétaire n'est jamais sur le VPS), puis
  `deploy.sh` par SSH avec une **clé bridée** (`command="/opt/coges/deploy.sh"`), test de
  fumée, retour à la version précédente si le test échoue ;
- sans clé de déploiement, le job s'arrête après les migrations et affiche la commande ;
- **règle des migrations** : compatibles avec la version précédente du code (ajouter
  d'abord, supprimer à la version suivante), pour revenir en arrière sans toucher la base.

**`deploy.sh`** (root:root, 0755, non modifiable par `deploy`) : arguments validés mot par
mot (y compris depuis `SSH_ORIGINAL_COMMAND`), verrou, contrôle du fichier de secrets
(`check_runtime_env.py --require-vps` : aucun DSN propriétaire, Neon en `sslmode=require`,
Redis interne, domaine nu en HTTPS, secrets de 32 caractères au moins), pull, `up -d`,
vérification **par Caddy** (`/api/v1/health/ready` puis `/login`), retour automatique,
journal `/var/log/coges/deploy.log`.

**Préproduction** : second projet compose (`coges-preprod`) sur le même VPS, même fichier
compose sans le profil `edge`, sous-domaine `preprod.<COGES_DOMAIN>` servi par le même
Caddy, branche Neon de préproduction, `/etc/coges/preprod.env`. **Arrêtée par défaut**,
lancée à la demande (`deploy.sh preprod <version>`), arrêtée par `deploy.sh preprod stop`.

**Mémoire** (VPS de 4 Go + 2 Go de swap) : plafonds Caddy 128 Mo, front 320 Mo, API
700 Mo, worker 900 Mo, beat 200 Mo, relais 200 Mo, Redis 640 Mo, autoheal 32 Mo, soit
≈ 3,1 Go pour la production. Ça tient en 4 Go, sans marge pour la préprod (≈ 2,6 Go de
plus) ni pour une montée du ML : **8 Go recommandés** ; sur 4 Go, ne lancer la préprod
que le temps d'un essai.

**Système** (`bootstrap.sh`, idempotent, `--dry-run`) : UTC, utilisateurs `coges` (sudo)
et `deploy` (sans sudo), SSH par clé seulement (refus si aucune clé n'est déposée), ufw
(SSH, 80, 443), fail2ban, mises à jour de sécurité automatiques, 2 Go de swap,
`vm.swappiness=10`, `vm.overcommit_memory=1`, Docker depuis le dépôt officiel, journald
borné.

## Écarts au prompt, assumés

- **Redémarrage automatique à 05 h 15 UTC**, pas 04 h 30 : 04 h 30 est l'heure de
  `ml-infer` dans `beat.py`. 05 h 15 tombe entre la fin des tâches de nuit et le scan des
  dettes de 06 h 00.
- **Quatre images au lieu de trois** : le bundle de configuration, pour que retour arrière
  et configuration restent liés.
- **`deploy` est dans le groupe `docker`** : c'est un droit de root en pratique. La
  protection tient à la clé bridée (elle ne lance que `deploy.sh`, qui valide ses
  arguments) ; documenté dans le guide.
- `backend/vercel.json`, `backend/api/index.py` et `requirements.txt` restent jusqu'à la
  suppression des projets Vercel par le propriétaire (la préproduction actuelle y vit
  encore) : plus aucun workflow ne les déploie.

## Registre : taille et quota

Taille compressée d'une version : front ≈ 89 Mo, API ≈ 78 Mo, worker ≈ 295 Mo, bundle
52 ko, soit ≈ 460 Mo ; les couches de base sont partagées entre versions, et une version
de plus coûte surtout ses couches applicatives (quelques dizaines de Mo). Cinq versions :
≈ 0,7 Go. **Le quota gratuit de GitHub pour un dépôt privé (500 Mo de paquets) ne suffit
pas.** Options : GitHub Pro (2 Go), ou ne garder que 2 versions (`min-versions-to-keep`),
ou un registre ailleurs. Le transfert vers GitHub Actions est gratuit ; celui vers le VPS
compte dans le quota de transfert (1 Go par mois en Free).

## Vérifications faites

- shellcheck propre (`deploy/vps/*.sh`, `deploy/scripts/*.sh`) ; Caddyfile validé et
  formaté par Caddy 2.10.2 ; compose validé.
- Images front, API et bundle construites en local ; le worker n'a pas été reconstruit sur
  le poste (2,9 Go libres) : l'image existante a servi à l'essai, la CI le construit.
- Pile complète lancée en local (`localhost`, certificat interne de Caddy, ports 8080 et
  8443, base `coges_e2e` de l'hôte) : tous les services `healthy`, `/health/ready` en 200,
  HTTP → HTTPS en 308, en-têtes de sécurité présents, cookies et jetons absents du
  journal de Caddy, `FLUSHALL` refusé par Redis, adresse forgée sans effet ; suite e2e
  Playwright passée contre elle (`E2E_BASE_URL=https://localhost:8443`).
- **`bootstrap.sh` n'a pas été essayé dans une machine virtuelle** Ubuntu 24.04 : qemu est
  présent mais le poste n'a plus l'espace disque nécessaire. Son mode `--dry-run` a tourné
  dans un conteneur `ubuntu:24.04` (tests `test_vps_scripts.py`). Premier passage réel :
  sur le VPS, en suivant `docs/runbooks/vps.md`, une console de secours Infomaniak ouverte.

## Conséquences

- Plus de déploiement à chaque push sur `main` : on déploie quand on veut, par un tag
  (préprod) ou à la main.
- Secrets GitHub à créer par le propriétaire : `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`,
  variables `DEPLOY_HOST`, `DEPLOY_PORT`, `COGES_PUBLIC_URL`. Les secrets Vercel
  deviennent inutiles.
- Guides : `docs/runbooks/deploiement.md` (pipeline) et `docs/runbooks/vps.md`
  (intervention).
