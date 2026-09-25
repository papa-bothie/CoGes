"""Module Dashboard — bande E, restitution.

**Composition seulement** : ni table, ni modèle, ni repository. Il assemble les
indicateurs d'accueil à partir des façades d'Analytics, de Notifications, de Finance
et d'Inventory — c'est la place que le Diagramme 3 lui donne, « composition des KPI
d'accueil sur agrégats pré-calculés ».

Deux contraintes le façonnent :

* **cible < 200 ms.** Chaque chiffre vient d'un agrégat déjà construit ou d'un index
  ; aucune requête ne balaye des lignes de vente. Un cache court par tenant, invalidé
  par événement, absorbe les rafraîchissements répétés (décision 14).
* **`dashboard:read`**, que le vendeur possède aussi. L'écran d'accueil d'une caisse
  n'est donc pas celui d'un gérant : il ne porte aucune marge — celle-là demande
  `analytics:read` (ADR 0030).
"""
