# 0084 — Sauvegarde externe chiffrée, hors de Neon et hors du VPS

- **Date** : 2026-10-17
- **Phase** : prompt 19 (après les prompts 16, 17 et 18)
- **Statut** : acceptée
- **Décideur** : cahier des charges du propriétaire, options recommandées appliquées
  (consigne du 2026-10-17)

## Contexte

Neon garde l'historique (PITR, 6 h en préprod, plus en offre payante), mais une copie qui
dépend du même fournisseur et du même compte ne protège ni d'une erreur de compte, ni
d'un incident chez Neon, ni d'une suppression par erreur au-delà de la fenêtre. Il faut
une copie chiffrée, ailleurs, et la preuve qu'on sait la relire.

## Décision

- **Où** : un workflow GitHub Actions planifié (`backup.yml`, chaque nuit à 02 h 15 UTC
  et à la main), **pas sur le VPS** : la sauvegarde continue si le VPS tombe, et aucun
  accès « lecture de toute la base » n'est déposé sur le VPS.
- **Rôle `coges_backup`** : LOGIN, BYPASSRLS, rien d'autre (`NOINHERIT`, aucune
  appartenance, `CONNECTION LIMIT 2`, `default_transaction_read_only = on`), créé par
  `deploy/sql/create_backup_role.sql` (cluster) ; SELECT seul sur toutes les tables et
  séquences de `public`, y compris les futures, par la **révision 0023**. **Vérifié sur
  Neon** (préprod, PostgreSQL 16.15) le 2026-10-17 : `neondb_owner` a BYPASSRLS et les
  rôles `coges_auth`, `coges_bus`, `coges_ops` en sont déjà dotés ; Neon le permet.
- **Exception à T36** : c'est le seul rôle connectable qui franchit la RLS (`pg_dump` ne
  verrait aucune ligne sinon, même sous `coges_owner`, les tables étant en FORCE). Elle
  est nommée dans le test, et bornée par de nouveaux tests : aucune écriture, aucun
  `EXECUTE` sur une fonction `SECURITY DEFINER`, aucune appartenance, lecture de toutes
  les tables (dump complet). Garde-fous : l'API et les workers refusent de démarrer sous
  un rôle BYPASSRLS (garde-fou 1) ; aucun code de `app/` ne le nomme ;
  `check_runtime_env.py` refuse son DSN sur le VPS (tests d'architecture).
- **Chaîne** (`deploy/scripts/backup.sh`) : `pg_dump -Fc` 16 (même version majeure que
  Neon) → tube → `age` avec la **clé publique** seule → `coges-AAAA-MM-JJ-HHMM.dump.age`
  et `.sha256` → `rclone` vers un stockage objet S3 hors Neon (Cloudflare R2, Backblaze B2
  ou Infomaniak Swiss Backup, au choix du propriétaire), clés d'écriture et de liste sans
  droit de suppression, `--immutable`. Le dump en clair ne touche ni un disque ni un
  artefact. Relecture du fichier distant (taille et sha256), échec si la taille tombe
  sous 50 % de la précédente (dump tronqué ou base vidée), ping Healthchecks.io
  (succès, `/fail`), aucune donnée personnelle dans le journal.
- **Rétention** (`backup_retention.py`, `backup-purge.yml`, dimanche 03 h 45 UTC) : 7
  quotidiennes, 4 hebdomadaires (dimanche), 12 mensuelles (le 1er), jamais rien de moins
  de 7 jours ; compte de stockage **distinct** (liste + suppression), pour qu'un
  workflow de sauvegarde compromis ne puisse pas effacer l'historique ; lancement manuel
  en essai à blanc par défaut. Autre voie décrite : règle de cycle de vie du bucket.
- **Restauration** (`restore_backup.sh`) : vérifie le sha256, refuse la production
  (`COGES_PRODUCTION_DB_HOST` obligatoire), refuse une base non vide, déchiffre en tube
  vers `pg_restore` (propriétaires conservés), puis `verify_restore.py` : révision
  Alembic à la tête du dépôt, lignes par entreprise, RLS FORCE partout, partition d'audit
  du mois, séquences, stock = somme des mouvements, aucun stock négatif, dettes
  cohérentes, aucun paiement plus lettré que son montant.
- **Preuve en CI** (`backup_chain_check.sh`, job « Sauvegarde : chaîne complète ») :
  base `demo` → `backup.sh` sous `coges_backup` → faux stockage local → restauration dans
  une base vide → vérifications vertes ; une seconde restauration est refusée. Aucun envoi
  réel. Jouée aussi en local le 2026-10-17 (trois entreprises, tout vert).

## Écarts au prompt, assumés

- Scripts dans `deploy/scripts/` (convention du dépôt) au lieu de `scripts/`.
- La CI de la chaîne tolère une base locale sans TLS par `BACKUP_ALLOW_LOCAL=1`, refusé
  pour tout hôte non local (test).

## Conséquences

- Prérequis de déploiement : `create_backup_role.sql` sur chaque cluster Neon **avant**
  la migration 0023 (sinon elle échoue, message explicite).
- Secrets et variables à créer : environnement GitHub `backup` (`BACKUP_DATABASE_URL`,
  `BACKUP_AGE_RECIPIENT`, clés S3 d'écriture, `BACKUP_PING_URL`, variables
  `BACKUP_S3_*`, `BACKUP_REMOTE_PATH`) et `backup-purge` (clés S3 de purge).
- Guide : `docs/runbooks/sauvegarde.md` (restaurer pas à pas, RTO/RPO, garde de la clé
  privée age).
