# Prompt 37 — Page d'accueil publique (landing page), visible seulement des nouveaux visiteurs

> **STATUT : PRÊT À LANCER** (8 novembre 2026). Premier lot de l'ordre décidé le 7 novembre : **page d'accueil → pages légales → inscription → paiement en ligne**.

Branche `feat/landing-page`, depuis `main` à jour.

## Décisions déjà prises

- La vitrine vit **dans le front existant** (`frontend/`), à la racine de `coges.app` : aucun nouveau projet, conteneur, domaine ni pipeline. `www.coges.app` redirigera vers `coges.app` (DNS et Caddy, voir « Ce que le propriétaire fait »).
- **Les personnes qui se connectent déjà ne voient aucun changement** : même redirection, même écran de connexion, même application installée sur le téléphone. La vitrine n'est affichée qu'aux visiteurs nouveaux.
- Pas de formulaire, pas de statistiques, pas de script tiers : la page ne collecte aucune donnée.
- Contact principal : **WhatsApp** (beaucoup de commerçants n'ont pas d'e-mail). « Créer ma boutique » viendra avec le lot Inscription.

## Avant de lancer (propriétaire)

1. Créer `frontend/content/vitrine.ts` avec : numéro WhatsApp du support (format international, sans espaces), horaires, message WhatsApp prérempli.
2. Décider si une section « Tarifs » est affichée. Par défaut : **non**, tant que les prix ne sont pas arrêtés et identiques aux CGV.
3. Fournir (ou laisser l'agent générer sur `make seed-demo`) les captures d'écran. Jamais de données réelles de commerçant.

## Prompt à donner à l'agent

```
Lot « Page d'accueil publique » (branche feat/landing-page, depuis main à jour).
Règles habituelles : ADR au prochain numéro libre, tests d'abord (rouge puis vert), aucun
service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod, backend/.vercel/
ni /etc/coges/*. Résumé en français à la fin, questions ouvertes par AskUserQuestion.

Avant tout code : lis frontend/AGENTS.md et le guide concerné dans
node_modules/next/dist/docs/ (cette version de Next 16.4.2 diffère de ce que tu connais),
puis les ADR 0047 et 0083 (une seule origine), 0102 (application installable, service
worker), docs/design/DESIGN.md et la maquette v2 (tokens, thème), l'ADR 0091 (essai).
Si frontend/content/vitrine.ts manque ou contient un numéro WhatsApp vide ou factice,
ARRÊTE-TOI et dis-le moi.

Principe non négociable : AUCUN changement pour les personnes qui se connectent déjà.
- Avec session (cookie coges_session=1) : comportement actuel, / mène à /dashboard.
- Application installée sur le téléphone : start_url /dashboard inchangé, manifeste, scope
  et service worker inchangés dans leur comportement.
- /login, /dashboard et toutes les routes de l'application : même comportement qu'avant.
- La vitrine n'est affichée qu'à un visiteur NOUVEAU : sans session ET jamais connecté
  sur cet appareil.

L1. Distinguer nouveau visiteur et commerçant de retour (proxy.ts)
- Sans session, un commerçant dont la session a expiré, ou qui tape coges.app comme
  d'habitude, doit continuer à arriver sur la connexion, pas sur la vitrine.
- Pose un marqueur « déjà connu » (cookie coges_known=1, non sensible, SameSite=Lax,
  durée 1 an, aucun identifiant) : par proxy.ts dès qu'une requête porte coges_session=1,
  et à la connexion réussie. Les comptes déjà connectés l'obtiennent donc à leur prochaine
  visite avec session, sans action de leur part.
- Route / : session OU coges_known -> comportement actuel (dashboard, ou /login si la
  session a expiré). Ni session ni coges_known -> vitrine.
- Toutes les autres routes gardent leur règle actuelle (sans session -> /login).
  Les routes publiques ajoutées par ce lot (vitrine, sitemap.xml, robots.txt, images de la
  vitrine, polices) sont listées explicitement, jamais par un motif large.
- Corrige le matcher : aujourd'hui seuls png, svg, ico, webp et txt sont exceptés ; les
  fichiers de la vitrine (xml, jpg, avif, woff2…) ne doivent pas partir vers /login.
- L'ADR documente l'arbre de décision (tableau : session / coges_known / route -> résultat)
  et explique pourquoi un commerçant de retour ne voit jamais la vitrine par surprise.
  Attention : une personne qui vide ses cookies ou change d'appareil verra la vitrine ; le
  bouton « Se connecter » doit donc être toujours visible, en haut, dès le premier écran.

L2. Contenu (français simple, FCFA, ton direct ; chaque promesse doit être vraie)
- En-tête : logo, « Fonctionnalités », « Se connecter » (bouton visible, mène à /login),
  bouton WhatsApp.
- Hero : en une phrase, CoGes gère les ventes, le stock et l'argent de la boutique ;
  boutons « Écrire sur WhatsApp » (lien wa.me avec message prérempli, depuis vitrine.ts)
  et « Voir comment ça marche » (ancre). Pas de bouton « Créer ma boutique » (lot suivant).
- Problème / solution : trois ou quatre situations de boutique (qui me doit quoi, ce qui
  reste en stock, combien j'ai gagné aujourd'hui).
- Fonctionnalités : ventes et caisse, stock, argent et dettes, tableau de bord, scan de
  code-barres, utilisateurs et rôles (gérant, vendeur, comptable). Seulement ce qui existe.
- Aperçu : captures réelles de l'application sur la démo (make seed-demo), téléphone et
  ordinateur, cadre d'appareil simple, texte alternatif descriptif, lazy-loading sous le pli.
- Avantages : simple, utilisable sur téléphone, installable sur l'écran d'accueil.
  NE PAS promettre « fonctionne sans connexion » : le hors ligne actuel est partiel
  (page hors ligne, brouillon retrouvé).
- FAQ : 5 à 6 questions (prix -> « écrivez-nous » tant que non arrêtés ; données et
  sécurité sans rien promettre que les pages légales ne disent pas ; téléphone ; support
  WhatsApp et horaires).
- Section « Tarifs » : absente par défaut. Si vitrine.ts en fournit, elle doit reprendre
  mot pour mot les CGV ; sinon rien.
- Essai gratuit : mentionné seulement si l'ADR 0091 le fixe, avec sa durée réelle.
- Pied de page : contact WhatsApp, horaires. PAS de liens /conditions ni /confidentialite
  dans ce lot (les pages n'existent pas encore ; le lot « Pages légales » les ajoutera).
- Aucun formulaire de contact, aucune API, aucun appel réseau (connect-src 'self' reste).

L3. Technique
- Groupe de routes dédié (ex. app/(vitrine)/) dans frontend/, rendu STATIQUE au build,
  composants serveur par défaut ; JavaScript client réduit à ce qui est indispensable
  (menu mobile). Réutilise Tailwind 4, shadcn, lucide-react et les tokens du projet ;
  clair et sombre comme le reste.
- Pas de Framer Motion : animations discrètes avec tw-animate-css ou CSS, désactivées par
  prefers-reduced-motion.
- La CSP de next.config.ts ne s'assouplit pas : images, polices et illustrations sont
  auto-hébergées (public/vitrine/), SVG ou WebP/AVIF optimisés, dimensions déclarées (pas
  de décalage de mise en page). Aucune police, CDN ou script externe.
- Illustrations : unDraw ou dessin maison seulement ; Storyset gratuit exige une
  attribution, donc non retenu sauf si je le demande. Cite la licence de chaque fichier
  dans l'ADR.
- Le service worker ne met pas la vitrine en cache de façon à ce qu'une nouvelle version
  n'apparaisse pas ; vérifie et teste.
- Redirection www -> domaine nu : écrite et testée dans Caddyfile (rendu), sans toucher
  aux blocs de l'administration ni de la préprod.

L4. Référencement et partage
- lang fr, titre et description, balises Open Graph et Twitter avec une image de partage,
  sitemap.xml et robots.txt (la vitrine seule est indexable ; /login et l'application,
  non), données structurées minimales (Organization/SoftwareApplication) sans rien inventer.
- La préproduction est en noindex (en-tête X-Robots-Tag côté Caddy ou métadonnées), testé.

L5. Tests (rouge d'abord)
- proxy.test.ts : tableau complet session / coges_known / route (/, /login, /dashboard,
  /support, /hors-ligne, /manifest.webmanifest, /sw.js, /sitemap.xml, une image de
  vitrine) ; sans session et sans coges_known : / sert la vitrine, /dashboard renvoie à
  /login ; avec session : / -> /dashboard ; avec coges_known seul : / -> /login ;
  coges_known posé par proxy quand coges_session=1 ; aucun cookie d'identifiant.
- e2e (Playwright) : navigation privée -> vitrine, aucun appel à /api, bouton « Se
  connecter » -> /login ; contexte avec session -> /dashboard sans voir la vitrine ;
  contexte avec coges_known sans session -> /login ; application installée (start_url
  /dashboard) inchangée ; parcours de connexion existants intacts (suite e2e complète).
- axe : 0 violation ; 360 px sans défilement horizontal ; clavier seul ; contraste en clair
  et en sombre ; make lighthouse sur la vitrine, score accessibilité ≥ 95 ; page légère en
  3G (poids total de la page et images affichés dans le résumé).
- Aucune requête externe (test sur les ressources chargées) ; CSP inchangée (test).
- Rendu du Caddyfile : www redirigé, administration et préprod inchangées.

Fin de lot : make front-check, e2e des écrans touchés, suite backend inchangée verte,
shellcheck, CI verte, PR ouverte. ADR (arbre de décision de la racine, marqueur coges_known,
choix « vitrine dans le front », licences des illustrations), README du front, CLAUDE.md §8
et table des ADR à jour.
```

## Ce que le propriétaire fait ensuite

1. **DNS** (Cloudflare, « DNS only ») : ajouter `www` en CNAME vers `coges.app` ; Caddy redirige vers le domaine nu et obtient le certificat.
2. Tester sur la préproduction (quand elle est remise en état), en navigation privée **et** avec son propre compte déjà connecté : la vitrine ne doit apparaître que dans le premier cas.
3. Vérifier avec le conseil juridique que la politique de confidentialité mentionne le cookie fonctionnel `coges_known` (aucune donnée personnelle, un an).
4. Déployer hors des heures d'ouverture, puis surveiller Sentry et UptimeRobot le lendemain.
5. Les liens « Conditions » et « Confidentialité » du pied de page sont ajoutés par le lot Pages légales.
