# 0104 — L'administration derrière Cloudflare Access, par un tunnel

- **Date** : 2026-10-29
- **Phase** : lot « Accès admin par Cloudflare Access »
- **Statut** : acceptée (amende 0089 : le filtre par adresse devient un retour arrière)
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
`admin.coges.app` n'était ouvert qu'aux adresses de `COGES_ADMIN_ALLOWED_IPS` (ADR 0089).
L'adresse publique Sonatel change chaque jour : l'équipe se retrouve dehors, et il faut
redéployer pour rentrer. Le domaine est déjà chez Cloudflare (registrar et DNS, en « DNS
only »). Objectif : l'administration accessible de partout, **seulement** après Cloudflare
Access (règle : une adresse e-mail), et impossible à atteindre en contournant Cloudflare.
`coges.app` et l'API commerçante ne changent pas. Aucun service payant.

## Options envisagées
1. **Tunnel Cloudflare (retenue)** : un conteneur `cloudflared` ouvre une connexion
   **sortante** vers Cloudflare ; `admin.coges.app` est routé par le tunnel vers Caddy, sur
   un port interne (8081) jamais publié. Caddy ne sert plus `admin.` sur 80/443 : la poignée
   TLS est refusée pour ce nom. Aucun port entrant, aucune liste d'adresses Cloudflare à
   tenir à jour.
2. Enregistrement « proxied » (nuage orange) : Caddy garde `admin.` sur 443 mais n'accepte
   que les plages d'adresses de Cloudflare (liste versionnée, à mettre à jour) et lit
   l'adresse réelle dans `CF-Connecting-IP`. **Les plages seules ne suffisent pas** : elles
   prouvent que la requête vient *d'un* serveur Cloudflare, pas qu'elle est passée par
   *notre* application Access. N'importe quel compte Cloudflare peut créer une zone dont un
   nom pointe sur l'adresse du VPS (ou un Worker qui l'appelle) et envoyer
   `Host: admin.coges.app` depuis ces mêmes plages, sans aucune règle Access. Seul le
   jeton signé par notre équipe, pour notre AUD, prouve le passage par Access.

Dans les deux cas le jeton `Cf-Access-Jwt-Assertion` est vérifié par CoGes. Où :
1. **Dans l'API, et par Caddy pour les pages (retenue)** : un middleware ASGI refuse en
   **403** `access_required` toute requête `/api/v1/platform/*` sans jeton valide, avant
   toute route (connexion et acceptation d'invitation comprises : pas même un essai de mot
   de passe). Caddy fait de même pour les pages par `forward_auth` vers
   `GET /api/v1/platform/access` (204 ou 403). Un seul vérificateur, en Python, testé.
2. API seulement : les pages (une coquille sans donnée) restaient servies sans contrôle.
3. API et `proxy.ts` de l'administration : deux implémentations à garder alignées.

Bibliothèque : **`pyjwt[crypto]`** (PyJWT était déjà là ; l'extra ajoute `cryptography`
pour RS256), plutôt qu'une seconde bibliothèque JOSE.

## Décision
- `app/core/cloudflare_access.py` : RS256 seul (ni `none`, ni HS256), signature avec les
  clés de `https://<équipe>.cloudflareaccess.com/cdn-cgi/access/certs`, `aud` contenant
  l'AUD, `iss` = l'équipe, `exp`/`nbf` avec 30 s de marge, une adresse e-mail présente.
  Clés gardées **1 h** ; un `kid` inconnu recharge le jeu (une fois par minute au plus) ;
  si le point certs ne répond plus, les clés déjà vérifiées servent encore **24 h**, puis
  refus. Sans clé en cache : refus immédiat. Jamais d'ouverture par défaut.
- Réglages `COGES_ACCESS_TEAM_DOMAIN` et `COGES_ACCESS_AUD` (les deux ou aucun, formes
  vérifiées au démarrage) ; `COGES_ACCESS_CERTS_URL` en `local` et `ci` seulement (e2e).
