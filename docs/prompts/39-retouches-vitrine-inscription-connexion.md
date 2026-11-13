# Prompt 39 — Retouches : « Comment ça marche » dans l'en-tête, inscription au style de la connexion, pages d'entrée toujours claires

> **STATUT : PRÊT À LANCER** (13 novembre 2026). Suite de la vitrine (prompts 37 et 38) et de l'inscription (prompt 30). À lancer après leur fusion ; sinon l'agent s'arrête.

Branche `feat/entree-claire-et-nav`, depuis `main` à jour. Une PR par bloc, dans l'ordre : N (navigation), S (inscription), C (thème clair), P (capture avec photos).

## Décisions déjà prises

- Quatre demandes du propriétaire sont dans ce lot : le lien « Voir comment ça marche » passe du hero à la barre de navigation ; la page d'inscription prend la mise en page de la page de connexion ; la vitrine, l'inscription, la connexion **et les pages légales** sont **toujours claires**, quel que soit le thème de l'appareil ; la capture de la caisse sur ordinateur (section « À quoi ça ressemble ») est refaite avec des **photos réelles de produits** à la place des carrés colorés.
- La photo d'article (Cloudinary, groupe 5 bloc I) est codée et fonctionnelle : la capture montre donc une vraie fonction. Par défaut, la nouvelle capture **remplace** l'actuelle capture ordinateur (deux écrans de caisse presque identiques feraient doublon) ; la capture du téléphone ne change pas.
- Rien ne change pour ceux qui se connectent déjà : le thème choisi dans l'application (clair, sombre, automatique) reste respecté dès que la personne est connectée.

## Prompt à donner à l'agent

