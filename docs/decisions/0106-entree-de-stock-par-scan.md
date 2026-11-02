# 0106 — Entrée de stock par scan du code-barres

- **Date** : 2026-10-31
- **Phase** : lot « Entrée de stock par scan » (prompt 33, branche `feat/stock-in-scan`)
- **Statut** : acceptée (complète 0066 et 0071)
- **Décideur** : utilisateur (bibliothèque pour l'iPhone décidée dans le prompt ; voie de
  création, chemin de la route et code d'erreur via AskUserQuestion le 2026-10-31)

## Contexte
« Recevoir une livraison » (`/inventory/receive`, ADR 0071) est l'entrée de stock de CoGes.
Le commerçant veut y scanner les articles reçus. Le bouton de scan de « Nouvel article »
(ADR 0066) existait déjà, mais :

1. **La caméra n'a jamais marché.** `frontend/next.config.ts` envoie
   `Permissions-Policy: camera=()` depuis le premier squelette du front (29/09), et le
   Caddyfile du VPS **remplace** cet en-tête par le même `camera=()` (ADR 0083). Le scan de
   l'ADR 0066 (08/10) est arrivé après : sous cet en-tête, `getUserMedia` rend
   `NotAllowedError` sans même demander à la personne (prouvé par e2e). Ni en développement,
   ni sur Vercel, ni sur le VPS, la caméra ne s'est donc jamais ouverte ; seule la saisie au
   clavier ou à la douchette servait.
2. iPhone (Safari) et Firefox n'ont pas l'API `BarcodeDetector`.

## Options envisagées
**Voie de création d'un article inconnu (S3)**
1. **(b) Créé à zéro, reçu par la livraison (retenue)** : `POST /inventory/products` sans stock
   d'ouverture, puis la quantité passe par `POST /inventory/deliveries` comme tout article.
2. (a) Quantité reçue = stock d'ouverture : une écriture de moins, mais l'entrée serait un
   mouvement `initial` sans fournisseur ni dette fournisseur, alors que c'est une livraison.

**Route de recherche (S1)**
1. **`GET /api/v1/inventory/products/by-barcode/{code}` (retenue)** : la réponse joint stock,
   coût moyen et dernière entrée, que Products (bande B) n'a pas le droit de lire ; seul
   Inventory peut composer les deux façades (ADR 0012), à côté de `POST /inventory/products`.
2. `/products/by-barcode/{code}` (chemin suggéré par le prompt) : servi par le router
   d'Inventory sous le préfixe de Products, propriété des préfixes brouillée.
3. Un paramètre exact sur `GET /inventory/stock` : écarté, la liste pagine et trie, une
   recherche exacte doit rendre un article ou un 404 parlant.

**Code d'erreur**
1. **`product_not_found` (retenu)**, comme le prompt ; le registre de fuite inter-tenant porte
   un `not_found_code` par route. Rien ne fuit : chez une autre entreprise, le code est
   simplement inconnu (`deleted_product: false`).
2. `not_found` partout, la raison dans `details.reason`.

**Lecteur pour iPhone et Firefox** : décidé par le propriétaire, une bibliothèque.

## Décision
**En-têtes.** `Permissions-Policy: camera=(self), microphone=(), geolocation=()` pour la
boutique, dans `next.config.ts` et dans Caddy. Le snippet `entetes` du Caddyfile prend
l'origine de la caméra en argument : `(self)` pour `pile` (production, préproduction et leur
page de maintenance), `()` pour les quatre portes de l'administration, qui ne scanne rien
(test de rendu `test_only_the_shop_may_open_the_camera`). La CSP du build de production gagne
`'wasm-unsafe-eval'` dans `script-src` : sans lui, le moteur ne compile pas
(`WebAssembly.instantiate() … violates … script-src 'self' 'unsafe-inline'`, prouvé sur le
build de production). Jamais `'unsafe-eval'` ; `connect-src 'self'` inchangé.

