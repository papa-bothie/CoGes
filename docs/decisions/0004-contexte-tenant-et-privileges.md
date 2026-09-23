# 0004 — Pose du contexte, amorçage d'un tenant et privilèges du rôle applicatif

- **Date** : 2026-09-23
- **Phase** : 01
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le § 12.1 point 1 du Modèle de données l'énonce sans détour : la pose du contexte tenant est
« le seul endroit où une erreur d'implémentation peut encore produire une fuite entre
tenants ». Trois questions restaient ouvertes autour de ce point.

**a. Comment poser le contexte ?** `SET LOCAL` n'accepte pas de paramètre lié : il faudrait
interpoler l'UUID dans la requête.

**b. Comment créer une entreprise ?** `companies` est en `FORCE ROW LEVEL SECURITY` avec une
politique `id = current_setting(...)`. Insérer une entreprise exige donc que le contexte vaille
déjà son propre identifiant — et `FORCE` s'applique aussi au propriétaire de la table.

**c. Qui crée le rôle `coges_app` ?** Le § 8.11 le crée dans le même bloc SQL que les politiques,
alors qu'un rôle est un objet de **cluster**, pas de base.

## Décision

**a. `SELECT set_config('app.company_id', :company_id, true)`**, avec l'UUID en paramètre lié.
Le troisième argument `true` signifie « portée transaction » : c'est l'équivalent exact de
`SET LOCAL`, sans aucune concaténation de chaîne, donc sans injection possible.

Ce SQL vit dans **`app/core/tenancy.py`, et nulle part ailleurs**, exposé comme
`SET_TENANT_CONTEXT_SQL`. Quatre tests d'architecture le verrouillent : aucun `SET` sans
`LOCAL` dans `app/` ni dans `migrations/`, aucun `set_config(..., false)`, aucun autre fichier
de `app/` ne mentionne `set_config` ni `app.company_id` dans son code exécutable (analyse AST,
les commentaires sont donc autorisés à en parler), et la constante doit porter la portée
transaction. Le test **T4** rejoue cette même constante : si quelqu'un passait un jour la portée
à `false`, T4 échouerait — vérifié en sabotant volontairement le code.

**b. UUID pré-généré côté serveur**, puis contexte, puis INSERT. Python génère l'identifiant de
l'entreprise, `tenant_transaction` pose le contexte sur cette valeur, et l'INSERT satisfait le
`WITH CHECK` de `companies_self`. Aucun objet SQL supplémentaire, aucune fonction
`SECURITY DEFINER`, aucun contournement de la RLS — et un seul endroit continue de poser le
contexte. C'est ce que fait le harnais de tests (`tests/tenancy/harness.py`) et ce que fera
l'inscription d'une entreprise.

**c. La migration ne crée pas le rôle.** `coges_app` et `coges_owner` sont créés à l'amorçage du
cluster (`deploy/postgres/init/01-roles.sql` en développement et en CI, le DBA en production).
`0001_platform` ne pose que les privilèges :

```sql
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO coges_app;
REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM coges_app;   -- suppression logique
REVOKE INSERT, UPDATE ON permissions FROM coges_app;           -- catalogue en lecture seule
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO coges_app;         -- tables des phases suivantes
```

Les **privilèges par défaut** évitent qu'une phase future oublie ses `GRANT` : toute table créée
par `coges_owner` sera automatiquement lisible et modifiable par `coges_app`, et jamais
supprimable.

`permissions` en lecture seule est un écart assumé au § 8.11, qui se contredit lui-même
(`GRANT … ON ALL TABLES` puis `GRANT SELECT ON permissions`). La table n'a pas de `company_id`,
donc pas de RLS : une écriture applicative y affecterait **tous** les tenants. Le vocabulaire
des droits est livré par migration.

## Conséquences

- Changer de tenant impose une nouvelle transaction : `TenantContext` est gelé (`frozen`).
- Le point P2 (connexion par couple slug + e-mail, phase 02) devra résoudre l'utilisateur
  **avant** d'avoir un contexte : il faudra une fonction `SECURITY DEFINER` restreinte ou un rôle
  d'authentification dédié. La présente décision ne le tranche pas.
- Le rôle `coges_analytics` du § 8.11 est reporté en phase 08, avec les tables analytiques.
- En production, la création des rôles est une étape d'infrastructure documentée dans
  `deploy/README-infra.md`, pas une étape de déploiement applicatif.
