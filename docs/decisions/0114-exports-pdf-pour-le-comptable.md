# 0114 — Exports PDF pour le comptable

- **Date** : 2026-11-04
- **Phase** : groupe 2, bloc X (prompt 35, branche `feat/group2-x-accountant-pdf`, empilée
  sur T)
- **Statut** : acceptée
- **Décideur** : propriétaire. Droits choisis via AskUserQuestion le 2026-11-04 : le stock
  passe par `analytics:export`, et la correspondance proposée pour les autres documents
  est validée telle quelle. Plan du bloc X validé le même jour.

## Contexte
Le propriétaire veut des documents prêts à remettre à un comptable, dans cet ordre :
ventes sur une période, journal de caisse, état du stock, dépenses par type, dettes. Le
moteur PDF existe depuis le bloc T (ADR 0113). Les chiffres doivent être **exactement**
ceux de l'écran correspondant.

## Options envisagées
1. **Lire chaque document par les façades de son écran (retenue)** : une seule règle par
   chiffre, et un test qui compare les deux sources.
2. Des requêtes propres aux exports : plus rapides à écrire, mais deux règles qui
   finiraient par diverger (compensations, annulations, bornes de jours).

## Décision
- **Cinq documents**, tous avec le même en-tête : logo, nom, adresse, NINEA, RC, titre,
  période, « Édité le … à … par … » (« Accès support CoGes » pour un jeton de support).
  Ils portent des totaux, « Page n/N » et le pied « Document généré par CoGes ».

  | Document | Règle (même façade que l'écran) | Génération |
  |---|---|---|
  | Ventes sur une période | ventes confirmées de la période (`list_sales`, bornes de jour de l'entreprise) ; n°, date, client, total, payé, reste, moyen ; totaux par jour (= `GET /sales/day-totals`), par moyen (encaissé à la vente ; le reste « réglé ensuite sur la dette »), sous-total, remises, TVA, retours, total net ; ventes annulées comptées à part | worker |
  | Journal de caisse | `cash_summary`, `daily_cash`, `cash_by_method` et les lignes de l'écran 21 (`journal_lines`, extrait pour servir aux deux) ; compensations, paiements annulés et annulations exclus des totaux, lignes annulées listées sans être comptées ; solde de début = tout ce qui est entré moins sorti avant la période | worker |
  | État du stock | `get_stock` et `stock_summary` (valeur au CMP) ; **à l'instant** : l'historique ne garde pas le CMP après chaque mouvement, une date passée demanderait de rejouer tout le journal | immédiat |
  | Dépenses par type | `totals_by_category` (écran 20) et `list_expenses` en détail | immédiat |
  | Dettes clients et fournisseurs | dettes ouvertes ou en partie payées (`open_debts`), regroupées par personne, ancienneté depuis la naissance de chaque dette (0-30, 31-60, 61-90, plus de 90 jours) ; totaux égaux aux cartes « On vous doit » et « Vous devez » de l'écran 17 | immédiat |

- **Droits** (sans droit nouveau) : le droit de lecture de l'écran **et** un droit
  d'export existant.
  - Ventes : `sales:read` + `sales:export`.
  - Caisse : `analytics:read` + `analytics:export`.
  - Stock : `inventory:read` + `analytics:export`.
  - Dépenses : `expenses:read` + `analytics:export`.
  - Dettes : `debts:read` + `analytics:export`.

  Ces droits sont posés par `require_permissions(*codes)` (`core/deps.py`). Ils figurent
  dans `reports.PDF_RIGHTS` côté serveur et dans `PDF_EXPORTS` de `lib/access.ts` côté
  front, et un test vérifie qu'ils sont identiques.
- **Période** : aujourd'hui, cette semaine (depuis lundi), ce mois (depuis le 1er), ou des
  dates choisies. 366 jours au plus : au-delà, ou dates inversées, la réponse est 422.
- **File d'exports** (révision 0037) :
  - `export_format` gagne `pdf` et `export_files.kind` admet `cash` ;
  - `POST /exports/pdf` prend `{kind: sales|cash, date_from, date_to}` avec
    `Idempotency-Key` ; il est plafonné à 3 exports en préparation par type ;
  - le PDF est produit par la tâche existante `exports.build_sales`, qui aiguille selon le
    format (nom gardé : les demandes enfilées et le balayage de nuit le connaissent) ;
  - plus de 20 000 lignes de caisse donne « Document trop volumineux : réduisez la
    période ».
- **Réglages → Fichiers** (écart à l'existant) : la liste, l'état et le téléchargement
  exigeaient `importexport:export`. Ils s'ouvrent désormais à qui porte un droit
  d'export, et chacun ne voit que ce que ses droits permettent :
  - les tableurs avec `importexport:export` ;
  - les PDF avec les droits de leur document.

  Un fichier d'un type non permis répond 404, comme celui d'une autre entreprise. Pour les
  rôles par défaut rien ne change, car la ligne « Exporter » de la grille donne les quatre
  droits ensemble. Tout fichier d'export est servi en `no-store`.
- **Exports immédiats** : `GET /analytics/stock/pdf`, `/analytics/expenses/pdf?from&to` et
  `/analytics/debts/pdf`, en `no-store`.
- **Journal** : chaque PDF est noté dans l'audit secondaire (`action = export`,
  `format = pdf`). L'Historique dit « X a préparé un document PDF ».
- **Code** :
  - `analytics/reports.py` assemble les chiffres par les façades, sans requête ;
  - `analytics/documents.py` met en page, en fonctions pures ;
  - finance gagne `paid_by_sales` et `open_debts` ;
  - montants « 87 500 F », « 0 F » et jamais « -0 F », dates `jj/mm/aa hh:mm` dans les
    colonnes étroites.
- **Front** :
  - bloc « Pour votre comptable » au pied des écrans L'argent (ventes et caisse), Caisse,
    Stock, Dépenses, Toutes les dettes et Réglages → Fichiers (à côté de l'export Excel) ;
  - chaque export est masqué sans ses deux droits ;
  - un document daté demande sa période ; un document long affiche « Le PDF est en
    préparation » avec le lien vers Fichiers ; un document court se télécharge tout de
    suite ;
  - la liste des fichiers nomme « Ventes de … · PDF », « Journal de caisse de … · PDF » et
    « … · Excel ».
- **e2e** : `deploy/scripts/e2e.sh system build-exports` produit les exports en attente
  comme le ferait le worker (les parcours tournent sans worker), sur `coges_e2e`
  seulement.

## Conséquences
- Tests :
  - backend : chaque PDF relu par pypdf ; chiffres comparés à l'écran (`day-totals`,
    `money`, `stock/summary`, `expenses-summary`, cartes des dettes) et à l'Excel des
    ventes ; période vide, solde de début reporté, bornes d'ancienneté 30/31, 60/61,
    90/91 ; plus de 366 jours ⇒ 422 ; droit de lecture ou d'export manquant ⇒ 403 ;
    fichier d'un type non permis ⇒ 404 ; autre entreprise ⇒ 404 et aucun texte de
    l'autre ; Historique ;
  - registres : `READ_ROUTES` (classe `PDF`, texte relu et comparé à B),
    `commit_failure_registry`, `KEYED` ;
  - Vitest : période, masquage, téléchargement immédiat, demande au worker avec clé,
    dates refusées, bloc filtré, registre égal au serveur ;
  - e2e : ventes du mois de bout en bout, stock immédiat, 360 px, axe.
- Un état du stock à une date passée reste à faire, si le propriétaire le demande : il
  faudrait rejouer le journal pour retrouver le CMP de l'époque.
