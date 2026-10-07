# Frontend CoGes — Next.js (App Router)

Next 16 · TypeScript strict · Tailwind 4 · shadcn/ui · TanStack Query · openapi-fetch
(ADR 0046 à 0048).

## Règles

- Le frontend n'appelle **que** l'API REST `/api/v1`, servie sous sa propre origine :
  `next.config.ts` réécrit `/api/v1/*` vers `COGES_API_URL` (ADR 0047).
- `types/api.ts` est **généré** depuis `backend/openapi.json` (`pnpm gen:api`), jamais écrit
  à la main.
- Aucun calcul métier : on affiche ce que l'API renvoie. Montants reçus en chaîne, formatés
  par `lib/format` sans passer par un `float`.
- Le RBAC du front ne fait que **masquer** (`lib/permissions.ts`, `<Can>`) : l'autorisation
  est vérifiée côté serveur.
- Textes de l'interface dans `lib/labels.ts`.

## Commandes

```bash
corepack enable pnpm && pnpm install      # ou `make front-install` depuis la racine
pnpm dev                                  # http://localhost:3000 (COGES_API_URL, défaut :8000)
pnpm gen:api                              # régénère types/api.ts après `make openapi`
pnpm lint && pnpm typecheck && pnpm test  # ce que joue la CI (+ check:api et build)
pnpm e2e                                  # Playwright, sur la base dédiée coges_e2e (voir ci-dessous)
```

Variables : voir `.env.example`. Captures de référence : `docs/design/captures/`.

## Tester en local

Depuis la racine, une seule commande lance l'API, le worker, le relais de l'outbox et le
front, chacun préfixé de son nom dans le terminal (`Procfile.dev`, honcho) ; Ctrl+C arrête
les quatre :

```bash
make up && make migrate   # PostgreSQL et Redis, puis le schéma
make dev                  # api.1, worker.1, relay.1, front.1 → http://localhost:3000
make dev API_PORT=8001    # si le port 8000 est déjà pris (le front suit)
```

Sans relais ni worker, une vente compte quand même dans le CA du jour (calculé en direct,
ADR 0061) ; ce sont les jours passés, les alertes et les conseils qui attendent, et le
tableau de bord du gérant l'annonce au bout de deux minutes.

## Parcours e2e : une base à part (ADR 0059)

Les suites Playwright tournent sur **`coges_e2e`**, jamais sur `coges` (la base de
développement), la préproduction ou Neon. Le développement (API :8001, front :3000) continue
de tourner à côté, sans rien partager avec les tests.

```bash
make up            # PostgreSQL et Redis locaux
make front-e2e     # = make e2e-reset, puis la suite complète
```

- **`make e2e-reset`** recrée la base avant chaque suite : `DROP` puis `CREATE DATABASE`
  de `coges_e2e` (superutilisateur du conteneur local), migrations, `seed-demo` (épicerie
  `demo`, `gerant@demo.example.com`, `demo-coges-2026`), ce que la nuit ferait (agrégats des
  91 derniers jours et CoGes Intelligence), puis l'entreprise **`e2e`** vide
  (`gerant@e2e.example.com`, même mot de passe). Aucune suppression de lignes dans le code
  applicatif.
- **Deux entreprises** (ADR 0060) : les parcours qui écrivent (articles, clients, vendeurs
  « E2E ») se connectent à `e2e` — `E2E` dans `e2e/fixtures.ts`, valeur par défaut de
  `managerApi` et `createSalesperson` ; captures, axe, classement par métrique,
  recommandations et cibles tactiles lisent `demo` (`DEMO`), qui reste propre.
- **`make e2e-api`** : API sur **:8100**, branchée sur `coges_e2e`, Redis local base n° 1,
  **limites de débit désactivées** (`COGES_RATE_LIMIT_*=0`) — une suite enchaîne des
  dizaines de connexions depuis la même IP.
- **`make e2e-front`** : front sur **:3100**, réécrit vers :8100, build dans `.next-e2e`
  (`COGES_NEXT_DIST_DIR`) pour ne pas gêner `pnpm dev`.
- Playwright démarre ces deux serveurs s'ils ne tournent pas déjà (`webServer`) ; on peut
  aussi les lancer à la main pour garder les journaux sous les yeux.
- **Garde-fou** : `deploy/scripts/e2e.sh` dérive les DSN du `.env` en remplaçant seulement le
  nom de la base, et **refuse** tout hôte autre que `localhost` (PostgreSQL comme Redis)
  avant la moindre commande.
- `pnpm e2e` seul ne recrée pas la base : les données s'accumulent alors d'une suite à
  l'autre. `E2E_BASE_URL=<url>` vise un front déjà déployé (aucun serveur lancé).
- Cibles tactiles : `e2e/touch-targets.spec.ts` émule une tablette (`hasTouch`, 1024 × 768)
  et mesure toutes les cibles de Nouvelle vente, Stock et Ventes (44 × 44 px au moins).

## Maquette v2 : composants et comparaison (phase 15, ADR 0064 et 0065)

- **`/dev/composants`** (développement seulement, sans connexion) : tous les composants de
  `components/kit/` et leurs états, avec le sélecteur de thème. En production, la page
  répond 404.
- **`make seed-maquette`** crée l'entreprise **`maquette`** (« Alimentation Keur Fatou »,
  `gerant@maquette.example.com`, `demo-coges-2026`) dans la base locale ; `make e2e-reset`
  la crée aussi dans `coges_e2e`. Pour la voir le mardi 6 octobre 2026 à 10 h 45 :
  `COGES_FROZEN_NOW=2026-10-06T10:45:00+00:00 make api`.
- **`make maquette-check`** compare chaque écran livré à sa capture (`pixelmatch`, 2 % de
  pixels différents au plus) avec ses propres serveurs : API **:8101** à l'heure figée
  (`deploy/scripts/e2e.sh maquette-api`, Redis n° 2) et front **:3101** (`.next-maquette`).
  Résultats : `docs/design/captures/phase-15/comparaison.md` et une image maquette | front |
  différences par écran. `MAQUETTE_ALL=1` mesure aussi les écrans pas encore refaits, sans
  échouer. Un écran est rendu bloquant en l'ajoutant à `DONE` dans `e2e/maquette.spec.ts`.
