# 0043 — Aucun palier commercial dans le code V1 (P8)

- **Date** : 2026-09-26
- **Phase** : 10 (temps B)
- **Statut** : remplacée par 0091 (abonnements, lot admin 3)
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
Point ouvert **P8** (`docs/architecture/README.md`) : la proposition commerciale évoque des
limites par palier (60 jours d'historique, nombre d'utilisateurs, Intelligence partielle),
absentes de l'architecture V1. La décision 18 range « abonnements » hors V1.

## Options envisagées
1. **Aucun palier dans le code V1 (retenu)** : conforme à la décision 18.
2. Une table de plans et des limites contrôlées : écart à la décision 18, avec une
   migration, des contrôles et des tests de plus.

## Décision
Aucune table de plans, aucune limite par palier. Le seul interrupteur existant reste
`settings.intelligence_enabled` par entreprise (ADR 0036), sans lien avec une offre
commerciale.

## Conséquences
- P8 est clos pour la V1 ; la facturation est une évolution post-V1, à concevoir comme
  telle (et à rapprocher de P7, « plusieurs entreprises par compte »).
