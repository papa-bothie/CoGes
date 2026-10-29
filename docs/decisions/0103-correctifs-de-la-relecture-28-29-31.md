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

## Conséquences
- Tests : Vitest `hooks/use-draft.test.tsx` (+5), `lib/drafts.test.ts` (+2) ; e2e
  `frontend/e2e/drafts.spec.ts` (+3, et la vente vérifie désormais l'absence de brouillon une
  seconde après l'envoi puis au rechargement). Les e2e rouges ont été joués sur le code d'avant.
- Un brouillon n'est plus écrit pendant un envoi : une frappe faite à ce moment, puis une page
  tuée avant la fin, est perdue (l'envoi, lui, est rejoué à l'identique).
