# 0103 — Correctifs de la relecture des lots 28, 29 et 31

- **Date** : 2026-10-29
- **Phase** : prompt 32 (correctifs de la relecture)
- **Statut** : acceptée
- **Décideur** : déjà tranché par le prompt 32 pour les blocs R, B, P ; utilisateur (via
  AskUserQuestion) pour D1, C1, C2 ; une PR par bloc, empilées (R → B → P → D → C)

## Contexte
Une relecture en lecture seule des ADR 0096 à 0102 a relevé des défauts sans rien exécuter.
Méthode : chaque point est d'abord reproduit par un test rouge, puis corrigé ; un point non
reproduit est noté ici tel quel, sans changement.

## Bloc R — brouillons de saisie (ADR 0101)

### Cause commune
Tous les écrans à clé d'idempotence effaçaient le brouillon (`clear()`) puis renouvelaient la clé
(`renew()`), ou l'inverse. `clear()` mémorisait la saisie **avec l'ancienne clé** ; le rendu
suivant portait la nouvelle, la saisie « changeait », et l'écriture différée (400 ms) recréait le
brouillon. Le retour, lui, renouvelait sa clé de création **au milieu** de l'envoi : un
remboursement de plus de 400 ms écrivait un brouillon complet avec une clé neuve.

### Décision
- `DraftSpec.keys` nomme les champs de clé d'idempotence : ils sont écrits avec le brouillon (un
  envoi interrompu rejoue avec la **même** clé) mais ne comptent pas comme une saisie. Une clé
  renouvelée après l'envoi ne recrée jamais le brouillon ; seule une vraie nouvelle saisie le fait.
- `busy` vrai ⇒ **aucune écriture** (minuterie, page cachée, démontage) : le brouillon d'avant
  l'envoi reste tel quel. Il est branché sur la mutation en cours (`useIsMutating` sur une
  `mutationKey` propre à l'écran, la mutation étant déclarée après le crochet), et, pour la vente
  et le retour, sur l'écran « enregistré ». Une saisie tapée pendant l'envoi est écrite à la fin
  s'il n'a pas abouti.
- Retour : les deux clés ne sont renouvelées que dans `onSuccess`, **après** `draft.clear()`, une
  fois tout l'envoi terminé (retour puis remboursement). Un remboursement refusé repart de la fiche
  du retour, sous sa propre clé.
- `unsent` : un formulaire démonté (ou caché par Next) retire sa clé ; son brouillon est en
  stockage et sera retrouvé, il ne retient plus la mise à jour invisible. Revenu, il la retient de
  nouveau.
