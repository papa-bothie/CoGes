# 0126 — Installation sur site en une commande : un script PowerShell lisible

- **Date** : 2026-11-17
- **Phase** : sur site, lot 3 (`docs/prompt-sur-site/03-script-installation.md`)
- **Statut** : acceptée
- **Décideur** : utilisateur (décisions écrites dans le prompt du lot 3 ; `coges.cmd` seul,
  choisi en cours de lot)

## Contexte

Installer CoGes sur le PC d'un client (ADR 0124, 0125) demandait de taper les étapes 1 à 11
de `docs/runbooks/sur-site.md`, une commande à la fois : tirer neuf secrets, copier un
modèle, choisir un port, migrer, démarrer, créer la société, poser la licence. Le
propriétaire de CoGes installe lui-même chez le client ; une erreur de frappe coûte un
déplacement.

## Décision

Un script PowerShell, `deploy/onprem/windows/installer.ps1`, livré avec le programme, qui
enchaîne ces étapes ; ses fonctions sont dans `CoGes.Install.ps1` (dot-sourcé par le point
d'entrée, la tâche planifiée et les tests).

- **Deux lignes données au technicien**, sans `| iex` : `Invoke-WebRequest … -OutFile`, puis
  `powershell -ExecutionPolicy Bypass -File … -Version vX.Y.Z`. Lancé seul depuis `%TEMP%`,
  le point d'entrée télécharge `CoGes.Install.ps1` **de la même étiquette**.
- **Le programme vient de l'archive GitHub de l'étiquette** (dépôt public, aucun jeton), dont
  seul `deploy/onprem/` est posé dans `C:\CoGes\programme\`, en remplaçant le dossier en
  entier (`Install-Programme`, réutilisable par le lot 5 : elle ne touche jamais aux
  réglages ni aux données). Plutôt qu'un installeur propre (MSI, signature) : un script
  lisible suffit pour un PC à la fois.
- **Docker Desktop n'est pas installé par le script** : sa licence dépend de la taille du
  client (ADR 0124). Le script le détecte (absent, éteint, moteur Windows, compte hors de
  `docker-users`), donne le lien officiel et s'arrête. Il ne change pas ses réglages ; il
  lit seulement `AutoStart` dans `%APPDATA%\Docker\settings-store.json` (ou
  `settings.json`) et dit de cocher « Start Docker Desktop when you sign in » si la valeur
  n'est pas lue à `true`.
- **Pas d'élévation** : `C:\CoGes`, le PATH **de l'utilisateur**, une tâche à son ouverture
  de session et un raccourci n'en demandent pas.
- **Tâche planifiée « CoGes - démarrage »**, filet de sécurité : à l'ouverture de session,
  `demarrage.ps1` attend que le moteur Docker réponde (5 minutes au plus) puis lance
  `up -d`. Le vrai démarrage reste celui de Docker Desktop.
- **Pas de fichier d'état** : l'état se déduit de ce qui est là (`programme\.version`, posé
  avec le dossier du programme et remplacé avec lui ; `coges.env` ; `docker compose ps` ;
  `license-status`). Relancer `Installer` ne recrée rien et reprend après un échec.
- **Réglages** : créés une fois (`FileMode.CreateNew` : jamais d'écrasement), UTF-8 **sans**
  BOM, LF, 8 secrets hexadécimaux et la clé base64 url-safe tirés de
  `RandomNumberGenerator`, port et adresse concordants, droits restreints par `icacls` aux
  SID du compte, de SYSTEM et des Administrateurs (les noms changent avec la langue).
  Ensuite, seules trois lignes peuvent changer, par `Reparer` : `COGES_HTTP_PORT`,
  `COGES_PUBLIC_URL`, `COGES_IMAGE_TAG`. Le script s'arrête jusqu'à `COPIE-FAITE`
  (`-CopieFaite` en `-NonInteractif`).
- **Ordre du guide, jamais autrement** : contrôles du PC, programme, réglages, `pull`,
  `check_onprem_env.py` (image worker, sans réseau), `migrate`, `up -d`, attente des neuf
  services (5 minutes, puis les 40 dernières lignes du service en cause), société
  (créée seulement si `license-status` dit « introuvable »), licence (« rien à faire » est
  un succès), `/` en 200 et `/api/v1/platform/` en 404 (la sonde du workflow « Sur site »).
- **Mot de passe du gérant** : `create-company` le lit par `getpass` (vérifié dans
  `backend/app/cli.py`). Le script lance `docker compose run --rm cli create-company` par
  `Start-Process -NoNewWindow` : docker reçoit la console elle-même (avec `& docker`,
  PowerShell lirait sa sortie ligne par ligne et l'invite resterait cachée). Avant : une
  vraie console exigée (`[Console]::IsInputRedirected`, `UserInteractive`, hôte
  `ConsoleHost`), puis le terminal du conteneur vérifié (`run --rm --entrypoint test cli
  -t 0`) ; `create-company` est lancé avec `-e PYTHONWARNINGS=error::getpass.GetPassWarning` :
  si la frappe ne peut pas être cachée, getpass s'arrête **avant** de lire au lieu de lire
  en clair. Dans les deux cas, arrêt net avec « Cette console ne peut pas cacher la frappe
  du mot de passe (GetPassWarning) », **sans repli** : aucun `--password`, un seul essai.
  Après : `license-status` relu, quelle que soit la sortie. Jamais de fichier de mot de
  passe.
- **Journal** à nous (`Write-Log`, pas `Start-Transcript`), chaque ligne passée par
  `Mask-Secrets` (valeurs lues dans `coges.env`). Un seul appel à docker, `Invoke-Docker`,
  qui sépare la réponse (sortie standard) de la progression de compose (sortie d'erreur).
- **Actions** : `Installer`, `Reparer` (blocs B à E sans rien recréer ; nouvelle version :
  arrêt de l'application avant `migrate`, comme le guide), `Etat` (n'écrit rien),
  `Desinstaller` (conteneurs, tâche, raccourci, `bin\` et PATH ; réglages et volumes
  gardés ; `-EffacerLesDonnees` exige le code de la boutique, vérifié par
  `license-status`, puis `EFFACER`, et supprime les volumes `coges-onprem_*` un par un,
  jamais par `down -v` ; refusé en `-NonInteractif`). `-Simulation` annonce chaque étape
  sans rien écrire ni lancer (`Invoke-Docker` refuse d'être appelé en simulation).
- **Compatibilité** : Windows PowerShell 5.1 (celui de Windows 11) et PowerShell 7, fichiers
  UTF-8 avec BOM et LF ; `PSUseCompatibleSyntax` cible 5.1 dans l'analyse.

## Écarts au prompt

- **`bin\coges.cmd` seul, sans `coges.ps1`** (choix du propriétaire) : Windows 11 bloque les
  scripts `.ps1` par défaut (stratégie « Restricted ») et PowerShell choisit `coges.ps1`
  avant `coges.cmd` ; « coges ps » aurait échoué dans toute nouvelle fenêtre. `coges.cmd`
  marche dans PowerShell, le Terminal et cmd sans toucher à la stratégie.
- **Un fichier de plus** : `demarrage.ps1`, l'action de la tâche planifiée.
- **Paramètres de réponse** (`-NomBoutique`, `-CodeBoutique`, `-NomGerant`,
  `-TelephoneGerant`, `-EmailGerant`, `-Offre`, `-NoteContrat`, `-CopieFaite`) : ce que
  `-NonInteractif` exige pour ne rien demander. En `-NonInteractif`, le récapitulatif vaut
  `OUI`, jamais `COPIE-FAITE` ni `EFFACER`.
- **Mémoire** : 8 Go **installés** (`Win32_PhysicalMemory`), repli sur
  `Win32_ComputerSystem.TotalPhysicalMemory` ; ce dernier retranche la mémoire réservée au
  matériel et refuserait un PC de 8 Go.
- **Virtualisation** : acceptée si `VirtualizationFirmwareEnabled` **ou**
  `Win32_ComputerSystem.HypervisorPresent` ; quand WSL 2 tourne déjà, Windows répond
  « firmware : non ».
- **Disque** : 20 Go libres pour une première installation, 5 Go quand le programme est déjà
  là (les images occupent déjà leur place).
- **Les noms et la note ne contiennent pas de guillemet double** (refusés à la saisie) :
  Windows PowerShell 5.1 les transmet mal à un programme.

## Conséquences

- Les tests Pester (`deploy/onprem/windows/tests/`) tournent sous Linux (pwsh, avec
  PSScriptAnalyzer) et sous Windows (Windows PowerShell 5.1 **et** pwsh), deux jobs du
  workflow « Sur site » ; le vrai `check_onprem_env.py` relit les réglages écrits par le
  script. `backend/tests/unit/test_onprem_windows.py` vérifie la forme des fichiers dans la
  CI principale.
- Vérifié sur Linux, hors CI, avec les images locales : pose du programme, réglages,
  contrôle, 42 migrations, neuf services prêts, société, licence puis « rien à faire »,
  `/` en 200 et `/api/v1/platform/` en 404, état, journal sans secret.
- **Limite assumée : aucun test d'exécution réelle sur Windows en CI.** Les runners Windows
  n'exécutent pas les conteneurs Linux. Le propriétaire vérifie sur un vrai PC (liste
  « Lot 3 — à vérifier sur la machine Windows », `docs/prompt-sur-site/README.md`).
- Aucun fichier protégé modifié, aucune dérogation nouvelle dans `check_protected_paths.py`,
  aucune image ni variable nouvelle : les utilisateurs actuels ne voient rien.
- Une étiquette n'est installable que si ses images sont publiées sur ghcr.io : `v0.1.0`
  ne l'est pas aujourd'hui (le contrôle « La version … n'existe pas » l'attrape).
