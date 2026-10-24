# 0092 — Accès support encadré à une entreprise (lot admin 4)

- **Date** : 2026-10-24
- **Phase** : lot admin 4 (`docs/prompts/25-admin-support-encadre.md`)
- **Statut** : acceptée — **relecture humaine demandée avant la fusion**
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte, pour qui n'a pas suivi le développement

Jusqu'ici, l'équipe CoGes ne voyait d'une entreprise que des métadonnées : nom, statut,
nombre de comptes, abonnement (ADR 0089, 0091). Aucune vente, aucun stock, aucun montant
commercial. C'est voulu : le compte de l'administration (`coges_app_platform` en base) n'a
**aucun droit** sur les tables commerciales.

Mais un commerçant qui appelle « ma caisse ne tombe pas juste » ne peut être aidé que si
quelqu'un regarde ses chiffres. Ce lot ouvre donc, **à titre exceptionnel, temporaire et
tracé**, la seule porte vers les données d'une entreprise depuis l'équipe CoGes. C'est le
lot qui touche le plus directement à la confiance des commerçants.

Principe imposé, et tenu : **aucun rôle PostgreSQL nouveau, aucun contournement de la
RLS**. L'équipe lit par *exactement* le même chemin qu'un utilisateur de l'entreprise :
le rôle `coges_app`, la RLS normale, `SET LOCAL app.company_id` posé par le serveur. Elle
ne voit donc rien de plus qu'un employé de la boutique — et même moins (lecture seule).

## Options retenues (AskUserQuestion)

