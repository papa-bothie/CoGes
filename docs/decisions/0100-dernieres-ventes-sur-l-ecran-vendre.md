# 0100 — Les dernières ventes sur l'écran Vendre

- **Date** : 2026-10-28
- **Phase** : prompt 28, bloc C4 (corrections du terrain)
- **Statut** : acceptée
- **Décideur** : déjà tranché par le prompt 28 (C4)

## Contexte
Dans l'onglet Vendre, on ne voyait pas la liste des dernières ventes : retrouver la vente d'il y a
un instant (pour un reçu, un retour, une erreur) obligeait à quitter la caisse.

## Décision
- Bloc « Dernières ventes » (`frontend/components/sales/recent-sales.tsx`) sur `/sales/new` : les
  **8 dernières ventes** de l'entreprise, sans brouillon, par la route de liste existante
  (`GET /api/v1/sales?include_drafts=false&page=1&page_size=8`), **aucune route nouvelle**.
- Chaque ligne (kit `ListRow`, `StatusPill`) : client (ou « Client de passage »), « Vente n° 42 ·
  10:15 », montant, pastille Payé / Reste X / Retour / Annulée / Dette abandonnée. Une vente annulée
  ou retournée porte aussi une **icône** et son montant est barré pour l'annulée : jamais la couleur
  seule. Un toucher ouvre la vente ; « Voir toutes les ventes » mène à `/sales`.
- Visible pour qui a `sales:read` (le vendeur l'a). Placé **sous le panier**, dans la colonne de
  droite dès 1024 px, sous la grille sur téléphone : le bloc ne pousse jamais le panier ni le bouton
  d'encaissement. Repliable (bouton à `aria-expanded`).
- Actualisé après chaque vente confirmée ou annulée : sa clé est sous `sales.all`, que ces deux
  écritures invalident déjà.
- Squelette au chargement, « Aucune vente pour l'instant » si vide ; une erreur reste dans le bloc
  (« Vous pouvez vendre quand même », « Réessayer ») et n'empêche pas de vendre.

## Conséquences
- À 360 px, la pastille passe sous le numéro de vente : en fin de ligne, « Retour : 8 000 F »
  débordait de 14 px (trouvé par l'e2e).
- Tests : Vitest (`components/sales/recent-sales.test.tsx` : requête, vide, erreur sans relance,
  ligne annulée en mots et icône, repli), e2e `frontend/e2e/recent-sales.spec.ts` (une vente
  confirmée apparaît en tête ; axe 0 violation ; 360 px sans défilement horizontal ; le bloc vient
  après le bouton d'encaissement ; repli).
