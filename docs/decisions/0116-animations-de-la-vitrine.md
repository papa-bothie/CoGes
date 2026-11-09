# 0116 — Animations de la vitrine : CSS seulement, finies, sans décalage

- **Date** : 2026-11-09
- **Phase** : prompt 38 (lot « Animations de la vitrine », complète l'ADR 0115)
- **Statut** : acceptée
- **Décideur** : utilisateur (prompt 38, puis deux AskUserQuestion du 2026-11-09 : hauteur
  du titre, taille à 768 px, entrée du hero ; puis le fondu restant du hero)

## Contexte

La vitrine (ADR 0115) était immobile, à part un fondu de 500 ms sur le bloc du hero. Le
prompt 38 demande des animations dans l'esprit d'izisaas.academy :

- un titre dont un mot change ;
- des apparitions au défilement ;
- un halo derrière l'illustration et un éclat sur le bouton WhatsApp ;
- des survols de cartes, un en-tête qui s'affirme au défilement, une FAQ fluide.

Ces animations doivent tenir sans bibliothèque, sans animation infinie, sans décalage de mise
en page, en mouvement réduit et sans JavaScript, dans un budget de 5 Ko gzip.

## Options envisagées

1. **CSS seulement, plus un petit observateur du défilement (retenue).** Les animations
   tournent sur le compositeur (`opacity`, `transform`, `translate`). Elles ne coûtent
   aucune hydratation, à part `<Revele />`, et la CSP ne change pas.
2. Une bibliothèque (Framer Motion, GSAP, AOS). Écartée par le prompt : poids de plusieurs
   dizaines de Ko, hydratation du hero, et le premier écran attendrait le script.
3. Un titre piloté par JavaScript (minuterie). Écarté : il faut hydrater le hero, le mot ne
   tourne pas sans script, et le temps se teste moins bien que des `@keyframes`.

## Décision

### Fichiers

- `components/vitrine/vitrine.module.css` : tout le mouvement. C'est un module CSS, chargé
  par `/` seulement, qui ne touche jamais l'application.
- `hero-title.tsx` : composant serveur du titre.
- `revele.tsx` : le seul composant client.
- `motion.ts` : la fonction `revele()`.

### A1. Le titre qui change de mot

- **Accessibilité et référencement.** Le `<h1 id="titre">` contient `hero.title` en texte
  réel (`sr-only`), et la version animée est `aria-hidden`. Un lecteur d'écran, un moteur
  de recherche, un visiteur sans JavaScript et le mouvement réduit reçoivent donc toujours
  la phrase complète. Les textes sont dans `hero.rotation` (`mots`, `complet`, `suite`). Un
  test vérifie que `mots` et `suite`, puis `complet` et `suite`, redonnent exactement
  `hero.title`.
- **Séquence.** Un tour dure 9 s, soit 3 s par mot : entrée de 0,4 s, pause, puis sortie de
  0,4 s vers le haut pendant que le mot suivant monte.
  - Le délai de −0,4 s montre « Les ventes » déjà en place à t = 0.
  - Chaque mot a ses propres `@keyframes` et la même horloge.
  - Trois tours, puis « Les ventes, le stock et l'argent » entre à 26,6 s pendant que
    « L'argent » sort (0,0444 tour de plus pour ce seul mot). **Tout s'arrête à 27 s.**
  - Aucun remplissage `forwards` : l'état de repos du CSS **est** l'état final (mots à
    opacité 0, phrase complète visible). Le mouvement réduit et la fin de séquence montrent
    donc la même chose, sans règle à part, et `getAnimations()` ne garde rien.
- **Hauteur.** Choix de l'utilisateur : la case est réservée.
  - Les trois mots et la phrase de fin sont superposés dans une même case de grille, qui
    prend d'office la hauteur de la phrase de fin, à toute largeur, sans valeur écrite à
    la main.
  - Le mot se pose en bas (`align-items: end`), juste au-dessus de la suite. La ligne
    réservée reste au-dessus du titre : un espace en haut, jamais un trou dans le texte.
  - `text-wrap: balance` évite un « l'argent » seul en bout de ligne.
  - La suite ne bouge jamais. L'autre option (remplacer tout le titre par `hero.title` à la
    fin) la faisait bouger une fois et laissait quand même une ligne vide.
