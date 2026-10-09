# Formats d'import (phase 10, ADR 0041)

`POST /api/v1/imports/{type}` accepte un fichier **CSV** (séparateur `;`, `,` ou
tabulation ; UTF-8 ou Windows-1252) ou **Excel .xlsx** (première feuille). Au plus
5 000 lignes et 4 Mo par fichier. `GET /api/v1/imports/{type}/template` rend un modèle vide.

Déroulé : envoyer avec `?dry_run=true` pour lire le rapport, corriger, renvoyer **le même
fichier** sans `dry_run`. L'import est **tout ou rien** : une seule ligne fautive et rien
n'est écrit (422 `import_invalid`, rapport dans `error.details`). En-tête `Idempotency-Key`
obligatoire.

Les en-têtes sont des **mots simples** (phase 15, ADR 0069), comparés sans casse, sans
accents, sans ponctuation et sans petits mots : `Prix de vente`, `prix_vente` et
`PRIX VENTE` désignent la même colonne. Les anciens en-têtes techniques restent reconnus
(colonne « Ancien nom » ci-dessous) : un fichier préparé avant la phase 15 s'importe
toujours. Le rapport d'erreurs nomme la colonne par son mot. Les nombres
acceptent `1 234,50`, `1.234,50` et `1234.50` ; un taux accepte `18 %` ou `0,18`. Les
booléens : `oui` / `non` (ou `vrai`/`faux`, `1`/`0`). Un export du même référentiel
(`GET /api/v1/exports/referentials/{type}`) produit exactement ces colonnes : il se réimporte
tel quel. L'export des ventes (`Vente n°`, `Date`, `Statut`, `Client`, `Sous-total`,
`Remise`, `Taxes`, `Total`, `Payé`, `Retourné`) ne se réimporte pas.

**Formules neutralisées (ADR 0045).** Un export ne contient jamais de formule. En CSV, un
texte qui commence par `=`, `+`, `-`, `@`, une tabulation ou un retour chariot est précédé
d'une apostrophe (`'=SOMME(A1)`, `'+221 77 …`). En .xlsx, tout texte est une cellule de type
texte, sans apostrophe visible. À l'import, une apostrophe suivie de l'un de ces caractères
est retirée : l'aller-retour export → import rend la valeur d'origine.

## categories

| Colonne | Ancien nom | Obligatoire | Contenu |
|---|---|---|---|
| `Nom` | `nom` | oui | nom de la catégorie |
| `Parent` | `parent` | non | nom d'une catégorie existante ou d'une ligne **précédente** du fichier |

## products

| Colonne | Ancien nom | Obligatoire | Contenu |
|---|---|---|---|
| `Référence` | `sku` | non | unique dans l'entreprise (mis en majuscules) ; générée (`ART-0001`…) si vide (ADR 0066) |
| `Nom` | `nom` | oui | désignation |
| `Prix de vente` | `prix_vente` | oui | premier prix de vente, > 0 (`product_prices`) |
| `Catégorie` | `categorie` | non | nom d'une catégorie existante, non ambigu |
| `Unité` | `unite` | non | `piece`, `kg`, `litre`, `carton`, `metre`, `paquet`, `sac`, `bouteille` (et leurs écritures usuelles) |
| `Code-barres` | `code_barres` | non | unique dans l'entreprise |
| `TVA` | `taux_taxe` | non | de 0 à < 1, ou en pourcentage ; à défaut, la TVA par défaut de l'entreprise |
| `Prix d'achat` | `prix_achat` | non | prix d'achat indicatif |
| `Seuil d'alerte` | `seuil_reappro` | non | seuil de stock bas |
| `Suivi du stock` | `suivi_stock` | non | `oui` par défaut |
| `Stock initial` | `stock_initial` | non | quantité ; crée un mouvement `initial` (façade Inventory) |
| `Coût unitaire` | `cout_unitaire` | si `Stock initial` | coût du stock initial (à défaut, `Prix d'achat`) : fixe le prix d'achat moyen |

## customers

| Colonne | Ancien nom | Obligatoire | Contenu |
|---|---|---|---|
| `Nom` | `nom` | oui | |
| `Code` | `code` | non | généré (`CLI-0001`…) si absent |
| `Téléphone` | `telephone` | non | |
| `E-mail` | `email` | non | |
| `Plafond de crédit` | `plafond_credit` | non | montant ≥ 0 |

## suppliers

| Colonne | Ancien nom | Obligatoire | Contenu |
|---|---|---|---|
| `Nom` | `nom` | oui | |
| `Code` | `code` | non | généré (`FRN-0001`…) si absent |
| `Téléphone` | `telephone` | non | |
| `Délai de paiement (jours)` | `delai_paiement_jours` | non | entier |

## Codes d'erreur du rapport

`required`, `missing_column`, `invalid_value` (message du validateur), `duplicate_in_file`,
`category_not_found`, `category_ambiguous`, `initial_cost_required`,
`initial_stock_untracked`, ainsi que les refus des modules (`product_sku_taken`,
`product_barcode_taken`, `customer_code_taken`, `supplier_code_taken`,
`category_name_taken`…) et `rejected_by_database`.

Les ventes historiques ne s'importent pas en V1.
