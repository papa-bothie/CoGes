# 0041 — Import et export des référentiels et des ventes

- **Date** : 2026-09-26
- **Phase** : 10 (temps B)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
L'architecture prévoit un module Import/Export V1 : « CSV/Excel du référentiel et des
ventes, uniquement si nécessaire au démarrage. Export volumineux en worker. » Deux trous :
l'API Vercel est sans état (où garder un fichier entre l'aperçu et la confirmation ?), et
le worker n'appelle jamais l'API (`B⇸A`) : où déposer un export produit par lui ?

## Options envisagées
1. **Formats** : **CSV + .xlsx (retenu, openpyxl + defusedxml)** ; CSV seul.
2. **Ventes historiques** : **non importées en V1 (retenu)** — une confirmation antidatée
   se heurterait à la fenêtre de 48 h (ADR 0015) et au CMP.
3. **Aperçu → confirmation** : **renvoyer le même fichier (retenu)**, `?dry_run=true` pour
   l'aperçu ; une table `import_jobs` en attente — une table et une purge de plus.
4. **Fichier d'export** : **table `export_files` + TTL (retenu)** ; stockage objet (R2/S3),
   un service de plus ; exports synchrones seulement, contraire à l'architecture.

## Décision
- `modules/importexport/`, en bande E : il écrit **uniquement** par les façades
  (`create_category`, `create_product` avec son premier prix, `record_movement` de type
  `initial`, `create_customer`, `create_supplier`) et lit les ventes par `list_sales`.
- **Tout ou rien, rapport complet.** Un `SAVEPOINT` par fichier, un par ligne : une ligne
  refusée (schéma du module, doublon dans le fichier ou en base, trigger) est annulée seule
  et rapportée, et l'import continue pour tout rapporter. À la fin, en simulation ou s'il
  existe une erreur, le savepoint de fichier est annulé : **rien** n'est écrit, ni
  référentiel, ni audit, ni événement. La simulation suit donc exactement le chemin réel.
- `POST /imports/{categories|products|customers|suppliers}` : multipart, 5 000 lignes et
  4 Mo au plus, 422 `import_invalid` avec le rapport ligne par ligne. `Idempotency-Key`
  exigée (le stock initial est une écriture valorisée) ; l'empreinte porte le type et le
  SHA-256 du fichier ; seule l'importation réelle enregistre la clé.
- Colonnes en français, comparées sans casse ni accents ni petits mots ; nombres
  `1 234,50` acceptés. L'export d'un référentiel produit ces mêmes colonnes, et un fichier
  exporté se réimporte tel quel (`docs/guides/import-formats.md`).
- **Exports** : les référentiels sont servis dans la requête, jusqu'à 10 000 lignes (409
  `export_too_large` au-delà). Les ventes d'une période (un an au plus) passent par le
  worker : `POST /exports/sales` répond 202, la tâche `exports.build_sales` écrit
  `export_files.content`, et l'API sert le fichier par `GET /exports/{id}/file`.
- **Table `export_files`** (révision 0013, écart au § 8 assumé) : RLS FORCE, FK composite
  vers `users`, `content` plafonné à 10 Mo, 24 h de vie. La purge nocturne ne supprime
  rien : elle vide `content` et passe `status` à `expired` (`coges_app` n'a toujours pas
  DELETE ; T36 est inchangé).
- **Enfilement depuis l'API** (`app/core/queue.py`) : la tâche est désignée par son nom
  (`send_task`), sans importer `app.workers` — c'est la flèche « API → Redis pour
  l'enfilement » du Diagramme 2. Il est réservé aux demandes explicites d'un utilisateur ;
  un fait métier passe toujours par l'outbox. Si Redis est en panne, la demande reste
  `pending`, et le balayage nocturne la renfile. Le worker réessaie s'il ne voit pas encore
  la ligne (enfilement avant le COMMIT de la requête).
- **Audit secondaire** de chaque export : dans la transaction du worker pour les ventes,
  par la tâche `audit.record` pour un référentiel ou un téléchargement.
- Permissions du catalogue existant : `importexport:create` (gérant) pour importer,
  `importexport:export` (gérant, comptable) pour exporter.

## Conséquences
- Nouvelles dépendances : `openpyxl`, `defusedxml` (XML sûr), `python-multipart`.
- Un import de 5 000 produits avec stock tient dans la durée d'une fonction Vercel
  (300 s) ; au-delà, le gérant découpe le fichier.
- La base gratuite de Neon (0,5 Go) borne les exports : 10 Mo par fichier, 24 h.
- Les routes `/imports/{kind}` et `/exports/referentials/{kind}` n'ont pas de ressource à
  croiser : leur isolation est prouvée par `tests/tenancy/test_importexport_isolation.py`,
  et `/exports/{export_id}` entre dans le test générique de fuite.