```
Lot « Pages d'entrée : navigation, inscription, thème clair » (branche
feat/entree-claire-et-nav, depuis main à jour). Règles habituelles : ADR au prochain numéro
libre, tests d'abord (rouge puis vert), aucun service payant, ne jamais ouvrir ni commiter
.env, deploy/.env.preprod, backend/.vercel/ ni /etc/coges/*. Résumé en français à la fin,
questions ouvertes par AskUserQuestion. Si les lots vitrine (ADR 0115), animations et
inscription (ADR 0118) ne sont pas fusionnés, ARRÊTE-TOI et dis-le moi.

Lis d'abord : frontend/AGENTS.md et node_modules/next/dist/docs/, docs/design/DESIGN.md,
frontend/app/globals.css (bloc `:root, .papier`, bloc `.dark`, `@custom-variant dark`),
frontend/app/providers.tsx (next-themes), frontend/app/(auth)/login/page.tsx,
frontend/app/(auth)/inscription/ (page.tsx, signup-flow.tsx et ses tests),
frontend/app/(auth)/verification/, frontend/components/vitrine/ (vitrine-header.tsx,
mobile-menu.tsx), frontend/content/vitrine-texte.ts.

Principes non négociables
- Aucune logique d'authentification ou d'inscription n'est modifiée : seulement la mise en
  page, le thème et un lien. proxy.ts, le cookie coges_known, les appels d'API et les tests
  de comportement existants restent inchangés et verts.
- L'écran de connexion garde le même rendu qu'aujourd'hui (la maquette v2, écran 25) :
  make maquette-check reste sous son seuil de 2 %.
- Aucune requête externe, CSP inchangée, aucune bibliothèque ajoutée.

BLOC N — « Comment ça marche » dans la barre de navigation
- Le lien « Voir comment ça marche » (ancre #comment) quitte le hero et entre dans la barre
  de navigation de la vitrine, entre « Fonctionnalités » et « Questions », sous le libellé
  court « Comment ça marche ». Il apparaît aussi dans le menu mobile (mobile-menu.tsx), au
  même rang.
- Le hero garde « Écrire sur WhatsApp » et la phrase d'essai gratuit. Le bouton WhatsApp se
  met à pleine largeur sur téléphone et garde sa taille naturelle sur ordinateur.
- Textes : ajoute nav.howItWorks dans frontend/content/vitrine-texte.ts et retire
  hero.howItWorks s'il n'est plus utilisé (aucun texte orphelin). Un test unitaire vérifie
  que chaque ancre de la navigation (#fonctionnalites, #comment, #questions) existe dans la
  page.
- Défilement : l'en-tête est collant ; la section visée ne doit pas se cacher dessous
  (scroll-margin-top). Au clavier, le focus arrive sur la section ou son titre.
- Les animations du lot 38 restent intactes (le titre du hero ne bouge pas de place).

BLOC S — Inscription à la mise en page de la connexion
- Extrais de login/page.tsx un composant de mise en page partagé (par exemple
  components/auth/entree-layout.tsx) : panneau vert à gauche (logo, phrase, texte, pastilles),
  formulaire à droite ; sur téléphone, le panneau se réduit au logo et à la phrase au-dessus
  du formulaire. La connexion l'utilise SANS changement visuel.
- /inscription et les écrans de la suite (« Vérifiez votre e-mail », « Demande reçue »,
  /verification et /verification/[jeton]) utilisent ce même composant. Le panneau de
  l'inscription peut porter son propre texte (par exemple la phrase de la connexion et la
  mention de l'essai gratuit de la durée réelle TRIAL_DAYS) : les textes vont dans
  frontend/lib/labels, jamais en dur.
- Dans la colonne de droite : le titre h1, le formulaire et les liens légaux, à la même
  largeur maximale (440 px) que la connexion. Un lien « J'ai déjà un compte » vers /login,
  équivalent du « Créer ma boutique » de la connexion.
- À conserver intact : la gestion du focus sur le titre à chaque étape, le champ piège
  (honeypot) hors écran, l'annonce des erreurs, le préfixe +221 du téléphone, le
  comportement quand l'inscription est fermée (404).
- Responsive : 360 px sans défilement horizontal ; le panneau ne repousse pas le formulaire
  hors du premier écran sur téléphone ; clavier seul.

BLOC C — Vitrine, inscription et connexion toujours claires
- Sont concernées : la vitrine (/), /login, /inscription, /verification,
  /verification/[jeton], /conditions et /confidentialite (les redirections /cgu et /cgv
  suivent). Elles s'affichent en CLAIR même si l'appareil est en mode sombre ou si la
  personne avait choisi « sombre » dans l'application. Les deux pages légales sont des pages
  publiques à une seule apparence : même une personne connectée en sombre qui les ouvre
  depuis les paramètres les voit claires (note-le dans l'ADR). Vérifie que le rendu du
  Markdown (tableaux, titres, liens) reste lisible et au bon contraste.
- Piège connu : `@custom-variant dark (&:is(.dark *))` fait que les variantes `dark:`
  s'appliquent à tout descendant de `html.dark`. Un simple conteneur `.papier` remettrait les
  jetons clairs mais laisserait les classes `dark:` actives. Il faut donc forcer le thème au
  niveau de next-themes (forcedTheme="light" selon le chemin, dans app/providers.tsx) et non
  seulement recolorer. Justifie ton choix dans l'ADR.
- Le thème choisi par la personne n'est JAMAIS effacé ni modifié : forcedTheme n'écrit rien
  dans le stockage. Une personne en sombre qui visite la vitrine puis se connecte retrouve son
  sombre dans l'application (test).
- Aucun éclair sombre au chargement : la page est claire dès le premier affichage, y compris
  le fond de la page et la barre de défilement. Ajoute `color-scheme: light` sur ces pages
  (et la balise meta correspondante) pour que les formulaires natifs restent clairs et que les
  modes « sombre forcé » de certains navigateurs mobiles n'inversent pas les couleurs.
  Vérifie aussi la couleur de barre du navigateur (theme-color) sur ces pages.
- Application installée, administration (frontend-admin/) et toutes les pages connectées :
  inchangées, thème automatique comme aujourd'hui.
- Les illustrations unDraw gardent leurs couleurs claires (déjà le cas) ; retire le code
  mort qui ne sert plus (variantes `dark:` de la vitrine, de l'inscription et de la
  connexion), et mets à jour les tests du lot 38 qui contrôlaient la vitrine en sombre :
  elle n'a plus de rendu sombre.

Tests (rouge d'abord)
- Unitaire : ancres de la navigation (bloc N) ; chemins forcés en clair (liste exacte,
  /dashboard et /parametres non inclus).
- e2e Playwright, colorScheme "dark" émulé ET localStorage theme="dark" : sur /, /login,
  /inscription, /verification, fond et texte calculés en clair (contraste AA), formulaires
  clairs ; sur /dashboard après connexion de démo, le sombre est bien appliqué ; le
  localStorage du thème est intact après la visite des pages d'entrée.
- e2e : « Comment ça marche » (ordinateur et menu mobile) fait défiler jusqu'à la bonne
  section sans la cacher sous l'en-tête ; le hero n'a plus qu'un bouton principal.
- e2e : inscription complète (e-mail capturé, lien, boutique prête, connexion) et chemin
  sans e-mail (demande reçue) dans la nouvelle mise en page, à 360 et 1280 px ; focus sur le
  titre à chaque étape ; honeypot inchangé ; axe 0 violation ; Lighthouse accessibilité
  100 sur la vitrine, /login et /inscription.
- Captures avant/après de /login (écart nul au sens du seuil de make maquette-check), de
  /inscription et de la vitrine ; donne-les dans le résumé.
- Parcours de connexion existants intacts ; proxy.test.ts inchangé et vert ; suite complète
  verte ; CSP et « aucune requête externe » verts.

Fin de lot : make front-check, make maquette-check, e2e des écrans touchés, CI verte, PR
ouverte. ADR (partage du composant de mise en page, forcedTheme et le piège de
`@custom-variant dark`, color-scheme, ce qui n'est pas concerné), README du front et table des
ADR à jour.
```

## Ce que le propriétaire fait ensuite

1. Tester en **mode sombre** (réglage du téléphone ou du PC) : vitrine, connexion et inscription restent claires ; l'application connectée, elle, suit toujours votre thème.
2. Tester l'inscription sur un vrai téléphone (360 px) : le panneau vert ne pousse pas le formulaire trop bas.
3. Trancher pour les pages légales (/conditions, /confidentialite) : claires aussi ou non.
4. Déployer hors des heures d'ouverture.

## Plus tard : capture de la caisse avec photos réelles

À faire **après le déploiement du groupe 5, bloc I (photos d'article)**, parce que la capture doit montrer ce que l'application fait vraiment.

1. Prendre ou choisir des photos de produits courants de boutique (riz, huile, sucre, savon, boissons) : vos propres photos, ou des images libres de droits (vérifier la licence, usage commercial autorisé). Éviter les emballages de marques reconnaissables et toute personne identifiable.
2. Les associer aux articles de la démo « Keur Fatou » dans l'application, puis prendre la capture de la grille de vente sur ordinateur (même cadre que les captures actuelles).
3. Ajouter l'image à `public/vitrine/` (WebP, taille réduite, texte alternatif), ajouter la capture à la section « À quoi ça ressemble », et mettre à jour le texte si besoin. Lot minuscule, à confier à l'agent après le groupe 5.
