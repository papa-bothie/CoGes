# 0127 — Sauvegarde et restauration sur site (lot 4)

- **Date** : 2026-11-20
- **Phase** : sur site, lot 4 (`docs/prompt-sur-site/04-sauvegarde-restauration.md`)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, puis trois changements au plan)

## Contexte

Une installation sur site (ADR 0124 à 0126) n'avait aucune sauvegarde : un disque qui lâche,
un PC volé ou un `down -v` de trop, et la boutique perdait tout. Le lot ajoute une
sauvegarde automatique, une copie hors du PC, une preuve régulière de relecture et une
restauration qui ne détruit rien. Règles du lot : ajouter seulement, aucune nouvelle image,
aucun changement de l'application, la sauvegarde de la production (ADR 0084) intacte.

## Décisions de l'utilisateur

1. **Chiffrement par clé publique**, comme la production : le PC n'a que la clé publique (il
   chiffre, il ne relit pas) ; la clé privée reste chez CoGes. Une clé USB volée ne livre
   rien ; seul CoGes restaure ; **clé privée perdue = sauvegardes illisibles**.
2. **Une paire par client.** De préférence tirée chez le technicien
   (`coffre.py paire`, image `worker`, réseau coupé) et posée par `-ClePublique <fichier>`.
   Sans `-ClePublique`, le script la tire sur place et écrit la clé privée **dans un fichier
   sur le disque amovible** `-LecteurCle E:` — jamais à l'écran, dans le journal ni dans le
   presse-papiers — puis demande `COPIE-FAITE` (changement 1 au plan).
3. **Rythme** : 13 h 00 et 20 h 30, plus au démarrage si la dernière bonne a plus de 20 h.
4. **Rétention sur le PC** : 14 dernières + 1 par semaine sur 8 semaines + 1 par mois sur 12
   mois ; sur le disque de copie : 10 dernières.
5. **Clé privée à la restauration** par l'**entrée standard** du conteneur, jamais par une
   variable d'environnement (visible par `docker inspect`) ni un argument (changement 2).
6. **Verrou commun** `C:\CoGes\coges.verrou` pour Sauvegarder, Restaurer, l'essai du
   dimanche, la tâche « CoGes - démarrage » et Reparer ; volume de travail vidé dans un
   `finally` (changement 3).

## Format du fichier « COGES-SAUV-1 » (`deploy/onprem/sauvegarde/coffre.py`)

```
en-tête = "COGES-SAUV-1\0" (13 o) · clé publique éphémère X25519 (32 o) · sel (16 o)
          · taille d'un bloc en clair (4 o, gros-boutiste ; 1 Mio)
clé     = HKDF-SHA256(X25519(éphémère, destinataire), sel,
                      info = "coges-sauvegarde-v1" · éphémère · destinataire) → 32 o
blocs   = AES-256-GCM(clé, nonce = n° du bloc (11 o) · drapeau de fin (1 o), bloc, AAD = en-tête)
```

Le drapeau vaut 1 sur le dernier bloc seulement (vide si la taille tombe juste) : un octet
changé, un bloc retiré, réordonné ou ajouté, un fichier coupé, même pile sur une frontière de
bloc, sont refusés. Mémoire bornée (un bloc). Clés en texte d'une ligne :
`COGES-CLE-PRIVEE-1:<base64url 32 o>` et `COGES-CLE-PUBLIQUE-1:<…>`. Windows PowerShell 5.1
n'ayant pas X25519, `Get-CogesX25519Public` calcule la clé publique en `BigInteger`
(RFC 7748, vecteurs du § 6.1 vérifiés par Pester et par pytest).

Le fichier chiffré est **relu dans le conteneur** juste après l'écriture : il est déchiffré
avec la clé de contenu encore en mémoire et son sha256 en clair comparé à celui du dump. Le
PC ne peut pas relire avec la clé privée, mais il prouve que le fichier redonne exactement
le dump qui vient d'être contrôlé par `pg_restore --list`.

À côté : `.sha256` (format de `sha256sum`) et `.manifest.json` : `coges_version`,
`alembic_revision`, `server_version`, `pg_dump_version`, boutiques, `base_octets`,
`base_id` (identifiant du serveur + oid de la base), lignes des tables clés comptées
**avant** le dump (`verify_restore.manifest_query()`), taille, sha256 du fichier et du dump.

## Montage, sans nouvelle image

