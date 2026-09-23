# Phase 03 — Référentiels : catégories, produits, prix historisés, clients, fournisseurs

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 03 : bande B
Référentiel**. C'est le premier ensemble de modules métier construit sur le socle : il fixe le
**gabarit** que suivront tous les modules suivants. Soigne-le.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 02 ✅ exigée) et les ADR existants.
2. Lis :
   - Architecture : modules Products, Categories, Customers, Suppliers (≈272-300) ; décision 01
     (façades, modèles privés).
   - Modèle : § 2.1 (pas de variantes), § 4.2 (`products`, `default_tax_rate`) ; SQL § 8.3
     (`customers`, `suppliers`, `categories`, `products`, `product_prices` avec `EXCLUDE`) ;
     index du § 8.10 pour ces tables ; RLS § 8.11.
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

CRUD complet, paginé, recherchable et isolé par tenant pour les 4 référentiels, avec un prix de
vente et un coût **historisés par intervalles** dans `product_prices`, et jamais stockés sur la
fiche produit.

## 2. Questions à me poser (AskUserQuestion)

1. **Gabarit de module** : je te montre d'abord le module `categories` complet (router, service,
   repository, models, schemas, events, tests) et tu le valides avant que je duplique le motif
   (Recommandé) / je fais les 4 modules d'un coup.
2. **Changement de prix** : `POST /api/v1/products/{id}/prices` ferme l'intervalle courant
   (`valid_to = now()`) et ouvre le nouveau dans la **même transaction**, avec un audit critique
   (Recommandé : le prix est une donnée financière) / sans audit critique / modification en place
   (interdite par le modèle : à écarter).
3. **Prix initial obligatoire** à la création d'un produit : oui, `unit_price` requis et
   `cost_price` optionnel dans le même appel (Recommandé : sinon le produit n'est pas vendable) / non.
4. **Stock dans la liste des produits** : `products` (bande B) ne peut pas dépendre de `inventory`
   (bande C). Options : la vue « produits + stock » est un endpoint de lecture du module
   `inventory` en phase 04 (Recommandé : respecte les dépendances vers le bas) / le frontend
   compose deux appels.
5. **Codes clients et fournisseurs** : générés automatiquement (`CLI-0001`) et modifiables
   (Recommandé) / saisie libre / pas de code.
6. **Recherche** : `pg_trgm` sur le nom et recherche exacte sur le SKU ou le code-barres (Recommandé) /
   `ILIKE` simple.

## 3. Périmètre

**Migration `0003_referentiels`** : tables du § 8.3 **sauf** `product_stock` (phase 04), avec
leurs index (§ 8.10), leur RLS (§ 8.11) et leurs triggers `updated_at`.

**Modules** (même découpage interne partout)
- `categories/` : arbre (`parent_id`), refus des cycles, nom unique par parent (index partiel
  `deleted_at IS NULL`), suppression logique refusée si la catégorie contient des produits actifs
  ou des sous-catégories.
- `products/` : `sku` unique par entreprise, `unit` limité aux 6 valeurs du CHECK,
  `is_stock_tracked`, `default_tax_rate` (0 ≤ t < 1, **paramètre de saisie seulement**),
  `reorder_point`, `is_active` ; historique des prix (`GET /products/{id}/prices`) ; prix courant
  = intervalle `valid_to IS NULL`. La façade `ProductsService` expose ce dont Sales et Inventory
  auront besoin : `get_current_price`, `get_tax_rate`, `is_stock_tracked`, `assert_sellable`.
- `customers/` : coordonnées, `credit_limit` (NULL = pas de plafond).
- `suppliers/` : coordonnées, `payment_terms_days` (0-365).
- La suppression logique d'un produit ou d'un client passe par un **audit critique**.
- Endpoints `/api/v1/{categories,products,customers,suppliers}` : liste paginée, filtres,
  recherche, détail, création, modification, suppression logique. Permissions RBAC de la phase 02.

**Tests**
- Étends le **harnais de fuite** et **T5** : FK croisée `products.category_id` → catégorie d'un
  autre tenant ⇒ violation de FK composite.
- `EXCLUDE` : deux prix qui se chevauchent pour un produit ⇒ rejet en base.
- Changement de prix : un seul intervalle ouvert à la fois ; l'ancien est fermé exactement à
  l'instant d'ouverture du nouveau.
- Le test générique de routes (phase 02) couvre automatiquement les nouveaux endpoints ; vérifie-le.
- Test d'architecture : aucun import croisé.

**Hors périmètre** : stock, import CSV (phase 10), photos de produits.

## 4. Règles à respecter

- Aucune colonne de prix, de coût ou de stock sur `products`.
- Aucune notion de variante (ni colonne `size`/`color`, ni convention de SKU interprétée).
- Montants en `Decimal`, sérialisés en chaîne.

## 5. Vérification

`make test` vert ; montre la sortie OpenAPI des nouveaux endpoints (`/docs`) et un scénario :
créer une catégorie → un produit avec prix → changer le prix → lire l'historique.

## 6. Clôture

ADR du gabarit de module (il servira de référence) ; `CLAUDE.md` mis à jour ; résumé.
