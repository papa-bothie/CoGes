# Comparaison du front à la maquette v2

Écrit par `frontend/e2e/maquette.spec.ts` (`make maquette-check`). Pourcentage de pixels
différents à 1280 et à 390 px ; seuil 2 %. Textes manquants : textes visibles de
`html/NN-nom.html` absents de la page (aucun toléré sur un écran livré ; « — » : état sans
page HTML). Images : maquette | front | différences.

| N° | Écran | Lot | 1280 px | 390 px | Textes manquants | Images |
|---|---|---|---|---|---|---|
| 01 | Accueil | 3a | 3.0 % | 9.1 % | 0 | [1280](comparaison/01-accueil.png) [390](comparaison/01-accueil-390.png) |
| 02 | Nouvelle vente | 3a | 10.9 % | 15.7 % | 0 | [1280](comparaison/02-nouvelle-vente.png) [390](comparaison/02-nouvelle-vente-390.png) |
| 02b | paiement d'une partie (montant tapé + pavé) | 3a | 9.3 % | 15.2 % | — | [1280](comparaison/02b-nouvelle-vente-une-partie.png) [390](comparaison/02b-nouvelle-vente-une-partie-390.png) |
| 02c | rendu de monnaie | 3a | 10.5 % | 15.7 % | — | [1280](comparaison/02c-nouvelle-vente-rendu-monnaie.png) [390](comparaison/02c-nouvelle-vente-rendu-monnaie-390.png) |
| 02d | écran de succès | 3a | 2.9 % | 16.2 % | — | [1280](comparaison/02d-nouvelle-vente-succes.png) [390](comparaison/02d-nouvelle-vente-succes-390.png) |
| 03 | Liste des ventes | 3a | 1.9 % | 5.8 % | 0 | [1280](comparaison/03-liste-des-ventes.png) [390](comparaison/03-liste-des-ventes-390.png) |
| 04 | Détail d'une vente | 3a | 4.4 % | 8.6 % | 0 | [1280](comparaison/04-detail-vente.png) [390](comparaison/04-detail-vente-390.png) |
| 04b | annulation (raison) | 3a | 4.4 % | 14.1 % | — | [1280](comparaison/04b-detail-vente-annulation.png) [390](comparaison/04b-detail-vente-annulation-390.png) |
| 05 | Reçu, petit ticket 80 mm | 3a | 5.1 % | 16.5 % | 0 | [1280](comparaison/05-recu-ticket.png) [390](comparaison/05-recu-ticket-390.png) |
| 05b | Reçu, facture A4 | 3a | 4.0 % | 13.8 % | — | [1280](comparaison/05b-recu-facture-a4.png) [390](comparaison/05b-recu-facture-a4-390.png) |
| 06 | Retour d'articles | 3a | 3.2 % | 12.1 % | 0 | [1280](comparaison/06-retour-articles.png) [390](comparaison/06-retour-articles-390.png) |
| 07 | Liste des articles (Stock) | 3b | 4.1 % | 12.4 % | 0 | [1280](comparaison/07-liste-articles.png) [390](comparaison/07-liste-articles-390.png) |
| 08 | Fiche article et étiquette | 3b | 5.4 % | 12.4 % | 0 | [1280](comparaison/08-fiche-article.png) [390](comparaison/08-fiche-article-390.png) |
| 09 | Nouvel article | 3b | 8.0 % | 11.7 % | 0 | [1280](comparaison/09-nouvel-article.png) [390](comparaison/09-nouvel-article-390.png) |
| 10 | Corriger le stock | 3b | 6.2 % | 16.9 % | 0 | [1280](comparaison/10-corriger-stock.png) [390](comparaison/10-corriger-stock-390.png) |
| 11 | Recevoir une livraison | 3b | 5.6 % | 10.6 % | 0 | [1280](comparaison/11-recevoir-livraison.png) [390](comparaison/11-recevoir-livraison-390.png) |
| 12 | Rayons | 3b | 2.7 % | 15.4 % | 0 | [1280](comparaison/12-rayons.png) [390](comparaison/12-rayons-390.png) |
| 13 | Clients et fournisseurs | 3c | 4.8 % | 11.4 % | 0 | [1280](comparaison/13-clients-fournisseurs.png) [390](comparaison/13-clients-fournisseurs-390.png) |
| 14 | Fiche client | 3c | 3.9 % | 12.2 % | 0 | [1280](comparaison/14-fiche-client.png) [390](comparaison/14-fiche-client-390.png) |
| 14b | rappel WhatsApp | 3c | 5.2 % | 14.6 % | — | [1280](comparaison/14b-fiche-client-rappel.png) [390](comparaison/14b-fiche-client-rappel-390.png) |
| 15 | Ajouter une personne | 3c | 2.5 % | 18.2 % | 0 | [1280](comparaison/15-ajouter-personne.png) [390](comparaison/15-ajouter-personne-390.png) |
| 16 | Fiche fournisseur | 3c | 3.7 % | 14.2 % | 0 | [1280](comparaison/16-fiche-fournisseur.png) [390](comparaison/16-fiche-fournisseur-390.png) |
| 17 | L'argent | 3d | 14.2 % | 18.8 % | 0 | [1280](comparaison/17-argent.png) [390](comparaison/17-argent-390.png) |
| 17b | journée en perte | 3d | 5.8 % | 23.3 % | — | [1280](comparaison/17b-argent-journee-en-perte.png) [390](comparaison/17b-argent-journee-en-perte-390.png) |
| 18 | Encaisser une dette | 3d | 5.8 % | 14.3 % | 0 | [1280](comparaison/18-encaisser-dette.png) [390](comparaison/18-encaisser-dette-390.png) |
| 18b | montant libre | 3d | 5.8 % | 14.5 % | — | [1280](comparaison/18b-encaisser-dette-montant-libre.png) [390](comparaison/18b-encaisser-dette-montant-libre-390.png) |
| 19 | Payer un fournisseur | 3d | 5.0 % | 16.2 % | 0 | [1280](comparaison/19-payer-fournisseur.png) [390](comparaison/19-payer-fournisseur-390.png) |
| 20 | Dépenses | 3d | 8.8 % | 12.4 % | 0 | [1280](comparaison/20-depenses.png) [390](comparaison/20-depenses-390.png) |
| 21 | Entrées et sorties de caisse | 3d | 2.8 % | 9.2 % | 0 | [1280](comparaison/21-entrees-sorties.png) [390](comparaison/21-entrees-sorties-390.png) |
| 21b | annulation d'une ligne | 3d | 2.9 % | 9.4 % | — | [1280](comparaison/21b-entrees-sorties-annulation.png) [390](comparaison/21b-entrees-sorties-annulation-390.png) |
| 22 | Conseils (à faire) | 3e | 8.4 % | 12.9 % | — | [1280](comparaison/22-conseils.png) [390](comparaison/22-conseils-390.png) |
| 22b | meilleurs articles (à faire) | 3e | 12.2 % | 12.1 % | — | [1280](comparaison/22b-meilleurs-articles.png) [390](comparaison/22b-meilleurs-articles-390.png) |
| 22c | prévisions (à faire) | 3e | 9.9 % | 11.7 % | — | [1280](comparaison/22c-previsions.png) [390](comparaison/22c-previsions-390.png) |
| 23 | Alertes (à faire) | 3e | 4.6 % | 8.6 % | — | [1280](comparaison/23-alertes.png) [390](comparaison/23-alertes-390.png) |
| 24 | Réglages : ma boutique (à faire) | 3e | 7.1 % | 8.5 % | — | [1280](comparaison/24-reglages-boutique.png) [390](comparaison/24-reglages-boutique-390.png) |
| 24b | personnes (à faire) | 3e | 9.2 % | 11.9 % | — | [1280](comparaison/24b-reglages-personnes.png) [390](comparaison/24b-reglages-personnes-390.png) |
| 24c | qui peut faire quoi (à faire) | 3e | 10.4 % | 10.1 % | — | [1280](comparaison/24c-reglages-droits.png) [390](comparaison/24c-reglages-droits-390.png) |
| 24d | historique (à faire) | 3e | 8.8 % | 10.7 % | — | [1280](comparaison/24d-reglages-historique.png) [390](comparaison/24d-reglages-historique-390.png) |
| 24e | fichiers Excel (à faire) | 3e | 11.0 % | 14.9 % | — | [1280](comparaison/24e-reglages-fichiers-excel.png) [390](comparaison/24e-reglages-fichiers-excel-390.png) |
| 25 | Connexion (à faire) | 3e | 7.0 % | 13.6 % | — | [1280](comparaison/25-connexion.png) [390](comparaison/25-connexion-390.png) |
| 26 | Sur téléphone (390 px) | 3a, puis chaque lot | — | 5.4 % | 0 | [390](comparaison/26-telephone-390.png) |
