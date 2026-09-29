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
pnpm e2e                                  # Playwright : API + front démarrés, `make seed-demo`
```

Variables : voir `.env.example`. Captures de référence : `docs/design/captures/`.
