# Prompt 18 — Tout CoGes sur le VPS (sauf la base) : installation et guide d'intervention

À lancer après les prompts 16 (lot A) et 17 (surveillance des workers).

Décision du propriétaire (2026-10-17) : on quitte Vercel. L'offre gratuite Hobby est réservée à un usage non commercial, et l'offre payante n'est pas retenue. Le front Next.js et l'API FastAPI rejoignent Redis, le worker, beat et le relais sur un VPS Infomaniak non géré (Suisse). PostgreSQL reste chez Neon (offre payante, Francfort).

```
Tout CoGes sur le VPS, sauf la base — installation, déploiement et guide d'intervention
(branche feat/vps-production, depuis main à jour, après les prompts 16 et 17).

Contexte décidé par le propriétaire :
- On quitte Vercel (front ET API) : l'offre Hobby interdit l'usage commercial.
- Un VPS non géré Infomaniak VPS Lite (Suisse, Ubuntu 24.04 LTS) porte : Caddy, front
  Next.js, API FastAPI, Redis, worker Celery, beat, relais. 4 Go de RAM au minimum,
  8 Go recommandés : règle les limites de mémoire pour que tout tienne dans 4 Go avec
  2 Go de swap, et dis-moi ce qui est juste.
- PostgreSQL reste chez Neon (Francfort, sslmode=require). Rien de la base sur le VPS.
- Un seul nom de domaine public (COGES_DOMAIN, que je fournis), HTTPS obligatoire.
- Écris une ADR (prochain numéro libre) qui remplace les ADR 0040 (hébergeurs) et la
  partie Vercel de l'ADR 0047, en gardant le principe « même origine » : le navigateur
  ne voit qu'un domaine, /api/v1/* va à l'API.

Règles de sécurité (non négociables) :
- Tu ne te connectes jamais au VPS et tu n'as aucune clé : tu écris les fichiers, c'est
  moi qui les lance. Aucun secret dans git ; tout est lu depuis /etc/coges/coges.env que
  je dépose moi-même (modèle versionné deploy/vps/coges.env.example, valeurs vides).
- Le DSN propriétaire (coges_owner) n'est JAMAIS sur le VPS (garde-fou 2 de l'ADR 0042) :
  les migrations restent dans le job GitHub Actions.
- Aucun service payant ouvert, aucun compte créé à ma place.

1. Images Docker (non-root, versions figées, multi-étapes)
   - frontend/Dockerfile : Next.js en `output: "standalone"`, Node LTS figé. Garde la
     réécriture /api/v1 de next.config.ts pour le développement ; en production c'est
     Caddy qui envoie /api/v1/* directement à l'API (un saut de moins). Retire la
     dépendance à la variable VERCEL dans next.config.ts.
   - backend/Dockerfile.api : uvicorn (2 processus pour commencer), `--proxy-headers`
     limité au réseau Docker ; COGES_TRUST_PROXY_HEADERS=true. Vérifie que l'IP du client
     utilisée par la limitation de débit (lot A) est bien celle que Caddy transmet, et
     qu'un client ne peut pas la falsifier en envoyant son propre X-Forwarded-For (test).
   - Dockerfile.worker existant pour worker, beat, relais.

2. deploy/vps/docker-compose.yml
   - caddy : seul service exposé (80 et 443). Certificat Let's Encrypt automatique pour
     COGES_DOMAIN, redirection HTTP -> HTTPS, HSTS, compression, en-têtes de sécurité
     repris de next.config.ts, /api/v1/* -> api:8000, le reste -> front:3000, logs
     d'accès sans corps de requête ni cookie.
   - front, api, worker, beat (un seul exemplaire), relay, redis.
   - redis : réseau Docker interne seulement (aucun port publié, donc pas de TLS
     nécessaire), mot de passe, commandes dangereuses interdites, maxmemory adapté
     (512 Mo de départ) et maxmemory-policy noeviction, appendonly yes, volume.
   - healthchecks et autoheal du prompt 17 ; limites de mémoire par service ; rotation
     des logs ; restart unless-stopped.

3. deploy/vps/bootstrap.sh (bash, set -euo pipefail, idempotent, --dry-run, shellcheck
   propre) :
   - fuseau UTC, locale, nom de machine ;
   - utilisateur `coges` (sudo), SSH par clé seulement (PasswordAuthentication no,
     PermitRootLogin no, port configurable) ; le script REFUSE de couper le mot de passe
     si aucune clé n'est dans ~coges/.ssh/authorized_keys ;
   - ufw : tout fermé en entrée sauf SSH, 80 et 443 ;
   - fail2ban sur SSH ;
   - unattended-upgrades (sécurité seulement, redémarrage automatique à 04 h 30 UTC si
     nécessaire, hors des tâches de nuit de beat.py) ;
   - 2 Go de swap, vm.swappiness=10, vm.overcommit_memory=1 (Redis) ;
   - Docker Engine + plugin compose depuis le dépôt officiel, versions notées ;
   - limites de journald.

4. Images et registre
   - Les images front, api et worker sont construites dans GitHub Actions (jamais sur le
     VPS : un build Next.js prendrait la mémoire de la production), étiquetées avec la
     version (vX.Y.Z) et le SHA du commit, puis poussées sur GitHub Container Registry
     (ghcr.io, privé). Garde seulement les 5 dernières versions (nettoyage automatique) ;
     indique la taille des images et si le quota gratuit de GitHub suffit.

5. Pipeline CI/CD sans Vercel (.github/workflows/ci.yml et deploy.yml)
   - CI inchangée sur chaque PR et sur main (lint, tests, front-check, analyses du lot A),
     plus le build des trois images (sans les pousser) pour détecter un Dockerfile cassé.
   - CD déclenchée À LA MAIN (workflow_dispatch « Déployer », choix preprod ou
     production, version) ou par un tag vX.Y.Z pour la préproduction seulement :
       a. build et push des images sur ghcr.io ;
       b. migrations Alembic contre Neon avec le DSN propriétaire (secret GitHub
          d'environnement, jamais sur le VPS). Règle : migrations compatibles avec la
          version précédente du code (on ajoute d'abord, on supprime à la version
          suivante), pour pouvoir revenir en arrière sans toucher la base ;
       c. déploiement sur le VPS par SSH avec une clé DÉDIÉE et BRIDÉE : utilisateur
          `deploy` sans sudo, clé limitée dans authorized_keys par
          command="/opt/coges/deploy.sh",no-port-forwarding,no-pty, et IP source si
          possible. Cette clé ne peut que lancer deploy.sh <version>. La clé privée va
          dans les secrets GitHub ; c'est moi qui la crée et l'y dépose ;
       d. deploy.sh : docker login ghcr (jeton en lecture seule), pull de la version,
          `docker compose up -d`, vérification (/api/v1/health/ready et /login via
          Caddy), retour automatique à la version précédente si elle échoue, journal
          des déploiements dans /var/log/coges/deploy.log ;
       e. smoke test (deploy/scripts/smoke.py) contre https://COGES_DOMAIN ; en cas
          d'échec : retour à la version précédente et job en rouge.
   - Retire toutes les étapes Vercel, le CLI vercel et VERCEL_TOKEN des workflows.
   - check_runtime_env.py : remplace --require-vercel par --require-vps (DSN Neon avec
     sslmode=require, pas de DSN propriétaire sur le VPS, Redis interne, COGES_DOMAIN en
     https).
   - Tant que la clé de déploiement n'existe pas, le job s'arrête après les migrations
     et affiche la commande deploy.sh à lancer à la main : le pipeline doit marcher
     dans les deux modes.
   - Documente le pipeline dans docs/runbooks/deploiement.md (schéma, qui fait quoi,
     comment revenir en arrière, que faire si une migration échoue).

6. deploy/vps/check.sh : bilan en une commande (disque, RAM, swap, conteneurs et leur
   santé, date d'expiration du certificat, mises à jour en attente, échecs fail2ban,
   latence vers Neon, réponse de https://COGES_DOMAIN/api/v1/health/ready).

7. Guide d'intervention docs/runbooks/vps.md, en français simple. Pour chaque cas : ce
   qu'on voit, ce que ça change pour les commerçants, les commandes exactes, quand c'est
   urgent :
   - le site ne répond plus (Caddy, front ou API) ; le VPS ne répond plus (console de
     secours Infomaniak) ;
   - certificat non renouvelé ;
   - un conteneur redémarre en boucle ; worker bloqué ; outbox en retard ;
   - disque plein ; mémoire saturée (processus tué) ;
   - Redis perdu (file et cache seulement, la base est chez Neon : repartir à vide) ;
   - Neon injoignable ;
   - revenir à la version précédente ;
   - soupçon de piratage (couper, changer TOUS les secrets : JWT, Redis, Neon, Sentry ;
     reconstruire un VPS neuf plutôt que nettoyer) ;
   - reconstruire le VPS de zéro en moins de 30 minutes (pas à pas) ;
   - routine mensuelle (environ 1 h).

8. Préproduction : un second projet compose sur le même VPS (sous-domaine
   preprod.COGES_DOMAIN, branche Neon de préproduction), ARRÊTÉ par défaut et lancé à la
   demande, pour ne pas prendre la mémoire de la production. Décris-le dans l'ADR.

9. Vérification avant livraison : shellcheck ; build des trois images ; la pile
   complète lancée en local avec docker compose (domaine local, certificat interne de
   Caddy) et la suite e2e passée contre elle ; essai de bootstrap.sh dans une machine
   virtuelle Ubuntu 24.04 si l'outil est disponible, sinon dis-le clairement. Mets à
   jour README-infra.md (tableau des composants), CLAUDE.md et le README du dépôt.
```

## Ce que le propriétaire fait lui-même

1. Commander le VPS Infomaniak (8 Go de RAM recommandés) et choisir Ubuntu 24.04 LTS.
2. Acheter un nom de domaine et le faire pointer vers l'IP du VPS (enregistrement A).
3. Passer Neon sur une offre payante (base de production, PITR).
4. Déposer sa clé SSH publique, puis `/etc/coges/coges.env` (secrets) sur le VPS.
5. Lancer `bootstrap.sh`, puis un premier `deploy.sh` à la main, en suivant le guide.
6. Plus tard, pour le déploiement automatique : créer la clé SSH bridée de l'utilisateur
   `deploy` et un jeton GitHub en lecture seule des images, et les déposer dans les
   secrets GitHub (environnement `production`).
7. Une fois la production stable, supprimer les projets Vercel et leurs variables.
8. Garder les secrets dans un gestionnaire de mots de passe, jamais dans git.
