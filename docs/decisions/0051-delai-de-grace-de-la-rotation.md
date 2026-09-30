# 0051 — Délai de grâce de la rotation du refresh token

- **Date** : 2026-09-30
- **Phase** : 12 (correctif de la session livrée en phase 02, front de la phase 11)
- **Statut** : acceptée — complète l'ADR 0005
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

L'ADR 0005 fait tourner le refresh token à chaque `/auth/refresh` et révoque **toute la
famille** dès qu'un jeton déjà consommé est présenté. En phase 12, un parcours Playwright a
montré une déconnexion sans vol : une navigation pleine page pendant le rafraîchissement
silencieux (ADR 0048) interrompt la réponse **après** le COMMIT de la rotation mais **avant**
que le navigateur n'enregistre le nouveau cookie. La page suivante présente l'ancien jeton,
la détection de réutilisation révoque la famille, l'utilisateur est renvoyé à la connexion.
Une coupure réseau sur mobile produit le même effet.

## Options envisagées

1. **Délai de grâce de 30 s (retenue)** : un jeton tourné il y a moins de 30 s, dont le
   successeur n'a jamais servi, obtient une nouvelle session ; le successeur jamais reçu est
   écarté ; la famille reste vivante.
2. Délai de 10 s : moins d'exposition, mais une connexion lente perd encore la session.
3. Statu quo documenté : sécurité maximale, déconnexions intempestives.

## Décision

`auth.service.refresh` accorde une reprise quand **toutes** ces conditions tiennent :

- le jeton présenté a été révoqué **par une rotation** (`replaced_by` renseigné) — pas par
  une déconnexion ni par la révocation d'une famille ;
- la rotation date de 30 s au plus (`ROTATION_GRACE`) ;
- le successeur (verrouillé `FOR UPDATE`) n'est ni révoqué ni expiré, donc n'a jamais servi.

Le successeur est alors révoqué **sans** `replaced_by` : présenté à son tour, il ne
bénéficie d'aucune grâce — une seule reprise par rotation. La reprise est tracée dans la
transaction (`audit_logs`, action `update`, motif `rotation_retried_within_grace`).
Hors de ces conditions, rien ne change : réutilisation, famille révoquée, audit critique.

## Conséquences

- La détection de vol reste entière dès que le client légitime a utilisé son nouveau jeton,
  ou après 30 s. Pendant la fenêtre, un voleur du jeton précédent qui passerait **avant** le
  client légitime obtiendrait une session ; le client légitime, en présentant ensuite le
  successeur écarté, déclencherait la révocation de la famille — le vol reste détecté, un
  peu plus tard.
- Deux reprises simultanées du même ancien jeton se sérialisent sur le verrou : la seconde
  voit le successeur révoqué et révoque la famille (le front mutualise déjà le
  rafraîchissement entre onglets, ADR 0048).
- Tests : `tests/integration/test_auth.py` (reprise accordée, une seule fois, refusée après
  30 s, refusée quand le successeur a servi).
