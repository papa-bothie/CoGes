# 0023 — Écarts assumés au § 8.7, et la règle d'annulation appliquée telle quelle

- **Date** : 2026-09-24
- **Phase** : 05
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

La consigne de la phase 05 était de copier le SQL des § 8.4, 8.6 et 8.7 **à l'identique**. Le SQL
a d'abord été exécuté tel quel dans `coges_test`, puis rejoué en `downgrade`/`upgrade`, avant
d'être figé dans la révision 0006. Deux points ont demandé un arbitrage, et une règle du § 5.2 a
été confirmée plutôt que modifiée.

## Décision 1 — `sale_items_frozen` couvre aussi l'INSERT

Le § 8.7 pose le trigger en `BEFORE UPDATE OR DELETE`. Rien n'empêche donc d'**insérer** une
ligne dans une vente déjà confirmée — et `sale_items_totals` en répercuterait aussitôt le
montant sur `subtotal`, `tax_total` et, par la colonne générée, sur `total`. Le total d'une vente
émise changerait après coup, ce que le Diagramme 4 exclut explicitement : « brouillon verrouillé
à la confirmation, **plus aucune ligne modifiable** ».

Le trigger devient `BEFORE INSERT OR UPDATE OR DELETE`. La fonction, son message et son
`restrict_violation` sont inchangés.

Un contrôle applicatif ne suffisait pas : le § 10 exige des tests qui attaquent la base
directement, et « un test qui ne passerait que parce que l'API a vérifié quelque chose ne vaut
rien ». Le service refuse quand même en amont, pour rendre un `sale_not_draft` nommé plutôt
qu'un SQLSTATE brut — même redondance assumée que pour les catégories (ADR 0014).

**Effet de bord repéré en écrivant T5** : sur une vente d'un **autre** tenant, le trigger ne
trouve pas la ligne, `v_status` vaut NULL, `v_status <> 'draft'` vaut NULL, et il laisse passer.
C'est `sale_items_sale_fk` qui refuse — la barrière 1, celle qui ne dépend d'aucun trigger. Le
test T5 le documente, et le harnais de fuite doit donc partir d'un **brouillon neuf** pour
mesurer la clé étrangère plutôt que le trigger.

## Décision 2 — `debt_credit_limit()` lève `CG030`

Le § 8.7 lève le dépassement de plafond en `check_violation` (23514). Ce code est **déjà pris**,
dans le périmètre même de la phase : `sales_discount_bounds`, `sale_items_discount_bounds`,
`debts_paid_bounds`, `sales_cancel_coherent`. Le service ne pourrait pas distinguer un plafond
dépassé d'une remise trop forte.

Même arbitrage qu'à l'ADR 0018 : seul l'`ERRCODE` change, la logique et le message restent mot
pour mot.

| SQLSTATE | Code métier | Origine |
|---|---|---|
| `CG030` | `credit_limit_exceeded` | `debt_credit_limit()`, au lieu de `check_violation` |

Les autres triggers du § 8.7 gardent leurs codes : aucun ne remonte en erreur métier nommée
avant la phase 06. `sale_items_frozen` conserve son `restrict_violation`, qui ne collisionne avec
rien ici.

Comme pour les catégories, le contrôle est **doublé** côté service : `finance.open_customer_debt`
lit le plafond par la nouvelle façade `customers.get_credit_limit` et l'encours par
`DebtRepository.open_balance_for_customer` — même définition que le trigger — pour nommer dans
`details` le plafond, l'encours et le montant qui ne passe pas. Le trigger reste l'autorité sous
concurrence : deux caisses peuvent ouvrir deux crédits au même client au même instant.

## Décision 3 — l'annulation du § 5.2, telle quelle

Le § 5.2 refuse l'annulation s'il existe un retour **ou un paiement encaissé non remboursé**.
La règle est appliquée sans aménagement : une vente payée comptant ne s'annule pas, elle se
corrige par un retour (phase 06).

Autrement dit, en phase 05, seule une vente **à crédit** est annulable. C'est voulu : effacer
une vente dont l'argent est entré en caisse ferait diverger la trésorerie du réel, et
l'annulation deviendrait un substitut au retour — exactement ce que le modèle refuse. Le refus
est nommé (`sale_has_payment`) et cite `paid_total`, pour que le caissier sache quoi faire.

La dette, elle, n'est abandonnée que si **rien** n'a été réglé dessus (`amount_paid = 0`) ;
sinon `debt_partially_paid`. `principal` n'est jamais réécrit (§ 5.5) : la dette est close, pas
effacée.

## Conséquences

- Trois écarts au total dans la révision 0006, tous commentés dans le SQL : le trigger étendu à
  l'INSERT, `CG030`, et la table `document_counters` (ADR 0021), qui n'est pas un écart mais un
  ajout.
- `customers.service` gagne `get_credit_limit`, et `products.schemas.CurrentPrice` gagne
  `price_id` — le § 5.1 étape 3 l'exige sur la ligne de vente, et la façade ne l'exposait pas.
  `ProductSummary` gagne `default_tax_rate`, pour que la confirmation fige les taux d'une vente
  entière sans une requête par ligne.
- L'annulation réutilise `inventory.reverse_sale_out`, qui n'écrit **pas** d'audit critique :
  c'est l'annulation de la vente qui est l'opération auditée, et elle porte le motif. Un audit
  par mouvement aurait noyé le fait dans ses conséquences.
