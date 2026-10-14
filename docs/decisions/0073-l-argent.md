# 0073 — L'argent de la maquette v2 (lot 3d)

- **Date** : 2026-10-14
- **Phase** : 15 (lot 3d)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-14)

## Contexte
Le lot 3d reproduit les écrans 17 à 21 de la maquette v2 :
- L'argent, avec une journée en perte ;
- encaisser une dette, avec un montant libre ;
- payer un fournisseur ;
- les dépenses ;
- les entrées et sorties de caisse, avec leur annulation.

Il remplace la page `/finance` à quatre onglets (vue d'ensemble, paiements, dettes, dépenses).
Il remplace aussi les liens provisoires « Encaisser sa dette » et « Le payer » du lot 3c (ADR 0072).

La maquette montre des choses que l'API ne donnait pas en une lecture :
- la caisse découpée par moment de la journée ou par semaine du mois ;
- la plus grosse dépense, qui explique une perte ;
- le net par moyen de paiement ;
- les lignes de caisse en mots (n° de vente, client, type de dépense) ;
- les dépenses du mois par type.

## Options envisagées et décisions

**Trois lectures composées par Analytics** (bande E, ADR 0030), en lecture seule :
- `GET /analytics/money?period=today|week|month`, ou `?from=&to=`.
  - Contenu : vendu, prix d'achat, dépenses, gagné, entré, sorti, les barres, la plus grosse dépense.
  - Ce que doivent les clients : les trois premiers.
  - Ce qu'on doit aux fournisseurs : par échéance.
  - Le jour en cours est lu en direct sur les ventes, comme l'accueil (ADR 0061).
- `GET /analytics/cash?day=`, pour l'écran 21 :
  - Lignes du jour, au plus 500, avec leurs noms.
  - Net par moyen de paiement.
  - Le paiement annulé et sa ligne inverse sont listés, jamais comptés.
  - Les compensations sont écartées (ADR 0024).
- `GET /analytics/expenses-summary`, pour l'écran 20 : le mois par type, et les cinq dernières dépenses avec leur moyen de paiement.

Les deux premières routes exigent `analytics:read`, la troisième `expenses:read`. Le vendeur
n'y a pas accès : la caisse nomme les dépenses, qu'il ne lit pas. Les cartes de ce qui est dû
valent `null` sans `debts:read`.

Encaisser, payer, dépenser et annuler passent par les routes d'écriture existantes, avec leur
clé d'idempotence et leur audit critique : `POST /payments` avec `allocations`, `POST /expenses`
avec `payment`, et `POST /payments/{id}/cancel`.

**Découpage du graphique** (retenu) :
- « Aujourd'hui » : Matin (avant 12 h), Midi (12 h – 14 h), Après-midi (14 h – 18 h), Soir (à partir de 18 h), à l'heure de la boutique.
- « Cette semaine » : les 7 derniers jours glissants.
- « Ce mois » : Semaine 1 (jours 1 à 7), Semaine 2 (8 à 14), Semaine 3 (15 à 21), Semaine 4 (du 22 à la fin du mois). Les quatre barres restent même vides.
- Option écartée : la semaine et le mois calendaires (du lundi au dimanche, de 4 à 6 barres).

**« Choisir des dates »** : un lien discret à côté des puces (retenu). Le graphique y est
découpé par jour jusqu'à 31 jours, par tranche de 7 jours au-delà.

**« Annuler » sur une ligne de caisse** = annulation du paiement par contre-écriture (ADR 0038).
- Retenu.
- Le motif est la raison choisie : « Erreur de montant », « Saisi deux fois » ou « Mauvais client ».
- Réservé au gérant et au comptable.
- Une vente ou une dépense concernée reste. Elle redevient « Reste X F », ou non payée.
- Options écartées :
  - cacher « Annuler » sur les ventes ;
  - annuler le document entier, ce qui mêlerait deux gestes.

**Fonctions absentes de la maquette** : liens secondaires (retenu).
- « Toutes les dettes » (`/finance/debts`) garde l'abandon de créance et la dette fournisseur saisie à la main.
- « Toutes les dépenses » (`/finance/expenses/all`) garde la liste par période.
- « Gérer les types de dépense » ouvre la fenêtre des catégories.
- La liste des paiements disparaît : l'écran 21 la remplace.
- Les anciennes adresses `/finance?tab=…` mènent à leur nouvelle page.

**Icônes des types de dépense** : déduites du nom côté front, « … » par défaut (retenu). Il n'y
a ni migration ni colonne d'icône.

**Écrans 18 et 19** : un seul composant. Le reste se fait ainsi :
- La liste de gauche réutilise `/analytics/customers|suppliers?owing=true` (ADR 0072). Elle est classée par plus vieille dette (clients) ou par échéance la plus proche (fournisseurs).
- Le versement couvre d'abord les dettes les plus anciennes.
- Une échéance à 7 jours ou moins s'affiche en orange.

## Conséquences
- Tests :
  - `tests/integration/test_lot_3d_money.py` : équation et perte, trois découpages, dates choisies, ce qui est dû, lignes en mots, ligne annulée et sa ligne inverse, autre jour, dépenses par type, vendeur refusé.
  - Fuite entre entreprises sur les trois lectures.
  - Vitest : écran 18, mots de l'argent, hauteur des barres, icônes.
  - e2e `money.spec.ts` : toute la dette en 4 touches ou moins, partie tapée, fournisseur payé, dépense ajoutée puis annulée dans la caisse, vendeur sans L'argent.
  - Cibles tactiles et axe sur les nouvelles pages.
- **Limite connue** : si l'on annule l'encaissement fait à la confirmation d'une vente, la vente affiche « Reste X F » mais aucune dette n'existe (ADR 0038). Elle n'apparaît donc pas dans « Encaisser une dette ». La seule issue aujourd'hui : annuler la vente (elle redevient annulable, ADR 0038), puis la ressaisir. À trancher avec le propriétaire si cela gêne.
- `formatDayMonth` écrit désormais « 1er octobre », comme `formatDayLong`.
- Les écarts à la maquette sont notés dans `docs/design/maquette-v2/ecarts.md`.
