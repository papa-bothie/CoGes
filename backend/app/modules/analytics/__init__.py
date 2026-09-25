"""Module Analytics — bande E, restitution.

Lecture seule, et **une seule table** : `daily_sales_facts`, la projection du § 4.10.
Tout le reste est de la composition — Analytics interroge les façades de Sales,
Finance, Expenses, Inventory et Companies, et met leurs chiffres côte à côte.

C'est le seul sens que l'ordre des dépendances autorise. Sales, qui est au-dessus de
Finance, ne peut pas être appelé par elle ; un module de restitution, lui, est au-dessus
de tout le monde et peut appeler tout le monde.

**Écart assumé par rapport à l'ADR 0030**, qui écrivait « ni table, ni modèle, ni
repository ». Les faits sont la projection d'Analytics et le Diagramme 3 les lui
attribue (« agrégats essentiels, vues matérialisées »). La règle qui compte n'a pas
bougé : aucun module de bande inférieure ne lit cette table, et rien de ce qu'elle
contient n'est une décision — elle est intégralement reconstruisible.

Phase 07 : les chiffres étaient calculés directement sur le transactionnel.
Phase 08 : la même réponse, lue sur les agrégats. L'endpoint n'a pas bougé, et
l'écart entre les deux sources est devenu le test **T32**.
"""
