# Prompt 19 — Sauvegarde externe chiffrée et page d'erreur

Branche `feat/backup-and-error-page`, depuis `main` à jour, après les prompts 16, 17 et 18 (elle réutilise `/health/ready`, les alertes « homme mort » et le VPS). Points 8 et 9 de la liste « avant la production ».

Pourquoi ce lot : la base est chez Neon. Neon garde l'historique (PITR), mais une copie qui dépend du même fournisseur et du même compte ne protège ni d'une erreur de compte, ni d'un incident chez Neon, ni d'une suppression par erreur. Il faut une copie chiffrée, ailleurs, et une preuve qu'on sait la relire. Et quand quelque chose casse, le commerçant doit voir un message clair, pas une page blanche.

```
Lot sauvegarde et page d'erreur (branche feat/backup-and-error-page, depuis main à jour).
Règles habituelles : ADR aux prochains numéros libres, tests d'abord, aucun service payant
ouvert sans mon accord, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni
backend/.vercel/. Résumé en français à la fin, questions ouvertes par AskUserQuestion.
Tu n'as accès ni à Neon, ni au VPS, ni au stockage externe : tu écris le code, les
scripts et les guides ; je crée les comptes et je pose les secrets moi-même.

B1. Sauvegarde quotidienne chiffrée, hors de Neon et hors du VPS
Décision de conception à documenter dans l'ADR : la sauvegarde tourne dans un workflow
GitHub Actions planifié (.github/workflows/backup.yml, chaque nuit à 02 h 15 UTC, hors des
tâches de beat.py, plus lancement manuel workflow_dispatch), PAS sur le VPS. Ainsi elle
continue si le VPS tombe, et aucun accès « lecture de toute la base » n'est déposé sur le VPS.
- Rôle dédié `coges_backup` : lecture seule sur toutes les tables, ET capable de lire malgré
  la RLS (sinon pg_dump ne verrait aucune ligne). Écris la migration ou le script SQL
  (deploy/sql/create_backup_role.sql) et VÉRIFIE que Neon autorise ce droit (BYPASSRLS ou
  équivalent). Si Neon ne le permet pas, arrête-toi et propose-moi une alternative
  (par exemple pg_dump avec le rôle propriétaire, en secret GitHub uniquement) avant de coder.
  Garde-fou : ce rôle ne peut ni écrire, ni se connecter depuis l'API ; test dans
  tests/architecture comme pour les autres rôles.
- Le workflow : pg_dump au format custom (-Fc), version du client alignée sur la version de
  Neon (figée), sslmode=require, DSN en secret GitHub BACKUP_DATABASE_URL. Le fichier est
  chiffré avec `age` (clé PUBLIQUE en secret/variable BACKUP_AGE_RECIPIENT ; la clé privée
  reste hors de GitHub, chez moi, et n'est jamais demandée au workflow). Le dump en clair ne
  touche jamais un disque persistant ni un artefact GitHub ; supprime-le dès le chiffrement.
- Envoi vers un stockage objet compatible S3 hors Neon (Cloudflare R2, Backblaze B2 ou
  Infomaniak Swiss Backup : je choisis et je crée le compte) via rclone, clés en secrets
  GitHub à droits limités (écriture seule + liste ; pas de suppression depuis le workflow).
  Nom : coges-AAAA-MM-JJ-HHMM.dump.age + fichier .sha256.
- Rétention : 7 sauvegardes quotidiennes, 4 hebdomadaires (dimanche), 12 mensuelles (le 1er).
  Écris la purge comme un second workflow (ou une règle de cycle de vie du bucket décrite
  dans le guide), avec un compte distinct de celui qui écrit, pour qu'un workflow
  compromis ne puisse pas effacer l'historique. Ne supprime jamais les sauvegardes des
  7 derniers jours.
- Vérification immédiate : après l'envoi, relire la taille du fichier distant, comparer le
  sha256, et échouer si la taille est inférieure à 50 % de la précédente (signal de dump
  tronqué ou de base vidée).
- Alerte : ping Healthchecks.io (URL en secret BACKUP_PING_URL) au succès, /fail à l'échec,
  délai de grâce 26 h. Aucune donnée personnelle dans les journaux du workflow.

B2. Script de restauration et preuve mensuelle
- scripts/restore_backup.sh <fichier.dump.age> : déchiffre avec la clé privée fournie par
  moi à l'exécution (chemin en argument, jamais dans git), restaure dans une base VIDE
  (refuse si la base cible contient déjà des tables, refuse la production : le nom d'hôte
  ne doit pas être celui de la base de production), puis lance les vérifications de B3.
- scripts/verify_restore.py : après restauration, compte les lignes des tables clés par
  entreprise, vérifie que les migrations Alembic sont à la dernière révision, que la RLS
  est active (relrowsecurity) sur chaque table de tenant, que les séquences/partitions
  d'audit existent, et que l'équilibre comptable des paiements et du stock est cohérent
  (réutilise les contrôles d'intégrité existants s'il y en a). Sortie lisible, code 0/1.
- Test automatisé dans la CI : un dump d'une base de test (jeu `demo`) -> chiffrement age
  avec une clé de test -> restauration dans un PostgreSQL temporaire (service Docker) ->
  verify_restore.py au vert. Ça prouve que la chaîne marche à chaque changement du schéma.
- docs/runbooks/sauvegarde.md, en français simple : où sont les sauvegardes, comment en
  choisir une, restaurer pas à pas, ce que perd chaque scénario (suppression par erreur,
  Neon perdu, compte Neon bloqué), quand utiliser le PITR de Neon plutôt que cette copie,
  et comment chronométrer l'exercice (RTO/RPO à noter dans un tableau à remplir par moi).
  Explique aussi comment garder la clé privée age (gestionnaire de mots de passe + copie
  papier ou clé USB dans un autre lieu), car sans elle les sauvegardes sont inutilisables.

B3. Page d'erreur côté commerçant
- frontend/app/error.tsx et frontend/app/global-error.tsx : écran chaleureux, dans le style
  de la maquette v2 (tokens existants, aucun nouveau style), texte du type « Un souci de notre
  côté. Vos données sont en sécurité. Réessayez dans un instant. » avec les boutons
  « Réessayer » et « Retour à l'accueil », et un code court (référence d'incident) que le
  commerçant peut nous lire par téléphone. Jamais de trace technique ni de message brut.
- L'API renvoie pour toute 5xx un corps JSON stable {code: "server_error", message,
  request_id} (jamais de détail interne) ; l'identifiant de requête est aussi dans l'en-tête
  de réponse et dans Sentry. Le front l'affiche comme référence d'incident.
- Coupure réseau ou API injoignable (fetch qui échoue, 502, 503, 504) : bandeau discret
  « Connexion difficile. Nous réessayons… » avec nouvel essai automatique espacé
  (2, 4, 8 s, puis manuel) pour les lectures uniquement. Pour une ÉCRITURE, jamais de
  rejeu silencieux : ce qui a été saisi (panier de vente, formulaire de paiement) reste à
  l'écran, le bouton « Réessayer » réutilise la MÊME clé d'idempotence pour qu'un double clic
  ou un rejeu ne crée jamais deux ventes ni deux paiements.
- Caddy (prompt 18) : page statique de maintenance servie par `handle_errors` pour 502/503/504
  quand l'API ou le front est arrêté (HTML autonome, sans dépendance, même ton, avec la
  référence d'incident vide). Fichier deploy/vps/maintenance.html et test de rendu.
- Écran 404 existant (not-found.tsx) : vérifie qu'il est cohérent avec le nouveau ton.

B4. Tests
- Backend : toute exception non gérée -> 500 avec le corps stable et sans trace ; aucune
  donnée de tenant ni chemin de fichier dans le message ; l'identifiant de requête figure
  dans la réponse et dans le log.
- Front (Vitest) : error.tsx affiche la référence, le bouton réessaie ; une écriture qui
  échoue conserve le formulaire et rejoue avec la même clé d'idempotence.
- E2E (Playwright) : API coupée pendant une lecture -> bandeau puis retour à la normale ;
  API qui répond 500 sur la confirmation d'une vente -> panier conservé, rejeu = UNE seule
  vente. Accessibilité : focus placé sur le titre de l'erreur, contraste vérifié, Lighthouse
  inchangé (≥ 95) sur les écrans touchés.
- Sauvegarde : tests des scripts (restore refuse une base non vide, refuse l'hôte de
  production, refuse un fichier dont le sha256 ne correspond pas).

B5. Fin de lot
Suite backend complète, ruff, mypy, shellcheck sur les scripts, make front-check, e2e des
écrans touchés, tests de fuite inter-tenant, CI verte. Mets à jour README-infra.md
(variables, secrets GitHub à créer, tableau des sauvegardes) et CLAUDE.md. Ne lance AUCUN
envoi réel vers un stockage externe : tout est testé avec des fausses cibles.
```

## Ce que le propriétaire fait lui-même

1. Choisir et créer le stockage externe (Cloudflare R2, Backblaze B2 ou Infomaniak Swiss Backup), avec deux jeux de clés : un pour écrire, un pour purger.
2. Générer la paire de clés `age` sur son poste, garder la clé privée dans un gestionnaire de mots de passe et une copie hors ligne dans un autre lieu, ne donner à l'agent et à GitHub que la clé publique.
3. Créer le rôle `coges_backup` sur Neon avec le script fourni, puis les secrets GitHub : `BACKUP_DATABASE_URL`, `BACKUP_AGE_RECIPIENT`, clés du stockage, `BACKUP_PING_URL`.
4. Créer le contrôle Healthchecks.io (grâce de 26 h) et choisir où recevoir l'alerte.
5. Faire un premier exercice de restauration réel avec le guide et noter le temps obtenu (RTO) et l'âge de la dernière sauvegarde (RPO).
