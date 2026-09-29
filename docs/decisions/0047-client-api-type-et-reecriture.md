# 0047 — Client API typé, servi sous la même origine

- **Date** : 2026-09-29
- **Phase** : 11
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

ADR 0006 : le refresh token est un cookie `httpOnly; SameSite=Lax`, chemin `/api/v1/auth`.
Le front et l'API vivent sur deux domaines `*.vercel.app`. `vercel.app` figure dans la *Public
Suffix List* : ce sont **deux sites** distincts, et le navigateur n'enverrait pas un cookie
`Lax` sur un `fetch` du front vers l'API. Les cookies tiers (`SameSite=None`) sont par
ailleurs bloqués par Safari et en voie de l'être partout.

## Options envisagées

1. **Réécriture Next `/api/v1/*` → `COGES_API_URL` (retenue)** : même origine pour le
   navigateur, cookie « first-party », plus de CORS pour le front, ADR 0006 intact.
2. Appel direct avec `SameSite=None` : modifie l'ADR 0006, refresh cassé chez une partie des
   utilisateurs.
3. Sous-domaines d'un domaine commun : exige un domaine configuré dès la préversion.

Client : `openapi-typescript` + `openapi-fetch` (retenu), plutôt qu'Orval ou hey-api qui
génèrent beaucoup de code et contrôlent moins le rafraîchissement.

## Décision

- `next.config.ts` réécrit `/api/v1/:path*` vers `${COGES_API_URL}/api/v1/:path*`.
  `COGES_API_URL` est lue **au build** ; elle est obligatoire sur Vercel.
- `pnpm gen:api` génère `frontend/types/api.ts` depuis `backend/openapi.json` ;
  `pnpm check:api` échoue en CI si le fichier est périmé. `lib/api/schema.ts` ne fait que
  nommer les types générés.
- `lib/api/client.ts` : `openapi-fetch` avec un `fetch` qui ajoute le Bearer et, sur 401,
  rafraîchit **une fois** puis rejoue la requête (copie du corps prise avant l'envoi).
- Erreurs : `{ error: { code, message, details } }` → `ApiError`. 422 → erreurs de champ
  (`details.fields`), autres erreurs de mutation → toast (désactivable par `meta`),
  404 → page « introuvable », 401 → rafraîchissement puis connexion.
- En-têtes du front : CSP de même origine, `X-Frame-Options: DENY`, `Referrer-Policy`.

## Conséquences

- `COGES_CORS_ORIGINS` n'est plus nécessaire pour le front (il reste configurable).
- **Vérifié en préversion le 2026-09-29** : à travers la réécriture de Vercel, l'API reçoit
  l'IP du client dans `X-Forwarded-For` (`auth_sessions.ip_address` = IP publique du poste
  de test, pour le navigateur comme pour `curl`). La limitation par IP (ADR 0042) voit donc
  le vrai client.
- Le projet Vercel du front doit déclarer le framework (`frontend/vercel.json`) : créé par la
  CLI sans préréglage, il cherchait un dossier statique `public/`.
- Aucune liste de l'API n'accepte de paramètre de tri : le `DataTable` n'offre le tri que sur
  les colonnes déclarées `sortable`, et ne trie jamais lui-même.
