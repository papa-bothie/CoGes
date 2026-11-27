# Offres et abonnements : changer l'offre, encaisser un an, droits acquis

Pour l'équipe CoGes (profil **administrateur** de l'administration de la plateforme).
Référence : ADR 0091 (abonnements), ADR 0132 (offres Pro et Business, droits acquis).

## Les offres

| Offre | Code | Par mois | Par an (-10 %) | Comptes | En vente |
|---|---|---|---|---|---|
| Pro | `starter` | 4 900 F | 52 920 F | 3 | oui |
| Business | `business` | 9 900 F | 106 920 F | 7 | oui |
| Premium | `premium` | sur devis | sur devis | 10 | non (administrateur seulement) |

Toute nouvelle boutique commence par **30 jours d'essai gratuit sur Pro**. L'import Excel/CSV
est réservé à Business (et Premium), sauf droit acquis. Les codes ne changent jamais : la
licence sur site les emploie (`activate-license --plan starter|business|premium`).

Les prix sont écrits à deux endroits **qui doivent rester égaux** : la table `plans` (révision
0043) et `frontend/content/offres.json` (vitrine, « Mon abonnement »). Un test les compare ;
changer un prix = une révision **et** ce fichier, dans la même PR.

## Changer l'offre d'une boutique

1. Administration → Entreprises → la boutique → carte **Abonnement**.
2. **Changer d'offre** : choisir l'offre (Premium apparaît « sur devis »), écrire la raison
   (« Le client passe à Business, message WhatsApp du 26/11 »), valider.
3. Refus « Désactivez-en N avant de changer d'offre » : la boutique a plus de comptes actifs
   que la nouvelle offre (ou son plafond acquis) n'en permet. Le gérant désactive des comptes
   d'abord, ou on accorde un plafond acquis (ci-dessous).

Changer d'offre ne touche ni la fin de période payée ni l'accès.

## Enregistrer un paiement d'un mois ou d'un an

1. Carte **Abonnement** → **Enregistrer un paiement**.
2. **Durée** : « 1 mois » ou « 1 an (-10 %) ». Le montant se remplit avec le prix de l'offre ;
   il doit être **exactement** celui-là (sinon : « Le montant attendu est de 52 920 FCFA. »).
   Premium : montant du devis, libre.
3. Date, moyen (Wave, Orange Money, espèces, virement), note (référence de la transaction).
4. La fin de période avance de 1 ou 12 mois. Un **renouvellement** (période en cours ou dans ses
   3 jours de grâce) part de l'ancienne fin ; une fin d'essai ou une boutique en pause part
   d'aujourd'hui (ADR 0133). Une boutique suspendue retrouve l'accès. Relances et pauses :
   `relances-et-suspensions.md`.

Un double clic ne paie pas deux fois (clé d'idempotence). Pour changer d'offre **et** encaisser,
changer l'offre d'abord : le montant attendu est celui de l'offre au moment du paiement.

## Accorder ou retirer un droit acquis

Un droit acquis est donné **en plus** de l'offre : l'import pour une boutique sur Pro, ou un
plafond de comptes plus haut. Les boutiques d'avant les offres (migration 0043) ont reçu
l'import et, au-delà de 3 comptes, leur nombre de comptes de ce jour-là.

1. Carte **Abonnement** → **Droits acquis**.
2. Cocher ou décocher les droits (« Import Excel ou CSV », « Support prioritaire » ; les
   fonctions des lots E et F n'ont encore aucun effet).
3. **Plafond de comptes acquis** : un nombre, ou vide pour revenir au plafond de l'offre.
4. **Raison** obligatoire (elle va au journal), puis **Enregistrer les droits acquis**.

Retirer un plafond (ou le baisser) sous le nombre de comptes actifs est refusé avec le nombre à
désactiver. Le gérant voit ses droits acquis dans **Réglages → Mon abonnement** (« Import inclus
pour votre boutique »). Le changement prend effet à la requête suivante.

## Vérifier

- Journal (Administration → Journal) : « … a changé les droits acquis de … », « … a enregistré
  un paiement de 52 920 FCFA (Wave) pour 1 an pour … ».
- Côté boutique : `GET /api/v1/auth/me` → `plan.features` ; un import refusé répond 403
  `plan_feature_required`.
