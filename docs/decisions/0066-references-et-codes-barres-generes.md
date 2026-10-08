# 0066 — Références et codes-barres générés

- **Date** : 2026-10-08
- **Phase** : 15 (lot 1)
- **Statut** : acceptée
- **Décideur** : utilisateur (prompt de phase 15, lot 1 ; plan validé le 2026-10-08)

## Contexte
Le formulaire de création d'un article demandait une référence (SKU) et un code-barres
que le commerçant ne connaît pas. Le prompt de phase 15 veut qu'on ne demande « que ce que
le commerçant sait déjà, le reste est déduit ou généré ». Il demande aussi le stock
d'ouverture (« Combien en avez-vous ? ») dans le même formulaire. Or Articles (bande B) ne
peut pas appeler Stock (bande C).

## Options envisagées
Pour la référence et le code-barres :
1. **Plus grand compteur de l'entreprise + index unique (retenue).** C'est le mécanisme
   des codes clients (ADR 0013), sans nouvelle table.
2. Un compteur dans `document_counters` : il est fait pour les suites sans trou (ADR
   0021), ce qu'une référence n'exige pas.

Pour le stock d'ouverture :
1. **Une route du module Stock qui compose la façade d'Articles (retenue)** : une seule
   transaction.
2. Deux appels depuis le front : un article pouvait rester sans stock si le second
   échouait.

## Décision
- **`sku` facultatif** dans `ProductCreate`. Omis, le serveur attribue `ART-0001`,
  `ART-0002`… par entreprise. Les références tapées à la main au format `ART-n` comptent
  dans le calcul ; les autres (`RIZ-25`) n'y entrent pas.
- **`barcode` omis** : le serveur génère un **EAN-13 interne** : préfixe `2` (plage GS1
  20-29, usage en magasin), compteur sur 11 chiffres, clé de contrôle (`2000000000015` pour le premier).
  Il est unique dans l'entreprise. Un code fabricant scanné reste prioritaire.
- **Concurrence** : deux créations simultanées calculent le même numéro.
  `products_sku_uq` ou `products_barcode_uq` refuse la seconde, qui recommence sous
  savepoint (5 tentatives). Un code imposé par l'appelant n'est jamais corrigé : 409.
- **Unités** : `sac` et `bouteille` s'ajoutent à `products.unit` (révision 0015). L'import
  CSV reconnaît « sac », « sacs », « bouteille », « bouteilles », « btl ».
- **`POST /api/v1/inventory/products`** (`NewProductCreate` = `ProductCreate` +
  `opening_qty`) : crée l'article par la façade d'Articles, puis le mouvement `initial`,
  dans la même transaction. Il exige `products:create` **et** `inventory:create` (le gérant).
  Une quantité positive exige le prix d'achat, qui valorise le stock d'ouverture. La
  réponse porte l'article et le mouvement (`null` si la quantité est nulle).
- **TVA à la création** (choix du 2026-10-08) : le formulaire ne la demande plus.
  `ProductCreate.default_tax_rate` omis ou nul prend le **taux par défaut de l'entreprise**,
  nouveau réglage `settings.default_tax_rate` (chaîne décimale, de 0 à moins de 1, quatre
  décimales au plus, vérifié comme `default_reorder_point`), 0 sans réglage. Un taux
  envoyé, même 0, n'est jamais remplacé. Réglages → « TVA des nouveaux articles (%) ».
- **Étiquette** : « Imprimer l'étiquette » sur la fiche article ouvre une page imprimable
  (code-barres EAN-13 dessiné en SVG par le front, nom, prix), sans service externe.

## Conséquences
- `POST /products` reste pour l'import et les intégrations ; le formulaire du front passe
  par `POST /inventory/products`.
- Tests : `test_product_codes.py` (compteur, EAN-13 valide et unique, par entreprise,
  création simultanée), `test_new_product_with_stock.py` (une transaction, prix d'achat
  exigé, 404 sur un rayon d'une autre entreprise, 403 pour un vendeur).
- **Pas de photo d'article en V1** (choix du 2026-10-08) : il faudrait un stockage de
  fichiers, peut-être payant. Le carré à initiale colorée en tient lieu ; noté dans
  `ecarts.md`.
- Tests : `test_default_tax_rate.py` (réglage appliqué, taux envoyé gardé, refus).
