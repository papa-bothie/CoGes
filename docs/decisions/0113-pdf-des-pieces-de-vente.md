# 0113 — PDF des pièces de vente

- **Date** : 2026-11-04
- **Phase** : groupe 2, bloc T (prompt 35, branche `feat/group2-t-receipt-pdf`, empilée sur
  F)
- **Statut** : acceptée
- **Décideur** : propriétaire (Q0 le 2026-11-04 : ReportLab côté serveur, ADR 0111 ; plan du
  bloc T validé le même jour)

## Contexte
Le commerçant veut télécharger le ticket et la facture, ou les partager sur WhatsApp, y
compris depuis un téléphone qui n'imprime pas. L'impression par le navigateur (bloc F)
reste en place. Le PDF doit suivre la même mise en page et la même source de données.

## Options envisagées
1. **ReportLab côté serveur, depuis `build_receipt` (retenue)** : le même rendu partout et
   les mêmes chiffres que l'écran, puisque c'est la même lecture.
2. PDF dans le navigateur : écarté par Q0 (rendu variable selon l'appareil, chiffres
   recalculés à deux endroits).

## Décision
- **Dépendances** :
  - `reportlab==5.1.0` à l'exécution : roues sans bibliothèque système, ne tire que
    `charset-normalizer` et Pillow, déjà présent ;
  - en dev seulement : `pypdf==6.21.4` (relit les PDF en test) et
    `types-reportlab==5.1.0.20261104` (pour mypy).
- **Polices** : instances statiques Regular et Bold de Figtree et de JetBrains Mono (OFL),
  tirées des fichiers du front par `fontTools.varLib.instancer`, dans
  `backend/app/core/fonts/` avec leurs licences (25 à 57 Ko chacune).
  - Chaque instance porte **son propre nom** dans la table `name`. Avec le même nom, le
    lecteur PDF confondait Regular et Bold, et le gras ne sortait pas (constaté puis
    corrigé).
  - La sous-police latine n'a pas l'espace fine insécable (U+202F) ; `pdf.text` la
    remplace par une espace insécable pleine, comme `formatAmount` le fait déjà à l'écran.
- **Moteur commun `app/core/pdf.py`**, sans règle métier :
  - polices, palette d'impression (les `recu-*`), styles, logo (niveaux de gris pour le
    ticket) ;
  - A4 paginé « Page n/N » par un canevas à deux passes ;
  - bande de ticket de 80 mm, aussi haute que son contenu (une seule page) ;
  - `Content-Disposition` avec un nom ASCII plus `filename*` en UTF-8 ;
  - largeur utile qui tient compte des 6 pt de marge intérieure des cadres ReportLab.

  Les exports du bloc X s'en serviront.
- **Mise en page `sales/documents.py`** : fonctions pures qui prennent des données et
  rendent des octets. Elles suivent l'impression du bloc F :
  - facture : tableau à en-tête répété, remise si elle existe, montants alignés, totaux,
    paiements par moyen, retours, montant en lettres (`display.amount_in_words`, même
    orthographe que le front), pied ;
  - ticket : lignes courtes en chasse fixe, retrait par `leftIndent` (un `Paragraph`
    efface les espaces de tête, même insécables) ;
  - bon de retour au gabarit du ticket.

  Les montants s'écrivent « 87 500 F », comme le reçu à l'écran (`display.amount`).
- **Routes**, toutes en `application/pdf`, `no-store` et `nosniff`, sans URL publique :
  - `GET /sales/{id}/receipt/pdf?format=ticket|a4` (`sales:read`) : brouillon ⇒ 409
    `sale_not_confirmed` ;
  - `GET /sale-returns/{id}/slip/pdf` (`sale_returns:read`) ;
  - autre entreprise ⇒ 404. L'accès support peut télécharger (ce sont des GET), sans
    jamais écrire ;
  - noms de fichier : `Facture-1044-Boutique-Keur-Fatou.pdf`, `Ticket-…`, `Retour-0007-…`
    (quatre chiffres au moins, nom de la boutique sans accent).
- **Durée mesurée** : environ 50 ms pour un ticket de 5 lignes sur le poste, polices déjà
  chargées (le test exige moins de 1 s).
- **Front** (reçu et bon de retour) :
  - **« Télécharger le PDF »** lit le PDF en blob, avec le jeton dans l'en-tête, et
    l'enregistre sous le nom donné par le serveur ;
  - **« Partager »** utilise `navigator.share({ files })` quand le téléphone le permet
    (WhatsApp, e-mail…), et un partage annulé n'est ni une erreur ni un téléchargement ;
    sinon le PDF est téléchargé et le lien WhatsApp existant s'ouvre avec le texte du
    reçu ;
  - la prise en charge est vérifiée **au clic**, avant tout `await`, sans quoi la fenêtre
    WhatsApp serait bloquée ;
  - le bouton WhatsApp texte reste, comme sur la maquette 05 ;
  - le service worker ne garde rien de `/api/v1` (ADR 0102).

## Conséquences
- Tests :
  - backend : PDF relus par pypdf (nom, adresse, NINEA, description, total, « Page n/N »,
    logo présent ou absent, ticket d'une page de 80 mm, 60 lignes sur plusieurs pages
    avec en-tête répété, prix de la fiche jamais imprimé) ; brouillon refusé, autre
    entreprise 404, droit manquant 403, vendeur et support autorisés, en-têtes, durée ;
    montant en lettres identique au front ;
  - registres : `CROSS_TENANT_ROUTES` ;
  - Vitest : partage avec fichier, repli téléchargement + WhatsApp au clic, annulation,
    nom du serveur ;
  - e2e : facture téléchargée (`%PDF-`, nom), ticket passé au partage simulé, bon de
    retour téléchargé, axe.
- La pagination « Page n/N » de la facture marche dans tous les lecteurs PDF, ce que
  l'impression de Firefox ne fait pas (ADR 0112).
