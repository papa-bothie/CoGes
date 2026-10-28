# 0098 — Mots de passe : afficher / cacher partout, et « Changer mon mot de passe »

- **Date** : 2026-10-28
- **Phase** : prompt 28, bloc C2 (corrections du terrain)
- **Statut** : acceptée
- **Décideur** : déjà tranché par le prompt 28 (C2) ; règle des sessions inchangée

## Contexte
Un vendeur ou un comptable qui change son mot de passe ne pouvait ni afficher ni cacher ce qu'il
tapait : seul l'écran de connexion avait un bouton, « Choisissez votre mot de passe » avait trois
champs sans bouton, et rien ne permettait de changer son mot de passe en dehors de la première
connexion (Réglages est réservé au gérant).

## Décision
- **Un composant** `frontend/components/password-field.tsx` : champ, libellé, aide et erreur, et
  un bouton « Afficher / Cacher » (`aria-pressed`, nom « Afficher le mot de passe » / « Cacher le
  mot de passe », 48 px de haut). La valeur reste la même à la bascule ; le champ se remasque à
  chaque envoi du formulaire (`submitted`) et quand l'onglet est caché (`visibilitychange`).
  `autocomplete` imposé par le type (`current-password` ou `new-password`). La valeur ne quitte
  jamais le champ : ni adresse, ni journal.
- Il remplace le bouton de `login-form.tsx` et équipe les trois champs de la première connexion,
  désormais écrite avec `components/password-change-form.tsx` (actuel, nouveau, « Retapez le
  nouveau mot de passe »), partagé avec le nouvel écran.
- **« Changer mon mot de passe »** (`/account/password`) : dans le menu du compte (l'engrenage),
  pour **tous** les rôles, sans droit requis. Règle de longueur (12 caractères au moins) affichée
  sous le champ avant toute erreur, concordance vérifiée avant l'envoi, mêmes messages que la
  première connexion. Appelle `POST /api/v1/auth/password`, qui existait déjà.
- **Administration** : copie du composant dans `frontend-admin/components/password-field.tsx`
  pour sa connexion (aucun import entre les deux applications, ADR 0089).

## Sessions après un changement (vérifié, inchangé)
`POST /auth/password` (`auth/router.py`, ADR 0088) remplace le mot de passe, **révoque toutes les
autres sessions** de la personne et rouvre celle de ce navigateur (nouveau cookie de
rafraîchissement). L'écran le dit : « Vos autres appareils sont déconnectés ». Aucune règle n'a été
changée.

## Conséquences
- Tests : Vitest (`components/password-field.test.tsx` : masqué par défaut, bascule sans perte,
  remasqué à l'envoi et à l'onglet caché ; copie de l'administration), e2e
  `frontend/e2e/password.spec.ts` (le vendeur et le comptable changent leur mot de passe depuis le
  menu, l'ancien est refusé, ils se reconnectent avec le nouveau ; axe 0 violation ; bascule de la
  connexion).
- Les e2e de l'administration qui cherchaient `getByLabel("Mot de passe")` passent en
  `exact: true` : le bouton « Afficher le mot de passe » porte aussi ces mots.
