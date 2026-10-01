# Audit Impeccable — avant finition (phase 14, passe 2)

> Relevé le 30/09/2026 sur `phase/14-polish-impeccable` (`f188372`), jeu de démonstration, avant
> toute modification visuelle. Sources : détecteur Impeccable (`impeccable detect` sur
> `frontend/app` et `frontend/components`), axe WCAG 2.1 AA sur 16 écrans + connexion en clair et
> en sombre (`captures/phase-14/avant/a11y-*.json`), captures `captures/phase-14/avant/`, relevés
> ponctuels à 1366 × 768, 1024 × 768 et 768 × 1024, lecture du code (tokens, composants partagés).
> Cet audit ne corrige rien : chaque point renvoie à la passe qui le traitera.

## Note de santé

| # | Dimension | Note | Constat principal |
|---|---|---|---|
| 1 | Accessibilité | 2/4 | Contraste AA manqué sur **tous** les écrans en clair (≈ 230 éléments), 1 attribut ARIA invalide |
| 2 | Performance | 3/4 | `backdrop-blur` sous chaque panneau et dialogue ; `transition-all` sur boutons, badges, onglets |
| 3 | Adaptation (tablette, petit portable) | 2/4 | À 1024 px, « Confirmer la vente » passe sous la ligne de flottaison ; à 1366 × 768 les indicateurs remplissent tout l'écran |
| 4 | Thème (tokens, sombre) | 3/4 | Aucune couleur en dur ; mais un seul token par état sert à la fois de fond et de texte, et le sombre n'a pas ses `*-foreground` |
| 5 | Intégrité de la mise en œuvre | 3/4 | Système cohérent ; un motif « IA » (bordure latérale 4 px), tuiles d'icônes génériques, répétitions |
| **Total** | | **13/20** | **Acceptable** — base saine, travail net à faire sur la couleur et la mise en page |

## Verdict d'intégrité : **réussi**

Le front exprime un système propre au produit : tokens centralisés dans `app/globals.css`, aucune
couleur en dur (vérifié : ni hexadécimal, ni `rgb()`, ni palette Tailwind brute dans `app/`,
`components/`, `lib/`), composant `Money` et utilitaire `numeric` pour les montants, badges de
statut déjà en variante discrète, règles d'affichage métier respectées (métrique nommée, date de
calcul, modèle, incertitude, « données insuffisantes »). Le détecteur ne remonte qu'un motif
(`side-tab`, `insight-card.tsx:39`). Les défauts sont des **valeurs de tokens** et quelques
**gabarits de mise en page**, pas une dérive.

## Résumé

- 19 constats : **P0 0 · P1 7 · P2 7 · P3 5**.
- Les cinq plus importants :
  1. Les couleurs d'état (vert, orange, rouge) servent aussi de **couleur de texte** : 2,0 à 2,5:1
     pour le vert et l'orange (AA exige 4,5:1).
  2. Le **gris d'annotation** (`--muted-foreground`) est juste sous le seuil sur les fonds teintés
     (4,26 à 4,49:1) : c'est la moitié des violations.
  3. **Nouvelle vente à 1024 px** : totaux, règlement et bouton de confirmation sous la ligne de
     flottaison.
  4. **Tableau de bord à 1366 × 768** : six cartes d'indicateurs de 170 px occupent tout l'écran ;
     le graphique et les dernières ventes n'apparaissent qu'au défilement.
  5. **Cartes d'Intelligence** : bordure latérale épaisse, « Données insuffisantes » répété jusqu'à
     4 fois dans la même carte, opacité 75 % qui fait tomber le contraste.

## Constats détaillés

### P1 — majeurs (AA manqué ou tâche gênée)

**[P1-1] Couleurs d'état utilisées comme texte**
- Où : `components/ui/badge.tsx` (variantes `success`, `warning`, `danger`) ; montants
  « Reste dû » `text-warning` (`sales/sales-list-view.tsx`) ; écarts `text-success` /
  `text-destructive` (`products/[id]/product-detail-view.tsx`, `inventory/movement-journal.tsx`) ;
  bandeau d'alerte (`components/alerts/alert-banner.tsx`) ; bouton `destructive` (`ui/button.tsx`).
