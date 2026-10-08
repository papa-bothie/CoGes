# 0068 — Wave et Orange Money

- **Date** : 2026-10-08
- **Phase** : 15 (lot 1)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-08)

## Contexte
Le prompt de phase 15 demande s'il faut distinguer Wave et Orange Money au lieu d'un seul
« Mobile money ». La maquette v2 les nomme partout (caisse, dépenses, règlements).

## Options envisagées
1. **Deux valeurs de `pay_method`, `wave` et `orange_money` (retenue).**
2. Une colonne `provider` à côté de `mobile_money` : deux champs à lire partout.
3. Garder « Mobile money » : le commerçant ne sait pas quel opérateur a encaissé.

## Décision
- Révision 0015 : `ALTER TYPE pay_method ADD VALUE 'wave'`, puis `'orange_money'`.
  `mobile_money` reste valable pour les paiements d'avant, l'API et les imports ; le front
  ne le propose plus.
- Aucun rapport du serveur ne ventile par moyen de paiement : rien à regrouper côté API.
  Le front affiche « Wave », « Orange Money », et « Mobile money » pour les anciens.
- La descente de la révision ramène Wave et Orange Money à `mobile_money` et recrée le type
  (une valeur d'ENUM ne se retire pas).
- Le seed `maquette` reprend les opérateurs des captures (loyer et eau par Wave, crédit
  internet par Orange Money…).

## Conséquences
- Les ADR suivants du prompt de phase 15 décalent encore d'un rang : la refonte visuelle
  devient 0069.
- Tests : `test_mobile_money_operators.py`.
