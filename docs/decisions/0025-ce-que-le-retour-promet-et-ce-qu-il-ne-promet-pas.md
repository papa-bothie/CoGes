# 0025 — Ce que le retour promet, et ce qu'il ne promet pas

- **Date** : 2026-09-24
- **Phase** : 06
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Quatre questions que le § 5.3 laisse ouvertes, et qui décident ensemble de ce qu'un client peut
obtenir quand il rapporte de la marchandise — et de qui, dans l'entreprise, peut le lui accorder.

## Décision 1 — Le numéro : `R-000123`, par le compteur déjà écrit

`document_counters` est générique depuis la phase 05 : son CHECK accepte `sale_return`, et
`DOCUMENT_PREFIXES` porte déjà `R` (ADR 0021). La phase 06 n'écrit donc **aucun** code de
numérotation, et les retours héritent de la propriété qui comptait : une suite continue par
entreprise, sans trou sauf `ROLLBACK`.

Comme pour les ventes, le numéro est attribué dans la transaction qui crée le retour. Un retour
refusé par `CG040` à sa troisième ligne ne consomme aucun numéro : l'`UPDATE … RETURNING` du
compteur est annulé avec le reste.

## Décision 2 — Le règlement vient après, et en plusieurs fois

Le retour naît **non réglé**, et se rembourse par un ou plusieurs appels à
`POST /sale-returns/{id}/refunds`. La création ne rembourse jamais, même quand le gérant sait
déjà comment il va payer : deux appels valent mieux qu'un endpoint qui fait deux choses, et
celui qui règle est de toute façon protégé par une autre permission (décision 3).

C'est ce que la table de lettrage et le statut `partial` sont faits pour représenter (§ 4.7), et
ce qu'exige **T20**. C'est aussi ce qui permet d'enregistrer la marchandise revenue tout de
suite — donc de la remettre en vente — même quand la caisse ne peut pas payer à l'instant.

## Décision 3 — Le comptoir enregistre, le gérant paie

La matrice de l'ADR 0007 est appliquée **sans modification**, et le catalogue des 60 permissions
contenait déjà tout ce qu'il fallait :

| Permission | Détenteurs | Ce qu'elle ouvre |
|---|---|---|
| `sale_returns:create` | gérant, vendeur | enregistrer un retour : stock, montants, audit |
| `sale_returns:read` | gérant, vendeur, comptable | lire les retours et leurs remboursements |
| `sale_returns:confirm` | gérant seul | **tout** règlement : trésorerie ou compensation |

Le vendeur reçoit la marchandise au comptoir — c'est là que la scène se passe — mais dès qu'une
écriture touche à la trésorerie ou à une dette, elle quitte la caisse. Exactement le partage
déjà arbitré pour l'annulation (`sales:cancel`, gérant seul).

Réutiliser `sale_returns:confirm` plutôt que d'ajouter un 61ᵉ code n'est pas qu'une économie de
migration : « confirmer un retour », c'est bien ce que fait le geste qui l'honore.

## Décision 4 — Aucun délai maximal de retour

Seule contrainte de date : `sold_at <= returned_at <= now()`, refusée par `return_before_sale`
et `return_in_future`. Rien dans le modèle n'impose de fenêtre, et en inventer une ferait refuser
des retours légitimes — marchandise rendue tard, litige, saison creuse — sans qu'aucun document
ne l'ait demandé. Un `return_window_days` dans `companies.settings` reste ajoutable plus tard,
avec le même critère de défaut que `tax_enabled` (ADR 0022).

Le mouvement de stock, lui, est daté de `now()` et non de `returned_at` : la marchandise rentre
quand on la reçoit. C'est la même règle qu'à la confirmation de vente, et elle évite la fenêtre
d'antidatage de l'ADR 0015.

## Décision 5 — On ne renonce pas à un remboursement (point soulevé en phase 06)

Le § 5.3 étape 5 dit qu'un retour peut se régler « par rien du tout (`none_due`) ». Mais le
trigger `return_refund_status_set` (§ 8.7) dérive `none_due` du **seul** montant nul :

```sql
WHEN NEW.total_refund = 0 THEN 'none_due'
```

Un gérant ne peut donc pas clore un retour de 5 000 FCFA en renonçant au remboursement. La
question n'était pas au programme de la phase ; elle a été posée en cours de route.

`none_due` reste dérivé du seul montant nul — le cas de la ligne offerte ou intégralement
remisée, couvert par un test unitaire. Un retour dû et non réglé reste `pending`, et l'index
partiel `returns_unpaid` le fait remonter tant qu'il l'est. La dette de l'entreprise envers son
client reste visible aussi longtemps qu'elle existe.

L'alternative — une colonne `waived_at` et un trigger élargi — aurait ouvert une porte pour
faire disparaître un dû sans trace monétaire. Si le besoin se confirme, elle se rouvrira sous
audit critique, avec un motif obligatoire.

## Conséquences

- Aucune migration RBAC, aucune modification de `matrix.py`. **T36** reste à quatre tables
  supprimables : un retour ne s'efface pas, il se corrige par un second retour.
- `SaleRead` gagne `returned_total` à côté de `has_returns`. Les deux sont **dérivés** :
  `sale_status` n'a pas de valeur « retournée » et n'en aura pas.
- `refund_status` n'est jamais écrit par le code — ni à la création, ni au règlement. Les trois
  colonnes concernées portent leur défaut serveur dans le modèle ORM, pour que SQLAlchemy les
  **omette** de l'INSERT plutôt que d'y envoyer NULL. C'est le seul moyen de rendre vraie la
  promesse « le code ne les écrit jamais », au lieu de l'écrire en commentaire.
