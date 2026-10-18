# Prompt 21 — Correctifs de la revue de code (avant l'ouverture)

Branche `fix/review-findings`, depuis `main` à jour, après les prompts 16 à 20. À lancer avant d'ouvrir la production. Né d'une relecture de lecture seule du code (lots A, 17, 18, 19, 20 et les modules d'argent), faite le 2026-10-18 : rien n'a été exécuté, donc chaque constat doit être **reproduit par un test avant d'être corrigé**.

Deux parties : la partie 1 regroupe huit défauts lus dans le code, la partie 2 des constats rapportés et non recoupés. Une PR par partie, plusieurs commits.

```
Correctifs de la revue — partie 1 (branche fix/review-findings-1, depuis main à jour).
Règles habituelles : ADR au prochain numéro libre (une seule ADR pour la partie, qui liste
chaque constat, sa cause, son correctif), migration au prochain numéro libre si besoin,
aucun service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/.
Résumé en français à la fin, questions ouvertes par AskUserQuestion.

MÉTHODE (obligatoire pour chaque point)
1. Écris d'abord un test qui échoue et montre le défaut (sortie rouge dans la PR).
2. Corrige, puis montre le test au vert.
3. Si le défaut ne se reproduit PAS, ne change rien : note dans l'ADR « non reproduit » avec
   la raison (par exemple une contrainte SQL ou un garde-fou que la relecture n'avait pas vu).
4. Les choix de comportement marqués [DEMANDER] se posent par AskUserQuestion avant de coder.
5. Les registres de lot C (écritures critiques, lectures, tâches, tables sans RLS) doivent
   rester à jour ; toute route modifiée garde son entrée.

P1.1 Événements de l'outbox mis au rebut pendant une panne de Redis
- Constat : `outbox_claim` incrémente `attempts` à chaque réclamation et ne réclame plus
  au-delà de 10. Quand Redis est injoignable, `relay.py` (run_once) compte chaque échec de
  publication comme une tentative : après quelques minutes de panne, des événements sains
  atteignent le plafond et ne repartent jamais seuls. `/system/workers` ne le signale pas.
- Test : relais avec un bus qui lève à chaque publication pendant plus de 10 passes, puis un
  bus qui répond : les événements doivent être publiés après le retour de Redis.
- Correctif : distinguer une panne de transport (connexion, délai) d'un événement
  empoisonné (échec propre à cet événement). Sur panne de transport, restituer la tentative
  (UPDATE attempts = attempts - 1 par une fonction SECURITY DEFINER de coges_bus, sur le
  patron de outbox_mark_published) ou vérifier Redis AVANT de réclamer. Le plafond de 10 ne
  vaut que pour un échec propre à l'événement.
- Ajoute le problème `outbox_dead_lettered` à `/system/workers` (503 si le rebut est non
  nul, avec le compte), et à `make ops-status`. Documente dans docs/runbooks/workers.md
  comment rejouer un événement mis de côté.

P1.2 Images de production : nettoyage et étiquettes (.github/workflows/deploy.yml)
- Constat : le nettoyage `delete-package-versions` garde « 5 versions » tous
  environnements confondus : cinq déploiements de préproduction peuvent supprimer l'image
  de production, donc le retour arrière et la reconstruction du VPS échouent.
  Par ailleurs, rien ne vérifie qu'une étiquette `vX.Y.Z` saisie n'existe pas déjà, et le
  checkout du job `images` ne part pas de l'étiquette : un déclenchement manuel depuis
  `main` avec `version=v1.2.0` pousse le code de `main` sous une étiquette existante.
- Correctif : (a) refuser une version déjà présente dans le registre ou déjà étiquetée dans
  git, sauf préproduction avec SHA ; (b) pour une version `vX.Y.Z` : checkout de l'étiquette
  git correspondante, qui doit exister ; (c) le nettoyage ne supprime JAMAIS une version qui
  est celle en production ou la précédente (fichiers de version du VPS : documente comment
  les retrouver, par exemple une étiquette mobile `production` et `production-previous`
  posées par le job de déploiement) ; ne purge que les versions de préproduction anciennes.
- Test : script de décision du nettoyage testé en Python (liste de versions en entrée,
  liste à supprimer en sortie) avec les cas : 5 préprods récentes + 1 production ancienne
  (la production reste), étiquette déjà existante (refus).
- [DEMANDER] Le quota gratuit de GitHub (500 Mo de paquets privés) ne suffit pas pour 5
  versions de ~460 Mo : propose les trois options (GitHub Pro, garder 2 versions, registre
  ailleurs) avec leur coût, ne choisis pas seul.

P1.3 Paiement rattaché à une vente sans contrôle (finance/service.py record_payment)
- Constat : `PaymentCreate` accepte `sale_id` ; `record_payment` le recopie dans le paiement
  sans vérifier le statut de la vente, le plafond, ni la dette. Un porteur de
  `payments:create` peut faire passer `paid_total` au-dessus du total, ou encaisser
  directement une vente dont la dette reste ouverte (le client paierait deux fois).
  L'ADR 0062 dit que le reste dû d'une vente suit sa dette.
- Test : (1) vente à crédit confirmée, POST /payments avec sale_id et sans allocation ->
  doit être refusé ; (2) montant supérieur au total -> refusé ; (3) vente brouillon ou
  annulée -> refusé ; (4) le cas légitime existant garde son comportement.
- Correctif [DEMANDER] : (a) retirer `sale_id` de `PaymentCreate` (le paiement d'une vente
  passe par la dette et ses allocations, déjà le cas de l'écran) ; ou (b) le garder et exiger
  vente confirmée, sans dette ouverte, et paid_total + montant <= total. Recommandation : (a)
  si aucun écran ni test ne l'utilise ; vérifie par recherche dans le front et les tests.
  Mets à jour openapi.json, frontend/types/api.ts et le registre commit_failure.

P1.4 Lignes d'un brouillon modifiées sans verrou (sales/service.py)
- Constat : `add_item`, `update_item`, `remove_item` lisent la vente sans `FOR UPDATE` alors
  que `confirm_sale` la verrouille. Une ligne ajoutée pendant la confirmation peut changer
  le total après le calcul de la dette et du paiement, sans sortie de stock ni coût.
- Test de concurrence (deux threads, comme tests/integration/test_concurrency_and_figures.py) :
  confirmation et ajout de ligne simultanés -> le résultat doit être soit « ligne dans la
  vente confirmée avec sortie de stock », soit « ligne refusée car la vente n'est plus un
  brouillon », jamais une vente confirmée dont le total ne correspond pas à ses sorties.
- Correctif : `get_for_update` (le même ordre de verrous que confirm_sale) dans les trois
  fonctions ; vérifie qu'aucune autre écriture sur les lignes (remise globale, client) a le
  même défaut. Ajoute l'invariant « vente confirmée : total = lignes = sorties de stock » à
  tests/helpers/invariants.py s'il n'y est pas déjà.

P1.5 Secret JWT par défaut accepté hors du développement (core/config.py)
- Constat : le défaut « change-me-000… » passe le validateur de longueur. Seul le VPS est
  protégé (check_runtime_env). Un environnement oublié (préproduction, démo) signerait avec
  une clé publique dans le dépôt.
- Test : Settings(env="production"|"staging"|"preprod", jwt_secret par défaut) -> erreur au
  démarrage ; `local` et `ci` acceptent le défaut ; un secret réel passe.
- Correctif : validateur de modèle qui refuse le secret par défaut (et tout secret commençant
  par « change-me ») hors `local` et `ci`. Fais de même pour `trust_proxy_headers` hors
  `local`/`ci`/VPS si cela a du sens (lis ADR 0083 avant), et pour tout autre défaut de
  développement que tu trouves dans config.py (liste-les dans l'ADR).

P1.6 Recréer un compte désactivé avec le même e-mail ou téléphone -> 500
- Constat : `users_email_uq` et `users_phone_uq` sont des UNIQUE (company_id, email|phone)
  sans filtre sur `deleted_at`, alors que `get_by_email` / `get_by_phone` ignorent les comptes
  supprimés : la vérification passe, l'INSERT échoue avec une IntegrityError non traduite.
- Test : désactiver un utilisateur puis en créer un autre avec le même e-mail, puis le même
  téléphone -> doit répondre proprement ; deux créations simultanées avec le même e-mail ->
  422 pour la seconde, jamais 500.
- Correctif [DEMANDER] : (a) index uniques partiels `WHERE deleted_at IS NULL` (migration,
  downgrade compris) pour permettre de réutiliser l'e-mail d'un employé parti ; ou (b)
  message clair « ce compte existe, désactivé : le réactiver ? ». Recommandation : (a).
  Dans les deux cas, traduis toute IntegrityError d'unicité en 422 au niveau du service
  (un `_flush` commun comme ailleurs dans le dépôt) pour que même une course ne donne pas 500.
  Vérifie la fonction auth_lookup (0019, 0022) : elle ne doit pas renvoyer un compte supprimé
  quand un homonyme actif existe.

P1.7 Alertes mélangées entre utilisateurs dans le cache du tableau de bord
- Constat : le cache du tableau de bord est par entreprise (60 s) mais `active_alerts` dépend
  de la personne connectée (`list_for_user(ctx.user_id)`). Le gérant peut voir pendant 60 s
  les alertes non lues d'un vendeur, ou l'inverse (lues/non lues faux).
- Test : A lit le tableau de bord (cache rempli), marque une alerte comme lue, B lit : chacun
  voit son propre état. Vérifie aussi que `cash_on_hand` et la marge ne sont montrés qu'à
  ceux qui ont la permission (lis ADR 0007 et la matrice : le vendeur et le comptable portent
  `dashboard:read` ; confirme que ce qu'ils voient est voulu, sinon [DEMANDER]).
- Correctif : sortir `active_alerts` (et tout champ propre à la personne) du cache, ou
  mettre la personne dans la clé. Mets à jour tests/tenancy/test_redis_keys_isolation.py si
  la forme des clés change.

P1.8 Annuler un achat de stock ne rend pas le coût moyen pondéré (CMP)
- Constat : stock 10 à 50, achat de 10 à 100 -> CMP 75 ; annulation de l'achat -> quantité 10
  mais CMP reste 75 (50 attendu). La valeur du stock et les marges suivantes sont faussées ;
  `rebuild_product_stock` rejoue la même formule et ne corrige rien (cmp_next_avg ne change
  pas la moyenne sur une sortie, et l'inverse d'une entrée est une sortie).
- Test : le scénario ci-dessus, plus : entrée, vente, annulation de l'entrée ; deux achats
  et annulation du premier.
- Correctif [DEMANDER] : (a) interdire l'annulation d'une entrée quand d'autres mouvements du
  même produit l'ont suivie (message clair, le geste correct est une correction de stock
  datée) ; ou (b) recalculer le CMP en rejouant le journal du produit depuis le mouvement
  annulé. Recommandation : (a), plus simple et sans réécriture d'historique ; vérifie que
  `rebuild_product_stock` reste cohérent avec la règle choisie.
  Ajoute au registre des invariants : valeur du stock = quantité x CMP après chaque scénario.

Fin de la partie 1 : suite backend complète, ruff, mypy, make front-check (si l'API change),
e2e des écrans touchés, make test-tenancy, make check-generated (openapi et types), CI verte.
Mets à jour CLAUDE.md (ADR) et README-infra.md si une variable change.
```

```
Correctifs de la revue — partie 2 (branche fix/review-findings-2, depuis main à jour,
après la fusion de la partie 1). Mêmes règles et même MÉTHODE que la partie 1 : chaque point
est d'abord REPRODUIT par un test ; s'il ne se reproduit pas, tu ne changes rien et tu l'écris
dans l'ADR avec la raison. Ces points viennent de la relecture et n'ont pas tous été recoupés.

Sécurité et sessions
P2.1 Mot de passe changé ou compte désactivé -> révoquer les sessions de la personne
  (`auth_sessions`, `revoke_family`) dans change_password, change_own_password et
  deactivate_user. Un jeton de rafraîchissement volé ne doit pas survivre au changement.
  Après un changement par la personne elle-même, garde la session courante si c'est simple,
  sinon toutes. Test : ancien jeton de rafraîchissement refusé après le changement.
P2.2 Redis absent au premier appel : `cache.get_client` mémorise l'échec (lru_cache) et les
  limites par IP et par entreprise restent coupées jusqu'au redémarrage. Ne pas mémoriser un
  échec ; retenter après quelques secondes. Test : Redis démarre après l'API.
P2.3 Délégation de droits : `POST /users` assigne les `role_ids` du corps sans exiger que le
  rôle n'excède pas les droits de l'appelant, et `PATCH /roles/{id}` permet d'ajouter
  `users:*` à un rôle sur mesure en contournant LOCKED_ABILITIES. Refuse l'attribution d'un
  rôle plus puissant que l'appelant, et refuse `users:*` et `roles:*` sur un rôle autre que
  gérant, sur TOUTES les routes (pas seulement /abilities). Test par route.
P2.4 Freinage de connexion : (a) un seul mauvais essai toutes les 30 min maintient le
  blocage de la victime même avec le bon mot de passe : garde le principe de l'ADR 0078 mais
  documente la limite et fais décroître le compteur avec le temps (fenêtre glissante
  réelle) ; (b) la séquence vérifier -> Argon2 -> enregistrer l'échec n'est pas atomique :
  une rafale parallèle passe avant le premier échec compté, compte l'échec AVANT la
  vérification Argon2 puis annule-le en cas de succès ; (c) un compte joignable par e-mail et
  par téléphone a deux compteurs : normalise vers l'identité du compte quand elle existe SANS
  révéler son existence ; (d) en mode dégradé, séparer les clés d'IP et de compte du LRU et
  ne pas laisser un flot d'identifiants fantaisistes évincer la victime ; si Redis clignote,
  l'échec enregistré en mémoire doit compter dans le contrôle suivant.
  [DEMANDER] avant de toucher à (a) et (c) : ils changent le comportement visible.
P2.5 X-Forwarded-For se terminant par une virgule : `rsplit(",",1)[-1]` donne une chaîne
  vide et le middleware saute la limite. Retombe sur l'adresse du pair TCP quand le segment
  est vide ou invalide. IPv6 : regroupe les compteurs par /64.
P2.6 Identifiant de requête : `.match` accepte un saut de ligne final, passe à `fullmatch`.
P2.7 Paramètres SQL dans les journaux et Sentry : `create_engine(..., hide_parameters=True)`
  et nettoyage des messages d'exception dans scrub_event (e-mail, hachage Argon2). Test : une
  erreur SQL forcée ne laisse ni valeur liée ni e-mail dans la sortie de journal.

Argent, stock, dates
P2.8 Verrous : ordre des verrous cohérent (par product_id, puis dette puis retour partout)
  dans receive_delivery, cancel_sale (for_references trie par UUID aléatoire), refund_return
  et cancel_payment ; traduis l'erreur PostgreSQL 40P01 (interblocage) et 40001 en 409
  « Réessayez » plutôt que 500. Test de concurrence croisée.
P2.9 Dates : `paid_at`, `returned_at`, `sold_at` sans fuseau horaire provoquent un TypeError
  (500) dans la comparaison avec « maintenant » ; exige un fuseau (422 clair) comme pour les
  mouvements de stock. `sold_at` d'une vente créée en brouillon puis confirmée un autre jour
  doit être recalée à la confirmation si la personne n'a pas saisi de date (sinon le chiffre
  d'affaires tombe sur la veille ou sur un mois clos) ; [DEMANDER] le comportement voulu.
P2.10 Dépenses : refuser de modifier le montant ou de supprimer une dépense déjà payée (ou
  passer par une contre-écriture comme pour les paiements, ADR 0038).
P2.11 Produits : `is_stock_tracked` ne se change plus s'il existe des mouvements ou du stock ;
  suppression d'un produit avec stock restant refusée ; un retour sur un produit supprimé
  logiquement remet bien la marchandise en stock (charger aussi les produits supprimés).
  Clients : refuser la suppression avec des dettes ouvertes.
P2.12 `setattr(None)` sur colonnes NOT NULL : `{"name": null}` donne 500 ; rejette en 422 dans
  les schémas de mise à jour (clients, fournisseurs, produits, catégories).
P2.13 Sous-total de vente : arrondir par ligne comme net_amount, pour que somme des lignes =
  total (trigger sale_items, migration corrective si besoin).

Processus de fond
P2.14 Celery : plafond de redélivrance pour acks_late + reject_on_worker_lost (une tâche qui
  fait tomber le worker ne doit pas boucler), `stop_grace_period` de 120 s dans les compose
  (tâches jusqu'à 360 s), `retry` sur les tâches d'alerte comme sur analytics.
P2.15 Rétention des sauvegardes (backup_retention.py) : ne considérer que les `.dump.age`
  (ignorer les `.sha256` orphelins), « premier dump de la semaine/du mois » plutôt que le
  dimanche/le 1er exacts, et un PLANCHER : ne jamais supprimer les N plus récentes sauvegardes
  valides même si les 7 derniers jours sont vides. Tests unitaires avec les cas cités.
P2.16 backup.sh : le contrôle de taille compare à la dernière sauvegarde VALIDÉE (pas à la
  dernière envoyée), un dump trop petit n'est pas gardé comme référence ; le premier lancement
  (préfixe distant vide) ne doit pas échouer ; `MIN_RATIO` jamais injecté dans du code Python.
P2.17 verify_restore.py : exige un manifeste de comptes écrit à la sauvegarde (lignes par table
  clé) et compare ; le contrôle du stock part des mouvements ET de product_stock.
P2.18 check_runtime_env.py : remplacer la liste noire de « ://coges_owner » par une analyse
  de l'URL (urlsplit + unquote) et une liste blanche de rôles (coges_app, coges_relay,
  coges_analytics) ; refuser aussi ?user= et les variantes encodées. Contrôler COGES_STACK
  (cf. P2.19). Tests avec les contournements cités (neondb_owner, coges%5Fowner, ?user=).
P2.19 deploy.sh : `export COGES_STACK="$STACK"` et refus si le fichier d'environnement en
  porte une autre valeur (une préproduction copiée du modèle ne doit jamais prendre l'alias
  réseau de la production sur coges_edge) ; retour arrière si `up -d` échoue (pas seulement si
  la vérification échoue) ; stocker le corps de /login dans une variable avant de le tester
  (pipefail + grep -q peut échouer à tort) ; nettoyage automatique des images anciennes qui
  garde production et précédente.
P2.20 Workflows : bloc `permissions: contents: read` en tête de ci.yml ; actions tierces
  figées par SHA ; les environnements de déploiement et de sauvegarde ne s'exécutent que
  depuis `main` ou une étiquette (condition sur github.ref dans chaque job qui lit un secret).
  Documente dans deploy/README-infra.md les protections d'environnement GitHub à régler
  par le propriétaire (branches autorisées, relecteur obligatoire pour production).
P2.21 Caddy : ne pas journaliser la chaîne de requête (noms et téléphones de clients dans les
  recherches). Redis : maxmemory plus bas que la limite du conteneur (marge pour la réécriture
  AOF), image d'autoheal figée par condensat. Ajoute un .dockerignore au front (ni .env.local
  ni jetons dans le contexte de build).

Import, export, front
P2.22 xlsx : avant `load_workbook`, ouvrir le zip, refuser si la somme des tailles
  décompressées dépasse une limite (par exemple 30 Mo) ou si le ratio est absurde, borner
  nombre de colonnes et longueur de cellule. Test avec un zip fabriqué (sans fichier géant dans
  git : génère-le dans le test).
P2.23 Nombres importés : « 1.500 » et « 1,500 » ne doivent pas devenir 1,5 en silence ;
  un séparateur unique suivi de exactement trois chiffres est ambigu -> ligne rejetée avec un
  message clair (« Écrivez 1500 »). En-têtes de colonnes en double -> erreur. Repli cp1252 :
  signaler au lieu de remplacer par « � ». Recherche : retirer les caractères de contrôle et
  NUL dans normalise_term (500 sur ?search=%00).
P2.24 Export des ventes : plafond d'exports en attente par entreprise, vérifier la taille avant
  de tout construire en mémoire si possible, clé d'idempotence ; export des catégories : le
  nom du parent ambigu empêche la réimportation -> exporter aussi le code du parent.
P2.25 Front : (a) vérifie la signature réelle de l'écran d'erreur de la version de Next
  installée (prop `retry`, `reset` ou `unstable_retry`) et ajoute un test e2e qui clique sur
  « Réessayer » ; (b) la référence d'incident n'est affichée que si elle vient de
  `ApiError.requestId` ; pour un `digest` Next, afficher le digest tel quel, jamais
  « 0000 0000 » ; (c) payment-amount.ts : refuser signes et décimales, `/^\d+$/` avant
  BigInt ; (d) allocation.ts : ignorer les dettes de solde <= 0 ; (e) session.ts : logout
  attend un rafraîchissement en cours, délai maximal sur navigator.locks, comparer le jeton
  avant de relancer une seconde rotation sur deux 401 décalés.

Fin de la partie 2 : mêmes vérifications que la partie 1 + shellcheck sur les scripts, suite
backend complète, CI verte. Dans l'ADR, tableau des points : reproduit / non reproduit /
corrigé / reporté (avec la raison de chaque report).
```

## Ce que le propriétaire fait lui-même

1. Choisir pour les points marqués `[DEMANDER]` : l'agent posera les questions, les options recommandées sont indiquées.
2. Dans les réglages GitHub : restreindre les environnements `production`, `preprod`, `backup` et `backup-purge` à `main` et aux étiquettes, et exiger une relecture pour `production`.
3. Décider du quota des paquets GitHub (Pro, 2 versions gardées, ou registre ailleurs).
4. Revoir l'ADR de chaque partie avant la fusion, surtout P1.3 (paiements), P1.4 (verrous) et P1.8 (coût moyen) qui touchent à l'argent.
