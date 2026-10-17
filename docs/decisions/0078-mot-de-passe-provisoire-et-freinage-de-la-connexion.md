# 0078 — Mot de passe provisoire à 48 h, freinage de la connexion par compte

- **Date** : 2026-10-17
- **Phase** : lot A (sécurité avant la production)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
Un mot de passe provisoire (ADR 0074) est connu de qui l'a donné et n'expirait jamais.
La connexion n'avait qu'un plafond **par IP** (ADR 0042) : un attaquant qui change d'IP
peut deviner sans frein le mot de passe d'un compte, et une panne de Redis levait toute
limite. Décision 16 de l'architecture : JWT courts, Argon2, limitation de débit.

## Options envisagées
1. **Échéance en colonne + freinage progressif par compte dans Redis, repli en mémoire
   pour `/auth/login` (retenue)**.
2. Verrouillage du compte après N échecs : refusé, n'importe qui pourrait bloquer la gérante.
3. Freinage en base : une écriture par échec, et la base de préproduction ne dormirait plus.

## Décision
**Mot de passe provisoire** (révision 0022)
- `users.must_change_password_until` = `now() + COGES_TEMP_PASSWORD_TTL_HOURS` (48) à chaque
  provisoire posé (création sans mot de passe, mot de passe donné par le gérant), `NULL`
  quand la personne choisit le sien. CHECK `users_temp_password_coherent`.
- Comptes déjà provisoires au moment de la migration : `NULL`, **sans échéance**.
- `auth_lookup` rend aussi `must_change_password` et l'échéance (supprimée puis recréée sous
  `coges_auth`, mêmes droits). Après le mot de passe **vérifié**, un provisoire échu donne
  401 `temporary_password_expired` ; l'heure est réelle, jamais `app.core.clock`.
- La tentative refusée est auditée (`action = login`, `after.refused`) et racontée dans
  l'Historique (« Awa n'a pas pu se connecter : mot de passe provisoire expiré ») : c'est la
  seule ligne `login` que l'Historique montre.
- Écran 24b : « Mot de passe provisoire · Expire le jj/mm à h h mm » ou « Expiré », et le
  geste **« Donner un nouveau mot de passe »**, qui n'existait pas : `POST
  /users/{id}/password` accepte un corps vide, le serveur tire alors un provisoire lisible,
  rendu une seule fois (`temporary_password`, comme à la création).

**Freinage par compte** (`app/core/rate_limit.py`)
- Clé `rl:acct:{sha256(slug|identifiant normalisé)}`, posée pour ce qui est **tapé**, que le
  compte existe ou non. Script Lua atomique : 5 échecs dans la fenêtre de 15 min ⇒ 1 min,
  puis 2, 4, 8… jusqu'à 30 min. Remise à zéro au succès. Pas de verrou définitif.
- Pendant l'attente : 429, `Retry-After`, « Trop d'essais. Réessayez dans N minutes. »,
  `details.scope = "account"` ; aucune recherche d'identité, aucun Argon2.
- Un provisoire expiré mais juste n'est **ni un échec ni un succès** pour le compteur.
- Au 10ᵉ échec d'un compte réel : alerte `login_failures` (nouveau type, CHECK de
  `notifications.type` étendu, écart assumé au § 8.8), aux porteurs de `users:update`,
  gravité « attention », une par heure au plus et par compte visé (`notify(dedupe_hours=1)`).
- Auth est de la Plateforme, les alertes de la Restitution : l'alerte est **enfilée par nom**
  (`notifications.login_failures`, `core/queue.py`) et écrite par le worker. Sans Redis ni
  worker, l'alerte se perd ; le freinage, lui, tient.
- Seuils dans `config.py` (`COGES_LOGIN_THROTTLE_*`).

**Mode dégradé sans Redis** : `/auth/login` seul bascule sur `_MemoryCounters` (même plafond
par IP, même barème par compte, 10 000 clés, LRU, verrou). Journal + Sentry « limitation de
connexion en mode dégradé », une fois par minute au plus. Les autres routes gardent « limite
désactivée ». Sur Vercel, une mémoire par instance : frein dégradé, pas une garantie.

## Conséquences
- Révision 0022 ; `AuthIdentity`, `UserRead.must_change_password_until`, `UserCreated` en
  réponse de `POST /users/{id}/password`.
- Les suites de tests et l'API e2e posent un seuil hors d'atteinte
  (`COGES_LOGIN_THROTTLE_FREE_FAILURES=1000000`) ; `test_login_throttle.py` pose le sien.
- Au-delà du 10ᵉ échec d'un compte réel, la réponse est identique mais l'enfilement de la
  tâche ajoute quelques millisecondes : l'attaquant est déjà freiné à ce stade.
- Tests : `test_temporary_password_expiry.py` (refus à 48 h 01, accepté à 47 h 59, `NULL`
  après changement, provisoire tiré), `test_login_throttle.py` (barème, pas d'Argon2,
  non-énumération, alerte, Redis absent ou en panne, éviction).
