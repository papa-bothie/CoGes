# Phase 15 — Simplicité d'abord : bugs, formulaires courts, refonte visuelle

> Prompt à coller dans l'agent. Il s'appuie sur des retours d'usage réels : CoGes doit être utilisable par
> un commerçant qui n'a pas fait d'études. Chaque écran doit se comprendre sans lire et chaque action se faire
> en quelques touches. La maquette validée par le propriétaire du produit (26 écrans : tous les parcours du
> logiciel, reçus compris) est décrite écran par écran au lot 3 : c'est la référence visuelle. Le style est validé ;
> il s'applique à **toutes** les fonctionnalités, sans exception.

## Règles de travail (inchangées)

- Lis `CLAUDE.md`, `DESIGN.md`, `PRODUCT.md` et les ADR 0001 à 0060 avant de commencer.
- **Un lot = une branche = une PR.** L'ordre est imposé : lot 0 (bugs), lot F (fondations visuelles), puis
  lots 1, 2, 3. Ne passe pas au lot suivant tant que la CI du précédent n'est pas verte.
- Chaque décision structurante a son ADR (numéros à partir de **0061**). Toute question de produit passe par
  `AskUserQuestion`, jamais par une supposition.
  *Note des lots 0 et F : 0063 a servi à la liste de clients de la vente (B3), 0064 au thème
  de la maquette v2 et 0065 à l'heure figée et au seed de la maquette ; les ADR nommés plus bas
  sont décalés de trois rangs (« Références et codes-barres générés » = 0066, « Raisons de
  correction en liste fermée » = 0067). Au lot 1, 0068 a servi à Wave et Orange Money : la
  refonte visuelle devient 0069.*
- **Invariants à ne jamais casser :** RLS FORCE et rôles séparés, Idempotency-Key sur les écritures
  financières, annulation par contre-écriture, outbox, garde du dernier gérant.
- Aucun service payant sans mon accord explicite. Ne commite jamais `.env` ni `.env.bak`.
- Captures avant/après de chaque écran touché, en clair et en sombre, dans
  `docs/design/captures/phase-15/{avant,apres}/{light,dark}/`.
- L'interface reste en français, sans abréviation (voir le lexique du lot 2).

---

## Suivre la maquette à la lettre (méthode imposée)

La maquette est livrée dans `docs/design/maquette-v2/`. Lis d'abord `README.md`, `ecrans.md` et `tokens.css` de ce
dossier. Pour chaque écran, trois références :

- la **capture** à 1280 px et à 390 px (`captures/`) : c'est la cible ;
- la **page statique** (`html/`) : ouvre-la et inspecte-la pour lire chaque valeur CSS exacte ;
- le **source** (`source/*.dc.html`) : textes, données d'exemple et logique de chaque état, dans le bloc `<script>`.

Six règles :

