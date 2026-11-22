# Lot 6 — Support à distance et remontée d'informations

> À donner à l'agent Claude Code, dans le dépôt `CoGes`, sur une branche `feat/sur-site-support`
> partie de `main` (lots 1 à 5 fusionnés : PR #92, #93, #95, #96, #97). Une seule PR.
> Suite de `01` à `05` dans `docs/prompt-sur-site/` : **mêmes règles d'or**, rien à rediscuter.
> Dernier lot de l'installation sur site.

## But

Aujourd'hui, si une sauvegarde échoue, si une mise à jour revient en arrière ou si le disque se
remplit chez un client, **personne chez CoGes ne le sait** : seul le commerçant voit une
notification Windows, qu'il peut ignorer. Et pour aider, il faut se déplacer. Ce lot apporte :

1. **la remontée d'informations** : chaque PC dit régulièrement à CoGes « je vais bien » ou
   « ceci a échoué », sans aucune donnée commerciale ;
2. **le diagnostic** : en une commande (ou un double-clic), un fichier qui rassemble tout ce qu'il
   faut pour comprendre une panne, sans aucun secret, à envoyer par WhatsApp ou e-mail ;
3. **la prise en main à distance**, avec l'accord du commerçant à chaque fois ;
4. **des journaux qui ne remplissent pas le disque**.

Critère de fin (README) : *un incident simulé chez le client est vu chez CoGes sans que le
commerçant appelle, et diagnostiqué à distance.*

## Règles d'or (rappel, plus deux)

Ajouter, ne rien modifier (ADR 0124) ; aucune nouvelle dérogation dans `check_protected_paths.py` ;
pas de changement de l'application ni de nouvelle image ; la production, le VPS (`deploy/vps/**`)
et leurs workflows ne sont pas touchés ; aucun secret dans un journal ; tu ne peux pas tester sur
Windows : prouve sous Linux, liste le reste. En plus :

- **Rien de commercial ne sort du PC** : ni chiffre d'affaires, ni montant, ni nom de client, ni
  article, ni nom de personne, ni numéro de téléphone. Ce qui sort est **listé une fois** dans
  l'ADR et dans une annexe pour le contrat, et un test vérifie que le message envoyé ne contient
  que les champs de cette liste.
- **Toujours sortant, jamais entrant** : aucun port ouvert, aucun service qui écoute, aucune
  commande reçue de l'extérieur. Le PC parle ; il n'obéit à personne.

## Avant d'écrire (lis les vrais fichiers)

- `deploy/onprem/windows/CoGes.Install.ps1` : `Etat` (ce qu'il sait déjà : version, services,
  licence, disque, sauvegardes, mises à jour), `Write-Log` et `Mask-Secrets`, `Show-CogesToast`,
  les tâches planifiées, le verrou, `sauvegarde.ps1`, `mise-a-jour.ps1`, `demarrage.ps1`
- ADR 0077 (les pings « homme mort » de la production : `GET <url>` et `<url>/fail`, variable
  `COGES_JOB_PING_URLS`) — **même mécanisme**, pour qu'un seul outil surveille la production et
  les clients sur site ; ADR 0124 à 0128 ; `docs/runbooks/sur-site.md`
- `deploy/onprem/sauvegarde/base.py` (`etat`, `compter`) pour ce qui se lit dans la base

## Questions à trancher avec moi (`AskUserQuestion`, au début, en une fois)

1. **Où arrivent les informations** — recommandé : **un service de pings « homme mort »**
   (Healthchecks.io, compte gratuit au départ ; auto-hébergeable plus tard), le même genre que celui
   de la production (ADR 0077). Un « check » par client et par sujet ; il m'alerte (e-mail, Telegram
   ou autre) quand un PC se tait ou signale un échec, et son tableau de bord montre tous les clients.
   **Aucun code à écrire côté serveur, le VPS n'est pas touché.** Autres options : une route sur le
   VPS de CoGes (demande de toucher l'application et le VPS : plus lourd, hors règles du sur-site) ;
   rien de remonté (diagnostic manuel seulement).
2. **Quels signaux** — recommandé, trois checks par client :
   - `vie` : chaque jour à l'ouverture de session (période 1 jour, tolérance 3 jours pour les
     fermetures du week-end), avec le résumé d'état ;
   - `sauvegarde` : après chaque sauvegarde (succès, ou `/fail` avec la raison), et l'essai de
     relecture du dimanche ;
   - `mise-a-jour` : après chaque application (succès, retour arrière en `/fail`, attente de plus
     de 3 jours en `/fail`).
3. **Prise en main à distance** — recommandé : **Assistance rapide de Windows** (*Quick Assist*,
   déjà dans Windows 11, gratuite, le commerçant donne un code et accepte à chaque fois, rien qui
   reste ouvert). Le script ne l'installe ni ne la lance seul : un raccourci « Aide CoGes » sur le
   Bureau l'ouvre et affiche le numéro de CoGes. Autres : RustDesk (libre, accès sans présence
   possible, serveur relais à héberger : plus tard) ; TeamViewer / AnyDesk (licence commerciale).
