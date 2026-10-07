# 0024 — Éteindre une dette par un retour : deux paiements en `offset`

- **Date** : 2026-09-24
- **Phase** : 06
- **Statut** : acceptée — amendée par 0062 (la compensation compte dans `paid_total`, qui veut dire « réglé »)
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le § 4.6 énumère les trois façons de régler un retour : un remboursement en trésorerie, **une
extinction de dette existante via `payment_allocations`**, ou rien du tout. La deuxième est
écrite en une ligne, et cette ligne ne se traduit pas telle quelle en SQL.

Une allocation exige un `payment_id`. Un paiement rattaché à un retour doit être un `outflow`
(`payments_return_outflow`, § 8.6). Et une dette **client** s'éteint par un `inflow`, que
`pa_rollup` additionne pour produire `amount_paid`. Avec les cinq moyens de paiement existants,
la compensation s'écrirait donc comme une sortie de caisse qui n'a pas eu lieu, suivie d'une
entrée qui n'a pas eu lieu non plus : la trésorerie du gérant sortirait fausse des deux côtés,
pour une opération où **aucun argent ne bouge**.

Le cas est pourtant le plus courant du terrain : un client à crédit rapporte trois articles sur
dix. Le rembourser en espèces puis lui réclamer la même somme est absurde, et c'est exactement ce
que l'option « trésorerie seulement » aurait imposé.

## Options envisagées

1. **Deux paiements `offset` (retenue)** : `offset` entre dans l'ENUM `pay_method`, et une seule
   transaction écrit un `outflow` rattaché au retour puis un `inflow` alloué à la dette, tous
   deux marqués `offset`. Les deux lettrages restent exacts ; la trésorerie exclut ces écritures
   sur ce seul critère.
2. **Trésorerie ou rien en V1** : aucun changement de schéma, mais une règle explicite du § 4.6
   reste non implémentée et le cas courant oblige à faire circuler de l'argent pour rien.
3. **Un seul `outflow`, alloué à la dette** : aucun changement de schéma non plus, et les
   triggers l'accepteraient — `allocation_check` ne regarde pas `direction`. Mais le sens
   financier s'inverse (une sortie éteindrait une créance) et la trésorerie enregistrerait un
   décaissement fictif. Écarté.

## Décision

La révision **0008** ajoute `offset` à `pay_method`. `finance.record_return_offset` écrit les
deux paiements et leurs lettrages dans la transaction du remboursement, et
`sales.refund_return` l'appelle quand le gérant choisit `method = "offset"`.

`offset` n'est **pas** un sixième moyen de payer : c'est la marque d'une écriture sans flux de
caisse. `finance.schemas.PaymentMethod` ne le contient donc pas — une vente ne s'encaisse pas en
compensation — et seul `RefundMethod`, réservé à l'endpoint de remboursement, l'accepte.

## Conséquences

- **L'`inflow` ne porte pas de `sale_id`**, et ce n'est pas un oubli. `sale_paid_rollup` somme
  les encaissements d'une vente pour produire `paid_total`, qui doit rester ce qui est
  **encaissé** ; une compensation n'encaisse rien. Le chaînage reste lisible par la dette, qui
  porte déjà `sale_id`. Un test le vérifie : après compensation, `paid_total` vaut toujours 0
  tandis que `debts.balance` a baissé.
- **La dette visée est celle de la vente retournée** (`finance.open_debt_for_sale`), lue
  `FOR UPDATE` avant toute écriture. Sans dette ouverte : refus `no_debt_to_offset`. Compensation
  supérieure au solde : refus `offset_exceeds_debt`, doublé par `CG044`. Compenser une **autre**
  dette du même client reste possible plus tard, en ajoutant un `debt_id` optionnel ; l'écran qui
  listerait ces dettes n'existe pas avant la phase 07.
- **Règle à tenir pour les phases 07 et 08** : tout état de trésorerie exclut `method = 'offset'`.
  La constante `finance.schemas.OFFSET_METHOD` existe pour qu'aucun de ces calculs n'ait à écrire
  la chaîne à la main. C'est la seule dette que cette décision laisse au futur, et elle est
  nommée.
- **Réversibilité, et ce qu'elle ne peut pas couvrir.** `ALTER TYPE … DROP VALUE` n'existe pas.
  Le `downgrade` de la 0008 rend donc les quatre fonctions trigger, mais **laisse `offset` dans
  l'ENUM**. La première version de cette migration recréait le type et convertissait
  `payments.method` ; elle a échoué dès la première suite de tests complète, sur
  `invalid input value for enum pay_method: "offset"` — les compensations écrites par les tests
  d'API empêchaient la remise à zéro de `coges_test`, qui passe par `downgrade base`.

  Les trois issues possibles ont été pesées : **échouer** rend la base de test irrécupérable ;
  **replier `offset` sur un moyen réel** dans le `USING` transformerait des compensations en
  mouvements de caisse qui n'ont jamais eu lieu, soit exactement ce que cette décision cherchait
  à empêcher ; **supprimer les lignes d'abord** est impossible, car `payments` est en
  `FORCE ROW LEVEL SECURITY` et `coges_owner` est `NOBYPASSRLS` (ADR 0004) — un `DELETE` lancé
  par une migration n'y verrait aucune ligne et n'en supprimerait aucune, **sans lever d'erreur**.
  Seule une réécriture DDL voit toute la table : c'est cette asymétrie entre DDL et DML sous RLS
  qui décide, et elle vaut pour toute future migration qui voudrait nettoyer des données.

  L'étiquette laissée est inerte : à la 0007, aucun code ne peut l'écrire, et les compensations
  déjà enregistrées restent lisibles plutôt que détruites ou falsifiées. `downgrade base` reste un
  retour complet — la révision 0001 supprime le type. La CI teste l'aller-retour à chaque push.
- L'événement `sale_return.refunded` porte `method`, donc `offset` : c'est à ce champ que
  l'analytique de la phase 08 reconnaîtra une écriture sans flux, sans relire `payments`.
- Aucun avoir client, aucun solde créditeur : ils restent hors V1 (§ 4.6). Un client dont le
  retour dépasse sa dette est remboursé du reste en trésorerie, en un second appel.
