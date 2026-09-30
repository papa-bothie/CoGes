# 0052 — Écrans opérationnels côté front : parcours de vente, stock et référentiels

- **Date** : 2026-09-30
- **Phase** : 12
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

La phase 12 branche sur l'API les écrans quotidiens du prototype : tableau de bord, ventes,
retours, stock, produits, catégories, clients, fournisseurs. Le prompt de phase laissait cinq
choix ouverts, et l'API a révélé en route un parcours de retour sans aperçu serveur.

## Décisions

1. **Brouillon côté serveur** : `POST /sales` au premier article, chaque ligne synchronisée
   (`POST/PATCH/DELETE /sales/{id}/items`), l'URL devient `/sales/{id}/edit` sans remonter
   l'éditeur (`history.replaceState`). Un rechargement reprend le brouillon.
2. **Totaux du serveur** : sous-total, remises, taxes et total sont ceux de `SaleDetail`, avec
   un indicateur « Mise à jour… ». Le front ne calcule aucun montant.
3. **Reçu** : `/sales/{id}/receipt`, ticket 80 mm (par défaut) ou A4, règle `@page` adaptée,
   coquille masquée à l'impression.
4. **Stock insuffisant** : confirmation désactivée quand le stock affiché est inférieur à la
   quantité (comparaison décimale sans `float`), et l'erreur `insufficient_stock` du serveur
   s'affiche sur la ligne concernée (`details.product_id`, `details.available`).
5. **Retour en deux temps** : saisie des lignes et quantités (plafonnées à `qty − returned_qty`),
   puis écran du retour avec le montant remboursable **calculé par le serveur** et les
   règlements successifs (trésorerie, ou compensation si la vente porte une dette ouverte).
6. **Ordre** : navigation, une capture par écran validée avant le suivant.

Règles transverses appliquées :

- `Idempotency-Key` créée à l'ouverture du formulaire, **gardée jusqu'au succès** (un refus
  métier annule la clé côté serveur, ADR 0027), renouvelée ensuite : confirmation, retour,
  remboursement, mouvement de stock.
- Aucune mise à jour optimiste sur le stock ou l'argent : invalidation après la réponse.
- Quantités et montants reçus en chaîne ; comparaisons, soustraction d'affichage, pourcentage
  ↔ taux par manipulation décimale (`lib/decimal.ts`), jamais par `number`.
- Masquage par permission (`<Can>`) : Dettes et Charges absentes pour qui n'a pas le droit de
  lecture ; le serveur revérifie.

## Écarts restants par rapport au prototype

| Écart | Raison |
|---|---|
| Pas de courbe des ventes récentes sur la fiche produit | Aucune série par produit dans l'API ; relève d'Analytics (phase 13) |
| Pas de total de l'encours d'un client | Non servi par l'API ; le sommer dans le front serait une règle métier |
| Bandeaux d'alerte menant à l'écran, pas à l'élément | `ActiveAlert` ne porte pas l'identifiant de l'entité |
| Écran Stock sans recherche ni filtre par statut | `/inventory/stock` n'expose que `product_id` ; ruptures en tête par l'API |
| Pas de suppression de produit, client ou fournisseur | Désactivation du produit par la case « actif » ; suppressions logiques renvoyées à une phase ultérieure |
| Pas d'aperçu du remboursable avant d'enregistrer un retour | Choix du retour en deux temps (décision 5) |
| Police, densité, polish visuel | Phase 14 (Impeccable) |

## Conséquences

- Composants partagés : `SearchCombobox`, `MovementDialog` (Stock et fiche produit),
  `DebtsCard` (fiches client et fournisseur), `Money`, badges de statut, `ErrorState`.
- Parcours Playwright : vente partielle et reçu, survente bloquée, retour et remboursement,
  ajustement avec motif et correction, produits et catégories, clients, fournisseurs.
- Captures de référence : `docs/design/captures/phase-12/`.
