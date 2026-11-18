# Lot 3 — Installation en une commande : script d'installation Windows

> À donner à l'agent Claude Code, dans le dépôt `CoGes`, sur une branche `feat/sur-site-installation-windows`
> partie de `main` (lots 1 et 2 fusionnés : PR #92 et #93). Un seul lot, une seule PR.
> Suite de `docs/prompt-sur-site/01-assemblage.md` et `02-licence.md` : **mêmes règles**, rien à rediscuter.

## But

Aujourd'hui, installer CoGes sur un PC Windows = suivre les étapes 1 à 11 de
`docs/runbooks/sur-site.md`, une commande à la fois. Ce lot les **enchaîne dans un script
PowerShell** : le technicien lance une commande, répond à quelques questions, et au bout
`http://localhost` s'ouvre sur une société créée, une licence posée, un raccourci sur le Bureau.

Public visé : **le propriétaire de CoGes, qui installe chez un client** (pas le commerçant).
Messages du script en **français simple**, sans jargon, sans trace Python ni Docker brute :
chaque échec dit *ce qui ne va pas* et *quoi faire*.

## Règles d'or (valables pour tout le lot)

1. **Ajouter, ne rien modifier** (ADR 0124). Aucun fichier de `deploy/vps/**`, `backend/app/**`,
   `frontend/**`, `backend/migrations/**`, ni le job `vps`/`ci.yml`/`deploy.yml`. **Aucune nouvelle
   dérogation** dans `check_protected_paths.py` : ce lot n'en a pas besoin. S'il en faut une, **stop**
   et demande.
2. **Les utilisateurs actuels ne voient aucune différence** : pas de nouvelle image, pas de nouvelle
   variable pour l'application, rien dans le code qui tourne en ligne.
3. **Jamais la production** : le script n'écrit, ne lit, ne contacte rien de la production ; il passe
   par `check_onprem_env.py` (déjà là) avant tout démarrage.
4. **Jamais d'écrasement des réglages ni des données** (les « trois endroits » du guide) : `coges.env`
   existant n'est jamais réécrit ; aucun `down -v` ni suppression de volume sans confirmation
   explicite (voir bloc F).
5. **Aucun secret dans un journal, un message, un argument de ligne de commande ni l'historique
   PowerShell.** Le mot de passe du gérant ne passe jamais par `--password`.
6. **Tu ne peux pas tester sur Windows** : ni toi ni la CI Linux. Écris le script pour être *prouvable
   sans Docker* (fonctions pures, tests Pester, mode simulation) et **liste honnêtement dans la PR ce
   que le propriétaire doit vérifier sur le vrai PC** (voir « Livrable »).

## Avant d'écrire (lis les vrais fichiers, ne devine pas)

- `docs/runbooks/sur-site.md` (étapes 1–11 : ce que le script doit automatiser, et leurs messages d'erreur)
- `deploy/onprem/coges.env.example`, `check_onprem_env.py` (règles exactes : 8 secrets hexadécimaux de
  64 caractères tous différents, `COGES_MFA_ENCRYPTION_KEY` en base64 url-safe 43 caractères, `COGES_IMAGE_TAG`
  ni vide ni `latest`, `COGES_HTTP_PORT` et `COGES_PUBLIC_URL` concordants), `docker-compose.yml` (profil `tools`,
  services `migrate` et `cli`), `.gitattributes`
- `backend/app/cli.py` : **comment `create-company` obtient le mot de passe** (invite sans écho ? lecture
  d'une variable ?) et ses codes de retour — le bloc E en dépend
- `deploy/onprem/check_protected_paths.py` et les tests `backend/tests/unit/test_onprem_*.py` : **quels
  fichiers de `deploy/onprem/` sont comptés ou comparés** (liste de fichiers livrés, par exemple). Si un
  test fige le contenu du dossier, mets-le à jour *dans la même PR* en ajout seulement.
- `deploy/onprem-ci/verifier.sh` et `.github/workflows/onprem.yml` (style, et ce que la CI rejoue déjà)
- `CLAUDE.md` : une phase à la fois, ADR dans `docs/decisions`, commits Conventional Commits en anglais,
  **pas de push ni de fusion sans mon accord**.

## Où vont les fichiers

```
deploy/onprem/windows/            ← livré avec le programme (il est copié dans C:\CoGes\programme\windows\)
  installer.ps1                   ← le point d'entrée : une commande, quatre actions (bloc A)
  CoGes.Install.ps1               ← les fonctions (dot-sourcées par installer.ps1 et par les tests)
  tests/CoGes.Install.Tests.ps1   ← Pester
docs/decisions/0126-installation-windows-sur-site.md
docs/runbooks/sur-site.md         ← section « Installer en une commande » en tête ; étapes manuelles gardées
docs/prompt-sur-site/README.md    ← ligne du lot 3 + liste de vérifications Windows du lot 3
.github/workflows/onprem.yml      ← deux jobs ajoutés (bloc G) ; le job `onprem` existant n'est pas touché
```

Contraintes de forme : **compatible Windows PowerShell 5.1** (celui de Windows 11, pas PowerShell 7 : pas de
`??`, pas de ternaire, pas de `&&`) ; fichiers `.ps1` en **UTF-8 avec BOM** (sinon les accents se
corrompent en 5.1) mais **fins de ligne LF** ; `Set-StrictMode -Version Latest` et `$ErrorActionPreference = 'Stop'`.
Écris `coges.env` en **UTF-8 sans BOM** (un BOM casserait la première ligne) — **piège classique de
`Set-Content -Encoding UTF8` en 5.1** : utilise `[IO.File]::WriteAllText(path, text, (New-Object Text.UTF8Encoding $false))`.

## Bloc A — Le point d'entrée

Commande donnée au technicien (à mettre en tête du guide) : **deux lignes**, pas de `| iex` (on lit le
script avant de l'exécuter, et un script téléchargé ne passe pas dans un tuyau) :

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/papa-bothie/CoGes/<TAG>/deploy/onprem/windows/installer.ps1 -OutFile $env:TEMP\coges-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\coges-install.ps1 -Version <TAG>
```

Le dépôt est public : aucun jeton. `<TAG>` est une étiquette `vX.Y.Z` qui **existe**.
Le script **ne demande pas** les droits d'administrateur (créer `C:\CoGes`, une tâche à l'ouverture de
session et un raccourci n'en ont pas besoin) ; il tourne avec l'utilisateur qui a Docker Desktop.

Paramètres :

| Paramètre | Rôle |
|---|---|
| `-Version vX.Y.Z` | obligatoire pour `Installer` ; refusée si vide, `latest`, ou pas au format `vX.Y.Z` |
| `-Action` | `Installer` (défaut), `Reparer`, `Etat`, `Desinstaller` |
| `-Simulation` | affiche ce qui serait fait, **n'écrit rien, ne lance rien** (testable sans Docker) |
| `-Racine` | `C:\CoGes` par défaut ; sert aux tests |
| `-Port` | force le port (sinon 80, puis 8080 si pris, bloc C) |
| `-NonInteractif` | refuse de poser une question : toute donnée manquante est un échec clair (pour les tests) |

Les questions posées (une seule fois, `Read-Host`) : nom de la boutique, code de la boutique (proposé à
partir du nom, validé `^[a-z0-9]+(-[a-z0-9]+)*$`), nom du gérant, téléphone **ou** e-mail du gérant, offre
(`starter`/`business`/`premium`, avec rappel : 3/7/10 comptes), note de contrat (date du contrat et fin de
maintenance : **obligatoire**, c'est la trace du contrat). Un récapitulatif, puis « Tapez OUI pour
continuer ».

**Idempotent** : relancer `Installer` sur un PC déjà installé ne casse rien, ne recrée rien, ne repose pas
de licence (« rien à faire »), reprend là où l'échec s'est produit. Le script **déduit** l'état de ce qu'il
voit (fichiers, conteneurs, `license-status`), il n'écrit pas de fichier d'état qui pourrait mentir.

## Bloc B — Vérifier le PC avant de toucher à quoi que ce soit

Dans l'ordre, **chaque contrôle s'arrête au premier échec** avec *quoi faire* :

1. Windows 11 (build ≥ 22000), 64 bits.
2. Mémoire ≥ 8 Go (`Win32_ComputerSystem`), disque libre ≥ 20 Go sur le lecteur de `-Racine`.
3. Virtualisation activée (`Win32_Processor.VirtualizationFirmwareEnabled`) ; sinon : « Activez Intel VT-x / AMD-V dans le BIOS ».
4. `docker` existe, `docker version` répond (le moteur tourne), moteur **Linux** (WSL 2), `docker compose version` répond.
   **Le script n'installe pas Docker Desktop** : sa licence dépend de la taille de l'entreprise cliente
   (ADR 0124) ; il affiche le lien officiel et s'arrête. Si Docker Desktop est installé mais éteint, il le dit.
5. L'utilisateur est dans `docker-users` si `docker` refuse l'accès (message dédié).
6. Internet joignable *pour ce jour-là* : `ghcr.io` et `github.com` répondent. Message dédié si un proxy ou un pare-feu
   bloque (aucune variable proxy inventée).
7. L'étiquette `-Version` existe **pour les trois images** (`docker manifest inspect ghcr.io/papa-bothie/coges/{front,api,worker}:<TAG>`).
8. **Cette version contient `activate-license`** : après avoir tiré l'image `api`,
   `docker run --rm --network none --entrypoint python …/api:<TAG> -m app.cli --help` doit citer `activate-license`
   et `license-status`. Sinon : « Cette version est antérieure à la licence sur site ; prenez une version plus récente. »

## Bloc C — Poser le programme, les réglages, le port

- **Programme** (`<Racine>\programme\`) : télécharge l'archive du dépôt à l'étiquette
  (`https://github.com/papa-bothie/CoGes/archive/refs/tags/<TAG>.zip`), l'extrait dans un dossier temporaire,
  **ne copie que `deploy/onprem/`** (et pas le reste du dépôt) vers `programme\`, en remplaçant le dossier
  en entier (fonction `Install-Programme`, **réutilisable telle quelle par le lot 5** : elle ne touche jamais
  à `reglages\`). Vérifie la présence de `docker-compose.yml`, `Caddyfile`, `maintenance.html`,
  `check_onprem_env.py`, `postgres-init\01-roles.sql` ; vérifie que `Caddyfile` et `01-roles.sql` **n'ont pas
  de `\r`** (LF conservé). Supprime le temporaire.
- **Réglages** (`<Racine>\reglages\coges.env`) : **si le fichier existe, on n'y touche pas** (sauf
  `COGES_IMAGE_TAG` en cas de `-Version` différente, par `Reparer`, jamais en `Installer`). Sinon on le crée
  depuis `coges.env.example` : `COGES_IMAGE_TAG` = `-Version`, **8 secrets distincts** de 32 octets aléatoires
  en hexadécimal (64 car.), `COGES_MFA_ENCRYPTION_KEY` en base64 url-safe sans `=` (43 car.), tirés de
  `RandomNumberGenerator` (jamais `Get-Random`). Les 2 lignes `PORT`/`URL` à jour (bloc ci-dessous).
  Droits du fichier restreints à l'utilisateur courant, `SYSTEM` et `Administrateurs`
  (`icacls /inheritance:r /grant:r …`). **Aucune valeur n'est affichée** ; le script dit seulement « 9 réglages
  secrets créés ».
- **Rappel de copie** : le script s'arrête et dit « Copiez `C:\CoGes\reglages\coges.env` dans le gestionnaire de
  mots de passe de CoGes **maintenant** : sans lui, la base de ce client ne s'ouvre plus. Tapez COPIE-FAITE. »
  (pas de contournement, y compris en `-NonInteractif` : dans ce cas, l'option `-CopieFaite` doit être passée explicitement).
- **Port** : si `-Port` absent, teste 80 (`Get-NetTCPConnection -State Listen`). Libre → 80. Pris → dit
  *quel processus* (`Get-Process -Id`), puis choisit 8080 (ou le premier libre au-dessus), met **les deux
  lignes** `COGES_HTTP_PORT` et `COGES_PUBLIC_URL` à jour **avant** le contrôle des réglages. L'adresse finale est
  gardée pour le raccourci et le message de fin.
- **Contrôle** : lance `check_onprem_env.py` comme l'étape 5 du guide (`docker run --rm --network none`, deux
  dossiers montés en lecture seule, image `worker` du tag). Des `REFUS` : les afficher mot pour mot, s'arrêter.

## Bloc D — Images, migrations, démarrage

Dans l'ordre du guide, **jamais autrement** : `pull` → contrôle des réglages (bloc C) → `migrate` → `up -d`.
Appelle docker avec la même ligne que la fonction `coges` du guide :
`docker compose --env-file <reglages>\coges.env -f <programme>\docker-compose.yml …`.

- Montre une progression lisible pour le `pull` (plusieurs minutes, ~2 Go) ; résume `migrate` en une ligne.
- Attend que les 9 services soient `healthy` (`docker compose ps --format json`), **5 minutes au plus**, en
  disant lequel attend. Au dépassement : affiche les 40 dernières lignes du journal du service en cause
  (`coges logs --tail 40 <service>`) **sans les variables d'environnement**, et sort en échec.
- Si `up -d` répond « port already allocated » malgré le bloc C (course) : relance le choix de port **une fois**.

## Bloc E — Société, licence, vérification

- **Société** : n'est créée que si `license-status --slug <code>` répond « Entreprise introuvable ». Sinon
  « déjà créée, on continue ».
- **Mot de passe du gérant** : **découvre dans `cli.py` comment il est lu.** S'il vient d'une invite du
  terminal, lance `docker compose … run --rm cli create-company …` **depuis la console** du script avec
  l'entrée standard réelle (le script s'exécute dans une vraie fenêtre PowerShell : on **ne redirige ni
  l'entrée ni la sortie** de cette commande). Avant de la lancer, vérifie `-not [Console]::IsInputRedirected`
  et `[Environment]::UserInteractive` ; sinon : échec clair « lancez le script dans une fenêtre PowerShell ou le
  Terminal Windows, pas dans un éditeur ». Après coup, relis `license-status` pour **confirmer** la création, quelle
  que soit la sortie. Si l'invite affiche `GetPassWarning` ou « Can not control echo » : **ne pas continuer**,
  explique de relancer dans une autre fenêtre (rien n'a été créé) — même précaution que l'étape 8 du guide.
  **Si `cli.py` n'offre aucune façon sûre de saisir le mot de passe depuis un script, ne contourne pas** :
  arrête-toi et demande-moi (jamais `--password` en clair, jamais de fichier de mot de passe qui reste sur le disque).
- **Licence** : `activate-license --slug … --plan … --note …`, puis `license-status`. Attend dans la sortie
  `Accès : actif` et `Fin de période : sans fin`, sinon échec. Relancée : « rien à faire » est un **succès**.
- **Dernier contrôle** : `GET http://localhost:<port>/` répond 200 *et* `/api/v1/platform/…` répond 404
  (c'est ce que la CI Linux vérifie déjà : reprends la même sonde, ne réinvente pas).

## Bloc F — Confort et sortie (tout ceci est retiré proprement par `Desinstaller`)

1. **`<Racine>\bin\coges.cmd`** (et `coges.ps1`) : l'équivalent de la fonction `coges` du guide, qui transmet
   les arguments. `<Racine>\bin` est ajouté au `PATH` **de l'utilisateur** (jamais celui de la machine), une
   seule fois (pas de doublon à la relance). Plus besoin de redéfinir `coges` à chaque fenêtre.
2. **Raccourci sur le Bureau « CoGes »** (`.url`) vers `http://localhost[:port]`.
3. **Tâche planifiée « CoGes - démarrage »**, à l'ouverture de session de l'utilisateur : attend que le
   moteur Docker réponde (jusqu'à 5 minutes) puis lance `up -d`. C'est un **filet de sécurité** : le vrai
   démarrage reste « Start Docker Desktop when you sign in » ; le script **vérifie** ce réglage
   (`%APPDATA%\Docker\settings-store.json` ou `settings.json`, clé `AutoStart` ; ne l'invente pas si le fichier
   a un autre format) et, s'il ne peut pas le lire ou s'il est faux, **dit** au technicien de le cocher. Il ne modifie
   pas les réglages de Docker Desktop.
4. **Journal** : `<Racine>\journaux\installation-AAAAMMJJ-HHMMSS.log`, écrit par une fonction `Write-Log`
   à nous (**pas** `Start-Transcript`, qui enregistrerait ce qui est saisi). On y trouve les étapes, durées, codes
   de sortie, lignes d'erreur de Docker ; **jamais** une valeur de `coges.env`, un mot de passe, ni la sortie brute d'un
   `docker compose config` (qui les contient). Une fonction `Mask-Secrets` retire de toute ligne les valeurs lues
   dans `coges.env` ; un test l'exerce.
5. **`-Action Etat`** : n'écrit rien. Affiche version installée, services, port, adresse, `license-status`,
   espace disque, dernier journal.
6. **`-Action Reparer`** : reprend les blocs B à E sans rien recréer (utile après un échec ou une mise à jour de Docker).
7. **`-Action Desinstaller`** : arrête et supprime les **conteneurs**, la tâche planifiée, le raccourci, `bin\`
   et son entrée de `PATH`. **Conserve par défaut** `reglages\` et les volumes (donc les données). Option
   `-EffacerLesDonnees` : exige de **retaper le code de la boutique**, rappelle qu'**il n'existe pas encore de
   sauvegarde (lot 4)**, puis seulement alors supprime les volumes `coges-onprem_*`. **Jamais** `down -v` sans cette chaîne.

## Bloc G — Tests et CI (Linux et Windows ; Docker n'est pas simulé)

- **Pester** (`tests/CoGes.Install.Tests.ps1`), sur des **fonctions pures** : génération des secrets (longueurs,
  alphabet, unicité entre eux, deux appels ≠), écriture du fichier de réglages (**UTF-8 sans BOM**, LF, `PORT` et
  `URL` concordants, jamais d'écrasement d'un fichier existant), choix du port (80 libre / pris / 8080 pris), validation du code
  de boutique et de `-Version` (`latest`, vide, `v1.4`, `1.4.0` refusés), `Mask-Secrets`, ajout à `PATH` sans doublon,
  `-Simulation` (rien d'écrit dans `-Racine`, sortie contenant chaque étape), refus en `-NonInteractif` quand une
  réponse manque. Les appels à `docker` passent par **une seule fonction** (`Invoke-Docker`) qu'un test remplace.
- Les fichiers produits par la fonction de réglages sont **relus par `check_onprem_env.py`** (le vrai) dans le test :
  s'il dit « OK », le script et le contrôle sont d'accord.
- **Deux jobs ajoutés** à `.github/workflows/onprem.yml` (le job `onprem` n'est pas modifié ; même déclencheurs,
  mêmes `permissions: contents: read`, aucun secret) :
  - `onprem-powershell` sur `ubuntu-latest` : `pwsh`, `Invoke-ScriptAnalyzer` (erreurs et avertissements bloquants,
    exceptions justifiées en commentaire), Pester ;
  - `onprem-windows` sur `windows-latest` : les **mêmes tests Pester sous Windows PowerShell 5.1**
    (`shell: powershell`) **et** sous `pwsh` — c'est ce qui attrape BOM, accents, `Join-Path`, droits `icacls`. Pas de
    Docker (les runners Windows n'exécutent pas les conteneurs Linux) : écris-le en commentaire, pour qu'on n'y revienne pas.
- Le test d'architecture existant de la liste des fichiers livrés (s'il y en a un) et `check_protected_paths.py`
  **passent sans nouvelle dérogation**.

## Bloc H — Documentation

- `docs/runbooks/sur-site.md` : une section **« Installer en une commande »** en tête (les deux lignes du bloc A,
  ce qui sera demandé, ce que le script ne fait pas : installer Docker Desktop, activer la virtualisation,
  régler Docker Desktop ; messages d'échec et quoi faire ; `Reparer`, `Etat`, `Desinstaller`). **Les étapes manuelles
  restent** (secours), en retirant la mention « Le script du lot 3 les enchaînera ». Retire la ligne du lot 3 du
  tableau « Ce qui n'existe pas encore ».
- `docs/decisions/0126-installation-windows-sur-site.md` : contexte, décision, conséquences. Y figurent : archive
  GitHub de l'étiquette (dépôt public) plutôt qu'un installeur propre ; Docker Desktop non installé par le script
  (licence) ; tâche de session en filet de sécurité ; pas d'élévation ; `Install-Programme` réutilisable par le lot 5 ;
  pas de fichier d'état ; **limite assumée : aucun test d'exécution réelle sur Windows en CI**.
- `docs/prompt-sur-site/README.md` : lot 3 passé à « ✅ code et tests ; **à vérifier sur Windows** », et une liste
  « Lot 3 — à vérifier sur la machine Windows » (voir ci-dessous).

## Ce que tu ne fais pas dans ce lot

- Pas de sauvegarde (lot 4), pas de mise à jour automatique ni de retour arrière (lot 5), pas de prise en main à
  distance ni de collecte de journaux vers nous (lot 6). Le script **ne sort jamais** de données du PC.
- Pas d'installation de Docker Desktop, de WSL ni de modification de leurs réglages.
- Pas d'ouverture de port, pas de pare-feu, pas d'écoute hors `127.0.0.1`.
- Pas de signature de code ni de MSI : un script lisible suffit pour un seul PC (à rediscuter plus tard).
- Aucune touche à `LICENSE` ni au contrat : sujet à part, le mien.

## Livrable et façon de travailler

1. Branche `feat/sur-site-installation-windows`, commits atomiques en anglais (Conventional Commits :
   `feat(onprem): …`, `test(onprem): …`, `docs(onprem): …`, `ci(onprem): …`).
2. Joue en local ce qui peut l'être : `pwsh -File … -Simulation`, Pester, `check_protected_paths.py --base origin/main`,
   `shellcheck`, la CI du workflow « Sur site » si tu peux la lancer. **Montre la sortie, ne la résume pas.**
3. **Ne pousse pas et n'ouvre pas la PR avant mon accord** : écris-moi un rapport court (ce qui est fait et prouvé ;
   ce qui n'est **pas** prouvé) et demande « Je pousse la branche et j'ouvre la PR ? ».
4. Dans la PR, une section **« À vérifier sur Windows »** (copie dans le README) :

   1. `-Simulation` sur le PC : tout est annoncé, rien n'est écrit.
   2. Installation complète, **version contenant `activate-license`**, sur un Windows 11 8 Go avec Docker Desktop :
      durée totale, message final, `http://localhost` ouvre, connexion du gérant.
   3. Le mot de passe du gérant : **demandé sans écho**, aucun `GetPassWarning`, depuis PowerShell **et** le Terminal Windows.
   4. `coges.env` : créé **sans BOM**, accessible à l'utilisateur seulement (`icacls`), les deux lignes `PORT`/`URL` bonnes.
   5. Port 80 occupé exprès (un serveur quelconque) : bascule sur 8080, tout fonctionne, raccourci compris.
   6. Relance de `Installer` sur le même PC : **rien ne change**, « rien à faire » pour la licence.
   7. Échecs simulés : Docker éteint, virtualisation (si possible), étiquette inexistante, version sans `activate-license`,
      Internet coupé → chaque message dit quoi faire.
   8. Redémarrage du PC : CoGes revient seul ; tâche « CoGes - démarrage » présente dans le Planificateur de tâches.
   9. `coges ps` dans une **nouvelle** fenêtre (le `PATH` utilisateur est pris en compte).
   10. `Etat`, puis `Desinstaller` (les données restent), puis `Installer` à nouveau : la société et les ventes sont là.
   11. `Desinstaller -EffacerLesDonnees` demande bien le code de la boutique (sur un PC d'essai seulement).
   12. Aucun mot de passe ni clé dans `C:\CoGes\journaux\*.log` (recherche d'une valeur de `coges.env`).

À rapporter : durée, messages exacts d'erreur, mémoire utilisée.
