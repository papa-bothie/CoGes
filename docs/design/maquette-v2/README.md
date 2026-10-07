# Maquette v2 de CoGes : la référence du nouveau design

Ce dossier est la **source de vérité visuelle** de la phase 15. Le propriétaire du produit l'a validée. Le front doit
la reproduire à la lettre : couleurs, tailles, textes, ordre des éléments et comportements. Toute différence est soit
corrigée, soit notée dans `ecarts.md` et validée par le propriétaire.

## Contenu

| Dossier ou fichier | À quoi il sert |
|---|---|
| `captures/` | 81 images : chaque écran et chaque état important, à 1280 px et à 390 px. C'est la cible visuelle. |
| `html/` | Une page statique par écran. Ouvrez-la dans Chrome et inspectez-la (F12) pour lire les valeurs exactes : marges, tailles, couleurs, rayons. |
| `source/` | Le code source de chaque écran de la maquette. Lisez le bloc `<script>` du bas pour connaître chaque état (ce qui change quand on touche un bouton), les messages et les règles de validation. Ces fichiers ne s'exécutent pas ici. |
| `tokens.css` | Toutes les valeurs du système : couleurs, polices, tailles, rayons, cibles tactiles. |
| `ecrans.md` | La liste des écrans, leurs captures, leur fichier source, la route du front et le lot de travail. |
| `logo/` | Le logo officiel (`coges-logo-original.jpg`) et trois découpes transparentes : logo complet, symbole seul, nom seul. |
| `ecarts.md` | Chaque différence voulue entre la maquette et le front, avec sa raison et la date de l'accord du propriétaire. |

## Les données des captures

Les captures utilisent la démo « Alimentation Keur Fatou » du mardi 6 octobre 2026 à 10 h 45 : Moussa Fall doit
25 000 F, le riz est à 2 sacs, 87 500 F vendus dans la journée, etc. L'entreprise `maquette` (`make seed-maquette`,
`backend/app/seed_maquette.py`, ADR 0065) recrée ces données **au plus près** : les captures se contredisent parfois
entre elles, et chaque chiffre qui diffère est listé dans `ecarts.md`.

## Conditions des captures

Le front se compare à la maquette dans les mêmes conditions, par `make maquette-check`
(`frontend/e2e/maquette.spec.ts`) :

- **Données** : l'entreprise `maquette` de la base `coges_e2e`, recréée par `make e2e-reset`. Ses horodatages sont
  recalés à la fin du remplissage : aucun ne dépasse le 6 octobre 2026 à 10 h 45, et chaque encaissement, sortie de
  stock ou dette porte l'heure de sa vente.
- **Heure** : `COGES_FROZEN_NOW=2026-10-06T10:45:00+00:00` (10 h 45 à Dakar) sur l'API, accepté seulement quand
  `COGES_ENV` vaut `local` ou `ci` ; `page.clock` figé au même instant dans le navigateur.
- **Serveurs à part** : API sur :8101 (cache Redis n° 2, sans limite de débit) et front sur :3101 ; les autres
  parcours e2e gardent l'heure réelle.
- **Écran** : thème clair, pleine page, 1280 × 900 px et 390 × 844 px ; animations et curseur coupés, indicateurs de
  développement de Next masqués ; connexion de la gérante (Fatou Diop) faite une fois la page chargée.
- **Pixels** : `pixelmatch` (sensibilité 0,1), images complétées par le fond papier si les hauteurs diffèrent ; au
  plus 2 % de pixels différents, sauf écran listé dans `ecarts.md`.
- **Textes** : chaque texte visible de `html/NN-nom.html` doit se trouver mot pour mot sur la page (espaces mis à
  part), sauf un montant noté « maquette : X F » dans `ecarts.md`. Un texte manquant fait échouer l'écran.
- **Résultat** : `docs/design/captures/phase-15/comparaison.md` et, pour chaque écran, une image maquette | front |
  différences (non versionnée).

Seuls les écrans livrés (lots 3a à 3e) bloquent ; `MAQUETTE_ALL=1 make maquette-check` mesure les autres sans échouer.

## Limites connues

- **Données** : un seul jeu cohérent ne peut pas reproduire toutes les captures (dernières ventes de l'accueil à
  90 000 F pour une tuile à 87 500 F, vente de 8 h 47 payée ou annulée selon l'écran…). Les différences sont dans
  `ecarts.md`.
- **États sans page HTML** : les états (02b, 04b, 22c…) n'ont qu'une capture ; seuls leurs pixels sont comparés,
  pas leurs textes.
- **Pages HTML statiques** : elles ne changent pas avec la largeur ; leurs textes sont vérifiés à 1280 px (à 390 px
  pour l'écran 26, qui n'a que cette capture).
- **Mode sombre** : absent de la maquette ; il est dérivé des jetons de `tokens.css` (ADR 0064) et validé sur les
  captures du front, pas par comparaison.
- **Ce que le modèle de données ne porte pas** : couleur des carrés d'article (tirée du nom), unités libres
  (« sacs », « bouteilles ») ; alertes et conseils calculés sur les données du seed.
- **Recalage des heures** : réservé à l'entreprise `maquette`. Dans la démo (`seed-demo`), les encaissements faits à
  la confirmation gardent la date du remplissage (ADR 0060).
- **Rendu** : polices hébergées dans le dépôt (Figtree, JetBrains Mono), Chromium de Playwright sous Linux ; un
  autre navigateur ou système lisse le texte autrement et change les pourcentages.

## Règles qui ne se discutent pas

1. Les textes de la maquette sont repris **mot pour mot** : aucun mot ajouté, aucune abréviation.
2. Les couleurs et les tailles viennent de `tokens.css` : aucune autre valeur en dur.
3. Tout nombre se tape librement ; les boutons rapides et les −/+ ne sont que des raccourcis.
4. Aucune cible cliquable ne fait moins de 48 px.
5. En cas de doute, la capture l'emporte sur l'interprétation.
