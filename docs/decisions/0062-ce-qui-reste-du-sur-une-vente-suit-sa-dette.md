# 0062 — Ce qui reste dû sur une vente suit sa dette

- **Date** : 2026-10-07
- **Phase** : 15 (lot 0, bug B2)
- **Statut** : acceptée — amende l'ADR 0024 sur le sens de `paid_total`
- **Décideur** : utilisateur (prompt de phase 15 ; compensation et badge d'abandon tranchés via AskUserQuestion)

## Contexte
`sales.paid_total` était tenu par `sale_paid_rollup` (révisions 0006 puis 0012), qui ne
sommait que les paiements portant `sale_id`. Un règlement de dette passe par
`payment_allocations` sur la dette (`debts.sale_id`), sans `sale_id` sur le paiement. La
dette se soldait, mais `balance = total − paid_total` ne bougeait jamais : la vente restait
« Reste dû ».

L'ADR 0024 avait voulu que `paid_total` reste « ce qui est encaissé ». La compensation
d'une dette par un retour (`offset`) n'y entrait donc pas, ce qui produisait le même
écart sur une vente avec retour.

## Options envisagées
1. **`paid_total` = encaissé direct + lettré sur la dette, compensation comprise
   (retenue).** Pour toute vente qui porte une dette, `total − paid_total = debts.balance`.
2. `paid_total` reste l'argent seul et le reste dû est lu sur la dette. Deux notions
   cohabitent, et l'égalité ne tient plus pour une vente avec retour.

## Décision
- **Révision 0014.** `sale_paid_recompute` somme les paiements directs vivants (`inflow`,
  `sale_id`) et les lettrages vivants sur les dettes de la vente, `offset` compris.
- **Le trigger `pa_sale_rollup`** sur `payment_allocations` (insertion, mise à jour,
  suppression) recalcule la vente de la dette touchée.
- **`payment_reversal_rollup`** verrouille puis recalcule aussi les ventes des dettes
  lettrées par le paiement annulé. Les verrous sont pris dans l'ordre des identifiants
  (ADR 0039).
- **Rattrapage dans la migration**, puis contrôle bloquant : aucune vente avec dette ne
  peut avoir `total − paid_total ≠ debts.balance`. Les dettes abandonnées sont exclues,
  leur solde est gelé.
- **Ordre des verrous : la dette, puis la vente.** Un règlement y conduit naturellement
  (`pa_check` puis `pa_sale_rollup`). L'annulation d'une vente verrouille donc désormais
  sa dette avant elle (`finance_service.lock_sale_debt`), sans quoi les deux
  s'interbloqueraient. Ce verrou ferme aussi un trou ancien : l'abandon de la dette
  relisait un `amount_paid` non verrouillé.
- **Pas de double comptage.** L'acompte encaissé à la confirmation porte `sale_id` et n'est
  jamais lettré, et la dette ne porte que le solde.
- **Lecture.** `SaleRead.debt_status` (additif) distingue une dette abandonnée. Le front
  affiche un badge : « Payé » en vert, « Reste X » en orange, ou « Dette abandonnée » en
  gris (écart noté dans `docs/design/maquette-v2/ecarts.md`). Ce badge remplace les
  colonnes « Payé » et « Reste dû » de la liste des ventes.

## Conséquences
- `paid_total` veut dire **« réglé »**, et non plus « encaissé ». La trésorerie ne change
  pas : elle exclut toujours `method = 'offset'` et les paiements annulés.
- `has_settled_payment` (refus d'annuler une vente encaissée) compte toujours les seuls
  paiements directs. Une dette partiellement réglée bloque déjà l'annulation par
  `DebtPartiallyPaidError`.
- Tests : `test_sale_paid_follows_debt.py` (règlement partiel puis complet, annulation,
  deux dettes pour un paiement, acompte, compensation, abandon). Le test de compensation
  de `test_returns_api.py` est mis à jour. La migration est rejouée `downgrade base` puis
  `upgrade head` à chaque exécution de la suite.
