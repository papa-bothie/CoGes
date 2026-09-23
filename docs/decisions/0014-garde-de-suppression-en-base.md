# 0014 — Une règle qu'un module n'a pas le droit de vérifier descend en base

- **Date** : 2026-09-23
- **Phase** : 03
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le périmètre de la phase 03 exige : « suppression logique d'une catégorie refusée si elle
contient des produits actifs ou des sous-catégories ». Mais le tableau des dépendances du
Diagramme 3 donne à **Categories aucune dépendance** — c'est Products qui dépend de Categories.
Le module `categories` n'a donc pas le droit d'interroger `products`, ni par ses modèles, ni par
sa façade sans créer un couple mutuel.

## Options envisagées

1. **Trigger en base (retenue)** : l'invariant ne dépend d'aucun module et tient contre une
   écriture directe.
2. Registre de gardes dans `core/` : respecte le sens des dépendances, mais invisible dans le
   SQL et inopérant hors API.
3. Dépendance assumée `categories → products` : contredit l'architecture et crée un cycle.

## Décision

La migration 0003 crée `categories_guard_soft_delete()`, trigger `BEFORE UPDATE` déclenché par
la seule transition `deleted_at IS NULL → NOT NULL`. Il refuse la suppression avec deux
SQLSTATE applicatifs distincts, que le service traduit en erreurs métier :

| SQLSTATE | Code métier | Cause |
|---|---|---|
| `CG001` | `category_has_children` | sous-catégorie vivante |
| `CG002` | `category_not_empty` | produit actif rattaché |

`app.core.errors.sqlstate(exc)` extrait le code : le SQLSTATE est stable, contrairement au texte
du message, qui dépend de la locale du serveur.

Le service `categories` garde en plus un contrôle applicatif des **sous-catégories**, pour rendre
la main sans toucher la base et donner un message immédiat. C'est une redondance assumée, dans
l'esprit du § 2.3 du modèle (stock négatif : `CHECK` **et** `RAISE` dans le trigger). Le trigger
reste l'autorité.

## Conséquences

- Un test attaque l'`UPDATE` brut en `coges_app` et vérifie le SQLSTATE : la règle ne vaut pas
  que pour les appelants polis (exigence du § 10).
- La garde porte sur les produits **actifs** (`is_active AND deleted_at IS NULL`), conformément
  au périmètre de la phase. Un produit désactivé mais vivant n'empêche donc pas la suppression
  de sa catégorie ; s'il est réactivé plus tard, il pointera une catégorie supprimée. C'est
  acceptable en V1 — la fiche produit affiche alors une catégorie vide — et se resserrerait en
  retirant `AND p.is_active` du trigger.
- `RAISE EXCEPTION 'texte' USING MESSAGE = …` est refusé par PL/pgSQL (`42601`, « RAISE option
  already specified ») : le message passe **uniquement** par `USING MESSAGE`.
- Le modèle de suppression gardée est réutilisable : toute règle inter-modules que le sens des
  dépendances interdit descendra en base de la même façon.
