# 0110 — Finitions du groupe 1 : action secondaire, formulaires, « À surveiller », fiche d'article

- **Date** : 2026-11-03
- **Phase** : groupe 1, bloc F (prompt 34, branche `feat/group1-f-visual-polish`)
- **Statut** : acceptée (complète 0064, 0070, 0071, 0073)
- **Décideur** : propriétaire (liste du prompt) ; « aucune logique métier » sauf le filtre
  de lecture `status=watch`, nécessaire à la carte « À surveiller »

## Contexte
Plusieurs actions de l'interface étaient des liens soulignés ou des textes gris discrets
(« Gérer les types de dépense », « Toutes les dépenses », « Toutes les dettes »…), d'autres
des boutons pleins : le commerçant ne voyait pas toujours qu'on pouvait les toucher. Les
formulaires des types de dépense gardaient le style d'avant la maquette v2 ; la carte « À
surveiller » ne menait nulle part ; « Modifier » et « Supprimer » manquaient sur la fiche
d'un article.

## Décision
**1. Un style unique d'action secondaire** : `components/kit/secondary-action.tsx`
(`SecondaryAction`, `SecondaryLink`, `secondaryActionClasses`) — pilule bordée de 2 px,
48 px de haut, texte gras, jetons `border-input`, `bg-card`, `hover:bg-voile`, anneau de
focus. Inventaire automatique (`grep -rn underline app components`) et sort de chaque
endroit :

| Endroit | Texte | Devient |
|---|---|---|
| `finance/expenses/expenses-view.tsx` | Gérer les types de dépense | action secondaire |
| `finance/expenses/expenses-view.tsx` | Toutes les dépenses | action secondaire |
| `components/finance/settle-screen.tsx` (encaisser un client, payer un fournisseur) | Toutes les dettes | action secondaire |
| `finance/money-view.tsx` | Choisir des dates | action secondaire |
| `finance/cash/cash-view.tsx` | Garder (annulation d'une ligne de caisse) | action secondaire |
| `dashboard/dashboard-view.tsx` | Tout voir (dernières ventes) | action secondaire |
| `components/sales/recent-sales.tsx` | Voir toutes les ventes | action secondaire |
| `sales/sale-success.tsx` | Voir l'accueil (déjà à jour) | action secondaire |
| `sales/[id]/sale-detail-view.tsx` | Voir le client | action secondaire |
| `products/products-list-view.tsx` | Tous les mouvements | action secondaire |
| `insights/insights-view.tsx` | Paramètres de l'entreprise ; Pourquoi ? | action secondaire |
| `insights/insight-sheet.tsx` | Voir l'élément concerné | action secondaire |
| `components/forecast/intelligence-summary-card.tsx` | Voir les recommandations | action secondaire |
| `settings/people/people-view.tsx` (×3) | Donner un nouveau mot de passe ; Changer son rôle | action secondaire |
| `(auth)/password/first-password-form.tsx` | Se déconnecter | action secondaire |
| `components/draft-banner.tsx` | Effacer (brouillon retrouvé) | action secondaire |

Gardent leur forme, et pourquoi :
- **Retours** (`components/back-link.tsx`, fiches client et fournisseur, rayons,
  `person-page.tsx`) : un retour n'est pas une action, c'est la flèche de l'ADR 0082.
- **Noms dans une liste** (`finance/debts-tab.tsx`, `insights-view.tsx` nom d'article,
  `components/finance/debts-card.tsx` date) : la ligne elle-même est l'objet ; souligné au
  survol seulement, comme un lien dans un texte.
- **Composants de bibliothèque** (`ui/button.tsx` et `ui/badge.tsx` variante `link`,
  `ui/dialog.tsx` liens dans une description) et la vitrine `/dev/composants` : liens de
  texte dans une phrase.

**2. Formulaires** : « Types de dépense » (fenêtre de L'argent) prend la forme des
formulaires v2 — libellé `text-libelle`, champ de 58 px (`fieldClasses("depenses")`), « Elle
revient » en deux grandes cases (`ChoiceGroup`, Fixe / Variable) au lieu d'une liste
déroulante, bouton standard de la rubrique, erreur sous les champs, liste des types en
lignes de 48 px ; mots revus (« Types de dépense », « Nom du type », « Ajouter ce type »).
« Rayons » : libellés `text-libelle`, champ de 58 px, bouton standard Stock, boutons de la
fenêtre de suppression et du renommage en variantes v2 (`secondaire`, `stock`), libellé
visible « Couleur du rayon ».

**3. « À surveiller »** : `GET /inventory/stock?status=watch` garde les bientôt épuisés
**et** les épuisés (le filtre « Bientôt épuisés » excluait les épuisés) ; Stock gagne la puce
« À surveiller (N) » (`?filter=watch`, dans l'URL) ; sur l'accueil, le titre de la carte et
« Voir les articles à surveiller » y mènent, chaque ligne garde son lien vers sa fiche (pas
de lien dans un lien).

**4. Fiche d'un article** : « Modifier » (vers `/products/[id]/edit` : nom, description,
rayon, unité ; `products:update`) et « Supprimer » (`products:delete`) à côté de « Changer
les prix », « Corriger le stock » et « Commander ». Le prix reste un geste à part, historisé
(ADR 0011), juste à côté. Supprimer ouvre une fenêtre : ce qui se passe (plus proposé à la
vente, l'historique reste), puis « Oui, supprimer l'article » ; un article qui a encore du
stock est refusé par la base (`CG004`, « corrigez le stock à zéro avant de le supprimer »),
sinon suppression logique auditée et retour au stock.

**5. `make maquette-check`** : l'état 06 cherchait « 2 800 F » partout sur la page, où le
montant revient dans d'autres phrases ; il lit maintenant le bloc « Valeur rendue ». Les
écarts voulus (01, 02, 07, 08, 17, 18, 19, 20) sont ajoutés à `docs/design/maquette-v2/ecarts.md`.

## Conséquences
- Toute nouvelle action secondaire passe par le kit ; un lien souligné neuf dans `app/` ou
  `components/` doit entrer dans l'une des trois familles gardées.
- Le filtre `watch` est une lecture : aucune donnée, aucun droit nouveaux.
