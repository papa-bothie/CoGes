# 0028 — Les dépenses sont un module, leur nature vit sur la catégorie, et elles sont numérotées

- **Date** : 2026-09-24
- **Phase** : 07
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le Diagramme 3 distingue quatre modules de bande D — Finance, Payments, Debts, Expenses — mais
l'ADR 0019 avait tranché « un seul module `finance/` » en phase 05, au motif qu'une dette et un
paiement ne se séparent pas. Restait à savoir ce qu'on faisait des dépenses, qui n'avaient encore
ni modèle Python, ni service, ni route.

Deux détails s'y sont ajoutés en regardant le § 8.6 de près.

## Décision 1 — `finance/` + `expenses/`, et non quatre modules

`finance/` garde les paiements, les dettes et les lettrages ; **`expenses/` devient un module à
part**, qui ne dépend que de `finance/` et de `suppliers/`, et dont personne ne dépend.

La frontière est réelle, contrairement à celle qu'aurait produit la séparation
`payments/` / `debts/` : une charge a son propre cycle de vie — elle se constate, se corrige, se
supprime logiquement — et ne partage aucune table avec les versements. Éclater `finance/` aurait
en revanche imposé de déplacer les modèles et les services déjà écrits en 05 et 06, et de
réécrire les imports de `sales/`, pour une frontière que l'ADR 0019 avait jugée décorative.

Le règlement d'une dépense n'appartient donc **pas** à `expenses/` : c'est
`POST /payments` avec `expense_id` et `direction = "outflow"`.

## Décision 2 — `kind` reste sur la catégorie

Le § 8.6 porte `expense_kind` (`fixed` / `variable`) sur `expense_categories`, pas sur
`expenses`. On suit le schéma : un loyer est fixe parce que c'est un loyer, pas parce qu'on l'a
coché. La dépense hérite de la nature de sa famille, et l'overview ventile par jointure.

Conséquence assumée et testée : **la nature d'une catégorie ne change plus dès qu'elle porte des
charges vivantes** (`expense_category_in_use`, 409). Autoriser ce changement réécrirait le passé
— une charge classée variable en janvier deviendrait fixe rétroactivement, et la ventilation de
tous les mois déjà présentés changerait. La sortie est de créer une nouvelle catégorie.

Aucune charge récurrente automatisée en V1. L'architecture cite les « charges récurrentes » dans
la responsabilité du module, mais aucune table ne les porte et le périmètre Finance V1 ne les
liste pas. L'écran de la phase 13 proposera « dupliquer le mois précédent », qui est un
formulaire pré-rempli, pas un job.

## Décision 3 — `expenses.expense_no`, écart assumé au § 8.6

L'ADR 0021 avait rendu `document_counters` générique et réservé le préfixe `D` pour les
dépenses, en annonçant qu'elles n'auraient « ni migration ni code de numérotation à écrire ».
C'était vrai pour le compteur, faux pour la colonne : le § 8.6 ne donne à `expenses` aucun
endroit où ranger le numéro. La révision 0009 ajoute `expense_no text NOT NULL` et
`UNIQUE (company_id, expense_no)`, symétriques de `sales.sale_no` et `sale_returns.return_no`.

Sans cette colonne, le compteur et le préfixe déjà livrés seraient restés morts.

## Conséquences

- La colonne est `NOT NULL` sans valeur par défaut : aucun service n'écrivait `expenses` avant
  cette révision, la table est donc vide. Si elle ne l'était pas, l'`ALTER` échouerait — c'est le
  bon comportement, et non un silence.
- Le numéro est consommé même par une dépense supprimée logiquement : ce qui est continu, c'est
  la suite des **pièces émises**, comme pour les ventes (ADR 0021).
- `expense.created` trouve enfin son émetteur, et porte `kind` dans son corps : l'analytique de
  la phase 08 ventile fixe/variable sans relire `expense_categories`.
- **Le `CHECK (spent_at <= current_date + 1)` est doublé dans le schéma Pydantic.** Il ne l'était
  pas dans la première version, et un test l'a révélé : la contrainte sortait en 500 au lieu d'un
  422 qui nomme le champ. La tolérance d'un jour est reprise telle quelle — elle absorbe l'écart
  entre le fuseau de l'entreprise et l'UTC du serveur.
