# 0128 — Mises à jour à distance et retour arrière sur site (lot 5)

- **Date** : 2026-11-21
- **Phase** : sur site, lot 5 (`docs/prompt-sur-site/05-mises-a-jour-a-distance.md`)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, deux fois, puis deux ajouts au plan)

## Contexte

Jusqu'au lot 4, changer la version d'un client demandait d'aller sur place et de taper
`-Action Reparer -Version vX.Y.Z`. Ce lot permet de publier une version depuis chez CoGes. Chaque
PC la voit seul, la télécharge sans gêner la boutique, l'installe à une heure calme, se vérifie,
et **revient seul en arrière** si quelque chose casse, données comprises. Aucun port ouvert,
aucune connexion entrante : le PC **va chercher** (ADR 0124). Règles du lot : ajouter seulement,
pas de changement de l'application ni d'image nouvelle, la production et ses workflows intacts.

## Décisions de l'utilisateur

1. **Le canal est un fichier sur `main`** : `deploy/onprem/canal/<canal>.json`, lu par
   `https://raw.githubusercontent.com/papa-bothie/CoGes/main/deploy/onprem/canal/<canal>.json`.
   Changer la version de tous les clients = une pull request qui modifie ce fichier.
2. **Canal non signé.** Risque assumé : quelqu'un qui prend la main sur le compte GitHub peut
   pousser une version chez tous les clients. Contre-mesures de ce lot : `.github/CODEOWNERS`
   (`deploy/onprem/canal/` → propriétaire), section « Protéger le compte GitHub » du guide
   (double authentification, protection de `main` : pull request obligatoire, pas de
   force-push). **Amélioration prévue** : une signature Ed25519 par une clé tenue par le
   propriétaire seul, vérifiée par la clé publique posée à l'installation. Le champ
   `signature` est **réservé** dès maintenant (toujours `null`, tout autre valeur est
   refusée) : la signer plus tard ne change pas le format.
3. **Quand** : téléchargement dès que la version est vue (CoGes tourne) ; application à
   **21 h 30** (réglable), seulement si **aucune vente depuis 30 minutes**, sinon le soir
   suivant ; jamais au démarrage du PC ; `-Action MettreAJour -Maintenant` pour forcer.
4. **Réglage par client** : `reglages\mise-a-jour.json` (`canal` : `stable` par défaut, `test`
   pour le PC d'essai ; `automatique` ; `heure`). Hors de `coges.env`, sans secret.
   `-Action Reparer -HeureMiseAJour 13:00` (et `-CanalMiseAJour test`) l'écrit et repose la tâche.
5. **Empreinte du programme = son contenu**, pas le `.zip` : GitHub fabrique l'archive d'une
   étiquette à la demande et ne garantit pas les octets dans le temps. sha256 du texte
   « `<sha256 du fichier>  <chemin>\n` » trié par chemin, sur les fichiers de `deploy/onprem/`
   qu'`Install-Programme` pose (hors `__pycache__`). Même calcul dans `publier.py` et
   `Get-CogesProgrammeDigest`, vérifié par un test croisé (Pester appelle Python).
6. **Une mise à jour ratée ne se retente plus seule.** La version passe en `echec` : seuls une
   version nouvelle sur le canal ou `-Action MettreAJour -Maintenant` la relancent. Pas de
   coupure ni de retour arrière chaque soir pour une migration qui rate toujours.
7. **Ajout au plan — l'alternative manuelle après 3 jours.** Une version `prete` qui n'a pas
   pu s'appliquer depuis 3 jours (PC éteint à l'heure prévue, ventes récentes) : raccourci
   « Mettre CoGes à jour » sur le Bureau (`Mettre CoGes à jour.cmd`) et une notification au
   plus une fois par jour (« Une mise à jour de CoGes est prête. Quand vous avez 5 minutes
   sans client, double-cliquez sur « Mettre CoGes à jour » sur le Bureau. »). Le raccourci
   lance `-Action MettreAJour -Maintenant -Bureau` dans une fenêtre visible : mots simples
   (« CoGes sera indisponible environ N minutes ; vos données sont sauvegardées avant »,
   N = durée de la dernière mise à jour, 5 sinon), `OUI` à taper, mêmes étapes et même retour
   arrière ; à la fin, « CoGes est à jour (vX). Vous pouvez reprendre. » ou « La mise à jour a
   échoué ; CoGes est revenu à vY. Rien n'est perdu. », puis la fenêtre attend Entrée. Le
   raccourci disparaît quand la version est appliquée, ratée ou annulée. `Etat` dit depuis
   combien de jours elle attend, et pourquoi.
