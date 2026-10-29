# Guide d'intervention — le VPS de CoGes (ADR 0083)

Une seule machine (VPS Infomaniak, Ubuntu 24.04) porte tout CoGes sauf la base : Caddy
(HTTPS), le site (front), l'API, Redis, le worker, beat et le relais. La base est chez
Neon. Ce guide dit, pour chaque situation : ce qu'on voit, ce que vivent les commerçants,
les commandes exactes, et quand c'est urgent. Les alertes des workers ont leur propre
guide : `docs/runbooks/workers.md`. Le déploiement : `docs/runbooks/deploiement.md`.

## Avant tout

```bash
ssh -p <port> coges@<vps>                 # jamais en root, jamais par mot de passe
/opt/coges/check.sh                       # bilan en une commande (rouge = à traiter)
alias dc='docker compose -p coges'        # la pile de production
dc ps                                     # services et santé
dc logs --since 30m api                   # journaux d'un service (caddy, front, api, worker, beat, relay, redis)
sudo -u deploy /opt/coges/deploy.sh production status
tail -50 /var/log/coges/deploy.log        # derniers déploiements
```

Niveaux d'urgence :

- **Immédiat** : les commerçants ne peuvent plus vendre, ou ne le pourront plus dans l'heure.
- **Dans la journée** : gênant, mais la vente continue.
- **Peut attendre** : rien de visible avant plusieurs jours.

Les secrets sont dans `/etc/coges/coges.env` (production) et `/etc/coges/preprod.env` :
jamais dans git, jamais copiés ailleurs que dans le gestionnaire de mots de passe.

---

## Le site ne répond plus

**Ce qu'on voit.** Le navigateur affiche une erreur de connexion, ou une page « 502 ».
`check.sh` est rouge sur « Application ».

**Pour les commerçants.** Plus de vente possible. **Urgence : immédiat.**

**Faire.**

1. `dc ps` : quel service n'est pas `healthy` ?
   - **caddy** arrêté : `dc logs --tail 50 caddy`, puis `dc up -d caddy`. Une erreur
     « adapting config » : le Caddyfile de la version est cassé → `deploy.sh production rollback`.
   - **front** ou **api** en échec : `dc logs --tail 100 api`. Une erreur de démarrage
     après un déploiement → `sudo -u deploy /opt/coges/deploy.sh production rollback`.
   - Tout est `healthy` mais rien ne répond : `sudo ufw status` (80 et 443 ouverts ?),
     DNS du domaine (`dig +short <domaine>` = IP du VPS ?).
2. `curl -s https://<domaine>/api/v1/health/ready` : `database: down` → voir « Neon
   injoignable » ; `redis: down` → voir « Redis perdu ».

## Le VPS ne répond plus du tout

**Ce qu'on voit.** Ni le site ni SSH. **Urgence : immédiat.**

**Faire.**

1. Manager Infomaniak → le VPS → état (arrêté ? disque plein ? facturation ?).
2. **Console de secours** (Manager → VPS → Console) : se connecter avec l'utilisateur
   `coges`… qui n'a pas de mot de passe. Pour cela, gardez un **mot de passe de secours**
   pour `coges` dans le gestionnaire (`sudo passwd coges` une fois) : SSH reste par clé
   seulement, la console accepte le mot de passe.
3. Redémarrer depuis le Manager si la machine est figée. Docker relance tout seul
   (`restart: unless-stopped`). Puis `/opt/coges/check.sh`.
4. Machine perdue : « Reconstruire le VPS de zéro » ci-dessous.

## Certificat non renouvelé

**Ce qu'on voit.** Le navigateur avertit « connexion non sécurisée ». `check.sh` :
« expire dans N jours » en rouge. Caddy renouvelle seul 30 jours avant l'échéance.

**Pour les commerçants.** Avertissement effrayant, puis site bloqué à l'échéance.
**Urgence : dans la journée** (immédiat si déjà expiré).

