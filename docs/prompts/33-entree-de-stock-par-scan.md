# Prompt 33 — Entrée de stock par scan du code-barres

Branche `feat/stock-in-scan`, depuis `main` à jour. Ajoute le scan du code-barres à l'écran **Stock → Recevoir une livraison** (`/inventory/receive`, `components/inventory/delivery-form.tsx`), qui est déjà « l'entrée de stock » de CoGes. Le scan **identifie** l'article ; seule la **validation** de la livraison augmente le stock.

Ce qui existe déjà et doit être réutilisé, pas refait :
- l'entrée de stock : `POST /api/v1/inventory/deliveries` (mouvement d'entrée, coût moyen pondéré, dette fournisseur si non payé, audit, outbox, clé d'idempotence) ;
- la création d'un article avec son stock d'ouverture en une transaction : `POST /api/v1/inventory/products` (ADR 0066) ;
- le bouton de scan `components/products/barcode-scanner.tsx` (API `BarcodeDetector` du navigateur, sinon saisie au clavier ou à la douchette), utilisé aujourd'hui par « Nouvel article » ;
- la recherche par code-barres côté serveur (`ProductRepository.get_by_barcode`, `code_matches` sur `sku` et `barcode`) ;
- les brouillons de saisie de la livraison (ADR 0101, formulaire `delivery`).

