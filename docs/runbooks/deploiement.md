# Déployer CoGes — le pipeline (ADR 0083)

CoGes tourne sur un VPS Infomaniak (Caddy, front, API, Redis, worker, beat, relais) ; la
base est chez Neon. Plus rien ne passe par Vercel. Ce guide dit qui fait quoi quand on
déploie, comment revenir en arrière, et que faire si une migration échoue. Pour
l'intervention sur la machine elle-même : `docs/runbooks/vps.md`.

## Le chemin d'une version

```
 poste ──git push──▶ GitHub ──CI verte──▶ « Déployer » (tag vX.Y.Z ou à la main)
                                              │
            ┌─────────────────────────────────┼──────────────────────────────┐
            ▼                                 ▼                              ▼
   1. images → ghcr.io            2. migrations → Neon            3. deploy.sh → VPS
   front, api, worker, bundle     coges_owner, depuis le job      clé SSH bridée
   étiquetées vX.Y.Z + SHA        (jamais sur le VPS)             pull, up -d, vérif.
                                                                         │
                                                       4. test de fumée ◀┘
                                                          échec → retour à la
                                                          version précédente
```

| Étape | Où | Qui a les droits |
|---|---|---|
| CI (lint, tests, T1–T40, fuites, images sans push) | GitHub Actions | tout le monde, sur chaque push et PR |
| Images | GitHub Actions → `ghcr.io/papa-bothie/coges/*` (privé) | `GITHUB_TOKEN` du workflow |
| Migrations | GitHub Actions, environnement `preprod` ou `production` | secret `NEON_OWNER_DSN` (connexion **directe**) |
| Déploiement | VPS, `/opt/coges/deploy.sh` lancé par l'utilisateur `deploy` | secret `DEPLOY_SSH_KEY` (clé bridée) |
| Test de fumée | GitHub Actions → `https://<domaine>` | compte `SMOKE_*` d'une entreprise dédiée |

## Lancer un déploiement

- **Préproduction** : pousser un tag, `git tag v1.4.0 && git push origin v1.4.0`. Ou
  GitHub → Actions → « Déployer » → *Run workflow* → `preprod`, version.
- **Production** : toujours à la main, *Run workflow* → `production`, la version déjà
  essayée en préprod (`v1.4.0`). Jamais une version qui n'est pas passée par la préprod.