- **768 px.** Le titre passe à 44 px entre 768 et 1023 px (choix de l'utilisateur). À
  52 px, il faisait 6 lignes dans la colonne étroite, avec une case de 3 lignes. À 44 px,
  il fait 4 lignes et la case 2. Rien ne change à 360 px (34 px) ni à partir de 1024 px
  (52 px).
- **Entrée du hero.** Le hero n'a plus de fondu (choix de l'utilisateur, en deux temps) :
  - d'abord, le titre est sorti du fondu de 500 ms ;
  - le paragraphe est alors devenu l'élément LCP, encore retardé par son fondu (environ
    880 ms à 360 px) ;
  - le fondu a donc été retiré de tout le bloc.
  La séquence démarre à t = 0 et rien ne l'attend.
- **Pause.** `animation-play-state: paused` au survol de la zone et au focus dans le bloc
  du hero (`:focus-within`, ses deux boutons). Les quatre animations s'arrêtent ensemble
  et restent synchrones.
- **Couleur.** Le mot relayé est en `text-primary` en clair (5,1:1 sur le papier) et en
  `text-marque` en sombre. Le contraste est vérifié en e2e (AA ≥ 4,5:1 dans les deux
  thèmes).

### A2. Apparitions au défilement

- `<Revele />` observe chaque `[data-revele]` et pose `data-vu` une seule fois (puis
  `unobserve`). L'élément monte de 24 px en fondu en 0,6 s, avec 80 ms de décalage par carte
  voisine (`--i`). Les captures ordinateur et téléphone glissent chacune de son côté
  (`gauche`, `droite`).
- **Masquage sous `@media (scripting: enabled) and (prefers-reduced-motion:
  no-preference)`** : sans script, ou en mouvement réduit, rien n'est jamais masqué. Un
  navigateur sans IntersectionObserver révèle tout d'un coup.
  - Risque accepté : si le JavaScript se charge mais n'hydrate pas, les sections sous le
    pli restent invisibles. Ce cas est le même que pour tout le reste de l'application.
- **Jamais sur le hero ni sur le premier écran.** La section « Les questions de tous les
  jours » est visible dès le premier affichage à partir de 768 px : elle n'a pas
  d'apparition. Un e2e vérifie à 360, 768, 1280 et 1440 px qu'aucun élément marqué n'est
  dans le premier écran.
- Le relevé se fait par `animation` (propriété `translate`), et non par `transition` : le
  survol des cartes (`transform`) ne la contrarie pas, et rien ne reste dans
  `getAnimations()` une fois l'apparition finie.

### A3 à A7

- **A3. Halo.** Un dégradé radial en `color-mix` du vert d'éclat, derrière l'illustration
  (`::before`, `z-index: -1`, `aria-hidden` par construction). Il dérive une fois en 20 s,
  puis reste fixe. Le hero coupe en `overflow-x: clip` (aucun défilement horizontal à
  360 px). Le halo n'est jamais derrière du texte.
- **A4. Éclat.** Une bande claire traverse le bouton « Écrire sur WhatsApp » du hero :
  3 passages, toutes les 4 s, à partir de 1,2 s, puis plus rien (fin à 13,2 s). Elle est
  sous le texte (`isolation`, `z-index: -1`) et `pointer-events: none`.
- **A5. Cartes.** Soulèvement de 4 px et ombre en 200 ms, avec une icône qui bouge, au
  survol et au `:focus-visible`. Le tout est sous `@media (hover: hover)` : rien ne reste
  « collé » au toucher.
- **A6. En-tête.** Un voile `::before` (fond plein et ombre) passe d'une opacité 0 à 1 sur
  les 96 premiers pixels de défilement (`animation-timeline: scroll(root)`), sous
  `@supports`. Ailleurs, rien ne change, sans JavaScript de secours.
- **A7. FAQ.** `::details-content` et `interpolate-size: allow-keywords`, sous
  `@supports selector(::details-content)`. Ailleurs, le comportement d'avant ne change pas.
  C'est **la seule animation de taille** (hauteur des réponses), et elle ne se déclenche
  qu'au clic (exclue du CLS). Le « + » qui tourne reste.
