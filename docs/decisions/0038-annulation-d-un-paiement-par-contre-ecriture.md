# 0038 — Annuler un paiement erroné : la contre-écriture

- **Date** : 2026-09-25
- **Phase** : 10 (temps A)
- **Statut** : acceptée — tranche la décision 4 de l'ADR 0031
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Un caissier qui saisit 50 000 au lieu de 5 000 n'avait aucun recours : `payments` n'a ni statut
ni suppression logique (§ 8.6), `coges_app` n'a pas `DELETE`, et `payments:cancel` existait au
catalogue sans endpoint (ADR 0031, décision 4). Bloquant pour une mise en production.

La difficulté est dans les lettrages : `payment_allocations.amount > 0` interdit l'allocation
négative, et modifier ou supprimer les lignes d'origine effacerait l'histoire. Il faut pourtant
que la dette remonte, et avec elle `sales.paid_total` et `sale_returns.refunded_total`.

## Options envisagées

1. **Contre-écriture + « lettrages vivants » (retenue)** : une ligne `payments` d'annulation
   pointe l'origine par `reversal_of_payment_id` ; les rollups ne somment plus que les lettrages
   dont le paiement n'est pas annulé. Rien n'est modifié, rien n'est supprimé.
2. Lettrages miroirs : l'annulation porte ses propres allocations, soustraites par les rollups.
   Plus traçable ligne à ligne, mais `allocation_check` et `refund_check` à réécrire en profondeur
   (le solde d'une dette soldée est nul).
3. `cancelled_at` sur le paiement d'origine : modifie une écriture financière. Écarté.

## Décision

Révision **0012** et `POST /api/v1/payments/{id}/cancel`, calqués sur le mouvement de stock inverse
(ADR 0017).

| Sujet | Choix |
|---|---|
| Schéma | `payments.reversal_of_payment_id` (FK composite auto-référente), `cancel_reason` sur la ligne d'annulation ; `payments_reversal_uq` (une annulation au plus), `payments_reversal_shape` (ni contexte ni référence, motif obligatoire) |
| « Même montant, sens opposé » | Pas un `CHECK` (il ne lit qu'une ligne) : `payment_reversal_check` **réécrit** `amount`, `method`, `direction` depuis l'origine, comme `inv_check_reversal` |
| Soldes | `debt_rollup`, `refund_rollup`, `sale_paid_rollup` délèguent à `debt_recompute`, `refund_recompute`, `sale_paid_recompute`, qui ignorent les lettrages d'un paiement annulé. `payment_reversal_rollup` (AFTER INSERT) verrouille dettes, retours et vente **puis** recalcule dans des instructions distinctes |
| Trésorerie | Le paiement annulé **et** son annulation sortent des totaux (`_counts_as_cash()`), comme `offset` : la saisie erronée « n'a jamais eu lieu », y compris sur son jour d'origine |
| Périmètre | Tous les paiements (encaissements, décaissements fournisseur et de dépense, remboursements) ; une compensation `offset` s'annule **par paire** |
| Événement | **`payment.cancelled`**, dixième type de la liste fermée, abonné `analytics.invalidate_dashboard` |
| Droits | `payments:cancel` : gérant **et** comptable, comme la matrice de l'ADR 0007 le prévoyait déjà |
| Délai | Aucun ; motif obligatoire (10 à 500 caractères) |
| Correction | Annuler puis ressaisir, en deux appels ; `payments:update` reste sans route |
| Dette abandonnée | Refus : l'abandon a figé la dette, et `debt_rollup` ignore les dettes `written_off` |

SQLSTATE applicatifs :

| SQLSTATE | Fonction | Erreur métier |
|---|---|---|
| `CG051` | `payment_reversal_check` | `cannot_cancel_a_reversal` |
| `CG052` | `allocation_check`, `refund_check` | `payment_cancelled` |
| `CG053` | `payment_reversal_check` | `payment_debt_written_off` |
| `23505` sur `payments_reversal_uq` | — | `payment_already_cancelled` |

## Conséquences

- **Verrouiller avant de sommer.** Un `UPDATE … FROM (SELECT SUM …)` qui attend un verrou garde
  l'instantané pris avant l'attente et manquerait l'allocation d'un paiement concurrent. Le trigger
  d'annulation prend donc les verrous (`ORDER BY id`) dans une instruction, puis recalcule dans
  d'autres : en READ COMMITTED, chacune voit ce qui a été commité pendant l'attente. Testé sous
  concurrence dans les deux sens (`test_payment_cancellation_concurrency.py`).
- **La paire `offset` n'a pas de lien en base.** Ses deux moitiés sont retrouvées par ce qu'elles
  partagent : `method = 'offset'`, sens opposé, même montant, même `created_at` (horodatage de
  transaction), même auteur. Plus d'un candidat, ou aucun ⇒ `offset_pair_ambiguous` (409). La base,
  elle, ne sait pas qu'une paire existe : annuler une seule moitié en SQL direct reste possible.
- **L'audit ne photographie que Finance.** Paiement(s) et dettes avant / après, plus les lettrages
  de remboursement neutralisés. `paid_total` et `refunded_total` appartiennent à Sales, que Finance
  ne lit pas (ordre des dépendances) : ils se déduisent des lettrages audités.
- **Une vente dont l'encaissement est annulé redevient annulable** (§ 5.2) : `has_settled_payment`
  ignore les encaissements annulés.
- **Idempotence** : l'endpoint enregistré dans `idempotency_keys` inclut l'identifiant du paiement.
  La même clé présentée pour annuler un autre paiement est `idempotency_key_reused`, pas un rejeu.
  `confirm` et `refunds` utilisent encore un gabarit sans identifiant : même clé sur deux ventes
  différentes ⇒ rejeu de la première réponse. Signalé, non corrigé ici (hors temps A).
- **Downgrade.** Les cinq fonctions de la 0006 et de la 0008 sont restituées ; le `CHECK` des
  événements est recréé `NOT VALID`, car l'outbox peut porter des `payment.cancelled` qu'une
  migration ne voit pas (FORCE RLS). Les lignes d'annulation déjà écrites redeviennent des
  paiements de sens opposé sans lien : le net de trésorerie reste exact, les soldes stockés
  restent ceux de l'annulation. Même asymétrie DDL / DML que l'ADR 0024.
- La liste fermée des événements passe à **dix** (`CLAUDE.md` § 4, `EventType`, `CHECK` en base,
  tests).
