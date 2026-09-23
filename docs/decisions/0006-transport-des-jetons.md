# 0006 — Transport et durée de vie des jetons

- **Date** : 2026-09-23
- **Phase** : 02
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Le choix du transport détermine la surface d'attaque (XSS, CSRF) et la configuration CORS du
frontend de la phase 11.

## Décision

**Access token** : JWT HS256, renvoyé dans le corps de la réponse, conservé **en mémoire** par
le navigateur. Durée : **15 minutes**.

**Refresh token** : cookie `httpOnly; Secure; SameSite=Lax`, chemin `/api/v1/auth`. Durée :
**7 jours**. Il n'apparaît jamais dans le corps d'une réponse.

`Secure` est désactivé quand `COGES_ENV=local`, sinon le cookie ne circulerait pas en HTTP.

La clé de signature fait **32 caractères minimum**, refusée au démarrage en deçà : HMAC-SHA256
avec une clé plus courte que sa sortie affaiblit la signature (RFC 7518 § 3.2).

## Conséquences

- Un XSS ne peut pas lire le refresh token : il est hors de portée de JavaScript. Il pourrait
  voler l'access token, mais celui-ci expire en 15 minutes.
- `SameSite=Lax` empêche l'envoi du cookie sur une requête POST venue d'un autre site : c'est ce
  qui couvre le risque CSRF sur `/auth/refresh`, sans jeton anti-CSRF généralisé.
- Le frontend devra rafraîchir en tâche de fond avant expiration, et refaire l'appel une fois
  après un 401.
- CORS devra autoriser les identifiants (`credentials: include`) sur le seul domaine du front.
