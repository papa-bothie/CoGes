# Prompt 30 — Inscription en libre-service : créer sa boutique et commencer l'essai

Branche `feat/self-signup`, depuis `main` à jour, **après** le lot « Pages légales » (docs du projet : `prompt-pages-legales.md`, acceptation des conditions tracée) et après le lot abonnements (prompt 24, essai Premium). Aujourd'hui une boutique naît uniquement par la ligne de commande (ADR 0009) : un commerçant qui arrive sur la page de CoGes ne peut que se connecter.

Décisions du propriétaire (AskUserQuestion, à ne pas rouvrir) :
- **Créer sa boutique, essai gratuit.** Le commerçant s'inscrit seul (nom de la boutique, son nom, e-mail, mot de passe) ; CoGes crée l'entreprise, le gérant et l'essai. Les vendeurs et comptables continuent d'être créés par le gérant. Pas de demande d'accès à une boutique existante dans ce lot.
- **Lien de vérification par e-mail + limites d'inscription.** Le compte ne fonctionne qu'après le clic sur le lien.

Pourquoi ce lot demande de la prudence : c'est la seule route **publique qui crée des données**. Elle ouvre la porte aux faux comptes, au spam et aux essais gratuits à répétition, et elle ne doit pas affaiblir l'isolation entre entreprises. Elle reste donc **éteinte par défaut** et ne s'allume que par un réglage que le propriétaire active lui-même.

