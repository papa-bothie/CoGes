# Prompt 22 — Lot admin 1 : rôle plateforme, statut des entreprises, vue métadonnées

Branche `feat/admin-platform-role`, depuis `main` à jour, après le lot C (prompt 20) et les correctifs de la revue (prompt 21). Premier lot de l'interface d'administration CipherOne : pose le socle (comptes plateforme, séparation stricte d'avec les comptes des entreprises clientes, statut actif/suspendu, et une première vue en lecture) sur lequel s'appuient tous les lots suivants (23 à 26). Aucune donnée commerciale d'une entreprise n'est accessible depuis ce lot — volontairement.

```
Lot admin 1 — Rôle plateforme et métadonnées des entreprises (branche feat/admin-platform-role,
depuis main à jour). Règles habituelles : ADR aux prochains numéros libres, tests d'abord, aucun
service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni backend/.vercel/.
Résumé en français à la fin, questions ouvertes par AskUserQuestion.

Principe directeur : le rôle plateforme ne doit JAMAIS, par construction, pouvoir lire les
ventes, le stock, la finance ou les référentiels d'une entreprise cliente. Pas une règle
applicative qu'on espère ne pas oublier de vérifier : une impossibilité au niveau du rôle
PostgreSQL, comme coges_backup ne peut déjà ni écrire ni se connecter depuis l'API.

[DEMANDER] avant de coder la section 1 : deux manières de lire les métadonnées plateforme à
travers la RLS. (a) Un rôle PostgreSQL dédié coges_app_platform, sans BYPASSRLS, avec un GRANT
SELECT limité aux seules tables/colonnes désignées « plateforme » (companies, un sous-ensemble de
colonnes, job_runs, les futures tables plans/subscriptions) — aucune table commerciale n'a de
GRANT pour ce rôle, donc une erreur de code ne peut physiquement pas lire une vente. (b) Garder
coges_app et ajouter une politique RLS supplémentaire par table (« OR current_setting
('app.platform_mode', true) = 'true' »), posée seulement par l'authentification plateforme.
Recommandation : (a), parce que l'impossibilité est au niveau du GRANT, pas d'un indicateur
logique qu'un bug pourrait contourner. Pose la question quand même : c'est structurant pour tous
les lots suivants.

1. Comptes et authentification plateforme
   - Nouvelle table platform_users (migration au prochain numéro libre, hors du schéma
     tenant, AUCUNE colonne company_id, pas sous RLS tenant — table de plateforme comme
     job_runs) : id, email, password_hash (Argon2, mêmes paramètres que users), display_name,
     is_active, created_at. Table platform_roles / platform_user_roles si plusieurs profils sont
     nécessaires dès maintenant (au minimum « administrateur », « support ») ; sinon une seule
     colonne role sur platform_users avec les deux valeurs, à étendre plus tard — pose la
     question par AskUserQuestion si ce n'est pas évident après lecture du code RBAC existant.
   - auth/service dédié (module platform/, voir plus bas) : /api/v1/platform/auth/login
     (e-mail + mot de passe, PAS le même écran que la connexion commerçant, PAS de sélecteur
     d'entreprise), JWT courts + refresh rotatif sur le même modèle que l'auth existante, mais
     avec une revendication platform_role au lieu de company_id — ce jeton ne doit JAMAIS être
     accepté par les routes /api/v1/* existantes, et réciproquement un jeton commerçant ne doit
     jamais être accepté par /api/v1/platform/*. Teste les deux sens.
   - Même freinage de connexion que le lot A (compteur par identifiant, barème progressif,
     jamais de verrouillage définitif) ; pas de notification au « gérant » puisqu'il n'y en a
     pas à ce niveau — notifie plutôt une adresse e-mail de l'équipe (variable d'env).
   - COGES_OPS_TOKEN existant (prompt 17) : NE LE RETIRE PAS. Il reste la voie d'accès
     machine à machine pour make ops-status et un futur script d'automatisation. Les comptes
     platform_users sont la voie humaine, pour l'interface web. Documente la distinction dans
     README-infra.md.

2. Nouveau module backend platform/
   - backend/app/modules/platform/ : router.py, service.py, repository.py, models.py,
     schemas.py — gabarit habituel (décision 0010), mais ce module ne dépend d'AUCUNE bande
     métier existante et aucune bande métier n'en dépend : c'est un axe à part, pas une
     sixième bande en dessous de Restitution. Documente ce choix dans l'ADR du lot.
   - Le repository de ce module utilise exclusivement le rôle choisi à la section [DEMANDER]
     (coges_app_platform recommandé) via une dépendance FastAPI dédiée (jamais la dépendance
     tenant existante core/deps.py get_db, qui pose app.company_id : ici il n'y en a pas).
   - Toutes les routes sous /api/v1/platform/*, jamais sous /api/v1/*.

3. Statut des entreprises
   - Migration : companies.status (enum : trial, active, suspended ; défaut active pour les
     entreprises existantes, trial pour les nouvelles une fois le lot 24 branché). Downgrade
     testé.
   - Vérification à la connexion ET à chaque requête authentifiée d'un utilisateur commerçant
     (core/deps.py, comme pour un jeton expiré) : entreprise suspended -> refus avec un message
     clair, dans le ton de la page d'erreur déjà conçue (prompt 19), jamais une erreur
     technique. Code dédié company_suspended. Entreprise en essai dont la date de fin est
     dépassée (table créée au lot 24, donc prévois juste le point d'extension ici, pas la
     logique complète) : laisse un TODO documenté plutôt qu'une fausse implémentation.
   - Écran de connexion commerçant : affiche le message dédié si l'API renvoie company_suspended
     plutôt que le message générique d'identifiants invalides.

4. Lecture des métadonnées plateforme
   - GET /api/v1/platform/companies (paginé, recherche par nom/slug) : nom, slug, statut, date
     d'inscription, nombre d'utilisateurs, date de dernière activité (dernière ligne dans
     audit_logs pour cette entreprise, rien de plus précis). AUCUN montant, AUCUNE donnée
     commerciale, même agrégée, à ce stade (ça vient aux lots 24 et 26).
   - GET /api/v1/platform/companies/{id} : le détail de ce qui précède, plus la liste des
     utilisateurs de l'entreprise (nom, rôle, dernière connexion) — toujours sans toucher aux
     données commerciales.
   - PATCH /api/v1/platform/companies/{id}/status : active <-> suspended (jamais vers trial
     depuis cette route). Audit critique obligatoire (table d'audit plateforme distincte de
     audit_logs du tenant — crée platform_audit_logs, même esprit que audit_logs mais hors RLS
     tenant). Envoie une notification par e-mail au gérant de l'entreprise (réutilise le
     mécanisme de notification existant si possible, sinon un envoi e-mail simple documenté).

5. Interface web
   - [DEMANDER] : application séparée frontend-admin/ (nouveau projet Next.js, son propre
     Dockerfile, déployée comme un service de plus dans deploy/vps/docker-compose.yml, servie
     par Caddy sur un sous-domaine dédié, par exemple admin.COGES_DOMAIN) plutôt qu'un groupe de
     routes protégées dans le frontend commerçant existant. Recommandation : application
     séparée — aucune route ni aucun bundle JavaScript d'administration n'est jamais livré au
     navigateur d'un commerçant, surface d'attaque plus petite, cohérent avec la philosophie du
     VPS (prompt 18). Coût : un peu de duplication (design system, client API).
   - Caddy : le sous-domaine admin n'est PAS ouvert à tout le monde — restriction par liste
     d'IP autorisées (variable d'env COGES_ADMIN_ALLOWED_IPS, bloc @admin_allowed remote_ip dans
     le Caddyfile, 403 sinon) en plus de l'authentification applicative. Documente dans
     docs/runbooks/vps.md comment ajouter une IP.
   - Écran de connexion propre (pas de sélecteur d'entreprise, pas le même logo/ton que
     l'app commerçant — un habillage neutre « CoGes — Administration » suffit pour ce lot).
   - Écran liste des entreprises (section 4), écran détail avec le bouton
     activer/suspendre (confirmation obligatoire avant l'appel API, comme pour toute action
     irréversible ou à fort impact dans le projet).

6. Tests
   - Un jeton plateforme ne peut appeler aucune route /api/v1/* existante (401/403, jamais de
     donnée) ; un jeton commerçant ne peut appeler aucune route /api/v1/platform/* (même
     chose) ; sans jeton -> 401 sur les deux familles.
   - Avec le rôle choisi en section [DEMANDER] : test qui énumère TOUTES les tables de la base
     et vérifie qu'aucune table commerciale (ventes, stock, finance, référentiels, clients,
     fournisseurs) n'a de GRANT pour ce rôle — test d'architecture, bloquant en CI, sur le
     modèle des tests de rôle existants (coges_backup, coges_relay).
   - Entreprise suspendue : connexion refusée avec le message dédié ; un jeton émis AVANT la
     suspension cesse de fonctionner à la requête suivante (pas seulement à la prochaine
     connexion).
   - Isolation : deux entreprises A et B, le résumé de A ne contient jamais le nom, le nombre
     d'utilisateurs ni rien de B et réciproquement (même esprit que tests/tenancy, mais ici
     c'est l'inverse qu'on vérifie : que le rôle plateforme voit bien A ET B, dans les colonnes
     autorisées, sans jamais de donnée commerciale d'aucune des deux).
   - Suite backend complète, ruff, mypy, make front-check sur les deux projets front, e2e de
     l'écran de connexion plateforme et de l'écran liste/détail.

Fin du lot : met à jour README-infra.md (nouveau service frontend-admin, sous-domaine, variable
COGES_ADMIN_ALLOWED_IPS, rôle coges_app_platform) et CLAUDE.md (nouveau module platform/, hors
des cinq bandes). Documente dans un ADR les deux choix structurants de ce lot (accès par rôle
PostgreSQL dédié, application séparée) avec leurs raisons.
```

## Ce que le propriétaire fait lui-même

1. Choisir et déposer la ou les adresses IP autorisées à atteindre le sous-domaine admin (`COGES_ADMIN_ALLOWED_IPS`).
2. Créer le premier compte `platform_users`, ou fournir l'e-mail à utiliser pour le compte provisoire posé par un script de bootstrap que l'agent écrit (jamais une route publique d'inscription).
3. Choisir le nom du sous-domaine (par exemple `admin.COGES_DOMAIN`) et s'assurer qu'il pointe vers le VPS.
4. Répondre aux questions `AskUserQuestion` avant que l'agent commence à coder.
