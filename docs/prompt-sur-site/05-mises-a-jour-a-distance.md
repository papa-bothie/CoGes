# Lot 5 — Mises à jour à distance et retour arrière

> À donner à l'agent Claude Code, dans le dépôt `CoGes`, sur une branche `feat/sur-site-mises-a-jour`
> partie de `main` (lots 1 à 4 fusionnés, v0.3.0 vérifiée sur Windows le 21/11/2026). Une seule PR.
> Suite de `01` à `04` dans `docs/prompt-sur-site/` : **mêmes règles d'or**, rien à rediscuter.

## But

Aujourd'hui, changer la version d'un client demande d'aller sur place et de taper
`-Action Reparer -Version vX.Y.Z`. Ce lot permet de **publier une version depuis chez CoGes** :
chaque PC la voit seul, la télécharge sans gêner la boutique, l'installe à une heure calme, se
vérifie, et **revient seul en arrière** si quelque chose casse. Aucun port ouvert, aucune connexion
entrante : le PC **va chercher**, personne ne vient le chercher (ADR 0124).

Critère de fin (README) : *passage d'une version à la suivante sans se déplacer*, et une mise à jour
ratée qui revient seule à l'état d'avant, données comprises.

## Bloc 0 — Corrections du lot 4 trouvées sur Windows (à faire en premier, commit à part)

Constatées pendant les vérifications du 21/11/2026 :

1. **Mauvaise sauvegarde restaurée.** Après `Desinstaller -EffacerLesDonnees` puis `Installer`, la
   sauvegarde la plus récente de la clé USB était celle de la **base neuve et vide** : la restaurer
   a « réussi » sans aucune donnée. À faire :
   - `-Action Restaurer` **sans `-Fichier`** liste les sauvegardes du PC et de la clé CoGes branchée
     (date, version, nombre de ventes et de sociétés lus au manifeste, origine), la plus récente en
     haut, et fait choisir par numéro ;
   - les sauvegardes faites **automatiquement avant** une action portent un suffixe lisible :
     `-avant-effacement`, `-avant-restauration`, `-avant-maj`, `-installation` (base neuve) ; la
     rétention et la copie sur la clé les traitent comme les autres ;
   - **avertissement renforcé** (taper `RESTAURER-QUAND-MEME`) si la sauvegarde choisie compte
     **0 vente** ou **moins de ventes que la base actuelle**, en disant combien seront perdues.
2. **« échec (code 1) » quand Docker Desktop est arrêté.** Toute action qui appelle Docker vérifie
   d'abord le moteur et dit « Docker Desktop ne tourne pas : ouvrez-le et attendez « Engine
   running », puis relancez. Rien n'a changé. » (réutilise le contrôle du bloc B du lot 3).
3. **Docker Desktop qui ne démarre plus** (« Docker Desktop is unable to start ») : ajoute au
   dépannage du guide la marche à suivre (quitter Docker, `wsl --shutdown`, place disque,
   redémarrage, `wsl --update`) et **l'interdiction** de « Clean / Purge data » et « Reset to
   factory defaults » (ils effacent la base). `-Action Etat` signale moins de 5 Go libres en rouge.

Tests Pester pour 1 et 2 ; ligne dans l'ADR 0127 (« corrections après le test Windows »).

## Règles d'or (rappel)

Ajouter, ne rien modifier (ADR 0124) ; aucune nouvelle dérogation dans `check_protected_paths.py` ;
pas de changement de l'application ni de nouvelle image ; la production et ses workflows ne sont pas
touchés ; aucun secret dans un journal ; tu ne peux pas tester sur Windows : prouve sous Linux,
liste le reste.

## Avant d'écrire (lis les vrais fichiers)

- `deploy/onprem/windows/CoGes.Install.ps1` : `Install-Programme` (déjà prévu pour ce lot, garde
  `programme.ancien`), `Invoke-CogesRepair` (changement de version manuel), `New-CogesBackup`,
  le verrou commun, `Show-CogesToast`, les tâches planifiées, `Invoke-CogesStep`, `-Simulation`
- `deploy/onprem/sauvegarde/base.py` (`bascule`, `retour`, `etat`, `revisions`) et `coffre.py`
- `docs/runbooks/sur-site.md` (« Mettre à jour à la main », « Revenir à la version précédente »),
  ADR 0124 à 0127, `.github/workflows/deploy.yml` (comment une étiquette publie les images ; **en
  lecture seule**), `deploy/onprem-ci/verifier.sh`

## Questions à trancher avec moi (`AskUserQuestion`, au début, en une fois)

1. **Où le PC apprend la version à installer (le « canal »)** — recommandé : un fichier
   `deploy/onprem/canal/stable.json` sur la branche `main` du dépôt public, lu par
   `raw.githubusercontent.com` (version, date, empreintes des images, version minimale de départ,
   note en français). Je change de version pour tous les clients en modifiant ce fichier par une PR.
   Autres : les « Releases » GitHub ; un fichier sur un serveur de CoGes.
