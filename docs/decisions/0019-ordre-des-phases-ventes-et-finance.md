# 0019 — La confirmation est atomique, donc la finance arrive avec les ventes

- **Date** : 2026-09-24
- **Phase** : 05
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`) — point ouvert **P6**

## Contexte

Le § 12 du Modèle de données recommande de développer « (4) ventes, confirmation,
annulation » **puis** « (6) dettes et paiements ». Or le § 5.1 place l'écriture dans `payments`
et `debts` à l'étape 7 de la confirmation, et le Diagramme 4 aux étapes 07-08 — **dans la même
transaction**. Les deux textes ne peuvent pas être suivis ensemble : sans ces tables, la
confirmation n'est pas atomique, et c'est précisément ce que l'architecture promet.

S'y ajoute une contrainte mécanique : `payments` référence `expenses` et `sale_returns`, et
`debts` référence `expenses`. On ne peut pas créer `payments` sans créer aussi ces tables.

## Options envisagées

1. **Tables complètes, services partiels (retenue)** : la révision 0006 crée **toutes** les
   tables du § 8.4 et du § 8.6 avec les triggers du § 8.7, les index du § 8.10 et la RLS du
   § 8.11. La phase 05 n'implémente que les services de vente et une façade Finance minimale.
2. Tout implémenter maintenant : la phase absorberait les retours, les allocations, les
   remboursements et les dépenses — c'est-à-dire les phases 06 et 07.
3. Confirmation sans volet financier jusqu'en phase 07 : la transaction de référence de
   l'architecture serait livrée amputée de ce qui la rend intéressante, et T24 comme le
   scénario de démonstration deviendraient intestables.

## Décision

La structure arrive entière, les services arrivent par phases. Une table sans service n'est pas
un demi-travail : c'est une contrainte déjà posée, que les phases suivantes ne pourront plus
contredire.

## Conséquences

- **Un seul module `finance/`**, et non `payments/` + `debts/` comme le Diagramme 3 les
  distingue. Les deux tables ne se séparent pas : une dette se solde par un paiement, un
  paiement s'impute sur une dette. Deux modules quasi vides avec une dépendance mutuelle
  auraient été une frontière décorative. `finance/` n'a **pas de `router.py`** en phase 05 :
  elle n'est appelée que par Sales, et une façade sans endpoint est une information utile.
- `expense_categories` et `expenses` existent sans modèle Python jusqu'à la phase 07 ; les
  triggers de retour et de remboursement du § 8.7 sont posés et inertes jusqu'à la phase 06.
- Les phases 06 et 07 n'auront **aucune migration structurante** à écrire : elles ajoutent des
  services sur des tables déjà contraintes et déjà sous RLS.
- Le harnais de fuite ne couvre que les tables que la phase 05 sait semer (`sales`,
  `sale_items`, `payments`, `debts`, `document_counters`). Les six autres entreront dans
  `TENANT_TABLES` avec les phases qui leur donneront des lignes ; leur RLS est déjà vérifiée
  par **T37**, qui est générique.
