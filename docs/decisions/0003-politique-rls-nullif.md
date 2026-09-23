# 0003 — Politique RLS : `NULLIF` sur le contexte, et `RESET ALL` au retour au pool

- **Date** : 2026-09-23
- **Phase** : 01
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`), sur un défaut démontré dans le § 8.11

## Contexte

Le § 8.11 du Modèle de données écrit la politique type ainsi :

```sql
USING (company_id = current_setting('app.company_id', true)::uuid)
```

Vérification faite sur PostgreSQL 16, avec le rôle `coges_app` :

```
BEGIN; SELECT set_config('app.company_id', '…', true); COMMIT;
SELECT current_setting('app.company_id', true);   -->  '' (chaîne vide, PAS NULL)
SELECT ''::uuid;                                  -->  ERROR: invalid input syntax for type uuid
```

Un paramètre personnalisé **ne revient jamais à NULL** une fois posé : il revient à la chaîne
vide, et `DISCARD ALL` ne change rien. Sur une connexion poolée ayant déjà servi une
transaction, la politique du § 8.11 **lèverait une erreur** au lieu de renvoyer un jeu vide.
Or le test **T3** du § 10 exige « 0 ligne, **jamais d'erreur** ni de fuite ».

Second constat, découvert en exécutant la suite : le `DISCARD ALL` recommandé par le
Diagramme 8 exécute un `DEALLOCATE ALL`, alors que psycopg 3 continue de croire ses requêtes
préparées vivantes. La requête suivante échoue avec
`prepared statement "_pg3_0" does not exist`.

## Options envisagées

1. **Corriger la politique avec `NULLIF` (retenue)** : l'absence de contexte redevient un jeu
   vide, sur toutes les tables et pour toutes les phases.
2. Copier le § 8.11 à l'identique : l'échec reste sûr (aucune fuite), mais en erreur PostgreSQL
   brute, et T3 devrait attendre une exception, contre la lettre du § 10.
3. Forcer un `RESET` au checkin pour ramener la variable à NULL : **vérifié impossible**, la
   chaîne vide persiste.

## Décision

Toutes les politiques RLS du projet comparent :

```sql
company_id = NULLIF(current_setting('app.company_id', true), '')::uuid
```

et `companies_self` fait de même sur `id`.

La réinitialisation au retour de la connexion dans le pool utilise **`RESET ALL`** et non
`DISCARD ALL`. Le Diagramme 8 laisse explicitement ce choix (« `DISCARD ALL` (ou
`RESET app.company_id`) »). `RESET ALL` neutralise **tous** les paramètres de session — y
compris un `app.company_id` qu'un `SET` sans `LOCAL` aurait laissé — sans casser le cache de
requêtes préparées de psycopg 3. Vérifié : après `RESET ALL`, `NULLIF(...)::uuid IS NULL` est
vrai et les requêtes préparées restent exécutables.

## Conséquences

- Toute phase future copie cette forme de politique : `NULLIF` fait partie du gabarit.
- L'oubli de contexte produit un **jeu vide**, jamais une erreur 500 : T3 et T4 le prouvent.
- Deux barrières indépendantes contre un `SET` de session : `RESET ALL` au checkin le
  neutralise, et le `NULLIF` rend la valeur résiduelle inopérante.
- Écart documenté par rapport au § 8.11, à reporter si le PDF est un jour corrigé.
