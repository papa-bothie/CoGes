# Prompt 34 — Groupe 1 : prix modifié à la vente, description d'article, finitions

Branche `feat/group1-price-description-polish`, depuis `main` à jour. Premier des cinq groupes décidés par le propriétaire le 3 novembre 2026. **Règle du propriétaire : chaque groupe est testé, fusionné et déployé avant de passer au suivant.** Une PR par bloc (P, D, E, F, A).

Ordre des groupes : 1) ce prompt ; 2) documents (logo, ticket et facture refaits, PDF à partager, exports PDF) ; 3) vente en gros (conditionnements) ; 4) devis en une minute ; 5) annuler et refaire une vente, photo d'article, notifications sur le téléphone.

```
Groupe 1 — prix modifié à la vente, description d'article, finitions (branche
feat/group1-price-description-polish, depuis main à jour). Règles habituelles : ADR au
prochain numéro libre, tests d'abord (rouge puis vert), aucun service payant, ne jamais
ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/. Résumé en français à la
fin, questions ouvertes par AskUserQuestion. Une PR par bloc, dans l'ordre P, D, E, F, A.
Migrations : ajouts seuls, rétrocompatibles (ADR 0083).

P. Changer le prix d'un article au moment de vendre (PRIORITAIRE)
Décision du propriétaire : tout utilisateur qui vend peut changer le prix d'une ligne, sans
limite, pour plus de souplesse ; la marge en tient compte ; le prix de la fiche ne change pas.
- Constat à vérifier d'abord : une ligne a déjà une remise (`discount`, SaleItemCreate /
  SaleItemUpdate), et `confirm_sale` RELIT le prix courant de l'article et le fige
  (`price.unit_price`) : un prix tapé sur la ligne serait aujourd'hui écrasé à la
  confirmation. Prouve-le par un test rouge.
- Conception (à décider dans l'ADR, avec la plus petite modification sûre) : la ligne garde le
  prix de la fiche (`list_price`, figé comme aujourd'hui) ET le prix appliqué. Recommandation :
  un prix plus bas s'écrit comme une remise par ligne (mécanique existante, rapports de
  remises inchangés) ; un prix plus haut, si tu dois le permettre, par un prix appliqué
  distinct — si cela complique trop le modèle, pose-moi la question (AskUserQuestion) avant
  de coder. Montant de la ligne, taxe, coût, marge, dette, chiffre d'affaires et rapports
  calculés sur le prix APPLIQUÉ. Jamais négatif ; prix à 0 (cadeau) accepté avec une
  confirmation à l'écran.
- Droit : celui de vendre (`sales:update` sur le brouillon), aucun nouveau droit, aucune
  limite de montant. Audit : la ligne garde le prix de la fiche et le prix appliqué ; le
  journal de la vente le montre (« Prix changé : 2 500 F → 2 000 F, par Awa »). Motif
  facultatif (liste courte + texte libre), jamais obligatoire.
- Écran (ticket de la vente, ticket-line.tsx) : toucher le prix unitaire ouvre un petit champ
  montant (pavé numérique du kit) avec « Prix habituel : 2 500 F » ; la ligne modifiée porte
  une mention visible (« prix changé ») ; « Revenir au prix habituel » en un geste.
- Reçu / facture : la ligne montre le prix appliqué (et la remise si elle existe
  aujourd'hui sur le reçu) ; rien de plus dans ce lot (la facture sera refaite au groupe 2).
- Tests : prix plus bas, plus haut (selon décision), à 0, revenu au prix habituel ; le prix
  tapé survit à la confirmation ; marge et chiffre d'affaires du tableau de bord, retours et
  remboursements calculés sur le prix appliqué (un retour rend ce qui a été payé, pas le prix
  de la fiche) ; vendeur, comptable sans droit de vendre refusé ; e2e caisse ; brouillon de
  vente (ADR 0101) qui garde le prix tapé.

D. Description d'un article
- Champ « Description » FACULTATIF, sous « Nom de l'article », dans Stock → Nouvel article,
  dans la modification de l'article et dans la version courte du scan (ADR 0106). Texte
  multiligne, 500 caractères au plus, compteur affiché, espaces de début et de fin retirés,
  vide = rien.
- Migration : `products.description text NULL` (ajout seul). API : création, modification,
  lecture ; import / export CSV et Excel (colonne facultative) ; recherche d'articles par la
  description NON (sauf si tu juges que c'est utile : demande-moi).
- Affichage : fiche de l'article (sous le nom) ; pas dans la grille de vente (lisibilité).
- Brouillons : le champ entre dans les listes blanches `product-new` et `product-edit`.
- Tests : backend (création avec et sans, 501 caractères refusé, isolation), Vitest, e2e.

E. Un article épuisé ne se vend pas, même par un autre chemin
- La grille de vente grise déjà un article épuisé et la base refuse tout stock négatif
  (CG020) à la confirmation. Le propriétaire dit en avoir vu passer : REPRODUIS par tous les
  chemins d'ajout au panier (grille, recherche, scan, douchette, brouillon retrouvé, bouton +
  au-delà du stock, deux caisses en même temps) et note lesquels laissent passer.
- Correction : pour un article suivi en stock, refuser l'ajout et l'augmentation au-delà du
  stock disponible dès le panier (serveur : add_item et update_item, message « Il n'en reste
  que 3 sacs » ; écran : bouton + désactivé au plafond, mention visible). La confirmation reste
  l'autorité finale (deux caisses en même temps) avec le même message clair. Article non suivi
  en stock : inchangé, et dis-le dans l'ADR.

F. Finitions visuelles (aucune logique métier)
- Un style unique de « bouton secondaire » pour tous les liens d'action aujourd'hui soulignés
  ou discrets, dans le kit (components/kit), puis appliqué partout : au minimum « Gérer les
  types de dépenses », « Toutes les dépenses », « Toutes les dettes » (clients et
  fournisseurs). Fais un inventaire automatique (recherche des liens soulignés dans app/ et
  components/) et liste dans l'ADR chaque endroit changé. Les liens de texte qui restent des
  liens (aide, conditions, « voir plus » dans une phrase) gardent leur forme : justifie.
- Formulaires « Gérer les types de dépenses » et « Catégorie » (rayons) : même mise en forme
  que les autres formulaires de la maquette v2 (champs, espacements, boutons, erreurs).
- Carte « À surveiller » de l'accueil : la carte (et son titre) mène à la liste des articles
  à stock bas (Stock, filtre « bas et épuisés » déjà présent ou ajouté), l'adresse portant le
  filtre ; chaque ligne garde son lien vers la fiche.
- Fiche d'un article : « Modifier » (nom, description, rayon, unité, prix) et « Supprimer »
  bien visibles (aujourd'hui la modification existe à /products/[id]/edit mais se trouve mal).
  Supprimer : confirmation claire, règles existantes (ADR 0014 : refus en base si l'article a
  un historique qui l'interdit ; sinon suppression logique) avec un message en mots simples.
  Droits existants (products:update, products:delete).
- Contraintes : maquette v2, jetons existants, aucune couleur en dur, cibles 44 px, axe 0
  violation en clair et en sombre, 360 px sans défilement horizontal. Mets à jour
  make maquette-check pour les écrans qui changent volontairement (captures avant / après) et
  corrige au passage le test de l'écran 06 qui cherche « 2 800 F » dans la mauvaise phrase.

A. Fin du groupe
Suite backend complète, ruff, mypy, make front-check, make maquette-check, e2e des écrans
touchés, tests de fuite inter-tenant, CI verte. ADR, CLAUDE.md §8, frontend/README.md.
Liste dans le résumé ce que le propriétaire doit vérifier après déploiement.
```

## Ce que le propriétaire fait lui-même

1. Répondre aux questions de l'agent (prix plus haut que la fiche, recherche par description).
2. Fusionner, déployer (`cd /opt/coges && sudo -u deploy /opt/coges/deploy.sh production <version>`), puis vérifier sur un téléphone :
   - vendre un article en changeant son prix : le ticket montre le nouveau prix, la fiche garde l'ancien ;
   - créer un article avec une description ;
   - essayer d'ajouter un article épuisé par la recherche et par le scan : refus clair ;
   - la carte « À surveiller » ouvre la liste des stocks bas.
3. Seulement ensuite, passer au groupe 2.
