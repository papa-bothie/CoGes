# 0076 — Clôture de la phase 15 : Lighthouse, audit et démo

- **Date** : 2026-10-15
- **Phase** : 15 (clôture)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-15)

## Contexte
Une fois les lots 0 à 3e-2 fusionnés (PR n° 8 à 17), trois critères de fin de phase du
prompt `15-refonte-simplicite.md` restaient ouverts :
- Lighthouse accessibilité ≥ 95 sur les 26 écrans ;
- un nouvel audit Impeccable (≥ 18/20) ;
- une démo qui montre chaque état.

Le propriétaire a choisi de les remplir avant de clore.

## Décisions
**Lighthouse en dépendance de développement** (retenu, contre une mesure ponctuelle par
`pnpm dlx`).
- `lighthouse@13.5.0` (version exacte) dans le front, et `make lighthouse` (`frontend/scripts/lighthouse.mjs`).
- Mêmes données et serveurs que `make maquette-check`, lancés s'ils ne répondent pas.
- Chromium de Playwright avec un profil gardé : la session de la gérante suit Lighthouse.
- Catégorie accessibilité seule, desktop ; 390 px pour l'écran 26.
- Une page qui mène ailleurs que prévu fait échouer la mesure, pour ne jamais noter l'écran de connexion à la place d'un autre. Seule exception : « Nouvelle vente » rouvre le brouillon du jour.
- Rapport : `docs/design/captures/phase-15/lighthouse.md`. Hors CI, comme `maquette-check`.
- Résultat : **100** sur les 26 écrans et les quatre rubriques des Réglages.

**Audit Impeccable** : `docs/design/audit-phase-15.md`, **18/20**, comme en fin de phase 14.
- Détecteur : aucun constat.
- Restent :
  - [P2] trois pages secondaires dans le style de la phase 13 ;
  - [P2] aucun passage manuel au lecteur d'écran ;
  - [P3] boutons d'icône de 28 px à la souris ;
  - [P3] grille des droits qui défile sur téléphone.

**Démo** : le seed `demo` montrait déjà les quatre états demandés (jours en perte, clients
soldés, articles sous le seuil, dettes fournisseurs dues dans la semaine), sans que rien le
garantisse. `tests/integration/test_seed_demo_states.py` les vérifie sur une démo neuve.

## Conséquences
- La phase 15 est close (✅ dans `CLAUDE.md`).
- Les constats P2 et P3 de l'audit restent à traiter dans une prochaine passe de finition.
