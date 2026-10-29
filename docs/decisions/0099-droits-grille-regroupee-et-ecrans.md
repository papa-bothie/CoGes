# 0099 — Droits : grille regroupée, droit exact par écran, garde de page

- **Date** : 2026-10-28
- **Phase** : prompt 28, bloc C3 (corrections du terrain)
- **Statut** : acceptée (remplace la grille de l'ADR 0075 ; matrice par défaut de l'ADR 0007 inchangée)
- **Décideur** : utilisateur (via AskUserQuestion : grille regroupée de 14 lignes validée, « En partie », onglet Stock sur `inventory:read`, matrice du comptable gardée)

## Contexte
Le comptable voyait presque tout le logiciel, quoi que le gérant règle dans « Qui peut faire quoi ».
Causes confirmées par test rouge :
1. **La grille ne pilotait que 8 gestes** (`rbac/matrix.py`). Les autres droits d'un rôle système
   « ne bougeaient pas » : le comptable gardait `debts:*`, `expenses:*`, `payments:update|cancel`,
   `audit:*`, `insights:*`, les exports, `company:read`…, et le gérant ne pouvait pas les retirer.
2. **Le menu ouvrait des écrans par un droit voisin** (`lib/navigation.ts`) : Stock sur
   `products:create | analytics:read`, Argent sur `debts:read | expenses:read` alors que l'écran
   Argent lit `analytics:read`, Conseils sur `insights:read | analytics:read`, Vendre ouvrait la
   caisse à qui n'avait que `sales:read`.
3. **Aucune garde de page** : une adresse tapée chargeait l'écran, qui enchaînait des 403.

## Décision
### La grille (serveur)
Quatorze lignes ; tout droit du catalogue, sauf `roles:*`, est dans au moins une ligne
(`tests/integration/test_abilities_registry.py` échoue sinon). Le vendeur et le comptable par défaut
sont **exactement** une somme de lignes : la matrice de l'ADR 0007 ne change pas.

| Clé | Ligne | Droits | Défaut |
|---|---|---|---|
| `base` 🔒 | Recevoir ses alertes et voir l'accueil | notifications:read/update, dashboard:read | tous |
| `see` | Voir les articles, le stock, les ventes et les fiches | products, categories, prices, inventory, suppliers, customers, sales, sale_returns : read | V C |
| `sell` | Vendre et enregistrer des retours | sales:create/update/confirm, payments:create/read, customers:create/update, sale_returns:create | V |
| `cancel_sale` | Annuler une vente, rembourser un retour, abandonner une dette | sales:cancel, sale_returns:confirm, debts:write_off | — |
| `change_prices` | Gérer les articles et les prix (aussi par fichier) | products:create/update/delete, categories:create/update/delete, prices:create, importexport:create | — |
| `stock` | Corriger le stock et recevoir des livraisons | inventory:create/update, debts:create | — |
| `parties` | Gérer les clients et les fournisseurs | customers:create/update/delete, suppliers:create/update/delete | — |
| `see_money` | Voir l'argent, les bénéfices et les conseils | analytics:read, expenses:read, payments:read, debts:read, insights:read/update | C |
| `collect_debt` | Encaisser une dette | debts:read, payments:create | C |
| `manage_money` | Gérer les dettes, les dépenses et les paiements | debts:create/update, expenses:create/update/delete, payments:update/cancel | C |
| `audit` | Voir le journal d'activité et les réglages | audit:read, company:read | C |
| `export` | Exporter des fichiers | sales, analytics, audit, importexport : export | C |
| `manage_people` 🔒 | Gérer les personnes | users:* | gérant |
| `shop_settings` 🔒 | Modifier les réglages et voir l'état du système | company:update, system:read | gérant |

