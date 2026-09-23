# docs/architecture — Index des références

Les deux PDF de `./pdf/` sont la **source de vérité**. Les fichiers `.txt` en sont des extraits
texte, découpés pour être lus **par morceaux** (avec `offset`/`limit`) plutôt qu'en entier.
Pour un tableau déformé ou une ligne SQL coupée, le PDF fait foi.

**Hiérarchie en cas de divergence :** Modèle de données V1.1 > Architecture technique V1.1 >
`CLAUDE.md` > décisions `docs/decisions/` > code existant.

## 01-architecture-technique-v1.1.txt (≈1 250 lignes)

| Sujet | Ligne ≈ |
|---|---|
| Ce que la V1.1 change (tableau de synthèse) | 26 |
| Diagramme 1 — Architecture logique + rôle de chaque couche | 74 |
| Diagramme 2 — Déploiement Vercel / Docker + règle d'affectation | 158 / 197 |
| Diagramme 3 — Modules backend (5 bandes) + responsabilités/dépendances | 224 / 272 |
| Diagrammes 4-6 — Flux vente (draft → confirm), paiement, mouvement de stock | 347 |
| Audit critique vs audit secondaire + liste des opérations à audit critique | 412 / 439 |
| Périmètres V1 : Sales réduit, Finance de gestion | 467 / 490 |
| Diagramme 7 — Pipeline CoGes Intelligence + 8 métriques + règles d'affichage | 509 |
| Diagramme 8 — Multi-tenant / RLS / pool + tests de fuite | 585 / 671 |
| Performance synchrone / asynchrone | 702 |
| Diagramme 9 — V1 / futur | 746 |
| Diagramme 10 — Arborescence cible du dépôt | 785 |
| Annexe A — Sources Mermaid | 902 |
| **18 décisions définitivement retenues** | 1137 |
| Risques techniques | 1217 |

## 02-modele-donnees-v1.1-sections-1-7.txt (≈1 470 lignes)

| Sujet | Ligne ≈ |
|---|---|
| §1 Résumé des corrections | 30 |
| §2 Décisions verrouillées (variantes, 1 compte = 1 entreprise, stock ≥ 0, CMP) | 99 |
| §3 Diagramme ER Mermaid (30 tables) | 156 |
| §4 Dictionnaire (4.1 recensement des 30 tables → 4.12 insights) | 555 |
| §5 Règles métier critiques (5.1 confirmation … 5.7 reconstruction CMP) | 1131 |
| §6 Architecture analytique (6.1 daily_sales_facts, 6.2 anti-fuite temporelle) | 1259 |
| §7 Isolation multi-tenant (politique RLS type, rôle coges_app) | 1412 |

## 03-schema-v1.1-section-8.sql.txt (≈1 175 lignes) — SQL complet

| Bloc | Ligne ≈ |
|---|---|
| 8.1 Extensions, types ENUM, `set_updated_at`, `cmp_next_avg` | 13 |
| 8.2 Tenant et RBAC (companies, users, roles, permissions, user_roles, role_permissions) | 62 |
| 8.3 Référentiels (customers, suppliers, categories, products, product_prices, product_stock) | 136 |
| 8.4 Ventes, retours (sales, sale_items, sale_returns, sale_return_items) | 248 |
| 8.5 Stock (inventory_movements, immuabilité, inverses, `inv_apply_movement`, rebuild) | 361 |
| 8.6 Charges, dettes, paiements, remboursements | 547 |
| 8.7 Triggers financiers et de cohérence des ventes | 678 |
| 8.8 notifications, audit_logs (partitionné), business_events (outbox) | 885 |
| 8.9 Couche analytique et résultats ML | 934 |
| 8.10 Index | 1036 |
| 8.11 RLS — couverture complète | 1126 |

⚠️ Extrait d'un PDF : certaines lignes longues sont coupées (ex. la regex d'e-mail de `users`).
Toujours relire et **exécuter** le SQL dans une base de test avant de l'intégrer à une migration.

## 04-modele-donnees-v1.1-sections-9-12.txt (≈400 lignes)

| Sujet | Ligne ≈ |
|---|---|
| §9 Migration V1 → V1.1 (**non applicable telle quelle** : projet neuf, voir ci-dessous) | 5 |
| §10 **Tests d'intégrité T1 à T40** | 102 |
| §11 Matrice V1 / V1.1 / futur | 256 |
| §12 Critère final + 3 points résiduels + **ordre de développement recommandé** | 343 |

## Points ouverts repérés dans les documents (à trancher avec l'utilisateur, pas à deviner)

Ces points ne sont **pas** tranchés par l'architecture. Le prompt de la phase concernée demande
à l'agent de poser la question avant de coder, puis de consigner la réponse dans `docs/decisions/`.

| # | Point | Phase |
|---|---|---|
| P1 | Projet neuf : le §9 décrit une migration V1 → V1.1. Faut-il plutôt créer directement le schéma V1.1, découpé en révisions Alembic par phase ? | 01 |
| P2 | **Connexion vs RLS** : la connexion se fait par (slug d'entreprise, e-mail), mais `users` et `companies` sont sous RLS : sans contexte, la recherche renvoie 0 ligne. Il faut un mécanisme (fonction `SECURITY DEFINER` restreinte, rôle d'authentification dédié…). | 02 |
| P3 | Aucune table pour les **refresh tokens / sessions** (refresh rotatif + révocation exigés). | 02 |
| P4 | Aucune colonne ni table pour les **clés d'idempotence** des écritures financières (`POST /payments`). | 05 / 07 |
| P5 | **Antidatage des mouvements** et CMP (§12.1 point 2) : refuser au-delà d'une fenêtre (48 h recommandée) ou corriger chaque nuit. | 04 |
| P6 | Ordre des phases : la confirmation d'une vente écrit dans `payments` et `debts` (étapes 7-8), que le §12 place pourtant **après** les ventes. | 05 |
| P7 | La proposition de tarification évoque plusieurs entreprises par compte, ce qui contredit la décision verrouillée « 1 compte = 1 entreprise ». Hors V1 technique : à ne pas implémenter, seulement à signaler. | — |
| P8 | La facturation et les limites par palier (historique 60 jours, nombre d'utilisateurs, Intelligence partielle) ne figurent pas dans l'architecture V1. | 10 |
