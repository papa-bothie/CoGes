# 0012 — La vue « produits + stock » appartient à Inventory

- **Date** : 2026-09-23
- **Phase** : 03
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le catalogue affiché en caisse montre le stock à côté du prix. Or `Products` est en bande B et
`Inventory` en bande C : les dépendances vont **vers le bas uniquement** (Diagramme 3). Products
ne peut donc pas lire `product_stock`.

## Décision

`GET /api/v1/products` ne renvoie **jamais** de stock. La vue jointe sera un endpoint de lecture
du module `inventory`, livré en phase 04 : Inventory a le droit d'appeler la façade de Products,
l'inverse est interdit.

## Conséquences

- La pagination et le tri par stock restent possibles côté serveur, dans Inventory, plutôt que
  d'être bricolés par le frontend sur deux appels.
- `products` n'aura jamais de colonne de stock : le stock est une projection de
  `inventory_movements`, reconstructible, et aucun code n'écrit `product_stock` à la main.
- `product_stock` n'est **pas** créée par la migration 0003 : sans le trigger qui l'alimente,
  elle laisserait croire qu'on peut l'écrire. Elle arrive avec le § 8.5, en phase 04.
