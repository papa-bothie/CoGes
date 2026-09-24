# 0020 — La quatrième et dernière exception au « pas de DELETE »

- **Date** : 2026-09-24
- **Phase** : 05
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Un caissier se trompe d'article et veut retirer la ligne de son brouillon. C'est un `DELETE`
sur `sale_items`, et `coges_app` n'a pas ce droit (§ 7 du Modèle, ADR 0007). Aucun contournement
n'existe : `sale_items` n'a ni `deleted_at`, ni place pour une ligne neutralisée dans
`sale_recompute_totals`, et `CHECK (qty > 0)` interdit de la vider.

## Options envisagées

1. **Accorder DELETE sur `sale_items` (retenue)** : quatrième exception, bornée par un trigger
   et par un test.
2. Suppression logique : ajouter `deleted_at` au § 8.4, puis exclure ces lignes du trigger de
   recalcul **et** de tous les agrégats analytiques à venir. Un écart au schéma pour une ligne
   qui n'a jamais engagé personne.
3. Recréer le brouillon : « supprimer la vente » est elle-même un `DELETE`, et le problème se
   déplace d'un cran en s'aggravant.

## Décision

`GRANT DELETE ON sale_items TO coges_app`. Rien d'autre.

## Conséquences

- La liste de **T36** passe de trois à quatre tables, et reste une **égalité stricte** :
  `["role_permissions", "roles", "sale_items", "user_roles"]`. Une cinquième exception fera
  échouer la CI sans qu'on touche au test — c'est le but.
- Le droit est borné par `sale_items_no_change`, qui refuse `DELETE` dès que la vente n'est
  plus `draft` (voir [0023](0023-ecarts-assumes-au-paragraphe-8-7.md)). Une ligne de vente
  confirmée reste indestructible, y compris pour qui attaque la base directement.
- Ce qui se supprime est ce qui n'a **jamais** produit d'effet : pas de mouvement de stock, pas
  d'écriture financière, pas d'audit, pas d'événement. La traçabilité n'y perd rien parce qu'il
  n'y avait rien à tracer.
- Une vente, elle, ne se supprime pas : il n'existe ni `DELETE /sales/{id}`, ni suppression
  logique. Elle s'annule, avec un motif, et la trace reste.
