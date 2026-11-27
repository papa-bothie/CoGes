# 0133 — Relances de fin d'essai et d'abonnement, délai de grâce, suspension à J+3

- **Date** : 2026-11-26
- **Phase** : lot C (`docs/prompts/43-relances-et-suspension.md`)
- **Statut** : acceptée. **Amende l'ADR 0091** (calendrier J-7/J-3/J-1, suspension le jour
  même, `trial_warned_days`, `past_due` manuel seulement) **et l'ADR 0132** (« Mon abonnement »,
  bloc `plan` de `/auth/me`).
- **Décideur** : le propriétaire pour le calendrier (décisions du 23 novembre 2026, écrites dans
  le prompt), l'utilisateur pour trois points (AskUserQuestion du 26 novembre 2026).

## Contexte

L'ADR 0091 prévenait à J-7, J-3 et J-1 puis suspendait un essai **le jour même** de sa fin.
Rien ne suivait une **période payée** (`current_period_end`) : une boutique dont l'abonnement
était échu restait ouverte jusqu'à un geste de l'équipe, et `past_due` n'était posé qu'à la
main. Le propriétaire veut des rappels chaleureux la veille, le jour J et à J+2, et une pause
automatique à J+3, pour l'essai comme pour un abonnement. Beaucoup de commerçants n'ont pas
d'e-mail : il faut un bandeau dans l'application et une liste pour l'équipe.

## Décisions de l'utilisateur (AskUserQuestion)

1. **Point de départ d'une période payée pendant la grâce** : un **renouvellement** (période
   payée en cours ou dans ses 3 jours de grâce) part de **l'ancienne échéance**, les jours de
   grâce ne sont pas offerts ; une **fin d'essai**, une boutique **en pause**, ou une échéance
   oubliée depuis plus de 3 jours partent **du jour du paiement** (`_period_start`).
2. **Rattrapage** : personne n'est mis en pause sans un **dernier rappel donné un jour
   précédent**. Si la tâche arrive à J+3 (ou plus tard) sans avoir envoyé le dernier rappel,
   elle l'envoie et suspend le lendemain. Cela vise aussi les périodes payées **déjà échues au
   déploiement** : elles reçoivent « mise en pause demain », puis sont suspendues la nuit
   suivante.
3. **« Prolonger » de N jours** : depuis l'échéance, ou depuis aujourd'hui si elle est passée.
   Une boutique en pause rouvre.

## Décision

### Le calendrier (`app/core/renewal.py`, fonctions pures)

Soit E l'échéance : `current_period_end` hors essai s'il existe, sinon `trial_ends_at`. J est
son jour calendaire **dans le fuseau de l'entreprise** (`companies.timezone`).

| Jour | Étape | Effet |
|---|---|---|
| J-1 | `eve` (veille) | rappel |
| J, J+1 | `due` (jour J) | rappel, abonnement `past_due`, **accès inchangé** (`trial` ou `active`) |
| J+2 | `last` (dernier rappel) | rappel « mise en pause demain » |
| J+3 et après | `suspended` | abonnement et accès `suspended`, audit sans acteur |

- Pas de J-7 ni de J-3. Une licence sur site (`is_license`) et une période sans fin (Premium
  posé sans échéance) ne sont pas suivies.
- **Une étape au plus par jour, jamais en arrière.** Une nuit manquée ne donne que l'étape du
  jour (jamais deux rappels d'un coup). La pause exige un `last` d'un jour précédent.
- J+1 est rattrapé par l'étape `due`, dont le texte dit alors « s'est terminé hier… encore
  2 jours ».

### L'état d'étape (révision 0044)

`subscriptions.reminder_stage` (`eve`, `due`, `last`, `suspended`), `reminder_for_end` (l'échéance
concernée) et `reminder_at` (quand), les trois ensemble (contrainte). Une échéance nouvelle
(paiement, « Prolonger ») ne correspond plus à `reminder_for_end` : le calendrier repart de zéro
sans rien effacer. Relancer la tâche le même jour ne refait rien. `trial_warned_days` reste en
base pour la version précédente pendant le déploiement (ADR 0083), plus lue ; à retirer plus
tard. Une entreprise déjà prévenue à J-7 ou J-3 suit simplement la suite du nouveau calendrier ;
une entreprise déjà suspendue reste suspendue.

`coges_app_platform` reçoit `SELECT (timezone)` sur `companies` : une métadonnée, pas une
donnée commerciale (ADR 0089).

### `past_due` pendant la grâce

Statut existant, désormais posé par la tâche de nuit à l'étape `due`. `ACCESS_OF["past_due"]`
reste `active` pour les gestes de l'équipe ; la tâche, elle, **ne touche pas à l'accès**
pendant la grâce : un essai en grâce garde `companies.status = 'trial'`. Un paiement remet
l'abonnement `active` et arrête les rappels.

### Les canaux

- **Tâche de nuit** (06 h 30 UTC, inchangée) : une transaction sous `coges_app_platform`, puis
  après COMMIT une sous-tâche `platform.renewal_notice` par entreprise (remplace
  `platform.trial_notice`) et le récapitulatif à l'équipe (`platform.trial_summary` : étapes du
  jour, puis mises en pause).
