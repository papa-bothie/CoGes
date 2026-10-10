---
name: CoGes
description: Gestion commerciale pour PME ouest-africaines — vente, stock, argent, décision. Simple, chaleureux, coloré (maquette v2).
colors:
  vert-marque: "#024A2C"
  vert-action: "#117A3C"
  vert-eclat: "#1A9A4C"
  papier: "#FBF8F3"
  carte: "#FFFFFF"
  bordure: "#ECE6DC"
  bordure-champ: "#E3DCD0"
  filet: "#F0EBE2"
  voile: "#F3EEE5"
  voile-2: "#F6F2EB"
  encre: "#1E2320"
  encre-2: "#3C4440"
  sourdine: "#5B625E"
  ventes: "#117A3C"
  ventes-teinte: "#E6F4EC"
  ventes-encre: "#024A2C"
  stock: "#C2410C"
  stock-teinte: "#FFF0E3"
  stock-encre: "#9A3412"
  argent: "#1F5BD8"
  argent-teinte: "#EAF1FD"
  argent-encre: "#1747AE"
  clients: "#6D3FC8"
  clients-teinte: "#F2ECFC"
  clients-encre: "#5530A3"
  depenses: "#A51D24"
  depenses-teinte: "#FDECEC"
  depenses-encre: "#A51D24"
  conseils: "#0E7490"
  conseils-teinte: "#E3F3F6"
  conseils-encre: "#0B5566"
  barre-claire: "#BFE3CF"
  barre-sortie: "#E8833A"
typography:
  titre-page:
    fontFamily: "Figtree, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 800
    letterSpacing: "-0.01em"
  titre-carte:
    fontFamily: "Figtree, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 700
  libelle:
    fontFamily: "Figtree, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 700
  corps:
    fontFamily: "Figtree, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.45
  chiffre:
    fontFamily: "Figtree, system-ui, sans-serif"
    fontSize: "28px à 36px"
    fontWeight: 800
    fontFeature: "tnum"
  chiffre-heros:
    fontFamily: "Figtree, system-ui, sans-serif"
    fontSize: "52px"
    fontWeight: 800
    fontFeature: "tnum"
  recu:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "13px"
rounded:
  carte: "22px"
  tuile: "20px"
  bouton: "18px"
  champ: "16px"
  touche: "14px"
  mini: "12px"
  puce: "999px"
spacing:
  cible: "48px"
  bouton: "56px"
  champ-montant: "64px"
  bouton-principal: "68px"
  touche: "56px"
  page-max: "1180px"
  marge-page: "24px"
  sections: "20px"
  carte: "22px"
components:
  button-principal:
    backgroundColor: "{colors.vert-action}"
    textColor: "#FFFFFF"
    rounded: "{rounded.bouton}"
    height: "68px"
    typography: "20px, 800"
  button-standard:
    backgroundColor: "{colors.vert-action}"
    textColor: "#FFFFFF"
    rounded: "{rounded.bouton}"
    height: "56px"
    typography: "{typography.libelle}"
  button-secondaire:
    backgroundColor: "{colors.carte}"
    textColor: "{colors.encre}"
    border: "2px {colors.bordure-champ}"
    rounded: "{rounded.bouton}"
    height: "56px"
  card:
    backgroundColor: "{colors.carte}"
    border: "1px {colors.bordure}"
    rounded: "{rounded.carte}"
    padding: "22px"
  stat-tile:
    backgroundColor: "{colors.<rubrique>-teinte}"
    rounded: "{rounded.carte}"
    padding: "22px"
    minHeight: "170px"
  chip:
    border: "2px {colors.bordure-champ}"
    rounded: "{rounded.puce}"
    height: "48px"
  field:
    border: "2px {colors.bordure-champ}"
    rounded: "{rounded.champ}"
    height: "56px"
    focus: "outline 3px <rubrique>-anneau, bordure <rubrique>"
  amount-field:
    height: "64px"
    typography: "28px, 800"
  status-pill:
    rounded: "{rounded.puce}"
    padding: "6px 12px"
    typography: "15px, 700"
---

<!--
  Système de la maquette v2 (phase 15, lot F, ADR 0064). Source normative des valeurs :
  docs/design/maquette-v2/tokens.css, reprise dans frontend/app/globals.css (jetons
  `--coges-*` puis rôles des composants). Ce fichier les décrit. Le système de la phase 14
  (bleu pétrole, Inter) est remplacé ; son histoire reste dans l'ADR 0056 et les audits
  docs/design/audit-phase-14-*.md.
-->

# Design System: CoGes (maquette v2)

## Overview

CoGes s'adresse à un commerçant qui n'a pas fait d'études : **chaque écran se comprend sans
lire, chaque action se fait en quelques touches**. Le style validé par le propriétaire du
produit est **chaleureux et coloré** : fond papier crème, cartes blanches très arrondies,
grands chiffres gras, une couleur par rubrique, et de grosses cibles tactiles.