1. **Rien n'est inventé.** Les textes sont copiés mot pour mot ; l'ordre des éléments, les couleurs, les tailles et
   les rayons sont ceux de la maquette. Si le backend ne permet pas un élément, tu poses la question par
   `AskUserQuestion` au lieu de t'écarter. Chaque écart accepté est noté dans `docs/design/maquette-v2/ecarts.md`
   (écran, différence, raison, date de l'accord).
2. **Jetons d'abord.** Les valeurs de `tokens.css` deviennent le thème Tailwind et `DESIGN.md`. Un test
   d'architecture interdit toute couleur en dur hors du thème dans `frontend/app` et `frontend/components`.
3. **Composants ensuite**, chacun comparé à sa capture avant d'être utilisé dans un écran :
   - barre du haut et barre basse sur téléphone ;
   - tuile chiffrée, carte, bouton (principal 68 px, standard 56 px, secondaire bordé) ;
   - puce (sélectionnée ou non, couleur de la rubrique) et grand choix exclusif ;
   - **champ montant + pavé numérique** ;
   - champ quantité (− champ +) ;
   - pastille d'état (Payé, Reste X F, Retour, Annulée), ligne de liste avec avatar, carré d'article à initiale ;
   - tuile de choix avec icône (raisons, catégories de dépense) ;
   - bandeau et écran de succès, message d'aide sous un champ ;
   - barres de graphique avec valeurs, interrupteur.

   Une page interne `/dev/composants`, en développement seulement et sans permission, les montre tous.
4. **Mêmes données que la maquette.** Ajoute `make seed-maquette`, qui recrée exactement les données des captures :
   Alimentation Keur Fatou, mêmes articles, clients, montants, stocks et dettes, au mardi 6 octobre 2026 à 10 h 45.
   Pour figer l'heure en test, ajoute un réglage `COGES_FROZEN_NOW`, refusé au démarrage si
   `COGES_ENV=production` (ADR), et utilise `page.clock` côté Playwright.
5. **Comparaison automatique.** `frontend/e2e/maquette.spec.ts` parcourt `ecrans.md` ligne par ligne :
   - il ouvre la route avec le seed `maquette`, reproduit l'état (mêmes clics, mêmes saisies) et capture à 1280 et
     390 px ;
   - il compare l'image à la capture de référence avec `pixelmatch` et écrit
     `docs/design/captures/phase-15/comparaison/NN-nom.png` (maquette | front | différences en rouge), plus un
     tableau `comparaison.md` avec le pourcentage de différence ;
   - seuil : **2 % de pixels différents au plus**, sauf écran listé dans `ecarts.md`. Au-delà, le test échoue.

   Ajoute `make maquette-check` pour le lancer.
6. **Validation humaine.** Chaque PR du lot 3 contient le tableau de comparaison et les images à trois panneaux des
   écrans touchés. Le propriétaire valide avant la fusion.

Le logo officiel est dans `docs/design/maquette-v2/logo/` :

- barre du haut : symbole (40 × 43 px) + nom « CoGes » (hauteur 24 px) + nom de la boutique dessous ;
- écran de connexion : logo complet avec « Votre entreprise sous contrôle » ;
- favicon et icône d'application : le symbole ;
- bas du ticket et de la facture : « Reçu édité avec CoGes ».

Tout carré vert avec un « C » disparaît. Les verts du thème viennent du logo : `#024A2C` (marque), `#117A3C`
(boutons), `#1A9A4C` (graphiques).

Le mode sombre n'est pas dans la maquette : dérive-le des jetons, montre les captures sombres au propriétaire et
attends son accord avant de le livrer.

## Lot F — Fondations visuelles, juste après le lot 0 (branche `feat/phase15-foundations`)

Avant tout écran :

- jetons ;
- police Figtree (`next/font/google`) ;
- logo et favicon ;
- les composants de la règle 3 ;
- `/dev/composants` ;
- le seed `maquette` et `COGES_FROZEN_NOW` ;
- `maquette.spec.ts` (il échouera sur les écrans pas encore faits : marque-les `test.fixme` avec le lot prévu).

Les lots 1, 2 et 3 n'utilisent que ces composants.

## Lot 0 — Trois bugs constatés (branche `fix/phase15-bugs`)

### B1. Le CA du jour, le CA du mois, la marge et le graphique ne bougent pas après une vente

**Cause constatée dans le code :**

- `dashboard._compose` lit `analytics_service.daily_revenue_and_margin`, c'est-à-dire la table
  `daily_sales_facts`.
- Cette table n'est reconstruite que par la tâche Celery `analytics.rebuild_sale_day`.
- Cette tâche ne reçoit l'événement `sale.confirmed` que si **le relais d'outbox** (`make relay`) **et** le worker
  tournent.
- En local, le relais n'était pas lancé. En préprod, tout dépend du Docker zone B allumé sur le PC du gérant.
- S'ajoute le cache Redis de 60 s, invalidé lui aussi par le worker.

Résultat : sans relais, le CA ne bouge jamais. Avec relais, il bouge avec un délai. Le nombre de ventes et la liste
« Dernières ventes » sont justes, puisqu'ils lisent `sales` directement, ce qui rend l'incohérence encore plus visible.

**Correction attendue (ADR 0061 « Le jour en cours est calculé en direct ») :**

1. **Aujourd'hui en direct.**
   - Ventes du jour et marge du jour : calcule-les directement depuis `sales` et `sale_items` du jour (index
     `company_id, status, sold_at`), avec le coût figé à la vente et les retours rattachés au jour de la vente,
     comme au § 4.10.
   - Mois en cours et courbe : utilise les faits jusqu'à **hier**, plus le jour en cours calculé en direct.
   - Garde la cible de moins de 200 ms et vérifie-la avec `make test-perf`.
2. **Invalidation synchrone.** Après le COMMIT d'une vente, d'une annulation, d'un retour, d'un paiement ou
   d'une dépense, l'API vide elle-même la clé `dashboard` de l'entreprise. L'invalidation par le worker reste
   en filet de sécurité.
3. **Retard visible.**
   - Si des événements d'outbox attendent depuis plus de 2 minutes, le tableau de bord du gérant affiche un
     bandeau neutre : « Certains chiffres se mettent à jour, patientez une minute. »
   - Pour savoir si des événements attendent, réutilise `GET /api/v1/system/outbox`, qui existe déjà.
4. **Démarrage local en une commande.** Ajoute `make dev`, qui lance API, worker, relais et front ensemble :
   un `Procfile.dev` avec `honcho` en dépendance de dev, sans service payant. Le terminal doit indiquer clairement
   chaque processus. Mets à jour `frontend/README.md` et la section « Tester en local ».
5. Mets à jour `deploy/README` : en préprod, le relais et le worker du Docker zone B doivent tourner, sinon les
   indicateurs analytiques prennent du retard.

**Tests :**

- *pytest :* confirmer une vente puis appeler `GET /dashboard` **sans worker ni relais** doit renvoyer un
  `revenue_today` qui inclut la vente. Même chose pour l'annulation et le retour.
- *e2e :* vendre 2 articles, revenir à l'accueil, et le montant « Vendu aujourd'hui » a augmenté du total.

### B2. Régler une dette ne fait pas passer la vente de « Reste dû » à « Payé »

**Cause constatée :**

- `sales.paid_total` est maintenu par le trigger `sale_paid_rollup` (migration 0006). Ce trigger n'additionne que
  les `payments` dont `sale_id` est renseigné.
- Un règlement de dette passe par `payment_allocations` sur la dette (`debts.sale_id`) : le paiement n'a pas de
  `sale_id`.
- Donc `balance = total - paid_total` ne bouge jamais, alors que la dette, elle, est bien soldée.

**Correction attendue (ADR 0062 « Ce qui reste dû sur une vente suit sa dette ») :**

- Migration 0014. `paid_total` d'une vente devient la somme de deux montants :
  - les paiements directs (`payments.sale_id`, entrées) ;
  - les lettrages sur les dettes de cette vente (`payment_allocations` → `debts.sale_id`).
- Ajoute un trigger sur `payment_allocations` (insertion, mise à jour, suppression) qui recalcule la vente
  concernée.
- Gère l'annulation de paiement (contre-écriture, ADR 0038), les retours et la compensation (ADR 0024).
- Pas de double comptage : l'acompte encaissé à la vente a déjà un `sale_id` et n'est jamais lettré sur la dette
  créée pour le solde. Vérifie-le avec un test.
- Backfill dans la migration, puis contrôle : pour toute vente avec dette, `total - paid_total = debts.balance`.
- Liste des ventes et fiche vente : badge **« Payé »** (vert) ou **« Reste 10 000 F »** (orange). Plus de colonne
  « Reste dû » à 0 pour une vente soldée.

**Tests :**

- *pytest :* paiement partiel, puis règlement du solde, puis annulation du règlement ; avec deux dettes lettrées
  par un seul paiement ; avec un retour compensé.
- *e2e :* vendre à crédit, encaisser la dette dans Finance, et la vente apparaît « Payé » dans la liste.

### B3. Dans « Nouvelle vente », la liste des clients est coupée

**Cause constatée :**

- La liste déroulante de `SearchCombobox` est en `position:absolute` à l'intérieur d'une `Card` shadcn qui a
  `overflow-hidden` : elle est rognée par la carte.
- `searchCustomers` ne demande que 8 clients (`page_size: 8`), sans téléphone affiché.

**Correction attendue :**

- La liste s'affiche dans une couche au-dessus de la page (Popover Radix ou portail), jamais rognée.
- Champ vide : on voit **tous** les clients, avec défilement, dans cet ordre :
  1. « Client de passage » ;
  2. les clients récents ;
  3. l'ordre alphabétique.
- Chaque ligne montre un avatar (initiales), le nom, le téléphone et « Doit X F » si le client a une dette.
- Lignes de 64 px de haut, `page_size` 50 avec chargement au défilement.
- Bouton « Nouveau client » en bas de la liste. Il ouvre le formulaire court du lot 1, puis revient à la vente avec
  le client choisi.

**Tests :**

- *Vitest :* le popover n'est pas un descendant d'un élément `overflow:hidden`.
- *e2e :* avec 30 clients, le 30ᵉ est visible après défilement et peut être choisi.

---

## Lot 1 — Formulaires courts, zéro saisie inutile (branche `feat/phase15-forms`)

### Règle de saisie libre (s'applique à tout le logiciel)

Tout champ qui attend un nombre (montant, quantité, prix, seuil, remise, nombre d'étiquettes) se **tape librement** :

- un vrai `<input inputmode="numeric">` en gros caractères : clavier chiffres sur tablette et téléphone, clavier
  physique sur ordinateur ;
- les boutons rapides (« Tout : 25 000 F », « La moitié », « Le compte juste », « 10 000 ») et les compteurs −/+ ne
  sont que des **raccourcis** qui remplissent ce champ ; ils ne remplacent jamais la saisie ;
- pour les montants d'argent, un **pavé numérique à l'écran** (1 à 9, 000, 0, effacer) sous le champ, pour les
  tablettes sans clavier ;
- validation immédiate et en clair sous le champ : « Il restera 4 000 F à payer », « C'est plus que ce qu'il doit
  (25 000 F) », « C'est le total : choisissez Tout payé ». Le bouton de validation reste grisé tant que le montant
  n'est pas valable.

Cela concerne au minimum :

- paiement partiel à la vente et monnaie donnée par le client ;
- encaissement de dette, paiement fournisseur, remboursement d'un retour, dépense ;
- livraison (quantité et prix d'achat) et correction de stock ;
- quantité d'une ligne du panier et remise sur une ligne ;
- prix de l'article, seuil d'alerte et nombre d'étiquettes.

Principe : **on ne demande que ce que le commerçant sait déjà, le reste est déduit ou généré.** Plus aucun texte
explicatif sous les champs (supprime tous les `*Hint` des formulaires). Les champs avancés passent dans un repli
« Plus d'infos » fermé par défaut, sur la fiche détail et non à la création.

### Article (ADR 0063 « Références et codes-barres générés »)

**Référence et code-barres :**

- `sku` devient facultatif dans `ProductCreate`. Le serveur attribue `ART-0001`, `ART-0002`… par entreprise, sur le
  même modèle que `CLI-0001` des clients : une séquence par tenant, sûre en concurrence.
- Sans code scanné, le serveur génère un **EAN-13 interne**, préfixe 2 (plage réservée à l'usage en magasin), clé
  de contrôle valide et unique par entreprise. Un code fabricant scanné reste prioritaire.
- Ajoute un bouton « Imprimer l'étiquette » sur la fiche article (code-barres, nom et prix) : une page imprimable,
  sans service externe.

**Le formulaire de création n'a plus que ces champs :**

| Champ | Saisie |
|---|---|
| Nom de l'article | texte |
| Prix de vente (F) | nombre |
| Prix d'achat (F) | nombre ; ligne en direct sous les prix : « Vous gagnez 1 500 F sur chaque sac » (vert), ou « Attention : vous perdez … » (orange) |
| Vendu par | puces : Pièce, Sac, Kg, Litre, Carton, Paquet, Bouteille. `ProductUnit` ne connaît que piece, kg, litre, carton, metre, paquet : ajoute `sac` et `bouteille` (Literal et contrainte en base, migration) |
| Rayon | puces des catégories + « Nouveau rayon » |
| Combien en avez-vous ? | nombre tapé librement, avec −/+ autour ; crée le mouvement `initial` |
| Me prévenir quand il en reste | nombre tapé librement, avec −/+ ; = `reorder_point` |
| Bouton « Scanner le code-barres » (facultatif) | utilise la caméra si elle est disponible, sinon saisie au lecteur |

- **Disparaissent de la création :** SKU, code-barres en saisie libre, TVA (on prend le taux par défaut de
  l'entreprise), « Suivi du stock » (toujours actif), « Actif » (toujours actif).
- La photo d'article n'existe pas côté backend : stockage nécessaire, peut-être payant. Ne l'implémente pas.
  Pose la question par `AskUserQuestion` en fin de lot.

### Client et fournisseur

- Un seul écran « Ajouter une personne » avec deux gros boutons : **Un client** (violet) / **Un fournisseur** (bleu).
- Champs : **Nom** et **Téléphone**, avec le préfixe `+221` affiché et le format `77 000 00 00`.
- **Le code n'est plus affiché ni saisi.** Le serveur l'attribue déjà : retire simplement le champ du formulaire.
- **Retire « Encours autorisé »** du formulaire client et **« Délai de paiement en jours »** du formulaire fournisseur.
  Les colonnes restent en base (nulles = pas de limite). Retire aussi leurs colonnes des listes.
- L'e-mail passe dans « Plus d'infos » sur la fiche détail.

### Corriger le stock (ADR 0064 « Raisons de correction en liste fermée »)

- Écran : on choisit l'article dans une liste. Les articles bientôt épuisés sont en tête, en orange, avec la quantité.
- Grande carte : « Le logiciel compte 2 sacs ».
- Deux gros boutons : « Dans la boutique, il y en a **Plus** / **Moins** ».
- Quantité tapée librement (−/+ autour), et aperçu en direct : « Après : 1 sac ».
- **Pourquoi ?** en tuiles avec icône, jamais au clavier :
  - Moins : Abîmé ou cassé, Périmé, Perdu ou volé, Pris pour la maison, Erreur de comptage.
  - Plus : Erreur de comptage, Retrouvé, Cadeau du fournisseur.
- Backend :
  - nouvelle colonne `reason_code` (enum fermé) sur les mouvements de stock, migration ;
  - le `type` se déduit de la raison : abîmé, périmé, perdu, maison → `loss` ; le reste → `adjustment` ;
  - `note` n'est plus obligatoire : `TYPES_REQUIRING_NOTE` est remplacé par « `reason_code` obligatoire pour
    `adjustment` et `loss` » ;
  - le coût unitaire est caché (coût moyen courant) et la date vaut « maintenant », cachée.
- La réception fournisseur reste un parcours à part (bouton « Recevoir une livraison »).
- Le journal des mouvements affiche la raison en toutes lettres.

### Paiements et règlements

- Retire **« Référence »** et **« Note »** de tous les dialogues de paiement, de règlement de dette et de dépense.
  Les champs restent facultatifs dans l'API.
- Montant : champ libre + pavé numérique, avec les raccourcis « Tout : 25 000 F » et « La moitié ». Le client paie
  la part qu'il veut, de 1 F jusqu'au total dû.
- Moyen de paiement en grosses puces. **Pose la question par `AskUserQuestion` :** faut-il distinguer **Wave** et
  **Orange Money** au lieu de « Mobile money » ? Si oui : ADR, migration de l'enum `payment_method` (ou colonne
  `provider`), rapports regroupés.

**Tests :** pytest pour chaque génération (concurrence de séquence SKU, validité EAN-13), Vitest pour chaque
formulaire, e2e « créer un article en moins de 8 touches ».

---

## Lot 2 — Mots simples (branche `feat/phase15-wording`)

Remplace dans `lib/labels.ts`, les en-têtes de tableaux, les exports et les notifications :

| Avant | Après |
|---|---|
| CA, CA net | Ventes, Vendu |
| CMP, Valeur au CMP | Prix d'achat moyen, Valeur du stock |
| Coût des ventes | Prix d'achat des articles vendus |
| Marge brute, Marge estimée | Gagné sur les ventes |
| Résultat estimé | Gagné (ou Perdu) |
| Encaissements / Décaissements | Entré dans la caisse / Sorti de la caisse |
| Trésorerie nette | Différence |
| Créances clients ouvertes | Les clients vous doivent |
| Dettes fournisseurs ouvertes | Vous devez aux fournisseurs |
| SKU | Référence (visible seulement dans « Plus d'infos ») |
| N° | Vente n° |
| Motif | Pourquoi ? |
| Mouvement de stock manuel | Corriger le stock |
| Échéance | À payer avant le |
| Client anonyme (liste des ventes, reçu) | Client de passage (même mot que le choix du client, B3) |

Supprime tous les sous-titres explicatifs qui décrivent un calcul, par exemple « Prix de vente − coût moyen
pondéré », « Mouvements réels de caisse, compensations… » ou « À l'instant, toutes périodes confondues ». Une
formule ne s'explique pas en texte : elle se montre (voir l'équation de « L'argent »).

Tests : un test d'architecture interdit les termes de la colonne « Avant » dans `labels.ts`, sauf dans une liste
d'exceptions commentée.

---

## Lot 3 — Refonte visuelle « chaleureuse et colorée » (branche `feat/phase15-visual`, ADR 0065)

Le lot est gros : découpe-le en **cinq PR** dans cet ordre, chacune avec ses captures avant/après :

- 3a : système et navigation, puis Vendre (écrans 1, 2, 8 à 11) ;
- 3b : Stock (écrans 4, 6, 12 à 15) ;
- 3c : Clients et fournisseurs (écrans 5, 16 à 18) ;
- 3d : Argent (écrans 3, 7, 19 à 21) ;
- 3e : Conseils, Alertes, Réglages, Connexion et téléphone (écrans 22 à 26).

### Système (mettre à jour `DESIGN.md` et les jetons Tailwind)

**Fond et forme :**

- Fond de page `#FBF8F3` (papier chaud) ; cartes blanches, bordure `#ECE6DC`, rayon 22 px.
- Police **Figtree** via `next/font/google`, 400 à 800. Texte de base 16 px, libellés 17 px gras, chiffres
  28 à 52 px gras en chiffres tabulaires. Aucun texte sous 15 px.

**Une couleur par rubrique** (solide / teinte / encre sur teinte) :

| Rubrique | Solide | Teinte | Encre sur teinte |
|---|---|---|---|
| Ventes | `#0B7A53` | `#E6F4EC` | `#075C3E` |
| Stock | `#C2410C` | `#FFF0E3` | `#9A3412` |
| Argent | `#1F5BD8` | `#EAF1FD` | `#1747AE` |
| Clients / dettes | `#6D3FC8` | `#F2ECFC` | `#5530A3` |
| Dépenses / danger | `#A51D24` | `#FDECEC` | — |

- Le mode sombre est dérivé de ces couleurs. Vérifie un contraste d'au moins 4,5:1 pour tout texte avec le test axe
  existant.

**Interaction et navigation :**

- Cibles tactiles de **48 px minimum** partout (on remonte le seuil de l'ADR 0059). Boutons d'action principale :
  64 à 68 px.
- Navigation : cinq entrées avec icône **et** mot : **Accueil, Vendre, Stock, Clients, Argent**. À droite de la
  barre : « Conseils » (ampoule), la cloche des alertes avec son compteur, l'engrenage des Réglages. Sur téléphone,
  les cinq entrées passent en barre fixe en bas de l'écran. Pour le rôle vendeur, seuls Accueil, Vendre et Clients
  sont visibles.
- Badge rouge de notification : affiché seulement s'il y a une alerte non lue de gravité haute.

### Écrans (reproduire fidèlement)

1. **Accueil**
   - « Bonjour Fatou » et la date, avec un très gros bouton vert « Nouvelle vente ».
   - Quatre tuiles colorées cliquables :
     - Vendu aujourd'hui (+ nombre de ventes), vert ;
     - Dans la caisse, bleu ;
     - Les clients vous doivent (+ nombre de clients), violet ;
     - Stock à surveiller (+ nombre d'articles), orange.
   - Barres « Vos ventes des 7 derniers jours » : valeur écrite au-dessus de chaque barre, jour en dessous,
     aujourd'hui en vert foncé, les autres en vert clair, total à droite du titre.
   - Carte « À surveiller » : articles bientôt épuisés et plus grosse dette ancienne.
   - « Dernières ventes » : avatar, nom, heure, montant, badge « Payé » ou « Reste X F ».
2. **Nouvelle vente**, pensée caisse, aucune saisie clavier nécessaire.
   - À gauche :
     - recherche « Chercher un article ou scanner son code » ;
     - puces de rayons ;
     - **grille de tuiles d'articles** : carré coloré avec l'initiale, nom, prix, « Plus que 2 sacs » en orange
       si stock bas, pastille de quantité si l'article est déjà dans le panier. Toucher la tuile ajoute 1.
   - À droite, le ticket :
     - bloc Client : « Client de passage » par défaut, « Changer » ouvre la liste du B3 ;
     - lignes avec −/+ de 48 px et la quantité tapable au milieu ;
     - sous chaque ligne, « Faire une remise » ouvre un champ en francs (la remise par ligne existe déjà dans l'API :
       `discount`) ;
     - **Total** en 36 px sur fond vert clair.
   - « Le client paie » avec trois gros boutons, et en dessous Espèces / Wave / Orange Money (ou Mobile money
     selon la réponse du lot 1) :
     - **Tout payé**, en espèces : rendu de monnaie avec « Le compte juste / 10 000 / 20 000 / 50 000 » ou
       « Autre montant » tapé, puis « À rendre : X F » ;
     - **Une partie** : champ libre + pavé numérique (raccourci « La moitié »), puis « Il restera X F à payer » ;
     - **À crédit** : exige un client, sinon message orange « Choisissez le client pour lui faire crédit ».
   - Bouton « Encaisser 12 500 F » de 68 px.
   - Après validation, **écran de succès** : grand rond vert coché, montant, « Payé en espèces » ou « Moussa Fall
     doit encore 10 000 F », boutons « Nouvelle vente », « Imprimer le reçu » et « Envoyer par WhatsApp ». Ce
     dernier ouvre un lien `wa.me` avec le reçu en texte prérempli, sans API payante.
3. **Encaisser une dette** (depuis Argent ou depuis la tuile violette).
   - À gauche, liste des clients qui doivent : montant et « Depuis 12 jours ».
   - À droite, le client choisi :
     - « Doit encore 25 000 F » en grand ;
     - « Ses achats » avec badge par vente ;
     - « Combien il paie ? » : champ libre + pavé numérique, raccourcis « Tout » et « La moitié », message en
       direct (« Il restera… », « C'est plus que ce qu'il doit ») ; il paie la part qu'il veut ;
     - « Comment ? » en puces ;
     - bouton violet « Encaisser 25 000 F ».
   - Après validation, un bandeau vert « Moussa Fall ne doit plus rien. Ses achats sont marqués Payé » et les badges
     passent à « Payé » immédiatement. Cela dépend du B2.
4. **Nouvel article** : le formulaire du lot 1, en une colonne de 820 px max, et un écran de succès « Riz brisé 25 kg
   est ajouté » avec « Ajouter un autre article » et « Aller vendre ».
5. **Ajouter une personne** : le formulaire du lot 1, en une colonne de 640 px max, et un succès avec avatar et
   initiales.
6. **Corriger le stock** : l'écran du lot 1, avec en haut « Nouvel article » et « Recevoir une livraison ».
7. **L'argent** (remplace la vue d'ensemble Finance).
   - En haut, quatre raccourcis colorés : Encaisser une dette, Payer un fournisseur, Ajouter une dépense, Entrées et
     sorties.
   - Puces de période : Aujourd'hui / Cette semaine / Ce mois. « Choisir des dates » reste en secondaire.
   - **Phrase héros :** « Ce mois-ci, vous avez **gagné 412 500 F** » en vert, 52 px. Si le résultat est négatif :
     « vous avez **perdu** 10 500 F » en orange foncé, avec la raison principale, c'est-à-dire la plus grosse
     dépense de la période (« À cause de la facture d'électricité payée ce matin (35 000 F) »).
   - **Équation visuelle** en blocs colorés : `Vendu − Prix d'achat des articles vendus − Dépenses = Gagné`, le
     dernier bloc en vert plein, ou orange plein si c'est une perte.
   - Trois cartes **de couleurs différentes** :
     - Entré dans la caisse : teinte verte, icône flèche entrante ;
     - Sorti de la caisse : teinte orange, flèche sortante ;
     - Différence : bleu plein, texte blanc.
   - Graphique en **barres groupées** (entré vert / sorti orange), valeur écrite au-dessus de chaque barre, légende
     en mots. Regroupement : par moment de la journée pour Aujourd'hui, par jour pour Semaine, par semaine pour
     Mois. Plus de courbe en aires. Une valeur extrême ne doit pas écraser les autres : échelle commune, mais
     hauteur minimale de 4 px pour toute valeur non nulle.
   - Deux cartes en bas :
     - « Les clients vous doivent » : total, 3 premiers et bouton « Encaisser une dette » ;
     - « Vous devez aux fournisseurs » : total, prochaines échéances « À payer avant le 10 octobre » et bouton
       « Payer un fournisseur ».

#### Les autres écrans (la maquette couvre tout le logiciel)

Même système, mêmes règles. Chaque liste a une recherche en haut et des puces de filtre ; chaque fiche a ses actions
en gros boutons ; chaque action importante se termine par un écran ou un bandeau de succès en mots simples.

**Ventes**

8. **Liste des ventes.**
   - Résumé du jour en haut et bouton « Nouvelle vente ».
   - Recherche « nom du client ou numéro ».
   - Puces de période (Aujourd'hui, Hier, Cette semaine, Ce mois) et d'état (Toutes, Payées, Pas encore payées,
     Avec retour, Annulées).
   - Ventes groupées par jour avec le total du jour. Chaque ligne : avatar, client, « Vente n° 1044 · 9 h 58 ·
     3 articles », montant, badge (Payé vert, Reste X F orange, Retour bleu, Annulée gris barré).
9. **Détail d'une vente.**
   - Gros boutons-tuiles : Imprimer le reçu, Envoyer par WhatsApp, Encaisser le reste, Retour d'articles, Annuler
     la vente (rouge).
   - Annuler demande la raison en boutons (Erreur de saisie, Le client a changé d'avis, Vente enregistrée deux
     fois, Autre), puis « Oui, annuler » / « Non, garder ».
   - Colonne droite : Total, Payé, Reste à payer, paiements reçus, « À payer avant le ».
10. **Reçu à imprimer**, deux formats au choix :
    - **petit ticket 80 mm** : police à chasse fixe, nom, adresse et téléphone de la boutique, numéro, date, client,
      vendeur, lignes, TOTAL, payé et moyen, rendu, reste dû et échéance, message de bas de reçu ;
    - **facture A4** : logo, NINEA et RC si renseignés, « FACTURE N° F-1044 », bloc client, tableau, totaux, montant
      **en toutes lettres** (« Arrêtée la présente facture à la somme de vingt-cinq mille francs CFA »), mention TVA,
      zone signature et cachet.
    - Boutons Imprimer (`window.print` + feuille de style d'impression dédiée), WhatsApp, PDF.
    - Tampon « VENTE ANNULÉE » en travers si la vente est annulée.
    - Même gabarit pour le **bon de retour**.
11. **Retour d'articles.**
    - Pour chaque ligne vendue, la quantité rendue (libre, plafonnée à ce qui est retournable).
    - Pourquoi ? en puces.
    - Valeur rendue calculée, et « Que fait-on de cet argent ? » :
      - Déduire de ce qu'il doit (compensation, ADR 0024) ;
      - Lui rendre de l'argent (montant libre ≤ valeur, moyen) ;
      - Plus tard.

**Stock**

12. **Liste des articles.**
    - Valeur totale du stock en haut.
    - Raccourcis Recevoir une livraison / Corriger le stock / Gérer les rayons.
    - Puces Tous / Bientôt épuisés / Épuisés / par rayon.
    - Ligne : carré coloré, nom, rayon, prix, quantité en couleur (vert, orange « Plus que 2 sacs », rouge
      « Épuisé ») et petite barre de niveau.
13. **Fiche article.**
    - Quatre tuiles : En stock, Prix de vente, Gagné par unité, Vendu ce mois.
    - Boutons Changer les prix (champs libres), Corriger le stock, Commander.
    - « Ce qui s'est passé » : l'historique des mouvements en phrases (« Vendu à Awa Diop », « Livraison de
      Grossiste Sandaga », « Abîmé »).
    - **Étiquette** : aperçu nom + prix + code-barres, nombre d'étiquettes libre, « Imprimer N étiquettes » sur
      planche A4.
    - « Plus d'infos » repliable : référence, code-barres, TVA, date de création.
14. **Recevoir une livraison** (achat fournisseur).
    - Qui livre ? en puces (+ Nouveau fournisseur).
    - Lignes article avec quantité et prix d'achat **libres** et total de ligne ; ajout rapide des articles bientôt
      épuisés.
    - Total.
    - « Vous payez » : Tout maintenant / Une partie (montant libre) / Plus tard. Pour « Plus tard », « À payer avant »
      en puces (7, 15, 30 jours), ce qui crée la dette fournisseur.
    - Succès : « Le stock et le prix d'achat moyen sont mis à jour ».
15. **Rayons.** Liste avec couleur et nombre d'articles, ajout (nom + couleur), renommer, supprimer seulement si vide.
    La couleur de rayon est une nouvelle colonne facultative (sinon couleur dérivée du nom).

**Clients et fournisseurs**

16. **Liste.**
    - Deux gros onglets Clients / Fournisseurs.
    - Recherche par nom ou téléphone, puce « Qui me doivent » / « À qui je dois ».
    - Cartes avec avatar, téléphone, « Doit 25 000 F » ou « Ne doit rien » et la dernière visite.
17. **Fiche client.**
    - Appeler (lien `tel:`) et Modifier.
    - Tuiles : Il vous doit, Acheté ce mois, Dernière visite.
    - Boutons Encaisser sa dette, Nouvelle vente pour lui, **Lui rappeler sa dette** : message WhatsApp prérempli et
      modifiable, avec le numéro Wave de la boutique.
    - Onglets Ses achats / Ses paiements.
18. **Fiche fournisseur.** Vous lui devez (avec l'échéance en orange si proche), Acheté ce mois, ce qu'il livre ;
    boutons Le payer, Recevoir une livraison ; onglets Ses livraisons / Vos paiements.

**Argent**

19. **Payer un fournisseur** : le même écran que « Encaisser une dette », en bleu, avec l'échéance de chaque
    fournisseur et le montant libre.
20. **Dépenses.**
    - « Pour quoi ? » en tuiles avec icône : Loyer, Électricité, Eau, Transport, Salaires, Téléphone et internet,
      Réparations, Taxes et impôts, Autre. Ce sont les catégories de dépense existantes, avec leur nature fixe ou
      variable portée par la catégorie.
    - Montant libre + pavé, « Quand ? » (Aujourd'hui, Hier, Autre jour), « Payé avec ».
    - À droite : barres « Ce mois-ci, par type » et dernières dépenses.
21. **Entrées et sorties de caisse.**
    - Totaux Entré / Sorti / Différence.
    - Totaux par moyen de paiement.
    - Liste du jour en + vert / − orange, en phrases (« Vente n° 1044 · Moussa Fall », « Dette encaissée · Aminata
      Sow », « Dépense · Électricité »).
    - « Annuler » sur chaque ligne demande la raison en boutons, puis ajoute une ligne inverse (contre-écriture,
      ADR 0038) : rien n'est effacé.

**Conseils, alertes, réglages**

22. **Conseils** (CoGes Intelligence et Analyses fusionnés), trois onglets :
    - **Conseils** : chaque recommandation en carte colorée, avec un titre en phrase (« Le riz va bientôt manquer »),
      une explication chiffrée en mots et trois boutons : action directe (Commander, Lui envoyer un rappel, Voir les
      dépenses…), « C'est fait » (= `resolved`), « Ignorer » (= `dismissed`). Les types existants (`stockout_risk`,
      `slow_mover`, `demand_spike`, `margin_drop`, `expense_anomaly`, `cash_shortfall`, `debt_overdue`,
      `cashier_anomaly`) ont chacun un titre, une couleur et une action. « Données insuffisantes » n'est plus une
      carte : c'est une seule ligne en bas.
    - **Vos meilleurs articles** : puces Rapporte le plus (marge) / Se vend le plus (quantité) / Fait le plus de
      ventes (chiffre) / Vente rare (rotation), puis un classement en barres horizontales avec la valeur.
    - **Prévisions** : « La semaine prochaine, vous devriez vendre environ 7 sacs (entre 5 et 9) » par article, avec
      « Il vous en reste 2 : commandez » en orange.
23. **Alertes.** Groupées Aujourd'hui / Hier, une couleur et une icône par type, point de couleur si non lue, action
    directe sur chaque alerte, « Tout marquer comme lu », filtre Non lues.
24. **Réglages**, menu latéral :
    - **Ma boutique** : logo (pour les reçus), nom, téléphone, adresse, numéro Wave, NINEA et RC facultatifs, message
      de bas de reçu, format de reçu par défaut, interrupteurs TVA et Conseils. Les champs qui n'existent pas encore
      sur l'entreprise passent par une migration ; le logo demande un stockage de fichier, donc `AskUserQuestion`
      avant tout service payant.
    - **Personnes** : liste avec rôle et dernière connexion, Couper / Redonner l'accès (garde du dernier gérant), et
      Ajouter : nom, téléphone ou e-mail, rôle en puces, mot de passe provisoire lisible.
    - **Qui peut faire quoi** : grille de cases à cocher de 48 px, actions en mots (Vendre, Annuler une vente,
      Corriger le stock, Recevoir une livraison, Voir l'argent et les bénéfices, Encaisser une dette, Changer les
      prix, Gérer les personnes). Chaque ligne correspond à un groupe de permissions existant ; la colonne Gérant
      est verrouillée.
    - **Historique** : le journal d'audit en phrases (« Modou a annulé la vente n° 1042 (enregistrée deux fois) »).
    - **Fichiers Excel** : interface du module import/export existant. Ventes en Excel par période (export
      asynchrone, puis « En préparation… » et « Télécharger »), modèle d'import d'articles et envoi du fichier,
      exports des listes.
25. **Connexion.** Panneau vert « Votre boutique, simplement. » et formulaire : code de la boutique, e-mail, mot de
    passe avec Afficher/Cacher, bouton « Entrer » de 64 px. Erreurs en phrases (« Le mot de passe ne correspond pas.
    Réessayez, ou demandez à votre gérant… »).
26. **Sur téléphone (390 px).** En-tête compact avec la cloche, « Nouvelle vente » pleine largeur, tuiles en 2 × 2,
    dernières ventes, barre de navigation fixe en bas avec les cinq entrées. Tous les écrans ci-dessus doivent
    fonctionner à 390 px sans défilement horizontal (les tableaux deviennent des cartes).

### Démo

Le seed `demo` doit faire apparaître chaque état. Ajoute ce qui manque :

- un jour avec perte ;
- un client soldé ;
- trois articles sous le seuil ;
- deux dettes fournisseurs à échéance proche.

---

## Critères de fin de phase

- Les 3 bugs sont couverts par des tests qui échouaient avant la correction : joins la sortie rouge puis verte
  dans la PR.
- **Test du commerçant**, mesuré en e2e (nombre de clics et de frappes clavier, chronométré) :

  | Parcours | Limite |
  |---|---|
  | Vente comptant de 3 articles avec rendu de monnaie | ≤ 7 touches, 0 frappe clavier |
  | Vente à crédit à un client existant | ≤ 8 touches |
  | Vente avec paiement partiel d'un montant tapé (7 500 F) | le champ accepte n'importe quel montant entre 1 F et le total |
  | Encaisser toute la dette d'un client | ≤ 4 touches |
  | Créer un article | seulement nom et 2 prix au clavier |
  | Corriger le stock (2 sacs abîmés) | ≤ 5 touches, 0 frappe clavier |

- axe : 0 violation en clair et en sombre ; Lighthouse accessibilité ≥ 95 sur les 26 écrans.
- Audit `impeccable` relancé : score ≥ 18/20 conservé, en joignant les deux rapports avant/après.
- Captures avant/après des 26 écrans dans `docs/design/captures/phase-15/`, en clair, en sombre et à 390 px.
- `make dev` démarre tout ; `make test`, `make front-check` et `make front-e2e` sont verts ; CI verte.
- Fin de chaque lot : résumé en français, liste des ADR, questions ouvertes posées par `AskUserQuestion`.
