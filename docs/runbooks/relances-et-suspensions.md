# Relances et suspensions : fin d'essai, fin d'abonnement, boutique en pause

Pour l'équipe CoGes (administration de la plateforme). Référence : ADR 0133 (et 0091, 0132).

## Ce qui se passe tout seul

Chaque matin à 06 h 30 (heure de Dakar), CoGes regarde la date de fin de chaque boutique : la
fin de l'**essai gratuit**, ou la fin de la **période payée**. Les jours se comptent dans le
fuseau de la boutique.

| Jour | Ce que reçoit le gérant | La boutique |
|---|---|---|
| La veille (J-1) | « Votre essai se termine demain » | ouverte |
| Le jour J | « Votre essai se termine aujourd'hui… ouverte encore 3 jours » | ouverte (abonnement « en retard ») |
| J+2 | « Dernier rappel : … mise en pause demain » | ouverte |
| J+3 | e-mail « Votre boutique est en pause » | **en pause** |

- Chaque rappel passe par la **cloche**, le **téléphone** (si les notifications sont activées)
  et l'**e-mail** des gérants qui en ont un. Un **bandeau** s'affiche en haut de l'application
  pour le gérant ; le dernier jour, les autres employés voient « Prévenez votre gérant ».
- Chaque rappel part **une seule fois**. Si la tâche n'a pas tourné une nuit, elle envoie
  seulement l'étape du jour. **Personne n'est mis en pause sans avoir reçu le dernier rappel la
  veille** : si la nuit de J+2 a été manquée, la pause est repoussée d'un jour.
- Une licence sur site et Premium sans date de fin ne reçoivent jamais rien.
- L'équipe reçoit chaque matin un récapitulatif (`COGES_PLATFORM_ALERT_EMAIL`) : les rappels
  envoyés, puis les mises en pause.

## La routine du matin : « À relancer »

Administration → **À relancer** (le compteur est aussi dans « À traiter » au tableau de bord).

On y trouve les boutiques entre la veille de leur fin et J+3, et celles mises en pause depuis
moins de 7 jours. Pour chacune : l'étape, la date de fin, la date de pause, ce qui est déjà
parti, et les gérants avec leur téléphone.

1. Commencer par les **« Dernier rappel »** (orange) et les **« En pause »** (rouge).
2. Relire le message prérempli, l'adapter si besoin (prénom, ton), puis **Écrire sur
   WhatsApp** : WhatsApp s'ouvre avec le message, on l'envoie depuis le téléphone de l'équipe.
   C'est gratuit : rien ne part tout seul.
3. Ceux qui n'ont pas d'e-mail ne reçoivent que la cloche et le bandeau : ce sont eux qu'il faut
   appeler ou écrire en priorité.

## Un commerçant appelle à J+2 (« ma boutique va fermer ? »)

1. Le rassurer : **ses données sont gardées**, rien n'est effacé, même en pause.
2. S'il paie maintenant : Entreprises → la boutique → **Enregistrer un paiement**. L'abonnement
   redevient actif, les rappels s'arrêtent, rien ne sera mis en pause.
   - Renouvellement : la nouvelle période part de l'**ancienne date de fin** (les jours de grâce
     ne sont pas offerts).
   - Fin d'essai : la période part **d'aujourd'hui**.
3. S'il a besoin de quelques jours : **Prolonger** (ci-dessous).

## Prolonger un essai ou une période

Entreprises → la boutique → carte **Abonnement** → **Prolonger** (profil administrateur).

1. Nombre de jours (1 à 90) et **raison** obligatoire (« Paiement promis lundi, appel du 26/11 »).
2. Les jours s'ajoutent à la date de fin, ou à aujourd'hui si elle est déjà passée.
3. Les rappels repartent de zéro pour la nouvelle date. Une boutique en pause **rouvre**.
4. Le geste est au journal de l'administration, avec la raison.

La ligne **Relances** de la carte dit la dernière étape envoyée pour la date de fin en cours.

## Réactiver une boutique en pause

Le plus simple : **Enregistrer un paiement**. La boutique rouvre tout de suite, le gérant reçoit
l'e-mail « accès rétabli », la nouvelle période part du jour du paiement.

Sans paiement (geste commercial, erreur) : **Prolonger** de quelques jours avec la raison.

Le commerçant en pause qui essaie de se connecter voit « Votre boutique est en pause », ses
données gardées, et un bouton WhatsApp vers l'équipe pour payer.

## Avant un déploiement de ce lot

Regarder dans « À relancer » (ou Entreprises, filtre Essai) les boutiques dont la fin tombe dans
les jours qui viennent : elles passent directement sur le nouveau calendrier. Une **période
payée déjà dépassée** (rien ne les suivait avant) reçoit d'abord « mise en pause demain », puis
est mise en pause la nuit suivante : prolonger ou encaisser avant si ce n'est pas voulu.

## Tester en préproduction

1. Prendre une boutique de test, **Prolonger** son essai pour que sa fin tombe demain (si l'essai
   finit loin, attendre ou partir d'un essai court).
2. Lancer la tâche à la main sur le VPS de préproduction, ou attendre 06 h 30 :
   `dc exec worker celery -A app.workers.celery_app call platform.subscriptions_daily` (`dc` :
   voir `workers.md`).
3. Vérifier chaque jour : veille, jour J (abonnement « En retard », boutique ouverte), J+2,
   pause à J+3 ; puis réactiver par un paiement déclaré.
