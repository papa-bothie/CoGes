# 0016 — Coût d'un ajustement positif : le CMP courant par défaut

- **Date** : 2026-09-23
- **Phase** : 04
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le § 8.5 impose `unit_cost NOT NULL CHECK (unit_cost >= 0)` et refuse explicitement toute entrée
sans coût : « Entrée de stock sans coût unitaire : CMP indéfinissable ». Pour une réception, le
coût d'acquisition est connu. Pour un **ajustement positif** — l'inventaire trouve dix cartons de
plus que le registre — il n'y a pas d'achat, donc pas de coût à saisir.

L'architecture ne tranche pas ce cas.

## Options envisagées

1. **CMP courant par défaut, surchargeable (retenue)** : retrouver de la marchandise déjà
   valorisée ne change pas sa valeur. `cmp_next_avg(q, a, d, a)` laisse la moyenne inchangée.
2. Coût saisi obligatoire : plus explicite, mais déforme le CMP dès que la valeur saisie est
   approximative, et alourdit un geste d'inventaire courant.
3. Dernier `cost_price` de `product_prices` : cohérent avec le tarif d'achat, mais ce coût est un
   **tarif fournisseur**, pas la valeur du stock détenu. Il déformerait le CMP à chaque ajustement.

## Décision

`unit_cost` est **facultatif** sur un ajustement positif. Sans saisie, `service._entry_unit_cost`
lit `product_stock.avg_cost` et l'utilise : le CMP reste inchangé. Le gérant peut le surcharger
s'il connaît le coût réel de la marchandise retrouvée.

Si le produit n'a **aucun** CMP à reprendre (première écriture, ou stock durablement à zéro avec
`avg_cost = 0`), le service lève `unit_cost_required` (409) plutôt que d'entrer une marchandise à
zéro : une valeur inventée serait pire qu'un refus.

## Conséquences

- Le schéma exige toujours `unit_cost` sur `initial` et `purchase_in` : ce sont de vraies entrées,
  leur coût existe. Seul `adjustment` positif en est dispensé.
- Le schéma **refuse** `unit_cost` sur une sortie : le coût d'une sortie est le CMP applicable,
  estampillé par `t20_inv_apply`. Il se constate, il ne se saisit pas.
- Aucun CMP n'est calculé en Python, ici comme ailleurs : le service ne fait que **relire** une
  valeur existante et la passer à la base, qui applique `cmp_next_avg`.
- Tout ajustement, positif ou négatif, exige un **motif écrit** et passe en audit critique : c'est
  la seule écriture de stock qui ne découle d'aucun flux métier (Architecture technique, liste des
  opérations à audit critique).
