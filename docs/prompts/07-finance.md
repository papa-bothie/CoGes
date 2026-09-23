# Phase 07 — Finance de gestion : paiements, dettes, dépenses, trésorerie

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 07 : bande D
Finance de gestion** (modules Payments, Debts, Expenses, Finance). Rappel du périmètre : CoGes V1
répond à la question « **où en est mon argent ?** ». Ce n'est **pas** une comptabilité générale.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 06 ✅ exigée) et les ADR (en particulier la façade Finance de la
   phase 05 et la compensation de la phase 06).
2. Lis :
   - Architecture : Diagramme 5 et annexe A.5 (paiement, idempotence) ; modules Finance, Payments,
     Debts, Expenses (≈272-330) ; périmètre Finance V1 et exclusions (≈490) ; décisions 09, 15, 16.
   - Modèle : § 5.5 (dettes et paiements) ; SQL § 8.6 (`expense_categories`, `expenses`,
     `debts`, `payments`, `payment_allocations`) et § 8.7 (`allocation_check`, `debt_rollup`,
     `debt_credit_limit`) ; § 10 tests **T25–T28**.
   - `docs/architecture/README.md` : point ouvert **P4** (clés d'idempotence).
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Enregistrer des encaissements et des décaissements **idempotents**, les allouer à une ou plusieurs
dettes, suivre les créances clients et les dettes fournisseurs (échéance, solde, statut), saisir
des dépenses catégorisées, et fournir une vue de trésorerie simple et une marge estimée.

## 2. Questions à me poser (AskUserQuestion)

1. **Clés d'idempotence (P4)** : table `idempotency_keys` tenant-scoped (`company_id`, `key`,
   `endpoint`, `request_hash`, `response_status`, `response_body`, `created_at`, `expires_at`),
   RLS, `UNIQUE (company_id, key)`, en-tête `Idempotency-Key` **obligatoire** sur les écritures
   financières, et même clé + corps différent ⇒ 422 (Recommandé) / colonne `idempotency_key` sur
   `payments` seulement / Redis.
2. **Rétro-application** : appliquer aussi l'en-tête `Idempotency-Key` à `POST /sales/{id}/confirm`
   et aux remboursements (Recommandé : ce sont aussi des écritures financières) / paiements seulement.
3. **Dette fournisseur** : créée à la main (fournisseur, montant, échéance, lien facultatif vers une
   dépense) (Recommandé en V1) / créée automatiquement depuis une dépense marquée « à payer » / les deux.
4. **Charges récurrentes** (citées par l'architecture) : en V1, une dépense porte `kind = fixed |
   variable` et l'écran propose « dupliquer le mois précédent » (Recommandé : aucune
   automatisation, hors V1) / génération automatique mensuelle par un job en phase 08.
5. **Définition de la marge estimée** : marge brute = CA net HT − coût des ventes net (CMP figé) ;
   résultat estimé = marge brute − dépenses de la période (Recommandé : conforme aux définitions de
   `daily_sales_facts` du § 4.10) / autre définition.
6. **Source des indicateurs financiers dans cette phase** : calcul direct sur les tables
   transactionnelles avec index et pagination, puis bascule sur les agrégats en phase 08
   (Recommandé) / attendre la phase 08 pour exposer les indicateurs.
7. **Abandon de créance** (`written_off`) : gérant seulement, motif obligatoire, audit critique
   (Recommandé) / autre.

## 3. Périmètre

**Migration `0007_finance`** : ce qui manque encore du § 8.6 et du § 8.7, plus la table
d'idempotence (réponse 1), avec RLS et index.

**Modules**
- `payments/` : `POST /api/v1/payments` (direction, méthode, montant > 0, date, référence,
  contexte : `sale_id`, `expense_id` ou rien, et allocations `[{debt_id, amount}]`). Diagramme 5
  dans l'ordre : idempotence → paiement → allocations (verrou `FOR UPDATE` sur chaque dette, dans
  l'ordre des id) → montant alloué ≤ solde (sinon 422, **sur-paiement refusé**) → solde recalculé
  par trigger → dette soldée ⇒ `paid` + `debt.settled` → audit critique → outbox
  `payment.received` → COMMIT. Toute correction importante d'un paiement (réallocation,
  annulation) passe par un **audit critique** avec la valeur avant et après, et ne supprime jamais
  physiquement.
- `debts/` : liste (partie, statut, échéance dépassée), détail avec allocations, création manuelle
  (réponse 3) avec contrôle du plafond de crédit pour un client, abandon (réponse 7) ;
  `debt.created`.
- `expenses/` : catégories (`fixed` / `variable`), dépenses (libellé, montant, date, fournisseur
  facultatif), suppression logique auditée ; paiement d'une dépense via `payments.expense_id` ;
  `expense.created`.
- `finance/` (lecture seule, façade de restitution) : `GET /api/v1/finance/overview?from=&to=` ⇒
  encaissements, décaissements, solde de la période (méthode `offset` exclue si elle existe),
  CA net, coût des ventes, marge brute, dépenses, résultat estimé, créances ouvertes, dettes
  fournisseurs ouvertes ; série journalière sur 30 jours.

**Tests**
- **T25** dette de 1 000, paiement de 400 ⇒ `partially_paid`, solde 600 ; **T26** paiement de 1 000
  réparti 400 / 400 / 300 ⇒ la 3ᵉ allocation échoue ; **T27** solde à 0 ⇒ `paid` et `closed_at` ;
  **T28** nouvelle dette au-delà de `credit_limit` ⇒ exception.
- Idempotence : même clé et même corps ⇒ même réponse, **un seul** paiement en base ; même clé et
  corps différent ⇒ 422 ; deux requêtes concurrentes avec la même clé ⇒ un seul paiement.
- Trésorerie : cohérente avec la somme des paiements ; la méthode `offset` n'apparaît pas.
- Harnais de fuite et T5 étendus (allocation de A sur une dette de B).

**Hors périmètre** : plan comptable, grand livre, rapprochement bancaire, déclarations fiscales,
multi-devises, prévision de trésorerie (phase 09).

## 4. Règles à respecter

- Jamais de montant négatif : le sens est porté par `direction`.
- `debts.principal` n'est **jamais** réécrit ; `balance` est une colonne générée.
- Les écritures restent horodatées, typées et rattachées à leur pièce d'origine (export
  comptable futur possible).

## 5. Vérification

`make test` vert ; scénario : deux ventes à crédit → un paiement réparti sur les deux dettes →
rejeu de la même requête (même clé) sans doublon → dépense + dette fournisseur → overview de la
période.

## 6. Clôture

ADR (idempotence, dettes fournisseurs, marge, abandon) ; `CLAUDE.md` mis à jour ; résumé. À ce
stade, **tout le transactionnel V1 est en place** : fais la liste des tests T1–T28 et T36–T39 et
de leur statut.