**Faire.** `dc logs caddy | grep -i -E "acme|certificate|error" | tail -20`. Causes
habituelles : le port 80 fermé (Let's Encrypt en a besoin : `sudo ufw allow 80/tcp`), le
DNS qui ne pointe plus sur le VPS, une limite de Let's Encrypt (trop d'essais : attendre
une heure). Puis `dc restart caddy`.

## Un conteneur redémarre en boucle

**Ce qu'on voit.** `dc ps` : `Restarting` ; `check.sh` : « redémarrages répétés ».

**Faire.** `dc logs --tail 100 <service>`. Juste après un déploiement :
`deploy.sh production rollback`. Sinon : « Mémoire saturée » (code 137 dans
`docker inspect <conteneur> --format '{{.State.ExitCode}}'`) ou « Neon injoignable ».
**Urgence** : immédiat pour caddy, front, api ; voir `workers.md` pour les autres.

## Worker bloqué, outbox en retard

Voir `docs/runbooks/workers.md` (`heartbeat_missing:*`, `outbox_lagging`). Ici, la
commande de bilan est `curl -s -H "Authorization: Bearer $COGES_OPS_TOKEN"
https://<domaine>/api/v1/system/workers` (jeton dans `/etc/coges/coges.env`).

## Disque plein

**Ce qu'on voit.** `check.sh` : « / plein à 9x % ». Les déploiements échouent, Redis ne
peut plus écrire son journal. **Urgence : immédiat au-dessus de 95 %.**

**Faire.**
```bash
sudo du -xh / --max-depth=2 2>/dev/null | sort -h | tail -15
docker system df
docker image prune -a --filter "until=720h"   # images de plus de 30 jours, hors celles en service
sudo journalctl --vacuum-size=200M
sudo rm -rf /opt/coges/releases/<versions anciennes>  # garder la courante et la précédente
```
Les journaux Docker sont bornés (10 Mo × 5 par conteneur) : s'ils débordent quand même,
c'est un service qui écrit en boucle — le chercher (`dc logs --tail 20 <service>`).

## Mémoire saturée (processus tué)

**Ce qu'on voit.** Un conteneur redémarre avec le code 137 ; `dmesg | grep -i oom` ;
`check.sh` : « moins de 300 Mo disponibles ». **Urgence : dans la journée** (immédiat si
c'est l'API).

**Faire.** `docker stats --no-stream` pour voir qui consomme. La préprod tourne-t-elle ?
`sudo -u deploy /opt/coges/deploy.sh preprod stop`. Si c'est le worker pendant le
calcul de nuit (ML), c'est attendu sur 4 Go : passer le VPS à 8 Go (Manager Infomaniak,
redémarrage de quelques minutes, à faire hors heures d'ouverture).

## Redis perdu

**Ce qu'on voit.** `health/ready` : `redis: down`, ou Redis vidé (volume perdu).

**Pour les commerçants.** La vente continue (la base est chez Neon) ; le cache et la
limitation de débit se coupent, les alertes et agrégats attendent. **Urgence : dans la
journée.**

**Faire.** Redis ne contient que la file des tâches, le cache et des compteurs : **on
repart à vide sans rien perdre d'important.** `dc up -d redis`, puis `dc restart worker
beat relay`. Volume abîmé : `dc stop redis && docker volume rm coges_redis-data && dc up -d
redis`. Les événements non traités sont toujours dans l'outbox en base : le relais les
renvoie.

## Neon injoignable ou base abîmée

**Ce qu'on voit.** `health/ready` : `database: down` ; `check.sh` : « Neon injoignable ».

**Pour les commerçants.** Plus de vente. **Urgence : immédiat.**

**Faire.**
1. `https://neonstatus.com` : incident chez Neon ? Alors attendre, rien à faire sur le VPS.
2. Console Neon : projet suspendu (facture, quota) ? mot de passe d'un rôle changé
   (`COGES_DATABASE_URL_*` à mettre à jour dans `/etc/coges/coges.env`, puis
   `deploy.sh production <version courante>` pour relancer) ?
3. Données abîmées (suppression par erreur) : Neon garde l'historique (PITR). Créer une
   branche à l'instant d'avant, vérifier, puis la promouvoir — ne jamais écraser la
   branche principale sans avoir vérifié la branche restaurée.

