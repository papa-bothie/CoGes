# 0101 — Brouillons de saisie conservés sur l'appareil

- **Date** : 2026-10-28
- **Phase** : prompt 29, P1 (brouillons et PWA)
- **Statut** : acceptée
- **Décideur** : déjà tranché par le prompt 29 (P1) ; écrans figés ici après lecture du code

## Contexte
Le panier d'une vente est déjà un brouillon **côté serveur** (ADR 0070). Tout le reste d'une
saisie vivait dans la mémoire du composant : changer d'écran, recharger ou laisser le téléphone
décharger la page faisait tout perdre.

## Décision
### Le magasin (`frontend/lib/drafts.ts`) et le crochet (`frontend/hooks/use-draft.ts`)
- **localStorage**, jamais sessionStorage seul ; chaque accès sous `try/catch` (absent, plein ou
  bloqué : l'écran marche sans).
- **Clé** `coges:draft:v1:<entreprise>:<personne>:<formulaire>[:<objet>]`, identité lue dans
  `/auth/me` : personne d'autre, ni une autre entreprise, ne relit un brouillon, même sur le même
  navigateur. Aucun brouillon en accès support (lecture seule).
- **Valeur** `{ v, at, fields }` : version du formulaire, horodatage, champs de la **liste
  blanche** seulement. Une version inconnue est ignorée et retirée. Chaque champ relu est revérifié
  (type, valeur permise) avant d'être remis dans le formulaire.
- **Écriture** 400 ms après la dernière frappe, et tout de suite quand la page est cachée
  (`visibilitychange`, `pagehide`) ou au démontage. Une saisie égale à l'état de départ, ou vide
  sur ses champs « significatifs », n'est pas un brouillon (elle est effacée).
- **Durée de vie** 24 heures sans modification. Effacé à l'envoi réussi, à « Effacer », à la
  déconnexion et à l'expiration de session (`forgetLocally` → tous les brouillons de la personne),
  et nettoyé à chaque ouverture de l'application.
- **Deux onglets** : le dernier qui écrit gagne (événement `storage`) ; une valeur reçue n'est pas
  réécrite (pas de ping-pong) ; un envoi en cours n'est pas écrasé (`busy`).
- **Retrouvé** : les champs reviennent et un bandeau discret « Brouillon retrouvé » propose
  « Effacer » — jamais une fenêtre bloquante. Après un envoi réussi, la saisie encore affichée n'est
  plus réécrite tant qu'elle ne change pas.
- **Idempotence** : la clé d'écriture fait partie du brouillon (`useIdempotencyKey().restore`). Un
  envoi interrompu puis retrouvé rejoue avec **la même** clé : jamais deux ventes, deux paiements,
  deux livraisons (ADR 0027, 0085). Elle disparaît avec le brouillon à l'envoi réussi.
- `hasUnsentDrafts()` dit si une saisie n'est pas envoyée : la mise à jour silencieuse de la PWA
  (P2) attend alors.

### Écrans et champs conservés (liste figée)
| Écran | Formulaire | Champs |
|---|---|---|
| Vendre (`sale-editor`) | `sale-payment` (par vente) | mode, montant payé, somme donnée, moyen, échéance, client choisi avant le 1er article, clé |
| Retour (`return-form`) | `sale-return` (par vente) | quantités, motif, que faire de l'argent, montant, moyen, deux clés |
| Encaisser / payer (`settle-screen`) | `settle-customer` / `settle-supplier` (par personne) | montant, moyen, clé |
| Dépense (`expenses-view`) | `expense` | type, montant, jour, moyen, clé |
| Livraison (`delivery-form`) | `delivery` | fournisseur, lignes (article, quantité, prix), mode, payé, moyen, échéance, clé |
| Correction de stock (`stock-correction`) | `stock-correction` (par article venu de sa fiche) | article, sens, quantité, raison, clé |
| Nouvel article (`new-product-form`) | `product-new` | nom, prix, prix d'achat, unité, rayon, stock d'ouverture, seuil, code-barres |
| Modifier un article (`product-form`) | `product-edit` (par article) | les champs du formulaire |
| Nouveau rayon (`categories-view`) | `category-new` | nom, couleur |
| Client / fournisseur (`person-form`) | `person-new`, `person-customer`, `person-supplier` (par fiche) | genre, nom, téléphone, e-mail, adresse |
| Ajouter une personne (Réglages) | `user-new` | nom, téléphone ou e-mail, rôle — **aucun mot de passe** (le provisoire est tiré par le serveur) |

**Jamais conservés** : mots de passe (connexion, première connexion, « Changer mon mot de passe »),
codes, jetons, références de paiement saisies à la main. Un test e2e tape une valeur piège dans les
champs mot de passe et la cherche dans tout le stockage.

### Le serveur reste l'autorité
Un brouillon ne contourne rien : prix, stock, client, article ou rayon sont revérifiés à l'envoi.
Une livraison retrouvée relit ses articles au serveur et retire, en le disant, ceux qui n'existent
plus ; un retour retrouvé ne rend jamais plus que ce qui reste à retourner (CG040 tranche de toute
façon).

## Conséquences
- Next 16 garde l'écran quitté en mémoire (Activity) : revenir par le menu rend la saisie intacte,
  sans bandeau (rien n'est « retrouvé ») ; le bandeau apparaît après un rechargement ou une page
  déchargée par le téléphone.
- Sur un téléphone partagé, la déconnexion efface les brouillons ; sans déconnexion, ils restent au
  nom de la personne, invisibles pour les autres, au plus 24 heures.
- Tests : Vitest du magasin (clé, liste blanche, version, 24 h, panne de stockage, déconnexion) et du
  crochet (écriture différée, page cachée, reprise, autre personne, effacement, onglet voisin) ;
  e2e `frontend/e2e/drafts.spec.ts` (dépense retrouvée après un autre écran et un rechargement,
  effacée à l'envoi ; déconnexion ; autre personne ; mot de passe jamais gardé ; vente à moitié
  encaissée retrouvée, une seule vente à la fin).
