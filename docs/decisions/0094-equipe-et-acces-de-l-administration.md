# 0094 — L'équipe et ses accès dans l'administration (lot admin 6)

- **Date** : 2026-10-24
- **Phase** : lot admin 6 (`docs/prompts/27-admin-interface-et-acces.md`, intitulé « lot admin
  4 » dans le prompt ; ce numéro est déjà pris par l'accès support, ADR 0092)
- **Statut** : acceptée — partie A (API) ; la partie B (interface) complétera cet ADR
- **Décideur** : propriétaire (décisions du prompt et AskUserQuestion)

## Contexte

L'équipe CoGes se gérait uniquement par `make create-platform-user`, et son journal
(`platform_audit_logs`) était écrit sans jamais être lisible. Le prompt 27 ajoute les
gestes du quotidien — inviter un collègue, changer son profil, le suspendre, retrouver qui
a fait quoi — et une interface au thème CoGes. **Aucune règle de sécurité ne s'assouplit** :
`coges_app_platform` n'obtient aucun droit sur une table de commerçant, les jetons restent à
audiences distinctes, chaque écriture est auditée et le compte qui agit est relu en base à
chaque requête.

Décisions du propriétaire, à ne pas rouvrir : l'interface gère **l'équipe** (profils
`administrator` et `support`) ; les comptes des commerçants sont **listés en lecture seule** ;
invitations **par e-mail, pour l'équipe seulement** ; **deux profils fixes** expliqués en
clair ; thème CoGes avec un repère « Administration » toujours visible.

## Options retenues (AskUserQuestion)

- **Deux PR successives** : A, l'API (cet ADR) ; B, après la fusion de A, le thème, la coque,
  les écrans, les parcours e2e chronométrés et Lighthouse.
- **Le jeton d'invitation naît dans le worker.** L'API crée l'invitation **sans jeton** et
  n'enfile que `invitation_id` et `issue` ; le worker tire le jeton, écrit son empreinte
  SHA-256, puis envoie l'e-mail. Le jeton en clair n'existe que dans la mémoire du worker et
  dans la boîte du destinataire : jamais dans Redis, jamais dans la base, jamais au journal.
  **Sans SMTP**, l'API tire le jeton dans sa transaction et rend le lien **une fois**
  (`invitation_url`, `email_sent: false`) ; une relance de la même clé ne le remontre pas.
  Option écartée : passer le jeton en argument de la tâche (en clair dans Redis et sa
  persistance jusqu'à l'envoi).
- **Repère « Administration » en encre ardoise** (`#1e2320`, l'encre de la maquette) : un
  bandeau sombre qu'aucune rubrique ni aucun statut n'utilise (partie B).
- **Mode sombre selon le système**, sans sélecteur (partie B).

## Décision — partie A

**Base (révision 0030).** `platform_invitations`, hors RLS et sans `company_id` : adresse en
minuscules, nom, profil, `token_hash` (vide tant que le lien n'est pas tiré), `issue`
(numéro d'émission), `idempotency_key` (unique), qui invite, création, échéance (72 h),
acceptation (et le compte créé), révocation. Une seule invitation en attente par adresse
(index unique partiel) ; une invitation échue est révoquée par le service pour faire place
à la nouvelle. `coges_app_platform` : SELECT et INSERT, UPDATE sur les seules colonnes du
cycle de vie. Index du journal par acteur, par cible et par date. Aucune table de commerçant
touchée.

**Invitation.** `POST /platform/team/invitations` (`Idempotency-Key` obligatoire : un double
clic n'envoie pas deux e-mails) ; 409 `platform_user_exists` ou `invitation_pending`.
`POST …/{id}/resend` : `issue` avance, l'empreinte est effacée, 72 h de plus ; un envoi plus
ancien encore en file ne trouve plus son numéro et ne fait rien. `DELETE …/{id}` révoque.
L'e-mail part **après le COMMIT** (`on_commit`), jamais si l'écriture échoue.
`POST /platform/auth/accept-invitation` (publique, freinée par adresse IP comme la connexion) :
mot de passe de 12 caractères au moins vérifié **avant** le jeton (un mot de passe trop court
ne consomme rien), compte créé, jeton consommé, session ouverte (cookie et jeton d'accès
comme une connexion). Jeton inconnu, échu, révoqué, remplacé ou déjà utilisé : **même**
réponse, 400 `invitation_invalid`. Le lien mène à `COGES_ADMIN_URL/invitation/<jeton>`.

**Profils et suspension.** `PATCH /platform/team/{id}` : `role`, `is_active`, `reason`
(obligatoire pour suspendre). Garde-fous :
- jamais son propre compte (409 `cannot_modify_self`) ;
- toujours un administrateur actif (409 `last_administrator`, sur le patron du dernier
  gérant, ADR 0054) : les administrateurs actifs sont verrouillés **avant** le compte visé,
  donc deux administrateurs qui se retirent l'un l'autre en même temps se sérialisent et le
  second est refusé ;
- une suspension révoque les sessions (trigger de 0026, prouvé) et coupe le compte dès la
  requête suivante ; un changement de profil compte aussi dès la requête suivante (profil
  relu en base, pas lu dans le jeton) ;
- audit critique de chaque changement, avant et après lisibles.

**Lectures** (les deux profils sauf le journal) :
- `GET /team` (comptes et invitations en attente ; `is_me` pour l'écran) et
  `GET /team/summary` (route à part plutôt qu'une extension de `/stats/overview`, qui parle
  des commerçants) ;
- `GET /users` : comptes commerçants **en lecture seule**, pages de 20, filtres `q` (nom,
  e-mail ou entreprise, jokers échappés), `role`, `status` (`active`, `deactivated`,
  `company_suspended` — l'entreprise suspendue l'emporte), `company_id`, tri par nom ou par
  dernière connexion. Seules les colonnes accordées par 0026 : ni téléphone ni hachage, prouvé
  en exécutant chaque branche sous le vrai rôle ;
- `GET /audit` (**administrateur seul**) : pages de 50, filtres acteur, action, entreprise,
  cible, période (jours compris, heure de Dakar), avec le nom de l'acteur, de la cible et de
  l'entreprise pour écrire des phrases. Le `diff` passe par une **liste blanche** récursive de
  champs (`role`, `is_active`, `status`, `reason`, montants, dates…) : un hachage, un jeton
  ou un mot de passe glissé par erreur n'en sort jamais (test avec une valeur piège) ;
- `GET /roles` : les deux profils et leurs capacités, **déduites des dépendances** de chaque
  route (`require_platform_role` porte ses profils, `get_platform_admin_session` seule ouvre
  aux deux). Seule la phrase de chaque route est écrite à la main
  (`platform/capabilities.py`) ; le test-registre échoue si une route `/platform` à profil
  n'a pas de phrase, ou si une phrase n'a plus de route ;
- `GET /attention` : essais qui finissent sous 7 jours, entreprises suspendues (20 et leur
  total), invitations qui échoient sous 24 h ;
- `GET /companies?status=` pour les puces de statut.

**Exploitation.** `COGES_ADMIN_URL` (API et worker) posée par le compose à
`https://admin.<COGES_DOMAIN>` ; l'API reçoit `COGES_SMTP_HOST` pour savoir si un e-mail
peut partir. `make create-platform-user` reste la voie du premier administrateur et du
secours.

## Conséquences

- Tests : `test_platform_team.py` (cycle de l'invitation, jeton jamais en clair, usage
  unique, envoi tardif d'une émission périmée, garde-fous, course entre deux
  administrateurs, COMMIT refusé sur chaque écriture), `test_platform_directory.py`
  (comptes commerçants, journal sans secret, profils, registre, « À traiter »), liste
  blanche des droits du rôle et T37 étendus, routes classées dans les registres de la CI.
- Le profil support voit l'équipe mais n'y écrit rien, et ne lit pas le journal.
- Hors lot : modifier un compte de commerçant, permissions cochables, suppression
  définitive, invitations de commerçants, double authentification.
