# Canal des mises à jour sur site (ADR 0128)

Chaque PC installé chez un client lit **un** fichier de ce dossier, sur la branche `main` :

- `stable.json` : les clients ;
- `test.json` : le PC d'essai de CoGes (`-Action Reparer -CanalMiseAJour test`).

Un fichier absent (aucune version publiée) : le PC note seulement « canal illisible » dans son
journal et réessaie plus tard. Ces fichiers ne s'écrivent **jamais à la main** : ils sortent de
`publier.py`, à partir d'une étiquette dont les images sont déjà publiées, puis entrent sur
`main` par une pull request. Marche à suivre : `docs/runbooks/sur-site.md`, « Publier une
version pour les clients ».