**Bibliothèque.** `barcode-detector` **3.2.2** (licence MIT, imite l'API `BarcodeDetector`) et
son moteur `zxing-wasm` **3.1.3** (MIT, ZXing-C++ en WebAssembly), versions figées. `zxing-wasm`
est déclaré directement, à la version que `barcode-detector` exige, pour que le bundler
résolve `new URL("zxing-wasm/reader/zxing_reader.wasm", import.meta.url)`.
`lib/barcode/detector.ts` rend le lecteur natif s'il existe ; sinon il charge la bibliothèque
par `import()` et lui donne, par `prepareZXingModule({ overrides: { locateFile } })`, le
chemin du moteur **copié dans le build** : `/_next/static/media/zxing_reader.<empreinte>.wasm`.
Le chemin jsDelivr par défaut de la bibliothèque n'est jamais demandé (e2e : aucune requête
hors de l'origine). Chrome Android garde son lecteur natif : ni le code de la bibliothèque ni
le moteur ne sont téléchargés (e2e).

- Poids : moteur 1 093 289 octets, **461 632 octets transférés** (compressé ; mesuré sous
  WebKit, Caddy compresse aussi `application/wasm`), code de la bibliothèque 41,7 Ko (14 Ko
  en gzip), seulement là où il sert.
- Temps : chargement et compilation du moteur 0,2 à 0,6 s en local (e2e, Chromium et
  WebKit) ; compter quelques secondes en 3G. « Préparation de la caméra… » s'affiche
  pendant ce temps.
- Service worker (ADR 0102) : le moteur est sous `/_next/static/`, donc gardé comme tout
  fichier statique versionné (aucune donnée) ; le second scan n'attend plus le réseau.

**Bouton de scan** (`components/products/barcode-scanner.tsx`, partagé) : caméra coupée dès
qu'un code est lu, que la fenêtre se ferme ou que l'onglet est caché ; conseil après 10 s
sans lecture (« Approchez à 10-20 cm, avec de la lumière, ou tapez le code ») ; le champ de
saisie (clavier, douchette) reste toujours là. La vidéo est **affichée dès la préparation** :
l'e2e WebKit a montré que WebKit ne lance pas une vidéo muette en `display: none` (`play()`
attend sans fin) ; l'ancien bouton la cachait jusqu'au démarrage, ce qui aurait bloqué
l'iPhone même avec la bibliothèque.

**Recherche exacte.** `scanned_code_candidates` (`app/core/codes.py`) : espaces retirés
partout ; EAN-8, UPC-A, EAN-13 et GTIN-14 doivent avoir une clé de contrôle juste, sinon 422
`invalid_barcode` ; un UPC-A et son EAN-13 (0 devant) sont le même code, un GTIN-14 à zéros de
tête est cherché sous ses formes courtes, un UPC-E (8 chiffres, système 0 ou 1, clé fausse en
EAN-8) aussi sous son UPC-A ; tout autre code (Code 128, référence) est cherché tel quel, et en
majuscules pour la référence. Correspondance **exacte** sur le code-barres, puis la référence,
articles vivants seulement, droit `inventory:read`. Réponse : article, rayon, unité, suivi,
stock, coût moyen, dernier coût d'entrée (`purchase_in` ou `initial` non annulée), prix de
vente. Aucun changement de schéma (index `products_barcode_uq`).

**Écran.** « Scanner un article », puis « Scanner l'article suivant » ; une ligne d'une pièce au
dernier coût, curseur sur la quantité ; le même code ajoute une pièce à sa ligne (le serveur
refuse deux lignes du même article). Article non suivi : dit, sans ligne. Article supprimé :
dit, sans proposer de recréer. La douchette tape dans la recherche puis Entrée : même
recherche exacte, sans caméra. Récapitulatif « Riz 25 kg : 5 → 25 » avant la validation, et
une ligne qui dit que le prix tapé est celui de la livraison (le coût moyen se recalcule, la
fiche ne change pas). La validation reste « Enregistrer la livraison » (le « Valider
l'entrée » du prompt), seule écriture du stock. Les lignes scannées vont dans le brouillon
`delivery` (ADR 0101) ; un article créé ici et encore jamais entré est relu par sa fiche à la
reprise.

**Article inconnu (voie b).** « Cet article n'existe pas encore. Le créer ? » ouvre le
formulaire de « Nouvel article » en mode réception (`NewProductForm intake`, pas de copie) :
code prérempli (« Corriger le code »), nom, rayon, prix d'achat et de vente, « Combien en
recevez-vous ? », unité par défaut, sans brouillon propre. L'article naît avec
`opening_qty = 0` ; la quantité et le prix deviennent la ligne de la livraison. Sans
`products:create` + `inventory:create` : « Demandez au gérant de le créer », code affiché.
Deux créations du même code : la seconde reçoit 409 `product_barcode_taken`, l'écran relit
l'article de l'autre et l'ajoute.

## Conséquences
- `ProductSummary` porte `barcode` (lecture) ; façade `products_service.find_by_code` et
  `code_was_deleted` ; `InventoryMovementRepository.last_entry_cost`.
- Registre de fuite : la route entre dans `CROSS_TENANT_ROUTES`, Beta reçoit un code propre
  (les EAN internes `2000…` se répètent d'une entreprise à l'autre).
- `playwright.pwa.config.ts` joue aussi `scan-library.spec.ts`, sous Chromium et **WebKit**
  (vert le 2026-10-31). WebKit exige `libavif16` sur le poste
  (`sudo pnpm exec playwright install-deps webkit`).
- Non automatisable : un vrai scan sur un iPhone et sur un Android (voir le résumé du lot).