- **A9. Mini-caisse.** Non faite dans ce lot : le prompt la laisse au choix du propriétaire
  après avoir vu le reste.

### Aucune animation infinie (WCAG 2.2.2)

La règle 2.2.2 (« Pause, arrêt, masquage ») interdit un mouvement automatique de plus de
5 s qui ne s'arrête pas et ne peut pas être mis en pause. Sur la vitrine :

- chaque animation à horloge a une fin : titre à 27 s, halo à 20 s, éclat à 13,2 s,
  apparitions en moins d'une seconde ;
- le titre se met aussi en pause au survol et au focus ;
- le mouvement réduit coupe tout.

`components/vitrine/animations.test.ts` refuse `infinite` et les utilitaires qui bouclent
(`animate-spin`, `-ping`, `-pulse`, `-bounce`) dans le CSS et les composants de la vitrine.
Il refuse aussi toute déclaration `animation` ou `transition` hors d'un bloc
`prefers-reduced-motion: no-preference`.

### Budget et performances

Mesures sur le build de production de `/`, en gzip niveau 9 :

| | `main` (après la PR n° 77) | Ce lot | Écart |
|---|---|---|---|
| CSS | 19 313 o | 20 521 o | +1 208 o |
| JS | 297 928 o | 298 158 o | +230 o |
| **CSS + JS** | | | **+1 438 o** (plafond : 5 120 o) |

**LCP**, en médiane de 5 chargements, les deux builds mesurés en alternance sur le même
poste (chargé, donc bruité) :

- à 360 px : de 812 à 996 ms avant, à 744 à 760 ms après. L'élément LCP était le `h1`, il
  est maintenant le paragraphe, sans fondu ;
- à 1280 px : l'illustration, inchangée (548 à 668 ms des deux côtés, selon le bruit).

Lighthouse accessibilité : 100 sur ordinateur et sur téléphone.

## Conséquences

Tests ajoutés :

- `content/vitrine-texte.test.ts` : cohérence de `hero.rotation` avec `hero.title`.
- `components/vitrine/animations.test.ts` : aucune animation infinie, tout mouvement sous
  `no-preference`.
- `e2e/vitrine-animations.spec.ts` (18 parcours) :
  - séquence aux instants 0, 3,2, 6,2, 9,2, 24,2 et 28 s, et relais à 2,8 s ;
  - fin à 27 s, puis plus aucune animation dans la zone ;
  - nom accessible du `h1` ;
  - pause au survol et au focus ;
  - contraste AA du mot relayé ;
  - CLS 0 et boîte du titre identique à chaque instant, à 360, 768 et 1280 px, en clair
    et en sombre ;
  - aucune apparition au premier écran ;
  - mouvement réduit (aucune animation, tout visible) ;
  - sans JavaScript (tout visible).

Les animations CSS ne suivent pas `page.clock` de Playwright. Les tests les arrêtent et
règlent leur `currentTime` (Web Animations) : aucune attente réelle.

`e2e/vitrine.spec.ts` a été retouché :

- les animations sont menées à leur fin avant axe ;
- `waitForLoadState("networkidle")` est remplacé par l'attente des images affichées. Avec
  les animations en cours, l'état « réseau calme » de Playwright ne venait parfois jamais
  (2 fois sur 12), alors qu'aucune requête de la page n'était en attente ; sur `main`,
  10 fois sur 10 sans souci.

`proxy.ts`, `proxy.test.ts`, `coges_known`, la mise en page racine et l'application ne
changent pas.

### Suites

**Changement de police.** `next/font` ajuste la police de secours sur Arial, absent de
Linux et d'Android. Quand Figtree arrive après le premier affichage, le texte se décale :

- l'en-tête de la vitrine, observé 1 fois sur 20 en production, et déjà le cas sur
  `main` ;
- le hero, en développement, depuis qu'il n'a plus de fondu pour le masquer.

Le test de CLS compte donc les décalages à partir de `document.fonts.ready`. Corriger la
police de secours touche la mise en page racine, donc l'application : c'est à décider
dans un lot à part.
