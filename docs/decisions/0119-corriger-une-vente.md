# 0119 — Corriger une vente : annuler et refaire pendant 10 minutes

- **Date** : 2026-11-11
- **Phase** : groupe 5, bloc R (prompt 36 `36-groupe-5-corriger-une-vente-notifications-photos.md`,
  branche `phase/36-r-corriger-une-vente`)
- **Statut** : acceptée (complète 0023, 0038, 0062 et 0088 ; écart assumé au § 5.2)
- **Décideur** : propriétaire (délai de 10 minutes et « toute personne qui peut vendre »,
  11 novembre 2026, dans le prompt) ; plan validé par l'utilisateur avant le code

## Contexte
Une vente encaissée par erreur (mauvaise quantité, mauvais article, mauvais moyen) ne se
corrigeait que de deux façons : un retour (lourd, réservé au gérant pour l'argent, ADR 0025)
ou une annulation, que le § 5.2 refuse dès qu'un encaissement existe (ADR 0023). Le vendeur,
qui fait l'erreur, n'avait aucun geste. Le propriétaire veut « Annuler et refaire » pendant
10 minutes, par toute personne qui peut vendre, sans donner le droit général d'annuler.

## Options envisagées
1. **Un geste dédié, une transaction (retenue)** : `POST /api/v1/sales/{id}/correct`
   contre-passe les encaissements de la confirmation, annule la vente et ouvre un brouillon
   identique relié à elle.
2. Ouvrir l'annulation au vendeur pendant 10 minutes : donnerait `sales:cancel` en partie,
   et laisserait la personne refaire la vente à la main, sans lien entre les deux.
3. Modifier la vente confirmée en place : impossible sans casser les snapshots figés
   (`sale_items_frozen`, ADR 0023) et le journal append-only du stock.

## Décision
**Délai** : `CORRECTION_WINDOW = 10 min` (`app/modules/sales/service.py`), compté depuis
`confirmed_at` à l'heure **réelle** du serveur (`_correction_now()`, pas `clock.now()` :
`confirmed_at` est écrit à l'heure réelle, une heure figée de l'ADR 0065 fausserait le
calcul). Le serveur rend `correction_seconds_left` sur chaque vente ; l'écran décompte à
partir de ce nombre et du moment de la réponse, jamais de l'heure du téléphone.

**Droits** : `sales:create` **et** `sales:confirm` (`require_permissions`). Le comptable est
refusé (403). `sales:cancel` reste au gérant, à tout moment, avec ses règles actuelles.

**Refus (409)**, vérifiés après les verrous :
| Code | Quand |
|---|---|
| `sale_already_corrected` | un brouillon la corrige déjà ; `details.draft_id` et `draft_sale_no` mènent à lui |
| `sale_already_cancelled`, `sale_not_confirmed` | brouillon ou vente annulée |
| `correction_window_closed` | plus de 10 minutes |
| `sale_has_returns` | un retour existe : « faites plutôt un retour » |
| `sale_paid_after_confirmation` | la dette de la vente a bougé depuis la confirmation : règlement lettré, compensation ou abandon (`finance_service.sale_debt_moved`) |

