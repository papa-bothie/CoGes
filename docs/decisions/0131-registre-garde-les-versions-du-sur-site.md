# 0131 — Le registre garde les versions du sur-site

- **Date** : 2026-11-24
- **Phase** : correctif de production (`fix/registre-versions-sur-site`), amende 0087 (P1.2)
- **Statut** : acceptée
- **Décideur** : utilisateur (demande du correctif : canaux + trois dernières vX.Y.Z, règle
  des SHA inchangée)

## Contexte

Le ménage du registre (`deploy/scripts/registry_cleanup.py`, ADR 0087) gardait `production`,
`production-previous` et **une seule** autre version (`KEEP_LATEST = 1`). La production n'est
pas encore ouverte : aucune image ne porte `production`. La pose de l'étiquette v0.4.1
(23/11/2026) a donc supprimé v0.4.0 de `front`, `api`, `worker` et `bundle` (constaté le
24/11/2026 par la liste anonyme des étiquettes de ghcr.io : seules v0.4.1 et son SHA restent ;
`admin` garde v0.3.0 et v0.4.0, à regarder dans le journal du job `cleanup`).

Le sur-site (ADR 0124 à 0129) dépend pourtant de versions qui ne sont ni la production ni la
dernière préproduction :

- le PC d'essai ne peut plus installer v0.4.0 (`-Version v0.4.0`), ni rejouer le passage
  v0.4.0 → v0.4.1 du canal `test` ;
- chez un client, la version publiée sur `stable.json` aurait disparu à l'étiquette suivante :
  une réinstallation, un `Reparer` ou un PC neuf échoueraient au `docker pull`.

La raison de `KEEP_LATEST = 1` était le quota gratuit de 500 Mo (ADR 0087, « pas d'images
publiques »). Les paquets sont publics depuis (vérifié : `GET /v2/papa-bothie/coges/<paquet>/tags/list`
répond sans compte pour les cinq paquets ; le dépôt est public). La documentation GitHub
(lue le 24/11/2026, page sans date) :

- « GitHub Packages usage is free for public packages. » ;
- « For private repositories, each GitHub account receives a quota of storage and data
  transfer for use with GitHub Packages, depending on the account's plan. » (500 Mo et 1 Go
  pour GitHub Free, par compte, partagés avec les artefacts d'Actions) ;
- « Container image storage and bandwidth for the Container registry is currently free. If
  you use Container registry, you'll be informed at least one month in advance of any change
  to this policy. »

Sources : <https://docs.github.com/en/billing/concepts/product-billing/github-packages>
(même texte sous `…/managing-billing-for-github-packages/about-billing-for-github-packages`).

## Options envisagées

1. **Protéger les canaux et les trois plus hautes vX.Y.Z, SHA inchangés (retenue)** : ce que
   les PC tirent reste toujours ; quelques versions de plus, gratuites tant que les paquets
   sont publics.
2. Tout garder : le registre grossit sans fin, et rien ne dit plus ce qui compte.
3. Garder seulement les canaux : le PC d'essai et la préproduction d'une version qui n'est
   pas encore sur un canal restent exposés (le cas de v0.4.0 aujourd'hui : `test.json` n'est
   pas encore sur `main`).

## Décision

`plan()` ne supprime jamais :

- `production` ni `production-previous` (inchangé), ni une version sans étiquette (inchangé) ;
- une version dont l'étiquette **ou** l'un des digests est cité par
  `deploy/onprem/canal/stable.json` ou `test.json` **de `main`** (les PC tirent par digest,
  ADR 0128 : le digest protège même si l'étiquette a bougé) ;
- les **trois plus hautes vX.Y.Z** par ordre des numéros (pas par date : une version
  reconstruite plus tard ne chasse pas une plus récente ; une préversion `-rc` passe avant sa
  version), qu'elles soient aussi protégées ailleurs ou non.

Les versions sans étiquette vX.Y.Z (SHA de préproduction) gardent la règle actuelle : la plus
récente reste, les autres partent ; une vX.Y.Z ne lui prend plus sa place.

Le job `cleanup` lit les canaux par `git fetch origin main` (quelle que soit la ref du
déclenchement) et les passe par `--channel`. Un canal **absent** ne protège rien ; un canal
**illisible** (JSON faux, format autre que `COGES-CANAL-1`, version ou digest mal formés)
fait sortir le plan en 1 **sans rien écrire** : le job échoue et rien n'est supprimé
(`pipefail`).

## Conséquences

- `deploy/scripts/registry_cleanup.py` (`KEEP_RELEASES = 3`, `Channels`, `read_channels`,
  `PackageVersion.digest` lu dans `name`), `.github/workflows/deploy.yml` (étape « Canaux du
  sur-site (main) »), `backend/tests/unit/test_registry_cleanup.py` (le cas v0.4.0/v0.4.1,
  ordre des numéros, préversion, canal par étiquette et par digest, deux canaux, SHA à côté
  des versions, production hors des trois places, canal absent, six canaux illisibles sans
  sortie, forme réelle de l'API, canaux versionnés lisibles).
- `deploy/README-infra.md` (« Registre d'images ») et `docs/runbooks/sur-site.md` mis à jour.
- Si GitHub fait payer le registre (préavis d'un mois annoncé) ou si les paquets redeviennent
  privés, le compte est d'environ 490 Mo par version : revoir `KEEP_RELEASES` à ce moment.
- **Reconstruire v0.4.0** (après fusion) : « Déployer » à la main depuis `main`, cible
  `preprod`, version `v0.4.0`. `decide` la reconstruit (absente) depuis son étiquette git ;
  le ménage qui suit garde v0.4.1 et v0.4.0 (deux des trois plus hautes, et v0.4.1 citée par
  `test.json` une fois sur `main`). Tant que cette branche n'est pas fusionnée, ne lancez
  aucun déploiement : l'ancien ménage supprimerait v0.4.1 à son tour.
- Non vérifié en vrai sur GitHub : le premier passage du job dira, dans son résumé, les
  canaux lus et les versions supprimées.
