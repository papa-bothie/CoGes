# 0017 — Corriger une erreur de saisie : le mouvement inverse

- **Date** : 2026-09-23
- **Phase** : 04
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

`inventory_movements` est append-only (§ 4.8) : ni `UPDATE`, ni `DELETE`. Un gérant qui saisit
« perte de 100 » au lieu de « perte de 10 » doit pourtant pouvoir se corriger.

Le § 8.5 prévoit tout l'outillage — `reversal_of_movement_id`, `inv_reversal_uq`,
`inv_check_reversal()` — mais l'architecture ne dit pas quel endpoint l'expose en V1, ni qui a le
droit de s'en servir.

## Options envisagées

1. **`POST /api/v1/inventory/movements/{id}/reverse` (retenue)** : le lien vers le mouvement
   d'origine reste lisible dans le journal, et l'unicité de l'annulation est garantie par la base.
2. Uniquement un nouvel `adjustment` de sens contraire : plus simple à coder, mais on perd le lien
   explicite, l'unicité garantie, et `inv_check_reversal()` resterait du code mort jusqu'à la
   phase 05.

## Décision

L'endpoint `POST /api/v1/inventory/movements/{id}/reverse` crée le mouvement inverse exact, sous
permission **`inventory:update`**, réservée au gérant par la matrice de l'ADR 0007. L'opération
écrit un **audit critique** (`action = cancel`) et émet `stock.updated`. Elle renvoie le mouvement
**inverse** créé, jamais celui d'origine — ce dernier n'a pas changé, et ne changera jamais.

Le type de l'inverse reste sémantique, conformément au § 4.8 : `customer_return_in` pour une
sortie de vente annulée, `adjustment` pour toute correction d'inventaire.

## Conséquences

- **Découvert en implémentant** : le contrôle applicatif « ce mouvement est-il déjà annulé ? » est
  **indispensable**, pas confortable. Les triggers `BEFORE INSERT` s'exécutent avant la
  vérification d'unicité : si le stock ne suffit plus, `t20_inv_apply` refuse la sortie en
  `CG020` et `inv_reversal_uq` ne parle jamais. Une seconde annulation serait alors annoncée au
  gérant comme un manque de stock. Le service lit donc l'annulation existante et lève
  `already_reversed` (409). `inv_reversal_uq` reste l'autorité sous concurrence.
- De même, annuler une annulation est refusé par le service (`movement_not_reversible`, 409) avant
  d'atteindre `inv_check_reversal()`, qui lève sans SQLSTATE applicatif (`P0001`).
- Le journal expose **ni `PATCH` ni `DELETE`** : l'absence de ces routes est une information, pas
  un oubli.
- `t10_inv_check_reversal` réécrit `unit_cost`, `ref_type` et `ref_id` depuis le mouvement
  d'origine. Le service doit donc relire la ligne après le `flush` — voir l'ADR 0018.