```
Lot « Inscription libre-service » (branche feat/self-signup, depuis main à jour, après les
lots Pages légales et abonnements). Règles habituelles : ADR aux prochains numéros libres,
tests d'abord (rouge puis vert), aucun service payant, ne jamais ouvrir ni commiter .env,
deploy/.env.preprod ni backend/.vercel/. Résumé en français à la fin, questions ouvertes par
AskUserQuestion. Lis d'abord les ADR 0009 (onboarding par CLI), 0078 (mot de passe
provisoire et freinage), 0083 (rétrocompatibilité des migrations), 0089, 0091 (essai), la
mécanique d'acceptation des conditions du lot Pages légales et le module d'envoi d'e-mails
du lot admin 1. Si le lot Pages légales n'est pas fusionné, ARRÊTE-TOI et dis-le moi.

S0. Interrupteur et principe
- Variable COGES_SIGNUP_ENABLED (faux par défaut, vérifiée par check_runtime_env comme les
  autres réglages de production). Faux : les routes d'inscription répondent 404, le lien
  « Créer ma boutique » n'apparaît pas, et rien n'est écrit. Vrai sans SMTP configuré :
  refus de démarrer en production (une inscription sans e-mail de vérification ne doit
  jamais exister).
- Réutilise le service d'onboarding de la ligne de commande (celui qui crée entreprise,
  rôles système, gérant) et le déclencheur d'essai du lot 24 : AUCUNE seconde façon de
  fabriquer une entreprise. Durée et offre de l'essai : ce que le lot 24 décide, pas une
  valeur nouvelle.

S1. Backend
Migration au prochain numéro, rétrocompatible (ADR 0083 : ajouts seuls).
- users.email_verified_at (timestamptz, nullable). Remplis les comptes existants (créés par
  les gérants ou la CLI) avec leur date de création : ils sont considérés vérifiés. À la
  création par un gérant ou la CLI : renseigné d'emblée. Seule l'inscription libre-service
  laisse NULL.
- Table email_verifications (hors tenant, hors RLS comme les tables de plateforme ; GRANT
  colonne par colonne et TABLES_WITHOUT_RLS à jour) : id, user_id, token_hash (sha256 ; le
  jeton n'est JAMAIS stocké ni journalisé en clair), expires_at (24 h), used_at, created_at.
  Un seul jeton valable par compte : en émettre un nouveau invalide l'ancien.
- POST /api/v1/auth/signup (publique), schéma extra="forbid" : shop_name, full_name, email,
  password (politique existante), accept_legal (obligatoire, vrai ; enregistre la version
  COURANTE des conditions côté serveur, comme le lot Pages légales, jamais une version
  envoyée par le client), champ piège invisible. Dans UNE transaction : entreprise (code
  de boutique `slug` généré depuis le nom, suffixe si pris, jamais un mot réservé), rôles,
  gérant non vérifié, essai, audit critique, jeton ; l'e-mail part APRÈS le COMMIT et jamais
  si l'écriture échoue (ADR 0079).
- Réponse identique, que l'adresse existe déjà ou non (pas d'énumération) : « Si cette
  adresse est valide, un e-mail de vérification vient d'être envoyé ». Si l'adresse existe
  déjà, l'e-mail envoyé le dit et propose la connexion ; aucune seconde entreprise.
- POST /api/v1/auth/verify-email (publique) : jeton + usage unique ; pose email_verified_at,
  consomme le jeton, ne connecte PAS automatiquement (la personne se connecte avec son mot
  de passe). Même réponse pour tout jeton inconnu, expiré ou déjà utilisé.
- POST /api/v1/auth/resend-verification (publique) : même réponse neutre, 1 envoi toutes les
  60 s et 5 par jour et par adresse.
- Connexion : un compte dont email_verified_at est NULL est refusé APRÈS vérification du mot
  de passe (comme le mot de passe provisoire expiré, ADR 0078), avec un message qui propose
  de renvoyer le lien ; aucune session, aucun jeton.
- Limites (Redis, clés de la forme documentée au lot C, TTL partout) : inscriptions par
  adresse IP (par heure et par jour), par e-mail normalisé, et plafond global par heure qui
  déclenche une alerte de l'équipe au lieu d'un refus silencieux ; Redis indisponible =
  inscription REFUSÉE (fermé par défaut, jamais ouvert). Adresses jetables : liste courte
  maintenue dans le dépôt, refus avec un message clair ; pas de service tiers payant.
- Nettoyage : tâche de fond (beat, par entreprise, idempotente, journal job_runs) qui,
  après 7 jours sans vérification, marque l'entreprise « inscription abandonnée » sans la
  supprimer ; l'administration (lot 27) la montre ; la suppression définitive reste une
  décision humaine, documentée dans le runbook. [DEMANDER] si tu vois mieux.
- Aucun nouveau droit PostgreSQL sur les tables des commerçants : l'inscription passe par le
  chemin d'onboarding existant (rôle propriétaire de la CLI ou fonction dédiée, à décider
  dans l'ADR avec le moindre privilège).

S2. Frontend (frontend/, thème de la maquette v2)
- Page de connexion : lien « Créer ma boutique » (seulement si l'inscription est ouverte,
  l'état vient du serveur par /auth/me ou une route publique de configuration sans secret).
- /inscription : nom de la boutique, votre nom, e-mail, mot de passe (composant PasswordField
  afficher/masquer du prompt 28), case des conditions avec liens vers /cgu et
  /confidentialite, bouton « Créer ma boutique » désactivé tant que la case n'est pas
  cochée. Règle du mot de passe visible avant l'erreur. Aucune donnée dans l'URL.
- Écran « Vérifiez votre e-mail » avec « Renvoyer le lien » (délai affiché) et « Changer
  d'adresse » ; page /verification/[jeton] : succès -> « Votre boutique est prête » avec le
  code de la boutique affiché ET prérempli sur la connexion, ou message unique pour tout
  jeton invalide, avec renvoi.
- Première connexion d'un nouveau gérant : tableau de bord vide qui propose les trois gestes
  de départ (ajouter un article, ajouter un client, faire une première vente) ; aucune
  donnée de démonstration injectée.
- Accessibilité : axe 0 violation, clavier seul, 360 px sans défilement horizontal,
  messages d'erreur annoncés, focus sur le titre à chaque étape.

S3. Administration (frontend-admin/, lecture seule)
- La liste des entreprises montre l'origine « inscription libre-service » et l'état « e-mail
  non vérifié » / « inscription abandonnée » ; les statistiques du lot 26 comptent les
  inscriptions (déjà par semaine / mois). Aucune action nouvelle.

S4. Tests (rouge d'abord)
- Backend : inscription complète (entreprise, rôles, gérant, essai, audit, jeton haché en
  base) ; réponse identique adresse connue / inconnue ; jeton expiré, réutilisé, inconnu =
  même réponse ; ancien jeton invalide après renvoi ; connexion refusée avant vérification
  puis acceptée après ; limites par IP, par e-mail, globales ; Redis coupé = refus ; échec
  au COMMIT = ni entreprise ni e-mail ; interrupteur éteint = 404 partout ; isolation
  inter-tenant inchangée (la suite complète du lot C reste verte) ; deux inscriptions
  simultanées avec le même nom de boutique = deux codes distincts ; aucune écriture
  possible dans une autre entreprise par ces routes ; e-mails sans donnée inutile.
- Frontend : formulaire (case non cochée = bouton inactif, mot de passe affichable),
  écrans de vérification.
- E2E : inscription -> e-mail capturé -> lien -> connexion -> tableau de bord vide ->
  première vente ; lien invalide ; interrupteur éteint = pas de lien ni de page.
- make check-runtime (check_runtime_env) couvre COGES_SIGNUP_ENABLED et les variables SMTP.

Fin de lot
Suite backend complète, ruff, mypy, shellcheck, make front-check, e2e des écrans touchés,
tests de fuite inter-tenant, CI verte. ADR : choix du chemin d'onboarding et des droits,
politique de limites et de nettoyage, ce que voit un commerçant sans e-mail (il passe
toujours par l'équipe ou la CLI). README-infra.md, coges.env.example, un runbook
« ouvrir ou fermer les inscriptions » en français simple, CLAUDE.md §8 et table des ADR.

Hors lot, volontairement : demande d'accès à une boutique existante, inscription par
téléphone ou par SMS (service payant), connexion avec un compte tiers, paiement en ligne de
l'abonnement.
```

## Ce que le propriétaire fait lui-même

1. **Avant d'ouvrir** : vérifier que `COGES_SMTP_*` est dans `/etc/coges/coges.env` (sinon CoGes refuse de démarrer avec l'inscription ouverte) et que le lot Pages légales est déployé.
2. **Tester sur la préproduction** avec une vraie adresse : s'inscrire, cliquer le lien, se connecter, faire une vente, puis regarder la boutique dans l'administration.
3. **Allumer** `COGES_SIGNUP_ENABLED=true` seulement quand le test est concluant ; l'éteindre est immédiat en cas d'abus.
4. Décider avec le conseil juridique si l'essai gratuit demande une mention particulière dans les CGU.
