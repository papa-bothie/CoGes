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