8. **Ajout au plan — sans signature, protéger le compte** : CODEOWNERS et la section du guide
   (point 2).

## Format du canal « COGES-CANAL-1 »

```json
{
  "format": "COGES-CANAL-1",
  "canal": "stable",
  "version": "v0.4.0",
  "publiee_le": "2026-11-22",
  "depuis_minimum": "v0.3.0",
  "images": { "front": "sha256:…", "api": "sha256:…", "worker": "sha256:…" },
  "programme": { "sha256": "<64 hexadécimaux>", "fichiers": 27 },
  "docker_desktop_minimum": null,
  "note": "Une ou deux phrases pour le technicien.",
  "signature": null
}
```

- `images` : le digest **vers lequel pointe l'étiquette** sur ghcr.io au moment de la
  publication (en-tête `Docker-Content-Digest`, index OCI compris).
- `depuis_minimum` : la plus ancienne version qui peut sauter directement à celle-ci ; plus
  ancienne, le PC refuse (« installez d'abord vM »).
- Écrit par `deploy/onprem/canal/publier.py` depuis une étiquette déjà publiée (bibliothèque
  standard seulement, jeton anonyme du registre). Il refuse une version sans
  `windows/mise-a-jour.ps1` (elle ne saurait pas se mettre à jour ensuite) et une version plus
  ancienne que celle que le fichier annonce déjà.

Le PC refuse, sans rien changer : canal illisible ou incomplet, canal d'un autre nom, version
plus ancienne que l'installée (le canal ne fait jamais redescendre), saut trop grand, Docker
Desktop trop ancien (lu dans `docker version`, `Server.Platform.Name`).

## Télécharger (`-Action VerifierMiseAJour`, tâche « CoGes - mise à jour »)

Tâche du même style que les deux autres (utilisateur courant, sans élévation, cachée) : 12 h,
18 h, ouverture de session (+10 min) et l'heure du soir ; `StartWhenAvailable`, une instance à la
fois. Sans Internet : rien, journal seulement.

1. Archive dans `C:\CoGes\mises-a-jour\<version>\programme.zip`, empreinte du contenu vérifiée,
   puis dépliée et contrôlée à côté (`Expand-CogesProgramme`, tiré d'`Install-Programme`).
2. Les trois étiquettes relues sur le registre **avant** tout téléchargement : une qui ne
   pointe plus vers le digest du canal arrête tout. Puis `docker pull <image>@<digest>` (jamais
   par l'étiquette), `docker tag` sur le PC, `RepoDigests` relu.
3. Les images d'autres éditeurs du **nouveau** compose (Caddy, PostgreSQL, Redis, autoheal).
4. 5 Go libres au moins après le téléchargement ; puis l'état `prete`.
5. Les images de plus de deux versions en arrière partent (jamais celle en service ni la
   précédente).

États (`C:\CoGes\mises-a-jour\etat.json`) : `vue`, `telechargement`, `prete`, `appliquee`,
`echec`, `annulee`, `remplacee` (une prête dépassée par une plus récente).

## Appliquer (`-Action MettreAJour [-Maintenant]`), verrou commun tenu

1. Conditions : version prête et images au bon digest, Docker, 5 Go libres, aucune vente
   créée, modifiée ou confirmée depuis 30 minutes (sauf `-Maintenant`).
2. Sauvegarde chiffrée `-avant-maj` (lot 4), copiée sur la clé si elle est branchée.
3. Contrôle à blanc : `check_onprem_env.py` **du nouveau programme**, dans la **nouvelle** image
   `worker`, contre les réglages actuels (plus les lignes ajoutées), passés par l'**entrée
   standard** (`--env-file /dev/stdin`, `docker run -i`) : aucun fichier temporaire de secrets.
   Une ligne du nouveau modèle absente de `coges.env` est ajoutée **à l'étape 6** avec sa valeur
   par défaut documentée ; un secret absent est un refus.
4. Arrêt de `front`, `api`, `worker`, `beat`, `relay` (Caddy montre la page de maintenance).
5. Copie `coges_avant_maj_AAAAMMJJ_HHMMSS` (`CREATE DATABASE … TEMPLATE coges`, application
   arrêtée) par `base.py copier` : le retour arrière se fait **sans la clé privée**. Une
   nouvelle mise à jour supprime la copie de la précédente (un seul point de retour).
6. `Install-Programme -GarderPrecedent` (l'ancien dans `programme.precedent`),
   `COGES_IMAGE_TAG` (et les lignes ajoutées) écrits **d'un coup** (`File.Replace`, droits
   `icacls` reposés), `migrate`, `up -d`.
7. Neuf services `healthy` (5 min), page d'accueil 200, administration 404, licence « actif,
   sans fin », **même nombre** de sociétés et de ventes qu'à l'étape 5, tâches planifiées
   reposées.
8. Échec en 6 ou 7 : **retour automatique** — arrêt, ancien programme, `coges.env` d'avant **à
   l'octet**, copie remise par `base.py remettre --ecarter echec` (la base ratée gardée sous
   `coges_echec_maj_…`), `up -d`, mêmes vérifications. Toast et journal : « La mise à jour vers
   vX a échoué ; CoGes est revenu à vY. Rien n'est perdu. CoGes est prévenu au prochain passage
   (lot 6). » Si le retour échoue aussi : « appelez CoGes », rien n'est effacé.
9. Réussite : la copie et `programme.precedent` gardés **7 jours**, puis supprimés par la tâche.

`Set-CogesEnvValue` écrit désormais aussi d'un coup (même fonction de texte).

## Revenir en arrière plus tard (`-Action RevenirVersionPrecedente`)

Dans les 7 jours : les ventes faites depuis la mise à jour sont comptées et annoncées comme
**perdues** ; sauvegarde `-avant-retour` d'abord ; `REVENIR` puis le code de la boutique ; copie
remise (la base d'après gardée sous `coges_apres_maj_…`, proposée par `NettoyerAncienneBase`),
ancien programme, ancienne version, démarrage, vérifications ; la version passe en `annulee` et
ne s'applique plus seule. Au-delà de 7 jours : refus, et renvoi vers `Reparer -Version` puis
`Restaurer` avec la sauvegarde `-avant-maj`. Jamais de `downgrade` Alembic.

## Ce qui n'est pas remis en arrière

Les volumes Redis (file et cache), état de beat, modèles de prévision et fichiers statiques du
front : des caches, refaits seuls. Les images d'autres éditeurs : le compose d'avant reprend les
siennes, gardées sur le PC.

## Essais (`deploy/onprem-ci/verifier-mises-a-jour.sh`, workflow « Sur site »)

Un registre local `registry:2.8.3`, trois versions faites des images construites par le job :
`v0.90.1`, `v0.90.2` (une couche `LABEL` : d'autres digests) et `v0.90.3` dont le worker porte une
migration qui échoue. Les numéros sont des `vX.Y.Z` (et non `ci-a`/`ci-b`) parce que le PC compare
les versions. Canaux écrits par `publier.py` ; archives au format de GitHub ; le vrai
`installer.ps1` sous pwsh. Scénarios : canal faux (digest de l'API, empreinte du programme,
canal incomplet) refusés sans rien tirer ; `v0.90.1 → v0.90.2` (données identiques, version
lue) ; vente en `v0.90.2` puis `RevenirVersionPrecedente` (vente annoncée perdue, sauvegardée
d'abord) ; `v0.90.1 → v0.90.3` (retour automatique, données identiques, version en échec non
reprise). Variables d'essai, sans effet en production : `COGES_CANAL_ESSAI`,
`COGES_ARCHIVE_ESSAI`, `COGES_BUREAU_ESSAI`, `COGES_PLACE_MIN_ESSAI`.

## Limites

- Pas d'exécution réelle sur Windows en CI : la tâche planifiée et ses déclencheurs, la
  notification, le raccourci du Bureau, `File.Replace` et `icacls` sur NTFS, `Get-CimInstance`
  pour l'heure de démarrage, un vrai ghcr.io et un vrai raw.githubusercontent.com (cache de
  quelques minutes) se vérifient sur le PC (liste du README des lots).
- Le premier PC en v0.3.0 n'a pas ce code : la première version qui le contient s'installe une
  fois à la main (`-Action Reparer -Version vX`).
- Changer l'heure à la main dans `mise-a-jour.json` ne repose pas la tâche : `-Action Reparer
  -HeureMiseAJour HH:MM` le fait.
- Un changement de version majeure de PostgreSQL dans un compose futur n'est pas pris en charge
  par ce mécanisme (il demanderait un dump et une restauration).
- Aucune remontée vers CoGes (« mise à jour réussie chez tel client ») : lot 6.
