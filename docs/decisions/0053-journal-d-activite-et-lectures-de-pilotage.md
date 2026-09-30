# 0053 — Journal d'activité, lectures de pilotage et dépense payée atomique

- **Date** : 2026-09-30
- **Phase** : 13
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

Les écrans de pilotage de la phase 13 (Finance, Paramètres) ont révélé quatre trous dans l'API :

1. aucune route ne lit `audit_logs` (§ 8.8), alors que le prototype prévoit un **journal
   d'activité** ;
2. `UserRead` ne porte pas les rôles du compte ;
3. une dette (`DebtDetail`) ne porte que l'identifiant du tiers, pas son nom ;
4. une dépense ne dit pas si elle a été réglée, et « ajouter une dépense payée » demandait deux
   requêtes, donc deux transactions (`POST /expenses` puis `POST /payments`).

## Options envisagées

- Journal : gérant + comptable (matrice ADR 0007 inchangée, **retenue**) / gérant seul (retirer
  `audit:read` au comptable par migration).
- Lectures : enrichir l'API par champs additifs, comme l'ADR 0050 (**retenue**) / requêtes N+1 côté
  front, sans état « payée » possible.
- Dépense payée : bloc `payment` facultatif atomique (**retenue**) / deux requêtes enchaînées /
  règlement toujours séparé.

## Décision

1. **Module `audit/`** (Plateforme, lecture seule) : `GET /api/v1/audit-logs`, paginé, filtres
   `actor_user_id`, `action` (les 8 valeurs du `CHECK`), `entity_table`, `entity_id`, `from`, `to`,
   plus récent d'abord. Permission `audit:read` (gérant et comptable). Audit critique et secondaire
   écrivent la même table : le journal les lit ensemble. `actor_name` vient de la façade Users
   (comptes supprimés compris). SQL Core : la table partitionnée n'a pas de modèle ORM. Aucune
   migration : `coges_app` a déjà `SELECT` sur chaque partition, sous RLS forcée.
2. **Champs additifs** : `UserRead.roles` (façade RBAC, une requête par page), `DebtDetail.party_name`
   (façades Customers et Suppliers, `null` si le tiers est supprimé), `ExpenseRead.amount_paid`
   (façade Finance : décaissements vivants — ni compensation, ni paiement annulé, ni annulation).
   Le reste à régler n'est **pas** servi : l'écran compare `amount_paid` à `amount`.
3. **`ExpenseCreate.payment`** facultatif `{method, paid_at?, reference?}` : Expenses appelle
   `finance.record_payment` (sortie, `expense_id`, montant de la dépense) dans la **même
   transaction**, sous la même `Idempotency-Key`. `payments:create` est alors exigé en plus
   d'`expenses:create` ; un refus annule aussi la dépense.

## Conséquences

- 99 opérations sous `/api/v1` ; `openapi.json` et `frontend/types/api.ts` régénérés.
- Tests : `tests/integration/test_pilotage_reads.py` (rôles, nom du tiers, dépense payée avec rejeu
  et annulation, rollback sans `payments:create`, filtres du journal, 403 du vendeur sur le journal,
  `/users` et `PATCH /companies/me`), `tests/tenancy/test_audit_log_isolation.py`.
- Le journal n'expose ni modification ni suppression : `audit_logs` reste append-only (ADR 0008).
