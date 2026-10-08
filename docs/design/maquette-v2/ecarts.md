# Écarts acceptés entre la maquette v2 et le front

Chaque différence voulue entre la maquette et le front, avec sa raison et la date de
l'accord du propriétaire. Un écran listé ici est exempté du seuil de 2 % de
`maquette.spec.ts` pour l'élément concerné.

| Écran | Différence | Raison | Accord |
|---|---|---|---|
| 03 Liste des ventes, 04 Détail d'une vente | Badge gris « Dette abandonnée » en plus de « Payé », « Reste X F », « Retour » et « Annulée » | Une dette abandonnée (ADR 0029) laisse un reste non nul qui n'est plus réclamé : l'afficher en orange ferait croire que le client doit encore (ADR 0062) | 2026-10-07 |
| Toutes (seed `maquette`) | Les données ne reprennent pas chaque capture : un seul jeu cohérent, au plus près (ADR 0065). Exacts : tuiles et graphique de l'accueil, dettes clients (54 500 F) et fournisseurs (185 000 F), dépenses du mois, articles, personnes | Les captures se contredisent entre elles (dernières ventes 90 000 F pour une tuile à 87 500 F, 4 ventes du jour dans la liste pour 14 sur l'accueil, vente de 8 h 47 payée ou annulée selon l'écran) | 2026-10-07 |
| 01 Accueil, 03 Liste des ventes | Boutique Ndiaye a acheté pour 35 000 F (maquette : 47 500 F) ; la vente de 8 h 47 est payée | Pour que les cinq dernières ventes tiennent dans les 87 500 F du jour | 2026-10-07 |
| 01 Accueil | « Stock à surveiller » compte 4 articles (maquette : 3) | Le lait en poudre épuisé (maquette 07) compte aussi ; la tuile de l'accueil se discute au lot 3a | 2026-10-07 |
| 03 Liste des ventes, 14 Fiche client, 21 Caisse | Numéros de ventes du seed : la dernière du jour est V-001046 comme la maquette, les autres suivent l'ordre du seed (maquette : 1012, 0987… sur la fiche de Moussa Fall) | Une seule numérotation sans trou (ADR 0021) | 2026-10-07 |
| 02, 07 et suivants | Couleurs des carrés d'article tirées du nom, pas celles de la maquette ; « boîtes » (lait) s'affiche « pièces » | Aucune colonne de couleur dans le modèle V1.1 (ADR 0064) ; sacs et bouteilles existent depuis le lot 1 (ADR 0066), pas les boîtes | 2026-10-08 |
| 23 Alertes, 22 Conseils | Alertes et conseils calculés par le worker et l'Intelligence sur les données du seed, pas ceux de la maquette | Lecture seule, jamais écrits à la main (décisions d'architecture) | 2026-10-07 |
