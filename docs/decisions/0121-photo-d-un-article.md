# 0121 — Photo d'un article, chez Cloudinary

- **Date** : 2026-11-11
- **Phase** : groupe 5, bloc I (prompt 36, branche `phase/36-i-photos`)
- **Statut** : acceptée (complète 0066, 0108, 0111 ; amende la CSP de 0046 et 0115)
- **Décideur** : propriétaire (Cloudinary, son compte, 11 novembre 2026) ; utilisateur via
  AskUserQuestion (envoi **par le serveur**, référence en **colonnes sur `products`**, appels
  par **httpx sans SDK**) ; plan validé avant le code

## Contexte
Un article n'avait qu'un carré coloré à initiale (ADR 0064). Le commerçant reconnaît plus
vite un article à sa photo, surtout dans la grille de vente. Les images ne vont pas en base
(poids, sauvegarde) : le propriétaire a choisi Cloudinary. Seul service externe permis pour
ce bloc.

## Options envisagées
1. **Envoi par le serveur (retenu)** : le front envoie l'image à l'API, qui la vérifie et la
   ré-encode comme le logo, puis la dépose. Le navigateur ne parle jamais à l'API Cloudinary.
2. Envoi direct signé depuis le navigateur : moins de charge sur le VPS, mais les
   métadonnées (GPS) partiraient telles quelles et `connect-src` s'ouvrirait.

Données : **colonnes sur `products` (retenu)**, lues sans jointure par le Stock et la
grille de vente ; une table `product_photos` aurait ajouté une jointure et un registre.
Appels : **httpx direct (retenu)**, trois appels documentés, aucune dépendance ; le SDK
officiel ajoutait `six`, `urllib3`, `certifi`, et sa dernière version avait moins de deux
semaines.

## Décision
**Réglages** : `COGES_CLOUDINARY_CLOUD_NAME`, `COGES_CLOUDINARY_API_KEY`,
`COGES_CLOUDINARY_API_SECRET`, les trois ou aucun (config, `check_runtime_env.py`). Sans
eux, `GET /products/photos/config` rend `{enabled: false}`, aucun bouton, aucune erreur ;
une photo déjà enregistrée n'est plus montrée (`photo: null`). Le secret ne sort jamais de
l'API. `COGES_CLOUDINARY_API_BASE` (faux Cloudinary des e2e) n'est accepté qu'en local et
en CI.

**Image** (`products/photo.py`) : type lu dans le contenu (PNG, JPEG, WebP ; SVG et le reste
refusés en 422 `photo_unsupported_format`), 5 Mo au plus reçus (413 `photo_too_large` ; la
route a son propre plafond de corps, `http_security.PHOTO_PATH`), plus de 40 Mpx refusés
sans décodage, orientation EXIF appliquée puis **toutes** les métadonnées retirées (GPS,
appareil) par ré-encodage en JPEG qualité 85, 1600 px de côté au plus, transparence sur
blanc. Le navigateur réduit déjà à 1600 px avant l'envoi (moins de données sur un réseau
lent) ; le serveur ré-encode quand même.

**Dépôt** (`core/cloudinary.py`) : `POST /v1_1/<cloud>/image/upload` signé (SHA-256 des
paramètres triés plus le secret), identifiant `coges-<env>/<entreprise>/<128 bits
aléatoires>` : jamais le nom de l'article, jamais devinable, la préproduction ne touche pas
le dossier de la production. Le dépôt se fait dans la requête, **avant** l'écriture en base ;
Cloudinary injoignable ⇒ 503 `photo_storage_unavailable`, article inchangé.

**Données** (révision 0042) : `products.photo_public_id`, `photo_version`, `photo_width`,
`photo_height`, les quatre ou aucune (`CHECK`). `ProductRead`, `ProductSummary` et les lignes
de `/inventory/stock` portent `photo` (`cloud_name`, `public_id`, `version`, dimensions).

**Routes** : `PUT /products/{id}/photo` (multipart) — `products:update`, ou `products:create`
pour un article encore sans photo (« Nouvel article ») ; `DELETE /products/{id}/photo` —
`products:update` (404 `photo_not_found` sans photo). L'article d'une autre entreprise
répond 404 avant tout (le fichier est facultatif dans la route pour cela). Audit critique de
l'ajout, du changement et du retrait (identifiants seulement, aucun octet).

**Suppression** : l'ancienne image (changée, retirée, ou article supprimé) est supprimée
par `products.delete_photo`, enfilée **après le COMMIT**, 5 nouvelles tentatives, et jamais
hors du dossier de l'entreprise. **Balayage de nuit** (`products.sweep_photos_all`, 04 h 45,
une sous-tâche par entreprise) : toute image du dossier qu'aucun article ne nomme et
déposée depuis plus de 24 h est supprimée — le dépôt d'un COMMIT refusé, une suppression
perdue quand Redis manquait.

**Affichage** : grande image sur la fiche (`c_limit`, 960 px), vignettes carrées dans la
liste du Stock et la grille de vente (`c_fill`, `f_auto,q_auto`, deux fois la taille
affichée, `loading="lazy"`), carré coloré sans photo. Pas sur les reçus. **CSP** : l'`img-src`
de l'application gagne `https://res.cloudinary.com` et rien d'autre ; la vitrine et les
textes légaux gardent une CSP sans aucun tiers (dernière règle de `next.config.ts`). Le
service worker ne garde pas les photos (autre origine, ADR 0102).

**Écrans** : champ photo (« Prendre une photo » avec `capture="environment"`, « Choisir une
image », aperçu, « Retirer ») dans « Nouvel article » (envoyé après la création ; un échec
laisse l'article), « Modifier l'article » et la fiche.

## Conséquences
- **Pas dans la sauvegarde chiffrée** (ADR 0084) : les octets sont chez Cloudinary. Une
  restauration rend les références ; les images reviennent si le compte existe toujours.
- **Compte Cloudinary perdu** : les articles restent, sans photo (les adresses ne répondent
  plus) ; retirer les trois réglages masque les images cassées. Un nouveau compte repart
  sans photo.
- **Quota** : le plan gratuit de Cloudinary compte stockage, bande passante et
  transformations ; l'API Admin (balayage) est limitée en appels par heure. À suivre dans la
  console Cloudinary (`docs/runbooks/photos.md`).
- **Sous-traitant** : Cloudinary héberge des images de la boutique ; il doit être cité dans
  la politique de confidentialité (`content/legal/confidentialite.md`, lot Pages légales,
  ADR 0117) — changer ce texte change sa version et redemande l'acceptation : à faire par
  le propriétaire, pas dans ce bloc.
- Registre d'échec au COMMIT : les deux routes y sont exemptées (service externe absent de
  cette suite) ; le COMMIT refusé est prouvé par `test_product_photos.py` (article inchangé,
  aucune suppression enfilée, image orpheline laissée au balayage).
- Tests : `tests/integration/test_product_photos.py` (faux Cloudinary qui vérifie la
  signature), `test_deploy_scripts.py`, Vitest (`lib/photo.test.tsx`, `photo-field.test.tsx`,
  `security-headers.test.ts`), e2e `photos.spec.ts` sur un faux Cloudinary local
  (`tests/helpers/fake_cloudinary.py`, lancé par `deploy/scripts/e2e.sh`).
