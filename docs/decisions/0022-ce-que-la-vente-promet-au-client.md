# 0022 — TVA, reçu, et pourquoi la confirmation n'est pas idempotente

- **Date** : 2026-09-24
- **Phase** : 05
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Trois questions que le § 5.1 laisse ouvertes, et qui décident ensemble de ce qu'un client voit
et peut opposer à l'entreprise.

## Décision 1 — TVA : le paramètre d'entreprise l'emporte, et son absence vaut « activée »

Le § 4.5 fait copier `tax_rate` depuis `products.default_tax_rate` à la confirmation. Le
périmètre V1 dit « taxes **si activées pour l'entreprise** », mais `tax_enabled` n'est pas une
colonne : il vit dans `companies.settings`, un JSONB qui vaut `{}` à la création.

`companies.service.is_tax_enabled()` lit `settings.get("tax_enabled", True)`. Absent ⇒ **taxes
actives**. Le vrai interrupteur est déjà ailleurs : `products.default_tax_rate` vaut 0 par
défaut, si bien qu'une entreprise non assujettie ne taxe rien sans avoir rien à paramétrer.
`tax_enabled: false` devient alors un geste explicite, qui force 0 **même sur un produit à
18 %** — et aucune entreprise déjà créée n'a besoin d'être reprise.

Le taux figé ne bouge plus jamais : activer la TVA plus tard ne recalcule aucune vente passée
(**T23**), et la désactiver n'efface aucune taxe déjà facturée.

## Décision 2 — Le reçu est un JSON, pas un document

`GET /api/v1/sales/{id}/receipt` renvoie tout ce qu'un reçu contient — entreprise, client,
lignes figées, totaux, règlements, solde — et le frontend le met en page. Ni PDF ni HTML côté
API : `CLAUDE.md` veut un frontend qui n'appelle que REST, et un rendu serveur imposerait une
dépendance de mise en page, un stockage de fichiers et de l'asynchrone que la phase 08 n'a pas
encore apporté.

Le reçu est refusé sur un **brouillon** (`sale_not_confirmed`) : il atteste d'une transaction
qui a eu lieu. Une vente **annulée** en garde un, au contraire — c'est la pièce qui explique
pourquoi le client est reparti sans rien.

Tout y est figé, sauf le libellé du produit et son SKU, relus au référentiel : un nom n'est pas
un montant. Le reçu d'une vente de l'an dernier reste donc exact après n'importe quel
changement de tarif.

## Décision 3 — Un second `confirm` est un conflit, pas une confirmation

`POST /sales/{id}/confirm` sur une vente déjà confirmée rend **409 `sale_not_draft`**.

Un 200 idempotent serait plus confortable côté réseau, mais il masquerait le seul cas qui
compte : deux caissiers confirmant la même vente avec deux règlements différents. Tous deux
recevraient un 200, et le second règlement disparaîtrait sans que personne ne l'apprenne.
L'idempotence réelle est ailleurs, en base : `inv_ref_idempotence` empêche de sortir deux fois
le stock d'une même ligne (**T17**), et le `FOR UPDATE` sur la vente sérialise les deux
caisses.

## Conséquences

- La clé d'idempotence des écritures financières (point ouvert **P4**) n'est pas nécessaire ici :
  l'état `draft` **est** la clé. Elle reste à trancher pour `POST /payments`, en phase 07.
- `settings` reste libre de forme. Si d'autres paramètres sensibles s'y ajoutent, chacun devra
  décider de son défaut avec le même critère : que se passe-t-il pour une entreprise qui n'a
  rien paramétré ?
