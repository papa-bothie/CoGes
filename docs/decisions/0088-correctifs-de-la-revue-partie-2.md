# 0088 — Correctifs de la revue de code, partie 2

- **Date** : 2026-10-18
- **Phase** : prompt 21, partie 2 (après la fusion de la partie 1, ADR 0087)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion) pour P2.4 (a) et (c), P2.9, P2.10,
  P2.13, et la mémoire de 45 min du freinage ; le reste suit le prompt.

## Contexte

La seconde partie de la revue rassemblait des constats rapportés sans avoir tous été
recoupés. Même règle qu'en partie 1 : chaque point est **d'abord reproduit par un test**
(sortie rouge gardée), puis corrigé ; un point non reproduit ne change rien. Révision
Alembic : **0025** (P2.1, P2.11, P2.13).

## Tableau des points

| # | Point | Reproduit | Résultat |
|---|---|---|---|
| P2.1 | Sessions après changement d'accès | oui (même un compte **supprimé** rafraîchissait) | corrigé |
| P2.2 | Échec Redis mémorisé à vie | oui | corrigé |
| P2.3 | Délégation de droits | oui | corrigé |
| P2.4 | Freinage de connexion (a) à (d) | oui, les quatre | corrigé |
| P2.5 | `X-Forwarded-For` vide, IPv6 | oui | corrigé |
| P2.6 | Identifiant de requête et saut de ligne | oui | corrigé |
| P2.7 | Paramètres SQL dans les journaux | oui | corrigé |
| P2.8 | Ordre des verrous, interblocage | oui (annulation, livraison, remboursement ; 500 sur 40P01) | corrigé |
| P2.9 | Dates sans fuseau, date de vente | oui | corrigé |
| P2.10 | Dépense payée modifiée ou supprimée | oui | corrigé |
| P2.11 | Produits et clients | oui, dont un retour **sans remise en stock** | corrigé |
| P2.12 | `null` sur un champ obligatoire | oui (500) | corrigé |
| P2.13 | Sous-total arrondi sur la somme | oui | corrigé (futur + brouillons) |
| P2.14 | Celery : redélivrance, alertes, arrêt | oui | corrigé |
| P2.15 | Rétention des sauvegardes | oui | corrigé |
| P2.16 | `backup.sh` | oui | corrigé |
| P2.17 | `verify_restore.py` | oui | corrigé |
| P2.18 | `check_runtime_env.py` | oui | corrigé |
| P2.19 | `deploy.sh` | oui, dont un faux échec sur une version saine | corrigé |
| P2.20 | Workflows | oui | corrigé ; réglages GitHub au propriétaire |
| P2.21 | Caddy, Redis, autoheal, `.dockerignore` | oui, sauf `.dockerignore` | corrigé ; `.dockerignore` **non reproduit** |
| P2.22 | Bombe zip `.xlsx` | oui | corrigé |
| P2.23 | Nombres ambigus, en-têtes, codage, NUL | oui | corrigé |
| P2.24 | Exports | oui | corrigé ; pré-calcul de taille **reporté** |
| P2.25 | Front (a) à (e) | (a) non ; (b) à (e) oui | corrigé ; e2e « Réessayer » **reporté** |

## Détail

### Sécurité et sessions

- **P2.1** — Un jeton de rafraîchissement continuait de servir après un nouveau mot de
  passe donné par le gérant, une désactivation, et même une suppression. Users ne peut pas
  appeler Auth (Auth dépend de Users) : trigger `users_revoke_sessions` sur `users`
  (`password_hash`, `is_active`, `deleted_at`), sur le précédent de l'ADR 0014. Le
  changement de son propre mot de passe rouvre une session neuve pour le navigateur qui
  fait le geste (`auth_service.reopen_session`, cookie reposé par `/auth/password`) : seuls
  les autres jetons tombent.
- **P2.2** — `cache.get_client` n'est plus sous `lru_cache` : un client qui répond est
  gardé, un échec seulement 5 s.
- **P2.3** — `rbac_service.assert_delegable` : un rôle ne s'attribue (création de compte,
  `POST /users/{id}/roles`) que si ses droits sont inclus dans ceux de l'appelant, sinon
  403. `users:*` et `roles:*` sont refusés (422) sur tout rôle sur mesure, à la création
  comme à la modification, plus seulement dans la grille. Le seed de démo attribue le rôle
  du vendeur avec les droits réels du gérant.
