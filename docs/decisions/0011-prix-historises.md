# 0011 — Prix historisés : création, changement, audit

- **Date** : 2026-09-23
- **Phase** : 03
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le § 8.3 range le prix de vente et le coût dans `product_prices`, par intervalles
`[valid_from, valid_to)`, avec `product_prices_no_overlap EXCLUDE USING gist`. Le modèle ne dit
ni comment un prix change, ni si un produit peut exister sans prix, ni qui est `created_by`.

## Décision

**1. Prix initial obligatoire.** `POST /api/v1/products` crée la fiche **et** son premier
intervalle dans la même transaction ; `unit_price` est requis, `cost_price` optionnel. Un
produit sans prix ne serait pas vendable : Sales n'aurait rien à figer sur sa ligne, et
`assert_sellable` devrait gérer un cas dégradé permanent.

**2. Changement de prix = fermeture + ouverture, en une transaction.**
`POST /api/v1/products/{id}/prices` exécute un `UPDATE … SET valid_to = now()` sur l'intervalle
ouvert, puis l'`INSERT` du nouveau, dont le `valid_from` vaut le `DEFAULT now()`. Les deux
`now()` sont évalués **par PostgreSQL** et valent l'instant de début de transaction : l'ancien
prix s'arrête exactement là où le nouveau commence, sans trou ni recouvrement, sans dépendre de
l'horloge du serveur d'application. Aucune modification en place : une ligne de
`product_prices` ne se corrige pas, elle se ferme.

**3. Audit critique à chaque prix.** Création comme changement écrivent une ligne d'audit dans
la transaction, avec l'ancien et le nouveau montant. Le prix est une donnée financière : le
canal critique est exigé par l'architecture (§ audit critique).

**4. `created_by` toujours renseigné.** Le § 8.3 laisse la colonne nullable ; l'API y met
systématiquement l'utilisateur du contexte. Un changement de prix sans auteur identifiable n'a
aucune valeur d'enquête. La colonne reste nullable en base pour les reprises de données.

**5. `EXCLUDE` repris tel quel.** La contrainte porte sur `product_id` seul, sans `company_id`.
`product_id` est globalement unique (clé primaire de `products`) : ajouter `company_id` ne
changerait rien. Deux changements de prix concurrents sur le même produit tombent dessus ; le
perdant reçoit `price_change_conflict` (409), traduit depuis le SQLSTATE `23P01`.

## Conséquences

- `ProductRead` expose `unit_price` et `cost_price` en **jointure** sur l'intervalle ouvert.
  Aucune colonne de prix n'existe sur `products`, et la liste paginée lit les prix courants en
  une seule requête (`prices_current`), pas en N+1.
- La façade `products.service` expose `get_current_price`, `get_tax_rate`, `is_stock_tracked`
  et `assert_sellable`, qui renvoient des schémas (`CurrentPrice`) et non des modèles : Sales
  et Inventory n'importeront jamais `products.models`.
- `get_current_price` lève `product_not_priced` plutôt que de renvoyer zéro : une vente à un
  prix inventé serait pire qu'une vente refusée.
- Une suppression logique de produit **conserve** tout son historique de prix : les ventes
  passées y renvoient.
- Reste ouvert pour une phase ultérieure : un prix **programmé** (`valid_from` futur). L'EXCLUDE
  le permettrait déjà ; l'API ne l'expose pas, faute de besoin V1.
