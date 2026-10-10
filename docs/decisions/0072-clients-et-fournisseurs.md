# 0072 — Clients et fournisseurs de la maquette v2 (lot 3c)

- **Date** : 2026-10-10
- **Phase** : 15 (lot 3c)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-10)

## Contexte
Le lot 3c reproduit les écrans 13 à 16 de la maquette v2 : la liste des clients et des
fournisseurs, la fiche client avec son rappel WhatsApp, « Ajouter une personne », la fiche
fournisseur. La maquette montre des choses que l'API ne donnait pas : ce que doit chaque
personne et depuis quand, sa dernière visite ou livraison, ses achats du mois, les articles
d'un achat ou d'une livraison, les paiements d'une personne, l'adresse d'un fournisseur. Elle
appelle aussi deux écrans du lot 3d (encaisser, payer).

## Options envisagées et décisions
- **Adresse d'un fournisseur** : colonne facultative `suppliers.address` (révision 0018,
  200 caractères au plus), saisie dans « Modifier » seulement — la création reste le nom et
  le téléphone (retenue) ; plutôt qu'aucune adresse et un écart.
- **« Ajouter une personne » en page** pour créer et modifier (`/customers/new`,
  `/suppliers/new`, `/…/[id]/edit`), avec l'écran de succès de la maquette (retenue) ; la
  fenêtre ne reste que dans la vente et la livraison, où quitter l'écran perdrait le travail
  en cours. Un même composant `PersonForm` sert les deux.
- **Liens provisoires** : « Encaisser sa dette » et « Le payer » ouvrent la fenêtre de
  règlement actuelle de L'argent, déjà répartie sur les dettes de la personne, jusqu'au lot
  3d (retenue) ; plutôt que de faire les écrans 18 et 19 ici ou de cacher les boutons.
- **Plafond de crédit** : jamais affiché sur la fiche, comme la maquette (choix du
  propriétaire). Un plafond posé avant le lot 1 continue de s'appliquer à la vente.
- **Lectures composées par Analytics** (bande de restitution, ADR 0030), huit routes en
  lecture seule :
  `GET /analytics/customers` et `/analytics/suppliers` (liste : qui doit d'abord, le plus gros
  montant, puis la dernière visite ou livraison la plus récente, puis le nom ; résumé et
  compteurs du sélecteur), `/analytics/customers/{id}` (tuiles), `…/sales` (achats avec
  leurs trois premiers articles), `…/payments` (versements à la vente ou sur une dette),
  `/analytics/suppliers/{id}` (tuiles et articles livrés), `…/deliveries` (chaque dette
  fournisseur et ses plus grosses lignes), `…/payments`. La liste se classe en mémoire :
  une boutique compte quelques centaines de personnes (plafond de 5 000 lues par requête).
- **Argent dû** : sans `debts:read` (le vendeur), aucun montant dû ne sort — `owed`,
  `owed_total`, `owing_count` et le montant du mois d'un fournisseur valent `null` ; le
  filtre « Qui me doivent » et les livraisons d'un fournisseur répondent 403. Le vendeur
  voit les personnes, leurs visites et leurs achats.
- **Recherche par téléphone** : la recherche des clients et des fournisseurs trouve aussi
  les chiffres du téléphone, espaces ignorés, dès 4 chiffres (« 77 655 », « 655 90 »,
  « +221 77 655 90 21 »).
- **Mots neutres** : le logiciel ne connaît pas le genre d'une personne. « Reste à payer »,
  « Lui vendre », « Dernier achat samedi », « Ses articles » remplacent « Il vous doit »,
  « Nouvelle vente pour lui », « Venu samedi », « Il vous livre » (écarts notés).
- **Une livraison écrit ses lignes dans le même instant** : leur ordre de saisie n'est pas
  gardé ; les lignes se classent par valeur (la plus grosse d'abord).
- **Rappel WhatsApp** : un message prêt et modifiable — prénom du client, prénom de
  l'utilisateur, nom de la boutique, montant, numéro Wave de la boutique s'il est enregistré
  (révision 0016) — puis `wa.me` vers le numéro du client.
- **Prérempli** : « Lui vendre » ouvre `/sales/new?customer=…` (le client se pose sur le
  brouillon du jour repris, ou sur le nouveau) ; « Recevoir une livraison » ouvre
  `/inventory/receive?supplier=…`.

## Conséquences
- Tests : `tests/integration/test_lot_3c_people.py` (adresse, téléphone, ordre et résumé de
  la liste, tuiles, achats, paiements à la vente et sur une dette, livraisons et articles,
  vendeur sans montant, 404), fuites entre entreprises sur les six routes à identifiant et
  sur les listes ; Vitest (liste, vendeur, rappel avec ou sans Wave, mots) ; e2e (ajout en
  page, recherche par téléphone, fiche, rappel, encaissement, « Lui vendre », modification,
  fournisseur avec livraison et adresse), cibles tactiles et accessibilité.
- La fiche fournisseur ne montre plus les dépenses rattachées au fournisseur : elles restent
  dans L'argent (écran 20 au lot 3d).
- Écarts à la maquette dans `docs/design/maquette-v2/ecarts.md`.
