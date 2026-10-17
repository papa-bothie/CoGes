# Prompt 16 — Lot A : sécurité avant la production

Branche `feat/security-lot-a`, depuis `main` à jour. Points 1, 2, 3 et 7 de la liste « avant la production », plus le test du point 5. À faire avant les prompts 17 (surveillance des workers) et 18 (VPS).

```
Lot A — Sécurité avant la production (branche feat/security-lot-a, depuis main à jour).
Règles habituelles : ADR aux prochains numéros libres, tests d'abord, aucun service payant,
ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/. Résumé en
français à la fin, questions ouvertes par AskUserQuestion.

A1. Expiration du mot de passe provisoire (48 h)
- Migration 0021 : users.must_change_password_until (timestamptz, nullable).
  Rempli à now() + COGES_TEMP_PASSWORD_TTL_HOURS (défaut 48) chaque fois qu'un mot de
  passe provisoire est posé (création d'une personne, réinitialisation par le gérant) ;
  remis à NULL quand la personne choisit son mot de passe.
- La fonction SECURITY DEFINER d'auth_lookup doit renvoyer ce champ (même migration,
  downgrade compris) ; AuthIdentity le porte.
- auth/service.login : APRÈS la vérification du mot de passe (jamais avant, pour ne rien
  révéler), si must_change_password et la date est dépassée -> refus 401 avec un code
  dédié `temporary_password_expired` et le message « Ce mot de passe provisoire a expiré.
  Demandez-en un nouveau au gérant. » Heure réelle (pas app.core.clock), comme les jetons.
- Écran 24b : sous une personne au mot de passe provisoire, « Expire le jj/mm à hh h mm »
  ou « Expiré », et le bouton existant pour en donner un nouveau. Écran de connexion :
  le message ci-dessus.
- Journal d'audit : « mot de passe provisoire expiré » à la tentative refusée.
- Tests : refusé à 48 h + 1 min, accepté à 47 h 59, NULL après changement, aucun écart
  de réponse entre identifiant inconnu et mot de passe faux (inchangé).

A2. Freinage progressif par compte
- Compteur Redis des échecs par (slug d'entreprise, identifiant normalisé), clé
  `rl:acct:{sha256(slug|identifiant)}` : aucune donnée personnelle en clair dans Redis.
  Clé posée pour l'identifiant TAPÉ, que le compte existe ou non (pas d'énumération).
- Barème : 5 échecs en 15 min -> attendre 1 min ; puis chaque nouvel échec double
  l'attente (2, 4, 8 min…) jusqu'à 30 min au plus. Remise à zéro après un succès.
  Pas de blocage définitif : on freine, on ne verrouille pas (sinon n'importe qui
  pourrait bloquer la gérante).
- Pendant l'attente : 429 + Retry-After, message « Trop d'essais. Réessayez dans
  N minutes. », même réponse que le compte existe ou non, et le mot de passe n'est pas
  vérifié (pas de coût Argon2 offert à l'attaquant).
- Le plafond par IP existant reste en place.
- Au 10e échec d'un compte réel, une notification au gérant de l'entreprise (« Plusieurs
  tentatives de connexion échouées sur le compte de X »), au plus une par heure.
- Seuils dans config.py ; tests du barème avec l'horloge substituable de rate_limit.

A3. Frein de connexion même sans Redis
- Si Redis est absent ou en erreur, /auth/login (et seulement lui) bascule sur un
  compteur en mémoire du processus : même plafond par IP et même barème par compte,
  dictionnaire borné (10 000 clés, plus anciennes évincées), protégé par un verrou.
- Journaliser et envoyer à Sentry « limitation de connexion en mode dégradé » (une fois
  par minute au plus). Les autres routes gardent le comportement actuel (limite désactivée).
- Documenter la limite : chaque processus de l'API a sa propre mémoire (2 processus
  uvicorn sur le VPS), c'est un frein dégradé, pas une garantie.
- Tests : Redis None et Redis qui lève -> le 429 arrive quand même sur /auth/login.

A5. Test d'un échec au COMMIT (preuve d'intégrité)
- Test d'intégration : confirmer une vente en forçant l'échec du COMMIT de la
  transaction tenant (par ex. contrainte différée violée, ou Session.commit remplacé pour
  ce seul appel). Attendu : réponse 5xx (jamais 2xx), vente toujours en brouillon,
  stock inchangé, aucun événement d'outbox, clé d'idempotence non enregistrée comme
  succès ; le même appel rejoué ensuite réussit.
- Même test pour : encaisser un paiement, corriger le stock.
- Si un de ces tests est rouge (succès renvoyé alors que rien n'est écrit), corrige
  core/deps.py ou tenancy pour que le COMMIT se fasse AVANT l'envoi de la réponse, puis
  montre la sortie rouge puis verte dans la PR. S'ils sont verts d'emblée, garde-les et
  explique dans l'ADR pourquoi l'ordre est déjà sûr.

A7. Analyses de sécurité en CI (.github/workflows/ci.yml)
- gitleaks sur TOUT l'historique (actions/checkout avec fetch-depth: 0), version figée,
  fichier .gitleaks.toml avec une liste blanche minimale et commentée (faux secrets des
  tests, .env.example).
- pip-audit sur les dépendances du backend (export uv, groupes prod et ml) ;
  `pnpm audit --prod --audit-level=high` sur le front.
- Échec du job sur une vulnérabilité haute ou critique. Exceptions dans un fichier
  versionné avec raison et date de fin, jamais d'ignore silencieux.
- Les mêmes vérifications chaque lundi (schedule) pour attraper les nouvelles failles.
- `make security-scan` pour les lancer en local.
- IMPORTANT : si gitleaks trouve un vrai secret dans l'historique, ARRÊTE-TOI et
  préviens-moi (nom du fichier, commit, type de secret, sans afficher sa valeur). Je le
  change moi-même ; ne réécris pas l'historique sans mon accord.

Fin du lot : suite backend complète, ruff, mypy, make front-check, e2e des écrans touchés
(connexion, 24b), tests de fuite inter-tenant, CI verte. Mets à jour README-infra.md
(nouvelles variables) et CLAUDE.md.
```