- Dernier propriétaire gardé sous `coges:draft-owner` (deux identifiants, rien d'autre) :
  `clearOwnDrafts()` l'utilise tant que `/auth/me` n'a pas répondu, puis le retire.
- `freezeDrafts()`, appelé par `forgetLocally()` avant tout effacement et toute redirection
  (déconnexion, expiration, suspension, déconnexion d'un autre onglet) : plus aucune écriture
  jusqu'à la personne suivante (`setDraftOwner`).

### Tableau
| Point | Reproduit | Correctif |
|---|---|---|
| R1 retour réécrit après l'envoi, clé neuve | **Oui** : Vitest (deux ordres `clear`/`renew`) et e2e (retour au remboursement ralenti de 1,5 s, vente encaissée) : brouillon présent 1 s après « enregistré » | `keys`, `busy`, clés renouvelées après `clear()` ; vente, retour, dépense, livraison, correction de stock, encaisser / payer |
| R1 autres écrans de la liste figée | Non concernés : nouvel article, modifier un article, nouveau rayon, client / fournisseur, ajouter une personne n'ont pas de clé et rien ne change après `clear()` (lecture du code, test Vitest existant « l'envoi efface le brouillon et ne le réécrit pas ») | Aucun |
| R2 `unsent` jamais vidé au démontage | **Oui** (Vitest : `hasUnsentDrafts()` vrai après démontage) | Retiré au démontage, remis au retour |
| R3 session refusée à la réouverture | **Oui** (e2e : refresh en 401 au rechargement, brouillon resté) | `coges:draft-owner` |
| R4 déconnexion depuis un autre onglet | **Oui** (e2e à deux onglets : brouillon réécrit par `pagehide`) | `freezeDrafts()` dans `forgetLocally()` |
| R5 `busy` à `false` (vente) ou absent (retour) | **Oui** (Vitest : écriture pendant l'envoi) | Branché sur la mutation en cours |

## Bloc B — mise à jour invisible (ADR 0102)

### Décision
- `UpdateManager.controllerChanged()`, appelé sur `controllerchange` (sauf à la toute première
  prise de contrôle, où la page vient du réseau à la même version) : la page sait qu'elle tourne
  sur l'ancienne version et se recharge au prochain moment sûr, sans réactiver un worker qui
  n'attend plus. Un onglet B dont l'onglet A a activé la version n'est plus bloqué.
- Les drapeaux `coges:pwa:reloaded-chunk` / `-outdated` ne sont posés qu'au rechargement
  effectif ; un rechargement lancé n'est pas relancé par la navigation qui suit.
- 426 sans moment sûr : la bannière « Une nouvelle version est prête » après **3 refus** ou
  **2 minutes**, sans recharger d'office.
- Le moment sûr est revérifié juste avant `reload()`, après l'attente de l'activation (jusqu'à
  5 s) ; s'il ne l'est plus, la page rechargera au suivant.
- Un fichier manquant pendant le rendu est rattrapé par `error.tsx` et n'atteint **jamais**
  `window.onerror` (vérifié sur un build de production) : `error.tsx` et `global-error.tsx`
  appellent `reportRenderError()`. Le gestionnaire existe en production même sans service worker
  (navigateur sans prise en charge, worker refusé) ; sans gestionnaire (mise en page racine en
  erreur), un seul rechargement par session. `isChunkLoadError` reconnaît aussi le texte de
  Turbopack (« Failed to load chunk … from module … »), un objet et la cause.
- **B5, rechargement de Next lié à `deploymentId`** : lu dans
  `next/dist/client/components/router-reducer/fetch-server-response.js`, Next fait une navigation
  complète quand la réponse d'une **navigation** (ou d'un `router.refresh()`) vient d'un autre
  build. Il ne survient donc qu'à un changement d'écran, jamais pendant une frappe ; les écrans de
  saisie ne naviguent par programme qu'après un envoi réussi (`sale-editor`, `settle-screen`,
  `product-form`). Une saisie en cours est déjà en brouillon (écrite à `pagehide`), un envoi en
  cours rejoue avec la même clé. Gardé tel quel (il protège aussi du mélange de deux versions),
  documenté ici.

### Tableau
| Point | Reproduit | Correctif |
|---|---|---|
| B1 deux onglets, celui qui n'a pas activé reste bloqué | **Oui** (Vitest à deux onglets partageant un worker ; deux builds successifs ne se jouent pas en e2e) | `controllerChanged()`, drapeaux au rechargement effectif |
| B2 426 sans moment sûr, aucune bannière | **Oui** (Vitest) | Bannière après 3 refus ou 2 min |
| B3 moment sûr non revérifié avant `reload()` | **Oui** (Vitest : vente commencée pendant l'activation) | Revérifié ; rechargement au moment sûr suivant |
| B4 message de Turbopack, vraie erreur | **Oui**, plus grave que prévu (e2e sur build de production, fichier de « Réglages » en 404 : l'écran d'incident reste, aucun rechargement ; l'erreur n'atteint que `error.tsx`) ; texte seul non reconnu (Vitest) | `reportRenderError()` dans les deux écrans d'erreur, gestionnaire sans worker, motif élargi, un seul rechargement |
| B5 rechargement de Next pendant une vente | Non : seulement à une navigation (lecture du code de Next) | Aucun ; documenté |
| Test d'installation instable (trouvé en route) | **Oui** (1 sur 3 : invite simulée avant l'hydratation) | Le test attend la coquille (4 sur 4) |

## Bloc P — PWA, cache et fichiers conservés (ADR 0102)