La référence est la maquette de `docs/design/maquette-v2/` (26 écrans, captures à 1280 et
390 px). Les textes sont repris mot pour mot, les valeurs viennent de `tokens.css`. Toute
différence voulue est notée dans `docs/design/maquette-v2/ecarts.md`, et
`make maquette-check` mesure l'écart de chaque écran livré (2 % de pixels au plus).

## Colors

### Marque
Les verts viennent du logo : **vert de marque** `#024A2C` (textes sur teinte verte, nom
« CoGes »), **vert d'action** `#117A3C` (boutons principaux, texte blanc dessus, 5,4:1),
**vert éclat** `#1A9A4C` (graphiques et icônes de succès, jamais du texte).

### Une couleur par rubrique
Chaque rubrique a un trio **plein / teinte / encre** : le plein pour un bouton ou un disque
d'icône, la teinte pour une tuile ou un encart, l'encre pour le texte posé sur la teinte.

| Rubrique | Plein | Teinte | Encre |
|---|---|---|---|
| Ventes | `#117A3C` | `#E6F4EC` | `#024A2C` |
| Stock | `#C2410C` | `#FFF0E3` | `#9A3412` |
| Argent | `#1F5BD8` | `#EAF1FD` | `#1747AE` |
| Clients | `#6D3FC8` | `#F2ECFC` | `#5530A3` |
| Dépenses | `#A51D24` | `#FDECEC` | `#A51D24` |
| Conseils | `#0E7490` | `#E3F3F6` | `#0B5566` |

Classes Tailwind : `bg-ventes`, `bg-ventes-teinte`, `text-ventes-encre`, et ainsi de suite.
L'anneau de focus d'un champ prend la couleur claire de sa rubrique (`outline-ventes-anneau`),
relevée dans les pages de la maquette.

### Fond et texte
Papier `#FBF8F3` (page), carte `#FFFFFF`, bordure `#ECE6DC`, bordure de champ `#E3DCD0`,
filet `#F0EBE2`, voile `#F3EEE5` (survol, fond neutre). Encre `#1E2320`, encre secondaire
`#3C4440`, sourdine `#5B625E` (6:1 sur papier).

### Carrés d'article
Douze couleurs pleines relevées dans la maquette (`bg-article-1` à `bg-article-12`), lettre
blanche. La couleur d'un article est **tirée de son nom** (ADR 0064) : aucune colonne en base.

### Rôles des composants
Les composants shadcn lisent des rôles (`background`, `primary`, `muted-foreground`,
`success-ink`…) qui pointent vers ces jetons dans `globals.css`. Les encres d'état de
l'ADR 0056 sont les encres de rubrique : succès = ventes, alerte = stock, danger = dépenses.

### Mode sombre (dérivé, soumis à l'accord du propriétaire)
La maquette n'en a pas : il est dérivé des mêmes jetons. Fond vert-noir chaud `#111612`,
cartes `#19201B`, teintes de rubrique assombries (`#15301F` pour ventes…), encres éclaircies
(`#8FDCAE`…), pleins éclaircis avec texte sombre dessus. Le logo y prend la silhouette du vert
de marque éclairci. Contraste AA vérifié par axe, en clair et en sombre.

### Named Rules
- **Aucune couleur en dur.** Tout vient du thème ; un test d'architecture
  (`lib/no-hardcoded-colors.test.ts`) refuse `#hex`, `rgb()`, `hsl()` et les palettes Tailwind
  dans `app/` et `components/`.
- **Le vert éclat n'écrit jamais.** Il colore les barres et les icônes, pas le texte.
- **Une rubrique, une couleur.** Un élément prend la couleur de la rubrique où il vit.

## Typography

**Figtree** (variable, graisses 400 à 800), chiffres tabulaires pour les montants.
**JetBrains Mono** pour le reçu imprimé. Les deux sont hébergées dans `frontend/app/fonts/`
(licence OFL) : le fichier de `next/font/google` n'a pas de table `prep`, et Chrome sous Linux
élargit alors certaines lettres.

### Hierarchy
- **Titre de page** (`text-titre-page`) : 30 px, gras 800.
- **Titre de carte** (`text-titre-carte`) : 20 px, gras 700.
- **Libellé de champ** (`text-libelle`) : 17 px, gras 700.
- **Corps** (`text-corps`) : 16 px. **Jamais moins de 15 px** pour un texte courant :
  `text-sm` vaut 15 px dans tout le front.
- **Chiffre de tuile** : 28 à 36 px, gras 800, tabulaire. **Chiffre héros** (« Vous avez
  gagné ») : 52 px.
- **Montants** : « 87 500 F » (`formatAmount`), espace insécable entre les milliers.

## Layout

Page de 1180 px au plus (1240 px pour « Nouvelle vente »), marge de 24 px (16 px sur
téléphone), 20 px entre sections, cartes de 22 px de marge intérieure. Chaque écran porte sa
largeur ; la coquille ne donne que les marges.