```
Lot « Entrée de stock par scan » (branche feat/stock-in-scan, depuis main à jour).
Règles habituelles : ADR au prochain numéro libre, tests d'abord (rouge puis vert), aucun
service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/.
Résumé en français à la fin, questions ouvertes par AskUserQuestion. Aucune nouvelle façon
d'écrire du stock : tout passe par la livraison existante ou la création d'article existante.

S0. Préalable : la caméra est aujourd'hui bloquée (À VÉRIFIER, test rouge d'abord)
- frontend/next.config.ts envoie `Permissions-Policy: camera=()` sur TOUTES les pages : le
  navigateur refuse alors la caméra, y compris au bouton de scan déjà présent dans « Nouvel
  article ». Prouve-le par un e2e (getUserMedia refusé sous cet en-tête), puis passe à
  `camera=(self)` (micro et position restent fermés). Vérifie le Caddyfile du VPS, qui ne
  doit pas renvoyer un autre en-tête. Dis dans l'ADR si le scan caméra de l'ADR 0066 a donc
  jamais marché en production.
- iPhone (Safari) et Firefox n'ont pas `BarcodeDetector`. DÉCISION DU PROPRIÉTAIRE : une
  bibliothèque de lecture les équipe de la caméra. Contraintes :
  * une seule bibliothèque, qui imite l'API `BarcodeDetector` (par exemple `barcode-detector`,
    moteur ZXing en WebAssembly) pour que barcode-scanner.tsx change le moins possible ;
    version figée, licence libre vérifiée, poids indiqué dans l'ADR ;
  * chargée SEULEMENT quand l'API native manque (import dynamique), jamais pour Chrome
    Android qui garde son lecteur natif ;
  * le moteur `.wasm` est SERVI PAR CoGES (copié dans le build, chemin configuré dans la
    bibliothèque) : aucun téléchargement depuis un site externe (CDN), la CSP
    `connect-src 'self'` reste telle quelle ; test qui échoue si une requête sort de
    l'origine pendant un scan ;
  * CSP : ajoute `'wasm-unsafe-eval'` à `script-src` si (et seulement si) le moteur ne
    démarre pas sans — vérifie-le d'abord par un test rouge ; jamais `'unsafe-eval'` ;
  * même règles de caméra : coupée dès que le code est lu, que la fenêtre se ferme ou que
    l'onglet est caché ; la saisie au clavier / douchette reste toujours disponible en
    secours ; un message d'aide si rien n'est lu après 10 s (« Approchez à 10-20 cm, avec
    de la lumière, ou tapez le code ») ;
  * le premier chargement du moteur affiche « Préparation de la caméra… » ; mesure son
    temps et son poids et dis-les dans l'ADR ;
  * le service worker (ADR 0102) peut garder le `.wasm` comme fichier statique versionné
    (aucune donnée) ; vérifie qu'il est bien sous `/_next/static` ou dans la pré-mise en
    cache, sinon dis-le.

S1. Backend : retrouver un article par son code
- GET /api/v1/products/by-barcode/{code} (ou un paramètre exact sur la recherche existante
  si c'est plus simple, à justifier) : correspondance EXACTE dans l'entreprise, articles
  vivants seulement, droit `inventory:read` (le scan sert l'écran Stock). Réponse : id, nom,
  rayon, unité, suivi en stock ou non, stock actuel, coût moyen actuel, dernier coût
  d'achat, prix de vente. 404 `product_not_found` si rien ; jamais d'article d'une autre
  entreprise (test de fuite inter-tenant, registre des routes de lecture).
- Normalisation du code : espaces retirés, chiffres seulement pour EAN/UPC ; un UPC-A
  (12 chiffres) et son EAN-13 (0 devant) désignent le même article ; clé de contrôle
  vérifiée, code invalide = 422 clair. Code d'un article SUPPRIMÉ : 404 avec l'indication
  `deleted_product` (l'écran le dit, sans proposer de recréer un doublon par erreur).
- Article non suivi en stock : retourné, avec `is_stock_tracked: false` ; l'écran dit qu'on
  ne reçoit pas de stock pour lui.
- Aucun changement de schéma attendu (index `products_barcode_uq` existant). Si tu en vois
  un nécessaire, demande-moi.

S2. Écran « Recevoir une livraison » : scanner
- Bouton « Scanner un article » en tête de l'ajout de lignes (grande cible, visible sur
  téléphone), à côté de la recherche par nom existante qui reste.
- Article trouvé : une ligne s'ajoute avec son nom, son stock actuel (« Il en reste 5 »),
  la quantité reçue à saisir (focus dessus, clavier numérique) et le prix d'achat prérempli
  par le dernier coût (modifiable). Le même code scanné une seconde fois AJOUTE 1 à la
  ligne existante au lieu de créer un doublon (et le dit).
- Après chaque ligne, « Scanner l'article suivant » relance la caméra : un commerçant
  reçoit souvent plusieurs articles. Caméra coupée dès que le scan aboutit, que la fenêtre
  se ferme ou que l'onglet est caché (aucune caméra qui reste allumée).
- Avant validation, un récapitulatif dit l'effet exact : « Riz 25 kg : 5 → 25 » pour
  chaque ligne. La validation reste celle d'aujourd'hui (fournisseur, payé ou non, moyen) ;
  le stock ne bouge qu'à « Valider l'entrée ». Le prix d'achat saisi est le coût de CETTE
  livraison : le coût moyen se recalcule (ex. 5 à 100 F + 20 à 120 F = 116 F), il n'écrase
  pas un « prix d'achat » de la fiche. Dis-le en une ligne à l'écran.
- Les lignes scannées entrent dans le brouillon `delivery` existant (ADR 0101) ; une
  livraison interrompue se retrouve, et rejoue avec la même clé.
- Douchette (lecteur USB ou Bluetooth qui tape le code puis Entrée) : le champ de saisie du
  bouton de scan l'accepte déjà ; vérifie que l'écran de livraison la reçoit aussi sans
  ouvrir la caméra.

S3. Article inconnu : proposer de créer sa fiche
- « Cet article n'existe pas encore. Le créer ? » avec le code scanné déjà rempli.
- Formulaire court (réutilise le formulaire de « Nouvel article », pas de copie) : nom,
  rayon, code-barres (prérempli, non modifiable sauf « Corriger le code »), prix d'achat,
  prix de vente, et « Combien en recevez-vous ? » comme stock initial. Unité par défaut.
- Création par `POST /api/v1/inventory/products` (une seule transaction, article + stock
  d'ouverture) ; puis retour à la livraison, l'article ajouté en ligne SANS compter deux
  fois la quantité : choisis UNE des deux voies et justifie-la dans l'ADR — (a) la
  quantité reçue devient le stock d'ouverture et la ligne n'est pas renvoyée dans la
  livraison, ou (b) l'article est créé à 0 et la quantité passe par la livraison (garde le
  fournisseur et la dette fournisseur). Recommandation : (b), pour la traçabilité.
- Droits : créer exige `products:create` + `inventory:create` (registre de l'ADR 0099).
  Sans ce droit : « Cet article n'existe pas. Demandez au gérant de le créer », code
  affiché pour qu'il puisse le noter ; aucune création.
- Deux personnes qui scannent le même code inconnu en même temps : la seconde création reçoit
  le 409 existant (`products_barcode_uq`) ; l'écran récupère alors l'article créé par
  l'autre et l'ajoute à la livraison.

S4. Tests (rouge d'abord)
- Backend : recherche exacte (trouvé, inconnu, supprimé, non suivi, autre entreprise,
  UPC-A = EAN-13, code invalide), droits, registre des lectures ; la livraison existante
  inchangée (tests actuels verts).
- Vitest : normalisation du code, ligne ajoutée puis incrémentée au second scan,
  récapitulatif 5 → 25, brouillon avec les lignes scannées.
- E2E (Chromium avec un faux flux caméra et un `BarcodeDetector` simulé, plus un cas
  douchette) : scan d'un article existant (stock 5, reçoit 20, après validation 25) ;
  article inconnu créé puis reçu (stock initial correct, une seule entrée) ; vendeur
  sans droit (refus clair) ; caméra coupée après le scan ; `Permissions-Policy` permet la
  caméra sur la même origine ; axe 0 violation ; 360 px sans défilement horizontal.
- Le scan de « Nouvel article » marche de nouveau (caméra) : e2e.
- Bibliothèque de lecture : e2e sous WebKit (Playwright) avec un faux flux caméra montrant un
  EAN-13 : le code est lu sans `BarcodeDetector` natif, le `.wasm` vient de la même origine,
  aucune requête externe, la CSP ne bloque rien (aucune violation dans la console).
  Chromium : la bibliothèque n'est PAS chargée (lecteur natif).
- Non automatisable : un vrai scan sur un iPhone. Liste-le dans « Ce que le propriétaire
  vérifie » avec le résultat attendu.

Fin de lot
Suite backend complète, ruff, mypy, make front-check, e2e des écrans touchés, tests de fuite
inter-tenant, CI verte. ADR : en-tête caméra, recherche exacte et normalisation, choix de la
voie de création (S3), choix pour iPhone. Mets à jour CLAUDE.md §8 et frontend/README.md.
```

## Ce que le propriétaire fait lui-même

1. Répondre à la question de l'agent sur la voie de création d'un article inconnu (recommandé : créé à zéro, puis reçu par la livraison). Pour l'iPhone, c'est décidé : bibliothèque de lecture.
2. Après le déploiement, sur un téléphone Android puis sur un iPhone : scanner un article existant (stock 5, recevoir 20 → 25), puis un article inconnu (le créer et le recevoir).
3. Autoriser la caméra quand le téléphone le demande la première fois.
