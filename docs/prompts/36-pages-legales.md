# Prompt 36 — Pages légales (CGU/CGV et confidentialité) sur coges.app

> **STATUT : PRÊT À LANCER** (8 novembre 2026). Remplace l'ancienne version reportée du 28 octobre. Ce lot passe **avant** le lot 30 « Inscription libre-service ».

Branche `feat/legal-pages`, depuis `main` à jour.

## Avant de lancer (propriétaire)

1. Dans les docs « CoGes — Conditions générales d'utilisation et de vente » et « CoGes — Politique de confidentialité (v1.0) », remplacer tous les crochets : e-mail de contact, WhatsApp, ville (Saint-Louis ?), date d'entrée en vigueur.
2. Exporter chaque doc en Markdown (menu d'export du doc).
3. Ajouter en **première ligne** de chaque fichier : `<!-- version: 2026-11-XX -->` (la date d'entrée en vigueur).
4. Déposer les fichiers dans le dépôt :
   - `frontend/content/legal/conditions.md` (CGU/CGV)
   - `frontend/content/legal/confidentialite.md`
5. Ne pas mettre en production tant que la déclaration CDP n'est pas faite (la politique l'affirme).

## Prompt à donner à l'agent

```
Lot « Pages légales » (branche feat/legal-pages, depuis main à jour).
Règles habituelles : ADR au prochain numéro libre, tests d'abord, aucun service payant,
ne jamais ouvrir ni commiter .env, deploy/.env.preprod, backend/.vercel/ ni /etc/coges/*.
Résumé en français à la fin, questions ouvertes par AskUserQuestion.

Les textes sont fournis par moi :
- frontend/content/legal/conditions.md   (CGU et CGV, un seul document)
- frontend/content/legal/confidentialite.md
Chacun commence par une ligne <!-- version: AAAA-MM-JJ -->.
Tu ne rédiges ni ne modifies leur contenu juridique. Si un fichier contient encore un
crochet du type « [à définir] », « [à confirmer] » ou « [date ...] », ou n'a pas de ligne
de version, arrête-toi et liste-moi les passages concernés.

L1. Deux pages publiques dans le front marchand
- /conditions et /confidentialite : rendu statique au build du Markdown (aucune requête à
  l'API). Si une bibliothèque Markdown est nécessaire : une seule, version figée, justifiée
  dans l'ADR. Les tableaux Markdown doivent s'afficher correctement (prix, prestataires,
  durées). Style de la maquette v2, tokens existants, lisible sur téléphone, thème clair et
  sombre, date de version visible en tête.
- Redirection permanente /cgu et /cgv -> /conditions.
- Accessibles SANS connexion : vérifie frontend/proxy.ts (redirection vers /login), le
  service worker (pas de mise en cache qui empêcherait une nouvelle version d'apparaître)
  et la CSP de next.config.ts. Test e2e : navigation privée, aucun appel à l'API.
- Version de chaque texte lue depuis sa ligne <!-- version --> au build, jamais écrite deux
  fois dans le code front.

L2. Liens
- Pied des pages de connexion et d'inscription : « Conditions d'utilisation et de vente ·
  Confidentialité ».
- Dans l'application : écran Paramètres (ou menu du compte), mêmes deux liens.
- Le front d'administration n'est pas concerné.

L3. Acceptation tracée
- Migration au prochain numéro : users.legal_accepted_version (text, nullable) et
  users.legal_accepted_at (timestamptz, nullable). Rétrocompatible (ADR 0083) : ajout seul.
- Version courante côté serveur : une constante backend LEGAL_VERSION (une seule valeur
  pour les deux textes, = la plus récente des deux dates). Un test vérifie qu'elle est
  égale à la plus récente des lignes <!-- version --> des deux fichiers, pour qu'on ne
  puisse pas oublier de la changer. Exposée par /auth/me.
- À la connexion, si la version acceptée est absente ou différente : écran « Avant de
  continuer » avec les deux liens et la case « J'ai lu et j'accepte les conditions
  d'utilisation et de vente et la politique de confidentialité ». Bouton inactif tant que
  la case n'est pas cochée. Rien d'autre accessible avant acceptation : réutilise la
  mécanique du changement de mot de passe provisoire (ADR 0074), n'en crée pas une seconde.
  Si les deux s'appliquent, mot de passe d'abord, puis acceptation.
- Route POST /api/v1/auth/legal-acceptance : enregistre la version COURANTE du serveur
  (jamais une version envoyée par le client), audit critique, schéma extra="forbid", tout
  utilisateur connecté, pour lui-même seulement.
- Inscription libre-service : si ce lot est déjà dans main, son formulaire doit porter la
  même case (obligatoire) et enregistrer l'acceptation à la création du compte gérant ;
  sinon, prévois un composant réutilisable et note-le dans l'ADR pour le lot inscription.
- Changer LEGAL_VERSION redemande l'acceptation à tous à leur prochaine connexion.
- Tests : backend (enregistrement, refus pour un autre utilisateur, audit, version imposée
  par le serveur, isolation entre entreprises) ; front (case non cochée = bouton inactif) ;
  e2e (premier login -> acceptation -> application ; second login -> plus d'écran ;
  changement de version -> l'écran revient).

L4. Fin du lot
Suite backend complète, ruff, mypy, make front-check, e2e des écrans touchés, Lighthouse
≥ 95 sur /conditions et /confidentialite, tests de fuite inter-tenant, CI verte. Mets à
jour CLAUDE.md (route, colonnes, constante) et docs/runbooks : publier une nouvelle version
d'un texte (déposer le Markdown, changer la ligne version et LEGAL_VERSION, déployer ;
tous les utilisateurs réacceptent).
```

## Après le lot (propriétaire)

1. Relire la PR (vérifier que le texte juridique n'a pas été modifié), fusionner.
2. Déployer : Actions → « Déployer » → production (migration jouée), puis sur le VPS : `cd /opt/coges && sudo -u deploy /opt/coges/deploy.sh production <version>`.
3. Vérifier en navigation privée : `https://coges.app/conditions` et `/confidentialite` s'ouvrent sans connexion, tableaux lisibles sur téléphone.
4. Se connecter avec la boutique de test : l'écran d'acceptation apparaît une fois, puis plus.