- **Déclenchement : le « bris de glace » d'abord.** Un membre de l'équipe ouvre l'accès
  seul, avec un **motif obligatoire** (10 caractères au moins), sans attendre le gérant —
  le cas « le commerçant appelle, on doit regarder ». Le **consentement du gérant** (le
  gérant accorde l'accès depuis son application) viendra plus tard sans changer la
  structure : la colonne `granted_by_user_id` existe déjà, NULL pour un bris de glace.
- **Durée : 2 h par défaut, 4 h au maximum**, de 30 min en 30 min dans le formulaire. Le
  maximum est vérifié par l'API **et** par une contrainte en base.
- **Voir les données : dans l'application commerçante elle-même**, ouverte dans un nouvel
  onglet avec le jeton de support, plutôt que de recopier des écrans dans l'administration.
  Les boutons d'écriture disparaissent parce que le rôle de support ne porte que des
  lectures, et le serveur refuse de toute façon.
- **Un seul droit en base ajouté**, validé explicitement (le prompt l'exigeait) :
  `coges_app` lit **cinq colonnes** de `support_sessions` — `id`, `company_id`,
  `started_at`, `expires_at`, `ended_at` —, et seulement les lignes de sa propre entreprise
  (RLS). Ni qui a ouvert, ni le motif. C'est ce qui permet à l'API de **revérifier la
  session à chaque requête** et d'afficher le bandeau à tous les utilisateurs. La
  plateforme, elle, ne gagne rien sur les tables commerciales.

Décidé dans le plan, sans objection :
- administrateur **et** support (les deux profils de l'équipe) peuvent ouvrir et fermer ;
  seul celui qui a ouvert peut obtenir à nouveau le jeton ;
- **une seule session ouverte** par entreprise (index unique) ;
- entreprise suspendue : pas d'accès support (refusé à l'ouverture, et le jeton serait de
  toute façon refusé comme celui de tout utilisateur) ;
- le rôle `support_readonly` est **défini dans le code** (`app/core/support_access.py`, repris
  par la matrice `rbac/matrix.py`), **jamais en base** : aucune entreprise ne le voit dans
  ses rôles, personne ne peut le recevoir.

## Décision

**Base (révision 0029).** Table `support_sessions` : qui (`platform_user_id`), pourquoi
(`justification`), quand (`started_at`, `expires_at`, `ended_at`, `ended_by`), et pour le
futur consentement `granted_by_user_id`. Rien de commercial. RLS FORCE : politique tenant
plus une politique qui ne nomme que `coges_app_platform`. Une garde (`CG008`) interdit de
réécrire une session, sauf pour la fermer, une fois. `notifications.type` admet
`support_access`.

**Le jeton.** Même mécanisme que celui d'un commerçant (même signature, même audience),
avec `via_support_session=true`, l'identifiant de session `sid`, aucun utilisateur, et
l'échéance **de la session** (pas 15 min). À **chaque** requête, `core/deps.py` :
1. refuse toute méthode autre que GET/HEAD (`403 support_read_only`), avant toute
   transaction ;
2. ouvre la transaction en `coges_app` sur l'entreprise du jeton et la déclare
   **`READ ONLY`** : PostgreSQL refuse lui-même la moindre écriture ;
3. relit la session sous la RLS : fermée, échue ou d'une autre entreprise ⇒
   `401 support_session_ended` ; entreprise suspendue ⇒ `403 company_suspended` ;
4. pose les permissions de `support_readonly` : dix-neuf lectures (ventes, stock, argent,
   clients, fournisseurs, conseils, journal, personnes, rôles…), **sans** les
   notifications (le fil est personnel) **ni** les exports (un export écrit un fichier).

Trois verrous indépendants : il faudrait que les trois cèdent ensemble pour qu'une écriture
passe.

**API de l'administration** (`/api/v1/platform`) : `POST /companies/{id}/support-sessions`
(ouvre et rend le jeton), `POST /support-sessions/{id}/token` (le redonne à qui l'a
ouverte), `DELETE /support-sessions/{id}` (ferme), `GET /companies/{id}/support-sessions`
(en cours et 20 dernières).

**Traces, des deux côtés.** L'ouverture et la fermeture s'écrivent dans
`platform_audit_logs` **et** dans le journal d'activité **de l'entreprise** (`audit_logs`,
auteur « l'équipe CoGes », jamais le nom de la personne ; le motif est cité). Le journal de
l'entreprise est écrit par `coges_app` dans le contexte de cette entreprise — le chemin de
tout utilisateur : c'est la **seule exception assumée** à la règle « le module `platform/`
ne parle qu'à `coges_app_platform` ». Les deux journaux sont sur deux connexions : celui de
l'entreprise est validé **d'abord**, et le jeton n'est rendu qu'une fois les deux validés.
Un accès utilisable laisse donc toujours sa trace chez l'entreprise ; dans le cas
(rarissime) où le second COMMIT échoue, l'entreprise peut lire une tentative qui n'a rien
ouvert (500, aucun jeton) — jamais l'inverse. Chaque nouvel envoi du jeton est aussi
journalisé côté plateforme.

**Le commerçant est prévenu.** Après COMMIT, une tâche du worker envoie un e-mail immédiat
au(x) gérant(s) (le motif et l'heure de fin) et pose une alerte dans la cloche. Un
**bandeau** « Accès support actif depuis 10 h 15, par l'équipe CoGes, jusqu'à 12 h 15 »
s'affiche pour **tous** les utilisateurs de l'entreprise (`GET /companies/me/support-access`,
relu toutes les minutes). L'historique des réglages raconte : « L'équipe CoGes a ouvert un
accès support, en lecture seule. Motif : « … » », puis « … a fermé son accès support ».

**Fin de l'accès.** Fermé avant l'heure : le jeton est refusé dès la requête suivante. À
l'heure dite : refusé sans rien faire (la base fait foi, pas seulement le jeton). Chaque
nuit (01 h 30 UTC), `platform.support_sessions_close` marque fermées les sessions échues,
pour que la liste des sessions ouvertes reste exacte.

**Côté navigateur.** « Voir l'entreprise » ouvre `https://<domaine>/support#token=…` : le
jeton est dans le **fragment**, qui ne part vers aucun serveur ; la page l'efface aussitôt de
l'adresse et le garde dans le `sessionStorage` de l'onglet. Un onglet de support n'appelle
jamais `/auth/refresh` ni `/auth/logout` (une vraie session ouverte dans le même navigateur
n'est jamais touchée) ; à la fin, il affiche « L'accès support est terminé ».

## Conséquences

- Tests : 82 tests dédiés (`test_support_access.py`), dont **toutes** les routes
  d'écriture de l'API commerçante (52, découvertes automatiquement) qui refusent le jeton,
  l'écriture refusée par la transaction elle-même, l'expiration et la fermeture à la
  requête suivante, l'isolation (le jeton de A ne voit rien de B, ajouté au balayage
  `test_list_routes_cross_tenant.py`), le COMMIT refusé ; e2e de bout en bout
  (`frontend-admin/e2e/support.spec.ts`).
- Registres : liste blanche du rôle plateforme, tâche de beat classée, routes classées.
- `audit_logs.actor_user_id` est désormais NULL (et non l'UUID nul) pour toute écriture
  sans utilisateur.
- Non fait : le consentement du gérant (a) ; un écran côté commerçant pour fermer lui-même
  l'accès (il peut répondre à l'e-mail) ; une alerte à l'équipe à chaque ouverture.
- Exploitation : `COGES_MERCHANT_URL` pour le conteneur `admin` (posé par le compose),
  procédure dans `docs/runbooks/acces-support.md`.
