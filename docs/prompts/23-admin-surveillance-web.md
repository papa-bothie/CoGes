# Prompt 23 — Lot admin 2 : surveillance système en version web

Branche `feat/admin-monitoring-ui`, depuis `main` à jour, après le lot admin 1 (prompt 22). Reprend ce qui existe déjà (`GET /system/workers`, `job_runs`, `make ops-status`) et l'habille en interface web dans `frontend-admin/`, derrière les comptes plateforme du prompt 22 plutôt que le seul jeton statique.

```
Lot admin 2 — Surveillance système en version web (branche feat/admin-monitoring-ui, depuis
main à jour, après le prompt 22). Règles habituelles : ADR aux prochains numéros libres, tests
d'abord, aucun service payant, ne jamais ouvrir ni commiter .env, deploy/.env.preprod ni
backend/.vercel/. Résumé en français à la fin, questions ouvertes par AskUserQuestion.

Rien de nouveau à construire côté données : /api/v1/system/workers, job_runs et make ops-status
existent déjà (prompt 17). Ce lot les rend accessibles depuis l'interface plateforme et y ajoute
ce qui manque pour qu'un humain, pas seulement un script, puisse comprendre l'état du système.

1. Authentification de /api/v1/system/workers
   - Accepte DEUX façons de s'authentifier désormais : le jeton COGES_OPS_TOKEN existant
     (inchangé, pour make ops-status et un futur monitoring externe), OU un jeton platform_users
     valide (prompt 22). Les deux donnent exactement la même réponse — ne duplique pas la
     logique, un seul chemin de lecture, deux portes d'entrée. Teste les deux.

2. Historique, pas seulement l'instant présent
   - GET /api/v1/platform/system/job-runs (paginé, filtrable par job et par statut) : expose
     job_runs sur une fenêtre glissante (90 jours, cohérent avec la purge existante), pour voir
     les tendances (une tâche qui échoue de plus en plus souvent) et pas seulement le dernier
     passage.
   - GET /api/v1/platform/system/outbox : âge du plus ancien événement en attente, nombre
     d'événements mis au rebut (outbox_dead_lettered, prompt 21/P1.1) avec le détail minimal
     utile pour rejouer (identifiant, type, date, nombre de tentatives — jamais le contenu de
     l'événement, qui peut porter des données commerciales).

3. Interface web (frontend-admin/)
   - Écran « Système » : les mêmes informations que make ops-status, lisibles (pastilles vertes/
     rouges par composant, âge du dernier battement, longueur de la file, statut de chaque
     tâche de beat.py), rafraîchi automatiquement (interrogation toutes les 30 s, pas de
     WebSocket pour ce lot).
   - Historique des tâches (section 2) : tableau trié par date, filtre par statut, un clic sur
     une ligne en échec affiche le message d'erreur court déjà stocké.
   - Rien de tout ça ne doit jamais afficher ni company_id ni nom d'entreprise au-delà de ce que
     job_runs porte déjà (qui est nullable et déjà pensé pour ne pas identifier une entreprise à
     qui que ce soit d'extérieur à la plateforme).

4. Alerte visuelle dans l'interface elle-même
   - Si /system/workers répond 503, bandeau rouge permanent en haut de TOUT l'écran
     d'administration (pas seulement l'écran Système), avec le motif exact du 503. Objectif :
     impossible de manquer un système en panne en travaillant sur un autre écran de
     l'administration.

5. Tests
   - Les deux voies d'authentification de la section 1 donnent la même réponse, octet pour
     octet, pour le même état du système.
   - job-runs et outbox : isolation déjà couverte par le rôle de lecture du prompt 22
     (vérifie que ces deux nouvelles routes sont bien classées dans le registre de rôle créé à
     ce lot) ; pas de donnée commerciale dans aucune des deux réponses (test qui cherche des
     montants ou des noms de client dans le JSON, comme au lot C).
   - Bandeau de panne : simulé par un battement manquant en test e2e, vérifie qu'il apparaît sur
     n'importe quel écran de l'administration, pas seulement Système.

Fin du lot : suite backend complète, make front-check sur frontend-admin/, e2e des deux écrans.
Met à jour docs/runbooks/workers.md si la nouvelle vue change la procédure d'intervention
recommandée (probablement : regarder l'écran web d'abord, le terminal ensuite).
```
