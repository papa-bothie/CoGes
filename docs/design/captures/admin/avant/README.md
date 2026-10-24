# Administration — état « avant » (prompt 27, D0)

Captures du 24/10/2026, avant la refonte : connexion, entreprises, fiche, statistiques,
système, tâches, en clair et en sombre (`ADMIN_CAPTURES=avant`, `e2e/captures.spec.ts`).

## Chronomètre de référence

Compté depuis une page quelconque de l'administration (Système, par exemple). Une
« action » est un clic ou une touche qui déclenche quelque chose ; la saisie du texte n'est
pas comptée. Ce sont les chiffres à battre.

| Tâche (D1) | Aujourd'hui | Chemin |
|---|---|---|
| 1. Retrouver une entreprise | 4 actions + saisie | « Entreprises », champ « Nom ou code », « Chercher », le résultat |
| 1. Retrouver un compte (équipe ou commerçant) | impossible | aucun écran ; base de données ou CLI |
| 2. Suspendre ou réactiver une entreprise | 6 actions + raison | 4 pour l'ouvrir, « Suspendre l'entreprise », « Suspendre » |
| 2. Suspendre un compte de l'équipe | impossible dans l'interface | `app.cli` (désactivation) sur le serveur |
| 3. Inviter un collègue | impossible dans l'interface | `make create-platform-user`, mot de passe transmis à la main |
| 4. Changer le profil d'un collègue | impossible | requête SQL sur `platform_users` |
| 5. Qui a fait quoi sur un compte ou une entreprise | impossible | requête SQL sur `platform_audit_logs` |
| 6. Ce qui demande une action | partiel | seul le bandeau « système en panne » ; essais qui finissent et entreprises suspendues : parcourir la liste page par page |
