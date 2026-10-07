# 0063 — Liste de clients pour la vente

- **Date** : 2026-10-07
- **Phase** : 15 (lot 0, bug B3)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
Dans « Nouvelle vente », la liste des clients de `SearchCombobox` était en
`position: absolute` à l'intérieur d'une `Card` en `overflow-hidden` : la carte la
rognait. `searchCustomers` ne demandait que 8 clients et n'affichait ni téléphone ni
dette.

Le prompt de phase 15 demande, champ vide, « Client de passage », puis les clients
récents, puis l'ordre alphabétique. Chaque ligne doit montrer l'avatar, le nom, le
téléphone et « Doit X F ». Or le module Clients (Référentiel) ne peut lire ni les ventes
ni les dettes, puisque les dépendances ne vont que vers le bas.

## Options envisagées
1. **Une route dans Ventes qui assemble les façades (retenue).** Ventes dépend déjà de
   Clients et de Finance.
2. Assembler côté front avec `/customers`, `/debts` et `/sales` : plusieurs appels par
   page, et un tri « récents » approximatif.

## Décision
- **`GET /api/v1/sales/customer-choices?search=&page=&page_size=`** (50 par défaut, 100 au
  plus), permission `sales:create`.
  - Sans recherche, la page 1 commence par les 5 clients des dernières ventes confirmées,
    du plus récent au plus ancien. Viennent ensuite tous les autres par ordre
    alphabétique, sans doublon. La pagination porte sur cette suite alphabétique, et
    `total` compte les deux blocs.
  - Avec une recherche, c'est l'ordre de pertinence de l'ADR 0050, sans bloc récent.
  - Chaque ligne donne `id`, `name`, `phone`, `open_debt` (somme des dettes ouvertes,
    même définition que le plafond de crédit) et `recent`.
- **Façades ajoutées** :
  - `customers_service.get_many` et `list_customers(exclude_ids=…)` ;
  - `finance_service.open_balances_by_customer`, en une requête groupée ;
  - `SaleRepository.recent_customer_ids`.
- **Front.**
  - `components/ui/popover.tsx` (Radix, portail) et `components/sales/customer-picker.tsx`.
    Le rôle `combobox` et le nom accessible restent les mêmes.
  - Lignes de 64 px, chargement par pages de 50 au défilement (`useInfiniteQuery` et
    `IntersectionObserver`).
  - « Nouveau client » en bas de la liste ouvre `CustomerFormDialog`, déplacé dans
    `components/customers/`, puis revient à la vente avec ce client.
  - « Client de passage » reste un choix du front (`customer_id = null`).

## Conséquences
- Les autres utilisateurs de `SearchCombobox` (articles, dépenses, mouvements) ne
  changent pas. Ils sont dans des dialogues, qui ne rognent pas, ou dans une barre
  d'outils.
- Le formulaire de client reste le formulaire complet jusqu'au lot 1 (formulaire court).
- La numérotation des ADR du prompt de phase 15 est décalée d'un rang à partir d'ici :
  « Références et codes-barres générés » devient 0064, et ainsi de suite.
- Tests : `test_customer_choices.py` (ordre, pagination sans doublon, recherche), un test
  de fuite dans `tests/tenancy/test_read_filters_cross_tenant.py`, Vitest
  `customer-picker.test.tsx` (aucun ancêtre en `overflow: hidden`, ordre, dette, choix,
  « Nouveau client »), et l'e2e « 30 clients » dans `phase15-bugs.spec.ts`.