2. **Signature du canal** — recommandé : **oui**, signature Ed25519 par une clé tenue par moi seul
   (jamais dans GitHub ni la CI), vérifiée sur le PC par la clé publique posée à l'installation. Sans
   elle, quiconque prend la main sur le dépôt GitHub pousse une version chez tous les clients.
   Commande pour signer sur mon Ubuntu (image `worker`, comme `coffre.py paire`).
3. **Quand appliquer** — recommandé : télécharger **dès que vu** (CoGes continue de tourner), puis
   **appliquer à 21 h 30** (réglable par client), seulement si **aucune vente depuis 30 minutes** ;
   sinon nouvel essai le soir suivant. Jamais au démarrage du PC (ça retarderait l'ouverture).
   Le technicien peut forcer : `-Action MettreAJour -Maintenant`.
4. **Choix par client** — recommandé : réglage local `reglages\mise-a-jour.json` : `canal`
   (`stable` par défaut, `test` pour mon PC de test), `automatique` (oui/non), `heure`. Le canal
   `test` me permet d'essayer une version sur mon PC avant de la donner aux clients.

## Bloc A — Le canal et sa vérification

- Format du fichier de canal (à écrire dans l'ADR 0128) : `version`, `publiee_le`, `depuis_minimum`
  (version la plus ancienne qui peut sauter directement à celle-ci ; sinon étapes intermédiaires),
  empreintes `sha256` des trois images (`front`, `api`, `worker`) **par digest**, empreinte de
  l'archive du programme, `docker_desktop_minimum` si besoin, `note` (une ou deux phrases pour le
  technicien), `signature`.
- Le PC ne fait **jamais confiance à une étiquette** : il tire les images **par digest**
  (`…/api@sha256:…`) et refuse si l'étiquette ne pointe plus au même endroit.
- Refus clairs : canal illisible, signature fausse, version plus ancienne que l'installée (pas de
  retour arrière par le canal), saut trop grand (`depuis_minimum`), Docker Desktop trop ancien.
- Outil pour moi : `deploy/onprem/canal/publier.py` (ou script) qui, depuis une étiquette déjà
  publiée, lit les digests sur ghcr.io, calcule l'empreinte de l'archive, écrit le JSON et le signe.
  Documenté pas à pas dans le guide (« Publier une version pour les clients »).

## Bloc B — Télécharger sans gêner (`-Action VerifierMiseAJour`, tâche « CoGes - mise à jour »)

- Tâche planifiée (même style que les deux autres, sans élévation, cachée) : vérifie le canal
  2 fois par jour et à l'ouverture de session (si Internet répond ; sinon rien, journal seulement).
- Nouvelle version vue : télécharge l'archive dans `C:\CoGes\mises-a-jour\<version>\`, vérifie son
  empreinte, tire les images **pendant que CoGes tourne**, vérifie les digests ; écrit l'état
  (`prete`, `appliquee`, `echec`, `annulee`) pour `Etat`.
- Place disque : refuse si moins de 5 Go libres après téléchargement ; supprime les images de plus
  de deux versions en arrière (jamais celles en service ni la précédente).

## Bloc C — Appliquer (`-Action MettreAJour [-Maintenant]`), avec le verrou commun

Dans l'ordre, chaque étape s'arrête au premier problème ; **avant l'étape 4, rien n'a changé** :

1. Conditions : version prête et vérifiée, Docker répond, 5 Go libres, aucune vente depuis 30 min
   (sauf `-Maintenant`), verrou pris.
2. **Sauvegarde chiffrée** `-avant-maj` (lot 4), copiée sur la clé si branchée.
3. Contrôle à blanc : `check_onprem_env.py` du **nouveau** programme contre les réglages actuels
   (une nouvelle version peut exiger une ligne de plus : la mise à jour l'ajoute alors avec la
   valeur par défaut documentée, jamais un secret inventé en silence ; sinon refus clair).
