# 0064 — Thème de la maquette v2 et composants du kit

- **Date** : 2026-10-07
- **Phase** : 15 (lot F)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-07) ; prompt de phase 15 (règles 2 et 3)

## Contexte
La phase 15 refait l'interface d'après la maquette v2 validée par le propriétaire du produit
(`docs/design/maquette-v2/`) : vert du logo, fond papier, une couleur par rubrique, police
Figtree, grosses cibles tactiles. Le système de la phase 14 (ADR 0056 : bleu pétrole, Inter,
`DESIGN.md`) est remplacé. Le lot F pose les fondations avant tout écran ; les lots 1 à 3
n'utilisent que ces composants.

## Options envisagées
1. **Remplacer le thème partout (retenue)** : les rôles existants (`primary`, `card`,
   `border`…) prennent les valeurs de `tokens.css`. Tous les écrans changent de couleurs et
   de police tout de suite ; leur mise en page reste celle de la phase 14 jusqu'au lot 3.
2. Thème à part pour les seuls nouveaux composants : deux thèmes pendant plusieurs PR.

Pour la couleur des carrés d'article (la maquette en donne une par article, le modèle de
données n'a aucune colonne) :
1. **Couleur tirée du nom (retenue)** : une des 12 couleurs de la maquette, stable, sans
   changement de base. Les carrés ne tombent pas sur les couleurs de la maquette (écart noté).
2. Colonne `color` sur `categories` et `products` : écart au modèle V1.1.
3. Colonne sur `categories` seulement : deux articles d'un rayon auraient la même couleur.

## Décision
- **Deux couches dans `globals.css`** : les jetons de la maquette (`--coges-*`, valeur pour
  valeur), puis les rôles des composants qui pointent vers eux. Classes de rubrique
  (`bg-ventes`, `bg-ventes-teinte`, `text-ventes-encre`, `outline-ventes-anneau`), rayons
  (`rounded-carte`, `rounded-bouton`…), tailles (`min-h-bouton`, `max-w-page`…), textes
  (`text-libelle`, `text-titre-page`…). `text-sm` passe à 15 px : jamais moins pour un texte
  courant. Les tailles et rayons sont déclarés à `cn` (tailwind-merge), sans quoi la fusion
  les prendrait pour des couleurs.
- **Valeurs relevées hors de `tokens.css`** : anneaux de focus par rubrique et 12 couleurs de
  carrés d'article, lus dans les pages `html/` de la maquette ; blanc fixe (pastille
  d'interrupteur), encre et papier du reçu, voile des fenêtres.
- **Mode sombre dérivé** des jetons (fond vert-noir chaud, teintes assombries, encres
  éclaircies), montré au propriétaire avec le lot F avant d'être livré écran par écran.
- **Polices hébergées** (`app/fonts/`, licence OFL) avec `next/font/local` : le fichier que
  télécharge `next/font/google` pour Figtree n'a pas de table `prep`, et Chrome sous Linux
  élargit alors certaines lettres (« connect er »). JetBrains Mono pour le reçu.
- **Logo officiel** (`public/brand/`, découpes nettoyées de leur halo) : symbole + nom +
  boutique dans la barre latérale, logo complet à la connexion, symbole en favicon et icône
  d'application. En sombre, sa silhouette au vert de marque éclairci.
- **Kit** `components/kit/` (barres de navigation, tuile chiffrée, carte, puce, grand choix,
  champ montant et pavé numérique, quantité, pastille, ligne de liste, avatar, carré
  d'article, tuiles de choix, bandeau, écran de succès, aide, barres des 7 jours,
  interrupteur) et vitrine `/dev/composants`, sans connexion, **404 en production**.
- **Montants au format court** « 87 500 F » (`formatAmount`, espace insécable) dans le kit ;
  le reste de l'interface y passe au lot 2.
- **Garde-fou** : `lib/no-hardcoded-colors.test.ts` refuse toute couleur en dur dans `app/`
  et `components/` (`#hex`, fonctions de couleur, palettes Tailwind, `bg-black`…).

## Conséquences
- Tous les écrans prennent les couleurs et la police de la maquette dès le lot F ; captures
  avant/après de chaque écran dans `docs/design/captures/phase-15/{avant,apres}/*/lot-f/`.
- `DESIGN.md` est réécrit d'après `tokens.css` ; l'ADR 0056 reste l'histoire de la phase 14.
- La navigation (barre du haut, barre basse) et la mise en page des écrans changent au lot 3.
- Les numéros d'ADR du prompt de phase 15 se décalent encore : « Références et codes-barres
  générés » devient 0066, « Raisons de correction en liste fermée » 0067, la refonte visuelle
  0068.
