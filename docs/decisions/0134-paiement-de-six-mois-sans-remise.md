# 0134 — Payer 6 mois d'un coup, sans remise

- **Date** : 2026-11-27
- **Phase** : prompt 44 (extension des lots B et C)
- **Statut** : acceptée ; amende 0132 et 0133
- **Décideur** : le propriétaire. La durée et le prix viennent de sa demande du 27/11/2026
  (`docs/prompts/44-paiement-six-mois.md`). La présentation sur la vitrine a été choisie par
  AskUserQuestion.

## Contexte

Le lot B (ADR 0132) vend Pro et Business au mois ou à l'année (-10 %). Le propriétaire ajoute
une troisième durée : **6 mois d'un coup, sans remise**. Cela fait 29 400 FCFA pour Pro
(6 × 4 900) et 59 400 FCFA pour Business (6 × 9 900). Premium reste sur devis, avec un montant
libre. La base n'acceptait que 1 ou 12 mois (`CHECK` de la révision 0043), comme le schéma de
l'API (`PeriodMonths`).

## Options envisagées

**Prix de 6 mois**
1. **Colonne `plans.semiannual_price_fcfa`, écrite par la migration (retenue).** Elle suit le
   même modèle que `annual_price_fcfa` : le montant est en base, jamais recalculé à
   l'affichage. Si un jour 6 mois portent une remise, une révision suffit.
2. Calculer 6 × `price_fcfa` dans le service. Il n'y aurait pas de colonne, mais la règle
   serait cachée dans le code, et `offres.json` ne pourrait plus être comparé à une valeur en
   base.

**Vitrine (question posée au propriétaire)**
1. **La bascule « Par mois / Par an (-10 %) » reste telle quelle, avec une ligne sous les
   cartes (retenue).** La ligne dit : « Paiement possible par mois, par 6 mois ou par an. ».
   6 mois valent 6 fois le mois : une troisième position n'apprendrait rien.
2. Une bascule à trois positions. Elle demande plus de CSS sans JavaScript, et une position
   qui ne montre qu'une multiplication.

**Retour arrière de la migration**
1. **Remettre l'ancien `CHECK (1, 12)` en `NOT VALID` (retenue).** Les paiements de 6 mois
   déjà enregistrés restent intacts, et la base n'en accepte plus de nouveaux. L'ancien code
   n'en écrit jamais.
2. Refuser le retour arrière dès qu'un paiement de 6 mois existe. C'est plus strict, mais un
   retour d'urgence deviendrait impossible, et la suite de tests, qui redescend les
   révisions, serait bloquée.

## Décision

- **Révision 0045** (ajout et élargissement seulement, ADR 0083) :
  - `plans.semiannual_price_fcfa numeric(14,2)`, positive ou nulle, qui exige un prix du mois
    (`plans_semiannual_needs_monthly`) ;
  - valeurs : 29 400 pour `starter`, 59 400 pour `business`, `NULL` pour `premium` ;
  - `subscription_payments.period_months` passe à `IN (1, 6, 12)` ;
  - aucun droit nouveau : `plans` est lue par `GRANT SELECT` sur toute la table.
- **API** : `PeriodMonths = Literal[1, 6, 12]`, et `PlanRead.semiannual_price_fcfa` est
  ajouté.
  - Pour 6 mois, le montant doit valoir exactement `semiannual_price_fcfa`. Sinon, la réponse
    est 422 `payment_amount_mismatch`, avec le montant attendu, comme pour 1 et 12.
  - Une offre à prix fixe sans prix de 6 mois répond 422 `semiannual_payment_unavailable`.
  - Premium : le montant est libre.
- **Période** : elle avance de 6 mois calendaires par `_add_months`, la fonction existante.
  Le jour qui n'existe pas est ramené au dernier jour du mois (31 août + 6 mois = 28 ou
  29 février). Le départ suit `_period_start` (ADR 0133) :
  - un renouvellement, pendant la période ou ses 3 jours de grâce, part de l'ancienne fin ;
  - une fin d'essai, une boutique en pause ou une fin oubliée depuis longtemps partent du jour
    du paiement.
- **Relances** : rien ne change, le calendrier ne regarde que la date de fin. La nouvelle fin
  ne correspond plus à `reminder_for_end`, donc le calendrier repart de zéro.
- **Statistiques** : le revenu reste l'argent déclaré (ADR 0093). 6 mois payés comptent
  29 400 F une fois, le jour du paiement, comme un an payé. Rien n'est étalé sur les mois.
- **`offres.json`** : chaque offre gagne `semiannual` (`null` pour Premium).
  `test_the_front_source_matches_the_database` le compare à la table.
- **Administration** (`subscription-card.tsx`, `lib/periods.ts`) :
  - les trois durées « 1 mois », « 6 mois », « 1 an (-10 %) », avec le montant prérempli ;
  - « Nouvelle fin : jj/mm/aaaa » affichée avant de valider, calculée comme le serveur. Le
    serveur reste l'autorité : la date du message de succès est la sienne ;
  - l'historique dit la durée, et le journal écrit « … pour 6 mois pour … ».
- **Boutique** : « Mon abonnement » → « Comment payer » propose trois choix : « 1 mois :
  4 900 F », « 6 mois : 29 400 F », « 1 an : 52 920 F, soit 10 % de moins ». Chacun a son
  bouton WhatsApp, et le message reprend la durée (« Je veux payer CoGes Pro pour 6 mois. »).

## Conséquences

- Tests :
  - `tests/integration/test_semiannual_payment.py` : prix = 6 × mois, `CHECK`, contrainte
    sur le prix du mois, montants bons et mauvais, Business, Premium libre, fins de mois,
    idempotence, grâce, pause, relances remises à zéro, 3 mois refusés, retour arrière qui
    garde l'historique ;
  - `test_platform_stats.py` (revenu compté une fois), `test_subscriptions_api.py` et
    `test_plan_features.py` (catalogue et source du front) ;
  - Vitest : `lib/periods.test.ts`, la carte, le journal, « Mon abonnement », la vitrine ;
  - e2e : abonnement dans l'administration, « Mon abonnement », « Nos offres », avec axe et
    360 px.
- Les CGU doivent citer le paiement par 6 mois (sans remise) : à faire par le propriétaire,
  dans la prochaine version des textes.
- Hors lot : le paiement en ligne (lot D) devra proposer les trois durées.
