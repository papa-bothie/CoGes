# 0108 — Description d'un article

- **Date** : 2026-11-03
- **Phase** : groupe 1, bloc D (prompt 34, branche `feat/group1-d-product-description`)
- **Statut** : acceptée
- **Décideur** : propriétaire (champ décrit dans le prompt) ; recherche par la description
  écartée via AskUserQuestion le 2026-11-03

## Contexte
Le commerçant veut noter sur un article ce que le nom ne dit pas (contenance, consigne,
origine). Le modèle V1.1 n'a pas de colonne pour cela.

## Options envisagées
1. **Colonne `products.description` facultative (retenue)** : révision 0035, `text NULL`,
   `CHECK (char_length(description) <= 500)`. Ajout seul, rétrocompatible (ADR 0083).
2. Recherche des articles aussi par la description (index trigramme) : écartée par le
   propriétaire, pour ne pas faire remonter des articles inattendus dans la grille de vente.

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
  la ligne gardés. Pas dans la grille de vente ni dans la recherche.
- **Brouillons** (ADR 0101) : `description` entre dans les listes blanches `product-new` (et
  ses champs « significatifs ») et `product-edit`, sans changer de version (un ancien
  brouillon n'a simplement pas le champ).

## Conséquences
- `ProductSummary` (façade vers les autres modules) ne porte pas la description : aucun
  autre module n'en a besoin.
- L'en-tête du modèle d'import change (`test_import_plain_headers`, `test_imports`).
