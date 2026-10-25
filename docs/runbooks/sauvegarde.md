# Sauvegardes de CoGes — où elles sont, comment les relire (ADR 0084)

La base est chez Neon. Neon garde son propre historique (PITR), mais une copie chez le
même fournisseur ne protège ni d'une erreur de compte ni d'un incident chez lui. Chaque
nuit, GitHub fait donc une **copie chiffrée** de toute la base et la dépose **ailleurs**.
Ce guide dit où elles sont, comment en choisir une, comment la restaurer, et comment
garder la clé sans laquelle elles ne servent à rien.

## En bref

| Quoi | Où | Quand |
|---|---|---|
| Copie chiffrée de toute la base (`coges-AAAA-MM-JJ-HHMM.dump.age` + `.sha256` + `.manifest.json`) | stockage objet choisi (R2, B2 ou Swiss Backup), dossier `BACKUP_REMOTE_PATH` | chaque nuit à 02 h 15 UTC (workflow « Sauvegarde ») |
| Rétention | 7 quotidiennes, 4 du dimanche, 12 du 1er du mois | purge le dimanche à 03 h 45 UTC (workflow « Sauvegarde — purge ») |
| Alerte | Healthchecks.io, période 1 jour, délai de grâce 2 h | e-mail si aucune sauvegarde réussie depuis 26 h, ou dès un échec |
| Clé de déchiffrement (clé PRIVÉE age) | **chez vous seulement** : gestionnaire de mots de passe + copie hors ligne | — |

## Mise en service (une fois, par le propriétaire)

À faire dans cet ordre. Rien de ceci n'est dans le dépôt : ce sont des comptes, des clés
et des réglages GitHub. Tant que l'étape 4 n'est pas faite, le workflow « Sauvegarde »
échoue chaque nuit sur « BACKUP_DATABASE_URL manquant » : ce n'est pas un bug.

1. **Stockage externe en Europe**, hors Neon. Un bucket privé (par ex.
   `coges-sauvegardes`), et **deux clés distinctes** limitées à ce bucket :
   - clé de **sauvegarde** : écriture, liste et lecture (le script relit le fichier envoyé
     pour comparer son sha256), **sans suppression** ;
   - clé de **purge** : liste, lecture et suppression, pour le workflow « Sauvegarde —
     purge » seulement (`rclone deletefile` lit d'abord l'en-tête du fichier : sans
     `readFiles`, B2 répond 403 ; les fichiers sont chiffrés, la lecture ne livre rien).

   Backblaze B2 est conseillé : ses *Application Keys* se limitent à un bucket et à des
   droits précis (`listBuckets`, `listFiles`, `readFiles`, `writeFiles`, sans
   `deleteFiles` pour la clé de sauvegarde). Région européenne : `eu-central-003`
   (Amsterdam). Les jetons R2 de Cloudflare « Object Read & Write » incluent la
   suppression : avec R2, préférer une règle de cycle de vie à la clé de purge.

   Avec l'outil `b2` (`uvx --from b2 b2 …` ou `pipx install b2`), connecté par la clé
   maîtresse du compte, qui ne sert qu'ici :
   ```bash
   b2 account authorize      # demande l'applicationKeyId puis la clé, sans les afficher
   b2 bucket create coges-sauvegardes allPrivate \
     --default-server-side-encryption SSE-B2 \
     --lifecycle-rule '{"daysFromHidingToDeleting": 7, "daysFromUploadingToHiding": null, "fileNamePrefix": ""}'
   b2 key create --bucket coges-sauvegardes coges-backup \
     listBuckets,listFiles,readFiles,writeFiles
   b2 key create --bucket coges-sauvegardes coges-backup-purge \
     listBuckets,listFiles,readFiles,deleteFiles
   b2 account clear          # oublie la clé maîtresse sur le poste
   ```
   Chaque `b2 key create` affiche **une seule fois** le keyID puis la clé : les ranger
   aussitôt dans le gestionnaire de mots de passe (ce sont les secrets de l'étape 4).
   La règle de cycle de vie compte : par l'API S3, B2 ne supprime pas un fichier, il le
   **masque** et garde l'ancienne version. Sans elle, la purge ne libère aucune place ;
   avec 7 jours, un fichier masqué par erreur (ou par une clé volée) se récupère encore
   une semaine.
2. **Clé age** : voir la section suivante. Clé publique → secret GitHub
   `BACKUP_AGE_RECIPIENT` ; clé privée → gestionnaire de mots de passe **et** copie hors
   ligne, puis effacée du poste.
3. **DSN de `coges_backup`** sur l'**hôte direct** de Neon (le nom d'hôte **sans**
   `-pooler`) : `pg_dump` passe mal par un pooler en mode transaction. Toujours
   `sslmode=require`.
   ```bash
   DSN='postgresql://coges_backup:<mot de passe>@ep-xxx.eu-central-1.aws.neon.tech/coges?sslmode=require'
   psql "$DSN" -c "SELECT count(*) FROM companies"   # doit être > 0
   psql "$DSN" -c "SHOW server_version"              # 18.x
   ```
   Un résultat à 0 signifie que le rôle ne passe pas la RLS (BYPASSRLS manquant :
   `deploy/sql/create_backup_role.sql`).
