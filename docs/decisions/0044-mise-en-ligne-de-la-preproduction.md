# 0044 — Mise en ligne de la préproduction : variables Vercel, test de fumée, relais

- **Date** : 2026-09-27
- **Phase** : 10 (temps B)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion), sauf le point 3, imposé par l'ADR 0032

## Contexte
Le premier déploiement réel de la préproduction (Neon, Redis Cloud, Vercel Hobby, zone B sur
le poste) a mis au jour trois écarts que la CI ne pouvait pas voir :

1. La CLI Vercel pose les variables de l'environnement *production* en mode **sensitive** :
   leur valeur n'est plus relisible, même par l'API. Le garde-fou 2 (ADR 0042) ne pouvait
   alors contrôler que les **noms** de variables, et répondait « OK » sans avoir vu les DSN.
2. Les URL propres à chaque déploiement (`coges-<hash>-…vercel.app`) sont derrière la
   protection Vercel (401). Le test de fumée visait cette URL.
3. Le relais ne reçoit que `COGES_DATABASE_URL_RELAY` (ADR 0032), mais la configuration
   exigeait `COGES_DATABASE_URL_APP` : le conteneur redémarrait en boucle.

## Options envisagées
1. Variables : **chiffrées et relisibles par le jeton (retenu)**, ou *sensitive* avec un
   garde-fou réduit aux noms.
2. Fumée : **domaine public de l'environnement (retenu)**, jeton de contournement partout,
   ou protection désactivée.
3. Relais : **DSN applicatif facultatif, `require_app_url()` à l'usage (retenu)**, ou DSN
   `coges_app` donné au relais (contraire au moindre privilège de l'ADR 0032).

## Décision
- Les variables Vercel sont posées par l'API avec `type: "encrypted"`, jamais par
  `vercel env add` (qui impose *sensitive*). Le garde-fou 2 lit donc les valeurs.
- En préproduction et en production, le test de fumée vise la variable d'environnement GitHub
  `COGES_PUBLIC_URL` (`https://coges-api.vercel.app` en préprod) ; la préversion garde l'URL du
  déploiement et `VERCEL_AUTOMATION_BYPASS_SECRET`. La protection des URL de déploiement reste
  active.
- `Settings.database_url_app` devient facultatif ; `get_engine()` passe par
  `require_app_url()`, qui échoue avec un message explicite, comme `require_relay_url()`.

## Conséquences
- Quiconque détient le jeton Vercel peut lire les secrets d'exécution : ce jeton se traite
  comme un secret d'administration (environnement GitHub seulement, rotation au départ d'une
  personne).
- Le garde-fou 2 répond encore « OK » si une variable repasse en *sensitive* : durcissement
  possible (refuser une valeur illisible), non fait à ce jour.
- Test unitaire `test_relay_starts_without_the_app_dsn`.
