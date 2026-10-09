# 0070 — Refonte visuelle de la maquette v2 : système, navigation et Vendre (lot 3a)

- **Date** : 2026-10-09
- **Phase** : 15 (lot 3a)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-09)

## Contexte
Le lot 3 du prompt de phase 15 reproduit la maquette v2 à la lettre. Le lot 3a couvre le
système, la navigation et les écrans de vente (maquette 01 à 06, 26 pour le téléphone).
Plusieurs éléments de la maquette n'avaient pas d'appui dans le modèle ou l'API :
coordonnées de la boutique sur le reçu, « Dans la caisse », carte « À surveiller », filtres
d'état de la liste, totaux par jour, nom du vendeur. D'autres demandaient un choix : place
de la déconnexion et du thème, pages pas encore fusionnées, bouton PDF, numéro de facture,
brouillons, référence du téléphone.

## Options envisagées et décisions
- **Coordonnées de la boutique** : six colonnes facultatives sur `companies` (révision
  0016 : adresse, téléphone, numéro Wave, NINEA, RC, message de bas de reçu), réglées par
  `PATCH /companies/me` sous audit critique, imprimées sur le reçu (retenue) ; plutôt que des
  clés dans `settings` ou un reçu sans ces lignes jusqu'au lot 3e.
- **« Dans la caisse »** : tout ce qui est entré moins tout ce qui est sorti depuis le
  début, paiements vivants, compensations exclues (retenue) ; plutôt que la différence ou les
  entrées du jour. Aucun fond de caisse de départ en V1.
- **Barre du haut** : l'engrenage ouvre un menu (personne et rôle, Réglages, Mode sombre,
  Se déconnecter) ; le réglage de densité disparaît (retenue).
- **Pages pas encore refaites** : liens provisoires — Stock s'allume sur `/inventory`,
  Clients sur `/suppliers`, Conseils sur `/analytics` — jusqu'aux lots 3b, 3c et 3e.
- **Reçu** : ni bouton PDF ni case « Voir une vente annulée » ; le tampon suit l'état réel.
  Le numéro de facture se tire du numéro de vente (V-001044 → F-1044), sans compteur.
- **« Stock à surveiller »** compte les épuisés avec les articles sous le seuil.
- **Téléphone** : l'écran 26 fait foi sous 768 px ; les captures « -390 » des autres écrans
  sont indicatives.
- **Brouillons** : absents de la liste ; « Nouvelle vente » reprend le brouillon du jour de
  la même personne (retenue) ; plutôt que les oublier ou les montrer.

## Décision
- **Serveur** (tous les champs sont additifs) : `seller_name` sur la fiche et le reçu,
  téléphone du client sur le reçu ; tableau de bord avec `cash_on_hand`,
  `receivables_customer_count`, `watch_stock` (épuisés d'abord, puis le plus bas rapporté à
  son seuil), `watch_debt` (plus gros encours, jours depuis la plus ancienne dette ouverte)
  et l'état de paiement des dernières ventes ; `GET /sales` gagne `state` (payées, pas
  encore payées, avec retour, annulées), une recherche par nom de client ou par numéro tapé
  sans préfixe, `item_count`, `include_drafts` et `mine` ; `GET /sales/day-totals` (mêmes
  filtres, nombre de ventes, ventes encaissées, total encaissé) ; `critical` dans le
  compteur d'alertes.
- **Front** : coquille de la maquette (cinq onglets, Conseils, cloche, engrenage, barre
  basse), cibles de 48 px (seuil de l'ADR 0059 remonté), écrans 01 à 06 et 26, bon de retour
  sur le gabarit du ticket. Le brouillon reste synchronisé avec le serveur (ADR 0052) ; le
  retour et son règlement partent en deux écritures sous deux clés d'idempotence.
- **Comparaison** : écrans 01 à 06 et 26 bloquants dans `make maquette-check` ; les écarts
  de données du seed sont cités mot pour mot dans `ecarts.md`.

## Conséquences
- Tests : `test_lot_3a_reads.py`, tests de fuite sur la recherche par nom et les totaux par
  jour, compteur d'alertes graves ; Vitest (dates, pastille, montant en lettres, valeur
  rendue, WhatsApp, navigation par rôle, cloche) ; e2e (parcours de vente, test du
  commerçant : vente comptant de 3 articles en 6 touches, vente à crédit en 6 touches, sans
  frappe).
- Les captures des phases 12 et 13 ne tournent plus que sur demande (`CAPTURES_PHASE`).
- La coquille n'a plus de fil d'Ariane ; les pages des lots 3b à 3e gardent leur mise en page
  sous la nouvelle barre jusqu'à leur lot.
- Le seed `maquette` remplit les coordonnées de la boutique et marque son outbox publiée :
  il construit lui-même les faits, et la comparaison tourne sans relais.
