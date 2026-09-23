# 0007 — Matrice des rôles système, et les trois exceptions au « pas de DELETE »

- **Date** : 2026-09-23
- **Phase** : 02
- **Statut** : acceptée
- **Décideur** : utilisateur (matrice validée avant codage, via `AskUserQuestion`)

## Contexte

Qui peut confirmer une vente, encaisser, annuler un paiement ou ajuster le stock est une
décision de **gestion**, pas un détail technique. Elle a donc été validée avant d'être écrite
en migration.

## Décision — matrice

Codes de permission : `ressource:action`. Le catalogue global (60 codes) est livré par la
migration `0002` ; les rôles, eux, sont créés **par entreprise** à sa création.

Le **gérant** reçoit tout le catalogue. Les deux autres rôles :

| Ressource | Vendeur | Comptable |
|---|---|---|
| `company` | — | `read` |
| `users`, `roles` | — | — |
| `categories`, `products`, `prices`, `suppliers` | `read` | `read` |
| `customers` | `read create update` | `read` |
| `sales` | `read create update` **`confirm`** | `read export` |
| `sale_returns` | `read create` | `read` |
| `inventory` | `read` | `read` |
| `payments` | `read create` | `read create update` **`cancel`** |
| `expenses` | — | `read create update delete` |
| `debts` | — | `read create update` |
| `dashboard` | `read` | `read` |
| `analytics` | — | `read export` |
| `insights` | — | `read update` |
| `audit` | — | `read export` |
| `importexport` | — | `export` |

Quatre arbitrages, explicitement validés :

1. le **vendeur confirme** une vente et encaisse — c'est la caisse — mais **n'annule jamais** :
   une annulation touche simultanément stock, finance et dette ;
2. l'**ajustement manuel de stock** (`inventory:update`) est réservé au gérant : c'est la seule
   écriture de stock qui ne vient pas d'un flux métier ;
3. le **comptable ne confirme aucune vente** et ne touche pas au stock ;
4. utilisateurs, rôles et paramètres d'entreprise : **gérant uniquement**.

La matrice vit dans `app/modules/rbac/matrix.py`, source unique reprise par la commande
d'onboarding et par les tests.

## Décision — trois exceptions au « pas de DELETE »

Révoquer un rôle exige de supprimer une ligne de `user_roles` ; or le § 8.2 ne donne à cette
table ni colonne `deleted_at`, ni clé de substitution, et la règle du projet interdit DELETE à
`coges_app`. Ajouter un `revoked_at` casserait la clé primaire `(user_id, role_id)` : un rôle
révoqué ne pourrait plus jamais être réattribué.

DELETE est donc accordé sur **exactement trois tables** : `user_roles`, `role_permissions` et
`roles`. Aucune ne porte de donnée métier historisée ; la traçabilité est assurée par l'audit
critique, qui enregistre l'avant et l'après. La FK `user_roles → roles` en `ON DELETE RESTRICT`
empêche la base de supprimer un rôle encore porté, et le service refuse les rôles système.

## Conséquences

- Le test **T36** vérifie que DELETE est accordé sur **exactement** ces trois tables : toute
  extension future de ce privilège fait échouer la CI sans qu'on modifie le test.
- Chaque attribution et chaque révocation laisse une ligne dans `audit_logs`.
- Les rôles système (`is_system = true`) ne sont ni modifiables dans leurs permissions, ni
  supprimables.
