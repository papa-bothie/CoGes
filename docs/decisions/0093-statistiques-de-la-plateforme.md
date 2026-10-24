# 0093 — Statistiques de la plateforme (lot admin 5)

- **Date** : 2026-10-24
- **Phase** : lot admin 5 (`docs/prompts/26-admin-statistiques.md`)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

L'équipe CoGes doit voir où en est la plateforme : combien d'entreprises, dans quel
état, sur quelle offre, combien d'argent est réellement entré, et la tendance des
inscriptions. Tout existe déjà dans les tables des lots 1 et 3 (`companies`, `users`,
`subscriptions`, `subscription_payments`, `plans`) ; aucune table ni aucun droit nouveau.

## Options retenues (AskUserQuestion)

- **Répartition par offre : les essais à part.** Une ligne par offre, trois colonnes
  d'après l'**abonnement** : « en essai », « payantes » (`active` et `past_due`),
  « suspendues ». Tous les essais sont sur Premium : les compter avec les payantes ferait
  croire que Premium se vend.
- **Nouvelles entreprises : par mois, bascule par semaine.** 12 mois ou 52 semaines (le
  lundi), la dernière période est celle en cours, une période sans création vaut 0. Des
  barres en CSS, sans bibliothèque de graphiques ajoutée, et le tableau des valeurs
  exactes sous « Voir les chiffres » (le graphique est masqué aux lecteurs d'écran).
- **Accès : administrateur et support**, comme les autres lectures. Le support voit déjà
  chaque paiement sur la fiche d'une entreprise ; le total n'en dit pas plus.
- **Période du revenu : heure de Dakar, 366 jours au plus.** Mois calendaires en
  `Africa/Dakar` (à l'heure de Greenwich toute l'année), jours comptés en entier, bornes
  comprises ; une période personnalisée exige ses deux dates, dans l'ordre, jamais après
  aujourd'hui (422 `period_dates_required`, `period_inverted`, `period_too_long`,
  `period_in_future`).

## Décision

Trois lectures sous `/api/v1/platform/stats`, en `coges_app_platform` (module `platform/`) :

- `GET overview` : entreprises par statut d'accès et total, comptes commerçants actifs
  (`is_active`, non supprimés, dans une entreprise vivante), répartition par offre, et
  `without_subscription` (aucune attendue : l'essai naît avec l'entreprise). **Une seule
  requête SQL**, donc un seul instantané : statuts, total et offres se recoupent même si
  une entreprise naît pendant la lecture.
- `GET revenue?period=current_month|previous_month|custom&start=&end=` : **somme des
  paiements déclarés reçus** (`subscription_payments.paid_at` dans la période), et leur
  nombre. Jamais un revenu récurrent théorique tiré des offres en cours : un chiffre
  optimiste qui ne correspond à rien d'encaissé est exactement ce qu'on s'interdit. L'écran
  le dit lui-même : « Basé sur les paiements enregistrés, pas sur les offres en cours ».
  Les paiements d'une entreprise supprimée restent comptés : l'argent a été reçu.
- `GET signups?granularity=month|week`.

Les entreprises supprimées (`deleted_at`) sont exclues des comptes et de la tendance,
comme de la liste des entreprises. Chaque réponse porte `computed_at`, affiché à l'écran
(« Comptés le 24/10/2026 à 10:45 ») ; « maintenant » vient de `core/clock.py`.

## Conséquences

- Tests : `test_platform_stats.py` — le revenu ne bouge ni à la naissance d'un essai, ni
  au changement d'offre, ni à la suspension, et bouge exactement du montant d'un paiement ;
  bornes au jour près (23 h 59 min 59 s compte, minuit le lendemain non) ; invariant après
  chaque geste (création, paiement, changement d'offre, suspension, suppression) par
  `tests/helpers/platform_invariants.py` : statuts = total = offres + sans abonnement =
  décompte de la base elle-même (lu par `coges_auth`, hors des politiques de
  l'administration). Routes classées dans `READ_ROUTES`. Vitest et e2e de l'écran (axe).
- L'administration couvre désormais les cinq volets demandés : entreprises, abonnements,
  système, support, statistiques.
- Non fait : revenu par moyen de paiement ou par offre, taux de conversion des essais,
  export. À ajouter quand le besoin se présente, sur les mêmes tables.
