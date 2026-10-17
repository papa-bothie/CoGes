# 0080 — Analyses de sécurité en CI : secrets et dépendances

- **Date** : 2026-10-17
- **Phase** : lot A (sécurité avant la production)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
Aucune analyse ne cherchait de secret dans l'historique git ni de faille connue dans les
dépendances. Contrainte : aucun service payant.

## Options envisagées
1. **gitleaks en binaire officiel vérifié par SHA-256, pip-audit et `pnpm audit`, lancés par
   un script commun (retenue)**.
2. Image Docker de gitleaks : plus lente en CI.
3. `gitleaks-action` : exige une licence si le dépôt passe dans une organisation.

## Décision
- `deploy/scripts/security_scan.py` (`make security-scan`, job CI `security`) :
  - **gitleaks 8.30.1** sur **tout** l'historique (`fetch-depth: 0`), valeurs masquées,
    `.gitleaks.toml` = règles par défaut + liste blanche commentée (gabarits `.env*.example`,
    faux secrets de CI et de test) ;
  - **pip-audit 2.10.1** sur `uv export --no-dev --group ml` : **toute** faille connue
    échoue, car les avis PyPI n'ont pas toujours de gravité ;
  - **`pnpm audit --prod`** : une faille haute ou critique échoue.
- Exceptions dans `security/audit-exceptions.toml` (identifiant, outil, raison, date de
  fin) ; une exception mal formée ou échue fait échouer. Aucun `--ignore` ailleurs.
- La CI tourne aussi **chaque lundi à 6 h UTC** (`schedule`) ; seul le job `security`
  s'exécute alors.
- Premier passage (217 commits) : **aucun secret**. Failles trouvées et corrigées dans ce
  lot, sans exception : PyJWT 2.14.0 → 2.15.1 (`PYSEC-2026-4141`, `PYSEC-2026-4183`),
  Next 16.3.6 → 16.3.8 (SSRF de l'optimisation d'images, haute, et 5 moindres),
  `shadcn` déplacé en `devDependencies` (CLI ; sa feuille CSS est lue au build, où les
  dépendances de dev sont installées) qui retire `braces` et le SDK MCP de la production,
  override pnpm `source-map-js >= 1.2.2` (tiré par postcss).

## Conséquences
- Le job `security` fait partie de la CI que le déploiement exige verte : une faille
  publiée bloque le déploiement jusqu'à correction ou exception datée.
- Si gitleaks trouve un secret : on s'arrête, on change le secret ; aucune réécriture
  d'historique sans accord.
- L'override `source-map-js` est à retirer quand postcss demandera lui-même la version
  corrigée.
