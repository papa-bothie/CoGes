"""Module Analytics — bande E, restitution.

Lecture seule, et **composition seulement** : Analytics n'a ni table, ni modèle,
ni repository. Elle interroge les façades de Sales, Finance, Expenses et Companies,
et met leurs chiffres côte à côte.

C'est le seul sens que l'ordre des dépendances autorise. Sales, qui est au-dessus
de Finance, ne peut pas être appelé par elle ; un module de restitution, lui, est
au-dessus de tout le monde et peut appeler tout le monde.

Phase 07 : les chiffres sont calculés directement sur le transactionnel. Phase 08 :
la même réponse, lue sur `daily_sales_facts`. L'endpoint ne bouge pas, et l'écart
entre les deux sources devient le test T32.
"""
