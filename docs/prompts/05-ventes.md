# Phase 05 — Ventes : brouillon, confirmation, annulation, reçu

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 05 : module
Sales**, le cœur du cycle vente → stock → argent. La confirmation d'une vente est **la** transaction
de référence de l'architecture (Diagramme 4) : 11 étapes, une seule transaction, rollback complet.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 04 ✅ exigée) et les ADR.
2. Lis :
   - Architecture : Diagramme 4 et annexe A.4 (séquence) ; périmètre Sales réduit (≈469) ;
     décisions 03, 04, 05, 08.
   - Modèle : § 4.4 et § 4.5 (taxes figées, colonnes générées) ; § 5.1 (confirmation, 8 étapes)
     et § 5.2 (annulation) ; § 5.5 (paiement direct, dette, plafond de crédit) ; SQL § 8.4
     (`sales`, `sale_items`), § 8.6 (`payments`, `debts`, `payment_allocations`), § 8.7 (triggers
     `sale_recompute_totals`, `sale_items_frozen`, `debt_credit_limit`, `sale_paid_rollup`,
     `debt_rollup`) ; § 10 tests **T14–T17**, **T23**, **T24**, **T39**.
   - `docs/architecture/README.md` : point ouvert **P6**.
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Créer une vente en brouillon (aucun effet de bord), la modifier, la confirmer en une transaction
atomique (snapshots, sorties de stock au CMP, encaissement, dette éventuelle, audit critique,
`sale.confirmed`), l'annuler proprement (mouvements inverses, `sale.cancelled`) et produire un
reçu simple.

## 2. Questions à me poser (AskUserQuestion)

1. **Ordre des phases (P6)** : la confirmation écrit dans `payments` et `debts`, que le § 12 place
   après les ventes, et `payments` référence `expenses` et `sale_returns`. Options : la migration
   0005 crée **toutes** les tables du § 8.4 et du § 8.6 avec les triggers du § 8.7 ; cette phase
   n'implémente que les services de vente, avec une façade Finance minimale (`record_sale_payment`,
   `open_customer_debt`) ; les phases 06 et 07 complètent les services (Recommandé) / tout
   implémenter maintenant / confirmation sans volet financier jusqu'en phase 07 (déconseillé :
   casse l'atomicité promise).
2. **Suppression des lignes de brouillon** : le rôle `coges_app` n'a **pas** de DELETE (§ 7), or
   retirer une ligne de brouillon est un DELETE sur `sale_items` (le trigger `sale_items_frozen`
   le bloque déjà après confirmation). Options : accorder DELETE sur `sale_items` **uniquement**,
   protégé par le trigger et par un test (Recommandé) / remplacer la ligne par une quantité à zéro
   (impossible : `CHECK qty > 0`) / recréer le brouillon.
3. **Numérotation** : `sale_no` séquentiel par entreprise, sans trou, format `V-000123`, via une
   table compteur verrouillée dans la transaction (Recommandé) / séquence PostgreSQL globale (trous
   possibles) / horodatage.
4. **Moment d'attribution du numéro** : dès le brouillon (Recommandé : lisible dans la liste) / à
   la confirmation seulement.
5. **Annulation d'une vente payée** : le § 5.2 refuse l'annulation s'il existe un paiement encaissé
   non remboursé ; une vente payée comptant se corrige donc par un **retour** (phase 06). Je
   confirme cette règle telle quelle (Recommandé : conforme au modèle) / je veux autre chose (ce
   serait un écart à documenter).
6. **TVA désactivée pour l'entreprise** : `tax_rate` figé à 0 à la confirmation, quel que soit
   `products.default_tax_rate` (Recommandé) / toujours appliquer le taux du produit.
7. **Reçu simple** : `GET /api/v1/sales/{id}/receipt` renvoie un JSON complet, et le frontend
   produit la version imprimable (Recommandé : rien de lourd côté API) / PDF généré par un worker /
   HTML rendu par l'API.
8. **Idempotence de la confirmation** : un second `confirm` sur une vente déjà confirmée ⇒ 409
   `sale_not_draft` (Recommandé) / 200 qui renvoie l'état actuel.

## 3. Périmètre

**Migration `0005_sales_finance_tables`** (selon la réponse 1) : tables, triggers, index et RLS
correspondants, SQL copié à l'identique.

