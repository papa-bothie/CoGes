# 0009 — Création d'une entreprise par commande d'administration

- **Date** : 2026-09-23
- **Phase** : 02
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Il n'existe aucune entreprise tant que personne n'en crée une, et `companies` est en
`FORCE ROW LEVEL SECURITY` avec une politique sur `id`.

## Décision

Pas d'inscription publique en V1. Une entreprise se crée par :

```bash
python -m app.cli create-company \
    --name "Boutique Diallo" --slug boutique-diallo \
    --manager-email gerant@example.com --manager-name "Awa Diallo"
```

La commande crée, **dans une seule transaction**, l'entreprise, ses trois rôles système avec
leurs permissions (ADR 0007) et son gérant. Le mot de passe est demandé de façon interactive :
il n'apparaît ni dans la ligne de commande ni dans l'historique du shell. L'e-mail est validé
par le même schéma que l'API — un e-mail refusé au login ne doit pas pouvoir entrer par la
porte de service.

L'amorçage suit l'ADR 0004 : l'UUID de l'entreprise est **pré-généré côté serveur**, posé comme
contexte, puis inséré. La politique `companies_self` accepte l'écriture, sans contournement de
la RLS ni fonction `SECURITY DEFINER`.

## Conséquences

- Aucune surface publique à durcir en V1 : ni vérification d'e-mail, ni anti-abus, ni
  limitation de débit sur une inscription.
- La suite de tests utilise **cette commande** pour créer ses entreprises : le chemin
  d'onboarding est donc exercé à chaque exécution.
- L'inscription en libre-service, si elle arrive, réutilisera le même service sans changer le
  schéma.
