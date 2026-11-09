# Prompt 38 — Animations de la vitrine (titre qui change de mot, apparitions au défilement)

> **STATUT : PRÊT À LANCER** (9 novembre 2026), après la fusion de la PR n° 77 (page d'accueil publique, prompt 37, ADR 0115). Si cette PR n'est pas fusionnée, l'agent s'arrête.

Branche `feat/landing-animations`, depuis `main` à jour.

## Décisions déjà prises

- Inspiration : izisaas.academy (animations 100 % CSS : balayage de lumière, apparitions au défilement, menu des questions fluide). On garde l'esprit, **sans bibliothèque**.
- **Titre qui change de mot** : seuls « Les ventes », « Le stock », « L'argent » se relaient ; « de votre boutique, au même endroit. » ne bouge jamais.
- **Trois tours (environ 27 secondes)**, puis le titre s'arrête sur la phrase **complète** : « Les ventes, le stock et l'argent de votre boutique, au même endroit. » (règle WCAG 2.2.2 : pas de mouvement automatique sans fin).
- **Aucune animation infinie** sur la page.
- Rien ne change pour les personnes qui se connectent déjà (`proxy.ts` et ses tests ne sont pas touchés).

## Avant de lancer (propriétaire)

Rien à fournir. À décider après avoir vu le résultat : la mini-caisse animée (A9) reste optionnelle.

## Prompt à donner à l'agent

```
Lot « Animations de la vitrine » (branche feat/landing-animations, depuis main à jour).
Règles habituelles : ADR au prochain numéro libre, tests d'abord (rouge puis vert), aucun
service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod, backend/.vercel/
ni /etc/coges/*. Résumé en français à la fin, questions ouvertes par AskUserQuestion.

Avant tout code : lis frontend/AGENTS.md et le guide concerné dans
node_modules/next/dist/docs/, l'ADR 0115 (vitrine), frontend/app/(vitrine)/page.tsx,
frontend/content/vitrine-texte.ts et frontend/app/globals.css (jetons, classes
d'animation déjà présentes : tw-animate-css, `motion-safe:animate-in`). Si la PR n° 77 n'est
pas fusionnée, ARRÊTE-TOI et dis-le moi.

Contraintes non négociables
- CSS seulement, plus UN petit composant client d'observation du défilement (A2).
  AUCUNE bibliothèque (pas de Framer Motion, GSAP, AOS). La CSP de next.config.ts ne
  s'assouplit pas ; aucune requête externe.
- On n'anime que opacity et transform (jamais width, height, top, margin) : aucun décalage de
  mise en page (CLS = 0).
- Tout est désactivé sous prefers-reduced-motion: reduce : la vitrine s'affiche alors
  complète et immobile, titre complet compris.
- AUCUNE animation infinie : toute boucle est finie (au plus trois tours, environ 30 s).
- Sans JavaScript, tout le contenu reste visible et lisible.
- Budget : au plus 5 Ko gzip de plus au total (CSS + JS), mesuré avant/après et donné dans
  le résumé. Le premier écran ne doit pas être ralenti : le titre est visible dès le
  premier affichage, rien ne l'attend.
- Aucun changement du comportement pour ceux qui se connectent déjà : proxy.ts, proxy.test.ts,
  le cookie coges_known et l'application ne sont pas modifiés.

A1. Titre du hero : un mot qui change, le reste immobile
- Rendu voulu : « [Les ventes | Le stock | L'argent] de votre boutique, au même endroit. »
  Le mot relayé est sur sa propre ligne (zone d'animation), « de votre boutique, au même
  endroit. » est fixe en dessous. Chaque mot sort vers le haut en fondu pendant que le
  suivant monte du bas. Environ 3 s par mot (entrée 0,4 s, pause, sortie 0,4 s), trois tours
  (environ 27 s), puis la zone affiche la phrase complète des trois éléments et s'arrête.
- Source unique des textes : frontend/content/vitrine-texte.ts. Garde hero.title (phrase
  complète, déjà utilisée ailleurs) et ajoute hero.rotation = { mots: ["Les ventes",
  "Le stock", "L'argent"], suite: "de votre boutique, au même endroit." }. Un test unitaire
  vérifie que « mots[0], mots[1] en minuscule initiale et mots[2] en minuscule initiale,
  puis suite » redonne exactement hero.title (personne ne change l'un sans l'autre).
- Accessibilité et référencement : le <h1> contient la phrase complète en texte réel
  (sr-only) et la version animée est aria-hidden. Un lecteur d'écran, Google, un visiteur
  sans JavaScript et reduced-motion reçoivent la phrase complète, jamais un mot seul.
  Le h1 garde id="titre" (aria-labelledby de la section).
- Pur CSS, composant serveur, aucune hydratation : les mots sont superposés dans la même
  case de grille ; keyframes avec des décalages (animation-delay, éventuellement négatifs)
  pour que le premier mot soit visible à t = 0 ; animation-iteration-count: 3 puis la phrase
  complète apparaît (fondu) et reste. Le bloc du hero porte déjà une entrée
  (animate-in, 500 ms) : décide si la séquence démarre après et justifie-le dans l'ADR.
- Pause au survol et au focus clavier (animation-play-state: paused sur :hover et
  :focus-within de la zone).
- Hauteur : la zone ne doit JAMAIS provoquer de décalage (CLS 0) à 360, 768 et 1280 px.
  Les trois mots courts et la phrase complète n'ont pas la même longueur : propose et
  justifie (AskUserQuestion avec captures) une solution sans trou visible de plus d'une
  ligne, par exemple réserver la hauteur par point de rupture, ou terminer sur la phrase
  complète placée dans le même emplacement que le texte fixe. Aucun saut de ligne
  horizontal d'un mot à l'autre à 360 px.
- Couleur : le mot relayé suit les jetons du projet (accent de marque), contraste AA en
  clair et en sombre.

A2. Apparition au défilement (sections sous le premier écran)
- Petit composant client (un IntersectionObserver, une seule fois par élément, unobserve
  après) qui pose data-vu sur les éléments marqués data-revele. Un décalage de 80 ms entre
  cartes voisines (propriété CSS --i).
- Le masquage initial ne s'applique que si @media (scripting: enabled) et
  (prefers-reduced-motion: no-preference) : sans JavaScript ou en mouvement réduit,
  tout est visible d'emblée.
- JAMAIS sur le hero ni sur ce qui est visible au premier affichage (LCP).
- Variantes : montée (par défaut), glissement latéral pour les captures ordinateur et
  téléphone (chacune de son côté).

A3. Hero : halo
- Un halo vert CoGes très doux derrière l'illustration, qui dérive lentement UNE fois
  (environ 20 s), puis reste fixe. Décoratif : aria-hidden, sans effet sur le contraste du
  texte (vérifié en clair et en sombre).

A4. Bouton « Écrire sur WhatsApp »
- Un éclat qui traverse le bouton, trois fois espacées de quelques secondes après le
  chargement, puis plus rien. Pas d'effet au clavier ni au toucher qui gêne le clic.

A5. Cartes et survols
- Cartes de fonctionnalités : léger soulèvement au survol (translateY de 4 px maximum,
  ombre), 200 ms. Icônes : léger mouvement au survol seulement (jamais en boucle).
- États :hover ET :focus-visible traités ensemble ; pas d'effet sur appareil tactile qui
  reste « collé » (utiliser @media (hover: hover)).

A6. En-tête
- Ombre et fond légèrement renforcés quand la page défile. Défilement piloté par CSS
  (animation-timeline: scroll()) là où le navigateur le permet ; sinon rien (ni JavaScript
  de secours, ni erreur).

A7. FAQ
- Ouverture et fermeture fluides des questions (les <details> existants) là où le navigateur
  le permet (::details-content, interpolate-size) ; sinon comportement actuel inchangé.
  Le « + » qui tourne existe déjà : le garder.

A9. (OPTIONNEL, à faire en dernier, abandonnable si le budget ou le rendu ne tient pas)
- Mini-caisse animée dans le hero, en CSS pur : trois articles apparaissent l'un après
  l'autre, le total en FCFA s'affiche, puis « Encaissé ✓ ». Données FICTIVES et crédibles
  (articles et prix de la démo « Keur Fatou »), une seule séquence (pas de boucle),
  aria-hidden avec un texte équivalent pour les lecteurs d'écran. Propose l'emplacement (en
  complément de l'illustration ou à sa place) par AskUserQuestion, avec une capture, avant
  de l'écrire.

Tests (rouge d'abord)
- Unitaire : cohérence hero.title / hero.rotation (voir A1).
- e2e Playwright, mouvement normal : à t = 0 « Les ventes » est visible et les deux autres
  mots ne le sont pas ; vers 3,2 s « Le stock » ; vers 6,2 s « L'argent » ; après environ 28 s
  la phrase complète est affichée et document.getAnimations() ne contient plus d'animation
  en cours sur la zone (horloge Playwright, pas d'attente réelle).
- e2e, reducedMotion: "reduce" : phrase complète visible tout de suite, aucune animation en
  cours (getAnimations vide pour les animations décoratives), tous les data-revele visibles.
- e2e, JavaScript désactivé : tout le contenu visible, titre complet lisible.
- Le texte sr-only du h1 est identique à hero.title ; le nom accessible du h1 aussi.
- CLS = 0 mesuré (PerformanceObserver layout-shift) à 360, 768 et 1280 px, clair et sombre ;
  LCP avant/après dans le résumé.
- axe : 0 violation (clair et sombre) ; Lighthouse accessibilité 100 sur ordinateur et
  téléphone ; clavier seul ; pause au focus vérifiée ; contraste AA du mot relayé.
- Aucune requête externe, CSP inchangée (tests existants verts) ; aucune animation avec
  iteration-count infinite dans le CSS de la vitrine (test de grep dans la suite).
- Poids avant/après (gzip) affiché ; le plafond de 5 Ko tient.
- Suite complète verte, y compris proxy.test.ts et les parcours de connexion (inchangés).

Fin de lot : make front-check, e2e des écrans touchés, CI verte, PR ouverte. ADR (CSS seulement
et pourquoi, aucune animation infinie et la règle WCAG 2.2.2, séquence trois tours puis phrase
complète, gestion de la hauteur, scripting: enabled, budget), README du front et table des ADR
à jour.
```

## Ce que le propriétaire fait ensuite

1. Regarder le titre sur un vrai téléphone (360 px) : le mot relayé ne doit pas faire sauter le texte, et la phrase complète apparaît après environ 27 secondes.
2. Tester le réglage « réduire les animations » du téléphone ou de l'ordinateur : la page doit s'afficher complète et immobile.
3. Décider de la mini-caisse (A9) après avoir vu le reste.
4. Déployer hors des heures d'ouverture, comme le lot précédent.
