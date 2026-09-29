# 0050 — Enrichissements de lecture pour le frontend

- **Date** : 2026-09-29
- **Phase** : 12
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

Les écrans opérationnels de la phase 12 ont besoin d'informations que l'API ne servait pas :

- une ligne de vente (`SaleItemRead`) ne portait que `product_id` : ni nom ni SKU à afficher
  dans l'éditeur de vente et le détail (le reçu les relit, mais il est refusé sur un brouillon,
  ADR 0022) ;
- la liste des ventes (`SaleRead`) ne portait que `customer_id` ;
- rien ne disait combien d'unités d'une ligne étaient déjà revenues : le formulaire de retour
  doit plafonner la saisie à ce qui reste retournable (le trigger `sri_check` refuse de toute
  façon l'excès) ;
- `GET /inventory/stock` n'avait aucun filtre : la liste des produits (qui vient de
  `/products`, ADR 0012) et la saisie d'une vente ne pouvaient pas lire le stock des seuls
  articles affichés ;
- `GET /debts` ne filtrait pas par tiers : la fiche client ne pouvait pas lister ses dettes.

## Options envisagées

1. **Enrichir les réponses et ajouter des filtres de lecture (retenue)** : quelques champs et
   paramètres, sans migration ni écriture, en respectant le sens des dépendances.
2. Tout reconstituer dans le front : un appel par ligne (N+1) et un cumul des retours calculé
   côté client — une règle métier hors du serveur.

## Décision

- `SaleItemRead` gagne `product_name`, `sku` (relus par la façade Products, `None` si le produit
  a été supprimé logiquement) et `returned_qty` (somme des `sale_return_items` de la ligne).
  Réponses de `POST/PATCH /sales/{id}/items` comprises.
- `SaleRead` (donc `SaleDetail`) gagne `customer_name` (façade `customers_service.names_by_ids`,
  en lot pour une page).
- `GET /inventory/stock` accepte `product_id` répété, au plus 100 : un article sans aucun
  mouvement n'a pas de ligne, le front affiche « — ».
- `GET /debts` accepte `customer_id` et `supplier_id`.

Ce sont des libellés et des cumuls de lecture : aucun ne porte de montant nouveau ni de règle.

## Conséquences

- `openapi.json` et `frontend/types/api.ts` régénérés ; les champs sont **requis** en sortie.
- Deux requêtes par lot (produits, retours) au lieu d'une par ligne.
- Tests : `tests/integration/test_front_read_enrichments.py` et
  `tests/tenancy/test_read_filters_cross_tenant.py` (un identifiant d'une autre entreprise passé
  en filtre ne renvoie rien).
