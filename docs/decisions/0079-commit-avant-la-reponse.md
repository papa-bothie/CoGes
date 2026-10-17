# 0079 — Le COMMIT se fait avant l'envoi de la réponse

- **Date** : 2026-10-17
- **Phase** : lot A (sécurité avant la production)
- **Statut** : acceptée
- **Décideur** : déjà tranché par l'architecture (une transaction par cas d'usage, rollback
  complet si une étape échoue) ; correctif validé avec le plan du lot A

## Contexte
La transaction d'un cas d'usage est ouverte et validée par la dépendance `yield`
`get_tenant_session`. Dans FastAPI 0.141, une dépendance `yield` de portée `request` (le
défaut) se ferme **après** `await response(...)` (`fastapi/routing.py`). Le COMMIT avait donc
lieu après l'envoi : un COMMIT refusé (contrainte différée, coupure, sérialisation)
laissait au client un 2xx pour une écriture absente.

Preuve, `tests/integration/test_commit_failure.py` avant correctif (un trigger
`DEFERRABLE INITIALLY DEFERRED` sur `business_events` fait échouer le vrai COMMIT) :

```
E  AssertionError: COMMIT refusé mais réponse 200   # confirmer une vente
E  AssertionError: COMMIT refusé mais réponse 201   # encaisser un paiement
E  AssertionError: COMMIT refusé mais réponse 201   # corriger le stock
3 failed
```

## Options envisagées
1. **`Depends(..., scope="function")` (retenue)** : la dépendance se ferme à la sortie du
   handler, sérialisation comprise, avant l'envoi. Une ligne par dépendance.
2. Commit explicite dans chaque routeur : dispersé, et facile à oublier.
3. Middleware qui retient la réponse : contourne le mécanisme prévu par FastAPI.

## Décision
`CurrentTenant` et `get_platform_session` sont déclarés en portée `function`. Après correctif :
5xx, vente en brouillon, stock et CMP inchangés, aucun événement d'outbox, clé d'idempotence
non enregistrée ; le rejeu avec la **même** clé réussit. `3 passed`.

## Conséquences
- `tests/architecture/test_commit_before_response.py` refuse toute route dont une
  dépendance transactionnelle n'est pas en portée `function`.
- Une réponse en flux (`StreamingResponse`) ne peut plus lire la session après le handler :
  aucune n'existe aujourd'hui (les exports sont rendus en un bloc).
- Les rappels `tenancy.on_commit` (vidage du cache, ADR 0061) partent désormais avant la
  réponse, ce qui est l'ordre attendu.
