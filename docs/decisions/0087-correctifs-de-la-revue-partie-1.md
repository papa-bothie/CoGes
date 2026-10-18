# 0087 — Correctifs de la revue de code, partie 1

- **Date** : 2026-10-18
- **Phase** : prompt 21, partie 1 (avant l'ouverture de la production)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion) pour P1.2, P1.3, P1.6, P1.7 et P1.8 ;
  le reste suit le prompt. **À relire avant la fusion** : P1.3 (paiements), P1.4 (verrous)
  et P1.8 (coût moyen), qui touchent à l'argent.

## Contexte

Une relecture en lecture seule (2026-10-18) a relevé huit défauts sans rien exécuter. La
règle de la partie : chaque constat est d'abord **reproduit par un test qui échoue**,
puis corrigé ; un constat non reproduit ne change rien. **Les huit ont été reproduits.**
Révision Alembic : **0024** (P1.1, P1.6, P1.8).

## Les huit points

| # | Constat | Reproduit | Correctif |
|---|---|---|---|
| P1.1 | Panne de Redis ⇒ événements sains au rebut | oui | tentative rendue sur panne de transport |
| P1.2 | Le nettoyage du registre peut supprimer l'image de production | oui (par le scénario) | étiquettes protégées, décision testée |
| P1.3 | `POST /payments` accepte `sale_id` sans contrôle | oui | `sale_id` retiré |
| P1.4 | Lignes d'un brouillon écrites sans verrou | oui | verrou de la vente, comme `confirm_sale` |
| P1.5 | Secret JWT par défaut accepté hors développement | oui | refusé au démarrage |
| P1.6 | Recréer un compte supprimé ⇒ 500 | oui | index uniques partiels, course ⇒ 422 |
| P1.7 | Alertes et chiffres d'argent mélangés dans le cache | oui | cache commun, champs de la personne à part |
| P1.8 | Annuler un achat ne rend pas le CMP | oui | retrait au coût d'entrée, refus si suivie |

### P1.1 — Outbox et panne de Redis

- **Reproduit** (`tests/integration/test_outbox_redis_outage.py`) : douze passages avec un
  bus en panne, l'événement est au rebut dès le dixième ; un passage essaie chaque
  événement du lot alors que Redis est tombé ; le vrai `CeleryEventBus` laisse remonter
  l'`OperationalError` de kombu, comptée comme un échec de l'événement.
- **Cause** : `outbox_claim` consomme une tentative à chaque réclamation, et le relais ne
  distinguait pas une panne de transport d'un événement empoisonné.
- **Correctif** : `TransportUnavailableError` (`app/core/events/bus.py`), levée par
  `CeleryEventBus` sur les erreurs de broker (kombu, redis-py, connexion, délai). Le
  relais arrête alors son passage et rend la tentative à tout ce qui n'est pas parti, par
  `outbox_release(bigint[])`, fonction de `coges_bus` exécutable par le seul `coges_relay`
  (T36 mis à jour). Le plafond de 10 ne vaut plus que pour un échec propre à l'événement
  (test : un événement empoisonné atteint toujours le rebut).
- `/system/workers` signale `outbox_dead_lettered:<nombre>` (503) ; `make ops-status`
  marque l'outbox KO ; `docs/runbooks/workers.md` dit comment lister et rejouer le rebut.
  Les tests qui fabriquent un rebut le referment (`bury_dead_letters`).

### P1.2 — Images de production

- **Reproduit par le scénario** : l'ancien nettoyage était une configuration
  (`min-versions-to-keep: 5`, tous environnements confondus), pas du code exécutable en
  test. Le scénario du prompt (cinq préproductions récentes, une production plus
  ancienne) supprimait la production. Le checkout du job `images` partait de la branche
  du déclenchement, et rien ne refusait une étiquette existante.
- **Choix de l'utilisateur** : quota gratuit, **2 versions gardées** (pas GitHub Pro,
  pas d'autre registre, pas d'images publiques).
