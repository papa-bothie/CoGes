# 0091 — Abonnements : offres, essai de 30 jours, plafond d'utilisateurs (lot admin 3)

- **Date** : 2026-10-24
- **Phase** : lot admin 3 (`docs/prompts/24-admin-abonnements.md`)
- **Statut** : acceptée — **remplace l'ADR 0043** et referme le point **P8**
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
L'ADR 0043 avait écarté tout palier commercial du code V1 (P8). Le propriétaire fixe
maintenant trois offres mensuelles — Starter 4 900 FCFA (3 utilisateurs), Business 9 900 FCFA
(7), Premium 14 900 FCFA (10) — une période d'essai, et la possibilité d'un palier « sur
devis » au-delà de 10 utilisateurs, sans redévelopper le modèle. Le paiement reste
déclaratif : l'équipe saisit qu'un paiement a été reçu.

Trois contraintes héritées :
1. `coges_app` (l'API commerçante) ne lit aucune table plateforme et le module `users/` ne
   peut pas importer `platform/` : le plafond doit vivre **en base** (comme l'ADR 0014) ;
2. le statut d'accès `companies.status` (lot 1, ADR 0089) ne change que par
   `coges_app_platform` ou le propriétaire (garde `CG006`) ;
3. le worker ne se connectait qu'en `coges_app`.

## Options retenues (AskUserQuestion)
- **Essai : 30 jours, toujours sur Premium** ; à l'expiration sans paiement, **suspension
  automatique** (le mécanisme du lot 1, rien de nouveau côté accès).
- **Avertissements chaleureux à J-7, J-3 et J-1**, par **e-mail au(x) gérant(s) et
  notification dans la cloche** (nouveau type `trial_ending`, adressé à `users:update`).
- **Fonctionnalités en jsonb** sur `plans` (liste indicative ; rien n'est encore réservé
  à une offre dans le produit).
- **Noms commerciaux Starter, Business, Premium** (codes internes identiques, noms
  modifiables par une mise à jour de `plans.name`).
- **Entreprises existantes** : un essai Premium de 30 jours à compter de la migration.
- **Un paiement déclaré** rend l'abonnement actif, avance la fin de période d'un mois
  (depuis aujourd'hui ou depuis la fin en cours, la plus lointaine) et réactive une
  entreprise suspendue.
- **Nouveau rôle `coges_billing`** (NOLOGIN, NOBYPASSRLS) propriétaire des deux règles en
  base, plutôt qu'élargir `coges_ops` (BYPASSRLS, confiné à `job_runs`).

Décidé dans le plan, sans objection :
- **Durée d'essai en base**, pas en variable d'environnement : l'essai naît par trigger
  dans la transaction de création de l'entreprise, qui ne lit pas l'environnement. La
  changer = une révision.
- **Deux statuts** : `subscriptions.status` (trial, active, past_due, suspended) est l'état
  commercial ; `companies.status` reste l'interrupteur d'accès. Synchronisés dans la même
  transaction quand le statut d'abonnement change (trial→trial, active/past_due→active,
  suspended→suspended). La suspension manuelle du lot 1 ne touche que l'accès.
- **Écritures réservées à l'administrateur** ; lectures pour administrateur et support.
- **Le worker reçoit `COGES_DATABASE_URL_PLATFORM`.**
- **Idempotence du paiement** par colonne unique `subscription_payments.idempotency_key`
  (`Idempotency-Key` obligatoire, 8 à 200 caractères) : `idempotency_keys` est une table
  par entreprise sous RLS commerçante.

## Décision
**Révision 0028.**
- `plans` (sans `company_id`, hors RLS) : `code` unique, `name`, `price_fcfa numeric(14,2)`
  (NULL : sur devis), `max_users` (NULL : illimité), `features jsonb`, `is_orderable`.
  Seed des trois offres. **Palier « sur devis »** : à ajouter le jour venu par
  `INSERT INTO plans (code, name, price_fcfa, max_users, is_orderable) VALUES ('sur_devis',
  'Sur devis', NULL, NULL, false)`, puis `is_orderable = true` (avec un prix) quand il se
  vend — aucun développement.
- `subscriptions` : une ligne par entreprise (`company_id` unique), `plan_id`, `status`,
  `trial_ends_at`, `started_at`, `current_period_end`, `trial_warned_days` (7, 3, 1 :
  dernier avertissement envoyé). RLS FORCE + politique tenant (T37) + politique de
  `coges_app_platform`. Aucun droit pour `coges_app`.
- `subscription_payments` (sans `company_id`) : append-only, moyens `wave`, `orange_money`,
  `cash`, `bank_transfer` (valeurs de `pay_method`, bornées par CHECK).
- Triggers `SECURITY DEFINER` de `coges_billing` :
  `companies_start_trial()` (AFTER INSERT ON companies) et `users_plan_limit()` (BEFORE
  INSERT / UPDATE OF is_active, deleted_at ON users) : un compte qui **devient** actif
  au-delà du plafond est refusé (`CG007`, plafond en DETAIL), l'abonnement est verrouillé
  `FOR UPDATE` (deux créations sur la dernière place : une seule passe). Il compte les
  comptes sous la RLS, dans l'entreprise du contexte seulement.
- `companies.status` : `active`→`trial` pour l'existant, défaut `trial`.

**API** (sous `/api/v1/platform`) : `GET /plans`, `GET /companies/{id}/subscription`,
`PATCH /companies/{id}/subscription` (offre vendable, statut ; descente refusée en 409
`plan_downgrade_too_many_users` avec `active_users`, `max_users`, `to_deactivate`),
`POST /companies/{id}/payments` (201, rejeu 200 + `Idempotent-Replay`). Audit critique
`platform_audit_logs` ; verrous : l'entreprise puis l'abonnement, partout. Côté commerçant,
`POST /users` et la réactivation rendent 409 `plan_user_limit_reached` : « Ce plan autorise
N utilisateurs maximum. Passez à un palier supérieur pour en ajouter. »

**Tâche de nuit** `platform.subscriptions_daily` (06 h 30 UTC, `job_runs`) : une
transaction sous `coges_app_platform` — essais échus ⇒ abonnement et accès suspendus,
audit sans acteur ; essais à ≤ 7, ≤ 3, ≤ 1 jour ⇒ palier posé une fois. Après COMMIT, une
sous-tâche `platform.trial_notice` par entreprise (e-mail chaleureux, cloche pour un
avertissement ; e-mail « votre essai est terminé » à l'échéance, sans l'e-mail de
suspension du lot 1) et un récapitulatif à l'équipe (`COGES_PLATFORM_ALERT_EMAIL`).

**Administration** : carte « Abonnement » sur la fiche entreprise (offre, statut, essai,
période payée, comptes actifs, paiements), « Changer d'offre » et « Enregistrer un
paiement » (clé gardée jusqu'au succès).

## Conséquences
- Prérequis Neon : `deploy/sql/create_billing_role.sql` **avant** 0028 (la migration le
  vérifie). Le worker doit recevoir `COGES_DATABASE_URL_PLATFORM`.
- T36 : `coges_billing` confiné (`plans`, `subscriptions`, quatre colonnes de `users`) ;
  aucun rôle commerçant n'atteint les trois tables. T37 : `plans` et
  `subscription_payments` déclarées sans RLS. Liste blanche du rôle plateforme étendue.
- Les entreprises partagées par la suite de tests passent au palier « sur devis » (elles
  hébergent les comptes d'une centaine de tests) ; le plafond a ses propres tests.
- Rien n'est encore réservé à une offre dans le produit (`features` indicatif) ; pas
  d'historique des abonnements (l'état courant seulement) ; pas de relance automatique des
  périodes payées échues (`past_due` se pose à la main) ; pas d'écran d'abonnement côté
  commerçant.
