# Frontend CoGes — Next.js (App Router)

**Rien n'est développé ici avant la phase 11** (`docs/prompts/11-front-fondations.md`).
Ce dossier n'est présent que pour figer sa place dans l'arborescence (Diagramme 10).

## Règles

- Gestionnaire de paquets : **pnpm**, activé par `corepack enable pnpm` (fourni avec Node 22).
- Le frontend n'appelle **que** l'API REST `/api/v1` ; aucun accès direct à la base.
- `types/` est **généré** depuis l'OpenAPI du backend, jamais écrit à la main.
- Interface en français, devise XOF : `1 234 567 FCFA`, dates `jj/mm/aaaa`, heures sur 24 h.
- Le RBAC du front ne fait que **masquer** : l'autorisation est vérifiée côté serveur.
