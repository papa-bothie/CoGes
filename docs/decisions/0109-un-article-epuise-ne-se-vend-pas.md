# 0109 — Un article épuisé ne se vend pas, même par un autre chemin

- **Date** : 2026-11-03
- **Phase** : groupe 1, bloc E (prompt 34, branche `feat/group1-e-no-sale-beyond-stock`)
- **Statut** : acceptée (complète 0052)
- **Décideur** : propriétaire (règle décrite dans le prompt) ; « déjà tranché par
  l'architecture » pour l'autorité finale (stock négatif interdit, `CG020`, § 8.5)

## Contexte
Le propriétaire dit avoir vu passer un article épuisé à la caisse. La base refuse tout
stock négatif à la confirmation (`CG020`, ADR 0018), et la grille grisait déjà une tuile
« Épuisé ». Reproduction, chemin par chemin, avant correction (tests rouges
`tests/integration/test_sale_beyond_stock.py`, lecture du code de l'écran) :

| Chemin | Avant | Laisse passer ? |
|---|---|---|
| Grille, article suivi **jamais reçu** (aucune ligne `product_stock`) | tuile active, `POST …/items` accepté (201) | **oui, au panier** |
| Grille, toucher la tuile au-delà du stock | chaque toucher = + 1, accepté | **oui, au panier** |
| Recherche puis Entrée / douchette (code puis Entrée) | ajoute le seul résultat sans lire le stock, même épuisé | **oui, au panier** |
| Scan caméra | absent de l'écran de vente (seulement Stock et livraison) | — |
| Bouton + au-delà du stock | aucun plafond, `PATCH` accepté (200) | **oui, au panier** |
| Quantité tapée au-delà | `PATCH` accepté | **oui, au panier** |
| Deux lignes du même article | chaque ligne vérifiée nulle part | **oui, au panier** |
| Brouillon retrouvé après une baisse du stock | aperçu « Stock insuffisant », confirmation bloquée à l'écran | non |
| Deux caisses en même temps | la seconde confirmation refusée (`CG020`) avec un message technique | non |

Aucun chemin ne **confirmait** une vente au-delà du stock d'un article suivi : ce que le
propriétaire a vu passer, c'est l'article **au panier**, refusé seulement à
l'encaissement, avec « Stock insuffisant : cette sortie rendrait la quantité négative. »

## Options envisagées
1. **Refuser dès le panier, confirmation toujours autorité (retenue)** : contrôle sans
   verrou à l'ajout et à l'augmentation, même message à la confirmation, verrou posé.
2. Réserver le stock au panier : un brouillon abandonné bloquerait la marchandise ;
   contraire au brouillon « sans effet de bord » (§ 5.1). Écartée.

## Décision
- **Serveur** : `inventory_service.assert_available` (façade) refuse, pour un article
  **suivi**, une quantité au panier supérieure au stock ; `add_item` et `update_item`
  (seulement quand la quantité monte) l'appellent avec la somme de **toutes** les lignes du
  même article. Code `insufficient_stock` (409) inchangé, message « Il n'en reste que
  3 sacs. » ou « Cet article est épuisé : il n'en reste plus. », détails `product_id`,
  `requested`, `available`. Unités accordées par `app/core/display.qty_with_unit` (la table
  des unités quitte `analytics/history.py` pour `core/display.py`).
- **Confirmation** : `record_sale_out` verrouille d'abord la ligne `product_stock`
  (`FOR UPDATE`, l'ordre des articles de § 5 inchangé, le même verrou que `t20_inv_apply`
  aurait pris) puis refuse avec le **même** message et la quantité exacte. `CG020` reste
  l'autorité pour qui écrirait sans passer par là.
- **Écran** : un article suivi sans ligne de stock vaut 0 ; tuile grisée quand il est
  épuisé (« Épuisé ») ou déjà tout entier au panier (« Tout est au panier ») ; Entrée de la
  recherche n'ajoute pas un article au plafond et le dit (`role="status"`) ; bouton + de la
  ligne désactivé au plafond avec « Il n'en reste que 2 pièces. » ; quantité tapée au-delà :
  le refus du serveur s'affiche sur la ligne ; refus de la confirmation et aperçu du
  brouillon retrouvé : les mêmes mots (l'ancien « Stock insuffisant — N disponible(s) » est
  retiré de l'écran de vente).
- **Article non suivi en stock** (service, recharge) : **inchangé**, aucune limite, aucun
  mouvement à la confirmation.

## Conséquences
- Les tests qui fabriquaient un panier au-delà du stock pour éprouver la confirmation
  (T39, concurrence) baissent désormais le stock **après** le panier, ce qui est le cas
  réel (deux caisses, perte saisie entre-temps).
- Le contrôle du panier n'est pas une réservation : deux caisses peuvent chacune mettre le
  dernier sac au panier ; la seconde confirmation est refusée, en mots.
