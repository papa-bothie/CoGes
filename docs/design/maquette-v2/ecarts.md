# Écarts acceptés entre la maquette v2 et le front

Chaque différence voulue entre la maquette et le front, avec sa raison et la date de
l'accord du propriétaire. Un écran listé ici est exempté du seuil de 2 % de
`maquette.spec.ts` pour l'élément concerné.

| Écran | Différence | Raison | Accord |
|---|---|---|---|
| 03 Liste des ventes, 04 Détail d'une vente | Badge gris « Dette abandonnée » en plus de « Payé », « Reste X F », « Retour » et « Annulée » | Une dette abandonnée (ADR 0029) laisse un reste non nul qui n'est plus réclamé : l'afficher en orange ferait croire que le client doit encore (ADR 0062) | 2026-10-07 |
