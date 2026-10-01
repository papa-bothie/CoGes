# 0058 — Le front se déploie avec l'API, à une adresse stable

- **Date** : 2026-10-01
- **Phase** : après la phase 14
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

Le workflow « Déploiement » (ADR 0040) déployait l'API à chaque push sur `main`, mais pas le
front (`coges-web`), déployé à la main en préversion depuis la phase 11. Résultat : après la
fusion de la phase 14, l'API de préproduction était à jour et le front ne l'était pas, et
aucune adresse stable ne permettait d'ouvrir le projet. Les déploiements Git de Vercel restent
désactivés sur les deux projets (aucun code ne part sans la CI).

## Options envisagées

1. **Production Vercel de `coges-web` à chaque push sur `main` (retenue)** : adresse stable
   `https://coges-app.vercel.app`, publique comme l'API de préproduction ; la connexion CoGes
   reste exigée. Ce domaine est **attribué au projet** : avec la protection standard de
   Vercel, l'adresse générée `coges-web-cipher-one1.vercel.app` reste, elle, derrière la
   connexion Vercel (`coges-web.vercel.app` était déjà pris).
2. Une préversion protégée par push : URL changeante, réservée aux comptes Vercel de l'équipe.
3. Statu quo (déploiement manuel).

## Décision

- Le job « Déployer » enchaîne, après le test de fumée de l'API : `vercel build` puis
  `vercel deploy --prebuilt` depuis `frontend/` (secret d'environnement
  `VERCEL_WEB_PROJECT_ID`), puis un **test de fumée du front** : page `/login` servie, et
  `deploy/scripts/smoke.py` (santé, connexion, tableau de bord) **à travers la réécriture**
  `/api/v1` du front, sur `COGES_WEB_PUBLIC_URL`.
- Le front part **après** l'API, jamais avant : il réécrit vers elle (ADR 0047).
- Le garde-fou 2 (ADR 0042) contrôle aussi les variables du projet `coges-web`.
- `COGES_API_URL` de `coges-web` est une variable **`encrypted`**, jamais *sensitive* : le build
  a lieu sur GitHub (`vercel build`), qui ne peut pas lire une variable sensible (ADR 0044).

## Conséquences

- Un push sur `main` met à jour l'API **et** le front de préproduction ; les workers de la
  zone B restent à reconstruire sur leur hôte (`up -d --build`).
- Le front de préproduction est publiquement joignable (page de connexion) : même régime que
  l'API, déjà publique.
- La cible `production` du workflow exigera le même secret et la même variable quand la
  production sera ouverte ; une cible `preview` a besoin du jeton de contournement de
  `coges-web` (`VERCEL_WEB_AUTOMATION_BYPASS_SECRET`) pour son test de fumée.