4. **Environnements GitHub** (Settings → Environments), chacun limité à la branche
   `main` (*Deployment branches* : *Selected branches* → `main`).

   Environnement `backup` :

   | Nom | Type | Exemple (factice) |
   |---|---|---|
   | `BACKUP_DATABASE_URL` | secret | le DSN de l'étape 3 |
   | `BACKUP_AGE_RECIPIENT` | secret | `age1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs0example` |
   | `BACKUP_S3_ACCESS_KEY_ID` | secret | B2 : `003a1b2c3d4e5f60000000001` (keyID) ; R2 : `0123456789abcdef0123456789abcdef` |
   | `BACKUP_S3_SECRET_ACCESS_KEY` | secret | B2 : `K003exempleexempleexempleexempl` (applicationKey) ; R2 : la clé secrète du jeton |
   | `BACKUP_PING_URL` | secret | `https://hc-ping.com/0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0` |
   | `BACKUP_S3_PROVIDER` | variable | B2 : `Other` ; R2 : `Cloudflare` |
   | `BACKUP_S3_ENDPOINT` | variable | B2 : `https://s3.eu-central-003.backblazeb2.com` ; R2 : `https://<ACCOUNT_ID>.eu.r2.cloudflarestorage.com` |
   | `BACKUP_S3_REGION` | variable | B2 : `eu-central-003` ; R2 : `auto` |
   | `BACKUP_REMOTE_PATH` | variable | `coges-sauvegardes/prod` (bucket/préfixe) |

   `BACKUP_S3_PROVIDER` est une valeur de rclone (option `provider` du stockage `s3`,
   <https://rclone.org/s3/>) : `Cloudflare` existe ; rclone n'a **pas** de valeur
   « Backblaze » pour le S3, B2 passe par `Other`. L'adresse R2 en `.eu.` correspond à
   un bucket créé en juridiction UE ; sans juridiction, c'est
   `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.

   Environnement `backup-purge` : secrets `BACKUP_PURGE_S3_ACCESS_KEY_ID` et
   `BACKUP_PURGE_S3_SECRET_ACCESS_KEY` (la clé de purge), et les **mêmes variables**
   `BACKUP_S3_PROVIDER`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_REGION`, `BACKUP_REMOTE_PATH`.

   Poser un secret sans qu'il s'affiche ni entre dans l'historique du terminal : le lire
   avec `read -rs`, puis le passer à `gh` sur l'entrée standard, jamais en argument.
   ```bash
   read -rs v && printf '%s' "$v" | gh secret set BACKUP_DATABASE_URL --env backup --repo papa-bothie/CoGes; unset v
   gh variable set BACKUP_S3_PROVIDER --env backup --repo papa-bothie/CoGes --body Other
   gh secret list --env backup --repo papa-bothie/CoGes   # noms seulement
   ```
   Un script local `deploy/scripts/set_backup_secrets.sh` (hors du dépôt, facultatif)
   peut enchaîner ces saisies : il ne doit contenir aucune valeur et contrôler, avant
   tout envoi, que le DSN porte `sslmode=require` sans `-pooler` et que la clé age
   commence par `age1`.
5. **Healthchecks.io** : un contrôle « coges-sauvegarde », période 1 jour, **grâce 2 h**,
   alerte par e-mail. L'alerte part quand période + grâce sont écoulées sans ping (26 h
   après la dernière sauvegarde réussie), ou dès un ping `/fail`. Son URL de ping → `BACKUP_PING_URL`. Le script appelle l'URL en cas
   de succès et `<URL>/fail` en cas d'échec.
