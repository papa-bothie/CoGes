# 0054 — Paramètres : seuil par défaut, devise figée, dernier gérant

- **Date** : 2026-09-30
- **Phase** : 13
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

L'écran Paramètres du prototype (écran 10) montre « seuils par défaut », la devise, et la
gestion des utilisateurs et des rôles. L'API révélait quatre trous :

1. aucun réglage d'entreprise pour un seuil d'alerte par défaut (`reorder_point` est par produit) ;
2. `settings` était un objet libre, sans aucune vérification des clés connues ;
3. la devise est modifiable alors que la V1 est mono-devise : la changer rebaptiserait tous les
   montants sans les convertir ;
4. rien n'empêchait de se désactiver soi-même par `PATCH` (seul `DELETE` le refusait), ni de
   retirer le rôle gérant au dernier gérant actif — l'entreprise perdait alors l'accès aux
   comptes, aux rôles et aux paramètres.

## Options envisagées

- Seuil : défaut appliqué **par le serveur** (retenue) / préremplissage côté front / pas de seuil.
- Devise : **lecture seule à l'écran** (retenue) / modifiable avec avertissement.
- Verrouillage : **garde serveur** (retenue) / masquage front / rien.
- Désactivation : **`PATCH is_active`**, réversible (retenue) / `DELETE`, définitive.

## Décision

1. `settings.default_reorder_point` (chaîne décimale ≥ 0, trois décimales au plus, `null` pour
   l'effacer). `products.create_product` l'applique à un produit **suivi** créé sans seuil — donc
   aussi à l'import CSV ; un seuil saisi, même `0`, n'est jamais remplacé. Products lit le
   réglage par la façade Companies (`default_reorder_point`).
2. `CompanyUpdate` vérifie les réglages connus : `tax_enabled` et `intelligence_enabled` booléens,
   `default_reorder_point` comme ci-dessus (422 sinon). Les autres clés sont conservées.
   `settings` **remplace** l'objet : le front renvoie les clés qu'il ne modifie pas.
3. La devise s'affiche sans pouvoir être modifiée à l'écran ; l'API est inchangée (multi-devises
   hors V1).
4. `LastManagerError` (409 `last_manager`) : ni désactivation (`PATCH` ou `DELETE`) ni retrait du
   rôle système `gerant` ne peut laisser l'entreprise sans gérant **actif**. Se désactiver
   soi-même est refusé par `PATCH` comme par `DELETE` (422). Les routes
   `POST/DELETE /users/{id}/roles` passent de RBAC à Users — mêmes chemins, mêmes droits —
   parce que RBAC n'a pas le droit de lire `users` (décision 01) ; Users compose les deux façades.
5. L'écran désactive par `PATCH is_active` (réversible) ; `DELETE` reste servi mais n'est pas
   proposé.

## Conséquences

- `tests/integration/test_settings_guards.py` : réglages refusés et acceptés, seuil appliqué ou
  non, dernier gérant (seul, second désactivé puis réactivé, compte « RH » sans rôle gérant).
- Le gérant reste défini par le **rôle système** `gerant`, pas par un ensemble de permissions :
  un rôle personnalisé très large ne compte pas comme gérant pour cette garde.

## Complément (2026-09-30) — la garde sous concurrence

**Défaut constaté** : deux gérants qui se désactivent mutuellement en même temps réussissaient
tous les deux. Chacun comptait l'autre comme encore actif, puisque aucune des deux transactions
n'avait encore validé. Reproduit : trois titulaires du rôle `gerant`, zéro actif. Une contrainte
déclarative ne peut pas rattraper ce cas : la règle porte sur un **ensemble de lignes**
(`users` × `user_roles`), pas sur une ligne.

**Correctif** : `_assert_a_manager_remains` prend d'abord un **verrou consultatif
transactionnel** propre à l'entreprise,
`pg_advisory_xact_lock(hashtextextended('coges:last_manager:<company_id>', 0))`
(`UserRepository.lock_manager_guard`), **avant** de compter les gérants actifs. Les trois voies
passent par cette fonction : `PATCH /users/{id}` (`is_active: false`), `DELETE /users/{id}` et
`DELETE /users/{id}/roles/{role_id}` sur le rôle `gerant`. Le verrou est libéré au COMMIT ou au
ROLLBACK ; en READ COMMITTED, le comptage qui suit voit ce que la transaction précédente vient de
valider.

Pourquoi un verrou consultatif plutôt que `SELECT … FROM companies … FOR UPDATE` : il ne
sérialise **que** les retraits de gérant d'une même entreprise, sans bloquer les autres écritures
sur la ligne `companies` (changement de réglage, par exemple). Une collision de hachage entre deux
entreprises ne ferait que sérialiser inutilement deux retraits, jamais les mélanger : le comptage
reste filtré par `company_id` et par la RLS.

**Test** : `tests/integration/test_last_manager_concurrency.py`, paramétré sur les trois voies.
Le test tient le verrou, lance deux retraits croisés (A retire B, B retire A), attend dans
`pg_locks` que **les deux** soient bloqués au rendez-vous, puis relâche. Un seul passe, l'autre
reçoit 409 `last_manager`, et il reste exactement un gérant actif. Sans le verrou, le test échoue :
aucun des deux retraits ne s'arrête au rendez-vous.
