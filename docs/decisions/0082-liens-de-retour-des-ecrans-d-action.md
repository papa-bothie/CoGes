# 0082 — Liens de retour des écrans d'action

- **Date** : 2026-10-17
- **Phase** : hors phase (retouche du front après la phase 15)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte

Sept écrans n'avaient aucun lien pour revenir en arrière : Entrées et sorties (caisse),
Encaisser une dette, Payer un fournisseur, Dépenses (L'argent), Corriger le stock,
Recevoir une livraison, Modifier un article (Stock). La maquette v2 ne leur en donne pas
(seules les fiches ont « ← Tous les articles », « ← Tous les clients ») et le front l'avait
suivie. On y arrive pourtant de plusieurs endroits (fiche client, vente, fiche article,
Conseils, Alertes, Accueil) : la seule sortie était la barre de navigation, qui perd la
fiche d'où l'on venait.

## Options envisagées

1. **Revenir d'où l'on vient (retenue)** : le lien d'entrée passe son chemin en `?from=`,
   l'écran le nomme ; sans `from`, l'écran parent. Même résultat après un rechargement ou
   un lien partagé.
2. Toujours l'écran parent : simple, mais perd la fiche d'origine.
3. Page précédente du navigateur : libellé forcément vague (« Retour »), comportement
   imprévisible à l'arrivée directe.

Placement : **ligne au-dessus du titre (retenue)**, le même lien que les fiches et
« Toutes les dettes », plutôt qu'une flèche seule à gauche du titre (deuxième modèle).

## Décision

- Composant unique `components/back-link.tsx` (`BackLink`), aussi utilisé par
  `FinanceSubpage` ; logique dans `lib/back-target.ts` (`resolveBack`, `withFrom`).
- `from` n'est suivi que s'il reste sur CoGes : `safePath`, la règle de la destination
  après connexion (ADR 0049), extraite de `safeNext`. Sinon, l'écran parent.
- Libellé : nom de la personne ou de l'article, « Vente n° 1044 », lus dans le cache des
  requêtes sans nouvelle lecture (« Fiche du client », « La vente »… si le cache est vide) ;
  sinon la rubrique (Accueil, L'argent, Stock, Conseils, Alertes).
- `from` est posé par : fiche client, vente, fiche fournisseur, page « Ajouter une
  personne », fiche article, Conseils, Alertes et la tuile de l'accueil. Les liens depuis
  L'argent ou Stock n'en ont pas besoin. Choisir une personne ou un jour garde `from`.
- Modifier un article revient toujours à sa fiche.

## Conséquences

- Écart à la maquette noté dans `docs/design/maquette-v2/ecarts.md` ; ces écrans étaient
  déjà exemptés du seuil de pixels de `make maquette-check`.
- Les adresses de ces écrans portent `&from=…` (tests des alertes mis à jour).
- Tests : `lib/back-target.test.ts` (origines refusées, libellés), `e2e/back-links.spec.ts`,
  retour à la fiche dans `e2e/customers.spec.ts`.