4. Page de maintenance ; arrêt de `front`, `api`, `worker`, `beat`, `relay`.
5. **Copie locale de la base** `coges_avant_maj_<horodatage>` dans le même PostgreSQL
   (`CREATE DATABASE … TEMPLATE coges`, application arrêtée) : c'est elle qui permet le retour
   arrière **sans la clé privée** (que le PC n'a pas).
6. Programme remplacé (`Install-Programme`, l'ancien gardé), `COGES_IMAGE_TAG` changé dans
   `coges.env` (seule ligne touchée, écriture atomique), `migrate`, `up -d`.
7. Vérifications : neuf services `healthy` (5 min au plus), page d'accueil 200, administration 404,
   `license-status` actif, nombre de sociétés et de ventes **identique** à avant, tâches planifiées
   reposées (les scripts ont pu changer).
8. **Échec à l'étape 6 ou 7 ⇒ retour arrière automatique** : ancien programme, ancienne étiquette,
   base `coges_avant_maj_…` remise par renommage (`base.py`, même mécanisme que la bascule du lot 4),
   `up -d`, mêmes vérifications. Toast et journal : « La mise à jour vers vX a échoué ; CoGes est
   revenu à vY. Rien n'est perdu. CoGes est prévenu au prochain passage (lot 6). »
9. Succès : la copie `coges_avant_maj_…` et l'ancien programme sont **gardés 7 jours**, puis
   supprimés par la tâche (jamais avant).

## Bloc D — Revenir en arrière plus tard (`-Action RevenirVersionPrecedente`)

Pour le technicien, dans les 7 jours : remet l'ancien programme, l'ancienne étiquette et la copie de
base d'avant la mise à jour. **Les ventes faites depuis la mise à jour seraient perdues** : le script
les compte, sauvegarde d'abord, et exige `REVENIR` puis le code de la boutique. Au-delà de 7 jours :
refus, et le guide renvoie vers la restauration du lot 4.

## Bloc E — Ce que voit le technicien

- `-Action Etat` : version installée, canal, version disponible et son état, dernière vérification du
  canal, prochaine application prévue, dernière mise à jour (réussie / revenue en arrière), copie de
  base gardée et sa date de fin.
- `-Action MettreAJour -Simulation` annonce tout sans rien faire.
- Journal `C:\CoGes\journaux\mise-a-jour-AAAAMMJJ.log`, sans secret.

## Bloc F — Tests et CI

- Pester : lecture et refus du canal (signature, plus ancienne, saut trop grand), choix de l'heure et
  règle « 30 minutes sans vente », états, rétention des 7 jours, `-Simulation`, bloc 0.
- Python : signature et vérification (bonne, fausse, clé autre, champ modifié).
- `verifier.sh` (Linux, workflow « Sur site ») avec deux étiquettes locales construites en CI
  (`ci-a` → `ci-b`) et un canal signé par une clé de test **générée dans le job** :
  a. mise à jour réussie, données identiques, version lue ;
  b. migration qui échoue exprès (image `ci-b-casse`) ⇒ retour arrière automatique, données
     identiques, ancienne version qui répond ;
  c. canal mal signé ⇒ refus, rien changé ;
  d. `RevenirVersionPrecedente` après une vente faite en `ci-b` : la vente est annoncée comme perdue,
     sauvegardée d'abord.
  Durée du job sous 30 min, sinon un job à part dans le même workflow.
- `check_protected_paths.py --base origin/main` sans dérogation.

## Bloc G — Documentation

- `docs/runbooks/sur-site.md` : « Mises à jour » (ce qui se passe seul, à quelle heure, ce que dit
  `Etat`, forcer, revenir en arrière), « Publier une version pour les clients » (pour moi : étiquette,
  essai sur le canal `test`, puis `stable`), dépannage du bloc 0 ; « Mettre à jour à la main » reste
  le secours ; retirer le lot 5 de « Ce qui n'existe pas encore ».
- `docs/decisions/0128-mises-a-jour-sur-site.md`.
- `docs/prompt-sur-site/README.md` : lot 5 et la liste « à vérifier sur Windows » :
  1. Canal `test` réglé sur mon PC ; une nouvelle étiquette publiée sur `test` est vue et téléchargée
     pendant qu'on vend, sans coupure.
  2. Application à l'heure prévue (heure avancée pour le test), puis `Etat` : nouvelle version.
  3. Une vente dans les 30 minutes : application repoussée au lendemain.
  4. `-Action MettreAJour -Maintenant` : durée de la coupure notée.
  5. Mise à jour ratée exprès (version de test cassée) : retour seul, données là, toast affiché.
  6. Canal à signature fausse : refusé, rien changé.
  7. `RevenirVersionPrecedente` : avertissement des ventes perdues, puis retour réussi.
  8. Bloc 0 : `Restaurer` sans `-Fichier` liste les sauvegardes ; une sauvegarde à 0 vente exige
     `RESTAURER-QUAND-MEME` ; Docker arrêté ⇒ message clair.

## Ce que tu ne fais pas dans ce lot

- Aucune remontée d'information vers CoGes (« la mise à jour a réussi chez tel client ») : c'est le
  lot 6. Ici, tout reste sur le PC (journal, `Etat`, toast).
- Pas de mise à jour de Docker Desktop ni de Windows.
- Pas de retour arrière par Alembic (`downgrade`) : uniquement par la copie de base.

## Livrable

Branche `feat/sur-site-mises-a-jour`, commits atomiques en anglais ; questions **avant** de coder,
puis plan court, puis feu vert ; sorties réelles montrées ; **pas de push ni de PR avant mon accord**.