6. **Premier lancement** : Actions → « Sauvegarde » → *Run workflow* (branche `main`).
   Dans le journal : « serveur 18.x, pg_dump 18.x », puis « taille et sha256
   identiques » et « Sauvegarde … : OK ». Dans le bucket, sous `BACKUP_REMOTE_PATH`,
   **trois fichiers** : `coges-AAAA-MM-JJ-HHMM.dump.age`, `….dump.age.sha256` et
   `….dump.age.manifest.json` (ce dernier porte `server_version`, `pg_dump_version` et les
   lignes des tables clés). Healthchecks.io passe au vert.
7. **Premier exercice de restauration**, chronométré, sur une **branche Neon jetable**
   (console Neon → Branches → *Create branch*, puis une base vide `coges_secours`) :
   section « Restaurer pas à pas », puis remplir le tableau de l'« Exercice de
   restauration ». Faire aussi un exercice de PITR Neon (branche à un instant passé) :
   l'offre actuelle ne garde que **6 h** d'historique. Supprimer la branche ensuite.
8. **Une semaine plus tard** : Actions → « Sauvegarde — purge » → *Run workflow*, case
   « Lister seulement » cochée (essai à blanc). Vérifier la liste « à supprimer » : avec
   moins de 8 sauvegardes, elle doit être **vide**.

## La clé privée age : sans elle, les sauvegardes sont inutilisables

1. Sur votre poste : `age-keygen -o coges-backup.key`. La ligne « Public key: age1… » est
   la clé **publique** : elle va dans le secret GitHub `BACKUP_AGE_RECIPIENT`.
2. Le fichier `coges-backup.key` est la clé **privée**. La ranger :
   - dans le gestionnaire de mots de passe (une note sécurisée, contenu complet) ;
   - **et** une copie hors ligne dans un autre lieu : papier imprimé ou clé USB dans une
     enveloppe, chez un associé ou au coffre.
3. L'effacer du poste ensuite. Ne jamais la mettre dans GitHub, sur le VPS, dans un e-mail
   ou dans une conversation.
4. Une fois par an : vérifier que les deux copies se lisent (exercice ci-dessous).

## Quand utiliser quoi

| Situation | Ce qu'on perd | Utiliser |
|---|---|---|
| Suppression ou erreur de saisie il y a moins de quelques heures | rien | **PITR de Neon** : branche à l'instant d'avant (console Neon → Branches → Restore) |
| Erreur découverte après la fenêtre PITR | ce qui a été fait depuis la sauvegarde choisie | cette copie : la sauvegarde de la nuit d'avant l'erreur |
| Neon perdu (incident long, projet supprimé) | au plus une journée (depuis 02 h 15 UTC) | cette copie, restaurée sur un nouveau projet Neon |
| Compte Neon bloqué (facture, fraude) | idem | cette copie, sur un autre compte Neon ou un autre PostgreSQL 18 |

## Restaurer pas à pas

Il vous faut : la clé privée, un poste avec `age`, `rclone` et le client PostgreSQL 18
(voir « Client PostgreSQL » ci-dessous), le dépôt CoGes, et un accès en lecture au
stockage. **Restaurer avec un client au moins de la version indiquée dans le manifeste**
(`pg_dump_version` du `.manifest.json`) : `restore_backup.sh` refuse un `pg_restore` plus
ancien (ADR 0095).

### Client PostgreSQL

La production Neon est en **PostgreSQL 18**. `pg_dump` refuse un serveur d'une version
majeure plus récente que lui, et `pg_restore` une archive d'un `pg_dump` plus récent.

- Ubuntu ou Debian (le dépôt d'Ubuntu 24.04 n'a que le 16) :
  ```bash
  sudo apt install -y postgresql-common age rclone
  sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  sudo apt install -y postgresql-client-18
  export PATH=/usr/lib/postgresql/18/bin:$PATH   # sinon le 16 peut répondre
  pg_restore --version                            # doit dire 18.x
  ```
  Ou, depuis le dépôt : `bash deploy/scripts/install_pg_client.sh 18` (même chose,
  vérification comprise).
- macOS : `brew install postgresql@18 age rclone`, puis
  `export PATH="$(brew --prefix postgresql@18)/bin:$PATH"`.

