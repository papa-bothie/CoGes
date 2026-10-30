# 0105 — Double authentification obligatoire de l'administration

- **Date** : 2026-10-30
- **Phase** : lot « Double authentification de l'administration » (branche `feat/admin-mfa`)
- **Statut** : acceptée (amende 0089, 0094 et 0104)
- **Décideur** : utilisateur (via AskUserQuestion, puis ajustements au feu vert)

## Contexte
Pour le lancement, l'administration (`frontend-admin/`, `/api/v1/platform/*`) ne sera protégée
ni par Cloudflare Access (ADR 0104, objets Cloudflare pas encore posés) ni par une liste
d'adresses (l'adresse Sonatel change chaque jour). La barrière devient une **double
authentification obligatoire** pour tout compte de la plateforme. Le code Cloudflare reste en
place, inutilisé (`COGES_ADMIN_GATE=cloudflare`). Le 29/10, `cloudflared` n'avait pas démarré :
`/opt/coges/deploy.sh` n'était installé qu'une fois par `bootstrap.sh` et ne suivait pas les
versions.

## Options envisagées
- **TOTP** : implémentation maison avec la bibliothèque standard (**retenue** : une quarantaine
  de lignes, vecteurs de la RFC 6238, rien qui puisse manquer dans l'image) ; `pyotp 2.9.0`
  (une dépendance de plus, l'anti-rejeu restait à notre charge).
- **QR code** : `segno==1.6.6` côté serveur, SVG rendu par l'API (**retenu** : Python pur, le
  front admin reste sans dépendance nouvelle) ; paquet `qrcode` dans le front.
- **Sessions** : 12 h au plus, 1 h d'inactivité (**retenu**) ; 8 h / 30 min ; 24 h / 2 h.
- **deploy.sh** : refus avec la commande d'installation (**retenu** : le script reste à root, la
  clé SSH bridée ne peut rien réécrire) ; mise à jour automatique (la clé de GitHub Actions
  aurait pu changer ce qui s'exécute sur le VPS).
- **Codes de secours** : Argon2 (dix vérifications lentes) ; **HMAC-SHA-256 sous une clé serveur
  (retenu au feu vert)**, une seule recherche en base.
- **Appareil connu** : navigateur + préfixe d'adresse (proposé) ; **jeton aléatoire en cookie +
  navigateur (retenu au feu vert)**, sans adresse IP (elle change chaque jour).

## Décision
**Connexion en deux temps.** `POST /platform/auth/login` vérifie le mot de passe et ne rend
qu'un **jeton intermédiaire** (`{step, challenge_token, expires_in}`) : 5 minutes, usage unique
(`consumed_at`), empreinte SHA-256 seule en base (`platform_mfa_challenges`), qui n'ouvre que
l'étape annoncée. `step = enroll` si le compte n'a pas de double authentification (premier
passage après ce lot, invitation acceptée, réinitialisation), sinon `verify`. Un nouveau mot de
passe juste rend caducs les jetons ouverts du compte. Le jeton de plateforme et la session
(refresh) ne naissent qu'après le code.

**Enrôlement.** `POST /auth/mfa/enrollment` propose un secret (base32, 160 bits) : QR code SVG
autonome, lien `otpauth://` (SHA-1, 30 s, 6 chiffres, émetteur « CoGes Administration ») et clé
texte. Le secret est gardé **chiffré** sur le jeton intermédiaire et ne devient actif qu'avec un
premier code juste (`/auth/mfa/enrollment/confirm`) : il passe alors sur le compte, dix codes de
secours sont tirés et montrés **une fois**, la session s'ouvre. Un compte actif ne peut pas
remplacer son secret par ce chemin. L'acceptation d'une invitation ne rend plus de session :
elle mène à l'enrôlement.

**Code.** `app/core/totp.py` : HMAC-SHA-1, ±1 pas, comparaison à temps constant, et
**anti-rejeu** : un code n'est accepté que pour un pas strictement plus récent que
`platform_users.mfa_last_step`, compte verrouillé (`FOR UPDATE`) pendant la vérification.

**Secrets au repos.** `app/core/mfa.py` : AES-256-GCM, nonce aléatoire, octet de format,
données associées = identifiant du compte (un secret recopié sur une autre ligne ne se déchiffre
pas). Codes de secours : HMAC-SHA-256 (compte + code normalisé). Les deux clés sont dérivées par
HKDF de **`COGES_MFA_ENCRYPTION_KEY`** (32 octets en base64url) : l'API refuse de démarrer sans
elle hors `local`/`ci` (`Settings.require_mfa_encryption_key`, appelé par `app/main.py`) ; en
`local`/`ci`, une clé de développement publique. Le worker n'en a pas besoin. Aucun secret, code
ni jeton n'entre au journal (`diff` en liste blanche : `mfa`, `method`, `new_device`, `device`,
`recovery_codes_left`).

