# 0032 — Le chemin asynchrone : relais, rôles, idempotence, alertes et cache

- **Date** : 2026-09-25
- **Phase** : 08
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`, questions 1 à 4 et 7 du prompt de phase)

## Contexte

Tout ce qui se passe **après COMMIT** est construit dans cette phase : sortir les événements de
l'outbox, les faire consommer, en tirer des alertes et des agrégats, et servir le tableau de bord
assez vite pour qu'il soit le premier écran de la journée.

Quatre questions n'avaient pas de réponse dans l'architecture, et elles se tiennent : qui lit
l'outbox et avec quels droits, comment un consommateur rejoué ne produit pas deux fois son effet,
où finit un événement qu'on n'arrive pas à publier, et qui reçoit une alerte.

## Décision 1 — Un relais en processus dédié, sous un rôle qui ne touche aucune table

`app/workers/relay.py` est un processus à part (`make relay`), pas une tâche Celery : une tâche
qui alimente la file dont elle dépend est un cycle, et il se referme exactement quand Redis va
mal. La boucle réclame un lot par `outbox_claim(batch)` — `FOR UPDATE SKIP LOCKED`, `attempts`
incrémenté dans le même mouvement — publie, puis marque `published_at` par
`outbox_mark_published(ids)`. Pause quand la file est vide, back-off exponentiel quand la
publication échoue, remis à zéro par un passage réussi.

Le relais est **le seul composant multi-tenant du projet** : `business_events` doit être lu sans
filtre d'entreprise. Il ne reçoit pourtant aucun privilège de contournement et **aucun privilège
de table**. Il se connecte en `coges_relay`, qui n'a qu'`EXECUTE` sur deux fonctions
`SECURITY DEFINER`. La surface qui franchit la RLS tient donc en deux fonctions, lisibles d'un
coup d'œil, au lieu d'un rôle `BYPASSRLS` dont il faudrait relire tout le code.

Ces fonctions appartiennent à **`coges_bus`** (`NOLOGIN`, `BYPASSRLS`), pour la raison de
l'ADR 0005 : sous `FORCE ROW LEVEL SECURITY`, une fonction `SECURITY DEFINER` appartenant à
`coges_owner` ne verrait rien non plus. Un troisième rôle, **`coges_analytics`**, exécute les
tâches de projection : il lit le transactionnel, écrit les tables analytiques, et c'est le **seul
rôle du projet autorisé à `DELETE`** — uniquement sur `daily_sales_facts`, qui se reconstruit
intégralement depuis le journal. Sans lui, la purge d'un fait devenu vide serait impossible et
**T31** échouerait.

Les trois rôles sont créés par `deploy/postgres/init/01-roles.sql` : un rôle est un objet de
cluster, il ne peut pas naître d'une migration. Après modification de ce fichier :
`docker compose down -v && make up`.

## Décision 2 — L'idempotence tient à une table, et à l'endroit où on l'écrit

`processed_events (company_id, consumer, event_id)`, clé primaire, sous RLS. `inbox.handle` pose
la marque **dans la transaction de l'effet** : elles commitent ensemble ou disparaissent
ensemble. Jamais d'effet sans marque, jamais de marque sans effet.

Une clé Redis à TTL était l'autre option. Elle ne peut pas commiter avec l'écriture métier : une
panne entre les deux perd l'effet ou le duplique, et c'est exactement le raisonnement de
l'ADR 0027 pour les clés d'idempotence des paiements. Redis reste déclaré non critique
(décision 04) ; la garantie ne peut donc pas reposer dessus.

La marque nomme son **consommateur**, pas seulement l'événement : `stock.updated` a deux abonnés,
et une marque anonyme ferait taire le second — celui qui arriverait en retard.

`ON CONFLICT DO NOTHING … RETURNING` : c'est l'index unique qui tranche, jamais un `SELECT`
préalable, sans quoi deux workers concurrents passeraient tous les deux.

## Décision 3 — La file de rebut est en base, pas sur un support jetable

Après dix tentatives, `outbox_claim` cesse de réclamer l'événement — le filtre `attempts < 10`
suffit, et `business_events` porte un `CHECK attempts <= 10`. L'événement **reste en base**,
rejouable à la main après correction. Une file Redis séparée aurait envoyé des données métier sur
un support qu'on redémarre sans y penser.

Le compteur est exposé par **`GET /api/v1/system/outbox`** : en attente, en rebut, publiés, date
du plus ancien en attente et de la dernière publication. La lecture passe par `coges_app`, donc
sous RLS : un gérant voit son outbox, pas celle de ses concurrents. La permission `system:read`
reste au gérant seul — ce n'est ni une information comptable, ni une information de caisse.

## Décision 4 — Les alertes visent un droit, et décrivent une situation

Le destinataire se déduit d'une **permission**, jamais d'un nom de rôle : `inventory:update` pour
le stock, `debts:update` pour les échéances, `sales:cancel` pour une annulation. Un rôle
personnalisé qui porterait le droit reçoit l'alerte sans qu'une ligne de code change.

La déduplication porte sur (type, entité, destinataire) sur une fenêtre de 24 h
(`COGES_NOTIFICATION_DEDUPE_HOURS`). Un stock bas est une **situation**, pas un flux d'événements :
sans fenêtre, chaque vente d'un article sous son seuil rouvrirait la même alerte, et un fil
illisible ne prévient plus de rien. L'entité fait partie de la clé, sans quoi deux produits en
rupture le même jour se dédoublonneraient l'un l'autre.

Le canal est un `Protocol` avec une seule implémentation en V1, `InAppChannel`, qui écrit en base.
L'e-mail réserve sa place sans fournisseur à choisir ni secret à gérer dans cette phase : le jour
où il arrivera, il s'ajoutera, il ne remplacera pas.

`debt_due` n'a pas d'événement et ne peut pas en avoir : une dette arrive à échéance précisément
quand **rien ne bouge**. C'est un balayage quotidien, et c'est pour lui qu'existe
`active_company_ids()` — une fonction `SECURITY DEFINER` qui ne rend **que des identifiants**.
Déduire la liste des entreprises ayant émis un événement aurait évité la fonction, et laissé les
entreprises calmes sans alertes.

## Décision 5 — Un cache court, transparent, et invalidé par événement

Le tableau de bord est mis en cache dans Redis, clé `coges:<company_id>:dashboard`, TTL 60 s, plus
une invalidation appelée par les consommateurs après COMMIT. La clé porte toujours le
`company_id`, construit par `app/core/cache.py` et jamais par l'appelant : aucune RLS ne veille
sur Redis, et une clé partagée serait une barrière de moins.

Toute panne du cache est avalée : Redis indisponible fait recalculer et servir, jamais échouer.
La valeur relue est **revalidée par Pydantic** plutôt que réinjectée telle quelle, de sorte
qu'une entrée écrite par une version antérieure du schéma est rejetée et non servie à moitié.

L'invalidation, dans `rebuild_sale_day`, est **hors** de la transaction : vider le cache avant le
COMMIT laisserait une lecture concurrente le remplir aussitôt avec les anciens chiffres.

## Conséquences

- Quatre fabriques de sessions cohabitent (`coges_app`, `coges_relay`, `coges_analytics`, et le
  propriétaire pour les migrations), toutes construites par `create_app_engine`, donc toutes avec
  le `RESET ALL` au retour au pool de l'ADR 0003.
- Les tests ont besoin des DSN des deux nouveaux rôles : `COGES_TEST_DATABASE_URL_RELAY` et
  `COGES_TEST_DATABASE_URL_ANALYTICS`. Sans eux, les suites du chemin asynchrone sont ignorées
  plutôt que de passer sous `coges_app` — elles passeraient pour de mauvaises raisons.
- Une tâche ouvre sa propre session : les tests la branchent sur `coges_test` par la fixture
  `workers_bound_to_test_database`, l'équivalent de ce que `api_client` fait pour l'API.
- T36 s'étend : les rôles de workers ne contournent pas la RLS, `coges_relay` ne détient aucun
  privilège de table, `coges_analytics` ne peut supprimer que des tables reconstructibles, et les
  fonctions privilégiées sont révoquées de `PUBLIC` puis accordées nommément.
- Aucune notation d'événement nouvelle. Un test d'architecture vérifie que les neuf types ont
  chacun au moins un abonné et que chaque abonné nommé correspond à une tâche enregistrée : un
  type sans abonné serait écrit, publié, puis perdu — la panne la plus difficile à voir, parce
  que rien n'échoue.
