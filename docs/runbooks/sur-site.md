# Guide — installer CoGes sur le PC d'un client (« sur site », ADR 0124)

Ce guide installe **tout CoGes sur un seul PC**, base de données comprise. Le commerçant
ouvre ensuite `http://localhost` dans le navigateur de ce PC. Rien ne dépend d'Internet une
fois les images téléchargées, et rien n'est joignable depuis le réseau du magasin.

Il est écrit pour quelqu'un qui débute : chaque commande se copie telle quelle dans
**PowerShell** (menu Démarrer, taper « PowerShell », Entrée).

> Les six lots sont faits. Ce que le sur-site ne fait pas est listé à la fin.
> Sauvegarde et restauration : section « Sauvegarde et restauration » (lot 4, ADR 0127).
> Mises à jour à distance : section « Mises à jour » (lot 5, ADR 0128).
> Support à distance, diagnostic, aide : section « Support à distance » (lot 6, ADR 0129).

## Installer en une commande (lot 3, ADR 0126)

Le script `installer.ps1` enchaîne les étapes 1 à 11 ci-dessous. Dans une fenêtre
**PowerShell** (menu Démarrer, « PowerShell », Entrée ; pas PowerShell ISE ni un éditeur),
avec le compte Windows qui a Docker Desktop, sans droits d'administrateur, tapez ces **deux
lignes** en remplaçant `vX.Y.Z` par la version donnée par CoGes (deux fois) :

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/papa-bothie/CoGes/vX.Y.Z/deploy/onprem/windows/installer.ps1 -OutFile $env:TEMP\coges-install.ps1 -UseBasicParsing
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\coges-install.ps1 -Version vX.Y.Z
```

Le fichier est d'abord enregistré : on peut le lire avant de le lancer. La version doit avoir
ses images publiées (`ghcr.io/papa-bothie/coges/{front,api,worker}:vX.Y.Z`) et contenir la
licence sur site (lot 2) ; le script le vérifie.

**Ce qu'il demande, une seule fois** : le nom de la boutique, son code (proposé à partir du
nom), le nom du gérant, son téléphone ou son e-mail, l'offre (`starter` 3 comptes,
`business` 7, `premium` 10) et la note du contrat (date du contrat et fin de maintenance,
obligatoire). Puis un récapitulatif : tapez `OUI`. Plus tard, après la création des
réglages, il s'arrête jusqu'à ce que vous tapiez `COPIE-FAITE` : copiez
`C:\CoGes\reglages\coges.env` dans le gestionnaire de mots de passe de CoGes **à ce
moment-là**. Enfin, la commande de création de la société demande le **mot de passe du
gérant** deux fois, sans l'afficher.

**Ce qu'il fait, dans l'ordre du guide** : contrôle du PC (Windows 11 64 bits, 8 Go, 20 Go
libres, virtualisation, Docker Desktop en moteur Linux, accès au groupe `docker-users`,
Internet, version publiée et contenant la licence) ; pose du programme dans
`C:\CoGes\programme\` (seulement `deploy/onprem/` de la version) ; réglages (8 mots de
passe et la clé tirés au hasard, jamais affichés, fichier lisible par ce compte seulement) ;
port 80, ou 8080 si 80 est pris (le programme qui le tient est nommé) ; images, contrôle des
réglages, migrations, démarrage (attente des neuf services, 5 minutes au plus) ; société,
licence et `license-status` ; `http://localhost` en 200 et l'administration en 404. Puis :
la commande `coges` dans toute nouvelle fenêtre (`C:\CoGes\bin\coges.cmd`, ajouté au PATH
de l'utilisateur), le raccourci « CoGes » sur le Bureau, la tâche planifiée « CoGes -
démarrage » (à l'ouverture de session, elle attend Docker puis lance `coges up -d`), et
l'ouverture de CoGes dans le navigateur. Enfin la tâche « CoGes - mise à jour » (lot 5,
section « Mises à jour »).

Chaque étape est écrite dans `C:\CoGes\journaux\installation-AAAAMMJJ-HHMMSS.log`
(étapes, durées, codes de sortie, erreurs de Docker), **jamais** un mot de passe ni une
valeur de `coges.env`.

**Ce qu'il ne fait pas** : installer Docker Desktop (sa licence dépend de la taille du
client : à vérifier avant), activer la virtualisation dans le BIOS, changer les réglages de
Docker Desktop (il dit seulement s'il faut cocher « Start Docker Desktop when you sign
in »), ouvrir un port ou le pare-feu. Il pose la sauvegarde automatique et en fait une
première (lot 4, « Sauvegarde et restauration »).

**Relancer ne casse rien** : `Installer` relancé sur le même PC garde le programme, les
réglages, la base et la société, répond « rien à faire » pour la licence, et reprend là où un
échec l'avait arrêté. Il ne garde aucun fichier d'état : il regarde ce qui est là.

| Message d'échec (début) | Quoi faire |
|---|---|
| `Ce PC n'est pas sous Windows 11 64 bits` · `il en faut 8 au moins` · `il en faut 20 au moins` | un autre PC, ou de la mémoire / de la place |
| `La virtualisation est désactivée` | l'activer dans le BIOS (Intel VT-x, AMD-V ou SVM) |
| `Docker Desktop n'est pas installé` | l'installer (lien affiché), moteur WSL 2 |
| `Docker Desktop est installé mais son moteur ne tourne pas` | l'ouvrir, attendre « Engine running » |
| `Docker refuse l'accès à ce compte Windows` | ajouter le compte au groupe `docker-users`, rouvrir la session |
| `Docker Desktop tourne avec des conteneurs Windows` | « Switch to Linux containers… » |
| `https://… ne répond pas depuis ce PC` | Internet, ou faire autoriser `github.com`, `ghcr.io` et `pkg-containers.githubusercontent.com` |
| `La version … n'existe pas` | vérifier la version donnée par CoGes |
| `La version … est antérieure à la licence sur site` | prendre une version plus récente |
| `Le contrôle des réglages refuse coges.env` | corriger chaque ligne `REFUS`, puis `-Action Reparer` |
| `Le service … ne démarre pas` | lire les 40 lignes affichées, puis `-Action Reparer` |
| `Le mot de passe du gérant doit se taper dans une vraie fenêtre` | relancer dans PowerShell ou le Terminal Windows |
| `Cette console ne peut pas cacher la frappe du mot de passe (GetPassWarning)` | rien n'est créé : relancer dans une fenêtre PowerShell ou le Terminal Windows ouverts directement |

