# Photos des articles (Cloudinary)

Les photos des articles sont stockées chez Cloudinary, sur le compte du propriétaire
(ADR 0121). L'API reçoit l'image, la nettoie (GPS et métadonnées retirés, 1600 px au plus)
et la dépose ; le navigateur ne parle jamais à l'API Cloudinary, il lit seulement les images
de `res.cloudinary.com`. Sans compte configuré, la photo est simplement indisponible.

## 1. Créer le compte et noter ses identifiants

Sur cloudinary.com, créer le compte (le plan gratuit suffit au lancement), puis dans
**Settings → API Keys** noter :

- le *cloud name* (en haut du tableau de bord) ;
- l'*API key* (chiffres) ;
- l'*API secret* — **ne jamais le coller dans une conversation ni dans git**.

## 2. Les poser dans `/etc/coges/coges.env` (production)

```bash
COGES_CLOUDINARY_CLOUD_NAME=<cloud name>
COGES_CLOUDINARY_API_KEY=<api key>
COGES_CLOUDINARY_API_SECRET=<api secret>     # SECRET
```

Les trois ensemble, ou aucun : `check_runtime_env.py` refuse une pile à moitié configurée.
L'API (dépôt) et le worker (suppression, balayage) les reçoivent par
`deploy/vps/docker-compose.yml`. Redéployer. La préproduction peut partager le compte :
chaque environnement a son dossier (`coges-production/…`, `coges-staging/…`).

## 3. Vérifier après le déploiement

Sur un téléphone : fiche d'un article → « Prendre une photo » → la photo s'affiche sur la
fiche, puis en petite vignette dans la grille de vente (Vendre). Dans la console
Cloudinary, l'image est dans `coges-production/<identifiant de l'entreprise>/`, sous un nom
aléatoire.

## 4. Surveiller le quota

Console Cloudinary → **Usage** : stockage, bande passante et transformations du mois. Le
plan gratuit est mesuré en « crédits » ; une alerte d'usage peut être posée dans les
réglages du compte. Le balayage de nuit fait un appel à l'API Admin par entreprise
(04 h 45) : surveiller la limite horaire de l'API Admin du plan si les boutiques se
comptent en centaines.

## 5. Ce qui n'est pas sauvegardé, et que faire si le compte est perdu

- Les photos **ne sont pas dans la sauvegarde chiffrée** (`docs/runbooks/sauvegarde.md`) :
  seules leurs références (colonnes `photo_*` de `products`) le sont.
- Compte perdu ou fermé : les articles restent, sans photo (les adresses ne répondent plus).
  Vider les trois réglages et redéployer masque les images cassées (`photo` à `null`). Avec un
  nouveau compte, les commerçants reprennent leurs photos.
- Une image orpheline (article supprimé pendant une panne de Redis, dépôt dont la
  transaction a échoué) est supprimée par le balayage de nuit après 24 h.

## 6. Données personnelles

Cloudinary est un **sous-traitant** : il héberge des images de la boutique. Le citer dans
la politique de confidentialité (`frontend/content/legal/confidentialite.md`) ; changer ce
texte change sa version et redemande l'acceptation à chacun
(`docs/runbooks/textes-legaux.md`).
