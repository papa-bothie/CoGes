# 0107 — Prix changé sur une ligne de vente

- **Date** : 2026-11-03
- **Phase** : groupe 1, bloc P (prompt 34, branche `feat/group1-p-sale-price`)
- **Statut** : acceptée (écart assumé au § 5.1 étape 3 et au § 4.5 du modèle)
- **Décideur** : propriétaire (prix libre sans limite, dans le prompt) ; prix plus haut,
  modèle de la ligne via AskUserQuestion le 2026-11-03

## Contexte
Le propriétaire veut que toute personne qui vend puisse changer le prix d'une ligne au
moment de vendre, sans limite, sans toucher au prix de la fiche, et que la marge en tienne
compte.

Constat, prouvé par deux tests rouges (`tests/integration/test_sale_line_price.py`) :

1. `SaleItemUpdate` refusait tout `unit_price` (`extra="forbid"` ⇒ 422) : aucun prix ne
   pouvait être tapé par l'API.
2. Même écrit sur la ligne du brouillon (directement en base), le prix était **écrasé** à la
   confirmation : `confirm_sale` relisait le prix courant (`price.unit_price`) et le
   recopiait sur la ligne. Ligne à 1 200 sur une fiche à 1 500 ⇒ 1 500 après confirmation.

La remise existante (`discount`) est un montant pour **toute la ligne**, pas un prix : s'en
servir pour un prix plus bas obligerait à la recalculer à chaque changement de quantité, et
ne permettrait pas un prix plus haut.

## Options envisagées
1. **`unit_price` = prix appliqué, `list_price` = prix de la fiche (retenue)** : la révision
   0034 ajoute `sale_items.list_price numeric(14,2) NULL` (≥ 0) et `price_reason text NULL`
   (120 caractères). Toutes les colonnes générées (montant, taxe, total de ligne) et tout
   ce qui en dérive (totaux de la vente, dette, CA, marge, retours, événements) lisent déjà
   `unit_price` : rien d'autre ne change.
2. Prix plus bas = remise `(fiche − tapé) × quantité`, prix plus haut à part : deux
   mécanismes, remise à recalculer à chaque quantité, rapports de remises mêlés aux prix
   changés. Écartée.

## Décision
- **Ajout** : `list_price` est posé au prix de la fiche. **Changer** (`PATCH …/items/{id}`
  avec `unit_price`, `price_reason` facultatif) : plus bas, plus haut ou 0, jamais négatif
  (422), aucune limite, droit `sales:update` (celui de vendre), aucun droit nouveau.
  Remettre le prix de la fiche efface le motif (« Revenir au prix habituel »).
- **Confirmation** : la fiche est relue comme avant et refigée dans `list_price`. Une ligne
  dont `unit_price ≠ list_price` garde son prix ; une ligne non touchée suit la fiche du
  moment (le prix a pu changer depuis le brouillon). Une ligne d'avant la révision
  (`list_price NULL`) suit la fiche, comme avant. Un prix tapé égal au prix de la fiche
  n'est pas un changement.
- **Audit** : critique, **à la confirmation** seulement (un brouillon n'a aucun effet), une
  ligne `sale_items` / `update` par prix changé : `before.unit_price` = fiche,
  `after` = prix appliqué, fiche, motif, article, vente. L'historique le raconte :
  « Awa a changé le prix du Riz sur la vente n° 1044 : 2 500 FCFA → 2 000 FCFA (client
  fidèle) ».
- **Lecture** : `SaleItemRead` gagne `list_price`, `price_changed`, `price_reason`.
- **Écran** : le prix unitaire de la ligne du ticket est un bouton (crayon) qui ouvre le
  champ montant et le pavé du kit, « Prix habituel : 2 500 F », quatre motifs en puces
  (« Client fidèle », « Prix négocié », « Article abîmé », « Cadeau ») et un texte libre,
  jamais obligatoires ; à 0, une seconde confirmation (« Oui, l'offrir ») ; la ligne porte
  « Prix changé » ; le détail de la vente « Prix changé (habituel : 2 500 F) — motif ».
- **Reçu et facture** : ils montraient déjà `unit_price` de la ligne, donc le prix
  appliqué ; rien d'autre dans ce lot (groupe 2).

## Conséquences
- Écart au § 5.1 étape 3 (« prix relu et figé ») : le prix de la fiche reste relu et figé,
  dans `list_price` ; le prix payé peut en différer. Le docstring de `sales/schemas.py` le dit.
- `discount_total` et les rapports de remises ne comptent **que** les remises : un prix
  changé n'est pas une remise.
- Un retour rend ce qui a été payé (`unit_price` de la ligne), pas le prix de la fiche (test).
- Le brouillon de vente est côté serveur : le prix tapé survit au rechargement (e2e).
- Migration d'ajout seul, rétrocompatible (ADR 0083) : une API d'avant la révision ignore
  les deux colonnes.
