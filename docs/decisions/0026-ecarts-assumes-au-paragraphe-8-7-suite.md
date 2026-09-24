# 0026 — Écarts assumés au § 8.7 (suite), et la forme de l'arrondi

- **Date** : 2026-09-24
- **Phase** : 06
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`), dans le prolongement des ADR 0018 et 0023

## Contexte

Les triggers de retour et de remboursement du § 8.7 sont posés depuis la révision 0006 et sont
restés **inertes** jusqu'ici (ADR 0019). En les réveillant, la phase 06 les a regardés de près.

## Décision 1 — Six SQLSTATE applicatifs, `CG040` à `CG045`

Le § 8.7 lève ces refus de deux façons, toutes deux inexploitables par un service :

- en `check_violation` (23514) pour le plafond de quantité et le dépassement du reste dû. Ce code
  est déjà porté, **dans le périmètre même de la phase**, par `sale_returns_refund_cap`,
  `sale_return_items_tax_bounds` et `debts_paid_bounds` : impossible de distinguer un retour trop
  grand d'une part de taxe incohérente ;
- **sans `ERRCODE` du tout** pour trois d'entre eux — le sens du paiement et les deux
  sur-affectations. Ils remontent donc en `P0001`, strictement indistinguable d'un bug.

Même arbitrage qu'aux ADR 0018 et 0023 : **seul l'`ERRCODE` change**. La logique, les messages et
les verrous des quatre fonctions sont restitués mot pour mot dans la révision 0008.

| SQLSTATE | Fonction | Erreur métier | Code d'origine |
|---|---|---|---|
| `CG040` | `return_item_check` | `return_qty_exceeds_sold` | `check_violation` |
| `CG041` | `refund_check` (reste dû) | `refund_exceeds_due` | `check_violation` |
| `CG042` | `refund_check` (sens) | `refund_requires_outflow` | *aucun* (`P0001`) |
| `CG043` | `refund_check` (sur-affectation) | `payment_over_allocated` | *aucun* (`P0001`) |
| `CG044` | `allocation_check` (solde) | `allocation_exceeds_balance` | `check_violation` |
| `CG045` | `allocation_check` (sur-affectation) | `payment_over_allocated` | *aucun* (`P0001`) |

`allocation_check` y figure parce que la compensation de l'ADR 0024 écrit une allocation : ses
refus doivent être nommables au même titre que ceux du remboursement. La phase 07, qui construira
les paiements et les lettrages pour eux-mêmes, hérite du travail.

Deux `RAISE` gardent volontairement leur `P0001` : « Ligne de vente introuvable » et « Retour
introuvable ». Ils ne sont atteignables que par une écriture croisée entre tenants, que les clés
étrangères composites referment de toute façon — les tests T5 le documentent. Les nommer
laisserait croire qu'un service devrait les rattraper.

Comme partout depuis l'ADR 0014, le contrôle est **doublé** côté service : `refund_return`
calcule le reste dû sous le verrou du retour et refuse en `refund_exceeds_due` avant d'écrire.
Le trigger reste l'autorité — c'est lui qui tient sous concurrence — et le contrôle applicatif ne
sert qu'à nommer le montant dans le cas courant.

## Décision 2 — L'arrondi du remboursable : net et taxe séparément

Le § 4.7 donne la formule `qty × (unit_price − discount/qty) × (1 + tax_rate)`, « arrondi à
2 décimales ». Appliquée telle quelle, avec un arrondi unique sur le TTC, elle rend parfois **un
centime de moins que `line_total`** sur un retour **total**. Un client qui rapporte tout ce qu'il
a acheté doit récupérer ce qu'il a payé, à l'unité de centime près : c'est la seule propriété
non négociable de ce calcul.

`_refund_amounts` reproduit donc exactement les colonnes générées de `sale_items` :

```
ht     = qty_rendue × unit_price − discount × qty_rendue / qty     (remise au prorata)
tax    = round(ht × tax_rate, 2)     → tax_refund
refund = round(ht, 2) + tax          → refund_amount
```

Contrepartie assumée et testée : la somme de plusieurs retours **partiels** peut s'écarter d'un
centime du total de la ligne. Aucune répartition ne peut éviter les deux à la fois, et c'est le
retour total qu'un client vient réclamer.

La remise est **proratisée** : rendre 3 articles sur 10 rend trois dixièmes de la remise. Ni la
remise entière — le client serait remboursé plus qu'il n'a payé —, ni rien du tout.

## Décision 3 — Aucun événement pour le paiement d'un remboursement

`finance.record_return_refund` écrit un `payment` sans rien émettre. La liste des neuf types
d'événements est **fermée** (`business_events` porte un CHECK, ADR 0008) et ne contient pas de
`payment.sent` ; émettre `payment.received` pour un décaissement dirait le contraire de ce qui
s'est passé.

C'est `sale_return.refunded`, émis par Sales, qui porte le fait — avec son `payment_id`, son
montant et sa méthode. Un abonné qui suit la trésorerie y trouve tout, y compris le `offset` qui
lui dit d'ignorer l'écriture (ADR 0024).

## Décision 4 — L'audit critique : l'un crée, l'autre règle

La création d'un retour est auditée en `INSERT` sur `sale_returns`, avec son `after`. Le
règlement est audité en `UPDATE` sur la **même entité**, avec `before` et `after` : ce qui change
est `refunded_total` et `refund_status`, et c'est cela qu'un enquêteur veut voir bouger. Finance
audite en plus l'écriture de trésorerie elle-même (`INSERT` sur `payments`, et sur
`payment_allocations` pour une compensation).

`AuditAction` n'est **pas** étendu : `INSERT` et `UPDATE` sur `sale_returns` disent déjà ce qui
s'est passé, et ajouter une valeur imposerait de toucher le CHECK de `audit_logs`, table
partitionnée et append-only.

## Décision 5 — L'ordre du § 5.4 est un ordre de verrous, pas une mise en page

Écrire les tests de concurrence a mis au jour une propriété que le § 5.4 énonce sans
l'expliquer. Son étape 1 — « verrouiller `sale_returns` FOR UPDATE » — précède son étape 2
— « insérer `payments` ». Inverser les deux **interbloque**.

`payments.sale_return_id` porte une clé étrangère vers `sale_returns`. Insérer le décaissement
prend donc un verrou `FOR KEY SHARE` sur la ligne du retour : partagé, donc accordé aux deux
caisses à la fois. Chacune demande ensuite le `FOR UPDATE` de `refund_check`, qui attend que
l'autre lâche son verrou partagé. Les deux s'attendent, et PostgreSQL en abat une en `40P01`.

Le résultat reste **sûr** — aucun double remboursement, la transaction perdante est annulée
entière — mais il est opaque : un `deadlock_detected` n'est pas un `refund_exceeds_due`, il ne
dit rien au caissier et désigne sa victime au hasard.

`sales.refund_return` prend donc le verrou fort **en premier**, par
`SaleReturnRepository.get_for_update`, avant de passer la main à Finance. La règle est générale
et vaut pour la phase 07 : ne jamais prendre un verrou partagé qu'il faudra ensuite élever.

`sale_return_items` n'a pas ce défaut, et la raison est instructive : `return_item_check` est un
trigger **BEFORE INSERT**, il prend son `FOR UPDATE` sur la ligne de vente *avant* que la clé
étrangère ne demande son `KEY SHARE`. L'ordre y est déjà le bon sans que personne ait eu à y
penser — ce qui explique qu'on ne s'en soit jamais aperçu ailleurs.

Un test fige chacune des deux moitiés : `test_t20_concurrent_refunds` prouve que l'ordre correct
sérialise et rend `CG041`, et `test_t20_refunding_without_locking_the_return_first_deadlocks`
prouve que l'inverser coûte un `40P01`.

## Conséquences

- La révision 0008 ne crée aucune table et n'accorde aucun privilège. Elle ne fait que remplacer
  quatre corps de fonction et ouvrir un ENUM.
- Les tests T18 et T20 assertent sur `CG040` et `CG041`, pas sur un texte de message : le
  SQLSTATE est stable, le message ne l'est pas (ADR 0014).
- Le test unitaire `test_refund_amounts.py` fixe la forme de l'arrondi, y compris l'égalité
  « retour total = `line_total` » qui la justifie. Il ne touche pas la base : c'est le seul calcul
  que la phase 06 fait en Python.
- `test_t18_t20_concurrent_returns.py` provoque les deux fenêtres de concurrence à trois
  connexions, comme T28 et T38 : une troisième transaction s'approprie la ligne de rendez-vous, les
  deux caisses viennent s'y bloquer, et c'est le COMMIT du test qui les relâche. Les verrous du
  § 8.7 étaient déjà là — contrairement au plafond de crédit, rien n'a dû être corrigé ; ces tests
  prouvent qu'ils tiennent, et l'ordre de la décision 5 avec eux.
