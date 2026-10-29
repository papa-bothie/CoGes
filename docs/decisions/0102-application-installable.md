# 0102 — Application installable : hors ligne minimal et mises à jour invisibles

- **Date** : 2026-10-28
- **Phase** : prompt 29, P2 (brouillons et PWA)
- **Statut** : acceptée
- **Décideur** : utilisateur (prompt 29 : installable + hors ligne + mises à jour invisibles ; via
  AskUserQuestion : worker écrit à la main, en-tête de version + version minimale, anciens fichiers
  gardés dans un volume servi par le front)

## Contexte
Aucune base : ni manifeste, ni service worker. Le propriétaire veut une application installable,
une page hors ligne et des mises à jour dont personne ne s'aperçoit. Pas de lecture hors ligne des
données, pas de vente hors ligne (lot à part : conflits de stock et de caisse).

## Décision
### Installable
- `app/manifest.ts` : « CoGes », `lang: fr`, `standalone`, `start_url: /dashboard` (que tout rôle
  lit ; sans session, `proxy.ts` mène à la connexion), `scope: /`. Icônes 192, 512 et masquable 512
  tirées du symbole officiel (`app/icon.png`, 256 px : le 512 est agrandi, un peu moins net).
- Couleurs : seule exception au garde-fou des couleurs, `lib/brand-colors.ts`, testé contre les
  jetons `--coges-vert-marque` et `--coges-papier`.
- « Installer l'application » dans le menu du compte (Android/Chrome : `beforeinstallprompt`
  gardé puis rejoué) ; aide iPhone « Partager, puis Sur l'écran d'accueil » ; invitation discrète
  une seule fois, à la 3ᵉ ouverture, jamais sur la connexion ni pendant une vente, plus jamais une
  fois installée ou refusée.
- **L'administration n'est pas installable** : ni manifeste, ni worker (test).

### Le service worker (`app/sw.js/route.ts`, `lib/pwa/sw-source.ts`, sans bibliothèque)
- Servi à la racine, `Cache-Control: no-cache`, généré au build avec l'identifiant de build
  (`NEXT_DEPLOYMENT_ID` = étiquette de l'image) qui nomme le cache `coges-static-<build>`.
- **Garde seulement** : `/_next/static/*`, icônes, fichiers de marque, manifeste, `/hors-ligne`.
  **Jamais** : l'API, une page HTML de l'application, une réponse avec `Set-Cookie`, `no-store` ou
  `private`, une requête avec `Authorization`, un export, un reçu. Un e2e parcourt tout le Cache
  Storage après une session complète.
- Navigation sans réseau : `/hors-ligne`, statique, même ton que l'écran d'erreur (ADR 0085), avec
  « Réessayer » en simple lien (marche sans script). Les écritures échouent comme avant ; aucune file
  d'attente cachée ; les brouillons (ADR 0101) gardent la saisie.
- Anciens caches supprimés à l'activation ; **tout est vidé à la déconnexion** (message `LOGOUT`
  et `caches.delete` depuis la page).

### Mise à jour invisible (`lib/pwa/update.ts`, `lib/pwa/register.ts`)
- Le nouveau worker s'installe puis **attend** (pas de `skipWaiting` d'office). Il est activé, et la
  page rechargée, à un **moment sûr** : au lancement, au retour d'un arrière-plan de plus de
  5 minutes, à la navigation suivante par un lien, ou après 24 heures d'attente sur un même écran ;
  et seulement sans écriture en cours (`isMutating`), sans saisie non envoyée (`hasUnsentDrafts`) et
  hors des écrans de vente et de retour en cours. Recherche d'une version au retour au premier plan
  et toutes les 6 heures.
