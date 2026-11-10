# 0117 — Pages légales et acceptation tracée

- **Date** : 2026-11-10
- **Phase** : prompt 36 (pages légales, avant le lot 30 « Inscription libre-service »)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion) ; mécanique imposée par le prompt 36

## Contexte
CoGes doit publier ses conditions générales d'utilisation et de vente et sa politique de
confidentialité sur `coges.app`, les rendre lisibles sans connexion et pouvoir prouver
qu'un compte les a acceptées, dans quelle version. Les textes sont rédigés par le
propriétaire (`frontend/content/legal/conditions.md` et `confidentialite.md`). Chacun
commence par `<!-- version: AAAA-MM-JJ -->`. Le code ne les rédige ni ne les modifie.

Les textes nomment Hetzner (Allemagne) comme hébergeur du serveur, alors que les runbooks
parlent d'un VPS Infomaniak. Le propriétaire confirme Hetzner (AskUserQuestion) : les
runbooks seront mis à jour à part.

## Options envisagées
Rendu du Markdown :
1. **`marked` 18.1.3 figée (retenue)** : une seule dépendance, sans sous-dépendance, sous
   licence MIT, publiée le 2 novembre 2026. Seul son **analyseur** sert : les jetons sont
   rendus en React (`components/legal/legal-markdown.tsx`). Il n'y a ni `innerHTML` ni HTML
   brut : un commentaire ou une balise du texte est ignoré. Un élément non prévu fait
   échouer le build plutôt que de s'afficher à moitié.
2. Un petit analyseur maison : aucune dépendance, mais il serait fragile au premier texte
   plus riche.
3. `remark` + `remark-gfm` : une vingtaine de paquets transitifs.

Barrière avant acceptation :
1. **Même mécanique que le mot de passe provisoire (ADR 0074), retenue** : barrière
   serveur dans `core/deps.py`, relue à chaque requête, et redirection du front par la
   coquille. Aucune seconde mécanique n'est créée.
2. Un écran côté front seulement : contournable, refusé par le prompt.

## Décision
- **Pages** : `/conditions` et `/confidentialite` sont rendues **au build**
  (`force-static`, `app/(vitrine)/`). Elles ne font aucune requête à l'API et sont
  publiques dans `proxy.ts`, nommées une à une.
  - La date de version est lue dans la ligne `<!-- version -->` du fichier
    (`lib/legal/parse.ts`) et n'est écrite nulle part ailleurs dans le front. Elle
    s'affiche en tête : « Version du 01/12/2026 ».
  - Les tableaux défilent dans leur propre cadre, focalisable au clavier (WCAG 1.4.10 et
    `scrollable-region-focusable`).
  - Les pages sont indexables et figurent dans `sitemap.xml` et `robots.txt`.
  - `/cgu` et `/cgv` redirigent en 308 vers `/conditions` (`next.config.ts`).
  - Le service worker ne garde aucune navigation : une nouvelle version paraît aussitôt
    (test). La CSP ne change pas.
  - `content/legal/` est exclu de Prettier : le texte juridique n'est jamais reformaté.
- **Liens** : le composant `LegalLinks` apparaît au pied de la connexion, de
  « Choisissez votre mot de passe », de la vitrine et des textes eux-mêmes. Le menu du
  compte (l'engrenage, visible par tous les rôles, contrairement à Réglages) porte les deux
  entrées. L'administration n'est pas concernée.
- **Base** (révision 0038) : `users.legal_accepted_version` (text) et
  `users.legal_accepted_at` (timestamptz), nullables, ajout seul.
  `users_legal_acceptance_coherent` exige les deux ensemble, ou aucun.
- **Version côté serveur** : `LEGAL_VERSION` dans `backend/app/core/legal.py`, une seule
  valeur pour les deux textes, égale à la plus récente de leurs dates.
  `tests/unit/test_legal_version.py` vérifie l'égalité avec les fichiers.
  - `GET /auth/me` rend `legal_version`, `user.must_accept_legal` et
    `user.legal_accepted_version`.
- **Barrière** : si la version acceptée diffère de `LEGAL_VERSION`, toute route répond
  409 `legal_acceptance_required`, sauf `/auth/me` et `/auth/legal-acceptance`. Le mot de
  passe provisoire passe d'abord : tant qu'il est à changer, l'acceptation elle-même
  répond `password_change_required`. Un jeton de support n'est pas concerné (il n'accepte
  rien au nom de l'entreprise).
- **`POST /api/v1/auth/legal-acceptance`** : tout utilisateur connecté, pour lui-même.
  - Le corps est vide (`extra="forbid"`) : une `version` ou un `user_id` envoyés sont
    refusés en 422.
  - La version enregistrée est celle du serveur.
  - Audit critique : version avant et après, plus la date. L'historique dit « X a accepté
    les conditions d'utilisation et la politique de confidentialité ».
  - Déjà acceptée : 204, rien n'est réécrit ni audité.
  - Classée `Exempt` dans `commit_failure_registry.py` (sa propre ligne, sans argent ni
    stock).
- **Front** : l'écran `/acceptation` (« Avant de continuer ») porte les deux liens (nouvel
  onglet) et la case `LegalConsent`. « Accepter et continuer » reste inactif tant que la
  case n'est pas cochée.
  - La coquille y renvoie dès que `must_accept_legal` est vrai, après le mot de passe.
  - Le client API y renvoie aussi sur tout 409 `legal_acceptance_required` : un onglet
    resté ouvert pendant un changement de version y arrive à sa requête suivante.
- **Seeds locaux** (`demo`, `maquette`) : les comptes sont marqués comme ayant accepté, sans
  ligne d'audit (l'écran Historique des captures ne change pas). `--existing-slug` ne
  touche à rien : une vraie entreprise accepte elle-même.
- **Inscription libre-service (lot 30)** : elle n'est pas encore dans `main`. Son formulaire
  devra reprendre **`components/legal/legal-consent.tsx`** (case obligatoire, liens) et
  `LegalLinks` en pied. Le compte gérant y sera créé avec `legal_accepted_version =
  LEGAL_VERSION` et `legal_accepted_at = now()`, dans la transaction de création, avec le
  même audit.

## Conséquences
- Changer `LEGAL_VERSION` redemande l'acceptation à **tout le monde**, dès sa requête
  suivante (la barrière est relue à chaque requête). La procédure est dans
  `docs/runbooks/textes-legaux.md`.
- Les comptes existants sont à `NULL` : ils accepteront au premier passage après le
  déploiement.
- Tests :
  - les aides `login_token` et `create_user_with_role` du backend acceptent après la
    connexion ;
  - côté e2e, `loginThroughUi` passe l'écran s'il s'ouvre (`{ acceptLegal: false }` pour
    le prouver) et `apiLogin` accepte par l'API ;
  - `e2e.sh system legal-stale <e-mail>` simule une version changée.
- `marked` entre dans les dépendances du front (aucune au runtime : le rendu se fait au
  build).
