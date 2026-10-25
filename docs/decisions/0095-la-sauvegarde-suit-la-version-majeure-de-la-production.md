# 0095 — La chaîne de sauvegarde suit la version majeure de la production

- **Date** : 2026-10-25
- **Phase** : lot « Sauvegarde PostgreSQL 18 » (branche `fix/backup-postgres-18`), préalable
  à la mise en service des sauvegardes
- **Statut** : acceptée
- **Décideur** : utilisateur (prompt du lot, qui fixe chaque point)

## Contexte

La production Neon (`coges-prod-eu`, `eu-central-1`) est en **PostgreSQL 18**. Toute la
chaîne de sauvegarde de l'ADR 0084 était en 16 : `backup.yml` installait
`postgresql-client-16` (le seul que fournit Ubuntu 24.04), le job CI « Sauvegarde : chaîne
complète » tournait sur `postgres:16`, le guide demandait le client 16. Or `pg_dump`
refuse un serveur d'une version majeure plus récente que lui. Reproduit sur le poste,
`pg_dump` 16.15 contre un serveur 18.6 :

```
pg_dump: error: aborting because of server version mismatch
pg_dump: detail: server version: 18.6; pg_dump version: 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
```

Même avec tous les secrets posés, la première sauvegarde de production aurait échoué. La
CI et le `docker-compose.yml` local testaient en plus le schéma sur 16, pas sur la
version de production. (Les échecs de chaque matin viennent d'ailleurs : les secrets de
l'environnement `backup` ne sont pas encore posés.)

## Décision

1. **Client PGDG figé.** `deploy/scripts/install_pg_client.sh <majeure>` installe
   `postgresql-client-<majeure>` depuis le dépôt officiel apt.postgresql.org
   (`postgresql-common`, puis `apt.postgresql.org.sh -y`), met
   `/usr/lib/postgresql/<majeure>/bin` en tête du PATH (le `pg_wrapper` de Debian pourrait
   sinon répondre avec le 16 préinstallé du runner) et échoue si `pg_dump`, `pg_restore` ou
   `psql` répond dans une autre version majeure. `backup.yml` le lance avec
   `PG_CLIENT_MAJOR: "18"`, jamais « latest », puis réaffiche `pg_dump --version` et
   échoue si la majeure diffère.
2. **Garde-fou de version dans les scripts.** `backup.sh` lit
   `server_version_num` par `psql` avant le dump : un `pg_dump` plus ancien que le serveur
   ⇒ « pg_dump N trop ancien pour un serveur M : installer postgresql-client-M » et ping
   `/fail`, rien n'est envoyé. Un `pg_dump` plus récent est accepté. Le manifeste porte
   désormais `server_version` et `pg_dump_version`. `restore_backup.sh` refuse un
   `pg_restore` d'une version majeure plus ancienne que le `pg_dump` du manifeste ; un
   manifeste sans version (sauvegarde d'avant cet ADR) donne un avertissement, pas un
   refus. La comparaison porte sur la **version majeure** : le format d'archive ne
   change qu'avec elle.
3. **CI en 18.** Le job `database` de `ci.yml` porte la majeure dans sa matrice
   (`postgres: ["18"]`), seule source du fichier : le service (`postgres:${{
   matrix.postgres }}`) et le client installé pour la suite « Sauvegarde » la reprennent.
   Une variable `env` ne convenait pas : GitHub ne l'évalue pas dans `services`. Toutes
   les suites (T1–T40, fuite inter-tenant, unitaires et intégration, migrations,
   latence, sauvegarde) tournent donc sur 18.
4. **Poste en 18.** `docker-compose.yml` passe à `postgres:18-alpine`, sur un **nouveau**
   volume `coges_pgdata18` monté sur `/var/lib/postgresql` (l'image 18 range ses données
   sous `/var/lib/postgresql/18/docker` ; un volume 16 ne démarre pas sous 18). L'ancien
   `coges_pgdata` reste en commentaire et n'est jamais supprimé par CoGes.
   `make db-upgrade-18` (`deploy/scripts/local_pg_upgrade.sh`) arrête le conteneur 16,
   relance un 16 à part sur l'ancien volume et un 18 sur le nouveau, copie tout par
   `pg_dumpall` du client **18**, compare rôles, bases et lignes de chaque table (en
   superutilisateur, sans RLS), puis `make up`. Refus si le volume 18 a déjà des
   données ; en cas d'échec, seul le volume créé par ce lancement est retiré.
5. **Un test lie les trois fichiers** (`tests/unit/test_workflows.py`) : la majeure de
   `backup.yml`, de `ci.yml` et de `docker-compose.yml` doit être la même (18), et aucun
   workflow ne peut écrire `postgresql-client-NN` ou `image: postgres:NN` en dur.

`deploy/postgres/init/01-roles.sql` passe tel quel sur 18 (joué dans un `postgres:18-alpine`
neuf : dix rôles, trois bases, aucune erreur).

## Vérifié sur PostgreSQL 18.6

- Suite backend complète (hors marqueur `perf`) sur un `postgres:18-alpine` jetable :
  **2 056 tests verts, aucun échec**, dont T1–T40 et les tests de fuite inter-tenant.
  Aucun test n'a cassé à cause de la 18 : aucun code ni aucune assertion modifiés pour
  elle. Latence du tableau de bord (marqueur `perf`) : médiane 48 ms à froid, 11 ms à
  chaud. Migrations : `downgrade -1` / `upgrade head`, puis `downgrade base` /
  `upgrade head`, sans erreur.
- `backup_chain_check.sh` avec le client 18 sur le jeu `seed-demo` : sauvegarde chiffrée,
  restaurée, `verify_restore.py` tout vert, manifeste compris (« pg_restore 18.6,
  sauvegarde de pg_dump 18.6 »).
- `make db-upgrade-18` joué sur un projet compose jetable (`COMPOSE_PROJECT_NAME`), depuis
  un volume 16 amorcé par `01-roles.sql` : rôles, `BYPASSRLS`, RLS `FORCE`, propriétaires
  et lignes identiques ; second lancement refusé.

## Conséquences

- **Monter de version majeure plus tard** = changer UNE valeur dans chaque fichier :
  `PG_CLIENT_MAJOR` de `.github/workflows/backup.yml`, `matrix.postgres` de
  `.github/workflows/ci.yml`, l'image de `docker-compose.yml` (et son nom de volume, avec
  un script de copie comme celui-ci), puis le test de concordance ; vérifier la CI avant
  de fusionner. Le guide `docs/runbooks/sauvegarde.md` cite aussi la version du client.
- Restaurer exige un client au moins de la version de `pg_dump_version` du manifeste ;
  le guide donne l'installation PGDG (Ubuntu/Debian) et `brew install postgresql@18`.
- Poste existant : après ce lot, lancer `make db-upgrade-18`, ou repartir de zéro
  (`make up && make migrate && make seed-demo`). L'ancien volume se supprime à la main.
- Les ADR antérieurs qui citent PostgreSQL 16 (0001, 0003, 0005, 0018, 0084) restent
  tels quels : ils disent ce qui était vrai et vérifié à leur date. Les extraits de
  `docs/architecture/` (« SQL PostgreSQL 16 complet ») ne sont pas modifiés (CLAUDE.md
  § 10) ; le schéma y est le même sous 18.
- La préproduction Neon `CoGes-preprod` reste en 16 (`deploy/README-infra.md`) : un
  client 18 la sauvegarde et la restaure sans difficulté.
