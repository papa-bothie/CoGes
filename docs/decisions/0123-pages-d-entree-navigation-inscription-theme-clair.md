# 0123 — Pages d'entrée : « Comment ça marche » dans la navigation, inscription à la mise en page de la connexion, toujours en clair

- **Date** : 2026-11-13
- **Phase** : prompt 39 (blocs N, S, C, P), suite des ADR 0115, 0116, 0117 et 0118
- **Statut** : acceptée
- **Décideur** : utilisateur (prompt 39 et AskUserQuestion du 2026-11-13 : photos fournies par
  le propriétaire pour le bloc P, barre du navigateur au fond papier clair)

## Contexte
Quatre demandes du propriétaire sur les pages qu'un visiteur voit avant d'être connecté :
le lien « Voir comment ça marche » du hero ira dans la barre de navigation, l'inscription
prendra la mise en page de la connexion, ces pages resteront claires quel que soit le thème de
l'appareil, et la capture de la caisse sur ordinateur montrera de vraies photos d'articles.
Ni l'authentification ni l'inscription ne changent (`proxy.ts`, `coges_known`, appels d'API).

## Bloc N — navigation
- `components/vitrine/nav-links.ts` (`NAV_LINKS`) liste les trois ancres : « Fonctionnalités »
  (`#fonctionnalites`), « Comment ça marche » (`#comment`) et « Questions » (`#questions`).
  L'en-tête et le menu du téléphone lisent cette même liste. `nav-links.test.ts` vérifie que
  chaque ancre existe une fois dans la page, et que `hero.howItWorks` a disparu, ce qui évite
  un texte orphelin.
- Le hero garde un seul bouton principal : « Créer ma boutique », ou « Écrire sur WhatsApp »
  si l'inscription est fermée. Les boutons prennent toute la largeur sur téléphone
  (`w-full sm:w-auto`) et gardent leur taille naturelle sur ordinateur. Le titre animé ne
  bouge pas (tests du lot 38 verts).
- Les sections ciblées ont `scroll-mt-20` (80 px pour un en-tête de 72 px) et `tabIndex={-1}`.
  Le navigateur y place le focus quand on suit l'ancre, ce qui aide le clavier et les
  lecteurs d'écran.
- Écart trouvé par le test e2e à 768 px : trois liens plus WhatsApp ne tiennent pas sur une
  ligne (34 px de trop). Le bouton WhatsApp de l'en-tête ne paraît donc qu'à partir de
  1024 px (`lg`). Entre 768 et 1023 px, on le trouve dans le hero, le dernier appel et le pied
  de page.
- Le test de la mini-caisse (lot 38) était soumis à une course : sous charge, la première
  ligne finissait avant que le test ne la mette en pause. Son horloge d'animation est
  ralentie par CDP le temps de la prendre en main. Le produit ne change pas.

## Bloc S — inscription à la mise en page de la connexion
- `components/auth/entree-layout.tsx` (`EntreeLayout`) reprend à l'identique la mise en page
  de `login/page.tsx` : panneau vert (logo, phrase, texte, pastilles dès 768 px) et colonne de
  440 px. La connexion l'utilise sans changement visuel : `make maquette-check` passe à 41/41
  (écran 25 sous 2 %).
- Le composant sert à `/inscription` (formulaire, « Vérifiez votre e-mail », « Demande
  reçue »), `/verification` et `/verification/[jeton]`. Leur panneau lit
  `labels.signup.panel` : la phrase de la connexion et « … ${TRIAL_DAYS} jours d'essai
  gratuit ». `TRIAL_DAYS` vit maintenant dans `lib/trial.ts` : `lib/labels` peut le lire sans
  embarquer les textes de la vitrine, qui la réexportent. L'introduction du formulaire ne
  répète plus l'essai.
- En bas de la colonne, « J'ai déjà un compte » suivi du bouton bordé « Se connecter »
  remplace le lien souligné : c'est le pendant de « Pas encore de boutique ? » + « Créer ma
  boutique » sur la connexion. Les pages de vérification gagnent les liens légaux.
- Restent inchangés : le focus sur le titre à chaque étape, le champ piège, les erreurs
  annoncées, le +221 et la 404 quand l'inscription est fermée (Vitest et e2e). Les e2e
  vérifient la mise en page à 1280 et à 360 px : panneau à gauche ou au-dessus, colonne
  ≤ 440 px, titre et premier champ dans le premier écran du téléphone, aucun défilement de
  côté, clavier, axe.
