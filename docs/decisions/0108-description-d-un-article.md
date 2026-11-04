# 0108 — Description d'un article

- **Date** : 2026-11-03
- **Phase** : groupe 1, bloc D (prompt 34, branche `feat/group1-d-product-description`)
- **Statut** : acceptée
- **Décideur** : propriétaire (champ décrit dans le prompt) ; recherche par la description
  écartée via AskUserQuestion le 2026-11-03, **puis demandée** par le propriétaire le
  2026-11-04 (correction avant fusion : distinguer deux articles de même nom)

## Contexte
Le commerçant veut noter sur un article ce que le nom ne dit pas (contenance, consigne,
origine). Le modèle V1.1 n'a pas de colonne pour cela.

## Options envisagées
1. **Colonne `products.description` facultative (retenue)** : révision 0035, `text NULL`,
   `CHECK (char_length(description) <= 500)`. Ajout seul, rétrocompatible (ADR 0083).
2. Recherche par la description **avec approximation** (trigramme, comme le nom) : écartée,
   un texte libre approchant ferait remonter dans la grille des articles inattendus.
3. Recherche par la description **en sous-chaîne simple (retenue le 2026-11-04)** : le
   vendeur tape « 1 kg » ou « rouge » ; jokers `%`, `_` et `\` neutralisés, même terme
   minimal (2 caractères) que la recherche actuelle. Sans index : quelques centaines
   d'articles par boutique, filtre déjà restreint au tenant.

## Décision
- **API** : `description` sur `ProductCreate` (donc aussi `POST /inventory/products`),
  `ProductUpdate` et `ProductRead`. Espaces de début et de fin retirés ; vide ou fait
  d'espaces = `null` ; 501 caractères ⇒ 422 sur le champ. En modification, un champ omis ne
  bouge pas, `""` ou `null` l'efface.
- **Import / export** : colonne « Description » juste après « Nom », facultative (un ancien
  fichier sans elle s'importe toujours), exportée avec le reste du référentiel (aller-retour
  fidèle, protection des formules de l'ADR 0045 comprise).
- **Écrans** : `DescriptionField` (`components/products/description-field.tsx`), multiligne,
  `maxLength` 500, compteur « 23 / 500 caractères » relié au champ, sous « Nom de
  l'article » dans « Nouvel article », dans la version courte de la livraison scannée (même
  formulaire, ADR 0106) et dans la modification. Fiche de l'article : sous le nom, retours à
  la ligne gardés.
- **Distinguer deux articles de même nom (2026-11-04)** : la description s'affiche sur une
  ligne tronquée sous le nom dans la liste du Stock, les tuiles et les résultats de Vendre,
  la ligne du ticket, et les propositions, les résultats et les lignes de la livraison (scan
  compris). `ProductHint` (`components/products/product-hint.tsx`) : texte complet dans le
  DOM (lecteur d'écran) et en infobulle (`title`) ; hors d'un bouton ou d'un lien (ticket,
  ligne de livraison), un toucher le déplie (`aria-expanded`). Dans une tuile ou une ligne
  du Stock, qui sont déjà un bouton ou un lien, le nom accessible porte la description
  (« Ajouter Huile, 5 litres ») et la fiche la montre en entier. Sans description, rien ne
  change (aucune ligne vide) ; deux homonymes **d'une même liste** sans description
  affichent leur référence (« Réf. ART-0012 ») : `productHints` (`lib/product-hint.ts`).
- **Recherche** : `GET /products?search=` et `GET /inventory/stock?search=` trouvent aussi
  la description (`text_contains`, `core/search.py`), après le code exact et le nom dans
  l'ordre de pertinence.
- **Lectures** : `description` sur `StockLine` et `ScannedProduct`, `product_description` sur
  `SaleItemRead`, par la façade `ProductSummary`.
- **Pas sur le reçu imprimé** dans ce lot (groupe 2).
- **Brouillons** (ADR 0101) : `description` entre dans les listes blanches `product-new` (et
  ses champs « significatifs ») et `product-edit`, sans changer de version (un ancien
  brouillon n'a simplement pas le champ).

## Conséquences
- `ProductSummary` (façade vers les autres modules) porte la description : Inventory et
  Sales la relaient à l'affichage, sans règle.
- Tests : `test_product_description.py` (recherche, jokers, stock, scan, ligne de vente,
  isolation), Vitest (`product-hint`, ticket), e2e `description.spec.ts` (deux « Huile »
  dans la grille, la recherche, le ticket, le Stock et la livraison, homonymes sans
  description, 360 px, axe clair et sombre).
- L'en-tête du modèle d'import change (`test_import_plain_headers`, `test_imports`).
