# 0059 — Cibles tactiles, base e2e dédiée, gravité des alertes

- **Date** : 2026-10-01
- **Phase** : après la phase 14 (améliorations reportées par l'ADR 0056)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

L'audit d'après la phase 14 (`docs/design/audit-phase-14-apres.md`) laissait trois points :
des cibles de 28 à 36 px sur tablette, des suites e2e qui accumulaient leurs données dans la
base de développement (lenteurs et instabilités), et un bandeau « Dette échue » neutre alors
qu'il signale un retard. Aucun de ces points ne change une règle ni un parcours.

## Décisions

1. **Cibles tactiles.** Sur `@media (pointer: coarse)` (variante Tailwind `pointer-coarse:`),
   toute cible interactive mesure au moins **44 × 44 px** : boutons (d'icône compris, donc
   pagination et croix des panneaux), champs, listes déroulantes, onglets, contrôle
   segmenté, liens de navigation et du fil d'Ariane, lignes de tableau, cases et radios
   natives (règle de `globals.css`). Tout passe par `components/ui`, `components/shell` et
   `globals.css`, jamais page par page. Sur ordinateur, rien ne change (hauteurs relevées
   identiques au pixel). Test : `e2e/touch-targets.spec.ts` (`hasTouch`, 1024 × 768) sur
   Nouvelle vente, Stock et Ventes.
2. **Base e2e dédiée `coges_e2e`.** `make e2e-reset` la recrée (`DROP` / `CREATE DATABASE` par
   le superutilisateur du conteneur local, migrations, `seed-demo`, puis agrégats et
   Intelligence, que la nuit construirait). `make e2e-api` (:8100, limites de débit à 0,
   Redis local base n° 1) et `make e2e-front` (:3100, build `.next-e2e`) sont démarrés par
   Playwright (`webServer`) ; `make front-e2e` commence par `e2e-reset`. Le script
   `deploy/scripts/e2e.sh` ne change que le nom de la base et **refuse tout hôte non local**,
   PostgreSQL comme Redis, avant la moindre commande. Aucune suppression de lignes dans le
   code applicatif.
3. **Gravité des alertes renvoyée par le serveur.** Champ `severity` (`warning` |
   `critical`) sur `NotificationRead` et sur les alertes du tableau de bord (`ActiveAlert`),
   **dérivé du type** par le module Notifications (`severity_of`) : `stock_out` et
   `insight_critical` sont critiques, tout le reste demande attention. Aucune migration.
   `AlertBanner` : ton « attention » (orange) par défaut, « danger » (rouge) seulement si
   `critical`, **jamais neutre** ; un groupe d'alertes prend la gravité la plus haute.

## Conséquences

- OpenAPI et `types/api.ts` gagnent `NotificationSeverity` (champ additif).
- Le développement (:8001 / :3000, base `coges`) n'est plus touché par les e2e ; les captures
  des phases 11 à 14 sont désormais produites sur la base e2e.
- Observé, non traité : à 1024 px, le tableau des ventes déborde de 74 px dans sa carte
  (colonne Statut), avec ou sans écran tactile — existant avant cette décision.
