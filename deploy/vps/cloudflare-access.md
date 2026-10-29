# Administration derrière Cloudflare Access (ADR 0104)

But : ouvrir `https://admin.coges.app` depuis n'importe où, **seulement** après le code
envoyé par Cloudflare à ton adresse e-mail. Et rendre l'administration **impossible à
atteindre** sans passer par Cloudflare : elle n'est plus servie sur les ports publics du
VPS, et l'API refuse toute requête qui n'a pas le jeton signé par Cloudflare.

`coges.app` (commerçants) et son API ne changent pas.

Tout est gratuit : Cloudflare Zero Trust, offre « Free » (jusqu'à 50 personnes).

```
navigateur ─▶ Cloudflare Access (code par e-mail) ─▶ tunnel ─▶ conteneur cloudflared
           ─▶ Caddy, port 8081 interne (jamais publié) ─▶ admin et /api/v1/platform/*
```

Ce qu'il te faut : l'accès au tableau de bord Cloudflare de `coges.app`, une session SSH
sur le VPS, et une version de CoGes qui contient ce lot (tag `vX.Y.Z` après la fusion).

> Les menus de Cloudflare changent parfois de nom. Si un libellé diffère un peu, cherche
> le plus proche : la logique reste la même.

---

## 1. Zero Trust : équipe et méthode de connexion

1. Ouvre <https://one.dash.cloudflare.com> et choisis ton compte.
2. Première visite : Cloudflare demande un **nom d'équipe** (par exemple `coges`) et
   l'offre : choisis **Free** (une carte peut être demandée, rien n'est prélevé sur Free).
3. Note le **domaine d'équipe** : `coges.cloudflareaccess.com` (Settings → Custom Pages,
   ou Settings → General → « Team domain »). C'est la valeur de
   `COGES_ACCESS_TEAM_DOMAIN`, **sans** `https://`.
4. Settings → Authentication → **Login methods** : vérifie que **One-time PIN** est là
   (code à six chiffres par e-mail). Il est actif par défaut.
5. Facultatif : « Add new » → **Google**, pour se connecter avec ton compte Google. Le
   code par e-mail reste disponible en secours.

## 2. L'application « admin.coges.app »

1. Access → Applications → **Add an application** → **Self-hosted**.
2. Nom : `CoGes administration`. **Session duration : 24 hours**.
3. Domaine : sous-domaine `admin`, domaine `coges.app`, chemin vide (toute l'application).
4. Méthodes de connexion : One-time PIN (et Google si tu l'as ajouté).
5. Règle (policy) : nom `Équipe CoGes`, action **Allow**, puis
   **Include → Emails → `papebothie03@gmail.com`**. Rien d'autre : ni « Everyone », ni
   domaine e-mail entier.
6. Enregistre. Rouvre l'application : dans « Overview » (ou « Basic information »),
   copie **Application Audience (AUD) Tag** : 64 caractères hexadécimaux. C'est
   `COGES_ACCESS_AUD`.

Un collègue invité dans l'administration (ADR 0094) doit **aussi** être ajouté à cette
règle (Include → Emails, une ligne de plus), sinon Cloudflare l'arrête avant la page
d'invitation.

## 3. Le tunnel

1. Networks → **Tunnels** → **Create a tunnel** → type **Cloudflared**.
2. Nom : `coges-vps`. Enregistre.
3. Cloudflare montre une commande d'installation. Choisis **Docker** et copie seulement
   ce qui suit `--token` (une longue chaîne qui commence souvent par `eyJ`). C'est
   `COGES_CLOUDFLARE_TUNNEL_TOKEN`. **C'est un secret** : ne le colle nulle part
   ailleurs que dans `/etc/coges/coges.env`. Ne lance **pas** la commande proposée : le
   conteneur fait déjà partie de la pile.
4. Passe l'étape du connecteur (il apparaîtra après l'étape 4).
5. **Supprime d'abord l'ancien enregistrement DNS** `admin` (type A, « DNS only ») dans
   DNS → Records de `coges.app` : sinon Cloudflare refuse la route. À partir de là,
   l'administration est coupée jusqu'à la fin de l'étape 4.
6. Dans le tunnel, onglet **Public hostname** (ou « Published application routes ») →
   **Add** :
   - sous-domaine `admin`, domaine `coges.app`, chemin vide ;
   - service : type **HTTP**, URL **`caddy:8081`**.
   Cloudflare crée lui-même l'enregistrement DNS `admin` (CNAME vers le tunnel, nuage
   orange). N'y touche pas.

## 4. Les variables sur le VPS, puis le redéploiement

```bash
sudo nano /etc/coges/coges.env
```

Ajoute ou modifie ces lignes (le modèle est `deploy/vps/coges.env.example`) :

