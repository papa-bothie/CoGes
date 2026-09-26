# 0042 — Sécurité HTTP, garde-fous de `coges_owner`, observabilité

- **Date** : 2026-09-26
- **Phase** : 10 (temps B)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
Décision 16 : « limitation de débit par IP et par tenant, schémas Pydantic stricts, clés
d'idempotence sur les écritures financières, secrets hors dépôt, sauvegardes avec
restauration testée ». Risque propre au projet : `coges_owner` est membre de deux rôles
`BYPASSRLS` (ADR 0005, 0032) et pourrait lire toutes les entreprises par un changement de
rôle.

## Options envisagées
1. Débit : **par IP et par tenant, compteurs Redis codés à la main (retenu)** ; par IP
   seulement ; bibliothèque slowapi.
2. Observabilité : **Sentry + logs JSON (retenu)** ; logs seuls ; OpenTelemetry.
3. Appartenance de `coges_owner` : **conservée et bornée (retenu)** ; retirée après chaque
   migration — il faudrait alors un DSN administrateur encore plus puissant dans la CI,
   et un échec au milieu laisserait l'appartenance en place.
4. Idempotence : **clé exigée aussi sur la création d'un retour (retenu)** ; sur les
   quatre écritures restantes ; aucun changement.

## Décision
- **Débit** (`core/rate_limit.py`) : fenêtre fixe d'une minute (`INCR` + `EXPIRE`), 300
  requêtes par IP, 10 connexions par IP, 1 200 requêtes par entreprise. Le compteur
  d'entreprise est posé dans `get_tenant_session`, sur le `company_id` **relu en base**.
  429 `rate_limited` avec `Retry-After`. Redis en panne : la limite est levée et
  l'incident journalisé, sans erreur 500. L'IP n'est lue dans `X-Forwarded-For` que si
  `COGES_TRUST_PROXY_HEADERS` est actif (derrière Vercel).
- **Middlewares ASGI** (`core/http_security.py`) : 413 `payload_too_large` au-delà de
  1 Mo (4 Mo sur `/imports`), y compris pour un corps sans `Content-Length` ; en-têtes
  `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP `default-src 'none'`, et HSTS
  hors local ; CORS limité à `COGES_CORS_ORIGINS`, avec `credentials` pour le cookie de
  rafraîchissement. Documentation interactive et `openapi.json` coupés en production.
- **Schémas** : un test lit le contrat OpenAPI et exige `additionalProperties: false` sur
  tout corps JSON — tous l'avaient déjà.
- **Idempotence** : `POST /sales/{id}/returns` exige désormais `Idempotency-Key`, avec une
  clé liée à la vente (ADR 0039). L'annulation de vente et l'abandon de créance (protégés
  par leur état : 409 au second appel, sans effet) et la modification d'une dépense (un
  PATCH en valeurs absolues) restent sans clé. La liste fermée est vérifiée par
  `test_financial_writes_require_idempotency.py`.
- **Garde-fous `coges_owner`** :
  1. `core/role_guard.py` : à la première connexion de chaque engine (événement
     `first_connect`, rejoué tant qu'il échoue), refus si `current_user` est
     `coges_owner` ou possède `rolbypassrls` ; vérification explicite au démarrage du
     worker, de beat et du relais ;
  2. `deploy/scripts/check_runtime_env.py` en CI et avant chaque déploiement : aucun
     `COGES_DATABASE_URL_OWNER`, ni aucun DSN `coges_owner`, dans Vercel ou le compose
     des workers ;
  3. risque résiduel décrit dans `deploy/README-infra.md`.
- **Sentry** (`core/observability.py`) : inactif sans DSN ; `send_default_pii=False`, et
  `before_send` retire `Authorization`, `Cookie`, `Idempotency-Key`, le corps et l'IP ;
  étiquettes `component`, `company_id`, `request_id`.
- **Restauration** : `deploy/scripts/restore-check.sh`, joué avec succès en local ; la
  procédure PITR de Neon est décrite, à rejouer en préproduction.
- **Contrat** : `backend/openapi.json` est versionné, et un test échoue si l'application
  en diverge.

## Conséquences
- Le frontend doit envoyer `Idempotency-Key` à la création d'un retour.
- La suite de tests coupe la limitation de débit (`tests/__init__.py`) et ne touche
  jamais le broker (fixture autouse) ; `test_rate_limit.py` rallume la limitation.
- La rotation de `COGES_JWT_SECRET` est documentée : elle invalide les jetons d'accès,
  pas les sessions de rafraîchissement.