**Codes de secours.** Dix codes `ABCD-EFGH` (alphabet sans 0/O/1/I/L, ~40 bits), usage unique
(`used_at`), régénération (`/auth/mfa/recovery-codes`, code de l'application exigé) = anciens
révoqués (`revoked_at`). Utilisé : journal (`method: recovery_code`, codes restants), e-mail au
compte et à `COGES_PLATFORM_ALERT_EMAIL`, entrée « À traiter ».

**Freinage.** Mot de passe et code partagent **le même compteur par compte** (ADR 0078, 0088) :
le mot de passe juste rend l'essai réservé sans remettre le compteur à zéro ; seul un code juste
le fait. Même 429 et même phrase quel que soit le facteur. Les routes `mfa` comptent aussi au
plafond de connexion par IP. Accepté au feu vert : l'écran du code dit, par nature, que le mot
de passe était juste.

**Sessions.** `platform_auth_sessions.authenticated_at` (début, gardé à chaque rotation) :
refus au rafraîchissement après **12 h**, ou après **1 h** sans rafraîchissement (contrôlé sur
`issued_at` du jeton présenté, donc à 15 min près). Cookie de 12 h. Le jeton d'accès porte
`amr: ["pwd","otp"]` et `iat` : `deps.py` refuse un jeton sans `otp`, et tout jeton émis avant
`mfa_enabled_at` du compte (réinitialisation ⇒ déconnexion immédiate, sans attendre 15 min).
Les sessions ouvertes avant ce lot sont révoquées par la révision.

**Appareils.** Cookie `coges_platform_device` (aléatoire, httpOnly, Secure, SameSite=Strict, un
an, chemin `/api/v1/platform/auth`), empreinte + navigateur (« Firefox · Linux », sans version)
dans `platform_known_devices`. Inconnu, ou connu sous un autre navigateur : journal
(`new_device`), e-mail si SMTP, et entrée dans `GET /platform/attention` (`security_events`,
7 jours, 20 au plus). L'enrôlement enregistre l'appareil sans alerte « nouvel appareil » mais
avec l'alerte « double authentification activée ».

**Téléphone perdu.** `POST /platform/team/{id}/mfa-reset` (administrateur, raison obligatoire,
jamais sur soi : 409 `cannot_reset_own_mfa`) : secret retiré, codes révoqués, jetons
intermédiaires consommés, sessions révoquées (et par le trigger
`platform_users_revoke_sessions_on_mfa`), audit, e-mail. Dernier recours :
`python -m app.cli reset-platform-mfa --email …`. `create-platform-user --mfa-secret` (secret
connu d'avance, pour les e2e) est refusé hors `local` et `ci`.

**Porte `mfa`.** `COGES_ADMIN_GATE=mfa` : `admin-mfa.caddy` sert `admin.<domaine>` sur 443 sans
filtre d'adresse, avec les en-têtes, le plafond de corps (1 Mo) et la fermeture des routes
commerçantes du mode `ip`. `check_runtime_env.py` l'accepte avec la constante
`PLATFORM_MFA_REQUIRED = True` (la même que `app.core.mfa`, test de concordance ; un bundle
d'avant ce lot ne connaît pas la porte et la refuse) et exige `COGES_MFA_ENCRYPTION_KEY` bien
formée pour **toute** pile (l'API ne démarrerait pas). `ip` et `cloudflare` restent possibles ;
`coges.env.example` passe à `mfa`.

**Scripts du VPS.** `deploy.sh` et `check.sh` voyagent dans le bundle (`/bundle/scripts/`).
`deploy.sh` porte `SCRIPTS_VERSION` (2) : si la version à déployer en porte un plus grand, rien
n'est changé (code 3 de `start`) et le journal donne les deux `sudo install` exacts puis la
commande à relancer. Une version aux scripts plus anciens (retour arrière) passe.

## Conséquences
- Révision **0033** : colonnes `mfa_*` et contrainte de cohérence sur `platform_users`,
  `authenticated_at`, trois tables hors RLS (comptes de la plateforme) réservées à
  `coges_app_platform` (UPDATE sur les seules colonnes de cycle de vie), lues par
  `coges_backup` ; registres T37 et GRANT mis à jour.
- Dépendances : `segno==1.6.6` et `cryptography` déclarés en production, importés au chargement
  du module (vus par `check_image_imports.sh`) ; `requirements.txt` régénéré.
- Tests : `test_totp.py` (vecteurs RFC), `test_mfa_secrets.py`, `test_platform_mfa.py`
  (enrôlement, jeton intermédiaire, rejeu, secours, freinage, sessions, appareil,
  réinitialisation, CLI, journal, COMMIT refusé), contrôle des portes et du bundle ; harnais :
  comptes créés avec `--mfa-secret`, appareil déclaré connu. Front : `mfa-steps`, Vitest et e2e
  (`e2e/mfa.ts` calcule les codes et tient un registre des pas servis).
- Perdre `COGES_MFA_ENCRYPTION_KEY` oblige toute l'équipe à réenrôler ; une sauvegarde restaurée
  exige la même clé (`docs/runbooks/administration.md`).
- Passkeys (WebAuthn) : non, à proposer en lot suivant.
- Revenir à une version d'avant ce lot exige `COGES_ADMIN_GATE=ip` (ou `cloudflare`).
