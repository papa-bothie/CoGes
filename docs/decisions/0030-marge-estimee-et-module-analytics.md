# 0030 — La marge se calcule dans un module de restitution, pas dans Finance

- **Date** : 2026-09-24
- **Phase** : 07
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le prompt de la phase demandait `GET /api/v1/finance/overview` rendant, entre autres, le CA net,
le coût des ventes, la marge brute et le résultat estimé. Ces quatre mesures se calculent sur
`sales`, `sale_items` et `sale_return_items`.

Or `CLAUDE.md` impose des dépendances **descendantes** (Opérations → Finance) et `sales`
importe déjà `finance.service` depuis la phase 05. Finance ne peut donc pas appeler Sales : ce
serait un cycle, et le rendre possible par un import tardif n'aurait fait que le cacher.

Trois issues étaient possibles, et le choix est structurant pour la phase 08.

## Options envisagées

1. **Un module `analytics/` de bande E (retenue)** : lecture seule, aucune table, aucun modèle,
   aucun repository. Il appelle les façades de Sales, Finance, Expenses et Companies. C'est le
   seul sens que l'ordre des dépendances autorise, et c'est la place que le Diagramme 3 donne à
   Analytics — « lecture seule : Sales, Inventory, Finance ».
2. **Finance lit les tables de vente en SQL brut** : l'URL restait `/finance/overview` et aucun
   module n'était créé, mais Finance aurait dépendu du **schéma** de Sales sans qu'aucun test ne
   le voie — le test d'architecture n'inspecte que les imports Python. Une frontière qui s'érode
   sans bruit est pire qu'une frontière déplacée.
3. **Overview réduit à ce que Finance possède** : trésorerie, créances, dettes. Aucun écart, mais
   la marge — demandée au § 1 du prompt — n'aurait pas été livrée par cette phase.

## Décision

Le module `analytics/` est créé, et l'endpoint devient **`GET /api/v1/analytics/overview`**.
Sales expose `revenue_totals()`, Expenses `totals_by_kind()`, Finance `cash_summary()`,
`daily_cash()` et `open_debt_totals()`, Companies `get_timezone()`. Analytics compose, et ne
calcule rien lui-même.

## Décision 2 — Les définitions du § 4.10, à la lettre

    gross_revenue     = Σ qty × unit_price                   (ventes confirmed)
    discount_total    = Σ discount
    refund_net_amount = Σ (refund_amount − tax_refund)
    net_revenue       = gross_revenue − discount_total − refund_net_amount
    cogs_gross        = Σ qty × unit_cost                    (CMP figé à la vente)
    cogs_returned     = Σ returned_qty × unit_cost
    cogs_net          = cogs_gross − cogs_returned
    marge brute       = net_revenue − cogs_net
    résultat estimé   = marge brute − dépenses de la période

Tout est **hors taxe** ; `tax_total` est rendu à part, car une taxe collectée n'a jamais été un
revenu (§ 4.10). Les retours sont rattachés au jour de la **vente d'origine**, jamais au leur :
la période porte sur `sales.sold_at`. Les ventes annulées et les brouillons sont exclus.

Ce n'est pas un résultat comptable : ni amortissement, ni provision, ni charge à payer. C'est la
question du gérant, pas celle de son expert-comptable (décision 09).

## Décision 3 — Calcul direct maintenant, agrégats en phase 08

Les chiffres sont agrégés sur le transactionnel, avec les index déjà posés
(`payments_dir`, `expenses_recent`, `sales_confirmed`) et une plage **obligatoire** bornée à
366 jours. La phase 08 remplacera la source par `daily_sales_facts` sans changer le contrat, et
l'écart entre les deux deviendra le test **T32**.

## Conséquences

- **Deux requêtes pour le revenu, jamais une jointure unique.** Agréger les lignes de vente et
  leurs retours ensemble dupliquerait chaque ligne autant de fois qu'elle a été retournée —
  c'est exactement la surestimation que la V1.1 corrige en pré-agrégeant les retours (§ 6.1), et
  le même piège attendait ici.
- **La trésorerie exclut `method = 'offset'`.** C'est la dette nommée que l'ADR 0024 laissait à
  cette phase, et elle est réglée en un seul endroit : `PaymentRepository.cash_totals`. Un test
  le vérifie — après compensation d'un retour, `cash_in` et `cash_out` n'ont pas bougé.
- **La série journalière est convertie dans le fuseau de l'entreprise.** `paid_at` est en UTC,
  mais une caisse ferme à l'heure locale : sans conversion, un encaissement de 23 h tomberait le
  lendemain. Les jours creux sont rendus à zéro plutôt qu'omis — une courbe trouée se lit comme
  une absence de données, pas comme une caisse immobile.
- **Permission `analytics:read`**, et non `dashboard:read` : le vendeur possède la seconde. Une
  caisse encaisse, elle n'a pas à lire la marge de l'entreprise.
- La phase 08 hérite d'un module déjà en place : elle y ajoutera les agrégats et le dashboard,
  sans déplacer d'endpoint.