4. **Où va le fichier de diagnostic** — recommandé : sur le **Bureau** du PC ; le commerçant
   l'envoie par WhatsApp ou e-mail. Aucun envoi automatique de fichier.

## Bloc A — Le résumé d'état (fonction pure, la seule source de ce qui sort)

`Get-CogesReport` construit un objet **fermé** (liste blanche de champs, rien d'autre) :

- identifiant du PC : une **valeur aléatoire** tirée à l'installation et gardée dans
  `reglages\support.json` (**jamais** le code de la boutique ni un nom) ; la correspondance
  identifiant ↔ client reste chez CoGes ;
- version installée, canal, état de la dernière mise à jour et sa date ;
- services : nombre `healthy` sur 9, noms de ceux qui ne le sont pas ;
- licence : active / suspendue, offre (sans note de contrat) ;
- sauvegarde : date de la dernière bonne, de la dernière copie hors du PC, résultat du dernier essai ;
- disque : Go libres ; mémoire du PC ; versions de Windows, de Docker Desktop, de WSL ;
- nombre d'erreurs (`ECHEC`) dans les journaux des 24 dernières heures, par source.

Rendu en **texte court** (quelques lignes, moins de 2 Ko) pour le corps du ping. **Test** : le
rendu ne contient aucune valeur de `coges.env`, aucun code de boutique, aucun nom ; tout champ hors
de la liste blanche fait échouer le test.

## Bloc B — Envoyer (pings sortants)

- Réglages dans `reglages\support.json` (**pas** dans `coges.env`, pour ne pas toucher au contrôle
  du lot 1) : `remontee` (oui/non, **non** tant que les adresses ne sont pas posées), les trois
  adresses de ping, l'identifiant du PC. Posé par `-Action Reparer -Support <fichier.json>` (le
  technicien prépare le fichier chez CoGes), ou `-Action ConfigurerSupport` en questions.
- Envoi par PowerShell sur l'**hôte Windows** (les conteneurs restent sans Internet) : `POST` du
  résumé vers l'adresse, ou vers `<adresse>/fail` en cas d'échec ; délai court (10 s), 2 essais,
  **jamais** bloquant : un ping qui échoue s'écrit au journal et l'action continue.
