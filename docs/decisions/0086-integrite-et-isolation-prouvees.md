# 0086 — Intégrité et isolation prouvées (lot C)

- **Date** : 2026-10-17
- **Phase** : prompt 20 (lot C, après le lot A)
- **Statut** : acceptée
- **Décideur** : cahier des charges du propriétaire, options recommandées appliquées
  (consigne du 2026-10-17). **Correction de fond à relire** par le propriétaire avant la
  fusion (voir « Correction de fond »).

## Contexte

Le lot A (ADR 0079) a prouvé l'échec au COMMIT sur trois écritures. Il fallait le
prouver sur toutes les écritures critiques, prouver qu'aucune lecture ne fuit entre deux
entreprises (y compris sans identifiant dans l'URL), et que Redis et les tâches de fond
ne mélangent jamais deux entreprises — de sorte qu'une régression d'isolation ne puisse
pas passer la CI.

## Décision

**Principe** : les tests DÉCOUVRENT les routes et les tâches dans l'application, et un
registre fait échouer la CI quand une route ou une tâche nouvelle n'y est pas classée.

- **C1** (`tests/integration/commit_failure_registry.py`,
  `test_commit_failure_all_writes.py`) : un trigger de contrainte **différé** est posé le
  temps du test sur **chaque** table d'entreprise (et `companies`) ; toute transaction qui
  a écrit pour l'entreprise de test échoue au COMMIT, comme un vrai refus de la base. Pour
  chaque écriture critique : 5xx, **empreinte complète** des données de l'entreprise
  inchangée (lignes, outbox, audit, clés d'idempotence), cache du tableau de bord ni
  invalidé ni remplacé ; rejeu avec la même clé ⇒ succès, invariants vérifiés ; pour les
  écritures à clé, un troisième envoi identique (réponse « perdue ») rend la même
  réponse sans réécrire. **Toutes vertes d'emblée** : l'ordre COMMIT → réponse → rappels
  après COMMIT (ADR 0079, `tenancy.on_commit`) est sûr partout.
- **C2** (`tests/tenancy/test_list_routes_cross_tenant.py`) : deux entreprises aux données
  marquées (dont le même nom de client et les mêmes numéros de pièce) ; chaque lecture
  sans paramètre appelée par A, réponse JSON parcourue récursivement, exports CSV et
  .xlsx lus : aucune trace de B. Filtres par identifiant de B, recherches à jokers
  (`%`, `_`, guillemets, injection), pagination et tri hostiles ; identifiants de B dans
  le corps d'écritures de A ⇒ refus sans effet ; vendeur sur les écrans du gérant ⇒ 403 ;
  en-têtes et paramètres forgés ⇒ confiné à A ; jeton expiré ⇒ 401 ; jeton d'une
  entreprise supprimée ⇒ 401. Registre RLS : `TABLES_WITHOUT_RLS` nomme les seules tables
  sans RLS (`alembic_version`, `permissions`), toute autre fait échouer T37.
- **C3** (`tests/tenancy/test_redis_keys_isolation.py`) : inventaire SCAN de toutes les
  clés créées par des opérations de A et B ; chacune préfixée par l'entreprise, compteur
  d'entreprise, sha256 documenté (`rl:acct`) ou globale de la liste blanche commentée ;
  aucune clé sans TTL. Cache de A jamais servi à B, invalidation de A sans effet sur B,
  plafond d'entreprise de A sans effet sur B, repli en base sans Redis. L'idempotence
  vit en base : corps différent et requêtes simultanées déjà prouvés
  (`test_payments_idempotency.py`), même clé chez A et B ⇒ deux traitements (C2).
- **C4** (`tests/tenancy/test_beat_tasks_tenant_isolation.py`) : registre de toutes les
  tâches de `BEAT_SCHEDULE` (8 éventails avec leur sous-tâche, 4 tâches de plate-forme
  avec leur raison) ; chaque sous-tâche lancée pour A ne change rien chez B (empreinte
  par le propriétaire sous le contexte de B, tables du ML comprises) et se relance sans
  doublon ; une entreprise en panne n'arrête pas la suivante et laisse `failed` dans
  `job_runs` avec la classe de l'erreur seulement. Relais : T40 et
  `test_worker_tenant_isolation.py`.
- **C5** (`tests/integration/test_concurrency_and_figures.py`,
  `tests/helpers/invariants.py`) : deux confirmations simultanées par HTTP pour le dernier
  article ⇒ une seule, l'autre « Stock insuffisant », stock 0, CMP intact ; deux
  règlements différents en parallèle ⇒ un seul, jamais plus que la dette. Invariants
  réutilisables (stock = mouvements, jamais négatif ; vente = ses lignes ; payé + reste
  dû = total ; payé ≤ total ; dettes et lettrages cohérents ; CA du tableau de bord =
  ventes confirmées du jour, recalculé en SQL), appelés après chaque écriture de C1, après
  C5, et sur le jeu de démonstration (`test_seed_demo_states`, `make invariants`).

## Correction de fond

**Une entreprise supprimée gardait ses sessions.** `auth_lookup` refusait la connexion
d'une entreprise supprimée (`companies.deleted_at`), mais la relecture de l'identité à
chaque requête (`core/deps.py`, `_LOAD_IDENTITY`) ne regardait que l'utilisateur : un
jeton d'accès encore valide (15 min), et ceux que le rafraîchissement réémettait tant que
la session vivait, ouvraient toujours les données. Correction : la relecture exige une
entreprise non supprimée (`JOIN companies … deleted_at IS NULL`). Sortie démontrée :
rouge sans la correction (200 avec des données), verte avec (401). Le rafraîchissement
n'est pas modifié : il réémet un jeton que toute requête refuse ensuite.

## Routes classées

**Écritures critiques (51)** — COMMIT refusé ⇒ 5xx, aucune trace ; rejeu ⇒ succès :

- `POST /api/v1/categories`
- `DELETE /api/v1/categories/{category_id}`
- `PATCH /api/v1/categories/{category_id}`
- `PATCH /api/v1/companies/me`
- `POST /api/v1/customers`
- `DELETE /api/v1/customers/{customer_id}`
- `PATCH /api/v1/customers/{customer_id}`
- `POST /api/v1/debts` — clé d'idempotence : rejeu à l'identique sans réécriture
- `POST /api/v1/debts/{debt_id}/write-off`
- `POST /api/v1/expense-categories`
- `PATCH /api/v1/expense-categories/{category_id}`
- `POST /api/v1/expenses` — clé d'idempotence : rejeu à l'identique sans réécriture
- `DELETE /api/v1/expenses/{expense_id}`
- `PATCH /api/v1/expenses/{expense_id}`
- `POST /api/v1/exports/sales`
- `POST /api/v1/imports/{kind}` — clé d'idempotence : rejeu à l'identique sans réécriture
- `PATCH /api/v1/insights/{insight_id}`
- `POST /api/v1/inventory/deliveries` — clé d'idempotence : rejeu à l'identique sans réécriture
- `POST /api/v1/inventory/movements`
- `POST /api/v1/inventory/movements/{movement_id}/reverse`
- `POST /api/v1/inventory/products`
- `POST /api/v1/notifications/read-all`
- `PATCH /api/v1/notifications/{notification_id}`
- `POST /api/v1/payments` — clé d'idempotence : rejeu à l'identique sans réécriture
- `POST /api/v1/payments/{payment_id}/cancel` — clé d'idempotence : rejeu à l'identique sans réécriture
- `POST /api/v1/products`
- `DELETE /api/v1/products/{product_id}`
- `PATCH /api/v1/products/{product_id}`
- `POST /api/v1/products/{product_id}/prices`
- `POST /api/v1/roles`
- `DELETE /api/v1/roles/{role_id}`
- `PATCH /api/v1/roles/{role_id}`
- `PUT /api/v1/roles/{role_id}/abilities`
- `POST /api/v1/sale-returns/{return_id}/refunds` — clé d'idempotence : rejeu à l'identique sans réécriture
- `POST /api/v1/sales`
- `PATCH /api/v1/sales/{sale_id}`
- `POST /api/v1/sales/{sale_id}/cancel`
- `POST /api/v1/sales/{sale_id}/confirm` — clé d'idempotence : rejeu à l'identique sans réécriture
- `POST /api/v1/sales/{sale_id}/items`
- `DELETE /api/v1/sales/{sale_id}/items/{item_id}`
- `PATCH /api/v1/sales/{sale_id}/items/{item_id}`
- `POST /api/v1/sales/{sale_id}/returns` — clé d'idempotence : rejeu à l'identique sans réécriture
- `POST /api/v1/suppliers`
- `DELETE /api/v1/suppliers/{supplier_id}`
- `PATCH /api/v1/suppliers/{supplier_id}`
- `POST /api/v1/users`
- `DELETE /api/v1/users/{user_id}`
- `PATCH /api/v1/users/{user_id}`
- `POST /api/v1/users/{user_id}/password`
- `POST /api/v1/users/{user_id}/roles`
- `DELETE /api/v1/users/{user_id}/roles/{role_id}`

**Écritures exemptées (4)** :

- `POST /api/v1/auth/login` — transaction d'identité puis de session, testée par test_login_throttle et test_temporary_password_expiry (aucune écriture métier)
- `POST /api/v1/auth/logout` — révocation de session, idempotente par nature
- `POST /api/v1/auth/password` — mot de passe de la personne connectée : sa propre session, couverte par test_temporary_password_expiry ; aucun argent, aucun stock
- `POST /api/v1/auth/refresh` — rotation de session, couverte par test_auth (réutilisation, délai de grâce)

**Lectures d'entreprise sans paramètre de chemin (40)**, appelées par A sans trace de B : `/analytics/cash`, `/analytics/customers`, `/analytics/expenses-summary`, `/analytics/history`, `/analytics/money`, `/analytics/next-week`, `/analytics/overview`, `/analytics/products`, `/analytics/suppliers`, `/analytics/timeseries`, `/audit-logs`, `/auth/me`, `/categories`, `/companies/me`, `/customers`, `/dashboard`, `/debts`, `/expense-categories`, `/expenses`, `/exports`, `/forecasts`, `/insights`, `/intelligence/summary`, `/inventory/movements`, `/inventory/stock`, `/inventory/stock/summary`, `/notifications`, `/notifications/unread-count`, `/payments`, `/permissions`, `/products`, `/products/category-counts`, `/roles`, `/roles/abilities`, `/sales`, `/sales/customer-choices`, `/sales/day-totals`, `/suppliers`, `/system/outbox`, `/users`.

**Lectures publiques ou d'exploitation** : `/api/v1/health` (public), `/api/v1/health/ready` (public), `/api/v1/system/workers` (ops).

## Durée ajoutée à la CI

Les 235 nouveaux tests ajoutent environ 1 minute à la suite (62 s en local ; suite complète 1 263 tests en 11 min 44 s) ; sous le seuil de
5 minutes, ils restent dans les jobs existants (`make test`, `make test-tenancy`).

## Conséquences

- Règle (CLAUDE.md) : toute nouvelle route d'écriture se classe dans
  `commit_failure_registry.py`, toute nouvelle lecture sans paramètre dans `READ_ROUTES`,
  toute tâche planifiée dans `test_beat_tasks_tenant_isolation.py`, toute table sans RLS
  dans `TABLES_WITHOUT_RLS` : la CI l'impose.
- `make invariants SLUG=…` recoupe les chiffres d'une entreprise locale.