- Deux services ponctuels ajoutés au compose (profil `tools`) : `sauvegarde-pg`
  (`postgres:18.7-alpine` : `pg_dump`, `pg_restore`) et `sauvegarde-py` (`worker` : Python,
  `cryptography`, `psycopg`). Tous deux en `network_mode: service:postgres` : ils partagent le
  réseau du conteneur de la base (donc le réseau interne, sans sortie, sans port) et s'y
  connectent en **superutilisateur sur 127.0.0.1, en confiance locale** (pg_hba de l'image
  officielle, vérifié). **Aucun mot de passe** ne leur est donné. Le superutilisateur est le
  seul rôle du poste qui lit sans filtre de RLS (`coges_backup` existe mais sans mot de
  passe, donc sans connexion).
- `check_onprem_env.py --rendered` gagne trois règles (testées) : le mot de passe du
  superutilisateur ne sort pas du service `postgres` ; seuls les services de sauvegarde
  partagent le réseau d'un autre conteneur, et seulement celui de `postgres` ; ils sont en
  profil `tools` et ne reçoivent aucun mot de passe ni DSN.
- Le dump en clair ne vit que dans le volume `sauvegarde-travail`, vidé à la fin (même
  après un échec). Le dossier `C:\CoGes\sauvegardes` est monté par `run -v` ; la copie
  vers la clé USB se fait par PowerShell, fichier à fichier (aucun montage d'un disque
  amovible, aucun tube binaire à travers PowerShell 5.1).
