# Prompt 20 — Lot C : intégrité et isolation prouvées

Branche `feat/integrity-lot-c`, depuis `main` à jour, après le lot A (prompt 16). Peut se faire en parallèle du prompt 19, mais pas des prompts qui modifient `core/deps.py` ou `core/tenancy.py`. Points 5, 6 et 10 de la liste « avant la production ».

Pourquoi ce lot : le lot A a prouvé l'échec au COMMIT sur trois opérations. Ici on le prouve sur toutes les écritures critiques, on prouve qu'aucune lecture ne fuit entre deux entreprises (y compris les routes sans identifiant dans l'URL, que le test existant `test_route_cross_tenant.py` ne croise pas), et que Redis et les tâches de fond ne mélangent jamais deux entreprises. Le but n'est pas d'ajouter des fonctionnalités : c'est de rendre impossible de livrer une régression d'isolation sans que la CI devienne rouge.

```
Lot C — Intégrité et isolation prouvées (branche feat/integrity-lot-c, depuis main à jour,
après le lot A). Règles habituelles : ADR aux prochains numéros libres, tests d'abord,
aucun service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni
backend/.vercel/. Résumé en français à la fin, questions ouvertes par AskUserQuestion.
Principe : des tests qui DÉCOUVRENT les routes dans l'application (comme
tests/tenancy/test_route_cross_tenant.py) plutôt que des listes écrites à la main, et un
registre qui fait échouer la CI quand une nouvelle route n'est pas classée.

C1. Échec au COMMIT sur TOUTES les écritures critiques (point 5)
- Réutilise le mécanisme du lot A (A5). Étends-le en un test découvert automatiquement :
  parcourt toutes les routes POST/PUT/PATCH/DELETE authentifiées, exige que chacune soit
  classée dans un registre (tests/integration/commit_failure_registry.py) : « écriture
  critique » (testée ici) ou « sans écriture / exemptée » avec la raison écrite. Une route
  ajoutée plus tard et absente du registre fait échouer le test.
- Pour chaque écriture critique : forcer l'échec du COMMIT, vérifier réponse 5xx (jamais
  2xx), aucune ligne écrite (comparer des comptages avant/après sur les tables concernées),
  aucun événement d'outbox, clé d'idempotence non enregistrée comme succès, aucune entrée
  d'audit orpheline, cache Redis de l'entreprise NON invalidé à tort ni rempli de la valeur
  fantôme ; puis rejouer le même appel avec la même clé : succès, une seule écriture.
- Couvre au minimum : ventes (créer, ligne, confirmer, annuler), retours, paiements et
  règlements, dépenses, stock (entrée, correction, réassort, inventaire), clients et
  fournisseurs (création, modification, désactivation), produits et catégories, utilisateurs
  (création, mot de passe, rôles), imports, réglages de l'entreprise.
- Si un test est rouge (succès renvoyé alors que rien n'est écrit, ou écriture partielle),
  corrige à la racine (core/deps.py, core/tenancy.py, ordre commit/cache/outbox), montre la
  sortie rouge puis verte dans la PR, et explique la cause dans l'ADR.
- Ajoute le cas inverse : si l'ÉCRITURE réussit mais que la RÉPONSE est perdue (client qui
  coupe), le rejeu avec la même clé renvoie la même réponse sans nouvelle écriture.

C2. Isolation de toutes les lectures, y compris sans identifiant dans l'URL (point 6)
- Nouveau test tests/tenancy/test_list_routes_cross_tenant.py : crée deux entreprises A et
  B avec des données reconnaissables (noms, montants, références uniques par entreprise,
  dont des cas limites : même nom de client dans les deux, même numéro de pièce).
  Découvre toutes les routes GET sans paramètre de chemin et sans exception (listes,
  tableau de bord, finance, rapports, analyses, aperçus/insights, notifications, journal
  d'audit, exports, recherche, compteurs). Appelées avec le jeton de A, aucune réponse ne
  doit contenir la moindre trace de B : parcours récursif du JSON à la recherche des
  identifiants, noms et montants marqueurs de B (exports CSV/PDF compris : lis le fichier).
- Même test avec des paramètres de requête hostiles : filtres par identifiant d'une
  ressource de B (customer_id, product_id, supplier_id, user_id, sale_id…) -> 404 ou liste
  vide, jamais les données de B ni un message qui révèle son existence ; pagination
  (page très grande, limite énorme, tri sur un champ inattendu) ; recherche avec jokers
  (%, _, guillemets) sans fuite ni erreur SQL.
- Lectures croisées en écriture : un identifiant de B glissé dans le corps d'une écriture de
  A (client, produit, fournisseur, ligne de vente, paiement) -> 404/422 sans effet, aucune
  ligne créée chez A pointant vers B (complète test_t05_cross_tenant_fk.py).
- Rôles : un vendeur de A n'accède pas aux routes réservées au gérant de A ; un gérant de B
  n'accède à rien de A ; un jeton de A avec l'en-tête ou le slug de B reste confiné à A.
  Jeton expiré, jeton d'une entreprise désactivée -> 401/403 sans donnée.
- Registre à jour : les routes sans paramètre rejoignent le registre du test existant, et
  toute nouvelle route non classée fait échouer la CI (même mécanisme que pour les routes
  paramétrées).
- RLS : le test t36/t37 doit couvrir aussi les tables ajoutées par les lots A, 17 et 19
  (par exemple job_runs). Toute table de tenant sans politique RLS fait échouer la CI ;
  toute table de plateforme volontairement sans RLS est listée avec sa raison.

C3. Redis : aucune clé partagée entre entreprises (point 10)
- Inventaire automatique : un test lance une série d'opérations pour A et B (tableau de
  bord, cache, limitation de débit, idempotence, jetons, notifications) puis parcourt TOUTES
  les clés Redis créées (SCAN) et vérifie que chacune est soit préfixée par
  coges:<company_id>:, soit un hachage sha256 documenté (rl:acct:…), soit une clé globale
  figurant dans une liste blanche commentée (rl:ip:…, rl:login:…, heartbeats). Une clé
  inconnue fait échouer le test.
- Cache : le tableau de bord de A mis en cache n'est jamais servi à B, même avec la même
  clé d'idempotence, le même utilisateur nominal ou le même nom de ressource ; l'invalidation
  de A n'efface pas le cache de B ; TTL toujours présent (aucune clé sans expiration, sauf
  liste blanche).
- Idempotence : la clé d'idempotence est liée à (entreprise, utilisateur, route, empreinte du
  corps). Même Idempotency-Key envoyée par A et par B -> deux traitements indépendants, jamais
  la réponse de l'autre. Même clé avec un corps différent -> 422/409, pas de rejeu.
  Deux requêtes SIMULTANÉES avec la même clé -> une seule écriture, l'autre attend ou reçoit
  409 « en cours ».
- Limitation de débit : le plafond par entreprise (rl:tenant) de A ne ralentit pas B. Le
  frein par compte du lot A (rl:acct) est le même quel que soit le slug tapé : pas de fuite
  d'existence.
- Redis vidé ou indisponible : aucune écriture ne réussit à tort ni n'échoue à tort à cause du
  cache ; les lectures retombent sur la base ; le comportement est identique pour A et B.

C4. Tâches de fond : une entreprise par tâche, une panne n'arrête pas les autres
- Les tâches par entreprise de l'éventail (beat.py) : chaque tâche reçoit un company_id,
  ouvre sa propre transaction tenant, ne lit et n'écrit que cette entreprise
  (complète test_worker_tenant_isolation.py pour TOUTES les tâches découvertes dans
  BEAT_SCHEDULE, avec un registre qui échoue si une tâche n'est pas classée).
- Une entreprise en échec (exception forcée) n'empêche ni les suivantes ni le journal des
  tâches (job_runs, prompt 17) de noter « failed » avec company_id ; la tâche est relançable
  à la main sans doublon (idempotence testée deux fois de suite : même résultat, mêmes
  comptages).
- Relais de l'outbox : un événement de A n'est jamais livré avec le contexte de B ; un
  événement empoisonné (traitement qui échoue toujours) est mis de côté après N essais sans
  bloquer la file des autres entreprises ; at-least-once vérifié (rejeu = effet unique côté
  consommateur).

C5. Concurrence et cohérence des chiffres
- Deux confirmations simultanées de ventes se disputant le dernier article en stock : une
  seule réussit, l'autre reçoit une erreur claire (« Stock insuffisant »), stock jamais
  négatif, coût moyen pondéré cohérent.
- Double clic sur « Encaisser » (même clé, requêtes parallèles) : un seul paiement. Deux
  règlements différents en parallèle sur la même dette : somme jamais supérieure à la dette.
- Après chaque scénario, contrôle croisé : somme des lignes de vente = total de la vente =
  montant en caisse + créances ; stock calculé = somme des mouvements ; chiffre d'affaires
  du tableau de bord = somme des ventes confirmées du jour. Écris-le comme une fonction
  réutilisable (tests/helpers/invariants.py) appelée en fin de chaque test d'intégration
  critique, et branche-la aussi sur le jeu `demo` (make seed-demo puis contrôle).

C6. Fin de lot
Suite backend complète (les nouveaux tests tournent dans make test et, pour les fuites,
dans make test-tenancy bloquant en CI), ruff, mypy, make front-check, CI verte. Donne dans
l'ADR : la liste des routes classées par catégorie (critique / lecture / exemptée avec
raison), les corrections de fond éventuelles, et la durée ajoutée à la CI (si elle dépasse
5 minutes de plus, sépare les tests lents dans un job parallèle). Mets à jour CLAUDE.md
(règle : toute nouvelle route doit être classée dans les registres, la CI l'impose).
```

## Ce que le propriétaire fait lui-même

Rien à créer côté comptes pour ce lot. À la fin, lisez seulement le résumé de l'ADR : si l'agent a dû corriger du code de fond (COMMIT, cache, concurrence), demandez-moi de relire la correction avant de fusionner, car c'est la partie qui touche à l'argent des commerçants.
