"""Ventes : brouillon, confirmation, annulation, reçu.

Le cœur du cycle vente → stock → argent. La confirmation est la transaction de
référence de l'architecture (Diagramme 4, § 5.1) : une seule transaction, rollback
complet si une étape échoue.
"""
