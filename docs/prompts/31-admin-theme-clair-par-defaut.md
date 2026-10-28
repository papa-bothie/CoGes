# Prompt 31 — Administration : thème clair par défaut et bascule clair / sombre

Branche `feat/admin-theme-toggle`, depuis `main` à jour (après la fusion des PR 37 et 38 du lot admin 6). Petit lot, `frontend-admin/` seulement.

Pourquoi : l'administration suit aujourd'hui le réglage du téléphone ou de l'ordinateur (`@media (prefers-color-scheme: dark)` dans `frontend-admin/app/globals.css`) et n'offre aucune bascule. Décision du propriétaire : **clair par défaut**, et un bouton pour passer au sombre et revenir au clair.

```
Lot « Administration : thème clair par défaut et bascule » (branche feat/admin-theme-toggle,
depuis main à jour). Règles habituelles : ADR au prochain numéro libre (ou addendum à
l'ADR 0094 si tu juges que c'est plus clair), tests d'abord (rouge puis vert), aucun service
payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/. Résumé
en français à la fin. Ne touche ni au backend, ni à frontend/ (l'application des
commerçants garde son thème actuel).

T1. Clair par défaut, indépendant du système
- À la première visite, l'administration est CLAIRE même si l'appareil est en mode sombre.
  Retire la décision par `prefers-color-scheme` : les jetons sombres ne s'appliquent que si
  la personne a choisi le sombre (attribut `data-theme="dark"` sur <html>, ou classe — ce qui
  s'accorde le mieux avec les jetons existants, sans dupliquer leurs valeurs).
- Pas d'éclair du mauvais thème au chargement : le thème choisi est posé AVANT l'affichage
  (petit script en ligne dans le layout racine, compatible avec la CSP de
  frontend-admin/next.config.ts — vérifie `script-src` et n'ajoute 'unsafe-inline' que s'il
  y est déjà ; sinon un nonce ou un fichier statique).
- `color-scheme` suit le thème (barres de défilement et champs natifs corrects).

T2. Bascule
- Un bouton « Passer en mode sombre » / « Passer en mode clair » dans la coque (en-tête ou
  bas du menu latéral), visible aussi sur mobile et sur l'écran de connexion. Icône
  soleil / lune de la même bibliothèque que le reste, nom accessible qui change avec l'état,
  `aria-pressed`, cible tactile de 44 px, aucun libellé réduit à la seule icône pour le
  lecteur d'écran.
- Deux états seulement (clair, sombre), pas de « système ».
- Le choix est mémorisé dans le navigateur (localStorage sous try/catch ; l'écran marche
  sans, retour au clair), propre à l'administration (clé préfixée, aucune interférence avec
  l'application des commerçants), et suit l'onglet voisin via l'événement `storage`.
- La page de connexion et la page d'acceptation d'invitation respectent le même choix.

T3. Tests (rouge d'abord)
- Vitest du composant : état initial clair, bascule, mémorisation, stockage indisponible.
- E2E (Playwright, administration) : navigateur en mode sombre forcé (`colorScheme: "dark"`)
  -> la page s'ouvre CLAIRE ; clic sur la bascule -> sombre ; rechargement -> sombre ;
  second clic -> clair ; aucun éclair (le premier rendu a déjà le bon thème) ; axe 0
  violation dans les DEUX thèmes sur chaque écran existant ; 360 px sans défilement
  horizontal ; clavier seul.
- Le garde-fou d'absence de couleur en dur de frontend-admin/ reste vert.

Fin de lot
make admin-check, make admin-e2e, CI verte. Captures avant / après (clair et sombre) dans
docs/design/captures/admin/. Mets à jour frontend-admin/README.md et CLAUDE.md §8.
```

## Ce que le propriétaire fait lui-même

Ouvrir l'administration sur un appareil en mode sombre : elle doit s'afficher claire. Appuyer sur la bascule, recharger : le sombre doit rester. Aucune autre action.