## Revenir à la version précédente

```bash
sudo -u deploy /opt/coges/deploy.sh production status
sudo -u deploy /opt/coges/deploy.sh production rollback
```
La configuration (compose, Caddyfile) revient avec la version. La base ne revient pas :
voir `docs/runbooks/deploiement.md`.

## Soupçon de piratage

**Ce qu'on voit.** Connexions SSH inconnues (`last`, `journalctl -u ssh`), processus
étranger (`top`), conteneur inconnu (`docker ps -a`), fichiers changés dans `/opt/coges`
ou `/etc/coges`, trafic anormal. **Urgence : immédiat.**

**Faire, dans cet ordre :**
1. **Couper** : Manager Infomaniak → pare-feu / arrêt du VPS. Ne pas « nettoyer » la
   machine : elle n'est plus digne de confiance.
2. **Changer TOUS les secrets**, depuis un poste sain :
   - `COGES_JWT_SECRET` (nouvelle valeur ; les sessions repartent) ;
   - `COGES_REDIS_PASSWORD` ;
   - mots de passe Neon de `coges_app`, `coges_relay`, `coges_analytics` (console Neon),
     et celui de `coges_owner` (secret GitHub `NEON_OWNER_DSN`) ;
   - DSN Sentry (régénérer la clé du projet) ;
   - clé SSH bridée (`DEPLOY_SSH_KEY`), jeton `ghcr` en lecture, `COGES_OPS_TOKEN` ;
   - URL des pings Healthchecks.io.
3. **Révoquer les sessions** : `UPDATE auth_sessions SET revoked_at = now() WHERE
   revoked_at IS NULL` (console Neon, rôle propriétaire).
4. **Reconstruire un VPS neuf** (ci-dessous) avec les nouveaux secrets. Garder l'ancien
   disque pour l'analyse, sans le rallumer en ligne.
5. Prévenir les commerçants si des données ont pu être lues (obligation légale possible).

## Reconstruire le VPS de zéro (moins de 30 minutes)

Ce qu'il faut avoir sous la main : la clé SSH de l'administrateur, le gestionnaire de mots
de passe (contenu de `coges.env`, jeton ghcr), l'accès au Manager Infomaniak et au DNS.

1. **(5 min)** Manager Infomaniak : nouveau VPS (ou réinstallation), Ubuntu 24.04 LTS,
   votre clé SSH publique. Noter l'IP.
2. **(2 min)** DNS : enregistrements A de `<domaine>` et `preprod.<domaine>` vers la
   nouvelle IP (TTL court).
3. **(1 min)** Copier les scripts :
   ```bash
   scp deploy/vps/{bootstrap.sh,deploy.sh,check.sh} ubuntu@<ip>:/tmp/
   ```
4. **(10 min)** `ssh ubuntu@<ip> 'sudo bash /tmp/bootstrap.sh --dry-run'` pour relire, puis
   `sudo bash /tmp/bootstrap.sh --ssh-port <port> --hostname coges-prod`.