**Navigation (lot 3a, ADR 0070).** Au-dessus de 768 px, **barre du haut** : logo et nom de
la boutique, cinq onglets (Accueil, Vendre, Stock, Clients, Argent) dont l'actif prend la
teinte de sa rubrique, puis Conseils, la cloche et l'engrenage. La cloche mène aux alertes ;
son badge n'apparaît que pour une alerte grave non lue. L'engrenage ouvre un menu : la
personne et son rôle, Réglages, Mode sombre, Se déconnecter (et Conseils sur téléphone). Le
vendeur ne voit qu'Accueil, Vendre et Clients. Au-dessous de 768 px, en-tête compact (logo,
nom, cloche, engrenage) et **barre basse** fixe à cinq entrées : l'écran 26 est la
référence du téléphone. Le reçu et le bon de retour s'affichent seuls, sans barres. Plus de
réglage de densité : 48 px partout.

## Shapes

Cartes 22 px, tuiles 20 px, boutons 18 px, champs 16 px, touches et carrés 14 px, petits
champs 12 px, puces et pastilles en pilule. Bordure de 2 px sur les champs, puces et boutons
secondaires ; 1 px sur les cartes.

## Components

Tous dans `frontend/components/kit/`, montrés par `/dev/composants` (développement seulement).

- **Boutons** (`Button`, tailles `principal` 68 px et `standard` 56 px, variante
  `secondaire` bordée, et une variante pleine par rubrique).
- **Tuile chiffrée** (`StatTile`) : teinte de rubrique, disque d'icône plein, libellé, grand
  chiffre, précision à l'encre ; version compacte pour le téléphone.
- **Carte** (`KitCard`) : titre h2 et action à droite.
- **Puce** (`Chip`) : choisie en teinte ou en plein ; `aria-pressed`.
- **Grand choix exclusif** (`ChoiceGroup`) : groupe radio de grosses cases (64 px).
- **Champ montant + pavé numérique** (`AmountField`, `NumericPad`, `AmountShortcuts`) : le
  montant se **tape librement**, le pavé et les raccourcis ne sont que des raccourcis.
- **Champ quantité** (`QuantityStepper`) : − champ +, saisie libre, virgule acceptée.
- **Pastille d'état** (`StatusPill`) : Payé, Reste X F, Retour : X F, Annulée, Dette
  abandonnée.
- **Ligne de liste** (`ListRow`), **avatar à initiales** (`Avatar`), **carré d'article**
  (`ProductSquare`).
- **Tuiles de choix avec icône** (`ChoiceTiles`) : raisons, catégories de dépense.
- **Bandeau** (`Banner`), **écran de succès** (`SuccessScreen`), **message d'aide**
  (`FieldHint`).
- **Barres des 7 jours** (`DayBars`) : valeur au-dessus, jour en cours en vert plein.
- **Interrupteur** (`ToggleSwitch`) : 64 × 36 px.
- **Barres de navigation** (`TopBar`, `TabLink`, `BottomNav`) et **logo** (`components/brand/`).

Écrans du lot 3a, dans `frontend/app/(app)/` : accueil (`dashboard/`), nouvelle vente
(`sales/sale-editor.tsx`, `product-grid.tsx`, `ticket-line.tsx`, `sale-success.tsx`), liste
et détail des ventes, reçu (`sales/[id]/receipt/`, ticket en JetBrains Mono et facture A4),
retour d'articles et bon de retour. Aides d'affichage : `lib/sale-status.ts` (pastille d'une
vente), `lib/units.ts` (« 2 sacs », « Vente n° 1044 »), `lib/whatsapp.ts` (reçu en texte,
lien `wa.me`), `lib/number-words.ts` (montant en toutes lettres), `lib/refund.ts` (valeur
rendue, même formule que le serveur).

Écrans du lot 3b (ADR 0071) : Stock (`products/products-list-view.tsx` : valeur du stock,
raccourcis, puces d'état et de rayon, barre de niveau verte, orange ou vide), fiche article
(`products/[id]/` : prix changés sur place, historique en phrases, étiquettes), nouvel
article avec écran de succès (`products/new/`), Rayons (`products/categories/` : huit
couleurs, suppression d'un rayon vide seulement), correction (`components/inventory/
stock-correction.tsx`, `/inventory/adjust`), livraison (`components/inventory/
delivery-form.tsx`, `/inventory/receive`) et « Tous les mouvements » (`/inventory`). Aides :
`lib/shelf-colors.ts` (couleur d'un rayon, la sienne ou tirée du nom), `lib/stock-history.ts`
(phrase, genre, date et quantité d'une ligne d'historique).

## Do's and Don'ts

### Do:
- Reprendre les textes de la maquette mot pour mot, sans abréviation.
- Garder toute cible cliquable à 48 px au moins.
- Laisser taper tout nombre librement.
- Noter dans `ecarts.md` toute différence voulue, avec l'accord du propriétaire.

### Don't:
- Écrire une couleur, un rayon ou une taille hors du thème.
- Expliquer une formule en texte : elle se montre.
- Utiliser le vert éclat pour du texte.
- Afficher un carré vert avec un « C » : le logo officiel le remplace partout.