- **Compatibilité entre versions** :
  1. l'API reste compatible avec le front précédent au moins 14 jours (ajouter d'abord, retirer
     ensuite, ADR 0083). Le front envoie `X-CoGes-Front: <version>` ; sous
     `COGES_MIN_FRONT_VERSION` (vide par défaut, aucun refus ; sans en-tête ou illisible, accepté),
     l'API répond **426 `front_outdated`**, qui déclenche la mise à jour au moment sûr suivant ; si
     la version est encore refusée après ce rechargement, et seulement alors, une bannière « Une
     nouvelle version de CoGes est prête » avec « Recharger » ;
  2. **fichiers du build précédent gardés 14 jours** : `.next/static` du front est un volume
     (`front-static`, un par pile) ; au démarrage, `static-entrypoint.sh` y ajoute les fichiers de la
     nouvelle image sans rien écraser (noms à empreinte) et retire ceux de plus de 14 jours. Choisi
     plutôt que Caddy (pile `edge` partagée entre production et préproduction) ; Caddy ne change pas.
     `deploymentId` est posé : un écran resté sur l'ancienne version qui change d'écran est rechargé
     par Next sur la nouvelle, sa saisie gardée (ADR 0101) ;
  3. un fichier de l'application introuvable (`ChunkLoadError`) est rattrapé **une fois** par un
     rechargement propre au moment sûr, sans message technique.
- CSP : `worker-src 'self'`, `manifest-src 'self'`. `proxy.ts` laisse passer `/manifest.webmanifest`,
  `/sw.js` et `/hors-ligne` sans connexion ni redirection.

## Ce que l'application fait et ne fait pas hors ligne
- **Fait** : s'ouvre (si elle a déjà été ouverte une fois), affiche « Pas de connexion » et
  « Réessayer », garde la saisie commencée sur l'appareil.
- **Ne fait pas** : afficher des ventes, du stock ou de l'argent ; vendre ; mettre une écriture en
  attente pour plus tard. Tout cela exige le réseau.

## Procédure de purge
Voir `docs/runbooks/deploiement.md`, « Purge en cas de défaut de cache » : déployer une version (le
cache suit l'étiquette, l'ancien est supprimé à l'activation), au besoin avec
`COGES_MIN_FRONT_VERSION` pour forcer la mise à jour sur tous les appareils.

## Conséquences
- Tests : Vitest du manifeste (champs, icônes et tailles, couleurs = jetons), du gestionnaire de mise
  à jour (moments sûrs, 5 min, 24 h, 426 puis bannière, fichier manquant une fois), du `proxy.ts`, de
  la conservation des fichiers (`static-entrypoint.sh`), de l'administration sans PWA ; tests backend
  de la version minimale (11) ; e2e `make front-pwa-e2e` sur un build de production (manifeste et
  worker servis sans connexion, aucune donnée en cache après une session, page hors ligne puis
  retour, déconnexion = caches vidés, installation proposée puis retirée).
- Non automatisé : la bascule réelle entre deux builds sur un téléphone (deux builds successifs) ;
  elle est couverte par les tests du gestionnaire et par la vérification du propriétaire (prompt 29,
  « Ce que le propriétaire fait lui-même », point 3). Lighthouse n'a pas été rejoué pour ce lot.

## Corrections
- **2026-10-29, prompt 32, bloc B (ADR 0103)** : un onglet dont un autre a activé la version se
  recharge au moment sûr suivant (`controllerchange`) ; drapeaux posés au rechargement effectif ;
  bannière après 3 refus en 426 ou 2 minutes ; moment sûr revérifié juste avant de recharger ;
  fichier manquant rattrapé par `error.tsx` / `global-error.tsx` (il n'atteint jamais
  `window.onerror`), gestionnaire actif même sans service worker ; rechargement de Next lié à
  `deploymentId` vérifié : seulement à une navigation.
- **2026-10-29, prompt 32, bloc P (ADR 0103)** : les fichiers d'un ancien build partent 14 jours
  après qu'il a cessé d'être courant (témoin par build dans le volume), jamais au démarrage
  suivant ; le script ne fait plus échouer le démarrage. La déconnexion remet la page hors ligne,
  ses styles et ses polices en cache. L'image refuse de se construire sans `NEXT_DEPLOYMENT_ID`.
