# 0111 — Logo de l'entreprise, et moteur PDF du groupe 2

- **Date** : 2026-11-04
- **Phase** : groupe 2, bloc L (prompt 35, branche `feat/group2-l-company-logo`)
- **Statut** : acceptée
- **Décideur** : propriétaire (Q0 via AskUserQuestion le 2026-11-04 : **ReportLab côté
  serveur**) ; le stockage et les détails ci-dessous sont présentés dans le plan du bloc L
  et validés le même jour

## Contexte
Le propriétaire veut le logo de la boutique sur le ticket et la facture (bloc F), puis
dans les PDF (blocs T et X). Jusqu'ici la facture montrait les initiales de la boutique et
CoGes ne stockait aucune image (ADR 0066 : pas de photo en V1). Le prompt impose une image
vérifiée côté serveur, SVG refusé, stockée dans PostgreSQL (pour la sauvegarde chiffrée de
l'ADR 0084), jamais sur le disque du VPS ni chez un tiers.

## Options envisagées
**Moteur PDF (Q0, pour les blocs T et X)**
1. **ReportLab côté serveur (retenue)** : licence BSD, roues Python sans dépendance
   système (l'image `slim` ne change presque pas), polices TTF embarquées, mise en page
   Platypus (tableaux, pagination). Même rendu partout, y compris sur un téléphone qui
   n'imprime pas.
2. WeasyPrint : HTML et CSS, mais Pango, HarfBuzz et fontconfig par apt (+60 à 80 Mo),
   plus de surface pour les analyses de sécurité.
3. PDF dans le navigateur : rendu variable, chiffres calculés en deux endroits ; écarté
   par le prompt.

**Stockage du logo**
1. **Table `company_logos` (retenue)** : une ligne par entreprise, RLS FORCE, politique
   tenant. Elle est couverte d'office par T37, l'échec au COMMIT (tables découvertes, ADR
   0086) et la sauvegarde (`coges_backup` lit toute table par ses privilèges par défaut).
2. Colonne `bytea` sur `companies` : `companies` est relue à presque chaque requête et lue
   colonne par colonne par `coges_app_platform` (ADR 0089). L'image alourdirait chaque
   lecture, ou demanderait un chargement différé facile à oublier.

## Décision
- **Révision 0036** : `company_logos (company_id PK, png bytea, sha256, width, height,
  byte_size, updated_by, created_at, updated_at)`. FK composite `(company_id, updated_by)`
  vers `users`. Contrôles en base : tout ou rien, signature PNG, 512 px, 256 Ko au plus,
  `byte_size = octet_length(png)`. `coges_analytics` n'y a aucun droit.
- **« Retirer » sans DELETE** (`coges_app` n'en a pas) : `png` et ses colonnes reviennent à
  `NULL`. L'image disparaît vraiment, et des sauvegardes suivantes aussi. La ligne reste.
- **Traitement** (`companies/logo.py`, **Pillow 13.0.0** figé) :
  - type lu dans le contenu (PNG, JPEG, WebP seulement ; SVG, GIF et le reste refusés) ;
  - 2 Mo au plus avant décodage, 40 Mpx au plus (bombe de décompression refusée) ;
  - orientation EXIF appliquée, puis copie des seuls pixels ré-encodée en PNG, ce qui
    retire toutes les métadonnées (GPS compris) ;
  - réduction à 512 px de côté. Si le PNG dépasse 200 Ko (photo bruitée), passage en
    palette de 256 couleurs puis réduction par paliers. Un logo réel pèse quelques dizaines
    de Ko.
- **Routes** (module `companies`) :
  - `PUT /companies/me/logo` (multipart, `company:update`) rend `width`, `height` et
    `updated_at` ;
  - `DELETE /companies/me/logo` (`company:update`) rend 204, ou 404 `logo_not_found` ;
  - `GET /companies/me/logo` rend `image/png` avec `Cache-Control: no-store` et `nosniff`.
    Il est **ouvert à tout utilisateur connecté de l'entreprise** : le vendeur imprime des
    reçus qui le portent, et l'accès support le lit (aucune écriture, ADR 0092).
  - `CompanyRead.logo_updated_at` (nul sans logo) dit au front s'il doit lire l'image et
    quand la relire.
- **Refus** : 413 `logo_too_large` « Image trop lourde (2 Mo au plus). » ; 422
  `logo_unsupported_format` « Format non pris en charge : PNG, JPEG ou WebP. ». Le
  middleware de taille accepte 2 Mo + 64 Ko sur cette seule route (1 Mo ailleurs).
- **Concurrence** : la ligne est créée vide au besoin (`ON CONFLICT DO NOTHING`) puis
  verrouillée `FOR UPDATE`. Deux envois simultanés se suivent au lieu de se heurter.
- **Audit critique** dans la transaction : `insert` (ajout), `update` (changement),
  `delete` (retrait) sur `company_logos`. Le `diff` contient l'empreinte, les dimensions et
  le poids, jamais les octets. L'Historique dit « X a ajouté / changé / retiré le logo ».
- **Front** :
  - bloc « Logo de la boutique » en tête de Réglages → Boutique : aperçu, « Ajouter le
    logo », « Changer », « Retirer » pour le gérant, aperçu seul pour les autres ;
  - contrôle de type et de poids avant l'envoi (le serveur revérifie) ;
  - `useCompanyLogo(version)` lit l'image en blob avec le jeton dans l'en-tête, puis la
    rend en adresse `data:` (rien à libérer, utilisable à l'impression par le bloc F) ;
  - le service worker ne garde que `/_next/static` (ADR 0102), ce qu'un test vérifie.

## Conséquences
- Tests :
  - unitaires : type par le contenu, SVG, GIF/BMP/TIFF, fichier tronqué, GPS retiré,
    orientation, 512 px, poids, bombe, vide ;
  - intégration : ajout, changement, retrait et relecture ; 3 audits sans octets ;
    vendeur lecteur non écrivain ; 413 du service et du middleware ; refus de la RLS
    sous un autre contexte ; support en lecture seule ; Historique ;
  - registres : `READ_ROUTES` gagne la classe `IMAGE` (lecture binaire, octets de A et
    B comparés), `commit_failure_registry` classe `PUT` et `DELETE` en écritures
    critiques ;
  - Vitest (bloc logo, service worker) et e2e (ajouter, changer, retirer, SVG refusé,
    axe clair et sombre, 360 px).
- ReportLab arrive avec le bloc T, première génération de PDF. Le bloc F refait la
  facture et le ticket imprimés par le navigateur avec ce logo.
- Pas d'autre image en V1 (photo d'article toujours hors périmètre, ADR 0066).