Les autres actions, depuis `C:\CoGes\programme\windows\` :

```powershell
# Voir l'état (n'écrit rien) : version, services, adresse, licence, disque, dernier journal
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action Etat
# Reprendre les contrôles, la base et le démarrage sans rien recréer (après un échec, une mise à jour de Docker)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action Reparer
# Changer de port : -Action Reparer -Port 8080 ; de version : -Action Reparer -Version vX.Y.Z
# Retirer CoGes en GARDANT les réglages et les données (Installer les retrouve)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action Desinstaller
```

`-Action Desinstaller -EffacerLesDonnees` efface aussi les données : il exige d'abord une
sauvegarde bonne de moins d'une heure (faite sur place si besoin) et dit où elle est, puis
fait retaper le code de la boutique et `EFFACER`. Ces données ne reviennent qu'avec
`-Action Restaurer` et la **clé privée** du client. `-Simulation` sur n'importe quelle action annonce
chaque étape sans rien écrire ni lancer.

Les étapes manuelles ci-dessous restent le **secours** si le script ne peut pas aller au bout.

## Ce qu'il faut

- Un PC sous **Windows 11, 64 bits**, avec **8 Go de mémoire** au moins et 20 Go de disque libres.
- La **virtualisation activée** : Gestionnaire des tâches (Ctrl + Maj + Échap), onglet
  Performance, Processeur : la ligne « Virtualisation » doit dire « Activé ». Sinon, elle
  s'active dans le BIOS du PC (souvent « Intel VT-x » ou « AMD-V » / « SVM »).
- **Docker Desktop** avec le moteur **WSL 2** (proposé par défaut à l'installation). Docker
  Desktop est gratuit pour les petites entreprises ; vérifiez ses conditions sur le site de
  Docker avant de l'installer chez un client. Dans ses réglages, cochez « Start Docker
  Desktop when you sign in to your computer » : CoGes redémarre alors avec le PC.
- Une connexion Internet **le jour de l'installation et des mises à jour** seulement.

Vérifier que Docker répond :

```powershell
docker version
docker compose version
```

## Les trois endroits

CoGes sur site tient en trois endroits **séparés**. C'est ce qui permet de mettre à jour
sans rien perdre.

| Endroit | Où | Ce que c'est | Une mise à jour… |
|---|---|---|---|
| 1. Le programme | `C:\CoGes\programme\` | le contenu du dossier `deploy/onprem/` (compose, Caddyfile, scripts) | le **remplace** en entier |
| 2. Les réglages | `C:\CoGes\reglages\coges.env` | les mots de passe et la version de ce client | n'y touche **jamais** |
| 3. Les données | volumes Docker `coges-onprem_…` | la base, la file d'attente, les fichiers | n'y touche **jamais** |

Ne rangez jamais `coges.env` dans `C:\CoGes\programme\` : il serait effacé à la mise à jour
suivante.

## 1. Poser le programme

Créez les dossiers, puis copiez le contenu de `deploy/onprem/` (fourni par CoGes pour la
version à installer) dans `C:\CoGes\programme\` :

```powershell
New-Item -ItemType Directory -Force C:\CoGes\programme, C:\CoGes\reglages
```

Le dossier doit contenir, entre autres : `docker-compose.yml`, `Caddyfile`,
`maintenance.html`, `coges.env.example`, `check_onprem_env.py` et `postgres-init\`.

> Ne passez pas ces fichiers par un outil qui change les fins de ligne (ils sont en « LF »).
> Une archive ZIP les garde telles quelles.

## 2. Remplir les réglages

Copiez le modèle **hors** du dossier du programme, puis ouvrez-le dans le Bloc-notes :

```powershell
Copy-Item C:\CoGes\programme\coges.env.example C:\CoGes\reglages\coges.env
notepad C:\CoGes\reglages\coges.env
```

Dans la section « 1. À REMPLIR » :

- `COGES_IMAGE_TAG` : la version donnée par CoGes, par exemple `v1.4.0` (jamais `latest`).
- Huit mots de passe, **tous différents**. Cette commande en tire un ; lancez-la huit fois
  et collez chaque résultat après le `=` d'une ligne :

  ```powershell
  $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') })
  ```

- `COGES_MFA_ENCRYPTION_KEY`, d'un autre format :

  ```powershell
  $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_')
  ```

Ne touchez pas à la section « 2. NE PAS TOUCHER ». Enregistrez et fermez.

**Gardez une copie de ce fichier en lieu sûr** (gestionnaire de mots de passe de CoGes) :
sans ses mots de passe, la base de ce client ne s'ouvre plus. Ils ne sont lus par la base
qu'à la toute première mise en route : ne les changez plus ensuite.

## 3. Le raccourci `coges`

Pour ne pas retaper les deux chemins à chaque commande, définissez ce raccourci. Il vaut
pour la fenêtre PowerShell en cours : **à refaire à chaque nouvelle fenêtre**.
(Après le script d'installation, inutile : `C:\CoGes\bin\coges.cmd` fait la même chose
dans toute nouvelle fenêtre.)

```powershell
function coges { docker compose --env-file C:\CoGes\reglages\coges.env -f C:\CoGes\programme\docker-compose.yml @args }
```

## 4. Télécharger les images

Les images sont publiques : aucun compte, aucun `docker login`. Comptez quelques minutes
(environ 2 Go).

```powershell
coges --profile tools pull
```

Si la commande répond « … manque dans coges.env », une ligne du fichier de réglages est
restée vide : corrigez-la (étape 2) et relancez.

## 5. Contrôler les réglages

Le contrôle tourne dans une image déjà téléchargée (aucun Python à installer), sans réseau :

```powershell
$tag = (Select-String -Path C:\CoGes\reglages\coges.env -Pattern '^COGES_IMAGE_TAG=(.+)$').Matches[0].Groups[1].Value.Trim()
docker run --rm --network none -v C:\CoGes\programme:/onprem:ro -v C:\CoGes\reglages:/reglages:ro --entrypoint python ghcr.io/papa-bothie/coges/worker:$tag /onprem/check_onprem_env.py --env-file /reglages/coges.env
```

- `OK — les réglages sont bons` : continuez.
- Une ou plusieurs lignes `REFUS — …` : chacune dit quoi corriger. Corrigez, relancez.

Ce contrôle refuse aussi toute adresse qui viserait les services en ligne de CoGes
(`neon.tech`, `coges.app`…) : une installation sur site ne s'y branche jamais.

## 6. Préparer la base (migrations)

```powershell
coges --profile tools run --rm migrate
```

La première fois, PostgreSQL se crée (une minute environ), puis une quarantaine de lignes
« Running upgrade » défilent. Relancer la commande ne change rien : elle ne joue que ce
qui manque.

## 7. Démarrer

```powershell
coges up -d
coges ps
```

Au bout d'une à deux minutes, chaque ligne de `coges ps` doit dire `Up … (healthy)` :
`caddy`, `autoheal`, `postgres`, `redis`, `front`, `api`, `worker`, `beat`, `relay`.

## 8. Créer la société et son gérant

```powershell
coges --profile tools run --rm -e PYTHONWARNINGS=error::getpass.GetPassWarning cli create-company --name "Boutique Diallo" --slug boutique-diallo --manager-name "Awa Diallo" --manager-phone "77 123 45 67"
```

- `--slug` : le « code de la boutique » tapé à la connexion (lettres minuscules, chiffres, tirets).
- `--manager-phone` ou `--manager-email` (l'un des deux au moins).
- Le mot de passe du gérant est demandé deux fois, sans s'afficher (12 caractères au moins).
  **Il ne s'écrit jamais dans la ligne de commande** : n'ajoutez pas `--password`, il
  resterait dans l'historique de PowerShell.

**Précaution du terminal interactif sous Windows.** `coges … run` ouvre d'office un
terminal interactif (l'équivalent du `-it` de `docker run`) : c'est ce qui permet de taper
le mot de passe sans qu'il s'affiche. Pour que cela marche :

- lancez la commande dans une **vraie fenêtre PowerShell** ou dans le Terminal Windows,
  pas dans PowerShell ISE, ni dans la console d'un éditeur, ni à travers un script ;
- n'ajoutez **jamais** `-T` (ni `-it`, qui n'existe pas pour `docker compose run`) ;
- `-e PYTHONWARNINGS=error::getpass.GetPassWarning` fait **s'arrêter** la commande, avant
  toute lecture, si la console ne peut pas cacher la frappe : le message se termine par
  `GetPassWarning: Can not control echo on the terminal`, rien n'est créé ; changez de
  fenêtre et relancez. Si les caractères tapés s'affichent malgré tout : **Ctrl+C**.

À ce moment, une période d'essai de 30 jours démarre, comme en ligne. L'étape suivante
la remplace par la licence.

## 9. Poser la licence

La licence achetée par le client : l'abonnement devient **actif, sans date de fin**
(ADR 0125). Elle se pose ici, sur le PC, sans l'administration de la plateforme.

```powershell
coges --profile tools run --rm cli activate-license --slug boutique-diallo --plan business --note "Contrat du 17/11/2026, maintenance jusqu'au 17/11/2027"
```

- `--plan` : l'offre achetée, `starter` (3 comptes), `business` (7) ou `premium` (10).
  L'offre fixe le **nombre de comptes actifs** ; les écrans sont les mêmes.
- `--note` : écrivez-y **la date du contrat et celle de fin de maintenance**. Elle est
  gardée dans le journal et relue par `license-status`.

Réponse attendue :

```
Entreprise       : Boutique Diallo (boutique-diallo)
Offre            : Business (business)
Comptes          : 1 actif(s) sur 7 au plus
Abonnement       : essai → actif, sans fin
Accès            : essai → actif
Licence activée.
```

Refus possibles (rien n'est changé) :

| Message | Ce qu'il faut faire |
|---|---|
| `Entreprise introuvable : « … »` | vérifier le code de la boutique (`--slug` de l'étape 8) |
| `Offre inconnue ou non proposée : …` | `starter`, `business` ou `premium`, en minuscules |
| `Offre refusée : … Désactivez-en N …` | trop de comptes actifs pour cette offre : en désactiver N dans Réglages → Personnes, ou choisir une offre plus grande |

## 10. Vérifier la licence

```powershell
coges --profile tools run --rm cli license-status --slug boutique-diallo
```

Les lignes à lire : `Accès : actif`, `Fin de période : sans fin`, et `Dernière licence`
avec la date et la note. Cette commande n'écrit rien : on peut la lancer à tout moment.

## 11. Ouvrir CoGes

Dans Edge ou Chrome, sur ce PC : **http://localhost**

Connectez-vous avec le code de la boutique, le téléphone (ou l'e-mail) et le mot de passe
du gérant. À la première connexion, CoGes demande d'accepter les conditions d'utilisation.

`http://localhost` ne s'ouvre **que depuis ce PC** : c'est voulu. Depuis un autre appareil
du magasin, l'adresse ne répond pas.

