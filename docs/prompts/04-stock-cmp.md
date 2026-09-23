# Phase 04 — Stock : journal de mouvements, projection et CMP

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 04 : module
Inventory**. Le stock est un **journal append-only** ; le stock courant n'en est qu'une
projection, maintenue par trigger et valorisée au **coût moyen pondéré (CMP)**. L'essentiel de la
logique est **en base** (§ 8.5) : ton travail consiste à l'installer à l'identique, à l'entourer
d'un service propre et à le prouver par les tests.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 03 ✅ exigée) et les ADR.
2. Lis :
   - Architecture : Diagramme 6 (mouvement de stock, ≈347+) ; module Inventory ; audit critique
     pour les ajustements manuels ; décision 10.
   - Modèle : § 2.3 (stock négatif interdit), § 2.4 (CMP), § 4.3 (`product_stock`), § 4.8
     (`inventory_movements`, inverses, idempotence), § 5.6 et § 5.7 (formules, reconstruction) ;
     SQL § 8.3 (`product_stock`) et § 8.5 en entier ; § 10 tests **T6–T13** et **T38** ;
     § 12.1 point 2 (antidatage).
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Enregistrer les mouvements manuels (stock initial, réception, retour fournisseur, perte,
ajustement), exposer le stock courant valorisé et le journal, émettre `stock.updated`, et prouver
en base : stock jamais négatif, CMP exact, journal immuable, idempotence, sérialisation sous
concurrence.

## 2. Questions à me poser (AskUserQuestion)

1. **Antidatage (P5)** : refuser tout `occurred_at` antérieur de plus de 48 h au dernier mouvement
   du produit, via un contrôle en base (Recommandé par le § 12.1 : plus simple à expliquer au
   gérant) / l'autoriser et laisser la reconstruction nocturne corriger le CMP, avec une trace
   d'audit / fenêtre différente (préciser).
2. **Coût d'un ajustement positif** : le § 8.5 exige un `unit_cost` pour toute entrée. Pour un
   ajustement positif (inventaire trouvé en plus) : CMP courant par défaut, modifiable par le
   gérant (Recommandé : ne déforme pas le CMP) / coût saisi obligatoire / dernier `cost_price` de
   `product_prices`.
3. **Réception fournisseur** : en V1, `purchase_in` crée uniquement le mouvement ; la dette ou la
   charge fournisseur est enregistrée séparément dans Finance en phase 07 (Recommandé : Inventory
   est en bande C et ne dépend pas de Finance, bande D) / créer la dette fournisseur dans la même
   opération (demanderait une orchestration au-dessus des deux modules).
4. **Correction d'une erreur de saisie** : endpoint `POST /inventory/movements/{id}/reverse` qui
   crée le mouvement inverse (unique grâce à `inv_reversal_uq`), réservé au gérant, avec audit
   critique (Recommandé) / uniquement par un nouvel ajustement.
5. **Stock initial** : type `initial` avec `ref_type = 'initial'`, un seul par produit (Recommandé) /
   un `purchase_in` ordinaire.
6. **Vue produits + stock** (suite de la question 4 de la phase 03) : `GET /api/v1/inventory/stock`
   renvoie produit, SKU, catégorie, quantité, CMP, valeur, seuil et statut
   (`ok / low / out`), en lisant les produits via la façade Products (Recommandé) / autre.

## 3. Périmètre

**Migration `0004_inventory`** : `product_stock` (§ 8.3), `inventory_movements`, l'index partiel
d'idempotence, les triggers `t10_inv_check_reversal` et `t20_inv_apply` (l'ordre alphabétique
compte), l'immuabilité (`inv_no_update`, `inv_no_delete`), `rebuild_product_stock`, les index
§ 8.10, la RLS, et le contrôle d'antidatage selon la réponse 1. **Copie le SQL à l'identique**,
relis chaque ligne coupée par l'extraction PDF, et signale-moi toute incohérence.

**Module `inventory/`**
- Service : `record_movement(ctx, …)` (un seul point d'entrée, utilisé aussi plus tard par
  Sales), `reverse_movement(ctx, movement_id)`, `get_stock(ctx, …)`, `list_movements(ctx, …)`.
- Traduction des exceptions PostgreSQL en erreurs métier : stock négatif ⇒
  `insufficient_stock` (422) avec la quantité disponible ; produit non suivi ⇒
  `product_not_stock_tracked` ; double annulation ⇒ `already_reversed` (409).
- Endpoints : `POST /api/v1/inventory/movements` (types manuels seulement : `initial`,
  `purchase_in`, `supplier_return_out`, `adjustment`, `loss` ; **jamais** `sale_out` ni
  `customer_return_in`, réservés aux flux de vente), `GET /api/v1/inventory/movements` (filtres
  produit, type, période), `GET /api/v1/inventory/stock`, reverse selon la réponse 4.
- Ajustement et perte : **motif obligatoire** (`note`) + **audit critique**.
- Outbox `stock.updated` dans la transaction (payload : `product_id`, `qty_on_hand`, `avg_cost`,
  `movement_id`, `below_reorder_point`).
- Tâche de reconstruction (appelable en CLI maintenant, planifiée en phase 08) : exécute
  `rebuild_product_stock` pour une entreprise, avec son contexte tenant, et journalise les écarts
  dans `audit_logs` (`action = 'rebuild'`).

**Tests (base réelle, `coges_app`)** — un fichier par test, nommé `test_tNN_…`
- **T6** vente simulée (mouvement `sale_out` inséré directement en SQL) au-delà du stock ;
  **T7** ajustement, perte et retour fournisseur au-delà du stock ; **T8** produit non suivi ;
  **T9** CMP en entrée (100 à 10 puis 100 à 20 ⇒ 15,0000 et 3 000,00) ; **T10** CMP en sortie ;
  **T11** stock à zéro sans division par zéro ; **T12** reconstruction après 200 mouvements
  aléatoires ⇒ écart nul ; **T13** UPDATE et DELETE sur le journal ⇒ `restrict_violation`.
- **T38** concurrence : deux transactions vendent simultanément la dernière unité (deux
  connexions, synchronisées par un verrou ou une barrière) ⇒ l'une réussit, l'autre échoue ; ni
  stock négatif ni CMP faux.
- Étends le harnais de fuite et T5 (mouvement de A sur un produit de B).
- Antidatage selon la réponse 1.

**Hors périmètre** : sorties et retours de vente (phases 05-06), multi-entrepôts, FIFO.

## 4. Règles à respecter

- **Aucun code applicatif n'écrit `product_stock`.**
- Ne reproduis pas le calcul du CMP en Python : la seule formule est `cmp_next_avg` en base
  (un test unitaire peut vérifier quelques valeurs, mais la vérité reste en SQL).
- Verrouillage dans un ordre déterministe (`product_id` croissant) dès qu'une opération touche
  plusieurs produits.

## 5. Vérification

`make test` vert, dont T6–T13 et T38 ; montre un scénario : stock initial, réception à un autre
coût, perte, lecture du stock valorisé et du journal.

## 6. Clôture

ADR (antidatage, coût des ajustements, correction par inverse) ; `CLAUDE.md` mis à jour ; résumé.