```bash
COGES_ADMIN_GATE=cloudflare
COGES_ACCESS_TEAM_DOMAIN=coges.cloudflareaccess.com
COGES_ACCESS_AUD=<les 64 caractères de l'étape 2>
COGES_CLOUDFLARE_TUNNEL_TOKEN=<le jeton de l'étape 3>
# Facultatif : vide, plus aucun filtre d'adresse (c'est le but : l'adresse Sonatel change).
COGES_ADMIN_ALLOWED_IPS=
```

Puis redéploie la version qui contient ce lot :

```bash
sudo -u deploy /opt/coges/deploy.sh production vX.Y.Z
sudo -u deploy /opt/coges/deploy.sh production status    # cloudflared doit être « Up »
```

`deploy.sh` vérifie d'abord le fichier (`check_runtime_env.py`) : il refuse un domaine
d'équipe, une AUD ou un jeton absents ou mal formés. Il démarre alors le conteneur
`cloudflared` (profil `tunnel`). Dans Zero Trust, le tunnel passe à **Healthy**.

## 5. Vérifier

Depuis ton ordinateur :

1. **Le bon chemin** : fenêtre de navigation privée → `https://admin.coges.app`. La page
   Cloudflare demande ton e-mail, puis le code reçu. Ensuite, la connexion de
   l'administration CoGes (ton mot de passe habituel), puis le tableau de bord.
2. **Le contournement par l'adresse du VPS est refusé** (remplace `<IP>` par l'adresse
   publique du VPS) :

   ```bash
   curl -v --resolve admin.coges.app:443:<IP> https://admin.coges.app/login
   ```

   Attendu : **échec de la poignée TLS** (`tlsv1 alert internal error` ou similaire) ;
   aucun site `admin.` n'est plus servi sur 443. Et le port interne n'est pas ouvert :

   ```bash
   curl -m 5 http://<IP>:8081/   # attendu : délai dépassé ou connexion refusée
   ```

3. **L'API refuse même « de l'intérieur » sans jeton**, sur le VPS :

   ```bash
   docker exec coges-caddy-1 wget -qSO- http://production-api:8000/api/v1/platform/access
   ```

   Attendu : `403 Forbidden` (code `access_required`).
4. **`coges.app` n'a pas changé** : `https://coges.app/login` s'ouvre, et
   `https://coges.app/api/v1/health/ready` répond `{"status":"ok",…}`.

La session Cloudflare dure 24 h. Passé ce délai, l'administration ouverte dans un onglet
affiche une erreur au prochain appel : recharge la page, Cloudflare redemande le code.

## 6. Retour arrière (revenir à la liste d'adresses)

1. Cloudflare : dans le tunnel, supprime la route `admin.coges.app`. Dans DNS → Records,
   recrée `admin` : type **A**, adresse du VPS, **DNS only** (nuage gris).
2. VPS, `/etc/coges/coges.env` :

   ```bash
   COGES_ADMIN_GATE=ip
   COGES_ADMIN_ALLOWED_IPS=<ton adresse du jour>     # curl -4 https://ifconfig.me
   COGES_ACCESS_TEAM_DOMAIN=
   COGES_ACCESS_AUD=
   ```

   Les deux variables Access **doivent** être vides : sinon l'API exigerait un jeton que
   plus personne n'apporte, et `check_runtime_env.py` refuse le fichier pour cette raison.
   Le jeton du tunnel peut rester : il ne sert plus.
3. Redéploie la même version : `deploy.sh` arrête `cloudflared`, Caddy sert de nouveau
   `admin.coges.app` sur 443 (certificat Let's Encrypt redemandé au besoin).

Revenir à une version d'**avant** ce lot n'est possible qu'en mode `ip` (étapes 1 et 2).

## 7. Cloudflare en panne : accès de secours par SSH

SSH ne passe pas par Cloudflare : c'est la porte de secours.

1. Connecte-toi au VPS en SSH, puis dans `/etc/coges/coges.env` :

   ```bash
   COGES_ADMIN_GATE=ssh
   COGES_ACCESS_TEAM_DOMAIN=
   COGES_ACCESS_AUD=
   ```

2. Redéploie la même version (`deploy.sh production vX.Y.Z`). L'administration est alors
   servie en HTTP sur le port **8082 de la boucle locale du VPS** seulement (rien
   d'ouvert sur Internet), sans contrôle Cloudflare : il reste ton mot de passe.
3. Depuis ton ordinateur, ouvre un tunnel SSH et laisse-le tourner :

   ```bash
   ssh -N -L 8082:127.0.0.1:8082 -p <port SSH> <compte>@<IP du VPS>
   ```

   puis ouvre **`http://localhost:8082`** dans le navigateur.
4. La panne finie : remets `COGES_ADMIN_GATE=cloudflare` et les deux variables Access
   (étape 4), redéploie. Ne garde pas le mode `ssh` plus longtemps que la panne.

Si la panne de Cloudflare touche aussi le DNS de `coges.app`, les commerçants sont
touchés eux aussi : c'est une autre affaire (le DNS est chez Cloudflare), hors de ce guide.
