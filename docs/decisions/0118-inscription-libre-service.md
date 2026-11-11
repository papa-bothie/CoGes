# 0118 — Inscription libre-service : automatique par e-mail, activée par l'équipe sans e-mail

- **Date** : 2026-11-10
- **Phase** : lot 30 (`docs/prompts/30-inscription-libre-service.md`), livré en 3 PR empilées : B (backend), C (front commerçant), A (administration et clôture)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion) ; amende l'ADR 0009 (onboarding par CLI seulement)

## Contexte
Jusqu'ici, une boutique ne naissait que par `python -m app.cli create-company` (ADR 0009).
Le propriétaire ouvre l'inscription en libre-service avec deux chemins dans le même
formulaire. Beaucoup de commerçants n'ont pas d'e-mail et se connectent avec leur numéro :

- **avec un e-mail**, un lien de vérification part et le clic ouvre la boutique ;
- **sans e-mail**, l'équipe contacte le commerçant sur WhatsApp et active.

Le numéro est obligatoire dans les deux cas.

## Options envisagées
Accès aux demandes :
1. **Nouveau rôle `coges_signup` (retenue)** : NOLOGIN, NOBYPASSRLS, propriétaire de neuf
   fonctions `SECURITY DEFINER` appelées sous `coges_app`, qui n'a aucun droit direct sur
   les tables. Il faut un script sur Neon avant la migration.
2. Des droits colonne par colonne à `coges_app` : pas d'étape sur Neon, mais le rôle de
   tous les commerçants pourrait lire les données personnelles des prospects.

Emplacement :
1. **Nouveau module `signup/`, bande Plateforme (retenue)** : il porte les routes publiques
   et les routes de l'équipe. La création d'entreprise de la CLI devient
   `signup_service.onboard_company`, que la CLI et l'activation appellent toutes les deux.
   `platform/` reste intact et n'importe toujours aucun module métier (ADR 0089).
2. Tout dans `platform/` : il aurait fallu amender l'ADR 0089 et son test d'architecture.

Une boutique « en attente » (une entreprise créée inactive) a été écartée par le prompt : elle
fabriquerait des entreprises fantômes et consommerait des essais.

## Décision

### Une demande n'est pas une boutique (révision 0039)
- Deux tables sans `company_id`, hors RLS, déclarées dans `TABLES_WITHOUT_RLS` :
  - `signup_requests`, dont la colonne `activated_company_id` nomme l'entreprise née de
    l'activation, comme `target_company_id` au journal de l'administration. Un `company_id`
    l'aurait fait passer pour une table d'entreprise (T37) ;
  - `signup_email_tokens`.
- **Rien n'est créé chez les commerçants avant l'activation** : ni entreprise, ni rôle, ni
  essai.
- Contraintes :
  - une demande en attente est complète ;
  - « activée » ⇔ entreprise nommée ;
  - « refusée » ⇔ raison en liste fermée (`unreachable`, `duplicate`, `not_a_business`,
    `fraud`, `other`) ;
  - « décidée » ⇔ datée ;
  - effacement seulement après refus ou abandon ;
  - une demande en attente par numéro et par e-mail (index uniques partiels).
- **Jeton** : 32 octets aléatoires, stocké seulement en sha256, valable 24 h, à usage unique.
  Un nouveau jeton révoque l'ancien. Il est **tiré par le worker**, si bien qu'il ne
  transite ni par la file ni par l'API.
