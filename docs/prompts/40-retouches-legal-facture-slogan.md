# Prompt 40 — Lot A : liens légaux au moment d'accepter, facture claire, slogan

> Premier lot du plan `plan-offres-paiement-et-retouches.md` (23 novembre 2026). Il ne dépend d'aucune décision sur les offres. Audit fait sur `main` au commit `a3bb0ec`.

Branche `feat/retouches-lot-a`, depuis `main` à jour.

```
Lot « Retouches A : liens légaux, facture claire, slogan » (branche feat/retouches-lot-a,
depuis main à jour). Règles habituelles : ADR au prochain numéro libre (0130 au moment de
l'audit), tests d'abord (rouge puis vert), aucun service payant, ne jamais ouvrir ni
commiter .env, deploy/.env.preprod ni backend/.vercel/. Résumé en français à la fin,
questions ouvertes par AskUserQuestion. Lis d'abord les ADR 0111 (logo), 0112 et son
amendement (ticket et facture), 0113 (PDF des pièces), 0115 (page d'accueil), 0117 (pages
légales et acceptation), 0123, ainsi que docs/design/DESIGN.md (jetons recu-*).
Aucune migration, aucune nouvelle route, openapi.json inchangé.

R1. Liens légaux : seulement au moment de les accepter
Décision du propriétaire : les conditions d'utilisation et la politique de confidentialité
ne doivent plus apparaître dans l'interface, seulement au moment de les accepter.
Constat (à vérifier) :
 - menu du compte : frontend/components/shell/settings-menu.tsx (entrées /conditions et
   /confidentialite, et leur séparateur) ;
 - <LegalLinks /> sur les pages d'entrée : (auth)/login, (auth)/password,
   (auth)/verification, (auth)/verification/[jeton], (auth)/inscription ;
 - pied de la page d'accueil : (vitrine)/page.tsx ;
 - case d'acceptation : frontend/components/legal/legal-consent.tsx (inscription, et
   écran d'acceptation à la première connexion ou à une nouvelle version, ADR 0117).
À faire :
 - Retirer les deux entrées du menu du compte et LegalLinks des cinq pages d'entrée.
 - GARDER : les liens dans la case d'acceptation (legal-consent.tsx) partout où on accepte ;
   les pages /conditions et /confidentialite elles-mêmes (publiques, sans connexion,
   inchangées, avec leurs liens internes de legal-page.tsx) ; l'acceptation tracée.
 - Les liens de la case d'acceptation ne doivent jamais faire perdre la saisie : ouverture
   dans un nouvel onglet (rel="noopener noreferrer") si ce n'est pas déjà le cas.
 - [DEMANDER] Pied de la page d'accueil. Recommandation : garder UN lien discret
   « Confidentialité » (la politique de confidentialité doit rester consultable par
   quelqu'un qui n'a pas encore de compte), et retirer « Conditions ». Autres options :
   garder les deux liens discrets, ou tout retirer.
 - Libellés devenus inutiles dans lib/labels.ts : les retirer ; LegalLinks supprimé s'il
   n'a plus d'usage.
 - Tests : Vitest (menu du compte sans les deux entrées pour chaque rôle ; pages d'entrée
   sans liens légaux ; case d'acceptation avec les deux liens, ouverts dans un nouvel
   onglet) ; e2e (/conditions et /confidentialite accessibles en navigation privée ;
   inscription et acceptation à la première connexion inchangées). Les tests existants qui
   attendaient ces liens sont mis à jour ; liste-les dans l'ADR.

R2. Facture en couleur claire (économie d'encre)
Décision du propriétaire : la facture consomme trop d'encre. Couleur claire pour tous,
maintenant. La personnalisation (couleur, style) viendra plus tard, comme fonction de
l'offre Business : NE PAS la construire dans ce lot.
Constat (à vérifier) : deux rendus de la facture A4 doivent rester identiques.
 - PDF : backend/app/core/pdf.py (PALETTE : coges-vert-marque #024a2c = BRAND,
   coges-vert-action = ACTION, coges-ventes-teinte = TINT, ON_GREEN) et
   backend/app/modules/sales/documents.py : bandeau d'en-tête du tableau en aplat BRAND,
   ligne du total en aplat BRAND avec texte blanc, bloc en TINT, titre « FACTURE » et nom
   de la boutique en BRAND, pastilles rondes pleines ACTION devant les coordonnées.
 - Vue et impression du navigateur : frontend/app/(app)/sales/[id]/receipt/receipt-view.tsx
   (facture A4 : rond bg-marque à la place du logo, pastilles bg-primary, bandeaux), avec
   [print-color-adjust:exact], qui force l'impression des fonds.
Attendu :
 - Plus aucun aplat foncé. En-tête du tableau et ligne du total : fond très clair (une
   teinte verte légère, à proposer) avec un texte encre foncée, et un filet vert fin pour
   la structure. Titre « FACTURE » et nom de la boutique : vert en texte seulement.
   Pastilles : contour vert ou fond très clair, icône verte. Sans logo : rond clair et
   initiale verte.
 - Règle mesurable, testée : aucune surface remplie de la facture (hors logo de la
   boutique et texte) n'a une luminance relative inférieure à 0,80, dans le PDF comme dans
   la vue. Contraste du texte sur son fond au moins 4,5:1 (étends receipt-contrast.test.ts
   et ajoute l'équivalent côté PDF).
 - Lisible imprimée en niveaux de gris : la structure (en-tête, total) reste repérable sans
   la couleur (filets, gras).
 - Ticket 80 mm : inchangé (déjà en noir et blanc). Les autres pièces qui partagent le
   modèle A4 (bon de retour, PDF des pièces de l'ADR 0113) reçoivent le même traitement.
 - Préparer la personnalisation future sans la construire : toutes les couleurs de la
   facture passent par un seul petit jeu de jetons (accent, accent clair, filet), défini à
   un seul endroit côté PDF et à un seul endroit côté front, pour qu'une couleur choisie par
   la boutique puisse plus tard remplacer l'accent. Aucun réglage, aucune migration.
 - Captures avant/après (écran, PDF, PDF imprimé en niveaux de gris) dans
   docs/design/captures/lot-a/. Amende l'ADR 0112.
 - Tests : couleurs utilisées par le PDF (commandes de dessin ou palette), Vitest de la vue,
   tests PDF existants verts, make maquette-check si la maquette est touchée.

R3. Slogan tout en bas de la page d'accueil
 - Texte exact : « Une meilleure façon de gérer son commerce. »
 - Dernière ligne du pied de page de la page d'accueil, sous les liens et le copyright.
   Texte dans frontend/content/vitrine-texte.ts (texte.footer.slogan), jamais en dur dans
   la page. Discret mais lisible : 15 px au moins, contraste AA, centré sur téléphone.
 - Tests (vitrine-texte.test.ts) : le slogan est présent, une seule fois ; les gardes
   existantes (promesses, prix, essai) restent vertes sans modification.

Fin de lot
make front-check, suite backend complète (tests PDF), e2e des écrans touchés, axe 0
violation, Lighthouse accessibilité au moins 95 sur la page d'accueil et la connexion, CI
verte. ADR « Retouches A » (choix des couleurs et règle de luminance, emplacement des liens
légaux), amendements des ADR 0112 et 0117, CLAUDE.md §8 et table des ADR.

Hors lot, volontairement : facture personnalisable (Business, lot E), offres, prix et
droits par offre (lot B), relances et suspension (lot C), paiement en ligne (lot D).
```

## Ce que le propriétaire fait lui-même

1. **Répondre à la question du pied de page** de la page d'accueil (lien « Confidentialité » gardé ou non).
2. **Après le déploiement**, imprimer une facture sur l'imprimante d'une boutique, en couleur puis en noir et blanc : elle doit rester lisible, et sans grandes surfaces sombres.
3. Ouvrir le menu du compte et les pages de connexion : plus aucun lien vers les textes légaux. Puis faire une inscription de test : les deux liens doivent être dans la case à cocher et s'ouvrir sans perdre la saisie.
4. Vérifier le slogan tout en bas de coges.app, sur téléphone et sur ordinateur.
