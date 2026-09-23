# Phase 10 — Import/export, durcissement, déploiement du backend

---

Tu es l'agent de développement du projet **CoGes**. Nous démarrons la **phase 10 : mise en état
de production du backend**. Aucune nouvelle règle métier : on ajoute l'import/export prévu en V1,
on durcit la sécurité et l'observabilité, on déploie selon le Diagramme 2, et on rend la CI
bloquante sur les tests d'intégrité.

## 0. Protocole

1. Lis `CLAUDE.md` (phase 09 ✅ exigée) et tous les ADR.
2. Lis :
   - Architecture : Diagramme 2 (zones Vercel / Docker, règle d'affectation, contraintes acceptées) ;
     module Import/Export (≈340) ; Diagramme 8, étape 4 (pooling en mode transaction) ; tests de
     fuite ; performance ; décisions 02, 06, 07, 14, 16, 17 ; risques techniques (≈1217).
   - Modèle : § 9 (contrôles de migration) ; § 10 (T1–T40) ; § 12.1.
   - `docs/architecture/README.md` : point **P8** (paliers commerciaux).
3. Pose les questions du § 2 avec `AskUserQuestion` avant de coder. Pour les services payants,
   **ne choisis rien à ma place**.
4. Plan → feu vert → exécution → vérification → clôture.

## 1. Objectif

Un backend déployé en préproduction, qui passe T1–T40 en CI, dont les déploiements sont bloqués
par la moindre fuite inter-tenant, observable, et capable d'importer un catalogue et des
clients au démarrage d'une entreprise.

## 2. Questions à me poser (AskUserQuestion)

1. **PostgreSQL managé** (doit offrir PostgreSQL 16, PITR, un pooler en **mode transaction**, et
   le rôle `coges_app` sans BYPASSRLS) : Neon / Supabase / autre (me demander lequel). Rappelle
   que psycopg 3 derrière un pooler en mode transaction exige de désactiver les requêtes préparées
   côté serveur (`prepare_threshold=None`).
2. **Redis managé** : Upstash / Redis Cloud / conteneur sur l'hôte des workers.
3. **Hôte des conteneurs Docker** (workers, beat, relais, ML) : Railway / Fly.io / VPS avec docker
   compose / autre.
4. **API sur Vercel** (Diagramme 2) : fonction Python Vercel avec `vercel.json` (Recommandé :
   conforme à l'architecture ; vérifie ensemble les limites de durée et de taille) / API dans un
   conteneur si les limites posent problème (écart à documenter).
5. **Import** : CSV **et** Excel (`.xlsx`) pour produits (avec prix et stock initial), catégories,
   clients et fournisseurs, avec validation complète **avant** écriture et rapport d'erreurs ligne
   par ligne (Recommandé) / CSV seulement. Import des ventes historiques : non en V1 (Recommandé) / oui.
6. **Limitation de débit** : par IP et par tenant, stockée dans Redis (Recommandé) / par IP
   seulement.
7. **Observabilité** : logs JSON + OpenTelemetry (traces) vers un fournisseur à choisir (me
   demander lequel) / Sentry pour les erreurs + logs JSON (Recommandé pour démarrer) / logs seuls.
8. **Paliers commerciaux (P8)** : aucune limitation par palier dans le code V1 (Recommandé : non
   prévu par l'architecture) / préparer une table de plan et des limites (écart à documenter).

## 3. Périmètre

**Import / export (`modules/importexport/`)**
- Téléversement → validation → aperçu des erreurs → confirmation → import dans **une**
  transaction par fichier (tout ou rien) ; le stock initial passe par des mouvements `initial`
  (façade Inventory) et les prix par `product_prices` (façade Products).
- Export CSV/Excel des référentiels et des ventes d'une période ; un export volumineux est une tâche
  worker (`exports.py`) dont le fichier est mis à disposition à la fin ; l'export est tracé en
  audit secondaire.

**Sécurité**
- Rate limiting (réponse 6) ; en-têtes de sécurité ; CORS limité au domaine du frontend ; taille
  maximale des requêtes et des fichiers ; revue des schémas Pydantic (`extra = forbid`, bornes) ;
  vérification que `Idempotency-Key` est exigé sur **toutes** les écritures financières.
- Revue des secrets : aucun dans le dépôt, rotation documentée de la clé JWT.

**Déploiement**
- `vercel.json` et point d'entrée `backend/app/main.py` ; `Dockerfile.worker` ;
  `deploy/docker-compose.worker.yml` ; `deploy/README-infra.md` (base, cache, scheduler, rôles SQL,
  sauvegardes, **procédure de restauration testée**).
- Migrations exécutées comme **étape de déploiement** (job CI), jamais au démarrage.
- Environnements : `preview` (par branche) et `production`, avec des secrets distincts.

**CI bloquante**
- Jobs : lint, mypy, tests unitaires, tests d'intégrité **T1–T40**, tests de fuite
  (`tests/tenancy/`), tests d'architecture, `alembic upgrade head` → `downgrade -1` → `upgrade head`.
- Échec d'un test de fuite ⇒ déploiement impossible.
- Export de l'OpenAPI (`openapi.json`) versionné, et un test qui échoue si le contrat change sans
  mise à jour du fichier : c'est la source des types du frontend.

**Tests supplémentaires**
- Import : fichier avec erreurs ⇒ rien n'est écrit ; SKU en double ; import dans A invisible de B.
- Rate limiting : dépassement ⇒ 429.
- Test de fumée post-déploiement : health, login, lecture du tableau de bord.

## 4. Règles à respecter

- Le Diagramme 2 décide de la zone : tout ce qui est long, planifié ou persistant va dans Docker.
- Aucun service payant n'est provisionné sans mon accord explicite.

## 5. Vérification

Préproduction en ligne ; montre la CI verte (T1–T40 listés), le test de fumée, et un import de
20 produits avec une erreur volontaire corrigée.

## 6. Clôture

ADR (hébergeurs, pooler, observabilité, import) ; `CLAUDE.md` mis à jour, avec la phase 10 ✅ et
un encadré « **Backend V1 terminé** » qui liste les endpoints et l'URL de l'OpenAPI ; résumé.
