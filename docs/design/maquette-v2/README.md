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
| `ecarts.md` | À créer par l'agent : chaque différence voulue entre la maquette et le front, avec sa raison et l'accord du propriétaire. |

## Les données des captures

Les captures utilisent la démo « Alimentation Keur Fatou » du mardi 6 octobre 2026 à 10 h 45 : Moussa Fall doit
25 000 F, le riz est à 2 sacs, 87 500 F vendus dans la journée, etc. Le seed `maquette` (voir le prompt de phase 15)
recrée exactement ces données, pour que les captures du front et celles de la maquette soient comparables pixel par
pixel.

## Règles qui ne se discutent pas

1. Les textes de la maquette sont repris **mot pour mot** : aucun mot ajouté, aucune abréviation.
2. Les couleurs et les tailles viennent de `tokens.css` : aucune autre valeur en dur.
3. Tout nombre se tape librement ; les boutons rapides et les −/+ ne sont que des raccourcis.
4. Aucune cible cliquable ne fait moins de 48 px.
5. En cas de doute, la capture l'emporte sur l'interprétation.
