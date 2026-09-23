# Phase 12 — Frontend : tableau de bord, référentiels, stock, ventes et retours

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 12 : les écrans
opérationnels**, ceux qu'un gérant ou un vendeur utilise tous les jours. On reprend le visuel et
les parcours du prototype, branchés sur les **vrais endpoints**.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 11 ✅ exigée) et les ADR (en particulier les phases 05, 06 et 11).
2. Lis `docs/design/prototype-reference.md` et les écrans 1 à 6 de
   `docs/design/prototype-bolt-prompt.md` ; parcours les endpoints concernés dans
   `backend/openapi.json`.
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder.
4. Travaille **écran par écran** : pour chacun, montre une capture et attends mon retour avant de
   passer au suivant, **sauf** si je te dis d'enchaîner.
5. Clôture.

## 1. Objectif

Des écrans complets et fidèles au prototype pour : tableau de bord, produits (liste, fiche, prix),
catégories, clients, fournisseurs, stock (courant et journal), ventes (liste, nouvelle vente,
détail, reçu imprimable, annulation) et retours (création, remboursement).

## 2. Questions à me poser (AskUserQuestion)

1. **Saisie d'une nouvelle vente** : le brouillon est créé côté serveur dès le premier article
   ajouté, et chaque ligne est synchronisée (Recommandé : aucune perte, totaux faisant foi calculés
   par le serveur) / tout est saisi localement puis envoyé en une fois à « Enregistrer en brouillon ».
2. **Aperçu des totaux** pendant la saisie : afficher les totaux **renvoyés par le serveur** après
   chaque modification, avec un indicateur de mise à jour (Recommandé) / aperçu calculé localement
   puis remplacé.
3. **Reçu imprimable** : page `/sales/[id]/receipt` optimisée pour l'impression (`@media print`,
   format ticket 80 mm et A4) (Recommandé) / A4 seulement.
4. **Stock insuffisant** : désactiver la confirmation quand l'aperçu du stock disponible est
   inférieur à la quantité, tout en affichant l'erreur `insufficient_stock` renvoyée par le serveur
   (Recommandé : confort + vérité serveur) / erreur serveur seulement.
5. **Ordre des écrans** : Ventes (nouvelle vente, liste, détail) d'abord, car c'est l'argument
   principal de la démo, puis Stock, Produits, Clients et Fournisseurs, et enfin le Tableau de
   bord (Recommandé) / l'ordre de la navigation.

## 3. Périmètre

- **Tableau de bord** : bandeaux d'alertes cliquables, 6 cartes KPI, graphique du CA sur 30 jours,
  5 dernières ventes (endpoint `/dashboard`).
- **Produits** : liste (depuis `/inventory/stock` pour le stock et le statut), filtres, recherche,
  fiche (historique des prix en frise, derniers mouvements, bouton « Ajuster le stock » avec motif
  obligatoire), formulaires de création et de modification, changement de prix.
- **Catégories** (arbre), **Clients** (fiche : encours autorisé, achats, dettes),
  **Fournisseurs** (délai de paiement).
- **Stock** : stock courant valorisé au CMP, avec le surlignage sous le seuil ; journal filtrable ;
  formulaires de mouvement manuel (initial, réception, perte, retour fournisseur, ajustement) ;
  correction par inverse si l'ADR de la phase 04 l'a retenue.
- **Ventes** :
  - liste avec badges de statut (brouillon, confirmée, annulée, et « retournée » dérivée),
    filtres de statut et de période, colonnes Payé et Reste dû ;
  - nouvelle vente : client, recherche d'articles par nom ou SKU, lignes (quantité, remise), taxe
    visible si la TVA est activée, règlement total, partiel ou à crédit, méthode de paiement ;
    boutons « Enregistrer en brouillon » et « Confirmer la vente » ;
  - détail : actions selon le statut (Confirmer, Annuler avec motif, Effectuer un retour),
    paiements, dette liée ;
  - reçu imprimable.
- **Retours** : sélection des lignes et des quantités (plafonnées à ce qui reste retournable),
  montant remboursable renvoyé par le serveur, règlement (trésorerie, compensation de dette si
  l'ADR de la phase 06 l'a retenue, ou plus tard), remboursements successifs.
- Envoi de l'en-tête **`Idempotency-Key`** (UUID généré à l'ouverture du formulaire, conservé en
  cas de nouvelle tentative) sur la confirmation, les paiements et les remboursements.
- États de chargement (squelettes), vides et d'erreur sur chaque écran.

## 4. Règles à respecter

- Toute action dont le résultat change le stock ou l'argent s'affiche **après** la réponse du
  serveur (pas de mise à jour optimiste sur ces actions).
- Les erreurs métier sont affichées en français, près du champ concerné.
- Les défauts du prototype listés dans `prototype-reference.md` § 5 ne sont pas reproduits.
- Aucun sélecteur d'entreprise.

## 5. Vérification

Playwright : (1) vente complète en brouillon → confirmation avec paiement partiel → reçu ;
(2) tentative de vente au-delà du stock, bloquée avec le bon message ; (3) retour partiel et
remboursement ; (4) ajustement de stock avec motif. Captures des écrans principaux.

## 6. Clôture

`CLAUDE.md` mis à jour ; liste des écarts restants par rapport au prototype ; résumé.
