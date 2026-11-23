# 0130 — Retouches A : liens légaux au moment d'accepter, facture claire, slogan

- **Date** : 2026-11-23
- **Phase** : prompt 40, lot A (branche `feat/retouches-lot-a`), premier lot du plan
  `plan-offres-paiement-et-retouches.md`
- **Statut** : acceptée
- **Décideur** : propriétaire (décisions R1 et R2 du prompt 40) ; pied de la vitrine et teinte
  claire choisis via AskUserQuestion le 2026-11-23
- **Amende** : ADR 0112 (facture au vert CoGes) et ADR 0117 (emplacement des liens légaux)

## Contexte
Trois retouches demandées par le propriétaire, sans migration, sans route nouvelle et avec
`openapi.json` inchangé :
- **R1** : les conditions d'utilisation et la politique de confidentialité ne doivent plus
  apparaître dans l'interface. On ne les voit qu'au moment de les accepter.
- **R2** : la facture A4 au vert (amendement de l'ADR 0112) consomme trop d'encre, avec trois
  grands aplats `vert-marque` (bandeau du tableau, bandeau « Total », rond des initiales) et
  des pastilles pleines `vert-action`. Elle passe en couleur claire pour tous, dès maintenant.
  La personnalisation (couleur, style) viendra avec l'offre Business (lot E) : elle n'est pas
  construite ici.
- **R3** : un slogan en dernière ligne de la page d'accueil.

## Options envisagées
Pied de la vitrine (R1) :
1. **« Confidentialité » seul (retenue)** : la politique reste consultable par quelqu'un qui
   n'a pas encore de compte. « Conditions » ne se lit plus qu'au moment d'accepter.
2. Garder les deux liens discrets : contraire à l'esprit de la décision du propriétaire.
3. Tout retirer : la politique de confidentialité ne serait plus atteignable que par son
   adresse ou le plan du site.

Teinte claire de la facture (R2) :
1. **`#e6f4ec`, la teinte des ventes (retenue)** : déjà dans la charte, luminance 0,88.
   Contraste de l'encre 16,6:1, du vert foncé 9,2:1, du gris 8,6:1.
2. `#eef7f1`, plus pâle (luminance 0,91) : la teinte se voit à peine sur certaines
   imprimantes.
3. Aucun fond, des filets seuls : le moins d'encre possible, mais l'aspect CoGes s'efface.

## Décision
### R1 — Liens légaux
- **Retirés** :
  - les deux entrées du menu du compte (`settings-menu.tsx`) et leur séparateur ;
  - `<LegalLinks />` sur `/login`, `/password`, `/verification`, `/verification/[jeton]` et
    `/inscription`.
- **Pied de la vitrine** : un seul lien discret, « Confidentialité ».
- **Gardés** :
  - les deux liens de la case d'acceptation (`LegalConsent`), à l'inscription et sur l'écran
    `/acceptation`. Ils s'ouvrent dans un nouvel onglet avec `rel="noopener noreferrer"` :
    la saisie n'est jamais perdue et l'onglet ouvert n'a pas d'`opener` ;
  - les pages `/conditions` et `/confidentialite` elles-mêmes (publiques, inchangées) et
    leurs liens croisés (`LegalLinks` dans `legal-page.tsx`, son seul usage restant) ;
  - l'acceptation tracée (ADR 0117), inchangée.
- **Libellés** : aucun n'est devenu inutile. `labels.legal.conditions`, `privacy` et
  `linksLabel` servent encore à `LegalLinks` sur les textes, et `privacy` au pied de la
  vitrine.

### R2 — Facture claire
- **Trois jetons seulement**, pour que la couleur de la boutique puisse un jour remplacer
  l'accent sans toucher au reste :

  | Jeton | Valeur | Rôle |
  |---|---|---|
  | `facture-accent` | `#024a2c` | texte seulement : titre « FACTURE », nom de la boutique, intitulés, icônes, initiales |
  | `facture-accent-clair` | `#e6f4ec` | seul fond teinté : en-tête du tableau, ligne « Total », « Facturé à », pastilles, rond des initiales |
  | `facture-filet` | `#117a3c` | filets fins : sous l'en-tête, de part et d'autre de l'en-tête du tableau et du total, contour des pastilles et du rond |

- **Où ils sont définis** :
  - côté front, à un seul endroit : le bloc clair de `globals.css` (`:root, .papier`),
    exposé en `bg-facture-*` / `text-facture-*` / `border-facture-*` ;
  - côté PDF, à un seul endroit : `pdf.PALETTE`, exposé en `INVOICE_ACCENT`,
    `INVOICE_ACCENT_LIGHT` et `INVOICE_RULE`.
- **Verts retirés de la palette PDF** : `vert-marque`, `vert-action`, `ventes-teinte` et
  `sur-action`. Plus aucune pièce ne les emploie.
- **Rendu** :
  - en-tête du tableau et total en accent clair, texte encre, en gras, entre deux filets ;
  - titre et nom de la boutique en vert, en texte seulement ;
  - pastilles claires cerclées de filet, avec une icône d'accent dessinée au trait (la
    touche du téléphone aussi, pour ne laisser aucune surface foncée pleine) ;
  - sans logo, un rond clair et les initiales en vert.
