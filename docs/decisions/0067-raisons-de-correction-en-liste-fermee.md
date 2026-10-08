# 0067 — Raisons de correction du stock en liste fermée

- **Date** : 2026-10-08
- **Phase** : 15 (lot 1)
- **Statut** : acceptée
- **Décideur** : utilisateur (prompt de phase 15, lot 1 ; plan validé le 2026-10-08)

## Contexte
Un ajustement ou une perte exigeait un motif écrit (`TYPES_REQUIRING_NOTE`). Le commerçant
devait taper une phrase, et aucun rapport ne pouvait regrouper les pertes par cause.

## Options envisagées
1. **Une raison choisie dans une liste fermée, colonne `reason_code` (retenue).**
2. Garder la note libre et proposer des phrases toutes faites : aucun regroupement fiable.

## Décision
- **ENUM `stock_reason`** et colonne `inventory_movements.reason_code` (révision 0015) :
  - perte (`loss`) : `damaged` (abîmé ou cassé), `expired` (périmé), `lost_or_stolen`
    (perdu ou volé), `home_use` (pris pour la maison) ;
  - ajustement (`adjustment`) : `count_error` (erreur de comptage, dans les deux sens),
    `found` (retrouvé) et `supplier_gift` (cadeau du fournisseur), ces deux derniers
    toujours en plus.
- **Le type se déduit de la raison** : `type` peut être omis ; fourni et contraire, 422.
- **La raison est obligatoire** pour `adjustment` et `loss` à la saisie ; la note devient
  facultative. Le coût reste le CMP courant (ADR 0016), la date « maintenant ».
- **`inv_reason_coherent`** (CHECK) refuse en base une raison qui ne va pas avec le type
  ou le sens. La raison reste nulle sur les mouvements d'avant (motif écrit) et sur les
  inverses (ADR 0017).
- La raison entre dans l'audit critique du mouvement et dans `MovementRead`.

## Conséquences
- Le journal des mouvements affiche la raison en toutes lettres.
- Tests : `test_stock_reasons.py` (type déduit, raison obligatoire, refus incohérents, en
  API et en SQL, inverse, journal).
