# 0010 — Gabarit d'un module métier

- **Date** : 2026-09-23
- **Phase** : 03
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`), module `categories` présenté puis validé

## Contexte

La phase 03 est le premier ensemble de modules métier. `CLAUDE.md` impose le découpage
`router · service · repository · models · schemas · events`, et la décision 01 de
l'architecture impose qu'un module expose une **façade de services** et garde ses modèles
privés. Restaient à fixer : où vivent les invariants, comment se nomment les erreurs, ce que
devient `events.py` pour un module qui n'émet rien.

## Décision

**1. Six fichiers, dont `events.py` seulement s'il y a des événements.** Les neuf types
d'événements de la V1 sont une liste fermée ; aucun ne concerne le référentiel. Les quatre
modules de la bande B n'ont donc pas de `events.py`. Un fichier vide dans quatre modules
aurait appris à ne pas lire les `events.py`.

**2. Répartition sans exception.**

| Couche | Contenu | Ce qu'on n'y trouve jamais |
|---|---|---|
| `router.py` | permission, pagination, validation d'entrée, mapping schéma | SQL, règle métier |
| `service.py` | erreurs métier, invariants, `flush`, audit critique | HTTP, requête construite à la main |
| `repository.py` | `_live()`, filtres, pagination, jointures | décision métier |
| `models.py` | colonnes, rien d'autre | relation vers un autre module |
| `schemas.py` | formes d'entrée et de sortie, bornes de saisie | accès base |

**3. Erreurs métier nommées.** `app/core/errors.py` gagne `BusinessRuleError` (HTTP **409**).
Chaque module déclare **une classe par règle**, en tête de son `service.py`, avec son code
stable en anglais et son message en français : `category_not_empty`, `product_sku_taken`,
`customer_code_taken`… `CLAUDE.md` exige des codes métier stables ; la phase 02 renvoyait
`validation_failed` pour tout, ce qui ne permet pas au client de réagir à la règle précise.
409 et non 422 : la donnée envoyée est valide, c'est l'état du système qui refuse.

**4. Bornes de saisie dans le schéma, autorité dans la base.** Chaque `CHECK` du § 8.3 est
doublé d'une contrainte Pydantic (`0 ≤ default_tax_rate < 1`, `unit_price > 0`,
`credit_limit ≥ 0`, `payment_terms_days` entre 0 et 365, noms rognés puis mesurés). Le client
reçoit un 422 qui nomme le champ au lieu d'un 500 sur violation de contrainte ; la base reste
le dernier mot pour qui n'entre pas par l'API.

**5. Lectures filtrées, suppression logique partout.** Tout repository part de `_live()`
(tenant + `deleted_at IS NULL`). Aucune suppression physique : `coges_app` n'a pas le droit
`DELETE`.

**6. Tests d'un module.** Une suite d'intégration par module, plus l'extension du **harnais de
fuite** (`TENANT_TABLES`, fabriques, `own_row_ids`) qui rend T1, T2, T36 et T37 automatiques
sur les nouvelles tables, plus l'inscription des routes paramétrées au registre de
`test_route_cross_tenant.py` — non inscrite, la route casse la CI.

## Conséquences

- Les phases 04 à 09 copient ce gabarit sans discussion ; toute exception devra être un ADR.
- Une règle métier qu'un module n'a pas le droit de vérifier descend en base (voir
  [0014](0014-garde-de-suppression-en-base.md)).
- `app/core/` accueille désormais ce qui est technique et partagé par plusieurs modules :
  `search.py` (prédicats de recherche), `codes.py` (numérotation des tiers), `errors.sqlstate`.
- **Découvert en implémentant** : après un `flush()` refusé par PostgreSQL, la transaction est
  morte et tout accès à un attribut expiré d'un objet ORM émet une requête qui échoue à son
  tour. Les identifiants utilisés dans le message d'erreur sont donc **capturés avant** le
  `flush` risqué. À reprendre dans tout service qui traduit une erreur de la base.