- **IP** : HMAC-SHA256 avec `COGES_SIGNUP_IP_HASH_KEY`, jamais un sha256 nu (4 milliards
  d'IPv4 se parcourent en quelques minutes) ; une IPv6 compte par son /64. Le même HMAC
  nomme le numéro et l'e-mail dans les clés Redis.
- **Mot de passe** : Argon2, même politique que les comptes (12 caractères). Le hachage
  devient celui du gérant à l'activation, sans mot de passe provisoire.
- **Version des textes légaux** : `LEGAL_VERSION` du serveur au moment de la demande,
  jamais envoyée par le client. Elle est recopiée sur le gérant à l'activation (ADR 0117).

### Droits PostgreSQL
- **`coges_signup`** (`deploy/sql/create_signup_role.sql`, préproduction puis production,
  **avant** 0039 ; la migration s'arrête avant toute modification et nomme le script si le
  rôle manque) :
  - SELECT, INSERT et UPDATE sur ses deux tables ;
  - INSERT sur `platform_audit_logs`, pour l'audit de l'activation, dans sa transaction ;
  - SELECT sur `users(email, phone, deleted_at)` par la politique `users_signup_read`, qui
    ne nomme que lui ;
  - aucun DELETE.
- **Les neuf fonctions** fixent `SET search_path = pg_catalog, public`. Leur `EXECUTE` est
  retiré à `PUBLIC` puis accordé à `coges_app` seul, **avant** le transfert de propriété
  (après, le REVOKE serait sans effet). Ce verrou est prouvé par
  `test_t36_signup_functions_are_locked`.
  - `signup_known` ne rend qu'un **booléen** (`test_t36_signup_known_answers_true_or_false_only`).
  - `signup_reserve` verrouille la demande `FOR UPDATE` jusqu'au COMMIT.
- **`coges_app_platform`** :
  - lit tout sauf `password_hash` et `ip_hash` ;
  - met à jour ses décisions, la bascule et l'effacement ;
  - n'a pas UPDATE sur `activated_company_id`, si bien qu'il ne peut pas marquer une
    demande « activée » sans fabriquer l'entreprise.
- **pg_dump ne sauvegarde pas les rôles** : `coges_signup` rejoint la liste de
  `restore_backup.sh`, de `backup_chain_check.sh` et du runbook de restauration.

### Une seule activation
- `signup_service.activate_request`, appelée par le lien (`verify`) comme par l'équipe, se
  fait en **une transaction** sous `coges_app`, dans le contexte de l'entreprise à naître :
  1. `signup_reserve` (verrou) ;
  2. `onboard_company`, avec le code de boutique tiré du nom, un suffixe sous point de
     sauvegarde s'il est pris, et jamais un mot réservé ;
  3. le gérant, avec son téléphone, son e-mail **s'il est vérifié** et le hachage de la
     demande ;
  4. l'acceptation des textes légaux ;
  5. `signup_mark_activated` et l'audit critique dans `platform_audit_logs` (lien e-mail
     compris).
