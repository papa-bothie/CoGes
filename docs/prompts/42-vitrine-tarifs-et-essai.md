# Prompt 42 — Page d'accueil : « Tarifs » dans la navigation, carte « Essai gratuit »

> Petite retouche de la section « Nos offres » du lot B (prompt 41, ADR 0132). Demande du propriétaire, 27 novembre 2026.

Sur la branche `feat/offres-pro-business` si la PR du lot B n'est pas encore fusionnée ; sinon, branche `feat/vitrine-tarifs-essai` depuis `main` à jour.

```
Retouche de la page d'accueil (vitrine). Règles habituelles : tests d'abord, aucun service
payant, ne jamais ouvrir ni commiter .env. Résumé en français à la fin. Amende l'ADR 0132
(pas de nouvel ADR). Aucune migration, aucune route.

1. Navigation : remplacer « Comment ça marche » par « Tarifs »
 - Dans la barre de navigation (ordinateur ET menu du téléphone), l'entrée
   « Comment ça marche » (texte nav.howItWorks dans frontend/content/vitrine-texte.ts,
   ancre #comment) devient « Tarifs », qui mène à la section « Nos offres » (#offres,
   frontend/components/vitrine/offres.tsx).
 - La section « Comment ça marche » (#comment) reste sur la page, à sa place : seule
   l'entrée du menu change. Retire le libellé devenu inutile.
 - Le défilement vers #offres tient compte de l'en-tête fixe (le titre de la section n'est
   pas caché dessous), et le focus va au titre de la section.

2. « Nos offres » : une première carte « Essai gratuit »
 - Trois cartes dans cet ordre : Essai gratuit, Pro, Business. La ligne « Premium, sur
   devis » reste en dessous.
 - Carte « Essai gratuit » : prix « 0 F », sous-titre « pendant 30 jours », puis
   « Toutes les fonctions de CoGes Pro » et « Aucun paiement pour commencer ». Bouton
   principal « Démarrer l'essai gratuit ».
 - Le nombre de jours et l'offre de l'essai viennent de content/offres.json (trialDays,
   trialPlan), jamais écrits en dur. Le « 0 F » de l'essai est ajouté à cette même source.
 - Le bouton mène à /inscription quand l'inscription est ouverte (même condition que le
   bouton « Créer ma boutique » existant) ; sinon, au lien WhatsApp prérempli
   (« Je veux essayer CoGes gratuitement »).
 - La bascule « Par mois / Par an (-10 %) » ne change pas la carte d'essai (0 F dans les
   deux cas).
 - Mise en page : trois colonnes sur ordinateur, cartes empilées sur téléphone (360 px sans
   défilement horizontal). La carte d'essai se distingue légèrement (bordure ou étiquette
   « Pour commencer »), sans prendre le dessus sur Pro et Business. Jetons de couleur
   existants, aucun nouveau style.

3. Tests
 - vitrine-texte.test.ts : « Tarifs » présent dans la navigation, « Comment ça marche »
   absent de la navigation (la section reste) ; les gardes des prix admettent « 0 F »
   seulement dans la carte d'essai, toujours depuis la source partagée.
 - Vitest : trois cartes dans l'ordre, bouton de l'essai vers /inscription ou WhatsApp
   selon l'état de l'inscription, carte d'essai inchangée par la bascule annuelle.
 - e2e : le lien « Tarifs » amène à la section des offres (ordinateur et téléphone) ;
   axe 0 violation en clair et en sombre ; 360 px sans défilement horizontal.
 - make front-check, make maquette-check si touché, CI verte.
```

## Ce que le propriétaire vérifie

Dans une fenêtre de navigation privée, sur http://localhost:3000 puis en préproduction : le lien « Tarifs » du menu (ordinateur et téléphone) descend aux offres, la carte « Essai gratuit — 0 F » est la première, et son bouton mène à l'inscription (ou à WhatsApp si l'inscription est fermée).