- Branché dans : `demarrage.ps1` (signal `vie`), `sauvegarde.ps1` et `New-CogesBackup` (signal
  `sauvegarde`, essai du dimanche compris), `mise-a-jour.ps1` et `MettreAJour` (signal
  `mise-a-jour`, y compris l'attente de plus de 3 jours du lot 5).
- Les adresses de ping sont traitées comme des secrets : masquées dans les journaux (`Mask-Secrets`)
  et jamais affichées par `Etat` (seulement « remontée : active, dernier envoi le … »).
- `-Action TesterSupport` : envoie un ping de test sur les trois adresses et dit lequel a répondu.

## Bloc C — Le diagnostic (`-Action Diagnostic`, et raccourci « Diagnostic CoGes »)

Un fichier `CoGes-diagnostic-AAAAMMJJ-HHMM.zip` sur le Bureau, **sans secret et sans donnée
commerciale**, qui contient :

- la sortie de `Etat` et le résumé du bloc A ;
- `coges ps`, `docker version`, `docker info` (abrégé), `wsl --version`, versions de Windows ;
- les journaux de `C:\CoGes\journaux\` des 7 derniers jours ;
- les 300 dernières lignes de chaque service (`coges logs`), **passées par `Mask-Secrets`** ;
- `coges.env` **réduit aux noms des variables** (jamais les valeurs) ; la liste des fichiers de
  `C:\CoGes\sauvegardes\` (noms, tailles, dates ; pas les fichiers) ;
- l'espace disque, la mémoire, les tâches planifiées de CoGes et leur dernier résultat.

Taille bornée (10 Mo au plus, sinon on raccourcit les journaux). **Test** : un faux PC avec des
secrets connus dans `coges.env` et dans les journaux des services ; aucun n'apparaît dans le zip ;
aucun nom de client ou d'article de la base de démo non plus.

Le raccourci « Diagnostic CoGes » (Bureau) lance l'action dans une fenêtre visible, dit en mots
simples où est le fichier et à qui l'envoyer, puis ouvre l'Explorateur sur le fichier.

## Bloc D — La prise en main à distance (selon la question 3)

- Raccourci « Aide CoGes » sur le Bureau : ouvre l'Assistance rapide de Windows et affiche une
  fenêtre avec le numéro de CoGes et la marche à suivre en trois phrases (« Appelez CoGes, donnez le
  code affiché, acceptez »). Si l'Assistance rapide manque, dit comment l'installer depuis le
  Microsoft Store.
- **Rien de permanent** : aucun logiciel d'accès sans présence n'est installé par le script.
- Guide (pour moi) : comment aider à distance (ouvrir l'Assistance rapide de mon côté, prendre la
  main, lancer `Etat` / `Diagnostic` / `Reparer`, ce qu'il ne faut jamais faire à distance : purger
  Docker, `EffacerLesDonnees`).

## Bloc E — Des journaux qui ne remplissent pas le disque

- `C:\CoGes\journaux\` : fichiers de plus de 60 jours supprimés, total plafonné à 200 Mo (les plus
  anciens d'abord), par la tâche de sauvegarde ; jamais le journal du jour.
- Vérifie que les journaux Docker sont bien plafonnés (`max-size`, `max-file` du lot 1) pour tous
  les services, y compris ceux des lots 4 et 5 ; sinon, ajoute-le (ajout seulement).

## Bloc F — Ce qui change ailleurs (ajouts seulement)

- `Installer` : tire l'identifiant du PC, pose les deux raccourcis, propose `-Support <fichier>`
  (facultatif, on peut le faire plus tard par `Reparer`).
- `Etat` : ligne « Remontée vers CoGes : active / inactive, dernier envoi … » et place des journaux.
- `Desinstaller` : retire les raccourcis ; garde `support.json` comme les autres réglages.

## Bloc G — Tests et CI

- Pester : liste blanche du résumé (champ en trop refusé), aucun secret ni nom dans le rendu, ping
  jamais bloquant (faux serveur lent, en panne, 404), `/fail` au bon moment pour chaque signal,
  rotation des journaux (60 jours, 200 Mo, journal du jour gardé), contenu et taille du zip,
  raccourcis posés et retirés, `-Simulation`.
- `verifier.sh` (Linux, workflow « Sur site ») : un **faux serveur de pings** local (dans le job)
  reçoit les envois ; scénario : sauvegarde réussie ⇒ ping `sauvegarde` ; sauvegarde ratée exprès
  ⇒ `/fail` avec la raison ; mise à jour cassée (v0.90.3 du lot 5) ⇒ `/fail` `mise-a-jour` ;
  le corps reçu est relu par un test qui applique la liste blanche ; un diagnostic est produit et
  fouillé (aucun secret du `coges.env` du job, aucun nom de la démo).
- `check_protected_paths.py --base origin/main` sans dérogation.

## Bloc H — Documentation

- `docs/runbooks/sur-site.md` : « Support à distance » (créer les checks pour un nouveau client,
  préparer `support.json`, ce que je reçois et quand, que faire à chaque alerte, aider avec
  l'Assistance rapide, lire un diagnostic) ; retirer le lot 6 de « Ce qui n'existe pas encore » ;
  si le tableau devient vide, le remplacer par « Ce que le sur-site ne fait pas » (photos, e-mails,
  notifications sur téléphone, administration de la plateforme, accès depuis un autre appareil).
- `docs/decisions/0129-support-a-distance-sur-site.md` : choix des quatre questions, **liste exacte
  de ce qui sort du PC**, ce qui ne sort jamais, limites.
- `docs/contrat/annexe-donnees-sur-site.md` (nouveau) : la même liste en français simple, pour
  l'annexe du contrat de licence et de maintenance (ce qui sort, vers où, pourquoi, comment
  l'arrêter).
- `docs/prompt-sur-site/README.md` : lot 6, et la liste « à vérifier sur Windows » :
  1. `-Action Reparer -Support <fichier>` puis `-Action TesterSupport` : les trois checks reçoivent
     le test.
  2. Ouverture de session : ping `vie` reçu, avec le résumé ; rien de commercial dedans.
  3. Sauvegarde : ping `sauvegarde` reçu ; clé USB débranchée et date de copie vieillie : le résumé
     le dit.
  4. Docker Desktop arrêté exprès pendant une sauvegarde planifiée : `/fail` reçu, alerte chez moi.
  5. PC éteint 4 jours (ou check mis en pause puis repris) : alerte « silence » reçue.
  6. Mise à jour (v0.4.1 sur le canal `test`) : ping `mise-a-jour` reçu après l'application.
  7. Raccourci « Diagnostic CoGes » : zip sur le Bureau, moins de 10 Mo ; fouillé : aucun mot de
     passe, aucun nom de client ou d'article.
  8. Raccourci « Aide CoGes » : l'Assistance rapide s'ouvre ; prise en main depuis un autre PC.
  9. Internet coupé : aucune action ne bloque ni n'échoue à cause des pings ; journal seulement.

## Ce que tu ne fais pas dans ce lot

- Aucune commande à distance qui agit sur le PC sans quelqu'un devant (pas d'agent qui écoute, pas
  de canal de commandes) : agir passe par l'Assistance rapide, avec l'accord du commerçant.
- Aucun envoi automatique de fichier (diagnostic, sauvegarde) vers Internet.
- Aucun changement sur le VPS, l'application ou la production.

## Livrable

Branche `feat/sur-site-support`, commits atomiques en anglais ; questions **avant** de coder, puis
plan court, puis feu vert ; sorties réelles montrées ; **pas de push ni de PR avant mon accord**.
À la fin, mets à jour `CLAUDE.md` (sections 8 et 9) et le tableau des lots du README : le sur-site
est complet côté code ; seule reste la vérification Windows des lots 5 et 6.
