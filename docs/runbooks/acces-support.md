# Accès support à une entreprise (ADR 0092)

Pour regarder les données d'un commerçant qui signale un problème : en **lecture seule**,
pour **une durée limitée**, et **toujours tracé** chez lui comme chez nous.

## Avant d'ouvrir

- Le motif sera lu par le gérant (e-mail, cloche, historique de sa boutique). Écrivez-le
  pour lui : « Vous nous avez signalé un écart de caisse le 24/10, nous vérifions vos
  encaissements du jour », pas « debug ».
- Une entreprise suspendue ne s'ouvre pas : réactivez-la d'abord si c'est justifié.
- Une seule session à la fois par entreprise. Si un collègue en a ouvert une, demandez-lui
  ou fermez-la, puis ouvrez la vôtre avec votre propre motif.

## Ouvrir

1. Administration → Entreprises → la fiche de l'entreprise → carte **Accès support**.
2. « Pourquoi cet accès ? » (10 caractères au moins), durée (2 h par défaut, 4 h au plus).
3. **Ouvrir un accès support.** Le gérant reçoit aussitôt un e-mail et une alerte ; tous les
   utilisateurs de la boutique voient un bandeau jusqu'à la fin.
4. **Voir l'entreprise** : l'application commerçante s'ouvre dans un nouvel onglet, avec le
   bandeau « lecture seule ». Aucun bouton ne modifie quoi que ce soit, et le serveur
   refuserait de toute façon (`support_read_only`).

L'onglet survit à un rechargement, pas à sa fermeture : recliquez « Voir l'entreprise »
(seul le membre de l'équipe qui a ouvert l'accès le peut ; chaque clic est journalisé).

## Fermer

- **Dès que c'est fini** : « Fermer l'accès ». L'onglet commerçant affiche « L'accès
  support est terminé » à sa requête suivante ; le bandeau disparaît chez le commerçant.
- Sinon, l'accès s'arrête seul à l'heure dite ; la tâche de nuit (01 h 30 UTC) le marque
  fermé.

## Ce qu'on ne fait pas

- Corriger une donnée à la place du commerçant : on lui explique quoi faire, ou on passe
  par lui. L'accès est en lecture seule par construction.
- Copier ses données hors de CoGes (captures d'écran comprises) au-delà de ce que la
  résolution exige.
- Ouvrir « au cas où » ou laisser une session ouverte sans raison.

## Vérifier après coup

- Côté commerçant : Réglages → Historique (« L'équipe CoGes a ouvert un accès support… »).
- Côté plateforme : la carte « Dernières sessions » (qui, quand, motif, fin) et
  `platform_audit_logs` (`entity_table = 'support_sessions'` : ouverture, chaque jeton
  remis, fermeture).
