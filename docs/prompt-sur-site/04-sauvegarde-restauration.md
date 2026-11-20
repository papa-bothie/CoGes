# Lot 4 — Sauvegarde et restauration locales

> À donner à l'agent Claude Code, dans le dépôt `CoGes`, sur une branche `feat/sur-site-sauvegarde`
> partie de `main` (lots 1, 2 et 3 fusionnés : PR #92, #93 et #95). Un seul lot, une seule PR.
> Suite de `01-assemblage.md`, `02-licence.md` et `03-script-installation.md` : **mêmes règles**.

## But

Aujourd'hui, une installation sur site n'a **aucune sauvegarde** : un disque qui lâche, un PC
volé ou un `down -v` de trop, et la boutique perd tout. Ce lot ajoute :

1. une **sauvegarde automatique** de la base, plusieurs fois par jour, sur le PC ;
2. une **copie hors du PC** (clé USB ou disque externe), sans geste technique pour le commerçant ;
3. une **preuve régulière** que les sauvegardes se relisent (restauration d'essai) ;
4. une **restauration** en une commande, sur le même PC ou sur un PC neuf, qui ne détruit
   rien tant que la base restaurée n'a pas été vérifiée.

Critère de fin du lot (README) : **une panne simulée, les données retrouvées** — en CI sous
Linux, puis sur le PC Windows par le propriétaire.

## Règles d'or (inchangées)

1. **Ajouter, ne rien modifier** (ADR 0124). Aucun fichier de `deploy/vps/**`, `deploy/scripts/**`,
   `deploy/sql/**`, `backend/**`, `frontend/**`, `.github/workflows/deploy.yml`, `backup*.yml`.
   **Aucune nouvelle dérogation** dans `check_protected_paths.py`. S'il en faut une : stop, demande.
2. **La sauvegarde de la production (ADR 0084) n'est pas touchée** : ni son script, ni ses
   workflows, ni ses secrets. Tu peux t'en **inspirer** et en **recopier** de la logique dans
   `deploy/onprem/` (qui doit rester autonome), avec un test qui garde la copie fidèle (bloc G).
3. **Pas de nouvelle image, pas de changement de l'application.** Tu n'as que les images déjà
   tirées par le PC : `postgres:18.7-alpine` (a `pg_dump`, `pg_restore`, `psql`, pas Python) et
   `worker` (a Python et `cryptography`, pas les outils PostgreSQL). Vérifie-le toi-même.
4. **Jamais d'écrasement silencieux de la base** : la restauration se fait d'abord **à côté**,
   puis on échange ; l'ancienne base est **gardée**.
5. **Aucun secret** dans un journal, un nom de fichier, un argument de ligne de commande.
6. **Tu ne peux pas tester sur Windows** : prouve sous Linux ce qui peut l'être, liste le reste.

## Avant d'écrire (lis les vrais fichiers)

- `deploy/onprem/docker-compose.yml` (service `postgres`, volumes `pgdata`, `redis-data`, `ml-artifacts`,
  `beat-state`, `front-static`, `caddy-*`, réseau `interne` sans sortie, profil `tools`), `postgres-init/01-roles.sql`
- `deploy/onprem/windows/CoGes.Install.ps1` : **réutilise** `Invoke-CogesStep`, `Write-Log`, `Mask-Secrets`,
  `Invoke-Docker`, `Invoke-CogesCompose`, `Get-CogesPath`, `Stop-CogesStep`, le style des messages
  (« ÉCHEC — … / Quoi faire : … ») et le mode `-Simulation`
- La sauvegarde de production : `deploy/scripts/backup.sh` (manifeste compté **avant** le dump, versions de
  `pg_dump` et du serveur, `alembic_revision`), `restore_backup.sh`, `verify_restore.py` (contrôles d'une base
  restaurée), `restore_toc_filter.py`, `docs/runbooks/sauvegarde.md`, ADR 0084, 0088, 0095
- `deploy/onprem-ci/verifier.sh` et `controle_donnees.py` (ce que la CI rejoue et relit déjà)
- `docs/runbooks/sur-site.md`, `docs/prompt-sur-site/README.md`, `CLAUDE.md`

**Questions à trancher avec moi** (`AskUserQuestion`, au début, en une fois) — au moins :

1. **Chiffrement de la copie hors du PC.** Ma recommandation : **par clé publique, comme la production** —
   le PC n'a que la clé publique (il chiffre, il ne peut pas relire) ; la clé privée reste chez CoGes
   (gestionnaire de mots de passe + copie hors ligne) et le technicien l'apporte pour restaurer. Mise en
   œuvre avec `cryptography` de l'image `worker` (X25519 + HKDF + AES-256-GCM par blocs, format écrit dans
   l'ADR, test aller-retour et test de falsification). Autres options : mot de passe connu du commerçant
   (scrypt) ; pas de chiffrement. Donne les conséquences de chacune (qui peut restaurer seul, ce qui se
   passe si la clé ou le mot de passe est perdu, ce que livre une clé USB volée).
2. **Rythme** : ma recommandation, à **13 h 00 et 20 h 30** chaque jour, plus une au démarrage du PC si la
   dernière a plus de 20 h (le PC d'une boutique est souvent éteint la nuit).
3. **Rétention sur le PC** : ma recommandation, les 14 dernières, plus 1 par semaine sur 8 semaines, plus
   1 par mois sur 12 mois.

## Ce qui est sauvegardé

- **La base PostgreSQL entière** (`pg_dump --format=custom`) en superutilisateur `postgres` (seul rôle qui
  lit sans filtre RLS ; vérifie-le), avec un **manifeste** JSON : date, version de CoGes (`COGES_IMAGE_TAG`),
  `alembic_revision`, versions du serveur et de `pg_dump`, lignes des tables clés comptées **avant** le dump
  (même requête que `verify_restore.py --print-manifest-query`), taille, sha256.
- **Pas** Redis (file d'attente et cache : l'outbox est en base), **pas** `caddy-*`, `front-static`,
  `beat-state`. Les modèles de prévision (`ml-artifacts`) : vérifie s'ils se recalculent la nuit ; si oui,
  pas de sauvegarde, et dis-le dans l'ADR.
- **`coges.env` n'est pas dans la sauvegarde.** Vérifie et écris dans l'ADR **qu'une base restaurée
  fonctionne avec un `coges.env` neuf** (rôles recréés par `01-roles.sql` avec les nouveaux mots de passe ;
  `COGES_JWT_SECRET` neuf = tout le monde se reconnecte ; `COGES_MFA_ENCRYPTION_KEY` : quelles données en
  dépendent sur site ? aucune si l'administration n'existe pas sur le poste — prouve-le). Si une donnée en
  dépend, **stop et demande**.

## Bloc A — Faire une sauvegarde (`-Action Sauvegarder`)

Nouvelle action de `installer.ps1`, fonction `New-CogesBackup` **réutilisable par le lot 5** (sauvegarde
obligatoire avant chaque mise à jour) et par `Desinstaller -EffacerLesDonnees` (bloc F).

- Dossier : `C:\CoGes\sauvegardes\` (hors `programme\` et `reglages\`). Nom :
  `coges-<code-boutique>-AAAAMMJJ-HHMM-<version>.coges` + `.manifest.json` (+ `.sha256`).
- **Le dump en clair ne touche jamais le dossier du PC ni la clé USB** : il passe dans un volume Docker
  temporaire (ou un tube **entre conteneurs**), est chiffré, puis effacé. **Jamais de tube binaire à travers
  PowerShell 5.1** (il corrompt les octets) : tout ce qui est binaire reste dans les conteneurs ou passe par
  des fichiers.
- Le service ou la commande de sauvegarde : dans `docker-compose.yml`, **ajouts seulement** (profil `tools`,
  réseau `interne`, aucune sortie Internet, aucun port). Pas de DSN propriétaire hors de `migrate` : le
  contrôle `--rendered` de `check_onprem_env.py` doit continuer à passer — s'il faut l'étendre pour un
  nouveau service, ajoute la règle et son test.
- Contrôles avant de dire « bon » : `pg_restore --list` lit le fichier déchiffré (dans le conteneur), taille
  non nulle et pas moins de 50 % de la précédente (comme la production), sha256 écrit et relu, manifeste
  complet. Sinon : échec clair, fichier marqué `.echec` et jamais compté dans la rétention.
- Espace : refuse si moins de 2 Go libres après la sauvegarde prévue ; dit quoi faire.
- Base qui tourne : la sauvegarde se fait **sans arrêter CoGes** (instantané cohérent de `pg_dump`).
- Rétention (bloc question 3) : fonction pure testée ; ne supprime **jamais** la dernière bonne, ni un
  fichier `.echec`, ni ce qui n'a pas le nom attendu.

## Bloc B — Copie hors du PC

- Le commerçant **branche** une clé USB ou un disque préparé par le technicien : à sa racine, un fichier
  `COGES-SAUVEGARDE.txt` qui contient le code de la boutique. **Sans ce fichier, rien n'est écrit** sur un
  disque branché (on n'écrit jamais sur une clé au hasard).
- À chaque sauvegarde, si un tel disque est présent, la dernière bonne y est copiée dans `\CoGes\` puis
  **relue** (sha256). Rétention sur le disque : les 10 dernières (plus ancienne effacée seulement après la
  copie relue).
- `-Action PreparerDisque -Lecteur E:` (technicien) : écrit le fichier repère, vérifie l'espace, fait une
  première copie.

## Bloc C — Planifier et prévenir

- Tâche planifiée **« CoGes - sauvegarde »** (même manière que « CoGes - démarrage » du lot 3 : utilisateur
  courant, sans élévation, `-WindowStyle Hidden`, `StartWhenAvailable`), aux heures choisies, plus le
  rattrapage au démarrage. Posée par `Installer` et `Reparer`, retirée par `Desinstaller`. Elle ne fait rien
  si Docker ne répond pas (journal), sans fenêtre qui s'ouvre.
- **Prévenir le commerçant sans changer l'application** : notification Windows (toast, API WinRT de
  Windows PowerShell 5.1) **seulement** quand il faut agir : aucune bonne sauvegarde depuis 48 h ; aucune
  copie hors du PC depuis 7 jours (« Branchez la clé CoGes ») ; disque presque plein. Texte en français
  simple, sans jargon. Si le toast échoue, journal seulement (jamais d'échec de la sauvegarde pour ça).
- `-Action Etat` gagne : dernière bonne sauvegarde (date, taille), dernière copie hors du PC, dernière
  restauration d'essai, nombre de fichiers gardés, place restante.

## Bloc D — Restauration d'essai (la preuve)

- Une fois par semaine (le dimanche, ou au premier démarrage après), la dernière sauvegarde est restaurée
  dans une base **temporaire** `coges_verif` du même PostgreSQL, puis vérifiée, puis supprimée.
- Les contrôles sont ceux de `verify_restore.py` (révision Alembic = manifeste, tables clés ≥ manifeste,
  RLS FORCE, cohérence stock et dettes…). L'image `postgres` n'a pas Python et l'image `worker` n'a pas
  `psql` : à toi de trouver le montage le plus simple **sans nouvelle image** (par exemple : les requêtes
  lancées par `psql` dans le conteneur postgres, la logique en SQL ; ou une version de la vérification qui
  parle par `psycopg` depuis le worker). Note le choix dans l'ADR.
- Résultat gardé (dernier succès / échec) pour `Etat` et pour le toast « La dernière sauvegarde ne se relit
  pas : appelez CoGes ».
- Mémoire : elle tourne pendant que CoGes tourne sur un PC de 8 Go ; mesure-la en CI et note-la.

## Bloc E — Restaurer (`-Action Restaurer -Fichier <chemin> [-Cle <chemin>]`)

Pour le **technicien**, en présence ou à distance (lot 6 plus tard). Dans l'ordre, chaque étape s'arrête au
premier problème **sans avoir rien changé** :

1. Fichier lisible, sha256 bon, manifeste lu ; récapitulatif (boutique, date, version, nombre de ventes au
   manifeste) ; tape `RESTAURER`.
2. Version : la révision Alembic de la sauvegarde doit être **connue** de la version installée (sauvegarde
   plus récente que le programme ⇒ refus : « installez d'abord la version vX.Y.Z »). Plus ancienne ⇒ la
   restauration se fait, puis `migrate`.
3. **Sauvegarde de la base actuelle d'abord** (bloc A), si elle existe et n'est pas vide.
4. Restauration dans `coges_restauration` (déchiffrée dans le conteneur, clé privée lue depuis `-Cle`,
   **jamais copiée** sur le PC), puis contrôles du bloc D.
5. Arrêt de `front`, `api`, `worker`, `beat`, `relay` (pas `postgres`, page de maintenance de Caddy) ;
   bascule par renommage : `coges` → `coges_avant_AAAAMMJJ_HHMM`, `coges_restauration` → `coges` ; vérifie
   les droits des rôles (même propriétaire, mêmes `GRANT` ; compare à une base fraîche).
6. `migrate` si besoin, `up -d`, attente des services, `license-status`, page d'accueil en 200.
7. En cas d'échec après la bascule : **retour automatique** à `coges_avant_…`, et message clair.
8. L'ancienne base est **gardée** ; `-Action Etat` la signale ; `-Action NettoyerAncienneBase` la supprime
   après confirmation (code de la boutique). Jamais de suppression automatique.

Cas à couvrir aussi : **PC neuf** (installation du lot 3, puis `Restaurer` : la société de la sauvegarde
remplace la base vide ; pas de `create-company` à refaire, pas de licence à reposer — vérifie que la
licence revient avec la base) ; **même PC après `down -v`**.

## Bloc F — Ce qui change dans le lot 3 (ajouts seulement)

- `Installer` : pose la tâche « CoGes - sauvegarde », fait une **première sauvegarde** à la fin, propose
  `PreparerDisque` (facultatif, on peut passer).
- `Desinstaller -EffacerLesDonnees` : exige une sauvegarde bonne de moins d'une heure (faite sur place si
  besoin), dit où elle est, **puis** seulement les confirmations existantes.
- `Reparer` : vérifie et repose la tâche.
- Mets à jour les tests Pester existants sans en affaiblir aucun.

## Bloc G — Tests et CI

- **Pester** : noms et rétention (PC et disque), repère de disque (absent, autre boutique, présent),
  contrôle de taille (50 %), messages, toast désactivable, calcul « rattrapage au démarrage », refus de
  version, `-Simulation` (rien écrit), aucun secret dans les journaux (même méthode que le lot 3).
- **Chiffrement** (si option 1) : tests Python aller-retour, octet modifié refusé, mauvaise clé refusée,
  fichier tronqué refusé, gros fichier par blocs (mémoire bornée).
- **Fidélité de la copie** : si tu recopies de la logique de `deploy/scripts/` (requête du manifeste,
  contrôles), un test compare les deux, pour qu'un changement de la production ne laisse pas le sur-site
  derrière.
- **`verifier.sh` (Linux, workflow « Sur site »)**, à la suite du parcours existant : ventes créées →
  sauvegarde → `down -v` → installation neuve → restauration → `controle_donnees.py` relit **les mêmes**
  chiffres ; puis fichier modifié d'un octet refusé ; sauvegarde d'une révision inconnue refusée ;
  restauration qui échoue après la bascule (simulée) ⇒ retour à l'ancienne base. Mesure la durée et la
  mémoire. Le temps total du job reste sous 30 minutes ; sinon un job à part, même workflow.
- `check_protected_paths.py --base origin/main` : OK sans dérogation.

## Bloc H — Documentation

- `docs/runbooks/sur-site.md` : section **« Sauvegarde et restauration »** (ce qui est fait seul, la clé USB,
  ce que dit `Etat`, que faire quand Windows prévient, restaurer sur le même PC ou sur un PC neuf, garder
  la clé privée) ; retirer le lot 4 de « Ce qui n'existe pas encore » ; corriger l'avertissement « aucune
  sauvegarde » de `Desinstaller`.
- `docs/decisions/0127-sauvegarde-sur-site.md` : décisions des trois questions, format du fichier, montage
  choisi pour la vérification, ce qui n'est pas sauvegardé et pourquoi, limites.
- `docs/prompt-sur-site/README.md` : lot 4 « ✅ code et CI ; à vérifier sur Windows », et la liste :

  **Lot 4 — à vérifier sur la machine Windows**
  1. Après `Installer`, la tâche « CoGes - sauvegarde » existe et la première sauvegarde est dans
     `C:\CoGes\sauvegardes\` (taille, `.manifest.json`, `.sha256`).
  2. `-Action Sauvegarder` à la main, CoGes ouvert dans le navigateur pendant ce temps : aucune coupure.
  3. Clé USB préparée (`PreparerDisque`), puis débranchée et rebranchée : copie faite à la sauvegarde suivante ;
     une clé **sans** repère reste intacte.
  4. PC éteint à l'heure prévue puis rallumé : rattrapage au démarrage.
  5. Toast « Branchez la clé CoGes » (forcer la date du dernier essai dans un PC de test) : il s'affiche, en
     français, sans fenêtre noire.
  6. Restauration d'essai de la semaine : résultat dans `Etat`.
  7. **Panne simulée** : `Desinstaller -EffacerLesDonnees`, puis `Installer`, puis `Restaurer` depuis la clé USB :
     la société, les ventes et la licence sont là ; connexion du gérant.
  8. Restauration sur un **deuxième PC** (si disponible) avec le même fichier et la clé privée.
  9. Fichier abîmé (un octet changé) : refusé, rien n'a changé.
  10. Aucun mot de passe ni clé dans `C:\CoGes\journaux\*.log`, et aucun fichier `.dump` en clair nulle part
      sur le disque (`Get-ChildItem C:\ -Recurse -Filter *.dump`).

## Ce que tu ne fais pas dans ce lot

- Pas d'envoi des sauvegardes sur Internet (cloud) : sujet du lot 6 au plus tôt, et à décider.
- Pas de mise à jour automatique (lot 5) : seulement `New-CogesBackup` prêt à être appelé.
- Pas de sauvegarde de `coges.env` par le script : elle reste dans le gestionnaire de mots de passe de CoGes.

## Livrable

1. Branche `feat/sur-site-sauvegarde`, commits atomiques en anglais (`feat(onprem): …`, `test(onprem): …`,
   `docs(onprem): …`, `ci(onprem): …`).
2. Questions posées **avant** de coder, puis plan court, puis feu vert.
3. Sorties réelles montrées (Pester, PSScriptAnalyzer, tests Python, `verifier.sh`, chemins protégés).
4. **Pas de push ni de PR avant mon accord** : rapport court (prouvé / non prouvé), puis « Je pousse la branche
   et j'ouvre la PR ? ».