## Premier démarrage : l'ordre à suivre

Les étapes 1 à 11 ci-dessus, dans cet ordre, sans en sauter : **réglages remplis** (2) →
**contrôle des réglages** (5) → **migrations** (6) → **démarrage** (7) → **société** (8)
→ **licence** (9) → **vérification** (10) → **connexion du gérant** (11).

## Changer d'offre

Le client achète une offre plus grande (ou plus petite) : relancez la commande de
l'étape 9 avec la nouvelle offre et une note qui dit pourquoi.

```powershell
coges --profile tools run --rm cli activate-license --slug boutique-diallo --plan premium --note "Avenant du 02/03/2027 : passage à Premium"
```

- Une offre plus petite est refusée tant que la société a plus de comptes actifs que son
  plafond (le message dit combien désactiver).
- Relancée avec **la même offre**, la commande répond `Licence déjà active, offre … : rien
  à faire.` et n'écrit rien.

## Ce qui se passe si on oublie la licence

Sans l'étape 9, la société reste en essai. Au **31ᵉ jour**, la tâche de nuit la suspend :
la connexion répond que l'accès est suspendu (les données restent, rien n'est effacé).
Il suffit alors de poser la licence (étape 9) : l'accès revient tout de suite, sans
redémarrer. Aucun e-mail n'est envoyé (pas de messagerie sur site).

---

## Au quotidien

Chaque commande suppose le raccourci `coges` de l'étape 3.

| Besoin | Commande |
|---|---|
| Voir l'état | `coges ps` |
| Arrêter CoGes (les données restent) | `coges down` |
| Redémarrer | `coges up -d` |
| Relancer un seul service | `coges restart api` |
| Journaux d'un service (30 dernières minutes) | `coges logs --since 30m api` |
| Suivre les journaux en direct (Ctrl + C pour quitter) | `coges logs -f api worker` |
| Mémoire utilisée par conteneur | `docker stats --no-stream` |

Services : `caddy` (entrée), `front` (écrans), `api`, `worker` et `beat` (tâches de fond
et de nuit), `relay` (événements), `redis`, `postgres` (la base).

> **Jamais `coges down -v`** : le `-v` efface les volumes, donc **toutes les données** du
> client. Seule une sauvegarde (section « Sauvegarde et restauration ») les ramènerait.

Après un redémarrage du PC, Docker Desktop relance CoGes tout seul (si l'option « Start
Docker Desktop when you sign in » est cochée, et après l'ouverture de la session Windows).

### Afficher la version installée

```powershell
docker inspect --format '{{.Config.Image}}' (coges ps -q api)
```

La réponse se termine par la version en cours d'exécution, par exemple
`ghcr.io/papa-bothie/coges/api:v1.4.0`. Pour tous les services d'un coup :
`coges ps --format "{{.Service}} {{.Image}}"`.

---

## Mettre à jour à la main

> **Le secours.** Depuis le lot 5, les mises à jour se font seules (section « Mises à
> jour »). Cette procédure sert quand le script ne peut pas aller au bout, ou pour installer
> une première fois la version qui contient le lot 5 sur un PC plus ancien (le plus simple :
> `Reparer` lancé avec le script **de la nouvelle version**, voir « Passer un PC d'avant
> v0.4.0 aux lots 5 et 6 » plus bas).

Une seule ligne décide de la version : `COGES_IMAGE_TAG`. La mise à jour ne passe que par
des connexions **sortantes** vers le registre public : aucun port à ouvrir sur le PC ni sur
la box du client.

1. **Notez la version actuelle** (commande ci-dessus), pour pouvoir revenir en arrière.
2. Si CoGes fournit un nouveau dossier du programme pour cette version, remplacez **tout**
   le contenu de `C:\CoGes\programme\` par le nouveau. `C:\CoGes\reglages\` ne bouge pas.
3. Changez l'étiquette dans les réglages :

   ```powershell
   notepad C:\CoGes\reglages\coges.env      # COGES_IMAGE_TAG=v1.5.0
   ```

4. Téléchargez, arrêtez l'application, migrez, redémarrez :

   ```powershell
   coges --profile tools pull
   coges stop api worker beat relay front
   coges --profile tools run --rm migrate
   coges up -d
   coges ps
   ```

   La base et Redis restent allumés pendant l'opération. Pendant les quelques minutes
   d'arrêt, le navigateur affiche la page « CoGes revient dans un instant ».

5. Vérifiez la version (commande ci-dessus) et ouvrez `http://localhost`.

### Revenir à la version précédente

Remettez l'ancienne étiquette dans `coges.env` (et l'ancien dossier du programme, s'il
avait été remplacé), puis :