- L'essai de 30 jours naît avec l'entreprise (trigger de l'ADR 0091) : **il commence à
  l'activation**.
- **Idempotente** : un second appel (deux clics, ou un clic pendant que l'équipe active)
  attend le verrou puis ne trouve plus de demande en attente : 409 `signup_not_pending`, ou
  lien invalide. Une seule boutique.
- Le mail de bienvenue part après le COMMIT, seulement si l'adresse est vérifiée.
- **Un numéro déjà inscrit n'ouvre jamais une boutique tout seul** : au clic, l'adresse est
  vérifiée mais la demande passe à l'équipe, qui voit « déjà connu : boutique X ». Une seule
  fonction lit les numéros, `app/core/phone.py` (`normalise_phone`, puis `to_e164` et
  `stored_form` construits dessus), testée sur « 77 000 00 00 », « +221770000000 »,
  « 00221 77… ».

### Routes publiques (404 tant que `COGES_SIGNUP_ENABLED` est faux)
- **`POST /auth/signup-requests`** : schéma `extra="forbid"`, case `accept_legal` à vrai,
  champ piège `website`. Le chemin de la demande se décide ainsi :
  - e-mail et SMTP présents : « Vérifiez votre boîte e-mail… » ;
  - sinon : « Demande reçue. Nous vous contactons sur WhatsApp sous 24 h. ».

  La réponse est **identique pour un même chemin**, que le numéro ou l'e-mail soient
  nouveaux, déjà en attente (la demande existante est rendue, sans doublon) ou déjà liés à
  un compte. Un e-mail déjà inscrit ne crée aucune demande : un e-mail lui dit qu'il a un
  compte et propose la connexion, sans nommer de boutique.
- **`POST /verify`** : jeton consommé, puis activation. Réponse `ready` avec le code de
  boutique (pas de connexion automatique), ou `team`. Tout jeton inconnu, expiré ou déjà
  utilisé reçoit la même réponse (400 `signup_link_invalid`).
- **`POST /resend` et `POST /contact-team`** : réponse neutre ; un envoi par minute, cinq
  par jour et par adresse.
- **`GET /auth/signup-config`** répond toujours : ouverte ou non, lien immédiat ou non,
  WhatsApp du support, délai de renvoi. Aucun secret.
- **Connexion** : quand aucun compte ne correspond, la demande en attente de cet
  identifiant prend la place du leurre, ce qui garde **une seule** vérification Argon2.
  Avec le bon mot de passe : 403 `signup_email_pending` ou `signup_team_pending`, sans
  session ni jeton. Sinon : le comportement habituel.

### Limites (Redis, fermées si Redis manque : 503 `signup_unavailable`)
| Limite | Valeur | Au-delà |
|---|---|---|
| Demandes par IP | 5 par heure, 20 par jour | 429 visible, avec `Retry-After` |
| Demandes par numéro | 3 par jour | 429 visible |
| Demandes par e-mail | 3 par jour | 429 visible |
| Plafond global | 30 demandes par heure | 429 visible |
| Demandes automatiques (par lien) | 50 par jour | **chemin de l'équipe** et alerte, jamais un refus silencieux |

Toutes les valeurs sont des réglages `COGES_SIGNUP_*`. Une adresse jetable (liste courte
du dépôt, `disposable_domains.txt`) passe par l'équipe, sans refus. Les clés sont
déclarées dans `test_redis_keys_isolation.py`, toutes avec TTL et sans valeur personnelle.

### Sans SMTP
L'inscription s'ouvre quand même : toute demande suit le chemin de l'équipe, sans erreur,
avec un avertissement au démarrage de l'API. L'administration l'affiche (`smtp_configured`).

### Durées (réglages, à valider avec le conseil juridique)
| Événement | Délai | Variable |
|---|---|---|
| Expiration du lien | 24 h | `COGES_SIGNUP_TOKEN_TTL_HOURS` |
| Bascule vers l'équipe (e-mail jamais vérifié) | 48 h | `…_TEAM_AFTER_HOURS` |
| Demande « abandonnée » sans suite de l'équipe | 7 jours | `…_ABANDON_AFTER_DAYS` |
| Effacement des données personnelles après refus ou abandon | 30 jours | `…_PURGE_AFTER_DAYS` |

L'effacement porte sur le nom, le téléphone, l'e-mail, le mot de passe haché, la note et
l'empreinte IP. Seuls le statut, le chemin et les dates restent, pour les statistiques. La
tâche `signup.maintenance` (beat, toutes les heures, `job_runs`) est idempotente.

### Équipe (`/api/v1/platform/signup-requests`)
- Liste filtrée (statut, chemin, ancienneté) avec le compteur de la file de l'équipe, fiche
  avec « déjà connu : boutique X », statistiques : administrateur et support.
- Activer, refuser (raison en liste fermée et note), noter : administrateur seul, avec un
  audit critique de chaque décision. Le texte d'une note n'entre pas dans le journal.
- Une alerte (`COGES_PLATFORM_ALERT_EMAIL`, si SMTP) part pour chaque demande du ressort de
  l'équipe, sans nom ni numéro dans l'e-mail.

### Point d'extension : code WhatsApp
Un futur « code WhatsApp » (WhatsApp Cloud API) sera un troisième `path` (`whatsapp`). Il
aura sa table de codes hachés (comme `signup_email_tokens`) et une fonction de
consommation `coges_signup` qui pose une date de vérification du numéro, et aboutira au
**même** `activate_request`. Rien de ce lot n'est à refaire ; non codé ici.

## Conséquences
- **Prérequis** : `create_signup_role.sql` sur Neon (préproduction, puis production) avant
  le déploiement de la révision 0039 ; `COGES_SIGNUP_IP_HASH_KEY` avant d'allumer
  l'inscription. Le compose pose `COGES_MERCHANT_URL` (liens des e-mails) sur l'API et le
  worker.
- **Tests** :
  - `test_signup.py` : 26 tests pour les deux chemins de bout en bout, la neutralité, les
    jetons, la concurrence, le COMMIT refusé, les limites, Redis coupé, l'interrupteur,
    les tâches de fond et les droits ;
  - T36 : rôle et fonctions verrouillés ;
  - registres de la CI complétés (écritures, lectures, beat, clés Redis, liste blanche
    plateforme, tables sans RLS) ;
  - `test_phone.py` ;
  - `check_runtime_env.py` (clé exigée quand l'inscription est ouverte).
- Le front commerçant (PR C) et l'administration (PR A) complètent cet ADR.
