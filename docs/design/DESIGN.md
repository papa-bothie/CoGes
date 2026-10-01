---
name: CoGes
description: Gestion commerciale pour PME ouest-africaines — vente, stock, argent, décision.
colors:
  bleu-petrole: "hsl(199 89% 28%)"
  bleu-petrole-nuit: "hsl(199 89% 48%)"
  vert-encaisse: "hsl(152 63% 40%)"
  vert-succes: "hsl(142 71% 45%)"
  orange-alerte: "hsl(32 95% 50%)"
  rouge-danger: "hsl(0 72% 51%)"
  violet-serie: "hsl(259 84% 56%)"
  papier: "hsl(210 20% 98%)"
  feuille: "hsl(0 0% 100%)"
  encre: "hsl(215 28% 17%)"
  gris-regle: "hsl(214 20% 88%)"
  gris-voile: "hsl(210 16% 95%)"
  gris-sourdine: "hsl(210 16% 93%)"
  gris-annotation: "hsl(215 16% 42%)"
  encre-succes: "hsl(145 63% 28%)"
  encre-alerte: "hsl(26 90% 33%)"
  encre-danger: "hsl(0 74% 40%)"
  encre-succes-nuit: "hsl(142 60% 60%)"
  encre-alerte-nuit: "hsl(35 95% 62%)"
  encre-danger-nuit: "hsl(0 90% 72%)"
  nuit: "hsl(215 28% 10%)"
  nuit-feuille: "hsl(215 28% 13%)"
  nuit-voile: "hsl(215 28% 18%)"
  nuit-regle: "hsl(215 28% 22%)"
  nuit-encre: "hsl(210 20% 92%)"
  nuit-annotation: "hsl(215 16% 60%)"
typography:
  page-title:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.33
    letterSpacing: "-0.02em"
  figure:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.33
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
  figure-sm:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.4
    fontFeature: "tnum"
  heading:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.43
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.33
  micro:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.45
    fontFeature: "tnum"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "20px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.bleu-petrole}"
    textColor: "{colors.feuille}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  button-outline:
    backgroundColor: "{colors.papier}"
    textColor: "{colors.encre}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  button-ghost:
    textColor: "{colors.encre}"
    rounded: "{rounded.md}"
    height: "36px"
  input:
    textColor: "{colors.encre}"
    rounded: "{rounded.lg}"
    padding: "4px 10px"
    height: "32px"
  card:
    backgroundColor: "{colors.feuille}"
    textColor: "{colors.encre}"
    rounded: "{rounded.xl}"
    padding: "16px"
  badge-status:
    backgroundColor: "{colors.gris-sourdine}"
    textColor: "{colors.gris-annotation}"
    rounded: "{rounded.md}"
    padding: "2px 8px"
    height: "20px"
  nav-item-active:
    backgroundColor: "{colors.bleu-petrole}"
    textColor: "{colors.feuille}"
    rounded: "{rounded.lg}"
    padding: "8px 12px"
  table-head:
    textColor: "{colors.gris-annotation}"
    typography: "{typography.label}"
    height: "40px"
    padding: "0 8px"
---

<!--
  État de référence relevé le 30/09/2026 avant la phase 14 ; typographie mise à jour par la
  passe 3 (typeset), mise en page par la passe 4 (layout),
  couleurs par la passe 5 (colorize). Chaque passe
  Impeccable qui change un token met ce fichier à jour. Source normative des valeurs :
  frontend/app/globals.css (triplets HSL shadcn) ; ce fichier les décrit.
-->

# Design System: CoGes

## Overview

**Creative North Star: "Le Registre de comptoir"**

CoGes se lit comme un livre de caisse moderne tenu au comptoir d'une boutique. Chaque écran est
un registre : des lignes calmes, des chiffres nets et alignés en colonne, un en-tête qui dit où
l'on est et combien d'éléments on regarde. Rien n'y est décoratif. Le bleu pétrole marque l'action
et l'endroit où l'on se trouve ; les autres couleurs n'apparaissent que pour dire un état (réglé,
en retard, en rupture, annulé).

La densité est celle d'un outil ouvert toute la journée sur un écran modeste : texte courant à
14 px, tableaux serrés, cartes plates cernées d'un filet. La profondeur n'est donnée qu'aux
éléments qui flottent au-dessus du registre (menus, panneaux, dialogues). Le mode sombre est un
registre de nuit : mêmes rôles, fonds bleu nuit, bleu pétrole éclairci.

**Key Characteristics:**
- Chiffres tabulaires, jamais coupés, alignés à droite dans les tableaux.
- Une seule couleur d'action (bleu pétrole) ; couleurs d'état réservées à leur sens.
- Surfaces plates, filets fins (1 px), ombres seulement sur ce qui flotte.
- Coins doucement arrondis, plus ronds à mesure que l'objet grandit (6 → 8 → 12 px).
- Pile shadcn/ui (Radix) + Tailwind 4 ; icônes lucide à traits fins.