```powershell
coges stop api worker beat relay front
coges up -d
```

**Attention : une migration déjà jouée ne se défait pas.** La règle de CoGes est qu'une
migration reste compatible avec la version précédente de l'application : revenir en
arrière fonctionne donc d'une version à la précédente. Au-delà, ou en cas de doute, il
faut restaurer une sauvegarde faite avant la mise à jour : lancez `-Action Sauvegarder` juste
avant de changer de version, puis `-Action Restaurer` (section « Sauvegarde et restauration »)
avec la version d'avant réinstallée. N'installez une nouvelle version chez un client qu'après
l'avoir essayée sur un PC de test.

---

## Mises à jour (lot 5, ADR 0128)

### Ce qui se passe seul

Le PC **va chercher** la version à installer : aucun port ouvert, aucune connexion entrante.
La tâche planifiée « CoGes - mise à jour » (posée par `Installer` et `Reparer`) :

1. **À 12 h, à 18 h et à l'ouverture de session**, elle lit le canal du PC
   (`deploy/onprem/canal/stable.json` sur GitHub, ou `test.json`). Une version nouvelle est
   **téléchargée pendant que CoGes tourne** dans `C:\CoGes\mises-a-jour\<version>\` : le
   programme (empreinte de son contenu vérifiée), les images `front`, `api` et `worker`
   **par digest** (jamais par l'étiquette : une étiquette qui a bougé est refusée), et les
   images d'accompagnement qui manqueraient. Elle passe alors « prête ». Sans Internet : rien,
   journal seulement.
2. **À 21 h 30** (réglable), si **aucune vente depuis 30 minutes**, elle l'applique ; sinon
   elle réessaie le soir suivant. Jamais au démarrage du PC (elle attend qu'il soit allumé
   depuis 15 minutes), jamais pendant une sauvegarde (verrou commun).
3. L'application, dans l'ordre : sauvegarde chiffrée `-avant-maj` (copiée sur la clé CoGes si
   elle est branchée) ; contrôle des réglages par la **nouvelle** version ; page « CoGes revient
   dans un instant » ; **copie de la base** dans PostgreSQL ; nouveau programme (l'ancien est
   gardé), `COGES_IMAGE_TAG` changé (seule ligne touchée, plus une ligne nouvelle du modèle avec
   sa valeur par défaut si la version en demande une), migrations, démarrage ; vérifications
   (neuf services, page d'accueil, licence, **même nombre** de sociétés et de ventes). Compter
   2 à 5 minutes d'arrêt.
4. **Si quelque chose casse** à partir du nouveau programme : **retour seul** à la version
   d'avant, avec la base d'avant (la copie). Notification et journal : « La mise à jour vers vX
   a échoué ; CoGes est revenu à vY. Rien n'est perdu. » Cette version **ne se réessaie plus
   seule**.
5. Après une mise à jour réussie, la copie de la base et l'ancien programme sont gardés
   **7 jours** (retour possible), puis supprimés.

**Au bout de 3 jours** sans avoir pu s'appliquer (PC éteint à 21 h 30, ventes tardives), un
raccourci « **Mettre CoGes à jour** » apparaît sur le Bureau, avec une notification une fois
par jour au plus : « Une mise à jour de CoGes est prête. Quand vous avez 5 minutes sans client,
double-cliquez sur « Mettre CoGes à jour » sur le Bureau. » Le double-clic ouvre une fenêtre qui
dit ce qui va se passer (« CoGes sera indisponible environ N minutes ; vos données sont
sauvegardées avant »), fait taper `OUI`, joue les mêmes étapes (même retour seul en cas de
problème), puis dit « CoGes est à jour (vX). Vous pouvez reprendre. » ou « La mise à jour a
échoué ; CoGes est revenu à vY. Rien n'est perdu. », et attend Entrée. Le raccourci disparaît
quand la version est appliquée ou abandonnée.

Le réglage du PC est dans `C:\CoGes\reglages\mise-a-jour.json` :

```json
{ "canal": "stable", "automatique": true, "heure": "21:30" }
```

`automatique: false` : la version est téléchargée mais ne s'applique qu'à la main. Pour changer
l'heure ou le canal, passer par le script (il repose la tâche) :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action Reparer -HeureMiseAJour 13:00
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action Reparer -CanalMiseAJour test
```

### Ce que dit `Etat`

`-Action Etat` ajoute : le canal, le mode et l'heure ; le dernier passage sur le canal et ce
qu'il a dit (à jour, nouvelle version, refus et pourquoi) ; la version prête, **depuis combien
de jours elle attend et pourquoi** (« PC éteint ou en veille à 21:30 », « une vente il y a 4
minutes »…) ; la prochaine application prévue ; la dernière mise à jour (réussie, ratée et
revenue seule, ou défaite à la main) ; la copie de la base gardée et sa date de fin.

### Forcer, vérifier, revenir (technicien)

```powershell
# Lire le canal et télécharger maintenant (n'applique rien)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action VerifierMiseAJour
# Appliquer la version prête maintenant (sans attendre 30 minutes sans vente : -Maintenant)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action MettreAJour -Maintenant
# Revenir à la version d'avant la dernière mise à jour (dans les 7 jours)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action RevenirVersionPrecedente
```

`-Simulation` annonce chaque étape sans rien faire. `MettreAJour -Maintenant` reprend aussi une
version marquée en échec (après correction par CoGes, par exemple).

`RevenirVersionPrecedente` remet l'ancien programme, l'ancienne version **et la base telle
qu'elle était juste avant la mise à jour** : les **ventes faites depuis seraient perdues**. Le
script les compte et le dit, fait une sauvegarde `-avant-retour` (elles y restent), puis exige
`REVENIR` et le code de la boutique. La base d'après est gardée (`-Action NettoyerAncienneBase`
la supprime). La version défaite ne s'applique plus seule. **Après 7 jours**, la copie n'existe
plus : `-Action Reparer -Version <ancienne>`, puis `-Action Restaurer` avec la sauvegarde
`-avant-maj` (section « Restaurer »).

| Message (début) | Quoi faire |
|---|---|
| `Le canal « … » ne se lit pas` | Internet ; rien n'a changé, nouvel essai seul |
| `Canal illisible` · `se dit du canal` | prévenir CoGes : le fichier du canal est à republier |
| `Le canal annonce vX, plus ancienne que vY installée` | rien : le canal ne fait jamais redescendre |
| `vX demande d'avoir déjà vM au moins` | `-Action Reparer -Version vM`, puis la mise à jour se fera |
| `vX demande Docker Desktop …` | mettre Docker Desktop à jour (Paramètres > Software updates) |
| `L'étiquette … ne pointe plus vers le digest du canal` · `L'empreinte du programme` | rien n'a changé ; prévenir CoGes |
| `Il ne reste que … Go libres` | libérer de la place (5 Go demandés) |
| `Pas maintenant : une vente il y a …` | relancer plus tard, ou `-Maintenant` boutique fermée |
| `La mise à jour vers vX a échoué ; CoGes est revenu à vY` | rien à faire tout de suite ; envoyer le journal à CoGes |
| `… et le retour à vY aussi. Appelez CoGes.` | **n'effacer rien** ; la sauvegarde et la copie de la base sont gardées |

