# 0075 — Réglages de la maquette v2 (lot 3e-2)

- **Date** : 2026-10-15
- **Phase** : 15 (lot 3e, seconde PR)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-14 et 2026-10-15)

## Contexte
La seconde PR du lot 3e reproduit les Réglages de la maquette v2 :
- 24 Ma boutique ;
- 24b Personnes ;
- 24c Qui peut faire quoi ;
- 24d Historique ;
- 24e Fichiers Excel.

Ces écrans remplacent les quatre onglets de la phase 13 (Entreprise, Utilisateurs, Rôles et
permissions, Journal d'activité, ADR 0053, 0054).

La maquette demande quatre choses que CoGes n'avait pas :
- une grille de huit gestes par rôle ;
- un historique écrit en phrases ;
- la date à laquelle un accès a été coupé ;
- un reçu choisi par défaut.

## Décisions

**Une page par rubrique** : `/settings`, `/settings/people`, `/settings/rights`, `/settings/history`, `/settings/files`.
- Un menu latéral montre seulement les rubriques permises ; une rubrique interdite dit « Ces réglages sont réservés au gérant » au lieu d'une erreur.
- Les anciens `?tab=users|roles|audit` mènent à leur rubrique.
- Les rôles sur mesure disparaissent de l'écran (l'API les garde : `POST/PATCH/DELETE /roles`).

**Grille « Qui peut faire quoi »** (2026-10-14).
- Huit lignes et leurs permissions (`rbac/matrix.py`, `ABILITIES`) :

| Ligne | Permissions |
|---|---|
| Vendre | `sales:create`, `sales:update`, `sales:confirm` |
| Annuler une vente | `sales:cancel`, `sale_returns:confirm` |
| Corriger le stock | `inventory:create`, `inventory:update` |
| Recevoir une livraison | `inventory:create`, `debts:create` |
| Voir l'argent et les bénéfices | `analytics:read`, `expenses:read` |
| Encaisser une dette | `debts:read`, `payments:create` |
| Changer les prix | `prices:create`, `products:update` |
| Gérer les personnes | `users:*` (verrouillée) |

- Colonnes : Gérant (verrouillé, il garde tout), Vendeur, Comptable. Pas de Magasinier.
- Une ligne est cochée quand le rôle porte **toutes** ses permissions.
- `GET /roles/abilities` (`roles:read`) donne la grille.
- `PUT /roles/{id}/abilities` (`roles:update`) coche exactement les lignes envoyées.
  - Nouvelle matrice = (droits actuels − droits de toutes les lignes) ∪ droits des lignes cochées : les droits hors grille ne bougent jamais, et un droit partagé (`inventory:create`) reste tant qu'une ligne cochée le demande.
  - Le gérant est refusé (409 `role_locked`) ; cocher ou décocher « Gérer les personnes » est refusé (422).
  - Audit critique, avec les permissions et les lignes avant et après.
- **Écart à l'ADR 0007** : les permissions des rôles système Vendeur et Comptable deviennent modifiables, par cette grille seulement. `PATCH /roles/{id}` continue de les refuser.
- Retirer « Encaisser une dette » au vendeur retire `payments:create`. La confirmation d'une vente, paiement compris, ne dépend que de `sales:confirm` : la caisse continue de fonctionner.

**Historique en phrases** (2026-10-15) : `GET /analytics/history` (`audit:read`).
- La lecture se fait en bande E, parce qu'Audit (Plateforme) ne peut pas appeler Ventes ou Articles. Elle lit le journal par la façade Audit, puis les noms par lots aux façades Products, Users, Finance, Inventory, RBAC et Expenses (`analytics/history.py`).
- Phrases au passé composé, sujet en tête, avec le prénom de l'auteur :
  - annulation de vente avec sa raison ;
  - changement de prix avec l'avant et l'après ;
  - correction de stock avec la quantité, l'unité et la raison ;
  - accès coupé ou redonné ;
  - encaissement ou paiement avec la personne ;
  - livraison reçue (une dette fournisseur qui a des lignes de stock) ;
  - dépense notée ;
  - abandon d'une dette ;
  - rôle changé ;
  - personne ajoutée.