- **Règle mesurable, testée** : aucune surface remplie de la facture (hors logo et texte)
  n'a une luminance relative inférieure à 0,80. Le texte est à 4,5:1 au moins sur chaque
  fond.
  - **PDF** : on lit les commandes de dessin avec pypdf (`rg` puis `f`/`B`, hors `Tj`) ;
    une vente payée, à crédit ou annulée, avec ou sans logo.
  - **Vue** : chaque classe `bg-*` / `text-*` de la facture est résolue par `@theme` puis
    le bloc clair de `globals.css`.
- **Niveaux de gris** : la structure tient par les filets (au moins cinq traits de filet,
  vérifiés dans le PDF ; luminance du filet < 0,25, contraste en gris ≥ 3:1) et par le gras.
- **Ticket 80 mm et bon de retour** : inchangés. Le bon de retour suit le gabarit du ticket
  (`render_return_slip`, `TicketHeader`), en noir et blanc, et ne partage pas le modèle A4 ;
  le PDF des pièces (ADR 0113) est celui de la facture, donc traité. Les exports du
  comptable (ADR 0114) n'utilisaient déjà que `recu-entete`.

### R3 — Slogan
- `texte.footer.slogan` = « Une meilleure façon de gérer son commerce. », dans
  `content/vitrine-texte.ts`.
- Rendu en dernière ligne du pied, sous le lien et le copyright : `text-corps` (16 px),
  `encre-2` sur la carte, centré sur téléphone et aligné à gauche dès 768 px.

## Conséquences
- **Tests ajoutés** :
  - `test_receipt_pdf.py` : `test_no_dark_surface_on_the_invoice` (6 cas) et
    `test_the_invoice_structure_survives_grey_printing` ;
  - `test_pdf_palette.py` : trois jetons, contraste du texte et du filet ;
  - `receipt-view.test.tsx` : aucune surface sombre (3 cas) ;
  - `receipt-contrast.test.ts` : refait pour la facture claire, les fonctions de contraste
    étant partagées dans `test/contrast.ts` ;
  - `settings-menu.test.tsx` : gérant, vendeur et comptable ;
  - `legal-placement.test.tsx` : pages d'entrée, menu, pied de la vitrine, case
    d'acceptation ;
  - `vitrine-texte.test.ts` : le slogan, une seule fois ;
  - e2e : liens de la case ouverts dans un onglet sans `opener`, case restée cochée.
- **Tests existants mis à jour** (ils attendaient les liens ou les aplats) :
  - `test_receipt_pdf.py::test_the_green_invoice_follows_the_model` : aplats foncés
    remplacés par l'accent clair ;
  - `test_pdf_palette.py` : `test_the_invoice_greens_are_in_the_palette` et
    `test_white_on_the_greens_is_aa`, remplacés ;
  - `receipt-view.test.tsx` : six assertions de classes (filet, pastilles, titre,
    « Facturé à », initiales, en-tête du tableau, total) ;
  - `receipt-contrast.test.ts` : blanc sur vert, remplacé ;
  - `e2e/legal.spec.ts` :
    - « les liens sont au pied de la connexion et de la vitrine » devient « aucun lien légal
      sur les pages d'entrée ; « Confidentialité » seul au pied de la vitrine » ;
    - « second login » vérifie l'absence des entrées dans le menu ;
  - `e2e/entree-claire.spec.ts` : les conditions s'ouvrent par l'adresse, et non plus par
    le menu du compte.
- **Captures** : `docs/design/captures/lot-a/`, avant et après, pour l'écran, l'impression
  du navigateur, le PDF et le PDF en gris (`e2e/captures-lot-a.spec.ts` sous
  `CAPTURES_STAGE`).
- **Hors lot** : la facture personnalisable (Business, lot E) ne fait que remplacer
  `facture-accent` (et dériver l'accent clair et le filet), sans réglage ni migration ici.
  Les offres, les relances et le paiement en ligne viendront dans les lots B à D.
