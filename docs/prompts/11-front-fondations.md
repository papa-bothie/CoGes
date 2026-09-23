# Phase 11 — Frontend : fondations, design system, client API, authentification

---

Tu es l'agent de développement du projet **CoGes**. Le backend V1 est terminé. Nous démarrons la
**phase 11 : fondations du frontend Next.js**. L'apparence s'inspire du **prototype Bolt**
(déjà analysé), mais le fonctionnement suit l'architecture : **aucune règle métier dans le
front**, qui consomme uniquement l'API REST.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 10 ✅ exigée, ou phase 07 ✅ avec un OpenAPI figé si nous avons décidé
   d'avancer en parallèle) et les ADR, en particulier le **transport des jetons** (phase 02).
2. Lis :
   - `docs/design/prototype-reference.md` (tokens, structure, composants, **défauts à ne pas
     copier**) et `docs/design/prototype-bolt-prompt.md` (écrans).
   - Architecture : Diagramme 1, couche Frontend (« aucune règle métier, aucun accès base ; les
     permissions ne sont qu'un confort d'affichage ») ; Diagramme 10, arborescence `frontend/`.
   - `backend/openapi.json`.
3. Si tu as accès à un navigateur, ouvre https://coges-visual-sales-p-ijo3.bolt.host pour voir le
   prototype. Sinon, appuie-toi sur `prototype-reference.md`.
4. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
5. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Un squelette Next.js déployable : design tokens du prototype, composants de base, coquille de
l'application (barre latérale, en-tête), connexion et déconnexion réelles contre l'API, client
typé généré depuis l'OpenAPI, formats FCFA et dates, garde de permissions d'affichage.

## 2. Questions à me poser (AskUserQuestion)

1. **Pile UI** : Next.js 15 App Router + TypeScript strict + Tailwind + shadcn/ui + lucide-react
   (Recommandé : la pile du prototype, donc tokens et composants réutilisables tels quels) /
   autre bibliothèque de composants.
2. **Données côté client** : TanStack Query pour le cache et les mutations, avec les Server
   Components pour le premier rendu quand c'est simple (Recommandé) / Server Components et Server
   Actions uniquement / SWR.
3. **Client typé** : `openapi-typescript` + `openapi-fetch`, types générés dans `frontend/types/`
   par `pnpm gen:api` (Recommandé : léger, zéro code généré à maintenir) / Orval (génère aussi les
   hooks React Query) / hey-api.
4. **Formulaires** : react-hook-form + zod, avec les schémas zod **dérivés** des types OpenAPI
   quand c'est possible (Recommandé) / Formik / sans bibliothèque.
5. **Graphiques** : Recharts, comme le prototype (Recommandé) / Tremor / visx.
6. **Police** : je propose 2 ou 3 polices lisibles avec chiffres tabulaires (par exemple Inter,
   Geist, IBM Plex Sans) et tu choisis ; la finition typographique viendra en phase 14.
7. **Tests front** : Vitest + Testing Library pour les composants, Playwright pour les parcours
   de bout en bout contre l'API de préproduction ou locale (Recommandé) / Playwright seulement.
8. **Mode sombre** : tokens dark du prototype dès maintenant, avec un bouton dans l'en-tête
   (Recommandé : les tokens existent déjà) / plus tard.

## 3. Périmètre

- Projet `frontend/` selon le Diagramme 10 : `app/(auth)/login`, `app/(app)/layout.tsx` (coquille
  protégée), `components/{ui,charts,data-table,alerts,forecast}`,
  `lib/{api,auth,format}`, `lib/permissions.ts`, `hooks/`, `types/` (généré).
- **Design tokens** : les variables HSL `:root` et `.dark` de `prototype-reference.md`, à
  l'identique, branchées dans la configuration Tailwind ; rayon `0.5rem`.
- **Composants de base** : Button, Input, Select, Dialog, Sheet, Tabs, Badge (statuts **discrets**,
  différents des boutons), Card, KpiCard, AlertBanner, EmptyState, Skeleton, Toast, et un
  **DataTable** générique (tri, recherche, filtres, pagination **côté serveur**, colonnes
  numériques alignées à droite, `nowrap`, chiffres tabulaires).
- **Coquille** : barre latérale (logo, **nom de l'entreprise sans sélecteur**, navigation dans
  l'ordre du prototype, version) ; en-tête (titre, entreprise, utilisateur, rôle, cloche reliée à
  `/notifications` avec son compteur, bouton de déconnexion, bouton de thème). Pas de bandeau
  « démo ».
- **Authentification** : écran de connexion avec **identifiant d'entreprise (slug) + e-mail + mot
  de passe** ; gestion des jetons conforme à l'ADR de la phase 02 (refresh silencieux, déconnexion
  sur échec) ; middleware Next.js qui protège `(app)`.
- **Permissions d'affichage** : `lib/permissions.ts` lit les permissions renvoyées par l'API et
  masque ou désactive les actions. Rappel : **le serveur reste l'unique juge**.
- **Formats** (`lib/format/`) : `formatMoney` (`Intl.NumberFormat('fr-FR')`, XOF sans décimales,
  « 1 234 567 FCFA »), les montants API reçus en **chaîne** et jamais convertis en `float` pour un
  calcul (affichage seulement) ; `formatDate` (jj/mm/aaaa, fuseau de l'entreprise), `formatQty`.
- **Erreurs** : le format `{ error: { code, message } }` est traduit en toasts ou en messages de
  champ ; 404 ⇒ page « introuvable » ; 401 ⇒ tentative de refresh puis retour au login.
- Pages vides (titre + état vide) pour chaque entrée de navigation, afin de valider la coquille.
- Déploiement Vercel du frontend (preview), avec l'URL de l'API en variable d'environnement.

## 4. Règles à respecter

- Aucun calcul métier (totaux, marge, stock) dans le front : on affiche ce que l'API renvoie.
  Seule exception, un **aperçu** non contractuel des totaux dans un formulaire, remplacé par la
  réponse du serveur.
- Types API jamais écrits à la main.
- Accessibilité : labels, focus visible, contraste AA, navigation au clavier.
- Interface en français ; textes regroupés dans un fichier de libellés pour éviter la dispersion.

## 5. Vérification

`pnpm lint && pnpm typecheck && pnpm test` ; Playwright : connexion → coquille → navigation →
déconnexion ; captures d'écran de la coquille en clair et en sombre, comparées au prototype.

## 6. Clôture

ADR (pile front, client typé, gestion des jetons côté front) ; `CLAUDE.md` mis à jour (commandes
front comprises) ; résumé.
