# Prompt 44 — Payer 6 mois d'un coup (sans remise)

> Petite extension des lots B et C (ADR 0132, 0133). Audit sur `main` au commit `a441ed4` (lot C fusionné, PR #109). Demande du propriétaire, 27 novembre 2026 : à faire **avant** le déploiement des lots B et C, pour tout mettre en ligne ensemble.
>
> **Décision du propriétaire :** en plus d'un mois et d'un an (-10 %), une boutique peut payer **6 mois d'un coup, sans remise** : **29 400 FCFA** pour Pro (6 × 4 900), **59 400 FCFA** pour Business (6 × 9 900). Premium reste sur devis (montant libre).

Branche `feat/paiement-six-mois`, depuis `main` à jour.

```
Lot « Paiement de 6 mois » (branche feat/paiement-six-mois, depuis main à jour). Règles
habituelles : ADR au prochain numéro libre (0134 au moment de l'audit), tests d'abord
(rouge puis vert), aucun service payant, ne jamais ouvrir ni commiter .env. Résumé en
français à la fin, questions ouvertes par AskUserQuestion. Lis d'abord les ADR 0091,
0132 (offres, prix annuels, offres.json, period_months) et 0133 (calendrier des relances,
point de départ d'une période payée). Migration rétrocompatible (ADR 0083 : ajouts et
élargissement seulement).

Constat (à vérifier) : subscription_payments.period_months a un CHECK (1, 12) (révision
0043) ; plans.annual_price_fcfa porte le prix annuel ; PeriodMonths dans
platform/schemas.py ; frontend/content/offres.json est la source unique des prix (vitrine
et « Mon abonnement »), comparée à la base par tests/integration/test_plan_features.py.

S1. Données et règles
- Migration : CHECK de period_months élargi à (1, 6, 12) ; nouvelle colonne
  plans.semiannual_price_fcfa (numeric(14,2), NULL = pas de paiement par 6 mois) :
  29 400 pour Pro, 59 400 pour Business, NULL pour Premium. Comme le prix annuel, le
  montant est écrit en base et jamais recalculé à l'affichage ; un test vérifie qu'il vaut
  exactement 6 x price_fcfa (aucune remise).
- POST /api/v1/platform/companies/{id}/payments : period_months accepte 6 ; le montant doit
  être égal à semiannual_price_fcfa (422 sinon, avec le montant attendu, comme pour 1 et
  12). Premium : montant libre, comme aujourd'hui.
- La période avance de 6 mois calendaires, avec les mêmes règles de départ que l'ADR 0133
  (renouvellement pendant la grâce : depuis l'ancienne date de fin ; fin d'essai ou
  boutique en pause : depuis le jour du paiement). Fins de mois gérées comme pour 1 et 12
  (31 août + 6 mois = 28 ou 29 février) : réutilise la fonction existante, ne la duplique
  pas.
- Le calendrier des relances (ADR 0133) ne change pas : il ne regarde que la date de fin.
- offres.json gagne « semiannual » pour chaque offre (null pour Premium) ; le test de
  comparaison avec la base le couvre.

S2. Administration (frontend-admin/)
- « Enregistrer un paiement » propose trois durées : « 1 mois », « 6 mois », « 1 an
  (-10 %) », avec le montant prérempli et la nouvelle date de fin affichée avant de valider.
- L'historique des paiements de la fiche entreprise affiche la durée payée.
- Statistiques : si elles comptent des revenus, un paiement de 6 mois compte pour 6 mois.

S3. Boutique (frontend/)
- « Mon abonnement », partie « Comment payer » : les trois durées avec leur montant
  (« 1 mois : 4 900 F », « 6 mois : 29 400 F », « 1 an : 52 920 F, soit 10 % de moins »),
  et le message WhatsApp prérempli qui reprend la durée choisie.
- Page d'accueil, section « Nos offres » : [DEMANDER] Recommandation : garder la bascule
  « Par mois / Par an (-10 %) » telle quelle, et ajouter sous les cartes une seule ligne :
  « Paiement possible par mois, par 6 mois ou par an. » (6 mois = 6 fois le prix mensuel,
  inutile d'en faire une troisième position de bascule). Autre option : une bascule à
  trois positions. Les gardes de vitrine-texte.test.ts restent vraies (prix seulement
  depuis offres.json).
- Textes : jamais « échéance » (test de vocabulaire de l'application).

S4. Tests (rouge d'abord)
- Migration : CHECK élargi, semiannual = 6 x prix pour Pro et Business, NULL pour Premium.
- Paiement de 6 mois : bon montant accepté, mauvais montant refusé avec le montant attendu,
  période +6 mois (y compris fin de mois), idempotence, renouvellement pendant la grâce
  depuis l'ancienne date de fin, réactivation d'une boutique en pause, relances qui
  repartent de zéro pour la nouvelle date de fin.
- Front : trois durées dans « Comment payer » et dans l'administration ; ligne de la
  vitrine ; axe 0 violation, 360 px.
- Suite inter-tenant complète verte.

Fin de lot
Suite backend complète, ruff, mypy, make front-check, admin-check, e2e des écrans touchés,
CI verte. ADR (6 mois sans remise, colonne semiannual_price_fcfa), amendements des ADR
0132 et 0133, openapi.json et types du front, runbook offres-et-abonnements.md (« enregistrer
un paiement de 6 mois »), CLAUDE.md §8 et table des ADR.

Hors lot : paiement en ligne Bictorys (lot D), qui devra proposer les trois durées.
```

## Ce que le propriétaire fait lui-même

1. **Répondre à la question de la page d'accueil** : une simple ligne (recommandé) ou une bascule à trois positions.
2. **CGU** : mentionner le paiement par 6 mois (sans remise) avec les autres durées, dans la nouvelle version des conditions.
3. **Ordre de mise en ligne** : fusionner ce lot, puis déployer `main` (lots B, C et 6 mois ensemble), après avoir réglé les abonnements dont la date de fin est déjà passée (voir le lot C).
4. **Après le déploiement** : dans l'administration, enregistrer un paiement de 6 mois sur une boutique de test et vérifier le montant prérempli (29 400 F pour Pro) et la nouvelle date de fin.
