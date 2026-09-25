# 0034 — Écarts assumés de la phase 08

- **Date** : 2026-09-25
- **Phase** : 08
- **Statut** : acceptée
- **Décideur** : utilisateur, pour l'écart 1 ; les autres découlent des documents, et sont
  consignés parce qu'ils se voient dans le code

## Contexte

La phase 08 bascule `GET /api/v1/analytics/overview` sur `daily_sales_facts`, comme l'ADR 0030
l'avait annoncé : « la phase 08 remplacera la source par `daily_sales_facts` sans changer le
contrat, et l'écart entre les deux deviendra le test T32 ». Quatre conséquences méritent d'être
écrites, parce qu'elles se voient dans le code et qu'aucun document ne les prévoit.

## Écart 1 — L'overview devient éventuellement cohérent

Une vente confirmée n'apparaît dans l'overview qu'une fois le relais passé et la tâche analytique
exécutée : quelques secondes en production. C'est le prix de la règle « aucun calcul long dans une
requête HTTP » (décision 14) et la contrepartie exacte du budget de 200 ms.

L'autre option aurait été de calculer la journée en cours directement sur `sale_items` et de lire
les faits pour le passé. Elle rend l'overview immédiat, et elle ramène dans la requête HTTP le
balayage qu'on venait d'en sortir — à l'heure où il est le plus coûteux, la journée en cours étant
celle qui reçoit toutes les écritures.

Assumé, donc, et sans champ supplémentaire dans la réponse : l'ajout d'un `computed_through` a été
envisagé et écarté pour cette phase. L'écran d'accueil affiche déjà `computed_at`.

**Conséquence sur les tests** : aucun worker ne tourne pendant la suite. Les tests qui mesurent un
revenu reconstruisent d'abord les faits du jour, sous `coges_analytics`, par
`facts_harness.rebuild_around`. Un test qui confirme une vente puis interroge l'overview sans
passer par là mesure une projection vide — et il l'a fait avant qu'on le corrige.

## Écart 2 — `sale_count` reste compté sur `sales`

Le § 4.10 définit `daily_sales_facts.sale_count` comme le nombre de ventes **contenant le
produit** : c'est le grain jour × produit. Sommer cette colonne pour obtenir le nombre de tickets
d'une période compterait deux fois une vente à deux articles.

Sales expose donc `confirmed_sale_count()`, et c'est la seule mesure de l'overview et du tableau
de bord qui reste lue sur le transactionnel. Elle porte sur une table indexée par
`sales_confirmed` et ne coûte rien.

La même colonne garde son sens d'origine dans les classements produit : c'est la métrique
`frequency` — « vendu souvent », qui n'est pas « beaucoup vendu ».

## Écart 3 — Les produits sont arrondis à la ligne, dans les deux sources

`SaleRevenueRepository` arrondit `qty × unit_price` et `qty × unit_cost` **à la ligne**, par
`round(…, 2)`, comme `sale_items.net_amount` l'est déjà par sa définition générée en base.

Sans cet arrondi, le calcul direct sommerait des produits à pleine précision pendant que
`daily_sales_facts` arrondirait chaque total jour × produit dans ses colonnes `numeric(14,2)`.
L'écart, invisible sur une vente, s'accumulerait sur quatre-vingt-dix jours : **T32** passerait ou
échouerait selon le jeu de données, ce qui est la pire forme de test — celle qui n'apprend rien
quand elle est verte. Avec l'arrondi, les deux sources sont égales par construction, et la
tolérance de 0,01 du § 10 reste une marge, pas une béquille.

## Écart 4 — Les bornes de période sont dans le fuseau de l'entreprise

`daily_sales_facts.day` est le jour **local** de la vente (§ 4.10). Les bornes instantanées d'une
plage de dates sont donc calculées dans le fuseau de l'entreprise, et non en UTC comme la phase 07
les calculait. Sans cela, une entreprise qui n'est pas à l'heure de Greenwich verrait l'overview et
les faits décrire deux périodes différentes, et T32 accuserait la reconstruction d'un écart qui ne
serait qu'un décalage de fuseau.

Un gérant qui demande « du 1er au 30 » désigne ses journées, pas celles de Londres.

## Écart 5 — `SET LOCAL ROLE` dans la révision 0010

La révision 0010 emprunte `coges_auth` le temps de refermer l'ACL d'`auth_lookup`, que la
révision 0002 avait laissée ouverte à `PUBLIC` (l'ordre de ses instructions rendait ses `REVOKE` et
`GRANT` silencieusement inopérants ; une migration livrée ne se réécrit pas, la correction est donc
posée en avant).

L'emprunt est `SET LOCAL ROLE`, pas `SET ROLE` : Alembic exécute la révision dans une transaction,
le rôle retombe donc au COMMIT — et surtout au ROLLBACK, si une instruction suivante échoue. Sans
cela, une migration interrompue laisserait sa connexion ouverte sous un rôle `BYPASSRLS`. Le test
d'architecture qui interdit les `SET` de portée session ne porte donc aucune exception de plus.

## Conséquences

- `sales_service.revenue_totals()` n'est plus la source de l'overview, mais reste la source du
  **calcul de référence** de la réconciliation T32 : c'est justement le fait d'avoir deux chemins
  indépendants qui donne sa valeur au contrôle hebdomadaire.
- `facts_harness` accueille les outils de reconstruction partagés, et sert désormais autant les
  tests d'API que T29-T32.
- La mesure de latence vit dans `tests/perf/`, derrière le marqueur `perf`, hors de `make test` :
  elle sème une entreprise entière. Relevé sur poste de développement, jeu de `make seed-demo` :
  **29 ms de médiane à froid, 9 ms à chaud**, pour un budget de 200 ms.