- Une ligne décochée retire tous ses droits, sauf ceux qu'une autre ligne cochée demande.
- **« En partie »** : un rôle réglé avant cette grille peut porter une partie d'une ligne
  (l'ancien « Corriger le stock » seul). `RoleAbilities.partial` le dit ; ses droits restent tant
  que le gérant n'y touche pas ; un appui coche la ligne entière, un second la retire.
- `company:update` et `system:read` rejoignent `users:` et `roles:` parmi les droits réservés au
  gérant : refusés aussi à un rôle sur mesure (422, `reserved_permissions`).
- Un changement de grille vaut **dès la requête suivante**, même jeton : les droits sont relus en
  base à chaque requête (`core/deps.py`) — vérifié pour un ajout et pour un retrait.

### Les écrans (front)
- **Registre** `frontend/lib/access.ts` : chaque page de `app/(app)` déclare le droit exact de
  son écran (`lib/access.test.ts` échoue si une page manque). `PermissionRule` gagne `allOf`
  pour les écrans qui en exigent deux (encaisser : `debts:read` + `payments:create`).
- **Menu** : chaque entrée liste ses écrans avec leur droit (`targets`) et s'ouvre sur le premier
  permis (Vendre → caisse ou historique ; Argent → compte, dettes ou dépenses ; Réglages → la
  première page permise). Un test vérifie que le droit de chaque cible est celui du registre.
  L'onglet Stock repose sur `inventory:read` (choix du propriétaire) : **le vendeur voit Stock en
  lecture**, ce qui change le menu décidé en phase 15 (Accueil, Vendre, Clients).
- **Garde de page** (coquille) : sans le droit du registre, « Vous n'avez pas accès à cette page »
  et la page n'est pas rendue — aucune donnée chargée, aucun appel d'API (vérifié en e2e).
- **Tableau de bord** : une tuile ou un raccourci n'apparaît que si l'écran où il mène est permis.
- **L'écran suit sans reconnexion** : au premier 403 `permission_denied`, `/auth/me` est relu
  (`lib/api/query.ts`) ; menu, tuiles et garde se mettent à jour.

### Droits exigés par écran
| Écran | Droit |
|---|---|
| Accueil `/dashboard` | dashboard:read |
| Alertes `/notifications` | notifications:read |
| Mot de passe `/account/password` | aucun (ADR 0098) |
| Vendre `/sales/new` | sales:create |
| Ventes `/sales`, fiche, reçu | sales:read ; modifier un brouillon : sales:update |
| Retour `/sales/[id]/returns/new` | sale_returns:create ; fiche et bon de retour : sale_returns:read |
| Stock `/products`, `/inventory` | inventory:read |
| Nouvel article `/products/new` | products:create + inventory:create |
| Article `/products/[id]`, étiquette | products:read ; modifier : products:update ; rayons : categories:read |
| Corriger `/inventory/adjust` | inventory:create |
| Recevoir `/inventory/receive` | inventory:create + debts:create |
| Clients / fournisseurs | customers:read / suppliers:read ; nouveau : :create ; modifier : :update |
| Argent `/finance`, caisse | analytics:read |
| Encaisser `/finance/collect`, payer `/finance/pay` | debts:read + payments:create |
| Dettes `/finance/debts` | debts:read |
| Dépenses `/finance/expenses` (+ toutes) | expenses:read |
| Conseils `/insights` (et `/analytics`) | insights:read |
| Réglages `/settings` | company:read ; personnes : users:read ; droits : roles:read ; historique : audit:read ; fichiers : importexport:export ou :create |

## Conséquences
- Les tests de la grille de l'ADR 0075 (`test_lot_3e2_settings.py`) sont réécrits pour la grille
  regroupée : c'est la décision elle-même. La ligne du registre d'échec au COMMIT pour
  `PUT /roles/{id}/abilities` envoie les nouvelles clés. Les tests de fuite inter-tenant ne
  changent pas.
- Le seed `maquette` coche `base`, `see`, `sell`, `collect_debt` pour le vendeur.
- Tests : registre serveur, grille (« en partie », verrous, droits réservés, effet à la requête
  suivante), registre front, navigation, relecture de l'identité, e2e `frontend/e2e/rights.spec.ts`
  (gérant, vendeur, comptable par défaut, comptable restreint, rôle sur mesure ; refus à l'écran et
  au serveur ; aucun appel d'API derrière un écran refusé).
- Les boutons d'action restent gardés par `<Can>` sur le droit de leur route ; ils ne sont pas au
  registre des écrans.

## Corrections
- **2026-10-29, prompt 32, bloc D (ADR 0103, révision 0031)** : « Vendre » ne donne plus
  `payments:create` (la caisse encaisse par la confirmation) ; `POST /payments` sans
  `payments:update` n'accepte qu'un encaissement lettré sur des dettes client ; rôles existants
  repris avec audit (`payments:create` sans `debts:read` ni `payments:update`, `company:update` et
  `system:read` hors gérant) ; décocher une ligne retire aussi ce qu'elle partage avec une ligne
  « en partie » ; rôle verrouillé à l'enregistrement de la grille.
