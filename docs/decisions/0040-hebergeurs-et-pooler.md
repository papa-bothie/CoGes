# 0040 — Hébergeurs, pooler et base qui s'endort

- **Date** : 2026-09-26
- **Phase** : 10 (temps B)
- **Statut** : acceptée
- **Décideur** : utilisateur (via AskUserQuestion)

## Contexte
Le Diagramme 2 place l'API sur Vercel, PostgreSQL et Redis chez des services managés, et
workers, beat, relais et ML dans des conteneurs Docker. Le choix des fournisseurs restait
ouvert, avec une contrainte : aucun service payant sans accord, et un budget gratuit au
démarrage. Le Diagramme 8 (étape 4) impose un pooler en **mode transaction**.

## Options envisagées
1. **PostgreSQL** : **Neon (retenu)** — PG 16, PgBouncer en mode transaction intégré, PITR ;
   Supabase — PITR payant, version à vérifier.
2. **Redis** : **Redis Cloud (retenu)** — instance fixe, compatible avec Celery qui sonde
   en continu ; Upstash — facturé à la commande, que ce sondage épuiserait ; conteneur
   local — il aurait fallu l'exposer sur internet pour Vercel.
3. **Zone B** : Vercel a d'abord été envisagé, mais il n'exécute ni conteneur ni processus
   permanent (relais, worker, beat). **Retenu pour la préproduction : le poste local**,
   avec `docker compose` ; l'hôte de production reste à choisir (VM Oracle Always Free,
   Railway, VPS…).
4. **API** : **fonction Python Vercel (retenu)**, conforme au Diagramme 2. Hobby en
   préproduction, **Pro en production** (l'offre Hobby exclut l'usage commercial).

## Décision
- **Neon** : préproduction sur l'offre gratuite (moins de 100 CU-heures par mois, veille
  après 5 min d'inactivité) ; production sur **Launch**, veille désactivée.
- **Relais économe en préproduction** : quand l'outbox est vide, l'attente double à
  chaque passage, de 1 s jusqu'à `COGES_OUTBOX_IDLE_MAX_SECONDS` (600 s en préproduction,
  1 s ailleurs). Elle revient à 1 s dès qu'un passage trouve un événement. Beat ne
  planifie que des tâches nocturnes, et le balayage des exports aussi.
- **Pooler** : `COGES_DB_POOLER=transaction` ⇒ `NullPool` (le pool est celui de Neon ;
  pas de pool local par instance Vercel) et `prepare_threshold=None` (psycopg 3 ne
  prépare plus de requêtes côté serveur, qui ne survivraient pas au changement de
  connexion physique). Migrations sur l'hôte **direct** de Neon, jamais sur le pooler.
- **Vercel** : `backend/api/index.py` expose `app.main:app` ; `vercel.json` réécrit toutes
  les URL vers lui (`maxDuration` 300 s, région `cdg1`). Les dépendances viennent de
  `backend/requirements.txt`, généré sans `dev` ni `ml` (≈ 94 Mo, sous la limite de
  250 Mo) et vérifié en CI. Les déploiements automatiques depuis Git sont désactivés : seul
  le workflow `Déploiement`, derrière la CI complète, déploie.

## Conséquences
- En préproduction, après une période calme, le premier événement peut attendre jusqu'à
  10 min avant d'atteindre agrégats et alertes. Le cache du tableau de bord (60 s) et les
  écritures métier ne sont pas touchés : la vente reste synchrone.
- Machine locale éteinte : événements et exports attendent, rien ne se perd (T40).
- Le passage en production demande trois ouvertures payantes (Neon Launch, Vercel Pro,
  hôte de la zone B), à valider le moment venu.
- À vérifier au provisionnement : Neon doit accepter la création des rôles `NOLOGIN
  BYPASSRLS` (`coges_auth`, `coges_bus`), et Vercel doit installer depuis
  `requirements.txt` plutôt que depuis `uv.lock` (qui inclurait les groupes `dev` et `ml`).
