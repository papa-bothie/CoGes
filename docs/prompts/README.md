# Prompts de phase — mode d'emploi

## Utilisation

1. Ouvre Claude Code **à la racine du dépôt `coges/`**, pour qu'il charge `CLAUDE.md`.
2. **Une phase = une session.** Lance `/clear` entre deux phases : le contexte reste léger et
   l'agent relit `CLAUDE.md`, qui contient l'avancement à jour.
3. Passe en **mode Plan** (Shift+Tab) avant de coller le prompt : l'agent pose ses questions,
   propose un plan, et n'écrit rien tant que tu n'as pas validé.
4. Colle le prompt en entier, depuis la ligne `---` du fichier jusqu'à la fin.
5. Réponds aux questions `AskUserQuestion`. En cas de doute, l'option « (Recommandé) » est
   alignée sur l'architecture.
6. En fin de phase, vérifie trois choses : tests verts, `CLAUDE.md` § 8 mis à jour, décisions
   écrites dans `docs/decisions/`. Ensuite, merge la branche toi-même.

## Ordre

| # | Fichier | Contenu |
|---|---|---|
| 00 | `00-initialisation.md` | Dépôt, outillage, docker compose local, CI vide |
| 01 | `01-socle-tenant-rls.md` | core/ (config, database, tenancy), schéma plateforme, RLS, T1–T5, T36–T37 |
| 02 | `02-auth-rbac-audit.md` | Companies, Auth (JWT/refresh/Argon2), Users, RBAC, audit critique, écriture outbox |
| 03 | `03-referentiels.md` | Categories, Products, product_prices, Customers, Suppliers |
| 04 | `04-stock-cmp.md` | inventory_movements, product_stock, CMP, ajustements, T6–T13, T38 |
| 05 | `05-ventes.md` | Draft → confirm → cancel, reçu, tables finance minimales, T14–T17, T23–T24, T39 |
| 06 | `06-retours.md` | Retours clients, remboursements, T18–T22 |
| 07 | `07-finance.md` | Paiements idempotents, dettes, allocations, dépenses, trésorerie, T25–T28 |
| 08 | `08-async-analytics.md` | Relais outbox, Celery, notifications, daily_sales_facts, dashboard, analytics, T29–T32, T40 |
| 09 | `09-intelligence.md` | Features, forecasts, insights, serving, T33–T35 |
| 10 | `10-durcissement-deploiement.md` | Import/export, rate limiting, observabilité, Vercel + Docker, CI bloquante |
| 11 | `11-front-fondations.md` | Next.js, design tokens du prototype, client OpenAPI, auth, layout |
| 12 | `12-front-operations.md` | Tableau de bord, référentiels, stock, ventes, retours |
| 13 | `13-front-pilotage.md` | Finance, analytics, Intelligence, paramètres, audit |
| 14 | `14-polish-impeccable.md` | Finition visuelle avec la skill Impeccable |

Le backend (00 → 10) est terminé et fonctionnel avant le début du frontend. La phase 11 peut
démarrer dès la fin de la phase 07 si le contrat OpenAPI des modules concernés est figé.