Journal : `C:\CoGes\journaux\mise-a-jour-AAAAMMJJ.log`, sans aucun secret.

### Publier une version pour les clients (CoGes)

Sur le poste Ubuntu de CoGes, dans le dépôt à jour :

1. **L'étiquette** `vX.Y.Z` est poussée et le workflow « Déployer » a publié ses images sur
   ghcr.io (comme pour la production). Elle doit contenir `windows/mise-a-jour.ps1`.
2. **Le canal `test` d'abord**, pour le PC d'essai de CoGes (réglé par `-CanalMiseAJour test`) :

   ```bash
   git switch -c canal/test-vX.Y.Z origin/main
   python3 deploy/onprem/canal/publier.py --version vX.Y.Z --canal test \
     --depuis-minimum vA.B.C --note "Une ou deux phrases pour le technicien."
   git add deploy/onprem/canal/test.json && git commit -m "chore(onprem): publish vX.Y.Z on the test channel"
   ```

   `--depuis-minimum` : la plus ancienne version installée chez un client qui peut passer
   directement à celle-ci (en général la précédente ; plus haut si une migration l'exige).
   `--docker-desktop-minimum 4.30.0` si la version demande un Docker Desktop récent. Le script
   lit les trois digests sur ghcr.io, télécharge l'archive de l'étiquette, calcule l'empreinte
   et écrit le fichier ; il refuse une version plus ancienne que celle que le fichier annonce.
3. Pull request avec **ce seul fichier**, fusionnée. Le PC d'essai la voit au plus tard au
   passage suivant de 12 h ou 18 h (ou `-Action VerifierMiseAJour`) ; vérifier
   `-Action MettreAJour -Maintenant`, puis une journée de vente normale.
4. **Puis `stable`**, de la même façon (`--canal stable`, fichier `stable.json`) : tous les
   clients l'appliquent les soirs suivants.

Pour arrêter une version en cours de diffusion : publier la suivante (corrigée). Le canal ne
fait jamais redescendre un PC ; un client déjà passé revient par `RevenirVersionPrecedente`.

### Protéger le compte GitHub

Le canal **n'est pas signé** (ADR 0128 ; une signature est prévue, son champ est réservé) :
quiconque peut fusionner sur `main` peut pousser une version chez **tous les clients**. Donc :

- **Double authentification** sur le compte GitHub du propriétaire (application TOTP ou clé de
  sécurité, codes de secours rangés hors ligne) ; aucun jeton d'accès personnel qui puisse
  écrire sur le dépôt sans en avoir besoin.
- **Protection de `main`** (Settings > Branches, ou Rulesets) : pull request obligatoire,
  revue des propriétaires de code exigée (`.github/CODEOWNERS` réserve `deploy/onprem/canal/`
  au propriétaire), **pas de force-push**, pas de suppression de la branche, règles appliquées
  aussi aux administrateurs.
- Personne d'autre que le propriétaire comme administrateur du dépôt.

---

## Dépannage

### Le port 80 est déjà pris

`coges up -d` répond « Ports are not available » ou « address already in use » : un autre
logiciel du PC utilise le port 80 (IIS, Skype, un autre serveur web).

Voir lequel (la dernière colonne est un numéro de processus, à retrouver dans le
Gestionnaire des tâches, onglet Détails) :

```powershell
netstat -ano | findstr ":80 "
```

Le plus simple est de changer le port de CoGes. Dans `coges.env`, section « NE PAS
TOUCHER », changez **les deux lignes ensemble** :

```
COGES_HTTP_PORT=8080
COGES_PUBLIC_URL=http://localhost:8080
```

Relancez le contrôle (étape 5), puis `coges up -d`. CoGes s'ouvre alors sur
**http://localhost:8080**.

### Une ligne de `coges ps` n'est pas « healthy »

- Attendez deux minutes après un démarrage : les sondes ne passent qu'une fois par minute.
- `coges logs --tail 80 <service>` montre la raison.
- `api` qui redémarre en boucle avec « COGES_… » dans ses journaux : un réglage manque ou
  est faux. Relancez le contrôle (étape 5).
- `worker`, `beat` ou `relay` en erreur juste après l'installation : les migrations n'ont
  pas été jouées (étape 6).
- Un service bloqué est relancé tout seul par `autoheal` au bout de quelques minutes.

### La page « CoGes revient dans un instant »

`front` ou `api` est arrêté ou en cours de démarrage : `coges ps`, puis `coges up -d`.

### La base s'est arrêtée

Après une panne (coupure de courant, PC éteint brutalement), PostgreSQL redémarre seul et
répare son journal : rien à faire. En revanche, un conteneur arrêté **à la main**
(`docker stop`, `docker kill`, bouton « Stop » de Docker Desktop) n'est jamais relancé par
Docker : `coges up -d` le ramène.

### Le PC rame

`docker stats --no-stream` : au repos, CoGes utilise environ 750 Mo ; ses plafonds
cumulés sont de 2,7 Go. Docker Desktop ne donne par défaut que la moitié de la mémoire du
PC (4 Go sur 8) : c'est suffisant. Si le PC n'a que 8 Go, fermez les logiciels lourds.

### « Docker Desktop ne tourne pas »

Toute action du script qui a besoin de Docker le vérifie d'abord et s'arrête **sans rien
changer** : « Docker Desktop ne tourne pas : ouvrez-le et attendez « Engine running », puis
relancez. Rien n'a changé. » Ouvrez Docker Desktop par le menu Démarrer, attendez « Engine
running » en bas à gauche, puis relancez la même commande. `-Action Etat` le dit aussi, et
montre quand même ce qu'il lit dans les fichiers (sauvegardes, version).

### Docker Desktop ne démarre plus (« Docker Desktop is unable to start »)

> **Jamais** « Clean / Purge data » ni « Reset to factory defaults » (menu de dépannage de
> Docker Desktop, l'icône d'insecte) : ils **effacent la base du client**. Pas non plus
> « Uninstall » de Docker Desktop.

Dans l'ordre, en relançant Docker Desktop après chaque étape :

1. Quitter Docker Desktop : clic droit sur son icône près de l'horloge, « Quit Docker
   Desktop ». Attendre une minute.
2. Arrêter WSL : dans PowerShell, `wsl --shutdown`, puis rouvrir Docker Desktop.
3. Place sur le disque : il faut plusieurs Go libres sur `C:` (`-Action Etat` affiche le
   disque libre en rouge sous 5 Go). Vider la Corbeille et les Téléchargements.
4. Redémarrer le PC (Démarrer > Marche/Arrêt > **Redémarrer**, pas « Arrêter »).
5. Mettre WSL à jour : PowerShell **en administrateur**, `wsl --update`, puis redémarrer le PC.

Si rien n'y fait, appelez CoGes avec une capture du message : les données sont dans le
disque virtuel de Docker Desktop, et les sauvegardes dans `C:\CoGes\sauvegardes\` et sur la
clé CoGes.

### Tout réinstaller sur un PC de test

**Efface toutes les données** : à ne faire que sur un PC d'essai.

```powershell
coges --profile tools down -v
```

Puis reprenez à l'étape 6. Les mots de passe de `coges.env` peuvent alors changer.

---

## Sauvegarde et restauration (lot 4, ADR 0127)

### Ce qui se fait tout seul

- **Deux sauvegardes par jour**, à **13 h 00** et à **20 h 30**, par la tâche planifiée
  « CoGes - sauvegarde » (posée par `Installer` et `Reparer`). Si le PC était éteint à
  l'heure prévue, elle se fait au démarrage suivant ; au démarrage aussi si la dernière a plus
  de 20 heures. CoGes reste ouvert pendant ce temps (aucune coupure).
- Chaque sauvegarde est la **base entière**, **chiffrée** par la clé publique du client :
  le PC peut chiffrer mais pas relire. Elle va dans `C:\CoGes\sauvegardes\` :
  `coges-<code>-AAAAMMJJ-HHMM-<version>.coges`, avec `.sha256` (empreinte) et
  `.manifest.json` (date, version, lignes comptées). Une sauvegarde faite **avant une
  action** le dit à la fin de son nom : `-avant-effacement`, `-avant-restauration`,
  `-avant-maj`, `-avant-retour`, et `-installation` pour la première, celle d'une base
  **neuve et vide**. Elles sont gardées, copiées et effacées comme les autres. Aucun fichier en clair ne touche le
  disque du PC ni la clé USB.
- Le PC garde les **14 dernières**, plus une par semaine sur 8 semaines, plus une par mois
  sur 12 mois. Une sauvegarde ratée est marquée `.echec` et gardée pour l'enquête.
- **Le dimanche** (ou au premier démarrage après), la sauvegarde est **restaurée pour
  essai** dans une base temporaire, contrôlée comme celle de la production, puis effacée.
- Pas sauvegardés : Redis (file d'attente, cache), Caddy, les fichiers statiques, l'état de
  beat, les modèles de prévision (refaits chaque lundi nuit ; les prévisions elles-mêmes sont
  en base). Ni `coges.env` : il reste dans le gestionnaire de mots de passe de CoGes.

### La clé USB du client

Le technicien prépare une clé USB (ou un disque externe) **pour cette boutique** :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action PreparerDisque -Lecteur E: -CodeBoutique boutique-diallo
```

Il écrit `COGES-SAUVEGARDE.txt` (le code de la boutique) à la racine de la clé, vérifie la
place et y fait une première copie. Ensuite, **à chaque sauvegarde où la clé est branchée**,
la dernière y est copiée dans `E:\CoGes\` puis relue ; la clé en garde 10. Une clé **sans**
ce fichier (ou celle d'une autre boutique) n'est jamais touchée. Le commerçant n'a qu'à la
brancher de temps en temps, et la ranger **hors du magasin**.

### Ce que dit `Etat`

`-Action Etat` ajoute : la dernière sauvegarde (date, taille), la dernière copie hors du PC,
la dernière restauration d'essai (réussie ou non), le nombre de fichiers gardés, une ancienne
base gardée après une restauration, et ce qu'il faut faire.

### Quand Windows prévient

Une notification « CoGes » ne s'affiche **que s'il faut agir** :

| Message | Quoi faire |
|---|---|
| « CoGes n'a pas pu sauvegarder vos données depuis 2 jours… » | `-Action Etat`, puis `-Action Sauvegarder` ; lire `C:\CoGes\journaux\sauvegarde-*.log` |
| « Branchez la clé CoGes… » | brancher la clé préparée ; la copie se fait à la sauvegarde suivante |
| « Le disque du PC est presque plein… » | libérer de la place (moins de 5 Go libres) |
| « La dernière sauvegarde ne se relit pas : appelez CoGes. » | `-Action Etat`, journal du jour, puis `-Action Sauvegarder -Essai` |

### La clé de sauvegarde (une par client)

La **clé privée** relit les sauvegardes : elle n'est **jamais** sur le PC du client. Rangez-la
dans le gestionnaire de mots de passe de CoGes (fiche du client, à côté de `coges.env`), avec
une copie hors ligne. **Perdue, aucune sauvegarde de ce client ne se relit.**

De préférence, tirez la paire **chez CoGes**, sur un poste Linux avec Docker (image `worker`
de la version installée, réseau coupé) :

```bash
mkdir -p ~/cles-coges && docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD/deploy/onprem/sauvegarde:/srv/onprem/sauvegarde:ro" -v ~/cles-coges:/cles \
  --entrypoint python ghcr.io/papa-bothie/coges/worker:vX.Y.Z -I \
  /srv/onprem/sauvegarde/coffre.py paire --prive /cles/boutique-diallo.cle --publique /cles/boutique-diallo.pub
```

Puis, sur le PC : `-Action Installer … -ClePublique E:\boutique-diallo.pub` (ou `-Action
Reparer -ClePublique …` sur un PC déjà installé). Seule la **publique** est posée, dans
`C:\CoGes\reglages\cle-publique-sauvegarde.txt`.

Sans `-ClePublique`, le script tire la paire sur place : la clé privée est écrite dans un
fichier sur le **disque amovible** donné par `-LecteurCle E:` (jamais à l'écran, dans le
journal ni dans le presse-papiers), puis il demande `COPIE-FAITE`. Rangez le fichier chez
CoGes, puis effacez-le de la clé USB.

### Restaurer (technicien)

Sur le **même PC** (après une erreur, une panne) ou sur un **PC neuf** (installé d'abord
par `-Action Installer`, même code de boutique) :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action Restaurer -Cle E:\boutique-diallo.cle
```

Sans `-Fichier`, le script liste les sauvegardes du PC **et** de la clé CoGes branchée, la
plus récente en haut, avec pour chacune la date, la version, le nombre de ventes et de
sociétés, l'origine (PC ou clé) et la raison (« installation : base neuve »…), puis fait
choisir **par numéro**. Avec `-Fichier <chemin du .coges>`, la sauvegarde est prise
directement.

> **La plus récente n'est pas toujours la bonne.** Après `Desinstaller -EffacerLesDonnees`
> puis `Installer`, la dernière sauvegarde est celle de la base neuve et vide
> (`-installation`, 0 vente). Regardez le nombre de ventes avant de choisir.

Dans l'ordre, chaque étape s'arrête au premier problème **sans rien changer** :

1. empreinte et manifeste ; récapitulatif (boutique, date, version, ventes de la sauvegarde
   et de ce PC) ; taper `RESTAURER`. Si la sauvegarde n'a **aucune vente**, ou **moins de
   ventes** que la base actuelle, le script dit combien seraient perdues et exige
   `RESTAURER-QUAND-MEME` ;
2. version : une sauvegarde **plus récente** que le programme est refusée (« installez d'abord
   la version vX.Y.Z », `-Action Reparer -Version vX.Y.Z`) ; plus ancienne, la base est mise
   à jour après ;
3. la base actuelle est **sauvegardée d'abord** ;
4. la sauvegarde est déchiffrée **dans un conteneur** (la clé privée passe par l'entrée
   standard, jamais copiée sur le PC), restaurée **à côté** (`coges_restauration`), contrôlée ;
5. l'application s'arrête (page « CoGes revient dans un instant »), les bases sont échangées :
   l'ancienne devient `coges_avant_AAAAMMJJ_HHMM` ;
6. démarrage, licence relue (elle revient **avec** la base : ni `create-company` ni
   `activate-license` à refaire), page d'accueil ;
7. en cas d'échec après l'échange : **retour automatique** à l'ancienne base.

Chacun se reconnecte avec le mot de passe qu'il avait au moment de la sauvegarde. Un
`coges.env` neuf (PC neuf) convient : les rôles de la base viennent de l'installation, pas de
la sauvegarde. L'ancienne base reste là tant qu'on ne lance pas `-Action
NettoyerAncienneBase` (code de la boutique retapé) ; `Etat` la signale.

`-Action Sauvegarder`, `Restaurer`, l'essai du dimanche, la tâche de démarrage et `Reparer`
partagent un **verrou** (`C:\CoGes\coges.verrou`) : une action qui le trouve pris attend ou
s'arrête en disant laquelle tourne. Un verrou laissé par un programme arrêté se libère seul.

---

## Support à distance (lot 6, ADR 0129)

Chaque PC dit à CoGes « je vais bien » ou « ceci a échoué ». Il envoie un court résumé
technique à un service de pings « homme mort » (Healthchecks.io), le même genre que celui de la
production (ADR 0077). Le PC **envoie** et n'écoute rien : aucun port ouvert, aucune commande
reçue. Ce qui sort est la liste fermée de `deploy/onprem/support/champs.txt` (versions,
services, licence, dates des sauvegardes, disque, nombre d'erreurs). Aucune donnée
commerciale, aucun nom : la liste et ce qui ne sort jamais sont dans l'ADR 0129 et dans
l'annexe du contrat (`docs/contrat/annexe-donnees-sur-site.md`), à joindre au contrat.

### Pour un nouveau client : créer les trois checks

Dans Healthchecks.io (compte de CoGes), créez un projet par client, ou une étiquette par
client dans un projet commun. Ajoutez-y trois checks, nommés par le numéro de client de
CoGes, **jamais** par le nom de la boutique :

| Check | Période | Tolérance | Ce qu'il dit |
|---|---|---|---|
| `<client>-vie` | 1 jour | 3 jours | le PC est allumé et CoGes démarre (ouverture de session, et 13 h 00 / 20 h 30) |
| `<client>-sauvegarde` | 1 jour | 2 jours | chaque sauvegarde, réussie ou ratée (`/fail`) |
| `<client>-mise-a-jour` | 30 jours | 30 jours | chaque mise à jour ; `/fail` au retour arrière, au retour raté, ou si une version attend plus de 3 jours |

Branchez les alertes du compte (e-mail, Telegram…). Copiez l'**adresse de ping** de chaque
check (`https://hc-ping.com/<uuid>`). C'est un secret : celui qui la connaît peut envoyer de
faux « je vais bien ». Gardez-la dans le gestionnaire de mots de passe, avec le `coges.env`
du client.

### Préparer `support.json` (chez CoGes)

```json
{
  "adresses": {
    "vie": "https://hc-ping.com/<uuid du check vie>",
    "sauvegarde": "https://hc-ping.com/<uuid du check sauvegarde>",
    "mise-a-jour": "https://hc-ping.com/<uuid du check mise-a-jour>"
  },
  "telephone_coges": "+221 xx xxx xx xx"
}
```

Sur la clé USB du technicien, par exemple `E:\support.json`.

#### Passer un PC d'avant v0.4.0 aux lots 5 et 6

Un PC installé en v0.3.0 ou avant garde le script de sa version, dans
`C:\CoGes\programme\windows\`. Ce script ne connaît ni `-Support`, ni `-CanalMiseAJour`, ni
`TesterSupport`, et il refuse ces options. Téléchargez d'abord `installer.ps1` de v0.4.0, et
lancez `Reparer` **avec ce script-là**. `Reparer` pose alors le programme de v0.4.0 dans
`C:\CoGes\programme\`, et les commandes suivantes passent par lui.

```powershell
# 1. Sauvegarde juste avant (script déjà installé, il connaît Sauvegarder depuis le lot 4)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action Sauvegarder
# 2. Le script de v0.4.0
Invoke-WebRequest https://raw.githubusercontent.com/papa-bothie/CoGes/v0.4.0/deploy/onprem/windows/installer.ps1 -OutFile $env:TEMP\coges-install.ps1 -UseBasicParsing
# 3. Passage à v0.4.0, adresses de ping posées. Sur le PC d'essai de CoGes, ajoutez -CanalMiseAJour test
#    (un PC de client reste sur stable, le défaut).
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\coges-install.ps1 -Action Reparer -Version v0.4.0 -Support E:\support.json -CanalMiseAJour test
# 4. Essai, avec le script maintenant installé
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action TesterSupport
```

Les mises à jour suivantes arrivent ensuite par le canal (section « Mises à jour »).

#### PC déjà en v0.4.0 ou plus

```powershell
# À l'installation (facultatif) ou plus tard :
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action Reparer -Support E:\support.json
# Sans Reparer (seulement les adresses) : -Action ConfigurerSupport -Support E:\support.json, ou en questions : -Action ConfigurerSupport
# Essai : un ping « test » sur les trois checks, et lequel a répondu
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CoGes\programme\windows\installer.ps1 -Action TesterSupport
```

Le script garde l'identifiant du PC (tiré à l'installation, `C:\CoGes\reglages\support.json`),
les adresses et le numéro. Notez dans la fiche du client l'identifiant que montre le
diagnostic (ligne `pc:`). Pour couper la remontée : `"remontee": false` dans ce fichier.

### Ce que je reçois, et quand

| Moment | Signal |
|---|---|
| ouverture de session Windows (+ démarrage de CoGes) | `vie` ; `/fail` si Docker ne répond pas en 5 minutes (`docker-arrete`) ou si `up -d` échoue (`demarrage`) |
| 13 h 00, 20 h 30 (tâche de sauvegarde), et l'ouverture de session | `vie` à chaque passage, puis `sauvegarde` s'il a sauvegardé ; `/fail` si elle a raté (`place-disque`, `cle-absente`, `taille`, `empreinte`, `autre`…), si Docker est arrêté à l'heure prévue, ou si l'essai du dimanche rate (`essai-rate`) |
| `-Action Sauvegarder` | `sauvegarde` ou `/fail` |
| mise à jour appliquée | `mise-a-jour` ; `/fail` `retour-arriere` (revenue seule), `retour-rate` (retour raté : urgent) |
| version prête depuis plus de 3 jours | `/fail` `attente-3-jours`, une fois par jour |

Chaque corps est le résumé : quelques lignes `nom: valeur` (voir « Lire un diagnostic »). Un
ping qui ne part pas (Internet coupé) n'arrête jamais rien : il est noté au journal, et `Etat`
dit « Dernier envoi raté ».

### Que faire à chaque alerte

| Alerte | Quoi faire |
|---|---|
| `vie` en silence (3 jours) | appeler le client : PC éteint, fermé, Internet coupé ? Sinon « Aide CoGes » puis `Etat` |
| `vie` `/fail` `docker-arrete` | Docker Desktop ne démarre plus : voir « Docker Desktop ne démarre plus » (dépannage) |
| `sauvegarde` `/fail` `place-disque` | libérer de la place sur le PC (jamais « Clean / Purge data » de Docker Desktop) |
| `sauvegarde` `/fail` `cle-absente`, `taille`, `empreinte` | à distance : `Diagnostic`, lire `journaux\sauvegarde-*.log` |
| `sauvegarde` `/fail` `essai-rate` | la sauvegarde est là mais ne se relit pas : `Diagnostic`, puis `-Action Sauvegarder -Essai` |
| `sauvegarde` en silence | la tâche ne tourne plus : `Etat`, puis `-Action Reparer` (repose les tâches) |
| résumé avec `copie_le` vieux de plus de 7 jours | demander au client de brancher la clé CoGes |
| `mise-a-jour` `/fail` `retour-arriere` | rien n'est perdu ; lire le diagnostic, corriger la version, ne pas la republier telle quelle |
| `mise-a-jour` `/fail` `retour-rate` | **urgent** : prise en main, `Etat`, ne rien effacer (ADR 0128) |
| `mise-a-jour` `/fail` `attente-3-jours` | PC éteint le soir ou boutique jamais calme : demander au client le raccourci « Mettre CoGes à jour » |

### Aider avec l'Assistance rapide

1. Le client double-clique sur **« Aide CoGes »** (Bureau). L'Assistance rapide s'ouvre, et une
   fenêtre dit d'appeler CoGes, de donner le code et d'accepter. Si l'Assistance rapide manque,
   la fenêtre dit de l'installer depuis le Microsoft Store (« Assistance rapide »), et le Store
   s'ouvre sur elle.
2. Chez vous : ouvrez l'Assistance rapide, choisissez **« Aider quelqu'un »**, et dictez le code
   au client.
3. Demandez le **contrôle total**. Le client accepte, il voit tout et peut arrêter.
4. Dans une fenêtre PowerShell du PC : `-Action Etat -CodeBoutique <code>`, `-Action Diagnostic`
   (le zip arrive sur le Bureau du client : il vous l'envoie), `-Action TesterSupport`,
   `-Action Reparer`.

**Jamais à distance** : « Clean / Purge data » ou « Reset to factory defaults » dans Docker
Desktop (efface toutes les données), `-Action Desinstaller -EffacerLesDonnees`, désinstaller
Docker Desktop ou WSL, `docker volume rm`, `-Action Restaurer` sans avoir parlé au client des
ventes perdues. Rien n'est installé pour un accès sans présence : chaque séance demande un
nouveau code au client.

### Lire un diagnostic

Le client double-clique sur **« Diagnostic CoGes »**. Une minute plus tard, le fichier
`CoGes-diagnostic-AAAAMMJJ-HHMM.zip` est sur son Bureau (10 Mo au plus), et l'Explorateur
s'ouvre dessus. Il vous l'envoie par WhatsApp ou par e-mail. Dedans :

| Fichier | Ce qu'il dit |
|---|---|
| `resume.txt` | le résumé tel qu'envoyé aux pings (ligne `pc:` = identifiant du PC) |
| `etat.txt` | la sortie de `Etat` (versions, services, sauvegardes, mises à jour, remontée) |
| `docker.txt` | `coges ps`, `docker version`, `docker info` abrégé, WSL, Windows |
| `services\<service>.log` | les 300 dernières lignes de chaque service (moins si le zip dépasse 10 Mo), secrets masqués |
| `journaux\` | les journaux du script des 7 derniers jours (installation, démarrage, sauvegarde, mise à jour, support) |
| `reglages.txt` | les **noms** des réglages de `coges.env` (jamais les valeurs), `support.json` sans adresses, `mise-a-jour.json` |
| `sauvegardes.txt` | noms, tailles et dates des sauvegardes du PC |
| `systeme.txt` | disque, mémoire, tâches planifiées et leur dernier résultat |

Commencez par `resume.txt` et `etat.txt`, puis le journal du sujet, et les lignes `[ECHEC]`.
Aucun mot de passe n'y est (ils sont remplacés par `********`), ni aucune vente.

### Les journaux ne remplissent pas le disque

`C:\CoGes\journaux` : la tâche de sauvegarde supprime les fichiers de plus de 60 jours, puis
garde au plus 200 Mo (les plus anciens partent d'abord). Elle ne supprime jamais le journal du
jour. `Etat` dit leur taille. Les journaux des conteneurs sont plafonnés par Docker (10 Mo × 3
par service).

## Ce que le sur-site ne fait pas

| Sujet | Pourquoi |
|---|---|
| Photos des articles | elles passent par un service en ligne (Cloudinary), éteint sur site |
| E-mails (mot de passe oublié, alertes) | aucun serveur d'e-mail sur le PC |
| Notifications sur le téléphone | Web Push demande un service en ligne et l'accès depuis le téléphone |
| Administration de la plateforme | absente du PC (`/api/v1/platform/*` répond 404) ; la licence se pose par la CLI (lot 2) |
| Accès depuis un autre appareil (téléphone, second PC) | CoGes n'écoute que `127.0.0.1` : rien n'est joignable depuis le réseau du magasin |
| Inscription libre-service, Sentry | éteints |
| Commandes à distance sans personne devant | volontairement : agir passe par l'Assistance rapide, avec l'accord du commerçant |

## Pour l'équipe : vérifier sur Linux

`deploy/onprem-ci/verifier.sh` joue ce guide de bout en bout sur un poste Linux ou dans le
workflow « Sur site » : réglages, contrôle, migrations (deux fois), démarrage, société,
licence et `license-status`, parcours Chromium (connexion, rechargement, service worker,
vente), tâches planifiées, tâche de nuit des abonnements à +45 jours (la société licenciée se connecte toujours, une
société témoin sans licence est suspendue), arrêt et redémarrage, changement de version,
arrêt brutal de PostgreSQL ; puis, par le vrai script Windows sous `pwsh` : sauvegarde avec
restauration d'essai et copie sur un « disque » préparé, `down -v` et réglages neufs,
restauration (mêmes lignes, licence revenue), fichier abîmé et révision inconnue refusés,
échec simulé après la bascule (retour à l'ancienne base), nettoyage ; enfin le support à
distance (lot 6) : un faux service de pings local reçoit `TesterSupport`, une sauvegarde
réussie, une sauvegarde ratée exprès (`/fail` `cle-absente`) et `vie` ; chaque corps est relu
par la liste fermée (`controle_remontee.py`), puis un diagnostic est fouillé (aucune valeur du
`coges.env`, aucun nom de la base).

```bash
ONPREM_REGISTRY=coges-local ONPREM_PORT=8080 deploy/onprem-ci/verifier.sh
```

`deploy/onprem-ci/verifier-mises-a-jour.sh` joue les mises à jour (lot 5) par le vrai script
sous `pwsh` : un registre local reçoit trois versions faites des images construites
(`v0.90.1`, `v0.90.2`, et `v0.90.3` à migration cassée), `publier.py` écrit les canaux ; canal
faux refusé sans rien tirer, mise à jour avec données identiques, vente puis
`RevenirVersionPrecedente`, migration cassée et retour automatique ; le faux service de pings
reçoit `mise-a-jour` après la réussite et `/fail` `retour-arriere` après la migration cassée.

```bash
ONPREM_REGISTRY=coges-local ONPREM_PORT=8080 deploy/onprem-ci/verifier-mises-a-jour.sh
```
