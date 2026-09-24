# 0027 — Une table pour les clés d'idempotence, et l'en-tête sur toute écriture d'argent

- **Date** : 2026-09-24
- **Phase** : 07
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`) — point ouvert **P4**

## Contexte

La décision 16 de l'architecture exige des « clés d'idempotence sur les écritures
financières », et le Diagramme 5 fait de la vérification de clé la **première** étape d'un
paiement. Le Modèle de données ne porte ni table ni colonne pour cela : c'est le point ouvert
P4, laissé à cette phase.

Le problème est réel et quotidien : un caissier au comptoir, sur une connexion mobile, clique
deux fois sur « encaisser ». Sans clé, la seconde requête écrit un second paiement — et si le
premier a soldé une dette, le second se heurte à un solde nul et sort en erreur, laissant le
caissier persuadé que rien n'a été encaissé.

## Options envisagées

1. **Table `idempotency_keys` tenant-scoped (retenue)** : `company_id`, `key`, `endpoint`,
   `request_hash`, `response_status`, `response_body`, `created_at`, `expires_at`, sous RLS,
   avec `UNIQUE (company_id, key)`.
2. **Colonne `idempotency_key` sur `payments`** : plus léger, mais incapable de **rejouer la
   réponse initiale** — le client reçoit un conflit, pas son résultat — et ne couvrant ni la
   confirmation de vente ni le remboursement d'un retour, qui sont aussi des écritures
   financières.
3. **Redis** : rapide, mais l'idempotence d'une écriture d'argent dépendrait alors d'un service
   que l'architecture déclare non critique. Redis indisponible ⇒ doublon possible. C'est
   exactement le raisonnement de la décision 04, qui garde l'audit et l'outbox hors de Redis.

## Décision

La révision **0009** crée `idempotency_keys`. `app/core/idempotency.py` la manipule, et
l'en-tête `Idempotency-Key` devient **obligatoire sur toutes les écritures financières** :
`POST /payments`, `POST /debts`, `POST /expenses`, et — en rétro-application — `POST
/sales/{id}/confirm` et `POST /sale-returns/{id}/refunds`.

## Conséquences

- **La clé est réservée dans la transaction du cas d'usage**, donc validée par le même COMMIT
  que le paiement. Un rollback annule les deux : jamais de clé qui bloquerait une écriture qui
  n'a pas eu lieu. Un test le vérifie — une écriture refusée en 404 rend sa clé.
- **La réservation passe par un `SAVEPOINT`** (`session.begin_nested()`). Sans lui, la violation
  d'unicité tuerait la transaction et il n'y aurait plus personne pour lire la réponse à
  rejouer. C'est la leçon de l'ADR 0010 appliquée à un conflit qu'on sait à l'avance possible.
- **La concurrence est réglée par l'index unique, et par rien d'autre.** La seconde requête
  bloque sur `idempotency_keys_key_uq` jusqu'au COMMIT de la première, puis lit la réponse déjà
  enregistrée. PostgreSQL ne lève la violation que si la transaction concurrente a **commité** —
  si elle a échoué, l'insertion en attente aboutit. Aucun verrou applicatif n'est nécessaire.
- **Le hachage porte sur le corps validé, pas sur les octets reçus** : deux requêtes qui ne
  diffèrent que par l'ordre des clés ou l'indentation sont la même demande. Même clé sur un
  corps différent ⇒ **422** `idempotency_key_reused` : rendre la première réponse à une seconde
  demande serait pire qu'un doublon, ce serait un mensonge.
- **La réponse fraîche et le rejeu sortent du même `JSONResponse`**, sur le même dictionnaire.
  Sans cela, « la même réponse » resterait une intention et un test ne pourrait comparer que des
  formes voisines. Un en-tête `Idempotent-Replay: true` distingue les deux.
- **L'ordre des dépendances FastAPI devient significatif** : `require_permission` est déclarée
  **avant** `idempotency_key` dans chaque signature. Sans jeton, la réponse doit être 401, jamais
  422 sur un en-tête manquant — un 422 apprendrait à un inconnu que l'endpoint existe et ce qu'il
  attend. Un test le vérifie sur la route de paiement.
- **La confirmation d'une vente garde son 409 `sale_not_draft`** (ADR 0022). Les deux garde-fous
  ne se confondent pas : la clé protège du réseau, le refus protège du métier. Une seconde
  confirmation *avec une clé neuve* reste un conflit réel — deux caissiers présentant deux
  règlements différents.
- **Le client de test pose lui-même une clé neuve** par requête (`_IdempotentClient` de
  `conftest.py`), comme le ferait une vraie bibliothèque cliente. Une clé explicite n'est jamais
  écrasée : c'est ainsi qu'un test rejoue une requête à l'identique.
- **`expires_at` (24 h) est posé mais rien n'est purgé en V1.** La purge viendra d'un job de la
  phase 08. Une clé gardée trop longtemps n'a jamais rendu une mauvaise réponse ; c'est
  l'inverse qui serait dangereux.
