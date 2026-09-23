# 0018 — Écarts assumés au § 8.5, et incohérences relevées dans les documents

- **Date** : 2026-09-23
- **Phase** : 04
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

La consigne de la phase 04 était de copier le SQL du § 8.5 **à l'identique**. Le SQL a d'abord été
exécuté tel quel dans `coges_test` avant d'être figé dans la migration. Trois points ont demandé
un arbitrage, et cinq observations méritent d'être consignées.

## Décision 1 — SQLSTATE dédiés pour les refus du trigger de stock

Le § 8.5 lève le stock négatif en `check_violation` (23514) et le produit non suivi en
`restrict_violation` (23001). Ces deux codes sont **déjà pris** :

| SQLSTATE du § 8.5 | Désigne aussi |
|---|---|
| `check_violation` | `inv_sign_coherent`, `CHECK (qty_on_hand >= 0)`, `CHECK (qty_delta <> 0)` |
| `restrict_violation` | `inv_no_update` / `inv_no_delete`, c'est-à-dire **T13** |

Le service ne peut donc pas distinguer T6/T7 d'un signe incohérent, ni T8 de T13. L'ADR 0014 a
déjà tranché le principe : le SQLSTATE est stable, le texte du message ne l'est pas.

Seuls les `ERRCODE` changent, la logique et les messages restent mot pour mot :

| SQLSTATE | Code métier | Origine |
|---|---|---|
| `CG010` | `movement_backdated_too_far` | `inv_check_backdating()` (ADR 0015, nouveau) |
| `CG020` | `insufficient_stock` | `inv_apply_movement()`, au lieu de `check_violation` |
| `CG021` | `product_not_stock_tracked` | `inv_apply_movement()`, au lieu de `restrict_violation` |

L'immuabilité du journal conserve `restrict_violation`, **exigé mot pour mot** par le § 10 (T13).

Pour `23505`, le SQLSTATE ne suffit pas non plus : `inv_reversal_uq` et `inv_ref_idempotence`
rendent le même code. `app/core/errors.py` gagne donc `constraint_name(exc)`, jumeau de
`sqlstate(exc)`, qui lit `exc.orig.diag.constraint_name` — renseigné par PostgreSQL pour les index
uniques comme pour les contraintes nommées.

## Décision 2 — `insufficient_stock` en 409, et non 422

Le prompt de phase demandait 422. L'ADR 0010 a fixé **409** pour toute `BusinessRuleError` :
« 409 et non 422 : la donnée envoyée est valide, c'est l'état du système qui refuse. » Un stock
insuffisant est exactement ce cas. 409 est retenu, pour que le front garde une règle simple :
422 = un champ invalide, 409 = une règle métier, avec des `details` exploitables.

## Décision 3 — aucun `REVOKE` sur `inventory_movements`

Le réflexe, sur un journal append-only, est de retirer `UPDATE` à `coges_app`, comme la révision
0002 le fait pour `audit_logs`. C'est d'abord ce qui avait été décidé — **et c'était une erreur**,
constatée en exécutant les tests :

> `SELECT … FOR SHARE` exige le privilège `UPDATE` (ou `DELETE`) en plus de `SELECT`.

Or `inv_check_reversal()` verrouille le mouvement d'origine par `FOR SHARE`. Sans `UPDATE`,
`permission denied for table inventory_movements` : **plus aucune annulation n'est possible**.

Aucun `REVOKE` n'est donc posé. L'immuabilité est portée par `inv_no_update` et `inv_no_delete`,
qui tiennent contre **n'importe quel** rôle — y compris le propriétaire, qui détient les droits.
Un `REVOKE` n'aurait protégé que le rôle applicatif. Le `DELETE`, lui, n'a jamais été accordé
(révision 0001) : il s'arrête plus tôt, en `insufficient_privilege`.

T13 le prouve deux fois : en `coges_app`, l'`UPDATE` atteint le trigger et rend bien
`restrict_violation` — la lettre du § 10 ; avec le rôle propriétaire, `UPDATE` **et** `DELETE`
lèvent tous les deux `restrict_violation`.

## Observations consignées, sans modification des documents

1. **§ 4.8 contre § 8.5** — le § 4.8 décrit encore l'immuabilité par des règles
   `DO INSTEAD NOTHING`. Le § 8.5 les remplace explicitement par `RAISE EXCEPTION`, en expliquant
   pourquoi (« masquait silencieusement un bug applicatif en renvoyant 0 ligne modifiée »). Le SQL
   fait foi, et T13 le confirme.
2. **Branche morte dans `inv_apply_movement`** — `IF NEW.qty_delta > 0 AND NEW.unit_cost IS NULL`
   est inatteignable : `unit_cost` est `NOT NULL` (§ 4.8 : « NON NULLABLE »). Copiée telle quelle,
   signalée en commentaire : elle protège un futur assouplissement de la colonne.
3. **`rebuild_product_stock` est correcte telle quelle** — le `JOIN product_stock s USING
   (product_id)` alors que `product_id` est un paramètre `OUT` faisait craindre une ambiguïté
   `42702`. Vérifié par exécution : PostgreSQL 16 l'accepte. Aucune correction.
4. **`CREATE TEMP TABLE _rebuilt … ON COMMIT DROP`** interdit deux appels dans la même
   transaction. La commande `rebuild-stock` ouvre donc **une transaction par entreprise**.
5. **`inv_product_fk` est inatteignable pour un produit d'un autre tenant.** `t20_inv_apply` est
   un trigger `BEFORE`, il cherche le produit dans le tenant courant et lève avant que la FK ne
   soit vérifiée. L'isolation tient — par le trigger, pas par la clé étrangère, qui reste la
   garantie structurelle si le trigger disparaissait. T5 est écrit en conséquence.

## Conséquence découverte en exécutant le scénario de démonstration

Les triggers `BEFORE INSERT` **réécrivent la ligne** : `t20_inv_apply` estampille `unit_cost` au
CMP sur toute sortie, `t10_inv_check_reversal` reprend `unit_cost`, `ref_type` et `ref_id` du
mouvement d'origine. SQLAlchemy l'ignore. Sans `session.refresh(movement)` après le `flush`,
l'API renvoyait `unit_cost = "0.0000"` sur une perte que la base portait à `15.0000` : le gérant
aurait lu un coût de perte nul dans son journal. Le service relit donc systématiquement le
mouvement après l'écriture, et un test couvre le cas.

À reprendre dans **tout** module dont une table porte un trigger `BEFORE INSERT` ou
`BEFORE UPDATE` qui modifie `NEW` — ce sera le cas des ventes en phase 05.