## Colors

Une palette froide et retenue : un bleu pétrole profond sur des gris-bleus très clairs, et quatre
couleurs d'état vives réservées à la signalisation.

### Primary
- **Bleu pétrole** (`bleu-petrole`, #085F87) : boutons principaux, élément de navigation actif,
  anneau de focus, première série des graphiques, liens. En sombre : **Bleu pétrole de nuit**
  (`bleu-petrole-nuit`, #0DA2E7), texte bleu nuit dessus.

### Secondary
- **Vert encaissé** (`vert-encaisse`, #26A66A ; nuit #2FD085) : jeton `accent` du prototype,
  deuxième série des graphiques (encaissements, positif).

### Tertiary (couleurs d'état)
- **Vert succès** (`vert-succes`, #21C45D ; nuit #25DA67) : réglé, stock sain, opération réussie.
- **Orange alerte** (`orange-alerte`, #F98806 ; nuit #F9941F) : seuil bas, partiellement réglé,
  retournée, avertissement.
- **Rouge danger** (`rouge-danger`, #DC2828, identique en nuit depuis la passe 5) : rupture,
  annulée, en retard, erreur, action destructrice.
- **Violet série** (`violet-serie`, #6C31ED ; nuit #8E5FF1) : cinquième série de graphique
  uniquement.

### Encres d'état (passe 5)
Les couleurs d'état ci-dessus sont des **fonds** (pastille, teinte de badge, barre de
graphique) : comme texte, elles ne lisaient qu'à 2,0–4,3:1. Tout texte qui dit un état utilise
son **encre** (`text-success-ink`, `text-warning-ink`, `text-danger-ink`), ≥ 4,5:1 sur carte,
fond de page et teinte à 10 % :
- **Encre succès** (`encre-succes`, #1A7440 ; nuit #5CD689).
- **Encre alerte** (`encre-alerte`, #A04A08 ; nuit #FAAD42).
- **Encre danger** (`encre-danger`, #B11B1B ; nuit #F87777).
Sur un fond plein vert ou orange, le texte est en encre foncée (`*-foreground`), pas en blanc.

### Neutral
- **Papier** (`papier`, #F9FAFB) : fond de page. **Feuille** (`feuille`, #FFFFFF) : cartes,
  barre latérale, menus.
- **Encre** (`encre`, #1F2937) : texte courant et titres.
- **Gris annotation** (`gris-annotation`, #5A687C, foncé à la passe 5 : 4,8:1 sur gris
  sourdine) : libellés secondaires, compteurs, légendes, onglets inactifs, en-têtes de tableau.
- **Gris règle** (`gris-regle`, #DAE0E7) : bordures, filets de tableau, contour des champs.
- **Gris voile** (`gris-voile`, #F0F2F4) et **gris sourdine** (`gris-sourdine`, #EAEDF0) :
  survol, boutons secondaires, fonds de badges neutres.
- Nuit : fond `nuit` (#121821), cartes `nuit-feuille` (#18202A), survols `nuit-voile`
  (#212C3B), filets `nuit-regle` (#283548), texte `nuit-encre` (#E7EBEF), annotations
  `nuit-annotation` (#8996A9).

### Named Rules
**La règle du Sens unique.** Vert, orange et rouge disent un état, jamais une décoration ni une
catégorie. Une icône de carte KPI n'a pas à être rouge si rien n'est en danger. Un seuil bas est
**orange** partout (badge, bandeau du tableau de bord) ; une rupture est **rouge**. Le survol d'un
menu est gris, jamais vert (le vert encaissé n'est pas une couleur d'interface).

**La règle du Signal unique.** Un état se dit une fois par ligne : le badge suffit, la ligne du
tableau n'est pas teintée en plus. Une recommandation lue reste lisible : son statut est un
badge, pas une opacité réduite.

**La règle de l'Encre.** Une couleur d'état écrite est toujours une encre ; un jeton d'état nu
(`text-warning`) n'apparaît jamais dans le code.

**La règle du Badge discret.** Un badge de statut est teinté (fond à 10 %, filet à 25-30 %, texte
en encre d'état) ; seul un bouton est plein.

## Typography

**Display Font:** aucune (pas de titre d'affichage)
**Body Font:** Inter variable, avec son **axe optique** (`opsz`, chargé par `next/font`) : les titres
et grands chiffres prennent automatiquement le dessin « display », plus serré ; repli
`ui-sans-serif, system-ui`.
**Label/Mono Font:** Inter, chiffres tabulaires (`tnum`) pour montants, quantités et dates

**Character:** Une seule famille, neutre et très lisible aux petites tailles ; la hiérarchie tient
au poids, à la taille et au ton (encre / gris d'annotation), pas au contraste de familles.

### Hierarchy
Rôles déclarés en tokens `@theme` (`frontend/app/globals.css`) : une classe porte taille,
interligne, graisse et interlettrage.
- **Page title** (`text-page-title` : 700, 24 px, 1.33, -0,02 em) : titre `h1` de chaque page.
- **Figure** (`text-figure` : 700, 24 px, -0,01 em, `tnum`) : valeur d'une carte KPI, chiffre clé
  du panneau d'Intelligence.
- **Figure small** (`text-figure-sm` : 700, 20 px, `tnum`) : total d'une vente, d'un retour,
  prix courant d'un produit, compteurs du résumé d'Intelligence.
- **Heading** (`text-heading` : 600, 16 px, 1.5) : titre de carte, de dialogue, de panneau,
  d'état vide.
- **Body** (400, 14 px, 1.43, `text-sm`) : texte courant, cellules de tableau, boutons (500), y
  compris les petits boutons. 16 px en densité confortable (passe 4).
- **Label** (500, 12 px, `text-xs`) : **en-têtes de tableau** (gris d'annotation), badges,
  indications sous une valeur.
- **Micro** (`text-2xs` : 11 px, 600, `tnum`) : seulement le compteur de la cloche. Le reçu
  imprimé garde ses tailles propres (ticket 80 mm).

### Named Rules
**La règle du Chiffre aligné.** Tout montant ou quantité passe par l'utilitaire `numeric`
(`tabular-nums` + `nowrap`) ou le composant `Money` : `1 234 567 FCFA` ne se coupe jamais. Toute
cellule de tableau est en chiffres tabulaires par défaut (`TableCell`).

**La règle du Même chiffre, même taille.** Un rôle de chiffre n'a qu'une taille : `figure` pour
un indicateur, `figure-sm` pour un total. Pas de `text-xl font-bold` isolé.

## Layout

Coquille à deux colonnes : barre latérale fixe (≈ 208 px, feuille, filet droit) et zone de
contenu sur fond papier, en-tête de 56 px en haut. Sous le seuil `lg` (1024 px : tablette en
portrait, petit écran), la barre latérale devient un panneau (`Sheet`) ouvert par un bouton menu,
et l'en-tête affiche alors le nom de l'entreprise.

**En-tête = fil d'Ariane.** L'en-tête ne répète pas le titre de la page : il montre la section
(« Ventes ») et, sur une sous-page, la section en lien suivie du titre déclaré par `PageHeader`
(« Ventes › Nouvelle vente », `components/shell/page-title.tsx`). À droite : cloche, densité,
thème, utilisateur, déconnexion.

Chaque page suit le même registre : `PageHeader` (titre `h1` + compteur à gauche, action
principale à droite), puis une barre de recherche et de filtres, puis un tableau dans une carte.
Le tableau de bord range ses KPI en grille (2 colonnes dès `sm`, 3 dès `xl`), puis la synthèse
d'Intelligence, le graphique et les dernières ventes : à 1366 × 768, KPI et synthèse tiennent
dans le premier écran.

**Nouvelle vente.** Dès `xl` (1280 px), deux colonnes : saisie à gauche, Totaux / Règlement /
actions collés à droite. En dessous, Totaux et Règlement passent côte à côte sous les articles,
et les actions deviennent une **barre fixée en bas** (total + « Enregistrer en brouillon » +
« Confirmer la vente ») : la confirmation reste toujours à portée sur tablette.

**Colonnes d'appoint.** Une colonne de `DataTable` marquée `secondary` disparaît sous `lg`
(Stock : Catégorie, Dernier mouvement) pour que les colonnes utiles tiennent en portrait.

**Densité.** Réglage du navigateur (`lib/density.ts`, `localStorage`), **compacte** par défaut.
*Confortable* (`data-density="comfortable"` sur `<html>`, variante Tailwind `comfortable:`) passe
les tableaux à 16 px, lignes de 12 px de marge verticale, en-têtes de 48 px. Posé avant
l'affichage par un script de `<head>`, sans clignotement.

Rythme d'espacement sur la base Tailwind de 4 px : 4 / 8 / 16 / 20 / 24 px. Cartes : 16 px de
marge intérieure (KPI compris). Tableaux : en-têtes de 40 px en rôle *label* (12 px, gris
d'annotation), cellules à 8 px de marge.

## Elevation & Depth

Système plat. Les cartes sont posées à plat et cernées d'un filet de 1 px (`ring-1 ring-border`),
sans ombre. La profondeur est réservée à ce qui flotte au-dessus du registre.

### Shadow Vocabulary
- **Flottant bas** (`shadow-md`) : menus déroulants, listes de sélection.
- **Flottant haut** (`shadow-lg`) : dialogues et panneaux latéraux, sur voile sombre.
- **Champ** (`shadow-sm` / `0 1px 2px rgb(0 0 0 / .05)`) : certains déclencheurs de sélection.

### Named Rules
**La règle du Plat par défaut.** Une surface posée n'a pas d'ombre ; une ombre signifie « ceci
flotte et se ferme ».

## Shapes

Coins doucement arrondis, dérivés d'un rayon de base de 8 px (`--radius: .5rem`) : 6 px pour les
boutons et badges, 8 px pour les champs, l'élément de navigation et les pastilles d'icône, 12 px
pour les cartes. Bordures de 1 px partout, jamais plus épaisses. Aucune forme libre, aucune
découpe : le rectangle arrondi est la seule silhouette.

## Components

### Buttons
Précis et retenus.
- **Shape:** coins doux (6 px), hauteur 36 px, texte 14 px / 500, icône 16 px.
- **Primary:** fond bleu pétrole, texte blanc ; survol à 80 % d'opacité.
- **Hover / Focus:** anneau de focus de 3 px en bleu pétrole à 50 %, bordure `ring`.
- **Outline / Secondary / Ghost:** filet gris règle sur papier ; voile gris ; transparent qui se
  voile au survol.
- **Destructive:** teinté (rouge à 10 %, texte rouge), plein seulement dans la confirmation.

### Chips (badges de statut)
- **Style:** hauteur 20 px, coins 6 px, texte 12 px / 500, fond teinté + filet fin de la couleur
  d'état (`neutral`, `info`, `success`, `warning`, `danger`), jamais plein.
- **State:** Brouillon (neutre), Confirmée (info), Annulée (danger), Retournée (alerte) ; Actif,
  Seuil bas, Rupture ; À régler, Partiellement réglé, Réglé.

### Cards / Containers
- **Corner Style:** 12 px.
- **Background:** feuille (nuit-feuille en sombre).
- **Shadow Strategy:** aucune (voir Elevation & Depth).
- **Border:** filet de 1 px gris règle.
- **Internal Padding:** 16 px (12 px en taille `sm`, 20 px pour les KPI).

### Inputs / Fields
- **Style:** hauteur 32 px, coins 8 px, filet gris règle, fond transparent, texte 16 px sur
  mobile et 14 px dès `md`.
- **Focus:** anneau de 3 px en bleu pétrole à 50 %.
- **Error / Disabled:** filet et anneau rouges (`aria-invalid`) + message `FieldError` sous le
  champ ; désactivé à 50 % d'opacité.

### Navigation
- **Style:** liste verticale, éléments de 36 px, icône 16 px + libellé 14 px / 500, coins 8 px.
- **Default / hover / active:** gris annotation ; voile gris et encre au survol ; plein bleu
  pétrole et texte blanc quand actif (`aria-current="page"`).
- **Tablette et mobile (< 1024 px):** même contenu dans un `Sheet` à gauche.

### Carte KPI (signature)
Libellé en gris annotation précédé d'une icône de 16 px (grise ; orange ou rouge seulement pour
un état d'alerte ou de danger), valeur en Figure, indication en Label ; 16 px de marge, environ
110 px de haut. Pas de pastille d'icône : elle prenait 50 px sans rien dire. La valeur arrive
formatée par l'API.

### Carte de recommandation (signature)
Carte d'Intelligence cliquable : badges type + confiance, titre, lignes **Métrique / Valeur /
Date de calcul** ; le détail (modèle et version, incertitude) s'ouvre dans un panneau latéral.

### Graphiques
Une barre par période (`PeriodBarChart`) pour un total journalier, hebdomadaire ou mensuel :
chaque valeur est distincte, une courbe lissée en inventait entre deux points. Série principale
`chart-1` (bleu pétrole), grille horizontale en pointillés gris règle, axes en gris annotation,
info-bulle sur feuille. Les flux de trésorerie gardent vert encaissé (entrées) et rouge (sorties).

## Do's and Don'ts

### Do:
- **Do** passer chaque montant par `Money` ou `numeric` : chiffres tabulaires, `1 234 567 FCFA`
  sans décimales, alignés à droite.
- **Do** modifier l'apparence par les tokens de `globals.css` et les composants partagés
  (`components/ui`, `components/*`), jamais page par page.
- **Do** réserver les ombres aux éléments flottants (menus, dialogues, panneaux).
- **Do** nommer la métrique, la date de calcul, le modèle et sa version, l'incertitude sur toute
  recommandation.

### Don't:
- **Don't** remplir un badge de statut comme un bouton (défaut du prototype).
- **Don't** couper un montant sur deux lignes (« 1 000 » puis « FCFA »).
- **Don't** employer vert, orange ou rouge hors de leur sens d'état.
- **Don't** afficher de sélecteur d'entreprise ni de bandeau « Mode démonstration ».
