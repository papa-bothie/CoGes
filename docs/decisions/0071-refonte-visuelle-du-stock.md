# 0071 — Refonte visuelle du stock : livraisons, niveau et rayons (lot 3b)

- **Date** : 2026-10-10
- **Phase** : 15 (lot 3b)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-09)

## Contexte
Le lot 3b reproduit les écrans de stock de la maquette v2 (07 Stock, 08 Fiche article,
09 Nouvel article, 10 Corriger le stock, 11 Recevoir une livraison, 12 Rayons). Plusieurs
éléments n'avaient pas d'appui dans le modèle ou l'API : une livraison qui fait entrer le
stock, crée la dette fournisseur et sort l'argent payé ; la barre de niveau de chaque
article ; la couleur d'un rayon ; le nombre d'articles par rayon ; la valeur du stock ;
l'historique d'un article en phrases. D'autres demandaient un choix : ce que fait
« Commander », où va le journal des mouvements, la couleur des carrés d'article.

## Options envisagées et décisions
- **Livraison en une seule transaction** (retenue) : `POST /api/v1/inventory/deliveries`
  (Inventory appelle la façade Finance, comme Sales) crée la dette fournisseur, une entrée
  `purchase_in` par article, référencée `('supplier_debt', debt_id)`, puis, si l'on paie
  tout ou une partie, une sortie de caisse lettrée sur la dette. Tout ou rien, sous
  `Idempotency-Key`, permissions `inventory:create` et `debts:create`. Plutôt que trois
  écritures enchaînées par le front, qui laisseraient un stock entré sans sa dette en cas
  d'échec. Aucun nouvel événement : `stock.updated` et `debt.created` suffisent.
- **Révision 0017** : `categories.color` (1 à 8, facultative), `ref_type` accepte
  `supplier_debt`, l'index d'idempotence des mouvements l'exclut, et un index unique
  `(company_id, ref_id, product_id)` interdit deux lignes du même article dans une
  livraison. `downgrade` détache les entrées de livraison (elles redeviennent des entrées
  sans référence) puis retire le reste.
- **« Commander »** sur une fiche ouvre la livraison avec l'article déjà ajouté (retenue) ;
  plutôt qu'une liste de courses ou un message au fournisseur, hors V1.
- **Niveau** = stock rapporté au plus haut stock atteint depuis 90 jours, rejoué du
  journal mouvement par mouvement, entre 0 et 1 (retenue) ; plutôt que rapporté au seuil d'alerte (illisible sans seuil) ou à un
  stock cible qui n'existe pas dans le modèle. L'épuisé a une barre vide, et la barre d'un
  article qui en a encore fait au moins 6 %.
- **Journal** : la liste de tous les mouvements reste, derrière le lien « Tous les
  mouvements » sous la liste du stock (`/inventory`), avec l'annulation par mouvement
  inverse (ADR 0017) et la saisie des mouvements rares (renvoi au fournisseur, stock de
  départ). La correction et la livraison ont leurs écrans (`/inventory/adjust`,
  `/inventory/receive`).
- **Couleur d'un rayon** : colonne facultative, choisie parmi huit à la création (retenue) ;
  sans couleur, le front la tire du nom. **Carrés d'article** : couleur tirée du nom, comme
  au lot F (ADR 0064), sans colonne.
- **Rayons** : on ajoute (nom et couleur), on renomme sur place, on supprime seulement un
  rayon vide (bouton grisé sinon, le serveur refuse aussi). Les sous-rayons déjà créés
  restent affichés sous leur parent avec leur chemin ; l'écran n'en crée plus, la maquette
  n'en montre pas.
- **Lectures ajoutées** : `GET /inventory/stock` filtrable par `status`, `category_id`,
  `search`, trié épuisés, bientôt épuisés puis par nom, avec `unit_price`, `level` et
  `is_stock_tracked` (les articles sans mouvement et non suivis apparaissent) ;
  `GET /inventory/stock/summary` (nombre d'articles, valeur au prix d'achat moyen, bientôt
  épuisés, épuisés) ; `GET /products/category-counts` ;
  `GET /analytics/products/{id}/history` (vendu ce mois, et les mouvements avec le client
  ou le fournisseur en face, pour des phrases comme « Vendu à Awa Diop »).
- **Seed `maquette`** : rayons colorés, livraison du Grossiste Sandaga passée par
  `receive_delivery` (payée en partie, échéance au 10 octobre).

## Conséquences
- Tests : `tests/integration/test_lot_3b_stock.py` (livraison payée tout de suite, en
  partie ou plus tard, refus sans stock entré, rejeu, niveau, filtres, résumé, historique), fuites entre
  entreprises sur les nouvelles lectures et la livraison, la livraison dans les écritures
  financières qui exigent une clé ; e2e de bout en bout (livraison payée en partie, rayons,
  correction depuis la fiche) ; test du commerçant : créer un article en ne tapant que le
  nom et deux prix, corriger 2 sacs abîmés en 5 touches sans frappe.
- La correction lit à part l'article venu de sa fiche, au-delà des 100 premiers.
- Repoussé : photo d'article (aucun stockage de fichiers en V1), bon de commande,
  livraison partielle d'une commande (pas de commandes en V1). Écarts à la maquette dans
  `docs/design/maquette-v2/ecarts.md`.
