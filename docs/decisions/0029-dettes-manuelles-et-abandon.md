# 0029 — Une dette fournisseur se déclare, une créance s'abandonne sous le nom du gérant

- **Date** : 2026-09-24
- **Phase** : 07
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

`debts.party_type` accepte `supplier` depuis la révision 0006, mais rien ne créait jamais une
dette fournisseur : la seule écriture existante était `open_customer_debt`, appelée par la
confirmation d'une vente à crédit. De même, `debt_status` porte `written_off` et le § 5.5 dit
« abandon : `written_off` avec motif en `audit_logs` » — sans dire qui a le droit de le faire.

## Décision 1 — La dette fournisseur est saisie à la main

`POST /api/v1/debts` : `party_type`, le tiers, le montant, une échéance facultative et un
`expense_id` facultatif. Aucune règle implicite ne crée d'engagement à la place du gérant.

L'option « automatique depuis une dépense marquée à payer » a été écartée : elle exigerait un
champ d'état sur `expenses` que le § 8.6 ne prévoit pas, et lierait deux objets dont le modèle ne
fait qu'un lien **facultatif** (`debts.expense_id` est nullable). Une dépense reste une charge
constatée, qu'elle soit payée ou non ; ce que l'entreprise déclare devoir est une autre
information, et c'est au gérant de la donner.

Le plafond de crédit s'applique de la même façon, quel que soit le chemin : une créance saisie à
la main passe par le même contrôle applicatif et le même trigger `debt_credit_limit` (`CG030`,
verrou depuis la révision 0007) qu'une dette née d'une vente.

## Décision 2 — L'abandon est réservé au gérant, motif obligatoire

`POST /api/v1/debts/{id}/write-off`, permission **`debts:write_off`**, motif d'au moins dix
caractères, audit critique avec l'état avant et après. `principal` n'est **jamais** réécrit
(§ 5.5) : la dette est close, pas effacée, et son montant initial reste lisible. `closed_at` est
renseigné, sans quoi le `CHECK` `debts_closed_coherent` refuserait le statut.

Une dette **déjà partiellement réglée est abandonnable** : renoncer au reliquat d'un client qui a
payé la moitié puis a disparu est le cas réel. Cela la distingue de `write_off_sale_debt`
(phase 06), qui sert l'**annulation d'une vente** et refuse une dette déjà réglée en
`debt_partially_paid` — là, de l'argent reçu devrait d'abord être rendu. Deux gestes, deux règles,
et les deux fonctions restent.

**Aucun événement n'est émis.** `debt.settled` dirait qu'elle a été réglée ; elle ne l'a pas été.
L'audit critique, lui, en garde la trace avec son motif.

## Conséquences

- La révision 0009 ajoute `debts:write_off` au catalogue global `permissions`, et **étend le
  `CHECK` sur `action`** : il énumérait sept verbes, `write_off` n'en faisait pas partie. C'est le
  rôle de ce `CHECK` que d'obliger à ce geste explicite plutôt que de laisser le vocabulaire des
  droits s'étendre par inadvertance.
- Le comptable ne le reçoit pas : `ACCOUNTANT_PERMISSIONS` ne le liste pas, et le gérant a
  **toutes** les permissions du catalogue par construction.
- **Le rattachement aux rôles existants est fait par la migration**, et non par une commande
  d'exploitation comme le plan l'envisageait. `role_permissions` est en `FORCE ROW LEVEL
  SECURITY` et `coges_owner` est `NOBYPASSRLS` : un `INSERT … SELECT` n'y verrait aucune ligne et
  n'insérerait rien, **sans lever d'erreur** (ADR 0024). La migration lève donc le `FORCE` le
  temps de l'écriture, exactement comme le `downgrade` de la révision 0002 le fait déjà. Sans ce
  backfill, les entreprises créées avant cette révision auraient eu un gérant incapable
  d'abandonner une créance, et rien ne l'aurait signalé.
- Une dette abandonnée n'accepte plus de règlement (`debt_already_closed`, 409) et sort des
  encours : `pa_rollup` l'ignore explicitement (`AND d.status <> 'written_off'`).
