# 0031 — Écarts assumés de la phase 07, et ce qui est repoussé

- **Date** : 2026-09-24
- **Phase** : 07
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`), dans le prolongement des ADR 0010, 0018, 0023 et 0026

## Décision 1 — 409 pour l'état, 422 pour la demande

L'annexe A.5 écrit « ROLLBACK · 422 » quand une allocation dépasse le solde d'une dette. Mais
l'ADR 0010 réserve 422 à la donnée invalide et 409 à l'état qui refuse, et le code livré en
phase 06 lève déjà `allocation_exceeds_balance` en **409** (`BusinessRuleError`) — suivre le
diagramme à la lettre aurait imposé de changer le contrat déjà publié des remboursements.

Le partage retenu :

| Code | Cas | Pourquoi |
|---|---|---|
| **422** | `allocations_exceed_payment` (Σ affectations > montant) | la requête se contredit seule |
| **422** | `duplicate_allocation` (même dette deux fois) | idem, doublé par `pa_pair_uq` |
| **422** | `idempotency_key_reused` / `_required` / `_malformed` | l'en-tête, pas l'état |
| **409** | `allocation_exceeds_balance` (`CG044`) | il faut lire la dette pour refuser |
| **409** | `payment_over_allocated` (`CG043`, `CG045`) | idem |
| **409** | `credit_limit_exceeded` (`CG030`) | idem |
| **409** | `debt_already_closed` | idem |
| **409** | `payment_reference_taken` (`payments_ref_uq`) | idem |

C'est la même règle que `insufficient_stock` (ADR 0018), et le client peut réagir à la règle
précise plutôt qu'à un « 422 » indifférencié.

## Décision 2 — Le sens d'une allocation est vérifié en applicatif, pas en base

Une créance client s'éteint par un `inflow`, une dette fournisseur par un `outflow`.
Ni le § 8.7 ni le § 5.5 ne posent cette règle, et `allocation_check` **ignore** volontairement
`direction` — la compensation de l'ADR 0024 en dépend, puisqu'elle alloue un `inflow` sans flux
de caisse. Durcir le trigger casserait la phase 06.

Le contrôle reste donc dans `finance.record_payment`, sous le nom
`allocation_direction_mismatch` (409). C'est le seul invariant de cette phase qui ne soit pas
doublé en base ; il est nommé ici pour qu'on sache où le chercher, et pourquoi il n'y est pas.

## Décision 3 — `paid_at` ne peut pas être dans le futur

Le § 8.6 ne borne pas `paid_at`. Le schéma d'entrée refuse pourtant une date future : un
encaissement de demain n'est pas un encaissement, c'est une prévision — et la prévision de
trésorerie est explicitement hors V1 (phase 09). Contrôle applicatif seul, assumé : il ne
protège que l'API, et c'est le seul chemin d'écriture.

Aucune fenêtre d'antidatage n'est imposée, contrairement aux mouvements de stock (ADR 0015) : un
paiement ne participe à aucun calcul incrémental qu'un antidatage fausserait, et saisir en fin de
semaine les règlements du lundi est le quotidien d'une PME.

## Décision 4 — La correction et l'annulation d'un paiement sont repoussées

Le prompt de la phase demandait que « toute correction importante d'un paiement (réallocation,
annulation) passe par un audit critique avec la valeur avant et après, et ne supprime jamais
physiquement ». La règle est juste ; ce qu'elle suppose n'existe pas.

`payments` ne porte ni `cancelled_at`, ni `deleted_at`, ni `status` (§ 8.6), et `coges_app` n'a
pas le droit `DELETE`. Annuler un versement exigerait donc une colonne que le Modèle de données
ne prévoit pas — c'est-à-dire une décision de schéma à part entière, pas un service de plus.

**Rien n'est livré, et rien n'est préparé.** `payments:update` et `payments:cancel` restent au
catalogue **sans endpoint** : leur présence sans route est une information, comme l'absence de
`DELETE /sales/{id}` en phase 05. La règle ci-dessus s'appliquera à la phase qui ouvrira le
sujet.

Ce qui existe en attendant : un versement mal saisi se corrige par un versement de sens inverse,
qui laisse les deux écritures visibles — la même philosophie que le mouvement de stock inverse de
l'ADR 0017.

## Décision 5 — Une borne de saisie inventée, et assumée

`MAX_ALLOCATIONS = 20` : aucun texte ne fixe le nombre de dettes qu'un seul versement peut
éteindre. La borne existe pour qu'une requête absurde soit refusée **avant** d'ouvrir cinquante
verrous `FOR UPDATE` dans la transaction d'un caissier. De même, `MAX_PERIOD_DAYS = 366` sur
l'overview : une plage saisie de travers ne doit pas balayer dix ans de lignes de vente dans le
cycle d'une requête HTTP.

## Conséquences

- Aucun nouveau SQLSTATE : `CG030` et `CG041`–`CG045` couvraient déjà tous les refus que les
  paiements et les lettrages peuvent rencontrer. L'ADR 0026 l'avait prévu — « la phase 07, qui
  construira les paiements et les lettrages pour eux-mêmes, hérite du travail ».
- Les violations de clés étrangères composites (`payments_sale_fk`, `payments_expense_fk`,
  `debts_expense_fk`, `pa_debt_fk`…) sont traduites en **404**. C'est un détour rendu nécessaire
  par l'ordre des dépendances : Sales et Expenses sont au-dessus de Finance, qui ne peut donc pas
  leur demander si la pièce existe. La contrainte le dit à sa place.