> **Écart daté (2026-10-26, décidé par le propriétaire).** La version de `main` qui
> porte les lots admin 4 à 6 (révisions 0029 et 0030, depuis `5d271c8` en production) part
> en production **sans passer par la préprod**, qui n'est pas utilisable : l'environnement
> GitHub `preprod` date de Vercel (`COGES_PUBLIC_URL` vers `coges-api.vercel.app`, DSN
> Neon de préprod du 2026-09-26 jamais revérifié, aucun `DEPLOY_*`), et aucune
> préprod n'a été déployée sur le VPS. Ce qui compense : migrations seulement additives
> (règle de l'ADR 0083, retour arrière sans toucher la base), CI verte sur PostgreSQL 18,
> sauvegarde de la nuit vérifiée et restauration exercée le 2026-10-25. À remettre en
> état avant le prochain déploiement : `preprod` (variables, secrets, `NEON_OWNER_DSN`,
> rôles `coges_backup`, `coges_app_platform`, `coges_billing` sur la branche Neon de
> préprod) et `/etc/coges/preprod.env`.

Avant : la préprod est arrêtée par défaut. La lancer (`deploy.sh preprod v1.4.0` sur le
VPS, ou le workflow), essayer, puis l'arrêter (`deploy.sh preprod stop`).

## Sans clé de déploiement (mode manuel)

Tant que `DEPLOY_SSH_KEY` n'existe pas dans l'environnement GitHub, le workflow s'arrête
après les migrations et écrit dans son résumé la commande à lancer :

```bash
ssh coges@<vps>
sudo -u deploy /opt/coges/deploy.sh production v1.4.0
```

## Mettre en place le déploiement automatique (une fois, par le propriétaire)

1. Sur le poste : `ssh-keygen -t ed25519 -f coges-deploy -C "github-actions coges"` (sans
   phrase de passe : c'est une clé de machine, bridée).
2. Sur le VPS, dans `/home/deploy/.ssh/authorized_keys`, UNE ligne :
   ```
   command="/opt/coges/deploy.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty,from="<plage IP de GitHub si souhaité>" ssh-ed25519 AAAA… github-actions coges
   ```
   `from=` est facultatif : les adresses des runners GitHub changent souvent (liste :
   `https://api.github.com/meta`, clé `actions`). Sans `from=`, la clé reste limitée à
   `deploy.sh`.
3. GitHub → Settings → Environments → `production` (et `preprod`) :
   - secret `DEPLOY_SSH_KEY` = contenu de `coges-deploy` (la clé **privée**) ;
   - secret `DEPLOY_KNOWN_HOSTS` = sortie de `ssh-keyscan -p <port> <vps>` ;
   - variables `DEPLOY_HOST`, `DEPLOY_PORT`, `COGES_PUBLIC_URL` (`https://<domaine>` ou
     `https://preprod.<domaine>`).
4. Jeton de lecture des images, sur le VPS : GitHub → Settings → Developer settings →
   *Personal access token (classic)* avec **seulement** `read:packages`. Le déposer :
   `/etc/coges/ghcr-user` (votre identifiant GitHub) et `/etc/coges/ghcr-token`, root:deploy,
   mode 0640.
5. Effacer `coges-deploy` du poste une fois déposée (une copie dans le gestionnaire de mots
   de passe si besoin).

## Ce que voit une personne qui a l'application installée (ADR 0102)

Rien, sauf en dernier recours.

- Le téléphone repère la nouvelle version (le `sw.js` du nouveau build) et la prépare en
  arrière-plan, sans rien changer à l'écran.
- Elle s'active à un **moment sûr** : à la prochaine ouverture de l'application, au retour
  après plus de 5 minutes en arrière-plan, au prochain changement d'écran par un lien, ou
  après 24 heures sur le même écran — jamais pendant une écriture, une saisie non envoyée,
  une vente ou un retour en cours.
- Un écran resté ouvert sur l'ancienne version continue de fonctionner : le front garde les
  fichiers des builds précédents 14 jours (volume `front-static`). S'il change d'écran, Next
  recharge la page sur la nouvelle version ; la saisie en cours est gardée (ADR 0101).
- **Retirer une compatibilité** (une route, un champ) : seulement 14 jours après la version
  qui ne s'en sert plus, puis régler `COGES_MIN_FRONT_VERSION` à cette version. Un front plus
  ancien reçoit alors 426 et se met à jour au moment sûr suivant ; s'il est encore refusé,
  il affiche « Une nouvelle version de CoGes est prête » avec « Recharger ».

### Purge en cas de défaut de cache

Le cache ne contient que des fichiers statiques et la page hors ligne. Si un défaut y est
découvert : déployer une version (le nom du cache suit l'étiquette, l'ancien est supprimé à
l'activation). Pour forcer tout de suite sur tous les appareils, déployer en plus
`COGES_MIN_FRONT_VERSION` égal à la version corrigée. Vider le volume `front-static`
(`docker volume rm <pile>_front-static`, front arrêté) ne sert que si un fichier statique
lui-même est fautif.

## Revenir en arrière

- **Automatique** : si `/api/v1/health/ready` ou `/login` ne répondent pas dans les 3 min
  après `up -d`, `deploy.sh` remet la version précédente ; si le test de fumée de GitHub
  échoue, le workflow lance `deploy.sh <pile> rollback`.
- **À la main**, sur le VPS :
  ```bash
  sudo -u deploy /opt/coges/deploy.sh production status     # version courante et précédente
  sudo -u deploy /opt/coges/deploy.sh production rollback   # revenir à la précédente
  sudo -u deploy /opt/coges/deploy.sh production v1.3.2     # ou une version précise
  ```
- **Retour impossible** : chaque version contrôle `/etc/coges/coges.env` avec son propre
  `check_runtime_env.py`. Un fichier modifié pour la nouvelle version (par exemple
  `COGES_ADMIN_GATE=cloudflare` sans liste d'adresses, ADR 0104) peut être refusé par la
  précédente. `deploy.sh` le vérifie **avant** de commencer et prévient (« pas de retour
  automatique possible ») ; si la nouvelle version échoue ensuite, il ne relance rien et
  écrit dans la sortie et dans `/var/log/coges/deploy.log` les refus, l'état de la pile et
  les deux issues : réparer et redéployer la nouvelle version, ou remettre dans le fichier
  ce que la précédente exige et la redéployer **par son nom** (`deploy.sh production
  vX.Y.Z`). Pas `rollback` dans ce cas : il viserait la version d'avant la précédente.
  Un fichier refusé par la nouvelle version, lui, arrête tout avant le moindre changement.
- **La base ne revient pas en arrière** : c'est pourquoi chaque migration doit rester
  compatible avec la version précédente du code (on ajoute une colonne d'abord, on retire
  l'ancienne à la version suivante). Une version qui casse cette règle ne se déploie pas.

## Une migration échoue

Le workflow s'arrête au job « Migrations » : **rien n'est déployé**, le VPS garde sa
version. Alembic joue chaque révision dans une transaction : une révision qui échoue est
annulée en entier.

1. Lire le journal du job (message d'erreur PostgreSQL).
2. Corriger la migration dans une PR, CI verte, nouveau tag.
3. Si la base est restée dans un état intermédiaire (révision non transactionnelle, rare) :
   ne rien forcer. Comparer `alembic current` (job manuel ou poste avec le DSN
   propriétaire) à la révision attendue, et demander de l'aide avant toute action.
4. En dernier recours, Neon permet de revenir à un instant précis (PITR) : voir
   `docs/runbooks/vps.md`, « Neon injoignable ou base abîmée ».

## Journal

- Sur le VPS : `/var/log/coges/deploy.log` (une ligne par étape, sans secret).
- Dans GitHub : l'historique du workflow « Déployer » et son résumé (version déployée).