- Mesures axe (clair) : vert #21C45D sur fond pâle **2,03–2,30:1** (28 éléments), orange #F98806
  **2,15–2,45:1** (31), rouge #DC2828 **3,94–4,27:1** (6). Sombre : rouge **3,40–3,93:1** (7).
- Impact : les statuts « Disponible », « Seuil bas », « Retournée » et les montants dus sont
  difficiles à lire sur un écran lumineux de boutique, précisément ce qu'on veut voir.
- WCAG 1.4.3 (contraste minimum).
- Recommandation : séparer chaque état en deux tokens, `--success` (fond, pastille, graphique) et
  `--success-text` (texte, assez foncé pour 4,5:1 sur carte **et** sur fond teinté), en clair et en
  sombre ; les badges et les montants lisent le token texte.
- Passe : **colorize**.

**[P1-2] Gris d'annotation sous le seuil sur les fonds teintés**
- Où : token `--muted-foreground: 215 16% 47%` (#65758B), sur `--background`, `--muted`, lignes
  survolées ou teintées, notifications non lues, badge `neutral`.
- Mesures : 4,26 à 4,49:1 (≈ 140 éléments, clair uniquement). Le sombre passe.
- Impact : SKU, dates, sous-titres, libellés de définition : tout le texte secondaire.
- Recommandation : foncer le token d'environ 5 points de luminosité (cible ≥ 4,6:1 sur `--muted`).
  Un seul token, effet partout.
- Passe : **colorize**.

**[P1-3] Cartes d'Intelligence lues à 75 % d'opacité**
- Où : `app/(app)/insights/insight-card.tsx:41` (`opacity-75` quand le statut n'est pas « new »).
- Impact : l'opacité s'applique au texte, ce qui fait passer libellés et badges sous AA. Une
  recommandation « prise en compte » reste une information à lire.
- Recommandation : signaler l'état lu par le badge de statut ou le poids du titre, pas par
  l'opacité.
- Passe : **colorize** (ou **distill**, avec les cartes).

**[P1-4] Onglets inactifs et sélecteur de règlement sous le seuil**
- Où : `components/ui/tabs.tsx` (Stock, Intelligence, Finance, Paramètres, Notifications) ;
  sélecteur « Total / Partiel / À crédit » de la nouvelle vente.
- Mesures : 3,80 à 3,99:1 (12 éléments).
- Recommandation : corrigé par P1-2 si les onglets inactifs lisent `--muted-foreground` sur
  `--muted` ; à vérifier après.
- Passe : **colorize**.

**[P1-5] Attribut ARIA invalide sur le filtre des notifications** (axe : *critique*)
- Où : `app/(app)/notifications/notifications-view.tsx:36-42`. Des `Tabs` servent de filtre
  sans `TabsContent` ; `aria-controls` pointe vers un panneau qui n'existe pas.
- Impact : un lecteur d'écran annonce un onglet qui ne contrôle rien.
- WCAG 4.1.2 (nom, rôle, valeur).
- Recommandation : un groupe de boutons bascule (`role="radiogroup"` ou `aria-pressed`) plutôt
  que des onglets, ou un vrai `TabsContent` englobant la liste. Même vérification sur les autres
  `Tabs` utilisés comme filtres.
- Passe : **polish** (correctif ciblé ; aucun changement de comportement).

**[P1-6] Pastille de la cloche en sombre**
- Où : `components/shell/notification-bell.tsx:62` : blanc sur `--destructive` sombre
  **4,37:1**, en `text-[10px]`. Le thème sombre ne redéfinit pas `--destructive-foreground`.
- Recommandation : donner leurs `*-foreground` au sombre (`destructive`, `warning`, `success`) ;
  pastille à 11 px au moins, sur l'échelle typographique.
- Passe : **colorize** (+ **typeset** pour la taille).

**[P1-7] Nouvelle vente sur tablette : la confirmation sort de l'écran**
- Où : `app/(app)/sales/sale-editor.tsx`. Sous `lg`, la colonne « Totaux / Règlement /
  Confirmer » passe **sous** Client et Articles. À 1024 × 768, le bouton « Confirmer la vente »
  n'est pas visible, même panier vide ; avec des lignes, il s'éloigne encore.
- Impact : principe produit n° 3 (« rapide au comptoir ») ; la tablette est un usage déclaré.
- Recommandation : garder deux colonnes dès 1024 px (colonne de droite plus étroite, collante),
  ou une barre de total et de confirmation collée en bas sous `lg`.
- Passe : **layout** (+ **adapt**).

### P2 — mineurs (gêne réelle, contournement possible)

**[P2-1] Indicateurs du tableau de bord trop hauts** — `components/kpi-card.tsx`,
`dashboard/dashboard-view.tsx`. Tuile d'icône + libellé + valeur, environ 170 px par carte, en 3 × 2 :
à 1366 × 768, ces cartes et le bandeau d'alerte remplissent l'écran ; le chiffre d'affaires sur
30 jours et les dernières ventes viennent au défilement. Les tuiles d'icône colorées au-dessus de
chaque chiffre sont un gabarit générique qui n'apporte aucune information. Même motif sur le
haut de l'écran Intelligence. → **layout**, **distill**.

**[P2-2] Cartes d'Intelligence chargées** (défaut connu, `prototype-reference.md` § 5) —
`insight-card.tsx`. Bordure latérale de 4 px (seul motif du détecteur) ; deux badges puis un titre
qui répète le type (« Données insuffisantes · Information » puis « Données insuffisantes — Sucre ») ;
la ligne « Métrique » tronque « Données insuffisa… » ; la ligne « Confiance » répète encore
« Données insuffisantes ». Les informations obligatoires (métrique, date, modèle, incertitude)
restent. → **distill** (+ **colorize** pour la sévérité sans bordure).

**[P2-3] Panneau d'Intelligence : débordement et actions sans hiérarchie** — `insight-sheet.tsx`.
La valeur « Règle de gestion (sans modèle statistique) » est **coupée** au bord droit ; les
libellés de définition passent sur deux lignes (« Jours de vente sur / 60 jours ») faute de
largeur ; quatre actions de même poids (« Marquer comme lu », « Prendre en compte », « Écarter »,
« Marquer résolu ») sans action principale. → **layout**, **clarify**.

**[P2-4] Sens des couleurs d'état incohérent** — le bandeau « Stock bas » du tableau de bord est
en **rouge danger**, alors qu'un seuil bas est une **alerte** (orange) partout ailleurs ; dans
Stock, les lignes au seuil sont à la fois teintées en orange **et** marquées d'un badge orange
(double signal qui alourdit le tableau). → **colorize**.

**[P2-5] Tablette en portrait (768 px)** — la barre latérale de 208 px reste affichée ; le tableau
du stock défile à l'intérieur de sa carte et masque CMP, Valeur et Statut, les colonnes utiles. →
**adapt**.

**[P2-6] Mouvement sans `prefers-reduced-motion`** — aucune occurrence de `motion-reduce` ni de
`prefers-reduced-motion` dans le front, alors que `PRODUCT.md` s'y engage ; panneaux et dialogues
glissent (`tw-animate-css`). WCAG 2.3.3 (AAA), engagement produit. → **animate**.

**[P2-7] Titre répété dans l'en-tête** — l'en-tête reprend le titre de la page (« Tableau de bord »
deux fois, 80 px d'écart) et se trompe parfois de niveau (« Ventes » au-dessus de « Nouvelle
vente »). Hauteur perdue sur un écran de 768 px. → **layout** (en-tête = fil d'Ariane ou
entreprise seule).

### P3 — finitions

**[P3-1]** `backdrop-blur-xs` sous chaque dialogue et panneau (`ui/dialog.tsx:34`,
`ui/sheet.tsx:34`) : coût de rendu sur PC d'entrée de gamme, effet décoratif. → **animate**.

**[P3-2]** `transition-all` sur `ui/button.tsx`, `ui/badge.tsx`, `ui/tabs.tsx` : animer
seulement couleur, ombre et opacité. → **animate**.

**[P3-3]** Tailles hors échelle `text-[10px]` (cloche) ; `text-[11px]` et `text-[12px]` du reçu
sont légitimes (impression 80 mm) et restent. → **typeset**.

**[P3-4]** Titres de page en 24 px gras avec `tracking-tight`, sous-titres en 14 px gris :
écart juste, échelle non déclarée en tokens. → **typeset**.

**[P3-5]** Graphique du chiffre d'affaires en courbe lissée (`type="monotone"`) sur des valeurs
journalières : lecture « continue » de ventes discrètes, pics étroits. Des barres ou une ligne
droite diraient mieux « un chiffre par jour ». → **colorize** (graphiques).

## Motifs systémiques

- **Un token par état sert à tout** (fond de pastille, texte, graphique, bouton) : c'est l'origine
  de P1-1, P1-6 et d'une partie de P2-4. Une seule correction de tokens en règle la majorité.
- **Un seul gris secondaire**, calibré sur le blanc et pas sur les fonds teintés : origine de P1-2
  et P1-4 (≈ 150 éléments).
- **Gabarit « tuile d'icône + libellé + chiffre »** répété (tableau de bord, Intelligence) :
  hauteur perdue et apparence générique.
- **Mises en page pensées pour 1440 px** : les ruptures à `lg` repoussent l'essentiel sous la
  ligne de flottaison sur les écrans cibles (1366 × 768, tablette).

## Ce qui fonctionne (à garder)

- Tokens complets, clair et sombre, **aucune couleur en dur**.
- Montants : `Money` + `numeric` (chiffres tabulaires, sans coupure), alignés à droite, FCFA sans
  décimales, espace fine insécable.
- Badges de statut déjà discrets (fond teinté, bordure fine), plus des boutons pleins.
- Lien d'évitement « Aller au contenu », `lang="fr"`, champs étiquetés, focus visible
  (`ring-3`), dialogues Radix accessibles au clavier.
- Aucun débordement horizontal de page à 768, 1024 et 1366 px.
- Sombre quasi conforme : connexion sans violation, 1 à 3 éléments par écran.
- Règles d'affichage de l'Intelligence respectées sur chaque carte et dans le panneau.

## Faux positifs écartés

- Le rond « N » en bas à gauche des captures est l'indicateur de développement de Next.js :
  absent en production.
- La barre latérale qui s'arrête à 900 px sur les captures pleine page vient de `sticky h-dvh` dans
  une capture plus haute que la fenêtre ; à l'écran, elle reste collée en haut.

## Actions recommandées, dans l'ordre des passes

1. **[P1] `/impeccable colorize`** : tokens texte des états (clair + sombre), `muted-foreground`
   plus foncé, `*-foreground` en sombre, opacité des cartes lues, bandeau « Stock bas » en alerte,
   double signal du stock, graphique (P1-1 à P1-4, P1-6, P2-4, P3-5).
2. **[P1] `/impeccable layout`** : nouvelle vente à 1024 px, hauteur des indicateurs, en-tête,
   panneau d'Intelligence (P1-7, P2-1, P2-3, P2-7).
3. **[P2] `/impeccable adapt`** : tablette en portrait, barre latérale repliable, colonnes
   prioritaires (P2-5).
4. **[P2] `/impeccable distill`** : cartes d'Intelligence, tuiles d'icônes (P2-1, P2-2).
5. **[P2] `/impeccable clarify`** : actions du panneau, libellés de définition (P2-3).
6. **[P3] `/impeccable typeset`** : échelle déclarée, tailles hors échelle (P3-3, P3-4).
7. **[P2] `/impeccable animate`** : `prefers-reduced-motion`, flou, `transition-all` (P2-6,
   P3-1, P3-2).
8. **`/impeccable polish`** : filtre des notifications (P1-5), puis nouvel audit à comparer à
   celui-ci.

> L'ordre du prompt de phase (typeset → layout → colorize → …) reste valable ; seul l'ordre de
> priorité ci-dessus diffère, car la couleur concentre la plupart des violations AA.

## Arbitrage (30/09/2026)

Tous les constats sont retenus : P1 (contrastes par les tokens, nouvelle vente à 1024 px, filtre
des notifications), P2 (tableau de bord et en-tête, Intelligence, couleur et tablette en
portrait, mouvement) et P3 (typographie, flou, `transition-all`, graphique).
Les passes suivent **l'ordre du prompt** : typeset → layout (+ adapt) → colorize → clarify /
distill → animate → polish, puis nouvel audit.
