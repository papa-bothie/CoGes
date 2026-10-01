# 0056 — Finition visuelle (phase 14) : direction, typographie, mise en page, densité

- **Date** : 2026-09-30
- **Phase** : 14
- **Statut** : acceptée (complétée à chaque passe)
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

La phase 14 fait passer l'interface d'un état « prototype repris à l'identique » (ADR 0046) à une
interface soignée, **sans changement fonctionnel** : aucune règle, aucun appel d'API, aucun
parcours ne change. Elle s'appuie sur la skill Impeccable, par passes validées une à une
(`docs/prompts/14-polish-impeccable.md` § 3). L'état de départ et l'audit sont consignés dans
`docs/design/audit-phase-14-avant.md`.

## Décisions

1. **Direction** : raffiner l'identité du prototype (bleu pétrole sobre), ne pas la remplacer.
   Périmètre : toutes les pages. Animations : discrètes, `prefers-reduced-motion` respecté.
2. **Emplacement du système de design** : `docs/design/DESIGN.md` et `docs/design/PRODUCT.md`
   font foi. Impeccable ne lit que la racine et n'a aucun réglage de chemin : `DESIGN.md` et
   `PRODUCT.md` à la racine sont des **liens symboliques** vers `docs/design/` (aucune copie qui
   puisse diverger). Le fichier annexe `.impeccable/design.json` est versionné.
3. **Accessibilité mesurée** : `@axe-core/playwright` (devDependency) et `e2e/a11y.spec.ts`
   (WCAG 2.1 AA, 16 écrans, clair et sombre). Rapports conservés par passe dans
   `docs/design/captures/phase-14/<passe>/a11y-*.json`. `A11Y_STRICT=1` rend bloquantes les
   violations sérieuses et critiques.
4. **Audit** : les 19 constats sont retenus ; les passes suivent l'ordre du prompt.
5. **Typographie (passe 3)** : **Inter conservée**, avec son axe optique (`opsz`, +25 Ko sur la
   police préchargée). Échelle **par rôle** en tokens `@theme` (`text-page-title`,
   `text-heading`, `text-figure`, `text-figure-sm`, `text-2xs`). Texte courant **14 px**,
   **16 px en densité confortable**. En-têtes de tableau en rôle *label* (12 px, gris), toute
   cellule en chiffres tabulaires.
6. **`cn` configuré** (`lib/utils.ts`, `createCn`) : les rôles typographiques sont déclarés comme
   tailles ; sinon la fusion les prenait pour des couleurs et les supprimait. Tous les
   composants importent `cn` depuis `@/lib/utils`, plus jamais depuis `"cn"`.
7. **Mise en page (passe 4)** :
   - **En-tête = fil d'Ariane** (« Ventes › Nouvelle vente ») : section en lien, titre déclaré
     par `PageHeader` via un contexte ; plus de titre répété. Hauteur 56 px.
   - **Barre latérale repliée sous 1024 px** (`lg`, au lieu de `md`).
   - **Nouvelle vente sous 1280 px** : barre fixée en bas avec le total, « Enregistrer en
     brouillon » et « Confirmer la vente » ; Totaux et Règlement côte à côte. Un seul bouton de
     confirmation dans le DOM.
   - **Cartes KPI compactes**, sans pastille d'icône (≈ 110 px au lieu de 170).
   - **Colonnes d'appoint** (`secondary` sur `DataTable`) masquées sous `lg`.
   - **Panneaux latéraux** : la largeur passée par l'appelant l'emporte enfin sur celle du
     composant de base ; les valeurs des listes de définitions peuvent passer à la ligne.
8. **Densité des tableaux** : réglage **du navigateur** (`localStorage`, clé `coges-density`),
   compacte par défaut, aucune donnée serveur ; menu dans l'en-tête ; attribut `data-density`
   posé avant l'affichage par un script en ligne (la CSP autorise déjà `'unsafe-inline'`).
9. **Couleurs (passe 5)** : un jeton d'**encre** par état (`--success-ink`, `--warning-ink`,
   `--danger-ink`, clair et sombre) pour tout texte d'état ; les jetons d'état restent pour les
   fonds et les graphiques. Gris d'annotation foncé (47 % → 42 %). Texte foncé sur fond plein
   vert ou orange ; rouge sombre aligné sur le clair (blanc lisible dessus). Survol des menus en
   gris (le jeton `accent`, vert encaissé, n'est plus une couleur d'interface). Seuil bas en
   orange partout, rupture en rouge ; lignes du stock non teintées (le badge suffit) ; cartes
   d'Intelligence lues sans opacité. Graphique de chiffre d'affaires **en barres**
   (`PeriodBarChart`, ex-`AreaChart`). Résultat axe : 220 → 1 violation en clair, 23 → 1 en sombre.

## Conséquences

- Aucun changement d'API ni de schéma ; les e2e des phases 11 à 13 restent le garde-fou.
- Les nouveaux styles passent par les tokens et les composants partagés (`components/ui`,
  `components/*`), jamais par une page isolée.
- ESLint ignore `playwright-report/` et `test-results/` (artefacts déjà ignorés par git).
- La densité n'est pas synchronisée entre appareils (choix assumé : aucune préférence serveur).