### Décision
- **Fichiers des anciens builds** (`frontend/static-entrypoint.sh`) : chaque build a son témoin
  dans le volume, `.next/static/.coges-builds/<build>.files` (la liste de ses fichiers ;
  l'identifiant est l'empreinte `cksum` de cette liste). Au démarrage d'une image, tout autre
  build reçoit `<build>.retired` = maintenant s'il n'en a pas ; ses fichiers partent **14 jours
  exactement après** ce moment, sauf ceux qu'un build encore gardé utilise aussi. Un build qui
  redevient courant (retour arrière) perd sa date de fin. Les fichiers d'un volume d'avant ce
  script (sans témoin) forment un build « orphelin » retiré au premier démarrage. Plus de
  `-mtime` (qui comptait 15 jours), plus de `cp -n` (copie fichier par fichier), plus de
  `set -e` : une erreur de nettoyage est écrite et le front démarre quand même. Les témoins
  contiennent des noms de fichiers déjà publics ; Next ne sert pas les dossiers cachés.
- **Déconnexion** : le worker vide tous les caches puis **remet sa pré-mise en cache** ; la page
  ne vide elle-même que sans worker (sinon elle effacerait ce qu'il vient de remettre).
- **Page hors ligne** : la pré-mise en cache suit ses styles et ses polices (`href` et `url(...)`
  sous `/_next/static/`, lus dans la page puis dans chaque feuille de style). Aucune donnée.
- **Identifiant de build** : `frontend/Dockerfile` refuse de construire si `NEXT_DEPLOYMENT_ID`
  est vide (vérifié : `docker build` échoue à cette étape) ; `deploy.yml` passe l'étiquette de
  version (déjà le cas), la construction de contrôle de `ci.yml` passe `ci-<sha>`. Le build local
  (`pnpm build`, `make front-check`) n'est pas concerné : il ne produit pas d'image.
- **Mineurs** : la règle `set-cookie` du worker, inopérante (en-tête jamais visible depuis Fetch),
  est retirée — ce qui protège, c'est le chemin (`isStatic`, page hors ligne) et `no-store` /
  `private` ; le commentaire de tête ne porte plus que le nom de cache nettoyé (un `*/` dans
  l'étiquette cassait le worker).

### Tableau
| Point | Reproduit | Correctif |
|---|---|---|
| P1 14 jours comptés depuis le dernier démarrage | **Oui** (Vitest : deux déploiements à 20 jours, l'ancien supprimé au démarrage du nouveau ; deux le même jour ; volume en lecture seule = démarrage en échec, avertissement `cp -n`) | Témoin par build, purge 14 j après la fin, jamais d'échec au démarrage |
| P2 déconnexion = page hors ligne perdue | **Oui** (Vitest du worker, e2e sur build de production : plus de `/hors-ligne` en cache après déconnexion) | Pré-mise en cache remise par le worker |
| P3 styles de la page hors ligne | **Oui** dans la pré-mise en cache (Vitest : ni CSS ni police) ; hors déconnexion, les styles n'étaient gardés qu'à l'usage | Styles et polices pré-mis en cache ; e2e : mise en page (`grid`) et Figtree hors ligne |
| P4 `NEXT_DEPLOYMENT_ID` vide | **Oui** (aucun garde ; image de contrôle de la CI sans identifiant) | Garde dans le Dockerfile, `ci-<sha>` en CI ; `deploy.yml` vérifié |
| P5 `set-cookie` inopérant | **Oui** (lecture : en-tête filtré par Fetch) | Retiré, règle documentée |
| P5 `*/` dans l'identifiant | **Oui** (Vitest : la source ne s'exécute plus) | Commentaire sur le nom nettoyé |
| P5 `-mtime +14` = 15 jours | **Oui** (lecture : `find` arrondit au jour entier) | Secondes, 14 × 86 400 |
| P5 `Cache-Control` de `/sw.js` en production | Non : `no-cache, no-store, must-revalidate` servi (e2e existant sur build de production) | Aucun |

## Bloc D — droits (ADR 0099)

### Ce qu'un vendeur par défaut pouvait faire par `POST /api/v1/payments`
Test joué avant correction, tout en 201 : encaisser une dette client, **payer une dette
fournisseur**, **sortir 20 000 F de la caisse sans motif**, enregistrer une entrée d'argent
libre. Il tenait `payments:create` de la ligne « Vendre », dont la caisse n'a pas besoin : la
confirmation encaisse par `sales:confirm` (`finance_service.record_sale_payment`), la déduction
de dette d'un retour par `sale_returns:create`.

### Décision (utilisateur, via AskUserQuestion)
- **« Vendre » ne donne plus `payments:create`** (ni le vendeur par défaut). L'encaissement au
  moment de vendre (tout, une partie, à crédit) ne change pas : test dédié.
- **`POST /payments` borné** (`finance.record_manual_payment`) : sans `payments:update`
  (« Gérer les dettes, les dépenses et les paiements »), seul un encaissement **lettré sur des
  dettes client** est accepté ; sortie d'argent, dette fournisseur, dépense ou entrée sans
  dette ⇒ 403 `permission_denied` (`required_permission: payments:update`). Aucun droit
  nouveau. Le front suit : « Payer » (raccourci, fiche fournisseur, dette fournisseur dans la
  liste) exige aussi `payments:update`.
- **Révision 0031** (données seulement) : retire `payments:create` de tout rôle sauf le gérant
  système qui n'a ni `debts:read` ni `payments:update` (un vendeur à qui « Encaisser une dette »
  a été donnée garde tout), et `company:update` / `system:read` de tout rôle sauf le gérant
  système (D3). Une ligne d'audit critique par rôle touché (auteur NULL, `diff.source =
  "0031"`, droits avant, retirés, après) ; le `downgrade` remet exactement les droits retirés,
  relus dans ces lignes.
- **D2** : décocher une ligne retire ses droits, même ceux qu'une ligne « en partie » partage
  (sauf ceux d'une ligne cochée) ; aucun droit n'est ajouté en silence.
- **D4** : le rôle est lu `FOR UPDATE` dans `set_role_abilities` ; la grille applique la réponse
  du serveur (« en partie » compris) dès l'enregistrement, et retire « en partie » d'une ligne
  touchée dans l'affichage optimiste ; docstrings « 8 lignes » et droit partagé mis à jour.

### Requête de contrôle (D3)
```sql
SELECT c.slug, r.name, r.is_system, p.code
  FROM roles r
  JOIN companies c ON c.id = r.company_id
  JOIN role_permissions rp ON rp.company_id = r.company_id AND rp.role_id = r.id
  JOIN permissions p ON p.id = rp.permission_id
 WHERE NOT (r.is_system AND r.name = 'gerant')
   AND (p.code IN ('company:update', 'system:read')
        OR (p.code = 'payments:create' AND NOT EXISTS (
              SELECT 1 FROM role_permissions o JOIN permissions q ON q.id = o.permission_id
               WHERE o.company_id = r.company_id AND o.role_id = r.id
                 AND q.code IN ('debts:read', 'payments:update'))))
 ORDER BY 1, 2, 4;
```
Jouée sur les bases locales `coges` et `coges_e2e` (propriétaire, lecture seule) : aucun rôle
avec `company:update` ou `system:read` ; chaque vendeur avec `payments:create`. Non jouée sur
Neon : la révision 0031 traite les deux cas où qu'ils soient, avec audit.

### Tableau
| Point | Reproduit | Correctif |
|---|---|---|
| D1 « Encaisser une dette » décoché ne retire pas `payments:create` | **Oui** (test API : vendeur par défaut, 4 écritures d'argent en 201) | Retiré de « Vendre », `POST /payments` borné, révision 0031, front |
| D2 ligne « en partie » qui retient un droit partagé | **Oui** (test du cas exact : `debts:create` reste après le second appui) | Droits des lignes décochées retirés |
| D3 rôles avec `company:update` / `system:read` | Non sur les bases locales ; inconnu sur Neon | Révision 0031, avec audit |
| D4 docstrings périmés | **Oui** (« 8 lignes », exemple `payments:create`) | Mis à jour |
| D4 verrou du rôle | **Oui** (test : `FOR SHARE NOWAIT` passait pendant un enregistrement) | `FOR UPDATE` |
| D4 « en partie » non recalculé après la mise à jour optimiste | **Oui** (Vitest : l'avis « en partie » restait) | Recalcul optimiste, réponse du serveur appliquée |

## Bloc C — retours (ADR 0097)

### Décision (utilisateur, via AskUserQuestion)
- **C1, retour après une dette abandonnée** : la part qui correspond à la dette abandonnée est
  **soldée sans argent**, d'office, à la création du retour. Nouvelle colonne
  `sale_returns.waived_total` (révision 0032) ; le reste dû devient
  `total_refund − refunded_total − waived_total` partout (plafond `sale_returns_refund_cap`,
  statut, `refund_check`, lecture `refund_due`). Montant soldé : ce que le retour doit au-delà
  de l'argent encore remboursable sur la vente, jamais plus que la dette abandonnée moins ce que
  les retours précédents en ont déjà soldé. Seulement si la dette de la vente est
  `written_off`. Audit critique (`waived_because: debt_written_off`), aucun événement (aucun
  argent ne bouge). Tout soldé ainsi ⇒ `none_due`. Le détail du retour montre la ligne « Non
  payé (dette abandonnée) ». Non couvert : une dette abandonnée **après** le retour ne solde
  rien rétroactivement (le retour garde son reste dû, réglable en argent jusqu'au plafond).
- **C2, annuler un encaissement déjà rendu** : **refusé** (409 `refund_exceeds_paid`, message
  « annulez d'abord le remboursement ») quand l'argent qui resterait versé sur la vente
  deviendrait inférieur à ce qui a été rendu en argent sur ses retours. Tenu en base par
  `payments_reversal_refund_guard` (`CG054`, révision 0032), sur le modèle de l'ADR 0014 :
  Finance ne lit pas les retours de Sales. L'ordre inverse (annuler le remboursement, puis
  l'encaissement) reste possible.
- **C3** : la sous-requête de `returnable` ne lit plus que les lignes de retour des ventes de la
  page (`sale_item_id IN (lignes de ces ventes)`), plus celles de toute l'entreprise.

### Tableau
| Point | Reproduit | Correctif |
|---|---|---|
| C1 retour jamais réglable après une dette abandonnée | **Oui** (test API : 6 000 F dus, 2 000 F rendus, 4 000 F refusés en argent et en compensation, retour « partiel » pour toujours) | `waived_total`, part abandonnée soldée sans argent, audit |
| C2 annulation d'un encaissement déjà remboursé | **Oui** (test API : annulation acceptée, 3 000 F sortis pour 0 F versé) | Refus en base (`CG054`) ⇒ 409 |
| C3 sous-requête sur toute l'entreprise | **Oui** (SQL émis : aucun filtre sur les ventes de la page) | Filtre sur les lignes de la page |

## Conséquences
- Tests : Vitest `hooks/use-draft.test.tsx` (+5), `lib/drafts.test.ts` (+2) ; e2e
  `frontend/e2e/drafts.spec.ts` (+3, et la vente vérifie désormais l'absence de brouillon une
  seconde après l'envoi puis au rechargement). Les e2e rouges ont été joués sur le code d'avant.
- Bloc B : Vitest `lib/pwa/update.test.ts` (+8) ; e2e `make front-pwa-e2e` (+1, vraie
  `ChunkLoadError` de Turbopack).
- Bloc P : Vitest `lib/static-entrypoint.test.ts` (+5), `lib/pwa/sw-source.test.ts` (4, nouveau,
  le worker exécuté dans un faux environnement), `lib/build-config.test.ts` (3) ; e2e PWA (+1).
- Bloc D : `backend/tests/integration/test_review_32_rights.py` (7 : D1 ×4, D2, D4, révision
  0031 aller et retour) ; Vitest `rights-view.test.tsx` (1). Un vendeur à qui le gérant donne
  « Encaisser une dette » encaisse les dettes client, rien d'autre.
- Bloc C : `backend/tests/integration/test_review_32_returns.py` (7 : C1 ×4 dont le plafond
  en base, C2 ×2, C3 sur le SQL émis).
- Un brouillon n'est plus écrit pendant un envoi : une frappe faite à ce moment, puis une page
  tuée avant la fin, est perdue (l'envoi, lui, est rejoué à l'identique).