- **Cloche et téléphone** : type `trial_ending` réutilisé pour l'essai comme pour l'abonnement
  (aucun type nouveau dans la contrainte des notifications), destinataires `users:update`
  (gérants), dédoublonnés par `renewal:<étape>:<échéance>` ; texte du téléphone
  `push.renewal(stage, kind)`, sans montant, vers `/settings/subscription`.
- **E-mail** aux gérants qui en ont un, une fois la cloche posée pour la première fois. Gérant
  sans e-mail : cloche, téléphone et bandeau, sans erreur.
- **Pause** : e-mail « Votre boutique est en pause » seulement (la boutique ne se connecte
  plus : pas de cloche).
- **Mots** : « échéance » est hors du lexique (ADR 0069, testé) ; la version « abonnement » dit
  « Votre abonnement CoGes Pro se termine demain », pas « arrive à échéance ».

### Le bandeau (`plan.renewal` de `/auth/me` et de `GET /subscription`)

Calculé depuis `current_plan()` (statut, dates) et le fuseau de l'entreprise, sans lecture
nouvelle des tables de la plateforme : `{kind, stage, ends_at, pause_on, days_left}`, de J-1 à
J+2 (et tant que la pause n'est pas posée). Front : `RenewalBanner` dans la coquille, pour le
gérant (`company:update`) de J-1 à J+2 avec « Choisir mon offre », pour les autres rôles
seulement au dernier rappel (« Prévenez votre gérant ») ; teinte « conseils », orange
(`stock`) au dernier rappel ; dans le flux de la page (ne couvre ni le panier ni
l'encaissement) ; repliable pour la journée (`coges:renewal-hidden:<entreprise>:<étape>:<jour>`
dans le stockage local) ; jamais sous l'accès support.

Connexion d'une boutique en pause (`company_suspended`) : écran « Votre boutique est en pause »,
données gardées, bouton WhatsApp prérempli vers l'équipe (le paiement en ligne viendra au lot D).

### L'administration

- `GET /api/v1/platform/reminders` (administrateur et support) : boutiques de J-1 à J+3 et en
  pause par la tâche depuis moins de 7 jours, avec l'étape du calendrier, ce qui est déjà
  parti, l'échéance, la pause, les gérants et leur téléphone, et le message de l'étape. Écran
  « À relancer » : message modifiable, « Écrire sur WhatsApp » (`wa.me`) et « Appeler » par
  gérant. Compteur `reminders` dans `/attention` et « À traiter ».
- `POST /api/v1/platform/companies/{id}/subscription/extend` (administrateur) : `days` de 1 à 90,
  raison obligatoire, audit critique ; état d'étape remis à zéro ; accès rendu si l'abonnement
  était en pause. Refusé pour une licence ou sans échéance.
- Fiche entreprise : ligne « Relances » (dernière étape envoyée pour cette fin) et formulaire
  « Prolonger » ; `SubscriptionDetail` gagne `reminder_stage`, `reminder_for_end`,
  `reminder_at`.

## Conséquences

- Tests : `tests/unit/test_renewal_calendar.py` (calendrier jour par jour, rattrapage, fuseau,
  bandeau) ; `tests/integration/test_renewal_lifecycle.py` (E-7 à E+4 pour un essai et pour une
  période payée, idempotence, nuits manquées, période déjà échue, entreprises avancées ou
  suspendues, fuseau, licence et Premium, paiement à J+1 et après la pause, renouvellement,
  Prolonger, À relancer, canaux, `/auth/me`) ; `test_onprem_license.py` (témoin mis en pause
  par le nouveau calendrier) ; registres (route d'écriture, lecture plateforme, grants du
  rôle). L'ancien `test_trial_lifecycle.py` est remplacé.
- Les tests qui font tourner la tâche dans le temps déplacent l'échéance ou l'horloge **vers
  le passé** : avancer l'horloge relancerait les entreprises partagées de la suite.
- Hors lot : paiement en ligne (lot D), messages WhatsApp automatiques (API payante), SMS.
- Avant le déploiement, le propriétaire regarde les boutiques dont la fin tombe dans les jours
  qui viennent : elles passent directement sur le nouveau calendrier
  (`docs/runbooks/relances-et-suspensions.md`).

## Amendement — prompt 44 (27 novembre 2026) : paiement de 6 mois

Voir l'ADR 0134.

- Un paiement de 6 mois suit les mêmes règles de départ (`_period_start`) et la même fonction
  de fin de mois (`_add_months`) que 1 et 12 mois.
- Le calendrier des relances ne change pas : il ne regarde que la date de fin, et il repart de
  zéro pour la nouvelle fin.
