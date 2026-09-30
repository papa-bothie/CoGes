# 0005 — Connexion malgré la RLS, et sessions de rafraîchissement

- **Date** : 2026-09-23
- **Phase** : 02
- **Statut** : acceptée — complétée par 0051 (délai de grâce de la rotation)
- **Décideur** : utilisateur (via `AskUserQuestion`), sur les points ouverts **P2** et **P3**

## Contexte

**P2.** La connexion se fait par le couple (slug d'entreprise, e-mail) — § 2.2 du Modèle de
données — mais `companies` et `users` sont sous RLS : sans contexte tenant, la recherche renvoie
zéro ligne. Et le contexte ne peut pas être posé avant de savoir qui se connecte.

Mesuré sur PostgreSQL 16 avant de décider :

| Situation | Lignes vues |
|---|---|
| `coges_owner`, propriétaire des tables, sans contexte | **0** — `FORCE` s'applique au propriétaire |
| Fonction `SECURITY DEFINER` appartenant à `coges_owner` | **0** |
| Fonction `SECURITY DEFINER` appartenant à un rôle `NOLOGIN BYPASSRLS` | **1** |
| `coges_app` en direct, après tout cela | **0** |

Une fonction `SECURITY DEFINER` ne suffit donc pas : il lui faut un propriétaire capable de
franchir la RLS.

**P3.** Aucune table n'existait pour les refresh tokens, alors que la décision 16 exige un
refresh **rotatif** et une révocation.

## Décision

**Fonction `auth_lookup(slug, email)`**, `STABLE SECURITY DEFINER`, `search_path` figé à
`pg_catalog, public`, noms d'objets qualifiés. Elle renvoie **quatre colonnes**
(`company_id`, `user_id`, `password_hash`, `is_active`) pour un seul couple. `EXECUTE` est
révoqué à `PUBLIC` et accordé au seul `coges_app`.

Elle appartient à **`coges_auth`**, rôle `NOLOGIN NOSUPERUSER BYPASSRLS` créé à l'amorçage du
cluster (`deploy/postgres/init/01-roles.sql`), pas par une migration — un rôle est un objet de
cluster (ADR 0004). `coges_owner` en est membre `WITH INHERIT FALSE`, uniquement pour pouvoir
transférer la propriété de la fonction ; aucune élévation implicite n'en découle.

**Table `auth_sessions`** tenant-scoped, sous RLS forcée : `token_hash`, `family_id`,
`expires_at`, `revoked_at`, `replaced_by`, `user_agent`, `ip_address`. Seule l'empreinte
SHA-256 du jeton est stockée — le jeton est un secret aléatoire de 256 bits, hors de portée
d'une attaque par dictionnaire.

Le refresh token a la forme `{company_id}.{secret}`. Le `company_id` n'est pas un secret — le
porteur connaît son entreprise — et le porter en clair évite **une seconde fonction capable de
franchir la RLS** pour retrouver la session.

**Rotation et détection de réutilisation** : chaque `/refresh` révoque le jeton présenté et en
émet un nouveau dans la même famille. Rejouer un jeton déjà consommé révoque **toute la
famille** et écrit une ligne d'audit critique.

## Conséquences

- La surface qui contourne la RLS tient en une fonction, vérifiée par trois tests : aucun rôle
  **connectable** n'a `BYPASSRLS`, `coges_app` n'est pas membre de `coges_auth`, et seul le
  module `auth` ouvre une session sans contexte tenant.
- `TenantContext.bootstrap(company_id)` existe pour les deux seuls cas où le porteur n'est pas
  encore connu : création d'entreprise et rafraîchissement. Il n'accorde aucune permission.
- **Piège corrigé en cours de route** : la révocation de la famille était d'abord écrite puis
  perdue, car lever l'erreur à l'intérieur de la transaction annulait tout. La révocation est
  désormais **commitée**, et l'erreur levée après.
- Un poste déconnecté par `/logout` perd toute sa chaîne de jetons.
