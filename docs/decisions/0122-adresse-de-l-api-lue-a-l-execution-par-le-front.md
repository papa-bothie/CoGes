# 0122 — Adresse de l'API lue à l'exécution par le front, aucune dans l'image

- **Date** : 2026-11-12
- **Phase** : correctif de production (`fix/front-api-url`)
- **Statut** : acceptée (amende 0047 et 0083)
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
En production, le bouton « Créer ma boutique » ne paraissait jamais alors que
`GET /api/v1/auth/signup-config` répondait `enabled: true`. `signupConfig()`
(`frontend/lib/signup/config.ts`, ADR 0118) lit `COGES_API_URL` **à l'exécution**, dans le
serveur Next ; le Dockerfile ne la posait qu'à l'étape de build (`docker exec coges-front-1`
⇒ `undefined`). La lecture visait `localhost:8000`, échouait, et rendait « fermé ».

La valeur de build, `http://api:8000`, était de toute façon ambiguë : production et
préproduction partagent le réseau `coges_edge`, où le nom de service `api` désigne les deux
piles. Next fige les réécritures de `next.config.ts` au build (`routes-manifest.json`), et la
même image sert les deux piles : aucune valeur de build ne peut nommer la bonne.

## Options envisagées
1. **Aucune réécriture dans l'image (retenue)** : le Dockerfile ne pose plus
   `COGES_API_URL` ; sans elle, un build de production n'émet aucune réécriture. Caddy reste
   la seule route `/api/v1` (un `/api/v1` égaré vers le front fait 404, jamais l'API de
   l'autre pile).
2. Réécriture refaite dans `proxy.ts` à l'exécution : filet gardé, plus de code.
3. Garder `api:8000` : le filet pouvait viser l'API de l'autre pile.

## Décision
`deploy/vps/docker-compose.yml` donne au service `front` `COGES_API_URL:
http://${COGES_STACK}-api:8000` (l'alias propre à la pile) ; les images `front` et `admin` ne
figent aucune adresse d'API ; `next.config.ts` (des deux fronts) n'émet de réécriture que si
`COGES_API_URL` est donnée au build, ou en développement (`localhost:8000`).

## Conséquences
- Test découvert (`tests/unit/test_vps_configuration.py`) : toute lecture `process.env.X`
  du code servi par un front (hors `NODE_ENV`, `NEXT_PUBLIC_*`, `NEXT_DEPLOYMENT_ID`, inlinés
  par Next, et hors fichiers de build) doit être fournie par son service compose ; aucun
  Dockerfile de front ne pose `COGES_API_URL`. Vitest sur les réécritures des deux configs.
- Dev, e2e et CI passent déjà `COGES_API_URL` au build : inchangés.
- L'administration ne lit à l'exécution que `COGES_MERCHANT_URL`, déjà fournie.
- Vérification ajoutée à `docs/runbooks/inscriptions.md`.