1. **Choisir** la sauvegarde : `rclone lsf coges:<BACKUP_REMOTE_PATH>` (la plus récente
   AVANT l'incident) — jamais une qui porte un `.suspect` (trop petite, ADR 0088). La
   télécharger avec son `.sha256` et son manifeste (lignes des tables clés, comptées
   avant le dump) :
   ```bash
   rclone copy coges:<chemin>/coges-2026-10-18-0215.dump.age .
   rclone copy coges:<chemin>/coges-2026-10-18-0215.dump.age.sha256 .
   rclone copy coges:<chemin>/coges-2026-10-18-0215.dump.age.manifest.json .
   ```
2. **Préparer une base vide**, JAMAIS la production :
   - Neon : nouvelle branche (ou nouveau projet) → base `coges_secours`. Sur un projet
     neuf, lancer d'abord la création des rôles (`deploy/postgres/init/01-roles.sql` adapté,
     voir `deploy/README-infra.md`, « Rôles PostgreSQL ») puis
     `deploy/sql/create_backup_role.sql`. L'utilisateur qui restaure doit pouvoir
     emprunter les rôles propriétaires : `GRANT coges_owner, coges_auth, coges_bus,
     coges_ops, coges_billing TO neondb_owner;` sur cette cible seulement (et
     `deploy/sql/create_billing_role.sql` d'abord, ADR 0091).
   - Local : `make up`, puis `CREATE DATABASE coges_secours OWNER coges_owner`.
3. **Restaurer et vérifier** :
   ```bash
   COGES_PRODUCTION_DB_HOST=<hôte de la base de production> \
   deploy/scripts/restore_backup.sh coges-2026-10-18-0215.dump.age ~/coges-backup.key \
     "postgresql://neondb_owner:…@<hôte de la cible>/coges_secours?sslmode=require"
   ```
   Le script refuse un fichier abîmé (sha256), un manifeste absent, la base de
   production et une base non vide. Il déchiffre sans écrire de copie en clair, restaure,
   puis lance `verify_restore.py` : tout doit être **vert**, y compris « autant de lignes
   qu'à la sauvegarde ». Une sauvegarde antérieure au manifeste (avant l'ADR 0088) se
   restaure avec `RESTORE_WITHOUT_MANIFEST=1`.
4. **Basculer** (si on remplace la production) : mettre la nouvelle base dans
   `/etc/coges/coges.env` du VPS (`COGES_DATABASE_URL_*`), redéployer la même version
   (`deploy.sh production <version>`), prévenir les commerçants de la période perdue.

## Exercice de restauration (à chronométrer)

Une fois par trimestre, sur une branche Neon jetable : étapes 1 à 3 ci-dessus. Noter :

| Date | Sauvegarde utilisée | Âge de la sauvegarde au moment de l'exercice (RPO) | Durée de bout en bout (RTO) | Tout vert ? | Qui |
|---|---|---|---|---|---|
| | | | | | |

La CI rejoue la même chaîne à chaque changement du code (job « Sauvegarde : chaîne
complète », `deploy/scripts/backup_chain_check.sh`), avec une clé de test et un faux
stockage : elle prouve que les scripts marchent, pas que vous avez la clé.

## Une sauvegarde a échoué (alerte Healthchecks.io)

1. GitHub → Actions → « Sauvegarde » → dernière exécution : lire l'étape en échec.
2. Causes habituelles : mot de passe de `coges_backup` changé (secret
   `BACKUP_DATABASE_URL`), clés S3 expirées, quota du stockage atteint, Neon injoignable.
   « pg_dump N trop ancien pour un serveur M » : Neon est passé à une version majeure
   plus récente ; changer `PG_CLIENT_MAJOR` dans `.github/workflows/backup.yml` (et les
   autres fichiers listés par l'ADR 0095).
3. « moins de 0.5 fois la précédente » : la sauvegarde est envoyée mais suspecte. Vérifier
   la base **avant tout** (données supprimées ?) ; si c'est normal (grosse purge
   volontaire), relancer le workflow à la main.
4. Relancer à la main (« Run workflow ») une fois corrigé.

## Purge

Le workflow « Sauvegarde — purge » applique la rétention avec des clés **distinctes**
(liste + suppression). Lancé à la main, il ne fait qu'un essai à blanc par défaut. Autre
possibilité, sans clé de suppression du tout : une règle de cycle de vie du bucket
(R2 : *Object lifecycle rules* ; B2 : *Lifecycle settings*) qui supprime après 400 jours,
en gardant ce workflow pour les quotidiennes.
