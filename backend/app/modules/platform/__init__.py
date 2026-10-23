"""Administration de la plateforme (ADR 0089).

Un axe à part, pas une sixième bande sous la Restitution : ce module n'importe aucun
module métier et aucun module métier ne l'importe (test d'architecture). Il ne parle
qu'à `coges_app_platform`, qui ne lit que des métadonnées d'entreprise — jamais une
vente, un stock, un paiement ou un article.
"""
