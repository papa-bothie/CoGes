# 0074 — Conseils, alertes et connexion de la maquette v2 (lot 3e-1)

- **Date** : 2026-10-14
- **Phase** : 15 (lot 3e, première PR)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion, 2026-10-14)

## Contexte
Le lot 3e reproduit les écrans 22 à 25 de la maquette v2. Il est découpé en deux PR
(choix du propriétaire) :
- la première, celle-ci, couvre les Conseils (22, 22b, 22c), les Alertes (23) et la Connexion (25) ;
- la seconde couvrira les Réglages (24 à 24e).

La maquette demande trois choses que CoGes ne faisait pas :
- ajouter une personne par son téléphone, avec un mot de passe provisoire qu'elle change à la première connexion ;
- un classement « Vente rare » en jours sans vente ;
- les prévisions de « la semaine prochaine ».

## Options envisagées et décisions

**Connexion par téléphone ou e-mail, avec changement forcé** (retenue). L'autre option
était l'e-mail seul, avec ou sans changement forcé.
- Révision 0019 :
  - `users.phone` : chiffres seuls, unique par entreprise ;
  - `users.email` devient facultatif (contrainte : un e-mail ou un téléphone) ;
  - `users.must_change_password`.
- `auth_lookup(slug, identifiant)` garde sa signature, donc son propriétaire `coges_auth` et ses droits (ADR 0005, T36). Un identifiant avec « @ » se compare à l'e-mail, sinon au numéro, ramené à ses chiffres par `app/core/phone.py`. L'indicatif 221 est retiré devant un numéro à 9 chiffres.
- `POST /auth/login` prend `identifier` ; `email` reste accepté.
- Un numéro illisible ne cherche personne, mais le mot de passe est quand même vérifié contre le leurre. Un refus dit seulement que « le code de la boutique, l'identifiant ou le mot de passe ne correspond pas » (ADR 0005).
- **Mot de passe provisoire** : un compte créé sans mot de passe en reçoit un lisible (« BAOBAB-4821-KORA », 14 caractères au moins, tiré par `secrets`).
  - Il est rendu **une seule fois** dans la réponse de `POST /users`.
  - Le compte doit le changer avant toute chose : tant que l'indicateur est levé, seuls `/auth/me` et `POST /auth/password` répondent, toutes les autres routes renvoient 409 `password_change_required`.
  - Le front ouvre « Choisissez votre mot de passe ».
- Un mot de passe choisi à la création (CLI, seed, API) reste tel quel. Un mot de passe remplacé par le gérant pour quelqu'un d'autre doit être changé.
- Le `downgrade` de la révision 0019 donne aux comptes sans e-mail l'adresse `<numéro>@telephone.invalid`. FORCE est levé le temps de cette seule mise à jour.

**Conseils** (écran 22, `/insights` ; `/analytics` y renvoie) : trois vues.
- **Conseils**, une carte par type :
  - un titre en phrase, une couleur, une action directe (« Commander », « Lui envoyer un rappel », « Voir l'article », « Changer le prix »…) ;
  - « C'est fait » (`resolved`) et « Ignorer » (`dismissed`) ;
  - un lien « Pourquoi ? » qui ouvre le panneau avec la métrique, la date, le modèle et l'incertitude : la règle « une recommandation nomme sa métrique » est tenue ;
  - « Données insuffisantes » n'est plus une carte, mais une ligne sous la liste.
- **Seuls les types que l'Intelligence produit apparaissent** (retenu). Les types `expense_anomaly`, `cash_shortfall` et `cashier_anomaly` ont leur titre et leur action, mais aucun calcul ne les émet encore. La carte « électricité » de la maquette est un écart.
- **Vos meilleurs articles** : le titre de la maquette est gardé (choix du propriétaire).
  - C'est une étiquette de navigation : chaque puce et chaque titre nomment leur métrique (« Ce qui vous rapporte le plus »…).
  - Aucun classement n'est anonyme, et la règle « jamais "meilleur produit" » s'applique aux classements, pas à ce titre d'onglet.
- **« Vente rare »** : une neuvième métrique nommée, `days_since_last_sale` (« Jours sans vente », unité jour). Elle ne compte que les articles en stock ; un article jamais vendu compte depuis sa dernière entrée en stock.
- **Prévisions** : `GET /analytics/next-week`.
  - Pour chaque article, la somme des 7 prochains jours prévus et la somme des bornes (une fourchette prudente).
  - Il donne aussi le stock restant, en orange s'il ne couvre pas la semaine.
  - Les articles sans historique suffisant sont comptés, le modèle et la date du calcul nommés.
  - Une prévision nulle ne fait pas de tuile.

**Textes en mots simples, du côté du serveur** : alertes du worker et gabarits d'insight, sans accord, puisqu'on ne connaît pas le genre d'un article.
- Exemples : « Riz brisé 25 kg va bientôt manquer », « Il vous en reste 13 et vous en vendez environ 8,7 par jour… Commandez-en 109 pour tenir deux semaines. », « Huile Dinor 1 L : plus que 4 », « Moussa Fall n'a pas payé à temps », « Vente n° 1042 annulée ».
- La métrique reste nommée dans `evidence`.
- L'alerte de dette porte désormais la personne (`party_id`), pour que « Encaisser » et « Payer » ouvrent les écrans 18 et 19.

**Alertes** (écran 23) :
- les alertes sont groupées par jour, avec une couleur et une icône par type, un point quand elles sont non lues, et une action directe ;
- « Tout marquer comme lu » appelle `POST /notifications/read-all`, qui ne touche que le fil de l'utilisateur ;
- le filtre « Non lues » ;
- les alertes plus anciennes s'affichent avec « Voir les alertes plus anciennes ».

**Seed `maquette`** :
- il rejoue ses événements à travers les vrais consommateurs d'alertes, puis le balayage des dettes échues du 6 octobre ;
- avec `--intelligence` (que `make seed-maquette` et la remise à zéro e2e passent), il lance le calcul de la nuit du 6 octobre, recalé sur 2 h.

## Conséquences
- Tests :
  - `tests/integration/test_lot_3e_access.py` : téléphone tapé de quatre façons, mot de passe provisoire rendu une fois, routes bloquées puis débloquées, mauvais mot de passe actuel, même mot de passe, règles de contact, e-mail et ancien champ, réinitialisation par le gérant, « Vente rare », semaine prochaine sans prévision ;
  - « Tout marquer comme lu », dont la fuite entre entreprises ;
  - textes des alertes ;
  - Vitest : actions et liens des alertes, neuf métriques ;
  - e2e : connexion par téléphone puis changement de mot de passe, Afficher et Cacher, « Tout marquer comme lu », conseil « C'est fait » et son « Pourquoi ? », puces du classement.
- Le test d'architecture « pas de `SET` sans `LOCAL` » accepte désormais `ALTER COLUMN … SET NOT NULL | DEFAULT` dans une migration.
- Écarts à la maquette dans `docs/design/maquette-v2/ecarts.md`.
