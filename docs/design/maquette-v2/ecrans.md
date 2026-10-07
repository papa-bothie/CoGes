# Index des écrans de la maquette v2

Chaque écran a :

- une capture à 1280 px (`captures/NN-nom.png`) et une à 390 px (`captures/NN-nom-390.png`) ;
- une page statique (`html/NN-nom.html`), à ouvrir dans un navigateur et à inspecter pour lire les valeurs CSS
  exactes ;
- son fichier source (`source/*.dc.html`), qui contient les textes, les données d'exemple et la logique de chaque
  état (bloc `<script>` en bas). Ce fichier se **lit** ; il ne s'exécute pas hors de l'outil de maquette.

Les lignes « état » (lettre après le numéro) montrent le même écran après une action.

| N° | Écran | Captures | Source | Route cible dans le front | Lot |
|---|---|---|---|---|---|
| 01 | Accueil | `01-accueil` | `Main.dc.html` | `/dashboard` | 3a |
| 02 | Nouvelle vente | `02-nouvelle-vente` | `Vente.dc.html` | `/sales/new` | 3a |
| 02b | … paiement d'une partie (montant tapé + pavé) | `02b-nouvelle-vente-une-partie` | idem | idem | 3a |
| 02c | … rendu de monnaie | `02c-nouvelle-vente-rendu-monnaie` | idem | idem | 3a |
| 02d | … écran de succès | `02d-nouvelle-vente-succes` | idem | idem | 3a |
| 03 | Liste des ventes | `03-liste-des-ventes` | `Ventes.dc.html` | `/sales` | 3a |
| 04 | Détail d'une vente | `04-detail-vente` | `VenteDetail.dc.html` | `/sales/[id]` | 3a |
| 04b | … annulation (raison) | `04b-detail-vente-annulation` | idem | idem | 3a |
| 05 | Reçu, petit ticket 80 mm | `05-recu-ticket` | `Recu.dc.html` | `/sales/[id]/receipt` | 3a |
| 05b | Reçu, facture A4 | `05b-recu-facture-a4` | idem | idem | 3a |
| 06 | Retour d'articles | `06-retour-articles` | `Retour.dc.html` | `/sales/[id]/returns/new` | 3a |
| 07 | Liste des articles (Stock) | `07-liste-articles` | `Articles.dc.html` | `/products` (fusionne `/inventory`) | 3b |
| 08 | Fiche article et étiquette | `08-fiche-article` | `ArticleFiche.dc.html` | `/products/[id]` | 3b |
| 09 | Nouvel article | `09-nouvel-article` | `Produit.dc.html` | `/products/new` | 3b |
| 10 | Corriger le stock | `10-corriger-stock` | `Stock.dc.html` | `/inventory/adjust` (nouvelle) | 3b |
| 11 | Recevoir une livraison | `11-recevoir-livraison` | `Livraison.dc.html` | `/inventory/receive` (nouvelle) | 3b |
| 12 | Rayons | `12-rayons` | `Rayons.dc.html` | `/products/categories` | 3b |
| 13 | Clients et fournisseurs | `13-clients-fournisseurs` | `Clients.dc.html` | `/customers` et `/suppliers` | 3c |
| 14 | Fiche client | `14-fiche-client` | `ClientFiche.dc.html` | `/customers/[id]` | 3c |
| 14b | … rappel WhatsApp | `14b-fiche-client-rappel` | idem | idem | 3c |
| 15 | Ajouter une personne | `15-ajouter-personne` | `Contact.dc.html` | `/customers/new`, `/suppliers/new` | 3c |
| 16 | Fiche fournisseur | `16-fiche-fournisseur` | `FournisseurFiche.dc.html` | `/suppliers/[id]` | 3c |
| 17 | L'argent | `17-argent` | `Finance.dc.html` | `/finance` | 3d |
| 17b | … journée en perte | `17b-argent-journee-en-perte` | idem | idem | 3d |
| 18 | Encaisser une dette | `18-encaisser-dette` | `Reglement.dc.html` | `/finance/collect` (nouvelle) | 3d |
| 18b | … montant libre | `18b-encaisser-dette-montant-libre` | idem | idem | 3d |
| 19 | Payer un fournisseur | `19-payer-fournisseur` | `PayerFournisseur.dc.html` | `/finance/pay` (nouvelle) | 3d |
| 20 | Dépenses | `20-depenses` | `Depenses.dc.html` | `/finance/expenses` | 3d |
| 21 | Entrées et sorties de caisse | `21-entrees-sorties` | `Caisse.dc.html` | `/finance/cash` (nouvelle) | 3d |
| 21b | … annulation d'une ligne | `21b-entrees-sorties-annulation` | idem | idem | 3d |
| 22 | Conseils | `22-conseils` | `Conseils.dc.html` | `/insights` (fusionne `/analytics`) | 3e |
| 22b | … meilleurs articles | `22b-meilleurs-articles` | idem | idem | 3e |
| 22c | … prévisions | `22c-previsions` | idem | idem | 3e |
| 23 | Alertes | `23-alertes` | `Alertes.dc.html` | `/notifications` | 3e |
| 24 | Réglages : ma boutique | `24-reglages-boutique` | `Reglages.dc.html` | `/settings` | 3e |
| 24b | … personnes | `24b-reglages-personnes` | idem | idem | 3e |
| 24c | … qui peut faire quoi | `24c-reglages-droits` | idem | idem | 3e |
| 24d | … historique | `24d-reglages-historique` | idem | idem | 3e |
| 24e | … fichiers Excel | `24e-reglages-fichiers-excel` | idem | idem | 3e |
| 25 | Connexion | `25-connexion` | `Connexion.dc.html` | `/login` | 3e |
| 26 | Sur téléphone (390 px) | `26-telephone` | `Telephone.dc.html` | toutes, en dessous de 768 px | 3a, puis chaque lot |

Les routes « (nouvelle) » sont des propositions ; l'agent peut en choisir d'autres s'il les note dans `ecarts.md`.
