# 0096 — Administration : clair par défaut et bascule clair / sombre

- **Date** : 2026-10-28
- **Phase** : prompt 31 (suite du lot admin 6)
- **Statut** : acceptée (amende l'ADR 0094, partie B, sur le choix du thème)
- **Décideur** : utilisateur (prompt 31 : « clair par défaut, et un bouton pour passer au sombre et revenir au clair »)

## Contexte
L'ADR 0094 donnait à `frontend-admin/` le thème CoGes en clair et en sombre, **selon le réglage
du système** (`@media (prefers-color-scheme: dark)`), sans bascule. Sur un téléphone ou un
ordinateur en mode sombre, l'administration s'ouvrait donc en sombre, ce que le propriétaire ne
veut pas par défaut.

## Options envisagées
1. **Attribut `data-theme` sur `<html>`, script en ligne dans le `<head>` (retenue)** : les jetons
   sombres passent de la requête média à `:root[data-theme="dark"]` (mêmes valeurs, aucun doublon),
   le script lit le choix mémorisé avant le premier affichage ; c'est le motif de la documentation
   de Next 16 (*Preventing flash before hydration*). La CSP a déjà `script-src 'self' 'unsafe-inline'`.
2. `next-themes`, comme `frontend/` : une dépendance de plus pour deux états, et un mode
   « système » qu'on ne veut pas.
3. Cookie lu par le serveur : rend le layout racine dynamique pour un réglage d'affichage.

## Décision
- Clair par défaut, quel que soit le système. Deux états seulement (clair, sombre).
- Choix mémorisé dans `localStorage` sous `coges-admin:theme` (préfixe propre, aucune
  interférence avec l'application des commerçants), lu et écrit sous `try/catch` : sans stockage,
  on reste en clair et la bascule vaut pour la page en cours. L'onglet voisin suit (`storage`).
- `color-scheme` suit le thème (`:root` et `[data-theme="dark"]`, et `style.colorScheme` posé par
  le script) : barres de défilement et champs natifs corrects.
- Bouton `components/theme-toggle.tsx` : icône lune / soleil de `lucide-react`, nom accessible
  « Passer en mode sombre » / « Passer en mode clair », `aria-pressed`, 44 px ; dans l'en-tête
  de la coque (visible sur téléphone), sur la connexion et sur la page d'invitation.
- `useSyncExternalStore` (`lib/theme.ts`) : le serveur rend le clair, React reprend la valeur
  réelle après l'hydratation, sans `setState` dans un effet.

## Conséquences
- `frontend/` n'est pas touché : l'application des commerçants garde son thème (système par défaut).
- Les e2e d'accessibilité et les captures ne pilotent plus le thème par `emulateMedia` : ils
  posent le choix mémorisé, l'appareil étant en sombre (`e2e/a11y.spec.ts`, `e2e/captures.spec.ts`).
- Tests : `lib/theme.test.ts` (script de démarrage : clair malgré un système sombre, sombre mémorisé,
  valeur inconnue, stockage qui refuse), `components/theme-toggle.test.tsx`, `e2e/theme.spec.ts`
  (système sombre ⇒ clair, bascule, rechargement, aucun éclair, clavier, onglet voisin, 360 px).
- Captures : `docs/design/captures/admin/apres/` (lot admin 6) sert d'« avant » ;
  `docs/design/captures/admin/theme/` est l'« après », appareil en sombre.