- **Correctif** (`deploy/scripts/registry_cleanup.py`, testé par
  `tests/unit/test_registry_cleanup.py`) :
  - après la fumée de **production**, le job `deploy` déplace `production-previous` ←
    `production` puis `production` ← la version (`imagetools create`, même condensat) ;
  - `plan` ne supprime jamais `production` ni `production-previous`, ni une version sans
    étiquette ; il garde la plus récente des autres (la préproduction en cours) et purge
    le reste. Images construites sans attestation de provenance (`provenance: false`) :
    plus de manifestes enfants sans étiquette ;
  - une `vX.Y.Z` doit exister en étiquette git ; le job se place sur son commit et
    étiquette l'image avec **ce** SHA (plus `github.sha`) ;
  - `decide` : version absente ⇒ construite ; présente avec le condensat de l'image du
    même commit ⇒ **réutilisée sans reconstruction** ; présente sous une autre image ⇒
    **refusée**. Écart au prompt, qui demandait de refuser toute version présente : cela
    aurait rendu impossible le passage préproduction → production d'une même version, le
    flux de l'ADR 0083. La réutilisation déploie exactement ce qui a été essayé.
- Documenté dans `deploy/README-infra.md` (« Registre d'images ») : les fichiers
  `/opt/coges/state/<pile>.version` et `.previous` du VPS désignent les mêmes versions.
- **Non vérifié en vrai** : le workflow ne s'exécute pas sur le poste. La liste des
  versions passe par `gh api /users/<propriétaire>/packages/container/…/versions` avec le
  `GITHUB_TOKEN` (`packages: write`) ; à confirmer au premier déploiement.

### P1.3 — Paiement rattaché à une vente

- **Reproduit** (`test_payment_without_sale_context.py`) : 201 pour un encaissement direct
  d'une vente à crédit (dette restée ouverte), pour un montant au-delà du total, pour un
  brouillon ; 404 pour une vente inconnue.
- **Choix de l'utilisateur** : retirer `sale_id` de `PaymentCreate`. Vérifié avant : ni le
  front ni aucun test ne l'envoyait. Le champ envoyé est refusé en 422 (`extra="forbid"`).
  L'encaissement de la confirmation garde son chemin (`record_sale_payment`).
- `openapi.json` et `frontend/types/api.ts` régénérés ; le registre d'écritures critiques
  n'avait rien à changer (même route, même classement).

### P1.4 — Lignes d'un brouillon sans verrou

- **Reproduit** (`test_draft_lines_lock.py`, fenêtre provoquée comme T20/T38 : une
  connexion tient la vente, la confirmation s'y bloque, puis l'écriture) : la ligne
  ajoutée passe sur la vente confirmée, sans sortie de stock, et le total ne correspond
  plus à la dette ; la modification d'une ligne finit en **interblocage** ; le
  changement de client passe sur une vente confirmée.
- **Cause** : `add_item`, `update_item`, `remove_item` et `update_sale` lisaient la vente
  sans `FOR UPDATE` ; `sale_items_no_change` voyait encore `draft`.
- **Correctif** : `_locked_draft` (même premier verrou que `confirm_sale`) dans les quatre.
  L'écriture attend la confirmation, relit `confirmed` et reçoit `sale_not_draft`. Aucune
  autre écriture sur les lignes ou l'en-tête n'avait le défaut (pas de remise globale en
  V1 ; retours et annulation verrouillaient déjà).
- Invariant ajouté (`tests/helpers/invariants.py`) : « vente confirmée : une sortie par
  ligne suivie ». Vérifié : sans le correctif, il signale la vente du test.

### P1.5 — Secret JWT par défaut

- **Reproduit** (`tests/unit/test_config_development_defaults.py`) : `staging` et
  `production` démarraient avec le secret public du dépôt, et avec celui des modèles
  (`CHANGE-ME-…`).
- **Correctif** : validateur de modèle, tout secret commençant par `change-me` (sans
  distinction de casse) est refusé hors `local` et `ci`. Le job `migrate` de
  `deploy.yml`, qui lance Alembic en `staging`/`production`, tire un secret jetable
  (`openssl rand`) : Alembic ne s'en sert pas, mais la configuration l'exige désormais.
- **Autres défauts de développement de `config.py`, examinés et laissés** :
  `trust_proxy_headers = False` (sûr ; c'est sur le VPS qu'il vaut `True`, ADR 0083, et
  rien ne permet de détecter un proxy absent) ; `redis_url` sur localhost (l'absence de
  Redis est un mode prévu, `not_configured` de l'ADR 0081, et le VPS le fixe) ;
  `cors_origins` vide, `ops_token` et `sentry_dsn` absents (défauts fermés) ; DSN absents
  (échec explicite à l'usage).

### P1.6 — Compte recréé avec un identifiant repris

- **Reproduit** (`test_reused_user_identifiers.py`) : 500 en recréant un compte avec
  l'e-mail, puis le téléphone, d'un compte supprimé ; `IntegrityError` brute pour deux
  créations simultanées.
- **Choix de l'utilisateur** : index uniques **partiels** (`WHERE deleted_at IS NULL`),
  noms gardés. `_flush` du service traduit leur violation en 422 (même message que la
  vérification) : une course ne donne plus jamais 500.
- `auth_lookup` filtrait déjà `deleted_at IS NULL` ; un test le verrouille (l'ancien mot
  de passe est refusé, le nouveau compte est celui qui se connecte).
- **Retour arrière** : les contraintes pleines reviennent ; un compte **supprimé** dont
  l'identifiant est repris perd d'abord le sien (téléphone effacé, e-mail réécrit en
  `supprime-<id>@compte.invalid`), sur le précédent de la révision 0019. Sans cela, le
  downgrade échouait — constaté sur la base de test, recréée par downgrade à chaque
  session.

### P1.7 — Tableau de bord en cache

- **Reproduit** (`test_dashboard_per_viewer.py`, sans invalidation entre deux lectures) :
  le vendeur reçoit les alertes du gérant depuis le cache ; une alerte lue reste affichée ;
  le JSON du vendeur porte marge, caisse et créances.
- **Choix de l'utilisateur** : filtrer côté serveur. Le cache (par entreprise, clé
  inchangée) ne garde que ce qui est commun ; à chaque requête, `_for_viewer` pose les
  alertes de la personne et met à `null` ce que ses droits ne lui ouvrent pas :
  `estimated_margin_month` et `cash_on_hand` sans `analytics:read` (ADR 0030 ; le droit de
  `/analytics/cash`), `receivables_open`, `receivables_customer_count` et `watch_debt`
  sans `debts:read` (ADR 0072). Le vendeur et le comptable gardent `dashboard:read` ; le
  comptable voit tout, le vendeur ventes, stock et ses alertes.
- Front : tuiles « Dans la caisse » et « On vous doit » masquées aussi quand la valeur est
  nulle (un rôle sur mesure peut avoir l'onglet Argent sans `analytics:read`).

### P1.8 — CMP après l'annulation d'une entrée

- **Reproduit** (`test_entry_reversal_cmp.py`, SQL direct) : 10 à 50 + 10 à 100 → 75 ;
  achat annulé → 10 à **75** ; annulations acceptées après une vente ou un second achat.
- **Cause** : l'inverse d'une entrée est une sortie, et `cmp_next_avg` laisse la moyenne
  inchangée sur une sortie ; `rebuild_product_stock` rejouait la même formule.
- **Choix de l'utilisateur** : refuser si l'entrée a été suivie. Révision 0024 :
  - `cmp_next_avg(…, p_reversal boolean)` : l'inverse d'une entrée la retire à son coût,
    (Q·A − q·c)/(Q − q), soit le CMP d'avant ; stock ramené à zéro ⇒ CMP gardé (T11) ;
    jamais négatif. La forme à quatre arguments reste inchangée ;
  - `inv_apply_movement` et `rebuild_product_stock` appellent tous deux la nouvelle forme
    (T12 : une seule formule) ;
  - sous le verrou de `product_stock`, le trigger refuse (`CG022`) l'inverse d'une entrée
    qu'un autre mouvement du même produit a suivie (enregistré ou daté après elle).
    Traduit en 409 `entry_reversal_superseded` : « D'autres mouvements ont suivi cette
    entrée : elle ne peut plus être annulée. Faites plutôt une correction de stock. »
  - Rendre une perte ou une correction négative reste libre (son inverse est une entrée).
  - **Limite** : seule la **dernière** entrée d'un produit est annulable, car l'annulation
    d'une entrée est elle-même un mouvement qui suit les précédentes. Achat A, achat B,
    annulation de B : l'annulation de A est ensuite refusée.
- Invariant ajouté : « valeur du stock = quantité × CMP » (structurel, `stock_value` est
  générée) et CMP jamais négatif ; les tests vérifient aussi que le recalcul de nuit ne
  diverge pas du trigger.

## Conséquences

- **Premier recalcul de nuit après le déploiement** : les articles dont une entrée avait
  déjà été annulée voient leur CMP corrigé, et l'écart est signalé. C'est attendu.
- `GET /dashboard` : cinq champs deviennent nullables (contrat régénéré).
- `POST /payments` : `sale_id` n'existe plus ; un client qui l'enverrait reçoit 422.
- Le propriétaire doit encore régler les protections d'environnement GitHub (partie 2,
  P2.20) ; le quota de paquets reste le gratuit.
