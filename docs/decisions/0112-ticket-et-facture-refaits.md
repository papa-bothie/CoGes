# 0112 — Ticket et facture refaits

- **Date** : 2026-11-04
- **Phase** : groupe 2, bloc F (prompt 35, branche `feat/group2-f-receipt-redesign`, empilée
  sur le bloc L)
- **Statut** : acceptée
- **Décideur** : propriétaire (contenu décrit dans le prompt 35, plan du bloc F validé le
  2026-11-04)

## Contexte
Le propriétaire veut un seul chantier « qualité et style » sur le reçu : le contenu
d'aujourd'hui, plus le logo (ADR 0111), avec l'adresse mise en évidence. Le PDF du bloc T
doit suivre la même mise en page et la même source de données.

## Options envisagées
1. **Enrichir `GET /sales/{id}/receipt` (retenue)** : une seule source pour l'écran,
   l'impression et le PDF du serveur. Les champs sont additifs.
2. Laisser le front recouper la vente, les retours et la fiche de l'article : trois
   lectures, et un PDF serveur qui devrait refaire le même assemblage ailleurs.

## Décision
- **Contrat du reçu** (ajouts, rien ne change de sens) :
  - `company.logo_updated_at` ;
  - `lines[].description` et `lines[].unit`, relus de la fiche comme le nom (des libellés,
    pas des montants) ;
  - `returns[]` : n°, date et valeur rendue des retours de la vente, du plus ancien au plus
    récent.
  - Le prix d'une ligne reste le **prix appliqué**. `list_price` et la raison d'un prix
    changé ne sont jamais exposés au client (ADR 0107), et un test le vérifie.
- **Facture A4** :
  - En-tête : le logo à gauche, ou les initiales cerclées d'encre s'il n'y en a pas (plus de
    pastille verte). Puis le nom, l'adresse en gras, le téléphone, le NINEA et le RC. À
    droite : « FACTURE », n°, ville et date, date et heure, vendeur.
  - Bloc client.
  - Vrai tableau HTML : désignation, avec la description en dessous ; quantité avec son
    unité (« 2,5 kg ») ; prix unitaire ; colonne « Remise » **seulement si une ligne en
    porte** ; montant. Les montants sont en chiffres tabulaires, alignés à droite.
  - Totaux : sous-total, remises et TVA (seulement quand il y a une remise ou une taxe),
    total, payé par moyen de paiement (paiements annulés et contre-écritures exclus,
    additionnés en décimal), déjà payé, reste dû.
  - Retours liés, montant en lettres, pied de reçu (à défaut « Merci de votre
    confiance. »), signature.
- **Pagination à l'impression** :
  - `@page` A4 numérote « Page n/N » dans la marge basse ; c'est supporté par Chrome et
    Edge, pas par Firefox, et le PDF du bloc T paginera partout ;
  - l'en-tête du tableau se répète (`table-header-group`) ;
  - une ligne, les totaux, les retours et le pied ne se coupent jamais (`break-inside`).
- **Petit ticket 80 mm** : logo en niveaux de gris en tête, nom, adresse en gras,
  téléphone ; lignes courtes, comme sur la maquette 05 (« 2 x 1 500 », sans description ni
  unité : l'unité est dans la colonne Quantité de la facture), et remise sous la ligne s'il
  y en a une ; mêmes totaux ; paiements par moyen ; retours ; pied de reçu.
- **Bon de retour** : même en-tête que le ticket (`TicketHeader`, `sales/receipt-parts.tsx`).
- **Palette d'impression** : uniquement les jetons `recu-*`, documentés dans
  `docs/design/DESIGN.md`. Le tampon « VENTE ANNULÉE » passe à l'encre, pour rester lisible
  en noir et blanc.
- **Réglages → Boutique** : sans adresse, le gérant lit « Ajoutez l'adresse de la boutique
  pour vos factures. »

## Conséquences
- Tests :
  - backend : description et unité, prix appliqué seul, retours liés, `logo_updated_at` ;
  - Vitest : facture avec et sans logo, avec et sans adresse, colonne et ligne de remise
    conditionnelles, 40 lignes (pagination et lignes insécables), montants alignés,
    paiements par moyen en décimal, ticket en noir et blanc, bon de retour, alerte
    d'adresse ;
  - e2e : ticket et facture avec logo, adresse et description, axe en clair et en sombre,
    360 px.
- `make maquette-check` : 05 et 05b s'écartent un peu plus de la maquette v2. C'est voulu
  (logo, adresse en gras, tableau à colonnes, totaux détaillés) ; les écarts sont notés
  dans `docs/design/captures/phase-15/comparaison.md`.
- Le bloc T rendra ces deux pièces en PDF côté serveur à partir de la même lecture.

## Amendement du 2026-11-05 : facture au vert CoGes
Demande du propriétaire avant fusion, d'après le modèle `docs/design/references/modele-facture.jpg`
(disposition et remise choisies par AskUserQuestion le 2026-11-05). **Remplace la palette
noir et blanc pour la facture A4 seulement** ; le ticket et le bon de retour restent en
noir et blanc (imprimantes thermiques).
- **En-tête** : logo à gauche (sinon initiales dans une pastille `vert-marque`) et nom ; à
  droite téléphone et adresse, chacun avec une pastille ronde `vert-action` ; filet vert
  dessous.
- **« De »** (nom, adresse, téléphone, NINEA, RC) à gauche, grand titre **« FACTURE »**
  en `vert-marque` à droite, « Facture n° F-1044 », la date et le vendeur dessous.
- **« Facturé à »** dans un cadre `ventes-teinte` : le client, ou « Client de passage ».
- **Tableau** : bandeau `vert-marque` à texte blanc (N°, Désignation, Prix unitaire, Qté,
  Total), en-tête répété sur chaque page ; description puis « Remise : -200 F » en petit
  sous la désignation (plus de colonne Remise) ; lignes alternées `recu-entete` ;
  montants alignés à droite. Sur un téléphone, le tableau défile dans son cadre.
- **Totaux** : sous-total, remises, TVA s'il y en a, bandeau `vert-marque` « Total », puis
  « Déjà payé » et « Reste à payer » — jamais pour une vente annulée.
- **Bas de page** : « Merci pour votre confiance », moyens de paiement utilisés avec leur
  montant, pied de reçu, puis un cadre « Signature et cachet » à droite ; « Page n/N ».
  Pas de coins décoratifs.
- **Couleurs** : jetons de la maquette v2 seulement. `.papier` reprend le bloc clair de
  `globals.css` (la facture reste claire en sombre) ; `print-color-adjust: exact`. Blanc
  sur `vert-marque` 11:1, sur `vert-action` 5,4:1 (AA), vérifiés par
  `receipt-contrast.test.ts`, y compris le bandeau converti en gris.
- **Captures** : `docs/design/captures/groupe-2/facture-verte/` (`avant-*`, `apres-*`, à
  1280 et 390 px) ; écart à la maquette v2 noté dans `docs/design/maquette-v2/ecarts.md`.
- Le PDF du serveur (bloc T, ADR 0113) suit la même mise en page.