- **Vérification d'une base restaurée** : `deploy/onprem/sauvegarde/verify_restore.py` est
  une **copie à l'octet près** de `deploy/scripts/verify_restore.py` (test
  `test_the_restore_checks_are_a_faithful_copy_of_the_production_ones`) ; `base.py` lui
  donne une connexion `psycopg` à la place de `psql` (absent de l'image `worker`) et ajoute
  les contrôles du sur site : aucun secret chiffré par `COGES_MFA_ENCRYPTION_KEY`, rôles de
  `postgres-init` présents, mêmes propriétaires et droits que la base en place.

## Ce qui n'est pas sauvegardé, et pourquoi

- **Redis** : file et cache ; l'outbox est en base.
- `caddy-*`, `front-static`, `beat-state` : recréés au démarrage.
- **`ml-artifacts`** : les modèles sont réentraînés **chaque semaine** (beat, lundi 3 h 45,
  rattrapé au démarrage) ; les prévisions et conseils déjà calculés sont dans la base. Après
  une restauration, les prévisions restent celles de la sauvegarde jusqu'au réentraînement.
- **`coges.env`** : reste dans le gestionnaire de mots de passe de CoGes. Une base restaurée
  fonctionne avec un `coges.env` **neuf** (prouvé par `verifier.sh`, qui change tous les
  mots de passe et clés avant de restaurer) : `pg_dump` ne contient pas les rôles, recréés
  par `01-roles.sql` avec les nouveaux mots de passe ; un `COGES_JWT_SECRET` neuf oblige
  seulement à se reconnecter ; `COGES_MFA_ENCRYPTION_KEY` ne chiffre que
  `platform_users.mfa_secret` (`core/mfa.py`), vide sur site (l'administration n'y existe
  pas) — contrôle « aucun secret chiffré » à chaque vérification.

## Restaurer

Huit étapes (`Restore-CogesBackup`), chacune arrêtée au premier problème sans rien changer :
empreinte et manifeste puis `RESTAURER` ; révision connue du programme installé (sinon
« installez d'abord la version vX.Y.Z ») ; sauvegarde de la base actuelle si elle a une
société ; déchiffrement dans le conteneur, restauration dans `coges_restauration`,
contrôles ; arrêt de `front`, `api`, `worker`, `beat`, `relay` (Caddy montre la page de
maintenance), bascule par renommage (`coges` → `coges_avant_AAAAMMJJ_HHMM`) ; `migrate` si
besoin, démarrage, licence relue, page d'accueil ; en cas d'échec, **retour automatique**
(`coges` → `coges_echec_…`, `coges_avant_…` → `coges`). L'ancienne base n'est supprimée que
par `-Action NettoyerAncienneBase`. La licence revient avec la base (abonnement en base,
ADR 0125). Un essai d'échec après la bascule se déclenche par
`COGES_ESSAI_ECHEC_APRES_BASCULE=1` (CI seulement).

## Restauration d'essai (bloc D)

Faite au moment d'une sauvegarde (le dimanche, ou au premier passage après), sur le **dump
même** qui vient d'être chiffré et relu : `coges_verif` préparée, `pg_restore`, contrôles de
la production + du sur site, puis supprimée. Le PC ne pouvant pas déchiffrer, c'est la seule
relecture possible sans la clé privée ; jointe à la relecture du fichier chiffré, elle prouve
que la sauvegarde se restaure. Résultat dans `C:\CoGes\sauvegardes\etat.json` (avec la
dernière copie hors du PC et la dernière erreur) — seul fichier d'état du sur site, ce que
les fichiers ne disent pas.

## Mesures (verifier.sh, poste Linux, 20/11/2026)

- Base de l'essai : 2 sociétés, 1 vente ; fichier chiffré de 0,4 Mo (dump de 13 Mo de base).
- `-Action Sauvegarder -Essai` (manifeste, dump, chiffrement relu, restauration d'essai,
  copie sur le « disque » préparé) : **28 s**, CoGes en marche.
- `-Action Restaurer` après `down -v` et réglages neufs (sauvegarde de la base en place,
  déchiffrement, restauration à côté, contrôles, bascule, redémarrage, licence) : **72 s**.
- Mémoire au plus haut pendant la sauvegarde et l'essai (`docker stats`, chaque seconde) :
  postgres 53 Mio, worker 226 Mio, beat 201 Mio, api et relay 112 Mio ; aucun service ne
  s'en approche de son plafond. Les deux outils ponctuels (`sauvegarde-pg`,
  `sauvegarde-py`) vivent quelques secondes chacun, sous un plafond de 256 Mio ; le
  chiffrement garde un bloc de 1 Mio en mémoire (pytest : moins de 8 Mio pour 48 Mo).
- Le scénario complet du workflow « Sur site » reste sous sa limite de 30 minutes (environ
  2 min de plus que le lot 3).

## Corrections après le test Windows (21/11/2026, lot 5, bloc 0)

Trois constats des vérifications sur le PC Windows 11, corrigés avant le lot 5 :

- **Mauvaise sauvegarde restaurée.** Après `Desinstaller -EffacerLesDonnees` puis
  `Installer`, la plus récente de la clé était celle de la base neuve et vide, restaurée
  « avec succès » sans donnée. Désormais : les sauvegardes faites avant une action portent
  sa raison à la fin du nom (`-avant-effacement`, `-avant-restauration`, `-avant-maj`,
  `-avant-retour`, `-installation`), traitées comme les autres par la rétention et la copie ;
  `Restaurer` sans `-Fichier` liste celles du PC et de la clé CoGes (date, version, ventes,
  sociétés, origine, raison) et fait choisir par numéro ; une sauvegarde sans vente, ou avec
  moins de ventes que la base actuelle (`base.py etat` compte les ventes), exige
  `RESTAURER-QUAND-MEME` en disant combien seraient perdues (`-RestaurerQuandMeme` en
  `-NonInteractif`).
- **« échec (code 1) » quand Docker Desktop est arrêté.** `Assert-CogesDockerRunning`
  (`Get-CogesDockerEngineProblem`) en tête de `Sauvegarder`, `Restaurer`, `PreparerDisque`,
  `NettoyerAncienneBase` et `Desinstaller` : « Docker Desktop ne tourne pas : ouvrez-le et
  attendez « Engine running », puis relancez. Rien n'a changé. » `Etat` le dit sans
  s'arrêter. `Installer` et `Reparer` gardent leur contrôle des prérequis.
- **Docker Desktop qui ne démarre plus.** Marche à suivre au dépannage du guide, avec
  l'interdiction de « Clean / Purge data » et « Reset to factory defaults » ; `Etat` affiche
  en rouge moins de 5 Go libres.

## Limites

- Pas d'exécution réelle sur Windows en CI (les runners n'exécutent pas les conteneurs
  Linux) : la tâche planifiée, les notifications WinRT, une vraie clé USB, `DriveInfo` des
  disques amovibles et `Restaurer` depuis Windows PowerShell 5.1 sont à vérifier sur le PC
  (liste du README des lots).
- La comparaison de taille à 50 % ne vaut qu'entre sauvegardes de la **même** base
  (`base_id`) : après une installation neuve ou une restauration, elle repart de zéro.
- La place libre se mesure sur le disque de `C:\CoGes` ; celle du disque virtuel de Docker
  Desktop (où passe le dump en clair) n'est pas mesurée : un disque plein y fait échouer la
  sauvegarde proprement (volume vidé, message, rien de compté).
- Une sauvegarde de plus de trois mois restaurée peut échouer au contrôle « partition
  d'audit du mois » de la production, comme sur le VPS.
- Les sauvegardes restent sur le PC et sa clé USB : pas d'envoi sur Internet (lot 6 au plus
  tôt, à décider).
