# Prompt 43 — Lot C : relances de fin d'essai et d'échéance, délai de grâce, suspension à J+3

> Troisième lot du plan `plan-offres-paiement-et-retouches.md`. Audit fait sur `main` au commit `812de68` (lots A et B fusionnés, ADR 0130 et 0132, révision 0043).
>
> **Décisions du propriétaire (23 novembre 2026), à ne pas rouvrir :** rappels **chaleureux** la veille de la fin (J-1), le jour J, puis un dernier rappel à J+2 qui annonce la suspension du lendemain ; **suspension automatique à J+3**. Le rappel de J-7 (et celui de J-3) disparaissent.

Branche `feat/relances-et-suspension`, depuis `main` à jour.

```
Lot « Relances et suspension » (branche feat/relances-et-suspension, depuis main à jour).
Règles habituelles : ADR au prochain numéro libre, tests d'abord (rouge puis vert), aucun
service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/.
Résumé en français à la fin, questions ouvertes par AskUserQuestion. Lis d'abord les ADR
0089 (companies.status, suspension), 0091 (abonnements, tâche platform.subscriptions_daily,
trial_notice), 0120 (notifications sur le téléphone), 0125 (licence sur site), 0132 (offres,
current_plan, « Mon abonnement »). Migration rétrocompatible (ADR 0083).

Constat (à vérifier) : backend/app/modules/platform/service.py, run_subscription_day :
WARNING_DAYS = (7, 3, 1) ; un essai échu passe en `suspended` LE JOUR MÊME ; aucun rappel
quand une PÉRIODE PAYÉE (current_period_end) arrive à échéance ; `past_due` n'est posé qu'à
la main. Tâche quotidienne à 06 h 30 UTC (beat.py), messages après COMMIT par
platform.trial_notice (cloche seulement pour un avertissement, e-mail au(x) gérant(s),
notification sur le téléphone), récapitulatif à l'équipe (trial_summary).

C1. Un seul calendrier pour l'essai ET pour une période payée
Soit E la date de fin (trial_ends_at pour un essai, current_period_end pour une période
payée), comptée en jours calendaires dans le fuseau de l'entreprise :
 - J-1 : rappel « veille » ;
 - J (jour de E) : rappel « jour J » ; l'abonnement passe en `past_due` (statut existant :
   l'ACCÈS reste ouvert, companies.status reste `trial`/`active` selon le cas) ;
 - J+2 : dernier rappel, qui annonce la suspension du lendemain ;
 - J+3 : suspension (abonnement et accès `suspended`, mécanisme existant, audit sans
   acteur). Jamais avant J+3, même si la tâche a manqué des jours.
 - Pas de J-7 ni de J-3. Une licence sur site (is_license, sans échéance) et Premium sans
   échéance ne reçoivent rien.
 - Idempotence : chaque étape (veille, jour J, dernier rappel, suspension) n'arrive qu'une
   fois par échéance. Remplace trial_warned_days par un état d'étape lié à l'échéance
   concernée (par exemple reminder_stage + reminder_for_end), pour qu'une nouvelle période
   payée reparte de zéro. Relancer la tâche le même jour ne refait rien.
 - Rattrapage : si la tâche n'a pas tourné un jour, elle envoie seulement l'étape due
   aujourd'hui (jamais deux rappels d'un coup) et ne suspend qu'à partir de J+3.
 - Entreprises en cours au déploiement : un essai déjà passé J-7 ou J-3 reçoit normalement
   la suite du nouveau calendrier ; une entreprise déjà suspendue reste suspendue.
 - Paiement pendant la grâce (J à J+2) : l'abonnement redevient `active`, les rappels
   s'arrêtent, rien n'est suspendu. Après la suspension : le paiement réactive (existant).
 - [DEMANDER] Point de départ de la période payée pendant la grâce. Recommandation : pour
   un RENOUVELLEMENT, la nouvelle période part de l'ancienne échéance (les jours de grâce
   ne sont pas offerts) ; pour une FIN D'ESSAI, elle part du jour du paiement.
   Aujourd'hui, record_payment prend la plus lointaine de « maintenant » et de l'échéance.

C2. Les messages, chaleureux et simples
Chaque étape passe par TOUS les canaux disponibles : cloche, notification sur le téléphone
(si activée), e-mail au(x) gérant(s) qui en ont un, bandeau dans l'application. Textes à
relire par le propriétaire (proposés, pas définitifs) :
 - Veille : « Votre essai gratuit de CoGes Pro se termine demain. Pour continuer sans
   interruption, choisissez votre offre. Nous sommes là si vous avez une question. »
 - Jour J : « Votre essai se termine aujourd'hui. Pas d'inquiétude : votre boutique reste
   ouverte encore 3 jours, le temps de choisir votre offre. »
 - J+2 : « Dernier rappel : sans paiement, votre boutique sera mise en pause demain. Vos
   données sont gardées, et tout revient dès le paiement. »
 - Versions « abonnement » pour une période payée (« Votre abonnement CoGes Pro arrive à
   échéance demain », etc.).
 - Suspension : e-mail « Votre boutique est en pause » (données conservées, comment la
   réactiver).
 Le bouton de chaque message mène à « Mon abonnement ».

C3. Bandeau dans l'application (indispensable sans e-mail)
 - De J-1 à J+2, un bandeau en haut de chaque écran pour le gérant (company:update) : le
   message de l'étape, le nombre de jours restants et « Choisir mon offre » (vers « Mon
   abonnement »). Ton chaleureux, orange à J+2, jamais rouge alarmant avant.
 - Pour les autres rôles, seulement à J+2 : « La boutique sera mise en pause demain.
   Prévenez votre gérant. »
 - Le bandeau vient de current_plan() (statut, échéance), sans nouvelle lecture des tables
   de la plateforme. Il ne cache jamais le panier ni le bouton d'encaissement (écran
   Vendre), et peut être replié pour la journée (préférence locale).
 - Boutique suspendue : la page de connexion (code company_suspended) montre un écran
   chaleureux « Votre boutique est en pause », les données conservées, et le bouton
   WhatsApp prérempli pour payer (le paiement en ligne viendra au lot D).

C4. Administration
 - Liste « À relancer » : entreprises entre J-1 et J+3, et suspendues depuis moins de
   7 jours, avec l'étape, l'échéance, le téléphone et un bouton « Écrire sur WhatsApp »
   (lien wa.me avec le message de l'étape, prérempli et modifiable, gratuit). Compteur sur
   le tableau de bord. Utile pour les commerçants sans e-mail.
 - Sur la fiche entreprise : l'étape en cours, et une action « Prolonger » (essai ou
   période de N jours, raison obligatoire, audit critique) qui remet le calendrier à zéro
   pour la nouvelle échéance.
 - Le récapitulatif quotidien à l'équipe liste les étapes du jour et les suspensions.

C5. Tests (rouge d'abord)
 - Calendrier : horloge déplacée jour par jour de E-2 à E+4, pour un essai et pour une
   période payée : exactement veille, jour J, dernier rappel, suspension à J+3 ; aucun
   message à E-7 ni E-3.
 - Idempotence (tâche relancée le même jour) ; rattrapage après des jours manqués ;
   entreprises déjà avancées au déploiement ; fuseau de l'entreprise.
 - Paiement à J+1 : actif, plus de rappel, pas de suspension ; paiement après J+3 :
   réactivation ; « Prolonger » : nouveau calendrier.
 - Licence sur site et Premium sans échéance : aucun message, jamais suspendus.
 - Canaux : cloche, téléphone, e-mail (gérants avec e-mail seulement), une fois par
   étape ; gérant sans e-mail = cloche et bandeau seulement, sans erreur.
 - Front : bandeau par étape et par rôle, jamais sur le panier, repliable ; écran « en
   pause » ; administration « À relancer » et « Prolonger ». axe 0 violation, 360 px.
 - Suite inter-tenant complète verte.

Fin de lot
Suite backend complète, ruff, mypy, make front-check, admin-check, e2e des écrans touchés,
tests de fuite inter-tenant, CI verte. ADR (calendrier, statut past_due pendant la grâce,
état d'étape, rattrapage, canaux), amendement des ADR 0091 et 0132, runbook « relances et
suspensions » en français simple (que faire quand un commerçant appelle à J+2, prolonger,
réactiver), CLAUDE.md §8 et table des ADR.

Hors lot, volontairement : paiement en ligne Bictorys (lot D), messages WhatsApp
automatiques (WhatsApp Cloud API, payant), SMS.
```

## Ce que le propriétaire fait lui-même

1. **Relire les textes des rappels** proposés par l'agent : c'est le ton de CoGes avec ses clients.
2. **Répondre à la question** sur le point de départ de la période payée pendant la grâce.
3. **Avant le déploiement**, regarder dans l'administration les boutiques dont l'essai ou la période se termine dans les jours qui viennent : elles passeront directement sur le nouveau calendrier.
4. **En préproduction**, prendre une boutique de test, mettre sa fin d'essai à demain avec « Prolonger », et vérifier chaque jour (ou en lançant la tâche à la main) : veille, jour J, J+2, suspension à J+3, puis réactivation par un paiement déclaré.
5. **Ensuite, la liste « À relancer »** dans l'administration devient votre routine du matin pour les commerçants sans e-mail.