- **P2.4** (choix de l'utilisateur) :
  - **(a)** un échec compte `fenêtre + attente maximale` = **45 min**, puis s'efface.
    Proposée d'abord, la fenêtre pure de 15 min plafonnait l'attente à 8 min et laissait
    ~36 essais par heure ; avec 45 min, le palier de 30 min reste atteignable et l'essai-
    erreur tombe à ~11 par heure. **Limite assumée** : environ huit échecs par 45 min
    suffisent encore à gêner une personne en continu (on freine, on ne verrouille pas,
    ADR 0078) ; ils déclenchent l'alerte du gérant au dixième ;
  - **(b)** l'essai est réservé **avant** Argon2 (ZSET des essais en cours, Lua atomique)
    et rendu en cas de succès : une rafale parallèle de 20 essais en fait vérifier 5 au
    plus ;
  - **(c)** quand l'identifiant tapé désigne un compte, le compteur suit le compte
    (`user:<id>`), sinon le texte tapé ; même forme de clé, même réponse ;
  - **(d)** en mode dégradé, deux réservoirs séparés (comptes réels, identifiants
    inconnus) : un flot d'identifiants fantaisistes n'évince plus la victime ; Redis
    revenu, les échecs gardés en mémoire y sont reportés.
  - Clés Redis : `rl:acct:<sha256>` (échecs), `:p` (essais en cours), `:u` (fin
    d'attente), inventoriées dans `test_redis_keys_isolation.py`.
- **P2.5** — Dernier segment de `X-Forwarded-For` vide ou invalide : le pair TCP.
  Compteurs par IP et de connexion regroupés par **/64** en IPv6.
- **P2.6** — `fullmatch` sur l'identifiant de requête.
- **P2.7** — `hide_parameters=True` sur les deux moteurs ; `scrub_text` (e-mail, hachage
  Argon2, détail « Key (…)=(…) » de PostgreSQL) appliqué au formateur JSON et aux
  messages et exceptions envoyés à Sentry.

### Argent, stock, dates

- **P2.8** — La confirmation verrouille le stock par `product_id` ; l'annulation d'une
  vente le faisait dans l'ordre aléatoire des identifiants de mouvement, la livraison dans
  l'ordre de saisie (réponse rendue dans l'ordre de saisie). Le remboursement verrouille la
  dette de la vente **avant** le retour, l'ordre où l'annulation d'un paiement les atteint
  (`refund_rollup`) ; `get_for_update` du retour relit l'objet (`populate_existing`).
  `cancel_payment` suivait déjà l'ordre paiements puis dettes (ADR 0039). 40P01 et
  40001 répondent **409 `concurrent_update`** (« Réessayez », rien n'est écrit). Preuve
  par l'ordre réellement pris (espion) et par la traduction ; le test d'un interblocage
  réel croisé n'est pas joué, sa fenêtre étant non déterministe.
- **P2.9** (choix : recaler si non saisie) — `paid_at`, `returned_at`, `sold_at` sans
  fuseau : 422 (`ZonedDatetime`, `app/core/clock.py`) au lieu d'un `TypeError`. À la
  confirmation, `sold_at` prend l'heure de confirmation quand `sold_at = created_at`
  (date jamais saisie) ; une date saisie sur le brouillon est gardée.
- **P2.10** (choix : refuser) — montant changé ou suppression d'une dépense réglée par un
  paiement vivant : 409 `expense_paid`. On annule d'abord le paiement (ADR 0038).
- **P2.11** — Triggers de la révision 0025 (le Référentiel ne lit ni stock ni dettes) :
  `CG003` `is_stock_tracked` figé dès un mouvement (409 `stock_tracking_locked`), `CG004`
  article avec stock non supprimable (409 `product_has_stock`), `CG005` client avec dette
  ouverte non supprimable (409 `customer_has_open_debts`). Un retour sur un article
  supprimé depuis la vente était **accepté sans remise en stock** : `get_summaries(…,
  include_deleted=True)` pour le retour.
- **P2.12** — `null` explicite sur un champ NOT NULL d'une mise à jour (clients,
  fournisseurs, catégories, produits) : 422 (`reject_explicit_nulls`).
- **P2.13** (choix : futur + brouillons) — `sale_recompute_totals` somme des lignes
  arrondies ; brouillons recalculés ; ventes confirmées intactes, leur nombre d'écarts
  écrit en NOTICE par la migration. **0 écart** sur les données locales (quantités
  entières).

### Processus de fond et infrastructure

- **P2.14** — `CogesTask` compte les livraisons interrompues (`coges:celery:deliveries:
  <tâche>`, 24 h) et écarte une tâche après 3, avec un message Sentry ; les alertes
  (stock, annulation, échecs de connexion) retentent 3 fois ; `stop_grace_period: 120s`
  pour worker, beat et relais dans les deux compose.
- **P2.15** — Seuls les `.dump.age` décident ; premier jour sauvegardé de chaque semaine et
  de chaque mois ; plancher des 7 plus récentes ; compagnons (`.sha256`,
  `.manifest.json`, `.suspect`) supprimés avec leur dump, orphelins jamais touchés.
- **P2.16** — Référence = dernière sauvegarde **validée** (un dump trop petit porte un
  `.suspect`) ; premier lancement sur un distant vide accepté ; `BACKUP_MIN_RATIO` validé
  comme nombre et passé en argument.
- **P2.17** — `backup.sh` compte les tables clés **avant** le dump (`<dump>.manifest.json`) ;
  ces tables ne perdent jamais de ligne (suppression logique), donc la restauration doit en
  avoir au moins autant. `restore_backup.sh` exige le manifeste (`RESTORE_WITHOUT_MANIFEST=1`
  pour une ancienne sauvegarde). Contrôle du stock dans les deux sens (`FULL JOIN`).
- **P2.18** — Utilisateurs de DSN décodés (`urlsplit`, `unquote`, `?user=`) et liste
  blanche par variable sur le VPS ; `--stack` vérifie `COGES_STACK`.
- **P2.19** — `COGES_STACK` exporté et vérifié ; retour arrière aussi quand `pull` ou
  `up -d` échoue ; réponses lues dans une variable (`curl | grep -q` sous `pipefail`
  faisait échouer une version saine, reproduit) ; images autres que la version courante
  et la précédente de chaque pile supprimées après un succès.
- **P2.20** — `ci.yml` en `contents: read` ; actions tierces figées par condensat ;
  `migrate`, `deploy`, `backup`, `purge` limités à `main` et aux étiquettes `v*`.
  Protections d'environnement à régler par le propriétaire : `deploy/README-infra.md`.
- **P2.21** — Caddy ne journalise plus la chaîne de requête ; `maxmemory` de Redis par
  défaut à 384 Mo sous 640 Mo (marge pour la copie sur écriture de la réécriture AOF ;
  l'ADR 0083 disait 512) ; autoheal figé par condensat. Le `.dockerignore` du front
  écartait déjà `.env*` : **non reproduit**.

### Import, export, front

- **P2.22** — Table des matières du zip lue avant `load_workbook` : plus de 30 Mo
  décompressés ou un rapport supérieur à 100 refusés ; 100 colonnes et 2 000 caractères
  par cellule au plus (CSV et `.xlsx`).
- **P2.23** — « 1.500 » ou « 1,500 » : ligne rejetée (`ambiguous_number`, « Écrivez
  1500 ») ; colonne en double : fichier refusé ; ni UTF-8 ni Windows-1252 : signalé ;
  caractères de contrôle et NUL retirés de `?search=` (500 sur les trois listes).
- **P2.24** — Au plus 3 exports de ventes en attente par entreprise (409
  `too_many_pending_exports`) ; `Idempotency-Key` exigée sur `POST /exports/sales`, le
  rejeu rend le même export (l'écran l'envoie). Les catégories n'ont pas de code : le
  parent (et la catégorie d'un produit) s'exporte par son **chemin** « Boissons > Lait »,
  que l'import résout. **Reporté** : vérifier la taille avant de construire le fichier ;
  le plafond borne déjà la mémoire du worker, et le contrôle des 10 Mo après coup reste.
- **P2.25** — **(a)** `retry` est bien la prop de Next 16.3.8 (stable depuis 16.3.0) :
  non reproduit. L'e2e qui clique « Réessayer » est **reporté** : aucune route de
  production ne fait tomber la frontière d'erreur sans ajouter une route de crash dédiée
  aux tests ; le clic est couvert par le test du composant. **(b)** la référence ne vient
  que de `ApiError.requestId`, un digest Next s'affiche tel quel. **(c)** montant tapé :
  chiffres seuls. **(d)** dettes sans solde ignorées. **(e)** la déconnexion attend un
  rafraîchissement en cours, le verrou des onglets abandonne après 10 s, un 401 tardif
  porteur d'un jeton déjà tourné est rejoué sans seconde rotation.

## Conséquences

- Codes d'erreur nouveaux : `concurrent_update`, `expense_paid`, `stock_tracking_locked`,
  `product_has_stock`, `customer_has_open_debts`, `ambiguous_number`,
  `too_many_pending_exports` ; SQLSTATE `CG003` à `CG005`.
- `POST /exports/sales` exige `Idempotency-Key` (contrat et types régénérés).
- Le premier déploiement doit pouvoir lire les versions du registre (P1.2) et trouvera des
  actions figées : leur mise à jour se fait par condensat (`deploy/README-infra.md`).
- Le propriétaire règle les protections d'environnement GitHub (production : relecteur
  obligatoire).
