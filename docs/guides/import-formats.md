# Formats d'import (phase 10, ADR 0041)

`POST /api/v1/imports/{type}` accepte un fichier **CSV** (séparateur `;`, `,` ou
tabulation ; UTF-8 ou Windows-1252) ou **Excel .xlsx** (première feuille). Au plus
5 000 lignes et 4 Mo par fichier. `GET /api/v1/imports/{type}/template` rend un modèle vide.

Déroulé : envoyer avec `?dry_run=true` pour lire le rapport, corriger, renvoyer **le même
fichier** sans `dry_run`. L'import est **tout ou rien** : une seule ligne fautive et rien
n'est écrit (422 `import_invalid`, rapport dans `error.details`). En-tête `Idempotency-Key`
obligatoire.

Les en-têtes sont comparés sans casse, sans accents, sans ponctuation et sans petits mots :
`Prix de vente`, `prix_vente` et `PRIX VENTE` désignent la même colonne. Les nombres
acceptent `1 234,50`, `1.234,50` et `1234.50` ; un taux accepte `18 %` ou `0,18`. Les
booléens : `oui` / `non` (ou `vrai`/`faux`, `1`/`0`). Un export du même référentiel
(`GET /api/v1/exports/referentials/{type}`) produit exactement ces colonnes : il se réimporte
tel quel.

## categories

| Colonne | Obligatoire | Contenu |
|---|---|---|
| `nom` | oui | nom de la catégorie |
| `parent` | non | nom d'une catégorie existante ou d'une ligne **précédente** du fichier |

## products

| Colonne | Obligatoire | Contenu |
|---|---|---|
| `sku` | oui | code article, unique dans l'entreprise (mis en majuscules) |
| `nom` | oui | désignation |
| `prix_vente` | oui | premier prix de vente, > 0 (`product_prices`) |
| `categorie` | non | nom d'une catégorie existante, non ambigu |
| `unite` | non | `piece`, `kg`, `litre`, `carton`, `metre`, `paquet` (et leurs écritures usuelles) |
| `code_barres` | non | unique dans l'entreprise |
| `taux_taxe` | non | de 0 à < 1, ou en pourcentage |
| `prix_achat` | non | coût d'achat indicatif |
| `seuil_reappro` | non | seuil de stock bas |
| `suivi_stock` | non | `oui` par défaut |
| `stock_initial` | non | quantité ; crée un mouvement `initial` (façade Inventory) |
| `cout_unitaire` | si `stock_initial` | coût du stock initial (à défaut, `prix_achat`) : fixe le CMP |

## customers

| Colonne | Obligatoire | Contenu |
|---|---|---|
| `nom` | oui | |
| `code` | non | généré (`CLI-0001`…) si absent |
| `telephone` | non | |
| `email` | non | |
| `plafond_credit` | non | montant ≥ 0 |

## suppliers

| Colonne | Obligatoire | Contenu |
|---|---|---|
| `nom` | oui | |
| `code` | non | généré (`FRN-0001`…) si absent |
| `telephone` | non | |
| `delai_paiement_jours` | non | entier |

## Codes d'erreur du rapport

`required`, `missing_column`, `invalid_value` (message du validateur), `duplicate_in_file`,
`category_not_found`, `category_ambiguous`, `initial_cost_required`,
`initial_stock_untracked`, ainsi que les refus des modules (`product_sku_taken`,
`product_barcode_taken`, `customer_code_taken`, `supplier_code_taken`,
`category_name_taken`…) et `rejected_by_database`.

Les ventes historiques ne s'importent pas en V1.
