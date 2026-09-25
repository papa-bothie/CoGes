"""Modèles versionnés de CoGes Intelligence (étape 05 du Diagramme 7).

Le dossier s'appelle `estimators/` et non `models/` comme au Diagramme 10 : le
gabarit de module (ADR 0010) réserve `models.py` aux tables, et les deux ne peuvent
pas coexister (ADR 0037).

Les calculs internes sont en flottants — ce sont des estimations statistiques, pas
des montants. Tout ce qui sort vers la base repasse en `Decimal` arrondi.
"""

#: Intervalle de prédiction à 80 % : quantile de la loi normale.
Z_80 = 1.2816
