# Phase 06 — Retours clients et remboursements

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 06 : retours et
remboursements** (module Sales, avec la façade Finance). Un retour est un **fait métier
autonome** (pas l'annulation d'un mouvement) : la marchandise revient au coût auquel elle était
sortie, et le remboursement est tracé et plafonné par la base.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 05 ✅ exigée) et les ADR, en particulier ceux de la phase 05.
2. Lis :
   - Modèle : § 4.6 (retours, absence d'avoir), § 4.7 (`sale_return_items`, `sale_return_refunds`),
     § 4.9 (`payments.sale_return_id`, CHECK de sens) ; § 5.3 (retour) et § 5.4
     (remboursement) ; SQL § 8.4 (`sale_returns`, `sale_return_items`), § 8.6
     (`sale_return_refunds`), § 8.7 (`return_item_check`, `return_recompute`,
     `return_refund_status_set`, `refund_check`, `refund_rollup`) ; § 10 tests **T18–T22**.
   - Architecture : audit critique (annulation ou retour de vente) ; événements `sale.returned` et
     `sale_return.refunded`.
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Enregistrer un retour partiel ou total sur une vente confirmée, remettre la marchandise en stock
au coût de sortie, calculer le remboursable TTC aux prix et taux historiques, et le régler selon le
choix du gérant (remboursement en trésorerie, extinction d'une dette ou rien), sans double
remboursement possible.

## 2. Questions à me poser (AskUserQuestion)

1. **Extinction d'une dette par un retour** : le § 4.6 le prévoit « via `payment_allocations` »,
   mais une allocation exige un paiement, et un paiement lié à un retour doit être un `outflow`.
   Le modèle ne dit pas comment représenter cette compensation sans flux de caisse. Options :
   (a) ajouter la méthode `offset` (compensation) à `pay_method`, puis créer dans la même
   transaction un `outflow` lié au retour (via `sale_return_refunds`) et un `inflow` alloué à la
   dette, tous deux en `offset` et exclus de la trésorerie (Recommandé : les deux lettrages restent
   exacts et la trésorerie n'est pas faussée) ;
   (b) V1 limitée au remboursement en trésorerie ou à `none_due`, compensation reportée ;
   (c) autre proposition, à documenter.
   C'est une **modification du schéma** : elle exige un ADR validé.
2. **Numérotation des retours** : `R-000123`, même mécanisme que `sale_no` (Recommandé) / autre.
3. **Règlement choisi à la création du retour ou plus tard** : les deux ; le retour naît en
   `pending` et peut être remboursé en une ou plusieurs fois (Recommandé : le modèle le permet) /
   obligatoirement à la création.
4. **Qui peut faire un retour et rembourser** : gérant seulement (Recommandé) / gérant et vendeur,
   remboursement réservé au gérant / selon la matrice RBAC existante.
5. **Délai maximal de retour** après la vente : aucun en V1 (Recommandé : rien ne l'impose) /
   paramètre d'entreprise.

## 3. Périmètre

**Migration `0006_returns`** (si la phase 05 n'a pas déjà créé ces tables) et, selon la réponse 1,
la modification de `pay_method` (réversible, avec un ADR).

**Service et endpoints**
- `POST /api/v1/sales/{id}/returns` : lignes (`sale_item_id`, `qty`), motif ; une transaction :
  vente `confirmed` exigée ; `returned_at >= sold_at` ; quantité ≤ vendue − déjà retournée (le
  trigger le garantit sous verrou) ; `refund_amount` et `tax_refund` calculés aux prix et taux
  historiques (formule du § 4.7) ; `unit_cost` recopié de `sale_items.unit_cost` ; mouvement
  `customer_return_in` **sans** `reversal_of_movement_id`, `ref_type = 'sale_return_item'`, via la
  façade Inventory ; audit critique ; outbox `sale.returned`.
- `POST /api/v1/sale-returns/{id}/refunds` (montant, méthode) : `FOR UPDATE` sur le retour ;
  `payments` (`outflow`, `sale_return_id`) + `sale_return_refunds` ; les triggers refusent tout
  dépassement ; `refunded_total` et `refund_status` recalculés ; audit critique ; outbox
  `sale_return.refunded`.
- Compensation d'une dette selon la réponse 1.
- `GET /api/v1/sales/{id}/returns`, `GET /api/v1/sale-returns/{id}` (lignes, remboursements),
  `GET /api/v1/payments/{id}/refunded-returns` (traçabilité inverse).
- La réponse de la vente expose `has_returns` et le total retourné (statut « retournée » dérivé).

**Tests**
- **T18** ligne de 10 retournée 3, 4 puis 4 ⇒ le 3ᵉ retour échoue ; **T19** vente au CMP 15, CMP
  passé à 20, retour ⇒ entrée à 15 ; **T20** retour de 1 000 remboursé 600 puis 500 ⇒ le second
  échoue, statut `partial` ; **T21** `inflow` avec `sale_return_id` ⇒ violation du CHECK ; **T22**
  requêtes croisées retour → paiement et paiement → retour ⇒ réponse unique dans les deux sens.
- Retour sur une vente brouillon ou annulée ⇒ refus ; remboursement d'un montant ≤ 0 ⇒ refus.
- Compensation (réponse 1) : dette diminuée, trésorerie inchangée, `refund_status = settled`.
- Harnais de fuite et T5 étendus (`sale_return_refunds` → paiement d'un autre tenant).

**Hors périmètre** : avoirs clients, solde créditeur, retours fournisseurs (déjà couverts par le
mouvement `supplier_return_out` de la phase 04).

## 4. Règles à respecter

- Aucune table `credit_notes`, aucun solde créditeur client (hors V1, § 4.6).
- Le montant d'un paiement n'est jamais négatif : c'est `direction` qui donne le sens.
- Les calculs de remboursement se font sur les **snapshots** de la ligne, jamais sur le prix du jour.

## 5. Vérification

`make test` vert ; scénario : vente de 10 à 18 % de TVA → retour de 3 → remboursement de 60 %,
puis du solde → tentative de sur-remboursement refusée → stock et CMP vérifiés.

## 6. Clôture

ADR (compensation, numérotation, droits) ; `CLAUDE.md` mis à jour ; résumé.
