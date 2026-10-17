# 0085 — Erreurs imprévues et coupures, vues par le commerçant

- **Date** : 2026-10-17
- **Phase** : prompt 19
- **Statut** : acceptée
- **Décideur** : cahier des charges du propriétaire, options recommandées appliquées

## Contexte

Quand quelque chose casse, le commerçant voyait une page blanche, un « Internal Server
Error » en texte brut, ou une page 502 de Caddy. Il doit voir un message clair, savoir
que ses données sont en sécurité, et pouvoir nous donner une référence.

## Décision

- **API** : toute exception non gérée est rattrapée par `RequestContextMiddleware` → 500
  au format du projet, `{"error": {"code": "server_error", "message": "Un souci de notre
  côté. Vos données sont en sécurité. Réessayez dans un instant.", "details": {},
  "request_id": "…"}}`, sans trace ni détail interne ; la même référence est dans
  l'en-tête `X-Request-Id`, dans le journal (avec la trace) et dans Sentry (étiquette
  `request_id`). Un `X-Request-Id` fourni par le client n'est repris que s'il est sage
  (`[A-Za-z0-9-]{8,64}`) : ni injection de ligne dans le journal ni d'en-tête.
- **Référence d'incident** : les 8 premiers signes de l'identifiant, en majuscules, en
  deux groupes (« AB12 CD34 ») : lisible au téléphone, assez pour retrouver la requête.
- **Front** : `app/error.tsx` et `app/global-error.tsx` (convention `retry` de Next 16)
  affichent `IncidentScreen` : titre qui reçoit le focus, phrase rassurante, référence,
  « Réessayer » et « Retour à l'accueil » ; jamais le message brut. `not-found.tsx` prend
  la même mise en page.
- **Coupures** : une LECTURE coupée (réseau, 502, 503, 504) est réessayée 3 fois, à 2, 4
  puis 8 s ; un bandeau « Connexion difficile. Nous réessayons… » s'affiche pendant les
  essais, puis « Connexion difficile. » avec « Réessayer » ; il disparaît seul au retour.
  Une ÉCRITURE n'est **jamais** rejouée en silence : la saisie reste à l'écran et
  « Réessayer » repart avec la **même** clé d'idempotence (déjà le cas, ADR 0052 ; prouvé
  par un test Vitest sur l'encaissement et un e2e sur la confirmation de vente).
- **Caddy** : `handle_errors 502 503 504` sert `deploy/vps/maintenance.html` (autonome,
  aucune ressource extérieure, clair et sombre selon le système, jetons de la maquette)
  avec le statut d'origine et les en-têtes de sécurité. Vérifié sur la pile locale :
  API arrêtée → `/api/v1/*` en 502 avec la page ; front arrêté → `/login` en 502 avec la
  page, HSTS présent.

## Vérifications

- Backend : 500 stable sans fuite (chemin, SQL, `company`, trace), référence dans la
  réponse, l'en-tête et le journal ; identifiant client forgé refusé.
- Vitest : écran d'incident (référence, focus, réessayer), état du bandeau, délais 2/4/8 s,
  écriture qui échoue puis rejouée avec la même clé.
- e2e : lecture coupée → bandeau → retour ; 500 sur la confirmation alors que la vente
  est enregistrée côté serveur → panier gardé, rejeu = une seule vente (stock 10 → 8).

## Conséquences

- `ApiError` porte `requestId` ; une 5xx sans corps de l'API (page de Caddy) donne le
  message rassurant au lieu du message générique.
- Le libellé `errors.backToDashboard` disparaît au profit de `incident.home`.