**Le geste**, en une transaction :
1. verrous : dette de la vente, puis vente (ordre de l'annulation, ADR 0062 et 0088) ;
2. les encaissements directs vivants de la vente — depuis l'ADR 0087, ce sont exactement
   ceux de la confirmation — sont contre-passés par `cancel_payment` (ADR 0038), motif
   « Corrigée » : audit critique et `payment.cancelled` comme toute annulation de paiement ;
3. un brouillon est ouvert : même client, mêmes lignes ; un prix changé à la caisse et son
   motif sont repris (ADR 0107), une ligne au prix de la fiche suit la fiche du moment ;
   les remises sont reprises ; `sales.corrects_sale_id` le relie à la vente ; son numéro
   est attribué tout de suite, comme à tout brouillon (ADR 0021) ;
4. la vente est annulée par la logique commune avec `cancel_sale` (`_cancel_confirmed` :
   mouvements inverses, dette éteinte par `write_off_sale_debt`, statut, audit critique,
   `sale.cancelled`), motif « Corrigée ». L'audit de l'annulation porte
   `after.correction = {draft_id, draft_sale_no}` ; `sale.cancelled` gagne `corrected` et
   `corrected_by_user_id` (champs ajoutés seulement dans ce cas, aucun type d'événement
   nouveau).

Le brouillon est rendu ; l'écran l'ouvre (`/sales/{id}/edit`). Réencaissé, il devient une
vente ordinaire. Abandonné, il reste dans « Nouvelle vente » et l'ancienne vente reste
annulée : l'écran le dit avant le geste.

**Données** (révision 0040, ajout seul) : `sales.corrects_sale_id`, clé étrangère composite
vers `sales`, index unique partiel `sales_corrects_sale_uq` (une vente n'est corrigée
qu'une fois, même si deux personnes passent le contrôle applicatif ensemble), `CHECK`
`corrects_sale_id <> id`.

**Caisse** : rien ne change dans les totaux. Le paiement d'origine et sa contre-écriture
sortent des totaux (ADR 0038) ; seul le nouvel encaissement compte. Le journal de caisse
(`/analytics/cash`) gagne `correction` : vrai sur la contre-écriture d'une vente corrigée
et sur l'encaissement direct de la vente qui la remplace, déduit à la lecture (aucune
colonne sur `payments`). L'encaissement d'origine reste barré, sans marque : il était
ordinaire.

**Traçabilité** : `SaleRead` gagne `corrects_sale` et `corrected_by_sale` (`id`, `sale_no`,
`status`). L'ancienne vente affiche « Corrigée — remplacée par la vente n° 43 » ou « en
cours de correction » tant que le brouillon n'est pas encaissé ; le brouillon rappelle la
vente qu'il corrige. `ReceiptRead.corrected` : ses PDF portent « VENTE ANNULÉE —
corrigée ». L'alerte `sale_cancelled` existante dit « Corrigée par {nom} » au lieu de la
raison : une correction n'est jamais silencieuse.

**Double appui** : `Idempotency-Key` obligatoire, endpoint enregistré avec l'identifiant de
la vente (ADR 0039).

**Écart assumé au § 5.2** : une vente encaissée s'annule ici, parce que l'encaissement est
contre-passé dans la même transaction. La trésorerie revient exactement à ce qu'elle était
avant la vente ; aucun argent ne sort.

## Conséquences
- Interblocage possible et sans dommage : le geste verrouille la vente avant les paiements,
  alors qu'une annulation de paiement lancée au même instant par le gérant verrouille le
  paiement avant la vente (trigger `payment_reversal_rollup`). PostgreSQL en sacrifie un,
  traduit en 409 `concurrent_update` (ADR 0088) ; l'autre réussit. Rien n'est faussé.
- Un article supprimé ou sans prix entre la vente et la correction fait refuser le geste
  (`assert_sellable`) : faire un retour. Un client supprimé reste sur le brouillon.
- Pas de contrôle de stock à l'ouverture du brouillon : le stock de la vente annulée lui
  revient dans la même transaction, et la confirmation contrôle (ADR 0109).
- La vente qui corrige peut à son tour être corrigée dans ses propres 10 minutes.
- Tests : `tests/integration/test_sale_correction.py` (caisse et stock exacts après la
  correction puis après le réencaissement, délai à l'horloge figée, payée en partie, à
  crédit, prix changé, retour, dette réglée après, vente annulée, vendeur sur la vente d'un
  collègue, vendeur toujours sans annulation, comptable, autre entreprise, double appui,
  deux personnes en même temps, audit, événements, alerte) ;
  `test_receipt_pdf.py::test_a_corrected_sale_says_so_on_both_documents` ; registres
  (`commit_failure_registry.py`, `CROSS_TENANT_ROUTES`) ; Vitest `correct-sale.test.tsx` ;
  e2e `sale-correction.spec.ts` (vendeur à 360 px, axe).
