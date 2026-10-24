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
make admin-lighthouse   # accessibilité Lighthouse de la connexion et du tableau de bord (≥ 95)
ADMIN_CAPTURES=apres pnpm --dir frontend-admin exec playwright test e2e/captures.spec.ts
                        # captures clair, sombre et 360 px dans docs/design/captures/admin/
```

**Interface (ADR 0094).** Thème CoGes : jetons `--coges-*` copiés de `frontend/app/globals.css`
(mêmes noms), Figtree hébergée, clair ou sombre selon le système. Repère « Administration » :
bandeau en **encre ardoise** en haut de chaque écran, titre d'onglet « Administration · … »,
favicon ardoise. Aucune couleur en dur hors de `app/globals.css` (`lib/no-hardcoded-colors.test.ts`).
Menu latéral dès 1024 px (Accès, Plateforme), tiroir en dessous ; recherche globale au « / »
(entreprises, comptes commerçants, équipe). Icônes `lucide-react` (version figée, comme
`frontend/`). Une seule fenêtre de confirmation pour les actions sensibles
(`components/confirm-dialog.tsx`). Écrans : tableau de bord et « À traiter », entreprises,
utilisateurs commerçants (lecture seule, état dans l'adresse), équipe (inviter, profil,
suspendre), journal en phrases, page d'invitation (`/invitation/<jeton>`, hors coque).
Procédures : `docs/runbooks/administration.md`.

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

**Statistiques** (ADR 0093) : entreprises par statut et par offre (les essais à part des
payantes), comptes actifs, revenu **déclaré** sur le mois en cours, le mois précédent ou
une période choisie (366 jours au plus), nouvelles entreprises sur 12 mois ou 52 semaines.
Chaque chiffre est daté ; le revenu ne compte que les paiements enregistrés, jamais ce que
les offres en cours « devraient » rapporter.
