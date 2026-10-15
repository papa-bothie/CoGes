# Audit Impeccable — fin de la phase 15 (maquette v2)

> Relevé le 15/10/2026 sur `chore/phase15-closure`, après la fusion des lots 0 à 3e-2. Il se
> compare à l'audit de fin de phase 14 (`audit-phase-14-apres.md`, 18/20).
>
> Sources :
> - détecteur Impeccable sur `frontend/app` et `frontend/components`, avec et sans la
>   configuration du projet ;
> - axe WCAG 2.1 AA en clair et en sombre (`e2e/a11y.spec.ts`, suite `make front-e2e` verte) ;
> - Lighthouse accessibilité sur les 26 écrans de la maquette et les quatre rubriques des
>   Réglages (`make lighthouse`, `captures/phase-15/lighthouse.md`) ;
> - cibles tactiles de 48 px sur `pointer: coarse` (`e2e/touch-targets.spec.ts`) ;
> - comparaison à la maquette (`make maquette-check`, 41 écrans et états) ;
> - captures clair, sombre et 390 px (`captures/phase-15/`) ;
> - lecture du code.

## Note de santé : phase 14 → phase 15

| # | Dimension | Phase 14 | Phase 15 | Constat principal |
|---|---|---|---|---|
| 1 | Accessibilité | 3/4 | **3/4** | axe : 0 violation en clair et en sombre. Lighthouse : 100 sur 30 pages. Toujours aucun passage manuel au lecteur d'écran ni au zoom 200 % |
| 2 | Performance | 4/4 | **4/4** | aucun `backdrop-blur`, `transition-all` ni `will-change`. Recharts reste dans trois écrans seulement |
| 3 | Adaptation | 3/4 | **4/4** | chaque écran a sa capture à 390 px, barre basse sur téléphone (écran 26), cibles de 48 px vérifiées, largeurs fixes toutes bornées (`max-w-…`) |
| 4 | Thème | 4/4 | **4/4** | jetons `--coges-*` et rôles, test qui interdit les couleurs en dur, sombre dérivé, 0 violation axe en sombre |
| 5 | Intégrité | 4/4 | **3/4** | détecteur : 0 constat. Trois pages secondaires gardent les tableaux et petits boutons de la phase 13 |
| **Total** | | **18/20** | **18/20** | **Excellent** : score conservé |

## Verdict d'intégrité : **réussi**

L'identité a changé de monde, avec l'accord du propriétaire (ADR 0064) : celui de la maquette
v2, chaleureux et coloré, tenu par le système.
- Une couleur par rubrique, des jetons de rôle et la police Figtree.
- Des composants du kit (`components/kit/`) réutilisés d'un écran à l'autre : puces, tuiles, interrupteurs, lignes, pavé, montants.
- Une vitrine de développement.

Le détecteur ne relève **aucun** constat, ni avec ni sans la configuration du projet
(`impeccable detect --no-config`). Les règles d'affichage métier tiennent :
- métrique nommée, date de calcul, modèle et incertitude derrière « Pourquoi ? » ;
- « Données insuffisantes » ;
- montants « 87 500 F » sans décimales ;
- textes en mots simples, testés.

## Résumé

- **18/20 (Excellent)**, comme en fin de phase 14.
- Constats : 0 P0, 0 P1, 2 P2, 2 P3.
- Points d'attention :
  1. **[P2] Deux mondes sur les pages secondaires** : « Toutes les dettes », « Toutes les dépenses » et le journal des mouvements gardent `DataTable` et les boutons `sm` / `icon-sm` de la phase 13.
  2. **[P2] Aucun passage manuel** au lecteur d'écran ni au zoom 200 %. Les vérifications restent automatiques (axe, Lighthouse).
  3. **[P3] Boutons d'icône de 28 px à la souris** (fermeture des fenêtres, pagination). Ils sont conformes WCAG 2.2 AA (24 px) et passent à 48 px au toucher.
  4. **[P3] La grille « Qui peut faire quoi » défile à 390 px**, comme la maquette, au lieu de se replier en cartes.