- Toute autre ligne garde une phrase générique (« Fatou a modifié un client »), jamais une ligne vide.
- **Le geste courant est écarté** par la façade Audit (`notable_only`) :
  - connexions, recalculs, lettrages ;
  - ventes confirmées ;
  - encaissements et dettes nés d'une vente ;
  - paiement d'une dépense, déjà raconté par la dépense ;
  - extinction de la dette d'une vente annulée, déjà racontée par l'annulation.
- Deux champs sont ajoutés aux audits pour ce tri : `expense_id` sur un paiement et `by_sale_cancel` sur l'extinction. Les lignes plus anciennes restent racontées, au plus en double.
- Montants en FCFA comme les autres textes du serveur (ADR 0057). Filtres « Qui » et période en haut de la page.

**Date de coupure d'un accès** (2026-10-15) : révision 0020, `users.deactivated_at`.
- Elle est posée quand l'accès est coupé et effacée quand il est redonné. `users_deactivated_coherent` lie la date à `is_active`.
- Les comptes déjà coupés reprennent `deleted_at`, sinon `updated_at`.
- « Accès coupé le 30 septembre ».

**Reçu par défaut** : `settings.receipt_format` vaut `ticket` (défaut) ou `a4`, vérifié par le serveur.
- `GET /auth/me` le donne (`company.receipt_format`), parce que le vendeur ne lit pas `/companies/me`.
- Le reçu s'ouvre dans ce format sans `?format=`.

**Ma boutique** :
- coordonnées du reçu (révision 0016), reçu par défaut, interrupteurs TVA et conseils ;
- le seuil d'alerte et la TVA par défaut d'un nouvel article sous « Plus de réglages », replié (2026-10-14) ;
- monnaie et fuseau en lecture seule (« Monnaie : franc CFA. Heure : Dakar. ») ;
- pas de logo en V1 (2026-10-14) ;
- la confirmation des changements sensibles de la phase 13 disparaît : chaque interrupteur dit ce qu'il fait, et l'enregistrement passe toujours par l'audit critique.

**Personnes** :
- ajout dans la page (nom, téléphone ou e-mail, rôle), mot de passe provisoire affiché une fois (ADR 0074) ;
- « Couper l'accès » et « Redonner l'accès », « Vous » pour soi ;
- « Vu hier à 19 h » (dernière connexion), « En ligne maintenant » pour soi, puisque le genre n'est pas connu ;
- « Changer son rôle » sous chaque personne : un seul rôle de la grille, l'ancien retiré après le nouveau ;
- la garde du dernier gérant reste celle du serveur (ADR 0054).

**Fichiers Excel** :
- ventes de ce mois, du mois dernier ou de cette année, préparées par le worker (ADR 0041) ;
- « Fichiers préparés », relu toutes les 2 s tant qu'un fichier est en préparation ;
- `ExportRead.params` donne la période, pour nommer le fichier avant qu'il soit prêt ;
- modèle d'articles (CSV, qu'Excel ouvre) ;
- envoi en deux temps : `dry_run` pour vérifier, puis « Ajouter ces articles » avec la même clé d'idempotence ;
- listes Articles, Clients et Fournisseurs en .xlsx.

**Seed `maquette`** :
- la grille du vendeur coche « Vendre » et « Encaisser une dette » ;
- Modou encaisse les dettes au comptoir ;
- Awa est coupée le 30 septembre à 20 h 41 et Modou vu le 5 à 19 h ;
- le prix du riz passe de 15 000 à 15 500 F le 5 à 9 h 05 (avant toute vente, recalé ensuite) ;
- un sac de riz abîmé le 5 à 18 h 20 ;
- les ventes de septembre préparées le 1er octobre ;
- la TVA coupée.

## Conséquences
- `PATCH /roles/{id}` et la grille coexistent ; seule la grille touche aux rôles système.
- L'Historique dépend de ce que l'audit garde : une ligne sans nom lisible reste générique.
- Écarts à la maquette : `docs/design/maquette-v2/ecarts.md` (24 à 24e).
