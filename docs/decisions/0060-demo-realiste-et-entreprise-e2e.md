# 0060 — Démo réaliste, entreprise `e2e` à part, remplissage d'une entreprise existante

- **Date** : 2026-10-02
- **Phase** : après 14 (retouches)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

Les captures de la phase 14 montraient « Article E2E 017548ff », « Client E2E 83f5688b » : les
parcours Playwright écrivaient dans l'entreprise `demo` de `coges_e2e`, celle-là même que lisent
les captures et l'audit axe. Le jeu `app/seed.py` (20 produits, 50 ventes sur 60 jours) était
trop maigre pour montrer CoGes, et la préproduction (`demo-front`) était vide.

## Options envisagées

1. **Remplacer `seed-demo` par un jeu réaliste (retenue)** : un seul jeu, utilisé en local, en
   e2e, par le test de performance et pour la préproduction.
2. Une seconde commande à côté : deux jeux à entretenir, et des captures toujours maigres.

Pour la préproduction : **remplir `demo-front` (retenue)**, renommée « Alimentation Keur
Fatou », plutôt qu'une nouvelle entreprise. Pour les e2e : **une entreprise `e2e` à part
(retenue)**, plutôt que tout faire dans une entreprise de test (les captures montreraient de
nouveau des articles « E2E »).

Pour les dates : **accepter et documenter (retenue)**, plutôt que des règlements datés pour
étaler la trésorerie (partiel : le comptant de comptoir resterait daté du jour) ou un
remplissage quotidien pendant 90 jours.

## Décision

- `python -m app.seed` (`make seed-demo`) crée une épicerie de quartier à Dakar : 46 articles en
  6 rayons (prix FCFA, TVA 18 % hors première nécessité, articles au kilo ou au litre), 15
  clients nommés avec plafonds de crédit et profils de paiement, 5 fournisseurs avec délais,
  un vendeur en plus du gérant, **90 jours** de ventes (≈ 13 par jour, samedi fort, dimanche
  calme, début de mois plus actif), ventes à crédit avec acomptes, règlements étalés en un ou
  deux versements, retards, un abandon de créance, annulations, retours (en partie
  remboursés), réassorts suivant la demande avec factures fournisseurs payées à l'échéance,
  dépenses mensuelles payées. Fin de période pilotée : 2 ruptures, 5 articles sous le seuil.
  Graine fixe, tout par les façades de service, chaque contexte avec les permissions réelles
  de l'utilisateur.
- `--existing-slug X --manager-email … --password …` remplit une entreprise existante : elle est
  trouvée par une **connexion** (`auth_service.login`, donc le mot de passe du gérant, sans
  contourner la RLS), refusée si elle a déjà une vente ; les produits hors catalogue sont
  archivés (suppression logique auditée), le nom remplacé (`--rename`, vide = inchangé).
  `--days` et `--scale` règlent le volume.
- `make e2e-reset` crée la démo **et** une entreprise `e2e` vide. Les parcours qui écrivent s'y
  connectent (`E2E` dans `frontend/e2e/fixtures.ts`, valeur par défaut de `managerApi` et
  `createSalesperson`) ; captures, axe, classement par métrique, recommandations et cibles
  tactiles lisent `demo` sans y créer d'article.

## Conséquences

- **Dates** : seules les dates métier saisissables sont étalées (`sold_at`, `returned_at`,
  `spent_at`, `paid_at` des règlements après coup, stock d'ouverture — premier mouvement, libre
  de date d'après l'ADR 0015). Sorties de stock et encaissements de confirmation, réceptions et
  création des dettes restent datés du remplissage : la trésorerie jour par jour et l'historique
  de stock se concentrent sur ce jour-là. CA, marges, créances et Intelligence sont réalistes.
- Le test de performance mesure le tableau de bord sur ce volume (≈ 1 200 ventes) ; le
  remplissage dure ≈ 2 min 30 en local.
- Les captures des parcours d'écriture (phase 12) montrent l'entreprise `e2e`, celles de la
  phase 14 la démo.
- Aucun changement d'API, de schéma ni de règle métier.
