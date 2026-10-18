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
| Alerte | Healthchecks.io, délai de grâce 26 h | e-mail si aucune sauvegarde réussie depuis 26 h |
| Clé de déchiffrement (clé PRIVÉE age) | **chez vous seulement** : gestionnaire de mots de passe + copie hors ligne | — |

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
| Compte Neon bloqué (facture, fraude) | idem | cette copie, sur un autre compte Neon ou un autre PostgreSQL 16 |

## Restaurer pas à pas

Il vous faut : la clé privée, un poste avec `age`, `rclone` et le client PostgreSQL 16
(`sudo apt install age rclone postgresql-client-16`), le dépôt CoGes, et un accès en
lecture au stockage.

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
     coges_ops TO neondb_owner;` sur cette cible seulement.
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
