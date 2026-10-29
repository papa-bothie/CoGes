# 0097 — Retours : une vente confirmée se retourne, quel que soit son paiement

- **Date** : 2026-10-28
- **Phase** : prompt 28, bloc C1 (corrections du terrain)
- **Statut** : acceptée (amende l'ADR 0025 sur la compensation ; complète 0024 et 0062)
- **Décideur** : utilisateur (via AskUserQuestion : déduction immédiate, plafond de l'argent versé)

## Contexte
Le propriétaire a constaté que le retour d'un article était refusé ou impossible sur une vente
**payée en totalité** et sur une vente **payée en partie**, alors que la vente à crédit non payée
marchait, et que l'historique ne proposait le retour que pour certaines ventes.

## Ce qui a été reproduit
Matrice en test d'intégration (`backend/tests/integration/test_return_matrix.py`, 30 cas :
paiement × rôle × retour partiel ou total, articles non suivi et supprimé, second retour,
comptable, liste) puis en e2e (`frontend/e2e/returns.spec.ts`).

| Case | Avant | Cause | Après |
|---|---|---|---|
| Vente payée (espèces, Wave, client identifié ou non), gérant : retour + remboursement par l'API | ✅ non reproduit | — | ✅ |
| Vente payée, **vendeur** : l'écran tente le remboursement, refusé (403), message muet « l'argent n'a pas pu être réglé » | ❌ reproduit | `return-form.tsx` tentait le remboursement sans `sale_returns:confirm` et avalait l'erreur (`settled = false`) | ✅ rien n'est tenté ; « Le gérant doit encore rembourser X F », retour « À régler » côté gérant |
| Vente payée en partie : le mode « Déduire de sa dette » ne rendait jamais le surplus ; il fallait une seconde opération depuis la fiche du retour | ❌ reproduit | l'écran proposait **soit** la dette **soit** l'argent | ✅ dette déduite d'abord, surplus rendu (ou « plus tard ») dans le même écran |
| Vente payée en partie ou à crédit, **vendeur** : la dette ne baissait pas | ❌ reproduit | la compensation passait par `POST /sale-returns/{id}/refunds` (`sale_returns:confirm`) | ✅ déduite dans la transaction du retour (`offset_debt`) |
| Dette passée en perte, puis retour : l'API acceptait de rendre en argent la valeur des articles, au-delà de ce que le client avait versé | ❌ reproduit | seul CG041 (reste dû du retour) bornait le remboursement | ✅ `refund_exceeds_paid` (409) |
| Historique : aucun bouton « Retour » dans la liste | ❌ reproduit | `sales-list-view.tsx` n'en avait pas | ✅ « Retour » sur chaque vente confirmée qui a encore quelque chose à rendre |
| Article non suivi, article supprimé depuis la vente : retour et remboursement | ✅ non reproduit | — | ✅ (le stock d'un article supprimé rentre, lu en base) |
| Second retour après un retour partiel ; au-delà de la quantité vendue | ✅ non reproduit (CG040) | — | ✅ |
| Comptable : ni retour, ni remboursement | ✅ non reproduit (403) | — | ✅ inchangé |

## Décisions
1. **Déduction immédiate** (choix du propriétaire). `POST /api/v1/sales/{id}/returns` accepte
   `offset_debt: true` : dans la même transaction que le retour, la valeur rendue éteint d'abord
   la dette encore ouverte de la vente, au plus son solde (compensation de l'ADR 0024, deux
   paiements `offset`, aucune ligne de caisse). Elle est permise à qui porte
   `sale_returns:create`, vendeur compris : aucun argent ne sort. Le surplus en argent exige
   toujours `sale_returns:confirm` (gérant). La dette est verrouillée **avant** la vente, l'ordre
   de tout règlement (ADR 0062, 0088). Sans le champ (défaut `false`), rien ne change : les tests
   des ADR 0024 et 0025 restent valables tels quels. L'écran l'envoie toujours.
2. **Plafond de l'argent versé** (choix du propriétaire). Un remboursement en argent ne dépasse
   jamais ce que le client a réellement versé sur la vente (encaissement direct et lettrages sur
   sa dette, vrais mouvements de caisse seulement), moins ce qui a déjà été rendu sur ses retours :
   `RefundExceedsPaidError`, code `refund_exceeds_paid`, 409. CG041 reste l'autorité sur le reste
   dû du retour ; ce contrôle s'y ajoute (`finance.cash_left_to_refund`).
3. **Lecture** : `SaleRead.returnable` (liste et fiche), vrai pour une vente confirmée dont une
   ligne n'est pas entièrement retournée, calculé en une requête par page. La fiche et la liste
   suivent la même règle.
4. **Écran** : plus de choix « dette ou argent » ; la déduction s'affiche (« Il doit X sur cette
   vente : Y sont déduits de sa dette »), puis « Reste à lui rendre » avec « Lui rendre de
   l'argent » ou « Plus tard » pour qui peut rembourser, « Le gérant lui rendra X » pour les
   autres. Un remboursement refusé affiche la vraie raison du serveur (`errorMessage`).

## Conséquences
- `sale_return.refunded` est émis pour la compensation faite à la création, comme pour celle faite
  après coup (même code, `_settle_return`) : aucun nouveau type d'événement.
- T18 à T22 et les tests des ADR 0024, 0025 et 0062 passent sans modification (225 tests liés aux
  retours et remboursements).
- Ce que le propriétaire refait à la main : retour d'une vente payée en totalité, puis d'une vente
  payée en partie, avec le gérant puis avec un vendeur.

## Corrections
- **2026-10-29, prompt 32, bloc C (ADR 0103, révision 0032)** : après une dette abandonnée, la part
  d'un retour que le client n'a jamais versée est soldée sans argent (`waived_total`, audit) ; le
  retour ne reste plus « à régler » pour toujours. Annuler un encaissement est refusé s'il a déjà
  été rendu sur un retour (`CG054` ⇒ 409 `refund_exceeds_paid`). `returnable` ne lit plus que les
  lignes de la page.
