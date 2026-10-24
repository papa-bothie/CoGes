# CoGes — Administration de la plateforme

Application Next.js **à part** du front commerçant (ADR 0089) : aucune de ses routes ni
aucun de son JavaScript n'est livré au navigateur d'un commerçant. Servie par Caddy sur
`admin.<domaine>`, filtrée par adresse IP (`COGES_ADMIN_ALLOWED_IPS`), elle n'appelle que
`/api/v1/platform/*` avec le jeton de l'équipe (audience `coges-platform`).

```bash
make admin-install      # dépendances et Chromium (même Playwright que frontend/)
make admin-dev          # http://localhost:3200, API sur COGES_API_URL (défaut :8000)
make admin-api          # régénère types/api.ts depuis backend/openapi.json
make admin-check        # types, lint, typecheck, Vitest, build
make admin-e2e          # coges_e2e recréée, API :8100, administration :3200, axe AA
```

Comptes : `make create-platform-user EMAIL=… NAME="…" ROLE=administrator|support`. Écrans :
connexion, liste des entreprises, fiche (comptes, suspendre ou réactiver avec confirmation
et raison, **abonnement** : offre, essai, paiements déclarés, changer d'offre, ADR 0091) ; **Système** et **Tâches** (ADR 0090 : bilan des workers rafraîchi toutes les
30 s, rebut de l'outbox, historique des tâches), avec un bandeau rouge sur toute page dès
que le bilan est en panne. Aucune donnée commerciale de l'entreprise : les seuls montants
sont ceux de son abonnement à CoGes.

**Accès support** (ADR 0092, `docs/runbooks/acces-support.md`) : sur la fiche, « Ouvrir un
accès support » (motif obligatoire, 30 min à 4 h, 2 h par défaut), puis « Voir
l'entreprise » ouvre l'application commerçante, en lecture seule, dans un nouvel onglet ;
« Fermer l'accès » la coupe à la requête suivante. L'adresse de l'application commerçante
est lue à l'exécution dans `COGES_MERCHANT_URL` (défaut `http://localhost:3000` ; sur le
VPS, `https://<COGES_DOMAIN>` par le compose ; en e2e, `:3100`, que `make admin-e2e` démarre
aussi).
