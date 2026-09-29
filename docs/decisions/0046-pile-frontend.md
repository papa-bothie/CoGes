# 0046 — Pile du frontend

- **Date** : 2026-09-29
- **Phase** : 11
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le Diagramme 10 fixe l'arborescence de `frontend/` (App Router, `components/`, `lib/`,
`types/` généré) sans fixer les bibliothèques. Le prototype Bolt (React + Vite + Tailwind +
shadcn/ui) sert de référence visuelle, pas de code.

## Options envisagées

1. **Next 16 + Tailwind 4 + shadcn/ui (Radix) (retenue)** : versions stables au moment de la
   phase ; tokens du prototype repris à l'identique via `@theme inline`.
2. Next 15 + Tailwind 3 : exactement la pile du prototype, mais une version majeure de retard.
3. Autre bibliothèque de composants : tokens et composants à réécrire.

## Décision

- **Next.js 16** (App Router, `proxy.ts` à la place de `middleware.ts`), **TypeScript strict**
  (`noUncheckedIndexedAccess`), **Tailwind 4**, **shadcn/ui** sur Radix, **lucide-react**.
- **TanStack Query** pour les lectures et mutations côté client ; les Server Components ne
  servent qu'au rendu statique (le jeton d'accès vit en mémoire navigateur, ADR 0006).
- **react-hook-form + zod** ; chaque schéma zod est contrôlé par
  `satisfies z.ZodType<…>` contre le type **généré** de la requête.
- **Recharts** pour les graphiques.
- **Inter** servie par `next/font` (auto-hébergée au build, chiffres tabulaires) ; la finition
  typographique reste en phase 14.
- **Vitest + Testing Library** (unitaires et composants), **Playwright** (parcours contre une
  API réelle). En CI : types à jour, lint, typecheck, Vitest, build ; les e2e se lancent en
  local jusqu'à la phase 12.
- **Mode sombre** dès maintenant : tokens `.dark` du prototype, `next-themes`, bouton dans
  l'en-tête (clair / sombre / système).
- `cn` vient du paquet officiel `cn` (shadcn), qui remplace `clsx` + `tailwind-merge`.
- pnpm via corepack, Node 22.

## Conséquences

- Les variables HSL du prototype sont conservées telles quelles ; les rares composants shadcn
  qui lisaient une variable brute (`var(--popover)`) l'enveloppent dans `hsl()`.
- Le jeu `chart-1…5` du prototype ne passe pas le validateur de palette **catégorielle**
  (chroma de `chart-1` en clair, bande de clarté en sombre). La phase 11 n'utilise qu'une
  série (`chart-1`) ; un graphique multi-séries (phases 13-14) devra revoir ce jeu.
- Badges de statut **teintés** (variantes `neutral/info/success/warning/danger`), jamais pleins
  comme un bouton (défaut du prototype corrigé).
