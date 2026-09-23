# 0008 — Audit partitionné, outbox et durcissement des journaux

- **Date** : 2026-09-23
- **Phase** : 02
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

`audit_logs` est partitionnée par mois (§ 8.8). Trois points que les documents ne tranchent pas
apparaissent dès qu'on l'implémente.

## Décision

**1. Partitions — fonction, deux mois d'avance, et une partition `DEFAULT`.**
`ensure_audit_partition(date)` crée la partition, y pose la RLS forcée et sa politique, y
accorde `SELECT, INSERT` et y **révoque UPDATE et DELETE**. Elle est `SECURITY DEFINER` : la
tâche planifiée de la phase 08 tourne en `coges_app`, qui n'a aucun droit DDL. La migration
crée le mois courant et le suivant.

Une partition `DEFAULT` sert de filet. Sans elle, une partition mensuelle manquante ferait
échouer **tout INSERT** dans `audit_logs` — donc toute vente, tout paiement, toute opération à
audit critique. Une panne de batch deviendrait une panne de caisse.

**2. RLS sur chaque partition.** Une politique déclarée sur la table parente s'applique aux
requêtes passant **par le parent**, mais pas à un accès direct à `audit_logs_2026m09`. Chaque
partition porte donc sa propre politique. Le test **T37** a été étendu aux tables partitionnées
(`relkind = 'p'`) : une partition créée sans RLS fait échouer la CI.

**3. Journal append-only.** Les privilèges par défaut de la phase 01 accordaient UPDATE sur
toute table nouvelle. `UPDATE` et `DELETE` sont révoqués sur `audit_logs`, sur sa partition
`DEFAULT` et sur chaque partition créée ensuite. Un test le vérifie table par table.

**4. Liste d'événements fermée en base.** Le § 8.8 déclare `event_type text` libre, alors que
`CLAUDE.md` fige neuf types. Un `CHECK` les énumère : une faute de frappe est impossible, et
ajouter un type impose une migration, donc une décision. Un test compare le `CHECK` à
`app.core.events.types.EventType`, pour que les deux listes ne puissent pas diverger.

## Conséquences

- L'audit critique n'appelle ni Redis ni worker : il écrit dans la session de l'opération.
- L'outbox est écrite dans la transaction, `published_at` reste NULL ; `bus.py` ne décrit que
  l'interface, le transport Redis arrive en phase 08.
- **Découvert en implémentant le `downgrade`** : `FORCE ROW LEVEL SECURITY` s'applique aussi aux
  migrations. Un `DELETE FROM role_permissions` exécuté par `coges_owner` ne supprimait
  silencieusement **aucune ligne**. Le `downgrade` lève `FORCE` le temps du nettoyage et le
  rétablit aussitôt. Toute migration future touchant des données tenant-scoped devra en tenir
  compte.