## Constats détaillés

**[P2] Pages secondaires dans le style de la phase 13**
- **Emplacement** : `app/(app)/finance/debts-tab.tsx`, `finance/expenses-tab.tsx`, `inventory/movement-journal.tsx`, `components/data-table/`.
- **Catégorie** : intégrité.
- **Impact** : en quittant un écran de la maquette par « Toutes les dettes » ou « Tous les mouvements », on change de densité, de taille de texte et de boutons. Rien n'est cassé, mais le passage se voit.
- **Recommandation** : reprendre ces trois listes avec `ListRow`, `Chip` et `StatusPill`, et garder `DataTable` pour l'export de masse seulement.
- **Commande** : `/impeccable polish`.

**[P2] Accessibilité vérifiée par automates seulement**
- **Catégorie** : accessibilité.
- **Impact** : axe et Lighthouse ne voient pas l'ordre de lecture réel, l'annonce des mises à jour (« Droits enregistrés », pavé numérique) ni le zoom 200 %.
- **Norme** : WCAG 1.4.4, 4.1.3.
- **Recommandation** : un passage NVDA et VoiceOver sur la vente, l'encaissement et la grille des droits, et un passage au zoom 200 % à 1366 px.
- **Commande** : `/impeccable harden`.

**[P3] Petits boutons d'icône à la souris**
- **Emplacement** : `components/ui/dialog.tsx:65`, `components/ui/sheet.tsx:71`, `components/data-table/data-table.tsx:246`.
- **Catégorie** : adaptation.
- **Impact** : 28 px sous un pointeur fin. Ils montent à 48 px au toucher (ADR 0059, 0070).
- **Recommandation** : 36 px au moins partout, si les fenêtres le permettent.
- **Commande** : `/impeccable adapt`.

**[P3] Grille des droits sur téléphone**
- **Emplacement** : `app/(app)/settings/rights/rights-view.tsx`.
- **Catégorie** : adaptation.
- **Impact** : à 390 px, on fait défiler le tableau pour voir les colonnes Vendeur et Comptable, comme sur la maquette 24c.
- **Recommandation** : une carte par rôle sous 640 px.
- **Commande** : `/impeccable adapt`.

## Ce qui est systémique

Rien ne se répète au-delà des trois pages secondaires citées. Les écarts à la maquette sont
tous listés et datés dans `docs/design/maquette-v2/ecarts.md`.

## Ce qui marche

- **Lighthouse accessibilité : 100** sur les 26 écrans et les quatre rubriques des Réglages,
  page d'arrivée vérifiée (aucune mesure faite par erreur sur l'écran de connexion).
- **axe : 0 violation** en clair et en sombre, bloquant dans la suite e2e.
- **Fidélité à la maquette** : 41 écrans et états comparés ; ceux qui dépassent 2 % ont leur
  écart noté et approuvé.
- **Test du commerçant** mesuré en touches et frappes (`e2e/merchant.spec.ts`,
  `e2e/money.spec.ts`).
- **Aucune couleur en dur**, un test le garantit. Le mode sombre est dérivé des jetons.
- **Mots simples** sur le front et le serveur, testés contre les anciens termes (ADR 0069).

## Actions recommandées

1. **[P2] `/impeccable polish`** : ramener « Toutes les dettes », « Toutes les dépenses » et le
   journal des mouvements dans le monde de la maquette v2.
2. **[P2] `/impeccable harden`** : passage manuel au lecteur d'écran et au zoom 200 % sur les
   parcours vente, encaissement et droits.
3. **[P3] `/impeccable adapt`** : boutons d'icône à 36 px, grille des droits en cartes sous 640 px.
4. **`/impeccable polish`** en dernier, après ces corrections.
