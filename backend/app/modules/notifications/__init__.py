"""Module Notifications — bande E, restitution.

Alertes principales : stock bas, rupture, dette échue, vente annulée. Elles naissent
**après COMMIT**, d'un événement ou d'un calendrier, jamais dans la transaction qui
les provoque : une alerte perdue est un désagrément, une vente perdue est une panne.

Trois choix structurent le module (ADR 0032) :

* **une ligne par destinataire**, jamais une ligne partagée par l'entreprise. « Lu »
  est une notion individuelle ; une ligne collective disparaîtrait pour tous dès que
  le premier l'ouvre, et le compteur de non-lus par utilisateur deviendrait impossible ;
* **destinataires par rôle** : le gérant reçoit tout, le comptable les dettes échues.
  Un vendeur n'a pas à être réveillé par la trésorerie de l'entreprise ;
* **déduplication par fenêtre** : le même fait ne réveille pas deux fois la même
  personne dans la journée. Un stock bas est une situation, pas un flux d'événements.

Le canal e-mail n'est pas livré en V1 : `NotificationChannel` réserve sa place, et
l'unique implémentation écrit en base (in-app).
"""