5. **(1 min)** Dans un NOUVEAU terminal (garder l'ancien ouvert) : `ssh -p <port> coges@<ip>`.
   Ça marche ? Alors seulement fermer l'ancien.
6. **(3 min)** Déposer les secrets :
   ```bash
   sudo install -m 0640 -o root -g deploy /dev/stdin /etc/coges/coges.env   # coller, Ctrl-D
   sudo install -m 0640 -o root -g deploy /dev/stdin /etc/coges/ghcr-user
   sudo install -m 0640 -o root -g deploy /dev/stdin /etc/coges/ghcr-token
   ```
7. **(5 min)** `sudo -u deploy /opt/coges/deploy.sh production <dernière version>` (le
   certificat arrive en moins d'une minute si le DNS est déjà propagé).
8. **(2 min)** `/opt/coges/check.sh`, puis remettre la clé bridée de GitHub dans
   `/home/deploy/.ssh/authorized_keys` et mettre à jour `DEPLOY_KNOWN_HOSTS` et
   `DEPLOY_HOST` dans GitHub.

Rien à restaurer : la base est chez Neon, Redis repart à vide, les artefacts ML se
recalculent la nuit suivante (`celery -A app.workers.celery_app call ml_train.train_all`
pour ne pas attendre).

## Administration de la plateforme (ADR 0089)

`admin.<domaine>` sert l'administration (application `admin`, comptes de l'équipe). Sa
porte se choisit par `COGES_ADMIN_GATE` (ADR 0104) :

- `cloudflare` (cible) : **Cloudflare Access** (code par e-mail) par un tunnel, puis le
  **compte** (API) ; aucun port public. Mise en place, vérifications, retour arrière et
  accès de secours par SSH : **`deploy/vps/cloudflare-access.md`**.
- `ip` (retour arrière, et fichiers d'avant ce lot) : l'**adresse IP** (Caddy, 403 pour
  toute autre) puis le compte, comme ci-dessous.
- `ssh` : secours quand Cloudflare est en panne (étape 7 du guide).

**Mode `ip` : ajouter ou changer une adresse autorisée** (peut attendre, sauf si l'équipe
est bloquée dehors) :

```bash
curl -4 https://ifconfig.me             # depuis le poste à autoriser : son adresse publique
sudo nano /etc/coges/coges.env          # COGES_ADMIN_ALLOWED_IPS="196.207.1.10 41.82.0.0/16"
                                        # IP ou CIDR, séparées par des espaces ; jamais 0.0.0.0/0
sudo -u deploy /opt/coges/deploy.sh production status    # note la version actuelle
sudo -u deploy /opt/coges/deploy.sh production vX.Y.Z    # la même version : contrôle puis relance
```

Redéployer la version en place relance le contrôle (`check_runtime_env.py` refuse une liste
vide, illisible ou ouverte à tous) et recrée Caddy avec la nouvelle liste. Vérifier depuis
le poste autorisé que `https://admin.<domaine>/login` répond, et depuis un autre (données
mobiles) qu'il reçoit 403. Une adresse de connexion mobile change souvent : préférer l'adresse fixe du bureau, ou le
bloc de l'opérateur en CIDR en connaissance de cause.

**Créer un compte de l'équipe** (jamais par une route publique) :

```bash
dc exec api python -m app.cli create-platform-user \
  --email prenom@equipe.example --name "Prénom Nom" --role administrator   # ou support
```

Le mot de passe est demandé deux fois (12 caractères au moins) et ne s'affiche pas.
`support` lit les entreprises ; seul `administrator` suspend ou réactive.

**Désactiver un compte de l'équipe** (immédiat si soupçon de vol) : ses sessions tombent
aussitôt (trigger), il ne se reconnecte plus.

```bash
dc exec api python -m app.cli deactivate-platform-user --email prenom@equipe.example
```

**Une entreprise suspendue par erreur** : la réactiver depuis l'administration (fiche de
l'entreprise, « Réactiver ») ; ses comptes se reconnectent aussitôt, les sessions encore
valides reprennent à la requête suivante.

---

## Routine mensuelle (environ 1 h)

- [ ] `/opt/coges/check.sh` : tout vert ? Noter disque, mémoire, swap.
- [ ] `sudo apt list --upgradable` : les mises à jour non de sécurité (noyau, Docker) se
      font ici, à la main, hors heures d'ouverture, puis `sudo reboot` et `check.sh`.
- [ ] `docker image prune -a --filter "until=720h"` ; garder 2 versions dans
      `/opt/coges/releases`.
- [ ] `sudo fail2ban-client status sshd` : beaucoup de bannissements ? Envisager un port
      SSH non standard (`bootstrap.sh --ssh-port`).
- [ ] Certificat : plus de 30 jours restants (`check.sh`).
- [ ] Journal des déploiements et des tâches de nuit (`make ops-status` depuis le poste).
- [ ] Sentry : nouveaux problèmes `component:api|worker|relay` ?
- [ ] Une fois par trimestre : un exercice « reconstruire le VPS » sur un VPS jetable,
      chronométré.
