# Prompt 30 — Inscription : automatique par e-mail, activée par l'équipe sans e-mail

> **STATUT : PRÊT, À LANCER APRÈS** le lot « Page d'accueil publique » (landing page) et le lot « Pages légales ». Ordre décidé le 7 novembre 2026 : landing page → inscription → paiement en ligne (Bictorys).
>
> **Décision du propriétaire (8 novembre 2026)** : deux chemins dans le même formulaire, parce que beaucoup de commerçants n'ont pas d'e-mail et se connectent avec leur numéro.
> - **Avec un e-mail** : un lien de vérification part automatiquement (SMTP). Le clic active la boutique, et le commerçant se connecte aussitôt.
> - **Sans e-mail** : la demande attend. L'équipe contacte le commerçant sur WhatsApp ou par téléphone, puis active la boutique depuis l'administration.
>
> Le numéro de téléphone est obligatoire dans les deux cas. Le code de vérification WhatsApp automatique (WhatsApp Cloud API, environ 0,004 $ par code) viendra plus tard comme troisième chemin, sans refaire ce lot. Cette version remplace celle du 27 octobre (lien e-mail obligatoire).

Branche `feat/self-signup`, depuis `main` à jour.

```
Lot « Inscription : automatique par e-mail, activée par l'équipe sans e-mail » (branche
feat/self-signup, depuis main à jour). Règles habituelles : ADR aux prochains numéros
libres, tests d'abord (rouge puis vert), aucun service payant, ne jamais ouvrir ni commiter
.env, deploy/.env.preprod ni backend/.vercel/. Résumé en français à la fin, questions
ouvertes par AskUserQuestion. Lis d'abord les ADR 0009 (onboarding par CLI), 0078 (mot de
passe provisoire et freinage), 0079 (effets après COMMIT), 0083 (rétrocompatibilité des
migrations), 0089 (administration, companies.status, module d'envoi d'e-mails), 0091
(abonnements, essai qui naît avec l'entreprise), la mécanique d'acceptation des conditions
du lot Pages légales, la connexion par téléphone existante (create-company
--manager-phone) et la page d'accueil publique. Si le lot Pages légales ou la page
d'accueil n'est pas fusionné, ARRÊTE-TOI et dis-le moi.

Principe
- Une DEMANDE n'est pas une boutique. Rien n'est créé chez les commerçants avant
  l'activation, qu'elle vienne du clic sur le lien e-mail ou de l'équipe : pas
  d'entreprise fantôme, pas d'essai consommé, isolation entre entreprises inchangée.
- UNE seule fonction d'activation, appelée par les deux chemins, qui réutilise le service
  d'onboarding de la ligne de commande (entreprise, rôles système, gérant) et le
  déclencheur d'essai de l'ADR 0091 : AUCUNE seconde façon de fabriquer une entreprise.
  L'essai commence à l'activation.
- Interrupteur COGES_SIGNUP_ENABLED (faux par défaut, contrôlé par check_runtime_env).
  Faux : routes publiques en 404, aucun lien « Créer ma boutique », rien n'est écrit.
- SMTP : il n'est PAS exigé pour ouvrir l'inscription. Sans SMTP configuré, une demande
  avec e-mail suit simplement le chemin de l'équipe (aucun e-mail ne part, aucune erreur,
  un avertissement au démarrage et dans l'administration). Avec SMTP : chemin automatique.
- Le parcours garde un point d'extension pour un futur « code WhatsApp » : décris-le dans
  l'ADR, sans le coder.

E1. Backend
Migration au prochain numéro, rétrocompatible (ADR 0083 : ajouts seuls).
- Table signup_requests (plateforme, hors tenant et hors RLS comme les tables de
  plateforme ; GRANT colonne par colonne, TABLES_WITHOUT_RLS à jour, rôle d'exécution au
  moindre privilège justifié dans l'ADR) : id, shop_name, full_name, phone (E.164,
  normalisé, +221 par défaut, obligatoire), email (facultatif, normalisé), password_hash
  (argon2, même politique que users ; jamais stocké ni journalisé en clair),
  legal_version acceptée (version COURANTE côté serveur, jamais envoyée par le client),
  legal_accepted_at, path (email, team), status (pending, activated, rejected, abandoned),
  email_verified_at, reject_reason, team_note, created_at, decided_at, decided_by
  (équipe, ou « lien e-mail »), company_id (après activation), ip_hash (pas l'IP en clair).
- Table signup_email_tokens : request_id, token_hash (sha256 ; jeton jamais stocké ni
  journalisé en clair), expires_at (24 h), used_at. Un nouveau jeton invalide l'ancien.
- POST /api/v1/auth/signup-requests (publique), schéma extra="forbid" : shop_name,
  full_name, phone, password (politique existante), email facultatif, accept_legal
  (obligatoire, vrai), champ piège invisible.
  * Avec e-mail ET SMTP configuré : jeton créé, e-mail de vérification envoyé APRÈS le
    COMMIT (jamais si l'écriture échoue, ADR 0079). Réponse : « Vérifiez votre boîte
    e-mail : cliquez sur le lien pour ouvrir votre boutique. »
  * Sinon : demande pour l'équipe. Réponse : « Demande reçue. Nous vous contactons sur
    WhatsApp sous 24 h. »
  * Réponse IDENTIQUE, pour un même chemin, que le numéro ou l'e-mail soient nouveaux, déjà
    en attente ou déjà liés à un compte (aucune énumération). Si l'e-mail est déjà celui
    d'un compte, l'e-mail envoyé le dit et propose la connexion ; aucune seconde boutique.
- POST /api/v1/auth/signup-requests/verify (publique) : jeton à usage unique. Valide ->
  email_verified_at, puis ACTIVATION immédiate (même fonction que l'équipe), puis réponse
  avec le code de boutique, pour préremplir la connexion. Le commerçant se connecte
  ensuite avec son e-mail OU son numéro, et son mot de passe ; pas de connexion
  automatique. Même réponse pour tout jeton inconnu, expiré ou déjà utilisé.
- POST /api/v1/auth/signup-requests/resend (publique) : même réponse neutre, 1 envoi toutes
  les 60 s et 5 par jour et par adresse.
- Bascule vers l'équipe : une demande avec e-mail non vérifié depuis 48 h passe d'elle-même
  dans la file de l'équipe (path = team), sans rien perdre. Le commerçant peut aussi
  choisir, sur l'écran d'attente, « Je n'ai pas reçu l'e-mail : être contacté sur WhatsApp ».
- Limites (Redis, clés au format documenté au lot C, TTL partout) : demandes par adresse IP
  (heure et jour), par numéro, par e-mail normalisé ; plafond global par heure ET plafond
  quotidien d'activations AUTOMATIQUES, au-delà duquel les nouvelles demandes passent par
  l'équipe et une alerte part (jamais un refus silencieux). Adresses jetables : courte liste
  maintenue dans le dépôt -> chemin de l'équipe, pas de refus brutal. Redis indisponible :
  demande REFUSÉE (fermé par défaut).
- Connexion : un numéro ou un e-mail dont la seule trace est une demande non activée
  obtient, APRÈS vérification du mot de passe et sans session ni jeton, un message selon le
  cas : « Ouvrez le lien reçu par e-mail (renvoyer) » ou « Votre boutique est en cours
  d'activation, nous vous contactons sur WhatsApp ». Sinon, comportement inchangé.
- Routes de plateforme (/api/v1/platform/*, rôle plateforme autorisé à proposer dans
  l'ADR, en principe administrateur) : lister et filtrer les demandes (chemin, statut,
  ancienneté), voir une demande (avec « numéro ou e-mail déjà connu : boutique X »),
  ACTIVER, REFUSER (raison obligatoire en liste fermée + note), ajouter une note. Audit
  critique de chaque décision, y compris les activations par lien e-mail.
- Activation : crée l'entreprise par le service d'onboarding, avec le gérant, son
  téléphone, son e-mail s'il est vérifié et le password_hash de la demande (pas de mot de
  passe provisoire) ; code de boutique tiré du nom, suffixe s'il est pris, jamais un mot
  réservé ; acceptation des conditions enregistrée sur le gérant ; tout dans UNE
  transaction, idempotente (lien cliqué deux fois, ou lien cliqué pendant que l'équipe
  active : une seule boutique) ; e-mail de bienvenue après le COMMIT si l'adresse est
  vérifiée.
- Tâches de fond (beat, idempotentes, journal job_runs) : demande en attente de l'équipe
  depuis 7 jours -> « abandoned » ; demandes refusées ou abandonnées depuis 30 jours ->
  données personnelles effacées (nom, téléphone, e-mail, mot de passe haché), seules les
  statistiques restent. [DEMANDER] si les durées te paraissent à revoir.
- Alerte de l'équipe à chaque nouvelle demande de son ressort : compteur dans
  l'administration, et un e-mail à COGES_PLATFORM_ALERT_EMAIL si le SMTP est configuré.

E2. Frontend commerçant (frontend/, thème de la maquette v2)
- Bouton « Créer ma boutique » sur la page d'accueil publique et sur la page de connexion,
  seulement si l'inscription est ouverte (état lu sur une route publique de configuration,
  sans secret).
- /inscription : nom de la boutique, votre nom, numéro de téléphone (préfixe +221 affiché,
  format 77 000 00 00), e-mail avec la mention « facultatif : avec un e-mail, votre
  boutique s'ouvre tout de suite », mot de passe (PasswordField, règle visible avant
  l'erreur) et confirmation, case des conditions avec liens vers /cgu et /confidentialite,
  bouton « Créer ma boutique » inactif tant que la case n'est pas cochée. Aucune donnée
  dans l'URL.
- Écran « Vérifiez votre e-mail » : adresse masquée, « Renvoyer le lien » (délai affiché),
  « Je n'ai pas reçu l'e-mail : être contacté sur WhatsApp ».
- Écran « Demande reçue » (sans e-mail) : horaires de l'équipe, numéro WhatsApp du support
  (réglage public), « Que se passe-t-il ensuite ? » en trois étapes.
- /verification/[jeton] : succès -> « Votre boutique est prête », code de boutique affiché
  et prérempli sur la connexion ; jeton invalide -> message unique et renvoi possible. Le
  jeton ne reste pas dans l'historique (remplacé dans l'URL après lecture).
- Première connexion d'un nouveau gérant : tableau de bord vide qui propose les trois
  premiers gestes (ajouter un article, ajouter un client, faire une vente).
- Accessibilité : axe 0 violation, clavier seul, 360 px sans défilement horizontal, erreurs
  annoncées, focus sur le titre à chaque étape. Pages légères (3G).

E3. Administration (frontend-admin/)
- Entrée « Demandes » avec compteur de la file de l'équipe (aussi sur le tableau de bord).
- Liste : date, boutique, nom, téléphone, chemin (e-mail en attente / équipe), ancienneté,
  alerte « déjà connu ».
- Fiche : « Écrire sur WhatsApp » (lien wa.me prérempli et modifiable, gratuit, aucune
  API), « Appeler » (tel:), note, Activer, Refuser. Après activation : « Envoyer l'accès
  sur WhatsApp » (code de boutique et lien de connexion, JAMAIS le mot de passe).
- Statistiques : demandes reçues par chemin, activées automatiquement, activées par
  l'équipe, refusées, abandonnées, délai moyen d'activation. Avertissement visible si le
  SMTP n'est pas configuré.

E4. E-mails
- Deux modèles en français simple, texte et HTML léger : vérification (lien, validité
  24 h, « si ce n'est pas vous, ignorez ce message ») et bienvenue (code de boutique, lien
  de connexion, numéro WhatsApp du support). Aucune donnée inutile, jamais le mot de passe.
- Le runbook explique les enregistrements DNS d'envoi à créer chez Cloudflare (SPF, DKIM,
  DMARC) pour que les e-mails n'arrivent pas en indésirables.

E5. Tests (rouge d'abord)
- Backend : chemin e-mail complet (demande, jeton haché, e-mail après COMMIT, clic ->
  boutique, gérant, essai, conditions, audit -> connexion par e-mail et par numéro) ;
  chemin équipe complet ; SMTP absent = chemin équipe sans erreur ; réponses identiques
  (numéro ou e-mail connus ou non) ; jeton expiré, réutilisé ou inconnu = même réponse ;
  ancien jeton invalide après renvoi ; bascule vers l'équipe après 48 h et sur demande ;
  double activation (deux clics, clic + équipe en même temps) = une seule boutique ; échec
  au COMMIT = rien de créé et aucun e-mail ; limites (IP, numéro, e-mail, global, plafond
  d'activations automatiques -> chemin équipe + alerte) ; adresse jetable -> chemin
  équipe ; Redis coupé = refus ; interrupteur éteint = 404 partout ; effacement à 30 jours ;
  routes de plateforme refusées aux commerçants et aux rôles non autorisés ; isolation
  inter-tenant inchangée (suite complète du lot C verte).
- Frontend : formulaire (case non cochée = bouton inactif, numéro normalisé, e-mail
  facultatif, mot de passe affichable), écrans d'attente, de vérification et de
  l'administration.
- E2E : e-mail capturé -> lien -> « boutique prête » -> connexion -> tableau de bord vide ->
  première vente ; sans e-mail -> demande dans l'administration -> activation -> connexion
  par numéro ; lien invalide ; interrupteur éteint = pas de bouton ni de page.

Fin de lot
Suite backend complète, ruff, mypy, shellcheck, make front-check, e2e des écrans touchés,
tests de fuite inter-tenant, CI verte. ADR : table de demandes plutôt que boutique en
attente, fonction d'activation unique, droits PostgreSQL, politique de limites et de
plafond automatique, durées de conservation, comportement sans SMTP, point d'extension
pour le code WhatsApp. README-infra.md, coges.env.example, runbooks « traiter les demandes
d'inscription », « ouvrir ou fermer les inscriptions » et « configurer l'envoi d'e-mails »
en français simple, CLAUDE.md §8 et table des ADR.

Hors lot, volontairement : code de vérification WhatsApp automatique (WhatsApp Cloud API),
SMS, paiement en ligne de l'abonnement (Bictorys), demande d'accès à une boutique existante.
```

## Ce que le propriétaire fait lui-même

1. **Choisir un relais SMTP** (beaucoup ont une offre gratuite de quelques centaines d'e-mails par jour), créer une adresse d'envoi du type `noreply@coges.app`, ajouter chez Cloudflare les enregistrements SPF, DKIM et DMARC qu'il fournit, puis remplir `COGES_SMTP_*` dans `/etc/coges/coges.env`.
2. **Préparer le chemin sans e-mail** : numéro WhatsApp du support, horaires affichés, deux messages types (premier contact, envoi de l'accès), et qui traite les demandes (y compris le week-end).
3. **Tester sur la préproduction** les deux chemins avec ses propres coordonnées : avec un e-mail (lien, connexion immédiate) et sans e-mail (demande, activation dans l'administration, connexion par numéro). Vérifier que l'e-mail n'arrive pas dans les indésirables.
4. **Allumer** `COGES_SIGNUP_ENABLED=true` quand le test est concluant ; l'éteindre est immédiat en cas d'abus.
5. Vérifier avec le conseil juridique la durée de conservation des demandes refusées ou abandonnées (30 jours proposés) et la mention de l'essai gratuit dans les CGU.
