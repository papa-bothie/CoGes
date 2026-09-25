# 0033 — Les huit métriques produit : calculées à la lecture, et jamais fusionnées

- **Date** : 2026-09-25
- **Phase** : 08
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`, questions 5 et 6 du prompt de phase)

## Contexte

Le Diagramme 7 de l'Architecture énumère huit métriques produit et pose une règle : elles ne sont
**jamais équivalentes**. Il n'existe pas de « meilleur produit » — il existe un produit qui génère
le plus de chiffre d'affaires, un autre qui tourne le plus vite, un troisième dont la demande
progresse, et ce ne sont pas les mêmes.

Restait à décider où elles se calculent, et comment se mesure la rotation du stock, qui est la
seule des huit à demander une information que la base ne garde nulle part : le stock détenu un
jour passé.

## Décision 1 — Sept métriques calculées à la lecture, la huitième renvoyée à la phase 09

Les métriques 1 à 7 se calculent **à la lecture**, sur `daily_sales_facts` et le journal de stock,
avec les index de la révision 0010 et le cache court de l'ADR 0032. Elles restent sous les 200 ms
parce que `daily_sales_facts` est déjà agrégé par jour et par produit : la lecture parcourt des
dizaines de lignes, pas des milliers.

    revenue       net_revenue de la période                         XOF
    margin        net_revenue − cogs_net                            XOF
    quantity      net_qty_sold                                      unité
    frequency     nombre de ventes contenant le produit             vente
    rotation      net_qty_sold ÷ stock moyen détenu                 fois
    velocity      net_qty_sold ÷ nombre de jours de la période      unité/jour
    demand_trend  variation de vélocité entre les deux moitiés      %

Une table de métriques précalculée chaque nuit était l'autre option. Elle aurait ajouté une
projection de plus à reconstruire, à réconcilier et à purger — pour éviter un calcul qui tient
déjà dans le budget. Le jour où il n'y tiendra plus, `daily_sales_facts` sera toujours la source,
et rien de ce qui est écrit ici ne sera à défaire.

La métrique 8, **`future_potential`**, vient d'un modèle de prévision qui n'existe pas encore. Elle
répond 200 avec `items: []` et un `unavailable_reason` qui annonce la phase 09, plutôt que
d'inventer un nombre. « Données insuffisantes » est une réponse ; une valeur fabriquée n'en est
pas une.

## Décision 2 — Le stock moyen est reconstitué, pas approché

La rotation rapporte la quantité écoulée au **stock moyen détenu** sur la période. Le stock d'un
jour passé n'est stocké nulle part — `product_stock` est une projection de l'état **courant** —
il faut donc le rejouer depuis `inventory_movements` : état à la veille du premier jour, puis
somme cumulée fenêtrée des variations, une valeur de fin de journée par jour.

L'approximation `(stock début + stock fin) / 2` était l'autre option, et elle se trompe là où la
question se pose : un article écoulé à zéro puis réapprovisionné en fin de période affiche un
stock moyen élevé et une rotation faible, alors que c'est l'inverse qui s'est produit.

Les jours sans mouvement **figurent** dans la série (`generate_series` et `CROSS JOIN`). Sans
eux, un article immobile vingt jours puis écoulé en un jour aurait le même stock moyen qu'un
article en rotation constante : la moyenne porterait sur les jours où il s'est passé quelque
chose, c'est-à-dire sur une autre question.

Le découpage en journées se fait dans le **fuseau de l'entreprise**, comme `daily_sales_facts.day`.

## Décision 3 — Ce qu'une métrique ne mesure pas, elle l'écarte

Un produit dont le **stock moyen est nul** est retiré du classement de rotation, pas rendu à zéro.
Sa rotation n'est pas faible, elle est indéfinie — et un zéro le ferait passer pour le pire du
catalogue, ce qui est une affirmation, et elle serait fausse.

Même règle pour `demand_trend` : un produit absent de la première moitié de la période n'a pas de
progression **mesurable**. Une variation par rapport à zéro est infinie, pas forte. Une période
d'un seul jour n'ayant pas deux moitiés, le classement est alors vide.

## Conséquences

- `GET /api/v1/analytics/products` impose `metric`, et rend `metric`, `metric_label` et `unit`.
  L'unité compte autant que le libellé : une vélocité en unités par jour lue comme des francs se
  compare à un chiffre d'affaires, et la comparaison est absurde.
- Aucun score composite, nulle part. Un test parcourt les huit valeurs de l'énumération et vérifie
  que chacune se nomme dans sa réponse ; d'autres vérifient que revenue, quantity et rotation
  classent délibérément les mêmes produits dans des ordres différents.
- Inventory expose `average_on_hand()` : aucun module ne lit `inventory_movements` directement, et
  Analytics ne fait pas exception.
- `analytics:read` appartient au gérant et au comptable, pas au vendeur. Une caisse encaisse ;
  elle n'a pas à lire la marge de l'entreprise.
- La phase 09 remplira `future_potential` depuis `forecasts` sans changer le contrat de la route :
  seul `unavailable_reason` disparaîtra.
