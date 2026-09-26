# 0039 — Verrous de l'annulation et idempotence par ressource

- **Date** : 2026-09-26
- **Phase** : 10 (temps A)
- **Statut** : acceptée — précise les ADR 0038 et 0027
- **Décideur** : utilisateur (revue du temps A)

## Contexte

La revue du temps A a relevé deux défauts, sans effet sur les soldes mais faux dans ce qu'ils
laissent derrière eux :

1. **L'audit critique d'une annulation pouvait mentir.** `cancel_payment` lisait les dettes sans
   verrou pour écrire le « before » ; le verrou n'arrivait qu'ensuite, dans le trigger
   `payment_reversal_rollup`. Un paiement concurrent sur la même dette, commité entre les deux,
   rendait le « before » (30 000 payés) incohérent avec le « after » (10 000 payés après
   l'annulation de 30 000 : il y en avait donc 40 000). Les soldes, eux, restaient exacts.
2. **Une clé d'idempotence pouvait rejouer la réponse d'une autre vente.**
   `POST /sales/{id}/confirm` et `POST /sale-returns/{id}/refunds` enregistraient un endpoint fixe
   (`{id}` en toutes lettres). Deux ventes confirmées avec le même corps avaient la même empreinte :
   la même clé présentée pour la seconde rendait la réponse de la première, et la seconde restait
   en brouillon, le client croyant l'avoir encaissée. Signalé par l'ADR 0038, non corrigé alors.

## Options envisagées

1. **(retenue)** Verrouiller dans le service, dans l'ordre paiements → dettes, avant de lire ; et
   inclure l'identifiant de la ressource dans l'endpoint enregistré, comme
   `POST /payments/{id}/cancel`.
2. Reconstituer le « before » depuis les lettrages après coup : plus de code, et un audit qui
   décrirait un calcul plutôt qu'un état observé.
3. Ajouter l'identifiant de la ressource dans l'empreinte (`request_hash`) seulement : même effet,
   mais l'endpoint enregistré resterait trompeur à la lecture de la table.

## Décision

- `cancel_payment` verrouille le ou les paiements d'origine (`PaymentRepository.lock_for_update`,
  `ORDER BY id`), **refait** le contrôle « déjà annulé » sous ce verrou, puis verrouille les dettes
  lettrées (`DebtRepository.get_for_update`, dans l'ordre des ids) **avant** de photographier le
  « before ». Les triggers de la révision 0012 prennent les mêmes verrous dans le même ordre
  (paiement → dettes → retours → vente) : aucun ordre nouveau, aucune migration.
- Règle générale : **tout endpoint d'écriture financière qui porte sur une ressource enregistre
  son identifiant** dans `idempotency_keys.endpoint`. `CONFIRM_SALE_ENDPOINT` et
  `REFUND_RETURN_ENDPOINT` deviennent des gabarits (`{sale_id}`, `{return_id}`) formatés au
  moment de la réservation. Même clé sur une autre ressource ⇒ 422 `idempotency_key_reused`.

## Conséquences

- Tests : `test_the_audited_before_includes_a_concurrent_payment` (paiement concurrent tenu ouvert,
  rendez-vous sur `pg_stat_activity.wait_event_type = 'Lock'`, « before » = 40 000) et
  `tests/integration/test_idempotency_per_resource.py` (vente et retour). Tous deux échouaient
  avant correction.
- Deux annulations simultanées du même paiement se sérialisent désormais sur le verrou du
  service ; la seconde reçoit `payment_already_cancelled` avant toute écriture.
  `payments_reversal_uq` reste l'autorité.
- Les clés déjà enregistrées sous l'ancien gabarit ne correspondent plus : une requête rejouée
  à cheval sur le déploiement serait refusée (`idempotency_key_reused`) plutôt que rejouée. Elles
  expirent en 24 h ; aucune migration.
