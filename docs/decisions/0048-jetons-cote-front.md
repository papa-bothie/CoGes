# 0048 — Jetons et identité côté front

- **Date** : 2026-09-29
- **Phase** : 11
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

ADR 0006 : access token en mémoire (15 min), refresh en cookie `httpOnly` (7 j, rotatif, un
rejeu révoque toute la famille, ADR 0005). Deux trous côté front :

1. `proxy.ts` (garde des pages) ne voit pas le cookie de rafraîchissement, limité au chemin
   `/api/v1/auth`.
2. Aucune route ne renvoyait l'utilisateur courant : un vendeur n'a ni `users:read` ni
   `company:read`, alors que l'en-tête et la garde d'affichage ont besoin de son nom, de son
   rôle, de ses permissions et du fuseau de l'entreprise.

## Options envisagées

- Garde des pages : **cookie indicateur non sensible (retenue)** / élargir le cookie de
  refresh à `/` (plus exposé) / garde client seule (flash de coquille vide).
- Identité : **`GET /api/v1/auth/me` (retenue)** / `/users/me` / décoder le JWT (qui ne porte
  ni nom, ni rôle, ni permissions).

## Décision

- **`GET /api/v1/auth/me`** : authentifié, **sans permission**. Renvoie `user`, `roles`
  (`name` technique, `description` affichée), `permissions` (triées, celles que la dépendance
  de session relit en base) et `company` (nom, slug, devise, fuseau, `tax_enabled`). Auth
  compose les façades `users`, `rbac` et `companies`.
- Jeton d'accès **en mémoire** seulement (`lib/auth/token-store.ts`). Pas de minuteur : le
  client rafraîchit **à la demande**, quand le jeton manque (page rechargée) ou expire dans
  moins d'une minute, et une fois après un 401.
- Rafraîchissements **mutualisés** dans l'onglet (une promesse partagée) et **sérialisés
  entre onglets** (Web Locks) : deux rotations concurrentes du même cookie seraient prises
  pour un rejeu.
- `coges_session=1` (chemin `/`, `SameSite=Lax`, 7 j, non `httpOnly`) : posé à la connexion
  et à chaque rafraîchissement, effacé à la déconnexion ou sur un refresh refusé. `proxy.ts`
  ne s'en sert que pour rediriger ; il ne donne aucun droit.
- Déconnexion propagée aux autres onglets par `BroadcastChannel`, avec **une seule instance
  par onglet** : sinon l'onglet émetteur s'entend lui-même (bogue trouvé par le parcours e2e).
- Refresh refusé (401) ⇒ `/login?reason=expired&next=…` ; serveur injoignable ⇒ pas de
  déconnexion. `next` n'accepte qu'un chemin interne (contrôle renforcé par l'ADR 0049 :
  le premier ne refusait pas `/\evil.example`).
- `lib/permissions.ts` (`can`, `filterByPermission`), `usePermission` et `<Can>` masquent ou
  désactivent : **le serveur reste l'unique juge**.

## Conséquences

- 98 opérations sous `/api/v1` (une de plus). Tests : identité par rôle, isolation entre
  entreprises, 401 sans jeton.
- Un XSS pourrait lire l'indicateur de session, qui ne vaut rien, et l'access token en
  mémoire (15 min) ; jamais le refresh token.