- **Porte de l'administration** `COGES_ADMIN_GATE`, qui choisit `admin-<porte>.caddy` :
  `cloudflare` (tunnel, port 8081, `forward_auth`, filet d'adresses facultatif sur
  `CF-Connecting-IP`, cru seulement venu du réseau `coges_tunnel` où ne sont que Caddy et
  `cloudflared`), `ip` (l'ancien site, retour arrière ; valeur par défaut, pour les
  fichiers d'avant ce lot) et `ssh` (secours si Cloudflare tombe : port 8082 publié sur
  `127.0.0.1` du VPS seulement, atteint par tunnel SSH).
- `check_runtime_env.py` (production) : `cloudflare` exige domaine d'équipe, AUD et jeton
  du tunnel bien formés ; `ip` exige la liste d'adresses ; hors `cloudflare`, les variables
  Access doivent être vides (l'API exigerait un jeton que plus rien n'apporte). Aucune
  administration sans protection.
- `deploy.sh` ajoute le profil `tunnel` en mode `cloudflare` et arrête `cloudflared` sinon
  (un service hors profil n'est pas un « orphelin » pour `up --remove-orphans`).
- `cloudflared` figé par condensat (`2026.10.0`), sans capacité, jeton
  `COGES_CLOUDFLARE_TUNNEL_TOKEN` transmis à lui seul.
- Guide pour le propriétaire : `deploy/vps/cloudflare-access.md` (Zero Trust, application,
  tunnel, variables, vérifications, retour arrière, secours).

## Conséquences
- Tests : vérificateur (valide, absent, autre clé, `none`, HS256, AUD, `iss`, expiré, pas
  encore valable, sans e-mail, cache, renouvellement, `kid` inconnu borné, panne avec et
  sans cache, 24 h), application entière (sonde, connexion refusée malgré le bon mot de
  passe, chaque route plateforme, routes commerçantes inchangées), rendu du Caddyfile par
  `caddy adapt` dans les trois portes, compose (port 8081 jamais publié, 8082 sur la boucle
  locale, réseau `tunnel` réduit à deux membres, jeton du tunnel chez `cloudflared` seul),
  `check_runtime_env.py` et `deploy.sh`. e2e de l'administration : l'API des parcours exige
  le jeton, signé par une clé de test dont `e2e.sh api` sert le jeu public ; un parcours
  sans jeton est refusé avec le bon mot de passe.
- `GET /api/v1/platform/access` entre dans les registres (route publique, aucune donnée).
- Un collègue invité doit aussi figurer dans la règle Access.
- Après 24 h, la session Cloudflare expire : un rechargement redemande le code.
- Revenir à une version d'avant ce lot n'est possible qu'en mode `ip`.
- Le secours `ssh` ne laisse que le mot de passe : à réserver à une panne de Cloudflare.

## Correctif du 2026-10-29 : l'image API ne démarrait pas
L'image de 3cafc49 s'arrêtait au démarrage (`ModuleNotFoundError: No module named 'httpx'`,
`app/core/cloudflare_access.py`) : `httpx` n'était que dans le groupe `dev`, que les images
n'installent pas (`uv sync --no-dev`). Tests verts, déploiement refusé puis annulé ; le
retour automatique a lui aussi échoué, la version précédente refusant le `coges.env`
écrit pour celle-ci.
- `httpx` passe dans `[project].dependencies`, avec `anyio`, `starlette` et `kombu`,
  importés directement par `app/` mais reçus jusque-là par fastapi ou celery seulement.
- `tests/architecture/test_runtime_dependencies.py` lit chaque `import` de `app/` (`ast`)
  et exige un paquet de `[project].dependencies` (ou du groupe `ml`, confiné au worker).
- `deploy/scripts/check_image_imports.sh` lance l'image construite, sans réseau, et importe
  son point d'entrée (`app.main` ; l'application Celery et ses tâches, le relais, la
  sonde) : dans la CI après chaque construction, et dans `deploy.yml` **avant** la
  poussée vers le registre (l'image publiée est construite depuis l'étiquette, pas depuis
  le commit vérifié par la CI).
- `deploy.sh` : `check_env` rend la main au lieu d'arrêter le script et écrit les refus
  dans le journal ; la version en place est contrôlée avant de commencer (avertissement
  « pas de retour automatique possible ») ; si le retour est impossible, rien n'est
  relancé et le journal dit l'état de la pile et les deux issues, avec les commandes
  exactes ; un fichier refusé par la nouvelle version arrête tout avant le moindre
  changement.