**Module `sales/`**
- `POST /api/v1/sales` → brouillon (`status = draft`) ; `PATCH` (client, date) ;
  `POST/PATCH/DELETE /api/v1/sales/{id}/items` tant que la vente est en brouillon. Les totaux sont
  recalculés par trigger. En brouillon, **aucun** mouvement, aucune écriture financière, aucun
  audit critique, aucun événement.
- `POST /api/v1/sales/{id}/confirm` avec le règlement (`paid_amount`, `method`), en **une seule
  transaction**, dans l'ordre du § 5.1 :
  1. RBAC `sales:confirm` ; `FOR UPDATE` sur la vente ; `status = draft` et au moins une ligne ;
  2. verrouillage des `product_stock` concernés, **par `product_id` croissant** ;
  3. snapshots : `unit_price` et `price_id` (prix ouvert), `tax_rate` (selon la réponse 6) ;
  4. un mouvement `sale_out` par ligne suivie, via la **façade Inventory** (`ref_type =
     'sale_item'`) ;
  5. recopie de `unit_cost` du mouvement dans `sale_items.unit_cost` (0 pour les articles non
     suivis) ;
  6. `status = confirmed`, `confirmed_at` ;
  7. `payments` (inflow, `sale_id`) pour la part payée ; `debts` (customer, `sale_id`) pour le
     solde, avec le contrôle du plafond de crédit (vente à crédit ⇒ client obligatoire) ;
  8. audit critique ; outbox `sale.confirmed` (+ `debt.created` et `payment.received` s'il y a
     lieu) ; COMMIT.
  Toute erreur ⇒ ROLLBACK complet, traduit en erreur métier claire
  (`insufficient_stock` avec la quantité disponible, `credit_limit_exceeded`, `no_open_price`…).
- `POST /api/v1/sales/{id}/cancel` (motif obligatoire), selon le § 5.2 : mouvements inverses
  `customer_return_in` avec `reversal_of_movement_id` ; dette non payée ⇒ `written_off` ; refus
  si retour ou paiement non remboursé ; audit critique ; `sale.cancelled`. Un second appel ⇒ la
  base lève `inv_reversal_uq` ⇒ réponse « déjà annulée », sans effet.
- `GET /api/v1/sales` (filtres statut, période, client, recherche par numéro), `GET /sales/{id}`,
  reçu selon la réponse 7.
- Le statut « retournée » affiché dans le prototype **n'est pas** un statut de la base : c'est une
  information dérivée (la vente a au moins un retour), exposée dans la réponse.

**Tests**
- **T14** annulation ⇒ un inverse par ligne, stock revenu à l'identique ; **T15** double
  annulation ⇒ violation de `inv_reversal_uq`, aucun mouvement de plus ; **T16** annuler une
  annulation ⇒ exception ; **T17** deux mouvements pour la même `sale_item` ⇒ violation de l'index
  d'idempotence ; **T23** taxe à 18 %, puis `default_tax_rate` passé à 5 % ⇒ vente inchangée ;
  **T24** balayage : `subtotal − discount_total + tax_total = total` partout ; **T39** ROLLBACK
  injecté après les mouvements ⇒ ni vente confirmée, ni mouvement, ni événement, stock intact.
- Scénarios de service : brouillon sans effet (stock, `payments`, `business_events` inchangés) ;
  paiement total, partiel (dette = solde) et crédit ; plafond de crédit dépassé ; ligne modifiée
  après confirmation ⇒ refusée par la base.
- Harnais de fuite étendu (ventes, lignes, paiements, dettes) ; T5 (ligne de A sur un produit de B).

**Hors périmètre** : retours et remboursements (06), paiements ultérieurs d'une dette,
allocations et dépenses (07), devis, commandes, avoirs.

## 4. Règles à respecter

- Sales passe par les **façades** Inventory, Products, Customers et Finance : aucun import de leur
  repository ou de leurs modèles.
- L'égalité comptable est **produite par la base** (colonnes générées) : ne la calcule pas en
  Python pour l'écrire.
- Montants reçus et renvoyés en chaîne décimale ; `paid_amount` ≤ total, pas de sur-paiement.

## 5. Vérification

`make test` vert ; démonstration de bout en bout : brouillon → ajout de 3 lignes → confirmation
avec paiement partiel → lecture du stock, de la dette et de l'outbox → tentative d'annulation
(refusée car paiement) → nouvelle vente à crédit → annulation réussie.

## 6. Clôture

ADR (P6, DELETE sur `sale_items`, numérotation, TVA désactivée, reçu) ; `CLAUDE.md` mis à jour ;
résumé.
