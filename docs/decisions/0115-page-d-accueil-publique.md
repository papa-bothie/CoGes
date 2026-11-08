# 0115 — Page d'accueil publique : vitrine dans le front, montrée au seul visiteur nouveau

- **Date** : 2026-11-08
- **Phase** : prompt 37 (lot « Page d'accueil publique »)
- **Statut** : acceptée
- **Décideur** : utilisateur (prompt 37, puis AskUserQuestion du 2026-11-08 : numéro factice
  bloquant, illustrations unDraw, mise en page racine commune)

## Contexte

`coges.app` n'avait pas de page publique : `/` redirigeait vers `/dashboard`, et `proxy.ts`
envoyait tout visiteur sans session à la connexion. Le prompt 37 demande une vitrine, avec
une règle qui prime sur tout le reste : **rien ne change pour les personnes qui se
connectent déjà**. Cela vaut pour la redirection, l'écran de connexion et l'application
installée (`start_url` `/dashboard`, ADR 0102).

## Options envisagées

1. **Vitrine dans `frontend/`, à la racine, triée par `proxy.ts` (retenue)**. Aucun projet,
   conteneur, domaine ni pipeline de plus. Une seule origine (ADR 0047 et 0083), et la CSP
   reste la même.
2. Site statique à part (autre conteneur ou sous-domaine). Il faudrait un second
   déploiement et un second certificat, et l'adresse `coges.app` que les commerçants tapent
   changerait de rôle.
3. Mise en page racine séparée pour la vitrine, avec moins de JavaScript. L'utilisateur l'a
   écartée : elle déplaçait la racine de l'application, ce qui risquait de casser le
   principe « aucun changement ».

## Décision

### Arbre de décision de `proxy.ts`

| `coges_session=1` | `coges_known=1` | Route demandée | Résultat |
|---|---|---|---|
| oui | — | `/` | redirection vers `/dashboard` (comme avant) |
| non | oui | `/` | redirection vers `/login` (commerçant de retour, session expirée) |
| non | non | `/` | **la vitrine** (visiteur nouveau) |
| non | — | `/login` | la connexion |
| oui | — | `/login` | redirection vers `/dashboard` (comme avant) |
| non | — | `/dashboard`, toute route de l'application | redirection vers `/login` (`?next=` comme avant) |
| — | — | `/manifest.webmanifest`, `/sw.js`, `/hors-ligne`, `/support`, `/support/termine` | servis (comme avant) |
| — | — | `/robots.txt`, `/sitemap.xml`, `/vitrine/<fichier listé>` | servis |
| oui | — | toute route qui passe par le proxy | la réponse pose aussi `coges_known=1` |

Les routes publiques de la vitrine sont **nommées une à une**. Les fichiers de
`public/vitrine/` sont listés dans `content/vitrine-files.ts`, et un test vérifie que la
liste correspond exactement au dossier. `/vitrine/inconnu.webp` et `/vitrine` mènent donc à
la connexion. Le matcher exclut en plus `avif`, `jpg`, `jpeg`, `woff2` et `xml`, qui
partaient vers `/login`.

### Le marqueur `coges_known`

`coges_known=1` dit seulement : « quelqu'un s'est déjà connecté à CoGes sur cet appareil ».

- Durée : un an.
- `SameSite=Lax`, `Path=/`, `Secure` en https.
- Pas `HttpOnly`, parce que la connexion le pose depuis le navigateur.
- Aucun identifiant, aucun droit.

Il est posé à deux endroits :

- **par `proxy.ts`** sur toute réponse quand la requête porte `coges_session=1`. Les comptes
  déjà connectés avant ce lot le reçoivent donc à leur visite suivante, sans rien faire ;
- **à la connexion réussie** (`acceptTokens` dans `lib/auth/session.ts`).

La déconnexion **ne l'efface pas**. L'accès support (ADR 0092) le pose aussi sur le poste
de l'équipe, ce qui est sans effet.

**Pourquoi un commerçant de retour ne voit jamais la vitrine par surprise.** Sur un appareil
où il s'est déjà connecté, il garde le marqueur pendant un an, même après une déconnexion ou
l'expiration de sa session. `/` le mène alors à la connexion, comme avant. Seules deux
situations montrent la vitrine à quelqu'un qui a un compte : des cookies vidés, ou un
nouvel appareil. Pour ce cas, « Se connecter » est toujours visible en haut de la vitrine,
dès le premier écran et à toute largeur (vérifié en e2e à 360 px).

### La page

- `app/(vitrine)/page.tsx` est rendue statique au build (`○ /`) et remplace `app/page.tsx`.
- Composants serveur. Seul JavaScript propre à la vitrine : le menu du téléphone
  (`components/vitrine/mobile-menu.tsx`). Les questions fréquentes utilisent `<details>`.
- Textes dans `content/vitrine-texte.ts`. Le contenu du propriétaire est dans
  `content/vitrine.ts` : numéro WhatsApp, horaires, message prérempli, adresse du site,
  tarifs (`null`, donc pas de section « Tarifs »).
- Promesses tenues par test (`content/vitrine-texte.test.ts`) :
  - jamais « sans connexion » ni « hors ligne » ;
  - l'essai à 30 jours, comme le fixe l'ADR 0091 ;
  - aucun prix ;
  - ni « Créer ma boutique » ni lien vers des pages légales.
- Le numéro factice livré avec le lot (`221000000000`) fait échouer
  `content/vitrine.test.ts`, au choix de l'utilisateur : la PR ne peut pas être fusionnée
  avec un faux contact.
- Contact par lien `wa.me` (message encodé en `%20`), sans aucune requête de la page.
  Aucun formulaire, aucune statistique, aucun script tiers.
- La mise en page racine est commune (choix de l'utilisateur) : thème clair et sombre,
  React Query et l'enregistrement du service worker sont chargés comme ailleurs.

### Images et licences

Toutes les images sont hébergées dans `public/vitrine/`, dimensions déclarées, chargées en
différé sous le pli.

| Fichier | Origine | Licence |
|---|---|---|
| `illustration-boutique.svg` (`groceries_4via`) | unDraw, accent recoloré au vert CoGes | [licence unDraw](https://undraw.co/license) : usage commercial libre, sans attribution ni coût ; interdits : en refaire une collection, les redistribuer en lots, les utiliser pour l'entraînement d'IA |
| `illustration-stock.svg` (`logistics_8vri`) | unDraw, recoloré | idem |
| `illustration-chiffres.svg` (`growth-analytics_vzjz`) | unDraw, recoloré | idem |
| `apercu-ordinateur.webp`, `apercu-telephone.webp` | captures de CoGes sur la démo `demo` (`e2e/captures-vitrine.spec.ts`, puis `scripts/vitrine-images.py`) | les nôtres ; aucune donnée réelle de commerçant |
| `partage.png` (1200 × 630) | composée par la même spec (police Figtree OFL, logo CoGes, capture de la démo) | la nôtre |

`illustration-paiement` a été écartée : elle affiche des « $ ».

Les illustrations sont posées sur un panneau `.papier`, qui reprend les jetons clairs comme
la facture A4 (ADR 0112) : elles gardent leurs couleurs en mode sombre.

### Service worker

Il n'a pas changé. Les navigations vont toujours au réseau, et `/vitrine/*` ne fait pas
partie des fichiers statiques gardés. Une nouvelle version de la vitrine paraît donc au
rechargement. Deux tests le vérifient : `lib/pwa/sw-source.test.ts` et `e2e/pwa.spec.ts`
(rien de `/` ni de `/vitrine/` dans Cache Storage, manifeste inchangé).

### Référencement

- `metadataBase` vient de `vitrine.siteUrl`. La mise en page racine dit `noindex, nofollow`,
  et seule la vitrine dit `index, follow`.
- Balises Open Graph et Twitter (`summary_large_image`) pointent vers `/vitrine/partage.png`.
- `robots.txt` : `Allow: /$`, `/vitrine/` et `/brand/`, puis `Disallow: /`. `sitemap.xml` ne
  liste que la racine.
- JSON-LD `Organization` et `SoftwareApplication` : nom, adresse, logo, contact WhatsApp. Ni
  prix ni note.
- Caddy :
  - `preprod.` répond `X-Robots-Tag: noindex, nofollow` ;
  - `www.{$COGES_DOMAIN}` redirige en 301 vers le domaine nu (`{uri}` gardé) ;
  - les blocs de l'administration ne changent pas, et gardent leur propre `noindex`.

## Conséquences

Tests ajoutés :

- `proxy.test.ts` : tableau complet session / marqueur / route, cookie posé, matcher, liste
  fermée des fichiers.
- `lib/auth/session.test.ts` : le marqueur survit à la fin de session.
- `e2e/vitrine.spec.ts` (14 parcours) :
  - aucune requête vers `/api` ni vers l'extérieur ;
  - CSP inchangée ;
  - session et marqueur ;
  - axe AA en clair et en sombre ;
  - 360 px ;
  - clavier.
- `e2e/pwa.spec.ts` : application installée inchangée.
- `make lighthouse` mesure aussi la vitrine (100 sur ordinateur et à 390 px).
- `test_vps_configuration.py` : redirection `www`, `noindex` de la préproduction.

Poids mesuré sur le build de production, transfert compressé :

- 446 Ko pour le premier écran sur téléphone ;
- 557 Ko pour la page entière (images 139 Ko, polices 52 Ko, CSS 20 Ko).

Le JavaScript partagé avec l'application (324 Ko) en est la plus grosse part. C'est le prix
de la mise en page commune, déjà en cache pour les commerçants.

Ce que le lot ne fait pas, et qui revient au propriétaire :

- remplacer le numéro WhatsApp, les horaires et le message de `content/vitrine.ts` ;
- poser le DNS de `www` ;
- mentionner `coges_known` dans la politique de confidentialité.

Les liens « Conditions » et « Confidentialité » viendront avec le lot Pages légales,
« Créer ma boutique » avec le lot Inscription.

Pour refaire les images après un changement d'écran :

```bash
make e2e-reset
VITRINE_CAPTURES=<dossier> pnpm --dir frontend exec playwright test captures-vitrine
uv run --directory backend python ../frontend/scripts/vitrine-images.py <dossier>
```
